#!/bin/sh
# Phase-13 arm (2 objectives: rotation x fully-closed contact; Sawbones 3406, cancellous interference delta 0.10 mm, micromotion recorded
# but not a constraint: PHASES[13]["mm_limit"] None; user 2026-10-24 12:20). = g11b_run.sh with SRC=13 DST=14, NEW 75 own picks,
# EXPECT_DELTA 0.1 (the init gate checks every round-0 spec), EXPECT_MM none (the gate requires "mm_limit": null in neckopt_p13.json and the
# launcher requires "mm_limit": None on the PHASES[13] line of the synced code; review wxa60xosx medium 1). Budget = init records + adopted
# sb13_* + NEW (from arms_gate.py).
# Every variable of g11b_run.sh can still be overridden (NEW=60 sh g13b_run.sh ...). See README_p11_ops.md section 8.
#   cd ~/mobo_toy_v2 && nohup sh adhoc/p11/g13b_run.sh > logs/g13b.log 2>&1 < /dev/null &
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=13 DST=14 NEW="${NEW:-75}" EXPECT_DELTA="${EXPECT_DELTA-0.1}" EXPECT_MM="${EXPECT_MM-none}"
export SRC DST NEW EXPECT_DELTA EXPECT_MM
exec sh "$HERE/g11b_run.sh" "$@"
