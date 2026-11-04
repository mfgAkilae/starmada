"""Check a running native-window test client and replay its actual installed shim.

python tools/test_window_render.py <run> <A|B> [--live-only]
Requires the test proxy and probe dependencies; instruction replays also need unicorn.
No desktop input.
"""
import ctypes
import argparse
from ctypes import wintypes as wt
from pathlib import Path
import struct
import sys
import unittest

import probe

BASE = Path(__file__).resolve().parents[1]
SITE, NORMAL, ERROR = 0x5816f4, 0x581700, 0x581697
STATE = None


def snapshot(run, tag):
    pid = int((BASE / 'work' / 'det' / run / f'pid_{tag}.txt').read_text())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenProcess(0x1010, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        def read(address, count=4):
            data, received = ctypes.create_string_buffer(count), ctypes.c_size_t()
            if not kernel.ReadProcessMemory(handle, address, data, count, ctypes.byref(received)):
                raise ctypes.WinError(ctypes.get_last_error())
            if received.value != count:
                raise RuntimeError('incomplete process read')
            return bytes(data)

        def integer(address):
            return struct.unpack('<I', read(address))[0]

        wrapper = next((b for b, _, n in probe.modules(pid) if n.lower() == 'ddraw.dll'), None)
        if wrapper is None:
            raise RuntimeError('test client exited or GOG wrapper is not loaded; run this check during a match')
        engine = integer(0x6d4aa0)
        device = integer(engine + 0xe4)
        hwnd = integer(engine + 0xe0)
        rect = wt.RECT()
        if not probe.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError('game client rectangle unavailable')
        return dict(code=read(SITE, 12), d3d=integer(wrapper + 0x460724),
                    windowed=integer(wrapper + 0x468478), frames=integer(0x6d6830),
                    mode=integer(engine + 0x124), fullscreen=read(device + 0x40, 1)[0],
                    view=tuple(round(v) for v in struct.unpack('<ff', read(device + 0xcc, 8))),
                    client=(rect.right - rect.left, rect.bottom - rect.top))
    finally:
        kernel.CloseHandle(handle)


class WindowRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if STATE is None:
            raise unittest.SkipTest('requires a running test client; use the documented CLI')

    def test_actual_device_and_canvas(self):
        self.assertEqual(STATE['mode'], 2, 'client must be in a match')
        self.assertGreater(STATE['frames'], 0)
        self.assertNotEqual(STATE['d3d'], 0, 'render loop runs without a GOG D3D9 device')
        self.assertEqual(STATE['windowed'], 1)
        self.assertEqual(STATE['fullscreen'], 0)
        self.assertEqual(STATE['view'], STATE['client'], 'black margins: canvas and game view differ')

    def replay(self, status, destination):
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP
        code = STATE['code']
        self.assertEqual(code[:3], b'\x8b\xcb\xe8', 'native mode shim is not installed')
        callback = (SITE + 7 + struct.unpack('<i', code[3:7])[0]) & 0xffffffff
        cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        cpu.mem_map(SITE & ~0xfff, 0x1000)
        cpu.mem_write(SITE, code)
        cpu.mem_map(callback & ~0xfff, 0x1000)
        cpu.mem_write(callback, b'\xc3')
        cpu.mem_map(0x2000000, 0x2000)
        stack, actor = 0x2001000, 0x12345678
        cpu.reg_write(UC_X86_REG_ESP, stack)
        cpu.reg_write(UC_X86_REG_EBX, actor)
        calls, stopped = [], []

        def step(machine, address, size, data):
            if address == callback:
                calls.append(machine.reg_read(UC_X86_REG_ECX))
                machine.reg_write(UC_X86_REG_EAX, status)
            elif address in (NORMAL, ERROR):
                stopped.append(address)
                machine.emu_stop()

        cpu.hook_add(UC_HOOK_CODE, step)
        cpu.emu_start(SITE, SITE + 0x100, count=32)
        self.assertEqual(calls, [actor])
        self.assertEqual(stopped, [destination])
        self.assertEqual(cpu.reg_read(UC_X86_REG_ESP), stack)
        self.assertEqual(cpu.reg_read(UC_X86_REG_EBX), actor)

    def test_success_continues_with_balanced_stack(self):
        self.replay(0, NORMAL)

    def test_failure_reaches_original_error_handler(self):
        self.replay(0x80004005, ERROR)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('tag', choices=('A', 'B'))
    parser.add_argument('--live-only', action='store_true')
    args = parser.parse_args()
    STATE = snapshot(args.run, args.tag)
    print('game view', STATE['view'], 'client', STATE['client'], 'windowed', STATE['windowed'])
    sys.argv[1:] = ['WindowRenderer.test_actual_device_and_canvas'] if args.live_only else []
    unittest.main(verbosity=2)
