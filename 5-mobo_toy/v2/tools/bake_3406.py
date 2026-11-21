"""S1：把 Churun 的未切割 Sawbones 3406（左股骨，原生坐标 +z 向远端）烘焙成"右侧化"的 STEP 对，供 femur_3406.py 用。

变换只有一个：z 取反（S = diag(1, 1, −1)），不用 README 的 A 系（A 系把 y 也取反，+y 会变成前方；
femur_real.landmarks 假定右股骨、+y 后方：髁 = argmax(y)，前倾符号 = −(u·ey)，model3d_v2.load_vector 的符号也写死了 +y 后方）。
原生系 x 内侧、y 后方、z 远端（左股骨）；只翻 z ⇒ x 内侧、y 后方、z 近端，而且左→右镜像，正好是检测器的约定。

输出（v2/data/femur_3406/，STEP 本身被 .gitignore 排除，只提交校验和与来源说明）
    3406R_cortical.STEP, 3406R_cancellous.STEP, SHA256SUMS.txt, PROVENANCE.md
验收（与 2026-10-23 侦察在 gmsh 4.15.2 里验证过的数一致）
    体积 271 529 / 127 952 mm³（±0.01 %），面数 869 / 155，fragment(皮质, 松质) → 147 个共享面。
用法
    .venv-mobo/Scripts/python.exe v2/tools/bake_3406.py [--src DIR] [--force]
    .venv-mobo/Scripts/python.exe v2/tools/bake_3406.py --refill [--force]       # v2 配方（扩孔再填），只写 *_v2 文件，见 ream_refill()

v2 配方（2026-10-23 S6 发现、S1 加入；默认关闭，--refill 打开）
    v1 的填孔圆柱两端各退 2.5 mm，在皮质内表面下留下两个盲窝，窝沿与皮质内面以极小角度相交；model3d_v2.build_intact 的
    fragment(皮质, 松质) 在头端孔口处碎片化出 0.01 mm 级的顶点/修剪曲线，皮质里出现 3 个 1.9e-9 mm³ 的退化四面体 → L3。
    修法：同轴、半径 = 填孔圆柱半径 + 0.3 mm、两端各伸出孔口 4 mm 的圆柱：芯 := (芯 − 圆柱) ∪ (圆柱 − 皮质实体)。
    填充体恰好止于皮质内表面（无盲窝、不与皮质重叠），原孔口的碎面随圆柱一起被挖掉。输出 3406R_cancellous_v2.STEP、
    SHA256SUMS_v2.txt、bake_report_v2.json，并在 PROVENANCE.md 末尾追加（可重复运行、覆盖）一节 "## v2"。皮质 STEP 不重烘焙、不改。
    femur_3406.py 的默认路径 / SHA 仍指向 v1，切换步骤见 research-log …/integration_2026-10-23/s1_rebake/SWITCHOVER.md。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
V2 = HERE.parent
OUT = V2 / "data" / "femur_3406"
SRC_DEFAULT = pathlib.Path(r"H:/projects/application/research-log/sawbone_3406_2026-10-23/churun_uncut_export")
FILES = {"cortical": ("Cortical_AP214.STEP", "3406R_cortical.STEP"), "cancellous": ("Cancellou_AP214.STEP", "3406R_cancellous.STEP")}
CANCELLOUS_V2 = "3406R_cancellous_v2.STEP"                                      # --refill 的输出；v1 文件不动
MIRROR_Z = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0]        # 3×4 行优先：diag(1, 1, −1)
EXPECT = {"cortical": {"mm3": 271529.0, "faces": 869}, "cancellous": {"mm3": 127952.0, "faces": 155}, "shared_faces": 147}
VOL_TOL = 1e-4                                                                  # ±0.01 %
REAM_MM, EXT_MM = 0.3, 4.0                                                      # v2：扩孔半径增量（相对填孔圆柱）、两端伸出孔口的长度
REFILL_RANGE_MM3 = (30.0, 400.0)                                                # v2 净增体积 = 两个盲窝；S6 实测 +123 mm³
PROV_V2_MARK = "## v2：扩孔再填（ream-and-refill）"


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def _session():
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    return gmsh


def _shell_components(gmsh, faces):
    """按共享边把面分成连通分量（一个实体的外壳 + 可能的内腔壳）。"""
    edge2 = {}
    for f in faces:
        _, down = gmsh.model.getAdjacencies(2, f)
        for e in down:
            edge2.setdefault(int(e), []).append(f)
    parent = {f: f for f in faces}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for fs in edge2.values():
        for g in fs[1:]:
            ra, rb = find(fs[0]), find(g)
            if ra != rb:
                parent[ra] = rb
    comps = {}
    for f in faces:
        comps.setdefault(find(f), []).append(f)
    return list(comps.values())


def _edge_loops(gmsh, edges):
    """把边按共享端点分成闭合环。"""
    pts = {e: [int(p) for p in gmsh.model.getAdjacencies(1, e)[1]] for e in edges}
    parent = {e: e for e in edges}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    by_pt = {}
    for e, ps in pts.items():
        for p in ps:
            by_pt.setdefault(p, []).append(e)
    for es in by_pt.values():
        for g in es[1:]:
            ra, rb = find(es[0]), find(g)
            if ra != rb:
                parent[ra] = rb
    loops = {}
    for e in edges:
        loops.setdefault(find(e), []).append(e)
    return list(loops.values())


def fill_bores(gmsh, V, strip_area=(300.0, 500.0), strip_thin_mm=6.0, ring_area_mm2=10.0):
    """填掉松质芯里的导针孔（2026-10-23 发现）：Churun 的 Cancellou 实体里有一条 Ø≈4.4 mm、长 97 mm 的贯通孔，
    沿颈部（烘焙坐标从 (−14, 2, 72) 到 (71, 2, 122)，即颈干角 ≈ 120°、前倾 ≈ 0° 的轴）从外侧皮质界面穿到头部芯表面，
    由两张 97 × 4.4 mm 的 B 样条条带面 + 两端各一张 4.4 mm² 的环面组成，两端开口贴在皮质内表面上。
    泡沫芯没有这种孔；留着它，距离场在颈部多一道"墙"（模板化判穿透），网格也会在柄旁留下薄片。
    做法：删掉孔的 4 张面，两端开口用 B 样条补片封上，用剩下的面重建实体。返回记录；没找到孔返回 None。"""
    occ = gmsh.model.occ
    faces = [int(t) for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]
    strips = []
    for f in faces:
        a = occ.getMass(2, f)
        if strip_area[0] <= a <= strip_area[1]:
            bb = np.array(gmsh.model.getBoundingBox(2, f))
            if (bb[3:] - bb[:3]).min() < strip_thin_mm:
                strips.append(f)
    if not strips:
        return None
    bore = set(strips)
    for f in strips:
        for e in gmsh.model.getAdjacencies(2, f)[1]:
            for u in gmsh.model.getAdjacencies(1, int(e))[0]:
                if occ.getMass(2, int(u)) < ring_area_mm2:
                    bore.add(int(u))
    rim = set()
    for f in bore:
        for e in gmsh.model.getAdjacencies(2, f)[1]:
            if any(int(u) not in bore for u in gmsh.model.getAdjacencies(1, int(e))[0]):
                rim.add(int(e))
    loops = _edge_loops(gmsh, sorted(rim))
    if len(loops) != 2:
        raise RuntimeError(f"bore: expected 2 rim loops (two openings), got {len(loops)}")
    bb = np.array([gmsh.model.getBoundingBox(2, f) for f in bore])
    rec = {"bore_faces": sorted(bore), "n_faces": len(bore), "area_mm2": float(sum(occ.getMass(2, f) for f in bore)),
           "bbox_min": bb[:, :3].min(0).tolist(), "bbox_max": bb[:, 3:].max(0).tolist(),
           "rim_loops": [{"edges": sorted(l), "length_mm": float(sum(occ.getMass(1, e) for e in l))} for l in loops]}
    # 开口环上的点 → 两端中心与轴；圆柱只放在孔内（两端各退到环最靠里的点再进 inset），不伸进皮质，不用再裁
    # （环面的补片方案 addSurfaceFilling 在 0.01–0.2 mm 的退化边上失败；伸出去再用皮质裁会把界面切成 200 多个面）
    P = []
    for l in loops:
        pts = {int(p) for e in l for p in gmsh.model.getAdjacencies(1, e)[1]}
        P.append(np.array([gmsh.model.getValue(0, p, []) for p in pts]))
    c1, c2 = P[0].mean(0), P[1].mean(0)
    u = (c2 - c1) / np.linalg.norm(c2 - c1)
    t1 = float(((P[0] - c1) @ u).max())                                  # 开口 1 最靠里的点（沿 +u）
    t2 = float(((P[1] - c1) @ u).min())                                  # 开口 2 最靠里的点
    r_bore = float(np.mean([np.linalg.norm((p - c) - ((p - c) @ u)[:, None] * u, axis=1).max() for p, c in ((P[0], c1), (P[1], c2))]))
    inset, r_cyl = 2.5, r_bore + 0.2                                     # 开口是斜的：半径只比孔大 0.2、两端退 2.5 mm，圆柱才不会从芯表面探进皮质
    #                                                                      （退 1 mm 时外侧开口处仍与皮质重叠 0.001 mm³，fragment 多出两个零体积碎片）
    a = c1 + (t1 + inset) * u
    length = (t2 - inset) - (t1 + inset)
    if length < 10:
        raise RuntimeError(f"bore: cylinder length {length:.1f} mm implausible")
    old_vol = float(occ.getMass(*V[0]))
    cyl = occ.addCylinder(*a, *(length * u), r_cyl)
    fused, _ = occ.fuse(V, [(3, cyl)], removeObject=True, removeTool=True)
    occ.synchronize()
    vols = [x for x in fused if x[0] == 3]
    if len(vols) != 1:
        raise RuntimeError(f"bore fill: fuse gave {len(vols)} volumes")
    V[:] = vols
    rec.update(axis_point_mm=c1.tolist(), axis_dir=u.tolist(), bore_length_mm=float(np.linalg.norm(c2 - c1)), bore_radius_mm=r_bore,
               cylinder={"start": a.tolist(), "length_mm": float(length), "radius_mm": float(r_cyl), "inset_mm": inset},
               volume_before_mm3=old_vol, volume_after_mm3=float(occ.getMass(*vols[0])),
               bore_volume_mm3=float(occ.getMass(*vols[0])) - old_vol,
               residual_pockets="two blind dimples (bore radius, <= rim obliquity + inset deep) under the cortex at the two openings")
    return rec


def _small_faces(gmsh, V, area_mm2=0.05) -> list[dict]:
    """实体边界上面积 < area_mm2 的碎面（S6 的诊断量：v1 芯上有 3 张 ≤ 0.05 mm² 的孔口残片）。"""
    occ = gmsh.model.occ
    out = []
    for d, t in gmsh.model.getBoundary(V, oriented=False):
        if d != 2:
            continue
        a = occ.getMass(2, t)
        if a < area_mm2:
            bb = np.array(gmsh.model.getBoundingBox(2, t))
            out.append({"face": int(t), "area_mm2": float(a), "centre_baked": ((bb[:3] + bb[3:]) / 2).round(3).tolist()})
    return out


def ream_refill(gmsh, V, cortical_step: pathlib.Path, bore: dict, ream_mm: float = REAM_MM, ext_mm: float = EXT_MM) -> dict:
    """v2 配方（S6 在 s6_fill_test.py 里验证过的做法，原样搬进烘焙）：在 fill_bores 之后，用同轴、半径 = 填孔圆柱半径 + ream_mm、
    两端各伸出两个孔口 ext_mm 的圆柱 T：芯 := (芯 − T) ∪ (T − 皮质实体)。
    - 芯 − T 把 v1 填孔圆柱、两个盲窝和 Churun 原件孔口的斜环面残片（≤ 0.05 mm² 的碎面）一起挖掉；
    - T − 皮质实体 落在骨内的那一块恰好止于皮质内表面（两端面就是皮质内面的一部分），既无盲窝也不与皮质重叠，所以 fragment(皮质, 松质)
      后皮质体积不变、界面仍共形；T 伸进皮质和伸出骨外的碎块按"质量 > 1 mm³、质心离轴 < r、沿轴落在孔长 ±1 mm 内"筛掉。
    皮质实体从已烘焙的 3406R_cortical.STEP 导入（就是模型用的那一件），用完连同弃块一起删掉，STEP 里只剩松质芯。返回记录。"""
    occ = gmsh.model.occ
    c1, u = np.array(bore["axis_point_mm"], float), np.array(bore["axis_dir"], float)
    u /= np.linalg.norm(u)
    Lb = float(bore["bore_length_mm"])
    r = float(bore["cylinder"]["radius_mm"]) + ream_mm                                  # = 孔半径 + 0.2 + ream_mm
    start = c1 - ext_mm * u
    vol_before = float(occ.getMass(*V[0]))
    faces_before = len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2])
    small_before = _small_faces(gmsh, V)
    t0 = time.time()
    cyl = occ.addCylinder(*start, *((Lb + 2 * ext_mm) * u), r)
    reamed, _ = occ.cut(V, [(3, cyl)], removeObject=True, removeTool=False)
    Vr = [x for x in reamed if x[0] == 3]
    if len(Vr) != 1:
        raise RuntimeError(f"ream: core − cylinder gave {len(Vr)} volumes")
    Cs = [x for x in occ.importShapes(str(cortical_step)) if x[0] == 3]
    if len(Cs) != 1:
        raise RuntimeError(f"ream: cortical STEP gave {len(Cs)} volumes")
    pieces, _ = occ.cut([(3, cyl)], Cs, removeObject=True, removeTool=False)
    occ.synchronize()
    vol_reamed = float(occ.getMass(*Vr[0]))
    keep, drop, recs = [], [], []
    for d, t in pieces:
        if d != 3:
            continue
        m = float(occ.getMass(3, t))
        c = np.array(occ.getCenterOfMass(3, t))
        dist_axis = float(np.linalg.norm(np.cross(c - c1, u)))
        s = float((c - c1) @ u)
        ok = m > 1.0 and -1.0 <= s <= Lb + 1.0 and dist_axis < r
        (keep if ok else drop).append((d, t))
        recs.append({"mass_mm3": m, "centre_baked": c.round(3).tolist(), "dist_to_axis_mm": dist_axis, "s_along_axis_mm": s, "kept": ok})
    if len(keep) != 1:
        raise RuntimeError(f"refill: expected exactly 1 filler piece inside the bone, got {len(keep)} ({recs})")
    fused, _ = occ.fuse(Vr, keep, removeObject=True, removeTool=True)
    vols = [x for x in fused if x[0] == 3]
    if len(vols) != 1:
        raise RuntimeError(f"refill: fuse gave {len(vols)} volumes")
    occ.remove(drop + Cs, recursive=True)                                           # STEP 里只留松质芯
    occ.synchronize()
    all3 = gmsh.model.getEntities(3)
    if all3 != vols:
        raise RuntimeError(f"refill: model holds {all3}, expected only {vols}")
    closure = set(gmsh.model.getBoundary(vols, recursive=True, oriented=False)) | set(gmsh.model.getBoundary(vols, oriented=False)) | set(vols)
    closure |= {(1, t) for f in gmsh.model.getBoundary(vols, oriented=False) for t in gmsh.model.getAdjacencies(2, f[1])[1]}
    orphans = [e for e in gmsh.model.getEntities() if e not in closure]
    if orphans:                                                                      # 删皮质后可能剩下不属于芯的自由面/线/点，不让它们进 STEP
        occ.remove(orphans, recursive=True)
        occ.synchronize()
    V[:] = vols
    vol_after = float(occ.getMass(*vols[0]))
    return {"recipe": "v2 ream-and-refill: core := (core - T) + (T - cortical solid)", "ream_mm": ream_mm, "ext_mm": ext_mm,
            "cylinder": {"start": start.tolist(), "length_mm": float(Lb + 2 * ext_mm), "radius_mm": r, "axis_dir": u.tolist()},
            "cortical_step": str(cortical_step), "volume_before_mm3": vol_before, "volume_reamed_mm3": vol_reamed, "volume_after_mm3": vol_after,
            "volume_added_mm3": vol_after - vol_before, "filler_pieces": recs, "n_filler_pieces_kept": len(keep), "n_orphans_removed": len(orphans),
            "faces_before": faces_before, "faces_after": len([t for d, t in gmsh.model.getBoundary(vols, oriented=False) if d == 2]),
            "small_faces_lt_0.05mm2_before": small_before, "small_faces_lt_0.05mm2_after": _small_faces(gmsh, vols), "boolean_s": round(time.time() - t0, 1)}


def bake_one(src: pathlib.Path, dst: pathlib.Path, fill_inner: bool = False, refill_with: pathlib.Path | None = None) -> dict:
    """导入 → 只翻 z →（松质芯：填导针孔；refill_with 给出皮质 STEP 时再按 v2 配方扩孔再填）→ 写 STEP。返回原生与镜像后的体积、面数。"""
    import numpy as _np  # noqa: F401
    gmsh = _session()
    try:
        occ = gmsh.model.occ
        V = [x for x in occ.importShapes(str(src)) if x[0] == 3]
        occ.synchronize()
        if len(V) != 1:
            raise RuntimeError(f"{src.name}: expected 1 volume, got {len(V)}")
        native = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                  "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        occ.affineTransform(V, MIRROR_Z)
        occ.synchronize()
        mirrored = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                    "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        bore = fill_bores(gmsh, V) if fill_inner else None
        if bore:
            vols = gmsh.model.getEntities(3)
            if len(vols) != 1:
                raise RuntimeError(f"{src.name}: {len(vols)} volumes after filling the bore")
            mirrored["bore_filled"] = bore
            mirrored["mm3_filled"] = occ.getMass(*vols[0])
            mirrored["faces_filled"] = len([t for d, t in gmsh.model.getBoundary(vols, oriented=False) if d == 2])
            mirrored["bbox_filled"] = list(gmsh.model.getBoundingBox(*vols[0]))
            if refill_with is not None:
                mirrored["refilled"] = ream_refill(gmsh, V, refill_with, bore)
                vols = gmsh.model.getEntities(3)
                mirrored["mm3_refilled"] = occ.getMass(*vols[0])
                mirrored["faces_refilled"] = len([t for d, t in gmsh.model.getBoundary(vols, oriented=False) if d == 2])
                mirrored["bbox_refilled"] = list(gmsh.model.getBoundingBox(*vols[0]))
        elif refill_with is not None:
            raise RuntimeError(f"{src.name}: --refill needs the bore (fill_bores found none)")
        t0 = time.time()
        tmp = dst.with_name(dst.stem + "_tmp.step")                     # gmsh 只认小写扩展名；写完改名为 .STEP（Windows 不分大小写，所以先用别的名字）
        gmsh.write(str(tmp))
        tmp.replace(dst)
        mirrored["write_s"] = round(time.time() - t0, 1)
    finally:
        gmsh.finalize()
    return {"native": native, "mirrored": mirrored}


def verify(paths: dict) -> dict:
    """重新导入两件：体积、面数；fragment 后的共享面数与体积（共形界面的证据）。"""
    gmsh = _session()
    try:
        occ = gmsh.model.occ
        C = [x for x in occ.importShapes(str(paths["cortical"])) if x[0] == 3]
        K = [x for x in occ.importShapes(str(paths["cancellous"])) if x[0] == 3]
        occ.synchronize()
        out = {}
        for k, V in (("cortical", C), ("cancellous", K)):
            if len(V) != 1:
                raise RuntimeError(f"{k}: re-import gives {len(V)} volumes")
            out[k] = {"mm3": occ.getMass(*V[0]), "faces": len([t for d, t in gmsh.model.getBoundary(V, oriented=False) if d == 2]),
                      "bbox": list(gmsh.model.getBoundingBox(*V[0]))}
        t0 = time.time()
        frag, fmap = occ.fragment(C, K)
        occ.synchronize()
        fc = {t for dt in fmap[:len(C)] for d, t in dt if d == 3}
        fk = {t for dt in fmap[len(C):] for d, t in dt if d == 3}
        bc = {t for d, t in gmsh.model.getBoundary([(3, v) for v in fc], oriented=False) if d == 2}
        bk = {t for d, t in gmsh.model.getBoundary([(3, v) for v in fk], oriented=False) if d == 2}
        out["fragment"] = {"cortex_vols": len(fc), "core_vols": len(fk), "shared_faces": len(bc & bk), "core_faces": len(bk),
                           "cortex_mm3_after": sum(occ.getMass(3, t) for t in fc), "core_mm3_after": sum(occ.getMass(3, t) for t in fk),
                           "fragment_s": round(time.time() - t0, 1)}
    finally:
        gmsh.finalize()
    return out


def accept(v: dict, bodies: dict) -> list[str]:
    """验收：皮质按原始数；松质按"镜像后原始体积 ±0.01 %，再加被填内腔的体积"，面数 = 155 − 内腔面数。"""
    bad = []
    for k in ("cortical", "cancellous"):
        e = dict(EXPECT[k])
        m = bodies[k]["mirrored"]
        if abs(m["mm3"] - e["mm3"]) > VOL_TOL * e["mm3"]:
            bad.append(f"{k} raw volume {m['mm3']:.1f} vs {e['mm3']:.0f} (tol ±{VOL_TOL * 100:.2f} %)")
        if "bore_filled" in m:
            b = m["bore_filled"]
            e["mm3"] = m["mm3_filled"]
            e["faces"] = m["faces_filled"]                               # 填孔后面数由 OCC 决定（原 155 + 圆柱两端面 ± 残留环面），只要求重导入一致
            if not (300.0 < b["bore_volume_mm3"] < 1200.0):            # Ø2.8 × 97 mm ≈ 600 mm³
                bad.append(f"{k} bore volume {b['bore_volume_mm3']:.0f} mm3 outside 300..1200")
        if "refilled" in m:                                              # v2：净增 = 两个盲窝的体积；填充体止于皮质内面
            r = m["refilled"]
            e["mm3"] = m["mm3_refilled"]
            e["faces"] = m["faces_refilled"]
            if not (REFILL_RANGE_MM3[0] < r["volume_added_mm3"] < REFILL_RANGE_MM3[1]):
                bad.append(f"{k} refill added {r['volume_added_mm3']:.1f} mm3 outside {REFILL_RANGE_MM3}")
            if r["n_filler_pieces_kept"] != 1:
                bad.append(f"{k} refill kept {r['n_filler_pieces_kept']} filler pieces")
        if abs(v[k]["mm3"] - e["mm3"]) > VOL_TOL * e["mm3"]:
            bad.append(f"{k} volume {v[k]['mm3']:.1f} vs {e['mm3']:.1f} (tol ±{VOL_TOL * 100:.2f} %)")
        if v[k]["faces"] != e["faces"]:
            bad.append(f"{k} faces {v[k]['faces']} vs {e['faces']}")
    f = v["fragment"]
    if abs(f["cortex_mm3_after"] - v["cortical"]["mm3"]) > 2.0:          # 填孔圆柱不得伸进皮质（fragment 后皮质体积不变）
        bad.append(f"cortex volume changed by fragment: {f['cortex_mm3_after']:.1f} vs {v['cortical']['mm3']:.1f}")
        if v[k]["bbox"][5] < 100 or v[k]["bbox"][2] > -100 and k == "cortical":
            bad.append(f"{k} z range {v[k]['bbox'][2]:.1f}..{v[k]['bbox'][5]:.1f}: head should be at +z (proximal) after mirroring")
    f = v["fragment"]
    if f["cortex_vols"] != 1 or f["core_vols"] != 1:
        bad.append(f"fragment gives {f['cortex_vols']} cortex / {f['core_vols']} core volumes")
    if f["shared_faces"] < EXPECT["shared_faces"]:                       # 填孔的补片贴在皮质内表面上，可能把共享面多分出 1–2 个
        bad.append(f"shared faces {f['shared_faces']} < {EXPECT['shared_faces']}")
    return bad


def _prov_v2_section(rep: dict, paths: dict) -> str:
    m = rep["bodies"]["cancellous"]["mirrored"]
    b, r, v = m["bore_filled"], m["refilled"], rep["verify"]
    kept = next((x for x in r["filler_pieces"] if x["kept"]), {"mass_mm3": float("nan")})
    return f"""{PROV_V2_MARK}（烘焙于 {rep['date']}，gmsh {rep['gmsh']}；`bake_3406.py --refill`）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
| `{paths['cancellous'].name}` | `{rep['bodies']['cancellous']['source']}` | `{rep['bodies']['cancellous']['source_sha256']}` | `{rep['output_sha256']['cancellous']}` |
| `{paths['cortical'].name}`（不变，未重烘焙） | 同 v1 | 同 v1 | `{rep['output_sha256']['cortical']}` |

- 为什么：v1 的填孔圆柱两端各退 {b['cylinder']['inset_mm']:g} mm，在皮质内表面下留下两个盲窝，窝沿面与皮质内面以极小角度相交。
  S6（2026-10-23，`integration_2026-10-23/s6/s6_report.md` §4）发现 `model3d_v2.build_intact` 的 fragment(皮质, 松质) 在**头端孔口**
  （模型坐标约 (73.0, 0.4, 57.9)）碎片化出三个 0.01 mm 级顶点和三条 0.01 mm 级修剪曲线，皮质里生成 3 个 1.9e-9 mm³ 的退化四面体，
  被 `SLIVER_REL_TOL = 1e-7` 的门槛拒绝（L3）；换 HXT / 改 h 都在同一处失败，`occ.healShapes` 会把皮质壳撕成两个体。
  同一批设计建模里 6（皮质）/ 12（松质）个 1e-4 级薄片也来自孔口残留的 ≤ 0.05 mm² 碎面。
- 配方（`ream_refill()`，与 S6 的 `s6_fill_test.py` 相同）：在 v1 填孔之后，取同轴圆柱 T：半径 {r['cylinder']['radius_mm']:.3f} mm
  （= 填孔圆柱 {b['cylinder']['radius_mm']:.3f} + {r['ream_mm']:g}，即孔半径 {b['bore_radius_mm']:.2f} + {0.2 + r['ream_mm']:.1f}），
  两端各伸出孔口 {r['ext_mm']:g} mm（长 {r['cylinder']['length_mm']:.1f} mm）；**芯 := (芯 − T) ∪ (T − 皮质实体)**。
  芯 − T 把填孔圆柱、两个盲窝和原件孔口的斜环面残片一起挖掉；T − 皮质实体落在骨内的那一块（{kept['mass_mm3']:.1f} mm³，
  共 {len(r['filler_pieces'])} 块中保留 {r['n_filler_pieces_kept']} 块）两端恰好是皮质内表面的一部分：无盲窝、不与皮质重叠。
- 数字：松质体积 v1 {r['volume_before_mm3']:.1f} → 扩孔后 {r['volume_reamed_mm3']:.1f} → 再填后 {r['volume_after_mm3']:.1f} mm³
  （净增 **{r['volume_added_mm3']:+.1f} mm³** = 两个盲窝；原件 {m['mm3']:.1f}，v1 填孔 {b['bore_volume_mm3']:+.0f}）；
  面数 {r['faces_before']} → {r['faces_after']}；≤ 0.05 mm² 碎面 {len(r['small_faces_lt_0.05mm2_before'])} → {len(r['small_faces_lt_0.05mm2_after'])}
  （剩下的在 {[x['centre_baked'] for x in r['small_faces_lt_0.05mm2_after']]}，烘焙坐标）。
  重导入验收：松质 {v['cancellous']['mm3']:.1f} mm³ / {v['cancellous']['faces']} 面；fragment(皮质, 松质) → {v['fragment']['cortex_vols']} + {v['fragment']['core_vols']} 个体，
  共享面 {v['fragment']['shared_faces']}（v1 147），皮质体积 {v['fragment']['cortex_mm3_after']:.1f}（重导入 {v['cortical']['mm3']:.1f}，即填充体没有伸进皮质）。
- 皮质 STEP 不变（SHA256 与 v1 相同，本次只核对，不重写）。校验和在 `SHA256SUMS_v2.txt`；完整报告 `bake_report_v2.json`。
- **默认仍是 v1**：`femur_3406.py` 的 `SHA256["cancellous"]` 与 `load_cfg()` 的路径未改；切换步骤（改路径 + SHA、换 SHA256SUMS、删哪些缓存）
  见 `H:/projects/application/research-log/sawbone_3406_2026-10-23/integration_2026-10-23/s1_rebake/SWITCHOVER.md`。
"""


def _append_prov_v2(section: str) -> None:
    """把 v2 一节追加到 PROVENANCE.md 末尾；已有 v2 节（同一标记起）则整段替换，v1 部分一字不动。"""
    p = OUT / "PROVENANCE.md"
    txt = p.read_text(encoding="utf-8") if p.exists() else "# v2/data/femur_3406 来源与变换\n"
    i = txt.find(PROV_V2_MARK)
    if i >= 0:
        txt = txt[:i].rstrip("\n") + "\n"
    p.write_text(txt.rstrip("\n") + "\n\n" + section, encoding="utf-8")


def main_refill(a) -> int:
    """v2：只重做松质芯（源 → 镜像 → 填孔 → 扩孔再填），皮质用已烘焙的 v1 文件；只写 *_v2 文件 + PROVENANCE.md 追加一节。"""
    paths = {"cortical": OUT / FILES["cortical"][1], "cancellous": OUT / CANCELLOUS_V2}
    if not paths["cortical"].exists():
        print("--refill needs the baked cortical STEP; run the plain bake first:", paths["cortical"])
        return 1
    if paths["cancellous"].exists() and not a.force:
        print("v2 core exists; use --force to re-bake:", paths["cancellous"])
        return 0
    rep = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "gmsh": None, "recipe": "v2 ream-and-refill (bake_3406.py --refill)", "source_dir": str(a.src),
           "transform": "diag(1, 1, -1) (z -> -z only)", "ream_mm": REAM_MM, "ext_mm": EXT_MM, "bodies": {}}
    import gmsh
    rep["gmsh"] = gmsh.__version__
    prior_p = OUT / "bake_report.json"
    prior = json.loads(prior_p.read_text(encoding="utf-8")) if prior_p.exists() else None
    cort_sha = sha256(paths["cortical"])
    cort = dict(prior["bodies"]["cortical"]) if prior else {"source": str(a.src / FILES["cortical"][0]), "source_sha256": None, "native": None,
                                                              "mirrored": {"mm3": EXPECT["cortical"]["mm3"], "faces": EXPECT["cortical"]["faces"]}}
    cort.update(output=str(paths["cortical"]), note="unchanged: --refill does not re-bake the cortical shell", output_sha256_on_disk=cort_sha,
                sha256_matches_bake_report=(prior["output_sha256"]["cortical"] == cort_sha) if prior else None)
    rep["bodies"]["cortical"] = cort
    if prior and not cort["sha256_matches_bake_report"]:
        print("NOT ACCEPTED: cortical STEP on disk does not match bake_report.json", cort_sha)
        return 1
    src = a.src / FILES["cancellous"][0]
    rep["bodies"]["cancellous"] = {"source": str(src), "source_sha256": sha256(src),
                                   **bake_one(src, paths["cancellous"], fill_inner=True, refill_with=paths["cortical"]), "output": str(paths["cancellous"])}
    m = rep["bodies"]["cancellous"]["mirrored"]
    print("cancellous", json.dumps({"mm3": m["mm3"], "mm3_filled": m.get("mm3_filled"), "mm3_refilled": m.get("mm3_refilled"),
                                    "faces": m["faces"], "faces_filled": m.get("faces_filled"), "faces_refilled": m.get("faces_refilled"),
                                    "refill_added_mm3": m.get("refilled", {}).get("volume_added_mm3")}, default=float))
    rep["verify"] = verify(paths)
    rep["accept_errors"] = accept(rep["verify"], rep["bodies"])
    rep["output_sha256"] = {k: sha256(p) for k, p in paths.items()}
    (OUT / "bake_report_v2.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(json.dumps(rep["verify"], indent=1, default=float))
    if rep["accept_errors"]:
        print("NOT ACCEPTED:", *rep["accept_errors"], sep="\n  ")
        return 1
    (OUT / "SHA256SUMS_v2.txt").write_text("".join(f"{rep['output_sha256'][k]} *{paths[k].name}\n" for k in ("cortical", "cancellous"))
                                           + f"source: {a.src} (Churun uncut 3406, SolidWorks 2025 AP214 export 2026-10-23); transform diag(1,1,-1); "
                                           f"cancellous v2 = bore filled + ream-and-refill (r + {REAM_MM} mm, ends +{EXT_MM:g} mm, filler = cylinder - cortical solid)\n",
                                           encoding="utf-8")
    _append_prov_v2(_prov_v2_section(rep, paths))
    print("ACCEPTED (v2) ->", paths["cancellous"])
    for k, p in paths.items():
        print(f"  sha256_{k}: {rep['output_sha256'][k]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=pathlib.Path, default=SRC_DEFAULT)
    ap.add_argument("--force", action="store_true", help="overwrite existing baked files")
    ap.add_argument("--refill", action="store_true", help="v2 recipe (ream-and-refill the bore against the cortical solid); writes only *_v2 files")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if a.refill:
        return main_refill(a)
    paths = {k: OUT / dst for k, (_, dst) in FILES.items()}
    if all(p.exists() for p in paths.values()) and not a.force:
        print("baked files exist; use --force to re-bake:", *paths.values(), sep="\n  ")
        return 0
    rep = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "gmsh": None, "source_dir": str(a.src), "transform": "diag(1, 1, -1) (z -> -z only)",
           "bodies": {}}
    import gmsh
    rep["gmsh"] = gmsh.__version__
    for k, (s, _) in FILES.items():
        src = a.src / s
        rep["bodies"][k] = {"source": str(src), "source_sha256": sha256(src), **bake_one(src, paths[k], fill_inner=(k == "cancellous")),
                            "output": str(paths[k])}
        print(k, json.dumps({kk: vv for kk, vv in rep["bodies"][k].items() if kk in ("native", "mirrored")}, default=float))
    rep["verify"] = verify(paths)
    rep["accept_errors"] = accept(rep["verify"], rep["bodies"])
    rep["output_sha256"] = {k: sha256(p) for k, p in paths.items()}
    (OUT / "bake_report.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print(json.dumps(rep["verify"], indent=1, default=float))
    if rep["accept_errors"]:
        print("NOT ACCEPTED:", *rep["accept_errors"], sep="\n  ")
        return 1
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{rep['output_sha256'][k]} *{paths[k].name}\n" for k in FILES)
                                        + f"source: {a.src} (Churun uncut 3406, SolidWorks 2025 AP214 export 2026-10-23); transform diag(1,1,-1)\n",
                                        encoding="utf-8")
    prov = f"""# v2/data/femur_3406 来源与变换（烘焙于 {rep['date']}，gmsh {rep['gmsh']}）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
""" + "".join(f"| `{paths[k].name}` | `{rep['bodies'][k]['source']}` | `{rep['bodies'][k]['source_sha256']}` | `{rep['output_sha256'][k]}` |\n" for k in FILES) + f"""
- 来源：Churun Lin 的未切割 Sawbones 3406（左股骨）Parasolid → 本机 SolidWorks 2025 转 STEP AP214（2026-10-23，见
  `H:/projects/application/research-log/sawbone_3406_2026-10-23/README_3406模型来源与核对_2026-10-23.md` 与 `churun_uncut_export/convert_log.txt`）。
- 变换：**只把 z 取反**，S = diag(1, 1, −1)，用 `gmsh.model.occ.affineTransform`；原生系 x 内侧、y 后方、z 远端（左股骨）
  ⇒ 烘焙后 x 内侧、y 后方、z 近端，并且左→右镜像。
- 为什么不用 README 的 A 系（x, −y, −z）：A 系是绕 x 转 180°，保持左股骨手性、+y 变成前方。计入哈希的代码假定
  右股骨且 +y 后方：`femur_real.landmarks` 取 argmax(y) 为后髁、前倾角符号 = −(u·ey)、`RealFemur.ant = (0, −1, 0)`，
  `model3d_v2.load_vector` 的 Bergmann → 模型符号也写死了 +y 后方（model3d_m1 按名导入同一函数）。A 系会让髁检测和载荷符号都错。
- 验收（重新导入）：皮质 {rep['verify']['cortical']['mm3']:.1f} mm³ / {rep['verify']['cortical']['faces']} 面，
  松质 {rep['verify']['cancellous']['mm3']:.1f} mm³ / {rep['verify']['cancellous']['faces']} 面；
  fragment(皮质, 松质) → 共享面 {rep['verify']['fragment']['shared_faces']} 个（松质 {rep['verify']['fragment']['core_faces']} 面中），
  体积不变（{rep['verify']['fragment']['cortex_mm3_after']:.1f} / {rep['verify']['fragment']['core_mm3_after']:.1f} mm³）。
  目标：271 529 / 127 952 mm³（±0.01 %）、869 / 155 面、147 个共享面。
- 原生体积：皮质 {rep['bodies']['cortical']['native']['mm3']:.1f}，松质 {rep['bodies']['cancellous']['native']['mm3']:.1f} mm³
  （gmsh 对裁剪 B 样条体积偏低约 4 %，与 SolidWorks 的 271.5 / 127.9 cm³ 一致）。
- 皮质壳是**开放**的（远端横销孔连通髓腔），无封闭的内膜空腔；松质芯（含头、颈）与皮质在同一坐标系，界面共形。
- **松质芯原件里有一条导针孔**（2026-10-23 发现）：半径 ≈ {rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bore_radius_mm', float('nan')):.2f} mm、
  长 {rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bore_length_mm', float('nan')):.1f} mm 的贯通孔，沿颈部从外侧皮质界面穿到头部芯表面
  （烘焙坐标 bbox {np.round(rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bbox_min', []), 1).tolist()} …
  {np.round(rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bbox_max', []), 1).tolist()}，轴向
  {np.round(rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('axis_dir', []), 3).tolist()} ⇒ 颈干角 ≈ 120°、前倾 ≈ 0°、离头心约 2 mm），
  由两张 97 × 4.4 mm 的条带面和两端的环面组成（gmsh 面号 {rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bore_faces')}）。
  泡沫芯没有这种孔：留着它，距离场在颈部多一道"墙"（模板化判穿透）、网格在柄旁留薄片。烘焙时在孔内并入一根圆柱
  （半径 {rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('cylinder', {}).get('radius_mm', float('nan')):.2f} mm，两端各退 0.3 mm 不伸进皮质）：
  松质体积 {rep['bodies']['cancellous']['mirrored']['mm3']:.1f} → {rep['bodies']['cancellous']['mirrored'].get('mm3_filled', float('nan')):.1f} mm³
  （孔体积 {rep['bodies']['cancellous']['mirrored'].get('bore_filled', {}).get('bore_volume_mm3', float('nan')):.0f} mm³），
  面数 155 → {rep['bodies']['cancellous']['mirrored'].get('faces_filled')}；两端在皮质内表面下各留一个 ≤ 3 mm 深的盲窝（开口是斜的）。原件未动（research-log 里）。
- 数据不进 git（`.gitignore: v2/data/**/*.STEP`）；校验和在 `SHA256SUMS.txt`，`femur_3406.py` 的配置里也写死同样的 SHA256。
- 完整报告：`bake_report.json`。
"""
    (OUT / "PROVENANCE.md").write_text(prov, encoding="utf-8")
    print("ACCEPTED ->", OUT)
    for k, p in paths.items():
        print(f"  sha256_{k}: {rep['output_sha256'][k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
