"""三种展示的 Ata 口径版（Linux，只读；adhoc）。用户 2026-10-02：用 Naghavi 2023 的分区口径重新作图。

分区 = resorption.zones_femur（论文图 5-9 的口径）：柄入口到柄尖（含尖端帽）的竖直范围 H 三等分，自上而下为 1/7、2/6、3/5 区，
内外侧按柄轴线分；4 区在柄尖以下，高 max(H/3, 10 mm)。1、7 区向上不设上限（含大转子与截骨面以下的内侧颈）。分区随每根柄变化。
其余（剖面、场值映射、骨吸收算法、数据）与 ata_style.py 相同。

    run.sh ../adhoc/ata_style/ata_style_ata.py   → adhoc/ata_style/out_ata/fig_A_zones_ata.png、fig_B_sections_ata.png、fig_C_zone_bars_ata.png、ata_style_ata.json
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "ata_style"))
import ata_style as A  # noqa: E402
from ata_style import J, RS, CR, ps, plt, MP, Normalize, TwoSlopeNorm  # noqa: E402

OUT = HOME / "adhoc" / "ata_style" / "out_ata"
SCHEME = "femur"
ZDEF = ("Gruen zones as in Naghavi 2023 (Fig. 5-9): the stem's vertical extent from entry to tip is split into thirds (zones 1/7, 2/6, 3/5 "
        "from the top), lateral/medial at the stem axis; zone 4 lies below the tip (height max(H/3, 10 mm)); zones 1 and 7 have no upper "
        "limit and include the greater trochanter and the medial neck below the cut. The zones therefore differ for every stem.")


def levels(geo):
    st, pl = geo["st"], geo["pl"]
    P0, d = pl["pose"][:2]
    Ltot = st.L + st.cap_length(pl["A0"])
    z_top, z_tip = float(P0[2]), float((P0 + Ltot * d)[2])
    H = z_top - z_tip
    return {"P0": P0, "tip": P0 + Ltot * d, "Ltot": Ltot, "z_top": z_top, "z_tip": z_tip, "H": H,
            "lines": [z_tip + 2 * H / 3, z_tip + H / 3, z_tip, z_tip - max(H / 3, 10.0)]}


def zmasks(geo):
    pg = A.plane_grid()
    lv = levels(geo)
    return RS.zones_femur(pg["P"], geo["pl"]["pose"], lv["Ltot"], geo["fm"].e_med0)


def zone_overlay(ax, geo, fs=4.6, split_colour="white"):
    pg = A.plane_grid()
    bone = pg["bone"].reshape(pg["shape"])
    a, z = pg["a"], pg["z"]
    ax.axhline(0.0, color="#666666", lw=0.3, ls=(0, (1, 1.5)), zorder=5)
    ax.text(A.AX[1] - 1, 1.5, "LT", fontsize=fs - 0.6, ha="right", va="bottom", color="#444444", zorder=6)
    if geo is None:
        return
    lv = levels(geo)
    for zl in lv["lines"]:
        row = int(np.argmin(abs(z - zl)))
        cols = np.nonzero(bone[row])[0]
        if len(cols):
            ax.plot([a[cols.min()] - 3, a[cols.max()] + 3], [zl, zl], color="black", lw=0.5, zorder=5)
    p0, p1 = A.to_xy(lv["P0"])[0], A.to_xy(lv["tip"])[0]
    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=split_colour, lw=0.5, ls=(0, (2, 1.5)), zorder=6)
    zm = zmasks(geo)
    for k in RS.ZONES:
        m = (zm[k] & pg["bone"]).reshape(pg["shape"])
        if k in ("G1", "G7"):
            m &= (z[:, None] <= lv["z_top"])
        if not m.any():
            continue
        r, c = np.nonzero(m)
        rr = int(np.median(r))
        rowc = c[r == rr] if (r == rr).any() else c
        if k in ("G1", "G2", "G3"):
            xa = a[rowc.min()] - 3.5
        elif k in ("G5", "G6", "G7"):
            xa = a[rowc.max()] + 3.5
        else:
            xa = a[int(np.median(rowc))]
        ax.text(xa, z[rr], k[1], fontsize=fs, ha="center", va="center", fontweight="bold", zorder=7)


def shaded(img, keep, zm):
    pg = A.plane_grid()
    sh = np.zeros(pg["shape"] + (3,)); has = np.zeros(pg["shape"], bool)
    cort = (~pg["canc"]).reshape(pg["shape"])
    for j, k in enumerate(RS.ZONES):
        m = (zm[k] & keep).reshape(pg["shape"])
        sh[m] = plt.matplotlib.colors.to_rgb(A.ZONE_C[j]); has |= m
    img[has] = 0.25 * img[has] + 0.75 * sh[has]
    img[has & cort] = np.clip(img[has & cort] * 0.78, 0, 1)
    return img


# ------------------------------------------------------------------ 图 A
def fig_A(geos):
    pg = A.plane_grid()
    fig = plt.figure(figsize=(190 * ps.MM, 96 * ps.MM))
    ref = geos["L60-W2"]
    for i, key in enumerate(A.SCHEMA_COLS):
        ax = fig.add_axes([0.02 + i * 0.245, 0.13, 0.235, 0.77])
        geo = geos.get(key)
        keep, stem = A.masks_for(geo)
        img = A.base_img(keep, stem, pg["canc"]).reshape(pg["shape"] + (3,))
        img = shaded(img, keep, zmasks(ref if geo is None else geo))
        if geo is not None:
            res = pg["bone"].reshape(pg["shape"]) & ~keep.reshape(pg["shape"]) & ~stem.reshape(pg["shape"])
            img[res] = 0.6 * np.array(CR.CORT) + 0.4
            img[stem.reshape(pg["shape"])] = plt.matplotlib.colors.to_rgb(A.STEM_GREY)
        ax.imshow(img, origin="lower", extent=(A.AX[0], A.AX[1], A.ZR[0], A.ZR[1]), interpolation="nearest")
        A.draw_implant(ax, geo)
        zone_overlay(ax, ref if geo is None else geo, split_colour="black" if geo is None else "white")
        A.frame(ax)
        if geo is None:
            title = "intact femur (zones of the 60 mm stem)"
        else:
            title = f"{key}: L {geo['st'].L:.0f} mm, {dict((d[0], d[2]) for d in A.DESIGNS)[key]}"
        ax.set_title(f"({chr(97 + i)}) {title}", fontsize=6, loc="left", pad=2)
    fig.text(0.02, 0.965, "Gruen zones as defined in Naghavi 2023 — bands set by each stem", fontsize=6.8, va="top")
    fig.text(0.02, 0.025, ZDEF + " Coronal section through the neck axis; pale = resected, dark grey = implant, dashed = stem axis (medial/lateral split).",
             fontsize=4.6, va="bottom", color="#444444", wrap=True)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_A_zones_ata.png", dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 图 B
def fig_B(geos, info):
    pg = A.plane_grid()
    gi = A.fields_on_plane("intact")
    n = len(A.SECTION_COLS)
    left, cw = 0.065, (0.995 - 0.065) / n
    fig = plt.figure(figsize=(190 * ps.MM, 128 * ps.MM))
    vm_cmap = plt.get_cmap("turbo"); vm_norm = Normalize(0, 30)
    r_cmap = plt.get_cmap("RdBu_r"); r_norm = TwoSlopeNorm(vmin=-2.0, vcenter=0.0, vmax=2.0)
    for i, key in enumerate(A.SECTION_COLS):
        geo = geos.get(key)
        keep, stem = A.masks_for(geo)
        g = gi if key == "intact" else A.fields_on_plane(info[key]["job"])
        for r, (what, cmap, norm) in enumerate((("vm", vm_cmap, vm_norm), ("ratio", r_cmap, r_norm))):
            ax = fig.add_axes([left + i * cw, 0.50 - r * 0.41, cw * 0.98, 0.375])
            img = np.ones(pg["shape"] + (4,))
            if what == "vm":
                v = g["vm"]; ok = keep & np.isfinite(v)
                rgba = cmap(norm(np.where(ok, v, 0)))
            else:
                if key == "intact":
                    v = np.zeros(len(keep)); ok = keep.copy()
                else:
                    v = np.log2(g["sed"] / gi["sed"]); ok = keep & np.isfinite(v) & (gi["sed"] > 0)
                rgba = cmap(norm(np.clip(np.where(ok, v, 0), -2, 2)))
            img = img.reshape(-1, 4); img[ok] = rgba[ok]
            img[pg["bone"] & ~keep & ~stem] = [0.88, 0.88, 0.88, 1.0]
            img[stem] = [*plt.matplotlib.colors.to_rgb(A.STEM_GREY), 1.0]
            ax.imshow(img.reshape(pg["shape"] + (4,)), origin="lower", extent=(A.AX[0], A.AX[1], A.ZR[0], A.ZR[1]), interpolation="nearest")
            A.draw_implant(ax, geo)
            zone_overlay(ax, geo, fs=4.0)
            A.frame(ax)
            if r == 0:
                if key == "intact":
                    head = "intact femur\n(zones follow each stem)"
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
    fig.text(left, 0.985, "Coronal section through the neck axis: stress and strain-energy change with stem length and collar",
             fontsize=6.6, va="top")
    fig.text(left + 0.72, 0.008, "Stair-climbing load 2391 N, bonded interface.\nGruen zones as in Naghavi 2023, set by each stem\n"
             "(figure A). Light grey = resected; dark grey = implant.", fontsize=4.4, va="bottom", color="#444444")
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_B_sections_ata.png", dpi=250)
    plt.close(fig)


# ------------------------------------------------------------------ 图 C
def fig_C(info):
    zones = list(RS.ZONES) + ["total"]
    labels = [f"Gruen\nzone {z[1]}" for z in RS.ZONES] + ["Total"]
    fig = plt.figure(figsize=(190 * ps.MM, 128 * ps.MM))
    nb = len(A.DESIGNS)
    bw = 0.8 / nb
    x = np.arange(len(zones))
    for r, (what, ylab, title) in enumerate((("sed_ratio", "cortical strain energy\nimplanted / intact (%)",
                                             "(a) Cortical strain energy relative to the intact femur"),
                                            ("res", "cortical bone predicted\nto resorb (%)",
                                             "(b) Bone resorption (dead zone 0.6)"))):
        ax = fig.add_axes([0.09, 0.575 - r * 0.45, 0.89, 0.33])
        for j, (k, L, col_, job, c) in enumerate(A.DESIGNS):
            z = info[k]["zones"]
            v = [((100 + z[q]["sed_chg_pct"]) if what == "sed_ratio" else z[q]["res_0.6"]) if z.get(q, {}).get("sed_chg_pct") is not None
                 else np.nan for q in zones]
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
    vols = " · ".join(f"{k} {info[k]['zones']['G7']['vol'] / 1000:.2f}" for k in [d[0] for d in A.DESIGNS])
    fig.text(0.09, 0.008, ZDEF + " Cortex only, bonded model; strain energy = zone mean of the element strain energy density on a common "
             f"1.5 mm grid; resorption = share of cortical points below 40 % of intact. Zone 7 cortical volume (cm³): {vols}. Stem families "
             "differ: 25 mm " + A.FAMILY[25] + "; 30 mm " + A.FAMILY[30] + "; 60 mm " + A.FAMILY[60] + ".",
             fontsize=4.3, va="bottom", color="#444444", wrap=True)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / "fig_C_zone_bars_ata.png", dpi=250)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RS._init()
    info, geos = {}, {}
    for k, L, col_, job, c in A.DESIGNS:
        rows, _ = RS.design_rows(job)
        z = {x["zone"]: {kk: x.get(kk) for kk in ("sed_chg_pct", "ssi_pct", "res_0.6", "vol")} for x in rows
             if x["scheme"] == SCHEME and x["tissue"] == "cortex"}
        r = J.result(job)
        info[k] = {"job": job, "L": L, "collar": col_, "f1_p95_um": r.get("f1_p95_um"), "collar_share": r.get("collar_force_share_load2"),
                   "zones": z}
        geos[k] = A.design_geom(job)
        lv = levels(geos[k])
        info[k]["zone_levels_z"] = {"top": lv["z_top"], "lines": lv["lines"]}
        print(k, {q: (None if v.get("sed_chg_pct") is None else round(v["sed_chg_pct"], 1), None if v.get("res_0.6") is None else
                      round(v["res_0.6"], 1), round(v["vol"] / 1000, 2)) for q, v in z.items()}, flush=True)
    (OUT / "ata_style_ata.json").write_text(json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "scheme": SCHEME, "designs": info},
                                                       indent=1, default=float))
    fig_A(geos); print("A done", flush=True)
    fig_C(info); print("C done", flush=True)
    fig_B(geos, info); print("B done", flush=True)


if __name__ == "__main__":
    main()
