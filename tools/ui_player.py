"""Logged, UI-only control of one declared multiplayer client.

from ui_player import UIPlayer
p = UIPlayer('agents6_1', 'A')
p.enable()
p.frame('opening')

Only virtual mouse/keyboard input is supported. No OS focus or desktop input.
Direct multiplayer-command IPC is intentionally unavailable here.
"""
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes as wt
import json
from pathlib import Path
import re
import time

from late_game_player import Memory
from play_input import BASE, Input
import probe

# Input.map uses the game's fixed US DirectInput key positions. The test proxy
# derives WM_KEY scan codes from the game Window Thread's current OS layout.
LETTER_SCANS = dict(zip('QWERTYUIOPASDFGHJKLZXCVBNM',
    [*range(0x10, 0x1a), *range(0x1e, 0x27), *range(0x2c, 0x33)]))


class UIPlayer(Input):
    def __init__(self, run, tag):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', run):
            raise ValueError('invalid run name')
        self.root = BASE / 'work' / 'det' / run
        metadata = json.loads((self.root / 'launch.json').read_text(encoding='utf-8-sig'))
        if len(tag) != 1 or tag not in metadata.get('peers', []):
            raise ValueError('client must be declared in this run')
        fixture = metadata['fixture']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', fixture):
            raise ValueError('invalid fixture name')
        super().__init__(run, tag)
        memory = Memory(self.pid, BASE / 'work' / 'play_clients' / fixture / tag / 'Armada.exe')
        memory.close()  # PID/path identity only; gameplay planning uses the UI.
        self.tag = tag
        self.frames = self.root / f'{tag}_ui'
        self.frames.mkdir(exist_ok=True)
        self.ledger = self.root / f'{tag}_ui_events.jsonl'

    def note(self, **values):
        entry = dict(wall_time=datetime.now(timezone.utc).isoformat(), tag=self.tag, **values)
        with self.ledger.open('a', encoding='utf-8') as output:
            output.write(json.dumps(entry, sort_keys=True) + '\n')

    def event(self, message, value):
        try:
            super().event(message, value)
        except Exception as error:
            self.note(event=hex(message), value=value, result='failed', error=str(error))
            raise
        self.note(event=hex(message), value=value, result='UI device Poll acknowledged')

    def command(self, *args, **kwargs):
        raise RuntimeError('UI validation forbids direct build/construction/attack Command-IPC')

    def _game_key(self, vk):
        scan = LETTER_SCANS.get(chr(vk))
        if scan is None:
            return vk
        user = probe.user32
        user.GetKeyboardLayout.argtypes = [wt.DWORD]
        user.GetKeyboardLayout.restype = wt.HANDLE
        user.MapVirtualKeyExW.argtypes = [wt.UINT, wt.UINT, wt.HANDLE]
        user.MapVirtualKeyExW.restype = wt.UINT
        thread = user.GetWindowThreadProcessId(self.hwnd, None)
        if not thread:
            raise RuntimeError('Game Window Thread is unavailable')
        layout = user.GetKeyboardLayout(thread)
        translated = user.MapVirtualKeyExW(scan, 3, layout)
        if not translated or user.MapVirtualKeyExW(translated, 0, layout) != scan:
            raise RuntimeError(f'Game key {chr(vk)} cannot be mapped to scan {scan:#x}')
        if translated != vk:
            self.note(key=chr(vk), translated_vk=translated, scan=scan,
                      reason='preserve Input.map key across OS layouts')
        return translated

    def key(self, vk):
        """Input.map letter or Windows VK for non-letter keys; no OS input."""
        super().key(self._game_key(vk))

    def chord(self, keys):
        super().chord([self._game_key(vk) for vk in keys])

    def frame(self, label='state'):
        label = re.sub(r'[^A-Za-z0-9_-]+', '_', label).strip('_')[:60] or 'state'
        target = self.frames / f'{time.time_ns()}_{label}.png'
        super().shot(str(target), flip_y=True)
        self.note(frame=str(target.relative_to(self.root)))
        return target
