"""带领、椭圆截面设计的整柄形状图（Linux，只读）：冠状面、侧面、截骨面俯视（领的外形与柄的截口）、三个横截面。"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc"))
import front_shapes as FS  # noqa: E402  （同目录，复用它的取图函数）
from front_shapes import CR, FR, G, MP, ps, plt  # noqa: E402
import fe3d_geom as E  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402

OUT = HOME / "adhoc" / "out"
COL = ps.DORR["A"]
COLLAR_C = "#D55E00"


def collar_pts3(fm, info, t):
    C, e1, e2, nrm = E.cut_plane(fm)
    uv = np.array(info["poly"].exterior.coords)
    bot = C + uv[:, :1] * e1 + uv[:, 1:2] * e2
    return np.vstack([bot, bot + t * nrm])


def hull_patch(ax, xy, color):
    h = ConvexHull(xy)
    ax.add_patch(MP(xy[h.vertices], closed=True, fc=color, ec=color, alpha=0.9))


def draw_top(ax, fm, st, pl, info):
    C, e1, e2, nrm = E.cut_plane(fm)
    g = np.arange(-30, 30.01, 0.15)
    U, V = np.meshgrid(g, g)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    lab = np.where(fm.canal_sdf(P) <= 0, 2, np.where(fm.outer_sdf(P) <= 0, 1, 0)).reshape(U.shape)
    ax.imshow(CR._rgb(lab, np.ones_like(lab, bool)), origin="lower", extent=(g[0], g[-1], g[0], g[-1]), interpolation="nearest")
    if info is not None:
        ax.add_patch(MP(np.array(info["poly"].exterior.coords), closed=True, fc=COLLAR_C, ec=COLLAR_C, alpha=0.55))
        foot = info["footprint"]
    else:
        foot = E.collar_outline(G.Stem3D(**{**st.__dict__, "collar_w": 0.01}), fm, pl)["footprint"]
    ax.add_patch(MP(np.array(foot.exterior.coords), closed=True, fc=COL, ec=COL, alpha=0.9))
    ax.set_xlim(-30, 30); ax.set_ylim(-30, 30); ax.set_aspect("equal"); CR._off(ax)


def main():
    ids = json.loads((HOME / "results" / "collar_ids.json").read_text())["jobs"]
    names = list(ids)
    fig, axes = ps.new_figure("double", 46 * len(names), len(names), 6)
    rec = {}
    for r, k in enumerate(names):
        spec = FS.spec_of(ids[k])
        st, fm, pl = FS.template(spec)
        info = E.collar_outline(st, fm, pl) if st.has_collar else None
        img = CR.neck_plane_image(fm)
        CR.draw_neck_plane(axes[r, 0], fm, img, st, pl, COL)
        FS.draw_lateral(axes[r, 1], fm, st, pl, COL)
        if info is not None:
            P3 = collar_pts3(fm, info, st.collar_t)
            hull_patch(axes[r, 0], CR._plane_xy(fm, P3), COLLAR_C)
            P0, d, e_ml, e_ap = pl["pose"]
            Q = P3 - P0
            hull_patch(axes[r, 1], np.c_[Q @ e_ap, Q @ d], COLLAR_C)
        draw_top(axes[r, 2], fm, st, pl, info)
        for c, fr in enumerate((0.15, 0.5, 0.85)):
            CR.draw_section(axes[r, c + 3], fm, st, pl, fr, COL)
        g = G.design_of_spec(spec)
        sec = "ellipse" if G.is_ellipse(spec["design"]) else "asymmetric section"
        txt = (f"{k}\nL {g['L']:.0f} mm, α {g['alpha']:.0f}°, {sec}\nshoulder {pl['A0']:.0f} mm²\n"
               + (f"collar {st.collar_w:.0f} mm: ring {info['ring_mm2']:.0f} mm², {100 * info['ring_cortex_frac']:.0f}% on cortex"
                  if info else "no collar"))
        axes[r, 0].text(0.02, 0.02, txt, transform=axes[r, 0].transAxes, fontsize=4.6, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
        rec[k] = {"A0": pl["A0"], "e": pl["e"], "collar": None if info is None else
                  {kk: v for kk, v in info.items() if kk not in ("poly", "footprint")}}
    for c, lab_ in enumerate(("coronal view", "side view (anterior → right)", "resection plane, top view", "section 0.15 L",
                              "section 0.50 L", "section 0.85 L")):
        axes[0, c].set_title(lab_, fontsize=6)
    fig.suptitle("Collared and elliptical stems (orange = collar on the resection plane; blue in the top view = stem cut)", fontsize=6.3)
    fig.savefig(OUT / "collar_shapes.png", dpi=200)
    plt.close(fig)
    (OUT / "collar_shapes.json").write_text(json.dumps(rec, indent=1, default=float))
    print(json.dumps(rec, indent=1, default=float))


if __name__ == "__main__":
    main()
