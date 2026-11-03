"""List call sites of targets with containing function, RTTI owner and caller chain."""
import sys
from pe import Image
from xref import func_start, describe, Rtti, entries

img = Image(sys.argv[1])
rt = Rtti.get(img)
srt, bis = entries(img)
depth = int(sys.argv[2])


def fn_of(va):
    f = func_start(img, va)
    if f is None:
        k = bis.bisect_right(srt, va) - 1
        f = srt[k]
    return f


def walk(t, d, ind, seen):
    for site, kind in img.calls_to(t):
        f = fn_of(site)
        tag = describe(img, rt, f)
        print(f'{ind}{site:08x} in {f:08x} {tag}')
        if d > 1 and not tag and f not in seen:
            seen.add(f)
            walk(f, d - 1, ind + '    ', seen)


for t in sys.argv[3:]:
    print('===', t)
    walk(int(t, 16), depth, '', set())
