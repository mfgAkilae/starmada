"""Set/verify the owned Create Game dialog's name without desktop focus."""
import argparse
import ctypes
from ctypes import wintypes as wt
from pathlib import Path
import re

from late_game_player import BASE, Memory
from setup_late_game_lobby import Lobby
import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('name')
    parser.add_argument('--fixture', default='live')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if (not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (args.run, args.fixture)) or
            not re.fullmatch(r'[ -~]{1,80}', args.name)):
        parser.error('safe run/fixture names and a printable ASCII game name required')
    lobby = Lobby(args.run, 'A', args.fixture)
    memory = Memory(lobby.pid, BASE / 'work' / 'play_clients' / args.fixture / 'A' / 'Armada.exe')
    try:
        if args.verify:
            actual = memory.read(0x68a308, 100).split(b'\0', 1)[0].decode('ascii')
            if actual != args.name:
                raise RuntimeError(f'Create Game model name differs: {actual!r}')
            print('verified host name:', actual)
            return
        edit = next((h for h, cls, _, _, _, cid in probe.children(lobby.dialog())
                     if cls == 'Edit' and cid == 2100), None)
        if not edit:
            raise RuntimeError('Create Game name control unavailable')
        send = probe.user32.SendMessageTimeoutW
        send.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                         ctypes.POINTER(ctypes.c_size_t)]
        send.restype = wt.LPARAM
        result = ctypes.c_size_t()
        source = ctypes.create_unicode_buffer(args.name)
        # Cross-process Edit text needs direct system messages; the WindowText
        # APIs can access only a caption cache in this case (Microsoft Win32 docs).
        if not send(edit, 0x000c, 0, ctypes.addressof(source), 2, 2000, ctypes.byref(result)):
            raise ctypes.WinError()
        text = ctypes.create_unicode_buffer(100)
        if not send(edit, 0x000d, 100, ctypes.addressof(text), 2, 2000, ctypes.byref(result)):
            raise ctypes.WinError()
        if text.value != args.name:
            raise RuntimeError('Create Game edit did not accept the text')
        if not send(lobby.dialog(), 0x111, 1, 0, 2, 2000, ctypes.byref(result)):
            raise ctypes.WinError()
        print('accepted Create Game text:', args.name)
    finally:
        memory.close()


if __name__ == '__main__':
    main()
