"""Per-client virtual input for the test proxy's real gameplay UI.

python tools/play_input.py <run> <A|B> enable|move|click|right|drag|key [arguments]
python tools/play_input.py <run> <A|B> build <actorID> <ODF-basename>
python tools/play_input.py <run> <A|B> construct <actorID> <ODF-basename> <x> <y> <z>
python tools/play_input.py <run> <A|B> attack <actorID> <targetID>
Coordinates are game pixels (640x480). No desktop input/focus is used. Every
virtual mouse/key event waits for an acknowledgement from the game device Poll.
Build/attack commands use the owning client's original multiplayer output queue;
an acknowledgement proves submission, not successful construction or combat.
The test instances must start with ARMADA_TEST_INPUT=1.
"""
from pathlib import Path
import ctypes
from ctypes import wintypes as wt
import struct
import sys
import time

import probe

BASE = Path(__file__).resolve().parents[1]
ENABLE, MOVE, BUTTON, KEY = 0x8410, 0x8411, 0x8412, 0x8413
CAPTURE = 0x8414
_network_sequence = (time.time_ns() // 1000000) & 0x7fffffff


class Input:
    def __init__(self, run, tag):
        self.pid = int((BASE / 'work' / 'det' / run / f'pid_{tag}.txt').read_text().strip())
        self.hwnd = probe.main_window(self.pid)['hwnd']
        self.diag = BASE / 'work' / 'det' / run / tag / 'diag.txt'

    def event(self, msg, value):
        seq = int(time.time() * 1000) & 0x7fffffff
        if not probe.user32.PostMessageW(self.hwnd, msg, seq, value):
            raise RuntimeError('PostMessage failed')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            text = self.diag.read_text(encoding='latin1') if self.diag.exists() else ''
            if f'input ack {seq} ' in text:
                time.sleep(0.12)
                return
            time.sleep(0.03)
        raise RuntimeError(f'input {seq} was not consumed by the game device Poll')

    def enable(self):
        probe.user32.PostMessageW(self.hwnd, ENABLE, 1, 0)
        time.sleep(0.3)
        self.move(320, 240)

    def move(self, x, y):
        if not (0 <= x < 640 and 0 <= y < 480):
            raise ValueError('coordinates must fit the 640x480 game view')
        self.event(MOVE, (y << 16) | x)

    def click(self, x, y, right=False):
        self.move(x, y)
        self.event(BUTTON, 3 if right else 1)
        self.event(BUTTON, 4 if right else 2)

    def drag(self, x1, y1, x2, y2):
        self.move(x1, y1)
        self.event(BUTTON, 1)
        for i in range(1, 9):
            self.move(x1 + (x2 - x1) * i // 8, y1 + (y2 - y1) * i // 8)
        self.event(BUTTON, 2)

    def key(self, vk):
        self.event(KEY, vk)
        self.event(KEY, vk | 0x10000)

    def chord(self, keys):
        for key in keys:
            self.event(KEY, key)
        for key in reversed(keys):
            self.event(KEY, key | 0x10000)

    def command(self, action, actor, target=0, name='', position=(0, 0, 0)):
        """One command through this player's normal multiplayer output queue."""
        global _network_sequence
        if len(name.encode('ascii')) > 8:
            raise ValueError('ODF basename must fit the native eight-byte command field')
        class CopyData(ctypes.Structure):
            _fields_ = [('dwData', ctypes.c_size_t), ('cbData', wt.DWORD), ('lpData', ctypes.c_void_p)]
        # Distinct orders can arrive within the same Windows clock tick. Only
        # retries of this order may share a sequence (the proxy deduplicates it).
        _network_sequence = ((_network_sequence + 1) & 0x7fffffff) or 1
        seq = _network_sequence
        raw = ctypes.create_string_buffer(struct.pack('<IIII8sfff', seq, action,
            actor & 0xffffffff, target & 0xffffffff, name.encode('ascii'), *position))
        copy = CopyData(0x41524d44, 36, ctypes.cast(raw, ctypes.c_void_p))
        send = probe.user32.SendMessageTimeoutW
        send.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                         ctypes.POINTER(ctypes.c_size_t)]
        send.restype = wt.LPARAM
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = ctypes.c_size_t()
            ok = send(self.hwnd, 0x4a, 0, ctypes.addressof(copy), 2, 500, ctypes.byref(result))
            if ok and result.value == 1:
                print('submitted network command', seq, action, actor, target, name, position)
                return
            if ok and result.value == 2:
                raise RuntimeError('command rejected: actor ownership, class or target invalid')
            time.sleep(0.03)
        raise RuntimeError('game did not collect this network command')

    def shot(self, path, flip_y=False):
        from PIL import Image
        seq = int(time.time() * 1000) & 0x7fffffff
        source = self.diag.parent / f'frame_{seq}.bmp'
        probe.user32.PostMessageW(self.hwnd, CAPTURE, seq, 0)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if source.exists() and f'capture {seq}:' in self.diag.read_text(encoding='latin1'):
                try:
                    frame = Image.open(source).convert('RGB')
                    if flip_y:
                        frame = frame.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                    frame.save(path)
                    print('captured native game snapshot', path)
                    return
                except OSError:
                    pass  # wait for the game's BMP writer to close the file
            time.sleep(0.05)
        raise RuntimeError('native game snapshot was not written')


if __name__ == '__main__':
    run, tag, action, *args = sys.argv[1:]
    device = Input(run, tag)
    if action == 'enable':
        device.enable()
    elif action == 'shot':
        device.shot(args[0])
    elif action == 'close':
        probe.user32.PostMessageW(device.hwnd, 0x10, 0, 0)
    elif action == 'build':
        device.command(1, int(args[0]), name=args[1])
    elif action == 'construct':
        device.command(3, int(args[0]), name=args[1], position=tuple(map(float, args[2:5])))
    elif action == 'attack':
        device.command(2, int(args[0]), target=int(args[1]))
    elif action in ('click', 'right'):
        device.click(*map(int, args), right=action == 'right')
    elif action == 'move':
        device.move(*map(int, args))
    elif action == 'drag':
        device.drag(*map(int, args))
    elif action == 'key':
        named = {'ESC': 27, 'SPACE': 32, 'ENTER': 13, 'HOME': 36, 'TAB': 9,
                 'CTRL': 17, 'ALT': 18, 'SHIFT': 16}
        keys = [named[key] if key in named else ord(key) for key in args[0].upper().split('+')]
        device.chord(keys)
    else:
        raise SystemExit(__doc__)
    print(f'{tag}: {action} {" ".join(args)} completed')
