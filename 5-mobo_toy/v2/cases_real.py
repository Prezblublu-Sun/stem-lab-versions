"""V2A 案例图（在 Linux 上跑）：真实股骨概览、示例柄模板化、随机设计的可行性扫描。

可行 = 模板化成功（最小号能进、尖端面积 ≥ 12 mm²）且肩部面积 A0 ≥ 假体颈截面（π·7² ≈ 154 mm²）：
肩部比假体颈还细时颈柄结合处无法成立，这类设计不进 FE。
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch
from matplotlib.patches import Polygon as MP
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import plotstyle as ps  # noqa: E402
from cases import EXAMPLES  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
MIN_A0 = math.pi * 7.0 ** 2                         # mm²，假体颈（半径 7 mm）截面积
CORT, CANC = np.array([0.79, 0.79, 0.79]), np.array([0.953, 0.890, 0.765])


def _off(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


def neck_plane_image(fm, ext=((-70.0, 55.0), (-205.0, 45.0)), h=0.3):
    C, e1, e2 = fm.neck_plane()
    a = np.arange(ext[0][0], ext[0][1], h); b = np.arange(ext[1][0], ext[1][1], h)
    A, B = np.meshgrid(a, b)
    P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
    cs, os_ = fm.canal_sdf(P), fm.outer_sdf(P)
    lab = np.where(cs <= 0, 2, np.where(os_ <= 0, 1, 0)).reshape(A.shape)
    kept = fm.below_cut(P).reshape(A.shape)
    return a, b, lab, kept


def _rgb(lab, kept):
    img = np.ones(lab.shape + (3,))
    img[lab == 1] = CORT; img[lab == 2] = CANC
    img[(lab > 0) & ~kept] = 0.55 * img[(lab > 0) & ~kept] + 0.45        # 截骨面以上（去除部分）淡显
    return img


def _plane_xy(fm, P):
    C, e1, e2 = fm.neck_plane()
    Q = np.atleast_2d(P) - C
    return np.c_[Q @ e1, Q @ e2]


def stem_silhouette(fm, st, pl):
    P0, d, e_ml, e_ap = pl["pose"]
    sec = G.unit_section(st.d, 160)
    s = np.r_[np.linspace(G.S_TOP, 0, 12, endpoint=False), np.linspace(0, st.L, 80)]
    k = np.sqrt(pl["A0"] * st.area_ratio(s))
    med, lat = k * sec[:, 0].max(), k * sec[:, 0].min()
    ring = np.r_[[P0 + si * d + mi * e_ml for si, mi in zip(s, med)], [P0 + (st.L + st.cap_length(pl["A0"])) * d],
                 [P0 + si * d + li * e_ml for si, li in zip(s[::-1], lat[::-1])]]
    from shapely.geometry import Polygon
    from shapely.geometry import Point
    poly = Polygon(_plane_xy(fm, ring)).buffer(0)
    # 只画截骨面以下：截骨线在颈平面上是过原点、沿 n3 的直线；保留侧为 (p − C0)·u ≤ 0
    C, e1, e2 = fm.neck_plane()
    u2 = np.array([fm.u3 @ e1, fm.u3 @ e2])
    big = 400.0
    n2 = np.array([-u2[1], u2[0]])
    half = Polygon([big * n2, -big * n2, -big * n2 - big * u2, big * n2 - big * u2])
    return poly.intersection(half)


def draw_neck_plane(ax, fm, img, st=None, pl=None, color=None, arrow=True):
    a, b, lab, kept = img
    ax.imshow(_rgb(lab, kept), origin="lower", extent=(a[0], a[-1], b[0], b[-1]), interpolation="nearest")
    C, e1, e2 = fm.neck_plane()
    n2 = np.array([fm.n3 @ e1, fm.n3 @ e2])
    ax.plot([-30 * n2[0], 30 * n2[0]], [-30 * n2[1], 30 * n2[1]], color="#D55E00", lw=0.8)
    if st is not None:
        poly = stem_silhouette(fm, st, pl)
        for g in getattr(poly, "geoms", [poly]):
            if g.geom_type == "Polygon":
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=color, ec=color, alpha=0.85))
        if arrow:
            P0, d = pl["pose"][0], pl["pose"][1]
            p = _plane_xy(fm, np.vstack([P0 - 45 * d, P0 - 20 * d]))
            ax.add_patch(FancyArrowPatch(tuple(p[0]), tuple(p[1]), arrowstyle="-|>", mutation_scale=7, color="black", lw=0.8))
        for fr in (0.15, 0.5, 0.85):
            P0, d, e_ml = pl["pose"][:3]
            c = P0 + fr * st.L * d
            q = _plane_xy(fm, np.vstack([c - 14 * e_ml, c + 14 * e_ml]))
            ax.plot(q[:, 0], q[:, 1], color="black", lw=0.4, ls="--")
    ax.set_xlim(a[0], a[-1]); ax.set_ylim(-120, b[-1]); ax.set_aspect("equal")
    _off(ax)


def draw_section(ax, fm, st, pl, frac, color, half=20.0):
    P0, d, e_ml, e_ap = pl["pose"]
    s = frac * st.L
    u, lab, kept = fm.labels_on_plane(P0 + s * d, e_ml, e_ap, half=half, h=0.15)
    ax.imshow(_rgb(lab, kept), origin="lower", extent=(u[0], u[-1], u[0], u[-1]), interpolation="nearest")
    sec = G.unit_section(st.d, 160) * math.sqrt(pl["A0"] * float(st.area_ratio(s)))
    ax.add_patch(MP(sec, closed=True, fc=color, ec=color, alpha=0.85, lw=0.5))
    ax.set_xlim(u[0], u[-1]); ax.set_ylim(u[0], u[-1]); ax.set_aspect("equal")
    _off(ax)
    ax.text(0.03, 0.03, f"s = {s:.0f} mm", transform=ax.transAxes, fontsize=5,
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.8))


# ------------------------------------------------------------------ 图 1：股骨概览
def fig_overview(fm, path):
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(ps.WIDTH_MM["double"] * ps.MM, 118 * ps.MM))
    gs = fig.add_gridspec(2, 5, width_ratios=[1.6, 1, 1, 1, 1])
    ax = fig.add_subplot(gs[:, 0])
    img = neck_plane_image(fm)
    draw_neck_plane(ax, fm, img)
    ax.set_ylim(-205, 45)
    Hc = _plane_xy(fm, fm.H)[0]
    ax.add_patch(Circle(Hc, fm.Rh, fill=False, ls="--", lw=0.6, color="#0072B2"))
    ax.plot(*Hc, "o", ms=2, color="#0072B2")
    q = _plane_xy(fm, np.vstack([fm.H + 10 * fm.u3, fm.H - 60 * fm.u3]))
    ax.plot(q[:, 0], q[:, 1], color="#0072B2", lw=0.7, label="neck axis")
    q = _plane_xy(fm, np.array([[0, 0, -200.0], [0, 0, 60.0]]))
    ax.plot(q[:, 0], q[:, 1], color="#009E73", lw=0.7, label="shaft axis")
    for z, lab_ in ((0.0, "LT"), (20.0, "LT+20"), (-100.0, "LT−100")):
        q = _plane_xy(fm, np.array([[-60, 0, z], [70, 0, z]]))
        ax.plot(q[:, 0], q[:, 1], color=ps.GREY, lw=0.4, ls=":")
        ax.text(q[0, 0] + 2, q[0, 1] + 1, lab_, fontsize=5, color=ps.GREY)
    ax.legend(fontsize=5, loc="lower right")
    lm = fm.lm
    ax.set_title(f"neck plane; head r {lm['head_r']:.1f} mm, neck–shaft {lm['neck_shaft_deg']:.1f}°,\n"
                 f"offset {lm['offset_mm']:.1f} mm, anteversion {lm['anteversion_deg']:.1f}°, "
                 f"cut {fm.cfg['femur']['cut_from_head_mm']:.0f} mm from head centre", fontsize=5.8)
    for i, z in enumerate((40.0, 20.0, 0.0, -40.0, -70.0, -100.0, -130.0, -150.0)):
        a2 = fig.add_subplot(gs[i // 4, 1 + i % 4])
        u, lab, kept = fm.labels_on_plane(np.array([10.0, 0.0, z]), np.array([1.0, 0, 0]), np.array([0, -1.0, 0]),
                                          half=35.0, h=0.2)
        a2.imshow(_rgb(lab, kept), origin="lower", extent=(u[0] + 10, u[-1] + 10, u[0], u[-1]), interpolation="nearest")
        a2.plot(0, 0, "+", color="#009E73", ms=4)
        a2.set_xlim(-25, 45); a2.set_ylim(-35, 35); a2.set_aspect("equal"); _off(a2)
        a2.set_title(f"z = {z:+.0f} mm (LT{z:+.0f})", fontsize=5.8)
    d = fm_summary_cache.get("dorr") or FR.dorr_indices(fm)
    fw, ch = d["full_width"], d["chord_y0"]
    fig.suptitle(f"Real femur (STEP, right): CFI {fw['CFI']:.2f} / CI {fw['CI']:.2f} by full canal width (AP-film convention) "
                 f"→ Dorr {fw['dorr_by_CI']}; chord through the shaft axis gives CFI {ch['CFI']:.2f}. Sections: medial → right, "
                 "anterior ↑, + = shaft axis", fontsize=6)
    fig.savefig(path, dpi=200)
    plt.close(fig)


fm_summary_cache: dict = {}


# ------------------------------------------------------------------ 图 2：示例柄
def fig_templated_real(fm, img, path, rows):
    import matplotlib.pyplot as plt
    fig, axes = ps.new_figure("double", 58 * len(rows), len(rows), 4)
    axes = np.atleast_2d(axes)
    rec = []
    col = ps.DORR["A"]
    for r, (name, d) in enumerate(rows):
        st = G.Stem3D(**d)
        pl = G.template(st, fm)
        if not pl["fit"]:
            for ax in axes[r]:
                _off(ax)
            axes[r, 0].text(0.5, 0.5, f"{name}: does not fit\n{pl['reason']}", transform=axes[r, 0].transAxes,
                            ha="center", fontsize=6)
            rec.append({"name": name, "fit": False, "reason": pl["reason"]})
            continue
        draw_neck_plane(axes[r, 0], fm, img, st, pl, col)
        ok = pl["A0"] >= MIN_A0
        axes[r, 0].text(0.02, 0.02, f"{name}\nα {st.alpha:.1f}°, offset {pl['e']:+.0f} mm\n"
                        f"shoulder {pl['A0']:.0f} mm²{'' if ok else ' (< neck 154: infeasible)'}\n"
                        f"tightest at s = {pl['s_bind']:.0f} mm, contact {pl['contact']:.1%}",
                        transform=axes[r, 0].transAxes, fontsize=4.8, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
        for c, fr in enumerate((0.15, 0.5, 0.85)):
            draw_section(axes[r, c + 1], fm, st, pl, fr, col)
        rec.append({"name": name, "fit": True, "feasible": bool(ok), **{k: pl[k] for k in ("e", "A0", "contact", "s_bind", "volume")},
                    "alpha": st.alpha})
    for c, lab_ in enumerate(("neck plane (dashed = section planes)", "section normal to axis, 0.15 L", "0.50 L", "0.85 L")):
        axes[0, c].set_title(lab_, fontsize=6)
    fig.suptitle("Example stems templated into the real femur: largest size with cortex penetration ≤ 0.25 mm; "
                 "sections: medial → right, anterior ↑", fontsize=6.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return rec


# ------------------------------------------------------------------ 图 3：可行性扫描
_FM = {}


def _work(job):
    i, u = job
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    st = G.Stem3D(**G.from_unit(u))
    r = G.template(st, _FM["fm"])
    row = {"i": i, **st.d, "fit": r["fit"], "reason": r.get("reason", "")}
    for k in ("e", "A0", "contact", "s_bind", "volume"):
        row[k] = r.get(k, math.nan)
    row["feasible"] = bool(r["fit"] and r["A0"] >= MIN_A0)
    if r["fit"] and not row["feasible"]:
        row["reason"] = "shoulder smaller than prosthetic neck"
    return row


def fig_feasibility(path, n=1024, seed=21):
    import matplotlib.pyplot as plt
    U = qmc.Sobol(len(G.VARS), scramble=True, seed=seed).random(n)
    with Pool(10) as pool:
        rows = pool.map(_work, list(enumerate(U)), chunksize=8)
    with open(OUT / "real_feasibility.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    ok = np.array([r["feasible"] for r in rows])
    a = np.array([r["alpha"] for r in rows]); L = np.array([r["L"] for r in rows])
    A0 = np.array([r["A0"] for r in rows])
    fig, axes = ps.new_figure("double", 62, 1, 4)
    ab = np.arange(G.ALPHA_LO, G.ALPHA_HI + 0.1, 5.0)
    rate_a = [float(ok[(a >= lo) & (a < hi)].mean()) for lo, hi in zip(ab[:-1], ab[1:])]
    axes[0].step(ab, np.r_[rate_a, rate_a[-1]], where="post", color=ps.DORR["A"])
    axes[0].set_xlabel("insertion angle α (°)"); axes[0].set_ylabel("fraction feasible"); axes[0].set_ylim(0, 1.05)
    lb = np.arange(40.0, 90.1, 10.0)
    rate_L = [float(ok[(L >= lo) & (L < hi)].mean()) for lo, hi in zip(lb[:-1], lb[1:])]
    axes[1].step(lb, np.r_[rate_L, rate_L[-1]], where="post", color=ps.DORR["A"])
    axes[1].set_xlabel("length L (mm)"); axes[1].set_ylabel("fraction feasible"); axes[1].set_ylim(0, 1.05)
    fitm = np.array([r["fit"] for r in rows])
    axes[2].hist(A0[fitm], bins=np.arange(0, 600, 20), color="#BBBBBB", label="templated (all)")
    axes[2].hist(A0[ok], bins=np.arange(0, 600, 20), color=ps.DORR["A"], label="feasible")
    axes[2].axvline(MIN_A0, color="black", lw=0.6, ls="--")
    axes[2].set_xlabel("shoulder area A0 (mm²)"); axes[2].legend(fontsize=5)
    axes[3].hist([r["s_bind"] for r in rows if r["feasible"]], bins=np.arange(-30, 95, 5), color=ps.DORR["A"])
    axes[3].set_xlabel("tightest point s (mm from shoulder)")
    reasons = {}
    for r in rows:
        if not r["feasible"]:
            k = r["reason"].split(" (")[0]; reasons[k] = reasons.get(k, 0) + 1
    fig.suptitle(f"{n} random designs (11 variables) templated into the real femur: {ok.sum()} feasible "
                 f"({ok.mean():.0%}); feasible = fits and shoulder ≥ prosthetic neck section ({MIN_A0:.0f} mm²)", fontsize=6.5)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return {"n": n, "feasible": int(ok.sum()), "rate": float(ok.mean()), "reasons": reasons,
            "rate_by_alpha": dict(zip([f"{lo:.0f}-{hi:.0f}" for lo, hi in zip(ab[:-1], ab[1:])], rate_a)),
            "rate_by_L": dict(zip([f"{lo:.0f}-{hi:.0f}" for lo, hi in zip(lb[:-1], lb[1:])], rate_L)),
            "A0_median_feasible": float(np.median(A0[ok])) if ok.any() else None,
            "s_bind_median_feasible": float(np.median([r["s_bind"] for r in rows if r["feasible"]])) if ok.any() else None}


def main():
    fm = FR.build()
    fm_summary_cache["dorr"] = FR.dorr_indices(fm)
    fig_overview(fm, OUT / "v2a_femur_overview.png")
    img = neck_plane_image(fm)
    ex = fig_templated_real(fm, img, OUT / "v2a_templated_examples.png", list(EXAMPLES.items()))
    feas = fig_feasibility(OUT / "v2a_feasibility.png")
    res = {"examples": ex, "feasibility": feas, "min_A0_mm2": MIN_A0}
    (OUT / "v2a_cases.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
