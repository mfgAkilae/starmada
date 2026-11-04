"""Summarize the actual game objects in a test-bed state dump (no game control).

python tools/gameplay_state.py <dump.txt> [team]
"""
import json
from pathlib import Path
import re
import sys


def objects(path):
    result = []
    for block in Path(path).read_text(encoding='latin1').split('GAMEOBJECT ')[1:]:
        lines = block.splitlines()
        header = lines[0].split(maxsplit=2)
        team = re.search(r'^  team (\d+)', block, re.M)
        pos = re.search(r'^  pos \(([^)]+)\)', block, re.M)
        health = re.search(r'curhealth (\S+) maxhealth (\S+)', block)
        if len(header) != 3 or not team:
            continue
        obj = dict(id=int(header[0]), kind=header[1], name=header[2], team=int(team[1]))
        if pos:
            obj['pos'] = [float(x) for x in pos[1].split(',')]
        if health:
            obj['health'], obj['max_health'] = map(float, health.groups())
        result.append(obj)
    return result


if __name__ == '__main__':
    result = objects(sys.argv[1])
    if len(sys.argv) > 2:
        result = [o for o in result if o['team'] == int(sys.argv[2])]
    print(json.dumps(result, indent=2))
