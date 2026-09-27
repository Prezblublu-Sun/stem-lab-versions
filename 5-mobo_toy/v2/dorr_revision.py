"""对比 v1 的 Dorr 参数与 v2 建议参数下的 2D 股骨：v1 固定外形、按 CFI 反推干骺端髓腔宽，C 型干骺端皮质反而最厚；
v2 建议让干骺端髓腔宽 A→C 递增（46 / 48 / 50 mm）、峡部皮质指数 A→C 递减，三型都仍落在各自 Dorr 判据区间内。"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from matplotlib.patches import Polygon as MP

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import femur2d as F  # noqa: E402
import plotstyle as ps  # noqa: E402

PROPOSED = {"A": {"cfi": 4.87, "ci": 0.65}, "B": {"cfi": 3.78, "ci": 0.53}, "C": {"cfi": 2.89, "ci": 0.36}}


def build_with(params: dict | None):
    F.build.cache_clear()
    saved = {t: dict(F.CFG["dorr"][t]) for t in "ABC"}
    try:
        if params:
            for t, p in params.items():
                F.CFG["dorr"][t].update(p)
        return {t: F.build(t) for t in "ABC"}
    finally:
        for t in "ABC":
            F.CFG["dorr"][t].clear(); F.CFG["dorr"][t].update(saved[t])
        F.build.cache_clear()


def main():
    import matplotlib.pyplot as plt
    sets = {"v1 (current)": build_with(None), "v2 proposal": build_with(PROPOSED)}
    fig, axes = ps.new_figure("double", 120, 2, 3)
    rec = {}
    for r, (name, fs) in enumerate(sets.items()):
        rec[name] = {}
        for c, t in enumerate("ABC"):
            f = fs[t]
            m = f.measured
            ax = axes[r, c]
            for g, fc in ((f.outer, "#C9C9C9"), (f.inner, "#F3E3C3")):
                ax.add_patch(MP(np.asarray(g.exterior.coords), closed=True, fc=fc, ec="none"))
            z20 = F.CFG["femur"]["cfi_level_z"]
            ax.axhline(z20, color=ps.DORR[t], lw=0.6, ls="--")
            ax.set_xlim(-40, 70); ax.set_ylim(-150, 95); ax.set_aspect("equal")
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
            for sp in ax.spines.values():
                sp.set_visible(False)
            band = F.dorr_band("cfi", m["cfi"]) + F.dorr_band("ci", m["ci"])
            ax.set_title(f"{name}: Dorr {t}", fontsize=6.5)
            ax.text(0.02, 0.02, f"CFI {m['cfi']:.2f}, CI {m['ci']:.2f} (bands {band[0]}/{band[1]})\n"
                    f"canal at LT+20 {m['canal20_mm']:.1f} mm\nwall at LT+20: med {m['wall20_medial_mm']:.1f} / lat {m['wall20_lateral_mm']:.1f} mm\n"
                    f"isthmus canal {m['canal_isthmus_mm']:.1f} mm", transform=ax.transAxes, fontsize=5,
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
            rec[name][t] = {k: round(float(v), 3) for k, v in m.items()} | {"bands": band}
    fig.suptitle("Dorr parameters: v1 makes Dorr C's metaphyseal cortex the thickest (dashed = LT+20 mm); "
                 "v2 proposal thins the cortex from A to C in both metaphysis and diaphysis", fontsize=6.5)
    fig.savefig(HERE / "out" / "v2_dorr_revision.png", dpi=200)
    plt.close(fig)
    (HERE / "out" / "v2_dorr_revision.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
