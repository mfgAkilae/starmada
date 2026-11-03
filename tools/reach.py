"""Direct-call reachability from root functions (recursive descent with capstone)."""
import sys, struct
import capstone
from pe import Image
from xref import describe, Rtti

img = Image(sys.argv[1]); rt = Rtti.get(img)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
lo, hi = img.text_va, img.text_va + img.text_size
_cache = {}


def callees(fva):
    if fva in _cache:
        return _cache[fva]
    out, seen, todo = set(), set(), [fva]
    while todo:
        a = todo.pop()
        if a in seen or not (lo <= a < hi):
            continue
        seen.add(a)
        if len(seen) > 4000:
            break
        try:
            code = img.read(a, 0x400)
        except Exception:
            continue
        for ins in md.disasm(code, a):
            seen.add(ins.address)
            m = ins.mnemonic
            if m == 'call' and ins.op_str.startswith('0x'):
                out.add(int(ins.op_str, 16))
            elif m == 'jmp':
                if ins.op_str.startswith('0x'):
                    t = int(ins.op_str, 16)
                    if t < fva or t > fva + 0x4000:   # tail call
                        out.add(t)
                    else:
                        todo.append(t)
                break
            elif m.startswith('j') and ins.op_str.startswith('0x'):
                todo.append(int(ins.op_str, 16))
            elif m in ('ret', 'retf', 'int3'):
                break
    _cache[fva] = out
    return out


def reach(roots, stop=()):
    seen = set(roots)
    todo = list(roots)
    parent = {}
    while todo:
        f = todo.pop()
        for c in callees(f):
            if c not in seen and c not in stop and lo <= c < hi:
                seen.add(c)
                parent[c] = f
                todo.append(c)
    return seen, parent


if __name__ == '__main__':
    roots = [int(x, 16) for x in sys.argv[2].split(',')]
    stops = [int(x, 16) for x in sys.argv[3].split(',')] if len(sys.argv) > 3 and sys.argv[3] else []
    s, parent = reach(roots, set(stops))
    print(len(s), 'functions reachable')
    for f in sorted(s):
        d = describe(img, rt, f)
        if d:
            chain = []
            x = f
            while x in parent and len(chain) < 6:
                x = parent[x]
                chain.append(f'{x:x}')
            print(f'{f:08x} {d}  <- {" <- ".join(chain)}')
