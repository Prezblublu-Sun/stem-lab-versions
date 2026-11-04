"""Side check (read-only): is the cortical margin m enforced right below the resection plane?

geom3d.penetration samples the stem surface with Stem3D.local_surface (S_TOP = -60 mm with 8 rings above the shoulder,
i.e. one ring every 7.5 mm), so the part of the stem between the shoulder (s = 0) and the resection plane (s ~ -2..-5 mm on
the tilted side) is not checked. Here templating is redone in this process with geom3d.penetration patched to add a dense
band of rings for s in [-12, +2] mm (0.25 mm apart, 96 points per ring), and A0 / e / alpha are compared with the stored
templating. Nothing in the code tree or the queue is modified (the patch lives in this process only).

    run.sh fail_tplfine.py --jobs j1,j2,... [--workers 3]   -> deck/ml_eff/failures/tplfine/tplfine.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import resource
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

OUT = FG.HOME / "deck" / "ml_eff" / "failures" / "tplfine"
G = FG.G
_ORIG_PEN = G.penetration


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))


def pen_dense(stem, fem, A0, pose, margin=None):
    base = _ORIG_PEN(stem, fem, A0, pose, margin)
    sec = G.unit_section(stem.d, 96)
    s = np.arange(-12.0, 2.0001, 0.25)
    k = np.sqrt(A0 * stem.area_ratio(s))
    loc = np.vstack([np.c_[np.full(len(sec), si), ki * sec] for si, ki in zip(s, k)])
    P = fem.to_world(loc, pose)
    P = P[fem.below_cut(P)]
    if not len(P):
        return base
    margin = stem.m if margin is None else margin
    return max(base, float(np.maximum(fem.canal_sdf(P) + margin, 0.0).max()))


def one(job):
    t0 = time.time()
    d = FG.J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    stored = json.loads((d / "result.json").read_text()).get("templating")
    rec = {"job": job, "stage": spec.get("stage"), "collar_rule": spec.get("collar_rule"), "m": spec["design"].get("m"),
           "stored": {k: stored.get(k) for k in ("alpha", "e", "A0", "volume")}}
    try:
        G.penetration = _ORIG_PEN
        st, fm, pl0 = FG.template_for(spec)
        rec["recomputed_orig"] = {k: pl0.get(k) for k in ("alpha", "e", "A0", "volume")} if pl0.get("fit") else {"fit": False}
        G.penetration = pen_dense
        st, fm, pl = FG.template_for(spec)
        if pl.get("fit"):
            rec["dense"] = {k: pl.get(k) for k in ("alpha", "e", "A0", "volume")}
            rec["dense"]["tl_min_mm"] = FG.thin_layer(st, fm, pl["A0"], pl["pose"])["tl_min_mm"]
            rec["dA0_pct"] = 100.0 * (pl["A0"] / stored["A0"] - 1.0)
            rec["de_mm"] = float(pl["e"] - stored["e"])
            rec["dvolume_mm3"] = float(pl["volume"] - stored["volume"])
        else:
            rec["dense"] = {"fit": False, "reason": str(pl.get("reason"))[:200]}
        rec["orig_tl_min_mm"] = FG.thin_layer(st, fm, stored["A0"], fm.pose(stored["alpha"], stored["e"]))["tl_min_mm"]
    except Exception as e:                                                   # noqa: BLE001
        rec["err"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        G.penetration = _ORIG_PEN
    rec["wall_s"] = time.time() - t0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default="", help="output tplfine_<tag>.json (default tplfine.json)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = a.jobs.split(",")
    if a.jobs.startswith("@"):                                               # @file with a comma-separated job list
        jobs = pathlib.Path(a.jobs[1:]).read_text().strip().split(",")
    with Pool(a.workers, initializer=_limit) as p:
        res = p.map(one, jobs, chunksize=1)
    (OUT / (f"tplfine_{a.tag}.json" if a.tag else "tplfine.json")).write_text(json.dumps(res, default=float))
    for r in res:
        print(r["job"], "m", round(r["m"], 3), "orig tl_min", round(r.get("orig_tl_min_mm", np.nan), 3), "dA0 %", round(r.get("dA0_pct", np.nan), 2),
              "de", r.get("de_mm"), "dense tl_min", round((r.get("dense") or {}).get("tl_min_mm", np.nan), 3), "err", r.get("err"), flush=True)


if __name__ == "__main__":
    main()
