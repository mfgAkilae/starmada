"""shot.py <tag> <png>: screenshot test instance <tag>, list its visible windows."""
import sys
sys.path.insert(0, r'E:\dev\starmada\tools')
import probe
pid = int(open(rf'E:\dev\starmada\work\pid_{sys.argv[1]}.txt').read().strip())
for w in probe.windows(pid):
    if w['visible']:
        print(w['cls'], repr(w['title']), w['rect'])
probe.shot(pid, sys.argv[2])
