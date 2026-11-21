"""截骨面俯视图（只读，Linux）：骨外轮廓、髓腔（皮质内缘）、柄截口、未裁剪的领（截口外扩 collar_w）、实际的领（与骨外轮廓内缩
COLLAR_CLIP 求交）。回答"领为什么像被切了一刀"：领按规则不得伸出骨面，截口贴近骨边缘的一侧被裁掉。
输出 ~/mobo_toy_v2/deck/collar_plan_view.png 与 collar_plan_view.json（每个设计未裁剪 / 实际领面积、各方向的领宽）。"""
from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import numpy as np  # noqa: E402

import fe3d_geom as E  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

CODES = {"FI": "demo_FI_c166a2e2", "J1": "demo_J1_c2ddbcbd", "B2": "demo_B2_5506a515", "LA": "demo_LA_6b911744",
         "R1": "demo_R1_c6d74566", "R2": "demo_R2_1c6d25d4"}


def width_by_direction(foot, col, n=36):
    """从截口形心沿 n 个方向，领外缘到截口外缘的径向距离（mm）。"""
    from shapely.geometry import LineString
    c = foot.centroid
    out = []
    for a in np.linspace(0, 2 * np.pi, n, endpoint=False):
        ray = LineString([(c.x, c.y), (c.x + 60 * np.cos(a), c.y + 60 * np.sin(a))])
        f = ray.intersection(foot.exterior); g = ray.intersection(col.exterior)
        df = max([c.distance(p) for p in getattr(f, "geoms", [f])] or [0])
        dg = max([c.distance(p) for p in getattr(g, "geoms", [g])] or [0])
        out.append(dg - df)
    return np.array(out)


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(10, 7))
    rep = {}
    for ax, (code, j) in zip(axes.flat, CODES.items()):
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        fm = J.femur_for(spec)
        st = G.Stem3D(**spec["design"])
        pl = G.template(st, fm, margin=spec.get("margin"))
        info = E.collar_outline(st, fm, pl)
        foot, col = info["footprint"], info["poly"]
        raw = foot.buffer(float(st.collar_w), quad_segs=16)
        # 骨外轮廓与皮质内缘（截骨面上）
        from fe3d_geom import _loops, _plane_basis
        C, e1, e2 = _plane_basis(fm)
        g = np.arange(-45, 45.075, 0.15)
        U, V = np.meshgrid(g, g)
        P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
        outer = _loops(fm.outer_sdf(P).reshape(U.shape), g, 0.0)
        canal = _loops(fm.canal_sdf(P).reshape(U.shape), g, 0.0)
        for poly, kw in ([(p, dict(color="#8c564b", lw=1.2, label="bone outline (periosteum)")) for p in outer[:1]] +
                         [(p, dict(color="#d4a017", lw=1.0, ls="--", label="canal (inner cortex)")) for p in canal[:1]] +
                         [(raw, dict(color="grey", lw=0.8, ls=":", label=f"footprint + {st.collar_w:.1f} mm (untrimmed)")),
                          (col, dict(color="#1f77b4", lw=1.6, label="collar as modelled")),
                          (foot, dict(color="black", lw=1.0, label="stem footprint"))]):
            x, y = poly.exterior.xy
            ax.plot(x, y, **kw)
        ax.fill(*col.exterior.xy, color="#1f77b4", alpha=0.15)
        from shapely.geometry import Point
        neck = Point(0.0, 0.0).buffer(float(fm.cfg["prosthesis"]["neck_radius_mm"]), quad_segs=32)   # 假体颈底面，圆心 = 截骨中心
        ax.plot(*neck.exterior.xy, color="#d62728", lw=1.2, label="prosthetic neck base (r 7 mm, on the neck axis)")
        outside = neck.difference(col)
        if outside.area > 0.05:
            for gpart in getattr(outside, "geoms", [outside]):
                ax.fill(*gpart.exterior.xy, color="#d62728", alpha=0.5)
        ax.set_aspect("equal"); ax.set_title(f"{code}: collar {st.collar_w:.1f} mm, kept {100 * (col.area - foot.area) / max(raw.area - foot.area, 1e-9):.0f} % of the ring", fontsize=8)
        ax.set_xlabel("u (mm): + inferomedial (calcar side), - superolateral", fontsize=7); ax.set_ylabel("v (mm): + anterior", fontsize=7)
        w = width_by_direction(foot, col)
        rep[code] = {"collar_w": float(st.collar_w), "untrimmed_ring_mm2": float(raw.area - foot.area), "actual_ring_mm2": float(col.area - foot.area),
                     "ring_kept_frac": float((col.area - foot.area) / max(raw.area - foot.area, 1e-9)),
                     "width_min_mm": float(w.min()), "width_median_mm": float(np.median(w)), "width_max_mm": float(w.max()),
                     "frac_directions_trimmed": float(np.mean(w < 0.9 * st.collar_w)), "ring_cortex_frac": info["ring_cortex_frac"]}
    axes.flat[0].legend(fontsize=6, loc="lower left")
    fig.suptitle("Cut-plane view: collar (blue) built around the stem footprint; red circle = prosthetic neck base; red fill = neck base outside the collar", fontsize=9)
    fig.tight_layout()
    fig.savefig(HOME / "deck" / "collar_plan_view.png", dpi=180)
    (HOME / "deck" / "collar_plan_view.json").write_text(json.dumps(rep, indent=1))
    for k, v in rep.items():
        print(k, {a: round(b, 2) for a, b in v.items()})


if __name__ == "__main__":
    main()
