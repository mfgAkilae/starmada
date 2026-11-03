import struct, sys
from pe import Image
img = Image(sys.argv[1])
want = set(sys.argv[2:])
d = img.data
lo, hi = img.base, img.base + img.pe.OPTIONAL_HEADER.SizeOfImage
def tdname(ptd):
    o = img.off(ptd)
    n = bytes(d[o+8:o+208]).split(b'\0')[0].decode('latin1')
    return n[4:].rstrip('@').replace('@@','').replace('@','::')
seen = set()
for s in img.pe.sections:
    if s.Name.rstrip(b'\0') not in (b'.rdata', b'.data'): continue
    for o in range(s.PointerToRawData, s.PointerToRawData + s.SizeOfRawData - 20, 4):
        sig, off, cd, ptd, pchd = struct.unpack_from('<5I', d, o)
        if sig or off or not (lo <= ptd < hi and lo <= pchd < hi): continue
        try:
            n = bytes(d[img.off(ptd)+8:img.off(ptd)+12])
        except Exception: continue
        if not n.startswith(b'.?A'): continue
        name = tdname(ptd)
        if name not in want or name in seen: continue
        seen.add(name)
        _, attr, nb, pba = struct.unpack('<4I', img.read(pchd, 16))
        bases = [tdname(img.u32(img.u32(pba + 4*i))) for i in range(nb)]
        print(name, '->', ' : '.join(bases[1:]))
