"""Inspect or configure six joined human slots through their owned lobby dialogs.

python tools/setup_six_player_lobby.py <run> [--fixture <fixture>] [--inspect | --host-only]
No client is started, launched, activated or closed. --inspect sends only read
messages; configuration uses the game's existing custom-combo mouse handler.
"""
import argparse
import ctypes
from ctypes import wintypes as wt
import hashlib
import json
from pathlib import Path
import re
import time

from late_game_metrics import resolve_peers
from late_game_player import Memory
import probe
from setup_late_game_lobby import BASE, Lobby


PEERS = list('ABCDEF')
RACES = dict(A=('Federation', 0), B=('Federation', 0), C=('Klingon', 3),
             D=('Klingon', 3), E=('Romulan', 2), F=('Borg', 1))
ALLIANCES = dict(A=1, B=2, C=1, D=2, E=1, F=2)
RESOURCE_IDS = dict(crew=2142, officers=2143, dilithium=2144)
MAP = '6violins.bzn'
CATALOGUE = {}
ROLE_MAPS = {}
SAVED_INSPECTIONS = {}
SEND = probe.user32.SendMessageTimeoutW
SEND.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                 ctypes.POINTER(ctypes.c_size_t)]
SEND.restype = wt.LPARAM


def send(hwnd, message, wp=0, lp=0):
    result = ctypes.c_size_t()
    if not SEND(hwnd, message, wp, lp, 2, 1000, ctypes.byref(result)):
        raise ctypes.WinError()
    return ctypes.c_ssize_t(result.value).value


def section_labels(data, section):
    found = re.search(rf'(?ms)^{section}[ \t]*\{{[^\r\n]*\r?\n(.*?)^[ \t]*\}}', data)
    if not found:
        raise RuntimeError(f'label.map section {section} is missing')
    return dict(re.findall(r'^[ \t]*\+[ \t]+(\w+)[ \t]+\{([^}]*)\}', found[1], re.M))


def items(hwnd, kind, style):
    count_message, length_message, text_message = (0x146, 0x149, 0x148) if kind == 'ComboBox' else (0x18b, 0x18a, 0x189)
    count = send(hwnd, count_message)
    if not 0 <= count <= 128:
        raise RuntimeError(f'unsupported {kind} item count {count}')
    owner_data = bool(style & (0x10 | 0x20)) and not bool(style & (0x200 if kind == 'ComboBox' else 0x40))
    result = []
    for index in range(count):
        text = None
        if not owner_data:
            length = send(hwnd, length_message, index)
            if not 0 <= length <= 4096:
                raise RuntimeError('unsupported item text length')
            buffer = ctypes.create_unicode_buffer(length + 1)
            if send(hwnd, text_message, index, ctypes.addressof(buffer)) < 0:
                raise RuntimeError('item text unavailable')
            text = buffer.value
        result.append(dict(index=index, text=text))
    return result


def controls(lobby):
    result = []
    for hwnd, kind, text, rectangle, visible, cid in probe.children(lobby.dialog()):
        record = dict(hwnd=hwnd, kind=kind, text=text, rect=list(rectangle), visible=visible, cid=cid,
                      enabled=bool(probe.user32.IsWindowEnabled(hwnd)))
        if kind in ('ComboBox', 'ListBox'):
            style = probe.user32.GetWindowLongW(hwnd, -16) & 0xffffffff
            try:
                record.update(selected=send(hwnd, 0x147 if kind == 'ComboBox' else 0x188),
                              items=items(hwnd, kind, style), style=hex(style))
            except (OSError, RuntimeError) as error:
                record['read_error'] = str(error)
        result.append(record)
    return result


def native(memory):
    lobby = memory.u(memory.u(0x678810) + 0x20)
    slot, data = memory.u(lobby), memory.u(lobby + 0xc)
    if not 0 <= slot < 8:
        raise RuntimeError('native local slot is unavailable')
    header = memory.read(data, 0x8c)
    engine = memory.u(0x6d4aa0)
    rows = []
    for index in range(8):
        row = memory.read(data + 0x8c + index * 0x4c, 0x4c)
        rows.append(dict(slot=index, player_team=int.from_bytes(row[:4], 'little'),
                         alliance_index=int.from_bytes(row[0xc:0x10], 'little'),
                         race_index=int.from_bytes(row[0x14:0x18], 'little')))
    return dict(local_slot=slot, player_team=memory.u(data + 0x8c + slot * 0x4c),
                infinite_moons=bool(memory.read(data + 0x56, 1)[0]),
                engine_mode=memory.u(engine + 0x124), header_hex=header.hex(),
                header_strings=[value.decode('latin1') for value in re.findall(rb'[ -~]{4,}', header)],
                resource_rules={key: int.from_bytes(header[offset:offset + 4], 'little')
                                for key, offset in (('dilithium', 0x58), ('crew', 0x5c), ('officers', 0x60), ('max_players', 0x68))},
                players=rows)


def screenshot(lobby, name):
    dialog = next(window for window in probe.dialogs(lobby.pid) if window['hwnd'] == lobby.dialog())
    original = probe.main_window
    try:
        probe.main_window = lambda _, dialog=dialog: dialog
        probe.shot(lobby.pid, str(lobby.root / name))
    finally:
        probe.main_window = original


def diagnostic(lobby, memory, state, error=None):
    result = dict(tag=lobby.tag, pid=lobby.pid, state=state, error=error,
                  windows=probe.windows(lobby.pid), dialogs=[])
    for dialog in probe.dialogs(lobby.pid):
        result['dialogs'].append(dict(hwnd=dialog['hwnd'], children=probe.children(dialog['hwnd'])))
    try:
        result['native'] = native(memory)
    except (OSError, RuntimeError) as failure:
        result['native_error'] = str(failure)
    (lobby.root / f'{state}_{lobby.tag}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def wait_ready(lobby, memory, seconds=45, inspect_only=False):
    deadline = time.monotonic() + seconds
    while True:
        dialogs = probe.dialogs(lobby.pid)
        candidates = dialogs if inspect_only else dialogs[:1]
        if any(kind == 'ComboBox' and cid == 2136 and send(hwnd, 0x146) >= 2
               for dialog in candidates for hwnd, kind, _, _, _, cid in probe.children(dialog['hwnd'])):
            diagnostic(lobby, memory, 'lobby_ready')
            return
        if not memory.alive() or time.monotonic() >= deadline:
            error = 'visible lobby with CID2136 did not become ready within the bounded wait'
            diagnostic(lobby, memory, 'lobby_not_ready', error)
            raise RuntimeError(f'{lobby.tag}: {error}; lobby_not_ready_{lobby.tag}.json preserved')
        time.sleep(.2)


def saved_controls(lobby):
    key = str(lobby.root)
    if key not in SAVED_INSPECTIONS:
        path = lobby.root / 'six_lobby_inspect.json'
        SAVED_INSPECTIONS[key] = json.loads(path.read_text()) if path.exists() else {}
    entry = SAVED_INSPECTIONS[key].get('clients', {}).get(lobby.tag, {})
    return entry.get('controls', []) if entry.get('pid') == lobby.pid else []


def control(lobby, cid, include_items=True, refresh=False):
    matches = [entry for entry in probe.children(lobby.dialog()) if entry[5] == cid and entry[1] == 'ComboBox']
    if len(matches) != 1:
        raise RuntimeError(f'{lobby.tag}: expected unique ComboBox CID {cid}')
    hwnd, kind, text, rectangle, visible, _ = matches[0]
    style = probe.user32.GetWindowLongW(hwnd, -16) & 0xffffffff
    result = dict(hwnd=hwnd, kind=kind, text=text, rect=list(rectangle), visible=visible, cid=cid,
                  selected=send(hwnd, 0x147))
    if include_items:
        key = (lobby.pid, lobby.dialog(), hwnd, cid)
        if key not in CATALOGUE and not refresh:
            previous = next((entry for entry in saved_controls(lobby) if entry.get('hwnd') == hwnd and entry['cid'] == cid
                             and 'items' in entry and 'read_error' not in entry), None)
            if previous:
                CATALOGUE[key] = [dict(index=item['index'], text=item['text']) for item in previous['items']]
        if key not in CATALOGUE or refresh:
            CATALOGUE[key] = items(hwnd, kind, style)
        result['items'] = CATALOGUE[key]
    return result


def role_controls(lobby, labels):
    key = (lobby.pid, lobby.dialog())
    if key in ROLE_MAPS:
        return ROLE_MAPS[key]
    race_labels = [labels[name] for name in ('federation', 'borg', 'romulan', 'klingon', 'random')]
    team_labels = [labels[f'team_{index}'] for index in range(1, 9)]

    def classify(entries):
        races, teams = [], []
        for entry in entries:
            values = [item.get('text') for item in entry.get('items', [])]
            if values == race_labels:
                races.append(entry['cid'])
            elif values == team_labels:
                teams.append(entry['cid'])
        return dict(races=sorted(races), alliances=sorted(teams))

    present = {cid for _, kind, _, _, _, cid in probe.children(lobby.dialog()) if kind == 'ComboBox'}
    result = classify([entry for entry in saved_controls(lobby) if entry.get('cid') in present])
    if len(result['races']) != 8 or len(result['alliances']) != 8:
        if ROLE_MAPS:
            candidate = next(iter(ROLE_MAPS.values()))
            if set(candidate['races'] + candidate['alliances']) <= present:
                result = dict(races=list(candidate['races']), alliances=list(candidate['alliances']))
        if len(result['races']) != 8 or len(result['alliances']) != 8:
            candidates = []
            for cid in sorted(present):
                if cid >= 2130:
                    continue
                entry = control(lobby, cid, include_items=False)
                if send(entry['hwnd'], 0x146) in (5, 8):
                    candidates.append(control(lobby, cid))
            result = classify(candidates)
    if len(result['races']) != 8 or len(result['alliances']) != 8:
        raise RuntimeError(f'{lobby.tag}: native Race/Alliance controls are not uniquely identifiable: {result}')
    result.update(race_labels=race_labels, alliance_labels=team_labels,
                  evidence='Native option-label signatures; ascending confirmed control order is the stock row order')
    ROLE_MAPS[key] = result
    return result


def options(entry, fallback):
    actual = [item['text'] for item in entry['items']]
    if actual and all(value is not None and value != '' for value in actual):
        return actual, 'native ComboBox items'
    if len(actual) != len(fallback):
        raise RuntimeError(f'CID {entry["cid"]}: item labels unavailable and stock count differs')
    return fallback, 'stock label.map order; owner-draw item text unavailable'


def stock_options(entry, labels):
    cid, count = entry['cid'], len(entry.get('items', []))
    prefix = {2142: 'sc', 2143: 'mo', 2144: 'sd'}.get(cid)
    if prefix:
        return [labels[f'{prefix}_value_{index}'] for index in range(1, 6)]
    if 2121 <= cid <= 2128 and 1 <= count <= 8:
        return [labels[f'team_{index}'] for index in range(1, count + 1)]
    if 2111 <= cid <= 2118 and count == 4:
        return [labels[key] for key in ('empty', 'computer_easy', 'computer_medium', 'computer_hard')]
    if cid == 2136 and count in (5, 7):
        return [labels[f'maximum_players_{index}'] for index in range(count + 1, 1, -1)]
    if cid == 2140:
        return [labels[f'default_units_{kind}'] for kind in ('map', 'minimal', 'standard', 'super')]
    if cid == 2119:
        return [labels[f'tech_level_{kind}'] for kind in ('one', 'two', 'three', 'four', 'five', 'six', 'seven')]
    return []


def center(lobby, entry):
    # Hidden ComboBox HWNDs store data; their bounds differ from the drawn controls.
    cid = entry['cid']
    roles = ROLE_MAPS.get((lobby.pid, lobby.dialog()), {})
    for name, x in (('races', 205), ('alliances', 291)):
        if cid in roles.get(name, []):
            return x, 64 + 19 * roles[name].index(cid)
    drawn = {2136: (580, 94), 2144: (580, 166), 2142: (580, 190),
             2143: (580, 214), 2140: (580, 237), 2119: (580, 262)}
    if cid in drawn:
        return drawn[cid]
    raise RuntimeError(f'CID {cid}: custom-draw input coordinates are not confirmed')


def choose(lobby, cid, desired, fallback, up=False, coordinates=None):
    entry = control(lobby, cid)
    labels, source = options(entry, fallback)
    matches = [index for index, value in enumerate(labels) if value.casefold() == str(desired).casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'CID {cid}: required label {desired!r} not unique in {labels!r}')
    index = matches[0]
    position = coordinates or center(lobby, entry)
    changed = entry['selected'] != index
    if changed:
        lobby.dropdown(*position, index, up=up)
    if lobby.selected(cid) != index:
        raise RuntimeError(f'{lobby.tag}: CID {cid} did not select {desired!r}')
    return dict(cid=cid, index=index, label=labels[index], options=labels, label_source=source,
                input_coordinates=list(position), input_sent=changed)


def choose_map(host, labels, title):
    previous = host.dialog()
    host.click(449, 281)
    deadline = time.monotonic() + 5
    while host.dialog() == previous:
        if time.monotonic() >= deadline:
            raise RuntimeError('Select Map dialog did not open')
        time.sleep(.1)
    map_labels = [labels['all_maps']] + [labels[f'maximum_players_{count}'] for count in range(8, 1, -1)]
    combos = [entry for entry in controls(host) if entry['kind'] == 'ComboBox' and 'items' in entry]
    candidates = []
    for entry in combos:
        try:
            values, _ = options(entry, map_labels)
        except RuntimeError:
            continue
        if labels['maximum_players_6'] in values:
            candidates.append(entry)
    if len(candidates) != 1:
        raise RuntimeError('six-player map filter is not uniquely identifiable; inspect Map dialog')
    chosen_filter = choose(host, candidates[0]['cid'], labels['maximum_players_6'], map_labels, coordinates=(306, 12))
    list_matches = [(entry, item) for entry in controls(host) if entry['kind'] == 'ListBox'
                    for item in entry.get('items', []) if item['text'] == title]
    if len(list_matches) == 1:
        entry, item = list_matches[0]
        rectangle = wt.RECT()
        if send(entry['hwnd'], 0x198, item['index'], ctypes.addressof(rectangle)) != 0:
            raise RuntimeError('selected map item rectangle unavailable')
        point = wt.POINT((rectangle.left + rectangle.right) // 2, (rectangle.top + rectangle.bottom) // 2)
        probe.user32.ClientToScreen(entry['hwnd'], ctypes.byref(point))
        probe.user32.ScreenToClient(host.dialog(), ctypes.byref(point))
        host.click(point.x, point.y)
        method, index = 'native ListBox label', item['index']
    else:
        host.click(160, 53)
        method, index = 'stock six-player picker second row; native filename readback required', 1
    picker = controls(host)
    host.click(73, 271)
    deadline = time.monotonic() + 5
    while host.dialog() != previous:
        if time.monotonic() >= deadline:
            raise RuntimeError('Select Map did not return to the lobby')
        time.sleep(.1)
    return dict(filename=MAP, title=title, filter=chosen_filter, selected_row=index,
                method=method, picker_controls=picker)


def inspect(lobbies, memories, filename, root=None, missing=None):
    root = root or lobbies['A'].root
    result = dict(requested_peers=PEERS, peers=list(lobbies), peer_count=len(lobbies), clients={})
    for tag in PEERS:
        if tag not in lobbies:
            result['clients'][tag] = dict(missing=True, reason=(missing or {}).get(tag, 'PID not available'))
            continue
        lobby = lobbies[tag]
        entry = dict(pid=lobby.pid, controls=[])
        try:
            data = (BASE / 'work' / 'play_clients' / lobby.fixture / tag / 'label.map').read_bytes()
            labels = section_labels(data.decode('latin1'), 'multiplayer_setup')
            roles = role_controls(lobby, labels)
            slot = native(memories[tag])['local_slot']
            needed = {roles['races'][slot], roles['alliances'][slot]}
            if tag == 'A':
                needed.update((2136, 2144, 2142, 2143, 2140, 2119))
            entry['controls'] = [control(lobby, cid) for cid in sorted(needed)]
            entry['role_controls'] = roles
            entry['label_map_sha256'] = hashlib.sha256(data).hexdigest()
            for widget in entry['controls']:
                if widget['kind'] != 'ComboBox' or 'items' not in widget:
                    continue
                try:
                    resolved, source = options(widget, stock_options(widget, labels))
                    widget.update(resolved_options=resolved, label_source=source,
                                  selected_label=resolved[widget['selected']] if 0 <= widget['selected'] < len(resolved) else None)
                except RuntimeError as error:
                    widget['label_resolution_error'] = str(error)
        except (OSError, RuntimeError, KeyError) as error:
            entry['label_map_error'] = str(error)
        try:
            entry['native'] = native(memories[tag])
        except (OSError, RuntimeError) as error:
            entry['native_error'] = str(error)
        try:
            screenshot(lobby, f'{tag}_{filename}.png')
        except (OSError, RuntimeError, StopIteration) as error:
            entry['screenshot_error'] = str(error)
        result['clients'][tag] = entry
    (root / f'{filename}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def map_confirmed(snapshot):
    return any(value.replace('\\', '/').split('/')[-1].lower() in (MAP, MAP[:-4])
               for value in snapshot['header_strings'])


def configure_host(host, memory, setup_labels, map_labels, title):
    requested = dict(dilithium=5000, crew=5000, officers=250)
    resource_options, targets, target_labels = {}, {}, {}
    for key, prefix in (('dilithium', 'sd'), ('crew', 'sc'), ('officers', 'mo')):
        fallback = [setup_labels[f'{prefix}_value_{index}'] for index in range(1, 6)]
        values, source = options(control(host, RESOURCE_IDS[key]), fallback)
        numeric = []
        for value in values:
            number = re.search(r'(\d+)\s*$', value)
            if not number:
                raise RuntimeError(f'CID {RESOURCE_IDS[key]}: resource value unavailable in {value!r}')
            numeric.append(int(number[1]))
        target = requested[key]
        if target not in numeric and key == 'dilithium':
            eligible = [value for value in numeric if 3000 <= value <= 10000]
            if eligible:
                target = min(eligible, key=lambda value: (abs(value - requested[key]), value))
        if target not in numeric:
            raise RuntimeError(f'no authorized stock {key} value in {values!r}; no configuration input sent')
        targets[key] = target
        target_labels[key] = values[numeric.index(target)]
        resource_options[key] = dict(cid=RESOURCE_IDS[key], labels=values, label_source=source)
    before = native(memory)
    if before['engine_mode'] != 3:
        raise RuntimeError('host must be in a pre-match lobby')
    selection = (dict(filename=MAP, title=title, method='native lobby already confirms map')
                 if map_confirmed(before) else choose_map(host, map_labels, title))
    max_control = control(host, 2136)
    upper = 6 if len(max_control['items']) == 5 else 8
    maximum = choose(host, 2136, setup_labels['maximum_players_6'],
                     [setup_labels[f'maximum_players_{count}'] for count in range(upper, 1, -1)])
    selected = {key: choose(host, RESOURCE_IDS[key], target_labels[key], resource_options[key]['labels']) for key in targets}
    selected['units'] = choose(host, 2140, setup_labels['default_units_standard'],
                               [setup_labels[f'default_units_{kind}'] for kind in ('map', 'minimal', 'standard', 'super')])
    selected['tech'] = choose(host, 2119, setup_labels['tech_level_one'],
                              [setup_labels[f'tech_level_{kind}'] for kind in ('one', 'two', 'three', 'four', 'five', 'six', 'seven')])
    if native(memory)['infinite_moons']:
        host.click(579, 334)
    expected = {2136: maximum['index'], **{entry['cid']: entry['index'] for entry in selected.values()}}
    deadline = time.monotonic() + 10
    while True:
        snapshot = native(memory)
        actual = {cid: host.selected(cid) for cid in expected}
        if actual == expected and not snapshot['infinite_moons'] and map_confirmed(snapshot):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f'host rule verification incomplete: controls={actual}, native_map_readback={map_confirmed(snapshot)}')
        time.sleep(.25)
    return dict(map=MAP, map_selection=selection, fixture=host.fixture, max_players=6,
                requested_resources=requested, **targets, stock_units=True, stock_tech=True,
                infinite_moons=False, selected=selected, maximum=maximum,
                host_selected_indices=actual, host_native=snapshot)


def configure(lobbies, memories, setup_labels, map_labels, title):
    before = {tag: native(memories[tag]) for tag in PEERS}
    if len({entry['local_slot'] for entry in before.values()}) != 6 or any(entry['engine_mode'] != 3 for entry in before.values()):
        raise RuntimeError('six unique connected pre-match local slots are required')
    host = lobbies['A']
    rules = configure_host(host, memories['A'], setup_labels, map_labels, title)
    players = {}
    for tag in PEERS:
        slot = native(memories[tag])['local_slot']
        roles = role_controls(lobbies[tag], setup_labels)
        race_name, expected_race = RACES[tag]
        race_fallback = [setup_labels[key] for key in ('federation', 'borg', 'romulan', 'klingon', 'random')]
        race_cid, alliance_cid = roles['races'][slot], roles['alliances'][slot]
        race_entry = control(lobbies[tag], race_cid, refresh=True)
        alliance_entry = control(lobbies[tag], alliance_cid, refresh=True)
        if ([item['text'] for item in race_entry['items']] != roles['race_labels'] or
                [item['text'] for item in alliance_entry['items']] != roles['alliance_labels']):
            raise RuntimeError(f'{tag}: current own Race/Alliance option signatures differ from the native catalogue')
        race = choose(lobbies[tag], race_cid, setup_labels[race_name.lower()], race_fallback,
                      up=slot >= 5, coordinates=(205, 64 + 19 * slot))
        if race['index'] != expected_race:
            raise RuntimeError(f'{tag}: stock race ordering differs')
        alliance = choose(lobbies[tag], alliance_cid, setup_labels[f'team_{ALLIANCES[tag]}'],
                          roles['alliance_labels'], up=slot >= 5, coordinates=(291, 64 + 19 * slot))
        players[tag] = dict(local_slot=slot, race=race_name, race_selection=race,
                            alliance=ALLIANCES[tag], alliance_selection=alliance)
    expected = dict(rules['host_selected_indices'])
    for entry in players.values():
        expected[entry['race_selection']['cid']] = entry['race_selection']['index']
        expected[entry['alliance_selection']['cid']] = entry['alliance_selection']['index']
    deadline = time.monotonic() + 15
    while True:
        actual = {cid: control(host, cid, include_items=False)['selected'] for cid in expected}
        snapshots = {tag: native(memories[tag]) for tag in PEERS}
        filenames = {tag: map_confirmed(entry) for tag, entry in snapshots.items()}
        native_rows_match = all(
            snapshot['players'][player['local_slot']]['race_index'] == player['race_selection']['index'] and
            snapshot['players'][player['local_slot']]['alliance_index'] == player['alliance'] - 1
            for snapshot in snapshots.values() for player in players.values())
        resources_match = all(snapshot['resource_rules'] == {key: rules[key] for key in
                             ('dilithium', 'crew', 'officers', 'max_players')} for snapshot in snapshots.values())
        if (actual == expected and len({entry['local_slot'] for entry in snapshots.values()}) == 6 and
                not any(entry['infinite_moons'] for entry in snapshots.values()) and all(filenames.values()) and
                native_rows_match and resources_match):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f'lobby verification incomplete: controls={actual}, native_map_readback={filenames}, '
                               f'native_rows={native_rows_match}, resources={resources_match}')
        time.sleep(.25)
    for lobby in lobbies.values():
        screenshot(lobby, f'{lobby.tag}_six_lobby_configured.png')
    (host.root / 'six_lobby_configured.json').write_text(json.dumps(dict(
        peers=PEERS, native=snapshots, host_selected_indices=actual, players=players), indent=2) + '\n')
    result = dict(rules, peers=PEERS, peer_count=6, human_clients=6, native_ai=0,
                  host_selected_indices=actual, players=players,
                  native=snapshots, native_ai_evidence='Six owned clients have unique connected local slots and fill Max Players: 6',
                  native_model_verified=True,
                  inspection='six_lobby_configured.json')
    (host.root / 'scenario.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--fixture')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--host-only', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run):
        parser.error('safe run name required')
    root = BASE / 'work' / 'det' / args.run
    if not root.is_dir():
        parser.error('run directory must already exist')
    launch = json.loads((root / 'launch.json').read_text(encoding='utf-8-sig')) if (root / 'launch.json').exists() else {}
    fixture = args.fixture or launch.get('fixture', 'live')
    if (not isinstance(fixture, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', fixture) or
            (args.fixture and 'fixture' in launch and args.fixture != launch['fixture'])):
        parser.error('safe fixture matching launch.json required')
    if resolve_peers(root, PEERS) != PEERS:
        parser.error('this setup requires the declared peers A through F')
    lobbies, memories, missing = {}, {}, {}
    try:
        for tag in (['A'] if args.host_only else PEERS):
            if args.inspect and not (root / f'pid_{tag}.txt').exists():
                missing[tag] = 'PID file is missing'
                continue
            try:
                lobby = Lobby(args.run, tag, fixture)
                memory = Memory(lobby.pid, BASE / 'work' / 'play_clients' / fixture / tag / 'Armada.exe')
            except (OSError, RuntimeError, ValueError) as error:
                if not args.inspect:
                    raise
                missing[tag] = str(error)
                continue
            lobbies[tag], memories[tag] = lobby, memory
            wait_ready(lobby, memory, inspect_only=args.inspect)
        if args.inspect:
            inspected = inspect(lobbies, memories, 'six_lobby_inspect_fast', root, missing)
            print(json.dumps(inspected))
            return 0
        game = BASE / 'work' / 'play_clients' / fixture / 'A'
        label = (game / 'label.map').read_bytes()
        if any((BASE / 'work' / 'play_clients' / fixture / tag / 'label.map').read_bytes() != label for tag in lobbies):
            raise RuntimeError('label.map differs between peers')
        map_data = (game / 'bzn' / MAP).read_bytes()
        description = re.search(rb'saveGameDesc\s*=\s*([0-9a-fA-F]+)', map_data)
        if not description or not re.search(r'^StartLocations\s*=\s*6\s*$', (game / 'bzn' / '6violins.mdf').read_text(), re.M):
            raise RuntimeError('stock six-player map metadata unavailable')
        title = bytes.fromhex(description[1].decode('ascii')).split(b'\0', 1)[0].decode('latin1')
        setup_labels = section_labels(label.decode('latin1'), 'multiplayer_setup')
        map_labels = section_labels(label.decode('latin1'), 'multiplayer_map_select')
        if args.host_only:
            result = configure_host(lobbies['A'], memories['A'], setup_labels, map_labels, title)
            result.update(phase='host-only', expected_peers=PEERS, inspected_peers=['A'],
                          native_ai_verified=False, label_map_sha256=hashlib.sha256(label).hexdigest())
            (root / 'host_setup.json').write_text(json.dumps(result, indent=2) + '\n')
            screenshot(lobbies['A'], 'A_six_host_ready.png')
            print(json.dumps(result))
            return 0
        result = configure(lobbies, memories, setup_labels, map_labels, title)
        result['label_map_sha256'] = hashlib.sha256(label).hexdigest()
        (root / 'scenario.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        for tag, lobby in lobbies.items():
            diagnostic(lobby, memories[tag], 'setup_failure', str(error))
        raise
    finally:
        for memory in memories.values():
            memory.close()


if __name__ == '__main__':
    raise SystemExit(main())
