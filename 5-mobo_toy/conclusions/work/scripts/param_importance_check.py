"""Tests of the local importance results. Reads a db3406 export only; writes data/param_importance_check.json.

    python -X utf8 param_importance_check.py [--db <export dir>]

1. Leave out every same-shape scan around A, refit, and predict those FE rows, so the GP slopes meet FE they never saw.
2. A V shape around A in each variable, which a monotonic rank test cannot see: distance from A against rotation in the corner rows.
3. Which template quantity carries the fit in the corner rows, and the same with the 13 variables left out.
"""
import argparse
import csv
import json
import math
import pathlib
import warnings

import numpy as np
from scipy.stats import spearmanr

from param_importance import NAME, VARS, boot_partial, load, nominal, num, partial_spearman
from param_importance_local import DERIVED, LABEL, cv, gp

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent.parent
SCAN = ("WS m", "WS m2", "WS alpha", "WS m alpha", "W-0 alpha", "W-0 L", "WL-1", "OW-2", "OW-3")


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
    A = next(r for r in rows if r["job"] == "sb13_a105_91e458e3")
    uA = np.array([A["u_" + k] for k in VARS])
    cond = lambda r: r["status"] == "DONE" and r["rot"] is not None and r["delta"] == 0.1 and r["R"] == 2391.0 and r["af"] == 20.0 and r["a_s"] == 18.0 and r["h"] == 2.0 and r["E"] == 155.0 and r["mu"] == 0.3 and r["cycles"] == 2 and r["e"] == 0.0 and r["forced"] in (None, 0.0)  # noqa: E731
    base = [r for r in rows if cond(r) and r["in_box"] and r["rot"] < 1.0]
    train = [r for r in base if r["layer"] not in SCAN]
    scans = [r for r in rows if cond(r) and r["layer"] in SCAN and r["job"].startswith("db_ws_p13_a105")]
    X = np.array([[r["u_" + k] for k in VARS] for r in train])
    y = np.log10([r["rot"] for r in train])
    m = gp(X, y)
    r2, rmse = cv(X, y, m.kernel_)
    pA = float(m.predict(uA[None])[0])
    print(f"1. scans left out: train n {len(train)} CV R2 {r2:.3f} RMSE {rmse:.3f}; A pred {10 ** pA:.4f} FE {A['rot']:.4f}; length scales", {k: round(float(v), 2) for k, v in zip(VARS, m.kernel_.k1.k2.length_scale)})
    table = []
    for r in sorted(scans, key=lambda r: (r["m"], r["alpha"], r["L"])):
        u = np.array([min(1.2, r["u_" + k]) for k in VARS])
        p = float(m.predict(u[None])[0])
        table.append({"job": r["job"], "m": r["m"], "L": r["L"], "alpha": r["alpha"], "in_box": r["in_box"], "fe_dex": math.log10(r["rot"] / A["rot"]), "pred_dex": p - pA})
    inb = [t for t in table if t["in_box"]]
    fe, pr = np.array([t["fe_dex"] for t in inb]), np.array([t["pred_dex"] for t in inb])
    slope = float(np.polyfit(fe, pr, 1)[0])
    out["heldout"] = {"n_train": len(train), "cv_r2": r2, "cv_rmse": rmse, "n": len(inb), "rmse": float(np.sqrt(((fe - pr) ** 2).mean())), "bias": float((pr - fe).mean()), "slope": slope, "rows": table}
    print(f"   held-out same-shape FE rows in box n {len(inb)}: RMSE {out['heldout']['rmse']:.3f} dex, bias {out['heldout']['bias']:+.3f}, slope pred on FE {slope:.2f}")
    for t in table:
        print(f"   m {t['m']:.2f} L {t['L']:.2f} a {t['alpha']:.1f} box {t['in_box']} FE {t['fe_dex']:+.3f} pred {t['pred_dex']:+.3f}")
    print("   local steps, scans left out, around A and at A m 1.0")
    out["local_heldout"] = {}
    u1 = uA.copy()
    u1[VARS.index("m")] = 1 / 3
    for name, u0 in (("A", uA), ("A，m 1.0", u1)):
        p0 = float(m.predict(u0[None])[0])
        o = {}
        for j, k in enumerate(VARS):
            d = {}
            for s in (-1, 1):
                u = u0.copy()
                u[j] += s * 0.1
                if -1e-9 <= u[j] <= 1 + 1e-9:
                    d[str(s)] = float(m.predict(u[None])[0]) - p0
            o[k] = d
            print(f"   {name:9s} {NAME[k]:18s} " + " ".join(f"{s}0.1u {v:+.3f}" for s, v in d.items()))
        out["local_heldout"][name] = o

    corner = [r for r in rows if nominal(r) and r["in_box"] and r["layer"] in ("CR-1", "CR-T")]
    yc = np.log10([r["rot"] for r in corner])
    bone = np.array([r["bone"] for r in corner])
    print("\n2. distance from A in each variable against rotation, corner rows, bone held out, n", len(corner))
    out["v_shape"] = {}
    for j, k in enumerate(VARS):
        x = np.abs(np.array([r["u_" + k] for r in corner]) - uA[j])
        ci = boot_partial(x, yc, bone)
        out["v_shape"][k] = {"u_A": float(uA[j]), "partial": partial_spearman(x, yc, bone), "ci": ci}
    for k, v in sorted(out["v_shape"].items(), key=lambda kv: -abs(kv[1]["partial"])):
        print(f"   {NAME[k]:18s} u_A {v['u_A']:.2f} partial {v['partial']:+.2f} [{v['ci'][0]:+.2f},{v['ci'][1]:+.2f}]")
    near = sorted([r for r in rows if cond(r) and r["layer"] not in SCAN and r["in_box"]], key=lambda r: r["rot"])[:20]
    gm = np.array([r["g_ml"] for r in near])
    print("   gamma_ml of the 20 best e 0 designs: A", round(A["g_ml"], 3), "min", round(float(gm.min()), 3), "median", round(float(np.median(gm)), 3), "max", round(float(gm.max()), 3), "; box 0.35 to 0.65")
    out["g_ml_top20"] = {"A": A["g_ml"], "min": float(gm.min()), "median": float(np.median(gm)), "max": float(gm.max())}

    print("\n3. template quantities in the corner rows")
    F = ["tpl_A0", "tpl_e", "tpl_s_bind", "foam_thk_p50_mm", "area_foam_lt1_mm2"]
    T = np.array([[r[k] for k in F] for r in corner], float)
    T = (T - T.mean(0)) / T.std(0)
    U = np.array([[r["u_" + k] for k in VARS] for r in corner])
    res = {}
    for lab, M in (("u13", U), ("u13 + 5 template", np.c_[U, T]), ("5 template only", T)):
        g = gp(M, yc)
        res[lab] = cv(M, yc, g.kernel_)
        print(f"   {lab:18s} CV R2 {res[lab][0]:.3f} RMSE {res[lab][1]:.3f}")
    allr = res["u13 + 5 template"][0]
    res["drop"] = {}
    for i, k in enumerate(F):
        M = np.c_[U, np.delete(T, i, axis=1)]
        g = gp(M, yc)
        res["drop"][k] = allr - cv(M, yc, g.kernel_)[0]
        print(f"   drop {LABEL[k]:16s} CV R2 falls {res['drop'][k]:+.3f}")
    print("   Spearman between them:", {f"{LABEL[F[i]]} / {LABEL[F[j]]}": round(float(spearmanr(T[:, i], T[:, j])[0]), 2) for i in range(len(F)) for j in range(i + 1, len(F)) if abs(spearmanr(T[:, i], T[:, j])[0]) > 0.5})
    out["corner_template"] = res
    (HERE / "data/param_importance_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written data/param_importance_check.json")


if __name__ == "__main__":
    main()
