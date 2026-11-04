"""Bind metrics to the verified runtime Owners and fixed Alliances of UI clients.

Reads identity metadata only. Never reads unit positions or submits game input.
python tools/bind_match_identity.py <run>
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from late_game_metrics import EvidenceError, compare_step, resolve_peers, shared_steps
from late_game_player import Memory
from setup_six_player_lobby import native

BASE = Path(__file__).resolve().parents[1]


def bind(run):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', run):
        raise ValueError('invalid run name')
    root = BASE / 'work' / 'det' / run
    path = root / 'launch.json'
    launch = json.loads(path.read_text(encoding='utf-8-sig'))
    peers = resolve_peers(root)
    if launch.get('human_clients') != len(peers) or launch.get('native_ai') != 0:
        raise EvidenceError('binding requires a declared all-human/no-native-AI cohort')
    if len(launch.get('programs', [])) != len(peers):
        raise EvidenceError('one exact program path per peer is required')
    steps = shared_steps(root, peers)
    if not steps:
        raise EvidenceError('runtime binding requires complete simulation captures')
    first = min(steps, key=lambda name: int(re.search(r'\d+', name)[0]))
    compare_step(root, first, peers)  # Validate every peer before declaring a scope.
    identities, reference = {}, None
    for tag, executable in zip(peers, launch['programs']):
        pid = int((root / f'pid_{tag}.txt').read_text())
        memory = Memory(pid, Path(executable))
        try:
            state = native(memory)
        finally:
            memory.close()
        if state['engine_mode'] != 2:
            raise EvidenceError(f'{tag}: runtime world mode is required')
        if reference is not None and state['players'] != reference:
            raise EvidenceError(f'{tag}: runtime Owner/Alliance rows disagree')
        reference = state['players']
        row = state['players'][state['local_slot']]
        owner, alliance = row['player_team'], row['alliance_index']
        if not 1 <= owner <= 8 or not 0 <= alliance <= 7:
            raise EvidenceError(f'{tag}: invalid runtime Owner/Alliance')
        identities[tag] = dict(owner=owner, alliance=alliance, local_slot=state['local_slot'],
                               engine_mode=state['engine_mode'], pid=pid, executable=executable)
    owners = [entry['owner'] for entry in identities.values()]
    if len(set(owners)) != len(peers):
        raise EvidenceError('runtime peer Owners must be unique')
    active = {row['player_team'] for row in reference if row['player_team']}
    if active != set(owners):
        raise EvidenceError('runtime contains undeclared active player Owners')
    record = dict(utc=datetime.now(timezone.utc).isoformat(), peers=identities,
                  native_players=reference,
                  scope='fixed Alliance test, runtime Owner rows; no gameplay-state control',
                  first_verified_step=first)
    backup = root / 'launch.before_player_binding.json'
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    (root / 'runtime_players.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    launch['player_teams'] = sorted(owners)
    launch['player_alliances'] = {str(entry['owner']): entry['alliance'] for entry in identities.values()}
    launch['player_binding'] = 'runtime_players.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(launch, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return record


if __name__ == '__main__':
    print(json.dumps(bind(sys.argv[1]), indent=2))
