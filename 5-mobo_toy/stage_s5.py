"""S5 BO × 三型 × 三种子 + 同预算 Sobol 基线 → R5 报告。python stage_s5.py [--types ABC] [--smoke] [--replot]

* 参考点（每型固定，跨种子相同）：三个种子的 12 个初始设计合并，取可行者各目标最大值 + 10 % 极差。
* 参考前沿（HV 比与 IGD 的分母）= 该型 R4 参考扫描 + R5 全部 FE 评估的可行非支配集。
* 代理诊断：每个 BO 种子最终 60 点训练的 GP，在 R4 参考扫描设计（与 BO 设计按 cache_key 不重叠）上检验。
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import torch
from scipy.stats import norm, spearmanr

import evaluate as EV
import femur2d as F
import mobo
import mobo_fe as MF
import plotstyle as ps
import reference_sweep as RS
import stem2d as S
from stage_s1 import CANC_FC, CORTEX_FC, draw, poly_rows, sel

ROOT = ps.ROOT
CFG = F.CFG
VARS = S.VARS
SEEDS = CFG["bo"]["seeds"]
OUTF = ROOT / "results" / "S5_runs.json"


def group_rows(prefix=""):
    g = json.loads((ROOT / "results" / f"{prefix}S4_groups.json").read_text())
    by = {r["design_id"]: r for r in EV.read_runs()}
    return {k: [by[d] for d in v if d in by] for k, v in g.items()}


# ------------------------------------------------------------------ 运行
def ref_point_for(t: str, pools: dict) -> np.ndarray:
    prob = MF.FEProblem(t, np.zeros(2), campaign="S5_init")
    X = np.vstack([pools[s][:CFG["bo"]["n_init"]] for s in SEEDS])
    Y, C, ok = prob.evaluate(X, seed=-1, round=0, method="init")
    Yf = Y[ok & (C[:, 0] <= 0)]
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def run_campaign(types: str, smoke: bool = False):
    out = json.loads(OUTF.read_text()) if OUTF.exists() and not smoke else {}
    nr = 1 if smoke else CFG["bo"]["n_rounds"]
    for t in types:
        pools = {s: MF.gated_pool(t, CFG["bo"]["n_candidates"][t], s) for s in SEEDS}
        ref = ref_point_for(t, pools)
        out.setdefault(t, {"ref_point": ref.tolist(), "pool_sizes": {str(s): len(p) for s, p in pools.items()}, "runs": {}})
        out[t]["ref_point"] = ref.tolist()
        for s in SEEDS:
            for m in ("qnehvi", "sobol"):
                key = f"{m}_{s}"
                if key in out[t]["runs"] and not smoke:
                    continue
                prob = MF.FEProblem(t, ref, campaign="test_S5" if smoke else "S5")
                recs, info = mobo.run(prob, method=m, seed=s, pool=pools[s], n_rounds=nr, noise_sd=MF.noise_sd())
                out[t]["runs"][key] = {"x": [r.x.tolist() for r in recs], "y": [r.y.tolist() for r in recs],
                                       "c": [r.c.tolist() for r in recs], "ok": [r.ok for r in recs],
                                       "round": [r.round for r in recs], "rows": prob.rows,
                                       "acq_s": info.get("timing", [])}
                if not smoke:
                    OUTF.write_text(json.dumps(out))
                print(f"{t} {key}: {len(recs)} evals, HV {mobo.hypervolume(np.array([r.y for r in recs if r.ok]), ref):.4g}",
                      flush=True)
    return out


# ------------------------------------------------------------------ plots（只读 CSV）
def plot_r5_f01(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        for m in ("qNEHVI", "Sobol"):
            seeds = sorted({d["seed"][i] for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m})
            curves = []
            for s in seeds:
                jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m and d["seed"][i] == s],
                            key=lambda i: d["n_fe"][i])
                x = [d["n_fe"][i] for i in jj]; y = [d["hv_ratio"][i] for i in jj]
                curves.append(y)
                if m == "qNEHVI":
                    ax.plot(x, y, color=ps.DORR[t], lw=0.7, alpha=0.5)
            med = np.median(np.array(curves), axis=0)
            st = dict(ps.METHOD[m]); st.setdefault("color", ps.DORR[t])
            ax.plot(x, med, label=f"{m} median ({len(seeds)} seeds)", **st)
        ps.threshold_line(ax, 0.9, "y", "0.9")
        ax.set_title(f"Dorr {t}"); ax.set_xlabel(ps.LABEL["n_fe"]); ax.set_ylim(0, 1.02)
    axes[0].set_ylabel(ps.LABEL["hv_ratio"]); axes[0].legend(loc="lower right")
    ps.panel_labels(axes)
    return fig


def plot_r5_f02(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        for m in ("qNEHVI", "Sobol"):
            seeds = sorted({d["seed"][i] for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m})
            curves = []
            for s in seeds:
                jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["method"][i] == m and d["seed"][i] == s],
                            key=lambda i: d["n_fe"][i])
                curves.append([d["igd"][i] for i in jj]); x = [d["n_fe"][i] for i in jj]
            st = dict(ps.METHOD[m]); st.setdefault("color", ps.DORR[t])
            ax.plot(x, np.median(np.array(curves), axis=0), label=f"{m} median", **st)
        ax.set_yscale("log"); ax.set_title(f"Dorr {t}"); ax.set_xlabel(ps.LABEL["n_fe"])
    axes[0].set_ylabel(ps.LABEL["igd"]); axes[0].legend(loc="upper right")
    ps.panel_labels(axes)
    return fig


def _front_axes(ax, t):
    ax.set_xscale("log"); ax.set_xlabel(ps.LABEL["f1"]); ax.set_title(f"Dorr {t}")


def plot_r5_f03(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 66, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        ref = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["kind"][i] == "reference"], key=lambda i: d["f1"][i])
        ax.step([d["f1"][i] for i in ref], [d["f2"][i] for i in ref], where="post", color="black", lw=1.0, label="reference front")
        for s, mk in zip(SEEDS, ("o", "s", "^")):
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["kind"][i] == f"bo_{s}"], key=lambda i: d["f1"][i])
            ax.plot([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], mk, ms=3, color=ps.DORR[t], alpha=0.8,
                    label=f"qNEHVI seed {s}")
        _front_axes(ax, t)
    axes[0].set_ylabel(ps.LABEL["f2"]); axes[0].legend(loc="upper right", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r5_f04(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 66, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        for kind, style in (("reference", dict(color="black", lw=1.0, ls="-")),
                            ("eaf_qNEHVI", dict(color=ps.DORR[t], lw=1.4, ls="-")),
                            ("eaf_Sobol", dict(color=ps.GREY, lw=1.2, ls="--"))):
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["kind"][i] == kind], key=lambda i: d["f1"][i])
            ax.step([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], where="post",
                    label=kind.replace("eaf_", "50 % attainment, "), **style)
        _front_axes(ax, t)
    axes[0].set_ylabel(ps.LABEL["f2"]); axes[0].legend(loc="upper right", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r5_f05(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 66, 1, 3, sharey=True)
    cmap = __import__("matplotlib").colormaps["plasma"]
    for ax, t in zip(axes, "ABC"):
        jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["kind"][i] == "proposal"]
        rr = [d["round"][i] for i in jj]
        sc = ax.scatter([d["tip_depth"][i] for i in jj], [d["w_prox"][i] for i in jj], c=rr, cmap=cmap, s=12,
                        vmin=0, vmax=CFG["bo"]["n_rounds"], edgecolors="none")
        kk = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["kind"][i] == "reference_front"]
        ax.scatter([d["tip_depth"][i] for i in kk], [d["w_prox"][i] for i in kk], marker="*", s=30, facecolors="none",
                   edgecolors="black", linewidths=0.6, label="reference-front designs")
        ax.set_title(f"Dorr {t}, seed 0"); ax.set_xlabel("Tip depth below LT (mm)")
    axes[0].set_ylabel(ps.LABEL["w_prox"]); axes[0].legend(loc="lower right", fontsize=6)
    fig.colorbar(sc, ax=axes, label="BO round (0 = initial design)", shrink=0.85)
    return fig


def plot_r5_f06(csv_path):
    d = ps.read_csv(csv_path)
    outs = list(dict.fromkeys(d["output"]))
    fig, axes = ps.new_figure("double", 66, 1, len(outs))
    for ax, o in zip(axes, outs):
        allv = []
        for t in "ABC":
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["output"][i] == o]
            yt = np.array([d["y_true"][i] for i in jj]); yp = np.array([d["y_pred"][i] for i in jj])
            lo = np.array([d["lo90"][i] for i in jj]); hi = np.array([d["hi90"][i] for i in jj])
            ax.errorbar(yt, yp, yerr=[yp - lo, hi - yp], fmt="none", ecolor=ps.DORR[t], alpha=0.25, elinewidth=0.5)
            ax.scatter(yt, yp, s=5, color=ps.DORR[t], edgecolors="none", label=f"Dorr {t}")
            allv += list(yt) + list(yp)
        lim = ps.shared_limits(allv)
        ax.plot(lim, lim, color="black", lw=0.8); ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel(f"FE {o}", fontsize=7); ax.set_ylabel(f"GP {o}", fontsize=7)
    axes[0].legend(loc="upper left", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r5_f07(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    outs = list(dict.fromkeys(d["output"]))
    for ax, t in zip(axes, "ABC"):
        ax.plot([0, 1], [0, 1], color="black", lw=0.8, label="ideal")
        ax.axhspan(0.80, 0.97, xmin=0.88, xmax=0.92, color="#E5E5E5")
        for o, ls in zip(outs, ("-", "--", ":")):
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["output"][i] == o], key=lambda i: d["nominal"][i])
            ax.plot([d["nominal"][i] for i in jj], [d["empirical"][i] for i in jj], ls, marker="o", ms=2.5,
                    color=ps.DORR[t], label=o)
        ax.set_title(f"Dorr {t}"); ax.set_xlabel(ps.LABEL["nominal"])
    axes[0].set_ylabel(ps.LABEL["empirical"]); axes[0].legend(loc="upper left", fontsize=6)
    ps.panel_labels(axes)
    return fig


def plot_r5_f08(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 72)
    for t in "ABC":
        jj = sorted([i for i, x in enumerate(d["dorr"]) if x == t], key=lambda i: d["f1"][i])
        ax.step([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], where="post", color=ps.DORR[t], lw=1.3)
        ax.scatter([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], s=12, color=ps.DORR[t], marker=ps.DORR_MARKER[t],
                   label=f"Dorr {t}", zorder=3)
    ax.set_xscale("log"); ax.set_xlabel(ps.LABEL["f1"]); ax.set_ylabel(ps.LABEL["f2"]); ax.legend(loc="upper right")
    return fig


def plot_r5_f09(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 66, 1, 2, sharey=True)
    for ax, t in zip(axes, "AC"):
        for grp, ls, lab in (("own", "-", "own cancellous modulus"), ("ctrl", "--", "cancellous 300 MPa")):
            jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["group"][i] == grp], key=lambda i: d["f1"][i])
            ax.step([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], where="post", color=ps.DORR[t], ls=ls, lw=1.3, label=lab)
        jj = sorted([i for i in range(len(d["dorr"])) if d["dorr"][i] == "B"], key=lambda i: d["f1"][i])
        ax.step([d["f1"][i] for i in jj], [d["f2"][i] for i in jj], where="post", color=ps.DORR["B"], lw=1.0, label="Dorr B (300 MPa)")
        _front_axes(ax, t)
        ax.legend(loc="upper right", fontsize=6)
    axes[0].set_ylabel(ps.LABEL["f2"])
    ps.panel_labels(axes)
    return fig


def plot_r5_f10(csv_path):
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import LogNorm
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 92, 1, 3)
    norm_ = LogNorm(vmin=0.3, vmax=300)
    for ax, t in zip(axes, "ABC"):
        jj = [i for i, x in enumerate(d["dorr"]) if x == t]
        polys = [[(d["x1"][i], d["z1"][i]), (d["x2"][i], d["z2"][i]), (d["x3"][i], d["z3"][i])] for i in jj]
        pc = PolyCollection(polys, array=np.clip([d["mises"][i] for i in jj], 0.3, 300), cmap="viridis", norm=norm_,
                            edgecolors="none")
        ax.add_collection(pc)
        ax.set_xlim(-40, 70); ax.set_ylim(-80, 92); ax.set_aspect("equal")
        ax.set_title(f"Dorr {t} knee: f1 {d['f1'][jj[0]]:.0f} µm, f2 {d['f2'][jj[0]]:.0f} %", fontsize=7)
    fig.colorbar(pc, ax=axes, shrink=0.8, label="von Mises (MPa, log), friction model under load")
    return fig


def plot_r5_f11(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 60, 1, 5)
    for ax, v in zip(axes, VARS):
        for k, t in enumerate("ABC"):
            jj = [i for i, x in enumerate(d["dorr"]) if x == t]
            vals = [d[v][i] for i in jj]
            xs = k + (np.random.default_rng(k).random(len(vals)) - 0.5) * 0.35
            ax.scatter(xs, vals, s=6, color=ps.DORR[t], alpha=0.7, edgecolors="none")
            if vals:
                ax.hlines(np.median(vals), k - 0.3, k + 0.3, color="black", lw=1.0)
        ax.set_xticks([0, 1, 2]); ax.set_xticklabels(["A", "B", "C"])
        ax.set_ylim(S.DS[v]["lo"], S.DS[v]["hi"]); ax.set_title(v, fontsize=7)
    axes[0].set_ylabel("Design variable value")
    return fig


def plot_r5_f12(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 66, 1, 2, sharey=True)
    for ax, q in zip(axes, ("log f1", "f2")):
        for t in "ABC":
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["objective"][i] == q]
            ax.scatter([d["ST"][i] for i in jj], [d["inv_ls_norm"][i] for i in jj], s=16, color=ps.DORR[t],
                       marker=ps.DORR_MARKER[t], label=f"Dorr {t}")
            for i in jj:
                ax.annotate(d["variable"][i], (d["ST"][i], d["inv_ls_norm"][i]), fontsize=5.5, xytext=(2, 1),
                            textcoords="offset points")
        ax.set_xlabel("Total Sobol index from R4 (–)"); ax.set_title(q)
    axes[0].set_ylabel("GP relevance 1/ℓ, normalised to max (–)"); axes[0].legend(loc="lower right", fontsize=6)
    ps.panel_labels(axes)
    return fig


# ------------------------------------------------------------------ 分析与发布
def knee(Y):
    Z = (Y - Y.min(0)) / np.where(Y.max(0) - Y.min(0) > 0, Y.max(0) - Y.min(0), 1)
    return int(np.argmin(np.linalg.norm(Z, axis=1)))


def publish(out):
    groups = group_rows()
    src = {"results": "results/S5_runs.json", "runs_csv": "campaign S5_* and S4_*"}
    hv_rows, igd_rows, front_rows, eaf_rows, prop_rows = [], [], [], [], []
    par_rows, cal_rows, t01, sil_f10, f11_rows, f12_rows, f8_rows, f9_rows = [], [], [], [], [], [], [], []
    ref_fronts, summary = {}, {}
    si = json.loads((ROOT / "results" / "S4_sobol_indices.json").read_text()) if (ROOT / "results" / "S4_sobol_indices.json").exists() else []
    for t in "ABC":
        R = out[t]
        ref = np.array(R["ref_point"])
        g = f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}"
        sweep = groups.get(g, [])
        allY, allrows = [], []
        for r in sweep:
            y, c, ok = RS.objectives(r)
            if ok and c <= 0:
                allY.append(y); allrows.append(r)
        for key, run in R["runs"].items():
            for y, c, ok in zip(run["y"], run["c"], run["ok"]):
                if ok and c[0] <= 0:
                    allY.append(y)
        allY = np.array(allY)
        rf = allY[mobo.pareto_mask(allY)]
        rf = rf[np.argsort(rf[:, 0])]
        ref_fronts[t] = rf
        hv_ref = mobo.hypervolume(rf, ref)
        scale = np.where(rf.max(0) - rf.min(0) > 0, rf.max(0) - rf.min(0), 1)
        fronts = {"qNEHVI": [], "Sobol": []}
        final = {"qNEHVI": [], "Sobol": []}
        for key, run in R["runs"].items():
            m = "qNEHVI" if key.startswith("qnehvi") else "Sobol"
            s = int(key.split("_")[1])
            Y = np.array(run["y"]); C = np.array(run["c"]); ok = np.array(run["ok"])
            feas = ok & (C[:, 0] <= 0)
            for n in range(CFG["bo"]["n_init"], len(Y) + 1, CFG["bo"]["q"]):
                Yn = Y[:n][feas[:n]]
                hv = mobo.hypervolume(Yn, ref)
                Fn = Yn[mobo.pareto_mask(Yn)] if len(Yn) else Yn
                hv_rows.append(dict(dorr=t, method=m, seed=s, n_fe=n, hv_ratio=hv / hv_ref))
                igd_rows.append(dict(dorr=t, method=m, seed=s, n_fe=n, igd=mobo.igd(Fn, rf, scale)))
            Yf = Y[feas]; Fr = Yf[mobo.pareto_mask(Yf)]
            fronts[m].append(Fr)
            final[m].append(mobo.hypervolume(Yf, ref) / hv_ref)
            if m == "qNEHVI":
                for y in Fr:
                    front_rows.append(dict(dorr=t, kind=f"bo_{s}", f1=10 ** y[0], f2=y[1]))
                if s == SEEDS[0]:
                    for x, rd in zip(run["x"], run["round"]):
                        prop_rows.append(dict(dorr=t, kind="proposal", round=rd, **S.to_physical(np.array(x))))
        for y in rf:
            front_rows.append(dict(dorr=t, kind="reference", f1=10 ** y[0], f2=y[1]))
            eaf_rows.append(dict(dorr=t, kind="reference", f1=10 ** y[0], f2=y[1]))
            f8_rows.append(dict(dorr=t, f1=10 ** y[0], f2=y[1]))
        grid = np.linspace(rf[:, 0].min() - 0.05, max(F_[:, 0].max() for F_ in fronts["qNEHVI"] + fronts["Sobol"]), 300)
        for m in ("qNEHVI", "Sobol"):
            e = mobo.attainment_surface(fronts[m], grid, 0.5)
            for gx, v in zip(grid, e):
                if np.isfinite(v):
                    eaf_rows.append(dict(dorr=t, kind=f"eaf_{m}", f1=10 ** gx, f2=v))
        # 参考前沿设计（F05 星号、F11）
        for r in allrows:
            y, _, _ = RS.objectives(r)
            if any(np.allclose(y, z) for z in rf):
                d_ = {v: EV.as_float(r, v) for v in VARS}
                prop_rows.append(dict(dorr=t, kind="reference_front", round="", **d_))
                f11_rows.append(dict(dorr=t, **d_))
        sob_med = float(np.median(final["Sobol"]))
        summary[t] = {"bo_final": final["qNEHVI"], "sobol_final": final["Sobol"], "sobol_median": sob_med,
                      "hv_ref": hv_ref, "n_ref_front": len(rf)}
        # ---- 代理诊断：每个 BO 种子的最终 GP 在 R4 扫描设计上
        test = [r for r in sweep if r["status"] == "OK"]
        Xte = np.array([S.to_unit({v: EV.as_float(r, v) for v in VARS}) for r in test])
        Yte = np.array([[math.log10(EV.as_float(r, "f1_p95_um")), EV.as_float(r, "f2_g7_loss_pct"), EV.as_float(r, "vm_p99")]
                        for r in test])
        train_keys = {row.get("cache_key") for key, run in R["runs"].items() if key.startswith("qnehvi") for row in run["rows"]}
        test_keys = {r.get("cache_key") for r in test}
        overlap = len(train_keys & test_keys)
        noise = MF.noise_sd()
        for key, run in R["runs"].items():
            if not key.startswith("qnehvi"):
                continue
            s = int(key.split("_")[1])
            ok = np.array(run["ok"])
            Xtr = np.array(run["x"])[ok]
            Ytr = np.c_[np.array(run["y"])[ok], np.array(run["c"])[ok][:, 0] + CFG["qoi"]["stem_vm_limit"]]
            for j, oname in enumerate(("log10 f1", "f2 (%)", "vm P99 (MPa)")):
                sd = float(np.std(Ytr[:, j])) or 1.0
                gp = mobo.fit_gp(torch.as_tensor(Xtr), torch.as_tensor(Ytr[:, j]), max(1e-6, (noise[j] / sd) ** 2))
                with torch.no_grad():
                    post = gp.posterior(torch.as_tensor(Xte), observation_noise=True)
                mu = post.mean.numpy().ravel(); sig = post.variance.clamp_min(1e-12).sqrt().numpy().ravel()
                yt = Yte[:, j]
                z90 = norm.ppf(0.95)
                cover90 = float(np.mean(np.abs(yt - mu) <= z90 * sig))
                r2 = 1 - np.sum((yt - mu) ** 2) / np.sum((yt - yt.mean()) ** 2)
                rho = float(spearmanr(yt, mu)[0])
                sharp = float(np.mean(2 * z90 * sig) / (np.std(yt) or 1))
                t01.append(dict(dorr=t, seed=s, output=oname, n_train=len(Xtr), n_test=len(Xte), R2=r2, spearman=rho,
                                coverage90=cover90, sharpness=sharp, leakage_overlap=overlap))
                if s == SEEDS[0]:
                    for a, b, c_ in zip(yt, mu, sig):
                        par_rows.append(dict(dorr=t, output=oname, y_true=a, y_pred=b, lo90=b - z90 * c_, hi90=b + z90 * c_))
                    for p in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
                        zq = norm.ppf(0.5 + p / 2)
                        cal_rows.append(dict(dorr=t, output=oname, nominal=p, empirical=float(np.mean(np.abs(yt - mu) <= zq * sig))))
                if j < 2 and s == SEEDS[0]:
                    ls = gp.covar_module.base_kernel.lengthscale.detach().numpy().ravel()
                    inv = 1 / ls
                    q = "log f1" if j == 0 else "f2"
                    for v, w in zip(VARS, inv / inv.max()):
                        st_ = next((x["ST"] for x in si if x["dorr"] == t and x["objective"] == q and x["variable"] == v), float("nan"))
                        f12_rows.append(dict(dorr=t, objective=q, variable=v, inv_ls_norm=w, ST=st_))
        summary[t]["overlap"] = overlap
        # ---- 膝点设计的场
        kidx = knee(rf)
        kn = None
        for r in allrows:
            y, _, _ = RS.objectives(r)
            if np.allclose(y, rf[kidx]):
                kn = r
                break
        if kn is not None:
            import qoi
            from stage_s2 import load_mesh_polys
            rd = ROOT / "runs" / kn["design_id"]
            s_ = qoi._csv(rd / f"{kn['design_id']}_fric_csv" / "LOAD_S.csv")
            mis = dict(zip(s_["elem"].astype(int), s_["mises"]))
            for reg, el, tri in load_mesh_polys(rd):
                if reg == "cavity" or el not in mis or tri[:, 1].min() < -85:
                    continue
                sil_f10.append(dict(dorr=t, x1=tri[0, 0], z1=tri[0, 1], x2=tri[1, 0], z2=tri[1, 1], x3=tri[2, 0], z3=tri[2, 1],
                                    mises=mis[el], f1=10 ** rf[kidx, 0], f2=rf[kidx, 1], design_id=kn["design_id"]))
    # 对照前沿
    for t in "AC":
        for grp, key in (("own", f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}"), ("ctrl", f"{t}_ctrl300")):
            ys, _, m = _front(groups.get(key, []))
            for y in ys[m]:
                f9_rows.append(dict(dorr=t, group=grp, f1=10 ** y[0], f2=y[1]))
    for y in ref_fronts["B"]:
        f9_rows.append(dict(dorr="B", group="own", f1=10 ** y[0], f2=y[1]))

    med = {t: float(np.median(summary[t]["bo_final"])) for t in "ABC"}
    # ---- 标题所需的数据驱动量
    EN = ps.VAR_EN
    igd_fin = {}
    for t in "ABC":
        for m in ("qNEHVI", "Sobol"):
            v = [r["igd"] for r in igd_rows if r["dorr"] == t and r["method"] == m
                 and r["n_fe"] == max(x["n_fe"] for x in igd_rows if x["dorr"] == t and x["method"] == m)]
            igd_fin[(t, m)] = float(np.median(v))
    on_front = []
    for t in "ABC":
        rf = ref_fronts[t]
        for r in front_rows:
            if r["dorr"] == t and r["kind"].startswith("bo_"):
                y = np.array([np.log10(r["f1"]), r["f2"]])
                on_front.append(bool(np.any(np.all(np.abs(rf - y) < 1e-9, axis=1))))
    frac_on = float(np.mean(on_front)) if on_front else float("nan")
    eaf_dom = {}
    for t in "ABC":
        eb = sorted([(r["f1"], r["f2"]) for r in eaf_rows if r["dorr"] == t and r["kind"] == "eaf_qNEHVI"])
        es = sorted([(r["f1"], r["f2"]) for r in eaf_rows if r["dorr"] == t and r["kind"] == "eaf_Sobol"])
        if eb and es:
            xs = np.array([a for a, _ in es]); ys_ = np.array([b for _, b in es])
            vals = []
            for a, b in eb:
                j = np.searchsorted(xs, a, side="right") - 1
                if j >= 0:
                    vals.append(b <= ys_[j] + 1e-9)
            eaf_dom[t] = float(np.mean(vals)) if vals else float("nan")
    def _u(r):
        return S.to_unit({v: r[v] for v in VARS})
    dist_first, dist_last = [], []
    for t in "ABC":
        refd = np.array([_u(r) for r in prop_rows if r["dorr"] == t and r["kind"] == "reference_front"])
        if not len(refd):
            continue
        for r in prop_rows:
            if r["dorr"] == t and r["kind"] == "proposal":
                dmin = float(np.min(np.linalg.norm(refd - _u(r), axis=1)))
                if r["round"] == 0:
                    dist_first.append(dmin)
                elif r["round"] >= CFG["bo"]["n_rounds"] - 2:
                    dist_last.append(dmin)
    r2 = {o: float(np.mean([r["R2"] for r in t01 if r["output"] == o and r["seed"] == SEEDS[0]])) for o in dict.fromkeys(r["output"] for r in t01)}
    cov_all = [r["coverage90"] for r in t01 if r["output"] != "vm P99 (MPa)"]
    fmin = {t: (min(r["f1"] for r in f8_rows if r["dorr"] == t), min(r["f2"] for r in f8_rows if r["dorr"] == t)) for t in "ABC"}
    ctrl = {}
    for t in "AC":
        for grp in ("own", "ctrl"):
            v = [r["f1"] for r in f9_rows if r["dorr"] == t and r["group"] == grp]
            ctrl[(t, grp)] = min(v) if v else float("nan")
    kn = {t: next(((r["f1"], r["f2"]) for r in sil_f10 if r["dorr"] == t), (float("nan"), float("nan"))) for t in "ABC"}
    spread = {}
    for v in VARS:
        meds = [np.median([S.to_unit({k: r[k] for k in VARS})[VARS.index(v)] for r in f11_rows if r["dorr"] == t] or [np.nan]) for t in "ABC"]
        spread[v] = (np.nanmax(meds) - np.nanmin(meds), meds)
    vmax = max(spread, key=lambda v: spread[v][0])
    from scipy.stats import spearmanr as _sp
    rho12 = float(_sp([r["ST"] for r in f12_rows], [r["inv_ls_norm"] for r in f12_rows])[0]) if len(f12_rows) > 3 else float("nan")
    ps.publish_figure("R5-F01", hv_rows, plot_r5_f01, sources=src,
                      title=("BO reaches a median HV ratio of " + " / ".join(f"{med[t]:.2f}" for t in "ABC") +
                             " (A / B / C) within 60 FE runs"),
                      caption=("HV 比 = 已评估可行设计的超体积 / 参考前沿超体积（参考前沿 = R4 扫描 + R5 全部评估的可行非支配集），"
                               "目标空间 (log10 f1, f2)，参考点每型固定。细线为单个 BO 种子，粗实线为 BO 中位，虚线为同预算 Sobol 中位。"))
    ps.publish_figure("R5-F02", igd_rows, plot_r5_f02, sources=src,
                      title=("Median final IGD: BO " + " / ".join(f"{igd_fin[(t, 'qNEHVI')]:.3f}" for t in "ABC")
                             + " vs Sobol " + " / ".join(f"{igd_fin[(t, 'Sobol')]:.3f}" for t in "ABC") + " (A / B / C)"),
                      caption="IGD：参考前沿每点到已评估可行非支配集最近点的平均距离（按参考前沿范围归一化），三个种子的中位。")
    ps.publish_figure("R5-F03", front_rows, plot_r5_f03, sources=src,
                      title=f"{frac_on:.0%} of the final BO non-dominated points are members of the reference front",
                      caption="黑线为参考前沿；彩色标记为各 BO 种子 60 次评估后的可行非支配点。")
    ps.publish_figure("R5-F04", eaf_rows, plot_r5_f04, sources=src,
                      title=("BO's 50 % attainment surface is at or below Sobol's on "
                             + " / ".join(f"{eaf_dom.get(t, float('nan')):.0%}" for t in "ABC") + " of the grid (A / B / C)"),
                      caption="经验达成函数 50 % 等值线（三个种子中至少两个达到的区域边界）。")
    ps.publish_figure("R5-F05", prop_rows, plot_r5_f05, sources=src,
                      title=(f"Mean distance from BO designs to the nearest reference-front design: {np.mean(dist_first):.2f} "
                             f"in the initial design, {np.mean(dist_last):.2f} in the last three rounds (unit cube, seed 0)"),
                      caption="种子 0 的全部评估点在 (尖端深度, 近端半宽) 平面上的位置，颜色为轮次；黑星为参考前沿设计。")
    ps.publish_figure("R5-F06", par_rows, plot_r5_f06, sources=src,
                      title=("Held-out R² of the seed-0 GPs: " + ", ".join(f"{o.split(' (')[0]} {v:.2f}" for o, v in r2.items())),
                      caption="种子 0 最终 GP（60 个 BO 设计训练）在 R4 参考扫描设计上的预测（含观测噪声的 90 % 区间）对 FE 真值。测试集与训练集按 cache_key 不重叠。")
    ps.publish_figure("R5-F07", cal_rows, plot_r5_f07, sources=src,
                      title=(f"Empirical 90 % coverage ranges {min(cov_all):.2f}–{max(cov_all):.2f} across types, seeds and objectives "
                             "(acceptance 0.80–0.97)"),
                      caption="校准曲线（Kuleshov 2018）：名义中心区间覆盖率对实际覆盖率；灰色小带为 90 % 名义处的 0.80–0.97 验收带。")
    ps.publish_figure("R5-F08", f8_rows, plot_r5_f08, sources=src,
                      title=("Lowest micromotion " + " / ".join(f"{fmin[t][0]:.1f}" for t in "ABC") + " µm and lowest shielding "
                             + " / ".join(f"{fmin[t][1]:.0f}" for t in "ABC") + " % on the reference fronts (A / B / C)"),
                      caption="各型参考前沿（R4 + R5 可行非支配集），共用坐标。")
    ps.publish_figure("R5-F09", f9_rows, plot_r5_f09, sources=src,
                      title=(f"With cancellous bone at 300 MPa the lowest micromotion changes from {ctrl[('A', 'own')]:.1f} to "
                             f"{ctrl[('A', 'ctrl')]:.1f} µm in Dorr A and from {ctrl[('C', 'own')]:.1f} to {ctrl[('C', 'ctrl')]:.1f} µm in Dorr C"),
                      caption="实线为本型松质骨模量（A 400 / C 150 MPa），虚线为 300 MPa 对照（同一尝试序列的 R4 扫描），B 型（300 MPa）为参照。")
    if sil_f10:
        ps.publish_figure("R5-F10", sil_f10, plot_r5_f10, sources=src,
                          title=("Knee-point designs: f1 " + " / ".join(f"{kn[t][0]:.1f}" for t in "ABC") + " µm, f2 "
                                 + " / ".join(f"{kn[t][1]:.0f}" for t in "ABC") + " % (A / B / C)"),
                          caption="各型参考前沿的膝点（归一化后离理想点最近）设计：摩擦模型加载步 von Mises 应力（对数色标）。")
    ps.publish_figure("R5-F11", f11_rows, plot_r5_f11, sources=src,
                      title=(f"Front designs differ most between Dorr types in {EN[vmax]} (normalised medians "
                             + " / ".join(f"{x:.2f}" for x in spread[vmax][1]) + ", A / B / C)"),
                      caption="各型参考前沿设计的五个设计变量取值（抖动散点），黑线为中位；纵轴为各变量的完整范围。")
    if f12_rows:
        ps.publish_figure("R5-F12", f12_rows, plot_r5_f12, sources=src,
                          title=f"GP relevance and R4 total Sobol indices agree with Spearman ρ = {rho12:.2f}",
                          caption="种子 0 最终 GP 的 ARD 长度尺度倒数（归一化到最大值）对 R4 的总效应 Sobol 指数。")
    ps.publish_table("R5-T01", t01, title="代理指标（每型、每种子、每个输出）与泄漏检查",
                     caption="训练集 = 该种子 BO 的 60 个设计；测试集 = R4 参考扫描的 FE 成功设计。锐度 = 平均 90 % 区间宽度 / 测试集标准差。")
    # 成本账本
    runs = {r["design_id"]: r for r in EV.read_runs()}
    t02 = []
    for t in "ABC":
        g = f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}"
        sweep_h = sum(EV.as_float(r, "t_total_s") for r in groups.get(g, []) if r["status"] == "OK") / 3600
        for m in ("qnehvi", "sobol"):
            ids = {row["design_id"] for key, run in out[t]["runs"].items() if key.startswith(m) for row in run["rows"]}
            h = sum(EV.as_float(runs[i], "t_total_s") for i in ids if i in runs and not math.isnan(EV.as_float(runs[i], "t_total_s"))) / 3600
            acq = sum(sum(run["acq_s"]) for key, run in out[t]["runs"].items() if key.startswith(m)) / 3600
            t02.append(dict(dorr=t, method=m, fe_designs_3_seeds=len(ids), fe_machine_h=h, acquisition_h=acq,
                            reference_sweep_machine_h=sweep_h, fe_saving_vs_sweep_pct=100 * (1 - h / 3 / sweep_h) if sweep_h else float("nan")))
    ps.publish_table("R5-T02", t02, title="成本账本", caption="机时为单设计墙钟之和（4 个设计并行）；节省比按单个种子（60 次）对参考扫描计算。")
    t03 = [dict(item="config.yaml sha256", value=ps.sha256_file(ps.CONFIG_PATH)),
           dict(item="seeds", value=str(SEEDS)), dict(item="candidate pools", value="results/pools/*.npy"),
           dict(item="BO records", value="results/S5_runs.json"), dict(item="runs.csv campaigns", value="S5_init, S5_qnehvi, S5_sobol, S4_ref, S4_control"),
           dict(item="noise floor", value="results/noise_floor.json"),
           dict(item="scripts", value="; ".join(f"{p}: {ps.sha256_file(ROOT / p)[:8]}" for p in
                                               ("mobo.py", "mobo_fe.py", "evaluate.py", "fe_model.py", "qoi.py", "stage_s5.py")))]
    ps.publish_table("R5-T03", t03, title="可复现包清单")
    # 验收
    cov = {t: [r["coverage90"] for r in t01 if r["dorr"] == t and r["output"] != "vm P99 (MPa)"] for t in "ABC"}
    a1 = all(med[t] >= 0.90 for t in "ABC")
    a2 = all(all(v > summary[t]["sobol_median"] for v in summary[t]["bo_final"]) for t in "ABC")
    cov_ok = all(0.80 <= min(v) and max(v) <= 0.97 for v in cov.values() if v)
    ov = sum(summary[t]["overlap"] for t in "ABC")
    ps.publish_acceptance("R5", [
        {"id": "R5-A1", "measured": "；".join(f"{t} {med[t]:.3f}" for t in "ABC"), "status": "PASS" if a1 else "FAIL",
         "note": "" if a1 else "未达 0.90 的型别见 R5-F01"},
        {"id": "R5-A2", "measured": "；".join(f"{t} {sum(v > summary[t]['sobol_median'] for v in summary[t]['bo_final'])}/3" for t in "ABC"),
         "status": "PASS" if a2 else "FAIL", "note": "" if a2 else "个别种子未胜过 Sobol 中位"},
        {"id": "R5-A3", "measured": "；".join(f"{t} {min(v):.2f}–{max(v):.2f}" for t, v in cov.items() if v),
         "status": "PASS" if cov_ok else "FAIL", "note": "" if cov_ok else "区间偏窄或偏宽，见 R5-F07"},
        {"id": "R5-A4", "measured": f"重叠 {ov}", "status": "PASS" if ov == 0 else "FAIL", "note": ""},
    ])
    ps.publish_inputs("R5", ref_points={t: out[t]["ref_point"] for t in "ABC"}, pool_sizes={t: out[t]["pool_sizes"] for t in "ABC"},
                      noise_sd=MF.noise_sd())
    json.dump(summary, open(ROOT / "results" / "S5_summary.json", "w"), indent=1, default=float)
    tx = ps.report_dir("R5") / "text"
    save = {r["dorr"]: r["fe_saving_vs_sweep_pct"] for r in t02 if r["method"] == "qnehvi"}
    tx.joinpath("summary.md").write_text(
        "BO（GP + qLogNEHVI，q = 4，12 + 12×4 = 60 次 FE）在三型上的最终 HV 比中位为 "
        + "、".join(f"{t} {med[t]:.3f}" for t in "ABC") + "（参考前沿 = R4 + R5 全部可行评估的非支配集），同预算 Sobol 中位为 "
        + "、".join(f"{t} {summary[t]['sobol_median']:.3f}" for t in "ABC") + "。"
        + f"验收：HV 比 ≥ 0.90 {'全部通过' if a1 else '未全部通过'}；三个种子都胜过 Sobol {'是' if a2 else '否'}；"
        + f"GP 90 % 区间覆盖率 {'在' if cov_ok else '不在'} 0.80–0.97 内；训练与测试集重叠 {ov}。"
        + "单个种子相对 256 点参考扫描节省 FE 机时 " + "、".join(f"{t} {v:.0f} %" for t, v in save.items()) + "。",
        encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**问题**：每型独立的双目标最小化，y1 = log10(P95 微动 µm)，y2 = Gruen 7 SED 下降率（%），约束 vm P99 ≤ 440 MPa。"
        "设计变量 5 个（R1-T02），候选池为每个种子一个打乱 Sobol 序列（A、B 型 20,000 点，C 型 40,000 点，按 R1-A4 处置）中过几何门者（保持序列顺序）。\n\n"
        "**BO**：`mobo.run`，初始设计 = 池的前 12 点；每轮为两个目标与约束各拟合一个 SingleTaskGP（ARD Matérn 5/2，"
        "Gamma(3, 6) 长度尺度先验，输入归一化、输出标准化，观测噪声下界来自 R2 噪声底），qLogNEHVI（128 个 QMC 样本，"
        "参考点每型固定）在未评估候选点上序贯贪心选 4 个；共 12 轮。Sobol 基线取池的前 60 点（与 BO 共享前 12 点）。\n\n"
        "**参考点**：三个种子的初始 12 点合并，可行者各目标最大值 + 10 % 极差。**参考前沿**：该型 R4 扫描 + R5 全部 FE 评估的可行非支配集。"
        "**代理诊断**：每个 BO 种子最终 60 点训练的 GP 在 R4 扫描设计（测试集，与训练集按 cache_key 无重叠）上预测，"
        "含观测噪声的预测区间；R²、Spearman、90 % 覆盖率、锐度（平均区间宽 / 测试集标准差），校准曲线按 Kuleshov 2018。",
        encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 所有结论只对本 2D 模型（含侧板假设与生产网格）成立；f1 绝对值因网格未收敛而偏低（R2），排序一致。\n"
        "- 参考前沿由有限样本得到，不是真前沿；HV 比可能略高估。\n"
        "- 每型只 3 个种子，中位与\"全部胜过\"判定的统计力有限。\n"
        "- 未做跨分型稳健优化（按用户选择）。", encoding="utf-8")
    print(json.dumps({t: {"median": med[t], "sobol": summary[t]["sobol_median"]} for t in "ABC"}, indent=1))


def _front(rows):
    ys, idx = [], []
    for i, r in enumerate(rows):
        y, c, ok = RS.objectives(r)
        if ok and c <= 0:
            ys.append(y); idx.append(i)
    ys = np.array(ys)
    return ys, np.array(idx), (mobo.pareto_mask(ys) if len(ys) else np.zeros(0, bool))


if __name__ == "__main__":
    types = next((a.split("=")[1] for a in sys.argv if a.startswith("--types=")), "ABC")
    if "--smoke" in sys.argv:
        run_campaign(types[:1], smoke=True)
        print("smoke OK")
    elif "--replot" in sys.argv:
        publish(json.loads(OUTF.read_text()))
    else:
        publish(run_campaign(types))
