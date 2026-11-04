"""阶段 9 启动前的空跑（Linux，不提交作业）：
1. 规格：阶段 9 的 spec_of 带 collar_rule = neck_in_shoulder、无领、新口径；
2. 可行率：600 个随机设计在新选号下的可行率与号的范围；
3. 建模核对：取 1 个可行设计在临时目录里按 jobs.prep 的流程建 M1 模型（不求解），数截骨面上法向朝骨的界面节点（应为 0），
   并对照同一设计按现行选号建模时的数目。"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import collar_rule as CR  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import model3d_m1 as M1  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402


def bearing_nodes(outdir, fm):
    m = np.load(outdir / "mesh3d.npz")
    lut = {int(n): i for i, n in enumerate(m["node_labels"])}
    P = np.array([m["nodes"][lut[int(n)]] for n in m["pair_bone"]])
    on = (np.abs((P - fm.C03) @ fm.u3) <= 0.05) & (np.abs(m["pair_normal"] @ fm.u3) > 0.9 * np.linalg.norm(m["pair_normal"], axis=1))
    return int(on.sum()), float(m["pair_area"][on].sum())


if __name__ == "__main__":
    ph = N.Phase(9, None, "abs")
    sp = ph.spec_of(np.full(len(ph.vars), 0.5), "dry")
    print("spec keys:", {k: sp[k] for k in ("stage", "collar_rule", "model", "h_cut", "delta", "slip_tol", "min_A0") if k in sp},
          "| collar in design:", "collar_w" in sp["design"], "| metric", ph.metric, "| rule", ph.rule)
    fm0 = FR.build()
    rng = np.random.default_rng(11)
    ok, A, pick = 0, [], None
    U = rng.random((600, len(ph.vars)))
    for u in U:
        d, h = ph.design_of(u)
        fm = fm0.with_cut(h)
        r = ph.template(G.Stem3D(**d), fm)
        if r["fit"] and r["A0"] >= S.MIN_A0:
            ok += 1; A.append(r["A0"])
            if pick is None and r["A0"] < 300:
                pick = (u, d, h, r)
    print(f"neck_in_shoulder feasible {ok}/600 ({100 * ok / 600:.0f} %); A0 {min(A):.0f}–{max(A):.0f} mm², median {np.median(A):.0f}")
    u, d, h, r = pick
    fm = fm0.with_cut(h); st = G.Stem3D(**d)
    print("dry-build design:", {k: round(v, 2) for k, v in d.items() if k in ("L", "alpha", "m", "q", "lam", "rho_tip")}, "h", round(h, 1),
          "new A0 %.0f e %+.0f overhang %.1f" % (r["A0"], r["e"], r["neck_overhang_mm2"]))
    r_old = CR._ORIG["template"](st, fm)
    print("same design, current rule: A0 %.0f e %+.0f overhang %.1f" % (r_old["A0"], r_old["e"], CR.neck_overhang(st, fm, r_old["A0"], r_old["pose"])))
    for tag, pl in (("neck_in_shoulder", r), ("current", r_old)):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            M1.build(st, fm, pl, out, "m", h_int=S.H_PROD, delta=0.025, slip_tol=2.5e-4)
            n, a = bearing_nodes(out, fm)
            print(f"  M1 build ({tag}): interface nodes on the cut plane facing the bone = {n} (lumped area {a:.1f} mm²)")
