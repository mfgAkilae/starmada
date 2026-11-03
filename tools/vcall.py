"""Find 'call dword ptr [reg+disp]' sites for a vtable displacement, with containing fn and owner."""
import sys
from pe import Image
from xref import func_start, describe, Rtti, entries
img = Image(sys.argv[1]); rt = Rtti.get(img); srt, bis = entries(img)
disp = int(sys.argv[2], 16)
d = img.data
res = []
start, end = img.text_off, img.text_off + img.text_size
for i in range(start, end - 6):
    if d[i] != 0xFF:
        continue
    m = d[i + 1]
    mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
    if reg != 2 or rm == 4:
        continue
    if mod == 1 and d[i + 2] == disp and disp < 0x80:
        ln = 3
    elif mod == 2 and int.from_bytes(d[i + 2:i + 6], 'little') == disp:
        ln = 6
    else:
        continue
    va = img.va(i)
    ins = img.dis(va, 8, 1)
    if not ins or ins[0].size != ln or ins[0].mnemonic != 'call':
        continue
    f = func_start(img, va) or srt[bis.bisect_right(srt, va) - 1]
    res.append((va, f, describe(img, rt, f)))
for va, f, dsc in res:
    print(f'{va:08x} in {f:08x} {dsc}')
print(len(res), 'sites')
