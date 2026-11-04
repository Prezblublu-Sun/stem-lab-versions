"""仿 Naghavi 2023 第 5 章的三种展示：分区示意、剖面云图组、分区柱状图（Linux，只读；adhoc）。用户 2026-10-02：用现有数据画。

数据：已解的 7 个界面模型作业（过盈 0.025 mm、生产网格），柄长 25 / 30 / 60 mm，有领与无领。完整股骨参照 = 标准参照作业。
分区：固定解剖分区（resorption.zones_fixed：小转子为 0，−10 / −40 / −70 / −100 mm，内外侧按 x = 0 分），不随柄长变化，柄长不同也可比。
剖面：颈平面（过颈轴、含竖直方向，柄轴也在这个面内）。场值 = 粘接模型 LOAD 步的单元值映射到 0.5 mm 的平面网格（最近 4 个单元体积加权）。
柱状图：皮质，固定分区，resorption.design_rows 的 sed_chg_pct（应变能相对完整股骨）与 res_0.6（骨吸收，死区 0.6）。

    run.sh ../adhoc/ata_style/ata_style.py   → adhoc/ata_style/out/fig_A_zones.png、fig_B_sections.png、fig_C_zone_bars.png、ata_style.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import fe3d_geom as E  # noqa: E402
import jobs as J  # noqa: E402
import plotstyle as ps  # noqa: E402
import cases_real as CR  # noqa: E402
import resorption as RS  # noqa: E402
import shielding as SH  # noqa: E402
from matplotlib.patches import Polygon as MP  # noqa: E402
from matplotlib.colors import TwoSlopeNorm, Normalize, ListedColormap  # noqa: E402
from scipy.spatial import ConvexHull  # noqa: E402

plt = ps.plt
OUT = HOME / "adhoc" / "ata_style" / "out"
DESIGNS = [  # (键, 柄长, 领说明, 作业, 颜色)
    ("L25-W0", 25, "no collar", "m1_short_h2_tol0.00025_delta0.025_7f62c025", "#F2B65A"),
    ("L25-W3", 25, "3 mm collar", "collar_short_w3_35350236", "#B86E00"),
    ("L30-W0", 30, "no collar", "collar_neck_w0_9e92d3e1", "#7FD1B9"),
    ("L30-W3", 30, "3 mm collar", "collar_neck_w3_36c2bb73", "#00805C"),
    ("L60-W0", 60, "no collar", "collar_base_w0_d23f6d02", "#9CCDEB"),
    ("L60-W2", 60, "2 mm collar", "collar_base_w2_9d3e7e27", "#3C8FC7"),
    ("L60-W4", 60, "4 mm collar", "collar_base_w4_b3e685fe", "#0B4F7C"),
]
FAMILY = {25: "asymmetric section, insertion 37°", 30: "elliptical section, insertion 40°", 60: "asymmetric section, insertion 20°"}
SECTION_COLS = ["intact", "L25-W0", "L25-W3", "L30-W0", "L30-W3", "L60-W0", "L60-W4"]
SCHEMA_COLS = ["intact", "L25-W3", "L30-W3", "L60-W2"]
AX = (-50.0, 52.0)                                   # 颈平面坐标 a（内侧为正）
ZR = (-108.0, 95.0)                                  # 股骨坐标 z（小转子为 0）
STEP = 0.5
ZONE_C = ["#9FC5E8", "#B6D7A8", "#FFE599", "#EA9999", "#B4A7D6", "#F9CB9C", "#76A5AF"]
STEM_GREY = "#7A7A7A"
_C = {}


def fm0():
    if "fm" not in _C:
        _C["fm"] = FR.build()
    return _C["fm"]


def plane_grid():
    if "pg" not in _C:
        fm = fm0()
        C, e1, e2 = fm.neck_plane()
        a = np.arange(AX[0], AX[1], STEP)
        z = np.arange(ZR[0], ZR[1], STEP)
        A, Z = np.meshgrid(a, z)
        P = C + A.reshape(-1, 1) * e1 + (Z.reshape(-1, 1) - C[2]) * e2
        bone = fm.outer_sdf(P) <= 0
        canc = fm.canal_sdf(P) <= 0
        _C["pg"] = {"a": a, "z": z, "shape": A.shape, "P": P, "bone": bone, "canc": canc & bone, "C": C, "e1": e1}
    return _C["pg"]


def to_xy(P):
    """三维点 → 颈平面图坐标 (a, z)。"""
    C, e1 = fm0().neck_plane()[:2]
    Q = np.atleast_2d(P) - C
    return np.c_[Q @ e1, np.atleast_2d(P)[:, 2]]


def design_geom(job):
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    res = J.result(job)
    t = res["templating"]
    st = G.Stem3D(**spec["design"])
    fm = fm0().with_cut(float(spec.get("h_cut", 25.0)))
    pl = {"A0": t["A0"], "alpha": t["alpha"], "e": t["e"], "pose": fm.pose(t["alpha"], t["e"])}
    col = E.collar_outline(st, fm, pl) if st.has_collar else None
    return {"spec": spec, "res": res, "st": st, "fm": fm, "pl": pl, "collar": col}


def fields_on_plane(job):
    pg = plane_grid()
    fl = SH.load_fields(SH.intact_job(True) if job == "intact" else J.QROOT / job)
    g = RS.to_grid(fl, pg["P"], pg["canc"], k=4)
    return g


def masks_for(geo):
    pg = plane_grid()
    if geo is None:
        keep = pg["bone"] & fm0().below_cut(pg["P"]) if False else pg["bone"].copy()
        return keep, np.zeros_like(keep)
    fm, st, pl = geo["fm"], geo["st"], geo["pl"]
    loc = SH.local(pg["P"], pl["pose"])
    stem = G.inside_stem(st, pl["A0"], loc) & fm.below_cut(pg["P"])
    keep = pg["bone"] & fm.below_cut(pg["P"]) & ~stem
    return keep, stem


def draw_implant(ax, geo):
    if geo is None:
        return
    fm, st, pl = geo["fm"], geo["st"], geo["pl"]
    C0 = fm0().neck_plane()[0]
    poly = CR.stem_silhouette(fm, st, pl)
    for p in getattr(poly, "geoms", [poly]):
        if p.geom_type == "Polygon":
            xy = np.asarray(p.exterior.coords)
            ax.add_patch(MP(np.c_[xy[:, 0], xy[:, 1] + C0[2]], closed=True, fc=STEM_GREY, ec="#333333", lw=0.3, zorder=4))
    if geo["collar"]:
        Cc, c1, c2, nrm = E.cut_plane(fm)
        uv = np.array(geo["collar"]["poly"].exterior.coords)
        B = Cc + uv[:, :1] * c1 + uv[:, 1:2] * c2
        xy = to_xy(np.vstack([B, B + st.collar_t * nrm]))
        h = ConvexHull(xy)
        ax.add_patch(MP(xy[h.vertices], closed=True, fc=STEM_GREY, ec="#333333", lw=0.3, zorder=4))
    # 假体颈与头的示意（虚线轮廓）
    u = fm.u3 / np.linalg.norm(fm.u3)
    p0, p1 = to_xy(fm.C03 + 2.5 * u)[0], to_xy(fm.H)[0]
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color="#333333", lw=0.4, ls=(0, (2, 1.5)), zorder=4)


def zone_overlay(ax, fs=4.6):
    pg = plane_grid()
    a0 = -pg["C"][0] / pg["e1"][0]                     # x = 0 在平面上的位置
    bone = pg["bone"].reshape(pg["shape"])
    a, z = pg["a"], pg["z"]
    for zl in RS.FIXED_Z:
        row = np.argmin(abs(z - zl))
        cols = np.nonzero(bone[row])[0]
        if len(cols):
            ax.plot([a[cols.min()] - 3, a[cols.max()] + 3], [zl, zl], color="black", lw=0.5, zorder=5)
    rows = np.nonzero((z >= RS.FIXED_Z[2]) & (z <= RS.FIXED_Z[0] + 25))[0]
    ax.plot([a0, a0], [RS.FIXED_Z[2], RS.FIXED_Z[0] + 25], color="black", lw=0.4, ls=(0, (3, 2)), zorder=5)
    zm = RS.zones_fixed(pg["P"])
    for i, k in enumerate(RS.ZONES):
        m = (zm[k] & pg["bone"]).reshape(pg["shape"])
        if k in ("G1", "G7"):
            m &= (z[:, None] < RS.FIXED_Z[0] + 22)
        if not m.any():
            continue
        r, c = np.nonzero(m)
        # 放在该区皮质外缘附近：取该区最外侧的列
        cc = c.min() if k in ("G1", "G2", "G3") else (c.max() if k in ("G5", "G6", "G7") else int(np.median(c)))
        rr = int(np.median(r))
        xa = a[cc] + (-4 if k in ("G1", "G2", "G3") else (4 if k in ("G5", "G6", "G7") else 0))
        ax.text(xa, z[rr], k[1], fontsize=fs, ha="center", va="center", fontweight="bold", zorder=6)
    ax.text(AX[1] - 1, 1.5, "LT", fontsize=fs - 0.6, ha="right", va="bottom", color="#444444", zorder=6)
    ax.axhline(0.0, color="#666666", lw=0.3, ls=(0, (1, 1.5)), zorder=5)


def base_img(keep, stem, canc):
    img = np.ones(keep.shape + (3,))
    img[keep & ~canc] = CR.CORT
    img[keep & canc] = CR.CANC
    return img


def frame(ax):
    ax.set_xlim(AX[0] - 6, AX[1] + 6); ax.set_ylim(ZR[0], ZR[1]); ax.set_aspect("equal")
    CR._off(ax)


# ------------------------------------------------------------------ 图 A：分区示意
def fig_A(geos):
    pg = plane_grid()
    fig = plt.figure(figsize=(190 * ps.MM, 92 * ps.MM))
    W = 0.235
    for i, key in enumerate(SCHEMA_COLS):
        ax = fig.add_axes([0.02 + i * 0.245, 0.10, W, 0.80])
        geo = geos.get(key)
        keep, stem = masks_for(geo)
        img = base_img(keep, stem, pg["canc"]).reshape(pg["shape"] + (3,))
        if key == "intact":
            zm = RS.zones_fixed(pg["P"])
            sh = np.zeros(pg["shape"] + (3,)); has = np.zeros(pg["shape"], bool)
            cort = (~pg["canc"]).reshape(pg["shape"])
            for j, k in enumerate(RS.ZONES):
                m = (zm[k] & keep).reshape(pg["shape"])
                sh[m] = plt.matplotlib.colors.to_rgb(ZONE_C[j]); has |= m
            img[has] = 0.25 * img[has] + 0.75 * sh[has]
            img[has & cort] = np.clip(img[has & cort] * 0.78, 0, 1)                 # 皮质压暗一档，仍看得出皮质层
        else:
            res = np.ones(pg["shape"], bool) & pg["bone"].reshape(pg["shape"]) & ~keep.reshape(pg["shape"]) & ~stem.reshape(pg["shape"])
            img[res] = 0.6 * np.array(CR.CORT) + 0.4
            img[stem.reshape(pg["shape"])] = plt.matplotlib.colors.to_rgb(STEM_GREY)   # 柄的真实剖面（含尖端帽），轮廓只是外形
        ax.imshow(img, origin="lower", extent=(AX[0], AX[1], ZR[0], ZR[1]), interpolation="nearest")
        draw_implant(ax, geo)
        zone_overlay(ax)
        frame(ax)
        title = "intact femur" if key == "intact" else f"{key}: L {geo['st'].L:.0f} mm, {dict((d[0], d[2]) for d in DESIGNS)[key]}"
        ax.set_title(f"({chr(97 + i)}) {title}", fontsize=6, loc="left", pad=2)
    fig.text(0.02, 0.965, "Gruen zones used in this project — fixed anatomical bands (same for every stem length)", fontsize=6.8, va="top")
    fig.text(0.02, 0.03, "Bands 0 to −10 mm (and above), −10…−40, −40…−70, −70…−100 mm relative to the lesser trochanter (LT); lateral zones 1–3, "
             "zone 4 below, medial zones 5–7; split at the shaft axis (dashed). Coronal section through the neck axis; grey = cortex, "
             "beige = cancellous, pale = resected, dark grey = implant. Zones 1 and 7 include the greater trochanter and the calcar / medial neck.",
             fontsize=4.6, va="bottom", color="#444444", wrap=True)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_A_zones.png", dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 图 B：剖面云图组
def fig_B(geos, info):
    pg = plane_grid()
    gi = fields_on_plane("intact")
    n = len(SECTION_COLS)
    left, cw = 0.065, (0.995 - 0.065) / n
    fig = plt.figure(figsize=(190 * ps.MM, 128 * ps.MM))
    vm_cmap = plt.get_cmap("turbo"); vm_norm = Normalize(0, 30)
    r_cmap = plt.get_cmap("RdBu_r"); r_norm = TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=2.0)
    for i, key in enumerate(SECTION_COLS):
        geo = geos.get(key)
        keep, stem = masks_for(geo)
        g = gi if key == "intact" else fields_on_plane(info[key]["job"])
        for r, (what, cmap, norm) in enumerate((("vm", vm_cmap, vm_norm), ("ratio", r_cmap, r_norm))):
            ax = fig.add_axes([left + i * cw, 0.50 - r * 0.41, cw * 0.98, 0.375])
            img = np.ones(pg["shape"] + (4,))
            if what == "vm":
                v = g["vm"]
                ok = keep & np.isfinite(v)
                rgba = cmap(norm(np.where(ok, v, 0)))
            else:
                if key == "intact":
                    v = np.zeros(len(keep)); ok = keep.copy()
                else:
                    v = np.log2(g["sed"] / gi["sed"])
                    ok = keep & np.isfinite(v) & (gi["sed"] > 0)
                rgba = cmap(norm(np.clip(np.where(ok, v, 0), -2, 2)))
            img = img.reshape(-1, 4); img[ok] = rgba[ok]
            res = pg["bone"] & ~keep & ~stem
            img[res] = [0.88, 0.88, 0.88, 1.0]
            img[stem] = [*plt.matplotlib.colors.to_rgb(STEM_GREY), 1.0]                    # 柄的真实剖面（含尖端帽）
            ax.imshow(img.reshape(pg["shape"] + (4,)), origin="lower", extent=(AX[0], AX[1], ZR[0], ZR[1]), interpolation="nearest")
            draw_implant(ax, geo)
            zone_overlay(ax, fs=4.0)
            frame(ax)
            if r == 0:
                if key == "intact":
                    head = "intact femur"
                else:
                    d = info[key]
                    head = (f"{key}\nL {d['L']} mm, {d['collar']}\nmicromotion {d['f1_p95_um']:.1f} µm\n"
                            f"zone 7 strain energy {d['zones']['G7']['sed_chg_pct']:+.0f} %")
                ax.set_title(head, fontsize=4.8, loc="left", pad=2, linespacing=1.15)
    fig.text(0.004, 0.69, "(a) von Mises stress", rotation=90, fontsize=6, va="center", fontweight="bold")
    fig.text(0.004, 0.28, "(b) strain energy vs intact", rotation=90, fontsize=6, va="center", fontweight="bold")
    c1 = fig.add_axes([left, 0.055, 0.30, 0.012])
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=vm_norm, cmap=vm_cmap), cax=c1, orientation="horizontal", extend="max")
    cb.ax.tick_params(labelsize=4.6, length=1.5, pad=1); cb.set_label("von Mises stress (MPa)", fontsize=4.8, labelpad=1)
    c2 = fig.add_axes([left + 0.38, 0.055, 0.30, 0.012])
    cb = plt.colorbar(plt.cm.ScalarMappable(norm=r_norm, cmap=r_cmap), cax=c2, orientation="horizontal", extend="both")
    cb.set_ticks([-2, np.log2(0.4), 0, 1, 2]); cb.set_ticklabels(["0.25×", "0.4× (resorption)", "1×", "2×", "4×"])
    cb.ax.tick_params(labelsize=4.4, length=1.5, pad=1); cb.set_label("strain energy density, implanted / intact", fontsize=4.8, labelpad=1)
    fig.text(left, 0.985, "Coronal section through the neck axis: stress and strain-energy change with stem length and collar "
             "(stair-climbing load 2391 N, bonded interface)", fontsize=6.6, va="top")
    fig.text(left + 0.72, 0.012, "Light grey = resected bone; dark grey = implant.\nZones = fixed Gruen bands (figure A).", fontsize=4.4,
             va="bottom", color="#444444")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_B_sections.png", dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 图 C：分区柱状图
def fig_C(info):
    zones = list(RS.ZONES) + ["total"]
    labels = [f"Gruen\nzone {z[1]}" for z in RS.ZONES] + ["Total"]
    fig = plt.figure(figsize=(190 * ps.MM, 125 * ps.MM))
    keys = [d[0] for d in DESIGNS]
    nb = len(keys)
    bw = 0.8 / nb
    x = np.arange(len(zones))
    for r, (what, ylab, title) in enumerate((("sed_ratio", "cortical strain energy\nimplanted / intact (%)",
                                             "(a) Cortical strain energy relative to the intact femur"),
                                            ("res", "cortical bone predicted\nto resorb (%)",
                                             "(b) Bone resorption (dead zone 0.6, as in the thesis)"))):
        ax = fig.add_axes([0.09, 0.56 - r * 0.45, 0.89, 0.34])
        for j, (k, L, col_, job, c) in enumerate(DESIGNS):
            z = info[k]["zones"]
            v = [(100 + z[q]["sed_chg_pct"]) if what == "sed_ratio" else z[q]["res_0.6"] for q in zones]
            ax.bar(x - 0.4 + bw * (j + 0.5), v, bw * 0.92, color=c, label=f"{k} ({col_})", zorder=3)
        if what == "sed_ratio":
            ax.axhline(100, color="#222222", lw=0.6, ls=(0, (4, 2)), zorder=4)
            ax.text(len(zones) - 0.45, 102, "intact = 100 %", fontsize=4.6, ha="right", va="bottom")
            ax.axhline(40, color="#C00000", lw=0.5, ls=(0, (1, 1.5)), zorder=4)
            ax.text(len(zones) - 0.45, 41, "resorption threshold 40 %", fontsize=4.4, ha="right", va="bottom", color="#C00000",
                    bbox=dict(fc="white", ec="none", pad=0.6), zorder=6)
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=5)
        ax.tick_params(axis="y", labelsize=5)
        ax.set_ylabel(ylab, fontsize=5.4)
        ax.set_title(title, fontsize=6.2, loc="left", pad=3)
        ax.grid(axis="y", lw=0.3, alpha=0.5, zorder=0)
        ax.axvline(len(zones) - 1.5, color="#999999", lw=0.4)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        if r == 0:
            ax.legend(ncol=7, fontsize=4.6, frameon=False, loc="upper left", bbox_to_anchor=(0.0, 1.2), handlelength=1.2, columnspacing=1.0)
    fig.text(0.09, 0.01, "Fixed anatomical Gruen bands (figure A), cortex only, bonded model. Strain energy = zone mean of the element strain "
             "energy density mapped to a common 1.5 mm grid; resorption = share of cortical points whose strain energy falls below 40 % of "
             "intact. Stem families differ: 25 mm " + FAMILY[25] + "; 30 mm " + FAMILY[30] + "; 60 mm " + FAMILY[60] + ".",
             fontsize=4.4, va="bottom", color="#444444", wrap=True)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_C_zone_bars.png", dpi=250)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RS._init()
    info, geos = {}, {}
    for k, L, col_, job, c in DESIGNS:
        if J.state(J.QROOT / job) != "DONE":
            raise SystemExit(f"{job} not DONE")
        rows, srow = RS.design_rows(job)
        z = {x["zone"]: {kk: x.get(kk) for kk in ("sed_chg_pct", "ssi_pct", "res_0.6", "vol")} for x in rows
             if x["scheme"] == "fixed" and x["tissue"] == "cortex"}
        r = J.result(job)
        info[k] = {"job": job, "L": L, "collar": col_, "f1_p95_um": r.get("f1_p95_um"), "collar_share": r.get("collar_force_share_load2"),
                   "zones": z}
        geos[k] = design_geom(job)
        print(k, job, "P95", round(r.get("f1_p95_um"), 2), {q: (round(v["sed_chg_pct"], 1), round(v["res_0.6"], 1)) for q, v in z.items()
                                                           if v.get("sed_chg_pct") is not None}, flush=True)
    (OUT / "ata_style.json").write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "designs": info}, indent=1, default=float))
    fig_A(geos)
    print("A done", flush=True)
    fig_C(info)
    print("C done", flush=True)
    fig_B(geos, info)
    print("B done", flush=True)


if __name__ == "__main__":
    main()
