"""可打印模型导出（Linux，0 次 FE）：按建模流程用 gmsh OCC 重建实体，细划表面网格，写二进制 STL（另写 STEP）。
每个设计一个文件夹 <label>/：
    stem.stl                柄体 + 领 + 假体颈 + 头，一个实体
    femur_with_cavity.stl   截骨 + 锉腔后的股骨（皮质与松质融合成一个实体；截断面在小转子下 150 mm）
    stem.step / femur_with_cavity.step
公共文件：
    femur_intact.stl        完整股骨（未截骨，同样截断）
    femur_resected_h<h>.stl 只截骨、不锉腔（每种截骨深度一个）
融合失败时退回到皮质 / 松质分开的文件（名字带 _cortex / _cancellous）。
    ~/mobo_toy_v2/run.sh print_export.py --out print_models --intact <intact_job> label=job [label=job ...] [--size-stem 0.4 --size-bone 0.8]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import jobs as J  # noqa: E402

Z_FLOOR = None
CORTEX_ONLY = False
STEMS_ONLY = False
FORCE_MARKER = False


def mesh_and_write(gmsh, path_stl: pathlib.Path, path_step: pathlib.Path | None, size: float) -> dict:
    gmsh.model.occ.synchronize()
    vols = gmsh.model.getEntities(3)
    if path_step is not None:
        gmsh.write(str(path_step))
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", size / 4)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 36)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.Binary", 1)
    gmsh.option.setNumber("Mesh.StlOneSolidPerSurface", 0)
    gmsh.model.mesh.generate(2)
    gmsh.write(str(path_stl))
    n_tri = len(gmsh.model.mesh.getElementsByType(2)[0])
    return {"n_volumes": len(vols), "volume_mm3": float(sum(gmsh.model.occ.getMass(3, t) for _, t in vols)), "n_triangles": int(n_tri)}


def whole_bone(occ, fm, cut: bool):
    """皮质 ∪ 松质，截断在 z_trunc 以上；cut=True 时再截骨。返回实体列表（期望 1 个）。"""
    import fe3d_geom as E
    from model3d_v2 import _femur_shapes
    C, K = _femur_shapes(occ, fm)
    if CORTEX_ONLY:                                                        # 只留皮质壳（中空，松质去掉）
        occ.remove(K, recursive=True); W = C
    else:
        W, _ = occ.fuse(C, K, removeObject=True, removeTool=True)
    z0 = fm.z_trunc if Z_FLOOR is None else Z_FLOOR                         # 远端截断高度（模型坐标，小转子为 0）
    box = [(3, occ.addBox(-300, -300, z0, 600, 600, 600))]
    if cut:
        box, _ = occ.intersect(box, E.kept_halfspace(occ, fm), removeObject=True, removeTool=True)
    Wk, _ = occ.intersect(W, box, removeObject=True, removeTool=True)
    return [x for x in Wk if x[0] == 3]


def build_stem(occ, fm, st, pl, sec_pts):
    import fe3d_geom as E
    pr = fm.cfg["prosthesis"]
    A0, pose = pl["A0"], pl["pose"]
    body = E.stem_solid(occ, st, A0, pose, delta=0.0, m=sec_pts)
    body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
    cv = []
    if getattr(st, "has_collar", False):
        cv = E.collar_solid(occ, fm, E.collar_outline(st, fm, pl)["poly"], st.collar_t)
    neck = occ.addCylinder(*fm.C03, *(float(np.linalg.norm(fm.H - fm.C03)) * fm.u3), pr["neck_radius_mm"])
    head = occ.addSphere(*fm.H, pr["head_radius_mm"])
    extra = []
    if FORCE_MARKER:                                                       # 球头上的载荷方向标记：沿本作业载荷方向的锥形箭头，尖端指向头心
        from model3d_v2 import load_vector
        F = load_vector(fm.cfg); f = F / np.linalg.norm(F)
        r = float(pr["head_radius_mm"]); Lm, rb, sink = 6.0, 2.0, 0.5
        apex = np.asarray(fm.H) - (r - sink) * f                           # 尖端落在头面内 0.5 mm，保证融合
        base = apex - Lm * f
        extra.append((3, occ.addCone(*base, *(apex - base), rb, 0.0)))
    stem, _ = occ.fuse(body_in, [(3, neck), (3, head)] + cv + extra, removeObject=True, removeTool=True)
    return [x for x in stem if x[0] == 3]


def export_design(label: str, j: str, out: pathlib.Path, size_stem: float, size_bone: float) -> dict:
    import gmsh
    import geom3d as G
    import collar_rule as CR
    import fe3d_geom as E
    spec = json.loads((J.QROOT / j / "spec.json").read_text())
    fm = J.femur_for(spec)
    G.template, E.collar_outline = CR._ORIG["template"], CR._ORIG["collar_outline"]   # 先恢复现行规则：install* 会替换整个进程的函数，
    if spec.get("collar_rule") == "wrap_fit":                                          # 同一进程里混导不同规则的作业时会串（2026-10-08 发现）
        CR.install(min_A0=float(spec.get("min_A0", 0.0)))
    elif spec.get("collar_rule") == "neck_in_shoulder":                   # 无领（阶段 9）：与 jobs.prep 相同的选号
        CR.install_neck(min_A0=float(spec.get("min_A0", 0.0)))
    st = G.Stem3D(**spec["design"])
    pl = G.template(st, fm, margin=spec.get("margin"))
    prep = json.loads((J.QROOT / j / "prep.json").read_text())
    t0 = prep.get("templating") or {}
    if abs(float(t0.get("A0", pl["A0"])) - pl["A0"]) > 0.05 or abs(float(t0.get("e", pl["e"])) - pl["e"]) > 1e-6:
        raise ValueError(f"re-templated size differs from the solved job: A0 {pl['A0']:.2f} vs {t0.get('A0')}, e {pl['e']} vs {t0.get('e')}")
    sec_pts = int((prep.get("mesh_attempt") or {}).get("section_points", 40))
    d = out / label
    d.mkdir(parents=True, exist_ok=True)
    rep = {"job": j, "L": st.L, "A0": pl["A0"], "e": pl["e"], "collar_w": float(getattr(st, "collar_w", 0.0) or 0.0), "h_cut": fm.cut_from_head_mm}
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0); gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("stem"); occ = gmsh.model.occ
        stem = build_stem(occ, fm, st, pl, sec_pts)
        rep["stem"] = mesh_and_write(gmsh, d / "stem.stl", d / "stem.step", size_stem)
        gmsh.model.remove()
        if STEMS_ONLY:
            return rep
        gmsh.model.add("bone"); occ = gmsh.model.occ
        W = whole_bone(occ, fm, cut=True)
        stem = build_stem(occ, fm, st, pl, sec_pts)
        bone, _ = occ.cut(W, stem, removeObject=True, removeTool=True)
        rep["femur_with_cavity"] = mesh_and_write(gmsh, d / "femur_with_cavity.stl", d / "femur_with_cavity.step", size_bone)
        gmsh.model.remove()
    finally:
        gmsh.finalize()
    return rep


def export_common(intact_job: str, h_cuts: list[float], out: pathlib.Path, size_bone: float) -> dict:
    import gmsh
    spec = json.loads((J.QROOT / intact_job / "spec.json").read_text())
    fm = J.femur_for(spec)
    rep = {}
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0); gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.model.add("intact"); occ = gmsh.model.occ
        whole_bone(occ, fm, cut=False)
        rep["femur_intact"] = mesh_and_write(gmsh, out / "femur_intact.stl", out / "femur_intact.step", size_bone)
        gmsh.model.remove()
        for h in h_cuts:
            fmh = fm.with_cut(h)
            gmsh.model.add(f"cut{h}"); occ = gmsh.model.occ
            whole_bone(occ, fmh, cut=True)
            nm = f"femur_resected_h{h:g}"
            rep[nm] = mesh_and_write(gmsh, out / f"{nm}.stl", out / f"{nm}.step", size_bone)
            gmsh.model.remove()
    finally:
        gmsh.finalize()
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("items", nargs="+", help="label=job_id")
    ap.add_argument("--out", default="print_models")
    ap.add_argument("--intact", required=True)
    ap.add_argument("--size-stem", type=float, default=0.4)
    ap.add_argument("--size-bone", type=float, default=0.8)
    ap.add_argument("--skip-common", action="store_true")
    ap.add_argument("--z-floor", type=float, default=None, help="远端截断高度，模型坐标（小转子 = 0）；默认 z_trunc = −150")
    ap.add_argument("--cortex-only", action="store_true", help="骨只留皮质壳（中空）")
    ap.add_argument("--stems-only", action="store_true", help="只导出柄")
    ap.add_argument("--force-marker", action="store_true", help="球头上加载荷方向的锥形箭头（长 6 mm、底半径 2 mm，尖端指向头心）")
    a = ap.parse_args()
    Z_FLOOR = a.z_floor; CORTEX_ONLY = a.cortex_only; STEMS_ONLY = a.stems_only; FORCE_MARKER = a.force_marker
    out = HOME / "deck" / a.out
    out.mkdir(parents=True, exist_ok=True)
    rep_path = out / "export_report.json"
    rep = json.loads(rep_path.read_text()) if rep_path.exists() else {}
    t0 = time.time()
    hs = set()
    for it in a.items:
        label, j = it.split("=", 1)
        try:
            rep[label] = export_design(label, j, out, a.size_stem, a.size_bone)
            hs.add(round(rep[label]["h_cut"], 1))
        except Exception as e:                                              # noqa: BLE001
            rep[label] = {"job": j, "error": f"{type(e).__name__}: {e}"[:300]}
        print(label, json.dumps(rep[label], default=float)[:300], f"{time.time() - t0:.0f} s", flush=True)
        rep_path.write_text(json.dumps(rep, indent=1, default=float))
    if not a.skip_common:
        try:
            rep["common"] = export_common(a.intact, sorted(hs), out, a.size_bone)
        except Exception as e:                                              # noqa: BLE001
            rep["common"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        print("common", json.dumps(rep["common"], default=float)[:400], f"{time.time() - t0:.0f} s", flush=True)
        rep_path.write_text(json.dumps(rep, indent=1, default=float))
