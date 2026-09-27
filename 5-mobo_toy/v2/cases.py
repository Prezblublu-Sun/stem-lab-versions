"""v2 案例图：设计变量（截面形状、面积降低曲线）、3D 柄外观、模板化进 Dorr A/B/C 的冠状面与垂直中轴截面、目录级统计。"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np
from matplotlib.patches import FancyArrowPatch
from matplotlib.patches import Polygon as MP
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import plotstyle as ps  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
MID = G.from_unit(np.full(len(G.VARS), 0.5))
A_SHOW = 250.0                                   # mm²，只用于展示截面的尺度
REF = {**MID, "g_ml": 0.56, "g_ap": 0.44, "n_a": 3.0, "n_p": 5.0, "tau_a": 0.15, "tau_p": -0.10}   # 截面图册的不对称基准
EXAMPLES = {
    "rounded, posterior-full, late taper": dict(L=70, rho_tip=0.35, q=0.7, lam=1.2, g_ml=0.5, g_ap=0.42, n_a=2.5, n_p=3.5,
                                                 tau_a=0.10, tau_p=-0.15, alpha=25.0),
    "boxy, calcar-heavy, early taper": dict(L=60, rho_tip=0.15, q=2.5, lam=1.9, g_ml=0.62, g_ap=0.42, n_a=5.0, n_p=3.0,
                                             tau_a=0.25, tau_p=0.05, alpha=20.0),
    "flat, lateral-heavy, linear taper": dict(L=85, rho_tip=0.25, q=1.0, lam=2.1, g_ml=0.4, g_ap=0.55, n_a=3.5, n_p=5.5,
                                               tau_a=-0.20, tau_p=0.10, alpha=12.5),
}


def _draw_section(ax, d, k, fc="#9BB8D3", ec="#1f4e79", mirror=True):
    sec = G.unit_section(d, 240) * k
    ax.add_patch(MP(sec, closed=True, fc=fc, ec=ec, lw=0.7))
    if mirror:                                   # 关于前后侧中线 (y = 0) 的镜像，虚线：与实形不重合 = 不对称
        ax.plot(*np.vstack([sec * [1, -1], sec[:1] * [1, -1]]).T, color="#D55E00", lw=0.5, ls=(0, (2, 1.5)))
    ax.axhline(0, color=ps.GREY, lw=0.3, ls=":"); ax.axvline(0, color=ps.GREY, lw=0.3, ls=":")


def _style_off(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


# ------------------------------------------------------------------------------ 图 1：截面形状变量
def fig_sections(path):
    import matplotlib.pyplot as plt
    shape_vars = G.SHAPE_VARS
    fig, axes = ps.new_figure("double", 100, 3, len(shape_vars))
    k = math.sqrt(A_SHOW)
    for c, v in enumerate(shape_vars):
        lo, hi = G.DESIGN[v]
        for r, val in enumerate((lo, 0.5 * (lo + hi), hi)):
            d = dict(REF); d[v] = val
            ax = axes[r, c]
            _draw_section(ax, d, k)
            ax.set_xlim(-20, 20); ax.set_ylim(-14, 14); ax.set_aspect("equal")
            _style_off(ax)
            ax.set_title(f"{G.LABEL[v].split(' ')[-1]} = {val:.2f}", fontsize=6)
            if r == 0 and c == 0:
                ax.annotate("", xy=(19, -12), xytext=(12, -12), arrowprops=dict(arrowstyle="->", lw=0.5, color=ps.GREY))
                ax.text(19, -10.5, "medial", fontsize=4.5, ha="right", color=ps.GREY)
                ax.annotate("", xy=(-18, 13), xytext=(-18, 6), arrowprops=dict(arrowstyle="->", lw=0.5, color=ps.GREY))
                ax.text(-17, 12, "anterior", fontsize=4.5, color=ps.GREY)
        axes[0, c].text(0.5, 1.35, G.LABEL[v].replace(" ", "\n", 1) if len(G.LABEL[v]) > 16 else G.LABEL[v],
                        transform=axes[0, c].transAxes, ha="center", va="bottom", fontsize=5.8, fontweight="bold")
    for r, lab in enumerate(("low", "mid", "high")):
        axes[r, 0].text(-0.12, 0.5, lab, transform=axes[r, 0].transAxes, rotation=90, va="center", fontsize=6.5)
    fig.suptitle(f"Seven cross-section shape variables (each column varies one around an asymmetric reference); all sections "
                 f"{A_SHOW:.0f} mm²; dashed = mirror image about the anterior–posterior midline (y = 0)", fontsize=6.5)
    fig.savefig(path, dpi=220)
    plt.close(fig)


# ------------------------------------------------------------------------------ 图 2：面积降低曲线
def fig_area_curves(path):
    import matplotlib.pyplot as plt
    fig, axes = ps.new_figure("double", 60, 1, 3)
    x = np.linspace(0, 1, 200)
    base = dict(MID)
    for q in (0.5, 1.0, 2.0, 3.0):
        st = G.Stem3D(**{**base, "q": q, "rho_tip": 0.3, "L": 1.0})
        axes[0].plot(x, st.area_ratio(x), label=f"q = {q:g}")
    axes[0].set_title("curve shape q (ρ_tip = 0.3)", fontsize=7)
    for rt in (0.1, 0.3, 0.5):
        st = G.Stem3D(**{**base, "q": 1.0, "rho_tip": rt, "L": 1.0})
        axes[1].plot(x, st.area_ratio(x), label=f"ρ_tip = {rt:g}")
    axes[1].set_title("amount of reduction ρ_tip (q = 1)", fontsize=7)
    for ax in axes[:2]:
        ax.set_xlabel("s / L  (shoulder → tip)"); ax.set_ylabel("A(s) / A0"); ax.set_ylim(0, 1.05)
        ax.legend(fontsize=5.5)
    for name, d in EXAMPLES.items():
        st = G.Stem3D(**d)
        s = np.linspace(0, st.L, 200)
        axes[2].plot(s, 2 * np.sqrt(A_SHOW * st.area_ratio(s) / math.pi), label=name)
    axes[2].set_xlabel("s (mm)"); axes[2].set_ylabel(f"equivalent diameter (mm), A0 = {A_SHOW:.0f} mm²")
    axes[2].set_title("three example stems", fontsize=7)
    axes[2].legend(fontsize=5)
    fig.suptitle("Area-reduction curve: A(s)/A0 = ρ_tip + (1 − ρ_tip)(1 − s/L)^q", fontsize=7)
    fig.savefig(path, dpi=220)
    plt.close(fig)


# ------------------------------------------------------------------------------ 图 3：3D 外观
def stem_grid(st: G.Stem3D, A0: float, m: int = 72, ns: int = 60):
    sec = G.unit_section(st.d, m)
    sec = np.vstack([sec, sec[:1]])
    s = np.r_[np.linspace(0, st.L, ns), st.L + st.cap_length(A0) * np.sin(np.linspace(0.2, 1, 6) * np.pi / 2)]
    k = np.sqrt(A0 * st.area_ratio(np.minimum(s, st.L)))
    capf = np.ones_like(s)
    tcap = (s - st.L) / max(st.cap_length(A0), 1e-9)
    capf[s > st.L] = np.sqrt(np.clip(1 - tcap[s > st.L] ** 2, 0, 1))
    X = (k * capf)[:, None] * sec[None, :, 0]
    Y = (k * capf)[:, None] * sec[None, :, 1]
    Z = -np.repeat(s[:, None], sec.shape[0], axis=1)
    return X, Y, Z


def fig_3d(path):
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(ps.WIDTH_MM["double"] * ps.MM, 80 * ps.MM))
    for i, (name, d) in enumerate(EXAMPLES.items()):
        st = G.Stem3D(**d)
        X, Y, Z = stem_grid(st, A_SHOW)
        ax = fig.add_subplot(1, 3, i + 1, projection="3d")
        ax.plot_surface(X, Y, Z, color="#9BB8D3", edgecolor="#1f4e79", lw=0.1, rstride=3, cstride=4, alpha=0.95, shade=True)
        ax.set_box_aspect((1, 1, 3.2))
        ax.set_xlim(-18, 18); ax.set_ylim(-18, 18); ax.set_zlim(-95, 0)
        ax.view_init(elev=18, azim=-60)
        ax.set_xlabel("medial →", fontsize=5, labelpad=-8); ax.set_ylabel("anterior →", fontsize=5, labelpad=-8)
        ax.set_zlabel("s (mm)", fontsize=5, labelpad=-6)
        ax.tick_params(labelsize=4, pad=-3)
        ax.set_title(f"{name}\nL {st.L:.0f}, ρ_tip {st.rho_tip:.2f}, q {st.q:.1f}, α {st.alpha:.1f}°\n"
                     f"λ {st.lam:.1f}, γ_ml {st.g_ml:.2f}, γ_ap {st.g_ap:.2f}\n"
                     f"n_a/n_p {st.n_a:.1f}/{st.n_p:.1f}, τ_a/τ_p {st.tau_a:+.2f}/{st.tau_p:+.2f}", fontsize=5.2)
    fig.suptitle(f"Example stems (shoulder area {A_SHOW:.0f} mm² for display; the real size is set by templating)", fontsize=7)
    fig.savefig(path, dpi=220)
    plt.close(fig)


# ------------------------------------------------------------------------------ 图 4：模板化进 A/B/C
def plane_raster(fem: G.Femur3D, C, e1, e2, half=22.0, h=0.15):
    u = np.arange(-half, half + h, h)
    U, V = np.meshgrid(u, u)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    canal = (fem.canal_excess(P) == 0).reshape(U.shape)
    bone = (fem.outer_excess(P) == 0).reshape(U.shape)
    kept = fem.below_cut(P).reshape(U.shape)
    return u, bone & kept, canal & kept


def draw_coronal(ax, fem: G.Femur3D, st: G.Stem3D, pl: dict, color):
    f = fem.f2d
    for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
        ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
    ax.plot(*np.asarray(f.cut_segment().coords).T, color="#D55E00", lw=0.8)
    P0, d, e_ml, e_ap = pl["pose"]
    sec = G.unit_section(st.d, 128)
    s = np.r_[np.linspace(G.S_TOP, 0, 10, endpoint=False), np.linspace(0, st.L, 80)]
    k = np.sqrt(pl["A0"] * st.area_ratio(s))
    med, lat = k * sec[:, 0].max(), k * sec[:, 0].min()
    ring = np.r_[[P0 + si * d + mi * e_ml for si, mi in zip(s, med)],
                 [P0 + (st.L + st.cap_length(pl["A0"])) * d],
                 [P0 + si * d + li * e_ml for si, li in zip(s[::-1], lat[::-1])]]
    from shapely.geometry import Polygon
    poly = Polygon(ring[:, [0, 2]]).buffer(0).intersection(f.kept_halfplane())
    for g in getattr(poly, "geoms", [poly]):
        if g.geom_type == "Polygon":
            ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=color, ec=color, alpha=0.8))
    a0 = P0 - 45 * d
    ax.add_patch(FancyArrowPatch((a0[0], a0[2]), (a0[0] + 22 * d[0], a0[2] + 22 * d[2]), arrowstyle="-|>",
                                 mutation_scale=7, color="black", lw=0.8))
    for fr in (0.15, 0.5, 0.85):
        c = P0 + fr * st.L * d
        w = 16
        ax.plot([c[0] - w * e_ml[0], c[0] + w * e_ml[0]], [c[2] - w * e_ml[2], c[2] + w * e_ml[2]], color="black", lw=0.4, ls="--")
    ax.set_xlim(-38, 68); ax.set_ylim(-95, 90); ax.set_aspect("equal")
    _style_off(ax)


def draw_section(ax, fem: G.Femur3D, st: G.Stem3D, pl: dict, frac: float, color):
    P0, d, e_ml, e_ap = pl["pose"]
    s = frac * st.L
    C = P0 + s * d
    u, bone, canal = plane_raster(fem, C, e_ml, e_ap)
    img = np.zeros(bone.shape + (3,)) + 1.0
    img[bone] = np.array([0.79, 0.79, 0.79])
    img[canal] = np.array([0.953, 0.890, 0.765])
    ax.imshow(img, origin="lower", extent=(u[0], u[-1], u[0], u[-1]), interpolation="nearest")
    sec = G.unit_section(st.d, 160) * math.sqrt(pl["A0"] * float(st.area_ratio(s)))
    ax.add_patch(MP(sec, closed=True, fc=color, ec=color, alpha=0.85, lw=0.5))
    ax.set_xlim(u[0], u[-1]); ax.set_ylim(u[0], u[-1]); ax.set_aspect("equal")
    _style_off(ax)
    ax.text(0.03, 0.03, f"s = {s:.0f} mm", transform=ax.transAxes, fontsize=5, bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.8))


def fig_templated(name, d, path):
    import matplotlib.pyplot as plt
    st = G.Stem3D(**d)
    fig, axes = ps.new_figure("double", 150, 3, 4)
    rec = []
    for r, t in enumerate("ABC"):
        fem = G.Femur3D(t)
        pl = G.template(st, fem)
        col = ps.DORR[t]
        if not pl["fit"]:
            for ax in axes[r]:
                _style_off(ax)
            axes[r, 0].text(0.5, 0.5, f"Dorr {t}: does not fit\n{pl['reason']}", transform=axes[r, 0].transAxes, ha="center",
                            fontsize=6)
            rec.append({"dorr": t, "fit": False, "reason": pl["reason"]})
            continue
        draw_coronal(axes[r, 0], fem, st, pl, col)
        axes[r, 0].text(0.02, 0.02, f"Dorr {t}\nα {pl['alpha']:.1f}°, offset {pl['e']:+.0f} mm\n"
                        f"shoulder {pl['A0']:.0f} mm² (Ø_eq {pl['w_eq']:.1f} mm)\n"
                        f"contact {pl['contact']:.1%}, tightest at s = {pl['s_bind']:.0f} mm",
                        transform=axes[r, 0].transAxes, fontsize=5, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
        for c, fr in enumerate((0.15, 0.5, 0.85)):
            draw_section(axes[r, c + 1], fem, st, pl, fr, col)
        rec.append({"dorr": t, "fit": True, **{k: pl[k] for k in ("alpha", "e", "A0", "w_eq", "contact", "volume", "s_bind")}})
    for c, lab in enumerate(("coronal (y = 0), dashed = section planes", "section normal to axis, 0.15 L", "section at 0.50 L",
                             "section at 0.85 L")):
        axes[0, c].set_title(lab, fontsize=6)
    fig.suptitle(f"'{name}' (α = {st.alpha:.1f}° is a design variable) templated into each femur: largest size with cortex "
                 f"penetration ≤ {G.TOL} mm; sections: medial → right, anterior ↑", fontsize=6.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return rec


# ------------------------------------------------------------------------------ 图 5：目录级模板化
_FEM = {}


def _work(job):
    i, t, u = job
    if t not in _FEM:
        _FEM[t] = G.Femur3D(t)
    st = G.Stem3D(**G.from_unit(u))
    r = G.template(st, _FEM[t])
    out = {"i": i, "dorr": t, **st.d, "fit": r["fit"], "reason": r.get("reason", "")}
    for k in ("e", "A0", "w_eq", "contact", "volume", "s_bind"):
        out[k] = r.get(k, math.nan)
    return out


def fig_catalogue(path, n=1024, seed=21):
    import matplotlib.pyplot as plt
    U = qmc.Sobol(len(G.VARS), scramble=True, seed=seed).random(n)
    jobs = [(i, t, U[i]) for t in "ABC" for i in range(n)]
    with Pool(12) as pool:
        rows = pool.map(_work, jobs, chunksize=8)
    with open(OUT / "catalogue_templating_v2.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    fig, axes = ps.new_figure("double", 62, 1, 4)
    summ = {}
    bins = np.arange(G.ALPHA_LO, G.ALPHA_HI + 0.1, 5.0)
    for t in "ABC":
        R = [r for r in rows if r["dorr"] == t]
        fit = [r for r in R if r["fit"]]
        summ[t] = {"fit": len(fit), "n": len(R), "reasons": {}}
        for r in R:
            if not r["fit"]:
                key = r["reason"].split(" (")[0]
                summ[t]["reasons"][key] = summ[t]["reasons"].get(key, 0) + 1
        a_all = np.array([r["alpha"] for r in R]); ok = np.array([r["fit"] for r in R])
        rate = [float(ok[(a_all >= lo) & (a_all < hi)].mean()) for lo, hi in zip(bins[:-1], bins[1:])]
        axes[0].step(bins, np.r_[rate, rate[-1]], where="post", color=ps.DORR[t], lw=1.0,
                     label=f"Dorr {t}: {len(fit)}/{len(R)} fit")
        A = np.array([r["A0"] for r in fit])
        axes[1].hist(A, bins=np.arange(0, 700, 20), histtype="step", color=ps.DORR[t], lw=1.0,
                     label=f"Dorr {t}: median {np.median(A):.0f} mm²")
        axes[2].hist([r["s_bind"] for r in fit], bins=np.arange(-30, 95, 5), histtype="step", color=ps.DORR[t], lw=1.0)
        summ[t].update(fit_rate_by_alpha={f"{lo:.0f}-{hi:.0f}": round(v, 3) for lo, hi, v in zip(bins[:-1], bins[1:], rate)},
                       A0_median=float(np.median(A)), A0_p10=float(np.percentile(A, 10)), A0_p90=float(np.percentile(A, 90)),
                       contact_median=float(np.median([r["contact"] for r in fit])),
                       s_bind_median=float(np.median([r["s_bind"] for r in fit])),
                       s_bind_frac_neck=float(np.mean([r["s_bind"] < 15 for r in fit])))
    axes[0].set_xlabel("insertion angle α (°)"); axes[0].set_ylabel("fraction that fits"); axes[0].set_ylim(0, 1.05)
    axes[0].legend(fontsize=4.8)
    axes[1].set_xlabel("templated shoulder area A0 (mm²)"); axes[1].set_ylabel("stems"); axes[1].legend(fontsize=4.8)
    axes[2].set_xlabel("tightest point s (mm from shoulder)"); axes[2].set_ylabel("stems")
    by = {t: {r["i"]: r for r in rows if r["dorr"] == t and r["fit"]} for t in "ABC"}
    common = sorted(set(by["A"]) & set(by["B"]) & set(by["C"]))
    rA = np.array([by["C"][i]["A0"] / by["A"][i]["A0"] for i in common])
    rB = np.array([by["C"][i]["A0"] / by["B"][i]["A0"] for i in common])
    axes[3].hist(rA, bins=30, histtype="step", color=ps.DORR["A"], label="A0(C) / A0(A)")
    axes[3].hist(rB, bins=30, histtype="step", color=ps.DORR["B"], label="A0(C) / A0(B)")
    axes[3].set_xlabel("size ratio, same stem"); axes[3].legend(fontsize=5)
    summ["fit_all_three"] = len(common)
    summ["same_stem_size_ratio_C_over_A_median"] = float(np.median(rA)) if len(rA) else None
    summ["same_stem_size_ratio_C_over_B_median"] = float(np.median(rB)) if len(rB) else None
    fig.suptitle(f"{n} catalogue designs (Sobol, {len(G.VARS)} variables incl. α {G.ALPHA_LO:.0f}–{G.ALPHA_HI:.0f}°) templated into each "
                 f"femur: {sum(summ[t]['fit'] for t in 'ABC')}/{3 * n} placements fit, {len(common)} designs fit all three",
                 fontsize=6.5)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return summ


# ------------------------------------------------------------------------------ 图 6：随机目录截面
def fig_random_sections(path, n=16, seed=5):
    import matplotlib.pyplot as plt
    U = qmc.Sobol(len(G.VARS), scramble=True, seed=seed).random(n)
    fig, axes = ps.new_figure("double", 58, 2, n // 2)
    k = math.sqrt(A_SHOW)
    for i, (ax, u) in enumerate(zip(axes.flat, U)):
        d = G.from_unit(u)
        _draw_section(ax, d, k)
        ax.set_xlim(-22, 22); ax.set_ylim(-15, 15); ax.set_aspect("equal")
        _style_off(ax)
        ax.set_title(f"γ_ap {d['g_ap']:.2f}, n {d['n_a']:.1f}/{d['n_p']:.1f}\nτ {d['tau_a']:+.2f}/{d['tau_p']:+.2f}", fontsize=4.8)
    fig.suptitle(f"{n} random catalogue sections ({A_SHOW:.0f} mm², medial → right, anterior ↑); dashed = mirror about the "
                 "anterior–posterior midline", fontsize=6.5)
    fig.savefig(path, dpi=220)
    plt.close(fig)


# ------------------------------------------------------------------------------ 图 7：插入角
def fig_alpha(path, name="boxy, calcar-heavy, early taper", dorr="B", angles=(5.0, 15.0, 25.0, 35.0)):
    import matplotlib.pyplot as plt
    fem = G.Femur3D(dorr)
    fig, axes = ps.new_figure("double", 78, 1, len(angles))
    rec = []
    for ax, a in zip(axes, angles):
        st = G.Stem3D(**{**EXAMPLES[name], "alpha": a})
        pl = G.template(st, fem)
        if pl["fit"]:
            draw_coronal(ax, fem, st, pl, ps.DORR[dorr])
            txt = (f"α {a:.0f}° (implant neck–shaft {130 + a:.0f}°)\noffset {pl['e']:+.0f} mm, shoulder {pl['A0']:.0f} mm²\n"
                   f"tightest at s = {pl['s_bind']:.0f} mm")
            rec.append({"alpha": a, "fit": True, "A0": pl["A0"], "e": pl["e"], "s_bind": pl["s_bind"]})
        else:
            f = fem.f2d
            for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
            ax.set_xlim(-38, 68); ax.set_ylim(-95, 90); ax.set_aspect("equal"); _style_off(ax)
            txt = f"α {a:.0f}°: does not fit\n{pl['reason']}"
            rec.append({"alpha": a, "fit": False, "reason": pl["reason"]})
        ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=5, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
    fig.suptitle(f"Insertion angle as a design variable: '{name}' in Dorr {dorr} at four angles "
                 "(size and entry offset re-templated each time)", fontsize=6.5)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return rec


def main():
    fig_sections(OUT / "v2_sections.png")
    fig_area_curves(OUT / "v2_area_curves.png")
    fig_3d(OUT / "v2_stems_3d.png")
    fig_random_sections(OUT / "v2_random_sections.png")
    alpha_rec = fig_alpha(OUT / "v2_alpha.png")
    rec = {}
    for j, (name, d) in enumerate(EXAMPLES.items()):
        rec[name] = fig_templated(name, d, OUT / f"v2_templated_{j + 1}.png")
    summ = fig_catalogue(OUT / "v2_catalogue.png")
    (OUT / "v2_cases.json").write_text(json.dumps({"examples": rec, "alpha_demo": alpha_rec, "catalogue": summ}, indent=1,
                                                  default=float), encoding="utf-8")
    print(json.dumps({"examples": rec, "alpha_demo": alpha_rec, "catalogue": summ}, indent=1, default=float))


if __name__ == "__main__":
    main()
