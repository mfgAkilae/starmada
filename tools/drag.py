"""drag.py <tag> x1 y1 x2 y2 [shot_while_down.png]: press at (x1,y1), move to (x2,y2), release."""
import os, sys, time
sys.path.insert(0, r'E:\dev\starmada\tools')
import probe
tag = sys.argv[1]
x1, y1, x2, y2 = map(int, sys.argv[2:6])
pid = int(open(os.path.join(os.environ.get('ARMADA_RUN_DIR', r'E:\dev\starmada\work'), f'pid_{tag}.txt')).read().strip())
h = probe.dialogs(pid)[0]['hwnd']
u = probe.user32
lp = lambda x, y: (y << 16) | (x & 0xFFFF)
u.PostMessageW(h, 0x200, 0, lp(x1, y1)); time.sleep(0.15)
u.PostMessageW(h, 0x201, 1, lp(x1, y1)); time.sleep(0.6)
if len(sys.argv) > 6:
    probe.shot(pid, sys.argv[6])
steps = 8
for i in range(1, steps + 1):
    u.PostMessageW(h, 0x200, 1, lp(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)); time.sleep(0.08)
time.sleep(0.4)
u.PostMessageW(h, 0x202, 0, lp(x2, y2))
print('drag', tag, (x1, y1), '->', (x2, y2))
