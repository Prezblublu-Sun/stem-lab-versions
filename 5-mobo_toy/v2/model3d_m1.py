"""M1 界面模型（修改方案 V4 的 P1，在 Linux 上跑）：柄与骨共用界面网格。

与 model3d_v2 的区别
* 锉腔 = 柄体本身（CAD 过盈为 0）。骨 = 皮质/松质 − 柄，三者一起碎片化，界面只划一次网格，两侧节点一一重合。
* 界面节点复制一份给柄侧（孪生节点）。粘接模型直接用共享节点（不需要 *TIE）；摩擦模型用孪生节点 + 接触对。
* 过盈：把柄侧孪生节点沿柄的外法向平移 δ（"offset"）。两侧分面完全相同，弦高误差相互抵消，
  法向过盈处处等于 δ；与皮质相邻的节点不平移（皮质处不施过盈）。再用 *CONTACT INTERFERENCE, SHRINK 逐步消除。
  备选 "clearance"：几何不动，用 *CLEARANCE, VALUE=−δ（只在 Lamé 对照里比较用）。
* 摩擦：罚函数的弹性滑移上限 = slip tolerance × 特征单元尺寸；默认 2.5e-4（2 mm 单元 → 0.5 µm）。可选 Lagrange。
* 步：PRESSFIT → RELEASE → LOAD → UNLOAD → LOAD2。微动取第二循环（LOAD2 对 UNLOAD）的节点对相对切向位移。
* mesh3d.npz 另存节点对：pair_bone、pair_stem、pair_normal（柄外法向）、pair_area、pair_interf、pair_cortex。

Lamé 对照（build_lame）：四分之一圆柱压入套筒，走同一套界面代码。
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
from model3d_v2 import MESH_OPTS, BuildError, _extract, _femur_shapes, _keep, _size_field, load_vector  # noqa: E402
from spot3d.model3d import FACES  # noqa: E402
from spot3d.qoi3d import FACE_MID  # noqa: E402

DEFAULTS = {"slip_tol": 2.5e-4, "lagrange": False, "interference": "clearance"}
# 2026-09-29 Lamé 对照：两种方法的力学状态都对（由套筒外表面膨胀反推的压力误差 offset −0.5%、clearance −0.2%），
# clearance 的界面法向位移更均匀（标准差 0.07 µm 对 0.6 µm），取为默认。节点 CPRESS 输出的均值偏差大（−24% / +11%），只作参考。
KEEP_FRIC = ["RELEASE_CONTACT.csv", "LOAD_CONTACT.csv", "UNLOAD_CONTACT.csv", "LOAD2_CONTACT.csv",
             "RELEASE_U.csv", "LOAD_U.csv", "UNLOAD_U.csv", "LOAD2_U.csv"]
KEEP_BOND = ["LOAD_ENER.csv", "LOAD_S.csv"]
KEEP_LAME = ["PRESSFIT_CONTACT.csv", "PRESSFIT_U.csv", "PRESSFIT_RF.csv", "PRESSFIT_E.csv", "PRESSFIT_CFORCE.csv"]
# 2026-09-29 第三份评估后：摩擦模型另外输出反力、节点接触力与接触面积、应变（导出见 abaqus/odb_export.py）
FIELD_M1 = "*OUTPUT, FIELD\n*NODE OUTPUT\nU, RF\n*ELEMENT OUTPUT\nS, E, ELSE, EVOL"
CONTACT_M1 = "*CONTACT OUTPUT\nCSTRESS, CDISP, CSTATUS, CFORCE, CNAREA"


def keep_lists(steps):
    k = [f"{s}_{x}.csv" for s in steps[1:] for x in ("U", "CONTACT", "CFORCE", "RF")]
    k += [f"{s}_{x}.csv" for s in ("RELEASE", steps[-1]) for x in ("E", "S")]
    return k


# ------------------------------------------------------------------------------------------------ 界面
def interface_faces(elems: dict, bone_regions, stem_region: str = "stem"):
    """柄单元与骨单元共用的三角面 → 从面（骨侧）与主面（柄侧）列表 [(region, 单元下标, 面号)]。"""
    tab = {}
    for r in list(bone_regions) + [stem_region]:
        for i, row in enumerate(elems[r]):
            for fc, idx in FACES.items():
                key = tuple(sorted(int(row[k]) for k in idx))
                tab.setdefault(key, []).append((r, i, fc))
    slave, master = [], []
    for ent in tab.values():
        if len(ent) != 2:
            continue
        rs = [e[0] for e in ent]
        if (rs[0] == stem_region) == (rs[1] == stem_region):
            continue
        slave.append(ent[0] if rs[1] == stem_region else ent[1])
        master.append(ent[1] if rs[1] == stem_region else ent[0])
    return slave, master


def node_pairs(elems: dict, coords: dict, slave, delta: float, no_interference=("cortex",)):
    """界面节点：柄外法向（指向骨内，面积加权平均）、集总面积（每面 A/6）、各节点的过盈量。"""
    acc_n, acc_a, touch = {}, {}, {}
    for r, i, fc in slave:
        row = elems[r][i]
        c = [int(row[k]) for k in FACES[fc]]
        mid = [int(row[k]) for k in FACE_MID[fc]]
        opp = int(row[[k for k in range(4) if k not in FACES[fc]][0]])
        P = np.array([coords[n] for n in c])
        nf = np.cross(P[1] - P[0], P[2] - P[0])
        A = 0.5 * float(np.linalg.norm(nf))
        if A <= 0:
            continue
        nf = nf / (2 * A)
        if nf @ (coords[opp] - P[0]) < 0:
            nf = -nf
        for n in c + mid:
            acc_n[n] = acc_n.get(n, 0.0) + A * nf
            acc_a[n] = acc_a.get(n, 0.0) + A / 6.0
            touch.setdefault(n, set()).add(r)
    nodes = np.array(sorted(acc_n), dtype=np.int64)
    nrm = np.array([acc_n[int(n)] for n in nodes])
    ln = np.linalg.norm(nrm, axis=1)
    if (ln < 1e-12).any():
        raise BuildError("L3", f"{int((ln < 1e-12).sum())} interface nodes have an undefined normal")
    nrm = nrm / ln[:, None]
    area = np.array([acc_a[int(n)] for n in nodes])
    on_cortex = np.array([bool(touch[int(n)] & set(no_interference)) for n in nodes])
    interf = np.where(on_cortex, 0.0, float(delta))
    return nodes, nrm, area, interf, on_cortex


def split_interface(elems: dict, coords: dict, nodes, nrm, interf, method: str, stem_region: str = "stem"):
    """复制界面节点给柄侧。返回（摩擦模型用的柄连接、含孪生节点的坐标、孪生节点号）。"""
    off = int(max(coords))
    twin = nodes + off
    lut = {int(n): int(t) for n, t in zip(nodes, twin)}
    stem_f = np.array([[lut.get(int(n), int(n)) for n in row] for row in elems[stem_region]], dtype=np.int64)
    cf = dict(coords)
    for n, t, v, d in zip(nodes, twin, nrm, interf):
        cf[int(t)] = coords[int(n)] + (d * v if method == "offset" else 0.0)
    return stem_f, cf, twin


def contact_block(mu: float, slip_tol: float, lagrange: bool, method: str, delta: float, n_interf: int = 1,
                  n_noint: int = 0) -> str:
    """method = "clearance"：逐节点给定初始过盈（节点集 NS_INTERF 为 −δ，NS_NOINT 为 0），几何不动。"""
    fr = "*FRICTION, LAGRANGE" if lagrange else f"*FRICTION, SLIP TOLERANCE={_f(slip_tol)}"
    s = f"""
*SURFACE INTERACTION, NAME=FRIC
{fr}
{_f(mu)},
*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD
*CONTACT PAIR, INTERACTION=FRIC, TYPE=SURFACE TO SURFACE, SMALL SLIDING
S_BONE, S_STEM"""
    if method == "clearance" and n_interf > 0 and delta > 0:
        s += f"\n*CLEARANCE, SLAVE=S_BONE, MASTER=S_STEM, TABULAR\nNS_INTERF, {_f(-delta)}"
        if n_noint > 0:
            s += "\nNS_NOINT, 0."
    return s


def _write_nodes(inp: Inp, coords: dict) -> None:
    inp.lines.append("*NODE")
    inp.lines += [f"{n}, {_f(coords[n][0])}, {_f(coords[n][1])}, {_f(coords[n][2])}" for n in sorted(coords)]


# ------------------------------------------------------------------------------------------------ 设计模型
def build(st: G.Stem3D, fm: FR.RealFemur, pl: dict, outdir: pathlib.Path, name: str, *, h_int=None, h_far=None, delta=None,
          mu=None, torque: bool = True, E_canc=None, slip_tol=None, lagrange=None, interference=None, cycles=None) -> dict:
    cfg = fm.cfg
    cycles = 2 if cycles is None else int(cycles)
    h_int = cfg["mesh"]["h_int_mm"] if h_int is None else h_int
    h_far = cfg["mesh"]["h_far_mm"] if h_far is None else h_far
    slip_tol = DEFAULTS["slip_tol"] if slip_tol is None else float(slip_tol)
    lagrange = DEFAULTS["lagrange"] if lagrange is None else bool(lagrange)
    interference = DEFAULTS["interference"] if interference is None else interference
    errors = []
    attempts = ((1, h_int, 40), (10, h_int, 40), (1, 0.97 * h_int, 40), (1, h_int, 24), (1, h_int, 72), (10, 0.97 * h_int, 24))
    for algo, h, m in attempts:
        try:
            info = _build(st, fm, pl, outdir, name, h_int=h, h_far=h_far, delta=delta, mu=mu, torque=torque, algo=algo, sec_pts=m,
                          E_canc=E_canc, slip_tol=slip_tol, lagrange=lagrange, interference=interference, cycles=cycles)
            info["mesh_attempt"] = {"algorithm3d": algo, "h_int": h, "section_points": m, "previous_errors": errors}
            (outdir / "model3d.json").write_text(json.dumps(info))
            return info
        except BuildError as e:
            if e.level == "L1":
                raise
            errors.append(f"algo {algo}, h {h:g}, m {m}: {e}"[:300])
        except Exception as e:                                            # noqa: BLE001  gmsh/OCC 的异常类型不统一
            errors.append(f"algo {algo}, h {h:g}, m {m}: {type(e).__name__}: {e}"[:300])
    raise BuildError("L3", "meshing failed after retries: " + " | ".join(errors))


def _build(st, fm, pl, outdir, name, *, h_int, h_far, delta, mu, torque, algo, sec_pts, E_canc, slip_tol, lagrange, interference, cycles=2):
    import gmsh
    cfg = fm.cfg
    ic = cfg["interface"]
    delta = ic["delta_mm"] if delta is None else float(delta)
    mu = ic["mu"] if mu is None else float(mu)
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
        body = E.stem_solid(occ, st, A0, pose, delta=0.0, m=sec_pts)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        u3 = fm.u3
        a = fm.C03
        Lneck = float(np.linalg.norm(fm.H - a))
        neck = occ.addCylinder(*a, *(Lneck * u3), pr["neck_radius_mm"])
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        stem, _ = occ.fuse(body_in, [(3, neck), (3, head)])
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
        if not cort_vols or not canc_vols or not stem_vols:
            raise BuildError("L3", f"fragment produced cortex {len(cort_vols)} / cancellous {len(canc_vols)} / stem {len(stem_vols)}")
        if set(stem_vols) & (set(cort_vols) | set(canc_vols)):
            raise BuildError("L3", "stem and bone volumes overlap after fragment")
        v_stem = float(sum(occ.getMass(3, t) for t in stem_vols))
        gmsh.model.addPhysicalGroup(3, cort_vols, name="cortex")
        gmsh.model.addPhysicalGroup(3, canc_vols, name="cancellous")
        gmsh.model.addPhysicalGroup(3, stem_vols, name="stem")
        surfs = sorted({t for v in stem_vols for d_, t in gmsh.model.getBoundary([(3, v)], oriented=False) if d_ == 2})
        _size_field(gmsh, surfs, cfg, h_int, h_far)
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.Algorithm3D", algo)
        gmsh.model.mesh.generate(3)
        elems, coords, quality = _extract(gmsh, {"cortex": cort_vols, "cancellous": canc_vols, "stem": stem_vols})
    finally:
        gmsh.finalize()
    slave, master = interface_faces(elems, ["cortex", "cancellous"])
    if len(slave) < 50:
        raise BuildError("L3", f"interface too small: {len(slave)} faces")
    nodes, nrm, area, interf, on_cortex = node_pairs(elems, coords, slave, delta)
    stem_f, coords_f, twin = split_interface(elems, coords, nodes, nrm, interf, interference)
    offs = {"cortex": 0, "cancellous": len(elems["cortex"]), "stem": len(elems["cortex"]) + len(elems["cancellous"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    Lc = cfg["load"]
    used_stem = np.unique(elems["stem"].ravel())
    used_bone = np.unique(np.r_[elems["cortex"].ravel(), elems["cancellous"].ravel()])
    head_n = [int(n) for n in used_stem if np.linalg.norm(coords[int(n)] - fm.H) <= Lc["head_coupling_radius_mm"] + 1e-6]
    fixed = [int(n) for n in used_bone if abs(coords[int(n)][2] - fm.z_trunc) < 1e-4]
    if len(head_n) < 10 or len(fixed) < 10:
        raise BuildError("L3", f"load/BC node sets too small: head {len(head_n)}, fixed {len(fixed)}")
    if set(head_n) & {int(n) for n in nodes}:
        raise BuildError("L3", "head load nodes touch the interface")
    F = load_vector(cfg)
    if not torque:
        F = F.copy()
        F[1] = 0.0
    Mt = cfg["materials"]
    E_canc = cfg["femur"]["E_cancellous"] if E_canc is None else float(E_canc)

    def common(kind, xyz, stem_conn):
        inp = Inp(f"mobo_toy M1 {name}_{kind} femur=real(STEP) delta={delta} mu={mu} torque={torque} E_canc={E_canc} "
                  f"interference={interference} slip_tol={slip_tol} lagrange={lagrange}")
        _write_nodes(inp, xyz)
        inp.elements("C3D10", "CORTEX", elab["cortex"], elems["cortex"])
        inp.elements("C3D10", "CANC", elab["cancellous"], elems["cancellous"])
        inp.elements("C3D10", "STEM", elab["stem"], stem_conn)
        inp.material("CORTICAL", Mt["cortical"]["E"], Mt["cortical"]["nu"])
        inp.material("CANCELLOUS", E_canc, Mt["cancellous_nu"])
        inp.material("TI6AL4V", Mt["titanium"]["E"], Mt["titanium"]["nu"])
        inp.lines += ["*SOLID SECTION, ELSET=CORTEX, MATERIAL=CORTICAL", ",",
                      "*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ",",
                      "*SOLID SECTION, ELSET=STEM, MATERIAL=TI6AL4V", ","]
        inp.nset("HEADN", head_n)
        inp.nset("FIXED", fixed)
        return inp
    load = (f"*CLOAD, OP=NEW\nHEADN, 1, {_f(F[0] / len(head_n))}\nHEADN, 2, {_f(F[1] / len(head_n))}\n"
            f"HEADN, 3, {_f(F[2] / len(head_n))}")
    unload = "*CLOAD, OP=NEW\nHEADN, 1, 0.\nHEADN, 2, 0.\nHEADN, 3, 0."
    out = f"{FIELD_M1}\n{CONTACT_M1}"
    steps = ["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2"] + [x for k in range(2, cycles) for x in (f"UNLOAD{k}", f"LOAD{k + 1}")]
    fric = common("fric", coords_f, stem_f)
    fric.element_surface("S_BONE", [(elab[r][i], fc) for r, i, fc in slave])
    fric.element_surface("S_STEM", [(elab[r][i], fc) for r, i, fc in master])
    n_int, n_no = int((interf > 0).sum()), int((interf <= 0).sum())
    if n_int:
        fric.nset("NS_INTERF", nodes[interf > 0])
    if n_no:
        fric.nset("NS_NOINT", nodes[interf <= 0])
    fric.raw(contact_block(mu, slip_tol, lagrange, interference, delta, n_int, n_no))
    fric.raw(f"""
*STEP, NAME=PRESSFIT, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*CONTACT INTERFERENCE, SHRINK
S_BONE, S_STEM
*BOUNDARY
FIXED, 1, 3
HEADN, 1, 3
{out}
*END STEP
*STEP, NAME=RELEASE, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*BOUNDARY, OP=NEW
FIXED, 1, 3
{out}
*END STEP
*STEP, NAME=LOAD, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
{load}
{out}
*END STEP
*STEP, NAME=UNLOAD, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
{unload}
{out}
*END STEP
*STEP, NAME=LOAD2, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
{load}
{out}
*END STEP""")
    for sname in steps[5:]:
        body = unload if sname.startswith("UNLOAD") else load
        fric.raw(f"*STEP, NAME={sname}, INC=1000\n*STATIC\n0.25, 1., 1e-08, 1.\n{body}\n{out}\n*END STEP")
    fric.write(outdir / f"{name}_fric.inp")
    bond = common("bond", coords, elems["stem"])
    bond.raw(f"""
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
FIXED, 1, 3
{load}
{FIELD_OUTPUT}
*END STEP""")
    bond.write(outdir / f"{name}_bond.inp")
    labs = np.array(sorted(coords_f))
    np.savez_compressed(outdir / "mesh3d.npz",
                        cortex_conn=elems["cortex"], cancellous_conn=elems["cancellous"], stem_conn=stem_f,
                        stem_conn_bond=elems["stem"], **{f"{k}_elab": v for k, v in elab.items()},
                        node_labels=labs, nodes=np.array([coords_f[int(n)] for n in labs]),
                        pair_bone=nodes, pair_stem=twin, pair_normal=nrm, pair_area=area, pair_interf=interf, pair_cortex=on_cortex)
    (outdir / "keep.json").write_text(json.dumps({"fric": keep_lists(steps), "bond": KEEP_BOND}))
    return {"name": name, "model": "m1", "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_nodes": len(coords_f),
            "n_slave_faces": len(slave), "n_master_faces": len(master), "n_pairs": int(len(nodes)),
            "n_pairs_cortex": int(on_cortex.sum()), "interface_area_mm2": float(area.sum()),
            "cortex_area_frac": float(area[on_cortex].sum() / area.sum()), "n_head": len(head_n), "n_fixed": len(fixed),
            "slave": [[int(elab[r][i]), fc] for r, i, fc in slave], "h_int": h_int, "h_far": h_far, "delta": delta, "mu": mu,
            "torque": torque, "E_canc": E_canc, "slip_tol": slip_tol, "lagrange": lagrange, "interference": interference, "cycles": cycles, "steps": steps,
            "load_N": F.tolist(), "stem_volume_mm3": v_stem, "A0": A0, "mesh_quality": quality}


# ------------------------------------------------------------------------------------------------ Lamé 对照
def lame_pressure(r: float, R: float, delta: float, E_h: float, nu_h: float, E_s: float, nu_s: float) -> float:
    """实心轴压入空心套筒的接触压力（平面应力，两端自由，无摩擦）。"""
    return delta / ((r / E_h) * ((R * R + r * r) / (R * R - r * r) + nu_h) + (r / E_s) * (1.0 - nu_s))


def build_lame(outdir: pathlib.Path, name: str, *, h: float = 2.0, delta: float = 0.10, mu: float = 0.0, r: float = 8.0,
               R: float = 20.0, L: float = 30.0, E_h: float = 400.0, E_s: float = 110000.0, nu: float = 0.3,
               slip_tol: float | None = None, lagrange: bool | None = None, interference: str | None = None) -> dict:
    import gmsh
    slip_tol = DEFAULTS["slip_tol"] if slip_tol is None else float(slip_tol)
    lagrange = DEFAULTS["lagrange"] if lagrange is None else bool(lagrange)
    interference = DEFAULTS["interference"] if interference is None else interference
    outdir.mkdir(parents=True, exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add(name)
        occ = gmsh.model.occ
        outer = occ.addCylinder(0, 0, 0, 0, 0, L, R, angle=math.pi / 2)
        inner = occ.addCylinder(0, 0, 0, 0, 0, L, r, angle=math.pi / 2)
        sleeve, _ = occ.cut([(3, outer)], [(3, inner)], removeObject=True, removeTool=False)
        ns = len(sleeve)
        frag, fmap = occ.fragment(sleeve, [(3, inner)])
        occ.synchronize()
        sl = sorted({t for dt in fmap[:ns] for d_, t in dt if d_ == 3})
        sh = sorted({t for dt in fmap[ns:] for d_, t in dt if d_ == 3})
        for k, v in MESH_OPTS:
            gmsh.option.setNumber(k, v)
        gmsh.option.setNumber("Mesh.MeshSizeMin", h)
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        elems, coords, quality = _extract(gmsh, {"cancellous": sl, "stem": sh})
    finally:
        gmsh.finalize()
    slave, master = interface_faces(elems, ["cancellous"])
    nodes, nrm, area, interf, on_cortex = node_pairs(elems, coords, slave, delta)
    stem_f, coords_f, twin = split_interface(elems, coords, nodes, nrm, interf, interference)
    offs = {"cancellous": 0, "stem": len(elems["cancellous"])}
    elab = {k: np.arange(offs[k] + 1, offs[k] + 1 + len(v)) for k, v in elems.items()}
    allx = {n: p for n, p in coords_f.items()}
    sx = [n for n, p in allx.items() if abs(p[0]) < 1e-6]
    sy = [n for n, p in allx.items() if abs(p[1]) < 1e-6]
    sz = [n for n, p in allx.items() if abs(p[2]) < 1e-6]
    inp = Inp(f"mobo_toy M1 Lame benchmark r={r} R={R} L={L} delta={delta} mu={mu} h={h} interference={interference} "
              f"slip_tol={slip_tol} lagrange={lagrange}")
    _write_nodes(inp, coords_f)
    inp.elements("C3D10", "CANC", elab["cancellous"], elems["cancellous"])
    inp.elements("C3D10", "STEM", elab["stem"], stem_f)
    inp.material("CANCELLOUS", E_h, nu)
    inp.material("TI6AL4V", E_s, nu)
    inp.lines += ["*SOLID SECTION, ELSET=CANC, MATERIAL=CANCELLOUS", ",", "*SOLID SECTION, ELSET=STEM, MATERIAL=TI6AL4V", ","]
    inp.nset("SYMX", sx)
    inp.nset("SYMY", sy)
    inp.nset("SYMZ", sz)
    inp.element_surface("S_BONE", [(elab[r_][i], fc) for r_, i, fc in slave])
    inp.element_surface("S_STEM", [(elab[r_][i], fc) for r_, i, fc in master])
    inp.nset("NS_INTERF", nodes)
    inp.raw(contact_block(mu, slip_tol, lagrange, interference, delta, len(nodes), 0))
    inp.raw(f"""
*STEP, NAME=PRESSFIT, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*CONTACT INTERFERENCE, SHRINK
S_BONE, S_STEM
*BOUNDARY
SYMX, 1, 1
SYMY, 2, 2
SYMZ, 3, 3
{FIELD_M1}
{CONTACT_M1}
*END STEP""")
    inp.write(outdir / f"{name}_fric.inp")
    labs = np.array(sorted(coords_f))
    np.savez_compressed(outdir / "mesh3d.npz", cancellous_conn=elems["cancellous"], stem_conn=stem_f,
                        **{f"{k}_elab": v for k, v in elab.items()}, node_labels=labs,
                        nodes=np.array([coords_f[int(n)] for n in labs]), pair_bone=nodes, pair_stem=twin, pair_normal=nrm,
                        pair_area=area, pair_interf=interf, pair_cortex=on_cortex)
    (outdir / "keep.json").write_text(json.dumps({"fric": KEEP_LAME}))
    info = {"name": name, "model": "m1-lame", "n_tet": {k: int(len(v)) for k, v in elems.items()}, "n_pairs": int(len(nodes)),
            "interface_area_mm2": float(area.sum()), "interface_area_exact_mm2": 0.5 * math.pi * r * L, "h": h, "delta": delta,
            "mu": mu, "r": r, "R": R, "L": L, "E_h": E_h, "E_s": E_s, "nu": nu, "slip_tol": slip_tol, "lagrange": lagrange,
            "interference": interference, "p_lame_MPa": lame_pressure(r, R, delta, E_h, nu, E_s, nu), "mesh_quality": quality}
    (outdir / "model3d.json").write_text(json.dumps(info))
    return info
