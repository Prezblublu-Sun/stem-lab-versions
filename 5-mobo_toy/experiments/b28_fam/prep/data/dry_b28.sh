#!/usr/bin/env bash
# Live dry run of b28 on the real queue: reads only; writes the log under logs/.
cd ~/mobo_toy_v2/code || exit 1
echo "stage_db md5 $(tr -d '\r' < v2/stage_db.py | md5sum | cut -c1-8); $(cat VERSION 2>/dev/null | head -c 120)"
OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 600 nice -n 19 taskset -c 4-11 ../run.sh v2/stage_db.py dry-run b28 > ../logs/db_dry_b28.txt 2>&1; rc=$?
echo "dry-run rc=$rc"
python3 - <<'EOF'
import json, os
t = open(os.path.expanduser('~/mobo_toy_v2/logs/db_dry_b28.txt')).read()
d = json.loads(t[t.index('DRY-RUN-JSON') + len('DRY-RUN-JSON'):])
print('problems', d.get('problems'), 'warnings', d.get('warnings'), 'n_new', d.get('n_new'))
for r in d['jobs']:
    print(r.get('key'), r.get('id') or r.get('expected_id'), r.get('dedup'), r.get('model_set'), r.get('layer'))
EOF
ls ~/mobo_toy_v2/logs/db_feed_b28.pid 2>/dev/null; ls ~/mobo_toy_v2/STOP_DB_FEED* 2>/dev/null; df -h / | tail -1
