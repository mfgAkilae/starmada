"""Build Federation fleets through normal multiplayer commands and verify peers.

python tools/late_game_player.py <run> --minutes 180
The controller preserves clients on failure and posts WM_CLOSE only after the
default Late-Game criteria pass. Command receipts prove submission only.
"""
import argparse
from contextlib import redirect_stdout
import ctypes
from ctypes import wintypes as wt
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import time

from cmpdumps import LOCAL, STEP
from gameplay_state import objects
from late_game_metrics import EvidenceError, RunMetrics, sample
from play_input import BASE, Input
import probe


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def atomic_json(path, value):
    pending = path.with_suffix(path.suffix + '.tmp')
    pending.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    pending.replace(path)


class Memory:
    def __init__(self, pid, expected_path):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self.kernel.OpenProcess.restype = wt.HANDLE
        self.kernel.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.kernel.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        self.kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                          ctypes.POINTER(wt.DWORD)]
        self.kernel.CloseHandle.argtypes = [wt.HANDLE]
        self.handle = self.kernel.OpenProcess(0x1010, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        path, length = ctypes.create_unicode_buffer(32768), wt.DWORD(32768)
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(length)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if Path(path.value).resolve() != expected_path.resolve():
            self.close()
            raise RuntimeError('run PID does not identify the expected game fixture')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def alive(self):
        code = wt.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259

    def read(self, address, count=4):
        data, received = ctypes.create_string_buffer(count), ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, data, count, ctypes.byref(received)):
            raise ctypes.WinError(ctypes.get_last_error())
        if received.value != count:
            raise OSError('incomplete own-process read')
        return bytes(data)

    def u(self, address):
        return struct.unpack('<I', self.read(address))[0]

    def f(self, address):
        value = struct.unpack('<f', self.read(address))[0]
        if not math.isfinite(value):
            raise OSError('non-finite own-process state')
        return value

    def string(self, address):
        return self.read(address, 96).split(b'\0', 1)[0].decode('ascii')

    def snapshot(self):
        lobby = self.u(self.u(0x678810) + 0x20)
        slot, data = self.u(lobby), self.u(lobby + 0xc)
        if slot >= 8:
            raise OSError('local lobby slot unavailable')
        team = self.u(data + 0x8c + slot * 0x4c)
        if not 1 <= team <= 8:
            raise OSError('local team unavailable')
        player = self.u(0x633e40 + team * 4)
        economy = dict(dilithium=self.f(player + 0x10), officers=self.u(player + 0x18),
                       crew=self.f(player + 0x20))
        sentinel = self.u(0x65a254)
        node = self.u(sentinel)
        visited, actors = set(), {}
        while node != sentinel:
            if not node or node in visited or len(visited) >= 20000:
                raise OSError('object list changed during read')
            visited.add(node)
            actor = self.u(node + 8)
            if self.u(actor + 0xbc) & 4 and self.u(actor + 0x194) == team:
                identity = struct.unpack('<i', self.read(actor + 0xc4))[0]
                klass = self.u(actor + 0xe0)
                name = self.string(self.u(klass + 0x8c))
                entry = dict(id=identity, name=name, builds={})
                if name in ('fbase', 'fconst', 'fyard'):
                    for i in range(11):
                        build = self.u(klass + 0x518 + 4 * i)
                        if build:
                            build_name = self.string(self.u(build + 0x8c))
                            dili, officers, crew, duration = struct.unpack('<iiif', self.read(build + 0x68, 16))
                            if min(dili, officers, crew, duration) < 0 or not math.isfinite(duration):
                                raise OSError('invalid nominal build cost')
                            entry['builds'][build_name] = dict(dilithium=dili, officers=officers,
                                                             crew=crew, seconds=duration)
                if name == 'fconst':
                    entry['active_class'], entry['queued'] = self.u(actor + 0x798), self.u(actor + 0x7b8)
                actors[identity] = entry
            node = self.u(node)
        return dict(team=team, economy=economy, actors=actors)


class Player:
    def __init__(self, tag, device, receipt, resource_stress=False):
        self.tag, self.device, self.receipt = tag, device, receipt
        self.resource_stress = resource_stress
        self.cooldowns, self.pending, self.catalogued = {}, [], set()
        self.submitted, self.rejected = 0, 0

    def log(self, now, event, **values):
        self.receipt(dict(wall_time=timestamp(), simulation_seconds=now, tag=self.tag,
                          event=event, **values))

    def submit(self, now, action, actor, name='', target=0, position=(0, 0, 0), cost=None):
        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                self.device.command(action, actor['id'], target=target, name=name, position=position)
        except (OSError, RuntimeError) as error:
            self.rejected += 1
            self.log(now, 'command', result='not_submitted', action=action, actor=actor['id'],
                     name=name, target=target, position=position, error=str(error))
            return False
        self.submitted += 1
        self.log(now, 'command', result='submitted', action=action, actor=actor['id'],
                 name=name, target=target, position=position, nominal_cost=cost,
                 acknowledgement=captured.getvalue().strip())
        return True

    @staticmethod
    def affordable(economy, cost):
        return all(economy[key] >= cost[key] for key in ('dilithium', 'officers', 'crew'))

    @staticmethod
    def reserve(economy, cost):
        for key in ('dilithium', 'officers', 'crew'):
            economy[key] -= cost[key]

    def build(self, now, actor, name, economy, cadence):
        key = ('build', actor['id'])
        cost = actor['builds'].get(name)
        if not cost or now < self.cooldowns.get(key, -1) or not self.affordable(economy, cost):
            return False
        self.cooldowns[key] = now + cadence
        if self.submit(now, 1, actor, name=name, cost=cost):
            self.reserve(economy, cost)
            return True
        return False

    def construct(self, now, actor, name, position, economy):
        key = ('construct', actor['id'])
        cost = actor['builds'].get(name)
        if (not cost or actor.get('active_class') or actor.get('queued') or
                any(request.get('actor') == actor['id'] for request in self.pending) or
                now < self.cooldowns.get(key, -1) or not self.affordable(economy, cost)):
            return False
        self.cooldowns[key] = now + 30
        if self.submit(now, 3, actor, name=name, position=position, cost=cost):
            self.reserve(economy, cost)
            self.pending.append(dict(name=name, actor=actor['id'], position=position,
                                     cost=cost, charged=False,
                                     expires=now + max(600, cost['seconds'] + 300)))
            return True
        return False

    def control(self, now, state, world, human_teams, offensive):
        team, actors = state['team'], state['actors']
        economy = dict(state['economy'])
        own = [obj for obj in world if obj['team'] == team and obj.get('health', 0) > 0]
        bases = [obj for obj in own if obj['name'].startswith('fbase')]
        if not bases:
            self.log(now, 'no_federation_base', team=team)
            return
        base = bases[0]
        for actor in actors.values():
            if actor['name'] in ('fbase', 'fconst', 'fyard', 'fmining') and actor['id'] not in self.catalogued:
                self.catalogued.add(actor['id'])
                self.log(now, 'producer_catalogue', actor=actor['id'], name=actor['name'],
                         available_classes=actor['builds'])
        self.pending = [request for request in self.pending if request['actor'] in actors and
                       now < request['expires'] and not any(
            obj['name'].startswith(request['name']) and 'pos' in obj and
            distance(obj['pos'], request['position']) < 250 for obj in own)]
        for request in self.pending:
            if actors[request['actor']].get('active_class'):
                request['charged'] = True
            if not request['charged']:
                self.reserve(economy, request['cost'])
        yards = [obj for obj in own if obj['name'].startswith('fyard')]
        mines = [obj for obj in own if obj['name'].startswith('fmining')]
        constructors = [obj for obj in own if obj['kind'] == 'constructionrig']
        freighters = [obj for obj in own if obj['name'].startswith('ffreight')]
        ships = sorted((obj for obj in own if obj['kind'] == 'wingman'), key=lambda obj: obj['id'])
        all_bases = [obj['pos'] for obj in world if obj['kind'] == 'starbase' and 'pos' in obj]
        center = [sum(p[i] for p in all_bases) / len(all_bases) for i in range(3)] if all_bases else [3000, 0, 3000]
        dx, dz = center[0] - base['pos'][0], center[2] - base['pos'][2]
        norm = math.hypot(dx, dz) or 1
        forward, side = (dx / norm, dz / norm), (-dz / norm, dx / norm)
        yard_positions = [(base['pos'][0] + forward[0] * depth + side[0] * offset, 38.5,
                           base['pos'][2] + forward[1] * depth + side[1] * offset)
                          for depth, offset in ((400, -300), (400, 300), (750, -450), (750, 450))]
        moons = sorted((obj for obj in world if obj['kind'] == 'scrap' and
                        obj['name'].startswith(('mdmoon', 'mmooninf')) and 'pos' in obj),
                       key=lambda obj: distance(obj['pos'], base['pos']))

        def requested(name):
            return sum(request['name'] == name for request in self.pending)

        def clear(position):
            stations = [obj['pos'] for obj in own if obj['kind'] not in ('wingman', 'constructionrig', 'freighter') and 'pos' in obj]
            return all(distance(position, other) >= 300 for other in stations + [p['position'] for p in self.pending])

        projected_ships = len(ships)
        for actor in actors.values():
            if actor['name'] != 'fconst' or actor['id'] not in {obj['id'] for obj in own}:
                continue
            yard_count = len(yards) + requested('fyard')
            mine_count = len(mines) + requested('fmining')
            need_mine = not self.resource_stress and (mine_count < 1 or (
                mine_count < 2 and len(freighters) >= 4 and economy['dilithium'] < 2500))
            if not need_mine and (yard_count < 1 or (yard_count < 4 and (mines or self.resource_stress))):
                target = next((pos for pos in yard_positions if clear(pos)), None)
                if target:
                    self.construct(now, actor, 'fyard', target, economy)
            elif need_mine:
                for moon in moons:
                    if distance(moon['pos'], base['pos']) > 2000:
                        break
                    if any(distance(moon['pos'], mine['pos']) < 1400 for mine in mines if 'pos' in mine):
                        continue
                    if any(request['name'] == 'fmining' and distance(moon['pos'], request['position']) < 1400 for request in self.pending):
                        continue
                    # Generic stock placement requires 450 units beyond both object
                    # radii. A point 200-250 units from the moon is rejected before
                    # resources are charged. Use clear ground and let freighters travel.
                    targets = [(moon['pos'][0] + math.cos(i * math.pi / 4) * 1100, 38.5,
                                moon['pos'][2] + math.sin(i * math.pi / 4) * 1100) for i in range(8)]
                    targets.sort(key=lambda pos: distance(pos, base['pos']))
                    target = next((pos for pos in targets if
                                   600 < pos[0] < 5800 and 600 < pos[2] < 5800 and clear(pos) and
                                   all(distance(pos, other['pos']) > 850 for other in moons)), None)
                    if target is not None:
                        self.construct(now, actor, 'fmining', target, economy)
                        break
        live_ids = {obj['id'] for obj in own}
        for actor in actors.values():
            if actor['id'] not in live_ids:
                continue
            if actor['name'] == 'fyard' and (mines or self.resource_stress) and projected_ships < 100:
                if self.build(now, actor, 'fdestroy', economy, 26):
                    projected_ships += 1
            elif actor['name'] == 'fbase' and (mines or self.resource_stress) and len(constructors) < 4:
                self.build(now, actor, 'fconst', economy, 55)
            elif actor['name'] in ('fmining', 'fbase') and mines and len(freighters) < 6:
                self.build(now, actor, 'ffreight', economy, 30)
        enemies = [obj for obj in world if obj['team'] and obj['team'] not in human_teams and
                   obj.get('health', 0) > 0 and 'pos' in obj]
        threats = [obj for obj in enemies if distance(obj['pos'], base['pos']) < 1200]
        threats.sort(key=lambda obj: (obj['kind'] != 'wingman', distance(obj['pos'], base['pos'])))
        anchors = []
        candidates = sorted(enemies, key=lambda obj: (obj['kind'] != 'starbase', obj['kind'] == 'wingman', obj['id']))
        for obj in candidates:
            if all(distance(obj['pos'], anchor['pos']) > 2200 for anchor in anchors):
                anchors.append(obj)
                if len(anchors) == 3:
                    break
        for index, obj in enumerate(ships):
            actor = actors.get(obj['id'])
            key = ('attack', obj['id'])
            if not actor or now < self.cooldowns.get(key, -1):
                continue
            target = threats[0] if threats else None
            if offensive and index % 2 == 0 and anchors:
                anchor = anchors[(index // 2) % len(anchors)]
                defenders = [enemy for enemy in enemies if enemy['kind'] == 'wingman' and
                             distance(enemy['pos'], anchor['pos']) < 1000]
                target = min(defenders, key=lambda enemy: distance(enemy['pos'], obj['pos'])) if defenders else anchor
            if target:
                self.cooldowns[key] = now + 20
                self.submit(now, 2, actor, target=target['id'])


def compare_pair(run, name):
    step = int(STEP.fullmatch(name)[1])
    texts = [(run / tag / name).read_text(encoding='latin1') for tag in ('A', 'B')]
    normalized = [[LOCAL.sub('', line) for line in text.splitlines()] for text in texts]
    for lines in normalized:
        if (len(lines) < 3 or not re.fullmatch(rf'step {step} synced_rng [0-9a-fA-F]+ table_index \d+', lines[0])
                or lines[-1] != f'END step {step}'):
            raise EvidenceError(f'{name}: incomplete or invalid dump')
    if normalized[0] != normalized[1]:
        raise EvidenceError(f'{name}: peer state diverged', 1)
    return sample('\n'.join(texts[0].splitlines()) + '\n')


def close_owned(player, memory):
    if not memory.alive():
        return False
    owner = wt.DWORD()
    probe.user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    probe.user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    probe.user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    probe.user32.GetWindowThreadProcessId(player.device.hwnd, ctypes.byref(owner))
    name = ctypes.create_unicode_buffer(64)
    probe.user32.GetClassNameW(player.device.hwnd, name, 64)
    if owner.value != player.device.pid or name.value != 'Armada':
        return False
    return bool(probe.user32.PostMessageW(player.device.hwnd, 0x10, 0, 0))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--minutes', type=float, default=180)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run) or not 0 < args.minutes <= 1440:
        parser.error('valid run name and wall timeout in (0, 1440] minutes required')
    run = BASE / 'work' / 'det' / args.run
    if not run.is_dir():
        parser.error('run directory does not exist')
    launch = json.loads((run / 'launch.json').read_text(encoding='utf-8-sig')) if (run / 'launch.json').exists() else {}
    fixture = launch.get('fixture', 'live')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', fixture):
        parser.error('invalid fixture name in launch metadata')
    scenario = json.loads((run / 'scenario.json').read_text()) if (run / 'scenario.json').exists() else {}
    resource_stress = scenario.get('dilithium', 10000) > 10000
    metrics, memories, players = RunMetrics(), {}, {}
    seen, seen_objects, initial_objects, damaged = set(), {}, None, set()
    first_health, disappeared = {}, set()
    started, last_progress, last_print = time.monotonic(), time.monotonic(), -60
    offensive, latest_economy, failure, exit_code = False, {}, None, 2
    status_path = run / 'player_status.json'

    def status(state, **extra):
        return dict(state=state, wall_time=timestamp(), wall_seconds=time.monotonic() - started,
                    metrics=metrics.summary(), economy=latest_economy, offensive=offensive,
                    submitted={tag: player.submitted for tag, player in players.items()},
                    rejected={tag: player.rejected for tag, player in players.items()},
                    seen_objects=len(seen_objects), born_objects=len(set(seen_objects) - (initial_objects or set())),
                    damaged_objects=len(damaged), disappeared_objects=len(disappeared), **extra)

    try:
        with (run / 'player_timeline.jsonl').open('a', encoding='utf-8', buffering=1) as timeline, \
             (run / 'player_commands.jsonl').open('a', encoding='utf-8', buffering=1) as commands, \
             (run / 'player_verified_steps.txt').open('w', encoding='utf-8', buffering=1) as verified:
            def receipt(value):
                commands.write(json.dumps(value, sort_keys=True) + '\n')

            receipt(dict(event='controller_start', wall_time=timestamp(), minutes=args.minutes))
            for tag in ('A', 'B'):
                device = Input(args.run, tag)
                memories[tag] = Memory(device.pid, BASE / 'work' / 'play_clients' / fixture / tag / 'Armada.exe')
                players[tag] = Player(tag, device, receipt, resource_stress)
            while time.monotonic() - started < args.minutes * 60:
                for tag, memory in memories.items():
                    if not memory.alive():
                        raise EvidenceError(f'client {tag} exited before acceptance')
                shared = {p.name for p in (run / 'A').glob('step_*.txt')} & {p.name for p in (run / 'B').glob('step_*.txt')}
                pending = sorted((name for name in shared - seen if STEP.fullmatch(name)),
                                 key=lambda name: int(STEP.fullmatch(name)[1]))
                latest = None
                for name in pending:
                    current = compare_pair(run, name)
                    metrics.add(current)
                    seen.add(name)
                    latest = run / 'A' / name
                    timeline.write(json.dumps(dict(wall_time=timestamp(), **current), sort_keys=True) + '\n')
                    verified.write(name + '\n')
                    world = [obj for obj in objects(latest) if obj['team'] and obj.get('health', 0) > 0]
                    current_ids = {obj['id'] for obj in world}
                    if initial_objects is None:
                        initial_objects = current_ids
                    for obj in world:
                        identity = obj['id']
                        first_health[identity] = max(first_health.get(identity, obj['health']), obj['health'])
                        if obj['health'] < first_health[identity] - .01:
                            damaged.add(identity)
                        seen_objects[identity] = obj
                    disappeared |= set(seen_objects) - current_ids
                    last_progress = time.monotonic()
                    offensive |= metrics.longest_fleet_seconds >= metrics.criteria.min_fleet_seconds
                    atomic_json(status_path, status('running', latest=current))
                if metrics.summary()['passed']:
                    atomic_json(status_path, status('accepted'))
                    closed = {tag: close_owned(player, memories[tag]) for tag, player in players.items()}
                    atomic_json(status_path, status('accepted', close_posted=closed))
                    print(json.dumps(status('accepted', close_posted=closed), sort_keys=True), flush=True)
                    return 0
                if latest:
                    current = metrics.previous
                    now = current['simulation_seconds']
                    try:
                        states = {tag: memory.snapshot() for tag, memory in memories.items()}
                    except (OSError, ValueError, UnicodeError) as error:
                        receipt(dict(event='memory_read_retry', wall_time=timestamp(),
                                     simulation_seconds=now, error=str(error)))
                    else:
                        human_teams = {state['team'] for state in states.values()}
                        latest_economy = {tag: dict(team=state['team'], **state['economy']) for tag, state in states.items()}
                        world = objects(latest)
                        for tag, player in players.items():
                            player.control(now, states[tag], world, human_teams, offensive)
                        atomic_json(status_path, status('running', latest=current))
                    if now - last_print >= 60:
                        print(json.dumps(dict(wall_time=timestamp(), step=current['step'],
                                              simulation_minutes=round(now / 60, 2), combat_ships=current['combat_ships'],
                                              fronts=current['active_battle_clusters'],
                                              longest_fleet_seconds=metrics.longest_fleet_seconds,
                                              parallel_combat_seconds=metrics.parallel_combat_seconds,
                                              economy=latest_economy), sort_keys=True), flush=True)
                        last_print = now
                if time.monotonic() - last_progress > 120:
                    raise EvidenceError('no new verified peer dump for 120 wall seconds')
                time.sleep(.5)
            failure = 'wall timeout before Late-Game acceptance'
    except (EvidenceError, OSError, RuntimeError, ValueError) as error:
        failure, exit_code = str(error), getattr(error, 'exit_code', 2)
    finally:
        for memory in memories.values():
            memory.close()
    atomic_json(status_path, status('failed', error=failure))
    print(json.dumps(status('failed', error=failure), sort_keys=True), flush=True)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
