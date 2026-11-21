"""批次 D（0 次 FE，Linux）：E2 模拟器上 Sobol 随机采样 vs 原两阶段（knee_all，实际用过的交接规则）vs 从零联合。

两阶段与从零联合的轨迹复用 10-04 已跑的 results/emulator/bench_E2_s{0..9}（s0 为重放版）；本脚本只补随机采样：
对每个种子用同一条 E2 样本路径（Emulator("E2", seed)），在联合优化的可行 Sobol 池（23945 点，Sobol 生成顺序）里取
第 seed × 2000 起的连续 2000 个点（各种子互不重叠），观测加同样的噪声 N(0, 0.02²)，超体积按无噪声真值、与 F5 同一参考点
（neckopt_p3.json 的 ref_point）。输出 ~/mobo_toy_v2/deck/D_bo_vs_random.json：每个种子三条超体积曲线。
注意：模拟器只部分通过校准（只有 E2 通过 T5 重放），用的是旧口径（整界面微动），结论是方向性的。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import emulator as EM  # noqa: E402
import jobs as J  # noqa: E402

N_RAND = 2000
STEPS = list(range(4, 137, 4))


def hv(recs, ref, k):
    import mobo
    R = [r for r in recs[:k] if r["c"] <= 0]
    Y = np.array([[r["y_true"], r["loss"]] for r in R]).reshape(-1, 2)
    return float(mobo.hypervolume(Y, ref)) if len(Y) else 0.0


def main():
    import torch
    torch.set_num_threads(2)
    ref = np.array(json.loads((J.RESULTS / "neckopt_p3.json").read_text())["ref_point"])
    X, y, c, loss, stage = EM.training_data()
    U3, L3 = EM.pool_p3()
    out = {"ref_point": ref.tolist(), "n_random": N_RAND, "steps": STEPS, "seeds": {}}
    for seed in range(10):
        t0 = time.time()
        f = EM.OUT / (f"bench_E2_s{seed}_replay.json" if seed == 0 else f"bench_E2_s{seed}.json")
        b = json.loads(f.read_text())["runs"]
        em = EM.Emulator("E2", seed, X, y, c)
        chk = b["joint_scratch"][:50]                          # 同一条样本路径的核对：重算 10-04 记录的真值
        dev = float(np.max(np.abs(em.y(np.array([r["x14"] for r in chk])) - np.array([r["y_true"] for r in chk]))))
        idx = np.arange(seed * N_RAND, (seed + 1) * N_RAND)
        rng = np.random.default_rng(seed + 777)
        yt = em.y(U3[idx]); cc = em.c(U3[idx])
        rand = [{"y_true": float(a), "loss": float(L3[i]), "c": float(k)} for i, a, k in zip(idx, yt, cc)]
        two = b["stage1"] + b["stage2_knee_all"]
        rsteps = sorted(set(STEPS + [200, 300, 400, 600, 800, 1000, 1500, 2000]))
        out["seeds"][str(seed)] = {"two_stage": [hv(two, ref, k) for k in STEPS], "joint_scratch": [hv(b["joint_scratch"], ref, k) for k in STEPS],
                                   "random_steps": rsteps, "random": [hv(rand, ref, k) for k in rsteps], "feasible_random": int(sum(r["c"] <= 0 for r in rand)),
                                   "path_check_max_abs_dev": dev}
        _ = rng
        print(seed, f"{time.time() - t0:.0f} s", {k: round(v[-1]) for k, v in out["seeds"][str(seed)].items() if isinstance(v, list) and k != "random_steps"}, flush=True)
    (HOME / "deck" / "D_bo_vs_random.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
