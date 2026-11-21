"""Importance near the best designs, where L, alpha and h_cut are already at their limits. Reads a db3406 export only; writes data/param_importance_local.json.

    python -X utf8 param_importance_local.py [--db <export dir>]

Two parts. Template quantities inside the corner box, sampled without looking at results. One-at-a-time GP predictions around A and A at m 1.0, trained on baseline rows that keep the templated offset 0 and rotate under a limit, so the steps do not cross an offset jump.
These rows include optimiser picks, so the GP part is a surrogate estimate; the same-shape FE scans for m, L and alpha are printed beside it as the check.
"""
import argparse
import csv
import json
import math
import pathlib
import warnings

import numpy as np
from scipy.stats import spearmanr
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.model_selection import KFold

from param_importance import NAME, VARS, boot_partial, load, nominal, num, partial_spearman

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent.parent
DERIVED = ("tpl_A0", "tpl_e", "tpl_s_bind", "tpl_contact", "tpl_margin", "e_margin", "foam_thk_p05_mm", "foam_thk_p50_mm", "area_foam_lt1_mm2")
LABEL = {"tpl_A0": "肩面积 A0", "tpl_e": "入口偏移 e", "tpl_s_bind": "卡点位置 s", "tpl_contact": "模板接触量", "tpl_margin": "模板余量", "e_margin": "离偏移跳变的距离", "foam_thk_p05_mm": "泡沫厚度 P05", "foam_thk_p50_mm": "泡沫厚度中位", "area_foam_lt1_mm2": "泡沫 < 1 mm 的面积"}
W = "db_ws_p13_a105_91e458e3_"


def gp(X, y):
    k = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(length_scale=np.ones(X.shape[1]), length_scale_bounds=(0.05, 50.0), nu=2.5) + WhiteKernel(1e-3, (1e-6, 1.0))
    return GaussianProcessRegressor(kernel=k, normalize_y=True, n_restarts_optimizer=1, random_state=0).fit(X, y)


def cv(X, y, kernel):
    pred = np.empty(len(y))
    for tr, te in KFold(10, shuffle=True, random_state=1).split(X):
        pred[te] = GaussianProcessRegressor(kernel=kernel, optimizer=None, normalize_y=True).fit(X[tr], y[tr]).predict(X[te])
    return float(1 - ((pred - y) ** 2).sum() / ((y - y.mean()) ** 2).sum()), float(np.sqrt(((pred - y) ** 2).mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"H:/projects/Femoral implant generation/db3406/v0.9")
    a = ap.parse_args()
    db = pathlib.Path(a.db)
    rows = load(db)
    extra = {r["job_id"]: {k: num(r[k]) for k in DERIVED} for r in csv.DictReader(open(db / "scalars.csv", encoding="utf-8"))}
    for r in rows:
        r.update(extra[r["job"]])
    out = {"export": db.name}

    corner = [r for r in rows if nominal(r) and r["in_box"] and r["layer"] in ("CR-1", "CR-T")]
    y = np.log10([r["rot"] for r in corner])
    bone = np.array([r["bone"] for r in corner])
    print("corner n", len(corner), "sd", round(float(y.std()), 3))
    out["corner"] = {"n": len(corner), "sd": float(y.std()), "derived": {}}
    for k in DERIVED:
        ok = [i for i, r in enumerate(corner) if r[k] is not None]
        x = np.array([corner[i][k] for i in ok], float)
        if len(set(x)) < 4:
            continue
        ci = boot_partial(x, y[ok], bone[ok])
        out["corner"]["derived"][k] = {"n": len(ok), "spearman": float(spearmanr(x, y[ok])[0]), "partial": partial_spearman(x, y[ok], bone[ok]), "ci": ci}
    for k, v in sorted(out["corner"]["derived"].items(), key=lambda kv: -abs(kv[1]["partial"])):
        print(f"  {LABEL[k]:16s} n {v['n']} rho {v['spearman']:+.2f} partial {v['partial']:+.2f} [{v['ci'][0]:+.2f},{v['ci'][1]:+.2f}]")
    by_e = {}
    for r in corner:
        by_e.setdefault(r["e"], []).append(r["rot"])
    out["corner"]["by_e"] = {str(k): {"n": len(v), "median_rot": float(np.median(v))} for k, v in sorted(by_e.items())}
    print("  by templated e", {k: (v["n"], round(v["median_rot"], 3)) for k, v in out["corner"]["by_e"].items()})
    U = np.array([[r["u_" + k] for k in VARS] for r in corner])
    k0 = gp(U, y)
    r0 = cv(U, y, k0.kernel_)
    tf = [k for k in ("tpl_A0", "tpl_e", "tpl_s_bind", "e_margin", "foam_thk_p50_mm", "area_foam_lt1_mm2") if all(r[k] is not None for r in corner)]
    T = np.array([[r[k] for k in tf] for r in corner], float)
    T = (T - T.mean(0)) / T.std(0)
    k1 = gp(np.c_[U, T], y)
    r1 = cv(np.c_[U, T], y, k1.kernel_)
    out["corner"]["cv"] = {"u13": r0, "u13_plus": r1, "features": tf}
    print("  corner GP CV R2, RMSE: u13", np.round(r0, 3), "u13 + template", np.round(r1, 3), tf)

    centres = {"A": next(r for r in rows if r["job"] == "sb13_a105_91e458e3"), "A，m 1.0": next(r for r in rows if r["job"].startswith(W + "m1_2a79"))}
    fe = {("A", "m", 1): ("m 0.5 到 0.75，+0.25 mm", 0.094, 0.25 / 1.5), ("A，m 1.0", "m", 1): ("m 1.0 到 1.5，+0.5 mm", math.log10(0.1047 / 0.0593), 0.5 / 1.5), ("A", "L", -1): ("L 43.06 到 42.5，−0.56 mm", 0.030, 0.56 / 25),
          ("A", "L", 1): ("L 43.06 到 44.5，+1.44 mm", -0.075, 1.44 / 25), ("A，m 1.0", "L", 1): ("L 43.06 到 44，+0.94 mm", -0.036, 0.94 / 25)}
    out["local"] = {}
    for limit in (1.0, 0.3):
        S = [r for r in rows if r["status"] == "DONE" and r["rot"] is not None and r["delta"] == 0.1 and r["R"] == 2391.0 and r["af"] == 20.0 and r["a_s"] == 18.0 and r["h"] == 2.0 and r["E"] == 155.0 and r["mu"] == 0.3 and r["cycles"] == 2
             and r["e"] == 0.0 and r["forced"] in (None, 0.0) and r["in_box"] and r["rot"] < limit]
        X = np.array([[r["u_" + k] for k in VARS] for r in S])
        y = np.log10([r["rot"] for r in S])
        m = gp(X, y)
        r2, rmse = cv(X, y, m.kernel_)
        print(f"\nlocal GP rot < {limit}: n {len(S)} sd {y.std():.3f} CV R2 {r2:.3f} RMSE {rmse:.3f} dex; length scales", dict(zip(VARS, np.round(m.kernel_.k1.k2.length_scale, 2))))
        rec = {"n": len(S), "cv_r2": r2, "cv_rmse": rmse, "length_scale": dict(zip(VARS, m.kernel_.k1.k2.length_scale.tolist())), "centres": {}}
        for name, c in centres.items():
            u0 = np.array([c["u_" + k] for k in VARS])
            p0 = float(m.predict(u0[None])[0])
            print(f" {name}: u pred {10 ** p0:.4f} FE {c['rot']:.4f}")
            rec["centres"][name] = {"pred": 10 ** p0, "fe": c["rot"], "vars": {}}
            for j, k in enumerate(VARS):
                d = {}
                for sgn in (-1, 1):
                    u = u0.copy()
                    u[j] += sgn * 0.1
                    if not (-1e-9 <= u[j] <= 1 + 1e-9):
                        continue
                    d[sgn] = float(m.predict(u[None])[0]) - p0
                rec["centres"][name]["vars"][k] = {str(s): v for s, v in d.items()}
                f = [fe[(name, k, s)] for s in (-1, 1) if (name, k, s) in fe]
                print(f"  {NAME[k]:18s} u0 {u0[j]:.2f} -0.1u {d.get(-1, float('nan')):+.3f} +0.1u {d.get(1, float('nan')):+.3f}" + "".join(f" | FE {t[0]} {t[1]:+.3f} = {t[1] / t[2] * 0.1:+.3f} per 0.1u" for t in f))
        out["local"][str(limit)] = rec
    (HERE / "data/param_importance_local.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written data/param_importance_local.json")


if __name__ == "__main__":
    main()
