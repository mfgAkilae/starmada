"""keys.py <tag> <keys>: post key presses (e.g. "ER") to the game window of test instance <tag>."""
import sys, time
sys.path.insert(0, r'E:\dev\starmada\tools')
import probe
tag, keys = sys.argv[1], sys.argv[2]
pid = int(open(rf'E:\dev\starmada\work\pid_{tag}.txt').read().strip())
h = probe.main_window(pid)['hwnd']
u = probe.user32
u.PostMessageW(h, 0x0006, 1, 0)   # WM_ACTIVATE(WA_ACTIVE): the game only reads input while active
time.sleep(0.3)
NAMED = {'ESC': 0x1B, 'F10': 0x79, 'ENTER': 0x0D}
tokens = keys.split(',') if ',' in keys or keys.upper() in NAMED else list(keys)
for ch in tokens:
    vk = NAMED.get(ch.upper(), None) or ord(ch.upper())
    sc = u.MapVirtualKeyW(vk, 0)
    u.PostMessageW(h, 0x100, vk, 1 | (sc << 16)); time.sleep(0.15)
    u.PostMessageW(h, 0x101, vk, 1 | (sc << 16) | (1 << 30) | (1 << 31)); time.sleep(0.4)
print('keys', tag, keys)
