"""Step 3: emulators of the phase-10 problem fitted to all comparable collarless FE results (165 rows:
neck9 99 + neck10 66, current code, no overrides, neck_in_shoulder).

Outputs modelled (one GP each, Matern 5/2 ARD + the optimiser's priors, explicit [0,1] input bounds = stage_v2a._fit_gp_unit):
  y_rot = log10(rotation first load, deg)      (minimise)
  y_con = closed contact area at LOAD2, mm2    (maximise)
  c_mm  = log10(stem-body micromotion P95, um) (<= log10 150)
  c_vm  = stem vM P99, MPa                     (<= 440)
  c_sed = calcar G7 cortex SED change, %       (|.| <= 30)
Emulator variants (inputs)
  E13  13 design variables (phase-9 unit cube, m in [-0.25, 2])
  E15  + geometric stem area below the cut + reamed volume (template quantities, ~0.3-0.6 s each, no FE)
  E19  + all six template quantities G6 = A0, entry offset e, reamed volume, geometric area, near-wall area (<= m + 1 mm),
       area-weighted mean wall distance
Validation: 5-fold CV (2 repeats) and the 'p9 -> p10' split (train on neck9, predict neck10).
Variable importance: (i) ARD length scales of E13 fitted to all 165, (ii) first-order correlation ratio of the chosen emulator mean
on the feasible base-Sobol candidates (template-gated), (iii) the optimiser's own p10 length scales.
Truth tables: posterior mean on (training designs + candidate universe) for the chosen emulator, plus 3 joint posterior sample paths.
Also builds the 'frozen' candidate pool for variant (c2): Sobol in the active variables, inactive ones fixed at the incumbent.
writes OUT/emul.npz, OUT/emul_report.json, OUT/frozen_pool.npz
"""
from __future__ import annotations

import json
import math
import sys
import time
from multiprocessing import Pool

import numpy as np
import torch

import eff_common as E

torch.set_default_dtype(torch.double)
OUTS = ["y_rot", "y_con", "c_mm", "c_vm", "c_sed"]
G6_TRAIN = ["px_tpl_A0", "px_tpl_e", "px_tpl_volume", "px_geo_area_mm2", "px_near_area_mm2", "px_mean_wall_mm"]
G6_UNIV = ["A0", "e", "volume", "geo_area_mm2", "near_area_mm2", "mean_wall_mm"]


def fit(X, y, noise_min=1e-6):
    import stage_v2a as S
    return S._fit_gp_unit(torch.as_tensor(X), torch.as_tensor(y), noise_min)


def pred_mean(gp, X):
    with torch.no_grad():
        return gp.posterior(torch.as_tensor(X)).mean.numpy().ravel()


def r2(y, p):
    return float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def feas_c(cmm, cvm, csed):
    return np.maximum.reduce([(10 ** cmm - E.MM_LIMIT) / E.MM_LIMIT, (cvm - E.VM_LIMIT) / E.VM_LIMIT, (np.abs(csed) - E.SED_LIMIT) / E.SED_LIMIT])


def main():
    t_start = time.perf_counter()
    z = np.load(E.OUT / "collarless_dataset.npz", allow_pickle=True)
    U = np.load(E.OUT / "universe.npz", allow_pickle=True)
    X9 = z["X9"]
    Y = {k: z[k] for k in OUTS}
    n = len(X9)
    fit_u = U["fit"]
    G_tr = np.column_stack([z[k].astype(float) for k in G6_TRAIN])
    G_un = np.column_stack([U[k][fit_u].astype(float) for k in G6_UNIV])
    g_lo = np.minimum(G_tr.min(0), G_un.min(0)); g_hi = np.maximum(G_tr.max(0), G_un.max(0))
    # small margin so that new (frozen-pool) points stay inside [0, 1] in most cases
    span = g_hi - g_lo; g_lo, g_hi = g_lo - 0.05 * span, g_hi + 0.05 * span

    def gnorm(G):
        return (G - g_lo) / (g_hi - g_lo)

    def feats(X, G):
        Gn = gnorm(G)
        return {"E13": X, "E15": np.c_[X, Gn[:, [3, 2]]], "E19": np.c_[X, Gn]}

    variants = feats(X9, G_tr)
    rep = {"n_train": int(n), "families": {str(k): int(v) for k, v in zip(*np.unique(z["family"], return_counts=True))},
           "G6": G6_UNIV, "G6_lo": g_lo.tolist(), "G6_hi": g_hi.tolist()}

    # ---------------------------------------------------------------- validation
    rng = np.random.default_rng(0)
    cv = {}
    for name, F in variants.items():
        cv[name] = {}
        for k in OUTS:
            y = Y[k]
            r2s, sps = [], []
            for rep_i in range(2):
                perm = rng.permutation(n)
                pred = np.empty(n)
                for f in range(5):
                    te = perm[f::5]
                    tr = np.setdiff1d(perm, te)
                    pred[te] = pred_mean(fit(F[tr], y[tr]), F[te])
                r2s.append(r2(y, pred)); sps.append(E.spearman(y, pred)[0])
            tr = z["nk_phase"] != 10; te = ~tr
            p = pred_mean(fit(F[tr], y[tr]), F[te])
            cv[name][k] = {"cv5_R2": float(np.mean(r2s)), "cv5_R2_sd": float(np.std(r2s)), "cv5_spearman": float(np.mean(sps)),
                           "p9_to_p10_R2": r2(y[te], p), "p9_to_p10_spearman": E.spearman(y[te], p)[0],
                           "p9_to_p10_bias": float((p - y[te]).mean())}
        print(name, json.dumps({k: {a: round(b, 3) for a, b in v.items()} for k, v in cv[name].items()}), flush=True)
    rep["validation"] = cv
    score = {nm: float(np.mean([cv[nm][k]["cv5_R2"] for k in OUTS])) for nm in variants}
    chosen = max(score, key=score.get)
    rep["chosen_emulator"] = chosen; rep["emulator_mean_cv_R2"] = score
    print("chosen", chosen, score, flush=True)

    # ---------------------------------------------------------------- full fits + importance
    gps = {nm: {k: fit(F, Y[k]) for k in OUTS} for nm, F in variants.items()}
    ls = {}
    for k in OUTS:
        l = gps["E13"][k].covar_module.base_kernel.lengthscale.detach().numpy().ravel()
        ls[k] = {v: float(x) for v, x in zip(E.VARS10, l)}
    rep["E13_lengthscales_p9unit"] = ls
    rep["chosen_lengthscales"] = {k: gps[chosen][k].covar_module.base_kernel.lengthscale.detach().numpy().ravel().tolist() for k in OUTS}

    jm = E.VARS10.index("m")
    lo9, hi9 = E.SPACE9["m"]; lo10, hi10 = E.SPACE10["m"]
    Uu = U["U"][fit_u].copy()
    Uu9 = Uu.copy(); Uu9[:, jm] = (lo10 + Uu[:, jm] * (hi10 - lo10) - lo9) / (hi9 - lo9)
    P9 = np.vstack([X9, Uu9])
    PG = np.vstack([G_tr, G_un])
    PF = feats(P9, PG)
    truth_mean = {nm: {k: pred_mean(gps[nm][k], PF[nm]) for k in OUTS} for nm in variants}

    # importance on feasible base-Sobol candidates (src 9 / 10) with the chosen emulator mean: correlation ratio eta^2
    src = U["src"][fit_u]
    base = np.r_[np.zeros(n, bool), np.isin(src, (9, 10))]
    Xb = PF["E13"][base]
    eta = {}
    for k in OUTS + ["c_comb"]:
        if k == "c_comb":
            y = feas_c(truth_mean[chosen]["c_mm"], truth_mean[chosen]["c_vm"], truth_mean[chosen]["c_sed"])[base]
        else:
            y = truth_mean[chosen][k][base]
        vy = y.var()
        e = {}
        for j, v in enumerate(E.VARS10):
            q = np.quantile(Xb[:, j], np.linspace(0, 1, 11))
            b = np.clip(np.searchsorted(q, Xb[:, j], side="right") - 1, 0, 9)
            mu = np.array([y[b == i].mean() if (b == i).any() else y.mean() for i in range(10)])
            cnt = np.array([(b == i).sum() for i in range(10)])
            e[v] = float((cnt * (mu - y.mean()) ** 2).sum() / cnt.sum() / vy)
        eta[k] = e
    rep["eta2_first_order_feasible"] = eta
    rep["n_base_feasible_for_eta"] = int(base.sum())

    st = json.loads((E.HOME / "results" / "neckopt_p10.json").read_text())
    lsh = st["lengthscales"]; last = lsh[max(lsh, key=lambda s: int(s))]
    crit = {"eta_rot": eta["y_rot"], "eta_con": eta["y_con"], "eta_c": eta["c_comb"],
            "invls_rot": {v: 1 / ls["y_rot"][v] for v in E.VARS10}, "invls_con": {v: 1 / ls["y_con"][v] for v in E.VARS10},
            "invls_p10_rot": {v: 1 / last["micromotion"][v] for v in E.VARS10}, "invls_p10_con": {v: 1 / last["constraint"][v] for v in E.VARS10}}
    ranks = {v: [] for v in E.VARS10}
    for cname, d in crit.items():
        order = sorted(E.VARS10, key=lambda v: -d[v])
        for r_, v in enumerate(order):
            ranks[v].append(r_ + 1)
    avg = {v: float(np.mean(r_)) for v, r_ in ranks.items()}
    order = sorted(E.VARS10, key=lambda v: avg[v])
    rep["importance_criteria"] = crit
    rep["importance_avg_rank"] = avg
    rep["importance_order"] = order
    k_act = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    active = order[:k_act]
    rep["active_vars"] = active
    print("importance order", [(v, round(avg[v], 1)) for v in order], flush=True)

    # ---------------------------------------------------------------- posterior sample paths (chosen emulator)
    samples = {}
    for s in range(3):
        g = torch.Generator().manual_seed(1000 + s)
        for k in OUTS:
            gp = gps[chosen][k]
            with torch.no_grad():
                post = gp.posterior(torch.as_tensor(PF[chosen]))
                mu = post.mean.numpy().ravel()
                Kc = post.mvn.covariance_matrix.numpy()
            Kc = 0.5 * (Kc + Kc.T)
            jit = 1e-8 * np.mean(np.diag(Kc))
            Lc = None
            for _ in range(8):
                try:
                    Lc = np.linalg.cholesky(Kc + jit * np.eye(len(Kc)))
                    break
                except np.linalg.LinAlgError:
                    jit *= 10
            eps = torch.randn(len(Kc), generator=g).numpy()
            samples[f"s{s}_{k}"] = mu + Lc @ eps
            del Kc, Lc
        print("sample path", s, "done", round(time.perf_counter() - t_start), "s", flush=True)

    # ---------------------------------------------------------------- frozen pool for (c2)
    import mobo
    warm = np.nonzero((z["nk_phase"] == 9) & (z["m"] >= 0.5 - 1e-9))[0]
    tm = truth_mean[chosen]
    Yw = np.c_[tm["y_rot"][warm], -tm["y_con"][warm]]
    cw = feas_c(tm["c_mm"][warm], tm["c_vm"][warm], tm["c_sed"][warm])
    fe = cw <= 0
    lo_, hi_ = Yw[fe].min(0), Yw[fe].max(0)
    ref = hi_ + 0.1 * (hi_ - lo_)
    hv_all = mobo.hypervolume(Yw[fe], ref)
    contrib = [hv_all - mobo.hypervolume(np.delete(Yw[fe], i, axis=0), ref) for i in range(fe.sum())]
    inc = warm[fe][int(np.argmax(contrib))]
    x_inc9 = X9[inc]
    x_inc10 = x_inc9.copy(); x_inc10[jm] = (lo9 + x_inc9[jm] * (hi9 - lo9) - lo10) / (hi10 - lo10)
    rep["incumbent"] = {"job": str(z["job"][inc]), "x_p10unit": x_inc10.tolist(),
                        "design": {v: E.SPACE10[v][0] + x_inc10[j] * (E.SPACE10[v][1] - E.SPACE10[v][0]) for j, v in enumerate(E.VARS10)}}
    from scipy.stats import qmc
    ia = [E.VARS10.index(v) for v in active]
    Sob = qmc.Sobol(len(ia), scramble=True, seed=777).random(2048)
    Ufz = np.tile(x_inc10, (len(Sob), 1)); Ufz[:, ia] = Sob
    import eff_pool as EP
    t0 = time.perf_counter()
    with Pool(2) as p:
        res = p.map(EP.job, list(Ufz), chunksize=16)
    okf = np.array([bool(r.get("fit")) for r in res])
    Gfz = np.array([[float(r.get(k, np.nan)) if r.get(k) is not None else np.nan for k in G6_UNIV] for r in res])
    okf &= np.all(np.isfinite(Gfz), 1)
    Ufz, Gfz = Ufz[okf], Gfz[okf]
    Ufz9 = Ufz.copy(); Ufz9[:, jm] = (lo10 + Ufz[:, jm] * (hi10 - lo10) - lo9) / (hi9 - lo9)
    FF = feats(Ufz9, Gfz)[chosen]
    fz_truth = {k: pred_mean(gps[chosen][k], FF) for k in OUTS}
    np.savez(E.OUT / "frozen_pool.npz", U=Ufz, G6=Gfz, geo=Gfz[:, 3], vol=Gfz[:, 2], **{f"mean_{k}": v for k, v in fz_truth.items()})
    rep["frozen_pool"] = {"n_sobol": 2048, "n_feasible": int(okf.sum()), "templating_s": time.perf_counter() - t0, "active": active}
    print("frozen pool", rep["frozen_pool"], flush=True)

    alt = [nm for nm in variants if nm != chosen]
    np.savez(E.OUT / "emul.npz", P9=P9, PG6=PG, Pgeo=PG[:, 3], Pvol=PG[:, 2], G6_lo=g_lo, G6_hi=g_hi, n_train=n, src=np.r_[np.full(n, -1), src],
             nk_phase=np.r_[z["nk_phase"], np.full(len(Uu), np.nan)], m_phys=np.r_[z["m"], lo10 + Uu[:, jm] * (hi10 - lo10)],
             family=np.r_[z["family"].astype(str), np.full(len(Uu), "pool")],
             **{f"mean_{k}": v for k, v in truth_mean[chosen].items()},
             **{f"alt{nm}_{k}": v for nm in alt for k, v in truth_mean[nm].items()},
             **samples, Y_obs_rot=Y["y_rot"], Y_obs_con=Y["y_con"], Y_obs_mm=Y["c_mm"], Y_obs_vm=Y["c_vm"], Y_obs_sed=Y["c_sed"])
    for nm in variants:
        tm_ = truth_mean[nm]
        rep.setdefault("proxy_vs_truth_on_universe", {})[nm] = {
            "spearman_geo_vs_contact": E.spearman(PG[n:, 3], tm_["y_con"][n:])[0],
            "R2_linear_geo_contact": float(np.corrcoef(PG[n:, 3], tm_["y_con"][n:])[0, 1] ** 2),
            "spearman_truth_rot_vs_E13_rot": E.spearman(tm_["y_rot"][n:], truth_mean["E13"]["y_rot"][n:])[0],
            "spearman_truth_con_vs_E13_con": E.spearman(tm_["y_con"][n:], truth_mean["E13"]["y_con"][n:])[0]}
    rep["proxy_vs_obs_train"] = {"spearman": E.spearman(z["px_geo_area_mm2"], Y["y_con"])[0],
                                 "R2_linear": float(np.corrcoef(z["px_geo_area_mm2"], Y["y_con"])[0, 1] ** 2)}
    rep["wall_s"] = time.perf_counter() - t_start
    E.dump("emul_report.json", rep)
    print(json.dumps({k: rep[k] for k in ("chosen_emulator", "emulator_mean_cv_R2", "active_vars", "incumbent", "frozen_pool",
                                          "proxy_vs_truth_on_universe", "proxy_vs_obs_train", "wall_s")}, indent=1, default=float))


if __name__ == "__main__":
    main()
