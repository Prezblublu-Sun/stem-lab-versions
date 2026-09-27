"""S4 参考扫描（真前沿）→ R4 报告。python stage_s4.py [--n 256] [--smoke]（.venv-mobo）

每型（A、B、C，及 A、C 的 300 MPa 对照）逐个 Sobol 尝试直到 n 个设计过几何门，全部跑 FE。
前沿点少于 15 个时把该型加到 512。--smoke 只跑 n = 6 检查代码路径（campaign 前缀 test_）。
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

import evaluate as EV
import femur2d as F
import mobo
import plotstyle as ps
import reference_sweep as RS
import stem2d as S
from stage_s1 import CORTEX_FC, CANC_FC, draw, poly_rows, sel

ROOT = ps.ROOT
CFG = F.CFG
VARS = S.VARS
STATUS_ORDER = ["OK", "L1", "L2", "L3", "L4", "L5"]


def front_of(rows):
    ys, idx = [], []
    for i, r in enumerate(rows):
        y, c, ok = RS.objectives(r)
        if ok and c <= 0:
            ys.append(y); idx.append(i)
    ys = np.array(ys)
    m = mobo.pareto_mask(ys) if len(ys) else np.zeros(0, bool)
    return ys, np.array(idx), m


def sobol_indices_gp(X, y, n_base=4096, seed=0):
    """GP 后验均值上的 Saltelli/Jansen 估计：一阶 S_i 与总效应 ST_i（单位立方体上均匀分布）。"""
    import torch
    gp = mobo.fit_gp(torch.as_tensor(X), torch.as_tensor(y))
    rng = np.random.default_rng(seed)
    A, B = rng.random((n_base, X.shape[1])), rng.random((n_base, X.shape[1]))

    def f(Z):
        with torch.no_grad():
            return gp.posterior(torch.as_tensor(Z)).mean.numpy().ravel()
    fA, fB = f(A), f(B)
    V = np.var(np.r_[fA, fB])
    S1, ST = [], []
    for i in range(X.shape[1]):
        ABi = A.copy(); ABi[:, i] = B[:, i]
        fABi = f(ABi)
        S1.append(np.mean(fB * (fABi - fA)) / V)          # Saltelli 2010
        ST.append(0.5 * np.mean((fA - fABi) ** 2) / V)    # Jansen 1999
    ls = gp.covar_module.base_kernel.lengthscale.detach().numpy().ravel()
    return np.array(S1), np.array(ST), ls


# ------------------------------------------------------------------ plots（只读 CSV）
def plot_r4_f01(csv_path):
    d = ps.read_csv(csv_path)
    groups = list(dict.fromkeys(d["group"]))
    fig, axes = ps.new_figure("double", 66, 1, len(groups), sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    for ax, g in zip(axes, groups):
        t = g[0]
        jj = [i for i in range(len(d["group"])) if d["group"][i] == g]
        feas = [i for i in jj if d["feasible"][i] == 1]
        inf = [i for i in jj if d["feasible"][i] == 0]
        ax.scatter([d["f1"][i] for i in feas], [d["f2"][i] for i in feas], s=5, color=ps.DORR[t], alpha=0.35,
                   edgecolors="none", label="feasible")
        if inf:
            ax.scatter([d["f1"][i] for i in inf], [d["f2"][i] for i in inf], s=8, marker="x", color=ps.GREY, lw=0.6,
                       label="stress constraint violated")
        fr = sorted([i for i in feas if d["front"][i] == 1], key=lambda i: d["f1"][i])
        ax.step([d["f1"][i] for i in fr], [d["f2"][i] for i in fr], where="post", color=ps.DORR[t], lw=1.2)
        ax.scatter([d["f1"][i] for i in fr], [d["f2"][i] for i in fr], s=14, color=ps.DORR[t], marker=ps.DORR_MARKER[t],
                   edgecolors="black", linewidths=0.4, zorder=3, label=f"reference front (n = {len(fr)})")
        ax.set_xscale("log"); ax.set_title(g.replace("_", " ")); ax.set_xlabel(ps.LABEL["f1"])
        ps.plain_log(ax, "x")
        if max(d["f1"][i] for i in jj) > 40:
            ps.threshold_line(ax, 50, "x", "50 µm")
        ax.legend(loc="upper right", fontsize=6)
    axes[0].set_ylabel(ps.LABEL["f2"])
    ps.panel_labels(list(axes))
    return fig


def plot_r4_f02(csv_path):
    d = ps.read_csv(csv_path)
    cols = VARS + ["log_f1", "f2"]
    fig, axes = ps.new_figure("double", 70, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        jj = [i for i, x in enumerate(d["dorr"]) if x == t]
        if not jj:
            continue
        vals = np.array([[d[c][i] for c in cols] for i in jj], float)
        lo, hi = vals.min(0), vals.max(0)
        for k in (5, 6):
            lo[k], hi[k] = min(lo[k], hi[k] - 1e-9), hi[k]
        for k in range(5):
            lo[k], hi[k] = S.DS[VARS[k]]["lo"], S.DS[VARS[k]]["hi"]
        z = (vals - lo) / np.where(hi - lo > 0, hi - lo, 1)
        order = np.argsort(vals[:, 5])
        cmap = __import__("matplotlib").colormaps["viridis"]
        for r, i in enumerate(order):
            ax.plot(range(len(cols)), z[i], color=cmap(r / max(len(order) - 1, 1)), lw=0.8, alpha=0.9)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(["tip depth", "tip lat.", "w_prox", "taper", "θ_in", "log f1", "f2"], rotation=35, fontsize=6.5)
        ax.set_title(f"Dorr {t} front (n = {len(jj)}), colour = f1 rank", fontsize=7)
    axes[0].set_ylabel("Normalised value (–)")
    return fig


def plot_r4_f03(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 90, 2, 5, sharey="row")
    for c, v in enumerate(VARS):
        for r, (q, lab) in enumerate((("f1", ps.LABEL["f1"]), ("f2", ps.LABEL["f2"]))):
            ax = axes[r, c]
            for t in "ABC":
                jj = [i for i, x in enumerate(d["dorr"]) if x == t]
                ax.scatter([d[v][i] for i in jj], [d[q][i] for i in jj], s=3, color=ps.DORR[t], alpha=0.5,
                           edgecolors="none", label=f"Dorr {t}")
            if q == "f1":
                ax.set_yscale("log"); ps.plain_log(ax, "y")
            if r == 1:
                ax.set_xlabel(v, fontsize=7)
            if c == 0:
                ax.set_ylabel(lab, fontsize=7)
    axes[0, 0].legend(loc="upper left", fontsize=6, markerscale=3)
    return fig


def plot_r4_f04(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 2, sharey=True)
    for ax, q in zip(axes, ("log f1", "f2")):
        for k, t in enumerate("ABC"):
            jj = [i for i in range(len(d["dorr"])) if d["dorr"][i] == t and d["objective"][i] == q]
            x = np.arange(len(jj)) + (k - 1) * 0.27
            ax.bar(x, [d["ST"][i] for i in jj], width=0.25, color=ps.DORR[t], alpha=0.45, label=f"Dorr {t} total")
            ax.bar(x, [d["S1"][i] for i in jj], width=0.25, color=ps.DORR[t], label=f"Dorr {t} first-order")
        ax.set_xticks(range(len(VARS))); ax.set_xticklabels(VARS, rotation=20, fontsize=6.5)
        ax.set_title(f"Sobol indices of {q}")
    axes[0].set_ylabel("Sobol index (–)")
    axes[1].legend(loc="upper right", fontsize=5.5, ncol=2)
    ps.panel_labels(axes)
    return fig


def plot_r4_f05(csv_path):
    d = ps.read_csv(csv_path)
    pairs = [("tip_depth", "tip_lat"), ("w_prox", "taper"), ("tip_depth", "theta_in")]
    fig, axes = ps.new_figure("double", 130, 3, 3)
    for r, t in enumerate("ABC"):
        jj = [i for i, x in enumerate(d["dorr"]) if x == t]
        for c, (vx, vy) in enumerate(pairs):
            ax = axes[r, c]
            for stt in STATUS_ORDER:
                kk = [i for i in jj if d["status"][i] == stt]
                if kk:
                    ax.scatter([d[vx][i] for i in kk], [d[vy][i] for i in kk], s=4 if stt == "OK" else 9,
                               color=ps.STATUS[stt] if stt != "OK" else ps.DORR[t], alpha=0.5 if stt == "OK" else 0.9,
                               marker="o" if stt in ("OK", "L1", "L2") else "X", edgecolors="none",
                               label=f"{stt} ({len(kk)})")
            ax.set_xlabel(vx, fontsize=6.5); ax.set_ylabel(vy, fontsize=6.5)
        axes[r, 2].legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=6, title=f"Dorr {t}", title_fontsize=6.5)
    return fig


def plot_r4_f06(csv_path):
    d = ps.read_csv(csv_path)
    n = int(max(d["rank"])) + 1
    fig, axes = ps.new_figure("double", 100, 3, n)
    for r, t in enumerate("ABC"):
        for c in range(n):
            ax = axes[r, c]
            draw(ax, d, sel(d, dorr=t, part="outer", rank=0.0), fc=CORTEX_FC)
            draw(ax, d, sel(d, dorr=t, part="inner", rank=0.0), fc=CANC_FC)
            idx = sel(d, dorr=t, part="stem", rank=float(c))
            if idx:
                draw(ax, d, idx, fc=ps.DORR[t], ec=ps.DORR[t], alpha=0.85, z=3)
                ax.set_title(f"f1 {d['f1'][idx[0]]:.0f} µm\nf2 {d['f2'][idx[0]]:.0f} %", fontsize=5.5)
            ax.set_xlim(-40, 70); ax.set_ylim(-80, 92); ax.set_aspect("equal")
            ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
            for sp in ax.spines.values():
                sp.set_visible(False)
        axes[r, 0].set_ylabel(f"Dorr {t}")
    return fig


# ------------------------------------------------------------------ main
def main():
    smoke = "--smoke" in sys.argv
    n = 6 if smoke else int(next((a.split("=")[1] for a in sys.argv if a.startswith("--n=")), CFG["bo"]["reference_n"]))
    pref = "test_" if smoke else ""
    groups = [("A", None), ("B", None), ("C", None), ("A", 300.0), ("C", 300.0)]
    results, attempts_n = {}, {}
    for t, E in groups:
        g = f"{t}_E{int(CFG['dorr'][t]['E_cancellous'])}" if E is None else f"{t}_ctrl{int(E)}"
        nn = n
        while True:
            rows = RS.run(t, nn, E, campaign=f"{pref}S4_ref" if E is None else f"{pref}S4_control")
            ys, idx, m = front_of(rows)
            if smoke or m.sum() >= CFG["bo"]["min_front_points"] or nn >= CFG["bo"]["reference_n_max"] or E is not None:
                break
            nn = CFG["bo"]["reference_n_max"]
        results[g] = rows
        attempts_n[g] = len(rows)
        print(g, "attempts", len(rows), "FE OK", sum(r["status"] == "OK" for r in rows), "front", int(m.sum()), flush=True)
    json.dump({g: [r["design_id"] for r in rows] for g, rows in results.items()},
              open(ROOT / "results" / f"{pref}S4_groups.json", "w"), indent=1)
    if smoke:
        print("smoke OK")
        return
    publish(results, attempts_n)


def publish(results, attempts_n):
    src = {"runs_csv": "campaign S4_ref / S4_control", "sweep_seed": RS.SWEEP_SEED}
    obj_rows, front_rows, var_rows, fail_rows, t01 = [], [], [], [], []
    fronts = {}
    for g, rows in results.items():
        t = g[0]
        ys, idx, m = front_of(rows)
        fronts[g] = (ys[m], [rows[i] for i in idx[m]])
        for k, i in enumerate(idx):
            r = rows[i]
            y, c, ok = RS.objectives(r)
            obj_rows.append(dict(group=g, dorr=t, f1=10 ** y[0], f2=y[1], feasible=int(c <= 0), front=int(m[k])))
        for r in rows:
            fail_rows.append(dict(group=g, dorr=t, status=r["status"], **{v: EV.as_float(r, v) for v in VARS}))
            if r["status"] == "OK" and "ctrl" not in g:
                var_rows.append(dict(dorr=t, **{v: EV.as_float(r, v) for v in VARS}, f1=EV.as_float(r, "f1_p95_um"),
                                     f2=EV.as_float(r, "f2_g7_loss_pct")))
    main_groups = [g for g in results if "ctrl" not in g]
    from scipy.stats import spearmanr
    EN = ps.VAR_EN

    def top_corr(rows_by_type, target, n=2):
        """每型内 Spearman ρ（变量对 target）的三型平均，按 |ρ| 取前 n 个。"""
        acc = {v: [] for v in VARS}
        for rows in rows_by_type.values():
            if len(rows) < 4:
                continue
            for v in VARS:
                r_ = spearmanr([x[v] for x in rows], [x[target] for x in rows])[0]
                if r_ == r_:
                    acc[v].append(r_)
        mean = {v: float(np.mean(a)) for v, a in acc.items() if a}
        return sorted(mean.items(), key=lambda kv: -abs(kv[1]))[:n]
    nf = {g: len(fronts[g][0]) for g in main_groups}
    ps.publish_figure("R4-F01", [r for r in obj_rows if r["group"] in main_groups], plot_r4_f01, sources=src,
                      title=("Reference fronts hold " + ", ".join(str(nf[g]) for g in main_groups)
                             + " feasible non-dominated designs (Dorr " + ", ".join(g[0] for g in main_groups) + ")"),
                      caption=("每型全部 FE 成功设计的目标空间（横轴对数）。彩色阶梯线与黑边标记为参考前沿（可行设计的非支配集），"
                               "灰叉为柄应力约束（vm P99 ≤ 440 MPa）不满足者；微动超过 40 µm 时画出 50 µm 点线。"))
    pc = []
    for g in main_groups:
        for y, r in zip(*fronts[g]):
            pc.append(dict(dorr=g[0], **{v: EV.as_float(r, v) for v in VARS}, log_f1=y[0], f2=y[1], design_id=r["design_id"]))
    tc = top_corr({t: [r for r in pc if r["dorr"] == t] for t in "ABC"}, "log_f1")
    ps.publish_figure("R4-F02", pc, plot_r4_f02, sources=src,
                      title=("Along the fronts, lower micromotion comes with "
                             + " and ".join(f"{'larger' if rho < 0 else 'smaller'} {EN[v]} (mean ρ {rho:+.2f})" for v, rho in tc)),
                      caption="各型参考前沿设计的平行坐标图：设计变量按其范围归一化，目标按前沿内范围归一化；颜色按 f1 从小（紫）到大（黄）。")
    by_t = {t: [r for r in var_rows if r["dorr"] == t] for t in "ABC"}
    c1, c2 = top_corr(by_t, "f1", 1)[0], top_corr(by_t, "f2", 1)[0]
    ps.publish_figure("R4-F03", var_rows, plot_r4_f03, sources=src,
                      title=(f"Micromotion {'falls' if c1[1] < 0 else 'rises'} most with {EN[c1[0]]} (mean ρ {c1[1]:+.2f}); "
                             f"shielding {'rises' if c2[1] > 0 else 'falls'} most with {EN[c2[0]]} (mean ρ {c2[1]:+.2f})"),
                      caption="参考扫描全部 FE 成功设计的目标对单个设计变量的散点（Saltelli 2019：先看散点再看指数）。")
    si_rows = []
    for g in main_groups:
        t = g[0]
        ok = [r for r in results[g] if r["status"] == "OK"]
        X = np.array([S.to_unit({v: EV.as_float(r, v) for v in VARS}) for r in ok])
        for q, col in (("log f1", lambda r: math.log10(EV.as_float(r, "f1_p95_um"))),
                       ("f2", lambda r: EV.as_float(r, "f2_g7_loss_pct"))):
            y = np.array([col(r) for r in ok])
            S1, ST, ls = sobol_indices_gp(X, y)
            for v, a, b, l in zip(VARS, S1, ST, ls):
                si_rows.append(dict(dorr=t, objective=q, variable=v, S1=a, ST=b, lengthscale=l))
    def top_st(q):
        m = {v: np.mean([r["ST"] for r in si_rows if r["objective"] == q and r["variable"] == v]) for v in VARS}
        return sorted(m, key=lambda v: -m[v])[:2]
    typ_f2 = {t: max(VARS, key=lambda v: next(r["ST"] for r in si_rows if r["dorr"] == t and r["objective"] == "f2" and r["variable"] == v))
              for t in {r["dorr"] for r in si_rows}}
    odd = [t for t, v in typ_f2.items() if v not in top_st("f2")]
    ps.publish_figure("R4-F04", si_rows, plot_r4_f04, sources=src,
                      title=(f"Micromotion is driven by {EN[top_st('log f1')[0]]} and {EN[top_st('log f1')[1]]}; shielding by "
                             f"{EN[top_st('f2')[0]]} and {EN[top_st('f2')[1]]}"
                             + (f" (Dorr {', '.join(sorted(odd))}: {EN[typ_f2[sorted(odd)[0]]]})" if odd else "")),
                      caption=("由参考数据拟合 GP（ARD Matérn 5/2），在其后验均值上用 Saltelli/Jansen 估计量（每组 4,096 基样本）计算"
                               "一阶（实心）与总效应（浅色）Sobol 指数。输入在整个单位立方体上均匀分布，含几何门不可行区（GP 外推），见局限。"))
    json.dump(si_rows, open(ROOT / "results" / "S4_sobol_indices.json", "w"), indent=1, default=float)
    fr_main = [r for r in fail_rows if r["group"] in main_groups]
    n_gate = sum(r["status"] in ("L1", "L2") for r in fr_main)
    n_fe = sum(r["status"] in ("OK", "L3", "L4", "L5") for r in fr_main)
    n_fefail = sum(r["status"] in ("L3", "L4", "L5") for r in fr_main)
    ps.publish_figure("R4-F05", fr_main, plot_r4_f05, sources=src,
                      title=(f"{n_gate / len(fr_main):.0%} of attempts fail the geometry gate; "
                             f"{n_fefail / max(n_fe, 1):.1%} of gate-passing designs fail in meshing or solving"),
                      caption="全部尝试设计按失败等级着色（L1/L2 几何门，L3 网格，L4 求解，L5 导出/QoI）。")
    sil = []
    for g in main_groups:
        t = g[0]
        f = F.build(t)
        sil += poly_rows(f.outer, dorr=t, part="outer", rank=0, f1="", f2="")
        sil += poly_rows(f.inner, dorr=t, part="inner", rank=0, f1="", f2="")
        ys, rs = fronts[g]
        order = np.argsort(ys[:, 0])
        pick = order[np.linspace(0, len(order) - 1, min(8, len(order))).round().astype(int)]
        for k, i in enumerate(pick):
            r = rs[i]
            st = S.make(t, {v: EV.as_float(r, v) for v in VARS})
            sil += poly_rows(st.full(), dorr=t, part="stem", rank=k, f1=10 ** ys[i, 0], f2=ys[i, 1])
    ps.publish_figure("R4-F06", sil, plot_r4_f06, sources=src,
                      title="Front stems of each Dorr type, ordered from lowest to highest micromotion",
                      caption="每型参考前沿按 f1 由小到大等距取至多 8 个设计的柄轮廓（含截骨线以上的假体颈与头）。")
    # 表
    for g in main_groups:
        for y, r in zip(*fronts[g]):
            t01.append(dict(group=g, design_id=r["design_id"], **{v: EV.as_float(r, v) for v in VARS},
                            f1_um=10 ** y[0], f2_pct=y[1], vm_p99=EV.as_float(r, "vm_p99")))
    ps.publish_table("R4-T01", sorted(t01, key=lambda r: (r["group"], r["f1_um"])), title="参考前沿设计清单",
                     caption="每型可行设计的非支配集，按 f1 升序。", units={"f1_um": "µm", "f2_pct": "%", "vm_p99": "MPa"})
    t02 = []
    for g, rows in results.items():
        cnt = {s: sum(r["status"] == s for r in rows) for s in STATUS_ORDER}
        gp = cnt["OK"] + cnt["L3"] + cnt["L4"] + cnt["L5"]
        t02.append(dict(group=g, attempts=len(rows), **cnt, gate_passed=gp,
                        fe_fail_rate_pct=100 * (gp - cnt["OK"]) / max(gp, 1)))
    ps.publish_table("R4-T02", t02, title="失败分级计数", caption="gate_passed = 通过几何门进入 FE 的设计数；fe_fail_rate 为其中 L3–L5 的比例。")
    t03 = []
    for g, rows in results.items():
        tt = [EV.as_float(r, "t_total_s") for r in rows if r["status"] == "OK" and str(r.get("cached", "0")) in ("0", "")]
        if not tt:
            tt = [EV.as_float(r, "t_total_s") for r in rows if r["status"] == "OK"]
        tt = [x for x in tt if not math.isnan(x)]
        t03.append(dict(group=g, n=len(tt), median_s=np.median(tt), p95_s=np.percentile(tt, 95),
                        total_machine_h=sum(tt) / 3600))
    ps.publish_table("R4-T03", t03, title="单设计耗时（网格 + 两个 Abaqus 作业 + QoI）",
                     caption="墙钟时间；4 个设计并行，总机时 ≈ 总和，墙钟约为其 1/4。", units={"median_s": "s"})
    nf = {g: len(fronts[g][0]) for g in main_groups}
    fe_fail = max(r["fe_fail_rate_pct"] for r in t02)
    rows_ok = all(r["attempts"] == attempts_n[r["group"]] for r in t02)
    ps.publish_acceptance("R4", [
        {"id": "R4-A1", "measured": "；".join(f"{g} {k}" for g, k in nf.items()),
         "status": "PASS" if min(nf.values()) >= CFG["bo"]["min_front_points"] else "FAIL",
         "note": "" if min(nf.values()) >= CFG["bo"]["min_front_points"] else (
             "按计划把不足 15 点的组扩到 512 个设计后仍不足：数百个可行设计里只有个位数非支配点，说明两个目标在本设计空间里"
             "强相关、权衡面短，而不是采样不足。影响：R5 的 HV 比与 IGD 以 R4 + R5 全部可行评估的非支配集为参考，点数会多于此处；"
             "处置建议：接受稀疏前沿，不再加样；该处置尚待用户同意（S5 已按此假设运行）。")},
        {"id": "R4-A2", "measured": "每组 runs.csv 行数 = 尝试数（含几何门失败行）" if rows_ok else "不一致",
         "status": "PASS" if rows_ok else "FAIL", "note": ""},
        {"id": "R4-A3", "measured": f"最大 {fe_fail:.1f} %", "status": "PASS" if fe_fail <= 5 else "FAIL",
         "note": "" if fe_fail <= 5 else "检查失败设计的网格与求解日志"},
    ])
    ps.publish_inputs("R4", groups=list(results), attempts=attempts_n, sweep_seed=RS.SWEEP_SEED)
    tx = ps.report_dir("R4") / "text"
    tx.joinpath("summary.md").write_text(
        "参考扫描：" + "；".join(f"{g} 尝试 {attempts_n[g]} 个、前沿 {nf.get(g, '—')} 点" for g in results) +
        f"。FE 失败率最高 {fe_fail:.1f} %。前沿与敏感性见图。", encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        f"每组按打乱 Sobol 序列（种子 {RS.SWEEP_SEED}）逐个尝试设计，先过几何门，通过者全部跑 FE（摩擦 + 粘接两个作业），"
        f"直到 {CFG['bo']['reference_n']} 个设计通过几何门；前沿不足 {CFG['bo']['min_front_points']} 点则扩到 "
        f"{CFG['bo']['reference_n_max']}。对照组（A、C 型松质骨改为 300 MPa）用与该型相同的尝试序列。"
        "目标：y1 = log10(f1)，y2 = f2，均最小化；可行 = 柄 von Mises P99 ≤ 440 MPa。参考前沿 = 可行设计的非支配集。"
        "全局敏感性：对每型每个目标拟合 GP，在后验均值上用 Saltelli 2010 一阶与 Jansen 1999 总效应估计量。", encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- Sobol 指数假设输入在整个单位立方体上独立均匀，而几何门可行域不是长方体；不可行区上的值是 GP 外推，指数只作定性排序。\n"
        "- 参考前沿本身是有限样本的非支配集，不是真前沿；R5 用 R4 + R5 全部评估的并集作参考。\n"
        "- 扩到 512 个设计时，前一轮中几何门失败的尝试在 runs.csv 里被重复记录（设计相同、design_id 不同）；"
        "本报告的计数以本阶段返回的尝试序列为准，不受重复行影响。之后的阶段已改为复用几何门结果。", encoding="utf-8")


def publish_only():
    """由 results/S4_groups.json 与 runs.csv 重建 R4（不调用 FE、不重算几何门）。"""
    groups = json.loads((ROOT / "results" / "S4_groups.json").read_text())
    by = {r["design_id"]: r for r in EV.read_runs()}
    results = {g: [by[d] for d in ids if d in by] for g, ids in groups.items()}
    publish(results, {g: len(ids) for g, ids in groups.items()})


if __name__ == "__main__":
    if "--publish" in sys.argv:
        publish_only()
    else:
        main()
