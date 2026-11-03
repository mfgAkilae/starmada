"""cmpdumps.py <dirA> <dirB> [--state FILE]: compare the state dumps of two nodes step by step.

Ignores the per-node presentation fields (isVisible/seen). Prints the first differing lines.
With --state, steps already found equal in an earlier call are skipped.
"""
import os
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--')]
a, b = args[0], args[1]
state = sys.argv[sys.argv.index('--state') + 1] if '--state' in sys.argv else None
LOCAL = re.compile(r'isVisible \S+ seen \S+')
done = set()
if state and os.path.exists(state):
    done = set(open(state).read().split())
steps = sorted(s for s in set(os.listdir(a)) & set(os.listdir(b)) if s.startswith('step_'))
first = None
newly = []
for s in steps:
    if s in done:
        continue
    la = [LOCAL.sub('', l) for l in open(os.path.join(a, s), errors='replace')]
    lb = [LOCAL.sub('', l) for l in open(os.path.join(b, s), errors='replace')]
    if la == lb:
        newly.append(s)
        continue
    diff = [(i, x, y) for i, (x, y) in enumerate(zip(la, lb)) if x != y]
    print(f'{s}: {len(la)} vs {len(lb)} lines, {len(diff)} differ')
    if first is None:
        first = s
        for i, x, y in diff[:12]:
            ctx = next((la[j] for j in range(i, -1, -1) if la[j].startswith(('GAMEOBJECT', 'WEAPON', 'ORDNANCE'))), '')
            print(f'   line {i} [{ctx.strip()[:60]}]\n     A: {x.rstrip()[:110]}\n     B: {y.rstrip()[:110]}')
        break
if state:
    with open(state, 'a') as fh:
        for s in newly:
            fh.write(s + '\n')
print('compared', len(steps), 'steps; first difference:', first)
