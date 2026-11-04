"""clk.py <tag> <x> <y> [shot.png]: click into the shell dialog of test instance <tag> (pid_<tag>.txt)."""
import os, sys, time
sys.path.insert(0, r'E:\dev\starmada\tools')
import probe
tag, x, y = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
pid = int(open(os.path.join(os.environ.get('ARMADA_RUN_DIR', r'E:\dev\starmada\work'), f'pid_{tag}.txt')).read().strip())
ds = probe.dialogs(pid)
h = ds[0]['hwnd'] if ds else probe.main_window(pid)['hwnd']
u = probe.user32
for dx in (-6, -3, 0):
    u.PostMessageW(h, 0x200, 0, (y << 16) | ((x + dx) & 0xFFFF)); time.sleep(0.12)
u.PostMessageW(h, 0x201, 1, (y << 16) | x); time.sleep(0.25)
u.PostMessageW(h, 0x202, 0, (y << 16) | x)
print('click', tag, hex(h), x, y)
if len(sys.argv) > 4:
    time.sleep(float(sys.argv[5]) if len(sys.argv) > 5 else 3)
    probe.shot(pid, sys.argv[4])
