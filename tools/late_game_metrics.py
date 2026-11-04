"""Compare complete peer dumps and require measured Late-Game load.

python tools/late_game_metrics.py work/det/<run> --output summary.json --timeline samples.jsonl
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


def sample(text):
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
    alive = {key: obj for key, obj in objects.items() if obj['team'] and obj['health'] > 0}
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
                weapon_instances=len(re.findall(r'^Weapon ', text, re.M)))


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

    def add(self, current):
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
        self.previous = current

    def summary(self):
        criteria = self.criteria
        conditions = dict(duration=self.observed_seconds >= criteria.min_simulation_seconds,
                          sustained_fleet=self.longest_fleet_seconds >= criteria.min_fleet_seconds,
                          parallel_combat=self.parallel_combat_seconds >= criteria.min_parallel_seconds)
        return dict(passed=self.samples >= 2 and all(conditions.values()), conditions=conditions,
                    criteria=asdict(criteria), pairs=self.samples,
                    first_simulation_seconds=self.first_seconds,
                    last_simulation_seconds=self.previous['simulation_seconds'] if self.previous else None,
                    last_step=self.previous['step'] if self.previous else None,
                    observed_seconds=self.observed_seconds, gaps_over_maximum=self.gaps,
                    longest_fleet_seconds=self.longest_fleet_seconds,
                    parallel_combat_seconds=self.parallel_combat_seconds,
                    peak_combat_ships=self.peak_combat_ships,
                    peak_battle_clusters=self.peak_battle_clusters)


def verified_samples(run):
    names = {p.name for p in (run / 'A').glob('step_*.txt')} & {p.name for p in (run / 'B').glob('step_*.txt')}
    names = [name for name in names if STEP.fullmatch(name)]
    for name in sorted(names, key=lambda value: int(STEP.fullmatch(value)[1])):
        step = int(STEP.fullmatch(name)[1])
        texts = [(run / tag / name).read_text(encoding='latin1') for tag in ('A', 'B')]
        normalized = [[LOCAL.sub('', line) for line in text.splitlines()] for text in texts]
        for lines in normalized:
            if (len(lines) < 3 or not re.fullmatch(rf'step {step} synced_rng [0-9a-fA-F]+ table_index \d+', lines[0])
                    or lines[-1] != f'END step {step}'):
                raise EvidenceError(f'{name}: incomplete or invalid dump')
        if normalized[0] != normalized[1]:
            raise EvidenceError(f'{name}: peer state diverged', 1)
        yield sample('\n'.join(texts[0].splitlines()) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeline', type=Path)
    defaults = Criteria()
    for field, value in asdict(defaults).items():
        parser.add_argument('--' + field.replace('_', '-'), type=type(value), default=value)
    args = parser.parse_args(argv)
    outputs = [path.resolve() for path in (args.output, args.timeline) if path]
    captures = [(args.run / tag).resolve() for tag in ('A', 'B')]
    if any(folder == path or folder in path.parents for path in outputs for folder in captures):
        parser.error('output paths must be outside peer capture directories')
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
    try:
        if args.timeline:
            timeline = args.timeline.open('w', encoding='utf-8')
        for current in verified_samples(args.run):
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
