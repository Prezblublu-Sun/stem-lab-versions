"""模拟器：用已解的 FE 结果冒充真实 FE，在上面比较"两阶段"与"联合"优化策略（用户 2026-10-04 11:00）。Linux 上跑，0 次 FE。

训练数据：stage_robust.scan() 里 neck1 / neck2 / neck3 的 225 个设计（平端、新截骨面、M1、过盈 0.025），14 维单位坐标；
    输出 = 整界面微动 log10 P95、约束违反量；骨量损失不模拟（候选池里每点都有模板化精确算出的值）。
三个模拟器
    E1  GP，Matérn 5/2 ARD（与优化器同族；作参照）——后验均值
    E2  GP，Matérn 3/2 ARD 的后验样本路径（pathwise / Matheron），每个种子一条 = 一个"可能的真世界"，比均值起伏
    E3  极端随机树集成（sklearn ExtraTrees）——与 GP 结构不同
    约束一律用 E1 的约束均值（实测里约束从未起作用）。评估时给微动加观测噪声 N(0, 0.02²)（对数尺度，≈ 重算变异系数 5 %），
    微动下限 1 µm。
校准检验（calib）
    T1 10 折交叉验证：R²、RMSE、Spearman（对数微动）
    T2 外推：只用两阶段 135 个训练 → 预测联合的 90 个；反过来再做一次；联合前沿点的微动相对误差
    T3 GP 的 50 % / 90 % 预测区间覆盖率（交叉验证）
    T4 模拟器在联合候选池上的"真前沿"超体积 对 实测已知最好前沿（同一参考点），看是否过度乐观
    T6 粗糙度：数据近邻点对的 |Δy| / 距离 对 模拟器在候选池近邻点对上的同一量
策略比较（bench，每个进程一个 模拟器 × 种子）
    两阶段：阶段 1 = 4 维（池 = 真实阶段 1 的池），16 初始 + 12 × 4；参考设计按 knee_all（实际用过的规则）与 knee_le40（排除 > 40 µm
            的离群点）各做一次阶段 2 = 10 维（池按参考现场模板化 4096 点），24 初始 + 12 × 4；各 136 次评估
    联合（从零）：14 维（池 = 联合的基础池 23945 点），24 初始 + 28 × 4 = 136 次评估
    联合（热启动，只在 --replay 时）：以模拟出的两阶段 136 个点热启动，再 22 × 4 = 88 次（= T5 轨迹重放）
    每次采集在池里随机取 4000 个候选（各策略相同），不做邻域补点（各策略相同）。超体积一律用联合优化实际用的参考点、按无噪声真值算。

    python v2/emulator.py calib                         → results/emulator/calib.json
    python v2/emulator.py bench --emu E1 --seed 0 [--replay]   → results/emulator/bench_E1_s0.json
    python v2/emulator.py summary                       → 打印 bench 汇总
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_robust as RB  # noqa: E402
import stage_v2a as S  # noqa: E402

OUT = J.RESULTS / "emulator"
NOISE_SD = 0.02
LOG_FLOOR = 0.0                      # 1 µm
PH3 = N.Phase(3, None, "abs")
PH1 = N.Phase(1, None, "abs")
STAGES = ("neck1_", "neck2_", "neck3_")


# ------------------------------------------------------------------------------------------------- 数据与模拟器
def training_data():
    ent = RB.scan()
    rows = [e for e in ent.values() if "a" in e and e["a_job"].startswith(STAGES)]
    rows.sort(key=lambda e: e["a_job"])
    X = np.array([e["x"] for e in rows])
    y = np.array([e["a"]["y"][0] for e in rows])
    c = np.array([e["a"]["c"][0] for e in rows])
    loss = np.array([e["a"]["y"][1] for e in rows])
    stage = np.array([e["a_job"][:6] for e in rows])
    return X, y, c, loss, stage


def _t(a):
    import torch
    return torch.as_tensor(np.asarray(a, float), dtype=torch.double)


def fit_gp(X, y, nu=2.5):
    """输入已在 [0,1]；输出手动标准化（pathwise 采样不经过 outcome transform）。返回 (gp, mu, sd)。"""
    import torch
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from gpytorch.constraints import GreaterThan
    from gpytorch.kernels import MaternKernel, ScaleKernel
    from gpytorch.likelihoods import GaussianLikelihood
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from gpytorch.priors import GammaPrior
    mu, sd = float(np.mean(y)), float(np.std(y)) or 1.0
    d = X.shape[1]
    kern = ScaleKernel(MaternKernel(nu=nu, ard_num_dims=d, lengthscale_prior=GammaPrior(3.0, 6.0)), outputscale_prior=GammaPrior(2.0, 0.15))
    gp = SingleTaskGP(_t(X), _t((y - mu) / sd).reshape(-1, 1), likelihood=GaussianLikelihood(noise_constraint=GreaterThan(1e-6)),
                      covar_module=kern)
    try:
        fit_gpytorch_mll(ExactMarginalLogLikelihood(gp.likelihood, gp))
    except Exception as e:                                           # noqa: BLE001
        print("  WARNING GP fit failed:", type(e).__name__, e, flush=True)
    gp.eval()
    return gp, mu, sd


def gp_predict(model, X, with_noise=False):
    import torch
    gp, mu, sd = model
    with torch.no_grad():
        post = gp.posterior(_t(X), observation_noise=with_noise)
        m = post.mean.squeeze(-1).numpy() * sd + mu
        v = post.variance.squeeze(-1).numpy() * sd ** 2
    return m, np.sqrt(np.maximum(v, 0.0))


class Emulator:
    """f(X14) → (log10 微动真值, 约束违反量)。"""

    def __init__(self, kind: str, seed: int, X, y, c):
        self.kind, self.seed = kind, seed
        self.cmodel = fit_gp(X, c, 2.5)
        if kind == "E1":
            self.m = fit_gp(X, y, 2.5)
        elif kind == "E2":
            import torch
            from botorch.sampling.pathwise import draw_matheron_paths
            self.m = fit_gp(X, y, 1.5)
            torch.manual_seed(1000 + seed)
            self.path = draw_matheron_paths(self.m[0], sample_shape=torch.Size([1]))
        elif kind == "E3":
            from sklearn.ensemble import ExtraTreesRegressor
            self.m = ExtraTreesRegressor(n_estimators=400, min_samples_leaf=2, max_features=0.6, random_state=seed).fit(X, y)
        else:
            raise ValueError(kind)

    def y(self, X):
        X = np.atleast_2d(np.asarray(X, float))
        if self.kind == "E1":
            v = gp_predict(self.m, X)[0]
        elif self.kind == "E2":
            import torch
            gp, mu, sd = self.m
            with torch.no_grad():
                v = np.concatenate([self.path(_t(X[i:i + 4096])).reshape(-1).numpy() for i in range(0, len(X), 4096)]) * sd + mu
        else:
            v = self.m.predict(X)
        return np.maximum(v, LOG_FLOOR)

    def c(self, X):
        return gp_predict(self.cmodel, np.atleast_2d(X))[0]


# ------------------------------------------------------------------------------------------------- 校准检验
def r2(a, b):
    return float(1 - np.sum((a - b) ** 2) / np.sum((a - np.mean(a)) ** 2))


def _fit_pred(kind, Xtr, ytr, Xte):
    if kind == "trees":
        from sklearn.ensemble import ExtraTreesRegressor
        m = ExtraTreesRegressor(n_estimators=400, min_samples_leaf=2, max_features=0.6, random_state=0).fit(Xtr, ytr)
        return m.predict(Xte), None
    model = fit_gp(Xtr, ytr, 2.5 if kind == "gp52" else 1.5)
    m, s = gp_predict(model, Xte, with_noise=True)
    return m, s


def calib():
    from scipy.stats import spearmanr
    OUT.mkdir(parents=True, exist_ok=True)
    X, y, c, loss, stage = training_data()
    res = {"n": int(len(X)), "by_stage": {s: int((stage == s).sum()) for s in np.unique(stage)}}
    rng = np.random.default_rng(0)
    folds = rng.permutation(len(X)) % 10
    for kind in ("gp52", "gp32", "trees"):
        pred, sdev = np.zeros(len(X)), np.zeros(len(X))
        for f in range(10):
            tr, te = folds != f, folds == f
            m, s = _fit_pred(kind, X[tr], y[tr], X[te])
            pred[te] = m
            if s is not None:
                sdev[te] = s
        out = {"R2": r2(y, pred), "RMSE": float(np.sqrt(np.mean((y - pred) ** 2))), "spearman": float(spearmanr(y, pred).correlation)}
        if kind != "trees":
            z = np.abs(y - pred) / np.maximum(sdev, 1e-9)
            out["coverage50"] = float(np.mean(z <= 0.674)); out["coverage90"] = float(np.mean(z <= 1.645))
        res[f"T1_T3_{kind}"] = out
        # T2 外推
        two, joint = np.isin(stage, ["neck1_", "neck2_"]), stage == "neck3_"
        m, s = _fit_pred(kind, X[two], y[two], X[joint])
        Y3 = np.c_[y[joint], loss[joint]]
        fr = [i for i in range(len(Y3)) if not any((Y3[j] <= Y3[i]).all() and (Y3[j] < Y3[i]).any() for j in range(len(Y3)))]
        relerr = np.abs(10 ** m[fr] - 10 ** y[joint][fr]) / 10 ** y[joint][fr]
        t2 = {"R2": r2(y[joint], m), "spearman": float(spearmanr(y[joint], m).correlation),
              "front_points": len(fr), "front_relerr_median": float(np.median(relerr)), "front_relerr_max": float(np.max(relerr)),
              "front_within_30pct": float(np.mean(relerr <= 0.30)),
              "pred_best_um": float(10 ** m.min()), "true_best_um": float(10 ** y[joint].min())}
        if s is not None:
            z = np.abs(y[joint] - m) / np.maximum(s, 1e-9); t2["coverage90"] = float(np.mean(z <= 1.645))
        m2, _ = _fit_pred(kind, X[joint], y[joint], X[two])
        t2["reverse_R2"] = r2(y[two], m2); t2["reverse_spearman"] = float(spearmanr(y[two], m2).correlation)
        res[f"T2_{kind}"] = t2
        print(kind, json.dumps({"T1": out, "T2": t2}, default=float), flush=True)
    # T4 / T6：在联合候选池上
    import mobo
    pool = np.load(sorted(J.RESULTS.glob("pools/neckopt_p3_n32768_s0_*.npz"))[0])
    U, L = pool["U"], pool["loss"]
    ref = np.array(json.loads((J.RESULTS / "neckopt_p3.json").read_text())["ref_point"])
    Yobs = np.c_[y, loss]
    hv_obs = float(mobo.hypervolume(Yobs, ref))
    res["T4_observed_HV"] = hv_obs
    # 数据近邻点对
    from scipy.spatial import cKDTree
    t = cKDTree(X)
    dd, ii = t.query(X, k=2)
    slope_data = np.abs(y - y[ii[:, 1]]) / dd[:, 1]
    res["T6_data_nn_dist_median"] = float(np.median(dd[:, 1]))
    res["T6_data_slope_median"] = float(np.median(slope_data))
    sub = np.random.default_rng(1).choice(len(U), 3000, replace=False)
    tu = cKDTree(U[sub])
    for kind in ("E1", "E2", "E3"):
        em = Emulator(kind, 0, X, y, c)
        ye = em.y(U)
        F = np.c_[ye, L]
        hv_e = float(mobo.hypervolume(F, ref))
        dp, ip = tu.query(U[sub], k=2)
        slope_e = np.abs(ye[sub] - ye[sub][ip[:, 1]]) / dp[:, 1]
        # 在与数据近邻同尺度的点对上比较：取池里距离与数据近邻距离中位数相近（±30 %）的点对
        scale = res["T6_data_nn_dist_median"]
        msk = np.abs(dp[:, 1] - scale) / scale < 0.3
        res[f"T4_T6_{kind}"] = {"pool_front_HV": hv_e, "HV_ratio_vs_observed": hv_e / hv_obs, "pool_best_um": float(10 ** ye.min()),
                                "pool_nn_dist_median": float(np.median(dp[:, 1])), "slope_median_all": float(np.median(slope_e)),
                                "slope_median_at_data_scale": float(np.median(slope_e[msk])) if msk.any() else None,
                                "n_pairs_at_data_scale": int(msk.sum()), "feasible_frac": float(np.mean(em.c(U[sub]) <= 0))}
        print(kind, json.dumps(res[f"T4_T6_{kind}"], default=float), flush=True)
    res["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "calib.json").write_text(json.dumps(res, indent=1, default=float))
    print("observed HV", round(hv_obs), "| data nn dist", round(res["T6_data_nn_dist_median"], 3), "slope", round(res["T6_data_slope_median"], 3))


# ------------------------------------------------------------------------------------------------- 策略模拟
def pool_p1():
    for f in sorted(J.RESULTS.glob("pools/neckopt_p1_n8192_s0_*.json")):
        meta = json.loads(f.read_text())
        if meta.get("feasible") == 6813 and len(meta.get("space", {})) == 4:
            z = np.load(f.with_suffix(".npz"))
            return z["U"], z["loss"]
    raise FileNotFoundError("stage-1 pool with 6813 feasible points")


def pool_p3():
    z = np.load(sorted(J.RESULTS.glob("pools/neckopt_p3_n32768_s0_*.npz"))[0])
    return z["U"], z["loss"]


def to14(ph: N.Phase, U):
    out = []
    for u in np.atleast_2d(U):
        d, h = ph.design_of(u)
        out.append(PH3.to_unit(d, h))
    return np.array(out)


def run_bo(ph, U, L, em, rng, n_init, n_rounds, q, seed, init_idx=None, warm=None, n_cand=4000, log=None, tag=""):
    """池上的同步批量 BO（与 stage_neckopt.bo 相同的代理、采集、参考点规则；不补点）。warm = (X_phase, Y, C) 热启动。
    返回记录列表：{x (phase), x14, y_true, y_obs, loss, c}。"""
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X14 = to14(ph, U) if ph is not PH3 else U
    det = {1: N.det_loss_fn(U, L)}
    used = np.zeros(len(U), bool)
    recs = []

    def evaluate(idx):
        yt = em.y(X14[idx]); cc = em.c(X14[idx])
        yo = np.maximum(yt + rng.normal(0.0, NOISE_SD, len(idx)), LOG_FLOOR)
        for i, a, b, k in zip(idx, yt, yo, cc):
            recs.append({"i": int(i), "x": U[i].tolist(), "x14": X14[i].tolist(), "y_true": float(a), "y_obs": float(b), "loss": float(L[i]), "c": float(k)})
            used[i] = True

    if init_idx is None:
        init_idx = rng.choice(len(U), n_init, replace=False)
    evaluate(np.asarray(init_idx))
    refp = None
    for rnd in range(1, n_rounds + 1):
        X = np.array([r["x"] for r in recs]); Y = np.array([[r["y_obs"], r["loss"]] for r in recs]); C = np.array([[r["c"]] for r in recs])
        if warm is not None:
            X, Y, C = np.vstack([warm[0], X]), np.vstack([warm[1], Y]), np.vstack([warm[2], C])
        if refp is None:
            refp = N.ref_point(Y, C)
        model = mobo.fit_models(X, Y, C, det=det)
        free = np.nonzero(~used)[0]
        cand = rng.choice(free, size=min(n_cand, len(free)), replace=False)
        pick = mobo.propose(model, X, refp, U[cand], q, 2, 1, seed * 1000 + rnd)
        evaluate(cand[pick])
        if log:
            log(f"{tag} round {rnd}: n {len(recs)}")
    return recs


def knee(recs, rule: str):
    Y = np.array([[r["y_obs"], r["loss"]] for r in recs if r["c"] <= 0])
    idx = [i for i, r in enumerate(recs) if r["c"] <= 0]
    fr = [idx[i] for i in range(len(Y)) if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in range(len(Y)))]
    if rule == "knee_le40":
        fr2 = [i for i in fr if recs[i]["y_obs"] <= math.log10(40.0)]
        fr = fr2 or fr
    F = np.array([[recs[i]["y_obs"], recs[i]["loss"]] for i in fr])
    lo, hi = F.min(0), F.max(0)
    Z = (F - lo) / np.where(hi - lo > 0, hi - lo, 1.0)
    return recs[fr[int(np.argmin(np.linalg.norm(Z, axis=1)))]]


def bench(kind: str, seed: int, replay: bool, workers: int = 2):
    import torch
    torch.set_num_threads(2)
    OUT.mkdir(parents=True, exist_ok=True)
    X, y, c, loss, stage = training_data()
    em = Emulator(kind, seed, X, y, c)
    t0 = time.time()
    logf = OUT / f"bench_{kind}_s{seed}{'_replay' if replay else ''}.log"

    def log(msg):
        with open(logf, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

    out = {"emulator": kind, "seed": seed, "replay": replay, "noise_sd": NOISE_SD, "runs": {}}
    U1, L1 = pool_p1()
    rng = np.random.default_rng(seed)
    init1 = np.arange(16) if (replay and seed == 0) else None             # 重放时与真实一样取池的 Sobol 前 16 个
    s1 = run_bo(PH1, U1, L1, em, rng, 16, 12, 4, 100 + seed, init_idx=init1, log=log, tag="stage1")
    out["runs"]["stage1"] = s1
    for rule in ("knee_all", "knee_le40"):
        r = knee(s1, rule)
        d, h = PH1.design_of(np.array(r["x"]))
        ref = {"L": d["L"], "alpha": d["alpha"], "collar_w": d.get("collar_w", 0.0), "h_cut": h}
        ph2 = N.Phase(2, ref, "abs")
        U2, L2 = N.gated_pool(ph2, n=4096, seed=seed, workers=workers)
        rng2 = np.random.default_rng(seed * 10 + (1 if rule == "knee_all" else 2))
        s2 = run_bo(ph2, U2, L2, em, rng2, 24, 12, 4, 200 + seed, log=log, tag=f"stage2 {rule}")
        out["runs"][f"stage2_{rule}"] = s2
        out[f"ref_{rule}"] = {**ref, "y_obs": r["y_obs"], "loss": r["loss"]}
        log(f"stage2 {rule} done; ref {ref}")
    U3, L3 = pool_p3()
    rng3 = np.random.default_rng(seed * 10 + 3)
    out["runs"]["joint_scratch"] = run_bo(PH3, U3, L3, em, rng3, 24, 28, 4, 300 + seed, log=log, tag="joint scratch")
    if replay:
        two = s1 + out["runs"]["stage2_knee_all"]
        warm = (np.array([r["x14"] for r in two]), np.array([[r["y_obs"], r["loss"]] for r in two]), np.array([[r["c"]] for r in two]))
        rng4 = np.random.default_rng(seed * 10 + 4)
        out["runs"]["joint_warm"] = run_bo(PH3, U3, L3, em, rng4, 0 or 4, 22, 4, 400 + seed, warm=warm, log=log, tag="joint warm")
    out["elapsed_s"] = time.time() - t0
    (OUT / f"bench_{kind}_s{seed}{'_replay' if replay else ''}.json").write_text(json.dumps(out, default=float))
    log(f"finished in {out['elapsed_s'] / 60:.1f} min")


def summary():
    import mobo
    ref = np.array(json.loads((J.RESULTS / "neckopt_p3.json").read_text())["ref_point"])

    def hv_curve(recs, steps):
        out = []
        for k in steps:
            R = [r for r in recs[:k] if r["c"] <= 0]
            Y = np.array([[r["y_true"], r["loss"]] for r in R]).reshape(-1, 2)
            out.append(float(mobo.hypervolume(Y, ref)) if len(Y) else 0.0)
        return out
    rows = {}
    for f in sorted(OUT.glob("bench_*.json")):
        b = json.loads(f.read_text())
        R = b["runs"]
        two = {rule: R["stage1"] + R[f"stage2_{rule}"] for rule in ("knee_all", "knee_le40")}
        steps = [16, 40, 64, 88, 112, 136]
        rec = {"two_knee_all": hv_curve(two["knee_all"], steps), "two_knee_le40": hv_curve(two["knee_le40"], steps),
               "joint_scratch": hv_curve(R["joint_scratch"], steps)}
        if "joint_warm" in R:
            rec["two_then_joint_warm"] = hv_curve(two["knee_all"] + R["joint_warm"], [136, 136 + 44, 136 + len(R["joint_warm"])])
        rows[f.stem] = rec
        print(f.stem, {k: [round(v) for v in vv] for k, vv in rec.items()})
    (OUT / "summary.json").write_text(json.dumps(rows, indent=1))
    by = {}
    for k, v in rows.items():
        emu = k.split("_")[1]
        by.setdefault(emu, []).append(v)
    for emu, vs in by.items():
        a = np.array([v["joint_scratch"][-1] / v["two_knee_all"][-1] for v in vs])
        b = np.array([v["joint_scratch"][-1] / v["two_knee_le40"][-1] for v in vs])
        print(f"{emu}: n {len(vs)}  joint/two(knee_all) median {np.median(a):.3f} [{a.min():.3f}, {a.max():.3f}]  "
              f"joint/two(knee_le40) median {np.median(b):.3f} [{b.min():.3f}, {b.max():.3f}]")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["calib", "bench", "summary"])
    ap.add_argument("--emu", default="E1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    if a.cmd == "calib":
        calib()
    elif a.cmd == "bench":
        bench(a.emu, a.seed, a.replay, a.workers)
    else:
        summary()
