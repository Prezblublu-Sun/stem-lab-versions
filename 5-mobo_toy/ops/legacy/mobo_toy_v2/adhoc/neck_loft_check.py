"""过渡颈（neck_shape = "loft"）的空跑核对（Linux，不提交作业、不求解）：
1. 预览里的 5 个无领设计 + 阶段 9 设计空间随机 6 个：按建模流程建柄（柄体 ∩ 截骨面以下 + 过渡颈 + 头），导出表面 STL；
2. 每个设计在临时目录里完整跑一次 M1.build（划网格、写 .inp），记录是否成功、四面体数、截骨面上朝骨的界面节点（应为 0）；
   同一设计用原来的圆柱颈再建一次作对照。
输出 ~/mobo_toy_v2/deck/preview9b/{check.json, <name>_loft.stl}"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import collar_rule as CR  # noqa: E402
import fe3d_geom as E  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

OUT = HOME / "deck" / "preview9b"


def bearing_nodes(outdir, fm):
    m = np.load(outdir / "mesh3d.npz")
    lut = {int(n): i for i, n in enumerate(m["node_labels"])}
    P = np.array([m["nodes"][lut[int(n)]] for n in m["pair_bone"]])
    nn = m["pair_normal"] / np.linalg.norm(m["pair_normal"], axis=1, keepdims=True)
    on = (np.abs((P - fm.C03) @ fm.u3) <= 0.05) & (np.abs(nn @ fm.u3) > 0.9)
    return int(on.sum()), float(m["pair_area"][on].sum()), int(len(P))


def stem_stl(st, fm, pl, path):
    import gmsh
    pr = fm.cfg["prosthesis"]
    gmsh.initialize(); gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("p"); occ = gmsh.model.occ
        body = E.stem_solid(occ, st, pl["A0"], pl["pose"], delta=0.0, m=40)
        body_in, _ = occ.intersect(body, E.kept_halfspace(occ, fm))
        a = fm.C03; Lneck = float(np.linalg.norm(fm.H - a))
        neck = occ.addCylinder(*a, *(Lneck * fm.u3), pr["neck_radius_mm"])          # 已装 neck_loft：这里建的是过渡体
        head = occ.addSphere(*fm.H, pr["head_radius_mm"])
        occ.fuse(body_in, [(3, neck), (3, head)])
        occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", 1.0); gmsh.option.setNumber("Mesh.MeshSizeMin", 0.3)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()


def m1_check(st, fm, pl):
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td)
        t0 = time.perf_counter()
        info = M1.build(st, fm, pl, out, "m", h_int=S.H_PROD, delta=0.025, slip_tol=2.5e-4)
        n, a, ntot = bearing_nodes(out, fm)
        return {"ok": True, "n_tet": info.get("n_tet"), "bearing_nodes": n, "bearing_area_mm2": a, "pairs": ntot, "build_s": time.perf_counter() - t0}


if __name__ == "__main__":
    import neck_loft as NL
    OUT.mkdir(parents=True, exist_ok=True)
    prev = json.loads((HOME / "deck" / "preview9" / "preview.json").read_text())
    designs = {k: (v["design"], v["h_cut"]) for k, v in prev.items()}
    ph = N.Phase(9, None, "abs")
    rng = np.random.default_rng(23)
    k = 0
    while k < 6:
        d, h = ph.design_of(rng.random(len(ph.vars)))
        if G.template(G.Stem3D(**d), FR.build().with_cut(h))["fit"]:
            designs[f"R{k + 1}"] = (d, h); k += 1
    fm0 = FR.build()
    rep = {}
    # 先用原圆柱颈建 M1 作对照（尚未装过渡颈）
    for name, (d, h) in designs.items():
        fm = fm0.with_cut(h); st = G.Stem3D(**d); pl = G.template(st, fm)
        try:
            rep[name] = {"design": d, "h_cut": h, "A0": pl["A0"], "e": pl["e"], "overhang_mm2": CR.neck_overhang(st, fm, pl["A0"], pl["pose"]),
                         "cylinder": m1_check(st, fm, pl)}
        except Exception as e:                                          # noqa: BLE001
            rep[name] = {"design": d, "h_cut": h, "cylinder": {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}}
    NL.install(r_head=float(fm0.cfg["prosthesis"]["head_radius_mm"]))
    for name, (d, h) in designs.items():
        fm = fm0.with_cut(h); st = G.Stem3D(**d); pl = G.template(st, fm)
        try:
            stem_stl(st, fm, pl, OUT / f"{name}_loft.stl")
            rep[name]["loft"] = m1_check(st, fm, pl)
        except Exception as e:                                          # noqa: BLE001
            rep[name]["loft"] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
        c, l = rep[name]["cylinder"], rep[name]["loft"]
        print(f"{name:24s} A0 {rep[name].get('A0', 0):5.0f} e {rep[name].get('e', 0):+.0f} overhang {rep[name].get('overhang_mm2', 0):5.1f} | "
              f"cylinder: {'ok' if c.get('ok') else 'FAIL'} bearing {c.get('bearing_nodes', '-')} ({c.get('bearing_area_mm2', 0):.1f} mm²) | "
              f"loft: {'ok' if l.get('ok') else 'FAIL ' + l.get('error', '')[:120]} bearing {l.get('bearing_nodes', '-')} ({l.get('bearing_area_mm2', 0):.1f} mm²) "
              f"tets {l.get('n_tet')} build {l.get('build_s', 0):.0f} s", flush=True)
    (OUT / "check.json").write_text(json.dumps(rep, indent=1, default=float))
