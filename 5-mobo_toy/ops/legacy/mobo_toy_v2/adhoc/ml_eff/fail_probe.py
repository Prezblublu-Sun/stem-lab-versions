"""Identify the geometric entities behind the L3 'overlapping facets' / PLC failures (no meshing, no queue writes).

For each failed job: re-run templating exactly as jobs.prep, rebuild the OCC geometry of model3d_m1._build up to
fragment + synchronize, then describe the surfaces named in FAILED.json ('on surface A surface B') and the
low-numbered mesh nodes named in prep.log (nodes on CAD points), in the resection-plane frame.

    run.sh probe.py <job> [<job> ...]     -> ~/mobo_toy_v2/deck/ml_eff/failures/probe/<job>.json
"""
from __future__ import annotations

import json
import pathlib
import re
import resource
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

resource.setrlimit(resource.RLIMIT_AS, (8 << 30, 8 << 30))
OUT = FG.HOME / "deck" / "ml_eff" / "failures" / "probe"
OUT.mkdir(parents=True, exist_ok=True)


def describe_surface(gmsh, tag, vol_class, fm):
    up, down = gmsh.model.getAdjacencies(2, tag)
    bb = gmsh.model.getBoundingBox(2, tag)
    pts = sorted({t for d, t in gmsh.model.getBoundary([(2, tag)], combined=False, recursive=True) if d == 0})
    info = {"tag": tag, "type": gmsh.model.getType(2, tag), "area_mm2": float(gmsh.model.occ.getMass(2, tag)),
            "volumes": [(int(v), vol_class.get(int(v), "?")) for v in up], "n_curves": len(down),
            "curves": [int(c) for c in down][:40], "points": pts[:60],
            "bbox": [round(float(x), 3) for x in bb]}
    # centre of mass, in the cut-plane frame
    try:
        com = gmsh.model.occ.getCenterOfMass(2, tag)
        info["com_plane"] = [round(v, 3) for v in FG.plane_coords(fm, com)]
    except Exception:                                                # noqa: BLE001
        pass
    return info


def describe_point(gmsh, tag, fm):
    try:
        X = gmsh.model.getValue(0, tag, [])
    except Exception as e:                                           # noqa: BLE001
        return {"tag": tag, "err": str(e)[:100]}
    up, _ = gmsh.model.getAdjacencies(0, tag)
    h, r, a, b = FG.plane_coords(fm, X)
    return {"tag": tag, "xyz": [round(float(v), 4) for v in X], "h_above_cut": round(h, 4), "r_from_C03": round(r, 4),
            "e1": round(a, 4), "e2": round(b, 4), "curves": [int(c) for c in up],
            "canal_sdf": float(fm.canal_sdf(np.asarray(X)[None])[0]), "outer_sdf": float(fm.outer_sdf(np.asarray(X)[None])[0])}


def run(job):
    import gmsh
    t0 = time.time()
    d = FG.J.QROOT / job
    spec = FG.load_spec(job)
    fail = json.loads((d / "FAILED.json").read_text()) if (d / "FAILED.json").exists() else {}
    reason = fail.get("reason", "")
    log = (d / "prep.log").read_text(errors="replace") if (d / "prep.log").exists() else ""
    surf_ids = sorted({int(x) for pair in re.findall(r"on surface (\d+) surface (\d+)", reason) for x in pair})
    node_ids = sorted({int(x) for tri in re.findall(r"\[(\d+), (\d+), (\d+)\]", log) for x in tri if int(x) < 200})
    st, fm, pl = FG.template_for(spec)
    rec = {"job": job, "family": spec.get("stage"), "collar_rule": spec.get("collar_rule"), "design": spec["design"],
           "h_cut": spec.get("h_cut"), "fail_level": fail.get("level"), "reason_head": reason[:400],
           "surf_ids": surf_ids, "node_ids_lowtag": node_ids, "prep_log": log[:1500], "code_hash": FG.J.code_hash()}
    if not pl.get("fit"):
        rec["templating"] = {"fit": False, "reason": pl.get("reason")}
        return rec
    rec["templating"] = {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in pl.items()
                         if k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin", "neck_overhang_mm2")}
    rec["thin"] = FG.thin_layer(st, fm, pl["A0"], pl["pose"])
    rec["neck"] = FG.neck_clearance(st, fm, pl["A0"], pl["pose"])
    gmsh.initialize()
    try:
        g = FG.occ_geometry(st, fm, pl, sec_pts=40, rule=spec.get("collar_rule"))
        vol_class = {**{v: "cortex" for v in g["cort_vols"]}, **{v: "cancellous" for v in g["canc_vols"]},
                     **{v: "stem" for v in g["stem_vols"]}}
        rec["n_surfaces"] = len(gmsh.model.getEntities(2))
        rec["n_points"] = len(gmsh.model.getEntities(0))
        rec["vols"] = {k: g[k] for k in ("cort_vols", "canc_vols", "stem_vols")}
        rec["surfaces"] = [describe_surface(gmsh, s, vol_class, fm) for s in surf_ids if (2, s) in gmsh.model.getEntities(2)]
        rec["points"] = [describe_point(gmsh, p, fm) for p in node_ids]
        # all small surfaces (< 1 mm2) and short curves (< 0.5 mm) anywhere in the model: knife edges / slivers
        small = []
        for _, s in gmsh.model.getEntities(2):
            a = gmsh.model.occ.getMass(2, s)
            if a < 1.0:
                up, _ = gmsh.model.getAdjacencies(2, s)
                small.append({"tag": s, "area_mm2": float(a), "type": gmsh.model.getType(2, s),
                              "volumes": [vol_class.get(int(v), "?") for v in up],
                              "com_plane": [round(v, 3) for v in FG.plane_coords(fm, gmsh.model.occ.getCenterOfMass(2, s))]})
        rec["small_surfaces"] = sorted(small, key=lambda x: x["area_mm2"])[:30]
        short = []
        for _, c in gmsh.model.getEntities(1):
            ln = gmsh.model.occ.getMass(1, c)
            if ln < 0.5:
                short.append({"tag": c, "len_mm": float(ln),
                              "com_plane": [round(v, 3) for v in FG.plane_coords(fm, gmsh.model.occ.getCenterOfMass(1, c))]})
        rec["short_curves"] = sorted(short, key=lambda x: x["len_mm"])[:30]
        # surfaces of the stem volume touching the cut plane (h ~ 0) and their types
        stem_plane = []
        for s in g["stem_surfs"]:
            bb = gmsh.model.getBoundingBox(2, s)
            stem_plane.append({"tag": s, "type": gmsh.model.getType(2, s), "area_mm2": float(gmsh.model.occ.getMass(2, s)),
                               "com_plane": [round(v, 3) for v in FG.plane_coords(fm, gmsh.model.occ.getCenterOfMass(2, s))]})
        rec["stem_surfaces"] = stem_plane
    except Exception as e:                                           # noqa: BLE001
        rec["geom_err"] = f"{type(e).__name__}: {e}"[:500]
    finally:
        gmsh.finalize()
    rec["wall_s"] = time.time() - t0
    return rec


if __name__ == "__main__":
    for job in sys.argv[1:]:
        r = run(job)
        (OUT / f"{job}.json").write_text(json.dumps(r, indent=1, default=float))
        print(job, "surfaces", [(s["tag"], s["type"], round(s["area_mm2"], 3), s["volumes"]) for s in r.get("surfaces", [])],
              "| points", [(p.get("tag"), p.get("h_above_cut"), p.get("r_from_C03")) for p in r.get("points", [])],
              "| neck", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.get("neck", {}).items()},
              "| thin min", round(r.get("thin", {}).get("tl_min_mm", float("nan")), 3), "| wall", round(r.get("wall_s", 0), 1), flush=True)
