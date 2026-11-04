"""Concept figures for the interim report v6 — simplified: key information only, one-sentence title per figure.
    fig1_bone_removal.png   bone removed = resected neck beyond the reference cut + stem cavity
    fig2_fe_setup.png       FE set-up: bone model and frame; load; press-fit interface + load history; zone definitions
    fig3_parametric_stem.png the 13-number stem: coronal parameters, section parameters, taper
Linux, read-only on the queue, geometry only:   run.sh adhoc/plan/fig_concepts.py
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "plan")); sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import plan_figs as PF  # noqa: E402
from plan_figs import R2, G, CR, S, ps, plt  # noqa: E402
import resorption as RS  # noqa: E402
from matplotlib.patches import Arc  # noqa: E402

OUT = HOME / "adhoc" / "plan" / "out"
FIRST = "collar_neck_w3_36c2bb73"
ORANGE, BLUE, GREY = "#D55E00", R2.STEM_C, "#555555"
RES_C, CAV_C = "#E69F00", "#0072B2"
YLIM = (-60.0, 46.0)
TITLE_FS, HEAD_FS, LAB_FS, NOTE_FS = 9.5, 7.0, 6.2, 6.0
_C = {}


def f0():
    return R2.fm0()


def frame():
    if "fr" not in _C:
        C, e1, e2 = f0().neck_plane()
        _C["fr"] = (C, e1, e2, np.cross(e1, e2))
    return _C["fr"]


def uv(X):
    C, e1, e2, _ = frame()
    Q = np.atleast_2d(np.asarray(X, float)) - C
    return np.c_[Q @ e1, Q @ e2]


def grid(step=0.25):
    if "grid" not in _C:
        C, e1, e2, _ = frame()
        a = np.arange(R2.EXT[0][0], R2.EXT[0][1], step); b = np.arange(R2.EXT[1][0], R2.EXT[1][1], step)
        A, B = np.meshgrid(a, b)
        P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
        fm = f0()
        lab = np.where(fm.canal_sdf(P) <= 0, 2, np.where(fm.outer_sdf(P) <= 0, 1, 0)).reshape(A.shape)
        _C["grid"] = (a, b, A, B, P, lab)
    return _C["grid"]


def bone(ax, kept=None):
    a, b, A, B, P, lab = grid()
    k = np.ones_like(lab, bool) if kept is None else kept
    ax.imshow(CR._rgb(lab, k), origin="lower", extent=(a[0], a[-1], b[0], b[-1]), interpolation="nearest")


def cut_line(ax, fm, color=ORANGE, half=32.0, lw=0.7, ls=(0, (3, 2))):
    C, e1, e2, _ = frame()
    off = uv(fm.C03)[0]; n2 = np.array([fm.n3 @ e1, fm.n3 @ e2])
    ax.plot(off[0] + np.array([-half, half]) * n2[0], off[1] + np.array([-half, half]) * n2[1], color=color, lw=lw, ls=ls)
    return off, n2


def lt_line(ax):
    v = uv([0.0, 0.0, 0.0])[0, 1]
    ax.axhline(v, color=GREY, lw=0.4, ls=(0, (1, 1.5)))
    return v


def stem_patch(ax, g, color=BLUE, alpha=0.88):
    fm, st, pl = g["fm"], g["st"], g["pl"]
    off = uv(fm.C03)[0]
    poly = R2.affinity.translate(CR.stem_silhouette(fm, st, pl), off[0], off[1])
    for p in getattr(poly, "geoms", [poly]):
        if p.geom_type == "Polygon":
            ax.add_patch(R2.MP(np.asarray(p.exterior.coords), closed=True, fc=color, ec=color, alpha=alpha, lw=0.3))
    return poly


def finish(ax, ylim=YLIM):
    ax.set_xlim(*R2.EXT[0]); ax.set_ylim(*ylim); ax.set_aspect("equal"); CR._off(ax)


def panel(fig, x, y, w, W, H, ylim=YLIM):
    h = w * (ylim[1] - ylim[0]) / (R2.EXT[0][1] - R2.EXT[0][0])
    ax = fig.add_axes([x / W, 1 - (y + h) / H, w / W, h / H])
    return ax, h


def title(fig, s, W, H):
    fig.text(6 / W, 1 - 3.0 / H, s, fontsize=TITLE_FS, fontweight="bold", va="top")


def head(fig, x, y, s, W, H):
    fig.text(x / W, 1 - (y - 1.5) / H, s, fontsize=HEAD_FS, fontweight="bold", va="bottom")


def note(fig, x, y, s, W, H, fs=NOTE_FS, color="#333333"):
    fig.text(x / W, 1 - y / H, s, fontsize=fs, va="top", ha="left", color=color, linespacing=1.4)


def label(ax, xy, text, dxy, fs=LAB_FS, color="#222222", ha="left", va="center"):
    ax.annotate(text, xy=xy, xytext=(xy[0] + dxy[0], xy[1] + dxy[1]), fontsize=fs, color=color, ha=ha, va=va,
                arrowprops=dict(arrowstyle="-", lw=0.5, color=color, shrinkA=0, shrinkB=1))


# ================================================================== Fig 1 — bone removal
def fig_bone_removal():
    a, b, A, B, P, lab = grid()
    fm = f0(); fm25 = fm.with_cut(25.0)
    k25 = fm25.below_cut(P).reshape(A.shape); in_bone = lab > 0
    g25, spec = PF.geo_of(FIRST)
    gh = None
    for h in (28.0, 27.0, 26.0):
        gg = R2.geom(spec["design"], h)
        if gg["fit"]:
            gh = gg; break
    h = gh["h_cut"]; fmh = fm.with_cut(h); kh = fmh.below_cut(P).reshape(A.shape)
    wedge = k25 & ~kh & in_bone
    v_res, v_cav = fmh.resected_volume() / 1000, gh["reamed"] / 1000
    W, H = 190.0, 90.0
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    title(fig, "Bone removed = neck cut beyond the reference plane + the stem's cavity", W, H)
    pw = 56.0
    heads = ["(a) intact femur and the reference cut", f"(b) cut deepened to {h:.0f} mm", "(c) stem placed and sized"]
    for i, hd in enumerate(heads):
        x = 6 + i * 62
        ax, ph = panel(fig, x, 16, pw, W, H)
        head(fig, x, 16, hd, W, H)
        if i == 0:
            bone(ax)
            off, n2 = cut_line(ax, fm25)
            Huv = uv(fm.H)[0]; ax.plot(*Huv, "o", ms=3.0, color="black")
            ax.annotate("", xy=off, xytext=Huv, arrowprops=dict(arrowstyle="-|>", lw=0.9, color="black", mutation_scale=8))
            ax.text(Huv[0] + 2.5, Huv[1] + 2.5, "head centre", fontsize=LAB_FS, va="bottom")
            ax.text((Huv[0] + off[0]) / 2 + 4, (Huv[1] + off[1]) / 2 - 2, "25 mm", fontsize=LAB_FS, va="top")
            end = off + (24 if n2[1] < 0 else -24) * n2
            ax.text(end[0] + 1, end[1] - 1, "reference cut\n(head–neck junction)", fontsize=LAB_FS, color=ORANGE, ha="left", va="top")
        else:
            bone(ax, kh)
            cut_line(ax, fm25); cut_line(ax, fmh, color=RES_C, ls="-", lw=0.9)
            ax.contourf(A, B, wedge.astype(float), levels=[0.5, 1.5], colors=[RES_C], alpha=0.9)
            wc = (float(A[wedge].mean()), float(B[wedge].mean()))
            if i == 1:
                ax.annotate(f"resected neck\n{v_res:.1f} cm³", xy=wc, xytext=(wc[0] - 34, wc[1] - 26), fontsize=LAB_FS + 0.5, color=RES_C, ha="left",
                            va="top", fontweight="bold", arrowprops=dict(arrowstyle="-", lw=0.6, color=RES_C))
            else:
                stem_patch(ax, gh, CAV_C, alpha=0.92)
                sc = uv(gh["pl"]["pose"][0] + 0.55 * gh["st"].L * gh["pl"]["pose"][1])[0]
                ax.text(sc[0], sc[1], f"cavity\n{v_cav:.1f} cm³", fontsize=LAB_FS + 0.5, color="white", ha="center", va="center", fontweight="bold")
                ax.text(R2.EXT[0][0] + 2, YLIM[0] + 3, f"bone removed = {v_res:.1f} + {v_cav:.1f} = {v_res + v_cav:.1f} cm³", fontsize=LAB_FS + 0.3,
                        va="bottom", fontweight="bold")
        lt_line(ax); finish(ax)
    note(fig, 6, H - 7, "Both volumes come from geometry alone, before any FE; the head above the reference cut is replaced in every design and is not counted.",
         W, H, color="#444444")
    fig.savefig(OUT / "fig1_bone_removal.png", dpi=250); plt.close(fig)
    print("fig1", f"h={h}", f"V_res={v_res:.2f}", f"V_cav={v_cav:.2f}", flush=True)


# ================================================================== Fig 2 — FE set-up
def load_vector(cfg):
    L = cfg["load"]
    tx, ty = math.tan(math.radians(L["alpha_front_deg"])), math.tan(math.radians(L["alpha_sagit_deg"]))
    fz = L["resultant_N"] / math.sqrt(1 + tx * tx + ty * ty)
    fx_B, fy_B, fz_B = tx * fz, -ty * fz, -fz
    return np.array([-fx_B, -fy_B, fz_B])


def fig_fe_setup():
    a, b, A, B, P, lab = grid()
    fm = f0(); cfg = fm.cfg
    C, e1, e2, n = frame()
    g, spec = PF.geo_of(FIRST)
    W, H = 190.0, 176.0
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    title(fig, "One Sawbones femur, one load, two interface models, two zone definitions", W, H)
    pw = 62.0
    pos = {"a": (6, 16), "b": (100, 16), "c": (6, 98), "d": (100, 98)}
    heads = {"a": "(a) bone model and frame", "b": "(b) stair-climbing load, 2 391 N", "c": "(c) press-fit interface and load history",
             "d": "(d) where load transfer is measured"}
    axes = {}
    for k, (x, y) in pos.items():
        ax, ph = panel(fig, x, y, pw, W, H)
        head(fig, x, y, heads[k], W, H)
        axes[k] = ax
    # (a)
    ax = axes["a"]; bone(ax)
    Huv = uv(fm.H)[0]
    ax.plot(*Huv, "o", ms=3.0, color="black"); ax.text(Huv[0] + 2.5, Huv[1] + 2.5, "head centre", fontsize=LAB_FS)
    t = np.linspace(-8, 70, 2); na = uv(fm.H[None, :] - t[:, None] * fm.u3[None, :])
    ax.plot(na[:, 0], na[:, 1], color="black", lw=0.6, ls=(0, (4, 2)))
    p40 = uv(fm.H - 38.0 * fm.u3)[0]; ax.text(p40[0] + 3, p40[1] - 1, "neck axis", fontsize=LAB_FS, ha="left", va="top")
    sh = uv(np.c_[np.zeros(2), np.zeros(2), np.array([-80.0, 40.0])])
    ax.plot(sh[:, 0], sh[:, 1], color="black", lw=0.6, ls=(0, (4, 2))); s45 = uv([0.0, 0.0, 16.0])[0]; ax.text(s45[0] - 2, s45[1], "shaft axis", fontsize=LAB_FS, va="center", ha="right")
    vlt = lt_line(ax); ax.text(R2.EXT[0][1] - 1, vlt + 1.2, "lesser trochanter", fontsize=LAB_FS, ha="right", va="bottom", color=GREY)
    sdf = fm.canal_sdf(P).reshape(A.shape)
    ax.contour(A, B, sdf, levels=[-9, -6, -3], colors=["#2E6E9E"], linewidths=0.4)
    ax.text(R2.EXT[0][0] + 2, YLIM[0] + 4, "canal distance field", fontsize=LAB_FS, color="#2E6E9E", va="bottom")
    finish(ax)
    note(fig, 70, 20, "Sawbones femur, CT:\ncortex + cancellous\nsolids (STEP)\n\nhead radius 25.3 mm\nneck–shaft 137.5°\noffset 39.5 mm\nanteversion 6.1°\n\ncortex 16.8 GPa\ncancellous 400 MPa\nTi-6Al-4V 110 GPa", W, H)
    # (b)
    ax = axes["b"]; bone(ax)
    F = load_vector(cfg); Fu, Fv, Fn = F @ e1, F @ e2, F @ n
    dirn = np.array([Fu, Fv]) / math.hypot(Fu, Fv)
    tail = Huv - 34.0 * dirn
    ax.annotate("", xy=Huv, xytext=tail, arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#C00000", mutation_scale=11))
    ax.plot(*Huv, "o", ms=3.0, color="black")
    ax.text(tail[0] - 2.5, tail[1] - 2, "2 391 N", fontsize=LAB_FS + 1, color="#C00000", ha="right", va="top", fontweight="bold")
    ax.text(Huv[0] + 4, Huv[1] - 1, "⊗", fontsize=9, color="#C00000", ha="center", va="center")
    ax.text(Huv[0] + 8.5, Huv[1] - 1, f"{abs(F[1]):.0f} N posterior", fontsize=LAB_FS, color="#C00000", va="center")
    P0, d = g["pl"]["pose"][0], g["pl"]["pose"][1]
    mid = uv(P0 + 0.5 * g["st"].L * d)[0]
    ax.add_patch(Arc(mid, 16, 9, angle=0, theta1=200, theta2=340, color="#C00000", lw=0.9))
    ax.annotate("", xy=(mid[0] + 7.5, mid[1] - 1.5), xytext=(mid[0] + 7.4, mid[1] - 2.5), arrowprops=dict(arrowstyle="-|>", lw=0.9, color="#C00000", mutation_scale=7))
    ax.text(mid[0] - 10, mid[1] - 7, "torsion ≈ 28 N·m", fontsize=LAB_FS, color="#C00000", ha="right", va="top")
    xs = np.linspace(-18, 10, 12); yb = YLIM[0] + 1.2
    for xx in xs:
        ax.plot([xx, xx - 2.5], [yb, yb - 2.5], color="black", lw=0.5, clip_on=False)
    ax.plot([xs[0] - 1, xs[-1] + 1], [yb, yb], color="black", lw=0.9, clip_on=False)
    ax.text(xs[-1] + 3, yb + 1, "distal end fixed", fontsize=LAB_FS, va="bottom")
    finish(ax)
    note(fig, 164, 20, "Bergmann 2016,\nstair climbing:\n20° frontal,\n18° sagittal\n\nposterior push\n→ backward tilt\n(twist is small)", W, H)
    # (c)
    ax = axes["c"]; R2.draw_coronal(ax, g)
    poly = stem_patch(ax, g, BLUE, alpha=0.0)
    for p in getattr(poly, "geoms", [poly]):
        if p.geom_type == "Polygon":
            xy = np.asarray(p.exterior.coords); ax.plot(xy[:, 0], xy[:, 1], color=ORANGE, lw=1.1, ls=(0, (2, 1)))
    off = uv(g["fm"].C03)[0]
    label(ax, (off[0] - 10, off[1] - 12), "interference 0.025 mm\nfriction μ = 0.3", (-16, -30), color=ORANGE, fs=LAB_FS)
    label(ax, (off[0] + 7, off[1] + 1), "collar: frictional\ncontact", (12, 12), color=ORANGE, fs=LAB_FS)
    finish(ax)
    axi = fig.add_axes([70 / W, 1 - (98 + 32) / H, 26 / W, 24 / H])
    steps = ["seat", "release", "load", "unload", "reload"]; lv = [0, 0, 1, 0, 1]
    axi.step(range(6), lv + [1], where="post", color="#222222", lw=1.1)
    axi.set_xticks(np.arange(5) + 0.5); axi.set_xticklabels(steps, fontsize=5.4, rotation=45, ha="right"); axi.set_yticks([0, 1]); axi.set_yticklabels(["0", "F"], fontsize=5.6)
    axi.set_xlim(0, 5); axi.set_ylim(-0.15, 1.4); axi.tick_params(length=1.5, pad=1)
    for s_ in ("top", "right"):
        axi.spines[s_].set_visible(False)
    axi.annotate("", xy=(4.5, 1.18), xytext=(3.5, 1.18), arrowprops=dict(arrowstyle="<->", lw=0.7))
    axi.text(4.0, 1.25, "micromotion", fontsize=5.4, ha="center", va="bottom")
    axi.set_title("load history", fontsize=6.2, loc="left")
    note(fig, 70, 138, "micromotion =\nslip(reload) − slip(unload)\n\nbonded model:\nshared nodes (collar\ntoo) → load transfer", W, H)
    # (d)
    ax = axes["d"]; R2.draw_coronal(ax, g)
    pl, st = g["pl"], g["st"]
    P0, d, e_ml, e_ap = pl["pose"]
    Q = P - P0; loc = np.c_[Q @ d, Q @ e_ml, Q @ e_ap]
    in_stem = G.inside_stem(st, pl["A0"], loc)
    keep = (lab.ravel() > 0) & g["fm"].below_cut(P) & ~in_stem
    fmc = g["fm"]; inb = lab.ravel() > 0
    z7 = ((P[:, 0] >= 0) & (P[:, 2] >= -10.0) & fmc.below_cut(P) & inb & ~in_stem).reshape(A.shape)
    ax.contourf(A, B, z7.astype(float), levels=[0.5, 1.5], colors=["#9ecae1"], alpha=0.5)
    ax.contour(A, B, z7.astype(float), levels=[0.5], colors=["black"], linewidths=0.9, linestyles="dashed")
    s_ = (P - fmc.C03) @ fmc.u3
    band = ((s_ <= 0) & (s_ >= -10.0) & ((P - fmc.C03) @ fmc.n3 >= 0) & (lab.ravel() == 1) & ~in_stem).reshape(A.shape)
    ax.contourf(A, B, band.astype(float), levels=[0.5, 1.5], colors=["#e6550d"], alpha=0.9)
    i = np.argmin(np.where(band, B, np.inf)); bx, by = A.ravel()[i], B.ravel()[i]
    label(ax, (bx, by), "10 mm band\nbelow the cut", (14, -12), color="#B03A00", fs=LAB_FS)
    finish(ax)
    note(fig, 164, 102, "orange: cortex in the\n10 mm band below the cut\n= the evaluation axis\n(same for every stem)\n\ndashed: fixed zone 7\n= the constraint\n(±30 % of intact)", W, H)
    fig.savefig(OUT / "fig2_fe_setup.png", dpi=250); plt.close(fig)
    print("fig2", "F model =", np.round(F, 0), flush=True)


# ================================================================== Fig 3 — parametric stem
def fig_parametric():
    g, spec = PF.geo_of(FIRST)
    fm, st, pl = g["fm"], g["st"], g["pl"]
    W, H = 190.0, 96.0
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    title(fig, "Fourteen numbers define a stem; placement sets its size", W, H)
    # (a)
    ax, ph = panel(fig, 6, 16, 64.0, W, H)
    head(fig, 6, 16, "(a) five coronal parameters", W, H)
    R2.draw_coronal(ax, g)
    P0, d, e_ml, e_ap = pl["pose"]
    p0, pt = uv(P0)[0], uv(P0 + st.L * d)[0]
    du = (pt - p0) / np.linalg.norm(pt - p0); nu = np.array([-du[1], du[0]])
    if nu[0] > 0:
        nu = -nu
    ang = math.degrees(math.atan2(du[1], du[0]))
    ax.annotate("", xy=pt - 1.5 * du, xytext=p0 + 1.5 * du, arrowprops=dict(arrowstyle="<->", lw=0.8, color="white", mutation_scale=7))
    ax.text(*((p0 + pt) / 2 + 3.0 * nu), f"L = {st.L:.0f} mm", fontsize=LAB_FS + 0.5, color="white", ha="center", va="center", rotation=ang + 180, fontweight="bold")
    ext = pt + 16 * du
    ax.plot([pt[0], ext[0]], [pt[1], ext[1]], color="black", lw=0.5, ls=(0, (2, 1.5)))
    ax.plot([pt[0], pt[0]], [pt[1], pt[1] - 16], color="black", lw=0.5, ls=(0, (2, 1.5)))
    a_deg = ang % 360
    ax.add_patch(Arc(pt, 20, 20, angle=0, theta1=min(270, a_deg), theta2=max(270, a_deg), color="black", lw=0.7))
    ax.text(pt[0] - 1, pt[1] - 17.5, f"α = {st.alpha:.0f}° insertion angle", fontsize=LAB_FS, ha="right", va="top")
    Huv, Cuv = uv(fm.H)[0], uv(fm.C03)[0]
    ax.plot(*Huv, "o", ms=2.6, color="black")
    ax.annotate("", xy=Cuv, xytext=Huv, arrowprops=dict(arrowstyle="-|>", lw=0.7, color="black", mutation_scale=7))
    ax.text(Huv[0] + 3, Huv[1] + 1, f"h = {g['h_cut']:.0f} mm resection level", fontsize=LAB_FS, va="bottom")
    label(ax, (Cuv[0] + 7, Cuv[1] - 3), f"collar w = {st.collar_w:.0f} mm", (14, -4), color=ORANGE)
    label(ax, (Cuv[0] - 1, Cuv[1] - 7), f"A0 = {pl['A0']:.0f} mm²: largest size\nthat fits (not a variable)", (24, -14))
    hw = 0.9 * math.sqrt(pl["A0"] * st.lam / math.pi)
    lat = p0 + 0.5 * st.L * du + hw * nu
    label(ax, lat, f"cortical margin\nm = {st.m:+.2f} mm".replace("-", "−"), (-5, -12), ha="right")
    label(ax, pt, "flat tip", (9, -2))
    finish(ax)
    # (b)
    head(fig, 80, 16, "(b) seven section parameters", W, H)
    secs = [("circle", dict(lam=1.0, g_ml=0.5, g_ap=0.5, n_a=2.0, n_p=2.0, tau_a=0.0, tau_p=0.0)),
            ("ellipse λ 1.3 (default)", dict(lam=1.3, g_ml=0.5, g_ap=0.5, n_a=2.0, n_p=2.0, tau_a=0.0, tau_p=0.0)),
            ("asymmetric (base)", {k: S.BASE[k] for k in ("lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")})]
    A0 = pl["A0"]
    for i, (nm, dd) in enumerate(secs):
        axs = fig.add_axes([(80 + i * 36) / W, 1 - (18 + 27) / H, 33 / W, 27 / H])
        xy = G.unit_section(dd, 160) * math.sqrt(A0)
        axs.fill(xy[:, 0], xy[:, 1], fc=BLUE, ec=BLUE, alpha=0.35, lw=0.6)
        axs.plot(np.r_[xy[:, 0], xy[0, 0]], np.r_[xy[:, 1], xy[0, 1]], color=BLUE, lw=0.8)
        axs.axhline(0, color=GREY, lw=0.3, ls=(0, (1, 1.5))); axs.axvline(0, color=GREY, lw=0.3, ls=(0, (1, 1.5)))
        axs.set_xlim(-19, 19); axs.set_ylim(-16, 16); axs.set_aspect("equal"); CR._off(axs)
        axs.set_title(nm, fontsize=6.4, loc="left", pad=2)
        if i == 2:
            xm, xl = xy[:, 0].max(), xy[:, 0].min(); ya, yp = xy[:, 1].max(), xy[:, 1].min()
            axs.annotate("", xy=(xm, -14), xytext=(xl, -14), arrowprops=dict(arrowstyle="<->", lw=0.6, mutation_scale=6))
            axs.text(0, -15.2, "λ = width / thickness", fontsize=5.4, ha="center", va="top")
            axs.text(xm - 1, ya - 1, "n: squareness", fontsize=5.4, ha="right", va="top")
            axs.text(xm - 1, yp + 1, "τ: skew", fontsize=5.4, ha="right", va="bottom")
            axs.text(xl - 0.5, ya + 1.2, "g: widest point", fontsize=5.4, ha="left", va="bottom")
        axs.text(17, 0.8, "medial →", fontsize=5.2, ha="right", va="bottom", color=GREY); axs.text(0.8, 14.5, "ant. ↑", fontsize=5.2, ha="left", va="top", color=GREY)
    # (c)
    head(fig, 80, 58, "(c) two taper parameters: section area along the stem", W, H)
    axt = fig.add_axes([88 / W, 1 - (60 + 24) / H, 78 / W, 24 / H])
    s = np.linspace(0, 1, 200)
    for (rho, q), nm, c in (((0.5, 1.0), "ρ 0.5, q 1 (default)", BLUE), ((0.3, 1.5), "ρ 0.3, q 1.5", "#009E73"), ((0.15, 2.5), "ρ 0.15, q 2.5", "#D55E00")):
        axt.plot(s, rho + (1 - rho) * (1 - s) ** q, color=c, lw=1.2, label=nm)
    axt.set_xlim(0, 1); axt.set_ylim(0, 1.05); axt.set_xlabel("shoulder → tip", fontsize=6); axt.set_ylabel("area / shoulder", fontsize=6)
    axt.tick_params(labelsize=5.8, length=1.5); axt.legend(fontsize=5.8, frameon=False, loc="lower left")
    for s_ in ("top", "right"):
        axt.spines[s_].set_visible(False)
    fig.savefig(OUT / "fig3_parametric_stem.png", dpi=250); plt.close(fig)
    print("fig3 done", flush=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["1", "2", "3"]
    if "1" in which:
        fig_bone_removal()
    if "2" in which:
        fig_fe_setup()
    if "3" in which:
        fig_parametric()
