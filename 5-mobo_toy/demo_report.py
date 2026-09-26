"""报告流水线演示：全部为合成数据（synthetic=True），只证明规范能落地，不含任何结果。

python report.py --demo  → reports/_demo_pipeline/RD_report.{md,html,pdf}
"""
from __future__ import annotations

import numpy as np

import plotstyle as ps

RID = "RD"


# ---------------------------------------------------------------- plot functions（只读 CSV）
def plot_hv_curve(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 3, sharey=True)
    for ax, t in zip(axes, "ABC"):
        rows = [i for i, x in enumerate(d["dorr"]) if x == t]
        for method in ("qNEHVI", "Sobol"):
            seeds = sorted({d["seed"][i] for i in rows if d["method"][i] == method})
            curves = []
            for s in seeds:
                idx = [i for i in rows if d["method"][i] == method and d["seed"][i] == s]
                x = np.array([d["n_fe"][i] for i in idx]); y = np.array([d["hv_ratio"][i] for i in idx])
                curves.append(y)
                if method == "qNEHVI":
                    ax.plot(x, y, color=ps.DORR[t], lw=0.7, alpha=0.45)
            med = np.median(np.vstack(curves), axis=0)
            style = dict(ps.METHOD[method])
            style.setdefault("color", ps.DORR[t])
            ax.plot(x, med, label=f"{method} median ({len(seeds)} seeds)", **style)
        ps.threshold_line(ax, 0.9, "y", "0.9")
        ax.set_title(f"Dorr {t}")
        ax.set_xlabel(ps.LABEL["n_fe"])
        ax.set_ylim(0, 1.02)
    axes[0].set_ylabel(ps.LABEL["hv_ratio"])
    axes[0].legend(loc="lower right")
    ps.panel_labels(axes)
    return fig


def plot_parity(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("onehalf", 68, 1, 2)
    for ax, obj in zip(axes, ("f1", "f2")):
        idx = [i for i, o in enumerate(d["objective"]) if o == obj]
        yt = np.array([d["y_true"][i] for i in idx]); yp = np.array([d["y_pred"][i] for i in idx])
        lo = np.array([d["lo90"][i] for i in idx]); hi = np.array([d["hi90"][i] for i in idx])
        cols = [ps.DORR[d["dorr"][i]] for i in idx]
        ax.errorbar(yt, yp, yerr=[yp - lo, hi - yp], fmt="none", ecolor=ps.LIGHT, elinewidth=0.6, zorder=1)
        ax.scatter(yt, yp, c=cols, s=9, zorder=2, edgecolors="none")
        lim = ps.shared_limits(yt, yp, lo, hi)
        ax.plot(lim, lim, color="black", lw=0.8)
        ax.set_xlim(lim); ax.set_ylim(lim); ax.set_aspect("equal")
        ax.set_xlabel(f"FE {ps.LABEL[obj]}"); ax.set_ylabel(f"GP {ps.LABEL[obj]}")
    for t in "ABC":
        axes[1].scatter([], [], c=ps.DORR[t], s=9, label=f"Dorr {t}")
    axes[1].legend(loc="upper left")
    ps.panel_labels(axes)
    return fig


def plot_fronts(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 72)
    for t in "ABC":
        idx = [i for i, x in enumerate(d["dorr"]) if x == t]
        f1 = np.array([d["f1"][i] for i in idx]); f2 = np.array([d["f2"][i] for i in idx])
        front = np.array([d["on_front"][i] for i in idx]) > 0.5
        ax.scatter(f1[~front], f2[~front], s=5, color=ps.DORR[t], alpha=0.18, edgecolors="none")
        o = np.argsort(f1[front])
        ax.step(f1[front][o], f2[front][o], where="post", color=ps.DORR[t], lw=1.3)
        ax.scatter(f1[front][o], f2[front][o], s=12, color=ps.DORR[t], marker=ps.DORR_MARKER[t],
                   label=f"Dorr {t} front", zorder=3)
    ps.threshold_line(ax, 50, "x", "50 µm")
    ax.set_xlabel(ps.LABEL["f1"]); ax.set_ylabel(ps.LABEL["f2"])
    ax.legend(loc="upper right")
    return fig


# ---------------------------------------------------------------- synthetic data
def _pareto_mask(F):
    F = np.asarray(F); m = np.ones(len(F), bool)
    for i in range(len(F)):
        if m[i]:
            dom = np.all(F <= F[i], axis=1) & np.any(F < F[i], axis=1)
            if dom.any():
                m[i] = False
    return m


def make() -> None:
    rng = np.random.default_rng(20260926)
    n = np.arange(12, 61, 4)
    rows = []
    for t, tau in zip("ABC", (14, 18, 24)):
        for s in range(3):
            y = 1 - 0.55 * np.exp(-(n - 12) / tau) + rng.normal(0, 0.01, n.size)
            rows += [dict(dorr=t, method="qNEHVI", seed=s, n_fe=int(k), hv_ratio=float(min(v, 1.0)))
                     for k, v in zip(n, np.maximum.accumulate(y))]
            y = 1 - 0.55 * np.exp(-(n - 12) / (tau * 4)) + rng.normal(0, 0.015, n.size)
            rows += [dict(dorr=t, method="Sobol", seed=s, n_fe=int(k), hv_ratio=float(min(v, 1.0)))
                     for k, v in zip(n, np.maximum.accumulate(y))]
    ps.publish_figure(
        "RD-F01", rows, plot_hv_curve, synthetic=True,
        title="[Synthetic] qNEHVI crosses 0.9 HV ratio before Sobol in every Dorr type",
        caption="细线为单个种子，粗线为中位；虚线为同预算 Sobol 中位；点线为 0.9 门槛。数据为合成。",
        units={"n_fe": "count", "hv_ratio": "–"}, sources={"generator": "demo_report.make, seed 20260926"})

    rows = []
    for t in "ABC":
        for _ in range(20):
            f1t = rng.lognormal(3.6, 0.5); f2t = rng.uniform(10, 60)
            s1, s2 = 0.12 * f1t, 3.0
            p1, p2 = f1t + rng.normal(0, s1), f2t + rng.normal(0, s2)
            rows.append(dict(dorr=t, objective="f1", y_true=f1t, y_pred=p1, lo90=p1 - 1.645 * s1, hi90=p1 + 1.645 * s1))
            rows.append(dict(dorr=t, objective="f2", y_true=f2t, y_pred=p2, lo90=p2 - 1.645 * s2, hi90=p2 + 1.645 * s2))
    ps.publish_figure(
        "RD-F02", rows, plot_parity, synthetic=True,
        title="[Synthetic] GP predictions track FE values with 90% intervals",
        caption="点为测试设计，灰色竖线为 GP 90% 预测区间，黑线为 y = x。数据为合成。",
        units={"y_true": "µm or %", "y_pred": "µm or %"}, sources={"generator": "demo_report.make"})

    cov = {o: float(np.mean([(r["lo90"] <= r["y_true"] <= r["hi90"]) for r in rows if r["objective"] == o]))
           for o in ("f1", "f2")}

    rows = []
    for t, shift in zip("ABC", (0.0, 10.0, 25.0)):
        f1 = rng.uniform(20, 160, 256) + shift
        f2 = 70 - 0.35 * f1 + rng.gamma(2, 6, 256) + shift / 3
        mask = _pareto_mask(np.c_[f1, f2])
        rows += [dict(dorr=t, f1=float(a), f2=float(b), on_front=int(m)) for a, b, m in zip(f1, f2, mask)]
    ps.publish_figure(
        "RD-F03", rows, plot_fronts, synthetic=True,
        title="[Synthetic] Fronts shift towards higher micromotion from Dorr A to C",
        caption="浅色点为全部设计，阶梯线与实心标记为非支配前沿；共用坐标。数据为合成。",
        units={"f1": "µm", "f2": "%"}, sources={"generator": "demo_report.make"})

    ps.publish_table(
        "RD-T01", [dict(objective=o, R2=0.9 - 0.05 * k, spearman=0.93 - 0.03 * k, coverage90=cov[o], sharpness=0.1 + 0.02 * k)
                   for k, o in enumerate(("f1", "f2"))],
        title="合成：代理指标", caption="R² 与 Spearman 在测试集上计算；coverage90 为 90% 区间实际覆盖率；锐度为区间平均半宽（标准化）。",
        units={"R2": "–", "coverage90": "–"}, synthetic=True)

    ps.publish_acceptance("RD", [
        {"id": "RD-A1", "measured": "0.96", "status": "PASS"},
        {"id": "RD-A2", "measured": f"{min(cov.values()):.2f}", "status": "FAIL",
         "note": "演示不通过的写法：写明原因（区间过窄）与处置（调高噪声先验后重跑）。"},
    ], synthetic=True)   # RD-A3 故意不提交，演示 PENDING

    ps.publish_inputs("RD", 数据来源="合成（numpy 种子 20260926）", Abaqus="未使用", runs_csv_rows="无")
    d = ps.report_dir("RD") / "text"
    (d / "summary.md").write_text(
        "本报告只演示报告流水线。三张图都由各自的 CSV 画出，可用 `python report.py --replot RD-F01` 重画；"
        "验收表演示了通过、不通过（必须写原因与处置）和待定三种状态。", encoding="utf-8")
    (d / "methods.md").write_text(
        "合成数据由 `demo_report.make()` 用固定随机种子生成。作图遵守 `plotstyle.py`：Dorr A/B/C 固定色，"
        "方法用线型区分，门槛用点线，图内英文、正文中文，PNG 300 dpi + SVG。", encoding="utf-8")
    (d / "limitations.md").write_text("- 全部数据为合成，不能引用。", encoding="utf-8")


if __name__ == "__main__":
    make()
