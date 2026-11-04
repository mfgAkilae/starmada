"""Configure the stock 8-player Late-Game test through background lobby input.

Uses only this run's owned dialogs; never activates a window or sends desktop input.
The match must not have started. Stock map picker ordering was checked on GOG 1.2.
"""
import ctypes
from ctypes import wintypes as wt
import json
import argparse
from pathlib import Path
import re
import sys
import time

import probe

BASE = Path(__file__).resolve().parents[1]
probe.user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
probe.user32.SendMessageW.restype = wt.LPARAM


class Lobby:
    def __init__(self, run, tag, fixture='live'):
        self.tag = tag
        self.fixture = fixture
        self.root = BASE / 'work' / 'det' / run
        self.pid = int((self.root / f'pid_{tag}.txt').read_text())

    def dialog(self):
        dialogs = probe.dialogs(self.pid)
        if not dialogs:
            raise RuntimeError('lobby dialog is unavailable')
        return dialogs[0]['hwnd']

    def mouse(self, message, x, y, buttons=0):
        if not probe.user32.PostMessageW(self.dialog(), message, buttons, (y << 16) | x):
            raise ctypes.WinError()

    def click(self, x, y):
        self.mouse(0x200, x, y)
        time.sleep(.15)
        self.mouse(0x201, x, y, 1)
        time.sleep(.25)
        self.mouse(0x202, x, y)
        time.sleep(.5)

    def dropdown(self, x, y, index, up=False):
        # The game's custom combo handler runs on actual mouse release, not CBN_SELCHANGE.
        self.mouse(0x200, x, y)
        self.mouse(0x201, x, y, 1)
        time.sleep(.5)
        target = y + (-1 if up else 1) * 19 * (index + 1)
        for i in range(1, 9):
            self.mouse(0x200, x, y + (target - y) * i // 8, 1)
            time.sleep(.08)
        self.mouse(0x202, x, target)
        time.sleep(.4)

    def selected(self, control_id):
        control = next((h for h, cls, _, _, _, cid in probe.children(self.dialog())
                        if cls == 'ComboBox' and cid == control_id), None)
        if control is None:
            raise RuntimeError(f'missing lobby control {control_id}')
        return probe.user32.SendMessageW(control, 0x147, 0, 0)

    def infinite_moons(self):
        from late_game_player import Memory
        memory = Memory(self.pid, BASE / 'work' / 'play_clients' / self.fixture / self.tag / 'Armada.exe')
        try:
            lobby = memory.u(memory.u(0x678810) + 0x20)
            return memory.read(memory.u(lobby + 0xc) + 0x56, 1)[0]
        finally:
            memory.close()


def configure(run, fixture='live'):
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (run, fixture)):
        raise ValueError('invalid run or fixture name')
    a, b = Lobby(run, 'A', fixture), Lobby(run, 'B', fixture)
    label = (BASE / 'work' / 'play_clients' / fixture / 'A' / 'label.map').read_text(encoding='latin1')
    value = re.search(r'^\s*\+\s+sd_value_5\s+\{(\d+)\}', label, re.M)
    if not value:
        raise RuntimeError('starting Dilithium rule is unavailable')
    a.click(449, 281)                 # Select Map
    a.dropdown(306, 12, 1)            # 8 Players
    a.click(160, 69)                  # 8open.bzn: The Great Wide Open
    a.click(73, 271)                  # Select Map
    a.dropdown(580, 94, 0)            # Max Players: 8
    for y in (166, 190, 214):         # Dilithium, Crew, Officers
        a.dropdown(580, y, 3)
        a.dropdown(580, y, 4)
    a.dropdown(580, 237, 2)           # Standard Units
    a.dropdown(580, 262, 0)           # Standard Tech
    if not a.infinite_moons():
        a.click(579, 334)
    a.dropdown(205, 64, 0)            # A Federation
    b.dropdown(205, 83, 0)            # B Federation
    a.dropdown(291, 64, 0)
    b.dropdown(291, 83, 1)
    for i, race in enumerate((0, 3, 2, 1, 0, 3)):
        y = 101 + 19 * i
        a.dropdown(79, y, 3, up=y >= 149)  # Hard AI
        a.dropdown(205, y, race, up=y >= 149)
        a.dropdown(291, y, i + 2, up=y >= 149)  # Distinct sides
    expected = {2136: 0, 2140: 2, 2119: 0, 2142: 4, 2143: 4, 2144: 4}
    expected.update({2113 + i: 3 for i in range(6)})
    expected.update({2121 + i: i for i in range(8)})
    expected.update({2097: 0, 2098: 0})
    actual = {cid: a.selected(cid) for cid in expected}
    if actual != expected:
        raise RuntimeError(f'lobby rules not applied: {actual}')
    deadline = time.monotonic() + 10
    while (a.infinite_moons(), b.infinite_moons()) != (1, 1):
        if time.monotonic() >= deadline:
            raise RuntimeError('Infinite Moons was not replicated to both clients')
        time.sleep(.25)
    # Capture both owned lobby dialogs for independent inspection of the map/slots/rules.
    for tag, lobby in (('A', a), ('B', b)):
        dialog = probe.dialogs(lobby.pid)[0]
        original = probe.main_window
        try:
            probe.main_window = lambda _, dialog=dialog: dialog
            probe.shot(lobby.pid, str(lobby.root / f'{tag}_late_lobby.png'))
        finally:
            probe.main_window = original
    result = dict(map='8open.bzn', fixture=fixture, human_clients=2, hard_ai=6, dilithium=int(value[1]),
                  crew=99999, officers=999, stock_units=True, stock_tech=True,
                  infinite_moons=True, separate_alliances=True, selected_indices=actual)
    (a.root / 'scenario.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--fixture', default='live')
    args = parser.parse_args()
    configure(args.run, args.fixture)
