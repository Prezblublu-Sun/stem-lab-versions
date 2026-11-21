"""给导师计划用的图与数据（Linux，只读队列；adhoc）。用户 2026-10-02：基于 fork 4 的分阶段设计与当前结果，写计算流程与计划，附两个组图。

图 1  第一个植入物：导师所发带领颈部柄的近似（椭圆截面 λ 1.3、L 30、α 40°、3 mm 领），作业 collar_neck_w3_36c2bb73。
组图 1  阶段 0 筛选：柄长 25 / 30 / 35 mm × 领 0 / 2 / 4 mm；每格画椭圆候选，文字给三种截面的现有结果（未解 / 失败照实标）。
组图 2  (a) 现有全部颈部柄 / 领作业的权衡散点：去骨量对微动，标股骨距约束；(b) 阶段 1–2 的“八候选”版式：两族（最短 20 mm、
      综合最优占位 40 mm）× 4 个设计，取自阶段 1 的设计空间（椭圆 λ 1.3、锥度 0.5 / 1.0、平端），按去骨量从小到大取 4 个分位。
另输出 plan_data.json：全部已解作业的指标（含两种分区口径的股骨距数值）。

    run.sh ../adhoc/plan/plan_figs.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import ref_figs2 as R2  # noqa: E402
import ref_figs3 as R3  # noqa: E402
from ref_figs2 import G, E, CR, S, ps, plt  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
import resorption as RS  # noqa: E402

OUT = HOME / "adhoc" / "plan" / "out"
LEN = {"S": 25.0, "M": 30.0, "L": 35.0}
WID = {0.0: "no collar", 2.0: "narrow collar (2 mm)", 4.0: "wide collar (4 mm)"}
SEC = ("circ", "ell", "asym")
SEC_N = {"circ": "circle", "ell": "ellipse", "asym": "asymmetric"}
_C = {}


def stage0_name(sec, L, w):
    if (sec, L, w) == ("ell", 30.0, 0.0):
        return "neck_w0"
    return f"neck_{sec}_L{L:g}_w{w:g}"


def fe_full(job: str | None) -> dict:
    """状态、主要指标、两种分区口径的股骨距数值、逐节点对微动（三维着色）。"""
    if not job:
        return {"state": "not submitted"}
    d = J.QROOT / job
    st = J.state(d)
    out = {"job": job, "state": st}
    if st == "FAILED":
        out["level"] = json.loads((d / "FAILED.json").read_text()).get("level")
    if st != "DONE":
        return out
    r = J.result(job)
    out.update({k: r.get(k) for k in ("f1_p95_um", "f1_all_p95_um", "f1_first_p95_um", "area_frac_gt40", "collar_force_share_load2",
                                      "collar_open_frac_load2", "collar_slip_rev_p95_um", "vm_p99", "open_frac_load2")})
    out["bone_loss_mm3"] = (r.get("bone_loss") or {}).get("total_mm3")
    out["A0"] = (r.get("templating") or {}).get("A0")
    if "rs" not in _C:
        RS._init(); _C["rs"] = True
    rows, srow = RS.design_rows(job)
    z = {f"{x['scheme']}:{x['zone']}": x for x in rows if x["tissue"] == "cortex"}
    for sc, tag in (("fixed", "fixed"), ("femur", "ata")):
        g7, tot = z.get(f"{sc}:G7") or {}, z.get(f"{sc}:total") or {}
        out[f"G7_sed_{tag}"] = g7.get("sed_chg_pct")
        out[f"G7_res_{tag}"] = g7.get("res_0.6")
        out[f"G7_vol_{tag}"] = g7.get("vol")
        out[f"total_res_{tag}"] = tot.get("res_0.6")
    out["vm_max_body_deep"] = srow.get("vm_max_body_deep")
    p = PM.pairs(d)
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("UNLOAD", "LOAD2")}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in U}
    v, n = rel["LOAD2"] - rel["UNLOAD"], p["pair_normal"]
    pos = np.zeros(int(p["node_labels"].max()) + 1, int)
    pos[p["node_labels"]] = np.arange(len(p["node_labels"]))
    out["_xyz"] = p["nodes"][pos[p["pair_stem"]]]
    out["_rev"] = np.linalg.norm(v - (v * n).sum(1)[:, None] * n, axis=1) * 1e3
    out["_collar"] = p["pair_collar"]
    return out


def geo_of(job):
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    return R2.geom(spec["design"], float(spec.get("h_cut", 25.0))), spec


def fmt(x, n=1, unit="", sign=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return (f"{x:+.{n}f}" if sign else f"{x:.{n}f}") + unit


def st_short(fe):
    return {"DONE": None, "FAILED": "×", "READY": "…", "NEW": "…", "CLAIMED": "…", "SOLVED": "…"}.get(fe["state"], "?")


# ------------------------------------------------------------------ 图 1：第一个植入物
def fig_first(fe, g):
    import math
    fig = plt.figure(figsize=(190 * ps.MM, 104 * ps.MM))
    W, H = 190.0, 104.0
    X = lambda mm: mm / W
    Y = lambda mm: 1 - mm / H
    ext = R2.EXT
    pc = 52.0; ph = pc * (ext[1][1] - ext[1][0]) / (ext[0][1] - ext[0][0])
    ax0 = fig.add_axes([X(4), Y(13 + ph), X(pc), ph / H]); R2.draw_coronal(ax0, g); ax0.set_title("(a) coronal section, in the bone", fontsize=6, loc="left")
    ax1 = fig.add_axes([X(60), Y(13 + 34), X(34), 34 / H]); R2.draw_top(ax1, g); ax1.set_title("(b) resection plane from above", fontsize=6, loc="left")
    ax2 = fig.add_axes([X(97), Y(13 + 46), X(46), 46 / H], projection="3d")
    R3.draw_3d(ax2, g, fe, R3.view_centre() + np.array([4.0, 0.0, 8.0]), half=34.0)
    ax2.set_title("(c) stem, 45° above-front; micromotion", fontsize=6, loc="left")
    ax3 = fig.add_axes([X(60), Y(13 + 34 + 32), X(34), 26 / H]); CR.draw_section(ax3, g["fm"], g["st"], g["pl"], 0.5, R2.STEM_C)
    ax3.set_title("(d) section at mid-length", fontsize=6, loc="left")
    c = fe.get("_prep_collar") or g["collar"]                       # 作业建模时的领（截骨面为当时的面）
    lines = [("Design", ""), ("stem length", f"{g['st'].L:.0f} mm"), ("insertion angle (to shaft axis)", f"{g['st'].alpha:.0f}° (neck axis 42.5°)"),
             ("section", "ellipse, width / thickness 1.3"), ("taper", "tip area = 0.5 × shoulder, linear"),
             ("shoulder area (size)", f"{g['pl']['A0']:.0f} mm²  (largest that fits)"), ("collar", f"3 mm overhang, 2.5 mm thick"),
             ("collar bearing ring", f"{c['ring_mm2']:.0f} mm², {100 * c['ring_cortex_frac']:.0f} % on cortex"),
             ("resection", "25 mm from head centre (head–neck junction)"),
             ("tip", f"{abs(g['tip_z']):.0f} mm {'above' if g['tip_z'] >= 0 else 'below'} the lesser trochanter"),
             ("Results (FE)", ""), ("micromotion P95, stem body", f"{fe['f1_p95_um']:.1f} µm  (44.6 µm without collar)"),
             ("micromotion P95, body + collar", f"{fe['f1_all_p95_um']:.1f} µm"),
             ("collar share of load", f"{100 * fe['collar_force_share_load2']:.0f} %"),
             ("collar face lifted at peak load", f"{100 * fe['collar_open_frac_load2']:.0f} %"),
             ("calcar strain energy vs intact", f"{fe['G7_sed_fixed']:+.0f} % fixed zone; {fe['G7_sed_ata']:+.0f} % thesis zone"),
             ("calcar bone resorption (s = 0.6)", f"{fe['G7_res_fixed']:.0f} % fixed zone; {fe['G7_res_ata']:.0f} % thesis zone"),
             ("implant stress, P99", f"{fe['vm_p99']:.0f} MPa"),
             ("bone removed", f"{fe['bone_loss_mm3'] / 1000:.1f} cm³ (broached; no extra resection)")]
    y = 13.0
    for k, v in lines:
        if v == "":
            fig.text(X(146), Y(y), k, fontsize=5.6, fontweight="bold", va="top"); y += 3.0
        else:
            fig.text(X(146), Y(y), k, fontsize=4.6, va="top", color="#444444")
            fig.text(X(146), Y(y + 1.9), v, fontsize=4.9, va="top"); y += 4.25
    fig.text(X(4), Y(2.5), "First implant generated by the pipeline from the collared neck-only design: placed, sized and evaluated "
             "automatically in the bone model (stair-climbing load, press-fit interface)", fontsize=6.6, va="top")
    cax = fig.add_axes([X(100), Y(13 + 52), X(36), 1.4 / H])
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=R3.NORM, cmap=R3.CMAP), cax=cax, orientation="horizontal")
    cb.set_ticks([1, 10, 40, 150]); cb.set_ticklabels(["≤1", "10", "40", "≥150 µm"]); cb.ax.tick_params(labelsize=4.4, length=1.5, pad=1)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig1_first_implant.png", dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 组图 1
def group1(ids, data):
    cells = []
    for lk in "SML":
        row = []
        for w in (0.0, 2.0, 4.0):
            L = LEN[lk]
            fes = {s: data.get(stage0_name(s, L, w)) or {"state": "not submitted"} for s in SEC}
            g, _ = geo_of(ids[stage0_name("ell", L, w)])
            fe = fes["ell"]
            mm = " · ".join(f"{SEC_N[s][:4]}. {fmt(v.get('f1_all_p95_um') if w > 0 else v.get('f1_p95_um'))}" if v["state"] == "DONE"
                            else f"{SEC_N[s][:4]}. {st_short(v)}" for s, v in fes.items())
            chip = R3.CMAP(R3.NORM(min(max((fe.get("f1_all_p95_um") or fe.get("f1_p95_um")), 1), 150))) if fe["state"] == "DONE" else None
            lines = [(f"micromotion (µm): {mm}", chip)]
            if fe["state"] == "DONE":
                lines.append((f"calcar SED vs intact: {fmt(fe['G7_sed_fixed'], 0, ' %', True)} (fixed zone), "
                              f"{fmt(fe['G7_sed_ata'], 0, ' %', True)} (thesis zone)", None))
                lines.append((f"calcar resorption {fmt(fe['G7_res_ata'], 0, ' %')} (thesis zone)"
                              + (f" · collar load {100 * fe['collar_force_share_load2']:.0f} %" if fe.get("collar_force_share_load2") else ""), None))
            else:
                lines.append(("calcar SED — (ellipse not yet solved)", None))
                lines.append(("", None))
            lines.append((f"bone removed {g['removal'] / 1000:.1f} cm³ · shoulder {g['pl']['A0']:.0f} mm²", None))
            row.append((g, fe, f"{lk}{w:.0f} · L {L:.0f} mm · {WID[w]}", lines))
        cells.append(row)
    n_done = sum(1 for k, v in data.items() if v.get("state") == "DONE" and k.startswith("neck_") and "_w3" not in k)
    R3.grid_figure(cells, 3, 3, [f"L {LEN[k]:.0f} mm" for k in "SML"], [WID[w] for w in (0.0, 2.0, 4.0)],
                   "Figure group 1 – Stage 0 screening: nine classes (stem length × collar), three sections each; ellipse shown",
                   "Each cell: coronal section (resection line dashed, lesser trochanter dotted), resection plane from above, and the elliptical "
                   "stem in 3-D coloured by micromotion when solved (blue = not yet solved). Micromotion = P95 of recoverable interface sliding "
                   "(stem body + collar face) under the stair-climbing load, for the circle / ellipse / asymmetric candidates of the class; "
                   "× = mesh failure (25 mm circle and asymmetric), … = queued. Calcar SED = cortical strain energy in Gruen zone 7 relative to "
                   "the intact femur (bonded model): fixed anatomical zone (used as the optimisation constraint, |Δ| ≤ 30 %) and the thesis "
                   "zone set by the stem (Naghavi 2023, Fig. 5-9). Insertion angle 40°, resection 25 mm, cortical margin −0.25 mm, rounded tip "
                   f"(Stage 0 settings).\nSolved Stage 0 designs: {n_done} of 27 at {time.strftime('%Y-%m-%d %H:%M')}.",
                   OUT / "fig2_group1_stage0.png", fs=4.6, text_mm=15.5)


# ------------------------------------------------------------------ 组图 2
PH1 = {"alpha": (15.0, 45.0), "collar_w": (0.0, 6.0), "m": (-0.25, 2.0), "h_cut": (25.0, 32.0)}


def _tmpl(args):
    L, u = args
    p = {k: lo + float(x) * (hi - lo) for (k, (lo, hi)), x in zip(PH1.items(), u)}
    d = G.ellipse_design(L, 0.5, 1.0, 1.3, p["alpha"], m=p["m"], collar_w=p["collar_w"] if p["collar_w"] > 0.05 else 0.0, cap_h=G.CAP_FLAT)
    fm = R2.fm0().with_cut(p["h_cut"])
    r = G.template(G.Stem3D(**d), fm)
    if not (r["fit"] and r["A0"] >= S.MIN_A0):
        return None
    return {"design": d, "h_cut": p["h_cut"], "A0": float(r["A0"]), "removal": float(fm.resected_volume() + r["volume"]), **p}


def family_picks(L, n=384, workers=3):
    from scipy.stats import qmc
    U = qmc.Sobol(4, scramble=True, seed=7).random(n)
    with Pool(workers) as pool:
        res = [r for r in pool.map(_tmpl, [(L, u) for u in U], chunksize=8) if r]
    res.sort(key=lambda r: r["removal"])
    q = [0, len(res) // 3, 2 * len(res) // 3, len(res) - 1]
    return [res[i] for i in q], len(res), n


def scatter(ax, data):
    pts = []
    for k, v in data.items():
        if v.get("state") != "DONE" or v.get("bone_loss_mm3") is None:
            continue
        mm = v.get("f1_all_p95_um") or v.get("f1_p95_um")
        pts.append((k, v["bone_loss_mm3"] / 1000, mm, v["_L"], v["_w"], v.get("G7_sed_fixed")))
    col = {25: "#B86E00", 30: "#00805C", 35: "#3C8FC7", 60: "#0B4F7C"}
    for k, x, y, L, w, sed in pts:
        Lk = 25 if L < 27 else (30 if L < 32 else (35 if L < 40 else 60))
        feas = sed is not None and abs(sed) <= 30
        ax.scatter(x, y, s=16 if w > 0 else 12, marker="o" if w > 0 else "s", fc=col[Lk] if feas else "white", ec=col[Lk], lw=0.8, zorder=3)
    P = np.array([(x, y) for _, x, y, *_ in pts])
    order = np.argsort(P[:, 0])
    front, best = [], np.inf
    for i in order:
        if P[i, 1] < best:
            front.append(P[i]); best = P[i, 1]
    front = np.array(front)
    ax.step(front[:, 0], front[:, 1], where="post", color="#555555", lw=0.6, ls=(0, (3, 2)), zorder=2)
    ax.set_yscale("log"); ax.set_ylim(0.5, 120)
    ax.axhline(40, color="#C00000", lw=0.5, ls=(0, (1, 1.5))); ax.text(ax.get_xlim()[0] if False else 6.05, 42, "40 µm", fontsize=4.4, color="#C00000")
    ax.set_xlabel("bone removed (cm³)", fontsize=5.4); ax.set_ylabel("micromotion P95 (µm)", fontsize=5.4)
    ax.tick_params(labelsize=4.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    from matplotlib.lines import Line2D
    h = [Line2D([], [], ls="", marker="o", mfc=c, mec=c, ms=3.5, label=f"L {k} mm") for k, c in col.items()]
    h += [Line2D([], [], ls="", marker="s", mfc="#999999", mec="#999999", ms=3, label="no collar"),
          Line2D([], [], ls="", marker="o", mfc="#999999", mec="#999999", ms=3.5, label="with collar"),
          Line2D([], [], ls="", marker="o", mfc="white", mec="#555555", ms=3.5, label="calcar |ΔSED| > 30 %"),
          Line2D([], [], color="#555555", lw=0.6, ls=(0, (3, 2)), label="current non-dominated set")]
    ax.legend(handles=h, fontsize=4.3, frameon=False, loc="upper right", ncol=2)
    return len(pts)


def group2(data):
    fams = [("A", 20.0, "shortest stem"), ("B", 40.0, "overall best (placeholder)")]
    cells, row_labels, picks_rec = [], [], {}
    for fk, L, role in fams:
        picks, nf, n = family_picks(L)
        row = []
        for j, (tag, pk) in enumerate(zip(("least bone removed", "trade-off 1", "trade-off 2", "largest stem"), picks)):
            g = R2.geom(pk["design"], pk["h_cut"])
            lines = [("micromotion — (Stage 1 FE pending)", None),
                     (f"α {pk['alpha']:.0f}° · collar {pk['collar_w']:.1f} mm · margin {pk['m']:+.2f} mm · cut {pk['h_cut']:.0f} mm", None),
                     (f"shoulder {g['pl']['A0']:.0f} mm² · bone removed {g['removal'] / 1000:.1f} cm³", None)]
            row.append((g, {"state": "pending"}, f"{fk}{j + 1} · {tag}", lines))
            picks_rec[f"{fk}{j + 1}"] = {k: v for k, v in pk.items() if k != "design"} | {"L": L}
        cells.append(row)
        row_labels.append(f"family {fk}: L {L:.0f} mm\n{role} ({nf}/{n} feasible)")
    R3.grid_figure(cells, 2, 4, row_labels, ["1 · least bone removed", "2 · trade-off", "3 · trade-off", "4 · largest stem"],
                   "Figure group 2 – what Stages 1–2 deliver: two families × four candidates along the trade-off (layout with illustrative designs)",
                   "Illustrative designs drawn from the Stage 1 design space (elliptical section 1.3, tip area 0.5 × shoulder, flat tip; insertion "
                   "angle 15–45°, collar 0–6 mm, cortical margin −0.25 to +2 mm, resection 25–32 mm): 384 Sobol samples per family, placed and sized "
                   "automatically; the four columns are the feasible designs at the minimum, one-third, two-thirds and maximum of bone removed. "
                   "Bone removed is exact; micromotion and calcar loading come from FE in Stage 1. In the final figure the columns are four "
                   "designs from each family's Pareto set (most stable, two trade-offs, least bone removed) after the section-shape stage, "
                   "and family B is the class ranked best in Stages 0–1.", OUT / "fig3_group2_stage12.png", fs=4.5, text_mm=12.5)
    # 散点单独一张
    fig = plt.figure(figsize=(110 * ps.MM, 70 * ps.MM))
    ax = fig.add_axes([0.12, 0.20, 0.85, 0.67])
    n = scatter(ax, data)
    fig.text(0.12, 0.96, f"Current trade-off: {n} solved neck / collared designs (Stage 0 and verification)", fontsize=6.2, va="top")
    fig.text(0.12, 0.02, "Micromotion = P95 over stem body + collar face (body only without collar). Hollow = fails the calcar constraint "
             "(|strain-energy change| > 30 % in the fixed zone 7).", fontsize=4.3, va="bottom", color="#444444", wrap=True)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig4_tradeoff_current.png", dpi=250)
    plt.close(fig)
    return picks_rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ids = json.loads((J.RESULTS / "collar_ids.json").read_text())["jobs"]
    extra = {"short_w0_old": "m1_short_h2_tol0.00025_delta0.025_7f62c025"}
    data = {}
    for k, j in {**ids, **extra}.items():
        fe = fe_full(j)
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        fe["_L"], fe["_w"] = float(spec["design"]["L"]), float(spec["design"].get("collar_w", 0.0))
        data[k] = fe
        print(k, fe["state"], fmt(fe.get("f1_p95_um")), fmt(fe.get("G7_sed_fixed")), fmt(fe.get("G7_res_ata")), flush=True)
    R2.fm0()
    fe1 = data["neck_w3"]
    fe1["_prep_collar"] = json.loads((J.QROOT / ids["neck_w3"] / "prep.json").read_text()).get("collar")
    g1, _ = geo_of(ids["neck_w3"])
    fig_first(fe1, g1); print("fig1 done", flush=True)
    group1(ids, data); print("group1 done", flush=True)
    picks = group2(data); print("group2 done", flush=True)
    clean = {k: {kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv) for kk, vv in v.items() if not kk.startswith("_") or kk in ("_L", "_w")}
             for k, v in data.items()}
    (OUT / "plan_data.json").write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "jobs": clean, "group2_picks": picks},
                                                   indent=1, default=float))
    print("written", flush=True)


if __name__ == "__main__":
    main()
