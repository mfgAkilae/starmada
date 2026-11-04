"""Create two independent, patched gameplay-test installs from verified GOG files.

python tools/prepare_play_test.py <run> [--source work/gog_repaired]
"""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
from pathlib import Path
import shutil
import sys

import gog_unpack

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'release'))
import armada_fix


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run')
    p.add_argument('--source', type=Path, default=BASE / 'work' / 'gog_repaired')
    p.add_argument('--manifest', type=Path, default=BASE / 'work' / 'gog' / 'install_script.iss')
    args = p.parse_args()
    if not args.run.replace('_', '').replace('-', '').isalnum():
        p.error('run must contain only letters, digits, hyphens and underscores')
    for entry in gog_unpack.manifest(args.manifest.read_text(encoding='utf-8-sig')):
        path = args.source / entry['name'].replace('\\', '/')
        if hashlib.md5(path.read_bytes()).hexdigest() != entry['md5']:
            raise SystemExit('source does not match GOG manifest: ' + entry['name'])
    target = BASE / 'work' / 'play_clients' / args.run
    if target.exists():
        raise SystemExit('preserve the existing fixture; choose a new run name')
    for tag in ('A', 'B'):
        game = target / tag
        shutil.copytree(args.source, game)
        with redirect_stdout(io.StringIO()):
            armada_fix.apply(str(game), ['--window', 'native'])
        print(tag, 'prepared from verified GOG files;', armada_fix.sha256((game / 'Armada.exe').read_bytes()))


if __name__ == '__main__':
    main()
