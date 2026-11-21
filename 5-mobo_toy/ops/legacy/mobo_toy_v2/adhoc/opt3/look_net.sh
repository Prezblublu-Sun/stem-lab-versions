#!/usr/bin/env bash
date -u +%H:%M:%S; uptime | cut -c1-70
echo "watchers: $(pgrep -fc '[w]atch_b25')"; pgrep -af '[w]atch_b25' | cut -c1-90
echo "sshd connections from here:"; who | tail -n 4 | cut -c1-60
last -n 6 -F 2>/dev/null | cut -c1-100 | head -n 6
cd ~/mobo_toy_v2/queue; d=0; for j in db_al_opt1_*; do [ -f "$j/DONE" ] && d=$((d+1)); done; echo "done $d of 8"; ls -d db_al_opt1_*/FAILED.json 2>/dev/null
tail -n 2 ~/mobo_toy_v2/logs/db_feed_b25.out | cut -c1-200
