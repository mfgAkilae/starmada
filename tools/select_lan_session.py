"""Select the exact owned test host, checking its native session GUID before Join.

This bounded test helper supports the first visible row. It refuses any other
layout rather than guessing when several waiting hosts are present.
"""
import argparse
import json
import re
import time

from late_game_player import BASE, Memory
from setup_late_game_lobby import Lobby


def select(run, name, fixture):
    if not all(re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in (run, fixture)):
        raise ValueError('invalid run or fixture')
    lobby = Lobby(run, 'B', fixture)
    memory = Memory(lobby.pid, BASE / 'work' / 'play_clients' / fixture / 'B' / 'Armada.exe')
    try:
        deadline = time.monotonic() + 15
        while True:
            head, count = memory.u(0x68a4a4), memory.u(0x68a4a8)
            if count > 128:
                raise RuntimeError('unsupported LAN session count')
            node, entries = memory.u(head), []
            for _ in range(count):
                if node == head or not node:
                    raise RuntimeError('session list changed during read')
                record = memory.u(node + 8)
                title = memory.read(memory.u(record + 4), 100).split(b'\0', 1)[0].decode('latin1')
                entries.append(dict(name=title, started=bool(memory.read(record + 0x16, 1)[0]),
                                    guid=memory.read(memory.u(record) + 4, 16).hex()))
                node = memory.u(node)
            matches = [(i, entry) for i, entry in enumerate(entries) if entry['name'] == name]
            if matches:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f'host {name!r} is not in the native session list')
            time.sleep(.25)
        if len(matches) != 1:
            raise RuntimeError('host name is ambiguous')
        index, entry = matches[0]
        if index != 0 or memory.u(0x68a4bc) != 0 or entry['started']:
            raise RuntimeError('expected unique waiting host in the first visible row')
        row = memory.u(0x68a434)
        if (memory.read(row + 0x1a0, 1)[0] or
                memory.read(memory.u(row + 0x1b0) + 4, 16).hex() != entry['guid']):
            raise RuntimeError('visible row does not match the expected waiting session GUID')
        lobby.click(97, 76)
        if memory.u(0x61e5ec) != 0:
            raise RuntimeError('native GUI did not select the verified first row')
        result = dict(expected_host=name, selected_row=0, guid=entry['guid'],
                      started=False, discovered=entries)
        (lobby.root / 'session_selection.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        memory.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('name')
    parser.add_argument('--fixture', default='live')
    args = parser.parse_args()
    select(args.run, args.name, args.fixture)
