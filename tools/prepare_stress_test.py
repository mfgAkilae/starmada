"""Prepare an optional high-resource multiplayer stress fixture from verified GOG files.

python tools/prepare_stress_test.py <fixture> [--dilithium 1000000]
Select the fifth starting-Dilithium option in the host lobby to activate it.
Only label.map's sd_value_5 differs from the ordinary patched fixture.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


BASE = Path(__file__).resolve().parents[1]
KEY = re.compile(rb'(?m)^[ \t]*\+[ \t]+sd_value_5\b')
VALUE = re.compile(rb'(?m)^[ \t]*\+[ \t]+sd_value_5[ \t]+\{([^}\r\n]*)\}[ \t]*\r?$')


def rewrite_label(data, dilithium):
    if not 10000 <= dilithium <= 10000000:
        raise ValueError('dilithium must be between 10000 and 10000000')
    matches = list(VALUE.finditer(data))
    if len(KEY.findall(data)) != 1 or len(matches) != 1 or matches[0][1] != b'10000':
        raise ValueError('trusted label.map must contain exactly one stock sd_value_5 {10000}')
    start, end = matches[0].span(1)
    return data[:start] + str(dilithium).encode('ascii') + data[end:]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture')
    parser.add_argument('--dilithium', type=int, default=1000000)
    args = parser.parse_args(argv)
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.fixture) or
            args.fixture.upper() in reserved):
        parser.error('fixture must be a safe ASCII name containing letters, digits, hyphens or underscores')
    if not 10000 <= args.dilithium <= 10000000:
        parser.error('dilithium must be between 10000 and 10000000')
    target = BASE / 'work' / 'play_clients' / args.fixture
    if target.exists() or target.is_symlink():
        parser.error('preserve the existing fixture; choose a new fixture name')
    if BASE.resolve() not in target.resolve().parents:
        parser.error('fixture path must remain inside the workspace')
    source = BASE / 'work' / 'gog_repaired' / 'label.map'
    original = source.read_bytes()
    modified = rewrite_label(original, args.dilithium)
    subprocess.run([sys.executable, '-B', str(BASE / 'tools' / 'prepare_play_test.py'), args.fixture],
                   cwd=BASE, check=True)
    clients = {tag: target / tag for tag in ('A', 'B')}
    for tag, game in clients.items():
        if (game / 'label.map').read_bytes() != original:
            raise RuntimeError(f'{tag}: copied label.map does not match the preflight source; fixture preserved')
        if (game / 'label.map.stress-backup').exists():
            raise RuntimeError(f'{tag}: unexpected existing label.map backup; fixture preserved')
    executable_hashes = {tag: sha256((game / 'Armada.exe').read_bytes()) for tag, game in clients.items()}
    records = {}
    for tag, game in clients.items():
        backup = game / 'label.map.stress-backup'
        with backup.open('xb') as output:
            output.write(original)
        (game / 'label.map').write_bytes(modified)
        actual = (game / 'label.map').read_bytes()
        if actual != modified or sha256((game / 'Armada.exe').read_bytes()) != executable_hashes[tag]:
            raise RuntimeError(f'{tag}: stress fixture verification failed; backup and fixture preserved')
        records[tag] = dict(label_map_before_sha256=sha256(original), label_map_after_sha256=sha256(actual),
                            label_map_backup=f'{tag}/label.map.stress-backup',
                            production_exe_sha256=executable_hashes[tag])
    if (clients['A'] / 'label.map').read_bytes() != (clients['B'] / 'label.map').read_bytes():
        raise RuntimeError('peer label.map files differ; fixture preserved')
    metadata = dict(schema=1, fixture=args.fixture, created_utc=datetime.now(timezone.utc).isoformat(),
                    source='work/gog_repaired', preparation='tools/prepare_play_test.py',
                    stress_delta=dict(file='label.map', key='sd_value_5', stock_value=10000,
                                      configured_value=args.dilithium,
                                      activation='Select the fifth starting-Dilithium option in the host lobby'),
                    clients=records)
    with (target / 'stress_fixture.json').open('x', encoding='utf-8', newline='\n') as output:
        json.dump(metadata, output, indent=2, sort_keys=True)
        output.write('\n')
    print(f'Prepared optional stress fixture: {target}')
    print(f'Lobby starting-Dilithium option 5: {args.dilithium}; ship stats and engine unchanged by the stress delta.')
    print(f'Evidence: {target / "stress_fixture.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
