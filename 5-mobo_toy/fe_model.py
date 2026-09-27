"""把几何（femur2d + stem2d）变成网格与 .inp：植入模型（_fric、_bond）与完整股骨参照模型。

规则（CLAUDE.md §5.2）：_bond 用 *TIE, ADJUST=NO，单步；_fric 摩擦接触，压配与加载分开：
Step PRESSFIT 以 *CONTACT INTERFERENCE, SHRINK 消除过盈，同时固定假体头节点（锥形柄在过盈下会被挤出，
相当于术中压住打入）；Step RELEASE 撤去该约束、不加载，让柄在摩擦下回弹到平衡；Step LOAD 保持并加载。
微动 = LOAD 相对 RELEASE 末的切向滑移增量。骨为从面、柄为主面；
从面只取被锉刀腔切出的骨边界（与柄过盈的部分），骨髓腔等间隙区不加任何约束。

骨网格一套同时用于 _fric 与 _bond：锉刀腔 = 柄体半宽内缩 δ。_bond 的 TIE 用位置容差覆盖 δ 的过盈。
每个模型目录另存 mesh.npz 与 model.json，供 qoi.py 做分区与沿弧长映射。
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import shapely
import shapely.prepared
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

import femur2d as F
import mesh2d
import stem2d as S
from inp_writer import CONTACT_OUTPUT, FIELD_OUTPUT, Inp, _f

CFG = F.CFG
RP_LABEL = 999999


def _opening(g, r):
    return g.buffer(-r, quad_segs=4).buffer(r, quad_segs=4) if r > 0 else g


GRID = 1e-3          # mm，所有边界先吸附到此网格再统一打断，共享边界逐点一致
MIN_PART = 0.01      # mm²
THIN = 0.05          # mm，比这更薄的面视为布尔运算的数值细条
MIN_ANGLE = 1.0      # 度，网格最小角低于此判 L3（柄体掠过内骨膜时会出现 1.3–2° 的薄条单元，可接受；< 1° 为退化）


def _rings(g):
    out = []
    for p in getattr(g, "geoms", [g]):
        if p.geom_type == "Polygon" and not p.is_empty:
            out.append(LineString(p.exterior.coords))
            out += [LineString(r.coords) for r in p.interiors]
    return out


def planar_regions(boundaries: list, classify, sliver: float) -> dict:
    """由一组边界一次性打断、polygonize 得到平面剖分，每个面按代表点分类。
    厚度 < sliver 的松质骨细条改标为皮质（只改标签不改几何，保持共形）。"""
    from shapely.ops import polygonize
    lines = []
    for g in boundaries:
        lines += _rings(shapely.set_precision(g, GRID))
    noded = unary_union(lines)
    faces = [f for f in polygonize(noded) if f.area > 1e-9]
    lab = []
    for f in faces:
        lb = classify(f.representative_point())
        thickness = 2.0 * f.area / max(f.length, 1e-12)
        if lb == "cancellous" and (thickness < sliver or f.area < MIN_PART):
            lb = "cortex"
        lab.append(lb)
    # 数值细条（厚度 < THIN）并入与之共享边界最长的非细条邻面：只改标签，几何不变，union 后细条消失
    thin = [2.0 * f.area / max(f.length, 1e-12) < THIN for f in faces]
    for i, f in enumerate(faces):
        if not thin[i] or lab[i] is None:
            continue
        best, blen = None, 0.0
        for j, g in enumerate(faces):
            if j == i or thin[j] or lab[j] is None or not f.intersects(g):
                continue
            ln = f.boundary.intersection(g.boundary).length
            if ln > blen:
                best, blen = lab[j], ln
        if best is not None:
            lab[i] = best
    labs: dict[str, list] = {}
    for f, lb in zip(faces, lab):
        if lb is not None:
            labs.setdefault(lb, []).append(f)
    return {k: unary_union(v) for k, v in labs.items()}


def implanted_regions(stem: S.Stem2D, delta: float, sliver: float):
    """返回 ({cortex, cancellous, cavity}, cavity)。cavity = 柄体按 δ 内缩后与保留骨的交。"""
    f = stem.femur
    # 不预先求交：保留骨外廓、完整柄体轮廓、完整髓腔轮廓一起打断，交点只算一次（避免近共线重复边造成的尖刺）
    kept = f.outer.intersection(f.kept_halfplane())
    body = stem.body(delta)
    kp = shapely.prepared.prep(kept.buffer(1e-6))
    cp, ip = shapely.prepared.prep(body), shapely.prepared.prep(f.inner)

    def classify(pt):
        if not kp.contains(pt):
            return None
        if cp.contains(pt):
            return "cavity"
        return "cancellous" if ip.contains(pt) else "cortex"
    reg = planar_regions([kept, body, f.inner], classify, sliver)
    cavity = reg.pop("cavity")
    return reg, cavity


def intact_regions(f: F.Femur2D, sliver: float) -> dict:
    outer = shapely.set_precision(f.outer, GRID)
    inner = shapely.set_precision(f.inner, GRID)
    op, ip = shapely.prepared.prep(outer.buffer(1e-6)), shapely.prepared.prep(inner)

    def classify(pt):
        if not op.contains(pt):
            return None
        return "cancellous" if ip.contains(pt) else "cortex"
    return planar_regions([outer, inner], classify, sliver)


def _save_mesh(path: pathlib.Path, meshes: dict):
    arrs = {}
    for name, m in meshes.items():
        arrs[f"{name}_nodes"] = m.nodes
        arrs[f"{name}_labels"] = m.node_labels
        for r in m.elems:
            arrs[f"{name}_{r}_conn"] = m.elems[r]
            arrs[f"{name}_{r}_elab"] = m.elem_labels[r]
    np.savez_compressed(path, **arrs)


def _materials(inp: Inp, E_canc: float):
    M = CFG["materials"]
    inp.material("CORTICAL", M["cortical"]["E"], M["cortical"]["nu"])
    inp.material("CANCELLOUS", E_canc, M["cancellous_nu"])
    inp.material("TI6AL4V", M["titanium"]["E"], M["titanium"]["nu"])


def _load_lines(load_sign: float, n_head: int) -> str:
    """头心载荷按均匀权重分到头部圆盘内全部节点（等价于 UNIFORM 分布耦合，但不引入约束方程）。
    *CLOAD 作用于节点集时，数值施加到集合里的每个节点。"""
    L = CFG["load"]
    return (f"*CLOAD\nHEADN, 1, {_f(load_sign * L['Fx'] / n_head)}\n"
            f"HEADN, 2, {_f(L['Fz'] / n_head)}")


SIDE_OFFSET = 500000   # 侧板单元号 = 骨单元号 + 偏移（共用节点）


def _bone_block(inp: Inp, bm, E_canc, side_plate: float = 0.0):
    inp.nodes(bm.node_labels, bm.nodes)
    inp.elements("CPS6M", "CORTEX", bm.elem_labels["cortex"], bm.elems["cortex"])
    if "cancellous" in bm.elems:
        inp.elements("CPS6M", "CANC", bm.elem_labels["cancellous"], bm.elems["cancellous"])
    t = CFG["plane_stress_thickness"]["bone"]
    inp.solid_section("CORTEX", "CORTICAL", t)
    if "cancellous" in bm.elems:
        inp.solid_section("CANC", "CANCELLOUS", t)
    if side_plate > 0:
        for reg in bm.elems:                          # 侧板：覆盖全部骨区与锉刀腔，与骨共节点
            inp.elements("CPS6M", f"SP_{reg.upper()}", bm.elem_labels[reg] + SIDE_OFFSET, bm.elems[reg])
        inp.elset("SIDEPLATE", [], generate_from=[f"SP_{reg.upper()}" for reg in bm.elems])
        inp.solid_section("SIDEPLATE", "CORTICAL", side_plate)
    zd = CFG["femur"]["distal_z"]
    inp.nset("FIXED", bm.node_labels[np.isclose(bm.nodes[:, 1], zd, atol=1e-5)])


def build_implanted(stem: S.Stem2D, outdir: pathlib.Path, name: str, *, mu: float | None = None,
                    delta: float | None = None, load_sign: float = 1.0, mesh_scale: float = 1.0,
                    side_plate: float | None = None) -> dict:
    """写 <name>_fric.inp 与 <name>_bond.inp；返回模型信息（单元数、质量、面、耗时相关量）。"""
    ic, mc = CFG["interface"], CFG["mesh"]
    side_plate = CFG["side_plate"]["thickness"] if side_plate is None else side_plate
    mu = ic["mu"] if mu is None else mu
    delta = ic["delta"] if delta is None else delta
    f = stem.femur
    regions, cavity = implanted_regions(stem, max(delta, 0.0), mc["sliver"])
    h_i, h_b, h_s = mc["h_interface"] * mesh_scale, mc["h_far_bone"] * mesh_scale, mc["h_far_stem"] * mesh_scale
    cav_ring = cavity.exterior if cavity.geom_type == "Polygon" else unary_union([p.exterior for p in cavity.geoms])
    part = dict(regions)
    if side_plate > 0:
        part["cavity"] = cavity                        # 侧板在锉刀腔处的部分（与骨共形）
    bm = mesh2d.mesh_partition(part, mesh2d.graded_size(cav_ring, h_i, h_b, mc["ramp"]), name=f"{name}_bone")
    if bm.quality["min_angle_deg"] < MIN_ANGLE:
        raise RuntimeError(f"degenerate bone mesh: min angle {bm.quality['min_angle_deg']:.4f} deg")
    stem_poly = stem.full()
    body_ring = stem.body().exterior
    sm = mesh2d.mesh_partition({"stem": stem_poly}, mesh2d.graded_size(body_ring, h_i, h_s, mc["ramp"] / 2),
                               node_offset=int(bm.node_labels.max()) + 1000,
                               elem_offset=int(max(v.max() for v in bm.elem_labels.values())) + 1000,
                               name=f"{name}_stem")

    # --- 从面：骨边界上、落在锉刀腔边界上的边（截骨面上的边除外）
    C0, u = f.cut
    cut_line = LineString([C0 - 80 * np.array([-u[1], u[0]]), C0 + 80 * np.array([-u[1], u[0]])])
    cavity_edges = []
    for el, face, a, b in bm.boundary_edges([r for r in regions if r in bm.elems]):
        pa, pb = bm.coords([a, b])
        mid = 0.5 * (pa + pb)
        d_ring = max(cav_ring.distance(Point(p)) for p in (pa, pb, mid))
        d_cut = max(cut_line.distance(Point(p)) for p in (pa, pb))
        if d_ring < 0.02 and d_cut > 0.05:
            cavity_edges.append((el, face, a, b))
    if not cavity_edges:
        raise RuntimeError("no slave (cavity) edges found")
    # --- 主面：柄体边界上、截骨线以下（放宽 3 mm）的边
    master_edges = []
    for el, face, a, b in sm.boundary_edges(["stem"]):
        pa, pb = sm.coords([a, b])
        mid = 0.5 * (pa + pb)
        if body_ring.distance(Point(mid)) < 0.02 and float((mid - C0) @ u) <= 3.0:
            master_edges.append((el, face, a, b))
    H = np.array(CFG["femur"]["head_center"], dtype=float)
    r_c = CFG["load"]["head_coupling_radius"]
    head_nodes = sm.node_labels[np.linalg.norm(sm.nodes - H, axis=1) <= r_c + 1e-6]

    def common(kind: str) -> Inp:
        inp = Inp(f"mobo_toy {name}_{kind} dorr={f.dorr} E_canc={f.E_cancellous} mu={mu} delta={delta} "
                  f"load_sign={load_sign:+g} mesh_scale={mesh_scale}")
        _bone_block(inp, bm, f.E_cancellous, side_plate)
        inp.nodes(sm.node_labels, sm.nodes)
        inp.elements("CPS6M", "STEM", sm.elem_labels["stem"], sm.elems["stem"])
        inp.solid_section("STEM", "TI6AL4V", CFG["plane_stress_thickness"]["stem"])
        _materials(inp, f.E_cancellous)
        inp.element_surface("S_BONE", [(e, fc) for e, fc, _, _ in cavity_edges])
        inp.element_surface("S_STEM", [(e, fc) for e, fc, _, _ in master_edges])
        inp.nset("HEADN", head_nodes)
        return inp

    outdir.mkdir(parents=True, exist_ok=True)
    fric = common("fric")
    fric.raw(f"""
*SURFACE INTERACTION, NAME=FRIC
{_f(CFG['contact_thickness'])},
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
FIXED, 1, 2
HEADN, 1, 2
{FIELD_OUTPUT}
{CONTACT_OUTPUT}
*END STEP
*STEP, NAME=RELEASE, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
*BOUNDARY, OP=NEW
FIXED, 1, 2
{FIELD_OUTPUT}
{CONTACT_OUTPUT}
*END STEP
*STEP, NAME=LOAD, INC=1000
*STATIC
0.25, 1., 1e-08, 1.
{_load_lines(load_sign, len(head_nodes))}
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
FIXED, 1, 2
{_load_lines(load_sign, len(head_nodes))}
{FIELD_OUTPUT}
*END STEP""")
    bond.write(outdir / f"{name}_bond.inp")
    _save_mesh(outdir / "mesh.npz", {"bone": bm, "stem": sm})
    info = {"name": name, "dorr": f.dorr, "E_cancellous": f.E_cancellous, "mu": mu, "delta": delta,
            "load_sign": load_sign, "mesh_scale": mesh_scale, "side_plate": side_plate,
            "n_elem_bone": bm.n_elems, "n_elem_stem": sm.n_elems,
            "min_angle": min(bm.quality["min_angle_deg"], sm.quality["min_angle_deg"]),
            "n_below_15deg": bm.quality["n_below_15deg"] + sm.quality["n_below_15deg"],
            "cavity_area": cavity.area, "stem_area_in_bone": stem.in_bone().area,
            "slave_edges": [[int(a), int(b), int(e), int(fc)] for e, fc, a, b in cavity_edges],
            "master_edges": [[int(a), int(b), int(e), int(fc)] for e, fc, a, b in master_edges],
            "n_head_nodes": int(len(head_nodes)),
            "axis": {"C0": list(map(float, stem.C0)), "d0": list(map(float, stem.d0)), "kappa": stem.kappa,
                     "L": stem.L, "s_min": stem.s_min}}
    (outdir / "model.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def build_intact(dorr: str, E_canc: float, outdir: pathlib.Path, name: str, *, load_sign: float = 1.0,
                 mesh_scale: float = 1.0, side_plate: float | None = None) -> dict:
    side_plate = CFG["side_plate"]["thickness"] if side_plate is None else side_plate
    f = F.build(dorr, E_canc)
    mc = CFG["mesh"]
    regions = intact_regions(f, mc["sliver"])
    zones = f.zones()
    # ROI 附近 1.0 mm，远处 3 mm
    target = unary_union([zones["gruen7"], zones["gruen1"]])
    bm = mesh2d.mesh_partition(regions, mesh2d.graded_size(target, 1.0 * mesh_scale, mc["h_far_bone"] * mesh_scale,
                                                           mc["ramp"]), name=name)
    H = np.array(CFG["femur"]["head_center"], dtype=float)
    r_c = CFG["load"]["head_coupling_radius"]
    head_nodes = bm.node_labels[np.linalg.norm(bm.nodes - H, axis=1) <= r_c + 1e-6]
    inp = Inp(f"mobo_toy {name} intact dorr={dorr} E_canc={E_canc} load_sign={load_sign:+g}")
    _bone_block(inp, bm, E_canc, side_plate)
    _materials(inp, E_canc)
    inp.nset("HEADN", head_nodes)
    inp.raw(f"""
*STEP, NAME=LOAD
*STATIC
1., 1., 1e-05, 1.
*BOUNDARY
FIXED, 1, 2
{_load_lines(load_sign, len(head_nodes))}
{FIELD_OUTPUT}
*END STEP""")
    outdir.mkdir(parents=True, exist_ok=True)
    inp.write(outdir / f"{name}.inp")
    _save_mesh(outdir / "mesh.npz", {"bone": bm})
    info = {"name": name, "dorr": dorr, "E_cancellous": E_canc, "load_sign": load_sign, "side_plate": side_plate,
            "n_elem_bone": bm.n_elems, "min_angle": bm.quality["min_angle_deg"], "n_head_nodes": int(len(head_nodes))}
    (outdir / "model.json").write_text(json.dumps(info), encoding="utf-8")
    return info


# --------------------------------------------------------------------------- Lamé 压配验证（R2-V1）
def lame_analytic(b: float, c: float, delta: float, E_o: float, nu_o: float, E_i: float, nu_i: float) -> float:
    """平面应力：实心圆盘（E_i, ν_i，半径 b）压入圆环（E_o, ν_o，内径 b、外径 c），径向过盈 δ。接触压力 p。"""
    return delta / ((b / E_o) * ((c * c + b * b) / (c * c - b * b) + nu_o) + (b / E_i) * (1 - nu_i))


def build_lame(outdir: pathlib.Path, name: str, *, b=10.0, c=25.0, delta=0.1, h=0.5, E_o=16800.0, nu_o=0.3,
               E_i=110000.0, nu_i=0.35, variant: str = "small_shrink") -> dict:
    """四分之一模型：圆盘（柄材料）与圆环（皮质）过盈 δ；x=0、y=0 两边对称约束。厚度 1、接触面外厚度 1。"""
    from shapely.geometry import Point as P, box as B
    quad = B(0, 0, 100, 100)
    disk = P(0, 0).buffer(b, quad_segs=256).intersection(quad)
    ring = P(0, 0).buffer(c, quad_segs=256).difference(P(0, 0).buffer(b - delta, quad_segs=256)).intersection(quad)
    rm = mesh2d.mesh_partition({"ring": ring}, lambda x, y: h, name=f"{name}_ring")
    dm = mesh2d.mesh_partition({"disk": disk}, lambda x, y: h, node_offset=int(rm.node_labels.max()) + 1000,
                               elem_offset=int(rm.elem_labels["ring"].max()) + 1000, name=f"{name}_disk")

    def arc_edges(m, reg, r):
        out = []
        for el, fc, a, bb in m.boundary_edges([reg]):
            pa, pb = m.coords([a, bb])
            if abs(np.linalg.norm(pa) - r) < 1e-3 and abs(np.linalg.norm(pb) - r) < 1e-3:
                out.append((el, fc))
        return out
    inp = Inp(f"mobo_toy Lame press-fit b={b} c={c} delta={delta} variant={variant}")
    for m, reg, mat, E, nu in ((rm, "ring", "RINGMAT", E_o, nu_o), (dm, "disk", "DISKMAT", E_i, nu_i)):
        inp.nodes(m.node_labels, m.nodes)
        inp.elements("CPS6M", reg.upper(), m.elem_labels[reg], m.elems[reg])
        inp.material(mat, E, nu)
        inp.solid_section(reg.upper(), mat, 1.0)
    allxy = np.vstack([rm.nodes, dm.nodes]); alllab = np.concatenate([rm.node_labels, dm.node_labels])
    inp.nset("SYMX", alllab[np.isclose(allxy[:, 0], 0.0, atol=1e-6)])
    inp.nset("SYMY", alllab[np.isclose(allxy[:, 1], 0.0, atol=1e-6)])
    inp.element_surface("S_RING", arc_edges(rm, "ring", b - delta))
    inp.element_surface("S_DISK", arc_edges(dm, "disk", b))
    sliding = "SMALL SLIDING" if variant.startswith("small") else ""
    ctype = ", TYPE=SURFACE TO SURFACE" if "node" not in variant else ", TYPE=NODE TO SURFACE"
    shrink = "*CONTACT INTERFERENCE, SHRINK\nS_RING, S_DISK" if "shrink" in variant else ""
    inp.raw(f"""
*SURFACE INTERACTION, NAME=FRIC
1.,
*FRICTION, SLIP TOLERANCE=0.005
0.3,
*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=HARD
*CONTACT PAIR, INTERACTION=FRIC{ctype}{(', ' + sliding) if sliding else ''}
S_RING, S_DISK
*STEP, NAME=PRESSFIT, INC=1000
*STATIC
0.05, 1., 1e-08, 1.
{shrink}
*BOUNDARY
SYMX, 1, 1
SYMY, 2, 2
*OUTPUT, FIELD
*NODE OUTPUT
U
*ELEMENT OUTPUT
S
*CONTACT OUTPUT
CSTRESS, CDISP, CSTATUS
*END STEP""")
    outdir.mkdir(parents=True, exist_ok=True)
    inp.write(outdir / f"{name}.inp")
    return {"p_analytic": lame_analytic(b, c, delta, E_o, nu_o, E_i, nu_i), "n_elem": rm.n_elems + dm.n_elems}
