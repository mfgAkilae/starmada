import sys
from pe import Image, fmt
from xref import func_start
img = Image(sys.argv[1])
before, after = int(sys.argv[2]), int(sys.argv[3])
for a in sys.argv[4:]:
    a = int(a, 16)
    f = func_start(img, a) or (a - 0x40)
    ins = list(img.md.disasm(img.read(f, a - f + 0x80), f))
    idx = next(i for i, x in enumerate(ins) if x.address <= a < x.address + x.size)
    print(f'--- {a:08x} (fn {f:08x})')
    print(fmt(ins[max(0, idx - before): idx + after]))
