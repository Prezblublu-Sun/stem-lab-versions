"""两组参考图（Linux，只读队列；adhoc）。用户 2026-10-02：九类候选组图 → 两类八候选组图，用现有结果先做参考版。

图一  九类 = 柄长 S/M/L（25/30/35 mm）× 领 0/2/4 mm；每类三个截面（圆、椭圆、非对称），取椭圆（λ 1.3）作例子。
图二  两类（默认 M2 = 暂定综合最优、S4 = 最短柄，与 stage_neck2 的默认一致）× 4 个候选：
      截骨 25 / 35 mm × 截面（椭圆 = 第一阶段的例子；最大填充 = 第二阶段搜索空间里模板化后肩部截面最大的可行截面）。
几何按作业规则模板化（插入角 40°、ρ_tip 0.5、q 1.0、皮质余量 −0.25）；去骨量 = 截骨（相对 25 mm）+ 柄在骨内的体积，与 jobs.prep 的 bone_loss 相同。
有限元结果只读队列里第一阶段的网格作业（stage_collar 登记的 id），没有结果的标出状态。不提交任何作业，不写 results/。

    run.sh ../adhoc/reffig/ref_figs.py [--classes M2,S4] [--n 256]   → adhoc/reffig/out/ref_fig1_nine_classes.png、ref_fig2_eight_candidates.png、ref_figs.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
CODE = HOME / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import fe3d_geom as E  # noqa: E402
import plotstyle as ps  # noqa: E402
import cases_real as CR  # noqa: E402
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402
import stage_collar as SC  # noqa: E402
import stage_neck2 as N2  # noqa: E402
from matplotlib.patches import Polygon as MP  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402
from shapely import affinity  # noqa: E402

plt = ps.plt
OUT = HOME / "adhoc" / "reffig" / "out"
STEM_C, COLLAR_C = ps.DORR["A"], "#D55E00"
LEN = {"S": 25.0, "M": 30.0, "L": 35.0}
LEN_NAME = {"S": "short", "M": "medium", "L": "long"}
WID_NAME = {0.0: "no collar", 2.0: "narrow collar (2 mm)", 4.0: "wide collar (4 mm)"}
SEC_NAME = {"circ": "circle", "ell": "ellipse", "asym": "asymmetric"}
EXT = ((-46.0, 46.0), (-62.0, 46.0))            # 冠状面视图范围：以 25 mm 截骨中心为原点，e1 内侧、e2 向近端
_FM = {}


def fm0():
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    return _FM["fm"]


# ------------------------------------------------------------------ 几何
def geom(d: dict, h: float) -> dict:
    st = G.Stem3D(**d)
    fm = fm0().with_cut(h)
    pl = G.template(st, fm)
    g = {"st": st, "fm": fm, "pl": pl, "h_cut": h, "fit": bool(pl["fit"])}
    if not pl["fit"]:
        return g
    pl["pose"] = fm.pose(pl["alpha"], pl["e"])
    g["collar"] = E.collar_outline(st, fm, pl) if st.has_collar else None
    g["resected"] = fm.resected_volume()
    g["reamed"] = float(pl["volume"])
    g["removal"] = g["resected"] + g["reamed"]
    return g


def _a0(args):
    u8, L, w = args
    d, h = N2.design_of(u8, L, w)
    r = G.template(G.Stem3D(**d), fm0().with_cut(h))
    return float(r["A0"]) if r["fit"] and r["A0"] >= S.MIN_A0 else float("nan")


def max_fill(cls: str, h: float, n: int, workers: int) -> tuple[dict, dict]:
    """第二阶段搜索空间（stage_neck2.SPACE）里、给定截骨高度下肩部截面最大的可行截面。"""
    from scipy.stats import qmc
    L, w = N2.parse_class(cls)
    U7 = qmc.Sobol(len(N2.VARS8) - 1, scramble=True, seed=11).random(n)
    uh = (h - N2.SPACE["h_cut"][0]) / (N2.SPACE["h_cut"][1] - N2.SPACE["h_cut"][0])
    U8 = np.c_[np.full(n, uh), U7]
    with Pool(workers) as p:
        a0 = np.array(p.map(_a0, [(u, L, w) for u in U8], chunksize=8))
    ok = np.isfinite(a0)
    k = int(np.nanargmax(a0))
    d, hh = N2.design_of(U8[k], L, w)
    return d, {"n": n, "feasible": int(ok.sum()), "A0_max": float(a0[k]), "A0_median_feasible": float(np.nanmedian(a0)), "h_cut": hh}


# ------------------------------------------------------------------ 有限元状态（只读）
def fe_status(sec: str, L: float, w: float) -> dict:
    ids = json.loads((J.RESULTS / "collar_ids.json").read_text())["jobs"]
    name = "neck_w0" if (sec, L, w) == ("ell", 30.0, 0.0) else f"neck_{sec}_L{L:g}_w{w:g}"
    j = ids.get(name)
    if not j:
        return {"name": name, "state": "not submitted"}
    st = J.state(J.QROOT / j)
    out = {"name": name, "job": j, "state": st}
    if st == "DONE":
        r = J.result(j)
        out.update({k: r.get(k) for k in ("f1_p95_um", "f1_first_p95_um", "area_frac_gt40", "collar_force_share_load2",
                                          "collar_open_frac_load2", "f2_g7_loss_pct", "vm_p99")})
        out["removal_job"] = (r.get("bone_loss") or {}).get("total_mm3")
    elif st == "FAILED":
        f = json.loads((J.QROOT / j / "FAILED.json").read_text())
        out["level"] = f.get("level")
    return out


def short_state(s: dict) -> str:
    return {"DONE": "solved", "FAILED": f"failed ({s.get('level', '')})", "READY": "queued", "NEW": "queued",
            "CLAIMED": "solving", "SOLVED": "post-processing"}.get(s["state"], s["state"])


# ------------------------------------------------------------------ 画
def coronal_image(h: float):
    key = ("img", h)
    if key not in _FM:
        f0, f = fm0(), fm0().with_cut(h)
        C, e1, e2 = f0.neck_plane()
        a = np.arange(EXT[0][0], EXT[0][1], 0.25); b = np.arange(EXT[1][0], EXT[1][1], 0.25)
        A, B = np.meshgrid(a, b)
        P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
        lab = np.where(f.canal_sdf(P) <= 0, 2, np.where(f.outer_sdf(P) <= 0, 1, 0)).reshape(A.shape)
        _FM[key] = (a, b, lab, f.below_cut(P).reshape(A.shape))
    return _FM[key]


def hull(ax, xy, color, alpha=0.9):
    hv = ConvexHull(xy)
    ax.add_patch(MP(xy[hv.vertices], closed=True, fc=color, ec=color, alpha=alpha, lw=0.3))


def draw_coronal(ax, g):
    """颈平面视图，固定坐标（25 mm 截骨中心为原点），不同截骨高度可直接比较。"""
    f0, fm, st, pl = fm0(), g["fm"], g["st"], g["pl"]
    a, b, lab, kept = coronal_image(g["h_cut"])
    ax.imshow(CR._rgb(lab, kept), origin="lower", extent=(a[0], a[-1], b[0], b[-1]), interpolation="nearest")
    C0, e1, e2 = f0.neck_plane()
    off = np.array([(fm.C03 - C0) @ e1, (fm.C03 - C0) @ e2])
    n2 = np.array([fm.n3 @ e1, fm.n3 @ e2])
    ax.plot(off[0] + np.array([-32, 32]) * n2[0], off[1] + np.array([-32, 32]) * n2[1], color=COLLAR_C, lw=0.5, ls=(0, (3, 2)))
    poly = affinity.translate(CR.stem_silhouette(fm, st, pl), off[0], off[1])
    for p in getattr(poly, "geoms", [poly]):
        if p.geom_type == "Polygon":
            ax.add_patch(MP(np.asarray(p.exterior.coords), closed=True, fc=STEM_C, ec=STEM_C, alpha=0.88, lw=0.3))
    if g.get("collar"):
        Cc, c1, c2, nrm = E.cut_plane(fm)
        uv = np.array(g["collar"]["poly"].exterior.coords)
        bot = Cc + uv[:, :1] * c1 + uv[:, 1:2] * c2
        hull(ax, CR._plane_xy(f0, np.vstack([bot, bot + st.collar_t * nrm])), COLLAR_C)
    ax.set_xlim(*EXT[0]); ax.set_ylim(*EXT[1]); ax.set_aspect("equal")
    CR._off(ax)


def draw_top(ax, g, half=30.0):
    """截骨面俯视：骨（皮质灰、松质米色）、领（橙）、柄的截口（蓝）。"""
    fm, st, pl = g["fm"], g["st"], g["pl"]
    C, e1, e2, nrm = E.cut_plane(fm)
    u = np.arange(-half, half + 0.01, 0.15)
    U, V = np.meshgrid(u, u)
    P = C + U.reshape(-1, 1) * e1 + V.reshape(-1, 1) * e2
    lab = np.where(fm.canal_sdf(P) <= 0, 2, np.where(fm.outer_sdf(P) <= 0, 1, 0)).reshape(U.shape)
    ax.imshow(CR._rgb(lab, np.ones_like(lab, bool)), origin="lower", extent=(u[0], u[-1], u[0], u[-1]), interpolation="nearest")
    info = g.get("collar")
    if info is not None:
        ax.add_patch(MP(np.array(info["poly"].exterior.coords), closed=True, fc=COLLAR_C, ec=COLLAR_C, alpha=0.6, lw=0.3))
        foot = info["footprint"]
    else:
        foot = E.collar_outline(G.Stem3D(**{**st.__dict__, "collar_w": 0.01}), fm, pl)["footprint"]
    ax.add_patch(MP(np.array(foot.exterior.coords), closed=True, fc=STEM_C, ec=STEM_C, alpha=0.9, lw=0.3))
    ax.set_xlim(-half, half); ax.set_ylim(-half, half); ax.set_aspect("equal")
    CR._off(ax)


def sec_text(d: dict) -> str:
    if G.is_ellipse(d):
        return "circle" if abs(d["lam"] - 1.0) < 1e-9 else f"ellipse λ {d['lam']:.1f}"
    return f"λ {d['lam']:.2f}, n {d['n_a']:.1f}/{d['n_p']:.1f}, τ {d['tau_a']:+.2f}/{d['tau_p']:+.2f}"


def cell_text(g: dict, head: str, fe: dict | None, extra: str = "") -> str:
    lines = [head, f"cut {g['h_cut']:.0f} mm · {sec_text(g['st'].__dict__)}"]
    if not g["fit"]:
        return "\n".join(lines + ["does not fit (templating)"])
    lines.append(f"shoulder {g['pl']['A0']:.0f} mm² · bone removed {g['removal'] / 1000:.1f} cm³")
    c = g.get("collar")
    lines.append(f"collar ring {c['ring_mm2']:.0f} mm², {100 * c['ring_cortex_frac']:.0f} % on cortex" if c else "no collar")
    if fe is None:
        lines.append("FE: not yet run (Stage 2)")
    elif fe["state"] == "DONE":
        s = f"FE: micromotion {fe['f1_p95_um']:.1f} µm"
        if fe.get("collar_force_share_load2") is not None:
            s += f", collar carries {100 * fe['collar_force_share_load2']:.0f} %"
        lines.append(s)
    else:
        lines.append(f"FE: {short_state(fe)}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def grid_figure(cells, nrows, ncols, row_labels, col_labels, title, foot, path, fs=4.9, text_mm=17.0):
    """cells[r][c] = (g, text)。按毫米摆放：每格左为冠状面视图（固定比例），右为截骨面俯视，下方文字。"""
    import textwrap
    W, left, right = 190.0, 11.0, 2.0
    cw = (W - left - right) / ncols
    pc, pt, gap = 0.56 * cw, 0.40 * cw, 0.02 * cw
    ph = pc * (EXT[1][1] - EXT[1][0]) / (EXT[0][1] - EXT[0][0])
    ch = ph + text_mm + 3.0
    title = textwrap.fill(title, 140)
    foot = textwrap.fill(foot, 205, replace_whitespace=False)
    top = 4.0 + 3.2 * (title.count("\n") + 1) + 5.0
    bottom = 3.0 + 2.1 * (foot.count("\n") + 1)
    H = top + nrows * ch + bottom
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    X = lambda mm: mm / W
    Y = lambda mm_from_top: 1.0 - mm_from_top / H
    fig.text(X(left), Y(3.0), title, fontsize=6.8, va="top", ha="left")
    for c in range(ncols):
        fig.text(X(left + c * cw), Y(top - 1.5), col_labels[c], fontsize=6.2, fontweight="bold", va="bottom", ha="left")
    for r in range(nrows):
        y0 = top + r * ch
        fig.text(X(left - 3.0), Y(y0 + ph / 2), row_labels[r], rotation=90, fontsize=6.2, fontweight="bold", va="center", ha="right",
                 multialignment="center")
        for c in range(ncols):
            g, txt = cells[r][c]
            x0 = left + c * cw
            ax0 = fig.add_axes([X(x0), Y(y0 + ph), X(pc), ph / H])
            ax1 = fig.add_axes([X(x0 + pc + gap), Y(y0 + ph * 0.62), X(pt), pt / H])
            if g["fit"]:
                draw_coronal(ax0, g)
                draw_top(ax1, g)
            else:
                CR._off(ax0); CR._off(ax1)
            fig.text(X(x0), Y(y0 + ph + 1.5), txt, fontsize=fs, va="top", ha="left", linespacing=1.25)
    fig.text(X(left), Y(H - 1.5), foot, fontsize=4.5, va="bottom", ha="left", color="#444444")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(path, dpi=250)
    plt.close(fig)


def rec_of(g: dict, fe: dict | None) -> dict:
    r = {"h_cut": g["h_cut"], "fit": g["fit"], "design": g["st"].__dict__}
    if g["fit"]:
        r.update({"A0": g["pl"]["A0"], "e": g["pl"]["e"], "resected_mm3": g["resected"], "reamed_mm3": g["reamed"], "removal_mm3": g["removal"]})
        c = g.get("collar")
        if c:
            r["collar"] = {k: v for k, v in c.items() if k not in ("poly", "footprint")}
    r["fe"] = fe
    return r


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", default="M2,S4")
    ap.add_argument("--n", type=int, default=256)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    rec = {"created": stamp, "fig1": {}, "fig2": {}}

    # 图一
    cells = []
    for lk in ("S", "M", "L"):
        row = []
        for w in (0.0, 2.0, 4.0):
            L = LEN[lk]
            cls = f"{lk}{w:g}"
            d = SC.NECK_SETS["ell"](L)
            if w > 0:
                d.update(collar_w=w, collar_t=G.COLLAR_T)
            g = geom(d, 25.0)
            fes = {s: fe_status(s, L, w) for s in ("circ", "ell", "asym")}
            extra = "class: " + ", ".join(f"{SEC_NAME[s]} {short_state(v)}" for s, v in fes.items())
            row.append((g, cell_text(g, f"{cls} · L {L:.0f} mm · {WID_NAME[w]}", fes["ell"], extra)))
            rec["fig1"][cls] = {**rec_of(g, fes["ell"]), "class_fe": fes}
            print("fig1", cls, json.dumps({k: v for k, v in rec["fig1"][cls].items() if k not in ("design", "class_fe")}, default=float), flush=True)
        cells.append(row)
    n_done = sum(v["state"] == "DONE" for c in rec["fig1"].values() for v in c["class_fe"].values())
    grid_figure(cells, 3, 3, [f"{LEN_NAME[k]} stem, L {LEN[k]:.0f} mm" for k in ("S", "M", "L")],
                [WID_NAME[w] for w in (0.0, 2.0, 4.0)],
                "Stage 1 – nine candidate classes (stem length × collar); one example per class: elliptical section λ 1.3, "
                "insertion 40°, cut 25 mm from head centre",
                f"Each cell: coronal (neck-plane) view, cut line dashed, resected bone pale; right: resection plane seen from above "
                f"(grey cortex, beige cancellous, orange collar, blue stem cut). Geometry templated into the real femur (Dorr A); "
                f"bone removed = resected neck bone (relative to the 25 mm cut) + stem volume in bone.\nFE: M1 interface model, "
                f"interference 0.025 mm; {n_done}/27 class candidates solved at {stamp} — cells marked queued/failed have no FE result yet.",
                OUT / "ref_fig1_nine_classes.png", fs=5.0, text_mm=17.0)

    # 图二
    classes = [c.strip() for c in a.classes.split(",") if c.strip()]
    roles = {classes[0]: "overall best (provisional)", classes[-1]: "shortest stem"} if len(classes) == 2 else {}
    cells, row_labels = [], []
    for cls in classes:
        L, w = N2.parse_class(cls)
        row = []
        for h in (25.0, 35.0):
            de = SC.NECK_SETS["ell"](L)
            if w > 0:
                de.update(collar_w=w, collar_t=G.COLLAR_T)
            ge = geom(de, h)
            fe = fe_status("ell", L, w) if h == 25.0 else None
            dm, info = max_fill(cls, h, a.n, a.workers)
            gm = geom(dm, h)
            k = len(row)
            row.append((ge, cell_text(ge, f"{cls}-{chr(97 + k)} · ellipse (Stage 1 example)", fe)))
            row.append((gm, cell_text(gm, f"{cls}-{chr(98 + k)} · max-fill section", None,
                                      f"largest shoulder of {info['feasible']}/{info['n']} feasible samples")))
            rec["fig2"][f"{cls}_h{h:g}_ell"] = rec_of(ge, fe)
            rec["fig2"][f"{cls}_h{h:g}_maxfill"] = {**rec_of(gm, None), "search": info}
            for kk in (f"{cls}_h{h:g}_ell", f"{cls}_h{h:g}_maxfill"):
                print("fig2", kk, json.dumps({x: v for x, v in rec["fig2"][kk].items() if x not in ("design",)}, default=float)[:600], flush=True)
        cells.append(row)
        row_labels.append(f"{cls}: L {L:.0f} mm, {WID_NAME[w]}" + (f"\n{roles[cls]}" if cls in roles else ""))
    grid_figure(cells, len(classes), 4, row_labels,
                ["cut 25 mm · ellipse", "cut 25 mm · max-fill section", "cut 35 mm · ellipse", "cut 35 mm · max-fill section"],
                "Stage 2 – two classes × four candidates (resection depth × section shape); reference layout before optimisation",
                "Max-fill section = among Sobol samples of the Stage 2 section space (λ 1–2.2, γ 0.35–0.65, n 2–6, τ ±0.3) the feasible one "
                "with the largest templated shoulder area at that cut; it is a placeholder for the optimised sections, not an optimum. "
                "At the 35 mm cut the plane also clips the greater trochanter (small fragment top-left in the top view).\n"
                f"Classes provisional (Stage 1 FE incomplete). Geometry and bone removal exact; FE for cut 25 mm ellipse = Stage 1 job, "
                f"all others not yet run. Built {stamp}.",
                OUT / "ref_fig2_eight_candidates.png", fs=4.4, text_mm=17.5)
    (OUT / "ref_figs.json").write_text(json.dumps(rec, indent=1, default=float))
    print("written", OUT, flush=True)


if __name__ == "__main__":
    main()
