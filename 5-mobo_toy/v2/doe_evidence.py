"""试验设计的量化依据（在 Linux 上跑，零求解）：用已有的现行版本设计回答“代理需要多少样本”。

* 标量学习曲线：训练样本数 n 取若干档，随机划分重复多次，高斯过程（ARD Matérn 5/2）在留出集上的 R²、RMSE、秩相关、90% 区间覆盖率。
* 场的主成分：皮质骨 log10 应变能密度在公共采样点上的快照矩阵，累计方差对模态数。
* 场的学习曲线：主成分降维 + 每个模态一个高斯过程；留出集上的相对 L2 误差、仅截断的误差、由场算出的固定 7 区应变能密度变化的误差。

数据：shielding.design_jobs() 里代码版本为现行的设计（粘接模型）；输入是 12 个设计变量加截骨高度。
注意：这是旧设计空间、单根股骨上的证据，只能说明量级。旧界面模型的微动结论已撤回，这里只把它当作一个“难学的量”的例子。

    python v2/doe_evidence.py [--workers 10] [--repeats 10]
输出：~/mobo_toy_v2/results/doe_evidence/{summary.json, snapshots.npz, figs/*.png}
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import warnings
from multiprocessing import Pool

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import shielding as SH  # noqa: E402
import resorption as RS  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

OUT = J.RESULTS / "doe_evidence"
N_LIST = (25, 50, 100, 150)
VARS = ("L", "alpha", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "h_cut")
R_MAX = 25


# ------------------------------------------------------------------------------------------------ 数据
def _one(dname):
    if "fm" not in RS._CTX:
        RS._init()
    d = J.QROOT / dname
    spec = json.loads((d / "spec.json").read_text())
    res = J.result(dname)
    t = res["templating"]
    dsg = G.design_of_spec(spec)
    stem = G.Stem3D(**spec["design"])
    h = float(spec.get("h_cut", 25.0))
    fm = RS._CTX["fm"].with_cut(h)
    pose = fm.pose(t["alpha"], t["e"])
    P, canc = RS._CTX["P"], RS._CTX["canc"]
    fl = SH.load_fields(d)
    ga, g6 = RS.to_grid(fl, P, canc, 1), RS.to_grid(fl, P, canc, 6)
    keep = (fm.below_cut(P) & ~G.inside_stem(stem, t["A0"], SH.local(P, pose)) & np.isfinite(ga["sed"]) & (ga["sed"] > 0)
            & np.isfinite(g6["sed"]) & (g6["sed"] > 0) & ~canc)
    x = [float(dsg.get(k, math.nan)) for k in VARS[:-1]] + [h]
    return dname, x, keep, ga["sed"].astype(np.float32), float(res.get("f1_p95_um", math.nan)), g6["sed"].astype(np.float32)


def collect(workers):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [r for r in RS.read("zones.csv") if r["version"] == "current"]
    ids = sorted({r["job_id"] for r in rows})
    with Pool(workers, initializer=RS._init) as p:
        res = p.map(_one, ids, chunksize=4)
    RS._init()
    gi = RS._CTX["gi"]["sed"]
    Pa, ca = RS._CTX["P"], RS._CTX["canc"]
    it = SH.load_fields(SH.intact_job(True))
    gi6 = RS.to_grid(it, Pa, ca, 6)["sed"]
    alt = sorted(J.QROOT.glob("ref_intact_h1.4_*"))
    alt = [a for a in alt if (a / "DONE").exists() and (a / "intact_csv" / "LOAD_ENER.csv").exists()][-1]
    fa = SH.load_fields(alt)
    a1, a6 = RS.to_grid(fa, Pa, ca, 1)["sed"], RS.to_grid(fa, Pa, ca, 6)["sed"]
    keep = np.all([r[2] for r in res], axis=0) & np.isfinite(gi) & (gi > 0)
    for g_ in (gi6, a1, a6):
        keep &= np.isfinite(g_) & (g_ > 0)
    S = np.array([r[3][keep] for r in res])
    S6 = np.array([r[5][keep] for r in res])
    X = np.array([r[1] for r in res])
    by = {(r["job_id"], r["scheme"], r["zone"], r["tissue"]): r for r in rows}
    st = {r["job_id"]: r for r in RS.read("stem.csv")}
    Y = {"g7_ssi_fixed": [by[(j, "fixed", "G7", "cortex")]["ssi_pct"] for j in ids],
         "g7_ssi_femur": [by[(j, "femur", "G7", "cortex")]["ssi_pct"] for j in ids],
         "res06_total_femur": [by[(j, "femur", "total", "cortex")]["res_0.6"] for j in ids],
         "vm_p99_body": [st[j]["vm_p99_body"] for j in ids],
         "log10_f1_old": [math.log10(max(r[4], 1e-3)) if np.isfinite(r[4]) else math.nan for r in res]}
    P = RS._CTX["P"][keep]
    zf = RS.zones_fixed(P)["G7"]
    np.savez_compressed(OUT / "snapshots.npz", X=X, S=S, S6=S6, intact=gi[keep].astype(np.float32), intact6=gi6[keep].astype(np.float32),
                        alt1=a1[keep].astype(np.float32), alt6=a6[keep].astype(np.float32), alt_job=alt.name, P=P.astype(np.float32), g7_fixed=zf,
                        ids=np.array(ids), **{f"y_{k}": np.array(v, float) for k, v in Y.items()})
    print(f"[doe] {len(ids)} designs, {int(keep.sum())} common cortex points, G7 fixed {int(zf.sum())}", flush=True)


# ------------------------------------------------------------------------------------------------ 模型
def gp_fit_predict(Xa, ya, Xb):
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    d = Xa.shape[1]
    k = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=np.ones(d), length_scale_bounds=(5e-2, 50.0), nu=2.5) + WhiteKernel(1e-2, (1e-6, 1.0))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        g = GaussianProcessRegressor(k, normalize_y=True, n_restarts_optimizer=1, random_state=0).fit(Xa, ya)
        mu, sd = g.predict(Xb, return_std=True)
    return mu, sd


def _scores(y, mu, sd):
    from scipy.stats import spearmanr
    ss = float(np.sum((y - y.mean()) ** 2))
    return {"r2": 1.0 - float(np.sum((y - mu) ** 2)) / ss if ss > 0 else math.nan, "rmse": float(np.sqrt(np.mean((y - mu) ** 2))),
            "spearman": float(spearmanr(y, mu)[0]), "cover90": float(np.mean(np.abs(y - mu) <= 1.645 * sd))}


def _scalar_task(a):
    name, n, rep, X, y = a
    rng = np.random.default_rng(1000 * n + rep)
    ok = np.where(np.isfinite(y))[0]
    idx = rng.permutation(ok)
    tr, te = idx[:n], idx[n:]
    mu, sd = gp_fit_predict(X[tr], y[tr], X[te])
    return name, n, {**_scores(y[te], mu, sd), "n_test": int(len(te)), "y_sd": float(y[ok].std()), "y_range": float(np.ptp(y[ok]))}


def _field_task(a):
    n, rep, X, Lg, intact, zf = a[:6]
    rng = np.random.default_rng(2000 * n + rep)
    idx = rng.permutation(len(X))
    tr, te = idx[:n], idx[n:]
    mean = Lg[tr].mean(0)
    A = Lg[tr] - mean
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    var = s ** 2 / np.sum(s ** 2)
    r = int(min(R_MAX, n - 1, np.searchsorted(np.cumsum(var), 0.99) + 1))
    C = A @ Vt[:r].T
    Ct = np.zeros((len(te), r))
    for j in range(r):
        Ct[:, j], _ = gp_fit_predict(X[tr], C[:, j], X[te])
    pred = mean + Ct @ Vt[:r]
    proj = mean + ((Lg[te] - mean) @ Vt[:r].T) @ Vt[:r]
    St, Sp, Sq = 10.0 ** Lg[te], 10.0 ** pred, 10.0 ** proj
    rel = np.linalg.norm(Sp - St, axis=1) / np.linalg.norm(St, axis=1)
    rel_t = np.linalg.norm(Sq - St, axis=1) / np.linalg.norm(St, axis=1)
    base = np.linalg.norm(10.0 ** mean - St, axis=1) / np.linalg.norm(St, axis=1)        # 只用训练集平均场当预测
    m0 = float(intact[zf].mean())
    chg = lambda S: 100.0 * (S[:, zf].mean(1) / m0 - 1.0)
    e = np.abs(chg(Sp) - chg(St))
    den = float(np.sum((Lg[te] - mean) ** 2))
    ev = 1.0 - float(np.sum((pred - Lg[te]) ** 2)) / den
    ev_t = 1.0 - float(np.sum((proj - Lg[te]) ** 2)) / den
    return n, {"explained": ev, "explained_truncation": ev_t, "r": r, "rel_l2_median": float(np.median(rel)), "rel_l2_p90": float(np.percentile(rel, 90)),
               "rel_l2_truncation_median": float(np.median(rel_t)), "rel_l2_mean_field_median": float(np.median(base)),
               "g7_abs_err_median_pts": float(np.median(e)), "g7_abs_err_p90_pts": float(np.percentile(e, 90)), "n_test": int(len(te))}


def _agg(v):
    keys = v[0].keys()
    return {k: {"median": float(np.median([x[k] for x in v])), "min": float(np.min([x[k] for x in v])), "max": float(np.max([x[k] for x in v]))}
            for k in keys}


def analyse(workers, repeats):
    import plotstyle as ps
    plt = ps.plt
    d = np.load(OUT / "snapshots.npz", allow_pickle=True)
    X0 = d["X"]
    var = [i for i in range(X0.shape[1]) if np.nanstd(X0[:, i]) > 1e-9]
    X = X0[:, var]
    X = np.where(np.isfinite(X), X, np.nanmean(X, 0))
    X = (X - X.min(0)) / (X.max(0) - X.min(0))
    out = {"n_designs": int(len(X)), "inputs": [VARS[i] for i in var], "n_points": int(d["S"].shape[1]), "repeats": repeats, "scalars": {}, "field": {}}
    names = [k[2:] for k in d.files if k.startswith("y_")]
    tasks = [(nm, n, rep, X, d[f"y_{nm}"]) for nm in names for n in N_LIST for rep in range(repeats) if np.isfinite(d[f"y_{nm}"]).sum() - n >= 30]
    with Pool(workers) as p:
        res = p.map(_scalar_task, tasks, chunksize=2)
    for nm in names:
        out["scalars"][nm] = {str(n): _agg([r[2] for r in res if r[0] == nm and r[1] == n]) for n in N_LIST if any(r[0] == nm and r[1] == n for r in res)}
    out["ard"] = {}
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    for nm in names:
        y = d[f"y_{nm}"]
        ok = np.isfinite(y)
        k = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=np.ones(X.shape[1]), length_scale_bounds=(5e-2, 50.0), nu=2.5) + WhiteKernel(1e-2, (1e-6, 1.0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            g = GaussianProcessRegressor(k, normalize_y=True, n_restarts_optimizer=2, random_state=0).fit(X[ok], y[ok])
        ls = np.asarray(g.kernel_.k1.k2.length_scale, float)
        w = (1.0 / ls) / np.sum(1.0 / ls)
        out["ard"][nm] = {"relevance": {out["inputs"][i]: float(w[i]) for i in np.argsort(-w)}, "noise_var_frac": float(g.kernel_.k2.noise_level)}
    roi = d["P"][:, 2] >= -40.0
    allp = np.ones(len(roi), bool)
    variants = {"raw": (d["S"], d["intact"], d["alt1"], allp), "smooth": (d["S6"], d["intact6"], d["alt6"], allp),
                "smooth_roi": (d["S6"], d["intact6"], d["alt6"], roi)}
    out["field"], out["pca"] = {}, {}
    for vn, (S_, it_, alt_, m) in variants.items():
        Lg = np.log10(S_.astype(float))[:, m]
        A = Lg - Lg.mean(0)
        sv = np.linalg.svd(A, compute_uv=False)
        cum = np.cumsum(sv ** 2) / np.sum(sv ** 2)
        noise = np.log10(alt_.astype(float) / it_.astype(float))[m]
        sig = Lg.std(0)
        nr = float(np.sqrt(np.mean(noise ** 2)))
        out["pca"][vn] = {"n_points": int(m.sum()), "cum_var": [float(c) for c in cum[:60]], "modes_90": int(np.searchsorted(cum, 0.90) + 1),
                          "modes_95": int(np.searchsorted(cum, 0.95) + 1), "modes_99": int(np.searchsorted(cum, 0.99) + 1),
                          "mesh_noise_rms_log10": nr, "between_design_sd_log10_median": float(np.median(sig)),
                          "between_design_sd_log10_rms": float(np.sqrt(np.mean(sig ** 2))),
                          "frac_points_signal_gt_2noise": float(np.mean(sig > 2.0 * nr))}
        ft = [(n, rep, X, Lg, it_.astype(float)[m], d["g7_fixed"][m]) for n in N_LIST for rep in range(max(3, repeats // 2))]
        with Pool(min(workers, 6)) as p:
            fr = p.map(_field_task, ft, chunksize=1)
        out["field"][vn] = {str(n): _agg([r[1] for r in fr if r[0] == n]) for n in N_LIST}
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))

    F = OUT / "figs"
    F.mkdir(exist_ok=True)
    LAB = {"g7_ssi_fixed": "zone 7 shielding, fixed zone", "g7_ssi_femur": "zone 7 shielding, stem-set zone", "res06_total_femur": "total resorbed bone",
           "vm_p99_body": "stem stress P99", "log10_f1_old": "log micromotion (old interface)"}
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.5))
    for nm, o in out["scalars"].items():
        ns = [int(k) for k in o]
        axes[0].plot(ns, [o[str(n)]["r2"]["median"] for n in ns], marker="o", ms=3, lw=1, label=LAB.get(nm, nm))
        axes[1].plot(ns, [o[str(n)]["cover90"]["median"] for n in ns], marker="o", ms=3, lw=1)
    axes[0].set_xlabel("training designs")
    axes[0].set_ylabel("R² on held-out designs")
    axes[0].legend(fontsize=5, frameon=False)
    axes[1].axhline(0.9, color="0.5", lw=0.5, ls=":")
    axes[1].set_xlabel("training designs")
    axes[1].set_ylabel("coverage of 90% interval")
    for vn, col, lab in (("raw", "0.7", "nearest element"), ("smooth", "0.4", "6-element average"), ("smooth_roi", "k", "6-element average, proximal")):
        fo = out["field"][vn]
        ns = [int(k) for k in fo]
        axes[2].plot(ns, [100 * fo[str(n)]["explained"]["median"] for n in ns], marker="o", ms=3, lw=1, color=col, label=lab)
    axes[2].set_xlabel("training designs")
    axes[2].set_ylabel("between-design variance explained (%)")
    axes[2].legend(fontsize=5, frameon=False)
    fig.tight_layout()
    fig.savefig(F / "D1_learning_curves.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(3.2, 2.4))
    for vn, col, lab in (("raw", "0.7", "nearest element"), ("smooth", "0.4", "6-element average"), ("smooth_roi", "k", "6-element average, proximal")):
        cv = out["pca"][vn]["cum_var"]
        ax.plot(range(1, len(cv) + 1), [100 * c for c in cv], marker="o", ms=2, lw=1, color=col, label=lab)
    ax.legend(fontsize=5, frameon=False)
    for t in (90, 95, 99):
        ax.axhline(t, color="0.6", lw=0.5, ls=":")
    ax.set_xlabel("number of modes")
    ax.set_ylabel("cumulative variance (%)")
    fig.savefig(F / "D2_pca_modes.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({"pca": {vn: {k: v for k, v in o.items() if k != "cum_var"} for vn, o in out["pca"].items()},
                      "field": {vn: {n: {k: round(v[k]["median"], 3) for k in ("explained", "explained_truncation", "r", "g7_abs_err_median_pts", "rel_l2_median")}
                                     for n, v in o.items()} for vn, o in out["field"].items()},
                      "ard_top4": {k: list(v["relevance"].items())[:4] for k, v in out["ard"].items()}}, indent=1), flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--skip-collect", action="store_true")
    a = ap.parse_args()
    if not a.skip_collect:
        collect(a.workers)
    analyse(a.workers, a.repeats)
