"""Phase-10 (and phase-9) candidate pools: how much of the pool lies in the meshing-failure band (read-only).

For every point of results/neckopt_p<phase>_pool_live.npz (gated Sobol pool + front-neighbourhood refresh points):
design_of(u) -> templating exactly as stage_neckopt.Phase.template (collar_rule neck_in_shoulder, min_A0 = pi*7^2)
-> the same pre-FE geometric features as fail_features.py (neck-base / footprint overhang pieces and tangency,
cancellous-layer thickness, coarse penetration). The BO records of the phase (pool_idx, ok) are attached.

    run.sh fail_pool.py --phase 10 [--workers 3] [--max 0]   -> deck/ml_eff/failures/pool/pool_p10.json
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import resource
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

OUT = FG.HOME / "deck" / "ml_eff" / "failures" / "pool"
_PH = {}


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))


def one(args):
    i, u, phase = args
    import stage_neckopt as SN
    import stage_v2a as S
    import collar_rule as CR
    t0 = time.time()
    if phase not in _PH:
        _PH[phase] = SN.Phase(phase)
    ph = _PH[phase]
    d, h = ph.design_of(np.asarray(u, float))
    rec = {"i": int(i), "h_cut": float(h), **{k: float(d[k]) for k in ph.vars if k in d}}
    try:
        fm = FG.femur_for({"h_cut": h})
        st = FG.G.Stem3D(**d)
        pl = CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0)
        rec["fit"] = bool(pl.get("fit") and pl["A0"] >= S.MIN_A0)
        if not rec["fit"]:
            rec["reason"] = str(pl.get("reason"))[:200]
            return rec
        rec.update({f"tpl_{k}": float(pl[k]) for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin") if k in pl})
        rec["neck_overhang_tpl_mm2"] = float(pl.get("neck_overhang_mm2", float("nan")))
        rec["pen_coarse_mm"] = float(FG.G.penetration(st, fm, pl["A0"], pl["pose"], st.m))
        rec.update(FG.thin_layer(st, fm, pl["A0"], pl["pose"]))
        rec.update(FG.neck_clearance(st, fm, pl["A0"], pl["pose"]))
    except Exception as e:                                                   # noqa: BLE001
        rec["err"] = f"{type(e).__name__}: {e}"[:300]
    rec["wall_s"] = time.time() - t0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=10)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max", type=int, default=0, help="random subsample of the pool (0 = all)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    J = FG.J
    z = np.load(J.RESULTS / f"neckopt_p{a.phase}_pool_live.npz")
    U = z["U"]
    gated = sorted((J.RESULTS / "pools").glob(f"neckopt_p{a.phase}_n*_s0_*.npz"))
    n_gated = int(len(np.load(gated[0])["U"])) if gated else None
    st = json.loads((J.RESULTS / f"neckopt_p{a.phase}.json").read_text())
    recs = st.get("records", [])
    idx = np.arange(len(U))
    if a.max and a.max < len(U):
        rng = np.random.default_rng(0)
        used = {r.get("pool_idx") for r in recs if r.get("pool_idx") is not None}
        keep = set(rng.choice(idx, size=a.max, replace=False).tolist()) | used
        idx = np.array(sorted(keep))
    print(f"phase {a.phase}: pool {len(U)} (gated {n_gated}); evaluating {len(idx)}", flush=True)
    t0 = time.time()
    with Pool(a.workers, initializer=_limit) as p:
        res = p.map(one, [(int(i), U[i].tolist(), a.phase) for i in idx], chunksize=8)
    by_idx = {}
    for k, r in enumerate(recs):
        if r.get("pool_idx") is not None:
            by_idx.setdefault(int(r["pool_idx"]), []).append({"order": k, "job": r.get("job_id"), "ok": r.get("ok"), "round": r.get("round")})
    for r in res:
        r["source"] = "gated" if (n_gated is not None and r["i"] < n_gated) else "refresh"
        r["proposed"] = by_idx.get(r["i"], [])
    meta = {"phase": a.phase, "pool_size": int(len(U)), "n_gated": n_gated, "n_eval": int(len(idx)), "vars": list(st.get("space", {}).keys()),
            "n_records": len(recs), "records": [{"order": k, "pool_idx": r.get("pool_idx"), "job": r.get("job_id"), "ok": r.get("ok"),
                                                  "round": r.get("round"), "x": r.get("x")} for k, r in enumerate(recs)],
            "wall_s": time.time() - t0}
    (OUT / f"pool_p{a.phase}.json").write_text(json.dumps({"meta": meta, "rows": res}, default=float))
    errs = [r for r in res if r.get("err")]
    print(f"done {len(res)} in {time.time() - t0:.0f} s; fit {sum(bool(r.get('fit')) for r in res)}; errors {len(errs)}", flush=True)
    for r in errs[:5]:
        print("ERR", r["i"], r["err"], flush=True)


if __name__ == "__main__":
    main()
