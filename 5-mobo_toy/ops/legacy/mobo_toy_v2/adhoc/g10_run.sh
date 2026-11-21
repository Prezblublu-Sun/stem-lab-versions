#!/bin/sh
# 阶段 10（用户 2026-10-10 会议后）：无领；皮质余量 m ≥ 0.5 mm（靠近皮质、不直接接触）；颈底须落在柄截口内。
# 目标 metric v3：柄相对骨的刚体转动（首次加载）最小、完全接触面积（LOAD2）最大；约束 柄身微动 ≤ 150 µm、柄应力 ≤ 440 MPa、|ΔSED| ≤ 30 %。
# 热启动 = 阶段 9 中 m ≥ 0.5 的 63 个；异步 qLogNEHVI 新增 72 个，同时在算 6 个；候选池 Sobol 16384，每完成 6 个在前沿邻域补 32 个。
# 只用 CPU 4–11、nice 19。记录 ~/mobo_toy_v2/results/neckopt_p10.json；日志 ~/mobo_toy_v2/logs/g10_p10.log
cd "$HOME/mobo_toy_v2/code" || exit 1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
exec taskset -c 4-11 nice -n 19 "$HOME/mobo_toy_v2/run.sh" v2/stage_neckopt.py async --phase 10 --budget 72 --inflight 6 --pool 16384 \
    --refresh 32 --refresh-rad 0.08 --warm family --workers 6
