"""v2 的 3D CAD 几何（gmsh OCC）：与 geom3d 的解析模型用同一张站位表/同一截面函数构造。

* 股骨外形与髓腔：沿干—颈中心线的站位截面（两段半椭圆拼成的闭合 B 样条）做光滑放样，再并大转子椭球与股骨头球。
* 柄：沿直中轴的截面（unit_section × √(A0·r(s))）做直纹放样（直纹保证相邻截面之间仍嵌套），肩部以上等截面延伸，
  尖端按半椭球轮廓收拢到很小的截面；再与截骨面以下半空间求交。
smoke()：建一例并划分网格，报告体积一致性（柄 ∩ 皮质 应接近 0，对应模板化的穿透容差）、单元数与耗时。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402

S_TOP_FE = -30.0     # mm，肩部以上等截面延伸（之后被截骨面裁掉）


def _wire(occ, pts3):
    tags = [occ.addPoint(*p) for p in pts3]
    sp = occ.addBSpline(tags + [tags[0]])
    return occ.addWire([sp])


def femur_station_points(fem: G.Femur3D, row, inner: bool, m: int = 36):
    sg = row[0]
    C, t, n = fem.frame2d(np.array([sg]))
    C, n = C[0], n[0]
    xc, a, ba, bp = (row[5], row[6], row[7], row[8]) if inner else (row[1], row[2], row[3], row[4])
    th = np.linspace(0, 2 * np.pi, m, endpoint=False)
    xi = xc + a * np.cos(th)
    eta = np.where(np.sin(th) >= 0, ba, bp) * np.sin(th)
    return np.c_[C[0] + xi * n[0], eta, C[1] + xi * n[1]]


def femur_solids(occ, fem: G.Femur3D, stride: int = 3):
    rows = fem.T[::stride]
    if rows[-1, 0] != fem.T[-1, 0]:
        rows = np.vstack([rows, fem.T[-1]])
    ow = [_wire(occ, femur_station_points(fem, r, False)) for r in rows]
    iw = [_wire(occ, femur_station_points(fem, r, True)) for r in rows]
    outer = occ.addThruSections(ow, makeSolid=True, makeRuled=False)
    inner = occ.addThruSections(iw, makeSolid=True, makeRuled=False)

    def ellipsoid(c, ax, shrink=0.0):
        s = occ.addSphere(c[0], c[1], c[2], ax[0] - shrink)
        occ.dilate([(3, s)], c[0], c[1], c[2], 1.0, (ax[1] - shrink) / (ax[0] - shrink), (ax[2] - shrink) / (ax[0] - shrink))
        return s
    Hx, Hz = fem.H
    O, _ = occ.fuse(outer, [(3, ellipsoid(fem.gt_c, fem.gt_ax)), (3, occ.addSphere(Hx, 0.0, Hz, fem.Rh))])
    I, _ = occ.fuse(inner, [(3, ellipsoid(fem.gt_c, fem.gt_ax, 2.0)), (3, occ.addSphere(Hx, 0.0, Hz, fem.Rh - 2.0))])
    I2, _ = occ.intersect(I, O, removeObject=True, removeTool=False)
    return O, I2


def kept_halfspace(occ, fem: G.Femur3D, size: float = 400.0):
    """截骨面以下的半空间（大盒子）。"""
    u, n = fem.u3, fem.n3
    e2 = np.array([0.0, 1.0, 0.0])
    c = fem.C03
    corners = [c + sa * size * n + sb * size * e2 for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    p = [occ.addPoint(*q) for q in corners]
    ln = [occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)]
    sf = occ.addPlaneSurface([occ.addCurveLoop(ln)])
    ex = occ.extrude([(2, sf)], *(-size * u))
    return [e for e in ex if e[0] == 3]


def stem_solid(occ, st: G.Stem3D, A0: float, pose, delta: float = 0.0, n_body: int = 24, m: int = 40):
    P0, d, e_ml, e_ap = pose
    sec = G.unit_section(st.d, m)
    s_body = st.L * (1 - np.cos(np.linspace(0, np.pi / 2, n_body)))        # 近端疏、远端密一些
    s_body = np.unique(np.r_[s_body, np.linspace(0, st.L, n_body)])[::2]
    s_body = np.unique(np.r_[0.0, s_body, st.L])
    k_body = np.sqrt(A0 * st.area_ratio(s_body))
    c = st.cap_length(A0)
    tc = np.linspace(0, 1, 6)[1:]
    s_cap = st.L + c * tc
    k_cap = math.sqrt(A0 * st.rho_tip) * np.sqrt(np.clip(1 - tc ** 2, 0.03 ** 2, 1))
    s_all = np.r_[S_TOP_FE, s_body, s_cap]
    k_all = np.r_[k_body[0], k_body, k_cap]
    wires = []
    for s_, k_ in zip(s_all, k_all):
        kk = max(k_ - delta, 0.2)
        pts = P0 + s_ * d + (kk * sec[:, :1]) * e_ml + (kk * sec[:, 1:2]) * e_ap
        wires.append(_wire(occ, pts))
    body = occ.addThruSections(wires, makeSolid=True, makeRuled=True)
    return body


def smoke(dorr="B", design=None, h_int=2.0, h_far=6.0, out=HERE / "out" / "fe3d_smoke", stride=3, algo2d=6,
          netgen=1, tag=""):
    import gmsh
    out.mkdir(parents=True, exist_ok=True)
    fem = G.Femur3D(dorr)
    st = G.Stem3D(**(design or G.from_unit(np.full(len(G.VARS), 0.5))))
    pl = G.template(st, fem)
    rec = {"dorr": dorr, "design": st.d, "template": {k: pl[k] for k in ("alpha", "e", "A0", "contact", "s_bind")}}
    t0 = time.time()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        occ = gmsh.model.occ
        O, I = femur_solids(occ, fem, stride=stride)
        K = kept_halfspace(occ, fem)
        Ok, _ = occ.intersect(O, K, removeObject=True, removeTool=False)
        Ik, _ = occ.intersect(I, K, removeObject=True, removeTool=False)
        body = stem_solid(occ, st, pl["A0"], pl["pose"])
        stem_in, _ = occ.intersect(body, K, removeObject=False, removeTool=False)
        occ.synchronize()
        vol = lambda dt: sum(occ.getMass(d, t) for d, t in dt)                     # noqa: E731
        v_stem = vol(stem_in)
        cort, _ = occ.cut(Ok, Ik, removeObject=False, removeTool=False)
        ov, _ = occ.intersect(stem_in, cort, removeObject=False, removeTool=False)
        occ.synchronize()
        v_ov = vol(ov) if ov else 0.0
        rec["cad"] = {"stem_volume_in_bone_mm3": v_stem, "stem_cortex_overlap_mm3": v_ov,
                      "overlap_fraction": v_ov / max(v_stem, 1e-9), "t_geometry_s": time.time() - t0}
        occ.remove(ov, recursive=True)
        occ.remove(cort, recursive=True)
        # 骨 = 保留外形 − 柄腔；松质 = 保留髓腔 − 柄腔（柄腔 = 柄内缩 δ）
        cav = stem_solid(occ, st, pl["A0"], pl["pose"], delta=0.1)
        bone, _ = occ.cut(Ok, cav, removeObject=True, removeTool=False)
        canc, _ = occ.cut(Ik, cav, removeObject=True, removeTool=True)
        frag, fmap = occ.fragment(bone, canc)
        occ.synchronize()
        canc_vols = sorted({t for dt in fmap[len(bone):] for d, t in dt if d == 3})
        cort_vols = sorted({t for d, t in frag if d == 3} - set(canc_vols))
        stem_vols = [t for _, t in stem_in]
        occ.remove(body, recursive=True)
        occ.synchronize()
        gmsh.model.addPhysicalGroup(3, cort_vols, name="cortex")
        gmsh.model.addPhysicalGroup(3, canc_vols, name="cancellous")
        gmsh.model.addPhysicalGroup(3, stem_vols, name="stem")
        surfs = [t for d, t in gmsh.model.getBoundary([(3, v) for v in stem_vols], oriented=False) if d == 2]
        fd = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", surfs)
        ft = gmsh.model.mesh.field.add("Threshold")
        for k, v in (("InField", fd), ("SizeMin", h_int), ("SizeMax", h_far), ("DistMin", 0.5), ("DistMax", 15.0)):
            gmsh.model.mesh.field.setNumber(ft, k, v)
        gmsh.model.mesh.field.setAsBackgroundMesh(ft)
        for k, v in (("Mesh.MeshSizeFromPoints", 0), ("Mesh.MeshSizeFromCurvature", 0), ("Mesh.MeshSizeExtendFromBoundary", 0),
                     ("Mesh.Algorithm3D", 1), ("Mesh.Optimize", 1), ("Mesh.OptimizeNetgen", netgen), ("Mesh.ElementOrder", 2),
                     ("Mesh.SecondOrderLinear", 1), ("Mesh.Algorithm", algo2d)):
            gmsh.option.setNumber(k, v)
        t1 = time.time()
        gmsh.model.mesh.generate(2)
        t_2d = time.time() - t1
        gmsh.model.mesh.generate(3)
        n_tet = {}
        for name, vols in (("cortex", cort_vols), ("cancellous", canc_vols), ("stem", stem_vols)):
            n = 0
            for v in vols:
                ty, _, en = gmsh.model.mesh.getElements(3, v)
                n += sum(len(e) // 10 for tt, e in zip(ty, en) if tt == 11)
            n_tet[name] = n
        rec["mesh"] = {"h_int": h_int, "n_tet": n_tet, "t_mesh_s": time.time() - t1, "t_surface_s": t_2d,
                       "stride": stride, "algo2d": algo2d, "netgen": netgen,
                       "n_volumes": {"cortex": len(cort_vols), "cancellous": len(canc_vols), "stem": len(stem_vols)}}
        gmsh.write(str(out / f"smoke_{dorr}{tag}.msh"))
    finally:
        gmsh.finalize()
    rec["t_total_s"] = time.time() - t0
    (out / f"smoke_{dorr}{tag}.json").write_text(json.dumps(rec, indent=1, default=float), encoding="utf-8")
    return rec


if __name__ == "__main__":
    for t in sys.argv[1:] or ["B"]:
        print(json.dumps(smoke(t), indent=1, default=float))
