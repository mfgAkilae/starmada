"""Transitive direct callers of the synchronized RNG functions, tagged with RTTI owners."""
import sys
from pe import Image
from xref import func_start, describe, Rtti, entries
img = Image(sys.argv[1]); rt = Rtti.get(img); srt, bis = entries(img)
targets = [int(x, 16) for x in sys.argv[3:]]
maxd = int(sys.argv[2])

def fn(va):
    f = func_start(img, va)
    return f if f is not None else srt[bis.bisect_right(srt, va) - 1]

seen = {}
frontier = [(t, 0, None) for t in targets]
while frontier:
    t, d, child = frontier.pop()
    if d >= maxd:
        continue
    for site, kind in img.calls_to(t):
        f = fn(site)
        if f in seen:
            continue
        seen[f] = (d + 1, t)
        frontier.append((f, d + 1, t))
for f, (d, via) in sorted(seen.items()):
    print(f'{f:08x} d{d} via {via:08x} {describe(img, rt, f)}')
