"""两组参考图，第二版（Linux，只读；adhoc）。用户 2026-10-02 下午：柄长 20 / 40 / 60 mm，插入角放进优化变量。

族（全部候选共用）：锥度 ρ_tip 0.3、q 1.5（颈部柄的 0.5 / 1.0 在 60 mm 放不进圆截面）；远端平端（cap_h = CAP_FLAT）；余量 −0.25；领厚 2.5 mm。
插入角：优化变量，范围 10–45°（45° 覆盖颈轴方向 ≈ 42.5°）。第一阶段每个候选取“肩部截面最大”的插入角（模板化在 2.5° 网格上选）。
图一  九类 = 柄长 20 / 40 / 60 mm × 领 0 / 2 / 4 mm；类内三个候选 = 圆、椭圆 λ 1.3、非对称（= 项目基准截面）；每类画椭圆那个。
图二  两类（默认 40 mm 窄领 = 综合最优的占位、20 mm 宽领 = 最短类）× 4 个候选，从第一阶段的例子出发每次只改一个变量：
      a 起点；b 插入角取可行范围的另一端；c 截骨 35 mm；d 截面 = 第二阶段截面空间里肩部最大的可行截面。
不提交作业、不写 results/。去骨量 = 截骨（相对 25 mm）+ 柄在骨内的体积，与 jobs.prep 的 bone_loss 相同。

    run.sh ../adhoc/reffig2/ref_figs2.py [--classes 40/2,20/4] [--n 256]   → adhoc/reffig2/out/ref2_fig1_nine_classes.png、ref2_fig2_eight_candidates.png、ref2_figs.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import textwrap
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
CODE = HOME / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import fe3d_geom as E  # noqa: E402
import plotstyle as ps  # noqa: E402
import cases_real as CR  # noqa: E402
import stage_v2a as S  # noqa: E402
from matplotlib.patches import Polygon as MP  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402
from shapely import affinity  # noqa: E402

plt = ps.plt
OUT = HOME / "adhoc" / "reffig2" / "out"
STEM_C, COLLAR_C = ps.DORR["A"], "#D55E00"
TAPER = (0.3, 1.5)
ALPHAS = np.arange(10.0, 45.01, 2.5)
LENGTHS = (20.0, 40.0, 60.0)
WIDTHS = (0.0, 2.0, 4.0)
LEN_NAME = {20.0: "ultra-short", 40.0: "short", 60.0: "medium-length"}
WID_NAME = {0.0: "no collar", 2.0: "narrow collar (2 mm)", 4.0: "wide collar (4 mm)"}
SEC_NAME = {"circ": "circle", "ell": "ellipse λ 1.3", "asym": "asymmetric"}
SEC_SPACE = {"lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0), "n_p": (2.0, 6.0),
             "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)}
EXT = ((-46.0, 46.0), (-76.0, 46.0))            # 冠状面视图：25 mm 截骨中心为原点，e1 内侧、e2 向近端
_FM = {}


def fm0():
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    return _FM["fm"]


def code(L, w):
    return f"L{L:.0f}-W{w:.0f}"


def parse(c: str) -> tuple[float, float]:
    a, b = c.split("/")
    return float(a), float(b)


# ------------------------------------------------------------------ 设计与几何
def design(sec, L, w, alpha, extra=None) -> dict:
    rho, q = TAPER
    if sec == "asym":
        d = {**S.BASE, "L": float(L), "rho_tip": rho, "q": q, "alpha": float(alpha), "m": G.M_LEGACY}
    elif sec in ("circ", "ell"):
        d = G.ellipse_design(L, rho, q, 1.0 if sec == "circ" else 1.3, alpha)
    else:                                                               # 截面参数直接给
        d = {"L": float(L), "rho_tip": rho, "q": q, **sec, "alpha": float(alpha), "m": G.M_LEGACY}
    d["cap_h"] = G.CAP_FLAT
    if w > 0:
        d.update(collar_w=float(w), collar_t=G.COLLAR_T)
    if extra:
        d.update(extra)
    return d


def a0_of(args) -> float:
    d, h = args
    r = G.template(G.Stem3D(**d), fm0().with_cut(h))
    return float(r["A0"]) if r["fit"] and r["A0"] >= S.MIN_A0 else float("nan")


def alpha_scan(sec, L, w, h=25.0, pool=None) -> dict:
    """每个 α 的肩部面积；可行范围与肩部最大的 α（并列取较小 α）。"""
    args = [(design(sec, L, w, a), h) for a in ALPHAS]
    a0 = np.array(pool.map(a0_of, args) if pool else [a0_of(x) for x in args])
    ok = np.isfinite(a0)
    if not ok.any():
        return {"feasible": False}
    k = int(np.nanargmax(a0))
    return {"feasible": True, "alpha_best": float(ALPHAS[k]), "A0_best": float(a0[k]), "alpha_lo": float(ALPHAS[ok].min()),
            "alpha_hi": float(ALPHAS[ok].max()), "a0": [None if not np.isfinite(x) else float(x) for x in a0]}


def geom(d: dict, h: float) -> dict:
    st = G.Stem3D(**d)
    fm = fm0().with_cut(h)
    pl = G.template(st, fm)
    g = {"st": st, "fm": fm, "pl": pl, "h_cut": h, "fit": bool(pl["fit"] and pl["A0"] >= S.MIN_A0)}
    if not g["fit"]:
        return g
    pl["pose"] = fm.pose(pl["alpha"], pl["e"])
    P0, dd = pl["pose"][:2]
    g["tip_z"] = float((P0 + (st.L + st.cap_length(pl["A0"])) * dd)[2])       # 股骨坐标 z 原点在小转子
    g["collar"] = E.collar_outline(st, fm, pl) if st.has_collar else None
    g["resected"] = fm.resected_volume()
    g["reamed"] = float(pl["volume"])
    g["removal"] = g["resected"] + g["reamed"]
    return g


def max_fill_section(L, w, alpha, h, n, pool) -> tuple[dict, dict]:
    from scipy.stats import qmc
    U = qmc.Sobol(len(SEC_SPACE), scramble=True, seed=11).random(n)
    secs = [{k: lo + float(u) * (hi - lo) for (k, (lo, hi)), u in zip(SEC_SPACE.items(), row)} for row in U]
    a0 = np.array(pool.map(a0_of, [(design(s, L, w, alpha), h) for s in secs], chunksize=8))
    k = int(np.nanargmax(a0))
    return secs[k], {"n": n, "feasible": int(np.isfinite(a0).sum()), "A0_max": float(a0[k]), "A0_median": float(np.nanmedian(a0))}


# ------------------------------------------------------------------ 画
def coronal_image(h: float):
    key = ("img", h)
    if key not in _FM:
        f0, f = fm0(), fm0().with_cut(h)
        C, e1, e2 = f0.neck_plane()
        a = np.arange(EXT[0][0], EXT[0][1], 0.25); b = np.arange(EXT[1][0], EXT[1][1], 0.25)
        A, B = np.meshgrid(a, b)
        P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
        lab = np.where(f.canal_sdf(P) <= 0, 2, np.where(f.outer_sdf(P) <= 0, 1, 0)).reshape(A.shape)
        _FM[key] = (a, b, lab, f.below_cut(P).reshape(A.shape))
    return _FM[key]


def draw_coronal(ax, g):
    f0, fm, st, pl = fm0(), g["fm"], g["st"], g["pl"]
    a, b, lab, kept = coronal_image(g["h_cut"])
    ax.imshow(CR._rgb(lab, kept), origin="lower", extent=(a[0], a[-1], b[0], b[-1]), interpolation="nearest")
    C0, e1, e2 = f0.neck_plane()
    y_lt = -float(C0[2])                                                 # 小转子水平（股骨坐标 z = 0）
    ax.axhline(y_lt, color="#555555", lw=0.4, ls=(0, (1, 1.5)))
    ax.text(EXT[0][1] - 1, y_lt + 1, "LT", fontsize=4.2, ha="right", va="bottom", color="#555555")
    off = np.array([(fm.C03 - C0) @ e1, (fm.C03 - C0) @ e2])
    n2 = np.array([fm.n3 @ e1, fm.n3 @ e2])
    ax.plot(off[0] + np.array([-32, 32]) * n2[0], off[1] + np.array([-32, 32]) * n2[1], color=COLLAR_C, lw=0.5, ls=(0, (3, 2)))
    poly = affinity.translate(CR.stem_silhouette(fm, st, pl), off[0], off[1])
    for p in getattr(poly, "geoms", [poly]):
        if p.geom_type == "Polygon":
            ax.add_patch(MP(np.asarray(p.exterior.coords), closed=True, fc=STEM_C, ec=STEM_C, alpha=0.88, lw=0.3))
    if g.get("collar"):
        Cc, c1, c2, nrm = E.cut_plane(fm)
        uv = np.array(g["collar"]["poly"].exterior.coords)
        bot = Cc + uv[:, :1] * c1 + uv[:, 1:2] * c2
        xy = CR._plane_xy(f0, np.vstack([bot, bot + st.collar_t * nrm]))
        hv = ConvexHull(xy)
        ax.add_patch(MP(xy[hv.vertices], closed=True, fc=COLLAR_C, ec=COLLAR_C, alpha=0.9, lw=0.3))
    ax.set_xlim(*EXT[0]); ax.set_ylim(*EXT[1]); ax.set_aspect("equal")
    CR._off(ax)


def draw_top(ax, g, half=30.0):
    fm, st, pl = g["fm"], g["st"], g["pl"]
    C, e1, e2, nrm = E.cut_plane(fm)
    u = np.arange(-half, half + 0.01, 0.15)
    U, V = np.meshgrid(u, u)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    lab = np.where(fm.canal_sdf(P) <= 0, 2, np.where(fm.outer_sdf(P) <= 0, 1, 0)).reshape(U.shape)
    ax.imshow(CR._rgb(lab, np.ones_like(lab, bool)), origin="lower", extent=(u[0], u[-1], u[0], u[-1]), interpolation="nearest")
    info = g.get("collar")
    if info is not None:
        ax.add_patch(MP(np.array(info["poly"].exterior.coords), closed=True, fc=COLLAR_C, ec=COLLAR_C, alpha=0.6, lw=0.3))
        foot = info["footprint"]
    else:
        foot = E.collar_outline(G.Stem3D(**{**st.__dict__, "collar_w": 0.01}), fm, pl)["footprint"]
    ax.add_patch(MP(np.array(foot.exterior.coords), closed=True, fc=STEM_C, ec=STEM_C, alpha=0.9, lw=0.3))
    ax.set_xlim(-half, half); ax.set_ylim(-half, half); ax.set_aspect("equal")
    CR._off(ax)


def sec_text(d: dict) -> str:
    if G.is_ellipse(d):
        return "circle" if abs(d["lam"] - 1.0) < 1e-9 else f"ellipse λ {d['lam']:.1f}"
    if all(abs(d[k] - S.BASE[k]) < 1e-9 for k in ("lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")):
        return "asymmetric (base section)"
    return f"λ {d['lam']:.2f}, n {d['n_a']:.1f}/{d['n_p']:.1f}, τ {d['tau_a']:+.2f}/{d['tau_p']:+.2f}"


def geo_lines(g: dict) -> list[str]:
    if not g["fit"]:
        return ["does not fit (templating)"]
    tip = g["tip_z"]
    c = g.get("collar")
    return [f"shoulder {g['pl']['A0']:.0f} mm² · bone removed {g['removal'] / 1000:.1f} cm³",
            f"tip {abs(tip):.0f} mm {'above' if tip >= 0 else 'below'} lesser trochanter",
            f"collar ring {c['ring_mm2']:.0f} mm², {100 * c['ring_cortex_frac']:.0f} % on cortex" if c else "no collar"]


def grid_figure(cells, nrows, ncols, row_labels, col_labels, title, foot, path, fs=4.9, text_mm=17.0):
    W, left, right = 190.0, 11.0, 2.0
    cw = (W - left - right) / ncols
    pc, pt, gap = 0.52 * cw, 0.44 * cw, 0.02 * cw
    ph = pc * (EXT[1][1] - EXT[1][0]) / (EXT[0][1] - EXT[0][0])
    ch = ph + text_mm + 3.0
    title = textwrap.fill(title, 140)
    foot = "\n".join(textwrap.fill(p, 205) for p in foot.split("\n"))
    top = 4.0 + 3.2 * (title.count("\n") + 1) + 5.0
    bottom = 3.0 + 2.1 * (foot.count("\n") + 1)
    H = top + nrows * ch + bottom
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    X = lambda mm: mm / W
    Y = lambda mm_from_top: 1.0 - mm_from_top / H
    fig.text(X(left), Y(3.0), title, fontsize=6.8, va="top", ha="left")
    for c in range(ncols):
        fig.text(X(left + c * cw), Y(top - 1.5), col_labels[c], fontsize=6.0, fontweight="bold", va="bottom", ha="left")
    for r in range(nrows):
        y0 = top + r * ch
        fig.text(X(left - 3.0), Y(y0 + ph / 2), row_labels[r], rotation=90, fontsize=6.0, fontweight="bold", va="center", ha="right",
                 multialignment="center")
        for c in range(ncols):
            g, txt = cells[r][c]
            x0 = left + c * cw
            ax0 = fig.add_axes([X(x0), Y(y0 + ph), X(pc), ph / H])
            ax1 = fig.add_axes([X(x0 + pc + gap), Y(y0 + ph * 0.55), X(pt), pt / H])
            if g["fit"]:
                draw_coronal(ax0, g)
                draw_top(ax1, g)
            else:
                CR._off(ax0); CR._off(ax1)
            fig.text(X(x0), Y(y0 + ph + 1.5), txt, fontsize=fs, va="top", ha="left", linespacing=1.25)
    fig.text(X(left), Y(H - 1.5), foot, fontsize=4.5, va="bottom", ha="left", color="#444444")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(path, dpi=250)
    plt.close(fig)


def rec_of(g: dict) -> dict:
    r = {"h_cut": g["h_cut"], "fit": g["fit"], "design": g["st"].__dict__}
    if g["fit"]:
        r.update({"A0": g["pl"]["A0"], "alpha": g["pl"]["alpha"], "e": g["pl"]["e"], "tip_z_vs_LT": g["tip_z"], "resected_mm3": g["resected"],
                  "reamed_mm3": g["reamed"], "removal_mm3": g["removal"]})
        if g.get("collar"):
            r["collar"] = {k: v for k, v in g["collar"].items() if k not in ("poly", "footprint")}
    return r


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", default="40/2,20/4")
    ap.add_argument("--n", type=int, default=256)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    rec = {"created": stamp, "taper": TAPER, "alphas": ALPHAS.tolist(), "fig1": {}, "fig2": {}}
    fm0()
    pool = Pool(a.workers)

    # 图一
    cells = []
    for L in LENGTHS:
        row = []
        for w in WIDTHS:
            scans = {s: alpha_scan(s, L, w, pool=pool) for s in ("circ", "ell", "asym")}
            se = scans["ell"]
            g = geom(design("ell", L, w, se["alpha_best"]), 25.0)
            others = " · ".join(f"{SEC_NAME[s].split()[0]} α {v['alpha_best']:.1f}°, {v['A0_best']:.0f} mm²" if v["feasible"]
                                else f"{SEC_NAME[s].split()[0]} does not fit" for s, v in scans.items() if s != "ell")
            txt = "\n".join([f"{code(L, w)} · {LEN_NAME[L]} · {WID_NAME[w]}",
                             f"ellipse λ 1.3 · α {se['alpha_best']:.1f}° (fits {se['alpha_lo']:.1f}–{se['alpha_hi']:.1f}°) · cut 25 mm"]
                            + geo_lines(g) + [f"class: {others}"])
            row.append((g, txt))
            rec["fig1"][code(L, w)] = {**rec_of(g), "alpha_scan": scans}
            print("fig1", code(L, w), json.dumps({k: v for k, v in rec["fig1"][code(L, w)].items() if k not in ("design", "alpha_scan")},
                                                 default=float)[:500], flush=True)
        cells.append(row)
    grid_figure(cells, 3, 3, [f"{LEN_NAME[L]}, L {L:.0f} mm" for L in LENGTHS], [WID_NAME[w] for w in WIDTHS],
                "Stage 1 – nine candidate classes (stem length 20 / 40 / 60 mm × collar); one example per class: elliptical section λ 1.3, "
                "insertion angle chosen by templating (largest shoulder), cut 25 mm from head centre",
                "Each cell: coronal (neck-plane) view with the cut line dashed, resected bone pale and the lesser-trochanter level dotted (LT); "
                "right: resection plane from above (grey cortex, beige cancellous, orange collar, blue stem cut). All candidates: taper "
                "tip-area ratio 0.3, exponent 1.5; flat distal end; cortical margin −0.25 mm; insertion angle searched 10–45° in 2.5° steps. "
                "Bone removed = resected neck bone (relative to the 25 mm cut) + stem volume in bone. Geometry only — no FE has been run "
                "for this family.\n"
                "Existing FE for orientation (M1 interface model, interference 0.025 mm; earlier families, pointed tip, so not the same "
                "designs): L 25 mm asymmetric, α 37°: 89.5 µm without collar, 33.2 µm with 3 mm collar; L 30 mm ellipse, α 40°: 44.6 / "
                "13.6 µm (3 mm); L 60 mm asymmetric (base), α 20°: 7.4 / 1.2 / 0.7 µm with 0 / 2 / 4 mm collar.",
                OUT / "ref2_fig1_nine_classes.png", fs=4.8, text_mm=18.5)

    # 图二
    classes = [parse(c) for c in a.classes.split(",") if c.strip()]
    roles = ["overall best (placeholder)", "shortest stem"] if len(classes) == 2 else [""] * len(classes)
    cells, row_labels = [], []
    for (L, w), role in zip(classes, roles):
        sc = rec["fig1"][code(L, w)]["alpha_scan"]["ell"]
        a1 = sc["alpha_best"]
        feas = [al for al, x in zip(ALPHAS, sc["a0"]) if x is not None]
        a2 = float(max(feas, key=lambda al: abs(al - a1)))
        sec_d, info = max_fill_section(L, w, a1, 25.0, a.n, pool)
        cand = [("a", "Stage 1 example", design("ell", L, w, a1), 25.0),
                ("b", "α at the other end of its range", design("ell", L, w, a2), 25.0),
                ("c", "deeper cut (35 mm)", design("ell", L, w, a1), 35.0),
                ("d", f"max-fill section ({info['feasible']}/{info['n']} samples fit)", design(sec_d, L, w, a1), 25.0)]
        row = []
        for tag, what, d, h in cand:
            g = geom(d, h)
            txt = "\n".join([f"{code(L, w)}-{tag} · {what}",
                             f"{sec_text(d)} · α {d['alpha']:.1f}° · cut {h:.0f} mm"] + geo_lines(g))
            row.append((g, txt))
            rec["fig2"][f"{code(L, w)}-{tag}"] = {**rec_of(g), "what": what, **({"search": info} if tag == "d" else {})}
            print("fig2", f"{code(L, w)}-{tag}", json.dumps({k: v for k, v in rec["fig2"][f'{code(L, w)}-{tag}'].items()
                                                             if k not in ("design",)}, default=float)[:500], flush=True)
        cells.append(row)
        row_labels.append(f"{code(L, w)}: {LEN_NAME[L]}, {WID_NAME[w]}" + (f"\n{role}" if role else ""))
    pool.close()
    grid_figure(cells, len(classes), 4, row_labels,
                ["a · start (Stage 1 example)", "b · insertion angle", "c · resection depth", "d · section shape"],
                "Stage 2 – two classes × four candidates: from the Stage 1 example, one optimisation variable changed at a time "
                "(insertion angle, resection depth, section shape)",
                "Optimisation variables in Stage 2: insertion angle 10–45°, resection depth 25–40 mm, section shape (λ 1–2.2, γ 0.35–0.65, "
                "n 2–6, τ ±0.3). Columns b–d are one-at-a-time changes from a, chosen by geometric rules, not optimised: b = feasible "
                "insertion angle farthest from a; c = 35 mm cut at a's angle; d = among Sobol samples of the section space, the one with the "
                "largest templated shoulder at a's angle and the 25 mm cut. At the 35 mm cut the plane also clips the greater trochanter "
                "(fragment top-left in the top view).\n"
                f"Classes are placeholders until Stage 1 FE results exist. Geometry and bone removal exact; no FE run. Built {stamp}.",
                OUT / "ref2_fig2_eight_candidates.png", fs=4.4, text_mm=16.0)
    (OUT / "ref2_figs.json").write_text(json.dumps(rec, indent=1, default=float))
    print("written", OUT, flush=True)


if __name__ == "__main__":
    main()
