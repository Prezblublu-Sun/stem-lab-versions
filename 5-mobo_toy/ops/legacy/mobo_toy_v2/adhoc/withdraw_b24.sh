#!/usr/bin/env bash
# The user dropped b24. Stop its feeder and the watcher, and move its unclaimed rows out of the queue. Nothing is deleted, the DONE row stays.
cd ~/mobo_toy_v2 || exit 1
FP=$(cat logs/db_feed_b24.pid)
CMD=$(ps -o cmd= -p "$FP")
echo "feeder $FP: ${CMD:0:80}"
case "$CMD" in
  *"stage_db.py feed b24"*) kill "$FP"; sleep 4; if ps -p "$FP" > /dev/null; then echo "feeder STILL ALIVE"; exit 2; else echo "feeder stopped"; fi ;;
  *) echo "pid is not the b24 feeder, nothing killed" ;;
esac
echo "$(date -u +%FT%TZ) user dropped b24, feeder stopped by hand" >> logs/db_feed_b24.out
mv logs/db_feed_b24.pid logs/db_feed_b24.pid.stopped

W=~/mobo_toy_v2/queue_withdrawn/b24_2026-11-04
mkdir -p "$W"
cd queue || exit 1
for j in db_cd_p13_a105_91e458e3_ow_m1_e+1.5_TA10_42039793 db_cd_p13_a105_91e458e3_m1_TB10_9667f89f db_cd_p13_a105_91e458e3_m1_pf_de-1_413b4378 db_cd_p13_a105_91e458e3_m1_pf_de+1_7439305e; do
  if [ -f "$j/READY" ] && [ ! -f "$j/CLAIMED" ] && [ ! -f "$j/SOLVED" ] && [ ! -f "$j/DONE" ]; then mv "$j" "$W/" && echo "withdrawn $j"; else echo "LEFT $j: not plain READY"; ls "$j" | head -n 5; fi
done
echo "Rows of b24 (TQ-1, PF-1 smoke) moved out of the queue on $(date -u +%FT%TZ): the user dropped b24. Prepared but never solved. Moving a folder back into queue/ restores it." > "$W/README.txt"

echo "--- queue, non-final rows of every stage"
n=0; for j in *; do
  [ -d "$j" ] || continue
  [ -f "$j/DONE" ] || [ -f "$j/FAILED.json" ] || { n=$((n+1)); s=NEW; [ -f "$j/READY" ] && s=READY; [ -f "$j/CLAIMED" ] && s=CLAIMED; [ -f "$j/SOLVED" ] && s=SOLVED; echo "$s $j"; }
done | head -n 20
echo "--- b24 rows still in the queue"
ls -d *_TA10_* *_TB10_* *_pf_de* 2>/dev/null

echo "--- watcher and feeders"
for p in $(pgrep -f 'b23end'); do [ "$p" = "$$" ] && continue; c=$(ps -o cmd= -p "$p"); case "$c" in *withdraw_b24*) ;; *) echo "kill watcher $p: ${c:0:70}"; kill "$p" ;; esac; done
sleep 1
ps -u "$USER" -o pid,etime,cmd | grep -E 'stage_db|watch|stage_v2a|sleep' | grep -v grep | cut -c1-100
