"""OCC face / edge scan before meshing (read-only on the queue; nothing is meshed or written to the queue).

For each job: templating (stored for DONE, recomputed for FAILED), then the OCC geometry of model3d_m1._build up to
fragment + synchronize (fail_fgeom.occ_geometry, a line-by-line mirror), then statistics of the small faces and short
edges that make the surface mesher fail ("overlapping facets", "PLC: a segment and a facet intersect").

    run.sh fail_occscan.py --set failed|collarless|sample|<job,job,...> [--workers 4] [--n-sample 60]
        -> deck/ml_eff/failures/occscan/occscan_<set>.json   (one record per job)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import resource
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

OUT = FG.HOME / "deck" / "ml_eff" / "failures" / "occscan"
FEAT = FG.HOME / "deck" / "ml_eff" / "failures" / "features.json"
AREA_TH = (0.01, 0.05, 0.1, 0.5)
EDGE_TH = (0.05, 0.1, 0.25)


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))


def pl_for(job, spec):
    """(st, fm, pl): stored templating for DONE jobs, recomputed otherwise."""
    d = FG.J.QROOT / job
    stored = None
    for f in ("result.json", "prep.json"):
        if (d / f).exists():
            stored = json.loads((d / f).read_text()).get("templating")
            if stored:
                break
    if stored:
        fm = FG.femur_for(spec)
        st = FG.G.Stem3D(**spec["design"])
        pl = dict(stored)
        pl["pose"] = fm.pose(stored["alpha"], stored["e"])
        pl["fit"] = True
        return st, fm, pl, "stored"
    st, fm, pl = FG.template_for(spec)
    return st, fm, pl, "recomputed"


def scan(job):
    import gmsh
    t0 = time.time()
    d = FG.J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    rec = {"job": job, "state": FG.J.state(d), "stage": spec.get("stage"), "collar_rule": spec.get("collar_rule"),
           "collar_w": float(spec["design"].get("collar_w", 0.0) or 0.0), "m": spec["design"].get("m")}
    named = []
    if (d / "FAILED.json").exists():
        reason = json.loads((d / "FAILED.json").read_text()).get("reason", "")
        named = sorted({int(x) for pair in re.findall(r"on surface (\d+) surface (\d+)", reason) for x in pair})
        rec["fail_reason_head"] = reason[:200]
    try:
        st, fm, pl, src = pl_for(job, spec)
        rec["tpl_src"] = src
        if not pl.get("fit"):
            rec["err"] = f"templating no fit: {pl.get('reason')}"
            return rec
    except Exception as e:                                                   # noqa: BLE001
        rec["err"] = f"templating {type(e).__name__}: {e}"[:300]
        return rec
    gmsh.initialize()
    try:
        g = FG.occ_geometry(st, fm, pl, sec_pts=40, rule=spec.get("collar_rule"))
        cls = {**{v: "cortex" for v in g["cort_vols"]}, **{v: "cancellous" for v in g["canc_vols"]}, **{v: "stem" for v in g["stem_vols"]}}
        faces = []
        for _, s in gmsh.model.getEntities(2):
            up, _ = gmsh.model.getAdjacencies(2, s)
            vc = tuple(sorted(cls.get(int(v), "?") for v in up))
            a = float(gmsh.model.occ.getMass(2, s))
            com = gmsh.model.occ.getCenterOfMass(2, s)
            h, r, e1, e2 = FG.plane_coords(fm, com)
            faces.append({"tag": int(s), "area": a, "type": gmsh.model.getType(2, s), "vols": vc, "h": h, "r": r, "e1": e1, "e2": e2})
        edges = []
        for _, c in gmsh.model.getEntities(1):
            ln = float(gmsh.model.occ.getMass(1, c))
            edges.append(ln)
        edges = np.array(edges)
        iface = [f for f in faces if "stem" in f["vols"] and ("cortex" in f["vols"] or "cancellous" in f["vols"])]
        cutp = [f for f in iface if f["type"] == "Plane" and abs(f["h"]) < 1e-3]               # stem faces lying on the resection plane
        neckp = [f for f in cutp if abs(f["r"] - 7.0) < 0.6]                                     # ... at the neck-base circle radius
        sc = [f for f in faces if f["vols"] == ("cortex", "stem")]
        rec.update({"n_faces": len(faces), "n_edges": int(len(edges)), "n_iface_faces": len(iface),
                    "min_face_mm2": float(min(f["area"] for f in faces)),
                    "min_iface_face_mm2": float(min(f["area"] for f in iface)) if iface else None,
                    "min_cutplane_iface_face_mm2": float(min(f["area"] for f in cutp)) if cutp else None,
                    "n_cutplane_iface_faces": len(cutp),
                    "min_neckbase_sliver_mm2": float(min(f["area"] for f in neckp)) if neckp else None,
                    "n_neckbase_faces": len(neckp),
                    "min_cortex_stem_face_mm2": float(min(f["area"] for f in sc)) if sc else None,
                    "n_cortex_stem_faces": len(sc),
                    "min_edge_mm": float(edges[edges > 1e-9].min()) if (edges > 1e-9).any() else None,
                    "n_zero_edges": int((edges <= 1e-9).sum())})
        for th in AREA_TH:
            rec[f"n_faces_lt{th:g}"] = int(sum(f["area"] < th for f in faces))
            rec[f"n_iface_faces_lt{th:g}"] = int(sum(f["area"] < th for f in iface))
        for th in EDGE_TH:
            rec[f"n_edges_lt{th:g}"] = int(((edges > 1e-9) & (edges < th)).sum())
        rec["small_faces"] = sorted([{k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()} for f in faces if f["area"] < 0.5],
                                    key=lambda f: f["area"])[:12]
        rec["named"] = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()} for f in faces if f["tag"] in named]
        rec["named_tags"] = named
    except Exception as e:                                                   # noqa: BLE001
        rec["err"] = f"occ {type(e).__name__}: {e}"[:300]
    finally:
        gmsh.finalize()
    rec["wall_s"] = time.time() - t0
    return rec


def job_set(name, n_sample):
    feat = json.loads(FEAT.read_text())
    if name == "failed":
        return [r["job"] for r in feat if r["state"] == "FAILED"]
    if name == "collarless":
        return [r["job"] for r in feat if r["state"] == "DONE" and not (r.get("collar_w") or 0) > 0]
    if name == "sample":
        rng = np.random.default_rng(0)
        pool = [r["job"] for r in feat if r["state"] == "DONE" and (r.get("collar_w") or 0) > 0 and not r.get("cfg")]
        return sorted(rng.choice(pool, size=min(n_sample, len(pool)), replace=False).tolist())
    return name.split(",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--n-sample", type=int, default=60)
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = job_set(a.set, a.n_sample)
    tag = a.tag or (a.set if "," not in a.set else "custom")
    print(f"{len(jobs)} jobs ({tag})", flush=True)
    t0 = time.time()
    res = []
    with Pool(a.workers, initializer=_limit, maxtasksperchild=4) as p:
        for r in p.imap_unordered(scan, jobs):
            res.append(r)
            print(f"[{len(res)}/{len(jobs)} {time.time() - t0:.0f}s] {r['job']} {r['state']} min_face {r.get('min_face_mm2')} "
                  f"neck {r.get('min_neckbase_sliver_mm2')} cs {r.get('min_cortex_stem_face_mm2')} edge {r.get('min_edge_mm')} "
                  f"named {[(n['tag'], round(n['area'], 3), n['vols']) for n in r.get('named', [])]} err {r.get('err')} wall {r.get('wall_s', 0):.0f}",
                  flush=True)
            if len(res) % 10 == 0:
                (OUT / f"occscan_{tag}.json").write_text(json.dumps(res, default=float))
    (OUT / f"occscan_{tag}.json").write_text(json.dumps(res, default=float))
    print(f"done {len(res)} in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
