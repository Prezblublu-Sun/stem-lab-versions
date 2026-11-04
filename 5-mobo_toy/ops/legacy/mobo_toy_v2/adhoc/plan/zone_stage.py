"""[zone_stage] band and fixed-zone low-SED fractions for the stage 1/2 designs of fork 4 (read-only). Based on: Fixed-depth zone under the cut (adhoc, read-only on the queue). Interim report v10, 2026-10-02.

Reviewer point: stem-set zone 7 (resorption.zones_femur, upper third of the stem's vertical extent, medial of the stem axis)
grows with stem length (0.3 cm3 at 25 mm, 2.3 cm3 at 60 mm), so part of the axis difference is "where it is measured".
Here: cortex below the cut, within D mm of the cut plane (along the neck axis), in the inferomedial half of the cut plane
((P - C03) . n3 >= 0). Independent of stem length, angle and section; moves only with the cut itself.
Also re-computes the stem-set zone 7 as a cross-check against plan_data.json (G7_res_ata).

    ./run.sh adhoc/plan/zone_depth.py      -> adhoc/plan/out/zone_depth.json
"""
from __future__ import annotations

import json
import pathlib
import sys
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path[:0] = [str(HOME / "code" / "v2"), str(HOME / "code")]
import jobs as J  # noqa: E402
import resorption as RS  # noqa: E402
import shielding as SH  # noqa: E402
import geom3d as G  # noqa: E402

OUT = HOME / "adhoc" / "plan" / "out"
DEPTHS = (5.0, 10.0, 15.0, 20.0)
S_LIST = (0.4, 0.6, 0.75)


def frac(m, ga, gi):
    n = int(m.sum())
    if n * RS.HG ** 3 < RS.MIN_VOL:
        return {"vol": n * RS.HG ** 3}
    r = ga["sed"][m] / gi["sed"][m]
    return {"vol": n * RS.HG ** 3, **{f"res_{s}": 100.0 * float(np.mean(r < 1.0 - s)) for s in S_LIST},
            "sed_chg": 100.0 * float(ga["sed"][m].mean() / gi["sed"][m].mean() - 1.0)}


def one(item):
    key, dname = item
    if "fm" not in RS._CTX:
        RS._init()
    d = J.QROOT / dname
    spec = json.loads((d / "spec.json").read_text())
    res = J.result(dname)
    t = res["templating"]
    stem = G.Stem3D(**spec["design"])
    h = float(spec.get("h_cut", 25.0))
    fm = RS._CTX["fm"].with_cut(h)
    pose = fm.pose(t["alpha"], t["e"])
    P, canc, gi = RS._CTX["P"], RS._CTX["canc"], RS._CTX["gi"]
    ga = RS.to_grid(SH.load_fields(d), P, canc, 1)
    loc = SH.local(P, pose)
    keep = (fm.below_cut(P) & ~G.inside_stem(stem, t["A0"], loc) & np.isfinite(ga["sed"]) & np.isfinite(gi["sed"]) & (gi["sed"] > 0))
    cort = keep & ~canc
    depth = -(P - fm.C03) @ fm.u3
    inf_med = (P - fm.C03) @ fm.n3 >= 0
    x_med = P[:, 0] >= 0
    Ltot = stem.L + stem.cap_length(t["A0"])
    zf = RS.zones_femur(P, pose, Ltot, fm.e_med0)
    out = {"key": key, "job": dname, "h_cut": h, "stemset_G7": frac(zf["G7"] & cort, ga, gi)}
    band = (depth > 0) & (depth <= 10.0)
    out["band10_n3"] = frac(band & inf_med & cort, ga, gi)
    zx = RS.zones_fixed(P)
    out["fixed_G7"] = frac(zx["G7"] & cort, ga, gi)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for ph in (1, 2):
        d = json.loads((HOME / "results" / f"neckopt_p{ph}.json").read_text())
        items += [(f"p{ph}:{r['job_id']}", r["job_id"]) for r in d["records"] if r.get("ok")]
    print(len(items), "designs", flush=True)
    with Pool(8, initializer=RS._init) as p:
        rows = p.map(one, items, chunksize=2)
    (OUT / "zone_stage.json").write_text(json.dumps(rows, indent=1))
    print("saved", OUT / "zone_stage.json", flush=True)


if __name__ == "__main__":
    main()
