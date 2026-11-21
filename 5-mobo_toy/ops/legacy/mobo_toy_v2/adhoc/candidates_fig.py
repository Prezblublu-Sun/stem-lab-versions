"""第一阶段九类候选（短/中/长柄 × 无/窄/宽领）的组图：每类画椭圆截面的那个作例子；几何数据写全部 27 个（Linux，只读）。
只用模板化，不等有限元。输出 adhoc/out/classes9.png、candidates.json。"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc"))
import front_shapes as FS  # noqa: E402
from front_shapes import CR, G, ps, plt  # noqa: E402
import collar_shapes as CS  # noqa: E402
import fe3d_geom as E  # noqa: E402

OUT = HOME / "adhoc" / "out"
COL = ps.DORR["A"]
COLLAR_C = "#D55E00"
LEN = {25.0: ("S", "short stem"), 30.0: ("M", "medium stem"), 35.0: ("L", "long stem")}
COLLAR = {0.0: "no collar", 2.0: "narrow collar", 4.0: "wide collar"}
SEC = {"circ": "circular", "ell": "elliptical", "asym": "asymmetric"}
EXAMPLE = "ell"


def name_of(cls: str, L: float, w: float) -> str:
    return "neck_w0" if (cls, L, w) == ("ell", 30.0, 0.0) else f"neck_{cls}_L{L:g}_w{w:g}"


def main():
    ids = json.loads((HOME / "results" / "collar_ids.json").read_text())["jobs"]
    rows = [(L, w) for L in LEN for w in COLLAR]
    fig, axes = ps.new_figure("double", 46 * len(rows), len(rows), 6)
    rec = {}
    fm_img = None
    for L, w in rows:
        klass = f"{LEN[L][0]}{w:g}"
        for cls in SEC:
            k = name_of(cls, L, w)
            spec = FS.spec_of(ids[k])
            st, fm, pl = FS.template(spec)
            g = G.design_of_spec(spec)
            if not pl["fit"]:
                rec[k] = {"job_id": ids[k], "class": klass, "section": SEC[cls], "fit": False, "reason": pl.get("reason"), "L": L, "collar_w": w}
                continue
            info = E.collar_outline(st, fm, pl) if st.has_collar else None
            b = (info["footprint"] if info else E.collar_outline(G.Stem3D(**{**st.__dict__, "collar_w": 0.01}), fm, pl)["footprint"]).bounds
            ml, ap = b[2] - b[0], b[3] - b[1]
            rec[k] = {"job_id": ids[k], "class": klass, "section": SEC[cls], "fit": True, "L": L, "collar_w": w, "collar_t": st.collar_t,
                      "A0": pl["A0"], "e": pl["e"], "alpha": g["alpha"], "lam": g["lam"], "rho_tip": g["rho_tip"], "q": g["q"],
                      "shoulder_ml_mm": ml, "shoulder_ap_mm": ap, "body_volume_mm3": st.volume(pl["A0"]), "s_bind": pl.get("s_bind"),
                      "collar": None if info is None else {kk: v for kk, v in info.items() if kk not in ("poly", "footprint")}}
            if cls != EXAMPLE:
                continue
            r = rows.index((L, w))
            if fm_img is None:
                fm_img = CR.neck_plane_image(fm)
            CR.draw_neck_plane(axes[r, 0], fm, fm_img, st, pl, COL)
            FS.draw_lateral(axes[r, 1], fm, st, pl, COL)
            if info is not None:
                P3 = CS.collar_pts3(fm, info, st.collar_t)
                CS.hull_patch(axes[r, 0], CR._plane_xy(fm, P3), COLLAR_C)
                P0, d, e_ml, e_ap = pl["pose"]
                Q = P3 - P0
                CS.hull_patch(axes[r, 1], np.c_[Q @ e_ap, Q @ d], COLLAR_C)
            CS.draw_top(axes[r, 2], fm, st, pl, info)
            for c, fr in enumerate((0.15, 0.5, 0.85)):
                CR.draw_section(axes[r, c + 3], fm, st, pl, fr, COL)
            txt = (f"Class {klass}: {LEN[L][1]}, {COLLAR[w]}\nexample: elliptical section\nlength {L:.0f} mm, insertion angle {g['alpha']:.0f}°, "
                   f"shoulder {pl['A0']:.0f} mm² ({ml:.0f} × {ap:.0f} mm)\n"
                   + (f"collar {w:.0f} mm: ring {info['ring_mm2']:.0f} mm², {100 * info['ring_cortex_frac']:.0f}% on cortex" if info else "no collar"))
            axes[r, 0].text(0.02, 0.02, txt, transform=axes[r, 0].transAxes, fontsize=4.6, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
    for c, lab_ in enumerate(("coronal view", "side view (anterior → right)", "resection plane, top view", "section 0.15 L",
                              "section 0.50 L", "section 0.85 L")):
        axes[0, c].set_title(lab_, fontsize=6)
    fig.suptitle("Stage 1: nine classes (stem length × collar), elliptical example of each. Collar in orange; blue in the top view = stem cut",
                 fontsize=6.3)
    fig.savefig(OUT / "classes9.png", dpi=200)
    plt.close(fig)
    (OUT / "candidates.json").write_text(json.dumps(rec, indent=1, default=float))
    print(json.dumps({k: {kk: v.get(kk) for kk in ("class", "section", "fit", "A0", "e", "shoulder_ml_mm", "shoulder_ap_mm", "s_bind")}
                      for k, v in rec.items()}, indent=1, default=float))


if __name__ == "__main__":
    main()
