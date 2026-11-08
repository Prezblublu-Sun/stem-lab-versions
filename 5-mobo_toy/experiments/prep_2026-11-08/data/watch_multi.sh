#!/usr/bin/env bash
# One watcher for several batches fed at the same time (same rules and lock as b28c's watch_cond.sh; one monitor per project).
#   ssh ... 'bash ~/mobo_toy_v2/adhoc/opt5/watch_multi.sh b29,b30,b31 <session> <seen_done> <known_failed>'
# seen_done and known_failed are totals over all the batches.
BS=${1:?batches}; SESSION=${2:-unknown}; SEEN=${3:-0}; KNOWN=${4:-0}
cd ~/mobo_toy_v2 || exit 1
LOCK=logs/watcher.lock
if [ -f "$LOCK" ]; then
  read -r opid osess ostart obatch < "$LOCK"
  if [ -n "$opid" ] && [ "$opid" != "$$" ] && kill -0 "$opid" 2>/dev/null; then
    echo "REFUSED: watcher $opid of session $osess for $obatch is alive since $ostart"; exit 3
  fi
fi
echo "$$ $SESSION $(date -u +%FT%TZ) $BS" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
trap 'rm -f "$LOCK"; exit 0' HUP TERM INT
JOBS=""; PIDS=""
for B in ${BS//,/ }; do
  MAN=results/db_manifest_$B.json
  [ -f "$MAN" ] || { echo "no manifest $MAN"; exit 4; }
  JOBS="$JOBS $(python3 - "$MAN" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1]))
rows = m.get("rows", m)
print(" ".join(sorted({r.get("id") or r.get("expected_id") for r in rows.values() if isinstance(r, dict) and (r.get("id") or r.get("expected_id"))})))
EOF
)"
  PIDS="$PIDS $B:$(cat logs/db_feed_$B.pid 2>/dev/null)"
done
N=$(echo $JOBS | wc -w)
echo "watching $BS: $N rows, feeders$PIDS, known failed $KNOWN, lock pid $$"
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
  if [ "$n_failed" -gt "$KNOWN" ]; then echo "EVENT new failure: $now"; for j in $JOBS; do [ -f "queue/$j/FAILED.json" ] && echo "  $j $(cut -c1-160 queue/$j/FAILED.json)"; done; exit 0; fi
  if [ -n "$oldest" ]; then echo "EVENT ready not claimed: $oldest; $now"; exit 0; fi
  if ls STOP_DB_FEED* > /dev/null 2>&1; then echo "EVENT stop file: $(ls STOP_DB_FEED* | tr '\n' ' '); $now"; exit 0; fi
  if [ $((n_done + n_failed)) -ge "$N" ]; then echo "EVENT all finished: $now"; exit 0; fi
  for bp in $PIDS; do
    b=${bp%%:*}; p=${bp#*:}
    if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null && ! tail -n 1 "logs/db_feed_$b.out" 2>/dev/null | grep -q "batch $b finished"; then
      echo "EVENT feeder $b gone: $now"; tail -n 3 "logs/db_feed_$b.out" 2>/dev/null | cut -c1-200; exit 0
    fi
  done
  if [ "$n_done" -ge $((SEEN+3)) ]; then echo "EVENT progress: $now"; exit 0; fi
  sleep 60
done
