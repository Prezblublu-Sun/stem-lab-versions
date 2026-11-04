"""代表设计的整柄图（Linux，只读）：命令行给 作业id:标签 列表；每行 冠状面 / 侧视 / 截骨面俯视 / 三个截面。输出 adhoc/out/reps_<name>.png + json。"""
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
name = sys.argv[1]
items = [a.split(":", 1) for a in sys.argv[2:]]
fig, axes = ps.new_figure("double", 46 * len(items), len(items), 6)
axes = np.atleast_2d(axes)
rec = {}
img = None
for r, (job, lab) in enumerate(items):
    spec = FS.spec_of(job)
    st, fm, pl = FS.template(spec)
    if img is None:
        img = CR.neck_plane_image(fm)
    info = E.collar_outline(st, fm, pl) if st.has_collar else None
    CR.draw_neck_plane(axes[r, 0], fm, img, st, pl, COL, arrow=(r == 0))
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
    g = G.design_of_spec(spec)
    txt = (f"{lab}\nL {g['L']:.0f} mm, α {g['alpha']:.0f}°, cut {spec.get('h_cut', 25):.0f} mm, margin {g.get('m', -0.25):+.2f} mm\n"
           f"shoulder {pl['A0']:.0f} mm², λ {g['lam']:.2f}, tip ratio {g['rho_tip']:.2f}\n"
           + (f"collar {st.collar_w:.1f} mm: ring {info['ring_mm2']:.0f} mm², {100 * info['ring_cortex_frac']:.0f}% on cortex" if info else "no collar"))
    axes[r, 0].text(0.02, 0.02, txt, transform=axes[r, 0].transAxes, fontsize=4.6, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
    rec[job] = {"label": lab, "A0": pl["A0"], "e": pl["e"], "design": g, "h_cut": spec.get("h_cut", 25.0), "body_volume_mm3": st.volume(pl["A0"]),
                "collar": None if info is None else {k: v for k, v in info.items() if k not in ("poly", "footprint")}}
for c, lab_ in enumerate(("coronal view", "side view (anterior → right)", "resection plane, top view", "section 0.15 L", "section 0.50 L", "section 0.85 L")):
    axes[0, c].set_title(lab_, fontsize=6)
fig.suptitle(f"{name}: representative designs (collar in orange; blue in the top view = stem cut)", fontsize=6.3)
fig.savefig(OUT / f"reps_{name}.png", dpi=200)
plt.close(fig)
(OUT / f"reps_{name}.json").write_text(json.dumps(rec, indent=1, default=float))
print("ok", OUT / f"reps_{name}.png")
