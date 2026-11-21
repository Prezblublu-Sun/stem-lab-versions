#!/usr/bin/env bash
# One watcher per project (AGENTS.md red line 4). The loop runs on Linux inside ONE long ssh connection and exits on the first event.
# Registry: ~/mobo_toy_v2/logs/watcher.lock holds "pid session started batch". A second watcher refuses to start while that pid is alive,
# so two sessions can no longer kill each other's loops (11-04 incident: the forked session and its parent each restarted the watcher).
#
#   ssh ... 'bash ~/mobo_toy_v2/ops/watch_remote.sh <batch> <session-id> [seen_done]'
#
# Events (prints one EVENT line and exits 0): a new FAILED row; a READY row unclaimed for 40 min; a STOP_DB_FEED* file; the feeder gone;
# all rows DONE; progress every 3 rows beyond seen_done. The lock is removed on exit, also when the ssh connection drops (HUP).
# Exit 3 = refused, another watcher is alive. Exit 4 = no manifest for the batch.
B=$1; SESSION=${2:-unknown}; SEEN=${3:-0}
[ -n "$B" ] || { echo "usage: watch_remote.sh <batch> <session> [seen_done]"; exit 2; }
cd ~/mobo_toy_v2 || exit 1
mkdir -p logs
LOCK=logs/watcher.lock
if [ -f "$LOCK" ]; then
  read -r opid osess ostart obatch < "$LOCK"
  if [ -n "$opid" ] && [ "$opid" != "$$" ] && kill -0 "$opid" 2>/dev/null; then
    echo "REFUSED: watcher $opid of session $osess for $obatch is alive since $ostart"; exit 3
  fi
fi
echo "$$ $SESSION $(date -u +%FT%TZ) $B" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
trap 'rm -f "$LOCK"; exit 0' HUP TERM INT
MAN=results/db_manifest_$B.json
[ -f "$MAN" ] || { echo "no manifest $MAN"; exit 4; }
JOBS=$(python3 - "$MAN" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
rows = m.get("rows", m)
print(" ".join(sorted({r.get("id") or r.get("expected_id") for r in rows.values() if isinstance(r, dict) and (r.get("id") or r.get("expected_id"))})))
EOF
)
N=$(echo "$JOBS" | wc -w)
PID=$(cat "logs/db_feed_$B.pid" 2>/dev/null)
echo "watching $B: $N rows, feeder pid ${PID:-none}, session $SESSION, lock pid $$"
while :; do
  n_done=0; n_failed=0; n_ready=0; n_claimed=0; oldest=""
  for j in $JOBS; do
    d=queue/$j
    [ -d "$d" ] || continue
    if [ -f "$d/DONE" ]; then n_done=$((n_done+1))
    elif [ -f "$d/FAILED.json" ]; then n_failed=$((n_failed+1))
    elif [ -f "$d/CLAIMED" ] || [ -f "$d/SOLVED" ]; then n_claimed=$((n_claimed+1))
    elif [ -f "$d/READY" ]; then n_ready=$((n_ready+1)); a=$(( $(date +%s) - $(stat -c %Y "$d/READY") )); [ "$a" -gt 2400 ] && oldest="$j ${a}s"
    fi
  done
  now="$(date -u +%H:%M) done $n_done failed $n_failed ready $n_ready claimed $n_claimed of $N"
  if [ "$n_failed" -gt 0 ]; then echo "EVENT failed: $now"; for j in $JOBS; do [ -f "queue/$j/FAILED.json" ] && echo "  $j"; done; exit 0; fi
  if [ -n "$oldest" ]; then echo "EVENT ready not claimed: $oldest; $now"; exit 0; fi
  if ls STOP_DB_FEED* > /dev/null 2>&1; then echo "EVENT stop file: $(ls STOP_DB_FEED* | tr '\n' ' '); $now"; exit 0; fi
  if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then echo "EVENT feeder gone: $now"; tail -n 3 "logs/db_feed_$B.out" 2>/dev/null | cut -c1-200; exit 0; fi
  if [ "$n_done" -ge "$N" ]; then echo "EVENT all done: $now"; exit 0; fi
  if [ "$n_done" -ge $((SEEN+3)) ]; then echo "EVENT progress: $now"; exit 0; fi
  sleep 60
done
