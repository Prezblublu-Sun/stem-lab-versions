"""S7 理想化 3D 抽检模型：由 2D 轮廓放样出的股骨 + 沿同一圆弧放样的超椭圆截面柄，C3D10。

几何（gmsh OCC）
* 股骨外形：z ∈ [−150, +30] 每 5 mm 一个椭圆截面，冠状面半轴 = 2D 外轮廓在该高度的半弦长，矢状面半轴 = 深度比 × 冠状半轴
  （干部 1.0，向近端线性减到 0.72）；再并上沿颈轴的椭圆柱（冠状 17.5、矢状 14 mm）、头部球（23 mm）与大转子椭球。
* 髓腔：同高度取 2D 内轮廓半弦长，矢状面半轴 = 外矢状半轴 − 冠状面平均壁厚；颈、头、大转子内缩 2 mm。
* 柄体：沿 2D 同一圆弧（stem2d.Stem2D）在 s ∈ [s_min, L] 取截面，截面为 4 次超椭圆，冠状半宽 w(s)、矢状半厚
  h(s) = 6 mm × w(s)/w_p（下限 2 mm），尖端并一个椭球帽；假体颈（半径 7 mm 圆柱）与头（14 mm 球）只在截骨面以上。
* 锉刀腔 = 柄体截面各内缩 δ；骨 = 外形 − 截骨面以上 − 锉刀腔；皮质 = 骨 − 髓腔，松质 = 骨 ∩ 髓腔（共形）。
接触面：骨边界三角形中心落在柄体实体内（锉刀腔面比柄体小 δ）者为从面；柄体边界在截骨面以下 3 mm 内为主面。
无侧板（3D 自带环向刚度）。其余材料、载荷、三步压配与 2D 相同，Fy 取 0 以与 2D 可比。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import femur2d as F  # noqa: E402
import stem2d as S  # noqa: E402
from inp_writer import CONTACT_OUTPUT, FIELD_OUTPUT, Inp, _f  # noqa: E402

CFG = F.CFG
FACES = {1: (0, 1, 2), 2: (0, 3, 1), 3: (1, 3, 2), 4: (2, 3, 0)}   # C3D10 面 → 角节点（0 基）
GMSH2ABQ = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]                            # gmsh tet10 → Abaqus C3D10 节点顺序
# 直边二阶（中点节点不贴曲面，避免负雅可比）；Delaunay + Netgen 优化减少细长四面体
MESH_OPTS = (("Mesh.MeshSizeFromPoints", 0), ("Mesh.MeshSizeFromCurvature", 0), ("Mesh.MeshSizeExtendFromBoundary", 0),
             ("Mesh.Algorithm3D", 1), ("Mesh.Optimize", 1), ("Mesh.OptimizeNetgen", 1),
             ("Mesh.ElementOrder", 2), ("Mesh.SecondOrderLinear", 1))


def check_volumes(elems: dict, coords: dict, rel_tol: float = 1e-4) -> dict:
    """角节点四面体体积：返回最小体积与相对（除以中位体积）过小的单元数；过小者会被 Abaqus 拒绝。"""
    out = {}
    for k, c in elems.items():
        P = np.array([[coords[int(n)] for n in row[:4]] for row in c])
        v = np.abs(np.einsum("ij,ij->i", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0])) / 6
        out[k] = {"min_vol": float(v.min()), "n_tiny": int((v < rel_tol * np.median(v)).sum())}
    return out


def depth_ratio(z):
    return float(np.interp(z, [-40.0, 30.0], [1.0, 0.72]))


def _ellipse_wire(occ, xc, z, a, b):
    """z 平面上的椭圆，冠状（x）半轴 a、矢状（y）半轴 b。"""
    if a >= b:
        e = occ.addEllipse(xc, 0.0, z, a, b)
    else:
        e = occ.addEllipse(xc, 0.0, z, b, a)
        occ.rotate([(1, e)], xc, 0.0, z, 0, 0, 1, math.pi / 2)
    return occ.addWire([e])


def _superellipse_wire(occ, center, e1, e2, a, b, m=4.0, n=28):
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    u = np.sign(c) * np.abs(c) ** (2 / m) * a
    v = np.sign(s) * np.abs(s) ** (2 / m) * b
    pts = [occ.addPoint(*(center + ui * e1 + vi * e2)) for ui, vi in zip(u, v)]
    sp = occ.addBSpline(pts + [pts[0]])
    return occ.addWire([sp])


def femur_solids(occ, f: F.Femur2D):
    zs = np.arange(-150.0, 40.01, 5.0)
    ow, iw = [], []
    for z in zs:
        a0, a1 = F.chord(f.outer, z)
        i0, i1 = F.chord(f.inner, z)
        a, xc = (a1 - a0) / 2, (a1 + a0) / 2
        ai, xci = (i1 - i0) / 2, (i1 + i0) / 2
        b = depth_ratio(z) * a
        bi = max(2.0, b - (a - ai))
        ow.append(_ellipse_wire(occ, xc, z, a, b))
        iw.append(_ellipse_wire(occ, xci, z, ai, bi))
    outer = occ.addThruSections(ow, makeSolid=True, makeRuled=False)
    inner = occ.addThruSections(iw, makeSolid=True, makeRuled=False)
    u, P0 = F.neck_axis()
    H = np.array(CFG["femur"]["head_center"], float)
    q0 = P0 + 8.0 * u
    L_neck = float(np.linalg.norm(H - q0))

    def neck(r, depth):
        c = occ.addCylinder(q0[0], 0.0, q0[1], L_neck * u[0], 0.0, L_neck * u[1], r)
        occ.dilate([(3, c)], q0[0], 0.0, q0[1], 1.0, depth / r, 1.0)
        return c
    Rh = CFG["femur"]["head_radius"]
    gt_c, gt_ax = (-18.0, 0.0, 52.0), (13.0, 14.0, 17.0)

    def ellipsoid(c, ax, shrink=0.0):
        sph = occ.addSphere(c[0], c[1], c[2], ax[0] - shrink)
        occ.dilate([(3, sph)], c[0], c[1], c[2], 1.0, (ax[1] - shrink) / (ax[0] - shrink), (ax[2] - shrink) / (ax[0] - shrink))
        return sph
    out_parts = outer + [(3, neck(17.5, 14.0)), (3, occ.addSphere(H[0], 0.0, H[1], Rh)), (3, ellipsoid(gt_c, gt_ax))]
    in_parts = inner + [(3, neck(15.5, 12.0)), (3, occ.addSphere(H[0], 0.0, H[1], Rh - 2.0)), (3, ellipsoid(gt_c, gt_ax, 2.0))]
    O, _ = occ.fuse(out_parts[:1], out_parts[1:])
    I, _ = occ.fuse(in_parts[:1], in_parts[1:])
    I2, _ = occ.intersect(I, O, removeObject=True, removeTool=False)
    return O, I2


def removed_halfspace(occ, f: F.Femur2D):
    C0, u = f.cut
    n = np.array([-u[1], u[0]])
    pts2 = [C0 - 200 * n, C0 + 200 * n, C0 + 200 * n + 300 * u, C0 - 200 * n + 300 * u]
    p = [occ.addPoint(x, -150.0, z) for x, z in pts2]
    ln = [occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)]
    cl = occ.addCurveLoop(ln)
    sf = occ.addPlaneSurface([cl])
    ex = occ.extrude([(2, sf)], 0, 300.0, 0)
    return [e for e in ex if e[0] == 3]


def stem_body(occ, st: S.Stem2D, delta: float = 0.0, n_sec: int = 26):
    s = np.linspace(st.s_min, st.L, n_sec)
    p, t, nrm = st.axis(s)
    w = st.halfwidth(s, delta)
    h = np.maximum(6.0 * st.halfwidth(s) / st.w_p, 2.0) - delta
    ey = np.array([0.0, 1.0, 0.0])
    wires = []
    for k in range(n_sec):
        c3 = np.array([p[k, 0], 0.0, p[k, 1]])
        e1 = np.array([nrm[k, 0], 0.0, nrm[k, 1]])
        wires.append(_superellipse_wire(occ, c3, e1, ey, w[k], h[k]))
    body = occ.addThruSections(wires, makeSolid=True, makeRuled=False)
    tipc = np.array([p[-1, 0], 0.0, p[-1, 1]])
    cap = occ.addSphere(*tipc, w[-1])
    occ.dilate([(3, cap)], *tipc, 1.0, h[-1] / w[-1], 1.0)
    B, _ = occ.fuse(body, [(3, cap)])
    return B


def stem_neck(occ, st: S.Stem2D):
    C0, u = st.femur.cut
    H = np.array(CFG["femur"]["head_center"], float)
    a = C0 - 2.0 * u
    L = float(np.linalg.norm(H - a))
    cyl = occ.addCylinder(a[0], 0.0, a[1], L * u[0], 0.0, L * u[1], CFG["stem"]["neck_halfwidth"])
    hd = occ.addSphere(H[0], 0.0, H[1], CFG["stem"]["head_radius"])
    return [(3, cyl), (3, hd)]


def build(st: S.Stem2D, outdir: pathlib.Path, name: str, *, h_int: float = 1.5, h_far: float = 5.0,
          delta: float | None = None, mu: float | None = None) -> dict:
    """先用默认设置建网格；失败（细长四面体、PLC 相交等）时依次改用 HXT 算法、界面尺寸 × 0.9 重试。"""
    attempts = [(1, h_int), (10, h_int), (1, 0.9 * h_int), (10, 0.9 * h_int)]
    errors = []
    for algo, h in attempts:
        try:
            info = _build(st, outdir, name, h_int=h, h_far=h_far, delta=delta, mu=mu, algo=algo)
            info["mesh_attempt"] = {"algorithm3d": algo, "h_int": h, "previous_errors": errors}
            (outdir / "model3d.json").write_text(json.dumps(info))
            return info
        except Exception as e:                                              # noqa: BLE001
            errors.append(f"algo {algo}, h {h:g}: {type(e).__name__}: {e}"[:200])
    raise RuntimeError("3D meshing failed after retries: " + " | ".join(errors))


def _build(st: S.Stem2D, outdir: pathlib.Path, name: str, *, h_int: float, h_far: float,
           delta: float | None, mu: float | None, algo: int) -> dict:
    import gmsh
    ic = CFG["interface"]
    delta = ic["delta"] if delta is None else delta
    mu = ic["mu"] if mu is None else mu
    f = st.femur
    outdir.mkdir(parents=True, exist_ok=True)
    C0, u = f.cut
    u3 = np.array([u[0], 0.0, u[1]]); C03 = np.array([C0[0], 0.0, C0[1]])
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(name)
        occ = gmsh.model.occ
        O, I = femur_solids(occ, f)
        R = removed_halfspace(occ, f)
        Ok, _ = occ.cut(O, R, removeObject=True, removeTool=False)
        Ik, _ = occ.cut(I, R, removeObject=True, removeTool=True)
        cav = stem_body(occ, st, delta)
        bone, _ = occ.cut(Ok, cav, removeObject=True, removeTool=False)
        canc, _ = occ.cut(Ik, cav, removeObject=True, removeTool=True)
        frag, fmap = occ.fragment(bone, canc)
        canc_vols = sorted({t for dt in fmap[len(bone):] for d, t in dt if d == 3})
        cort_vols = sorted({t for d, t in frag if d == 3} - set(canc_vols))
        body = stem_body(occ, st, 0.0)
        stem, _ = occ.fuse(body, stem_neck(occ, st))
        chk = stem_body(occ, st, 0.0)                                   # 只用于"点在柄体内"判定
        occ.synchronize()
        gmsh.model.addPhysicalGroup(3, cort_vols, name="cortex")
        gmsh.model.addPhysicalGroup(3, canc_vols, name="cancellous")
        gmsh.model.addPhysicalGroup(3, [t for _, t in stem], name="stem")
        stem_surfs = [t for d, t in gmsh.model.getBoundary(stem, oriented=False) if d == 2]
        fd = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", stem_surfs)
        ft = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(ft, "InField", fd)
        gmsh.model.mesh.field.setNumber(ft, "SizeMin", h_int)
        gmsh.model.mesh.field.setNumber(ft, "SizeMax", h_far)
        gmsh.model.mesh.field.setNumber(ft, "DistMin", 0.5)
        gmsh.model.mesh.field.setNumber(ft, "DistMax", 15.0)
        gmsh.model.mesh.field.setAsBackgroundMesh(ft)
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.Algorithm3D", algo)
        chk_tags = [t for d, t in chk]
        gmsh.model.mesh.generate(3)
        ntag, ncoord, _ = gmsh.model.mesh.getNodes()
        xyz = ncoord.reshape(-1, 3)
        lut = {int(t): i for i, t in enumerate(ntag)}
        elems = {}
        for name_, vols in (("cortex", cort_vols), ("cancellous", canc_vols), ("stem", [t for _, t in stem])):
            conn = []
            for v in vols:
                ty, _, en = gmsh.model.mesh.getElements(3, v)
                for tt, e in zip(ty, en):
                    if tt != 11:
                        raise RuntimeError(f"unexpected 3D element type {tt}")
                    conn.append(e.reshape(-1, 10)[:, GMSH2ABQ])
            elems[name_] = np.vstack(conn).astype(np.int64)

        def in_body(pt):
            return any(gmsh.model.isInside(3, t, list(map(float, pt))) for t in chk_tags)

        used_bone = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
        used_stem = np.unique(elems["stem"].ravel())
        if np.intersect1d(used_bone, used_stem).size:
            raise RuntimeError("bone and stem share nodes")
        coords = {int(t): xyz[lut[int(t)]] for t in np.r_[used_bone, used_stem]}
        for k in elems:                                                  # 正体积
            c = elems[k]
            P = np.array([[coords[int(n)] for n in row[:4]] for row in c])
            vol = np.einsum("ij,ij->i", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0])
            neg = vol < 0
            if neg.any():
                c[neg] = c[neg][:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]

        vq = check_volumes(elems, coords)
        if any(q["n_tiny"] for q in vq.values()):
            raise RuntimeError(f"3D mesh has near-zero-volume tetrahedra: {vq}")

        def boundary_faces(regions):
            cnt = {}
            for r in regions:
                for i, row in enumerate(elems[r]):
                    for fc, (a, b, c_) in FACES.items():
                        key = tuple(sorted((int(row[a]), int(row[b]), int(row[c_]))))
                        cnt.setdefault(key, []).append((r, i, fc))
            return [(k, v[0]) for k, v in cnt.items() if len(v) == 1]
        slave, master = [], []
        for key, (r, i, fc) in boundary_faces(["cortex", "cancellous"]):
            cen = np.mean([coords[k] for k in key], axis=0)
            if abs(float((cen - C03) @ u3)) < 0.05:
                continue
            if in_body(cen):
                slave.append((r, i, fc))
        for key, (r, i, fc) in boundary_faces(["stem"]):
            cen = np.mean([coords[k] for k in key], axis=0)
            if float((cen - C03) @ u3) <= 3.0:
                master.append((r, i, fc))
    finally:
        gmsh.finalize()
    # --- 写 .inp
    offs = {"cortex": 0, "cancellous": len(elems["cortex"]), "stem": len(elems["cortex"]) + len(elems["cancellous"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    H = np.array(CFG["femur"]["head_center"], float)
    H3 = np.array([H[0], 0.0, H[1]])
    stem_nodes = np.unique(elems["stem"].ravel())
    head = [int(n) for n in stem_nodes if np.linalg.norm(coords[int(n)] - H3) <= CFG["load"]["head_coupling_radius"] + 1e-6]
    bone_nodes = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
    fixed = [int(n) for n in bone_nodes if abs(coords[int(n)][2] - CFG["femur"]["distal_z"]) < 1e-4]
    L = CFG["load"]

    def common(kind):
        inp = Inp(f"mobo_toy S7 3D {name}_{kind} dorr={f.dorr} delta={delta} mu={mu}")
        allnodes = sorted(coords)
        inp.lines.append("*NODE")
        inp.lines += [f"{n}, {_f(coords[n][0])}, {_f(coords[n][1])}, {_f(coords[n][2])}" for n in allnodes]
        for k, es in (("cortex", "CORTEX"), ("cancellous", "CANC"), ("stem", "STEM")):
            inp.elements("C3D10", es, elab[k], elems[k])
        M = CFG["materials"]
        inp.material("CORTICAL", M["cortical"]["E"], M["cortical"]["nu"])
        inp.material("CANCELLOUS", f.E_cancellous, M["cancellous_nu"])
        inp.material("TI6AL4V", M["titanium"]["E"], M["titanium"]["nu"])
        inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",",
                      "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ",",
                      "*SOLID SECTION, ELSET=STEM, MATERIAL=TI6AL4V", ","]
        inp.element_surface("S_BONE", [(elab[r][i], fc) for r, i, fc in slave])
        inp.element_surface("S_STEM", [(elab[r][i], fc) for r, i, fc in master])
        inp.nset("HEADN", head)
        inp.nset("FIXED", fixed)
        return inp
    load = (f"*CLOAD\nHEADN, 1, {_f(L['Fx'] / len(head))}\nHEADN, 3, {_f(L['Fz'] / len(head))}")
    fric = common("fric")
    fric.raw(f"""
*SURFACE INTERACTION, NAME=FRIC
*FRICTION, SLIP TOLERANCE={_f(ic['slip_tolerance'])}
{_f(mu)},
*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD
*CONTACT PAIR, INTERACTION=FRIC, TYPE=SURFACE TO SURFACE, SMALL SLIDING
S_BONE, S_STEM
*STEP, NAME=PRESSFIT, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*CONTACT INTERFERENCE, SHRINK
S_BONE, S_STEM
*BOUNDARY
FIXED, 1, 3
HEADN, 1, 3
{FIELD_OUTPUT}
{CONTACT_OUTPUT}
*END STEP
*STEP, NAME=RELEASE, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*BOUNDARY, OP=NEW
FIXED, 1, 3
{FIELD_OUTPUT}
{CONTACT_OUTPUT}
*END STEP
*STEP, NAME=LOAD, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
{load}
{FIELD_OUTPUT}
{CONTACT_OUTPUT}
*END STEP""")
    fric.write(outdir / f"{name}_fric.inp")
    bond = common("bond")
    bond.raw(f"""
*TIE, NAME=BOND, ADJUST=NO, POSITION TOLERANCE={_f(ic['tie_position_tolerance'])}
S_BONE, S_STEM
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
FIXED, 1, 3
{load}
{FIELD_OUTPUT}
*END STEP""")
    bond.write(outdir / f"{name}_bond.inp")
    np.savez_compressed(outdir / "mesh3d.npz", **{f"{k}_conn": v for k, v in elems.items()},
                        **{f"{k}_elab": v for k, v in elab.items()},
                        node_labels=np.array(sorted(coords)), nodes=np.array([coords[n] for n in sorted(coords)]))
    info = {"name": name, "dorr": f.dorr, "n_tet": {k: int(len(v)) for k, v in elems.items()},
            "n_nodes": len(coords), "n_slave_faces": len(slave), "n_master_faces": len(master), "n_head": len(head),
            "n_fixed": len(fixed), "slave": [[int(elab[r][i]), fc] for r, i, fc in slave], "h_int": h_int, "h_far": h_far}
    (outdir / "model3d.json").write_text(json.dumps(info))
    return info


def build_intact(f: F.Femur2D, outdir: pathlib.Path, name: str, *, h_roi: float = 2.0, h_far: float = 6.0) -> dict:
    """完整 3D 股骨（无截骨、无柄），头心 14 mm 球内节点均分载荷；作 3D 的 SED 参照。"""
    import gmsh
    outdir.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(name)
        occ = gmsh.model.occ
        O, I = femur_solids(occ, f)
        frag, fmap = occ.fragment(O, I)
        canc_vols = sorted({t for dt in fmap[len(O):] for d, t in dt if d == 3})
        cort_vols = sorted({t for d, t in frag if d == 3} - set(canc_vols))
        occ.synchronize()
        box = gmsh.model.mesh.field.add("Box")
        for k, v in (("VIn", h_roi), ("VOut", h_far), ("XMin", -40), ("XMax", 60), ("YMin", -40), ("YMax", 40),
                     ("ZMin", -20), ("ZMax", 90), ("Thickness", 10)):
            gmsh.model.mesh.field.setNumber(box, k, v)
        gmsh.model.mesh.field.setAsBackgroundMesh(box)
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.model.mesh.generate(3)
        ntag, ncoord, _ = gmsh.model.mesh.getNodes()
        xyz = ncoord.reshape(-1, 3)
        lut = {int(t): i for i, t in enumerate(ntag)}
        elems = {}
        for name_, vols in (("cortex", cort_vols), ("cancellous", canc_vols)):
            conn = []
            for v in vols:
                ty, _, en = gmsh.model.mesh.getElements(3, v)
                conn += [e.reshape(-1, 10)[:, GMSH2ABQ] for tt, e in zip(ty, en) if tt == 11]
            elems[name_] = np.vstack(conn).astype(np.int64)
    finally:
        gmsh.finalize()
    used = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
    coords = {int(t): xyz[lut[int(t)]] for t in used}
    for k in elems:
        c = elems[k]
        P = np.array([[coords[int(n)] for n in row[:4]] for row in c])
        vol = np.einsum("ij,ij->i", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0])
        neg = vol < 0
        if neg.any():
            c[neg] = c[neg][:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]
    vq = check_volumes(elems, coords)
    if any(q["n_tiny"] for q in vq.values()):
        raise RuntimeError(f"3D intact mesh has near-zero-volume tetrahedra: {vq}")
    offs = {"cortex": 0, "cancellous": len(elems["cortex"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    H = np.array(CFG["femur"]["head_center"], float); H3 = np.array([H[0], 0.0, H[1]])
    head = [n for n in coords if np.linalg.norm(coords[n] - H3) <= CFG["load"]["head_coupling_radius"] + 1e-6]
    fixed = [n for n in coords if abs(coords[n][2] - CFG["femur"]["distal_z"]) < 1e-4]
    L = CFG["load"]
    inp = Inp(f"mobo_toy S7 3D intact {name} dorr={f.dorr}")
    inp.lines.append("*NODE")
    inp.lines += [f"{n}, {_f(coords[n][0])}, {_f(coords[n][1])}, {_f(coords[n][2])}" for n in sorted(coords)]
    inp.elements("C3D10", "CORTEX", elab["cortex"], elems["cortex"])
    inp.elements("C3D10", "CANC", elab["cancellous"], elems["cancellous"])
    M = CFG["materials"]
    inp.material("CORTICAL", M["cortical"]["E"], M["cortical"]["nu"])
    inp.material("CANCELLOUS", f.E_cancellous, M["cancellous_nu"])
    inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",", "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ","]
    inp.nset("HEADN", head); inp.nset("FIXED", fixed)
    inp.raw(f"""
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
FIXED, 1, 3
*CLOAD
HEADN, 1, {_f(L['Fx'] / len(head))}
HEADN, 3, {_f(L['Fz'] / len(head))}
{FIELD_OUTPUT}
*END STEP""")
    inp.write(outdir / f"{name}.inp")
    np.savez_compressed(outdir / "mesh3d.npz", **{f"{k}_conn": v for k, v in elems.items()},
                        **{f"{k}_elab": v for k, v in elab.items()},
                        node_labels=np.array(sorted(coords)), nodes=np.array([coords[n] for n in sorted(coords)]))
    info = {"name": name, "dorr": f.dorr, "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_head": len(head)}
    (outdir / "model3d.json").write_text(json.dumps(info))
    return info
