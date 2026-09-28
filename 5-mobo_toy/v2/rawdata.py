"""V2A 原始数据导出（在 Linux 上跑，不做统计）：

    results/raw/all_designs.csv          每个设计作业一行：变量、模板化尺寸、网格、QoI、求解时间、失败级别（含失败与非生产网格）
    results/raw/gallery_silhouettes_*.png 全部已解设计在颈平面上的轮廓（按长度排序）
    results/raw/gallery_sections.png     全部已解设计的肩部截面（真实尺寸）
    results/raw/design_points_pairs.png  11 个设计变量的两两散点（评估过的点，按来源着色，失败为叉）
    results/raw/stl/<job>.stl            每个已解设计的柄体（模型坐标，二进制 STL）；stl.zip
    results/raw/fields/<job>.png         选定设计的场：柄 von Mises、骨 SED、接触压力、滑移增量、接触状态
    results/raw/fields_csv.zip           选定设计的 Abaqus 导出 CSV + 网格 + 作业说明
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import shutil
import struct
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import plotstyle as ps  # noqa: E402
import cases_real as CR  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import qoi  # noqa: E402
from spot3d.qoi3d import FACES, FACE_MID  # noqa: E402

plt = ps.plt
RAW = J.RESULTS / "raw"
SRC_COL = {"reference": ps.GREY, "bo": ps.DORR["A"], "probe": "#D55E00", "warm": "#E69F00", "base": "black", "other": ps.LIGHT}
QOI_KEYS = ("f1_p95_um", "f1_mean_um", "frac_open", "frac_stick", "n_slave_nodes", "interface_area", "vm_p99", "vm_max",
            "sed_gruen7", "sed_gruen1", "f2_g7_loss_pct", "f2_g1_loss_pct", "intact_job")


def _source(job_id: str) -> str:
    for k, v in (("ref_", "reference"), ("conv_r", "reference"), ("bo_", "bo"), ("probe_", "probe"), ("warm_", "warm"),
                 ("e2e_", "base"), ("signs_", "base"), ("conv_base", "base")):
        if job_id.startswith(k):
            return v
    return "other"


# ================================================================== 1 设计表
def all_jobs() -> list[dict]:
    rows = []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design":
            continue
        r = J.result(d.name) or {}
        prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
        tmpl = r.get("templating") or prep.get("templating") or {}
        row = {"job_id": d.name, "source": _source(d.name), "stage": spec.get("stage"), "tag": spec.get("tag"),
               "state": J.state(d), "h_int_mm": spec.get("h_int"),
               "variant_delta": spec.get("delta", ""), "variant_mu": spec.get("mu", ""), "variant_torque": spec.get("torque", True),
               "variant_E_canc": spec.get("E_canc", "")}
        dsg = G.design_of_spec(spec)
        row.update({f"x_{k}": dsg[k] for k in G.VARS})
        row.update({"A0_mm2": tmpl.get("A0", ""), "entry_offset_mm": tmpl.get("e", ""), "contact_frac": tmpl.get("contact", ""),
                    "tightest_s_mm": tmpl.get("s_bind", ""), "stem_volume_mm3": tmpl.get("volume", "")})
        nt = r.get("n_tet") or prep.get("n_tet") or {}
        row.update({"n_tet_cortex": nt.get("cortex", ""), "n_tet_cancellous": nt.get("cancellous", ""), "n_tet_stem": nt.get("stem", "")})
        row.update({k: r.get(k, "") for k in QOI_KEYS})
        sv = r.get("solve", {})
        row.update({"wall_fric_s": sv.get("m_fric", {}).get("wall_s", ""), "wall_bond_s": sv.get("m_bond", {}).get("wall_s", "")})
        f = r.get("failed") or {}
        row.update({"fail_level": f.get("level", ""), "fail_stage": f.get("stage", ""), "fail_reason": (f.get("reason") or "")[:200]})
        rows.append(row)
    return rows


def export_csv(rows) -> pathlib.Path:
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / "all_designs.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return p


def solved_production(rows) -> list[dict]:
    """已解、生产网格、标准变体、去重（同设计取最早）。"""
    seen, out = set(), []
    for r in rows:
        if r["state"] != "DONE" or r["h_int_mm"] != 2.0 or r["variant_delta"] != "" or r["variant_mu"] != "" or r["variant_torque"] is False:
            continue
        key = tuple(round(r[f"x_{k}"], 6) for k in G.VARS)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _design(r) -> dict:
    return {k: float(r[f"x_{k}"]) for k in G.VARS}


# ================================================================== 2 图册
def gallery_silhouettes(fm, rows, per_page=80, ncol=10):
    img = CR.neck_plane_image(fm, ext=((-60.0, 50.0), (-125.0, 45.0)), h=0.4)
    rows = sorted(rows, key=lambda r: r["x_L"])
    paths = []
    for pg in range(0, len(rows), per_page):
        chunk = rows[pg:pg + per_page]
        nrow = math.ceil(len(chunk) / ncol)
        fig, axes = ps.new_figure("double", 26 * nrow, nrow, ncol)
        axes = np.atleast_2d(axes).reshape(nrow, ncol)
        for ax in axes.flat:
            ax.axis("off")
        for ax, r in zip(axes.flat, chunk):
            st = G.Stem3D(**_design(r)); pl = G.template(st, fm)
            CR.draw_neck_plane(ax, fm, img, st, pl, SRC_COL[r["source"]], arrow=False)
            ax.set_xlim(-60, 50); ax.set_ylim(-125, 45)
            ax.set_title(f"L{r['x_L']:.0f} α{r['x_alpha']:.0f} A0 {float(r['A0_mm2']):.0f}\n{float(r['f1_p95_um']):.1f}µm  "
                         f"{abs(float(r['f2_g7_loss_pct'])):.0f}%", fontsize=4.6)
        fig.suptitle(f"All solved designs in the neck plane, sorted by length (page {pg // per_page + 1}); title: L, α, shoulder area | "
                     "micromotion P95, Gruen 7 |ΔSED|; colour = source (grey reference, blue BO, orange probe, yellow warm BO, black base)",
                     fontsize=6)
        p = RAW / f"gallery_silhouettes_{pg // per_page + 1}.png"
        fig.savefig(p, dpi=200); plt.close(fig); paths.append(p)
    return paths


def gallery_sections(fm, rows, ncol=16):
    rows = sorted(rows, key=lambda r: r["x_L"])
    nrow = math.ceil(len(rows) / ncol)
    fig, axes = ps.new_figure("double", 13 * nrow, nrow, ncol)
    axes = np.atleast_2d(axes).reshape(nrow, ncol)
    for ax in axes.flat:
        ax.axis("off")
    for ax, r in zip(axes.flat, rows):
        d = _design(r)
        sec = G.unit_section(d, 120) * math.sqrt(float(r["A0_mm2"]))
        ax.fill(sec[:, 0], sec[:, 1], fc=SRC_COL[r["source"]], ec="black", lw=0.3, alpha=0.8)
        ax.set_xlim(-16, 16); ax.set_ylim(-14, 14); ax.set_aspect("equal")
        ax.set_title(f"L{r['x_L']:.0f} {float(r['A0_mm2']):.0f}mm²", fontsize=4.2)
    fig.suptitle("Shoulder cross-sections of all solved designs at templated size (true scale, ±16 mm; medial → right, anterior ↑), sorted by length",
                 fontsize=6)
    p = RAW / "gallery_sections.png"
    fig.savefig(p, dpi=200); plt.close(fig)
    return p


def pairs_plot(rows_all):
    ev = [r for r in rows_all if r["h_int_mm"] == 2.0 and r["variant_delta"] == "" and r["variant_mu"] == "" and r["variant_torque"] is not False]
    n = len(G.VARS)
    fig, axes = ps.new_figure("double", 190, n, n)
    for i in range(n):
        for j in range(n):
            ax = axes[i, j]
            if j > i:
                ax.axis("off"); continue
            xi, xj = G.VARS[i], G.VARS[j]
            if i == j:
                for s, col in SRC_COL.items():
                    v = [r[f"x_{xi}"] for r in ev if r["source"] == s and r["state"] == "DONE"]
                    if v:
                        ax.hist(v, bins=15, range=G.DESIGN[xi], histtype="step", color=col, lw=0.6)
                ax.set_xlim(*G.DESIGN[xi])
            else:
                for s, col in SRC_COL.items():
                    ok = [(r[f"x_{xj}"], r[f"x_{xi}"]) for r in ev if r["source"] == s and r["state"] == "DONE"]
                    bad = [(r[f"x_{xj}"], r[f"x_{xi}"]) for r in ev if r["source"] == s and r["state"] == "FAILED"]
                    if ok:
                        ax.scatter(*zip(*ok), s=1.5, color=col, lw=0)
                    if bad:
                        ax.scatter(*zip(*bad), s=5, marker="x", color=col, lw=0.4)
                ax.set_xlim(*G.DESIGN[xj]); ax.set_ylim(*G.DESIGN[xi])
            ax.tick_params(labelsize=3.5, length=1.5, pad=1)
            if i == n - 1:
                ax.set_xlabel(xj, fontsize=5)
            else:
                ax.set_xticklabels([])
            if j == 0 and i > 0:
                ax.set_ylabel(xi, fontsize=5)
            else:
                ax.set_yticklabels([])
    fig.suptitle("Evaluated design points, pairwise (grey reference, blue BO, orange probe, yellow warm BO, black base; × = build/solve failed)",
                 fontsize=6.5)
    p = RAW / "design_points_pairs.png"
    fig.savefig(p, dpi=220); plt.close(fig)
    return p


# ================================================================== 3 STL
def stem_stl(fm, r, path: pathlib.Path):
    import cases as CS
    d = _design(r); st = G.Stem3D(**d); pl = G.template(st, fm)
    X, Y, Z = CS.stem_grid(st, pl["A0"])                         # 局部：X 内侧、Y 前方、Z = −s
    P0, dd, e_ml, e_ap = pl["pose"]
    W = P0 + (-Z)[..., None] * dd + X[..., None] * e_ml + Y[..., None] * e_ap      # (nrow, ncol, 3)
    tris = []
    nr, nc = X.shape
    for i in range(nr - 1):
        for j in range(nc - 1):
            a, b, c, d_ = W[i, j], W[i, j + 1], W[i + 1, j + 1], W[i + 1, j]
            tris += [(a, b, c), (a, c, d_)]
    cen = W[0].mean(0)                                            # 肩部封口
    for j in range(nc - 1):
        tris.append((cen, W[0, j + 1], W[0, j]))
    T = np.array(tris)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    area = np.linalg.norm(n, axis=1)
    keep = area > 1e-9
    T, n = T[keep], n[keep] / area[keep][:, None]
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec["n"] = n; rec["v"] = T
    with open(path, "wb") as fh:
        fh.write(b"V2A stem in femur model coordinates (mm): +x medial, +y posterior, +z proximal".ljust(80, b" "))
        fh.write(struct.pack("<I", len(rec)))
        fh.write(rec.tobytes())
    return len(rec)


# ================================================================== 4 场图
def _mesh(d):
    m = dict(np.load(d / "mesh3d.npz"))
    lab, X = m["node_labels"], m["nodes"]
    lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
    return m, X, lut


def _fld(c, name):
    k = c["field"] == name
    return dict(zip(c["node"][k].astype(int), c["value"][k]))


def fields_figure(fm, r, path: pathlib.Path):
    d = J.QROOT / r["job_id"]
    m, X, lut = _mesh(d)
    info = json.loads((d / "model3d.json").read_text())
    # 界面节点（从面）
    conn = {}
    for reg in ("cortex", "cancellous"):
        for el, row in zip(m[f"{reg}_elab"], m[f"{reg}_conn"]):
            conn[int(el)] = row
    inodes = set()
    for el, fc in info["slave"]:
        row = conn[el]
        inodes.update(int(row[k]) for k in FACES[fc]); inodes.update(int(row[k]) for k in FACE_MID[fc])
    inodes = np.array(sorted(inodes))
    Pi = X[lut[inodes]]
    c1 = qoi._csv(d / "m_fric_csv" / "RELEASE_CONTACT.csv"); c2 = qoi._csv(d / "m_fric_csv" / "LOAD_CONTACT.csv")
    a1, a2, b1, b2 = _fld(c1, "CSLIP1"), _fld(c1, "CSLIP2"), _fld(c2, "CSLIP1"), _fld(c2, "CSLIP2")
    pres, stat = _fld(c2, "CPRESS"), _fld(c2, "CSTATUS")
    slip = np.array([np.hypot(b1.get(n, 0) - a1.get(n, 0), b2.get(n, 0) - a2.get(n, 0)) for n in inodes]) * 1000.0
    cp = np.array([pres.get(n, np.nan) for n in inodes]); cs = np.array([stat.get(n, np.nan) for n in inodes])
    # 柄应力（粘接模型）与骨 SED
    s = qoi._csv(d / "m_bond_csv" / "LOAD_S.csv"); en = qoi._csv(d / "m_bond_csv" / "LOAD_ENER.csv")
    mis = dict(zip(s["elem"].astype(int), s["mises"]))
    e_by = dict(zip(en["elem"].astype(int), en["else"])); v_by = dict(zip(en["elem"].astype(int), en["evol"]))
    cen_st = X[lut[m["stem_conn"][:, :4]]].mean(1); vm = np.array([mis.get(int(e), np.nan) for e in m["stem_elab"]])
    keep = fm.below_cut(cen_st) | (((cen_st - fm.C03) @ fm.u3) < 12)         # 柄体 + 颈根，不画头球
    bone_c, bone_sed = [], []
    for reg in ("cortex", "cancellous"):
        c = X[lut[m[f"{reg}_conn"][:, :4]]].mean(1)
        sed = np.array([e_by.get(int(e), 0.0) / max(v_by.get(int(e), 1e-9), 1e-9) for e in m[f"{reg}_elab"]])
        bone_c.append(c); bone_sed.append(sed)
    bone_c = np.vstack(bone_c); bone_sed = np.concatenate(bone_sed)
    slab = np.abs(bone_c[:, 1]) < 3.0

    fig, axes = ps.new_figure("double", 125, 2, 3)
    def view(ax, P, v, lab, cmap="viridis", log=False, vmin=None, vmax=None, s=3):
        o = np.argsort(-P[:, 1])                                  # 后方先画，前方在上（从前面看）
        from matplotlib.colors import LogNorm
        norm = LogNorm(vmin=max(vmin or np.nanmin(v[v > 0]), 1e-12), vmax=vmax or np.nanmax(v)) if log else None
        sc = ax.scatter(P[o, 0], P[o, 2], c=v[o], s=s, lw=0, cmap=cmap, norm=norm, vmin=None if log else vmin, vmax=None if log else vmax)
        fig.colorbar(sc, ax=ax, shrink=0.8, pad=0.02).set_label(lab, fontsize=6)
        ax.set_aspect("equal"); ax.set_xlabel("x medial → (mm)", fontsize=6); ax.set_ylabel("z (mm)", fontsize=6)
        ax.tick_params(labelsize=5)
    view(axes[0, 0], cen_st[keep], vm[keep], "stem von Mises, bonded model (MPa)", cmap="inferno")
    axes[0, 0].set_title("stem stress (element centroids, anterior view)", fontsize=6.5)
    o = np.argsort(-cen_st[keep][:, 0])
    sc = axes[0, 1].scatter(cen_st[keep][o, 1], cen_st[keep][o, 2], c=vm[keep][o], s=3, lw=0, cmap="inferno")
    fig.colorbar(sc, ax=axes[0, 1], shrink=0.8, pad=0.02).set_label("stem von Mises (MPa)", fontsize=6)
    axes[0, 1].set_aspect("equal"); axes[0, 1].set_xlabel("y posterior → (mm)", fontsize=6); axes[0, 1].tick_params(labelsize=5)
    axes[0, 1].set_title("stem stress (medial view)", fontsize=6.5)
    view(axes[0, 2], bone_c[slab], bone_sed[slab], "bone SED, bonded model (mJ/mm³)", cmap="magma", log=True, s=2)
    axes[0, 2].set_title("bone strain-energy density, coronal slab |y| < 3 mm", fontsize=6.5)
    view(axes[1, 0], Pi, np.nan_to_num(cp), "contact pressure, LOAD (MPa)", cmap="viridis")
    axes[1, 0].set_title("interface contact pressure", fontsize=6.5)
    view(axes[1, 1], Pi, slip, "slip increment LOAD − RELEASE (µm)", cmap="plasma", vmin=0, vmax=max(np.nanpercentile(slip, 99), 1e-3))
    axes[1, 1].set_title("interface micromotion", fontsize=6.5)
    view(axes[1, 2], Pi, np.nan_to_num(cs), "CSTATUS (0 open, 1 slip, 2 stick)", cmap="coolwarm", vmin=0, vmax=2)
    axes[1, 2].set_title("contact status at LOAD", fontsize=6.5)
    fig.suptitle(f"{r['job_id']}  L {r['x_L']:.1f} mm, α {r['x_alpha']:.1f}°, A0 {float(r['A0_mm2']):.0f} mm² | "
                 f"f1 P95 {float(r['f1_p95_um']):.2f} µm, Gruen 7 ΔSED {float(r['f2_g7_loss_pct']):+.1f}%, stem vM P99 {float(r['vm_p99']):.0f} MPa",
                 fontsize=6.5)
    fig.savefig(path, dpi=180); plt.close(fig)


def select_for_fields(rows) -> list[dict]:
    import mobo
    Y = np.array([[math.log10(float(r["f1_p95_um"])), abs(float(r["f2_g7_loss_pct"]))] for r in rows])
    pm = mobo.pareto_mask(Y)
    pick = [r for r, p in zip(rows, pm) if p]
    extra = [rows[int(np.argmin(Y[:, 0]))], rows[int(np.argmax(Y[:, 0]))], rows[int(np.argmax(Y[:, 1]))]]
    extra += [r for r in rows if r["source"] == "base"][:1]
    for r in extra:
        if r not in pick:
            pick.append(r)
    return pick[:12]


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    fm = FR.build()
    rows_all = all_jobs()
    export_csv(rows_all)
    rows = solved_production(rows_all)
    print(f"designs: {len(rows_all)} jobs, {len(rows)} solved unique at production mesh", flush=True)
    gallery_silhouettes(fm, rows)
    gallery_sections(fm, rows)
    pairs_plot(rows_all)
    (RAW / "stl").mkdir(exist_ok=True)
    for r in rows:
        stem_stl(fm, r, RAW / "stl" / f"{r['job_id']}.stl")
    shutil.make_archive(str(RAW / "stl"), "zip", RAW / "stl")
    sel = select_for_fields(rows)
    (RAW / "fields").mkdir(exist_ok=True)
    tmp = RAW / "_fields_csv"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir()
    for r in sel:
        try:
            fields_figure(fm, r, RAW / "fields" / f"{r['job_id']}.png")
        except Exception as e:                                          # noqa: BLE001
            print(f"fields {r['job_id']}: {type(e).__name__}: {e}", flush=True)
        src = J.QROOT / r["job_id"]; dst = tmp / r["job_id"]; dst.mkdir()
        for f in ("mesh3d.npz", "model3d.json", "prep.json", "spec.json", "result.json"):
            if (src / f).exists():
                shutil.copy(src / f, dst / f)
        for sub in ("m_fric_csv", "m_bond_csv"):
            if (src / sub).exists():
                shutil.copytree(src / sub, dst / sub)
    shutil.make_archive(str(RAW / "fields_csv"), "zip", tmp)
    shutil.rmtree(tmp)
    (RAW / "README.txt").write_text(
        "V2A raw data export (no statistics).\n"
        "all_designs.csv: one row per design job (all mesh sizes, variants and failures); x_* are the 11 design variables (physical units),\n"
        "  A0_mm2 templated shoulder area, entry_offset_mm, tightest_s_mm; f1_p95_um micromotion P95; f2_g7_loss_pct = 100*(1 - SED_implanted/SED_intact) in Gruen 7\n"
        "  (negative = more strain energy than intact); vm_p99 stem von Mises P99 (bonded model, below cut).\n"
        "stl/: stem solids in femur model coordinates (mm; +x medial, +y posterior, +z proximal; origin on the shaft axis at lesser-trochanter height).\n"
        "fields/: per-design field plots; fields_csv.zip: the Abaqus exports behind them (RELEASE_/LOAD_CONTACT.csv node fields; LOAD_ENER.csv ELSE/EVOL;\n"
        "  LOAD_S.csv element mises/s11/s22/s12; mesh3d.npz nodes+C3D10 connectivity; model3d.json slave faces [element, face]).\n"
        f"selected designs for fields: {[r['job_id'] for r in sel]}\n", encoding="utf-8")
    print("raw export done:", [p.name for p in sorted(RAW.iterdir())], flush=True)


if __name__ == "__main__":
    main()
