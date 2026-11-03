"""Context helpers: function-start heuristic, MSVC RTTI vtable map, caller chains.

Usage:
  python xref.py <exe> ctx <target_hex> [depth]   # call sites of target, containing fn, vtable owners, callers
"""
import struct
import sys

from pe import Image


def _syncs(img, start, site):
    """True when a linear sweep from start lands exactly on site."""
    for ins in img.md.disasm(img.read(start, site - start + 16), start):
        if ins.address == site:
            return True
        if ins.address > site:
            return False
    return False


_ENTRIES = {}


def entries(img):
    """Function entries: 16-byte aligned targets of direct calls in .text, plus RTTI vtable slots."""
    if img.path in _ENTRIES:
        return _ENTRIES[img.path]
    d = img.data
    lo, hi = img.text_va, img.text_va + img.text_size
    ents = set()
    i = d.find(b'\xe8', img.text_off, img.text_off + img.text_size - 5)
    while i != -1:
        rel = struct.unpack_from('<i', d, i + 1)[0]
        t = (img.text_va + (i - img.text_off) + 5 + rel) & 0xFFFFFFFF
        if lo <= t < hi and t & 0xF == 0:
            ents.add(t)
        i = d.find(b'\xe8', i + 1, img.text_off + img.text_size - 5)
    import bisect
    srt = sorted(ents | set(Rtti.get(img).vt_owner))
    _ENTRIES[img.path] = (srt, bisect)
    return _ENTRIES[img.path]


def func_start(img, va, limit=0x8000):
    """Nearest known entry at or before va from which a linear sweep reaches va."""
    srt, bisect = entries(img)
    k = bisect.bisect_right(srt, va) - 1
    while k >= 0 and va - srt[k] <= limit:
        if srt[k] == va or _syncs(img, srt[k], va):
            return srt[k]
        k -= 1
    return None


class Rtti:
    _cache = {}

    @classmethod
    def get(cls, img):
        if img.path not in cls._cache:
            cls._cache[img.path] = cls(img)
        return cls._cache[img.path]

    def __init__(self, img):
        self.img = img
        self.vt_owner = {}  # func va -> list of (class, slot)
        self.vtables = {}   # vtable va -> class
        base = img.base
        lo_img, hi_img = base, base + img.pe.OPTIONAL_HEADER.SizeOfImage
        d = img.data
        for s in img.pe.sections:
            if s.Name.rstrip(b'\0') not in (b'.rdata', b'.data'):
                continue
            so, sz = s.PointerToRawData, s.SizeOfRawData
            for o in range(so, so + sz - 20, 4):
                sig, off, cdoff, ptd, pchd = struct.unpack_from('<5I', d, o)
                if sig != 0 or not (lo_img <= ptd < hi_img) or not (lo_img <= pchd < hi_img):
                    continue
                try:
                    tdo = img.off(ptd)
                except Exception:
                    continue
                name = bytes(d[tdo + 8:tdo + 8 + 200]).split(b'\0')[0]
                if not name.startswith(b'.?A'):
                    continue
                col_va = img.va(o)
                cls = name.decode('latin1')[4:].rstrip('@').replace('@@', '').replace('@', '::')
                if off:
                    cls += f'+{off:#x}'
                for ref in img.dword_refs(col_va):
                    if not isinstance(ref, int):
                        continue
                    vt = ref + 4
                    self.vtables[vt] = cls
                    for slot in range(0, 400):
                        try:
                            f = img.u32(vt + slot * 4)
                        except Exception:
                            break
                        if not (img.text_va <= f < img.text_va + img.text_size):
                            break
                        if slot and (vt + slot * 4) in self.vtables:
                            break
                        self.vt_owner.setdefault(f, []).append((cls, slot))


def describe(img, rt, fva):
    own = rt.vt_owner.get(fva)
    if own:
        return ', '.join(f'{c}[{s}]' for c, s in own[:4]) + (' ...' if len(own) > 4 else '')
    return ''


def ctx(img, rt, target, depth, seen=None, indent=''):
    seen = seen if seen is not None else set()
    for site, kind in img.calls_to(target):
        f = func_start(img, site)
        tag = describe(img, rt, f) if f else ''
        print(f'{indent}{site:08x} in {f:08x} {tag}' if f else f'{indent}{site:08x} in ?')
        if depth > 1 and f and f not in seen and not tag:
            seen.add(f)
            ctx(img, rt, f, depth - 1, seen, indent + '    ')


if __name__ == '__main__':
    img = Image(sys.argv[1])
    cmd = sys.argv[2]
    rt = Rtti.get(img)
    if cmd == 'ctx':
        depth = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        ctx(img, rt, int(sys.argv[3], 16), depth)
    elif cmd == 'owner':
        for a in sys.argv[3:]:
            a = int(a, 16)
            f = func_start(img, a)
            print(f'{a:08x} fn {f:08x} {describe(img, rt, f)}')
    elif cmd == 'vtstats':
        print(len(rt.vtables), 'vtables', len(rt.vt_owner), 'virtual fns')
