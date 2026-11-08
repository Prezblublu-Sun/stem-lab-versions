"""b28 0 FE preparation, steps 3.3 to 3.4 and the first pass of 4: families, micromotion model with distance-calibrated uncertainty, scores by the G41 rule.

    python -X utf8 select_b28.py first     families, model, scores; writes data/shortlist_e.csv (designs that get the e grid) and data/model.json
    python -X utf8 select_b28.py final     after the e grid and the placement check; writes data/picks.csv and data/power.json

Everything is read only on db3406 v0.11 and on the geometry files that run_prep.sh wrote (copied into data/).
Objectives are the ones G41 judges: F on the new axis at mesh scale, stair micromotion f1_p95_um, bone_total_mm3. "Beats A" = route 1 (F >= A + 5 mm and
micromotion <= 1.05 x A) or route 2 (micromotion <= 0.80 x A and F >= A - 2 mm), against the A family curve at the same bone removed.
"""
import csv
import glob
import json
import math
import pathlib
import sys
import warnings

import numpy as np
from scipy.stats import norm
from sklearn.cluster import KMeans
from sklearn.gaussian_process import GaussianProcessRegressor as GPR
from sklearn.gaussian_process.kernels import ConstantKernel as CK
from sklearn.gaussian_process.kernels import Matern, WhiteKernel

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parent
D = HERE / "data"
DB = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/v0.11")
U_COLS = ["u_L", "u_alpha", "u_h_cut", "u_m", "u_rho_tip", "u_q", "u_lam", "u_g_ml", "u_g_ap", "u_n_a", "u_n_p", "u_tau_a", "u_tau_p"]
B1_G = ("A0", "e", "volume", "geo_area", "near_area", "mean_wall", "F", "F_A", "S_all", "S_z15", "t_min", "s_bind", "contact")
B1_LOG = ("R_fnd", "R_spin", "R_tilt", "Kr_axis", "Kr_min", "Kt_all")
N3 = np.array([0.381, 0.025, -0.924])
U_NECK = np.array([0.92228, 0.06137, 0.38162]) / np.linalg.norm([0.92228, 0.06137, 0.38162])
CREF = np.array([37.65271204198696, 0.8509371708090849, 41.89415555538172])
T = "db_ws_p13_a105_91e458e3_"
CURVE = (T + "ow_m1_e+2.5_8a2bd628", T + "ow_m1_e+2_c9ca96c8", T + "ow_m1_e+1.5_52dc478a", T + "ow_m1_e+1_fea69910", T + "ow_m1_e+0.5_c17f7b2a", T + "m1_2a79b613", T + "ow_m1_e-0.5_03b0a7bc")
DF1, R1, R2, DF2 = 5.0, math.log10(1.05), math.log10(0.80), -2.0     # G41 routes
K_FAM, RING, BATCH_DIST, SEED = 5, (0.25, 0.75), 0.15, 56102   # 11-07: ring 0.25 to 0.75 from A; FE rows beyond 0.75 already show micromotion >= 3.8 x the A family
UM1 = 1.0 / 3.0


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else math.nan
    except (TypeError, ValueError):
        return math.nan


def feat(z, U, ok=None):
    sel = slice(None) if ok is None else ok
    return np.c_[U, *[z[c][sel] for c in B1_G], *[np.log10(np.maximum(z[c][sel], 1e-9)) for c in B1_LOG]]


def mesh_F(want):
    out = {}
    for p in sorted(glob.glob(str(DB / "fields" / "iface_*.npz"))):
        z = np.load(p, allow_pickle=False)
        jobs = [str(j) for j in z["job_id"]]
        if not want & set(jobs):
            continue
        off, frame, X_, ar, dc, co = z["off"], z["frame"], z["X"], z["area"], z["d_canal"], z["collar"]
        for j, job in enumerate(jobs):
            if job not in want:
                continue
            a, b = off[j], off[j + 1]
            body = ~co[a:b]
            X, w, t = X_[a:b][body], ar[a:b][body], -dc[a:b][body]
            P0, ax = frame[j, 0], frame[j, 1]
            q = X - P0
            rad = q - (q @ ax)[:, None] * ax
            em = N3 - (N3 @ ax) * ax
            em /= np.linalg.norm(em)
            ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
            ep /= np.linalg.norm(ep)
            th = np.degrees(np.arctan2(rad @ ep, rad @ em))
            m = (-(X - CREF) @ U_NECK <= 15) & (np.abs(th) <= 45)
            out[job] = float((w[m] / np.maximum(t[m], 0.25)).sum())
    return out


def p_beat(dF, sdF, dl, sdl):
    """P(route 1 or route 2) for F - A_F ~ N(dF, sdF), log f1 - A_l ~ N(dl, sdl), independent."""
    pY2, pY1 = norm.cdf((R2 - dl) / sdl), norm.cdf((R1 - dl) / sdl)
    pX2, pX1 = norm.sf((DF2 - dF) / sdF), norm.sf((DF1 - dF) / sdF)
    return pY2 * pX2 + np.maximum(pY1 - pY2, 0) * pX1


def load_training():
    R = {r["job_id"]: r for r in csv.DictReader(open(DB / "scalars.csv", encoding="utf-8"))}
    g = np.load(D / "geom_base_v11.npz")
    jobs = [str(j) for j in g["job"]]
    ok = g["ok"] & np.array([j in R for j in jobs])
    J = [j for j, o in zip(jobs, ok) if o]
    U = np.array([[num(R[j][c]) for c in U_COLS] for j in J])
    X = feat(g, U, ok)
    y = np.log10([num(R[j]["f1_p95_um"]) for j in J])
    rot = np.array([num(R[j]["rot_first_deg"]) for j in J])
    tspec = np.array([R[j]["t_spec_utc"] or "" for j in J])
    Fm = mesh_F(set(J) | set(CURVE))
    fastF = g["F"][ok]
    m_ = np.array([num(R[j]["m"]) for j in J])
    return R, J, U, X, y, rot, tspec, Fm, fastF, m_


def fit_gp(X, y):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    k = CK(1.0, (1e-2, 1e2)) * Matern(np.ones(X.shape[1]) * 2.0, (0.2, 200.0), nu=2.5) + WhiteKernel(1e-3, (1e-6, 1e-1))
    gp = GPR(k, normalize_y=True, n_restarts_optimizer=1, random_state=0).fit((X - mu) / sd, y)
    return gp, mu, sd


def nn_dist(A, B):
    out = np.empty(len(A))
    for i0 in range(0, len(A), 2000):
        out[i0:i0 + 2000] = np.linalg.norm(A[i0:i0 + 2000, None, :] - B[None, :, :], axis=2).min(1)
    return out


def calibrate(U, X, y):
    """Leave one design cluster out (8 clusters in u13). Returns bins of nearest-neighbour distance to the training designs and the factor that brings 90 % coverage to 0.9 in each."""
    lab = KMeans(8, n_init=10, random_state=SEED).fit_predict(U)
    z, d = [], []
    for c in range(8):
        tr, te = lab != c, lab == c
        gp, mu, sd = fit_gp(X[tr], y[tr])
        m, s = gp.predict((X[te] - mu) / sd, return_std=True)
        z += list(np.abs(y[te] - m) / s)
        d += list(nn_dist(U[te], U[tr]))
    z, d = np.array(z), np.array(d)
    edges = np.quantile(d, [0, 0.25, 0.5, 0.75, 1.0])
    fac = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        k = (d >= lo) & (d <= hi)
        fac.append(max(1.0, float(np.quantile(z[k], 0.9) / 1.645)))
    return {"edges": edges.tolist(), "factor": fac, "n": int(len(z)), "cover90_raw": float(np.mean(z <= 1.645))}


def factor_of(cal, d):
    e, f = np.array(cal["edges"]), np.array(cal["factor"])
    i = np.clip(np.searchsorted(e, d, side="right") - 1, 0, len(f) - 1)
    return f[i]


def candidates():
    C = {"U": [], "e": [], "X": [], "F": [], "bone": [], "src": [], "idx": []}
    for name, fn in (("new", "geom_new_v11.npz"), ("pool65k", "geom_pool65k_v11.npz"), ("ring", "geom_ring_v11.npz"), ("egrid", "geom_egrid_v11.npz")):
        if not (D / fn).exists():
            continue
        g = np.load(D / fn)
        ok = g["ok"] & np.isfinite(g["F"]) & np.isfinite(g["bone"]) & np.isfinite(g["s_bind"])
        U = g["u13"]
        ok &= U[:, 3] >= UM1 - 1e-9
        C["U"].append(U[ok]); C["e"].append(g["e"][ok]); C["X"].append(feat(g, U[ok], ok)); C["F"].append(g["F"][ok]); C["bone"].append(g["bone"][ok] / 1000)
        C["src"].append(np.full(int(ok.sum()), name)); C["idx"].append(np.flatnonzero(ok))
        print(name, "points", len(ok), "usable m>=1", int(ok.sum()), flush=True)
    return {k: np.concatenate(v) for k, v in C.items()}


def main():
    mode = sys.argv[1]
    R, J, U, X, y, rot, tspec, Fm, fastF, m_ = load_training()
    mask = rot <= 2.0
    # fast F -> mesh F, new axis, rows m >= 1 with f1 < 40 um
    k_ = (m_ >= 0.999) & (10 ** y < 40) & np.array([j in Fm for j in J])
    xf, yf = fastF[k_], np.array([Fm[j] for j, kk in zip(J, k_) if kk])
    slope, icpt = np.polyfit(xf, yf, 1)
    resid_sd = float(np.std(yf - (slope * xf + icpt), ddof=2))
    # the A family curve, new-axis mesh F
    cb = np.array([num(R[j]["bone_total_mm3"]) / 1000 for j in CURVE])
    cF = np.array([Fm[j] for j in CURVE])
    cl = np.log10([num(R[j]["f1_p95_um"]) for j in CURVE])
    o = np.argsort(cb)
    cb, cF, cl = cb[o], cF[o], cl[o]
    gp, mu, sd = fit_gp(X[mask], y[mask])
    cal = calibrate(U[mask], X[mask], y[mask])
    # forward check, the way the 0.148 dex was measured: early 60 % by spec time predicts the rest
    order = np.argsort(tspec[mask])
    n60 = int(0.6 * mask.sum())
    tr_, te_ = order[:n60], order[n60:]
    g2, mu2, sd2 = fit_gp(X[mask][tr_], y[mask][tr_])
    m2, s2 = g2.predict((X[mask][te_] - mu2) / sd2, return_std=True)
    d2 = nn_dist(U[mask][te_], U[mask][tr_])
    s2c = s2 * factor_of(cal, d2)
    fwd = {"rmse": float(np.sqrt(np.mean((m2 - y[mask][te_]) ** 2))), "cover90_raw": float(np.mean(np.abs(y[mask][te_] - m2) <= 1.645 * s2)), "cover90_cal": float(np.mean(np.abs(y[mask][te_] - m2) <= 1.645 * s2c))}
    print("fastF->mesh", round(slope, 4), round(icpt, 2), "resid sd", round(resid_sd, 2), "| calibration", cal, "| forward", fwd, flush=True)
    C = candidates()
    uA = np.array(json.load(open(D / "inputs.json"))["uA"])
    dA = np.linalg.norm(C["U"] - uA, axis=1)
    Fc = slope * C["F"] + icpt
    keep = (dA >= RING[0]) & (dA <= RING[1]) & (C["bone"] >= cb[0]) & (C["bone"] <= cb[-1]) & (C["e"] >= -1.0 - 1e-9) & (C["e"] <= 2.5 + 1e-9)
    for k in C:
        C[k] = C[k][keep]
    Fc, dA = Fc[keep], dA[keep]
    pm, ps = np.zeros(len(Fc)), np.zeros(len(Fc))
    for i0 in range(0, len(Fc), 3000):
        pm[i0:i0 + 3000], ps[i0:i0 + 3000] = gp.predict((C["X"][i0:i0 + 3000] - mu) / sd, return_std=True)
    dtr = nn_dist(C["U"], U[mask])
    psc = ps * factor_of(cal, dtr)
    dF = Fc - np.interp(C["bone"], cb, cF)
    dl = pm - np.interp(C["bone"], cb, cl)
    P = p_beat(dF, resid_sd, dl, psc)
    # families: directions away from A of the ring designs (unit vectors of u13 - uA)
    Ud, inv = np.unique(np.round(C["U"], 9), axis=0, return_inverse=True)
    dirs = (Ud - uA) / np.linalg.norm(Ud - uA, axis=1, keepdims=True)
    km = KMeans(K_FAM, n_init=10, random_state=SEED).fit(dirs)
    fam = km.labels_[inv]
    for f_ in range(K_FAM):
        c_ = km.cluster_centers_[f_]
        top = np.argsort(-np.abs(c_))[:3]
        print(f"family {f_} direction: " + ", ".join(f"{U_COLS[t]} {c_[t]:+.2f}" for t in top), flush=True)
    print("candidates kept", len(Fc), "designs", len(Ud), "per family", np.bincount(fam).tolist(), flush=True)
    for f_ in range(K_FAM):
        k = fam == f_
        i = np.where(k)[0][np.argmax(P[k])]
        print(f"family {f_}: n {int(k.sum())}, median dist A {np.median(dA[k]):.2f}, P(beat) max {P[i]:.3f} at bone {C['bone'][i]:.2f} F {Fc[i]:.1f} (A {np.interp(C['bone'][i], cb, cF):.1f}) f1 {10 ** pm[i]:.1f} (A {10 ** np.interp(C['bone'][i], cb, cl):.1f}) sd {psc[i]:.3f} e {C['e'][i]:+.1f}; "
              f"best dF {dF[k].max():+.1f}; best dl {dl[k].min():+.3f}", flush=True)
    json.dump({"fastF_to_mesh": [float(slope), float(icpt)], "fastF_resid_sd": resid_sd, "calibration": cal, "forward": fwd, "n_train": int(mask.sum()),
               "curve": {"bone": cb.tolist(), "F": cF.tolist(), "logf1": cl.tolist()}, "fam_centers": km.cluster_centers_.tolist()}, open(D / "model.json", "w", encoding="utf-8"), indent=1)
    np.savez_compressed(D / f"scored_{mode}.npz", U=C["U"], e=C["e"], src=C["src"], idx=C["idx"], F=Fc, bone=C["bone"], pm=pm, ps=ps, psc=psc, dF=dF, dl=dl, P=P, fam=fam, dA=dA, dtr=dtr)
    key = np.c_[np.round(C["U"], 9), np.round(C["e"], 3)]
    _, first_of = np.unique(key, axis=0, return_index=True)
    uniq = np.zeros(len(P), bool)
    uniq[first_of] = True                     # one entry per (design, e); ring and egrid overlap at e 0, 1, 2
    Ue = np.c_[C["U"], C["e"] / 3.0]
    if mode == "tol":
        out = []
        for f_ in range(K_FAM):
            k = np.where((fam == f_) & uniq)[0]
            top = k[np.argsort(-P[k])][:30]
            ex = k[(dF[k] >= -10) & ~np.isin(k, top)]
            ex = ex[np.argsort(-psc[ex])][:5]
            out += [(f_, "top", i) for i in top] + [(f_, "explore", i) for i in ex]
        with open(D / "tol_list.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["fam", "kind", "src", "src_idx", "e", *U_COLS])
            for f_, kind, i in out:
                w.writerow([f_, kind, C["src"][i], int(C["idx"][i]), float(C["e"][i]), *[repr(float(v)) for v in C["U"][i]]])
        print("placement list:", len(out))
    if mode == "final":
        lst = list(csv.DictReader(open(D / "tol_list.csv", encoding="utf-8")))
        tol = json.load(open(D / "tol_ring.json", encoding="utf-8"))
        okmap = {(t["src"], str(t["src_idx"]), round(float(t["e"]), 3)): t for t in tol}
        cand = []
        for n, r in enumerate(lst):
            t = okmap.get((r["src"], str(r["src_idx"]), round(float(r["e"]), 3)))
            if t is None or not t["ok"]:
                continue
            u = np.array([float(r[c]) for c in U_COLS])
            i = int(np.where(np.all(np.isclose(C["U"], u, atol=1e-9), axis=1) & np.isclose(C["e"], float(r["e"])) & uniq)[0][0])
            cand.append((int(r["fam"]), r["kind"], i, t))
        print("placement passed:", len(cand), "of", len(lst), {f_: sum(1 for c in cand if c[0] == f_) for f_ in range(K_FAM)})
        picks = []

        def far_enough(i):
            return all(np.linalg.norm(Ue[i] - Ue[j]) >= BATCH_DIST for _, _, j, _ in picks)
        for f_ in range(K_FAM):
            pool_ = [c for c in cand if c[0] == f_]
            for role in ("best", "outer", "explore"):
                if role == "best":
                    order = sorted(pool_, key=lambda c: -P[c[2]])
                elif role == "outer":
                    order = sorted([c for c in pool_ if dA[c[2]] >= 0.45], key=lambda c: -P[c[2]]) + sorted(pool_, key=lambda c: -P[c[2]])
                else:
                    order = sorted([c for c in pool_ if dF[c[2]] >= -10], key=lambda c: -psc[c[2]])
                for c in order:
                    if far_enough(c[2]):
                        picks.append((f_, role, c[2], c[3]))
                        break
        rng = np.random.default_rng(SEED)
        n_mc, sdF_meas, sdl_meas = 20000, 0.6, 0.012
        ii = np.array([p[2] for p in picks])
        fams = np.array([p[0] for p in picks])

        def beats(xF, xl):
            return ((xF >= DF1) & (xl <= R1)) | ((xl <= R2) & (xF >= DF2))
        res = {}
        for name, mF, ml, sF, sl in (("predictions right", dF[ii], dl[ii], resid_sd, psc[ii]), ("no improvement", 0 * dF[ii], 0 * dl[ii], 0.0, 0.0)):
            tF = mF + sF * rng.standard_normal((n_mc, len(ii)))
            tl = ml + sl * rng.standard_normal((n_mc, len(ii)))
            ok1 = beats(tF + sdF_meas * rng.standard_normal(tF.shape), tl + sdl_meas * rng.standard_normal(tl.shape))
            ok2 = beats(tF + sdF_meas * rng.standard_normal(tF.shape), tl + sdl_meas * rng.standard_normal(tl.shape))
            conf = ok1 & ok2
            fam_pass = np.stack([conf[:, fams == f_].any(1) for f_ in range(K_FAM)], 1)
            res[name] = {"P_G41_pass": float(fam_pass.any(1).mean()), "expected_families": float(fam_pass.sum(1).mean()), "expected_rows_confirmed": float(conf.sum(1).mean()),
                         "P_family": fam_pass.mean(0).round(3).tolist()}
        json.dump(res, open(D / "power.json", "w", encoding="utf-8"), indent=1)
        print("power", json.dumps(res))
        with open(D / "picks.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["fam", "role", "src", "src_idx", "e", "dist_A", "bone_cm3", "F_pred_mm", "F_A_mm", "f1_pred_um", "f1_A_um", "sd_dex_cal", "P_beat", "h_cut", "A0", "alpha", "design_json", *U_COLS])
            for f_, role, i, t in picks:
                w.writerow([f_, role, C["src"][i], int(C["idx"][i]), float(C["e"][i]), round(float(dA[i]), 3), round(float(C["bone"][i]), 3), round(float(Fc[i]), 1), round(float(np.interp(C["bone"][i], cb, cF)), 1),
                            round(float(10 ** pm[i]), 2), round(float(10 ** np.interp(C["bone"][i], cb, cl)), 2), round(float(psc[i]), 3), round(float(P[i]), 3), t.get("h_cut"), t.get("A0"), t.get("alpha"),
                            json.dumps(t.get("design")), *[repr(float(v)) for v in C["U"][i]]])
                print(f"fam {f_} {role:7s} {C['src'][i]}#{int(C['idx'][i])} e {C['e'][i]:+.1f} dist {dA[i]:.2f} bone {C['bone'][i]:.2f} F {Fc[i]:.1f} (A {np.interp(C['bone'][i], cb, cF):.1f}) "
                      f"f1 {10 ** pm[i]:.1f} (A {10 ** np.interp(C['bone'][i], cb, cl):.1f}) sd {psc[i]:.3f} P {P[i]:.3f}")
    if mode == "first":
        rows = []
        for f_ in range(K_FAM):
            k = np.where(fam == f_)[0]
            best = {}
            for i in k:   # best score per design over its e levels
                key = tuple(np.round(C["U"][i], 9))
                if key not in best or P[i] > P[best[key]]:
                    best[key] = i
            ii = np.array(list(best.values()))
            top = ii[np.argsort(-P[ii])][:40]
            expl = ii[(dF[ii] >= -10)]
            expl = expl[np.argsort(-psc[expl])][:10]
            for i in np.unique(np.r_[top, expl]):
                rows.append([f_, C["src"][i], int(C["idx"][i]), *[repr(float(v)) for v in C["U"][i]]])
        with open(D / "shortlist_e.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["fam", "src", "src_idx", *U_COLS])
            w.writerows(rows)
        print("shortlist designs for the e grid:", len(rows))


if __name__ == "__main__":
    main()
