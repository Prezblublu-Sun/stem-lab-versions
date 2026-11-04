"""无领柄设计预览（Linux，只读，不建 FE 作业）：阶段 9 设计空间里挑 6 个无领设计，各按两种选号规则重做模板化：
current          = 现行"号最大的偏移"（颈底可以伸出柄截口、压在截骨面上）；
neck_in_shoulder = 颈底必须整个落在截口里（用户 2026-10-07 定的无领规则）。
每个设计输出：截骨面上的骨标签图（皮质 / 松质）、两种规则的截口多边形、颈底圆、伸出面积；柄的表面 STL（柄体 ∩ 截骨面以下 + 颈 + 头）。
输出 ~/mobo_toy_v2/deck/preview9/{preview.json, <name>_bone.npz, <name>_<rule>.stl}"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402
from shapely.geometry import Point  # noqa: E402

import collar_rule as CR  # noqa: E402
import fe3d_geom as E  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import stage_neckopt as N  # noqa: E402

OUT = HOME / "deck" / "preview9"
MIN_A0 = 153.93804002589985


def stl_of(st, fm, pl, path):
    import gmsh
    pr = fm.cfg["prosthesis"]
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("p"); occ = gmsh.model.occ
        body = E.stem_solid(occ, st, pl["A0"], pl["pose"], delta=0.0, m=40)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        a = fm.C03; Lneck = float(np.linalg.norm(fm.H - a))
        neck = occ.addCylinder(*a, *(Lneck * fm.u3), pr["neck_radius_mm"])
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        occ.fuse(body_in, [(3, neck), (3, head)])
        occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0); gmsh.option.setNumber("Mesh.MeshSizeMin", 0.3)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def describe(st, fm, pl):
    foot = CR.footprint(st, fm, pl["A0"], pl["pose"])
    return {"A0": float(pl["A0"]), "e": float(pl["e"]), "alpha": float(pl["alpha"]), "overhang_mm2": CR.neck_overhang(st, fm, pl["A0"], pl["pose"]),
            "footprint": np.asarray(foot.exterior.coords).round(3).tolist(), "volume_mm3": float(pl["volume"])}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    ph = N.Phase(9, None, "abs")
    fm0 = FR.build()
    rng = np.random.default_rng(7)
    cand = []
    for u in rng.random((600, len(ph.vars))):
        d, h = ph.design_of(u)
        fm = fm0.with_cut(h); st = G.Stem3D(**d)
        p0 = CR._ORIG["template"](st, fm)
        if not (p0["fit"] and p0["A0"] >= MIN_A0):
            continue
        p1 = CR.template_neck_in_shoulder(st, fm, min_A0=MIN_A0)
        cand.append((CR.neck_overhang(st, fm, p0["A0"], p0["pose"]), p0["A0"], bool(p1["fit"]), u, d, h))
    print("feasible under current rule:", len(cand), "| also feasible with neck in shoulder:", sum(c[2] for c in cand))
    cand.sort(key=lambda c: -c[0])
    small = [c for c in cand if c[1] < 200]
    def first(*conds):
        for cond in conds:
            hit = [c for c in cand if cond(c)]
            if hit:
                return hit[0]
        return None
    pick = {"A_small_no_fit": first(lambda c: c[1] < 200 and not c[2]),
            "B_short_no_fit": first(lambda c: c[4]["L"] < 30 and not c[2] and c[1] >= 200),
            "C_mid_fixed": first(lambda c: 200 <= c[1] < 300 and c[0] > 10 and c[2], lambda c: c[0] > 10 and c[2]),
            "D_long_fixed": first(lambda c: c[4]["L"] > 45 and c[0] > 5 and c[2], lambda c: c[4]["L"] > 45 and c[2]),
            "E_large_fixed": first(lambda c: c[1] >= 300 and 1 < c[0] < 10 and c[2]),
            "F_already_inside": first(lambda c: c[0] <= 1.0)}
    pick = {k: v for k, v in pick.items() if v is not None}
    print("A0 range of designs feasible with neck in shoulder:", round(min(c[1] for c in cand if c[2])), "-", round(max(c[1] for c in cand if c[2])))
    rep = {}
    for name, (ov, A0, ok, u, d, h) in pick.items():
        fm = fm0.with_cut(h); st = G.Stem3D(**d)
        C, e1, e2 = E._plane_basis(fm)
        uu, lab, below = fm.labels_on_plane(C, e1, e2, half=28.0, h=0.2)
        np.savez_compressed(OUT / f"{name}_bone.npz", u=uu, lab=lab)
        r = {"design": {k: round(float(v), 3) for k, v in d.items()}, "h_cut": h, "plane": {"C": C.tolist(), "e1": e1.tolist(), "e2": e2.tolist(), "u3": fm.u3.tolist()},
             "neck_r": float(fm.cfg["prosthesis"]["neck_radius_mm"])}
        p0 = CR._ORIG["template"](st, fm)
        r["current"] = describe(st, fm, p0)
        stl_of(st, fm, p0, OUT / f"{name}_current.stl")
        p1 = CR.template_neck_in_shoulder(st, fm, min_A0=MIN_A0)
        if p1["fit"]:
            r["neck_in_shoulder"] = describe(st, fm, p1)
            stl_of(st, fm, p1, OUT / f"{name}_neck_in_shoulder.stl")
        else:
            r["neck_in_shoulder"] = {"fit": False, "reason": p1["reason"][:300]}
        rep[name] = r
        print(name, "current A0 %.0f e %+.0f overhang %.1f" % (r["current"]["A0"], r["current"]["e"], r["current"]["overhang_mm2"]), "| new:",
              ("A0 %.0f e %+.0f overhang %.1f" % (r["neck_in_shoulder"]["A0"], r["neck_in_shoulder"]["e"], r["neck_in_shoulder"]["overhang_mm2"])) if p1["fit"] else "infeasible")
    (OUT / "preview.json").write_text(json.dumps(rep, indent=1))
