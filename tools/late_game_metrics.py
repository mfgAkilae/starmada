"""Compare complete peer dumps and require measured Late-Game load.

python tools/late_game_metrics.py work/det/<run> --output summary.json --timeline samples.jsonl
launch.json peers are binding; runs without a declaration default to A/B.
--peers A B C D E F selects peers only without a manifest or when identical.
Exit 1 means divergence; exit 2 means invalid or insufficient evidence.
"""
import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import sys

from cmpdumps import LOCAL, STEP


@dataclass
class Criteria:
    min_simulation_seconds: float = 90 * 60
    late_start_seconds: float = 60 * 60
    min_combat_ships: int = 200
    min_fleet_seconds: float = 10 * 60
    min_battle_clusters: int = 3
    min_parallel_seconds: float = 5 * 60
    max_gap_seconds: float = 60


class EvidenceError(ValueError):
    def __init__(self, message, exit_code=2):
        super().__init__(message)
        self.exit_code = exit_code


def _number(value):
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceError('non-finite numeric state')
    return result


def _metric_scope(player_teams=None, player_alliances=None):
    if player_teams is None:
        if player_alliances is not None:
            raise EvidenceError('player_alliances requires player_teams')
        teams = None
    else:
        if (not isinstance(player_teams, (list, tuple)) or not player_teams or
                any(type(team) is not int or not 1 <= team <= 8 for team in player_teams) or
                len(set(player_teams)) != len(player_teams)):
            raise EvidenceError('player_teams must contain unique integer Owner IDs from 1 through 8')
        teams = sorted(player_teams)
    alliances = None
    if player_alliances is not None:
        if (not isinstance(player_alliances, dict) or
                set(player_alliances) != {str(team) for team in teams} or
                any(type(value) is not int or not 0 <= value <= 7 for value in player_alliances.values())):
            raise EvidenceError('player_alliances must map every declared string Owner ID to an integer Alliance ID 0..7')
        alliances = {str(team): player_alliances[str(team)] for team in teams}
    return dict(player_teams=teams, player_alliances=alliances,
                fleet_scope='declared_players' if teams is not None else 'all_non_neutral',
                combat_scope='hostile_declared_alliances' if alliances is not None else 'cross_owner')


def sample(text, player_teams=None, player_alliances=None):
    scope = _metric_scope(player_teams, player_alliances)
    allowed = set(scope['player_teams']) if scope['player_teams'] is not None else None
    alliances = scope['player_alliances']
    clock = re.search(r'^simulation_seconds (\S+) tick (\d+)$', text, re.M)
    header = re.match(r'step (\d+) synced_rng [0-9a-fA-F]+ table_index \d+\n', text)
    if not clock or not header:
        raise EvidenceError('missing simulation clock or valid step header')
    if text.splitlines()[-1] != f'END step {header[1]}':
        raise EvidenceError('missing matching END marker')
    seconds = _number(clock[1])
    if seconds < 0:
        raise EvidenceError('negative simulation clock')
    objects = {}
    for block in re.split(r'^GAMEOBJECT ', text, flags=re.M)[1:]:
        lines = block.splitlines()
        identity = lines[0].split(maxsplit=2)
        team = re.search(r'^  team (\d+)', block, re.M)
        health = re.search(r'curhealth (\S+) maxhealth (\S+)', block)
        if len(identity) != 3 or not team or not health:
            continue
        obj = dict(id=int(identity[0]), kind=identity[1], name=identity[2],
                   team=int(team[1]), health=_number(health[1]), maximum=_number(health[2]))
        pos = re.search(r'^  pos \(([^)]+)\)', block, re.M)
        shot = re.search(r'who_i_shot (-?\d+) when_i_shot (\S+)', block)
        if pos:
            values = [_number(x) for x in pos[1].split(',')]
            if len(values) != 3:
                raise EvidenceError('invalid object position')
            obj['pos'] = values
        if shot:
            obj['target'], obj['when_shot'] = int(shot[1]), _number(shot[2])
        if obj['id'] in objects:
            raise EvidenceError('duplicate game object ID')
        objects[obj['id']] = obj
    alive = {key: obj for key, obj in objects.items() if obj['team'] and obj['health'] > 0 and
             (allowed is None or obj['team'] in allowed)}
    teams = {}
    ships = []
    edges = []
    for obj in alive.values():
        team = teams.setdefault(str(obj['team']), dict(objects=0, combat_ships=0))
        team['objects'] += 1
        if obj['kind'] == 'wingman':
            team['combat_ships'] += 1
            ships.append(obj)
        target = alive.get(obj.get('target', 0))
        if (target and target['team'] != obj['team'] and
                (alliances is None or alliances[str(target['team'])] != alliances[str(obj['team'])]) and
                0 <= seconds - obj.get('when_shot', -10000) <= 5):
            edges.append((obj['id'], target['id']))
    points = {key: alive[key]['pos'] for edge in edges for key in edge if 'pos' in alive[key]}
    parents = {key: key for key in points}

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(a, b):
        parents[root(a)] = root(b)

    for a, b in edges:
        if a in points and b in points:
            union(a, b)
    entries = list(points.items())
    for i, (a, pa) in enumerate(entries):
        for b, pb in entries[i + 1:]:
            if (pa[0] - pb[0]) ** 2 + (pa[2] - pb[2]) ** 2 <= 1000 ** 2:
                union(a, b)
    clusters = {root(a) for a, b in edges if a in points and b in points}
    return dict(step=int(header[1]), simulation_seconds=seconds, tick=int(clock[2]),
                teams=teams, combat_ships=len(ships),
                damaged_combat_ships=sum(o['health'] < o['maximum'] - .01 for o in ships),
                active_firing_ships=len({a for a, _ in edges if alive[a]['kind'] == 'wingman'}),
                active_battle_clusters=len(clusters),
                weapon_instances=len(re.findall(r'^Weapon ', text, re.M)), **scope)


class RunMetrics:
    def __init__(self, criteria=None):
        self.criteria = criteria or Criteria()
        self.previous = None
        self.samples = 0
        self.first_seconds = None
        self.observed_seconds = 0
        self.loaded_seconds = 0
        self.longest_fleet_seconds = 0
        self.parallel_combat_seconds = 0
        self.peak_combat_ships = 0
        self.peak_battle_clusters = 0
        self.gaps = 0
        self._scope = None

    def add(self, current):
        scope = _metric_scope(current.get('player_teams'), current.get('player_alliances'))
        for field in ('fleet_scope', 'combat_scope'):
            if field in current and current[field] != scope[field]:
                raise EvidenceError(f'inconsistent metric scope field: {field}')
        if self._scope is not None and scope != self._scope:
            raise EvidenceError('metric scope changed within run')
        criteria = self.criteria
        now = current['simulation_seconds']
        if self.previous is None:
            self.first_seconds = now
        else:
            previous = self.previous
            delta = now - previous['simulation_seconds']
            if current['step'] <= previous['step'] or delta <= 0:
                raise EvidenceError('step and simulation clock must increase')
            if delta <= criteria.max_gap_seconds:
                self.observed_seconds += delta
                loaded = (previous['simulation_seconds'] >= criteria.late_start_seconds and
                          min(previous['combat_ships'], current['combat_ships']) >= criteria.min_combat_ships)
                if loaded:
                    self.loaded_seconds += delta
                else:
                    self.loaded_seconds = 0
                if loaded and min(previous['active_battle_clusters'], current['active_battle_clusters']) >= criteria.min_battle_clusters:
                    self.parallel_combat_seconds += delta
            else:
                self.gaps += 1
                self.loaded_seconds = 0
            self.longest_fleet_seconds = max(self.longest_fleet_seconds, self.loaded_seconds)
        self.samples += 1
        self.peak_combat_ships = max(self.peak_combat_ships, current['combat_ships'])
        self.peak_battle_clusters = max(self.peak_battle_clusters, current['active_battle_clusters'])
        self._scope = scope
        self.previous = current

    def summary(self):
        criteria = self.criteria
        conditions = dict(duration=self.observed_seconds >= criteria.min_simulation_seconds,
                          sustained_fleet=self.longest_fleet_seconds >= criteria.min_fleet_seconds,
                          parallel_combat=self.parallel_combat_seconds >= criteria.min_parallel_seconds)
        scope = (_metric_scope(self._scope['player_teams'], self._scope['player_alliances'])
                 if self._scope is not None else _metric_scope())
        return dict(passed=self.samples >= 2 and all(conditions.values()), conditions=conditions,
                    criteria=asdict(criteria), pairs=self.samples,
                    first_simulation_seconds=self.first_seconds,
                    last_simulation_seconds=self.previous['simulation_seconds'] if self.previous else None,
                    last_step=self.previous['step'] if self.previous else None,
                    observed_seconds=self.observed_seconds, gaps_over_maximum=self.gaps,
                    longest_fleet_seconds=self.longest_fleet_seconds,
                    parallel_combat_seconds=self.parallel_combat_seconds,
                    peak_combat_ships=self.peak_combat_ships,
                    peak_battle_clusters=self.peak_battle_clusters, **scope)


def _peer_list(value):
    if (not isinstance(value, (list, tuple)) or not 2 <= len(value) <= 8 or
            any(not isinstance(tag, str) or not re.fullmatch(r'[A-H]', tag) for tag in value) or
            len(set(value)) != len(value)):
        raise EvidenceError('peers must contain 2..8 unique tags from A through H')
    return list(value)


def resolve_peers(run, peers=None):
    explicit = _peer_list(peers) if peers is not None else None
    manifest = Path(run) / 'launch.json'
    if not manifest.exists():
        return explicit if explicit is not None else ['A', 'B']
    try:
        launch = json.loads(manifest.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise EvidenceError(f'cannot read launch.json: {error}') from error
    if not isinstance(launch, dict):
        raise EvidenceError('launch.json must contain an object')
    declared = _peer_list(launch['peers']) if 'peers' in launch else ['A', 'B']
    if explicit is not None and explicit != declared:
        raise EvidenceError(f'--peers conflicts with launch.json peers: {declared}')
    return declared


def shared_steps(run, peers=None):
    run = Path(run)
    peers = resolve_peers(run, peers)
    names = None
    for tag in peers:
        directory = run / tag
        if not directory.is_dir():
            raise EvidenceError(f'required peer {tag} capture directory is missing')
        current = {path.name for path in directory.glob('step_*.txt') if STEP.fullmatch(path.name)}
        names = current if names is None else names & current
    return names


def _scope_from_launch(run):
    manifest = Path(run) / 'launch.json'
    if not manifest.exists():
        return _metric_scope()
    try:
        launch = json.loads(manifest.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise EvidenceError(f'cannot read launch.json: {error}') from error
    if not isinstance(launch, dict):
        raise EvidenceError('launch.json must contain an object')
    for field in ('player_teams', 'player_alliances'):
        if field in launch and launch[field] is None:
            raise EvidenceError(f'{field} must not be null')
    return _metric_scope(launch.get('player_teams'), launch.get('player_alliances'))


def compare_step(run, name, peers=None):
    run = Path(run)
    peers = resolve_peers(run, peers)
    scope = _scope_from_launch(run)
    match = STEP.fullmatch(name)
    if not match:
        raise EvidenceError('invalid step filename')
    step = int(match[1])
    captures = {}
    for tag in peers:
        try:
            lines = (run / tag / name).read_text(encoding='latin1').splitlines()
        except OSError as error:
            raise EvidenceError(f'{name}: required peer {tag} capture unavailable: {error}') from error
        if (len(lines) < 3 or not re.fullmatch(rf'step {step} synced_rng [0-9a-fA-F]+ table_index \d+', lines[0])
                or lines[-1] != f'END step {step}'):
            raise EvidenceError(f'{name}: peer {tag} incomplete or invalid dump')
        captures[tag] = lines
    reference = [LOCAL.sub('', line) for line in captures[peers[0]]]
    for tag in peers[1:]:
        if [LOCAL.sub('', line) for line in captures[tag]] != reference:
            raise EvidenceError(f'{name}: peer {tag} state diverged from {peers[0]}', 1)
    current = sample('\n'.join(captures[peers[0]]) + '\n', scope['player_teams'], scope['player_alliances'])
    return dict(current, peers=peers, peer_count=len(peers))


def verified_samples(run, peers=None):
    peers = resolve_peers(run, peers)
    for name in sorted(shared_steps(run, peers), key=lambda value: int(STEP.fullmatch(value)[1])):
        yield compare_step(run, name, peers)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeline', type=Path)
    parser.add_argument('--peers', nargs='+', metavar='TAG', help='required peer tags; must match launch.json when present')
    defaults = Criteria()
    for field, value in asdict(defaults).items():
        parser.add_argument('--' + field.replace('_', '-'), type=type(value), default=value)
    args = parser.parse_args(argv)
    outputs = [path.resolve() for path in (args.output, args.timeline) if path]
    captures = [(args.run / tag).resolve() for tag in 'ABCDEFGH']
    if any(folder == path or folder in path.parents for path in outputs for folder in captures):
        parser.error('output paths must be outside peer capture directories')
    if (args.run / 'launch.json').resolve() in outputs:
        parser.error('output paths must preserve launch.json')
    if len(outputs) != len(set(outputs)):
        parser.error('summary and timeline need distinct output paths')
    criteria = Criteria(**{key: getattr(args, key) for key in asdict(defaults)})
    if any(not math.isfinite(value) or value < 0 or (key != 'late_start_seconds' and value == 0)
           for key, value in asdict(criteria).items()):
        parser.error('criteria must be finite and positive; late start may be zero')
    metrics = RunMetrics(criteria)
    timeline = None
    failure = None
    exit_code = 2
    peers = []
    try:
        peers = resolve_peers(args.run, args.peers)
        if args.timeline:
            timeline = args.timeline.open('w', encoding='utf-8')
        for current in verified_samples(args.run, peers):
            metrics.add(current)
            if timeline:
                timeline.write(json.dumps(current, sort_keys=True) + '\n')
        exit_code = 0 if metrics.summary()['passed'] else 2
    except (EvidenceError, OSError, ValueError) as error:
        failure = str(error)
        exit_code = getattr(error, 'exit_code', 2)
    finally:
        if timeline:
            timeline.close()
    result = metrics.summary()
    result.update(peers=peers, peer_count=len(peers))
    if failure:
        result['passed'], result['error'] = False, failure
    rendered = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        try:
            args.output.write_text(rendered, encoding='utf-8')
        except OSError as error:
            result['passed'], result['error'] = False, str(error)
            rendered = json.dumps(result, indent=2, sort_keys=True) + '\n'
            exit_code = 2
    print(rendered, end='')
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
