#!/bin/sh
# Phase-14 arm (3 objectives: rotation x fully-closed contact x bone removal, metric v4; frozen warm start = phase-13 init records +
# adopted sb13_*, re-scored with phase-14 settings: v4, mm_limit None). = g12_run.sh with SRC=13 DST=14, EXPECT_DELTA 0.1, EXPECT_MM none,
# default BUDGET 75 own submissions (the warm rows are not counted). Usage: sh g14_run.sh [BUDGET [INFLIGHT]] (default 75 2).
# Every variable of g12_run.sh can still be overridden. See README_p11_ops.md section 8.
#   cd ~/mobo_toy_v2 && nohup sh adhoc/p11/g14_run.sh 75 2 > logs/g14.log 2>&1 < /dev/null &
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=13 DST=14 EXPECT_DELTA="${EXPECT_DELTA-0.1}" EXPECT_MM="${EXPECT_MM-none}"
export SRC DST EXPECT_DELTA EXPECT_MM
exec sh "$HERE/g12_run.sh" "${1:-75}" "${2:-2}"
