"""两组参考图，第三版（Linux，只读；adhoc）。用户 2026-10-02：变量描述移出图片（另出设计表），图中放微动与应力屏蔽数值；
截骨面俯视图下方加一个同样大小的三维柄示意（斜上 45° 视角），柄面按微动着色。

几何沿用 ref_figs2.py 的输出 ref2_figs.json；有限元结果读 submit_ref2.py 登记的 ref2_ids.json 里各作业（未解完的标 pending）。
    微动    = 柄身可恢复切向微动 P95（第二次加载，µm），与 post_m1.f1_p95_um 相同
    应力屏蔽 = 固定解剖分区的 Gruen 7 区（股骨距）皮质应变能相对完整股骨的变化（resorption.design_rows，scheme fixed），负 = 屏蔽
    领承载   = 峰值载荷时领面接触力占柄传给骨的合力的比例
    去骨量   = 截骨（相对 25 mm）+ 柄在骨内的体积（几何，精确）

    run.sh ../adhoc/reffig2/ref_figs3.py            → out/ref3_fig1_nine_classes.png、ref3_fig2_eight_candidates.png、ref3_design_table.csv/.md、ref3_figs.json
    run.sh ../adhoc/reffig2/ref_figs3.py --test     → out/ref3_test_3d.png（用已解的领验证作业检查三维着色）
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import sys
import textwrap
import time

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import ref_figs2 as R2  # noqa: E402  （同目录：几何、冠状面与俯视图的画法）
from ref_figs2 import G, E, CR, S, ps, plt, MP  # noqa: E402
import jobs as J  # noqa: E402
import post_m1 as PM  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

OUT = HOME / "adhoc" / "reffig2" / "out"
SRC = OUT / "ref2_figs.json"
IDS = HOME / "adhoc" / "reffig2" / "ref2_ids.json"
CMAP = plt.get_cmap("YlOrRd")
NORM = LogNorm(1.0, 150.0)
NECK_C = np.array([0.72, 0.72, 0.74])
ELEV, AZIM = 45.0, -90.0                                              # 斜上 45°，从前方看（内侧在右，与冠状面视图一致）


# ------------------------------------------------------------------ 有限元结果（只读）
def fe_of(job: str | None) -> dict:
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
    out.update({k: r.get(k) for k in ("f1_p95_um", "f1_first_p95_um", "area_frac_gt40", "collar_force_share_load2",
                                      "collar_slip_rev_p95_um", "collar_open_frac_load2", "vm_p99")})
    import resorption as RS
    if "rs" not in _C:
        RS._init(); _C["rs"] = True
    rows, _ = RS.design_rows(job)
    z = {f"{x['scheme']}:{x['zone']}": x for x in rows if x["tissue"] == "cortex"}
    # 应变能口径的屏蔽指数（= −应变能变化 %），与图中“calcar strain energy”的标注一致；此前误用了按应力算的 ssi_pct
    sed = lambda key: (lambda v: None if v is None else -v)((z.get(key) or {}).get("sed_chg_pct"))
    out["calcar_ssi_fixed"] = sed("fixed:G7")
    out["calcar_ssi_stemset"] = sed("femur:G7")
    out["resorbed_total_fixed"] = (z.get("fixed:total") or {}).get("res_0.6")
    # 逐节点对的可恢复切向微动（与 post_m1.micromotion 同一算法），给三维着色
    p = PM.pairs(d)
    U = {s: PM._utab(d / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in ("UNLOAD", "LOAD2")}
    rel = {s: U[s][p["pair_stem"]] - U[s][p["pair_bone"]] for s in U}
    v, n = rel["LOAD2"] - rel["UNLOAD"], p["pair_normal"]
    rev = np.linalg.norm(v - (v * n).sum(1)[:, None] * n, axis=1) * 1e3
    pos = np.zeros(int(p["node_labels"].max()) + 1, int)
    pos[p["node_labels"]] = np.arange(len(p["node_labels"]))
    out["_xyz"] = p["nodes"][pos[p["pair_stem"]]]
    out["_rev"] = rev
    out["_collar"] = p["pair_collar"]
    return out


_C = {}


# ------------------------------------------------------------------ 三维柄
def _shade(normals, base):
    light = np.array([-0.2, -0.5, 0.85]); light /= np.linalg.norm(light)
    k = 0.5 + 0.5 * np.clip(normals @ light, 0, 1)
    return np.clip(base * k[:, None], 0, 1)


def stem_polys(g: dict, nt: int = 26, m: int = 48):
    """柄体（截到建模实际的截骨面）、平端、领（若有）、假体颈的多边形，以及各面的类别与外法向。"""
    st, fm, pl = g["st"], g["fm"], g["pl"]
    P0, d, e_ml, e_ap = pl["pose"]
    C, c1, c2, nrm = E.cut_plane(fm)
    sec = G.unit_section(st.d, m)
    k = lambda s: np.sqrt(pl["A0"] * np.asarray(st.area_ratio(s), float))
    sg = np.linspace(G.S_TOP, st.L, 900)
    pts = P0 + sg[:, None, None] * d + k(sg)[:, None, None] * (sec[None, :, :1] * e_ml + sec[None, :, 1:] * e_ap)
    f = (pts - C) @ nrm                                                 # > 0 = 截骨面以上（头侧）
    s_top = np.empty(m)
    for j in range(m):
        above = np.nonzero(f[:, j] > 0)[0]
        if not len(above):
            s_top[j] = sg[0]; continue
        i = min(above.max(), len(sg) - 2)
        a, b = f[i, j], f[i + 1, j]
        s_top[j] = sg[i] + (sg[i + 1] - sg[i]) * a / (a - b) if a != b else sg[i]
    t = np.linspace(0, 1, nt)
    Sg = s_top[None, :] + t[:, None] * (st.L - s_top[None, :])          # (nt, m)
    X = P0 + Sg[..., None] * d + k(Sg.ravel()).reshape(Sg.shape)[..., None] * (sec[None, :, :1] * e_ml + sec[None, :, 1:] * e_ap)
    polys, kind, nrms = [], [], []
    for i in range(nt - 1):
        for j in range(m):
            jj = (j + 1) % m
            q = np.array([X[i, j], X[i + 1, j], X[i + 1, jj], X[i, jj]])
            nn = np.cross(q[2] - q[0], q[3] - q[1])
            c = q.mean(0); ax_pt = P0 + Sg[i:i + 2, j].mean() * d
            if nn @ (c - ax_pt) < 0:
                nn = -nn
            polys.append(q); kind.append("body"); nrms.append(nn / (np.linalg.norm(nn) + 1e-12))
    polys.append(X[-1]); kind.append("tip"); nrms.append(d)
    if not g.get("collar"):
        polys.append(X[0]); kind.append("top"); nrms.append(nrm)
    t_c = 0.0
    if g.get("collar"):
        t_c = st.collar_t
        uv = np.array(g["collar"]["poly"].exterior.coords)[:-1]
        if len(uv) > 160:
            uv = uv[np.linspace(0, len(uv) - 1, 160).astype(int)]
        B = C + uv[:, :1] * c1 + uv[:, 1:] * c2
        T = B + t_c * nrm
        cen = B.mean(0)
        polys.append(T); kind.append("collar_top"); nrms.append(nrm)
        for j in range(len(B)):
            jj = (j + 1) % len(B)
            q = np.array([B[j], B[jj], T[jj], T[j]])
            nn = np.cross(q[1] - q[0], q[3] - q[0])
            if nn @ (q.mean(0) - cen) < 0:
                nn = -nn
            polys.append(q); kind.append("collar_side"); nrms.append(nn / (np.linalg.norm(nn) + 1e-12))
    # 假体颈：沿颈轴，截骨面（或领顶）起 12 mm，半径 = 假体颈 7 mm
    u = fm.u3 / np.linalg.norm(fm.u3)
    a1 = np.cross(u, [0, 0, 1.0]); a1 /= np.linalg.norm(a1); a2 = np.cross(u, a1)
    r = math.sqrt(S.MIN_A0 / math.pi)
    base = fm.C03 + (t_c + 0.3) * u
    ang = np.linspace(0, 2 * math.pi, 37)[:-1]
    ring = r * (np.cos(ang)[:, None] * a1 + np.sin(ang)[:, None] * a2)
    for j in range(len(ang)):
        jj = (j + 1) % len(ang)
        q = np.array([base + ring[j], base + ring[jj], base + 12 * u + ring[jj], base + 12 * u + ring[j]])
        nn = (ring[j] + ring[jj]) / 2
        polys.append(q); kind.append("neck"); nrms.append(nn / np.linalg.norm(nn))
    polys.append(base + 12 * u + ring); kind.append("neck"); nrms.append(u)
    return polys, np.array(kind), np.array(nrms)


def draw_3d(ax, g: dict, fe: dict | None, centre: np.ndarray, half: float = 38.0):
    polys, kind, nrms = stem_polys(g)
    base = np.tile(np.array(plt.matplotlib.colors.to_rgb(R2.STEM_C)), (len(polys), 1))
    base[np.char.startswith(kind, "collar")] = plt.matplotlib.colors.to_rgb(R2.COLLAR_C)
    base[kind == "neck"] = NECK_C
    if fe and fe.get("state") == "DONE":
        cen = np.array([p.mean(0) for p in polys])
        xyz, rev, col = fe["_xyz"], fe["_rev"], fe["_collar"].astype(bool)
        for mask_face, mask_node, tol in ((kind == "body", ~col, 3.0),):                # 领保持橙色，领面滑移另报
            if mask_face.any() and mask_node.any():
                dist, idx = cKDTree(xyz[mask_node]).query(cen[mask_face])
                vals = rev[mask_node][idx]
                rgb = CMAP(NORM(np.clip(vals, NORM.vmin, NORM.vmax)))[:, :3]
                rgb[dist > tol] = base[mask_face][dist > tol]
                base[mask_face] = rgb
    cols = _shade(nrms, base)
    pc = Poly3DCollection(polys, facecolors=cols, edgecolors=cols, linewidths=0.25, antialiased=False)
    ax.add_collection3d(pc)
    ax.set_proj_type("ortho")
    ax.view_init(elev=ELEV, azim=AZIM)
    for setl, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), centre):
        setl(c - half, c + half)
    try:
        ax.set_box_aspect((1, 1, 1), zoom=1.92)
    except TypeError:
        ax.set_box_aspect((1, 1, 1))
    ax.set_axis_off()
    ax.patch.set_alpha(0)


def view_centre() -> np.ndarray:
    return R2.fm0().C03 + np.array([-6.0, 0.0, -19.0])


# ------------------------------------------------------------------ 指标文字
def fmt_pct(x, signed=True):
    return "—" if x is None or not np.isfinite(x) else (f"{x:+.0f} %" if signed else f"{x:.0f} %")


def metric_lines(g: dict, fe: dict, ref: dict | None = None) -> list[tuple[str, tuple | None]]:
    """[(文字, 色块颜色或 None)]。ref = 同一行的起点 a，用来写相对变化。"""
    out = []
    done = fe.get("state") == "DONE"
    if done:
        mm = fe["f1_p95_um"]
        s = f"micromotion {mm:.1f} µm"
        if ref and ref.get("state") == "DONE":
            s += f"  ({100 * (mm / ref['f1_p95_um'] - 1):+.0f} % vs a)"
        out.append((s, CMAP(NORM(min(max(mm, NORM.vmin), NORM.vmax)))))
        ssi = fe.get("calcar_ssi_fixed")
        out.append((f"calcar strain energy {fmt_pct(-ssi if ssi is not None else None)} vs intact", None))
        cs = fe.get("collar_force_share_load2")
        out.append((f"collar carries {100 * cs:.0f} % of load" if cs is not None else "no collar", None))
    else:
        lab = {"FAILED": f"FE failed ({fe.get('level', '')})", "not submitted": "FE not submitted"}.get(fe.get("state"), "FE pending")
        out.append((f"micromotion — ({lab})", None))
        out.append(("calcar strain energy —", None))
        out.append(("collar load —" if g["st"].has_collar else "no collar", None))
    rm = g["removal"] / 1000 if g["fit"] else float("nan")
    s = f"bone removed {rm:.1f} cm³"
    if ref and ref.get("_removal"):
        s += f"  ({100 * (g['removal'] / ref['_removal'] - 1):+.0f} % vs a)"
    out.append((s, None))
    return out


# ------------------------------------------------------------------ 版式
def grid_figure(cells, nrows, ncols, row_labels, col_labels, title, foot, path, fs=5.2, text_mm=14.0):
    """cells[r][c] = (g, fe, code, lines)。每格：左冠状面视图；右上截骨面俯视、右下同样大小的三维柄；下方指标。"""
    W, left, right = 190.0, 11.0, 2.0
    cw = (W - left - right) / ncols
    pc, gap = 0.53 * cw, 0.02 * cw
    ph = pc * (R2.EXT[1][1] - R2.EXT[1][0]) / (R2.EXT[0][1] - R2.EXT[0][0])
    pt = min((ph - 1.0) / 2, cw - pc - gap - 0.5)
    ch = ph + text_mm + 3.0
    title = textwrap.fill(title, 140)
    foot = "\n".join(textwrap.fill(p, 200) for p in foot.split("\n"))
    top = 4.0 + 3.2 * (title.count("\n") + 1) + 5.0
    bottom = 9.0 + 2.1 * (foot.count("\n") + 1)
    H = top + nrows * ch + bottom
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    X = lambda mm: mm / W
    Y = lambda mm_from_top: 1.0 - mm_from_top / H
    fig.text(X(left), Y(3.0), title, fontsize=6.8, va="top", ha="left")
    for c in range(ncols):
        fig.text(X(left + c * cw), Y(top - 1.5), col_labels[c], fontsize=6.0, fontweight="bold", va="bottom", ha="left")
    centre = view_centre()
    for r in range(nrows):
        y0 = top + r * ch
        fig.text(X(left - 3.0), Y(y0 + ph / 2), row_labels[r], rotation=90, fontsize=6.0, fontweight="bold", va="center", ha="right",
                 multialignment="center")
        for c in range(ncols):
            g, fe, code, lines = cells[r][c]
            x0 = left + c * cw
            ax0 = fig.add_axes([X(x0), Y(y0 + ph), X(pc), ph / H])
            ax1 = fig.add_axes([X(x0 + pc + gap), Y(y0 + pt), X(pt), pt / H])
            ax2 = fig.add_axes([X(x0 + pc + gap), Y(y0 + 2 * pt + 1.0), X(pt), pt / H], projection="3d")
            if g["fit"]:
                R2.draw_coronal(ax0, g)
                R2.draw_top(ax1, g)
                draw_3d(ax2, g, fe, centre)
            else:
                for a_ in (ax0, ax1, ax2):
                    a_.set_axis_off()
            yt = y0 + ph + 1.6
            fig.text(X(x0), Y(yt), code, fontsize=fs + 0.4, fontweight="bold", va="top", ha="left")
            for i, (s, chip) in enumerate(lines):
                yy = Y(yt + 2.5 + i * 2.25)
                if chip is not None:
                    fig.text(X(x0), yy, "■", fontsize=fs + 1.5, color=chip, va="top", ha="left")
                fig.text(X(x0 + (2.4 if chip is not None else 0.0)), yy, s, fontsize=fs, va="top", ha="left")
    # 微动色标
    cax = fig.add_axes([X(left), Y(H - bottom + 6.0), X(48.0), 1.6 / H])
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=NORM, cmap=CMAP), cax=cax, orientation="horizontal")
    cb.set_ticks([1, 10, 40, 150]); cb.set_ticklabels(["≤1", "10", "40", "≥150"])
    cb.ax.tick_params(labelsize=4.5, length=1.5, pad=1)
    cb.outline.set_linewidth(0.3)
    fig.text(X(left + 50.0), Y(H - bottom + 6.0), "reversible micromotion on the 3-D stem body (µm); blue stem = FE not yet available; collar orange, grey = prosthetic neck", fontsize=4.5, va="bottom", ha="left", color="#444444")
    fig.text(X(left), Y(H - 1.5), foot, fontsize=4.5, va="bottom", ha="left", color="#444444")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(path, dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 设计表
COLS = ["candidate", "job_id", "fe_state", "L_mm", "collar_w_mm", "section", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p",
        "taper_rho_tip", "taper_q", "alpha_deg", "cut_mm", "shoulder_mm2", "tip_vs_LT_mm", "bone_removed_cm3", "collar_ring_mm2",
        "collar_ring_on_cortex_pct", "micromotion_p95_um", "first_loading_p95_um", "area_gt40um_pct", "collar_load_pct",
        "calcar_SED_vs_intact_fixed_pct", "calcar_SED_vs_intact_stemset_pct", "resorbed_cortex_total_pct", "stem_vM_p99_MPa"]


def table_row(name, g, fe) -> dict:
    d = g["st"].__dict__
    c = g.get("collar") or {}
    num = lambda x, n=1: "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)
    return {"candidate": name, "job_id": fe.get("job", ""), "fe_state": fe.get("state"), "L_mm": num(d["L"], 0),
            "collar_w_mm": num(d.get("collar_w", 0.0), 0), "section": R2.sec_text(d), **{k: num(d[k], 2) for k in
            ("lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")}, "taper_rho_tip": d["rho_tip"], "taper_q": d["q"],
            "alpha_deg": num(d["alpha"]), "cut_mm": num(g["h_cut"], 0), "shoulder_mm2": num(g["pl"]["A0"], 0),
            "tip_vs_LT_mm": num(g["tip_z"]), "bone_removed_cm3": num(g["removal"] / 1000), "collar_ring_mm2": num(c.get("ring_mm2"), 0),
            "collar_ring_on_cortex_pct": num(100 * c["ring_cortex_frac"], 0) if c else "",
            "micromotion_p95_um": num(fe.get("f1_p95_um")), "first_loading_p95_um": num(fe.get("f1_first_p95_um")),
            "area_gt40um_pct": num(100 * fe["area_frac_gt40"]) if fe.get("area_frac_gt40") is not None else "",
            "collar_load_pct": num(100 * fe["collar_force_share_load2"], 0) if fe.get("collar_force_share_load2") is not None else "",
            "calcar_SED_vs_intact_fixed_pct": num(-fe["calcar_ssi_fixed"]) if fe.get("calcar_ssi_fixed") is not None else "",
            "calcar_SED_vs_intact_stemset_pct": num(-fe["calcar_ssi_stemset"]) if fe.get("calcar_ssi_stemset") is not None else "",
            "resorbed_cortex_total_pct": num(fe.get("resorbed_total_fixed")), "stem_vM_p99_MPa": num(fe.get("vm_p99"), 0)}


# ------------------------------------------------------------------ main
FOOT = ("Each cell: left, coronal (neck-plane) view — cut line dashed, resected bone pale, lesser-trochanter level dotted (LT); right, "
        "resection plane from above (grey cortex, beige cancellous, orange collar, blue stem cut) and the stem in 3-D seen 45° from "
        "above-front (medial to the right). Micromotion = reversible tangential micromotion P95 of the stem body under the stair-climbing "
        "load (second cycle), interface model with 0.025 mm interference. Calcar strain energy = cortical strain energy in Gruen zone 7 "
        "(fixed anatomical zones) relative to the intact femur; negative = stress shielding. Bone removed = resected neck bone + stem "
        "volume in bone. Design variables of every candidate: ref3_design_table.csv.")


def test():
    jobs_ = ["collar_base_w2_9d3e7e27", "collar_neck_w3_36c2bb73", "collar_short_w3_35350236"]
    fig = plt.figure(figsize=(120 * ps.MM, 45 * ps.MM))
    for i, j in enumerate(jobs_):
        spec = json.loads((J.QROOT / j / "spec.json").read_text())
        g = R2.geom(spec["design"], float(spec.get("h_cut", 25.0)))
        fe = fe_of(j)
        ax = fig.add_axes([i / 3, 0.05, 1 / 3, 0.85], projection="3d")
        draw_3d(ax, g, fe, view_centre())
        fig.text(i / 3 + 0.01, 0.95, f"{j}\nP95 {fe['f1_p95_um']:.1f} µm, calcar {fmt_pct(-fe['calcar_ssi_fixed'])}", fontsize=5, va="top")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "ref3_test_3d.png", dpi=250)
    print("test written", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        return test()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    Rj = json.loads(SRC.read_text())
    ids = json.loads(IDS.read_text()) if IDS.exists() else {}
    rec, table = {"created": stamp}, []

    def build(key, src):
        g = R2.geom(src["design"], float(src["h_cut"]))
        fe = fe_of(ids.get(key))
        table.append(table_row(key, g, fe))
        rec[key] = {k: v for k, v in fe.items() if not k.startswith("_")}
        print(key, json.dumps(rec[key], default=float)[:300], flush=True)
        return g, fe

    cells = []
    for L in R2.LENGTHS:
        row = []
        for w in R2.WIDTHS:
            k = R2.code(L, w)
            g, fe = build(k, Rj["fig1"][k])
            row.append((g, fe, k, metric_lines(g, fe)))
        cells.append(row)
    n_done = sum(1 for r in cells for c in r if c[1].get("state") == "DONE")
    grid_figure(cells, 3, 3, [f"{R2.LEN_NAME[L]}, L {L:.0f} mm" for L in R2.LENGTHS], [R2.WID_NAME[w] for w in R2.WIDTHS],
                "Stage 1 – nine candidate classes (stem length × collar), one example per class",
                FOOT + f"\nFE available for {n_done}/9 cells at {stamp}.", OUT / "ref3_fig1_nine_classes.png")

    cells, row_labels = [], []
    classes = sorted({k.rsplit("-", 1)[0] for k in Rj["fig2"]}, key=lambda c: -float(c[1:3]))
    roles = {classes[0]: "overall best (placeholder)", classes[-1]: "shortest stem"} if len(classes) == 2 else {}
    for cls in classes:
        row, ref = [], None
        for tag in "abcd":
            k = f"{cls}-{tag}"
            g, fe = build(k, Rj["fig2"][k])
            if tag == "a":
                ref = {**fe, "_removal": g["removal"]}
            row.append((g, fe, k, metric_lines(g, fe, None if tag == "a" else ref)))
        cells.append(row)
        L, w = R2.parse(cls[1:3] + "/" + cls[-1])
        row_labels.append(f"{cls}: {R2.LEN_NAME[L]}, {R2.WID_NAME[w]}" + (f"\n{roles[cls]}" if cls in roles else ""))
    n_done = sum(1 for r in cells for c in r if c[1].get("state") == "DONE")
    grid_figure(cells, len(classes), 4, row_labels,
                ["a · start (Stage 1 example)", "b · insertion angle", "c · resection depth", "d · section shape"],
                "Stage 2 – two classes × four candidates: one optimisation variable changed at a time from the Stage 1 example",
                FOOT + " Columns b–d are one-at-a-time changes chosen by geometric rules, not optimised; classes are placeholders until "
                f"Stage 1 FE results exist.\nFE available for {n_done}/8 cells at {stamp}.", OUT / "ref3_fig2_eight_candidates.png",
                fs=4.8)

    with open(OUT / "ref3_design_table.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader(); wr.writerows(table)
    md = ["| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)] + ["| " + " | ".join(str(r[c]) for c in COLS) + " |" for r in table]
    (OUT / "ref3_design_table.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (OUT / "ref3_figs.json").write_text(json.dumps(rec, indent=1, default=float))
    print("written", OUT, flush=True)


if __name__ == "__main__":
    main()
