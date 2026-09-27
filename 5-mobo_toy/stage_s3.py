"""S3 优化器自检：在前沿已知的解析基准上检验 qLogNEHVI 流程 → R3 报告。python stage_s3.py（.venv-mobo）

与 FE 阶段用同一套代码路径（mobo.run：离散 Sobol 候选池 20,000、q = 4、初始 12 + 12 轮 = 60 次评估）。
"""
from __future__ import annotations

import json
import sys

import numpy as np
import torch
from scipy.stats import qmc

import mobo
import plotstyle as ps

ROOT = ps.ROOT
OUT = ROOT / "results" / "S3_selftest.json"
SEEDS = [0, 1, 2, 3, 4]
N_POOL = 20000


class Bench:
    def __init__(self, name, fn, d):
        self.name, self.fn, self.d = name, fn, d
        self.n_obj, self.n_con = 2, 0
        self.ref_point = fn.ref_point.numpy()
        self.max_hv = float(fn.max_hv)

    def pool(self, n, seed):
        return qmc.Sobol(self.d, scramble=True, seed=1000 + seed).random(n)

    def evaluate(self, X, **_):
        Y = self.fn(torch.as_tensor(X)).numpy()
        return Y, np.zeros((len(X), 0)), np.ones(len(X), bool)

    def true_front(self):
        if self.name == "ZDT1 (d = 5)":
            f1 = np.linspace(0, 1, 2001)
            return np.c_[f1, 1 - np.sqrt(f1)]
        X = qmc.Sobol(self.d, scramble=True, seed=99).random(2 ** 18)
        Y = self.fn(torch.as_tensor(X)).numpy()
        return Y[mobo.pareto_mask(Y)]


def benches():
    from botorch.test_functions.multi_objective import BraninCurrin, ZDT1
    return [Bench("BraninCurrin (d = 2)", BraninCurrin(), 2), Bench("ZDT1 (d = 5)", ZDT1(dim=5), 5)]


# ------------------------------------------------------------------ plots（只读 CSV）
MCOL = {"qNEHVI": "#000000", "Sobol": ps.GREY}


def plot_r3_f01(csv_path):
    d = ps.read_csv(csv_path)
    names = list(dict.fromkeys(d["bench"]))
    fig, axes = ps.new_figure("double", 62, 1, len(names))
    for ax, b in zip(axes, names):
        for m in ("qNEHVI", "Sobol"):
            jj = [i for i in range(len(d["bench"])) if d["bench"][i] == b and d["method"][i] == m]
            n = np.array(sorted({d["n_eval"][i] for i in jj}))
            M = np.array([[d["log_hv_diff"][i] for i in jj if d["n_eval"][i] == k] for k in n])
            mean, se = M.mean(1), M.std(1, ddof=1) / np.sqrt(M.shape[1])
            st = dict(ps.METHOD[m]); st["color"] = MCOL[m]
            ax.plot(n, mean, label=f"{m} (mean ± 2 SE, {M.shape[1]} seeds)", **st)
            ax.fill_between(n, mean - 2 * se, mean + 2 * se, color=MCOL[m], alpha=0.15, lw=0)
        ax.set_title(b); ax.set_xlabel(ps.LABEL["n_eval"]); ax.set_ylabel("log10(HV_max − HV)")
        ax.axvline(12, color=ps.LIGHT, lw=0.8, ls=":")
    axes[0].legend(loc="upper right")
    ps.panel_labels(axes)
    return fig


def plot_r3_f02(csv_path):
    d = ps.read_csv(csv_path)
    names = list(dict.fromkeys(d["bench"]))
    fig, axes = ps.new_figure("double", 68, 1, len(names))
    for ax, b in zip(axes, names):
        jj = [i for i in range(len(d["bench"])) if d["bench"][i] == b]
        for kind, style in (("true", dict(color="#000000", lw=1.0, ls="-")),):
            kk = sorted([i for i in jj if d["kind"][i] == kind], key=lambda i: d["f1"][i])
            ax.plot([d["f1"][i] for i in kk], [d["f2"][i] for i in kk], label="true front", **style)
        for m, mk in (("qNEHVI", "o"), ("Sobol", "x")):
            kk = sorted([i for i in jj if d["kind"][i] == m], key=lambda i: d["f1"][i])
            ax.step([d["f1"][i] for i in kk], [d["f2"][i] for i in kk], where="post", color=MCOL[m], lw=0.8,
                    ls=ps.METHOD[m]["ls"])
            ax.plot([d["f1"][i] for i in kk], [d["f2"][i] for i in kk], mk, color=MCOL[m], ms=3.5,
                    label=f"{m}, median seed")
        ax.set_title(b); ax.set_xlabel("Objective 1 (–)"); ax.set_ylabel("Objective 2 (–)")
    axes[0].legend(loc="upper right")
    ps.panel_labels(axes)
    return fig


def plot_r3_f03(csv_path):
    d = ps.read_csv(csv_path)
    names = list(dict.fromkeys(d["bench"]))
    fig, axes = ps.new_figure("double", 68, 1, len(names))
    for ax, b in zip(axes, names):
        jj = [i for i in range(len(d["bench"])) if d["bench"][i] == b]
        kk = sorted([i for i in jj if d["kind"][i] == "true"], key=lambda i: d["f1"][i])
        ax.plot([d["f1"][i] for i in kk], [d["f2"][i] for i in kk], color="#000000", lw=1.0, label="true front")
        for m in ("qNEHVI", "Sobol"):
            kk = sorted([i for i in jj if d["kind"][i] == f"eaf_{m}"], key=lambda i: d["f1"][i])
            xs = [d["f1"][i] for i in kk]; ys = [d["f2"][i] for i in kk]
            st = dict(ps.METHOD[m]); st["color"] = MCOL[m]
            ax.step(xs, ys, where="post", label=f"{m}: 50 % attainment", **st)
        ax.set_title(b); ax.set_xlabel("Objective 1 (–)"); ax.set_ylabel("Objective 2 (–)")
    axes[0].legend(loc="upper right")
    ps.panel_labels(axes)
    return fig


# ------------------------------------------------------------------ main
def run_all():
    res = {}
    for b in benches():
        res[b.name] = {"max_hv": b.max_hv, "ref": b.ref_point.tolist(), "runs": {}}
        pool_oracle = []
        for seed in SEEDS:
            pool = b.pool(N_POOL, seed)
            Yp = b.evaluate(pool)[0]
            pool_oracle.append(mobo.hypervolume(Yp, b.ref_point))
            for m in ("qnehvi", "sobol"):
                recs, info = mobo.run(b, method=m, seed=seed, pool=pool, verbose=False)
                res[b.name]["runs"][f"{m}_{seed}"] = {"Y": [r.y.tolist() for r in recs], "X": [r.x.tolist() for r in recs],
                                                     "acq_s": info.get("timing", [])}
                print(f"{b.name} {m} seed {seed}: final HV {mobo.hypervolume(np.array([r.y for r in recs]), b.ref_point):.4f}"
                      f" / max {b.max_hv:.4f}", flush=True)
        res[b.name]["pool_oracle_hv"] = pool_oracle
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res))
    return res


def publish(res):
    bs = {b.name: b for b in benches()}
    hv_rows, front_rows, eaf_rows, t01 = [], [], [], []
    final = {}
    for name, R in res.items():
        b = bs[name]
        ref, mx = np.array(R["ref"]), R["max_hv"]
        tf = b.true_front()
        scale = tf.max(0) - tf.min(0)
        fronts = {"qNEHVI": [], "Sobol": []}
        for key, run in R["runs"].items():
            m = "qNEHVI" if key.startswith("qnehvi") else "Sobol"
            seed = int(key.split("_")[1])
            Y = np.array(run["Y"])
            for n in range(12, len(Y) + 1, 4):
                hv = mobo.hypervolume(Y[:n], ref)
                hv_rows.append(dict(bench=name, method=m, seed=seed, n_eval=n, hv=hv,
                                    log_hv_diff=float(np.log10(max(mx - hv, 1e-12)))))
            F = Y[mobo.pareto_mask(Y)]
            fronts[m].append(F)
            final.setdefault((name, m), []).append((mobo.hypervolume(Y, ref) / mx, mobo.igd(F, tf, scale), seed, F))
        for m in ("qNEHVI", "Sobol"):
            vals = sorted(final[(name, m)], key=lambda v: v[0])
            med = vals[len(vals) // 2]
            for f1, f2 in med[3]:
                front_rows.append(dict(bench=name, kind=m, f1=f1, f2=f2))
            grid = np.linspace(tf[:, 0].min(), max(F[:, 0].max() for F in fronts[m]), 400)
            eaf = mobo.attainment_surface(fronts[m], grid, 0.5)
            for g, v in zip(grid, eaf):
                if np.isfinite(v):
                    eaf_rows.append(dict(bench=name, kind=f"eaf_{m}", f1=g, f2=v))
            r = np.array([v[0] for v in vals]); ig = np.array([v[1] for v in vals])
            t01.append(dict(benchmark=name, method=m, HV_ratio_median=np.median(r), HV_ratio_mean=r.mean(),
                            HV_ratio_sd=r.std(ddof=1), IGD_mean=ig.mean(), IGD_sd=ig.std(ddof=1),
                            pool_oracle_HV_ratio=np.median(R["pool_oracle_hv"]) / mx, seeds=len(r)))
        step = max(1, len(tf) // 400)
        for f1, f2 in tf[np.argsort(tf[:, 0])][::step]:
            front_rows.append(dict(bench=name, kind="true", f1=f1, f2=f2))
            eaf_rows.append(dict(bench=name, kind="true", f1=f1, f2=f2))
    src = {"results": "results/S3_selftest.json", "seeds": SEEDS, "pool": f"scrambled Sobol n = {N_POOL}"}
    med = {n: np.median([v[0] for v in final[(n, "qNEHVI")]]) for n in res}
    ps.publish_figure("R3-F01", hv_rows, plot_r3_f01, sources=src,
                      title=("qLogNEHVI closes the hypervolume gap faster than Sobol on both benchmarks "
                             f"(median final HV ratio {min(med.values()):.3f}–{max(med.values()):.3f})"),
                      caption=("纵轴为已知最大超体积与当前超体积之差的常用对数（Daulton 2020 作图惯例），5 个种子的均值 ± 2 标准误；"
                               "点线处为 12 个初始点结束。参考点用 BoTorch 标准值：BraninCurrin [18, 6]，ZDT1 [11, 11]。"))
    ps.publish_figure("R3-F02", front_rows, plot_r3_f02, sources=src,
                      title="BO reaches the true front on BraninCurrin; on ZDT1 the discrete candidate pool keeps both methods above it",
                      caption="各方法取最终超体积为中位数的那个种子的非支配点；黑线为真前沿（BraninCurrin 为 2^18 个 Sobol 点的非支配集，ZDT1 为解析解）。")
    dom = {}
    for name in res:
        tf = bs[name].true_front()
        fr = {m: [] for m in ("qNEHVI", "Sobol")}
        for key, run in res[name]["runs"].items():
            Y = np.array(run["Y"]); fr["qNEHVI" if key.startswith("qnehvi") else "Sobol"].append(Y[mobo.pareto_mask(Y)])
        grid = np.linspace(tf[:, 0].min(), max(F_[:, 0].max() for m in fr for F_ in fr[m]), 400)
        e_b, e_s = mobo.attainment_surface(fr["qNEHVI"], grid, 0.5), mobo.attainment_surface(fr["Sobol"], grid, 0.5)
        ok = np.isfinite(e_b) & np.isfinite(e_s)
        dom[name] = float(np.mean(e_b[ok] <= e_s[ok] + 1e-12)) if ok.any() else float("nan")
    ps.publish_figure("R3-F03", eaf_rows, plot_r3_f03, sources=src,
                      title=("qLogNEHVI's 50 % attainment surface is at or below Sobol's on "
                             + " and ".join(f"{v:.0%} of the {n.split(' (')[0]} grid" for n, v in dom.items())),
                      caption="经验达成函数的 50 % 等值线（Zitzler 2003）：5 个种子中至少 3 个达到的目标区域边界。")
    ps.publish_table("R3-T01", t01, title="60 次评估时的超体积比与 IGD（5 个种子）",
                     caption=("HV 比 = 最终超体积 / 已知最大超体积；IGD 以真前沿范围归一化。pool_oracle 为整个 20,000 点候选池非支配集的"
                              "超体积比，即离散候选池能达到的上限。"))
    a1 = all(v >= 0.95 for v in med.values())
    beat = {}
    for n in res:
        sob_med = np.median([v[0] for v in final[(n, "Sobol")]])
        beat[n] = all(v[0] > sob_med for v in final[(n, "qNEHVI")])
    ps.publish_acceptance("R3", [
        {"id": "R3-A1", "measured": "；".join(f"{n}: {v:.4f}" for n, v in med.items()), "status": "PASS" if a1 else "FAIL",
         "note": "" if a1 else "BO 未达到 95 %：检查采集函数、参考点与 GP 拟合，暂不进入 FE 阶段"},
        {"id": "R3-A2", "measured": "；".join(f"{n}: {'全部' if v else '未全部'}高于 Sobol 中位" for n, v in beat.items()),
         "status": "PASS" if all(beat.values()) else "FAIL", "note": "" if all(beat.values()) else "个别种子未胜过 Sobol"},
    ])
    acq = [t for R in res.values() for k, r in R["runs"].items() if k.startswith("qnehvi") for t in r["acq_s"]]
    ps.publish_inputs("R3", seeds=SEEDS, candidate_pool=N_POOL, q=4, n_init=12, n_rounds=12,
                      acquisition="qLogNoisyExpectedHypervolumeImprovement（BoTorch 0.18.1），128 个 Sobol QMC 样本",
                      gp="SingleTaskGP，ARD Matérn 5/2，Gamma(3, 6) 长度尺度先验，输入归一化、输出标准化",
                      acq_time_median_s=round(float(np.median(acq)), 1) if acq else "")
    tx = ps.report_dir("R3") / "text"
    tx.joinpath("summary.md").write_text(
        f"在两个解析基准上，同一套 BO 代码（20,000 点离散候选池、q = 4、12 + 12×4 = 60 次评估）的中位最终超体积比为 "
        + "、".join(f"{n} {v:.3f}" for n, v in med.items())
        + f"，{'达到' if a1 else '未达到'} 95 % 验收线；qLogNEHVI 在"
        + ("每个种子上都胜过同预算 Sobol 的中位。" if all(beat.values()) else "部分种子上未胜过 Sobol。")
        + ("可以进入 FE 阶段。" if a1 and all(beat.values()) else "需要先排查。"), encoding="utf-8")
    tx.joinpath("methods.md").write_text(
        "**基准**：BraninCurrin（d = 2）与 ZDT1（d = 5，与 FE 问题同维），均为双目标最小化，已知最大超体积取 BoTorch 给出的值"
        "（参考点 [18, 6] 与 [11, 11]）。\n\n"
        "**方法**：与 FE 阶段相同的 `mobo.run`。每个种子先生成打乱的 Sobol 候选池 20,000 点；BO 与 Sobol 基线用同一候选池，"
        "BO 以池的前 12 点为初始设计，之后 12 轮每轮拟合每个目标一个 GP（ARD Matérn 5/2，Gamma(3, 6) 长度尺度先验，"
        "Gamma(2, 0.15) 输出尺度先验，噪声下界 1e-6），在未评估的候选点上用 qLogNEHVI（128 个 QMC 样本）序贯贪心选 4 个。"
        "Sobol 基线取池的前 60 点。\n\n"
        "**指标**：超体积（最小化空间，参考点固定）、IGD（参考前沿每点到所得前沿最近点的平均距离，按真前沿范围归一化）、"
        "50 % 经验达成面。标准参考点离前沿较远，HV 比的区分度有限，因此同时画 log 超体积差（Daulton 2020）。", encoding="utf-8")
    tx.joinpath("limitations.md").write_text(
        "- 离散候选池限制了可达的最优：ZDT1 的真前沿要求 x2…x5 = 0，池中没有这样的点，pool_oracle 列给出池能达到的上限。\n"
        "- 基准无噪声、无约束；FE 问题有重新网格化噪声与柄应力约束，这两点只在 R5 检验。", encoding="utf-8")
    print(json.dumps({k: float(v) for k, v in med.items()}), beat)


if __name__ == "__main__":
    res = json.loads(OUT.read_text()) if (OUT.exists() and "--replot" in sys.argv) else run_all()
    publish(res)
