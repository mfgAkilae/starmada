"""Compare node dumps; exit 1 on divergence, 2 on insufficient evidence.

Only per-node presentation fields (isVisible/seen, local_rng) are ignored.
--state writes the verified filenames for existing watchers; it never trusts an
old filename cache. --min-step/--min-pairs make final run acceptance explicit.
"""
import argparse
from itertools import zip_longest
from pathlib import Path
import re
import sys

LOCAL = re.compile(r'isVisible \S+ seen \S+| local_rng \S+')
STEP = re.compile(r'step_(\d+)\.txt$')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('a', type=Path)
    p.add_argument('b', type=Path)
    p.add_argument('--state', type=Path)
    p.add_argument('--min-step', type=int, default=0)
    p.add_argument('--min-pairs', type=int, default=1)
    p.add_argument('--legacy', action='store_true', help='accept old dumps without an END marker')
    args = p.parse_args(argv)
    steps = sorted({s.name for s in args.a.glob('step_*.txt')} &
                   {s.name for s in args.b.glob('step_*.txt')})
    equal, first, last_step = [], None, 0
    for s in steps:
        match = STEP.fullmatch(s)
        if not match:
            continue
        la = [LOCAL.sub('', l) for l in (args.a / s).read_text(encoding='latin1').splitlines()]
        lb = [LOCAL.sub('', l) for l in (args.b / s).read_text(encoding='latin1').splitlines()]
        expected = int(match[1])
        # A nonempty header and content prevent an empty/truncated file from passing.
        if any(len(lines) < 3 or not lines[0].startswith(f'step {expected} synced_rng ')
               for lines in (la, lb)):
            print(f'{s}: incomplete or invalid dump')
            return 2
        if not args.legacy and any(lines[-1] != f'END step {expected}' for lines in (la, lb)):
            print(f'{s}: missing END marker (old captures require --legacy)')
            return 2
        if la == lb:
            equal.append(s)
            last_step = max(last_step, expected)
            continue
        first = s
        diff = [(i, x, y) for i, (x, y) in enumerate(zip_longest(la, lb, fillvalue='<missing>')) if x != y]
        print(f'{s}: {len(la)} vs {len(lb)} lines, {len(diff)} differ')
        for i, x, y in diff[:12]:
            print(f'   line {i + 1}\n     A: {x[:110]}\n     B: {y[:110]}')
        break
    if args.state:
        args.state.write_text(''.join(s + '\n' for s in equal))
    print('compared', len(equal) + int(first is not None), 'steps; first difference:', first)
    if first:
        return 1
    if len(equal) < args.min_pairs or not equal or last_step < args.min_step:
        print(f'insufficient evidence: {len(equal)} pairs, last step {last_step}; '
              f'require {max(1, args.min_pairs)} pairs and step {args.min_step}')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
