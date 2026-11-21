#!/bin/sh
# 阶段 8（用户 2026-10-07 10:50 同意）：领的新规则 wrap_fit + 新口径 metric v2，与阶段 3 相同的 14 个变量全部放开。
# 热启动 = 阶段 7 的 72 个 + 批次 F1 的 23 个（含 1 个重复性核对作业）；异步 qLogNEHVI 新增 72 个，同时在算 6 个；
# 候选池 Sobol 16384 个过新规则选号，每完成 6 个在前沿各点邻域补 32 个候选。只用 CPU 4–11、nice 19。
# 记录 ~/mobo_toy_v2/results/neckopt_p8.json；日志 ~/mobo_toy_v2/logs/g8_p8.log
cd "$HOME/mobo_toy_v2/code" || exit 1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
exec taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py async --phase 8 --budget 72 --inflight 6 --pool 16384 \
    --refresh 32 --refresh-rad 0.08 --warm family --workers 6
