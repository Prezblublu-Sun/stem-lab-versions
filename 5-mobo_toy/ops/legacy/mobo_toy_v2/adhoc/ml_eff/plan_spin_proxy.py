"""0-FE spin-out proxies for the collarless (neck_in_shoulder) current-code jobs. READ-ONLY on the queue.

For each job, stem-body interface pairs (bone side), stem axis P0/ax = fm.pose(tpl_alpha, tpl_e) (as stability.py):
  r_perp      distance of the node from the stem axis (mm)
  e_theta     circumferential unit vector ax x r_hat
  T_fric_<S>  mu * sum(A * CPRESS_S * r_perp * |e_theta projected on the tangent plane|)   (N*m)
              = Coulomb friction torque capacity about the stem axis if every closed node slid circumferentially,
              S = RELEASE (press-fit only) and LOAD (press-fit + stair-climbing load)
  K_key       sum(A * r_perp * |n . e_theta|) (mm^3): geometric keying index (non-round section -> normal contact resists spin)
  K_key_rel   K_key / sum(A * r_perp): share of the surface whose normal faces the spin direction
  T_head      torque of the stair-climbing head force about the stem axis (N*m), from plan/torque_axis.csv logic
Writes ~/mobo_toy_v2/deck/ml_eff/plan/spin_proxy.csv. Uses <= 2 worker processes.
"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import femur_real as FR  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import model3d_v2 as M  # noqa: E402

OUT = HOME / "deck" / "ml_eff" / "plan"
TABLE = HOME / "deck" / "ml_eff" / "data" / "metrics_all.csv"
_FM = {}


def femur(h):
    if "b" not in _FM:
        _FM["b"] = FR.build()
    return _FM["b"] if h is None else _FM["b"].with_cut(float(h))


def one(job):
    d = J.QROOT / job
    try:
        spec = json.loads((d / "spec.json").read_text())
        res = json.loads((d / "result.json").read_text())
        t = res.get("templating") or json.loads((d / "prep.json").read_text()).get("templating")
        fm = femur(spec.get("h_cut"))
        P0, ax, _, _ = fm.pose(t["alpha"], t["e"])
        ax = ax / np.linalg.norm(ax)
        mu = float(spec.get("mu") or fm.cfg["interface"]["mu"])
        p = PM.pairs(d)
        n = p["n"]
        lut = np.full(int(p["node_labels"].max()) + 1, -1)
        lut[p["node_labels"].astype(int)] = np.arange(len(p["node_labels"]))
        body = ~p["pair_collar"]
        X = p["nodes"][lut[p["pair_bone"].astype(int)]][body]
        nrm = p["pair_normal"][body]
        nrm = nrm / np.linalg.norm(nrm, axis=1)[:, None]
        w = p["pair_area"][body]
        pb = p["pair_bone"][body]
        q = X - P0
        r = q - (q @ ax)[:, None] * ax
        rp = np.linalg.norm(r, axis=1)
        eth = np.cross(ax, r / np.maximum(rp, 1e-9)[:, None])
        ndot = (eth * nrm).sum(1)
        tang = np.linalg.norm(eth - ndot[:, None] * nrm, axis=1)
        out = {"job": job, "mu": mu}
        for s in ("RELEASE", "LOAD"):
            c = PM._ctab(d / "m_fric_csv" / f"{s}_CONTACT.csv", n)["CPRESS"][pb]
            c = np.where(np.isfinite(c), np.maximum(c, 0.0), 0.0)
            out[f"T_fric_{s}_Nm"] = float(mu * (w * c * rp * tang).sum()) / 1000.0
            out[f"Fn_{s}_N"] = float((w * c).sum())
            out[f"rp_eff_{s}_mm"] = float((w * c * rp).sum() / max((w * c).sum(), 1e-12))
        out["K_key_mm3"] = float((w * rp * np.abs(ndot)).sum())
        out["K_key_rel"] = float((w * rp * np.abs(ndot)).sum() / max((w * rp).sum(), 1e-12))
        F = M.load_vector(fm.cfg)
        out["T_head_Nm"] = float(np.cross(fm.H - P0, F) @ ax) / 1000.0
        out["err"] = ""
        return out
    except Exception as e:  # noqa: BLE001
        return {"job": job, "err": f"{type(e).__name__}: {e}"[:300]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(TABLE, encoding="utf-8")))
    jobs = [r["job"] for r in rows if r["current_code"] == "True" and r["variant_class"] == "none"
            and r["collar_rule"] == "neck_in_shoulder"]
    t0 = time.time()
    with Pool(2) as pool:
        res = pool.map(one, jobs, chunksize=4)
    keys = sorted({k for r in res for k in r}, key=lambda k: (k != "job", k))
    with open(OUT / "spin_proxy.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=keys)
        wr.writeheader()
        wr.writerows(res)
    print(len(jobs), "jobs", sum(1 for r in res if r.get("err")), "errors", f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
