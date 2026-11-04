#!/usr/bin/env bash
# One watcher for b25, loop on Linux, exits on the first event. Run through one long ssh connection.
# Events: feeder gone with the manifest finished, a new FAILED, a STOP file, a READY row unclaimed for 40 min, or a row finished every 3 rows as a heartbeat.
cd ~/mobo_toy_v2 || exit 1
Q=queue
PID=$(cat logs/db_feed_b25.pid 2>/dev/null)
seen_done=${1:-0}
while :; do
  n_done=0; n_failed=0; n_ready=0; n_claimed=0; oldest=""
  for j in $Q/db_al_opt1_*; do
    [ -d "$j" ] || continue
    if [ -f "$j/DONE" ]; then n_done=$((n_done+1));
    elif [ -f "$j/FAILED.json" ]; then n_failed=$((n_failed+1));
    elif [ -f "$j/CLAIMED" ] || [ -f "$j/SOLVED" ]; then n_claimed=$((n_claimed+1));
    elif [ -f "$j/READY" ]; then n_ready=$((n_ready+1)); a=$(( $(date +%s) - $(stat -c %Y "$j/READY") )); [ "$a" -gt 2400 ] && oldest="$j $a s"; fi
  done
  now="$(date -u +%H:%M) done $n_done failed $n_failed ready $n_ready claimed $n_claimed"
  if [ "$n_failed" -gt 0 ]; then echo "EVENT failed: $now"; ls -d $Q/db_al_opt1_*/FAILED.json | head -n 3; exit 0; fi
  if [ -n "$oldest" ]; then echo "EVENT ready not claimed: $oldest; $now"; exit 0; fi
  if ls STOP_DB_FEED* > /dev/null 2>&1; then echo "EVENT stop file: $(ls STOP_DB_FEED*); $now"; exit 0; fi
  if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then echo "EVENT feeder gone: $now"; tail -n 4 logs/db_feed_b25.out | cut -c1-200; exit 0; fi
  if [ "$n_done" -ge 8 ]; then echo "EVENT all done: $now"; exit 0; fi
  if [ "$n_done" -ge $((seen_done+3)) ]; then echo "EVENT progress: $now"; exit 0; fi
  sleep 60
done
