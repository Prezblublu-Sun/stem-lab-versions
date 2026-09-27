"""V2A 的 3D FE 建模器（在 Linux 上跑）：真实股骨 STEP × 直轴短柄 → C3D10 网格 → 两个 .inp（摩擦 / 粘接）。

几何（gmsh OCC，全部在模型坐标下；STEP 先刚体变换进来）
* 保留域 = {z ≥ z_trunc} ∩ 截骨面以下半空间；皮质 = 皮质 STEP ∩ 保留域，松质 = 松质 STEP ∩ 保留域。
* 锉腔 = 柄体（含肩部以上棱柱与尖端帽）各截面内缩 δ 的直纹放样；骨 = 皮质 − 锉腔，松质 = 松质 − 锉腔，碎片化得共形界面。
* 柄 = 柄体 ∩ 截骨面以下 + 假体颈（沿颈轴，从截骨面下 3 mm 到头心，半径 7）+ 假体头（半径 14）。柄必须是单一连通体
  （入口偏移过大时颈根落在肩面外，判 L1）。
* 从面：骨边界面中面心在柄体内的（锉腔面比柄小 δ），用 geom3d.inside_stem 在柄局部坐标里判定；主面：柄边界面中
  截骨面以下 3 mm 以内的。
* 摩擦模型三步：PRESSFIT（*CONTACT INTERFERENCE, SHRINK，头固定）→ RELEASE → LOAD；粘接模型：*TIE，单步 LOAD。
  与 spot3d/model3d 相同，只是几何、材料与载荷（三分量）换成 V2A 的。
* 完整股骨参照（build_intact）：两件 STEP 截到 z ≥ z_trunc，不截骨；头心 14 mm 球内节点分载。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import fe3d_geom as E  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
from inp_writer import CONTACT_OUTPUT, FIELD_OUTPUT, Inp, _f  # noqa: E402
from spot3d.model3d import FACES, GMSH2ABQ, check_volumes  # noqa: E402

MESH_OPTS = (("Mesh.MeshSizeFromPoints", 0), ("Mesh.MeshSizeFromCurvature", 0), ("Mesh.MeshSizeExtendFromBoundary", 0),
             ("Mesh.Algorithm", 6), ("Mesh.Optimize", 1), ("Mesh.OptimizeNetgen", 0),
             ("Mesh.ElementOrder", 2), ("Mesh.SecondOrderLinear", 1))


class BuildError(RuntimeError):
    """建模失败：level = L1（几何不成立）/ L3（网格或布尔失败）。"""

    def __init__(self, level: str, msg: str):
        super().__init__(f"{level}: {msg}")
        self.level = level


def load_vector(cfg: dict) -> np.ndarray:
    """模型坐标（+x 内侧、+y 后方、+z 向上）下作用在头上的力。见 config_v2a.yaml 的 load 节。"""
    L = cfg["load"]
    tx, ty = math.tan(math.radians(L["alpha_front_deg"])), math.tan(math.radians(L["alpha_sagit_deg"]))
    fz = L["resultant_N"] / math.sqrt(1 + tx * tx + ty * ty)
    fx_B, fy_B, fz_B = tx * fz, -ty * fz, -fz                     # Bergmann：+x 外侧、+y 前方
    return np.array([-fx_B, -fy_B, fz_B])                         # 模型：+x 内侧、+y 后方


def _femur_shapes(occ, fm: FR.RealFemur):
    fc = fm.cfg["femur"]
    Rm, org = fm.lm["Rm"], fm.lm["origin"]
    M = np.eye(4); M[:3, :3] = Rm; M[:3, 3] = -Rm @ org
    C = [x for x in occ.importShapes(str(FR.DATA / fc["step_cortical"])) if x[0] == 3]
    K = [x for x in occ.importShapes(str(FR.DATA / fc["step_cancellous"])) if x[0] == 3]
    occ.affineTransform(C + K, list(M[:3].ravel()))
    return C, K


def _keep(occ, fm: FR.RealFemur, cut: bool = True):
    z0 = fm.z_trunc
    b = [(3, occ.addBox(-300, -300, z0, 600, 600, 600))]
    if not cut:
        return b
    K, _ = occ.intersect(b, E.kept_halfspace(occ, fm))
    return K


def _extract(gmsh, groups: dict) -> tuple[dict, dict]:
    ntag, ncoord, _ = gmsh.model.mesh.getNodes()
    xyz = ncoord.reshape(-1, 3)
    lut = {int(t): i for i, t in enumerate(ntag)}
    elems = {}
    for name, vols in groups.items():
        conn = []
        for v in vols:
            ty, _, en = gmsh.model.mesh.getElements(3, v)
            for tt, e in zip(ty, en):
                if tt != 11:
                    raise BuildError("L3", f"unexpected 3D element type {tt} in {name}")
                conn.append(e.reshape(-1, 10)[:, GMSH2ABQ])
        if not conn:
            raise BuildError("L3", f"region {name} has no elements")
        elems[name] = np.vstack(conn).astype(np.int64)
    used = np.unique(np.concatenate([e.ravel() for e in elems.values()]))
    coords = {int(t): xyz[lut[int(t)]] for t in used}
    for k in elems:                                                   # 正体积
        c = elems[k]
        P = np.array([[coords[int(n)] for n in row[:4]] for row in c])
        vol = np.einsum("ij,ij->i", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0])
        neg = vol < 0
        if neg.any():
            c[neg] = c[neg][:, [0, 2, 1, 3, 6, 5, 4, 7, 9, 8]]
    vq = check_volumes(elems, coords)
    if any(q["n_tiny"] for q in vq.values()):
        raise BuildError("L3", f"near-zero-volume tetrahedra: {vq}")
    return elems, coords


def _boundary_faces(elems, regions):
    cnt = {}
    for r in regions:
        for i, row in enumerate(elems[r]):
            for fc, (a, b, c_) in FACES.items():
                key = tuple(sorted((int(row[a]), int(row[b]), int(row[c_]))))
                cnt.setdefault(key, []).append((r, i, fc))
    return [(k, v[0]) for k, v in cnt.items() if len(v) == 1]


def _size_field(gmsh, surfs, cfg, h_int, h_far):
    m = cfg["mesh"]
    fd = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(fd, "SurfacesList", surfs)
    ft = gmsh.model.mesh.field.add("Threshold")
    for k, v in (("InField", fd), ("SizeMin", h_int), ("SizeMax", h_far), ("DistMin", m["dist_min_mm"]),
                 ("DistMax", m["dist_max_mm"])):
        gmsh.model.mesh.field.setNumber(ft, k, v)
    gmsh.model.mesh.field.setAsBackgroundMesh(ft)


def build(st: G.Stem3D, fm: FR.RealFemur, pl: dict, outdir: pathlib.Path, name: str, *,
          h_int: float | None = None, h_far: float | None = None, delta: float | None = None,
          mu: float | None = None, torque: bool = True) -> dict:
    """建一个设计的两个 .inp；失败抛 BuildError。重试：Delaunay → HXT → 0.9·h（与 v1 相同）。"""
    cfg = fm.cfg
    h_int = cfg["mesh"]["h_int_mm"] if h_int is None else h_int
    h_far = cfg["mesh"]["h_far_mm"] if h_far is None else h_far
    errors = []
    for algo, h in ((1, h_int), (10, h_int), (1, 0.9 * h_int), (10, 0.9 * h_int)):
        try:
            info = _build(st, fm, pl, outdir, name, h_int=h, h_far=h_far, delta=delta, mu=mu, torque=torque, algo=algo)
            info["mesh_attempt"] = {"algorithm3d": algo, "h_int": h, "previous_errors": errors}
            (outdir / "model3d.json").write_text(json.dumps(info))
            return info
        except BuildError as e:
            if e.level == "L1":
                raise
            errors.append(f"algo {algo}, h {h:g}: {e}"[:300])
        except Exception as e:                                            # noqa: BLE001  gmsh/OCC 的异常类型不统一
            errors.append(f"algo {algo}, h {h:g}: {type(e).__name__}: {e}"[:300])
    raise BuildError("L3", "meshing failed after retries: " + " | ".join(errors))


def _build(st, fm, pl, outdir, name, *, h_int, h_far, delta, mu, torque, algo) -> dict:
    import gmsh
    cfg = fm.cfg
    ic = cfg["interface"]
    delta = ic["delta_mm"] if delta is None else delta
    mu = ic["mu"] if mu is None else mu
    pr = cfg["prosthesis"]
    outdir.mkdir(parents=True, exist_ok=True)
    A0, pose = pl["A0"], pl["pose"]
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add(name)
        occ = gmsh.model.occ
        C, K = _femur_shapes(occ, fm)
        Ck, _ = occ.intersect(C, _keep(occ, fm))
        Kk, _ = occ.intersect(K, _keep(occ, fm))
        cav = E.stem_solid(occ, st, A0, pose, delta=delta)
        bone, _ = occ.cut(Ck, cav, removeObject=True, removeTool=False)
        canc, _ = occ.cut(Kk, cav, removeObject=True, removeTool=True)
        frag, fmap = occ.fragment(bone, canc)
        canc_vols = sorted({t for dt in fmap[len(bone):] for d, t in dt if d == 3})
        cort_vols = sorted({t for d, t in frag if d == 3} - set(canc_vols))
        if not cort_vols or not canc_vols:
            raise BuildError("L3", f"fragment produced cortex {len(cort_vols)} / cancellous {len(canc_vols)} volumes")
        body = E.stem_solid(occ, st, A0, pose, delta=0.0)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        u3 = fm.u3
        a = fm.C03 - 3.0 * u3
        Lneck = float(np.linalg.norm(fm.H - a))
        neck = occ.addCylinder(*a, *(Lneck * u3), pr["neck_radius_mm"])
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        stem, _ = occ.fuse(body_in, [(3, neck), (3, head)])
        occ.synchronize()
        stem_vols = [t for d, t in stem if d == 3]
        if len(stem_vols) != 1:
            raise BuildError("L1", f"stem is {len(stem_vols)} disconnected volumes (neck base outside the shoulder?)")
        v_stem = occ.getMass(3, stem_vols[0])
        gmsh.model.addPhysicalGroup(3, cort_vols, name="cortex")
        gmsh.model.addPhysicalGroup(3, canc_vols, name="cancellous")
        gmsh.model.addPhysicalGroup(3, stem_vols, name="stem")
        surfs = [t for d, t in gmsh.model.getBoundary(stem, oriented=False) if d == 2]
        _size_field(gmsh, surfs, cfg, h_int, h_far)
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.Algorithm3D", algo)
        gmsh.model.mesh.generate(3)
        elems, coords = _extract(gmsh, {"cortex": cort_vols, "cancellous": canc_vols, "stem": stem_vols})
    finally:
        gmsh.finalize()
    used_bone = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
    used_stem = np.unique(elems["stem"].ravel())
    if np.intersect1d(used_bone, used_stem).size:
        raise BuildError("L3", "bone and stem share nodes")
    # 从面 / 主面
    P0, d, e_ml, e_ap = pose

    def local(P):
        Q = np.atleast_2d(P) - P0
        return np.c_[Q @ d, Q @ e_ml, Q @ e_ap]
    slave, master = [], []
    cands = _boundary_faces(elems, ["cortex", "cancellous"])
    cen = np.array([np.mean([coords[k] for k in key], axis=0) for key, _ in cands])
    on_cut = np.abs((cen - fm.C03) @ u3) < 0.05
    on_trunc = np.abs(cen[:, 2] - fm.z_trunc) < 0.05
    ins = G.inside_stem(st, A0, local(cen), tol=0.05)
    for (key, rif), m in zip(cands, ins & ~on_cut & ~on_trunc):
        if m:
            slave.append(rif)
    for key, rif in _boundary_faces(elems, ["stem"]):
        c = np.mean([coords[k] for k in key], axis=0)
        if float((c - fm.C03) @ u3) <= 3.0:
            master.append(rif)
    if len(slave) < 50 or len(master) < 50:
        raise BuildError("L3", f"contact surfaces too small: slave {len(slave)}, master {len(master)}")
    # 写 .inp
    offs = {"cortex": 0, "cancellous": len(elems["cortex"]), "stem": len(elems["cortex"]) + len(elems["cancellous"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    Lc = cfg["load"]
    head = [int(n) for n in used_stem if np.linalg.norm(coords[int(n)] - fm.H) <= Lc["head_coupling_radius_mm"] + 1e-6]
    fixed = [int(n) for n in used_bone if abs(coords[int(n)][2] - fm.z_trunc) < 1e-4]
    if len(head) < 10 or len(fixed) < 10:
        raise BuildError("L3", f"load/BC node sets too small: head {len(head)}, fixed {len(fixed)}")
    F = load_vector(cfg)
    if not torque:
        F = F.copy(); F[1] = 0.0                                          # 符号检查：去掉前后向分量
    Mt = cfg["materials"]
    E_canc = cfg["femur"]["E_cancellous"]

    def common(kind):
        inp = Inp(f"mobo_toy V2A {name}_{kind} femur=real(STEP) delta={delta} mu={mu} torque={torque}")
        allnodes = sorted(coords)
        inp.lines.append("*NODE")
        inp.lines += [f"{n}, {_f(coords[n][0])}, {_f(coords[n][1])}, {_f(coords[n][2])}" for n in allnodes]
        for k, es in (("cortex", "CORTEX"), ("cancellous", "CANC"), ("stem", "STEM")):
            inp.elements("C3D10", es, elab[k], elems[k])
        inp.material("CORTICAL", Mt["cortical"]["E"], Mt["cortical"]["nu"])
        inp.material("CANCELLOUS", E_canc, Mt["cancellous_nu"])
        inp.material("TI6AL4V", Mt["titanium"]["E"], Mt["titanium"]["nu"])
        inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",",
                      "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ",",
                      "*SOLID SECTION, ELSET=STEM, MATERIAL=TI6AL4V", ","]
        inp.element_surface("S_BONE", [(elab[r][i], fc) for r, i, fc in slave])
        inp.element_surface("S_STEM", [(elab[r][i], fc) for r, i, fc in master])
        inp.nset("HEADN", head)
        inp.nset("FIXED", fixed)
        return inp
    load = (f"*CLOAD\nHEADN, 1, {_f(F[0] / len(head))}\nHEADN, 2, {_f(F[1] / len(head))}\n"
            f"HEADN, 3, {_f(F[2] / len(head))}")
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
*TIE, NAME=BOND, ADJUST=NO, POSITION TOLERANCE={_f(ic['tie_position_tolerance_mm'])}
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
    return {"name": name, "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_nodes": len(coords),
            "n_slave_faces": len(slave), "n_master_faces": len(master), "n_head": len(head), "n_fixed": len(fixed),
            "slave": [[int(elab[r][i]), fc] for r, i, fc in slave], "h_int": h_int, "h_far": h_far, "delta": delta,
            "mu": mu, "torque": torque, "load_N": F.tolist(), "stem_volume_mm3": v_stem, "A0": A0}


def build_intact(fm: FR.RealFemur, outdir: pathlib.Path, name: str, *, h_roi: float = 2.0, h_far: float = 6.0) -> dict:
    """完整股骨（不截骨、无柄），截到 z ≥ z_trunc；头心 14 mm 球内节点均分载荷。Gruen 区 SED 的参照。"""
    import gmsh
    cfg = fm.cfg
    outdir.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add(name)
        occ = gmsh.model.occ
        C, K = _femur_shapes(occ, fm)
        Ck, _ = occ.intersect(C, _keep(occ, fm, cut=False))
        Kk, _ = occ.intersect(K, _keep(occ, fm, cut=False))
        frag, fmap = occ.fragment(Ck, Kk)
        canc_vols = sorted({t for dt in fmap[len(Ck):] for d, t in dt if d == 3})
        cort_vols = sorted({t for d, t in frag if d == 3} - set(canc_vols))
        occ.synchronize()
        box = gmsh.model.mesh.field.add("Box")
        for k, v in (("VIn", h_roi), ("VOut", h_far), ("XMin", -45), ("XMax", 75), ("YMin", -45), ("YMax", 45),
                     ("ZMin", -20), ("ZMax", 110), ("Thickness", 10)):
            gmsh.model.mesh.field.setNumber(box, k, v)
        gmsh.model.mesh.field.setAsBackgroundMesh(box)
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        elems, coords = _extract(gmsh, {"cortex": cort_vols, "cancellous": canc_vols})
    finally:
        gmsh.finalize()
    offs = {"cortex": 0, "cancellous": len(elems["cortex"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    Lc = cfg["load"]
    head = [n for n in coords if np.linalg.norm(coords[n] - fm.H) <= Lc["head_coupling_radius_mm"] + 1e-6]
    fixed = [n for n in coords if abs(coords[n][2] - fm.z_trunc) < 1e-4]
    F = load_vector(cfg)
    Mt = cfg["materials"]
    inp = Inp(f"mobo_toy V2A intact {name}")
    inp.lines.append("*NODE")
    inp.lines += [f"{n}, {_f(coords[n][0])}, {_f(coords[n][1])}, {_f(coords[n][2])}" for n in sorted(coords)]
    inp.elements("C3D10", "CORTEX", elab["cortex"], elems["cortex"])
    inp.elements("C3D10", "CANC", elab["cancellous"], elems["cancellous"])
    inp.material("CORTICAL", Mt["cortical"]["E"], Mt["cortical"]["nu"])
    inp.material("CANCELLOUS", cfg["femur"]["E_cancellous"], Mt["cancellous_nu"])
    inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",", "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ","]
    inp.nset("HEADN", head); inp.nset("FIXED", fixed)
    inp.raw(f"""
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
FIXED, 1, 3
*CLOAD
HEADN, 1, {_f(F[0] / len(head))}
HEADN, 2, {_f(F[1] / len(head))}
HEADN, 3, {_f(F[2] / len(head))}
{FIELD_OUTPUT}
*END STEP""")
    inp.write(outdir / f"{name}.inp")
    np.savez_compressed(outdir / "mesh3d.npz", **{f"{k}_conn": v for k, v in elems.items()},
                        **{f"{k}_elab": v for k, v in elab.items()},
                        node_labels=np.array(sorted(coords)), nodes=np.array([coords[n] for n in sorted(coords)]))
    info = {"name": name, "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_head": len(head), "n_fixed": len(fixed),
            "h_roi": h_roi, "h_far": h_far, "load_N": F.tolist()}
    (outdir / "model3d.json").write_text(json.dumps(info))
    return info


if __name__ == "__main__":
    import time
    fm = FR.build()
    print("load (model frame, N):", load_vector(fm.cfg).round(1), "|F| =", round(float(np.linalg.norm(load_vector(fm.cfg))), 1))
    from cases import EXAMPLES
    st = G.Stem3D(**EXAMPLES["boxy, calcar-heavy, early taper"])
    pl = G.template(st, fm)
    print("template:", {k: v for k, v in pl.items() if k != "pose"})
    t = time.time()
    info = build(st, fm, pl, HERE / "out" / "smoke_v2a", "smoke")
    print("build", round(time.time() - t, 1), "s", {k: v for k, v in info.items() if k != "slave"})
    t = time.time()
    ii = build_intact(fm, HERE / "out" / "smoke_v2a_intact", "intact")
    print("intact", round(time.time() - t, 1), "s", ii)
