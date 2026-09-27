"""探索：弯柄沿直线插入（平移）时的扫掠腔与过切 —— 给用户看案例用，不进正式流水线。

直线平移扫掠的精确做法：多边形 P 沿线段 v 平移扫过的区域 = P ∪ (P + v) ∪ 各条边沿 v 扫出的平行四边形。
过切 = 扫掠腔 ∩ 截骨线以下的骨 − 最终柄体；最大间隙 = 过切区到柄体表面的最大距离。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import femur2d as F  # noqa: E402
import plotstyle as ps  # noqa: E402
import stem2d as S  # noqa: E402
from scipy.stats import qmc  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


def sweep_translate(poly: Polygon, v: np.ndarray) -> Polygon:
    """poly 沿向量 v 平移扫过的区域（精确）。"""
    c = np.asarray(poly.exterior.coords)
    parts = [poly, shapely.affinity.translate(poly, *v)]
    for a, b in zip(c[:-1], c[1:]):
        q = Polygon([a, b, b + v, a + v])
        if q.area > 1e-12:
            parts.append(q)
    return unary_union(parts).buffer(0)


def straight_insertion(st: S.Stem2D, direction: np.ndarray) -> dict:
    """沿单位向量 direction 插入（柄从截骨线外沿 direction 前进到最终位置）。"""
    f = st.femur
    body = st.body()
    kept = f.outer.intersection(f.kept_halfplane())
    travel = st.L + 40.0
    swept = sweep_translate(body, -travel * direction)          # 最终位置向后退的整条路径
    cav = swept.intersection(kept)
    final = body.intersection(kept)
    over = cav.difference(final)
    over = shapely.make_valid(over)
    gap = 0.0
    if not over.is_empty:
        pts = []
        for g in getattr(over, "geoms", [over]):
            if g.geom_type == "Polygon" and g.area > 1e-3:
                pts += list(g.exterior.coords)
        if pts:
            gap = max(final.exterior.distance(Point(p)) for p in pts)
    return {"cavity": cav, "final": final, "overcut": over, "overcut_area": over.area,
            "gap_max": gap, "cortex_cut": cav.intersection(f.cortex).area, "direction": direction}


def best_direction(st: S.Stem2D, n: int = 61) -> tuple[np.ndarray, float, list]:
    """在弦方向 ±30° 内搜索使过切面积最小的插入方向。"""
    p, t, _ = st.axis(np.array([0.0, st.L]))
    chord = p[1] - p[0]
    a0 = math.atan2(chord[1], chord[0])
    scan = []
    for da in np.linspace(-30, 30, n):
        a = a0 + math.radians(da)
        d = np.array([math.cos(a), math.sin(a)])
        r = straight_insertion(st, d)
        scan.append((da, r["overcut_area"], r["cortex_cut"]))
    da_best = min(scan, key=lambda x: x[1] + 10 * x[2])[0]
    a = a0 + math.radians(da_best)
    return np.array([math.cos(a), math.sin(a)]), da_best, scan


def chord_dir(st):
    p, _, _ = st.axis(np.array([0.0, st.L]))
    c = p[1] - p[0]
    return c / np.linalg.norm(c)


def pick_designs(dorr: str, kappas=(0.009, 0.014, 0.019)):
    U = qmc.Sobol(5, scramble=True, seed=99).random(4096)
    cands = []
    for u in U:
        st = S.make(dorr, S.to_physical(u))
        if S.gate(st)["pass"]:
            cands.append((st.kappa, u))
    out = []
    for k in kappas:
        kk, u = min(cands, key=lambda c: abs(c[0] - k))
        out.append(u)
    return out


# ------------------------------------------------------------------ 作图
def draw_case(ax, st, mode, res=None, title=""):
    from matplotlib.patches import Polygon as MP, FancyArrowPatch
    f = st.femur
    for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
        ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
    seg = f.cut_segment()
    ax.plot(*np.asarray(seg.coords).T, color="#D55E00", lw=1.0)
    body = st.body()
    if mode == "arc":
        c = st.center
        for k, tau in enumerate(np.linspace(0, st.L * 0.9, 6)[1:]):
            g = shapely.affinity.rotate(body, -tau * st.kappa, origin=tuple(c), use_radians=True)
            ax.plot(*np.asarray(g.exterior.coords).T, color=ps.GREY, lw=0.4)
        ax.plot(c[0], c[1], "k+", ms=5)
        fin = body.intersection(f.outer).intersection(f.kept_halfplane())
        ax.add_patch(MP(np.asarray(fin.exterior.coords), closed=True, fc=ps.DORR[f.dorr], ec=ps.DORR[f.dorr], alpha=0.75))
        txt = "rotation about arc centre\novercut 0 mm²"
    else:
        d = res["direction"]
        for tau in np.linspace(0, st.L * 0.9, 6)[1:]:
            g = shapely.affinity.translate(body, *(-tau * d))
            ax.plot(*np.asarray(g.exterior.coords).T, color=ps.GREY, lw=0.4)
        for g in getattr(res["cavity"], "geoms", [res["cavity"]]):
            if g.geom_type == "Polygon":
                ax.plot(*np.asarray(g.exterior.coords).T, color="black", lw=0.7, ls="--")
        for g in getattr(res["overcut"], "geoms", [res["overcut"]]):
            if g.geom_type == "Polygon" and g.area > 1e-3:
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc="#E69F00", ec="#E69F00", alpha=0.8, hatch="////"))
        fin = res["final"]
        for g in getattr(fin, "geoms", [fin]):
            if g.geom_type == "Polygon":
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=ps.DORR[f.dorr], ec=ps.DORR[f.dorr], alpha=0.75))
        p0 = st.C0 - 35 * d
        ax.add_patch(FancyArrowPatch(tuple(p0), tuple(p0 + 25 * d), arrowstyle="-|>", mutation_scale=9, color="black", lw=1.0))
        txt = (f"straight insertion\novercut {res['overcut_area']:.0f} mm², max gap {res['gap_max']:.1f} mm"
               + (f"\ncuts cortex {res['cortex_cut']:.1f} mm²" if res["cortex_cut"] > 0.5 else ""))
    ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=6, va="bottom",
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=1.5))
    ax.set_xlim(-40, 70); ax.set_ylim(-80, 95); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(title, fontsize=7)


def main():
    import matplotlib.pyplot as plt
    summary = []
    # 图 1：Dorr B，三种曲率 × 三种插入方式
    us = pick_designs("B")
    fig, axes = ps.new_figure("double", 190, 3, 3)
    for r, u in enumerate(us):
        st = S.make("B", S.to_physical(u))
        rc = straight_insertion(st, chord_dir(st))
        db, da, scan = best_direction(st)
        rb = straight_insertion(st, db)
        R = 1 / st.kappa
        draw_case(axes[r, 0], st, "arc", title=f"R = {R:.0f} mm, L = {st.L:.0f} mm: rotation (current)")
        draw_case(axes[r, 1], st, "line", rc, title="straight, along chord")
        draw_case(axes[r, 2], st, "line", rb, title=f"straight, best direction (chord {da:+.0f}°)")
        summary.append({"dorr": "B", "R_mm": R, "L_mm": st.L, "design": S.to_physical(u),
                        "chord": {"overcut_mm2": rc["overcut_area"], "gap_mm": rc["gap_max"], "cortex_mm2": rc["cortex_cut"]},
                        "best": {"offset_deg": da, "overcut_mm2": rb["overcut_area"], "gap_mm": rb["gap_max"], "cortex_mm2": rb["cortex_cut"]}})
    fig.savefig(OUT / "cases_B_three_curvatures.png", dpi=200)
    plt.close(fig)
    # 图 2：同一归一化设计在 A/B/C 中，最佳直线方向
    fig, axes = ps.new_figure("double", 75, 1, 3)
    u = us[1]
    for ax, t in zip(axes, "ABC"):
        st = S.make(t, S.to_physical(u))
        g = S.gate(st)
        db, da, _ = best_direction(st)
        rb = straight_insertion(st, db)
        draw_case(ax, st, "line", rb, title=f"Dorr {t}: best straight direction (chord {da:+.0f}°)"
                  + ("" if g["pass"] else f"\n[arc-gate: {g['reason']}]"))
        summary.append({"dorr": t, "same_u_as_B_middle": True, "R_mm": 1 / st.kappa, "L_mm": st.L,
                        "best": {"offset_deg": da, "overcut_mm2": rb["overcut_area"], "gap_mm": rb["gap_max"], "cortex_mm2": rb["cortex_cut"]}})
    fig.savefig(OUT / "cases_ABC_best_direction.png", dpi=200)
    plt.close(fig)
    (OUT / "cases_summary.json").write_text(json.dumps(summary, indent=1, default=float), encoding="utf-8")
    for s in summary:
        print(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.items() if k != "design"}, default=float))


if __name__ == "__main__":
    main()
