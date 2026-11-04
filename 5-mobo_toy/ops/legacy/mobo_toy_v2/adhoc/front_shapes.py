"""前沿设计的整柄形状图（在 Linux 上跑，只读）：每个设计一行，五格
   颈平面视图（冠状面方向）、垂直于颈平面且含柄轴的侧视图（前后方向）、0.15 / 0.50 / 0.85 L 三个横截面。
设计从队列里的 spec.json 读出，按作业时的规则重新模板化；与作业记录的肩部面积核对。
输出：~/mobo_toy_v2/adhoc/out/front_shapes_*.png 与 front_shapes.json
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import plotstyle as ps  # noqa: E402
import cases_real as CR  # noqa: E402
import stage_v2a as S  # noqa: E402
from matplotlib.patches import Polygon as MP  # noqa: E402

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
OUT = pathlib.Path.home() / "mobo_toy_v2" / "adhoc" / "out"
OUT.mkdir(parents=True, exist_ok=True)
plt = ps.plt

V2A_FRONT = [(57.581, 30.585), (57.024, 27.911), (55.664, 29.433), (59.93, 25.701), (54.84, 33.378), (64.302, 23.922)]
V3_FRONT = ["bo_qnehvi_s1_r0_62bbf792", "ref_r51_h2_944c4554", "ref_r2_h2_2dce8f64", "ref_r9_h2_e3e0f7ad"]
REPS = [("base", None), ("Design B", "bo_qnehvi_s1_r0_62bbf792"), ("short stem", "probe_L25_12_e265f0bf")]


def spec_of(job):
    return json.loads((Q / job / "spec.json").read_text())


def find_v2a(L, a):
    hits = []
    for d in Q.glob("*"):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        s = json.loads(sp.read_text())
        if s.get("kind") != "design" or s.get("h_int") != 2.0 or s.get("model") is not None:
            continue
        if any(s.get(k) is not None for k in ("delta", "mu", "E_canc", "rep", "h_cut")) or s.get("torque", True) is False:
            continue
        g = G.design_of_spec(s)
        if abs(g["L"] - L) < 2e-3 and abs(g["alpha"] - a) < 2e-3:
            hits.append(d.name)
    return sorted(hits)


def template(spec):
    st = G.Stem3D(**spec["design"])
    fm = FR.build()
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(spec["h_cut"])
    pl = G.template(st, fm, margin=spec.get("margin"))
    pl["pose"] = fm.pose(pl["alpha"], pl["e"])
    return st, fm, pl


def lateral_image(fm, pl, ext=((-40.0, 40.0), (-25.0, 105.0)), h=0.3):
    """含柄轴、垂直于颈平面的平面：横轴 e_ap（前方为正），纵轴沿柄轴向远端为正（图里朝下画）。"""
    P0, d, e_ml, e_ap = pl["pose"]
    a = np.arange(ext[0][0], ext[0][1], h)
    b = np.arange(ext[1][0], ext[1][1], h)
    A, B = np.meshgrid(a, b)
    P = P0 + A.reshape(-1, 1) * e_ap + B.reshape(-1, 1) * d
    lab = np.where(fm.canal_sdf(P) <= 0, 2, np.where(fm.outer_sdf(P) <= 0, 1, 0)).reshape(A.shape)
    kept = fm.below_cut(P).reshape(A.shape)
    return a, b, lab, kept


def lateral_silhouette(st, pl):
    sec = G.unit_section(st.d, 160)
    s = np.linspace(0, st.L, 90)
    k = np.sqrt(pl["A0"] * st.area_ratio(s))
    ant, post = k * sec[:, 1].max(), k * sec[:, 1].min()
    tip = st.L + st.cap_length(pl["A0"])
    return np.r_[np.c_[ant, s], [[0.0, tip]], np.c_[post[::-1], s[::-1]]]


def draw_lateral(ax, fm, st, pl, color):
    a, b, lab, kept = lateral_image(fm, pl)
    ax.imshow(CR._rgb(lab, kept), origin="upper", extent=(a[0], a[-1], b[-1], b[0]), interpolation="nearest")
    ax.add_patch(MP(lateral_silhouette(st, pl), closed=True, fc=color, ec=color, alpha=0.85))
    ax.set_xlim(a[0], a[-1]); ax.set_ylim(b[-1], b[0]); ax.set_aspect("equal")
    CR._off(ax)


def figure(rows, path, title):
    img = None
    fig, axes = ps.new_figure("double", 52 * len(rows), len(rows), 5)
    axes = np.atleast_2d(axes)
    col = ps.DORR["A"]
    rec = []
    for r, (name, job, spec, note) in enumerate(rows):
        st, fm, pl = template(spec)
        img = CR.neck_plane_image(fm)
        CR.draw_neck_plane(axes[r, 0], fm, img, st, pl, col)
        draw_lateral(axes[r, 1], fm, st, pl, col)
        for c, fr in enumerate((0.15, 0.5, 0.85)):
            CR.draw_section(axes[r, c + 2], fm, st, pl, fr, col)
        g = G.design_of_spec(spec)
        res = json.loads((Q / job / "result.json").read_text()) if job and (Q / job / "result.json").exists() else {}
        a0_job = (res.get("templating") or {}).get("A0")
        axes[r, 0].text(0.02, 0.02, f"{name}\nL {g['L']:.0f} mm, α {g['alpha']:.0f}°\nshoulder {pl['A0']:.0f} mm², margin {g['m']:+.2f} mm\n"
                        f"cut {fm.cut_from_head_mm:.0f} mm from head\n{note}",
                        transform=axes[r, 0].transAxes, fontsize=4.6, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
        rec.append({"name": name, "job": job, "L": g["L"], "alpha": g["alpha"], "m": g["m"], "h_cut": fm.cut_from_head_mm,
                    "A0": pl["A0"], "A0_job": a0_job, "e": pl["e"], "s_bind": pl["s_bind"], "contact": pl["contact"],
                    "volume": pl["volume"], "f1_old": res.get("f1_p95_um"), "design": spec["design"]})
    for c, lab_ in enumerate(("coronal view (neck plane)", "side view (anterior → right)", "section 0.15 L", "section 0.50 L", "section 0.85 L")):
        axes[0, c].set_title(lab_, fontsize=6)
    fig.suptitle(title, fontsize=6.3)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return rec


def main():
    out = {}
    rows = []
    for i, (L, a) in enumerate(V2A_FRONT):
        hits = find_v2a(L, a)
        job = hits[0] if hits else None
        out.setdefault("v2a_matches", []).append({"k": i, "L": L, "alpha": a, "jobs": hits})
        if job:
            rows.append((f"V2A front #{i}", job, spec_of(job), f"job {job}"))
    out["v2a"] = figure(rows, OUT / "front_shapes_V2A.png",
                        "V2A front (old interface model, withdrawn): whole-stem shape, templated into the real femur; "
                        "sections: medial → right, anterior ↑")
    rows = [(f"V3 front #{i}", j, spec_of(j), f"job {j}") for i, j in enumerate(V3_FRONT)]
    out["v3"] = figure(rows, OUT / "front_shapes_V3.png",
                       "V3 front (old interface model, withdrawn): whole-stem shape; #3 is the same design as V2A front #0")
    rows = []
    for name, j in REPS:
        spec = S.design_spec(dict(S.BASE), "x", "base") if j is None else spec_of(j)
        rows.append((name, j, spec, "baseline design of the project" if j is None else f"job {j}"))
    out["reps"] = figure(rows, OUT / "front_shapes_reps.png",
                         "Representative designs used in the interface-model verification (re-solved with the new model)")
    (OUT / "front_shapes.json").write_text(json.dumps(out, indent=1, default=float))
    for k in ("v2a", "v3", "reps"):
        for r in out[k]:
            print(k, r["name"], r["job"], f"L {r['L']:.1f} a {r['alpha']:.1f} m {r['m']:+.2f} cut {r['h_cut']:.0f} "
                  f"A0 {r['A0']:.0f} (job {r['A0_job']}) f1_old {r['f1_old']}", flush=True)
    print("v2a matches", json.dumps(out["v2a_matches"]))


if __name__ == "__main__":
    main()
