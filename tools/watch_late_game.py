"""Observe complete peer dumps and the Late-Game load gate; never play the game.

python tools/watch_late_game.py <run> [--minutes 190]
Write observer.stop in the run folder after closing the test. Stop succeeds only
when the measured acceptance conditions passed. Failures preserve all evidence.
"""
import argparse
import json
from pathlib import Path
import re
import time

from cmpdumps import STEP
from late_game_metrics import EvidenceError, RunMetrics
from late_game_player import atomic_json, compare_pair, timestamp

BASE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--minutes', type=float, default=190)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run) or not 0 < args.minutes <= 1440:
        parser.error('valid run and wall limit required')
    run = BASE / 'work' / 'det' / args.run
    if not (run / 'A').is_dir() or not (run / 'B').is_dir():
        parser.error('both capture directories are required')
    metrics, seen = RunMetrics(), set()
    started = progress = time.monotonic()
    printed = -60
    result, error, exit_code = None, None, 2
    with (run / 'observer_timeline.jsonl').open('w', encoding='utf-8', buffering=1) as timeline:
        try:
            while time.monotonic() - started < args.minutes * 60:
                shared = {p.name for p in (run / 'A').glob('step_*.txt')} & {
                    p.name for p in (run / 'B').glob('step_*.txt')}
                for name in sorted((name for name in shared - seen if STEP.fullmatch(name)),
                                   key=lambda name: int(STEP.fullmatch(name)[1])):
                    current = compare_pair(run, name)
                    metrics.add(current)
                    seen.add(name)
                    progress = time.monotonic()
                    timeline.write(json.dumps(dict(wall_time=timestamp(), **current)) + '\n')
                    result = dict(state='observing', wall_time=timestamp(), metrics=metrics.summary(), latest=current)
                    atomic_json(run / 'observer_status.json', result)
                    if current['simulation_seconds'] - printed >= 60:
                        print(json.dumps(result), flush=True)
                        printed = current['simulation_seconds']
                if (run / 'observer.stop').exists():
                    exit_code = 0 if metrics.summary()['passed'] else 2
                    break
                if time.monotonic() - progress > 180:
                    raise EvidenceError('no new verified peer capture for 180 wall seconds')
                time.sleep(.5)
            else:
                error = 'observer wall limit reached'
        except (EvidenceError, OSError, ValueError) as failure:
            error, exit_code = str(failure), getattr(failure, 'exit_code', 2)
    result = dict(state='complete' if exit_code == 0 else 'incomplete', wall_time=timestamp(),
                  metrics=metrics.summary(), error=error)
    atomic_json(run / 'observer_status.json', result)
    print(json.dumps(result), flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
