"""Read-only robustness check of the stability.py rigid-fit rotation split (axial vs tilt) on a few phase-10 jobs.
Reads ~/mobo_toy_v2/queue/<job>/ (mesh3d.npz, spec/result/prep json, m_fric_csv/*_U.csv); writes nothing to queue/results/code.
Variants: all body pairs (reproduces stability), proximal half, distal half, unweighted, and an independent spin estimate
from the area-weighted signed circumferential relative displacement / radius.
"""
import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code"))
sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import stability as ST  # noqa: E402

JOBS = ["neck10_a57_09bff191", "neck10_a64_2649f8de", "neck10_a68_2302d773", "neck10_a69_e394e85c",
        "neck10_a12_b1fbfd1c", "neck10_a59_0f44d7e2", "neck10_a24_41b88dd9", "neck10_a36_0911f520",
        "neck10_a19_c15fe9c6", "neck10_a46_be288f8f"]


def split(om, ax):
    a = float(om @ ax)
    return np.degrees(abs(a)), np.degrees(np.linalg.norm(om - a * ax))


def one(job):
    d = J.QROOT / job
    p = PM.pairs(d)
    spec = json.loads((d / "spec.json").read_text())
    res = json.loads((d / "result.json").read_text())
    t = res.get("templating") or json.loads((d / "prep.json").read_text()).get("templating")
    fm = J.femur_for(spec)
    P0, ax, _, _ = fm.pose(t["alpha"], t["e"])
    ax = ax / np.linalg.norm(ax)
    lut = {int(n): i for i, n in enumerate(p["node_labels"])}
    X = np.array([p["nodes"][lut[int(n)]] for n in p["pair_bone"]])
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("RELEASE", "LOAD")}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in U}
    body = ~p["pair_collar"]
    w = p["pair_area"]
    Rr = (rel["LOAD"] - rel["RELEASE"])
    s_ax = (X - P0) @ ax
    out = {"job": job}
    med = np.median(s_ax[body])
    subsets = {"all": body, "prox": body & (s_ax <= med), "dist": body & (s_ax > med)}
    for name, msk in subsets.items():
        tr, om, c, rms = ST.rigid_fit(X[msk], Rr[msk], w[msk])
        a, tl = split(om, ax)
        out[name] = {"axial": round(a, 5), "tilt": round(tl, 5), "rms_um": round(rms * 1e3, 2)}
    tr, om, c, rms = ST.rigid_fit(X[body], Rr[body], None)
    a, tl = split(om, ax)
    out["unweighted"] = {"axial": round(a, 5), "tilt": round(tl, 5), "rms_um": round(rms * 1e3, 2)}
    # independent spin estimate: area-weighted mean of circumferential rel. displacement / radius
    q = X[body] - P0
    radial = q - (q @ ax)[:, None] * ax
    r = np.linalg.norm(radial, axis=1)
    e_th = np.cross(ax, radial / np.maximum(r, 1e-9)[:, None])
    ut = (Rr[body] * e_th).sum(1)
    wb = w[body]
    spin = float(np.degrees((wb * ut * r).sum() / (wb * r * r).sum()))
    out["spin_circ_deg"] = round(abs(spin), 5)
    out["circ_arc_med_um"] = round(float(np.median(np.abs(ut))) * 1e3, 2)
    out["r_med_mm"] = round(float(np.median(r)), 2)
    return out


if __name__ == "__main__":
    for j in JOBS:
        try:
            print(json.dumps(one(j)), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"job": j, "err": repr(e)[:300]}), flush=True)
