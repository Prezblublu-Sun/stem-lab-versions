"""R2 (second round of b28): pick 16 rows around 3b. Local, 0 FE.

    python -X utf8 select_r2.py top        writes data/r2_tol_list.csv (the best 40 for the placement check)
    python -X utf8 select_r2.py final      after data/tol_r2.json; writes data/r2_rows.json and prints the power of G49 / G50

Model: the b28 micromotion GP refitted with the 14 b28 rows that have FE micromotion (db3406 v0.12), uncertainty factor from b28's calibration.
Scores, against the A family curve at the same bone removed (same as b28's G41):
  P(improves on 3b): (dF >= dF3b + 3 mm and dl <= dl3b + log10 1.05)  or  (dl <= dl3b - 0.05 and dF >= dF3b - 2 mm), dF3b = +9.68 mm, dl3b = -0.0738 dex (FE)
  P(beats A): b28's two routes.
12 rows by largest P(improves on 3b), 4 rows by largest uncertainty among P(beats A) >= 0.3; all placement-checked; pairwise distance >= 0.05 in (u13, e / 3).
"""
import csv
import json
import math
import pathlib
import sys

import numpy as np
from scipy.stats import norm

HERE = pathlib.Path(__file__).resolve().parent
B28P = HERE.parent / "b28_fam" / "prep"
sys.path.insert(0, str(B28P))
import select_b28 as S  # noqa: E402

DF3, DL3 = 9.68, -0.0738
IMP_F, IMP_L, IMP_L2, IMP_F2 = 3.0, math.log10(1.05), 0.05, 2.0
V12 = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.12")


def p_improve(dF, sdF, dl, sdl):
    a1 = norm.sf((DF3 + IMP_F - dF) / sdF) * norm.cdf((DL3 + IMP_L - dl) / sdl)
    a2 = norm.cdf((DL3 - IMP_L2 - dl) / sdl) * norm.sf((DF3 - IMP_F2 - dF) / sdF)
    both = norm.sf((DF3 + IMP_F - dF) / sdF) * norm.cdf((DL3 - IMP_L2 - dl) / sdl)
    return a1 + a2 - both


def main():
    mode = sys.argv[1]
    R, J, U, X, y, rot, tspec, Fm, fastF, m_ = S.load_training()
    mask = rot <= 2.0
    info = json.load(open(S.D / "model.json", encoding="utf-8"))
    slope, icpt = info["fastF_to_mesh"]
    cb, cF, cl = (np.array(info["curve"][k]) for k in ("bone", "F", "logf1"))
    # b28 rows: features from the b28 candidate geometry, labels from v0.12
    sc = {r["tag"]: r for r in csv.DictReader(open(V12 / "scalars.csv", encoding="utf-8"))}
    fam = json.load(open(S.D / "fam1_rows.json", encoding="utf-8"))
    geo = {"ring": np.load(S.D / "geom_ring_v11.npz"), "egrid": np.load(S.D / "geom_egrid_v11.npz")}
    Xb, yb, Ub = [], [], []
    for r in fam:
        t = sc.get(f"fam1_{r['label']}_e{r['e']:+g}")
        if t is None or t["status"] != "DONE":
            continue
        g = geo[r["src"]]
        i = r["src_idx"]
        ok = np.zeros(len(g["ok"]), bool)
        ok[i] = True
        Xb.append(S.feat(g, g["u13"][ok], ok)[0])
        yb.append(math.log10(float(t["f1_p95_um"])))
        Ub.append(g["u13"][i])
    Xt = np.vstack([X[mask], np.array(Xb)])
    yt = np.r_[y[mask], yb]
    Ut = np.vstack([U[mask], np.array(Ub)])
    gp, mu, sd = S.fit_gp(Xt, yt)
    print("training rows", len(yt), "of which b28", len(yb), flush=True)
    g = np.load(HERE / "data" / "geom_r2.npz")
    ok = g["ok"] & np.isfinite(g["F"]) & np.isfinite(g["bone"])
    idx = np.flatnonzero(ok)
    Uc, Ec = g["u13"][ok], g["e"][ok]
    Xc = S.feat(g, Uc, ok)
    pm, ps = gp.predict((Xc - mu) / sd, return_std=True)
    psc = ps * S.factor_of(info["calibration"], S.nn_dist(Uc, Ut))
    bone = g["bone"][ok] / 1000
    inb = (bone >= cb[0]) & (bone <= cb[-1])
    Fc = slope * g["F"][ok] + icpt
    dF = Fc - np.interp(bone, cb, cF)
    dl = pm - np.interp(bone, cb, cl)
    sdF = info["fastF_resid_sd"]
    Pi = np.where(inb, p_improve(dF, sdF, dl, psc), 0.0)
    Pa = np.where(inb, S.p_beat(dF, sdF, dl, psc), 0.0)
    print(f"candidates {len(idx)}, in the curve range {int(inb.sum())}; P(improves on 3b) max {Pi.max():.3f}, n > 0.3 {int((Pi > 0.3).sum())}; P(beats A) > 0.5 {int((Pa > 0.5).sum())}", flush=True)
    if mode == "top":
        top = np.argsort(-Pi)[:80]            # 11-08: 30 + 10 gave only 12 that pass the placement check, so 80 + 20
        ex = np.flatnonzero((Pa >= 0.3) & ~np.isin(np.arange(len(Pa)), top))
        ex = ex[np.argsort(-psc[ex])][:20]
        with open(HERE / "data" / "r2_tol_list.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["src", "src_idx", "e", "kind", *S.U_COLS])
            for k, kind in [(k, "improve") for k in top] + [(k, "explore") for k in ex]:
                w.writerow(["r2", int(idx[k]), float(Ec[k]), kind, *[repr(float(v)) for v in Uc[k]]])
        np.savez_compressed(HERE / "data" / "r2_scored.npz", idx=idx, U=Uc, e=Ec, pm=pm, psc=psc, dF=dF, dl=dl, Pi=Pi, Pa=Pa, bone=bone, Fc=Fc)
        print("placement list", len(top) + len(ex))
        return
    tol = {(str(t["src_idx"]), round(float(t["e"]), 3)): t for t in json.load(open(HERE / "data" / "tol_r2.json", encoding="utf-8"))}
    lst = list(csv.DictReader(open(HERE / "data" / "r2_tol_list.csv", encoding="utf-8")))
    pos = {int(i): k for k, i in enumerate(idx)}
    passed = [(r["kind"], pos[int(r["src_idx"])]) for r in lst if tol.get((r["src_idx"], round(float(r["e"]), 3)), {}).get("ok")]
    print("placement passed", len(passed), "of", len(lst))
    Ue = np.c_[Uc, Ec / 3.0]
    picks = []
    for kind, n_want, key in (("improve", 12, lambda k: -Pi[k]), ("explore", 4, lambda k: -psc[k])):
        for _, k in sorted([p for p in passed if p[0] == kind], key=lambda p: key(p[1])):
            if len([p for p in picks if p[0] == kind]) >= n_want:
                break
            if all(np.linalg.norm(Ue[k] - Ue[j]) >= 0.05 for _, j in picks):
                picks.append((kind, k))
    if len(picks) < 16:   # fill from the improve list if the explore list ran short
        for _, k in sorted([p for p in passed if p[0] == "improve"], key=lambda p: -Pi[p[1]]):
            if len(picks) >= 16:
                break
            if all(np.linalg.norm(Ue[k] - Ue[j]) >= 0.05 for _, j in picks):
                picks.append(("improve", k))
    out = []
    for n, (kind, k) in enumerate(picks, 1):
        t = tol[(str(idx[k]), round(float(Ec[k]), 3))]
        out.append({"label": f"r2_{n:02d}", "kind": kind, "e": float(Ec[k]), "A0": float(t["A0"]), "bone_mm3": float(t["bone_mm3"]), "u13": Uc[k].tolist(),
                    "dist_3b": float(np.linalg.norm(Uc[k] - np.array(json.load(open(HERE / 'data' / 'inputs.json'))["u3b"]))),
                    "pred_log_f1": float(pm[k]), "pred_sd_cal": float(psc[k]), "pred_F_mm": float(Fc[k]), "pred_dF": float(dF[k]), "pred_dl": float(dl[k]), "P_improve": float(Pi[k]), "P_beatA": float(Pa[k])})
        print(f"{out[-1]['label']} {kind:7s} e {Ec[k]:+.1f} bone {bone[k]:.2f} dF {dF[k]:+.1f} dl {dl[k]:+.3f} sd {psc[k]:.3f} P_imp {Pi[k]:.2f} P_A {Pa[k]:.2f} d3b {out[-1]['dist_3b']:.3f}")
    json.dump(out, open(HERE / "data" / "r2_rows.json", "w", encoding="utf-8"), indent=1)
    ii = np.array([k for _, k in picks])
    rng = np.random.default_rng(56203)
    n = 40000
    tF = dF[ii] + sdF * rng.standard_normal((n, len(ii))) + 0.6 * rng.standard_normal((n, len(ii)))
    tl = dl[ii] + psc[ii] * rng.standard_normal((n, len(ii))) + 0.012 * rng.standard_normal((n, len(ii)))
    imp = ((tF >= DF3 + IMP_F) & (tl <= DL3 + IMP_L)) | ((tl <= DL3 - IMP_L2) & (tF >= DF3 - IMP_F2))
    beat = ((tF >= 5) & (tl <= math.log10(1.05))) | ((tl <= math.log10(0.8)) & (tF >= -2))
    print(f"power if the model is right: P(G49 PASS) {np.mean(imp.any(1)):.3f}; P(G50 PASS, >= 4 beat A) {np.mean(beat.sum(1) >= 4):.3f}; expected rows beating A {beat.sum(1).mean():.1f}")


if __name__ == "__main__":
    main()
