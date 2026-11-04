#!/bin/sh
# 阶段 9：无领优化（设计见 无领优化设计_2026-10-07.md）。与阶段 8 同口径：16 个准随机初始点 + 异步 qLogNEHVI 补到 100 个
# （用户 2026-10-07 定：100 个，分析时在第 72 个处另报一次，与阶段 8 同预算比较），同时在算 6 个；候选池 Sobol 16384（13 维），
# 每完成 6 个在前沿邻域补 32 个候选；不热启动。选号规则 neck_in_shoulder（颈底须落在柄截口内，见 stage_neckopt 阶段 9 的注释）。
# 只用 CPU 4–11、nice 19。记录 ~/mobo_toy_v2/results/neckopt_p9.json；日志 ~/mobo_toy_v2/logs/g9_p9.log
cd "$HOME/mobo_toy_v2/code" || exit 1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py bo --phase 9 --init 16 --rounds 0 --warm none --pool 16384 --workers 6 || exit 1
exec taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py async --phase 9 --budget 100 --inflight 6 --pool 16384 \
    --refresh 32 --refresh-rad 0.08 --warm none --workers 6
