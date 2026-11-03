#!/bin/bash
# watch_mp.sh <run> <minutes>: compare the two nodes' dumps every 60 s until a difference
# appears, a game process ends, or the time is up.
run=$1; mins=${2:-15}
PY=/e/dev/starmada/.venv/Scripts/python
for i in $(seq 1 $mins); do
  sleep 60
  out=$($PY /e/dev/starmada/tools/cmpdumps.py /e/dev/starmada/work/det/$run/A /e/dev/starmada/work/det/$run/B --state /e/dev/starmada/work/det/$run.equal 2>&1)
  last=$(echo "$out" | tail -1)
  n=$(ls /e/dev/starmada/work/det/$run/A | wc -l)
  alive=$(tasklist //FI "IMAGENAME eq Armada.exe" //NH 2>/dev/null | grep -c Armada.exe)
  echo "[$i min] dumps=$n procs=$alive :: $last"
  if ! echo "$last" | grep -q 'first difference: None'; then echo "$out" | head -40; break; fi
  if [ "$alive" -lt 2 ]; then echo "a game process ended"; break; fi
done
