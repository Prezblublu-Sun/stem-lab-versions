#!/bin/sh
# 批次 G4（2026-10-06 晚）：阶段 7 = 领的新规则 wrap_fit + 新口径 metric v2，从零优化（不用任何已有结果热启动）。
# 先同步版只跑 16 个准随机初始点（--rounds 0），再异步版补到 72 个；只用 CPU 4–11、nice 19。
# 记录 ~/mobo_toy_v2/results/neckopt_p7.json；日志 ~/mobo_toy_v2/logs/g4_p7.log
cd "$HOME/mobo_toy_v2/code" || exit 1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py bo --phase 7 --init 16 --rounds 0 --warm none --workers 6 || exit 1
exec taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py async --phase 7 --budget 72 --inflight 4 --warm none --workers 6
