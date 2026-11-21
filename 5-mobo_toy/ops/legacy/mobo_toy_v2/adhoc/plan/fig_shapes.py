"""Best stem in each length class (knee of the two-axis front below the 20 µm threshold): coronal placement, two 3-D views,
shoulder and tip cross-sections on a common scale. Linux, read-only on the queue:
    run.sh adhoc/plan/fig_shapes.py   → adhoc/plan/out/fig9_best_shapes.png
Picks (interim report v15, all_designs.json): short 25–30 mm = 30 mm asymmetric, 3 mm collar (screening);
medium 30–40 mm = 38.4 mm ellipse, 3.4 mm collar, cut 27.8 mm (Round 1); long > 40 mm = 48.8 mm thin stem (Round 2).
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "plan")); sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import plan_figs as PF  # noqa: E402
from plan_figs import R2, R3, G, CR, ps, plt, J  # noqa: E402
import fig_maps as FM  # noqa: E402

OUT = HOME / "adhoc" / "plan" / "out"
PICK = [("collar_neck_asym_w3_4f71e698", "short (25–30 mm): 30 mm"),
        ("neck1_init_c4fca4ea", "medium (30–40 mm): 38 mm"),
        ("neck2_r11_8687e375", "long (> 40 mm): 49 mm")]
TITLE = "Best stem in each length class: the longer it is, the slimmer it ends up"
SEC_LIM = 14.0


def numbers(job):
    fe = PF.fe_full(job); g, spec = PF.geo_of(job)
    st, pl = g["st"], g["pl"]
    mm = fe.get("f1_all_p95_um") or fe["f1_p95_um"]
    return g, dict(bone=fe["bone_loss_mm3"] / 1000, band=FM.band_res(job), mm=mm, L=st.L, alpha=float(pl["alpha"]),
                   w=float(getattr(st, "collar_w", 0.0)), h=float(spec.get("h_cut", 25.0)), A0=float(pl["A0"]),
                   m=float(getattr(st, "m", -0.25)), rho=float(st.rho_tip), q=float(st.q))


def main():
    cols = [(lab, *numbers(job)) for job, lab in PICK]
    for lab, g, n in cols:
        print(lab, {k: round(v, 2) for k, v in n.items()}, flush=True)
    left, cw = 6.0, 61.0
    W = left + 3 * cw + 2.0
    pw = cw - 4.0
    h_main = 44.0
    h_cor = (pw / 2) * (FM.COR_V[1] - FM.COR_V[0]) / (R2.EXT[0][1] - R2.EXT[0][0])
    hs, gap, top = 24.0, 2.5, 14.0
    H = top + h_main + h_cor + hs + 3 * gap + 15.0
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    X = lambda mm: mm / W
    Y = lambda mm_from_top: 1.0 - mm_from_top / H
    fig.text(X(4), Y(3.0), TITLE, fontsize=9.5, fontweight="bold", va="top")
    centre = R3.view_centre()
    for c, (lab, g, n) in enumerate(cols):
        x0 = left + c * cw
        fig.text(X(x0), Y(top - 1.5), lab, fontsize=7.0, fontweight="bold", va="bottom")
        y = top
        polys = R3.stem_polys(g)[0]
        ctr = np.vstack(polys).mean(0)                     # centre each stem; same half-width = same scale for all three
        ax = fig.add_axes([X(x0), Y(y + h_main), X(pw), h_main / H], projection="3d")
        R3.draw_3d(ax, g, None, ctr, half=36.0)
        y += h_main + gap
        ax = fig.add_axes([X(x0), Y(y + h_cor), X(pw / 2), h_cor / H], projection="3d")
        R3.draw_3d(ax, g, None, ctr, half=40.0)
        ax.view_init(elev=5.0, azim=R3.AZIM + 90.0)
        fig.text(X(x0 + 1), Y(y + 1.0), "side view", fontsize=6.0, color="#555555", va="top")
        ax = fig.add_axes([X(x0 + pw / 2), Y(y + h_cor), X(pw / 2), h_cor / H])
        R2.draw_coronal(ax, g); ax.set_ylim(*FM.COR_V)
        fig.text(X(x0 + pw / 2 + 1), Y(y + 1.0), "in the femur", fontsize=6.0, color="#555555", va="top")
        y += h_cor + gap
        ax = fig.add_axes([X(x0 + 2), Y(y + hs), X(hs), hs / H])
        sec = G.unit_section(g["st"].d)
        for scale, ls in ((math.sqrt(n["A0"]), "-"), (math.sqrt(n["A0"] * n["rho"]), (0, (2, 1.5)))):
            pts = scale * np.vstack([sec, sec[:1]])
            ax.plot(pts[:, 0], pts[:, 1], color=R2.STEM_C, lw=1.0, ls=ls)
        ax.set_xlim(-SEC_LIM, SEC_LIM); ax.set_ylim(-SEC_LIM, SEC_LIM); ax.set_aspect("equal"); ax.set_axis_off()
        if c == 2:
            ax.plot([SEC_LIM - 11, SEC_LIM - 1], [-SEC_LIM + 1] * 2, color="black", lw=1.0)
            ax.text(SEC_LIM - 6, -SEC_LIM + 2.2, "10 mm", fontsize=5.8, ha="center", va="bottom")
        fig.text(X(x0 + hs + 5), Y(y + hs * 0.5), f"cross-sections{chr(10)}shoulder {n['A0']:.0f} mm² (solid){chr(10)}tip {n['A0'] * n['rho']:.0f} mm² (dashed)",
                 fontsize=5.9, va="center", color="#444444", linespacing=1.35)
        y += hs + gap
        key = (f"{n['bone']:.1f} cm³  ·  risk {n['band']:.0f} %  ·  {n['mm']:.1f} µm{chr(10)}"
               f"collar {n['w']:.1f} mm  ·  cut {n['h']:.1f} mm  ·  margin {n['m']:+.2f} mm").replace("-", "−")
        fig.text(X(x0), Y(y + 1), key, fontsize=6.4, fontweight="bold", va="top", linespacing=1.35)
    fig.text(X(left), Y(H - 4.0), "risk = low-strain-energy fraction in the 10 mm band below the cut; micromotion = P95, stem body + collar face",
             fontsize=5.9, color="#444444", va="top")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig9_best_shapes.png", dpi=250)
    plt.close(fig)
    print("written", OUT / "fig9_best_shapes.png", flush=True)


if __name__ == "__main__":
    main()
