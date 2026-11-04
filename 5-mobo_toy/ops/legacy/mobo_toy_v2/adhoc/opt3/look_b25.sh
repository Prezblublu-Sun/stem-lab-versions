#!/usr/bin/env bash
# Read only: state of the b25 rows, the feeder and the first results.
cd ~/mobo_toy_v2 || exit 1
date -u +%H:%M
for j in queue/db_al_opt1_*; do
  s=NEW; [ -f $j/READY ] && s=READY; [ -f $j/CLAIMED ] && s=CLAIMED; [ -f $j/SOLVED ] && s=SOLVED; [ -f $j/DONE ] && s=DONE; [ -f $j/FAILED.json ] && s=FAILED
  echo "$s ${j#queue/}"
done
tail -n 3 logs/db_feed_b25.out | cut -c1-220
pgrep -f '^.*/.venv/bin/python v2/stage_db.py feed' | wc -l
pgrep -fc '[w]atch_b25'
for j in queue/db_al_opt1_*; do
  [ -f $j/FAILED.json ] && { echo "--- ${j#queue/}"; cut -c1-600 $j/FAILED.json; }
done
python3 - <<'EOF'
import glob, json, os
for d in sorted(glob.glob(os.path.expanduser("~/mobo_toy_v2/queue/db_al_opt1_*"))):
    p = d + "/result.json"
    if os.path.exists(p) and os.path.exists(d + "/DONE"):
        r = json.load(open(p))
        print(os.path.basename(d), "f1_p95", round(r.get("f1_p95_um", -1), 2), "contact", round(r.get("contact_area_load2_mm2", -1)), "open", round(r.get("open_frac_load2", -1), 3))
EOF
