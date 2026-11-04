"""Create independent, patched gameplay-test installs from verified GOG files.

python tools/prepare_play_test.py <run> [--players 2..8] [--source work/gog_repaired]
"""
import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys

import gog_unpack

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'release'))
import armada_fix


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run')
    p.add_argument('--players', type=int, choices=range(2, 9), default=2)
    p.add_argument('--source', type=Path, default=BASE / 'work' / 'gog_repaired')
    p.add_argument('--manifest', type=Path, default=BASE / 'work' / 'gog' / 'install_script.iss')
    args = p.parse_args(argv)
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.run) or
            args.run.upper() in reserved):
        p.error('run must be a safe ASCII name containing letters, digits, hyphens or underscores')
    target = BASE / 'work' / 'play_clients' / args.run
    if os.path.lexists(target):
        p.error('preserve the existing fixture; choose a new run name')
    target = target.resolve()
    if BASE.resolve() not in target.parents:
        p.error('fixture path must remain inside the workspace')
    source, manifest = args.source.resolve(), args.manifest.resolve()
    if source == target or source in target.parents:
        p.error('fixture path must not be inside the source directory')
    manifest_data = manifest.read_bytes()
    for entry in gog_unpack.manifest(manifest_data.decode('utf-8-sig')):
        path = (source / entry['name'].replace('\\', '/')).resolve()
        if source not in path.parents:
            p.error('GOG manifest path escapes the source directory: ' + entry['name'])
        if hashlib.md5(path.read_bytes()).hexdigest() != entry['md5']:
            raise SystemExit('source does not match GOG manifest: ' + entry['name'])
    tags = list('ABCDEFGH'[:args.players])
    clients = {}
    target.mkdir(parents=True)
    for tag in tags:
        game = target / tag
        shutil.copytree(source, game)
        with redirect_stdout(io.StringIO()):
            armada_fix.apply(str(game), ['--window', 'native'])
        hashes = {name: armada_fix.sha256((game / name).read_bytes())
                  for name in ('Armada.exe', 'Strlkup.dll', 'ddraw.dll', 'dxcfg.ini', 'label.map')}
        if clients and hashes != clients[tags[0]]:
            raise SystemExit('prepared clients differ; fixture preserved')
        clients[tag] = hashes
        print(tag, 'prepared from verified GOG files;', hashes['Armada.exe'])
    metadata = dict(schema=1, fixture=args.run, tags=tags, source=str(source),
                    manifest=dict(path=str(manifest), sha256=armada_fix.sha256(manifest_data)),
                    clients=clients)
    with (target / 'fixture.json').open('x', encoding='utf-8', newline='\n') as output:
        json.dump(metadata, output, indent=2, sort_keys=True)
        output.write('\n')


if __name__ == '__main__':
    main()
