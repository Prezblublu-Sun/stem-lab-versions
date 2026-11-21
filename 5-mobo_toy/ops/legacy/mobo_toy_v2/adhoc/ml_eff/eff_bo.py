"""Step 4: simulated BO campaigns on the emulator (phase-10 problem), pool-based acquisition like stage_neckopt.

usage: eff_bo.py <task> [<task> ...]     task = truth:method:seed   e.g. mean:nehvi:0   s1:tr:1
  truth   mean | s0 | s1 | s2       (emulator posterior mean, or one of three joint posterior sample paths)
  method  random   63-point warm start + 72 random pool points
          random0  72 random pool points, no warm start
          nehvi    current setup: qLogNEHVI, 13-D GPs (rotation, contact, combined constraint), 63-point warm start
          nehvi0   same, no warm start: 12 random initial points + 60 BO
          active   GPs on the 6 most influential variables only (others ignored by the surrogate), full pool
          frozen   inactive variables frozen at the incumbent; pool = Sobol in the active variables (template-gated); 6-D GPs
          warm99   warm start = all 99 neck9 designs (incl. 36 with m < 0.5, outside the phase-10 box), GP on the phase-9 box
          tr       trust region: candidates restricted to pool points within an L-inf box around the current feasible front
          geo      GP inputs = 13 design variables + 6 template quantities (A0, e, reamed volume, geometric area, near-wall
                   area, mean wall distance; all computed by the template gate at no FE cost), full pool
          geo0     as geo, no warm start (12 random initial points + 60 BO)
          geotr    geo GP + trust region
          geo99    geo GP + the 99-design warm start of warm99
          proxy    contact area treated as deterministic: a + b * geometric stem area below the cut (template quantity),
                   a, b refitted by least squares on the observed data each round; GPs only for rotation and constraint
Budget 72 new evaluations, batches of q = 6 (sequential-greedy qLogNEHVI on the discrete pool; the real phase 10 ran async with
6 in flight, which is the same pending-point logic with a refit after every completion).
HV: feasible points only, minimisation of (log10 rot, -contact), fixed reference point = 1.1 x range of the warm-start truth (as the
optimiser does), identical for all methods of one truth.
writes OUT/bo/<truth>_<method>_s<seed>.json
"""
from __future__ import annotations

import json
import sys
import time
import warnings

import numpy as np
import torch

import eff_common as E

warnings.filterwarnings("ignore")
torch.set_default_dtype(torch.double)
BUDGET, Q = 72, 6
POOL_N = int(__import__("os").environ.get("EFF_POOL", "2000"))
MC = int(__import__("os").environ.get("EFF_MC", "64"))
BODIR = __import__("os").environ.get("EFF_BODIR", "bo")
OUTS = ["y_rot", "y_con", "c_mm", "c_vm", "c_sed"]
JM = E.VARS10.index("m")
LO9, HI9 = E.SPACE9["m"]
LO10, HI10 = E.SPACE10["m"]


def p9_to_p10(X):
    X = np.array(X, float, copy=True)
    X[:, JM] = (LO9 + X[:, JM] * (HI9 - LO9) - LO10) / (HI10 - LO10)
    return X


def feas_c(cmm, cvm, csed):
    return np.maximum.reduce([(10 ** cmm - E.MM_LIMIT) / E.MM_LIMIT, (cvm - E.VM_LIMIT) / E.VM_LIMIT, (np.abs(csed) - E.SED_LIMIT) / E.SED_LIMIT])


def propose(model, X_obs, ref_min, pool, q, seed):
    """mobo.propose with a configurable number of MC samples (default there: 128)."""
    from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
    from botorch.acquisition.multi_objective.objective import IdentityMCMultiOutputObjective
    from botorch.models import ModelListGP
    from botorch.optim import optimize_acqf_discrete
    from botorch.sampling import SobolQMCNormalSampler
    if isinstance(model, ModelListGP):
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([MC]), seed=seed)
    else:
        from botorch.sampling.get_sampler import get_sampler
        sampler = get_sampler(model.posterior(torch.as_tensor(X_obs[:1])), sample_shape=torch.Size([MC]), seed=seed)
    acq = qLogNoisyExpectedHypervolumeImprovement(
        model=model, ref_point=(-torch.as_tensor(ref_min)).tolist(), X_baseline=torch.as_tensor(X_obs), prune_baseline=True,
        sampler=sampler, constraints=[lambda Z: Z[..., 2]], objective=IdentityMCMultiOutputObjective(outcomes=[0, 1]), cache_root=False)
    cand, _ = optimize_acqf_discrete(acq, q=q, choices=torch.as_tensor(pool), max_batch_size=2048, unique=True)
    cand = cand.numpy()
    return np.array([int(np.argmin(np.linalg.norm(pool - c, axis=1))) for c in cand])


class World:
    def __init__(self, truth):
        z = np.load(E.OUT / "emul.npz", allow_pickle=True)
        self.rep = json.loads((E.OUT / "emul_report.json").read_text())
        n = int(z["n_train"])
        key = (lambda k: f"mean_{k}") if truth == "mean" else (lambda k: f"{truth}_{k}")
        T = {k: z[key(k)] for k in OUTS}
        self.Y = np.c_[T["y_rot"], -T["y_con"]]
        self.C = feas_c(T["c_mm"], T["c_vm"], T["c_sed"])
        self.P9 = z["P9"]
        self.P10 = p9_to_p10(self.P9)
        self.geo = z["Pgeo"]
        self.G6n = (z["PG6"] - z["G6_lo"]) / (z["G6_hi"] - z["G6_lo"])
        nk, m = z["nk_phase"], z["m_phys"]
        self.warm63 = np.nonzero((nk == 9) & (m >= 0.5 - 1e-9))[0]
        self.warm99 = np.nonzero(nk == 9)[0]
        self.univ = np.arange(n, len(self.P9))
        fe = self.C[self.warm63] <= 0
        Yw = self.Y[self.warm63][fe]
        lo, hi = Yw.min(0), Yw.max(0)
        self.ref = hi + 0.1 * (hi - lo)
        self.active = self.rep["active_vars"]
        self.ia = [E.VARS10.index(v) for v in self.active]
        if truth == "mean":                           # frozen pool (mean truth only)
            f = np.load(E.OUT / "frozen_pool.npz")
            self.fz_X10 = f["U"]
            self.fz_Y = np.c_[f["mean_y_rot"], -f["mean_y_con"]]
            self.fz_C = feas_c(f["mean_c_mm"], f["mean_c_vm"], f["mean_c_sed"])
            self.fz_geo = f["geo"]


def hv(Y, C, ref):
    import mobo
    f = C <= 0
    return float(mobo.hypervolume(Y[f], ref)) if f.any() else 0.0


def front_mask(Y, C):
    import mobo
    f = np.nonzero(C <= 0)[0]
    out = np.zeros(len(Y), bool)
    if len(f):
        out[f[mobo.pareto_mask(Y[f])]] = True
    return out


def run(truth, method, seed):
    import mobo
    import stage_v2a as S
    mobo.fit_gp = S._fit_gp_unit
    W = World(truth)
    rng = np.random.default_rng(seed)
    # per-seed candidate pool (same for every method of this seed)
    pool_rows = np.sort(rng.choice(W.univ, size=min(POOL_N, len(W.univ)), replace=False))
    use_geo, cold, use_tr = method in ("geo", "geo0", "geotr", "geo99"), method in ("nehvi0", "geo0"), method in ("tr", "geotr")
    base = W.P9 if method in ("warm99", "geo99") else W.P10
    coords = np.c_[base, W.G6n] if use_geo else base
    if method == "frozen":
        if truth != "mean":
            raise SystemExit("frozen only with mean truth")
        nfz = len(W.fz_X10)
        sub = np.sort(rng.choice(nfz, size=min(POOL_N, nfz), replace=False))
        PX, PY, PC, PG = W.fz_X10[sub], W.fz_Y[sub], W.fz_C[sub], W.fz_geo[sub]
    else:
        PX, PY, PC, PG = coords[pool_rows], W.Y[pool_rows], W.C[pool_rows], W.geo[pool_rows]
    warm = {"random0": [], "nehvi0": [], "geo0": [], "warm99": W.warm99, "geo99": W.warm99}.get(method, W.warm63)
    WX = coords[warm] if len(warm) else np.zeros((0, coords.shape[1]))
    if method == "frozen":
        WX = W.P10[warm]
    WY, WC, WG = W.Y[warm], W.C[warm], W.geo[warm]
    used = np.zeros(len(PX), bool)
    sel = []                                                 # pool indices in evaluation order
    trace = [hv(WY, WC, W.ref)]
    timing = []
    tr_r, tr_s, tr_f, tr_hist = 0.2, 0, 0, []

    def data():
        idx = np.array(sel, int)
        return (np.vstack([WX, PX[idx]]), np.vstack([WY, PY[idx]]) if len(idx) else WY, np.r_[WC, PC[idx]], np.r_[WG, PG[idx]])

    def add(idx):
        for i in idx:
            used[i] = True; sel.append(int(i))
            X_, Y_, C_, _ = data()
            trace.append(hv(Y_, C_, W.ref))

    if method in ("random", "random0"):
        order = rng.permutation(len(PX))
        add(order[:BUDGET])
    else:
        if cold:
            add(rng.permutation(len(PX))[:12])
        rnd = 0
        while len(sel) < BUDGET:
            rnd += 1
            t0 = time.perf_counter()
            X_, Y_, C_, G_ = data()
            q = min(Q, BUDGET - len(sel))
            free = np.nonzero(~used)[0]
            dims = W.ia if method in ("active", "frozen") else list(range(PX.shape[1]))
            Xm = X_[:, dims]
            if method == "proxy":
                A = np.c_[np.ones(len(G_)), G_]
                coef, *_ = np.linalg.lstsq(A, -Y_[:, 1], rcond=None)        # contact = a + b * geo
                from scipy.spatial import cKDTree
                allX = np.vstack([X_, PX]); allG = np.r_[G_, PG]
                tree = cKDTree(allX)

                def fn(Z, tree=tree, allG=allG, coef=coef):
                    Zf = Z.detach().cpu().numpy().reshape(-1, Z.shape[-1])
                    _, ii = tree.query(Zf, k=1, workers=1)
                    return torch.as_tensor(-(coef[0] + coef[1] * allG[ii]), dtype=Z.dtype).reshape(Z.shape[:-1])
                model = mobo.fit_models(Xm, Y_, C_[:, None], det={1: fn})
            else:
                model = mobo.fit_models(Xm, Y_, C_[:, None])
            t_fit = time.perf_counter() - t0
            cand = free
            if use_tr:
                fm = front_mask(Y_, C_)
                Fx = X_[fm] if fm.any() else X_[[int(np.argmin(C_))]]
                dist = np.min(np.max(np.abs(PX[free][:, None, :] - Fx[None, :, :]), axis=2), axis=1)
                cand = free[dist <= tr_r]
                if len(cand) < 4 * q:
                    cand = free[np.argsort(dist)[:4 * q]]
                tr_hist.append({"round": rnd, "r": tr_r, "n_cand": int(len(cand)), "n_front": int(fm.sum())})
            pick = propose(model, Xm, W.ref, PX[cand][:, dims], q, seed * 1000 + rnd)
            hv_before = trace[-1]
            add(cand[pick])
            if use_tr:
                if trace[-1] > hv_before * (1 + 1e-3):
                    tr_s, tr_f = tr_s + 1, 0
                else:
                    tr_s, tr_f = 0, tr_f + 1
                if tr_s >= 2:
                    tr_r, tr_s = min(0.5, tr_r * 1.5), 0
                if tr_f >= 2:
                    tr_r, tr_f = max(0.05, tr_r / 2), 0
            timing.append({"round": rnd, "fit_s": t_fit, "total_s": time.perf_counter() - t0, "n_cand": int(len(cand))})
            print(f"[{truth}:{method}:s{seed}] round {rnd}: n_new {len(sel)} HV {trace[-1]:.5g} ({timing[-1]['total_s']:.0f} s)", flush=True)
    idx = np.array(sel, int)
    pool_opt = hv(np.vstack([WY, PY]), np.r_[WC, PC], W.ref)
    out = {"truth": truth, "method": method, "seed": seed, "budget": BUDGET, "q": Q, "mc": MC, "pool_n": int(len(PX)),
           "n_warm": int(len(warm)), "ref": W.ref.tolist(), "trace": trace, "hv_warm": trace[0], "hv_final": trace[-1],
           "hv_pool_opt": pool_opt, "sel_y": PY[idx].tolist(), "sel_c": PC[idx].tolist(), "sel_x": PX[idx].tolist(),
           "n_feasible_new": int((PC[idx] <= 0).sum()), "timing": timing, "tr_hist": tr_hist, "active": W.active}
    d = E.OUT / BODIR
    d.mkdir(exist_ok=True)
    (d / f"{truth}_{method}_s{seed}.json").write_text(json.dumps(out, default=float))
    return out


if __name__ == "__main__":
    for task in sys.argv[1:]:
        t, m, s = task.split(":")
        t0 = time.perf_counter()
        f = E.OUT / BODIR / f"{t}_{m}_s{s}.json"
        if f.exists():
            print("skip existing", f.name, flush=True)
            continue
        o = run(t, m, int(s))
        print(f"DONE {task}: HV warm {o['hv_warm']:.4g} final {o['hv_final']:.4g} pool-opt {o['hv_pool_opt']:.4g} "
              f"({time.perf_counter() - t0:.0f} s)", flush=True)
