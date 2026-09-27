"""直柄目录的案例图：(1) 目录图册；(2) 几根柄在 Dorr A/B/C 中的模板化放置。"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np
from matplotlib.patches import FancyArrowPatch
from matplotlib.patches import Polygon as MP
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur2d as F  # noqa: E402
import plotstyle as ps  # noqa: E402
import straight_stem as SS  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


def gallery(stems, path):
    import matplotlib.pyplot as plt
    n = len(stems)
    fig, axes = ps.new_figure("double", 88, 1, n, sharey=True)
    for i, (ax, (k, st)) in enumerate(zip(axes.flat, stems.items())):
        poly = st.local_polygon(s_top=0.0)
        ax.add_patch(MP(np.asarray(poly.exterior.coords), closed=True, fc="#9BB8D3", ec="#1f4e79", lw=0.6))
        ax.axvline(0, color=ps.GREY, lw=0.4, ls=":")
        ax.set_xlim(-16, 16); ax.set_ylim(-115, 5); ax.set_aspect("equal")
        ax.set_xticks([-10, 0, 10]); ax.set_yticks([0, -25, -50, -75, -100])
        ax.tick_params(labelsize=5.5)
        ax.set_title(f"{k}\nL {st.L:.0f}\nmed {st.w_mp:.1f} / lat {st.w_lp:.1f}\ntip {st.w_tip:.1f}", fontsize=5.5)
        ax.text(0.97, 0.02, "med →", transform=ax.transAxes, ha="right", fontsize=5, color=ps.GREY)
    axes.flat[0].set_ylabel("axial position from shoulder (mm)", fontsize=6)
    fig.suptitle("Catalogue examples (Sobol draws): straight axis, independent medial and lateral half-widths, mm in the stem's own frame",
                 fontsize=7)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def seating(stems, path):
    import matplotlib.pyplot as plt
    names = list(stems)
    fig, axes = ps.new_figure("double", 55 * len(names), len(names), 3)
    info = []
    for r, k in enumerate(names):
        st = stems[k]
        for c, t in enumerate("ABC"):
            ax = axes[r, c]
            f = F.build(t)
            for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
            ax.plot(*np.asarray(f.cut_segment().coords).T, color="#D55E00", lw=1.0)
            pl = SS.seat(st, f)
            if pl["fit"]:
                for back in (60, 40, 20):
                    g = st.placed(pl["P0"], pl["alpha"], pl["z"] - back)
                    ax.plot(*np.asarray(g.exterior.coords).T, color=ps.GREY, lw=0.4)
                kept = f.outer.intersection(f.kept_halfplane())
                fin = pl["poly"].intersection(kept)
                for g in getattr(fin, "geoms", [fin]):
                    ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=ps.DORR[t], ec=ps.DORR[t], alpha=0.8))
                out = pl["poly"].difference(kept)
                for g in getattr(out, "geoms", [out]):
                    if g.geom_type == "Polygon" and g.area > 0.1:
                        ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc="none", ec=ps.DORR[t], lw=0.6, ls="--"))
                p0 = pl["P0"] - 55 * pl["d"]
                ax.add_patch(FancyArrowPatch(tuple(p0), tuple(p0 + 30 * pl["d"]), arrowstyle="-|>", mutation_scale=9,
                                             color="black", lw=1.0))
                oc = SS.translation_overcut(st, f, pl)
                txt = (f"fits: α {pl['alpha']:.1f}°, offset {pl['e']:+.1f} mm\nsink {pl['z']:.1f} mm, fill {pl['fill']:.0%}"
                       f"\novercut {oc:.2f} mm²")
                info.append({"stem": k, "dorr": t, "fit": True, "alpha": pl["alpha"], "offset": pl["e"],
                             "sink": pl["z"], "fill": pl["fill"], "overcut_mm2": oc})
            else:
                txt = f"does not fit: {pl['reason']}"
                info.append({"stem": k, "dorr": t, "fit": False, "reason": pl["reason"], "code": pl["code"]})
            ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=5.8, va="bottom",
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.2))
            ax.set_xlim(-40, 70); ax.set_ylim(-105, 95); ax.set_aspect("equal")
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
            for sp in ax.spines.values():
                sp.set_visible(False)
            if r == 0:
                ax.set_title(f"Dorr {t}", fontsize=8)
        axes[r, 0].set_ylabel(k, fontsize=7)
        axes[r, 0].yaxis.set_visible(True)
    fig.suptitle("Same catalogue stems templated into each femur: straight insertion (arrow), pushed in until they wedge",
                 fontsize=8)
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return info


def main():
    U = qmc.Sobol(6, scramble=True, seed=5).random(8)
    cat = {f"S{i + 1}": SS.StraightStem(**SS.from_unit(u)) for i, u in enumerate(U)}
    gallery(cat, OUT / "catalogue_gallery.png")
    hand = {
        "slim symmetric": SS.StraightStem(L=70, w_mp=8, w_lp=8, w_tip=3.5, p_m=1.0, p_l=1.0),
        "calcar-curved medial": SS.StraightStem(L=65, w_mp=13, w_lp=7, w_tip=3.5, p_m=2.5, p_l=0.8),
        "wide, short": SS.StraightStem(L=45, w_mp=12, w_lp=10, w_tip=5, p_m=1.5, p_l=1.2),
        "lateral-flared": SS.StraightStem(L=80, w_mp=8, w_lp=10, w_tip=4, p_m=1.0, p_l=2.0),
    }
    info = seating(hand, OUT / "templating_ABC.png")
    (OUT / "templating_ABC.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    for i in info:
        print(i)


if __name__ == "__main__":
    main()
