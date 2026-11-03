import sys, time, ctypes
sys.path.insert(0, r'E:\dev\starmada\tools')
import probe
pid = int(open(r'E:\dev\starmada\work\pid.txt').read().strip())
x, y = int(sys.argv[1]), int(sys.argv[2])
h = probe.dialogs(pid)[0]['hwnd'] if len(sys.argv) < 4 or sys.argv[3] == 'dialog' else probe.main_window(pid)['hwnd']
u = probe.user32
for dx in (-6, -3, 0):
    u.PostMessageW(h, 0x200, 0, ((y) << 16) | ((x + dx) & 0xFFFF)); time.sleep(0.12)
u.PostMessageW(h, 0x201, 1, (y << 16) | x); time.sleep(0.25)
u.PostMessageW(h, 0x202, 0, (y << 16) | x); time.sleep(0.1)
print('clickseq', hex(h), x, y)
