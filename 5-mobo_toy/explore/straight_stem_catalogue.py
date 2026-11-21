"""直柄目录的整体演示：1024 根 Sobol 柄（与股骨无关的绝对尺寸）逐一模板化进 Dorr A/B/C，
看每型有多少能放进去、放不进去的原因、同一根柄能服务几种骨形，再从每型的可用柄里挑 4 根形状各异的展示。
只做几何，不跑 FE；FE + BO 之后在"每型可用子集"上做选择。"""
from __future__ import annotations

import csv
import json
import pathlib
import sys
from multiprocessing import Pool

import numpy as np
from matplotlib.patches import FancyArrowPatch
from matplotlib.patches import Polygon as MP
from scipy.cluster.vq import kmeans2
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur2d as F  # noqa: E402
import plotstyle as ps  # noqa: E402
import straight_stem as SS  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
N = 1024
SEED = 11
OUTCOME_COLOR = {"too small": "#BBBBBB", "blocked": "#555555", "tip out of bone": "#CC79A7"}
_FEMURS: dict = {}


def _femur(t):
    if t not in _FEMURS:
        _FEMURS[t] = F.build(t)
    return _FEMURS[t]


def work(job):
    i, t, params = job
    pl = SS.seat(SS.StraightStem(**params), _femur(t))
    row = {"i": i, "dorr": t, **params, "fit": pl["fit"]}
    if pl["fit"]:
        row.update(code="fit", alpha=pl["alpha"], e=pl["e"], z=pl["z"], fill=pl["fill"])
    else:
        row.update(code=pl["code"], alpha=np.nan, e=np.nan, z=np.nan, fill=np.nan)
    return row


def draw_placed(ax, st, f, t, pl, label):
    for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
        ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
    ax.plot(*np.asarray(f.cut_segment().coords).T, color="#D55E00", lw=0.8)
    kept = f.outer.intersection(f.kept_halfplane())
    fin = pl["poly"].intersection(kept)
    for g in getattr(fin, "geoms", [fin]):
        if g.geom_type == "Polygon":
            ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=ps.DORR[t], ec=ps.DORR[t], alpha=0.8))
    p0 = pl["P0"] - 50 * pl["d"]
    ax.add_patch(FancyArrowPatch(tuple(p0), tuple(p0 + 25 * pl["d"]), arrowstyle="-|>", mutation_scale=7,
                                 color="black", lw=0.8))
    ax.text(0.02, 0.02, label, transform=ax.transAxes, fontsize=5.2, va="bottom",
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.0))
    ax.set_xlim(-40, 70); ax.set_ylim(-95, 95); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)


def main():
    import matplotlib.pyplot as plt
    U = qmc.Sobol(len(SS.VARS), scramble=True, seed=SEED).random(N)
    cat = [SS.from_unit(u) for u in U]
    jobs = [(i, t, cat[i]) for t in "ABC" for i in range(N)]
    with Pool(8) as pool:
        rows = pool.map(work, jobs, chunksize=16)
    with open(OUT / "catalogue_templating.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    by = {t: {r["i"]: r for r in rows if r["dorr"] == t} for t in "ABC"}
    fitset = {t: {i for i, r in by[t].items() if r["fit"]} for t in "ABC"}

    # ---------- 图 1：可行性图 + 重叠
    fig, axes = ps.new_figure("double", 62, 1, 4)
    for ax, t in zip(axes[:3], "ABC"):
        for code, col in list(OUTCOME_COLOR.items()) + [("fit", ps.DORR[t])]:
            pts = [r for r in by[t].values() if r["code"] == code]
            if pts:
                ax.scatter([r["L"] for r in pts], [r["w_mp"] + r["w_lp"] for r in pts], s=3 if code != "fit" else 5,
                           c=col, lw=0, label=f"{'fits' if code == 'fit' else code} ({len(pts)})",
                           zorder=3 if code == "fit" else 2)
        ax.set_xlabel("length L (mm)")
        ax.set_title(f"Dorr {t}: {len(fitset[t])}/{N} fit", fontsize=7)
        ax.legend(fontsize=4.8, loc="upper right", markerscale=1.5, handletextpad=0.2, borderpad=0.3)
        ax.set_xlim(38, 92); ax.set_ylim(9, 27)
    axes[0].set_ylabel("proximal width  w_mp + w_lp (mm)")
    sets = {"A only": fitset["A"] - fitset["B"] - fitset["C"], "B only": fitset["B"] - fitset["A"] - fitset["C"],
            "C only": fitset["C"] - fitset["A"] - fitset["B"], "A∩B only": (fitset["A"] & fitset["B"]) - fitset["C"],
            "B∩C only": (fitset["B"] & fitset["C"]) - fitset["A"], "A∩C only": (fitset["A"] & fitset["C"]) - fitset["B"],
            "A∩B∩C": fitset["A"] & fitset["B"] & fitset["C"]}
    ax = axes[3]
    ax.barh(list(sets)[::-1], [len(v) for v in sets.values()][::-1], color="#7F7F7F")
    for y, v in enumerate([len(v) for v in sets.values()][::-1]):
        ax.text(v, y, f" {v}", va="center", fontsize=5.5)
    ax.set_xlabel("catalogue stems")
    ax.tick_params(axis="y", labelsize=5.5)
    ax.set_title("which femurs each stem fits", fontsize=7)
    fig.suptitle(f"{N} catalogue stems templated into each femur (geometry only): "
                 f"{len(fitset['A'] | fitset['B'] | fitset['C'])} fit at least one type", fontsize=7)
    fig.savefig(OUT / "catalogue_feasibility.png", dpi=200)
    plt.close(fig)

    # ---------- 图 2：每型 4 根形状各异的可用柄
    fig, axes = ps.new_figure("double", 150, 3, 4)
    picks = {}
    for r_, t in enumerate("ABC"):
        ids = sorted(fitset[t])
        X = U[ids]
        k = min(4, len(ids))
        _, lab = kmeans2(X, k, seed=SEED, minit="++")
        chosen = []
        for c in range(k):
            mem = [ids[j] for j in range(len(ids)) if lab[j] == c]
            if mem:
                chosen.append(max(mem, key=lambda i: by[t][i]["fill"]))
        picks[t] = chosen
        f = _femur(t)
        for c_, ax in enumerate(axes[r_]):
            if c_ >= len(chosen):
                ax.axis("off")
                continue
            i = chosen[c_]
            st = SS.StraightStem(**cat[i])
            pl = SS.seat(st, f)
            also = "".join(o for o in "ABC" if o != t and i in fitset[o])
            draw_placed(ax, st, f, t, pl,
                        f"#{i}: L {st.L:.0f}, med {st.w_mp:.1f}/lat {st.w_lp:.1f}, tip {st.w_tip:.1f}\n"
                        f"α {pl['alpha']:.1f}°, sink {pl['z']:.1f} mm, fill {pl['fill']:.0%}\n"
                        f"also fits: {', '.join(also) if also else 'none'}")
            if c_ == 0:
                ax.set_ylabel(f"Dorr {t}", fontsize=7)
                ax.yaxis.set_visible(True)
    fig.suptitle("Four dissimilar catalogue stems that fit each femur (k-means on the design vector of the fitting subset; best fill per cluster)",
                 fontsize=7)
    fig.savefig(OUT / "catalogue_picks.png", dpi=180)
    plt.close(fig)

    summary = {"N": N, "seed": SEED, "ranges": SS.RANGES,
               "fit": {t: len(fitset[t]) for t in "ABC"},
               "fail_codes": {t: {c: sum(1 for r in by[t].values() if r["code"] == c) for c in OUTCOME_COLOR} for t in "ABC"},
               "overlap": {k: len(v) for k, v in sets.items()},
               "picks": picks,
               "fit_L_range": {t: [min(by[t][i]["L"] for i in fitset[t]), max(by[t][i]["L"] for i in fitset[t])]
                               for t in "ABC" if fitset[t]}}
    (OUT / "catalogue_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
