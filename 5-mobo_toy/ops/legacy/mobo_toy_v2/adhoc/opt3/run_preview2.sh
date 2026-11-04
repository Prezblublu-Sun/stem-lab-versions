#!/usr/bin/env bash
date -u +%H:%M; echo "watchers: $(pgrep -fc '[w]atch_b25')"
cd ~/mobo_toy_v2/queue; d=0; for j in db_al_opt1_*; do [ -f "$j/DONE" ] && d=$((d+1)); done; echo "done $d of 8"; ls -d db_al_opt1_*/FAILED.json 2>/dev/null
cd ~/mobo_toy_v2/code/v2 && OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 280 taskset -c 4-7 nice -n 19 ../../run.sh ../../adhoc/opt3/preview2_b25.py 2>&1 | grep -v 'bench skipped' | cut -c1-230
