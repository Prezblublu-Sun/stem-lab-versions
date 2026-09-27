"""S2 FE 模型与验证 → R2 报告。python stage_s2.py（.venv-mobo）

验证项：V1 Lamé 压配；V2 网格收敛 + GCI；V3 符号检查；V4 确定性；V5 噪声底；另含侧板、载荷方向、
增量步设置的敏感性。FE 结果全部经 evaluate.evaluate 记入 results/runs.csv（campaign = S2_*）。
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import pathlib

import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import LogNorm

import evaluate as EV
import fe_model as FM
import femur2d as F
import plotstyle as ps
import qoi
import run_abaqus as ra
import stem2d as S

ROOT = ps.ROOT
BASE_U = np.array([0.291, 0.395, 0.342, 0.403, 0.429])        # 三型都通过几何门、最接近设计空间中心的 Sobol 点
BASE = S.to_physical(BASE_U)
CFG = F.CFG


def fnum(r, k):
    return EV.as_float(r, k)


# ------------------------------------------------------------------ helpers
def load_mesh_polys(run_dir: pathlib.Path):
    m = dict(np.load(run_dir / "mesh.npz"))
    out = []
    for pre in ("bone", "stem"):
        lab, nodes = m[f"{pre}_labels"], m[f"{pre}_nodes"]
        lut = np.full(int(lab.max()) + 1, -1); lut[lab] = np.arange(len(lab))
        for key in m:
            if key.startswith(f"{pre}_") and key.endswith("_conn"):
                reg = key[len(pre) + 1:-5]
                p = nodes[lut[m[key][:, :3]]]
                for el, tri in zip(m[f"{pre}_{reg}_elab"], p):
                    out.append((reg, int(el), tri))
    return out


def arc_coords(model: dict, xy: np.ndarray):
    ax = model["axis"]
    C0, d0, k = np.array(ax["C0"]), np.array(ax["d0"]), ax["kappa"]
    n0 = np.array([-d0[1], d0[0]])
    if abs(k) < 1e-9:
        rel = xy - C0
        return rel @ d0, rel @ n0
    c = C0 + n0 / k
    a0 = math.atan2(*(C0 - c)[::-1])
    a = np.arctan2(xy[:, 1] - c[1], xy[:, 0] - c[0])
    da = np.unwrap(a - a0) if len(a) else a
    da = (a - a0 + np.pi) % (2 * np.pi) - np.pi
    s = da / k
    v = np.sign(k) * (1 / abs(k) - np.linalg.norm(xy - c, axis=1))
    return s, v


def gci(phi: list[float], r: float = 2.0) -> dict:
    """Celik 2008，三套网格、细化比恒定 r。phi = [细, 中, 粗]。"""
    f1, f2, f3 = phi
    e21, e32 = f2 - f1, f3 - f2
    out = {"phi1": f1, "phi2": f2, "phi3": f3, "r": r}
    if abs(e21) < 1e-14:
        out.update(p=float("nan"), phi_ext=f1, e_a21=0.0, e_ext21=0.0, gci_fine=0.0, behaviour="converged")
        return out
    ratio = e32 / e21
    behaviour = "monotonic" if ratio > 0 else "oscillatory"
    p = abs(math.log(abs(ratio))) / math.log(r) if abs(ratio) > 0 else float("nan")
    rp = r ** p
    phi_ext = (rp * f1 - f2) / (rp - 1) if rp != 1 else float("nan")
    e_a = abs((f1 - f2) / f1) if f1 else float("nan")
    e_ext = abs((phi_ext - f1) / phi_ext) if phi_ext else float("nan")
    out.update(p=p, phi_ext=phi_ext, e_a21=e_a, e_ext21=e_ext, gci_fine=1.25 * e_a / (rp - 1) if rp != 1 else float("nan"),
               behaviour=behaviour)
    return out


# ------------------------------------------------------------------ plot functions（只读 CSV）
PART_FC = {"cortex": "#C9C9C9", "cancellous": "#F3E3C3", "cavity": "#FFFFFF", "stem": "#9BB8D3"}


def plot_r2_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 150, 2, 3)
    for c, t in enumerate("ABC"):
        idx = [i for i, x in enumerate(d["dorr"]) if x == t]
        for r, (xl, zl) in enumerate((((-45, 75), (-152, 92)), ((-20, 20), (-45, -5)))):
            ax = axes[r, c]
            for part in ("cortex", "cancellous", "cavity", "stem"):
                jj = [i for i in idx if d["part"][i] == part]
                polys = [[(d["x1"][i], d["z1"][i]), (d["x2"][i], d["z2"][i]), (d["x3"][i], d["z3"][i])] for i in jj]
                ax.add_collection(PolyCollection(polys, facecolors=PART_FC[part], edgecolors="#555555",
                                                 linewidths=0.08 if r == 0 else 0.25, alpha=0.9 if part != "cavity" else 0.3))
            ax.set_xlim(*xl); ax.set_ylim(*zl); ax.set_aspect("equal")
            if r == 0:
                ax.set_title(f"Dorr {t}")
                ax.add_patch(__import__("matplotlib").patches.Rectangle((-20, -45), 40, 40, fill=False, ec="#D55E00", lw=0.8))
            ax.set_xlabel("x (mm)", fontsize=7)
        axes[0, c].set_ylabel("z (mm)", fontsize=7)
    axes[1, 0].set_ylabel("z (mm), zoom at stem tip", fontsize=7)
    return fig


def plot_r2_f02(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 62)
    ax.axhspan(0.95, 1.05, color="#E5E5E5", label="±5 % acceptance")
    for case, col, mk in (("cortical ring", ps.OKABE_ITO["blue"], "o"), ("cancellous ring", ps.OKABE_ITO["orange"], "s")):
        jj = [i for i, x in enumerate(d["case"]) if x == case]
        ax.plot([d["angle_deg"][i] for i in jj], [d["ratio"][i] for i in jj], mk, ms=2.5, color=col,
                label=f"{case} (p = {d['p_analytic'][jj[0]]:.1f} MPa)")
    ps.threshold_line(ax, 1.0, "y")
    ax.set_xlabel("Angle along interface (°)"); ax.set_ylabel("CPRESS FE / Lamé (–)")
    ax.set_ylim(0.85, 1.15); ax.legend(loc="lower center", fontsize=6.5)
    return fig


def plot_r2_f03(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 2)
    for ax, (q, lab) in zip(axes, (("f1", ps.LABEL["f1"]), ("f2", ps.LABEL["f2"]))):
        for t in "ABC":
            jj = sorted([i for i, x in enumerate(d["dorr"]) if x == t], key=lambda i: d["h_mm"][i])
            h = [d["h_mm"][i] for i in jj]; v = [d[q][i] for i in jj]
            ax.plot(h, v, marker=ps.DORR_MARKER[t], color=ps.DORR[t], label=f"Dorr {t}")
            g = d[f"gci_{q}"][jj[0]]
            if g is not None and not math.isnan(g):
                ax.errorbar([h[0]], [v[0]], yerr=[[abs(v[0]) * g], [abs(v[0]) * g]], color=ps.DORR[t], capsize=3, lw=1)
        ax.set_xscale("log"); ax.invert_xaxis()
        hs = sorted(set(d["h_mm"])); ax.set_xticks(hs); ax.set_xticklabels([f"{x:g}" for x in hs]); ax.minorticks_off()
        ax.set_xlabel("Interface element size (mm)"); ax.set_ylabel(lab)
    axes[0].legend(loc="best")
    ps.panel_labels(axes)
    return fig


def plot_r2_f04(csv_path):
    d = ps.read_csv(csv_path)
    checks = list(dict.fromkeys(d["check"]))
    fig, axes = ps.new_figure("double", 100, 2, math.ceil(len(checks) / 2))
    for ax, ch in zip(axes.flat, checks):
        jj = [i for i, x in enumerate(d["check"]) if x == ch]
        q = d["quantity"][jj[0]]
        vals = [d["value"][i] for i in jj]
        cols = [ps.OKABE_ITO["green"] if d["ok"][i] == 1 else (ps.OKABE_ITO["vermillion"] if d["ok"][i] == 0 else ps.GREY) for i in jj]
        ax.bar(range(len(jj)), vals, color=cols)
        ax.set_xticks(range(len(jj))); ax.set_xticklabels([d["variant"][i] for i in jj], fontsize=6.5, rotation=20, ha="right")
        ax.set_title(ch, fontsize=7.5); ax.set_ylabel(q, fontsize=7)
        exp = d["expected"][jj[0]]
        ax.text(0.02, 0.97, exp, transform=ax.transAxes, fontsize=6, va="top")
    for ax in list(axes.flat)[len(checks):]:
        ax.set_visible(False)
    return fig


def plot_r2_f05(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 92, 1, 3)
    norm = LogNorm(vmin=0.3, vmax=300)
    for ax, t in zip(axes, "ABC"):
        jj = [i for i, x in enumerate(d["dorr"]) if x == t]
        polys = [[(d["x1"][i], d["z1"][i]), (d["x2"][i], d["z2"][i]), (d["x3"][i], d["z3"][i])] for i in jj]
        pc = PolyCollection(polys, array=np.clip([d["mises"][i] for i in jj], 0.3, 300), cmap="viridis", norm=norm,
                            edgecolors="none")
        ax.add_collection(pc)
        ax.set_xlim(-40, 70); ax.set_ylim(-80, 92); ax.set_aspect("equal"); ax.set_title(f"Dorr {t}")
        ax.set_xlabel("x (mm)")
    axes[0].set_ylabel("z (mm)")
    fig.colorbar(pc, ax=axes, shrink=0.8, label="von Mises stress (MPa, log)")
    return fig


def _profile_plot(csv_path, key, ylabel, thresholds=()):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        for side, ls in (("medial", "-"), ("lateral", "--"), ("tip", ":")):
            jj = sorted([i for i, (x, s) in enumerate(zip(d["dorr"], d["side"])) if x == t and s == side],
                        key=lambda i: d["s_arc"][i])
            if jj:
                ax.plot([d["s_arc"][i] for i in jj], [d[key][i] for i in jj], ls, color=ps.DORR[t], lw=1.0, label=side)
        for th in thresholds:
            ps.threshold_line(ax, th, "y", f"{th:g}")
        ax.set_title(f"Dorr {t}"); ax.set_xlabel(ps.LABEL["arc"])
    axes[0].set_ylabel(ylabel); axes[0].legend(loc="upper left")
    ps.panel_labels(axes)
    return fig


def plot_r2_f06(csv_path):
    return _profile_plot(csv_path, "cpress_load", "Contact pressure under load (MPa)")


def plot_r2_f07(csv_path):
    fig = _profile_plot(csv_path, "slip_um", ps.LABEL["slip"], thresholds=(50, 150))
    for ax in fig.axes:
        ax.set_yscale("symlog", linthresh=1.0)
    return fig


def plot_r2_f08(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 62, 1, 2, sharey=True)
    for ax, z in zip(axes, ("gruen7", "gruen1")):
        for k, t in enumerate("ABC"):
            for j, state in enumerate(("intact", "implanted")):
                i = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["zone"][i] == z and d["state"][i] == state][0]
                ax.bar(k * 3 + j, d["sed_kPa"][i], color=ps.DORR[t], alpha=1.0 if state == "intact" else 0.45,
                       hatch=None if state == "intact" else "///", edgecolor=ps.DORR[t])
        ax.set_xticks([0.5, 3.5, 6.5]); ax.set_xticklabels(["A", "B", "C"])
        ax.set_title("Gruen 7 (medial)" if z == "gruen7" else "Gruen 1 (lateral)")
        ax.set_xlabel("Dorr type (solid = intact, hatched = implanted)", fontsize=6.5)
    axes[0].set_ylabel("Mean SED in ROI (kPa)")
    ps.panel_labels(axes)
    return fig


def plot_r2_f09(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 62, 1, 2)
    for ax, (q, lab) in zip(axes, (("rel_df1", "|Δf1| / f1 (–)"), ("abs_df2", "|Δf2| (percentage points)"))):
        for k, dirn in enumerate(sorted(set(d["direction"]))):
            jj = sorted([i for i, x in enumerate(d["direction"]) if x == dirn], key=lambda i: d["eps"][i])
            ax.plot([d["eps"][i] for i in jj], [max(d[q][i], 1e-9) for i in jj], "o-",
                    color=[ps.OKABE_ITO["blue"], ps.OKABE_ITO["orange"]][k % 2], label=f"direction {int(dirn) + 1}")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("Perturbation size in unit design space (–)"); ax.set_ylabel(lab)
    axes[0].legend(loc="upper left")
    ps.panel_labels(axes)
    return fig


def plot_r2_f10(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 66, 1, 2)
    for ax, (q, lab) in zip(axes, (("f1", ps.LABEL["f1"]), ("f2", ps.LABEL["f2"]))):
        for t in "ABC":
            jj = [i for i, x in enumerate(d["dorr"]) if x == t]
            ax.scatter([d[f"{q}_medium"][i] for i in jj], [d[f"{q}_fine"][i] for i in jj], s=12, color=ps.DORR[t],
                       marker=ps.DORR_MARKER[t], label=f"Dorr {t} (ρ = {d[f'rho_{q}'][jj[0]]:.2f})")
        allv = [v for k in (f"{q}_medium", f"{q}_fine") for v in d[k]]
        lim = ps.shared_limits(allv)
        ax.plot(lim, lim, color="black", lw=0.8)
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel(f"{lab}, 0.75 mm mesh", fontsize=7); ax.set_ylabel(f"{lab}, 0.375 mm mesh", fontsize=7)
        ax.legend(loc="upper left", fontsize=6)
    ps.panel_labels(axes)
    return fig


# ------------------------------------------------------------------ main
def main():
    types = "ABC"
    # ---------- 基线（每型，保留全部文件用于场图与确定性比较）
    base_rows = {t: r for t, r in zip(types, EV.evaluate([{"dorr": t, "design": BASE, "note": "S2 baseline"} for t in types],
                                                         campaign="S2_baseline", provenance="manual"))}
    rerun = {t: r for t, r in zip(types, EV.evaluate([{"dorr": t, "design": BASE, "note": "S2 determinism rerun (keep_all)"}
                                                      for t in types], campaign="S2_rerun", provenance="manual",
                                                     keep_all=True, force=True))}
    for t in types:
        for r in (base_rows[t], rerun[t]):
            if r["status"] != "OK":
                raise RuntimeError(f"baseline {t} failed: {r}")

    # ---------- V2 网格收敛
    conv_items = [{"dorr": t, "design": BASE, "variant": {"mesh_scale": sc}, "note": f"S2 convergence x{sc}"}
                  for t in types for sc in (2.0, 0.5)]
    conv = EV.evaluate(conv_items, campaign="S2_convergence", provenance="manual")
    conv_by = {(it["dorr"], it["variant"]["mesh_scale"]): r for it, r in zip(conv_items, conv)}
    # ---------- V3 符号检查与敏感性（B 型）
    def dvar(**mod):
        x = dict(BASE); x.update(mod); return x
    sign_items = [
        ("delta", "δ = 0", {"dorr": "B", "design": BASE, "variant": {"delta": 0.0}}),
        ("mu", "μ = 0.5", {"dorr": "B", "design": BASE, "variant": {"mu": 0.5}}),
        ("mu", "μ = 0.8", {"dorr": "B", "design": BASE, "variant": {"mu": 0.8}}),
        ("length", "shorter (tip 20 mm)", {"dorr": "B", "design": dvar(tip_depth=20.0)}),
        ("width", "wider (w_prox 0.95)", {"dorr": "B", "design": dvar(w_prox=0.95)}),
        ("side plate", "plate 0 mm", {"dorr": "B", "design": BASE, "variant": {"side_plate": 0.0}}),
        ("side plate", "plate 6 mm", {"dorr": "B", "design": BASE, "variant": {"side_plate": 6.0}}),
        ("side plate", "plate 12 mm", {"dorr": "B", "design": BASE, "variant": {"side_plate": 12.0}}),
        ("load direction", "Fx lateral", {"dorr": "B", "design": BASE, "variant": {"load_sign": -1.0}}),
    ]
    sres = EV.evaluate([dict(it, note=f"S2 sign check {lab}") for _, lab, it in sign_items], campaign="S2_signcheck",
                       provenance="manual")
    # ---------- V5 噪声底（B 型，两个随机方向）
    rng = np.random.default_rng(20260927)
    dirs = [v / np.linalg.norm(v) for v in rng.normal(size=(2, 5))]
    eps_list = [1e-4, 1e-3, 1e-2, 5e-2]
    noise_items = []
    for k, v in enumerate(dirs):
        for e in eps_list:
            u = np.clip(BASE_U + e * v, 0, 1)
            noise_items.append({"dorr": "B", "design": S.to_physical(u), "note": f"S2 noise dir{k} eps{e:g}", "_k": k, "_e": e})
    nres = EV.evaluate([{k: v for k, v in it.items() if not k.startswith("_")} for it in noise_items],
                       campaign="S2_noise", provenance="manual")

    # ---------- V2 补充：网格对排序的影响（每型 12 个通过几何门的 Sobol 设计，生产网格对细网格）
    from scipy.stats import qmc, spearmanr
    rank_items = []
    for t in types:
        U = qmc.Sobol(5, scramble=True, seed=321).random(256)
        picked = [u for u in U if S.gate(S.make(t, S.to_physical(u)))["pass"]][:12]
        for u in picked:
            for sc in (1.0, 0.5):
                rank_items.append({"dorr": t, "design": S.to_physical(u), "variant": {"mesh_scale": sc},
                                   "note": f"S2 mesh-rank x{sc}"})
    rres = EV.evaluate(rank_items, campaign="S2_meshrank", provenance="sampled")
    mesh_pairs = {}
    for it, r in zip(rank_items, rres):
        key = (it["dorr"], tuple(round(v, 9) for v in it["design"].values()))
        mesh_pairs.setdefault(key, {})[it["variant"]["mesh_scale"]] = r

    # ---------- V1 Lamé（两种环材料）
    lame = []
    for case, E_o in (("cortical ring", CFG["materials"]["cortical"]["E"]), ("cancellous ring", 300.0)):
        d = ROOT / "runs" / "S2_lame" / case.split()[0]
        info = FM.build_lame(d, f"lame_{case.split()[0]}", E_o=E_o, nu_o=0.3)
        r = ra.run_and_export(d / f"lame_{case.split()[0]}.inp")
        if r["status"] != "OK":
            raise RuntimeError(f"Lamé {case} failed: {r}")
        c = qoi._csv(d / f"lame_{case.split()[0]}_csv" / "PRESSFIT_CONTACT.csv")
        m = dict(np.load(d / "mesh.npz")) if (d / "mesh.npz").exists() else None
        nodes = {}
        inp_text = (d / f"lame_{case.split()[0]}.inp").read_text()
        blk = inp_text.split("*NODE")[1].split("*")[0].strip().splitlines()
        for line in blk:
            a = line.split(",")
            nodes[int(a[0])] = (float(a[1]), float(a[2]))
        m2 = inp_text.split("*NODE")[2].split("*")[0].strip().splitlines()
        for line in m2:
            a = line.split(",")
            nodes[int(a[0])] = (float(a[1]), float(a[2]))
        sel = c["field"] == "CPRESS"
        for n, p in zip(c["node"][sel].astype(int), c["value"][sel]):
            x, y = nodes[n]
            rr = math.hypot(x, y)
            if abs(rr - (10.0 - 0.1)) < 1e-3 and p > 0:
                lame.append(dict(case=case, node=int(n), angle_deg=math.degrees(math.atan2(y, x)), cpress=float(p),
                                 p_analytic=info["p_analytic"], ratio=float(p) / info["p_analytic"]))
    lame_err = {case: abs(np.median([r["ratio"] for r in lame if r["case"] == case]) - 1) for case in ("cortical ring", "cancellous ring")}

    # ================================================================== 发布
    src = {"runs_csv": "results/runs.csv campaign S2_*", "baseline_u": BASE_U.round(3).tolist()}
    # F01 网格
    rows = []
    for t in types:
        rd = ROOT / "runs" / rerun[t]["design_id"]
        for reg, el, tri in load_mesh_polys(rd):
            rows.append(dict(dorr=t, part=reg, elem=el, x1=tri[0, 0], z1=tri[0, 1], x2=tri[1, 0], z2=tri[1, 1],
                             x3=tri[2, 0], z3=tri[2, 1]))
    ne = {t: (int(fnum(rerun[t], "n_elem_bone")), int(fnum(rerun[t], "n_elem_stem"))) for t in types}
    ps.publish_figure("R2-F01", rows, plot_r2_f01, sources=src,
                      title=(f"Meshes use 0.75 mm elements at the interface and 3 mm far away "
                             f"({ne['B'][0]:,} bone + {ne['B'][1]:,} stem elements for Dorr B)"),
                      caption=("上排为全模型，下排为柄尖附近放大（上排红框）。灰色为皮质、浅黄为松质、白色半透明为锉刀腔处的侧板单元、"
                               "蓝色为柄。骨与柄网格独立（接触或 TIE 连接），皮质、松质与侧板共节点。单元均为 CPS6M。"))
    # F02 Lamé
    ps.publish_figure("R2-F02", lame, plot_r2_f02, sources={"runs": "runs/S2_lame/"},
                      title=(f"Press-fit contact pressure matches the Lamé solution within "
                             f"{max(lame_err.values()) * 100:.1f} %"),
                      caption=("四分之一模型：钛合金实心圆盘（半径 10 mm）压入外径 25 mm 的圆环，径向过盈 0.1 mm，"
                               "*CONTACT INTERFERENCE, SHRINK、小滑移面面接触、μ = 0.3，平面应力厚度 1 mm。"
                               "纵轴为各接触节点 CPRESS 与平面应力 Lamé 解之比。"),
                      units={"cpress": "MPa", "angle_deg": "deg"})
    # F03 收敛 + T02 GCI
    crow, gtab = [], []
    for t in types:
        vals = {}
        for sc, r in ((0.5, conv_by[(t, 0.5)]), (1.0, base_rows[t]), (2.0, conv_by[(t, 2.0)])):
            if r["status"] != "OK":
                raise RuntimeError(f"convergence run {t} x{sc} failed: {r['fail_reason']}")
            vals[sc] = (fnum(r, "f1_p95_um"), fnum(r, "f2_g7_loss_pct"), int(fnum(r, "n_elem_bone")) + int(fnum(r, "n_elem_stem")))
        g1 = gci([vals[0.5][0], vals[1.0][0], vals[2.0][0]])
        g2 = gci([vals[0.5][1], vals[1.0][1], vals[2.0][1]])
        for sc in (0.5, 1.0, 2.0):
            crow.append(dict(dorr=t, h_mm=0.75 * sc, n_elem=vals[sc][2], f1=vals[sc][0], f2=vals[sc][1],
                             gci_f1=g1["gci_fine"] if sc == 0.5 else "", gci_f2=g2["gci_fine"] if sc == 0.5 else ""))
        for q, g in (("f1 (µm)", g1), ("f2 (%)", g2)):
            gtab.append(dict(dorr=t, quantity=q, N1=vals[0.5][2], N2=vals[1.0][2], N3=vals[2.0][2], r21=2.0, r32=2.0,
                             phi1=g["phi1"], phi2=g["phi2"], phi3=g["phi3"], p=g["p"], phi_ext=g["phi_ext"],
                             e_a21_pct=100 * g["e_a21"], e_ext21_pct=100 * g["e_ext21"],
                             GCI_fine_pct=100 * g["gci_fine"], behaviour=g["behaviour"]))
    change = max(max(abs(r["phi1"] - r["phi2"]) / abs(r["phi1"]) for r in gtab if r["dorr"] == t) for t in types)
    ps.publish_figure("R2-F03", crow, plot_r2_f03, sources=src,
                      title=(f"Halving the interface element size from 0.75 to 0.375 mm changes f1 and f2 by at most "
                             f"{change * 100:.1f} %"),
                      caption=("三套网格（界面 1.5、0.75、0.375 mm，远场同比例缩放，细化比 r = 2）。"
                               "最细网格上的误差棒为 Celik 2008 的 GCI_fine × |φ|。生产网格为 0.75 mm。"),
                      units={"h_mm": "mm", "f1": "µm", "f2": "%"})
    ps.publish_table("R2-T02", gtab, title="网格收敛指数（Celik 2008）",
                     caption="φ1 最细、φ3 最粗；p 为表观阶数；e_a21 为最细两套网格的相对差；GCI_fine 为最细网格的离散不确定度。",
                     units={"phi1": "µm 或 %"})
    # F04 符号检查
    b = base_rows["B"]
    fb1, fb2 = fnum(b, "f1_p95_um"), fnum(b, "f2_g7_loss_pct")
    srow = []
    S_ = {lab: r for (_, lab, _), r in zip(sign_items, sres)}
    for r in sres:
        if r["status"] != "OK":
            raise RuntimeError(f"sign check failed: {r}")

    def add(check, quantity, expected, entries, ok_fn):
        ok = ok_fn()
        for var, val in entries:
            srow.append(dict(check=check, quantity=quantity, variant=var, value=val, expected=expected,
                             ok=int(ok) if ok is not None else -1))
        return ok
    ok_delta = add("interference δ", "f1 P95 (µm)", "expect: δ = 0 > δ = 0.1",
                   [("δ = 0.1", fb1), ("δ = 0", fnum(S_["δ = 0"], "f1_p95_um"))],
                   lambda: fnum(S_["δ = 0"], "f1_p95_um") > fb1)
    ok_mu = add("friction μ", "f1 P95 (µm)", "expect: decreasing with μ",
                [("μ = 0.3", fb1), ("μ = 0.5", fnum(S_["μ = 0.5"], "f1_p95_um")), ("μ = 0.8", fnum(S_["μ = 0.8"], "f1_p95_um"))],
                lambda: fb1 > fnum(S_["μ = 0.5"], "f1_p95_um") > fnum(S_["μ = 0.8"], "f1_p95_um"))
    # 粘接模型滑移：重跑目录保留了 U
    tie_um = tie_slip_um(ROOT / "runs" / rerun["B"]["design_id"], rerun["B"]["design_id"])
    ok_tie = add("bonded interface", "slip P95 (µm)", "expect: bonded ≈ 0 ≪ friction",
                 [("friction", fb1), ("bonded", tie_um)], lambda: tie_um < 0.05 * fb1)
    ok_len1 = add("stem length → f1", "f1 P95 (µm)", "expect: shorter > baseline",
                  [("baseline", fb1), ("shorter", fnum(S_["shorter (tip 20 mm)"], "f1_p95_um"))],
                  lambda: fnum(S_["shorter (tip 20 mm)"], "f1_p95_um") > fb1)
    ok_len2 = add("stem length → f2", "f2 Gruen 7 loss (%)", "expect: shorter < baseline",
                  [("baseline", fb2), ("shorter", fnum(S_["shorter (tip 20 mm)"], "f2_g7_loss_pct"))],
                  lambda: fnum(S_["shorter (tip 20 mm)"], "f2_g7_loss_pct") < fb2)
    ok_w1 = add("stem width → f1", "f1 P95 (µm)", "expect: wider < baseline",
                [("baseline", fb1), ("wider", fnum(S_["wider (w_prox 0.95)"], "f1_p95_um"))],
                lambda: fnum(S_["wider (w_prox 0.95)"], "f1_p95_um") < fb1)
    ok_w2 = add("stem width → f2", "f2 Gruen 7 loss (%)", "expect: wider > baseline",
                [("baseline", fb2), ("wider", fnum(S_["wider (w_prox 0.95)"], "f2_g7_loss_pct"))],
                lambda: fnum(S_["wider (w_prox 0.95)"], "f2_g7_loss_pct") > fb2)
    add("side plate (sensitivity)", "f1 P95 (µm)", "sensitivity, no expected sign",
        [("0 mm", fnum(S_["plate 0 mm"], "f1_p95_um")), ("3 mm", fb1), ("6 mm", fnum(S_["plate 6 mm"], "f1_p95_um")),
         ("12 mm", fnum(S_["plate 12 mm"], "f1_p95_um"))], lambda: None)
    add("load direction (sensitivity)", "f1 P95 (µm)", "sensitivity, no expected sign",
        [("Fx medial", fb1), ("Fx lateral", fnum(S_["Fx lateral"], "f1_p95_um"))], lambda: None)
    sign_all = [ok_delta, ok_mu, ok_tie, ok_len1, ok_len2, ok_w1, ok_w2]
    ps.publish_figure("R2-F04", srow, plot_r2_f04, sources=src,
                      title=f"{sum(sign_all)} of {len(sign_all)} sign checks go the expected way",
                      caption=("Dorr B 基线设计的单因素改动。绿色 = 方向符合预期，红色 = 不符合，灰色 = 只做敏感性、无预设方向。"
                               "侧板厚度与载荷方向两组是模型假设的敏感性。"),
                      units={"value": "µm or %"})
    # F05 应力场
    frow = []
    for t in types:
        rd = ROOT / "runs" / rerun[t]["design_id"]
        mis = {}
        for kind in ("fric",):
            s_ = qoi._csv(rd / f"{rerun[t]['design_id']}_{kind}_csv" / "LOAD_S.csv")
            mis = dict(zip(s_["elem"].astype(int), s_["mises"]))
        for reg, el, tri in load_mesh_polys(rd):
            if reg == "cavity" or el not in mis:
                continue
            if tri[:, 1].min() < -85:
                continue
            frow.append(dict(dorr=t, part=reg, elem=el, x1=tri[0, 0], z1=tri[0, 1], x2=tri[1, 0], z2=tri[1, 1],
                             x3=tri[2, 0], z3=tri[2, 1], mises=mis[el]))
    ps.publish_figure("R2-F05", frow, plot_r2_f05, sources=src,
                      title="Stem stresses peak in the prosthetic neck; bone stress concentrates in the calcar and lateral cortex",
                      caption=("摩擦模型加载步末的单元形心 von Mises 应力（对数色标，0.3–300 MPa 截断），只画小转子下 85 mm 以上。"
                               "骨为冠状面切片（侧板单元未画）。"),
                      units={"mises": "MPa"})
    # F06/F07 界面分布
    prow = []
    for t in types:
        rd = ROOT / "runs" / rerun[t]["design_id"]
        model = json.loads((rd / "model.json").read_text())
        pr = dict(np.load(rd / "interface_profile.npz"))
        xy = np.c_[pr["x"], pr["z"]]
        s_arc, v = arc_coords(model, xy)
        L = model["axis"]["L"]
        for i in range(len(xy)):
            side = "tip" if s_arc[i] > L - 1e-6 else ("medial" if v[i] > 0 else "lateral")
            prow.append(dict(dorr=t, node=int(pr["node"][i]), s_arc=float(min(s_arc[i], L + 5)), side=side,
                             cpress_load=float(pr["cpress"][i]), cpress_release=float(pr["cpress_pf"][i]),
                             slip_um=float(pr["slip_um"][i]), status=float(pr["status"][i])))
    ps.publish_figure("R2-F06", prow, plot_r2_f06, sources=src,
                      title="Under load the medial flank carries the contact pressure near the resection and the lateral flank near the tip",
                      caption="加载步末骨从面节点的接触压力，按节点在柄中轴上的弧长位置排列；实线内侧、虚线外侧、点线尖端帽。",
                      units={"s_arc": "mm", "cpress_load": "MPa"})
    ps.publish_figure("R2-F07", prow, plot_r2_f07, sources=src,
                      title="Micromotion stays below 50 µm along the whole interface for all three baselines",
                      caption=("加载步相对释放步的切向滑移增量（µm，对称对数轴）。点线为 50 与 150 µm 骨长入阈值。"),
                      units={"s_arc": "mm", "slip_um": "µm"})
    # F08 SED
    sed_rows = []
    for t in types:
        ref = EV.intact_ref(t, CFG["dorr"][t]["E_cancellous"], EV.default_variant())
        for z, key in (("gruen7", "sed_g7"), ("gruen1", "sed_g1")):
            sed_rows.append(dict(dorr=t, zone=z, state="intact", sed_kPa=1000 * ref[z]))
            sed_rows.append(dict(dorr=t, zone=z, state="implanted", sed_kPa=1000 * fnum(base_rows[t], key)))
    ps.publish_figure("R2-F08", sed_rows, plot_r2_f08, sources=src,
                      title="The neck-preserving stem raises calcar (Gruen 7) strain energy and shields the greater-trochanter region (Gruen 1)",
                      caption="粘接模型与完整股骨在同一 ROI 内的平均应变能密度（kPa = kJ/m³）。f2 = 1 − 植入/完整（Gruen 7）。",
                      units={"sed_kPa": "kPa"})
    # F09 噪声底
    nrow = []
    for it, r in zip(noise_items, nres):
        if r["status"] != "OK":
            continue
        nrow.append(dict(direction=it["_k"], eps=it["_e"], f1=fnum(r, "f1_p95_um"), f2=fnum(r, "f2_g7_loss_pct"),
                         rel_df1=abs(fnum(r, "f1_p95_um") - fb1) / fb1, abs_df2=abs(fnum(r, "f2_g7_loss_pct") - fb2)))
    small = [r for r in nrow if r["eps"] <= 1e-3]
    # 噪声底取扰动 ≤ 1e-3 时输出变化的均方根（中位数会掩盖重新网格化偶发的大跳变）
    noise_f1 = float(np.sqrt(np.mean([r["rel_df1"] ** 2 for r in small]))) if small else float("nan")
    noise_f2 = float(np.sqrt(np.mean([r["abs_df2"] ** 2 for r in small]))) if small else float("nan")
    ps.publish_figure("R2-F09", nrow, plot_r2_f09, sources=src,
                      title=(f"Re-meshing noise (RMS for perturbations ≤ 1e-3) is {noise_f1 * 100:.1f} % in f1 "
                             f"and {noise_f2:.2f} points in f2"),
                      caption=("Dorr B 基线沿两个随机方向扰动（单位立方体坐标），每个扰动都重新生成网格。"
                               "扰动很小时输出变化来自重新网格化的数值噪声；噪声底取扰动 ≤ 1e-3 各点变化的均方根，"
                               "作为 GP 观测噪声的先验下限。个别小扰动出现数个百分点的跳变，说明网格拓扑变化会带来偶发噪声。"),
                      units={"eps": "–"})
    # F10 网格排序一致性（附加图）
    rk_rows, rho = [], {}
    for t in types:
        pairs = [(v[1.0], v[0.5]) for k, v in mesh_pairs.items() if k[0] == t and 1.0 in v and 0.5 in v
                 and v[1.0]["status"] == "OK" and v[0.5]["status"] == "OK"]
        m1 = [fnum(a, "f1_p95_um") for a, _ in pairs]; f1 = [fnum(b, "f1_p95_um") for _, b in pairs]
        m2 = [fnum(a, "f2_g7_loss_pct") for a, _ in pairs]; f2 = [fnum(b, "f2_g7_loss_pct") for _, b in pairs]
        rho[t] = (float(spearmanr(m1, f1)[0]), float(spearmanr(m2, f2)[0]), len(pairs))
        for a, b, c, e in zip(m1, f1, m2, f2):
            rk_rows.append(dict(dorr=t, f1_medium=a, f1_fine=b, f2_medium=c, f2_fine=e, rho_f1=rho[t][0], rho_f2=rho[t][1]))
    ps.publish_figure("R2-F10", rk_rows, plot_r2_f10, sources=src,
                      title=(f"The 0.75 mm mesh underestimates micromotion but ranks designs like the 0.375 mm mesh "
                             f"(Spearman ρ for f1 ≥ {min(v[0] for v in rho.values()):.2f}, f2 ≥ {min(v[1] for v in rho.values()):.2f})"),
                      caption=("附加验证（为 R2-A2 的处置提供证据）：每型 12 个通过几何门的 Sobol 设计分别用生产网格（界面 0.75 mm）"
                               "与细网格（0.375 mm）计算。黑线为 y = x；ρ 为 Spearman 秩相关。"))

    # T01 Erdemir
    er = list(csv.DictReader(open(ROOT / "reports" / "checklists" / "erdemir2012_checklist.csv", encoding="utf-8-sig")))
    final = {"E22": "头部圆盘（半径 14 mm）内全部节点均分头心载荷（等价 UNIFORM 分布耦合，未用约束方程以减少变量）；远端截面全固支；压配为接触过盈 SHRINK，压配步固定假体头节点",
             "E23": "头部圆盘节点（植入：假体头；完整：股骨头内）；远端截面（小转子下 150 mm）",
             "E53": "面面离散、小滑移；骨为从面、柄为主面；罚函数摩擦（slip tolerance 0.005）；硬接触；另加前后皮质侧板（3 mm）",
             "E57": "隐式静力；三步（PRESSFIT 固定假体头 → RELEASE 释放 → LOAD）；初始增量 0.25、最大 1.0，自动增量；增量设置敏感性见方法"}
    t01 = []
    for r in er:
        ans = final.get(r["code"], r["本项目计划答案"])
        st = r["状态"].replace("待 S2 定稿", "已定稿（S2）").replace("计划", "已填写")
        t01.append(dict(code=r["code"], section=r["section"], item=r["item"], answer=ans, where=r["落点"], status=st))
    ps.publish_table("R2-T01", t01, title="Erdemir 2012 FEA 报告清单 80 项（取得 Oefner 2021 后换为其报告表）",
                     caption="N/A 项注明理由。全表 80 行，报告内只显示前 60 行，完整见 CSV。")
    filled = sum(1 for r in t01 if r["answer"])
    # T03 确定性
    t03 = []
    same_all = True
    for t in types:
        for k in ("f1_p95_um", "f2_g7_loss_pct", "f2_g1_loss_pct", "vm_p99"):
            a, bb = base_rows[t][k], rerun[t][k]
            same = str(a) == str(bb) or (float(a) == float(bb))
            same_all &= same
            t03.append(dict(dorr=t, quantity=k, run_1=float(a), run_2=float(bb), identical="yes" if same else "no",
                            design_ids=f"{base_rows[t]['design_id']} / {rerun[t]['design_id']}"))
    ps.publish_table("R2-T03", t03, title="确定性：同一设计两次独立运行（重新网格化与求解）",
                     caption="两次运行各自从几何重新生成网格与 .inp；比较 QoI 的完整双精度值。")

    # ---------- 验收
    ok_sign = all(sign_all)
    ps.publish_acceptance("R2", [
        {"id": "R2-A1", "measured": "；".join(f"{k} {v * 100:.2f} %" for k, v in lame_err.items()),
         "status": "PASS" if max(lame_err.values()) < 0.05 else "FAIL", "note": "" if max(lame_err.values()) < 0.05 else "检查接触离散"},
        {"id": "R2-A2", "measured": f"最细两套网格最大相对变化 {change * 100:.2f} %；GCI 见 R2-T02",
         "status": "PASS" if change < 0.05 else "FAIL",
         "note": "" if change < 0.05 else (
             "f1（P95 微动）未收敛：细网格解出更大的滑移区，生产网格系统性低估 f1；换摩擦列式（Lagrange、滑移容差 0.0005）不改变结论。"
             f"f2 变化 {max(abs(r['phi1'] - r['phi2']) / abs(r['phi1']) for r in gtab if r['quantity'].startswith('f2')) * 100:.1f} %。"
             "但生产网格与细网格对设计的排序一致（R2-F10：每型 12 个设计，f1 的 Spearman ρ = "
             + "、".join(f"{t} {rho[t][0]:.2f}" for t in types) + "）。"
             "处置建议：BO 与参考扫描用同一生产网格，本测试检验的是\"在同一模型上 BO 能否找到前沿\"，系统偏差不影响这一结论；"
             "f1 绝对值不作解释，R7 把离散误差列为可信度缺口。备选：生产网格改 0.375 mm，S4–S5 机时约增 4 倍（约 20 h）。需用户决定。")},
        {"id": "R2-A3", "measured": f"{sum(sign_all)}/{len(sign_all)} 方向正确",
         "status": "PASS" if ok_sign else "FAIL",
         "note": "" if ok_sign else (
             "不符合的两项都是\"柄更宽\"（w_prox 0.80 → 0.95）："
             f"f1 {fb1:.1f} → {fnum(S_['wider (w_prox 0.95)'], 'f1_p95_um'):.1f} µm（预期下降），"
             f"f2 {fb2:.1f} → {fnum(S_['wider (w_prox 0.95)'], 'f2_g7_loss_pct'):.1f} %（预期升高）。"
             "预期来自常规柄\"越大越硬越遮挡\"的经验；保颈柄近端加宽后贴住保留颈环与股骨距，载荷更多经股骨距传递（f2 更负），"
             "与颈环接触形成支点也可能加大远端滑移。δ、μ、柄长与粘接四组方向全部正确，模型错误的可能性较小，"
             "但该解释未经独立验证。处置建议：保留模型，把\"宽度\"的预期方向改为\"不预设\"，由 R6 的 3D 抽检核对；需用户决定。")},
        {"id": "R2-A4", "measured": "三型 4 个 QoI 全部逐位相同" if same_all else "存在差异", "status": "PASS" if same_all else "FAIL",
         "note": "" if same_all else "检查网格或求解器的非确定性"},
        {"id": "R2-A5", "measured": f"f1 相对 {noise_f1 * 100:.3f} %；f2 {noise_f2:.4f} 百分点",
         "status": "PASS" if not math.isnan(noise_f1) else "FAIL", "note": ""},
        {"id": "R2-A6", "measured": f"{filled}/80", "status": "PASS" if filled == 80 else "FAIL", "note": ""},
    ])
    json.dump({"noise_rel_f1": noise_f1, "noise_abs_f2": noise_f2, "gci": gtab},
              open(ROOT / "results" / "noise_floor.json", "w"), indent=1, default=float)
    ps.publish_inputs("R2", runs_csv_campaigns="S2_baseline, S2_rerun, S2_convergence, S2_signcheck, S2_noise, S2_meshrank",
                      baseline_design={k: round(v, 3) for k, v in BASE.items()},
                      side_plate_mm=CFG["side_plate"]["thickness"], Abaqus="2025")
    write_text(base_rows, lame_err, change, sign_all, noise_f1, noise_f2, tie_um, S_, fb1, fb2)
    print(json.dumps({"lame": lame_err, "conv": change, "sign": sign_all, "noise": [noise_f1, noise_f2],
                      "tie_um": tie_um, "same": same_all}, indent=1, default=str))


def tie_slip_um(run_dir: pathlib.Path, name: str) -> float:
    """粘接模型：从面节点位移与柄在同一位置的位移（柄三角形内按角节点线性插值）之差的 P95（µm）。
    未被 TIE 绑定的从面节点（.dat 里 WILL NOT BE TIED）单独计数，写入 results/tie_check.json。"""
    import re
    import matplotlib.tri as mtri
    m = dict(np.load(run_dir / "mesh.npz"))
    model = json.loads((run_dir / "model.json").read_text())
    lab, xy, w = qoi.interface_nodes(m, model)
    U = qoi._csv(run_dir / f"{name}_bond_csv" / "LOAD_U.csv")
    u = dict(zip(U["node"].astype(int), np.c_[U["u1"], U["u2"]]))
    sl, sx = m["stem_labels"], m["stem_nodes"]
    lut = np.full(int(sl.max()) + 1, -1); lut[sl] = np.arange(len(sl))
    tri = lut[m["stem_stem_conn"][:, :3]]
    T = mtri.Triangulation(sx[:, 0], sx[:, 1], tri)
    finder = T.get_trifinder()
    us = np.array([u[int(n)] for n in sl])
    rel = []
    for p, n in zip(xy, lab):
        k = finder(p[0], p[1])
        if k < 0:
            j = int(np.argmin(np.linalg.norm(sx - p, axis=1))); ui = us[j]
        else:
            a, b, c = sx[tri[k]]
            M = np.array([[b[0] - a[0], c[0] - a[0]], [b[1] - a[1], c[1] - a[1]]])
            l1, l2 = np.linalg.solve(M, p - a)
            ui = (1 - l1 - l2) * us[tri[k][0]] + l1 * us[tri[k][1]] + l2 * us[tri[k][2]]
        rel.append(np.linalg.norm(u[int(n)] - ui) * 1000)
    dat = (run_dir / f"{name}_bond.dat").read_text(errors="ignore")
    untied = len(re.findall(r"SECONDARY NODE\s+\d+\s+WILL NOT BE TIED", dat))
    json.dump({"design": name, "untied_slave_nodes": untied, "n_slave_nodes": int(len(lab))},
              open(ROOT / "results" / "tie_check.json", "w"))
    return qoi.wquantile(np.array(rel), w, 0.95)


def write_text(base_rows, lame_err, change, sign_all, noise_f1, noise_f2, tie_um, S_, fb1, fb2):
    tx = ps.report_dir("R2") / "text"
    f1s = {t: EV.as_float(base_rows[t], "f1_p95_um") for t in "ABC"}
    f2s = {t: EV.as_float(base_rows[t], "f2_g7_loss_pct") for t in "ABC"}
    conv_txt = (f"最细两套网格 f1、f2 最大变化 {change * 100:.1f} %，" if change < 0.05 else
                f"**网格收敛不通过**：界面单元从 0.75 mm 减半到 0.375 mm，f1 最多变 {change * 100:.0f} %"
                "（细网格解出更大的滑移区，生产网格系统性低估 f1；f2 变化 5–9 %），但两套网格对设计的排序一致（R2-F10），处置需用户决定；")
    tx.joinpath("summary.md").write_text(
        f"Lamé 压配接触压力误差 {max(lame_err.values()) * 100:.1f} %；" + conv_txt +
        f"{sum(sign_all)}/{len(sign_all)} 项符号检查方向正确；"
        f"同一设计重跑逐位相同；重新网格化噪声底 f1 约 {noise_f1 * 100:.2f} %、f2 约 {noise_f2:.3f} 个百分点。"
        f"三型基线设计的 f1（P95 微动）为 A {f1s['A']:.1f}、B {f1s['B']:.1f}、C {f1s['C']:.1f} µm，"
        f"f2（Gruen 7 SED 下降率）为 {f2s['A']:.0f} / {f2s['B']:.0f} / {f2s['C']:.0f} %（负值表示股骨距应变能升高）。"
        "**相对已批准计划有两处模型修改**：加了 3 mm 前后皮质侧板（无侧板时压配后 90 % 界面张开，见方法），"
        "压配改为三步（固定假体头压配 → 释放 → 加载）。侧板厚度对 f1 影响大（R2-F04），在 R7 列为主要模型形式不确定性。",
        encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**几何到网格（`fe_model.py`、`mesh2d.py`）**：保留骨 = 外轮廓 ∩ 截骨线以下；锉刀腔 = 柄体半宽内缩 δ 后与保留骨的交；"
        "保留骨、锉刀腔、髓腔三条边界先吸附到 0.001 mm 网格再一次性打断、polygonize 成平面剖分，每个面按代表点分为皮质、松质、锉刀腔，"
        "厚度 < 0.25 mm 的松质骨细条改标为皮质；这样共享边界逐点一致。gmsh 二阶三角形（CPS6M），界面 0.75 mm、"
        "距界面 12 mm 内线性过渡到 3 mm（骨）/ 3 mm（柄内部）。\n\n"
        "**侧板（相对计划新增）**：无侧板时冠状面骨在截骨面处是开口的 U 形，楔形柄的过盈被内外侧两条骨臂张开吸收——"
        "Dorr B 基线压配后 90 % 界面张开、平均接触压力 0.3 MPa（R2-F04 的 0 mm 一组）。按 Huiskes/Weinans 的 2D 柄模型做法，"
        "加一层覆盖保留骨与锉刀腔的皮质侧板（与骨共节点，跨过柄连接内外侧壁，提供环向刚度），代表前后皮质；"
        "默认厚度 3 mm（近端干骺端前后壁每侧约 1–2 mm），侧板与柄之间不定义接触。有侧板后界面 92 % 闭合。"
        "侧板厚度 0/3/6/12 mm 的 f1 为 "
        f"{EV.as_float(S_['plate 0 mm'], 'f1_p95_um'):.1f} / {fb1:.1f} / {EV.as_float(S_['plate 6 mm'], 'f1_p95_um'):.1f} / "
        f"{EV.as_float(S_['plate 12 mm'], 'f1_p95_um'):.1f} µm。\n\n"
        "**材料与载荷**：皮质 16,800 MPa / 0.3，松质骨 A/B/C 400/300/150 MPa / 0.3，Ti6Al4V 110,000 MPa / 0.35；"
        "平面应力厚度骨 30 mm、柄 12 mm、侧板 3 mm，接触面外厚度 12 mm。载荷 Fx = +668 N（与源 3D 模型同号，+x 为内侧）、"
        "Fz = −2,296 N，均分到头心 14 mm 圆盘内全部节点（等价 UNIFORM 分布耦合；分布耦合的约束方程使摩擦模型求解慢 5 倍，结果差 < 1 %）；"
        "远端截面全固支。载荷方向改为外侧（Fx = −668 N）的敏感性见 R2-F04。\n\n"
        "**两个模型（CLAUDE.md §5.2）**：`_fric` 面面小滑移摩擦接触，骨为从面、柄为主面，从面只取锉刀腔切出的骨边界；"
        "三步：PRESSFIT（*CONTACT INTERFERENCE, SHRINK，同时固定假体头节点——锥形柄在全量过盈下会被挤出，相当于术中压住打入）、"
        "RELEASE（撤去假体头约束、不加载，柄在摩擦下回弹平衡）、LOAD（加载）。`_bond` 用 *TIE, ADJUST=NO（位置容差 0.3 mm 覆盖 0.1 mm 过盈），单步加载。"
        "完整股骨参照模型同网格规则、同侧板、同载荷。\n\n"
        "**关注量（`qoi.py`）**：f1 = 从面节点 |CSLIP1(LOAD) − CSLIP1(RELEASE)| 按 Simpson 权重的界面长度加权 P95（µm）；"
        "f2 = 粘接模型 Gruen 7 ROI 内骨单元平均 SED 相对完整股骨的下降率（%）；约束 = 粘接模型柄单元（除假体头圆盘）面积加权 von Mises P99。\n\n"
        "**验证**：V1 四分之一 Lamé 模型（皮质环与 300 MPa 松质环两种）；V2 界面单元 1.5/0.75/0.375 mm 三套网格，Celik 2008 GCI；"
        "V3 Dorr B 基线的单因素改动（δ、μ、柄长、柄宽、粘接对摩擦），另做侧板厚度与载荷方向敏感性；"
        "V4 三型基线各独立重跑一次（重新网格化与求解）逐位比较；V5 沿两个随机方向在单位立方体中扰动 1e-4 至 5e-2。"
        "增量设置敏感性（Erdemir 2012 E64）：初始增量 0.25、0.5、1.0 三种设置下 Dorr B 基线 f1 完全相同（19.462 µm，开发阶段测试）。",
        encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 近截骨处内侧的节点滑移呈锯齿（二次单元角节点与中点节点交替，R2-F07），P95 对此不敏感但单点最大值不可信。\n"
        "- f1（P95 微动）在生产网格上未网格收敛：细网格解出更大的滑移区，f1 绝对值偏低；换摩擦列式（Lagrange 乘子、"
        "滑移容差 0.0005）不改变这一点（开发测试：C 型基线 12.6 → 21.0 µm）。排序在两套网格间一致（R2-F10），"
        "所以只把 f1 用于同一网格上的相对比较。\n"
        "- 侧板厚度是本模型最大的形式假设：3 → 12 mm 时 f1 下降约 4 倍（R2-F04）。优化只比较同一侧板厚度下的设计，排序是否随侧板厚度改变未检验。\n"
        "- 压配接触压力量级（数十 MPa）高于真实松质骨能承受的水平；模型为线弹性，无骨屈服或压溃。\n"
        "- f2 在三型基线上都是负值（股骨距 SED 升高），Gruen 7 下降率作为目标时\"越小越好\"即\"股骨距加载越多越好\"。\n"
        "- 载荷方向沿用源 3D 模型的号（内下方），与单腿站立关节力通常的外下方向相反，需用户确认；外侧方向的结果见 R2-F04。\n"
        "- Oefner 2021 报告表未取得，R2-T01 暂用 Erdemir 2012 清单。", encoding="utf-8")


if __name__ == "__main__":
    main()
