#!/usr/bin/env bash
# Live dry runs of b29, b30, b31 on the real queue: reads only; writes the logs under logs/.   bash dry_urows.sh b29 b30 b31
cd ~/mobo_toy_v2/code || exit 1
echo "stage_db md5 $(tr -d '\r' < v2/stage_db.py | md5sum | cut -c1-8); $(head -c 40 VERSION 2>/dev/null)"
for b in "$@"; do
  OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 900 nice -n 19 taskset -c 4-11 ../run.sh v2/stage_db.py dry-run "$b" > ../logs/db_dry_$b.txt 2>&1; rc=$?
  echo "== $b dry-run rc=$rc"
  B=$b python3 - <<'EOF'
import json, os
b = os.environ['B']
t = open(os.path.expanduser(f'~/mobo_toy_v2/logs/db_dry_{b}.txt')).read()
d = json.loads(t[t.index('DRY-RUN-JSON') + len('DRY-RUN-JSON'):])
print('problems', d.get('problems'), 'warnings', d.get('warnings'), 'n_new', d.get('n_new'))
jobs = d['jobs']
print('jobs', len(jobs), 'dedup', sorted({r.get('dedup') for r in jobs}), 'layers', sorted({r.get('layer') for r in jobs}))
for r in jobs[:3] + jobs[-2:]:
    print(' ', r.get('key'), r.get('id') or r.get('expected_id'), r.get('dedup'))
EOF
done
ls ~/mobo_toy_v2/logs/db_feed_b29.pid ~/mobo_toy_v2/logs/db_feed_b30.pid ~/mobo_toy_v2/logs/db_feed_b31.pid 2>/dev/null; ls ~/mobo_toy_v2/STOP_DB_FEED* 2>/dev/null; df -h / | tail -1
