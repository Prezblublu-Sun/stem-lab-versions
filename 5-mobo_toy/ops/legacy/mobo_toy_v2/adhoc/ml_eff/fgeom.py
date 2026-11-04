"""Shared helpers for the failure analysis (read-only use of ~/mobo_toy_v2/code; nothing in the queue is written).

* setup_paths()            : sys.path for the mobo code
* template_for(spec)       : femur + stem + templating exactly as jobs.prep does it (collar rule installed in THIS process only)
* thin_layer(st, fm, pl)   : cancellous-layer thickness between stem surface and cortex (t = -canal_sdf at stem surface points
                             below the cut plane, area weighted), plus near-cortex statistics
* neck_clearance(...)      : in-plane clearance between the prosthetic neck base circle (r 7, centred on C03) and the stem
                             footprint on the resection plane (negative = neck base protrudes out of the footprint)
* occ_geometry(...)        : the OCC geometry of model3d_m1._build up to fragment+synchronize (no meshing), so surface /
                             point tags can be identified. Mirrors the code of model3d_m1._build line by line.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"


def setup_paths():
    for p in (str(HOME / "code"), str(HOME / "code" / "v2")):
        if p not in sys.path:
            sys.path.insert(0, p)


setup_paths()
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

_ORIG_TEMPLATE = G.template
_FM_BASE = {}


def femur_for(spec):
    """Same as jobs.femur_for but caches the expensive FR.build()."""
    import copy
    if "fm" not in _FM_BASE:
        _FM_BASE["fm"] = FR.build()
    fm = _FM_BASE["fm"]
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(spec["h_cut"])
    if spec.get("cfg"):
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        J._merge(fm.cfg, spec["cfg"])
    return fm


def template_for(spec: dict):
    """Returns (st, fm, pl) as jobs.prep would build them (design/variant kinds)."""
    import collar_rule as CR
    G.template = _ORIG_TEMPLATE
    fm = femur_for(spec)
    rule = spec.get("collar_rule")
    min_A0 = float(spec.get("min_A0", 0.0))
    if rule == "wrap_fit":
        tpl = lambda st, fm_, margin=None: CR.template_wrap_fit(st, fm_, margin=margin, min_A0=min_A0)  # noqa: E731
    elif rule == "neck_in_shoulder":
        tpl = lambda st, fm_, margin=None: CR.template_neck_in_shoulder(st, fm_, margin=margin, min_A0=min_A0)  # noqa: E731
    else:
        tpl = lambda st, fm_, margin=None: _ORIG_TEMPLATE(st, fm_, margin=margin)  # noqa: E731
    if spec.get("entry_offset") is not None:
        e = np.array([float(spec["entry_offset"])])
        tpl = lambda st, fm_, margin=None: _ORIG_TEMPLATE(st, fm_, offsets=e, margin=margin)  # noqa: E731
    st = G.Stem3D(**spec["design"])
    pl = tpl(st, fm, margin=spec.get("margin"))
    return st, fm, pl


def pose_from(fm, alpha, e):
    return fm.pose(alpha, e)


# --------------------------------------------------------------------------------------------- thin layer
def stem_surface(st, A0, s_top=-15.0, ds=0.25, m=180):
    """Area-weighted stem surface quads (local coords s, x, y of the quad centroids, quad areas).
    Body s in [s_top, L] (s < 0 = constant prism up to the cut); the tip cap is added as rings."""
    sec = G.unit_section(st.d, m)
    s = np.arange(s_top, st.L + 1e-9, ds)
    if s[-1] < st.L:
        s = np.r_[s, st.L]
    k = np.sqrt(A0 * st.area_ratio(s))
    c = st.cap_length(A0)
    kt = math.sqrt(A0 * st.rho_tip)
    tc = np.linspace(0, 1, 13)[1:]
    s = np.r_[s, st.L + c * tc]
    k = np.r_[k, kt * np.sqrt(np.clip(1 - tc ** 2, 0, 1))]
    rings = np.stack([np.c_[np.full(m, si), ki * sec] for si, ki in zip(s, k)])     # (ns, m, 3)
    a = rings[:-1, :, :]
    b = rings[1:, :, :]
    a2 = np.roll(a, -1, axis=1)
    b2 = np.roll(b, -1, axis=1)
    cen = 0.25 * (a + b + a2 + b2)
    ar = 0.5 * np.linalg.norm(np.cross(b - a, a2 - a), axis=2) + 0.5 * np.linalg.norm(np.cross(b2 - b, a2 - b), axis=2)
    return cen.reshape(-1, 3), ar.reshape(-1)


def thin_layer(st, fm, A0, pose, thresholds=(0.5, 0.6, 0.75, 1.0, 1.5, 2.0)):
    loc, ar = stem_surface(st, A0)
    P = fm.to_world(loc, pose)
    keep = fm.below_cut(P)
    P, ar, loc = P[keep], ar[keep], loc[keep]
    t = -fm.canal_sdf(P)                     # > 0: cancellous between stem surface and endosteal surface (mm)
    to = -fm.outer_sdf(P)                    # distance to the periosteal surface (mm)
    out = {"tl_area_total_mm2": float(ar.sum()), "tl_min_mm": float(t.min()),
           "tl_p01_mm": float(np.percentile(t, 1)), "tl_p05_mm": float(np.percentile(t, 5)),
           "tl_wmed_mm": float(np.median(t)), "tl_outer_min_mm": float(to.min()),
           "tl_area_lt0_mm2": float(ar[t < 0].sum()),
           "tl_area_graze_mm2": float(ar[np.abs(t) < 0.25].sum())}
    for th in thresholds:
        out[f"tl_area_lt{th:g}_mm2"] = float(ar[t < th].sum())
    # where is the thinnest region: axial position s and distance below the cut plane
    i = int(np.argmin(t))
    out["tl_min_s_mm"] = float(loc[i, 0])
    out["tl_min_depth_mm"] = float(-((P[i] - fm.C03) @ fm.u3))
    # number of separate thin patches is not needed; give the axial extent of the < 1 mm band
    band = t < 1.0
    out["tl_band1_s_extent_mm"] = float(np.ptp(loc[band, 0])) if band.any() else 0.0
    # near the cut plane (top 3 mm below the cut): thinnest layer there (the planar cancellous ring at the cut)
    depth = -((P - fm.C03) @ fm.u3)
    top = depth < 3.0
    out["tl_top3_min_mm"] = float(t[top].min()) if top.any() else float("nan")
    out["tl_top3_area_lt1_mm2"] = float(ar[top & (t < 1.0)].sum())
    return out


# --------------------------------------------------------------------------------------------- neck clearance
def neck_clearance(st, fm, A0, pose):
    """Footprint of the stem on the resection plane vs the neck base circle (r 7 about C03) and vs the endosteal outline."""
    import collar_rule as CR
    import fe3d_geom as E
    from shapely.geometry import Point
    r = float(fm.cfg["prosthesis"]["neck_radius_mm"])
    out = {}
    try:
        foot = CR.footprint(st, fm, A0, pose)
    except Exception as e:                                           # noqa: BLE001
        return {"nk_err": f"{type(e).__name__}: {e}"[:200]}
    o = Point(0.0, 0.0)
    d_c = float(foot.exterior.distance(o))
    inside = bool(foot.contains(o))
    out["foot_area_mm2"] = float(foot.area)
    out["neck_centre_inside"] = inside
    out["neck_clear_mm"] = (d_c - r) if inside else -(d_c + r)          # > 0: whole circle inside with this clearance
    circ = o.buffer(r, quad_segs=64)
    out["neck_overhang_mm2"] = float(circ.difference(foot).area)
    # endosteal outline on the cut plane: clearance between the footprint and the cortex (2D cancellous ring width)
    g, U, P = CR._plane_grid(fm)
    canal = E._loops(fm.canal_sdf(P).reshape(U.shape), g, 0.0)
    host = [p for p in canal if p.intersects(foot)]
    if host:
        hp = max(host, key=lambda p: p.intersection(foot).area)
        out["cut_ring_min_mm"] = float(hp.exterior.distance(foot.exterior)) if hp.contains(foot) else -float(foot.difference(hp).area)
        out["cut_canal_area_mm2"] = float(hp.area)
    return out


# --------------------------------------------------------------------------------------------- OCC geometry
def occ_geometry(st, fm, pl, sec_pts=40, name="m", rule=None, neck_r=None):
    """Mirror of model3d_m1._build up to occ.synchronize() (gmsh must be initialised by the caller).
    rule = spec collar_rule (wrap_fit swaps the collar outline as collar_rule.install does).
    neck_r overrides the prosthetic neck radius (diagnostic only).
    Returns dict with cort_vols, canc_vols, stem_vols, stem_surfs."""
    import gmsh
    import fe3d_geom as E
    from model3d_v2 import BuildError, _femur_shapes, _keep
    if rule == "wrap_fit":
        import collar_rule as CR
        E.collar_outline = CR.collar_outline_wrap
    cfg = fm.cfg
    pr = cfg["prosthesis"]
    A0, pose = pl["A0"], pl["pose"]
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    gmsh.model.add(name)
    occ = gmsh.model.occ
    C, K = _femur_shapes(occ, fm)
    Ck, _ = occ.intersect(C, _keep(occ, fm))
    Kk, _ = occ.intersect(K, _keep(occ, fm))
    body = E.stem_solid(occ, st, A0, pose, delta=0.0, m=sec_pts)
    body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
    collar_v = []
    if getattr(st, "has_collar", False):
        collar_info = E.collar_outline(st, fm, pl)
        collar_v = E.collar_solid(occ, fm, collar_info["poly"], st.collar_t)
    u3 = fm.u3
    a = fm.C03
    Lneck = float(np.linalg.norm(fm.H - a))
    neck = occ.addCylinder(*a, *(Lneck * u3), pr["neck_radius_mm"] if neck_r is None else float(neck_r))
    head = occ.addSphere(*fm.H, pr["head_radius_mm"])
    stem, _ = occ.fuse(body_in, [(3, neck), (3, head)] + collar_v)
    if len([1 for d_, _t in stem if d_ == 3]) != 1:
        raise BuildError("L1", "stem is not a single volume (neck base outside the shoulder?)")
    bone, _ = occ.cut(Ck, stem, removeObject=True, removeTool=False)
    canc, _ = occ.cut(Kk, stem, removeObject=True, removeTool=False)
    nb, nc = len(bone), len(canc)
    frag, fmap = occ.fragment(bone + canc, stem)
    occ.synchronize()
    cort_vols = sorted({t for dt in fmap[:nb] for d_, t in dt if d_ == 3})
    canc_vols = sorted({t for dt in fmap[nb:nb + nc] for d_, t in dt if d_ == 3})
    stem_vols = sorted({t for dt in fmap[nb + nc:] for d_, t in dt if d_ == 3})
    surfs = sorted({t for v in stem_vols for d_, t in gmsh.model.getBoundary([(3, v)], oriented=False) if d_ == 2})
    return {"cort_vols": cort_vols, "canc_vols": canc_vols, "stem_vols": stem_vols, "stem_surfs": surfs}


def plane_coords(fm, X):
    """World point -> (height above the cut plane along u3, in-plane radius from C03, in-plane coords e1, e2)."""
    import fe3d_geom as E
    C, e1, e2, nrm = E.cut_plane(fm)
    q = np.asarray(X, float) - C
    return float(q @ nrm), float(np.hypot(q @ e1, q @ e2)), float(q @ e1), float(q @ e2)


def load_spec(job):
    return json.loads((J.QROOT / job / "spec.json").read_text())
