"""Field-map composite figures for the interim report v6 — simplified: key information only, one-sentence title.
Read-only on the queue; writes adhoc/plan/out/<name>.{png,json}.

    run.sh adhoc/plan/fig_maps.py best3     intact femur + the three best-ranked collared stems (one per length)
    run.sh adhoc/plan/fig_maps.py collar    intact femur + the first implant with and without its collar

Rows: coronal placement; bone von Mises on the neck plane (bonded model); strain-energy change vs intact (box-averaged 5 mm per tissue);
3-D stem coloured by recoverable micromotion (press-fit model). One line of key numbers under each column.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "adhoc" / "plan")); sys.path.insert(0, str(HOME / "adhoc" / "reffig2"))
import plan_figs as PF  # noqa: E402
from plan_figs import R2, R3, G, CR, ps, plt, J  # noqa: E402
import shielding as SH  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402

OUT = HOME / "adhoc" / "plan" / "out"
MAP_U, MAP_V = (-46.0, 46.0), (-70.0, 35.0)
COR_V = (-70.0, 46.0)
S_NORM = LogNorm(0.3, 60.0)
TITLE_FS, HEAD_FS, ROW_FS, LAB_FS = 9.5, 7.0, 6.8, 6.3
VARIANTS = {
    "best3": dict(
        out="fig5_best3_maps",
        pick=[("circle", "collar_neck_circ_w3_3e52efc7", "circle"),
              ("ellipse", "collar_neck_w3_36c2bb73", "ellipse (first implant)"),
              ("asymmetric", "collar_neck_asym_w3_4f71e698", "asymmetric")],
        heads=lambda cols: ["intact femur"] + [lab for _, _, lab, *_ in cols],
        title="Three sections, same length and collar: the section mostly changes bone removed"),
    "collar": dict(
        out="fig6_collar_vs_none",
        pick=[("with collar", "collar_neck_w3_36c2bb73", "first implant, 3 mm collar"),
              ("no collar", "collar_neck_w0_9e92d3e1", "same stem, collarless")],
        heads=lambda cols: ["intact femur"] + [lab for _, _, lab, *_ in cols],
        title="The collar restores load transfer to the medial cortex and cuts micromotion by two-thirds"),
    "stages": dict(
        out="fig8_stage_maps",
        pick=[("first", "collar_neck_w3_36c2bb73", "first implant, 30 mm"),
              ("s1", "neck1_r6_102aba81", "Round 1 knee design, 49 mm"),
              ("s2", "neck2_r7_87dc94f4", "Round 2 thin stem, 49 mm")],
        heads=lambda cols: ["intact femur"] + [lab for _, _, lab, *_ in cols],
        title="Round 1 chose a slender long stem; Round 2 thinned it and unloaded less cortex"),
}


def intact_coronal(ax):
    f0 = R2.fm0(); fm = f0.with_cut(25.0)
    C, e1, e2 = f0.neck_plane()
    a = np.arange(R2.EXT[0][0], R2.EXT[0][1], 0.25); b = np.arange(R2.EXT[1][0], R2.EXT[1][1], 0.25)
    A, B = np.meshgrid(a, b)
    P = C + A.reshape(-1, 1) * e1 + B.reshape(-1, 1) * e2
    lab = np.where(f0.canal_sdf(P) <= 0, 2, np.where(f0.outer_sdf(P) <= 0, 1, 0)).reshape(A.shape)
    ax.imshow(CR._rgb(lab, np.ones_like(lab, bool)), origin="lower", extent=(a[0], a[-1], b[0], b[-1]), interpolation="nearest")
    y_lt = -float(C[2])
    ax.axhline(y_lt, color="#555555", lw=0.4, ls=(0, (1, 1.5)))
    off = np.array([(fm.C03 - C) @ e1, (fm.C03 - C) @ e2]); n2 = np.array([fm.n3 @ e1, fm.n3 @ e2])
    ax.plot(off[0] + np.array([-32, 32]) * n2[0], off[1] + np.array([-32, 32]) * n2[1], color=R2.COLLAR_C, lw=0.6, ls=(0, (3, 2)))
    ax.set_xlim(*R2.EXT[0]); ax.set_ylim(*COR_V); ax.set_aspect("equal"); CR._off(ax)


def _nanbox(g, k=5, min_cover=0.2):
    from scipy.ndimage import uniform_filter
    v = np.nan_to_num(g, nan=0.0); w = np.isfinite(g).astype(float)
    sv, sw = uniform_filter(v, k, mode="constant"), uniform_filter(w, k, mode="constant")
    out = np.full_like(g, np.nan); ok = (sw > min_cover) & np.isfinite(g)
    out[ok] = sv[ok] / sw[ok]
    return out


def smooth_by_tissue(g, is_canc, k=5):
    out = np.full_like(g, np.nan)
    for m in (is_canc, ~is_canc):
        sm = _nanbox(np.where(m, g, np.nan), k)
        out[m] = sm[m]
    return out


def maps_of(job: str) -> dict:
    d = J.QROOT / job
    spec = json.loads((d / "spec.json").read_text()); t = J.result(job)["templating"]
    stem = G.Stem3D(**spec["design"]); fm = SH._CTX["fm"].with_cut(float(spec.get("h_cut", 25.0)))
    pose = fm.pose(t["alpha"], t["e"])
    kept = lambda P: fm.below_cut(P) & ~G.inside_stem(stem, t["A0"], SH.local(P, pose))
    f = SH.load_fields(d)
    U, V, vm_d, P = SH.plane_grid(f, fm, "vm", kept)
    _, _, sed_d, _ = SH.plane_grid(f, fm, "sed", kept)
    _, _, sed_k, _ = SH.plane_grid(SH._CTX["intact"], fm, "sed", kept)
    is_canc = (fm.canal_sdf(P) <= 0).reshape(U.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        chg = 100.0 * (smooth_by_tissue(sed_d, is_canc) / smooth_by_tissue(sed_k, is_canc) - 1.0)
    in_bone = fm.outer_sdf(P) <= 0
    in_stem = (G.inside_stem(stem, t["A0"], SH.local(P, pose)) & fm.below_cut(P) & in_bone).reshape(U.shape)
    z7 = ((P[:, 0] >= 0) & (P[:, 2] >= -10.0) & fm.below_cut(P) & in_bone).reshape(U.shape)
    s_ = (P - fm.C03) @ fm.u3                      # v10: evaluation band = cortex 0-10 mm below the cut, inferomedial half
    band = ((s_ <= 0) & (s_ >= -BAND) & ((P - fm.C03) @ fm.n3 >= 0) & in_bone & (fm.canal_sdf(P) > 0)).reshape(U.shape) & ~in_stem
    return dict(U=U, V=V, vm=vm_d, chg=chg, in_stem=in_stem, in_bone=in_bone.reshape(U.shape), z7=z7, band=band)


def draw_map(ax, m: dict, key: str, outline=True):
    if key == "vm":
        im = ax.pcolormesh(m["U"], m["V"], m["vm"], norm=S_NORM, cmap="viridis", shading="nearest", rasterized=True)
    else:
        im = ax.pcolormesh(m["U"], m["V"], np.clip(m["chg"], -100, 100), vmin=-100, vmax=100, cmap="RdBu_r", shading="nearest", rasterized=True)
    if m.get("in_stem") is not None:
        ax.contourf(m["U"], m["V"], np.where(m["in_stem"], 1.0, np.nan), levels=[0.5, 1.5], colors=[ps.LIGHT])
    if outline:
        ax.contour(m["U"], m["V"], m["in_bone"].astype(float), levels=[0.5], colors=["#888888"], linewidths=0.3)
    if key != "vm" and m.get("z7") is not None:
        ax.contour(m["U"], m["V"], m["z7"].astype(float), levels=[0.5], colors=["black"], linewidths=0.6, linestyles="dashed")
    if key != "vm" and m.get("band") is not None and m["band"].any():
        ax.contour(m["U"], m["V"], m["band"].astype(float), levels=[0.5], colors=["black"], linewidths=0.7)
    ax.set_xlim(*MAP_U); ax.set_ylim(*MAP_V); ax.set_aspect("equal"); CR._off(ax)
    return im


def _v(fe, k):
    x = fe.get(k)
    return x if x is not None and np.isfinite(x) else None


BAND = 10.0
_ZD = {}


def band_res(job: str) -> float:
    if not _ZD:
        _ZD.update({r["job"]: r for r in json.loads((OUT / "zone_depth.json").read_text())})
        if (OUT / "zone_stage.json").exists():
            _ZD.update({r["job"]: r for r in json.loads((OUT / "zone_stage.json").read_text())})
    b = _ZD[job][f"band{BAND:g}_n3"]
    return b["res"] if "res" in b else b["res_0.6"]


def key_line(fe: dict, g: dict) -> str:
    mm = _v(fe, "f1_all_p95_um") or fe["f1_p95_um"]
    return (f"{g['removal'] / 1000:.1f} cm³  ·  cut {band_res(fe['job']):.0f} %\n{mm:.1f} µm  ·  zone 7 {fe['G7_sed_fixed']:+.0f} %").replace("-", "−")


def main(variant: str):
    V = VARIANTS[variant]
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    SH._init()
    fm25 = SH._CTX["fm"].with_cut(25.0)
    U, Vg, vm_i, P = SH.plane_grid(SH._CTX["intact"], fm25, "vm", lambda P: np.ones(len(P), bool))
    intact = dict(U=U, V=Vg, vm=vm_i, in_bone=(fm25.outer_sdf(P) <= 0).reshape(U.shape))
    cols = []
    for tag, job, label in V["pick"]:
        fe = PF.fe_full(job); g, spec = PF.geo_of(job); m = maps_of(job)
        cols.append((tag, job, label, fe, g, m))
        print(tag, job, fe["state"], f"{fe['f1_p95_um']:.1f} um", f"G7 {fe['G7_sed_fixed']:+.0f} %", f"{time.time() - t0:.0f} s", flush=True)

    left, right, cw = 14.0, 10.0, 44.0
    ncols = 1 + len(cols)
    W = left + right + ncols * cw
    pw = cw - 2.5
    h_cor = pw * (COR_V[1] - COR_V[0]) / (R2.EXT[0][1] - R2.EXT[0][0])
    h_map = pw * (MAP_V[1] - MAP_V[0]) / (MAP_U[1] - MAP_U[0])
    h_3d = 38.0
    gap = 4.5
    top = 15.0
    rows = [("placement", h_cor), ("bone stress\n(MPa)", h_map), ("load transfer:\nstrain energy vs intact (%)", h_map), ("micromotion\n(µm)", h_3d)]
    H = top + sum(h for _, h in rows) + gap * len(rows) + 16.0
    fig = plt.figure(figsize=(W * ps.MM, H * ps.MM))
    X = lambda mm: mm / W
    Y = lambda mm_from_top: 1.0 - mm_from_top / H
    fig.text(X(6), Y(3.0), V["title"], fontsize=TITLE_FS, fontweight="bold", va="top")
    for c, h in enumerate(V["heads"](cols)):
        fig.text(X(left + c * cw), Y(top - 1.5), h, fontsize=HEAD_FS, fontweight="bold", va="bottom", ha="left")
    y = top
    centre = R3.view_centre()
    ims = {}
    for r, (lab, h) in enumerate(rows):
        fig.text(X(left - 3.5), Y(y + h / 2), lab, rotation=90, fontsize=ROW_FS, fontweight="bold", va="center", ha="right", multialignment="center")
        for c in range(ncols):
            x0 = left + c * cw
            if r == 3:
                if c == 0:
                    cax = fig.add_axes([X(x0 + 2.0), Y(y + 10.0), X(pw - 6.0), 2.0 / H])
                    cb = plt.colorbar(plt.cm.ScalarMappable(norm=R3.NORM, cmap=R3.CMAP), cax=cax, orientation="horizontal")
                    cb.set_ticks([1, 10, 40, 150]); cb.set_ticklabels(["≤1", "10", "40", "≥150 µm"]); cb.ax.tick_params(labelsize=6, length=1.5, pad=1)
                    cb.outline.set_linewidth(0.3)
                    fig.text(X(x0 + 2.0), Y(y + 14.5), "40 µm: literature reference", fontsize=LAB_FS, va="top", ha="left", color="#444444")
                    continue
                ax = fig.add_axes([X(x0 + 1.0), Y(y + h), X(h), h / H], projection="3d")
                _, _, _, fe, g, _ = cols[c - 1]
                R3.draw_3d(ax, g, fe, centre, half=38.0)
                continue
            ax = fig.add_axes([X(x0 + 1.0), Y(y + h), X(pw), h / H])
            if r == 0:
                if c == 0:
                    intact_coronal(ax)
                else:
                    R2.draw_coronal(ax, cols[c - 1][4]); ax.set_ylim(*COR_V)
            elif r == 1:
                ims["vm"] = draw_map(ax, intact if c == 0 else cols[c - 1][5], "vm", outline=c > 0)
            else:
                if c == 0:
                    ax.set_axis_off()
                    fig.text(X(x0 + 1.0), Y(y + h / 2), "reference\n(0 % everywhere)", fontsize=LAB_FS, va="center", ha="left", color="#444444")
                else:
                    ims["chg"] = draw_map(ax, cols[c - 1][5], "chg")
        if r in (1, 2):
            cax = fig.add_axes([X(W - right + 1.5), Y(y + 0.9 * h), 2.0 / W, 0.8 * h / H])
            cb = plt.colorbar(ims["vm" if r == 1 else "chg"], cax=cax, orientation="vertical")
            cb.ax.tick_params(labelsize=6, length=1.5, pad=1); cb.outline.set_linewidth(0.3)
            if r == 1:
                cb.set_ticks([0.3, 1, 3, 10, 30, 60]); cb.set_ticklabels(["0.3", "1", "3", "10", "30", "60"])
            else:
                cb.set_ticks([-100, -50, 0, 50, 100]); cb.set_ticklabels(["−100", "−50", "0", "+50", "+100"])
        y += h + gap
    for c in range(1, ncols):
        fig.text(X(left + c * cw), Y(y), key_line(cols[c - 1][3], cols[c - 1][4]), fontsize=LAB_FS - 0.2, va="top", ha="left", fontweight="bold", linespacing=1.35)
    fig.text(X(left + cw), Y(y + 7.0), "upper line: bone removed · cut = low-strain-energy fraction in the 10 mm band below the cut" + "\n" + "lower line: micromotion P95 · zone 7 = strain energy vs intact, fixed zone", fontsize=LAB_FS - 0.3, va="top", ha="left", color="#444444", linespacing=1.35)
    with plt.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(OUT / f"{V['out']}.png", dpi=250)
    plt.close(fig)
    print("written", OUT / f"{V['out']}.png", f"{time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "best3")
