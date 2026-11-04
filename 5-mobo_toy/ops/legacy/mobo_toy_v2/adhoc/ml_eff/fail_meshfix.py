"""Mesh-robustness experiment (no FE jobs, nothing written to the queue, code imported read-only).

Rebuilds the M1 model of selected jobs with model3d_m1._build into a scratch directory under
deck/ml_eff/failures/meshfix/tmp/, for ONE mesh attempt = the first production attempt (Algorithm3D 1, the spec h_int,
40 section points), under candidate fixes:

  base      production settings (must reproduce the failure of a FAILED job / the stored mesh of a DONE job)
  fuzzy01   gmsh Geometry.ToleranceBoolean = 0.01 mm (OCC fuzzy booleans), set right after gmsh.initialize
  fuzzy05   Geometry.ToleranceBoolean = 0.05 mm
  fuzzy10   Geometry.ToleranceBoolean = 0.1 mm
  facetol   Mesh.AngleToleranceFacetOverlap = 0.01 rad (default 0.1; the check that raises "overlapping facets")
  neckr     diagnostic only: prosthetic neck radius reduced so the neck-base circle lies inside the shoulder footprint with
            0.3 mm clearance (r = 7 + min(0, dev_min) - 0.3); removes the neck/footprint near-tangency

Per run: ok / error, wall time, n_tet per region, n_nodes, n_pairs, interface area, cortex area fraction, stem volume,
mesh quality; DONE jobs also get the stored prep.json values for comparison. The .inp / npz files are deleted after reading.

    run.sh fail_meshfix.py --jobs j1,j2,... --variants base,fuzzy01,... [--workers 4]
        -> deck/ml_eff/failures/meshfix/meshfix_<tag>.json
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import resource
import shutil
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fail_fgeom as FG  # noqa: E402

OUT = FG.HOME / "deck" / "ml_eff" / "failures" / "meshfix"
VARIANTS = {"base": {}, "fuzzy01": {"Geometry.ToleranceBoolean": 0.01}, "fuzzy05": {"Geometry.ToleranceBoolean": 0.05},
            "fuzzy10": {"Geometry.ToleranceBoolean": 0.1}, "facetol": {"Mesh.AngleToleranceFacetOverlap": 0.01}, "neckr": {},
            # added 2026-10-22 (resume run): local refinement around the neck base and a different 2D surface mesher
            "lref05": {}, "lref025": {}, "alg2d1": {}}
# lrefXX: local refinement: Distance field from every curve lying in the resection plane within 12 mm of the neck-base centre
#         C03 (neck circle, stem-footprint outline, sliver edges) -> Threshold (size XX mm within 0.3 mm, h_far beyond 3 mm),
#         combined with the production Threshold field by Min (model3d_m1._size_field wrapped in-process)
# alg2d1: Mesh.Algorithm (2D) = 1 (MeshAdapt) instead of the production 6 (Frontal-Delaunay) (M1.MESH_OPTS patched in-process)
LREF = {"lref05": 0.5, "lref025": 0.25}


def _limit():
    resource.setrlimit(resource.RLIMIT_AS, (7 << 30, 7 << 30))


def run(task):
    job, var = task
    import gmsh
    import model3d_m1 as M1
    import fe3d_geom as E
    t0 = time.time()
    d = FG.J.QROOT / job
    spec = json.loads((d / "spec.json").read_text())
    rec = {"job": job, "variant": var, "state": FG.J.state(d), "stage": spec.get("stage"), "collar_rule": spec.get("collar_rule")}
    tmp = OUT / "tmp" / f"{job}__{var}"
    orig_init = gmsh.initialize
    orig_sf, orig_opts = M1._size_field, M1.MESH_OPTS
    try:
        E.collar_outline = FG._ORIG_COLLAR_OUTLINE
        if spec.get("collar_rule") == "wrap_fit":                      # as jobs.prep: collar_rule.install (in this process only)
            import collar_rule as CR
            E.collar_outline = CR.collar_outline_wrap
        # templating: stored (DONE) or recomputed (FAILED)
        stored = None
        for f in ("result.json", "prep.json"):
            if (d / f).exists():
                stored = json.loads((d / f).read_text()).get("templating")
                if stored:
                    break
        if stored:
            fm = FG.femur_for(spec)
            st = FG.G.Stem3D(**spec["design"])
            pl = dict(stored, fit=True, pose=fm.pose(stored["alpha"], stored["e"]))
        else:
            st, fm, pl = FG.template_for(spec)
            if not pl.get("fit"):
                rec["err"] = f"templating no fit: {pl.get('reason')}"
                return rec
        if var == "neckr":
            nk = FG.neck_clearance(st, fm, pl["A0"], pl["pose"])
            r0 = float(fm.cfg["prosthesis"]["neck_radius_mm"])
            r_new = r0 + min(0.0, float(nk.get("neck_dev_min_mm", 0.0))) - 0.3
            fm = copy.copy(fm)
            fm.cfg = copy.deepcopy(fm.cfg)
            fm.cfg["prosthesis"]["neck_radius_mm"] = r_new
            rec["neck_radius_mm"] = r_new
        opts = VARIANTS[var]
        if var in LREF:
            import numpy as _np
            hloc, c0, u3 = LREF[var], _np.asarray(fm.C03, float), _np.asarray(fm.u3, float)

            def sf(gm, surfs, cfg, h_int, h_far):
                orig_sf(gm, surfs, cfg, h_int, h_far)
                F = gm.model.mesh.field
                bg = max(F.list())                                           # the production Threshold field (last added)
                # curves lying in the resection plane within 12 mm of the neck-base centre (neck circle, footprint outline, slivers)
                cut = []
                for _, t in gm.model.getEntities(1):
                    lo, hi = gm.model.getParametrizationBounds(1, t)
                    uu = _np.linspace(lo[0], hi[0], 9)
                    P = _np.asarray(gm.model.getValue(1, t, list(uu)), float).reshape(-1, 3) - c0
                    hgt = P @ u3
                    rad = _np.linalg.norm(P - _np.outer(hgt, u3), axis=1)
                    if _np.abs(hgt).max() < 0.02 and rad.min() < 12.0:
                        cut.append(t)
                rec["n_refined_curves"] = len(cut)
                if not cut:
                    return
                fd = F.add("Distance")
                F.setNumbers(fd, "CurvesList", cut)
                F.setNumber(fd, "Sampling", 200)
                ft = F.add("Threshold")
                for kk, vv in (("InField", fd), ("SizeMin", hloc), ("SizeMax", h_far), ("DistMin", 0.3), ("DistMax", 3.0)):
                    F.setNumber(ft, kk, vv)
                mn = F.add("Min")
                F.setNumbers(mn, "FieldsList", [bg, ft])
                F.setAsBackgroundMesh(mn)
            M1._size_field = sf
            rec["local_size_mm"] = hloc
        if var == "alg2d1":
            M1.MESH_OPTS = tuple((k, 1 if k == "Mesh.Algorithm" else v) for k, v in orig_opts)

        def init(*a, **k):
            orig_init(*a, **k)
            for kk, vv in opts.items():
                gmsh.option.setNumber(kk, vv)
        gmsh.initialize = init
        tmp.mkdir(parents=True, exist_ok=True)
        info = M1._build(st, fm, pl, tmp, "m", h_int=spec["h_int"], h_far=spec.get("h_far") or fm.cfg["mesh"]["h_far_mm"],
                         delta=spec.get("delta"), mu=spec.get("mu"), torque=spec.get("torque", True), algo=1, sec_pts=40,
                         E_canc=spec.get("E_canc"), slip_tol=spec.get("slip_tol") if spec.get("slip_tol") is not None else M1.DEFAULTS["slip_tol"],
                         lagrange=spec.get("lagrange") if spec.get("lagrange") is not None else M1.DEFAULTS["lagrange"],
                         interference=spec.get("interference") or M1.DEFAULTS["interference"],
                         cycles=int(spec.get("cycles") or 2))
        rec["ok"] = True
        rec.update({k: info.get(k) for k in ("n_tet", "n_nodes", "n_pairs", "n_pairs_cortex", "interface_area_mm2", "cortex_area_frac",
                                             "stem_volume_mm3", "mesh_quality", "n_slave_faces")})
    except Exception as e:                                                   # noqa: BLE001
        rec["ok"] = False
        rec["err"] = f"{type(e).__name__}: {e}"[:400]
        rec["level"] = getattr(e, "level", None)
    finally:
        gmsh.initialize = orig_init
        M1._size_field, M1.MESH_OPTS = orig_sf, orig_opts
        shutil.rmtree(tmp, ignore_errors=True)
    if (d / "prep.json").exists():
        p = json.loads((d / "prep.json").read_text())
        rec["stored"] = {k: p.get(k) for k in ("n_tet", "n_nodes", "n_pairs", "interface_area_mm2", "cortex_area_frac", "stem_volume_mm3")}
        rec["stored"]["mesh_attempt"] = {k: (p.get("mesh_attempt") or {}).get(k) for k in ("algorithm3d", "h_int", "section_points")}
        rec["stored"]["n_previous_errors"] = len((p.get("mesh_attempt") or {}).get("previous_errors") or [])
    rec["wall_s"] = time.time() - t0
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--variants", default="base,fuzzy01,fuzzy05,facetol")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = a.jobs.split(",")
    tasks = [(j, v) for j in jobs for v in a.variants.split(",")]
    print(f"{len(tasks)} builds", flush=True)
    t0 = time.time()
    res = []
    with Pool(a.workers, initializer=_limit, maxtasksperchild=1) as p:
        for r in p.imap_unordered(run, tasks):
            res.append(r)
            nt = r.get("n_tet") or {}
            snt = (r.get("stored") or {}).get("n_tet") or {}
            print(f"[{len(res)}/{len(tasks)} {time.time() - t0:.0f}s] {r['job']} {r['variant']} ok={r.get('ok')} "
                  f"tet={sum(nt.values()) if nt else None} stored={sum(snt.values()) if snt else None} pairs={r.get('n_pairs')} "
                  f"area={r.get('interface_area_mm2')} err={str(r.get('err'))[:150]} wall={r['wall_s']:.0f}", flush=True)
            (OUT / f"meshfix_{a.tag}.json").write_text(json.dumps(res, default=float))
    print(f"done {len(res)} in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
