#!/usr/bin/env bash
# Live dry runs of b25 and two regressions. Writes only the dry-run logs.
cd ~/mobo_toy_v2/code || exit 1
for b in b25 b23 b22; do
  OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 500 nice -n 19 taskset -c 4-7 ../run.sh v2/stage_db.py dry-run $b > ../logs/db_dry_$b.txt 2>&1
  echo "$b live dry-run rc=$?"
done
grep -E '^per layer|^dedup:|^PROBLEMS|^jobs \(' ../logs/db_dry_b25.txt | cut -c1-175 | head -n 6
grep -E '^  OPT1_' ../logs/db_dry_b25.txt | cut -c1-120 | head -n 10
python3 - <<'EOF'
import json, os
t = open(os.path.expanduser('~/mobo_toy_v2/logs/db_dry_b25.txt')).read()
d = json.loads(t[t.index('DRY-RUN-JSON') + len('DRY-RUN-JSON'):])
print('problems', d.get('problems'), 'warnings', d.get('warnings'), 'n_new', d.get('n_new'), 'code_hash', d.get('code_hash'), 'keys', sorted(d.keys())[:14])
for k in ('jobs', 'rows'):
    if d.get(k):
        print(k, json.dumps(d[k][:1])[:300])
EOF
df -BG --output=avail / | tail -1; ls ~/mobo_toy_v2/STOP_DB_FEED* 2>/dev/null; cat ~/mobo_toy_v2/code/VERSION; pgrep -f '^.*/.venv/bin/python v2/stage_db.py feed' | wc -l
