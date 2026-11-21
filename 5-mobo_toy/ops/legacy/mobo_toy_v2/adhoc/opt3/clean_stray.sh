#!/usr/bin/env bash
# Remove the stray copy the first deploy run wrote at 18:33. Only that one file and its empty folders; rmdir refuses anything not empty.
S=~/mobo_toy_v2/mobo_toy_v2
find "$S" | sed "s#$HOME/##"
n=$(find "$S" -type f | wc -l)
[ "$n" = "1" ] || { echo "more than the one file, left alone"; exit 1; }
rm "$S/code/v2/stage_db.py" && rmdir "$S/code/v2" "$S/code" "$S" && echo removed
ls -d "$S" 2>&1 | cut -c1-80
