"""Save or restore owned test-client positions without activation or resizing.

python tools/game_window_positions.py save <run> [A ... H]
python tools/game_window_positions.py restore <run> [A ... H]
The local profile survives runs under work/game_window_positions.json.
"""
import argparse
import ctypes
from ctypes import wintypes as wt
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

import probe

BASE = Path(__file__).resolve().parents[1]
PROFILE = BASE / 'work' / 'game_window_positions.json'


def owned_window(run, tag, executable=None):
    root = BASE / 'work' / 'det' / run
    if executable is None:
        metadata = json.loads((root / 'launch.json').read_text(encoding='utf-8-sig'))
        peers = metadata.get('peers', list('AB'))
        executable = metadata['programs'][peers.index(tag)]
    pid = int((root / f'pid_{tag}.txt').read_text().strip())
    # Check the actual executable, not just a PID that Windows could have reused.
    probe.k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    probe.k32.OpenProcess.restype = wt.HANDLE
    probe.k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    probe.k32.CloseHandle.argtypes = [wt.HANDLE]
    handle = probe.k32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError(f'Client {tag} is not running')
    try:
        path = ctypes.create_unicode_buffer(32768)
        size = wt.DWORD(len(path))
        if not probe.k32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        actual = Path(path.value).resolve()
        if actual != Path(executable).resolve():
            raise RuntimeError(f'Client {tag} PID/path identity mismatch')
    finally:
        probe.k32.CloseHandle(handle)
    return next((w for w in probe.windows(pid) if w['visible'] and w['cls'] == 'Armada'), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('save', 'restore'))
    parser.add_argument('run')
    parser.add_argument('tags', nargs='*', choices=list('ABCDEFGH'))
    parser.add_argument('--timeout', type=float, default=0)
    parser.add_argument('--executable', help='Exact owned executable for a standalone test launch')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.run):
        parser.error('Invalid run name')
    # Explicit thread context keeps coordinates physical on mixed-DPI monitors.
    probe.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    probe.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    probe.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    probe.user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, wt.UINT]
    root = BASE / 'work' / 'det' / args.run
    if args.executable and len(args.tags) != 1:
        parser.error('--executable requires exactly one client tag')
    tags = args.tags
    if not tags:
        metadata = json.loads((root / 'launch.json').read_text(encoding='utf-8-sig'))
        tags = metadata.get('peers', list('AB'))
    profile = json.loads(PROFILE.read_text(encoding='utf-8-sig')) if PROFILE.exists() else {
        'schema': 1, 'coordinates': 'physical-screen-pixels', 'clients': {}}
    if profile.get('schema') != 1 or profile.get('coordinates') != 'physical-screen-pixels':
        raise ValueError('Unsupported window position profile')
    for tag in tags:
        if args.action == 'restore' and tag not in profile['clients']:
            print(f'{tag}: no saved position; unchanged')
            continue
        deadline = time.monotonic() + max(0, args.timeout)
        while True:
            window = owned_window(args.run, tag, args.executable)
            if window or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        if not window:
            raise RuntimeError(f'Client {tag} has no visible Armada window')
        left, top, right, bottom = window['rect']
        if args.action == 'save':
            profile['clients'][tag] = dict(x=left, y=top, width=right-left, height=bottom-top)
        else:
            position = profile['clients'][tag]
            # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE: no focus, size or z-order changes.
            if not probe.user32.SetWindowPos(window['hwnd'], None,
                    int(position['x']), int(position['y']), 0, 0, 0x0015):
                raise ctypes.WinError(ctypes.get_last_error())
        print(f'{tag}: {args.action} {profile["clients"][tag]["x"]},{profile["clients"][tag]["y"]}')
    if args.action == 'save':
        profile.update(saved_utc=datetime.now(timezone.utc).isoformat(), source_run=args.run)
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = PROFILE.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
        temporary.replace(PROFILE)


if __name__ == '__main__':
    main()
