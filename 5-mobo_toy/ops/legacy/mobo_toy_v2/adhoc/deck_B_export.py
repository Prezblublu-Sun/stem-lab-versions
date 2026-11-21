"""批次 B 导出（Linux）：每个演示设计的 ParaView 文件、带场的 GLB、STL 与 STEP。

输出 ~/mobo_toy_v2/deck/B_demo/<代号>/（之后取回本机 deck_data/B_demo/，文件名全英文 ASCII）：
    fields.vtu        骨 + 柄的体网格（粘接模型、领共节点，二次四面体）。点数据 displacement_mm（LOAD）；单元数据 region
                      （0 皮质 / 1 松质 / 2 柄）、von_mises_MPa、sed_MPa、sed_change_pct（相对完整股骨，骨单元；最近同组织单元映射）
    interface.vtp     界面三角面（骨侧节点）。点数据 micromotion_um（柄身 + 领面，第 2 次加载的可恢复切向相对位移）、
                      contact_status（LOAD2：0 张开 / 1 滑移 / 2 粘着）、gap_um（LOAD2）、collar（1 = 领面）
    fields.glb        表面网格 + 逐顶点颜色，每个"表面 × 场"一个网格：stem_von_mises（色标截在 P99）、cortex_sed_change、
                      interface_micromotion（对数色标）、interface_contact_status、cancellous（灰）。原始数值另存为 _VALUE 属性
    fields_meta.json  每个场的色标、范围、单位
    stem.stl / femur_cut_cortex.stl / femur_cut_cancellous.stl / cavity.stl（FE 网格的表面，与计算用的几何一致）
    stem.step / femur_cut_cortex.step / femur_cut_cancellous.step / assembly.step（gmsh OCC 按建模流程重建的实体）
完整股骨：femur_cortex / femur_cancellous 的 STL 与 STEP（未截骨），fields.vtu 只有 SED。
"""
from __future__ import annotations

import json
import math
import pathlib
import struct
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

import jobs as J  # noqa: E402
import post_m1 as PM1  # noqa: E402
import qoi  # noqa: E402

OUT = HOME / "deck" / "B_demo"
REG = ("cortex", "cancellous", "stem")
TRI = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0))                      # C3D10 四个面的角点（与 FACES 相同）


# ------------------------------------------------------------------------------------------------ 读结果
def table(path, key, cols):
    t = qoi._csv(path)
    return t[key].astype(int), np.c_[tuple(t[c] for c in cols)]


def boundary_tris(conn: np.ndarray) -> np.ndarray:
    """四面体集合的外表面三角形（只出现一次的面），按外法向排序。"""
    faces = np.concatenate([conn[:, list(f)] for f in TRI])
    key = np.sort(faces, axis=1)
    _, idx, cnt = np.unique(key, axis=0, return_index=True, return_counts=True)
    return faces[idx[cnt == 1]]


# ------------------------------------------------------------------------------------------------ 颜色与 GLB
def colors(v: np.ndarray, cmap: str, lo: float, hi: float, log: bool = False) -> np.ndarray:
    import matplotlib
    cm = matplotlib.colormaps[cmap]
    x = np.log10(np.clip(v, lo, hi)) if log else np.clip(v, lo, hi)
    a, b = (math.log10(lo), math.log10(hi)) if log else (lo, hi)
    c = cm((x - a) / (b - a))
    c[~np.isfinite(v)] = (0.75, 0.75, 0.75, 1.0)
    return (c * 255).round().astype(np.uint8)


def normals(P: np.ndarray, T: np.ndarray) -> np.ndarray:
    fn = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
    vn = np.zeros_like(P)
    for k in range(3):
        np.add.at(vn, T[:, k], fn)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    return (vn / np.where(ln > 0, ln, 1)).astype(np.float32)


def write_glb(path: pathlib.Path, meshes: list[dict]) -> None:
    """最小 glTF 2.0 二进制写出：每个网格 POSITION、NORMAL、COLOR_0（RGBA8 归一化）、_VALUE（原始数值）与索引。"""
    blob, views, acc, gm, nodes = bytearray(), [], [], [], []

    def add(arr: np.ndarray, target: int | None) -> int:
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob.extend(arr.tobytes())
        views.append({"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes, **({"target": target} if target else {})})
        return len(views) - 1

    mats = [{"name": "vertex_colours", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.85},
             "doubleSided": True}]
    for m in meshes:
        P = m["P"].astype(np.float32)
        T = m["T"].astype(np.uint32)
        a = {}
        a["POSITION"] = len(acc); acc.append({"bufferView": add(P, 34962), "componentType": 5126, "count": len(P), "type": "VEC3",
                                               "min": P.min(0).tolist(), "max": P.max(0).tolist()})
        a["NORMAL"] = len(acc); acc.append({"bufferView": add(normals(P, T), 34962), "componentType": 5126, "count": len(P), "type": "VEC3"})
        a["COLOR_0"] = len(acc); acc.append({"bufferView": add(m["C"].astype(np.uint8), 34962), "componentType": 5121, "normalized": True,
                                              "count": len(P), "type": "VEC4"})
        if m.get("V") is not None:
            V = np.nan_to_num(m["V"].astype(np.float32), nan=-9999.0)
            a["_VALUE"] = len(acc); acc.append({"bufferView": add(V, 34962), "componentType": 5126, "count": len(P), "type": "SCALAR"})
        ia = len(acc); acc.append({"bufferView": add(T.ravel(), 34963), "componentType": 5125, "count": int(T.size), "type": "SCALAR"})
        gm.append({"name": m["name"], "primitives": [{"attributes": a, "indices": ia, "material": 0, "mode": 4}]})
        nodes.append({"name": m["name"], "mesh": len(gm) - 1})
    gl = {"asset": {"version": "2.0", "generator": "deck_B_export.py"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
          "nodes": nodes, "meshes": gm, "materials": mats, "accessors": acc, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    while len(blob) % 4:
        blob.append(0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack("<II", len(blob), 0x004E4942)); fh.write(bytes(blob))


def write_stl(path: pathlib.Path, P: np.ndarray, T: np.ndarray, name: str) -> None:
    v = P[T]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, v
    with open(path, "wb") as fh:
        fh.write(name.encode("ascii")[:80].ljust(80, b" ")); fh.write(struct.pack("<I", len(T))); fh.write(rec.tobytes())


def write_vtp(path: pathlib.Path, P: np.ndarray, T: np.ndarray, point_data: dict) -> None:
    """VTK XML PolyData（ASCII）：三角面 + 点数据；无值的点写 −1。meshio 不写 .vtp，所以自己写；ParaView 直接打开。"""
    def f(a):
        return " ".join(f"{x:.6g}" for x in np.asarray(a, float).ravel())
    nl = "\n"
    pd = "".join(f'<DataArray type="Float32" Name="{k}" NumberOfComponents="1" format="ascii">{f(np.nan_to_num(v, nan=-1.0))}</DataArray>{nl}'
                 for k, v in point_data.items())
    conn = " ".join(map(str, np.asarray(T, int).ravel()))
    offs = " ".join(map(str, range(3, 3 * len(T) + 1, 3)))
    xml = (f'<?xml version="1.0"?>{nl}<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">{nl}<PolyData>{nl}'
           f'<Piece NumberOfPoints="{len(P)}" NumberOfVerts="0" NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="{len(T)}">{nl}'
           f'<PointData>{nl}{pd}</PointData>{nl}'
           f'<Points><DataArray type="Float32" NumberOfComponents="3" format="ascii">{f(P)}</DataArray></Points>{nl}'
           f'<Polys><DataArray type="Int32" Name="connectivity" format="ascii">{conn}</DataArray>{nl}'
           f'<DataArray type="Int32" Name="offsets" format="ascii">{offs}</DataArray></Polys>{nl}'
           f'</Piece>{nl}</PolyData>{nl}</VTKFile>{nl}')
    path.write_text(xml)


def compact(P_all: np.ndarray, lut: np.ndarray, T_lab: np.ndarray):
    """节点号三角形 → 局部顶点数组。"""
    u, inv = np.unique(T_lab.ravel(), return_inverse=True)
    return P_all[lut[u]], inv.reshape(-1, 3), u


# ------------------------------------------------------------------------------------------------ 主流程
def intact_sed(intact: str):
    d = J.QROOT / intact
    m = dict(np.load(d / "mesh3d.npz"))
    lut = np.full(int(m["node_labels"].max()) + 1, -1); lut[m["node_labels"]] = np.arange(len(m["node_labels"]))
    el, val = table(d / "intact_csv" / "LOAD_ENER.csv", "elem", ("else", "evol"))
    sed = dict(zip(el.tolist(), (val[:, 0] / val[:, 1]).tolist()))
    out = {}
    for r in ("cortex", "cancellous"):
        cen = m["nodes"][lut[m[f"{r}_conn"][:, :4]]].mean(1)
        out[r] = (cKDTree(cen), np.array([sed.get(int(e), np.nan) for e in m[f"{r}_elab"]]))
    return out, m


def export_design(code: str, j: str, intact: str, out: pathlib.Path) -> dict:
    import meshio
    d = J.QROOT / j
    m = dict(np.load(d / "mesh3d.npz"))
    labs, X = m["node_labels"], m["nodes"]
    n = int(labs.max())
    lut = np.full(n + 1, -1); lut[labs] = np.arange(len(labs))
    conn = {"cortex": m["cortex_conn"], "cancellous": m["cancellous_conn"], "stem": m["stem_conn_bond"]}
    # 粘接模型（领共节点）：位移、单元应力与应变能
    U = np.nan_to_num(PM1._utab(d / "m_bond_csv" / "LOAD_U.csv", n))
    el, sv = table(d / "m_bond_csv" / "LOAD_S.csv", "elem", ("mises",))
    vm = dict(zip(el.tolist(), sv[:, 0].tolist()))
    el, ev = table(d / "m_bond_csv" / "LOAD_ENER.csv", "elem", ("else", "evol"))
    sed = dict(zip(el.tolist(), (ev[:, 0] / ev[:, 1]).tolist()))
    isd, _ = intact_sed(intact)
    used = np.unique(np.concatenate([c.ravel() for c in conn.values()]))
    lut2 = np.full(n + 1, -1); lut2[used] = np.arange(len(used))
    cells, cd = [], {"region": [], "von_mises_MPa": [], "sed_MPa": [], "sed_change_pct": []}
    per_elem = {}
    for k, r in enumerate(REG):
        c = conn[r]
        e = m[f"{r}_elab"]
        v_vm = np.array([vm.get(int(x), np.nan) for x in e]); v_sed = np.array([sed.get(int(x), np.nan) for x in e])
        if r in isd:
            cen = X[lut[c[:, :4]]].mean(1)
            dist, idx = isd[r][0].query(cen)
            ref = isd[r][1][idx]
            chg = np.where((dist < 6.0) & (ref > 0), 100.0 * (v_sed / ref - 1.0), np.nan)
        else:
            chg = np.full(len(c), np.nan)
        per_elem[r] = (v_vm, v_sed, chg)
        cells.append(("tetra10", lut2[c]))
        cd["region"].append(np.full(len(c), k, float)); cd["von_mises_MPa"].append(v_vm); cd["sed_MPa"].append(v_sed); cd["sed_change_pct"].append(chg)
    meshio.write(out / "fields.vtu", meshio.Mesh(X[lut[used]], cells, point_data={"displacement_mm": U[used]}, cell_data=cd), binary=True)
    # 摩擦模型：界面微动与接触状态（骨侧节点）
    p = PM1.pairs(d)
    pb, ps, nrm, di, col = p["pair_bone"], p["pair_stem"], p["pair_normal"], p["pair_interf"], p["pair_collar"]
    Uf = {s: PM1._utab(d / "m_fric_csv" / f"{s}_U.csv", n) for s in ("UNLOAD", "LOAD2")}
    rel = {s: Uf[s][ps] - Uf[s][pb] for s in Uf}
    dv = rel["LOAD2"] - rel["UNLOAD"]
    mic = np.linalg.norm(dv - (dv * nrm).sum(1)[:, None] * nrm, axis=1) * 1e3
    gap = -(di + (rel["LOAD2"] * nrm).sum(1)) * 1e3
    C = PM1._ctab(d / "m_fric_csv" / "LOAD2_CONTACT.csv", n)
    stt = C["CSTATUS"][pb]
    status = np.where(stt > 1.5, 2, np.where(stt > 0.5, 1, 0)).astype(float)
    # 界面三角面：骨侧单元里三个角点都是界面节点、且与柄共面的面 = 用粘接网格找骨–柄共有的三角面
    from model3d_m1 import interface_faces
    sl, _ = interface_faces({k: conn[k] for k in REG}, ["cortex", "cancellous"])
    from spot3d.model3d import FACES
    Tif = np.array([[conn[r][i][q] for q in FACES[fc]] for r, i, fc in sl])
    Pif, Tl, uif = compact(X, lut, Tif)
    pos = {int(b): k for k, b in enumerate(pb)}
    kk = np.array([pos.get(int(u), -1) for u in uif])
    take = lambda a: np.where(kk >= 0, a[np.maximum(kk, 0)], np.nan)  # noqa: E731
    write_vtp(out / "interface.vtp", Pif, Tl, {"micromotion_um": take(mic), "contact_status": take(status), "gap_um": take(gap),
                                                "collar": take(col.astype(float))})
    # 表面网格与逐顶点场
    T_stem = boundary_tris(conn["stem"][:, :4]); T_cort = boundary_tris(conn["cortex"][:, :4]); T_canc = boundary_tris(conn["cancellous"][:, :4])
    acc = np.zeros(n + 1); cnt = np.zeros(n + 1)
    for kq in range(4):
        np.add.at(acc, conn["stem"][:, kq], np.nan_to_num(per_elem["stem"][0])); np.add.at(cnt, conn["stem"][:, kq], 1)
    vm_node = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    acc = np.zeros(n + 1); cnt = np.zeros(n + 1)
    ch = per_elem["cortex"][2]
    okc = np.isfinite(ch)
    for kq in range(4):
        np.add.at(acc, conn["cortex"][okc, kq], ch[okc]); np.add.at(cnt, conn["cortex"][okc, kq], 1)
    sed_node = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    vm_cut = float(np.nanpercentile(per_elem["stem"][0], 99))
    meta = {"stem_von_mises": {"unit": "MPa", "cmap": "inferno", "min": 0.0, "max": vm_cut, "note": "colour scale clipped at the element P99"},
            "cortex_sed_change": {"unit": "% vs intact femur", "cmap": "RdBu", "min": -50.0, "max": 50.0, "note": "negative = less strain energy (shielding)"},
            "interface_micromotion": {"unit": "um", "cmap": "viridis", "min": 0.5, "max": 100.0, "log": True,
                                      "note": "reversible tangential relative displacement, 2nd load cycle; values < 2 um are below the numerical floor"},
            "interface_contact_status": {"unit": "category", "categories": {"0": "open", "1": "slip", "2": "stick"},
                                         "colours": {"0": [200, 200, 200], "1": [230, 120, 30], "2": [40, 90, 200]}},
            "cancellous": {"unit": "-", "colour": [215, 200, 170]}}
    meshes = []
    Ps, Ts, us = compact(X, lut, T_stem)
    meshes.append({"name": "stem_von_mises", "P": Ps, "T": Ts, "C": colors(vm_node[us], "inferno", 0.0, vm_cut), "V": vm_node[us]})
    Pc, Tc, uc = compact(X, lut, T_cort)
    meshes.append({"name": "cortex_sed_change", "P": Pc, "T": Tc, "C": colors(sed_node[uc], "RdBu", -50.0, 50.0), "V": sed_node[uc]})
    Pk, Tk, uk = compact(X, lut, T_canc)
    meshes.append({"name": "cancellous", "P": Pk, "T": Tk, "C": np.tile(np.array([215, 200, 170, 255], np.uint8), (len(Pk), 1)), "V": None})
    mv = take(mic)
    meshes.append({"name": "interface_micromotion", "P": Pif, "T": Tl, "C": colors(np.maximum(mv, 0.5), "viridis", 0.5, 100.0, log=True), "V": mv})
    sv_ = take(status)
    cs = np.array([[200, 200, 200, 255], [230, 120, 30, 255], [40, 90, 200, 255]], np.uint8)[np.nan_to_num(sv_, nan=0).astype(int)]
    meshes.append({"name": "interface_contact_status", "P": Pif, "T": Tl, "C": cs, "V": sv_})
    write_glb(out / "fields.glb", meshes)
    (out / "fields_meta.json").write_text(json.dumps(meta, indent=1))
    write_stl(out / "stem.stl", Ps, Ts, f"{code} stem")
    write_stl(out / "femur_cut_cortex.stl", Pc, Tc, f"{code} cortex")
    write_stl(out / "femur_cut_cancellous.stl", Pk, Tk, f"{code} cancellous")
    write_stl(out / "cavity.stl", Pif, Tl, f"{code} cavity wall")
    return {"code": code, "job": j, "vm_p99_colour_cut_MPa": vm_cut, "n_interface_tris": int(len(Tl)),
            "micromotion_p95_um_check": float(PM1._wq(mic[~col], p["pair_area"][~col], 0.95))}


def export_intact(j: str, out: pathlib.Path) -> dict:
    import meshio
    isd, m = intact_sed(j)
    labs, X = m["node_labels"], m["nodes"]
    lut = np.full(int(labs.max()) + 1, -1); lut[labs] = np.arange(len(labs))
    cells, cd = [], {"region": [], "sed_MPa": []}
    for k, r in enumerate(("cortex", "cancellous")):
        cells.append(("tetra10", lut[m[f"{r}_conn"]]))
        cd["region"].append(np.full(len(m[f"{r}_conn"]), k, float)); cd["sed_MPa"].append(isd[r][1])
    meshio.write(out / "fields.vtu", meshio.Mesh(X, cells, cell_data=cd), binary=True)
    for r, nm in (("cortex", "femur_cortex"), ("cancellous", "femur_cancellous")):
        P, T, _ = compact(X, lut, boundary_tris(m[f"{r}_conn"][:, :4]))
        write_stl(out / f"{nm}.stl", P, T, nm)
    return {"code": "intact", "job": j}


def export_step(code: str, j: str, out: pathlib.Path) -> dict:
    """gmsh OCC 按 model3d_m1 的建模流程重建实体（不划网格），写 STEP。"""
    import gmsh
    import fe3d_geom as E
    import geom3d as G
    from model3d_v2 import _femur_shapes, _keep
    spec = json.loads((J.QROOT / j / "spec.json").read_text())
    fm = J.femur_for(spec)
    pr = fm.cfg["prosthesis"]
    if spec["kind"] == "intact":
        parts = {}
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            for nm in ("femur_cortex", "femur_cancellous"):
                gmsh.model.add(nm)
                C, K = _femur_shapes(gmsh.model.occ, fm)
                keep = C if nm == "femur_cortex" else K
                gmsh.model.occ.remove([x for x in (K if nm == "femur_cortex" else C)], recursive=True)
                gmsh.model.occ.synchronize()
                gmsh.write(str(out / f"{nm}.step"))
                parts[nm] = len(keep)
        finally:
            gmsh.finalize()
        return parts
    if spec.get("collar_rule") == "wrap_fit":                      # 与建模时一样：新领规则的选号与领外形
        import collar_rule as CR
        CR.install(min_A0=float(spec.get("min_A0", 0.0)))
        G, E = CR.G, CR.E
    st = G.Stem3D(**spec["design"])
    pl = G.template(st, fm, margin=spec.get("margin"))
    A0, pose = pl["A0"], pl["pose"]
    prep = json.loads((J.QROOT / j / "prep.json").read_text())
    t0 = prep.get("templating") or {}
    if abs(float(t0.get("A0", A0)) - A0) > 0.05 or abs(float(t0.get("e", pl["e"])) - pl["e"]) > 1e-6:
        raise ValueError(f"re-templated size differs from the solved job: A0 {A0:.2f} vs {t0.get('A0')}, e {pl['e']} vs {t0.get('e')}")
    sec_pts = int((prep.get("mesh_attempt") or {}).get("section_points", 40))     # 与该作业建模时实际用的截面点数一致

    def build(occ):
        C, K = _femur_shapes(occ, fm)
        Ck, _ = occ.intersect(C, _keep(occ, fm))
        Kk, _ = occ.intersect(K, _keep(occ, fm))
        body = E.stem_solid(occ, st, A0, pose, delta=0.0, m=sec_pts)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        cv = []
        if getattr(st, "has_collar", False):
            cv = E.collar_solid(occ, fm, E.collar_outline(st, fm, pl)["poly"], st.collar_t)
        neck = occ.addCylinder(*fm.C03, *(float(np.linalg.norm(fm.H - fm.C03)) * fm.u3), pr["neck_radius_mm"])
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        stem, _ = occ.fuse(body_in, [(3, neck), (3, head)] + cv)
        bone, _ = occ.cut(Ck, stem, removeObject=True, removeTool=False)
        canc, _ = occ.cut(Kk, stem, removeObject=True, removeTool=False)
        return {"stem": stem, "femur_cut_cortex": bone, "femur_cut_cancellous": canc}

    gmsh.initialize()
    res = {}
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        for target in ("assembly", "stem", "femur_cut_cortex", "femur_cut_cancellous"):
            gmsh.model.add(target)
            occ = gmsh.model.occ
            P = build(occ)
            if target != "assembly":
                occ.remove([x for k, v in P.items() if k != target for x in v], recursive=True)
            occ.synchronize()
            gmsh.write(str(out / f"{target}.step"))
            res[target] = sum(occ.getMass(3, t) for d_, t in gmsh.model.getEntities(3))
            gmsh.model.remove()
    finally:
        gmsh.finalize()
    return {f"{k}_volume_mm3": v for k, v in res.items()}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*")
    ap.add_argument("--no-step", action="store_true")
    ap.add_argument("--ids", default="deck_B_ids.json", help="作业表（results/ 下），如 deck_BW_ids.json")
    ap.add_argument("--out", default="B_demo", help="输出目录名（~/mobo_toy_v2/deck/ 下）")
    a = ap.parse_args()
    OUT = HOME / "deck" / a.out
    ids = json.loads((J.RESULTS / a.ids).read_text())["jobs"]
    intact = ids.get("intact") or json.loads((J.RESULTS / "deck_B_ids.json").read_text())["jobs"]["intact"]
    rep = {}
    for code in a.codes or [k for k in ids if not k.endswith("_contact")]:
        j = ids[code]
        if J.state(J.QROOT / j) != "DONE":
            print(code, "not DONE", flush=True); continue
        out = OUT / code
        out.mkdir(parents=True, exist_ok=True)
        r = export_intact(j, out) if code == "intact" else export_design(code, j, intact, out)
        if not a.no_step:
            try:
                r["step"] = export_step(code, j, out)
            except Exception as e:                                          # noqa: BLE001
                r["step_error"] = f"{type(e).__name__}: {e}"[:300]
        rep[code] = r
        print(code, json.dumps(r, default=float), flush=True)
    (OUT / "export_report.json").write_text(json.dumps(rep, indent=1, default=float))
