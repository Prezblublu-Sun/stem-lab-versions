"""Which parameters matter most for stability once bone removed is taken out. Reads a db3406 export only; writes data/param_importance.json and .csv.

    python -X utf8 param_importance.py [--db <export dir>]

Three measures on rows sampled without looking at results (selection iid, unbiased true, nominal condition), so the optimiser's choices do not bias them:
partial Spearman with bone removed held out, the drop in cross-validated R2 when a variable is left out of a GP, and the swing of the GP partial dependence between the 5th and 95th percentile.
The corner rows (CR-1, CR-T) repeat the first measure inside the box where the best designs sit, because the whole-space ranking need not hold there.
"""
import argparse
import csv
import json
import math
import pathlib
import warnings

import numpy as np
from scipy.stats import rankdata, spearmanr
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent.parent
VARS = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
NAME = {"L": "柄长 L", "alpha": "插入角 α", "h_cut": "截骨深度 h_cut", "m": "皮质余量 m", "rho_tip": "尖端面积比 ρ_tip", "q": "面积曲线指数 q", "lam": "宽厚比 λ", "g_ml": "内侧占比 γ_ml", "g_ap": "前方占比 γ_ap",
        "n_a": "前半方正度 n_a", "n_p": "后半方正度 n_p", "tau_a": "前半楔形 τ_a", "tau_p": "后半楔形 τ_p", "A0": "肩面积 A0", "e": "入口偏移 e"}
RNG = np.random.default_rng(20261104)


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def load(db):
    rows = []
    for r in csv.DictReader(open(db / "scalars.csv", encoding="utf-8")):
        o = {k: num(r[k]) for k in VARS}
        o.update({"u_" + k: num(r["u_" + k]) for k in VARS})
        o.update(job=r["job_id"], layer=r["layer"], status=r["status"], unbiased=r["unbiased"] == "true", selection=r["selection"], in_box=r["in_bounds_v1"] == "true", rot=num(r["rot_first_deg"]), bone=(num(r["bone_total_mm3"]) or float("nan")) / 1000,
                 e=num(r["tpl_e"]), A0=num(r["tpl_A0"]), f1=num(r["f1_p95_um"]), contact=num(r["contact_area_load2_mm2"]), delta=num(r["delta_mm"]), R=num(r["load_R_N"]), af=num(r["alpha_front_deg"]), a_s=num(r["alpha_sagit_deg"]), h=num(r["h_int_mm"]),
                 E=num(r["E_canc_MPa"]), mu=num(r["mu"]), cycles=num(r["cycles"]), forced=num(r["entry_offset_forced_mm"]))
        rows.append(o)
    return rows


def nominal(r):
    return (r["status"] == "DONE" and r["rot"] is not None and r["bone"] == r["bone"] and r["delta"] == 0.1 and r["R"] == 2391.0 and r["af"] == 20.0 and r["a_s"] == 18.0 and r["h"] == 2.0 and r["E"] == 155.0 and r["mu"] == 0.3
            and r["cycles"] == 2 and r["forced"] is None)


def partial_spearman(x, y, z):
    """Spearman of x and y after a straight-line fit on the ranks of z is taken out of both."""
    rx, ry, rz = rankdata(x), rankdata(y), rankdata(z)
    Z = np.c_[np.ones(len(z)), rz]
    ex = rx - Z @ np.linalg.lstsq(Z, rx, rcond=None)[0]
    ey = ry - Z @ np.linalg.lstsq(Z, ry, rcond=None)[0]
    return float(np.corrcoef(ex, ey)[0, 1])


def boot_partial(x, y, z, n=2000):
    idx = RNG.integers(0, len(x), size=(n, len(x)))
    vals = np.array([partial_spearman(x[i], y[i], z[i]) for i in idx])
    return float(np.percentile(vals, 5)), float(np.percentile(vals, 95))


def gp_fit(X, y):
    k = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=np.ones(X.shape[1]), length_scale_bounds=(0.05, 50.0), nu=2.5) + WhiteKernel(1e-2, (1e-5, 1.0))
    return GaussianProcessRegressor(kernel=k, normalize_y=True, n_restarts_optimizer=1, random_state=0).fit(X, y)


def cv_r2(X, y, kernel, seeds=(1, 2, 3)):
    out = []
    for s in seeds:
        pred = np.empty(len(y))
        for tr, te in KFold(10, shuffle=True, random_state=s).split(X):
            pred[te] = GaussianProcessRegressor(kernel=kernel, optimizer=None, normalize_y=True).fit(X[tr], y[tr]).predict(X[te])
        out.append(1 - ((pred - y) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    return float(np.mean(out))


def analyse(S, target, label):
    y = np.log10([r[target] for r in S]) if target != "contact" else np.array([r[target] for r in S], float)
    bone = np.array([r["bone"] for r in S])
    X = np.array([[r["u_" + k] for k in VARS] for r in S])
    full = gp_fit(X, y)
    r2 = cv_r2(X, y, full.kernel_)
    Xb = np.c_[X, (bone - bone.mean()) / bone.std()]
    fb = gp_fit(Xb, y)
    r2b = cv_r2(Xb, y, fb.kernel_)
    out = {"label": label, "target": target, "n": len(S), "y_sd": float(y.std()), "cv_r2_13": r2, "cv_r2_13_bone": r2b, "spearman_bone": float(spearmanr(bone, y)[0]), "vars": {}}
    for j, k in enumerate(VARS):
        x = X[:, j]
        keep = [i for i in range(X.shape[1]) if i != j]
        d = gp_fit(X[:, keep], y)
        out["vars"][k] = {"spearman": float(spearmanr(x, y)[0]), "partial": partial_spearman(x, y, bone), "partial_ci": boot_partial(x, y, bone), "spearman_bone": float(spearmanr(x, bone)[0]), "drop_r2": r2 - cv_r2(X[:, keep], y, d.kernel_)}
        lo, hi = np.percentile(x, [5, 95])
        pd_ = []
        for v in np.linspace(lo, hi, 9):
            T = X.copy()
            T[:, j] = v
            pd_.append(float(full.predict(T).mean()))
        out["vars"][k]["pd_swing"] = max(pd_) - min(pd_)
        out["vars"][k]["pd_end"] = pd_[-1] - pd_[0]
        out["vars"][k]["pd_lo_hi"] = [float(lo), float(hi)]
    for extra in ("A0", "e"):
        x = np.array([r[extra] for r in S], float)
        out["vars"][extra] = {"spearman": float(spearmanr(x, y)[0]), "partial": partial_spearman(x, y, bone), "partial_ci": boot_partial(x, y, bone), "spearman_bone": float(spearmanr(x, bone)[0])}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"H:/projects/Femoral implant generation/db3406/v0.9")
    a = ap.parse_args()
    rows = load(pathlib.Path(a.db))
    nom = [r for r in rows if nominal(r) and r["in_box"] and r["f1"] is not None and r["contact"] is not None]
    iid = [r for r in nom if r["unbiased"]]
    corner = [r for r in nom if r["layer"] in ("CR-1", "CR-T")]
    print("nominal in box", len(nom), "unbiased", len(iid), "unbiased m>=1", sum(r["m"] >= 0.999 for r in iid), "corner", len(corner))
    print("unbiased layers", {k: sum(r["layer"] == k for r in iid) for k in sorted({r["layer"] for r in iid})})
    res = {"export": a.db.replace("\\", "/").split("/")[-1], "n_rows": len(rows), "sets": {}}
    for label, S, t in (("全空间，转动", iid, "rot"), ("全空间，微动", iid, "f1"), ("全空间，接触面积", iid, "contact"), ("m ≥ 1.0，转动", [r for r in iid if r["m"] >= 0.999], "rot"), ("最优区角落，转动", corner, "rot")):
        o = analyse(S, t, label)
        res["sets"][label] = o
        print(f"\n== {label} n {o['n']} sd {o['y_sd']:.3f} CV R2 13var {o['cv_r2_13']:.3f} with bone {o['cv_r2_13_bone']:.3f} Spearman bone {o['spearman_bone']:+.3f}")
        ord_ = sorted(o["vars"], key=lambda k: -abs(o["vars"][k]["partial"]))
        for k in ord_:
            v = o["vars"][k]
            print(f"{NAME[k]:18s} rho {v['spearman']:+.2f} partial {v['partial']:+.2f} [{v['partial_ci'][0]:+.2f},{v['partial_ci'][1]:+.2f}] rho_bone {v['spearman_bone']:+.2f}" + (f" dropR2 {v['drop_r2']:+.3f} PDswing {v['pd_swing']:.3f} end {v['pd_end']:+.3f}" if "drop_r2" in v else ""))
    (HERE / "data/param_importance.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(HERE / "data/param_importance.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["set", "n", "cv_r2", "parameter", "spearman", "partial_with_bone_held", "partial_ci5", "partial_ci95", "spearman_with_bone", "drop_cv_r2", "pd_swing", "pd_end"])
        for label, o in res["sets"].items():
            for k, v in sorted(o["vars"].items(), key=lambda kv: -abs(kv[1]["partial"])):
                w.writerow([label, o["n"], round(o["cv_r2_13"], 3), NAME[k], round(v["spearman"], 3), round(v["partial"], 3), round(v["partial_ci"][0], 3), round(v["partial_ci"][1], 3), round(v["spearman_bone"], 3), round(v.get("drop_r2", float("nan")), 3), round(v.get("pd_swing", float("nan")), 3), round(v.get("pd_end", float("nan")), 3)])
    print("written data/param_importance.json, .csv")


if __name__ == "__main__":
    main()
