"""V2A 报告的 FE 部分（在 Linux 上跑，由 report_v2a.py 调用）：验证（符号、网格、排序、失败率）与 BO。

数据：~/mobo_toy_v2/results/{signs,convergence,reference,mesh_decision,bo_s0..2}.json 与队列里各作业的 result.json。
缺数据的图与验收项跳过（验收记 PENDING）。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import plotstyle as ps  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

plt = ps.plt
ACOL = ps.DORR["A"]
SEEDS = (0, 1, 2)
QTY = {"f1_p95_um": "micromotion P95 (µm)", "f2_g7_loss_pct": "Gruen 7 SED loss (%)", "vm_p99": "stem von Mises P99 (MPa)"}


def _load(name):
    f = J.RESULTS / name
    return json.loads(f.read_text()) if f.exists() else None


def _scan(stage=None, tag=None, kind="design") -> list[dict]:
    """队列里符合 stage/tag 的作业结果（含失败）。"""
    out = []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != kind or (stage and spec.get("stage") != stage) or (tag and spec.get("tag") != tag):
            continue
        r = J.result(d.name)
        out.append({"job_id": d.name, "spec": spec, "result": r, "state": J.state(d)})
    return out


# ================================================================== 验证
def part_verification(fm) -> list[dict]:
    items = []
    s = _load("signs.json")
    if s:
        rows = []
        for var in ("base", "torque_off", "delta_0", "mu_0.8", "rerun"):
            for q in QTY:
                if q in s.get(var, {}):
                    rows.append({"variant": var, "quantity": q, "value": s[var][q]})
        ch = s.get("checks", {})
        n_dir = sum(bool(ch.get(k)) for k in ("torque raises micromotion", "no interference raises micromotion",
                                               "higher friction lowers micromotion"))
        ps.publish_figure("V2A-F07", rows, plot_f07,
                          title=f"Sign checks: {n_dir} of 3 micromotion responses go the expected way; rerun "
                                f"{'identical' if ch.get('rerun identical') else 'differs'}",
                          caption="同一设计（calcar-heavy 示例，α 20°）的四个变体：基准；去掉前后向载荷分量（无扭转）；压配量 δ = 0；摩擦系数 μ = 0.8；"
                                  "以及重建网格重跑。每个变体都是完整的建模 + 求解 + 后处理。", units={"value": "see quantity"})
        trows = [{"check": k, "observed": bool(v)} for k, v in ch.items()]
        base = s.get("base", {})
        for var in ("torque_off", "delta_0", "mu_0.8", "rerun"):
            v = s.get(var, {})
            trows.append({"check": f"{var}: f1 / f2 / vm", "observed": f"{v.get('f1_p95_um', float('nan')):.3g} µm / "
                          f"{v.get('f2_g7_loss_pct', float('nan')):.3g}% / {v.get('vm_p99', float('nan')):.3g} MPa "
                          f"(base {base.get('f1_p95_um', float('nan')):.3g} / {base.get('f2_g7_loss_pct', float('nan')):.3g} / "
                          f"{base.get('vm_p99', float('nan')):.3g})"})
        ps.publish_table("V2A-T04", trows, title="Sign checks and rerun determinism", caption="方向检查只看 f1（P95 微动）；f2、柄应力照录。")
        ok5 = n_dir == 3
        items.append({"id": "V2A-A5", "measured": f"{n_dir}/3 directions as expected " + ", ".join(f"{k}: {'yes' if v else 'no'}" for k, v in ch.items() if k != "rerun identical"),
                      "status": "PASS" if ok5 else "FAIL", "note": "" if ok5 else "有方向与预期相反，需分析（见 V2A-T04）"})
        ok6 = bool(ch.get("rerun identical"))
        items.append({"id": "V2A-A6", "measured": "identical" if ok6 else "differs", "status": "PASS" if ok6 else "FAIL",
                      "note": "" if ok6 else "重建重跑结果不同"})
    c = _load("convergence.json")
    if c:
        rows = []
        for key, v in c["grid"].items():
            name, h = key.rsplit("_h", 1)
            for q in QTY:
                if q in v:
                    rows.append({"design": name, "h": float(h), "quantity": q, "value": v[q]})
        gci = c.get("gci", {})
        worst = max((abs(v["rel_change_2.0_vs_1.0"]) for k, v in gci.items() if v.get("rel_change_2.0_vs_1.0") is not None
                     and k.split(":")[1] == "f1_p95_um"), default=float("nan"))
        ps.publish_figure("V2A-F08", rows, plot_f08,
                          title=f"Mesh convergence: f1 changes by up to {100 * worst:.0f}% between 2.0 and 1.0 mm interface elements",
                          caption="两个设计（calcar-heavy 示例与参考池第 1 个可行设计）在界面单元 2.0、1.4、1.0 mm 下的三个关注量；完整股骨参照按同一网格档。"
                                  "GCI 按 Celik 2008（细化比 1.4、1.43），见 V2A-T05。", units={"h": "mm"})
        trows = [{"quantity": k, **{kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}} for k, v in gci.items()]
        ps.publish_table("V2A-T05", trows, title="Mesh convergence and GCI (Celik 2008)",
                         caption="h1.0/h1.4/h2.0 为三档网格下的值；p 为表观阶数；gci_fine 为细网格的 GCI；最后一列为 2.0 对 1.0 的相对变化。")
        pairs = []
        for i in range(12):
            a = [r for r in _scan(tag=f"r{i}_h2") if r["result"] and "f1_p95_um" in r["result"]]
            b = [r for r in _scan(tag=f"r{i}_h1.4") if r["result"] and "f1_p95_um" in r["result"]]
            if a and b:
                for q in ("f1_p95_um", "f2_g7_loss_pct"):
                    pairs.append({"i": i, "quantity": q, "h2.0": a[0]["result"][q], "h1.4": b[0]["result"][q]})
        rk = c.get("ranking_2.0_vs_1.4", {})
        if pairs:
            ps.publish_figure("V2A-F09", pairs, plot_f09,
                              title=f"Ranking is preserved between meshes: Spearman f1 {rk.get('f1_p95_um', {}).get('spearman', float('nan')):.2f}, "
                                    f"f2 {rk.get('f2_g7_loss_pct', {}).get('spearman', float('nan')):.2f} (n = {len(pairs) // 2})",
                              caption="参考池前 12 个可行设计在 2.0 与 1.4 mm 界面单元下的 f1、f2。虚线为 y = x。BO 只依赖排序，排序保持即可用较粗网格。")
        dec = _load("mesh_decision.json")
        if dec is None:
            import stage_v2a as S
            dec = S.mesh_decision(c)
        ok7 = dec["production_h"] is not None
        items.append({"id": "V2A-A7", "measured": f"rel. change vs 1.0 mm: " + ", ".join(f"{k.split(':')[0]}·{k.split(':')[1][:2]} {100 * v:.0f}%" for k, v in dec["rel_change_vs_finest"].items() if v is not None)
                      + f"; Spearman 2.0 vs 1.4: " + ", ".join(f"{k[:2]} {v:.2f}" for k, v in dec["spearman_2.0_vs_1.4"].items() if v is not None),
                      "status": "PASS" if ok7 else "FAIL", "note": "" if ok7 else "2.0 mm 未满足预设判据，BO 未启动，等用户决定"})
    # A9：可行设计（L1 以外）的 FE 失败率（最终状态，重试与修正之后）
    des = [r for r in _scan() if r["spec"].get("h_int") == 2.0 and r["state"] in ("DONE", "FAILED")]
    fails = [r for r in des if r["state"] == "FAILED" and r["result"]["failed"]["level"] != "L1"]
    feas = [r for r in des if not (r["state"] == "FAILED" and r["result"]["failed"]["level"] == "L1")]
    if feas:
        rate = len(fails) / len(feas)
        items.append({"id": "V2A-A9", "measured": f"{len(fails)} of {len(feas)} ({100 * rate:.1f}%) at 2.0 mm; levels "
                      + ", ".join(sorted({r['result']['failed']['level'] for r in fails})) if fails else f"0 of {len(feas)}",
                      "status": "PASS" if rate <= 0.05 else "FAIL", "note": "" if rate <= 0.05 else "失败率超过 5%，见失败清单"})
    return items


def plot_f07(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 55, 1, 3)
    order = ["base", "torque_off", "delta_0", "mu_0.8", "rerun"]
    for ax, q in zip(axes, QTY):
        vals = {d["variant"][i]: d["value"][i] for i in range(len(d["variant"])) if d["quantity"][i] == q}
        xs = [v for v in order if v in vals]
        ax.bar(range(len(xs)), [vals[v] for v in xs], color=[ACOL if v == "base" else ps.LIGHT for v in xs])
        ax.set_xticks(range(len(xs))); ax.set_xticklabels(xs, rotation=30, fontsize=6)
        ax.set_ylabel(QTY[q])
    return fig


def plot_f08(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 55, 1, 3)
    for ax, q in zip(axes, QTY):
        for name, mk in (("base", "o"), ("ref0", "s")):
            ii = [i for i in range(len(d["design"])) if d["design"][i] == name and d["quantity"][i] == q]
            ii.sort(key=lambda i: d["h"][i])
            ax.plot([d["h"][i] for i in ii], [d["value"][i] for i in ii], marker=mk, color=ACOL if name == "base" else ps.GREY, label=name)
        ax.set_xlabel("interface element size (mm)"); ax.set_ylabel(QTY[q]); ax.invert_xaxis()
    axes[0].legend(fontsize=6)
    return fig


def plot_f09(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 60, 1, 2)
    for ax, q in zip(axes, ("f1_p95_um", "f2_g7_loss_pct")):
        ii = [i for i in range(len(d["quantity"])) if d["quantity"][i] == q]
        x = np.array([d["h2.0"][i] for i in ii]); y = np.array([d["h1.4"][i] for i in ii])
        ax.scatter(x, y, s=10, color=ACOL)
        lo, hi = min(x.min(), y.min()), max(x.max(), y.max())
        ax.plot([lo, hi], [lo, hi], color=ps.GREY, lw=0.6, ls="--")
        ax.set_xlabel(f"{QTY[q]}, 2.0 mm"); ax.set_ylabel(f"{QTY[q]}, 1.4 mm")
    return fig


# ================================================================== BO
def _feasible_y(rows):
    Y = np.array([r["y"] for r in rows if r["ok"] and r["c"] <= 0], float)
    return Y


def _hv_curve(Y_seq, C_seq, ok_seq, ref, hv_best, n_max=64):
    import mobo
    out = []
    for n in range(1, min(n_max, len(Y_seq)) + 1):
        m = np.array(ok_seq[:n]) & (np.array(C_seq[:n]) <= 0)
        Y = np.array(Y_seq[:n])[m]
        out.append(mobo.hypervolume(Y, ref) / hv_best if len(Y) else 0.0)
    return out


def part_bo(fm) -> list[dict]:
    import mobo
    import stage_v2a as S
    items = []
    ref = _load("reference.json")
    if not ref:
        return items
    rrows = ref["rows"]
    refp = np.array(S.ref_point())
    bos = {s: _load(f"bo_s{s}.json") for s in SEEDS}
    bos = {s: b for s, b in bos.items() if b}
    # 已知最佳前沿：参考集 + 全部 BO 可行点
    allY = [np.array(r["y"]) for r in rrows if r["ok"] and r["c"] <= 0]
    allX = [np.array(r["x"]) for r in rrows if r["ok"] and r["c"] <= 0]
    allsrc = ["reference"] * len(allY)
    for s, b in bos.items():
        for x, y, c, ok in zip(b["x"], b["y"], b["c"], b["ok"]):
            if ok and c[0] <= 0:
                allY.append(np.array(y)); allX.append(np.array(x)); allsrc.append(f"bo_s{s}")
    allY, allX = np.array(allY), np.array(allX)
    pm = mobo.pareto_mask(allY)
    hv_best = mobo.hypervolume(allY, refp)
    # F10 参考集散点
    rows = []
    Yr = np.array([r["y"] for r in rrows if r["ok"]])
    pr = mobo.pareto_mask(np.array([r["y"] for r in rrows if r["ok"] and r["c"] <= 0])) if any(r["ok"] and r["c"] <= 0 for r in rrows) else []
    k = 0
    for r in rrows:
        if not r["ok"]:
            continue
        feas = r["c"] <= 0
        front = bool(feas and pr[k]) if feas else False
        k += int(feas)
        rows.append({"i": r["i"], "y1_log10_f1": r["y"][0], "y2_g7_abs_dsed": r["y"][1], "c_vm_minus_440": r["c"], "feasible": feas, "front": front})
    ps.publish_figure("V2A-F10", rows, plot_f10,
                      title=f"Reference set: {sum(r['front'] for r in rows)} non-dominated designs among {len(rows)} solved "
                            f"({sum(not r['feasible'] for r in rows)} violate the stress limit)",
                      caption=f"S4′ 参考集：参考池（种子 999）前 64 个可行设计全部 FE。横轴 log10(P95 微动 µm)，纵轴 Gruen 7 区 SED 相对完整股骨的偏离 |ΔSED|（2026-09-28 起的 f2）。"
                              f"实心为非支配前沿；叉号为违反柄应力约束者。超体积参考点 = 可行点各目标最大值 + 10% 范围 = ({refp[0]:.3f}, {refp[1]:.2f})。")
    # F11 敏感性（参考集 64 点上的 GP）
    X = np.array([r["x"] for r in rrows if r["ok"]]); Y = np.array([r["y"] for r in rrows if r["ok"]])
    try:                                                   # 最终版：用全部已解设计（含探针、热启动）拟合敏感性 GP
        import stage_v2a2 as S2
        Xs, Ys_, _, _ = S2.solved_dataset()
        if len(Xs) > len(X):
            X, Y = Xs, Ys_
    except Exception as e:                                 # noqa: BLE001
        print(f"  sensitivity: falling back to reference set ({e})", flush=True)
    srows = []
    if len(X) >= 20:
        for j, q in enumerate(("y1_log10_f1", "y2_g7_abs_dsed")):
            ST, STg = _sobol_total(X, Y[:, j])
            for v, val in zip(G.VARS, ST):
                srows.append({"objective": q, "level": "variable", "name": v, "ST": val})
            for g, val in STg.items():
                srows.append({"objective": q, "level": "group", "name": g, "ST": val})
        top = {q: max((r for r in srows if r["objective"] == q and r["level"] == "group"), key=lambda r: r["ST"])["name"]
               for q in ("y1_log10_f1", "y2_g7_abs_dsed")}
        ps.publish_figure("V2A-F11", srows, plot_f11,
                          title=f"Global sensitivity: micromotion is driven mostly by {top['y1_log10_f1']}, "
                                f"deviation of proximal SED from intact by {top['y2_g7_abs_dsed']}",
                          caption="在参考集（n = %d）上各拟合一个 GP（ARD Matérn 5/2，输入 [0,1]），在后验均值上用 Jansen 估计总效应指数 ST；"
                                  "组指数把组内变量一起替换。输入按单位立方体均匀分布，不可行区是 GP 外推，指数只作定性排序（Saltelli 2019）。" % len(X))
    if not bos:
        return items
    # F12 HV 比曲线
    rng = np.random.default_rng(0)
    Ys = [np.array(r["y"]) for r in rrows]; Cs = [r["c"] for r in rrows]; OKs = [r["ok"] for r in rrows]
    n_max = 64
    sob = []
    for _ in range(200):
        o = rng.permutation(len(Ys))
        sob.append(_hv_curve([Ys[i] for i in o], [Cs[i] for i in o], [OKs[i] for i in o], refp, hv_best, n_max))
    sob = np.array(sob)
    hrows = []
    for n in range(1, sob.shape[1] + 1):
        hrows.append({"series": "sobol_median", "n": n, "hv_ratio": float(np.median(sob[:, n - 1])),
                      "lo": float(np.percentile(sob[:, n - 1], 10)), "hi": float(np.percentile(sob[:, n - 1], 90))})
    final = {}
    for s, b in bos.items():
        cur = _hv_curve([np.array(y) for y in b["y"]], [c[0] for c in b["c"]], b["ok"], refp, hv_best, n_max)
        final[s] = cur[-1]
        hrows += [{"series": f"bo_s{s}", "n": n + 1, "hv_ratio": v, "lo": v, "hi": v} for n, v in enumerate(cur)]
    sob_final = float(np.median(sob[:, -1]))
    med = float(np.median(list(final.values())))
    ps.publish_figure("V2A-F12", hrows, plot_f12,
                      title=f"BO reaches a median {med:.2f} of the best-known hypervolume in {n_max} FE runs "
                            f"(same-budget Sobol median {sob_final:.2f})",
                      caption="超体积比 = 前 n 次评估中可行点的超体积 / 已知最佳前沿（参考集 + 全部 BO 可行点）的超体积。"
                              "Sobol 基线：把 64 点参考集随机排序 200 次，给中位与 10–90% 区间。BO：qLogNEHVI，初始 24 点 + 10 轮 × 4。")
    # F13 前沿叠图
    frows = [{"series": "best_known", "y1": float(y[0]), "y2": float(y[1])} for y in allY[pm]]
    for s, b in bos.items():
        Yb = np.array([y for y, c, ok in zip(b["y"], b["c"], b["ok"]) if ok and c[0] <= 0])
        if len(Yb):
            for y in Yb[mobo.pareto_mask(Yb)]:
                frows.append({"series": f"bo_s{s}", "y1": float(y[0]), "y2": float(y[1])})
    ps.publish_figure("V2A-F13", frows, plot_f13, title=f"BO fronts against the best-known front ({int(pm.sum())} points)",
                      caption="各种子 64 次评估后的非支配前沿与已知最佳前沿（灰）。")
    # F14 GP 校准：BO 全部数据训练，参考集测试
    Xtr = np.vstack([np.array(b["x"])[np.array(b["ok"])] for b in bos.values()])
    Ytr = np.vstack([np.array(b["y"])[np.array(b["ok"])] for b in bos.values()])
    crow, cover90 = _calibration(Xtr, Ytr, X, Y)
    ps.publish_figure("V2A-F14", crow, plot_f14,
                      title=f"GP trained on BO data covers {100 * np.mean(list(cover90.values())):.0f}% of the independent reference set "
                            f"at the nominal 90% level",
                      caption=f"训练：3 个 BO 种子的全部可行评估（n = {len(Xtr)}）；测试：64 点参考集（n = {len(X)}，与训练集独立的 Sobol 池）。"
                              "上：名义覆盖率对实际覆盖率（对角线 = 完美校准）；下：预测均值（带 90% 区间）对 FE 值。")
    # F15 前沿设计图册 + T07
    idx = np.nonzero(pm)[0]
    order = idx[np.argsort(allY[idx, 0])]
    pick = order if len(order) <= 6 else order[np.linspace(0, len(order) - 1, 6).round().astype(int)]
    arows, trows = [], []
    for k, i in enumerate(pick):
        dd = G.from_unit(allX[i]); st = G.Stem3D(**dd)
        pl = G.template(st, fm)
        sec = G.unit_section(dd, 120) * math.sqrt(pl["A0"])
        arows += [{"k": k, "kind": "section", "x": float(x), "y": float(y)} for x, y in sec]
        s = np.linspace(0, st.L, 40)
        arows += [{"k": k, "kind": "area", "x": float(si), "y": float(pl["A0"] * st.area_ratio(si))} for si in s]
        arows.append({"k": k, "kind": "meta", "x": float(st.alpha), "y": float(pl["A0"])})
        trows.append({"k": k, "source": allsrc[i], **{v: round(dd[v], 3) for v in G.VARS}, "A0_mm2": round(pl["A0"], 1),
                      "f1_um": round(10 ** allY[i, 0], 2), "g7_abs_dsed_pct": round(allY[i, 1], 2)})
    ps.publish_figure("V2A-F15", arows, plot_f15, title=f"{len(pick)} designs spread along the best-known front",
                      caption="沿前沿按 f1 从小到大等距取点（最多 6 个）。上：肩部截面（按模板化尺寸，内侧向右、前方向上）；下：截面积沿长度。"
                              "面板标题给插入角与肩部面积。")
    ps.publish_table("V2A-T07", trows, title="Designs on the best-known front", caption="变量为物理量；f1 为 P95 微动，g7 为 Gruen 7 区 SED 相对完整股骨的偏离 |ΔSED|。")
    trows6 = [{"series": f"bo_s{s}", "final_hv_ratio": round(v, 3),
               "n_eval": len(bos[s]["x"]), "n_ok": int(sum(bos[s]["ok"]))} for s, v in final.items()]
    trows6.append({"series": "sobol (median of 200 orders)", "final_hv_ratio": round(sob_final, 3), "n_eval": n_max, "n_ok": ""})
    ps.publish_table("V2A-T06", trows6, title="BO against the same-budget Sobol baseline",
                     caption="超体积比的分母为已知最佳前沿；参考点见 V2A-F10。")
    items.append({"id": "V2A-A10", "measured": f"median {med:.3f} (seeds " + ", ".join(f"{v:.3f}" for v in final.values()) + ")",
                  "status": "PASS" if med >= 0.90 else "FAIL", "note": "" if med >= 0.90 else "BO 中位超体积比低于 0.90"})
    n_beat = sum(v > sob_final for v in final.values())
    items.append({"id": "V2A-A11", "measured": f"{n_beat}/{len(final)} above Sobol median {sob_final:.3f}",
                  "status": "PASS" if n_beat == len(final) == 3 else ("FAIL" if len(final) == 3 else "PENDING"),
                  "note": "" if n_beat == len(final) else "有种子未超过 Sobol 基线"})
    cv = np.mean(list(cover90.values()))
    items.append({"id": "V2A-A12", "measured": ", ".join(f"{k} {100 * v:.0f}%" for k, v in cover90.items()),
                  "status": "PASS" if 0.80 <= cv <= 0.97 else "FAIL", "note": "" if 0.80 <= cv <= 0.97 else "覆盖率不在 0.80–0.97"})
    return items


def _sobol_total(X, y, n_base=4096, seed=0):
    """GP 后验均值上的 Jansen 总效应：逐变量与按组（组内变量一起替换）。"""
    import torch
    import stage_v2a as S
    gp = S._fit_gp_unit(torch.as_tensor(X), torch.as_tensor(y))
    rng = np.random.default_rng(seed)
    A, B = rng.random((n_base, X.shape[1])), rng.random((n_base, X.shape[1]))

    def f(Z):
        with torch.no_grad():
            return gp.posterior(torch.as_tensor(Z)).mean.numpy().ravel()
    fA, fB = f(A), f(B)
    V = np.var(np.r_[fA, fB])

    def st(cols):
        ABi = A.copy(); ABi[:, cols] = B[:, cols]
        return float(0.5 * np.mean((fA - f(ABi)) ** 2) / V)
    ST = [st([i]) for i in range(X.shape[1])]
    STg = {g: st([G.VARS.index(v) for v in vs]) for g, vs in G.GROUPS.items()}
    return ST, STg


def _calibration(Xtr, Ytr, Xte, Yte):
    import torch
    from scipy.stats import norm
    import stage_v2a as S
    rows, cover90 = [], {}
    for j, q in enumerate(("y1_log10_f1", "y2_g7_abs_dsed")):
        gp = S._fit_gp_unit(torch.as_tensor(Xtr), torch.as_tensor(Ytr[:, j]))
        with torch.no_grad():
            post = gp.posterior(torch.as_tensor(Xte), observation_noise=True)
            mu = post.mean.numpy().ravel(); sd = post.variance.sqrt().numpy().ravel()
        z = np.abs(Yte[:, j] - mu) / np.maximum(sd, 1e-12)
        for p in np.linspace(0.05, 0.95, 19):
            rows.append({"objective": q, "kind": "calib", "nominal": float(p), "observed": float(np.mean(z <= norm.ppf(0.5 + p / 2))), "fe": "", "mu": "", "sd": ""})
        for yt, m_, s_ in zip(Yte[:, j], mu, sd):
            rows.append({"objective": q, "kind": "point", "nominal": "", "observed": "", "fe": float(yt), "mu": float(m_), "sd": float(s_)})
        cover90[q] = float(np.mean(z <= norm.ppf(0.95)))
    return rows, cover90


def plot_f10(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 70)
    feas = [str(v) == "True" for v in d["feasible"]]; front = [str(v) == "True" for v in d["front"]]
    x, y = np.array(d["y1_log10_f1"], float), np.array(d["y2_g7_abs_dsed"], float)
    ax.scatter(x[np.array(feas) & ~np.array(front)], y[np.array(feas) & ~np.array(front)], s=10, facecolors="none", edgecolors=ACOL, label="feasible")
    ax.scatter(x[np.array(front)], y[np.array(front)], s=14, color=ACOL, label="non-dominated")
    ax.scatter(x[~np.array(feas)], y[~np.array(feas)], s=12, marker="x", color=ps.GREY, label="stress limit violated")
    ax.set_xlabel("log10 micromotion P95 (µm)"); ax.set_ylabel("Gruen 7 |ΔSED| vs intact (%)"); ax.legend(fontsize=6)
    return fig


def plot_f11(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 2, gridspec_kw={"width_ratios": [3, 1.2]})
    objs = ("y1_log10_f1", "y2_g7_abs_dsed")
    for k, (lev, ax) in enumerate((("variable", axes[0]), ("group", axes[1]))):
        names = [d["name"][i] for i in range(len(d["name"])) if d["level"][i] == lev and d["objective"][i] == objs[0]]
        xs = np.arange(len(names))
        for j, (q, col) in enumerate(zip(objs, (ACOL, ps.GREY))):
            vals = [d["ST"][i] for i in range(len(d["name"])) if d["level"][i] == lev and d["objective"][i] == q]
            ax.bar(xs + (j - 0.5) * 0.38, vals, width=0.38, color=col, label=("micromotion" if j == 0 else "|ΔSED|"))
        ax.set_xticks(xs); ax.set_xticklabels(names, rotation=45, ha="right", fontsize=6)
        ax.set_ylabel("total-effect Sobol index")
    axes[0].legend(fontsize=6)
    return fig


def plot_f12(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 70)
    ser = sorted(set(d["series"]))
    for s in ser:
        ii = [i for i in range(len(d["series"])) if d["series"][i] == s]
        n = [d["n"][i] for i in ii]; v = [d["hv_ratio"][i] for i in ii]
        if s == "sobol_median":
            ax.fill_between(n, [d["lo"][i] for i in ii], [d["hi"][i] for i in ii], color=ps.LIGHT, alpha=0.6, lw=0)
            ax.plot(n, v, color=ps.GREY, label="Sobol (median, 10–90%)")
        else:
            ax.plot(n, v, color=ACOL, lw=0.9, alpha=0.9, label=s)
    ax.axhline(0.9, color="black", lw=0.6, ls="--")
    ax.set_xlabel("FE evaluations"); ax.set_ylabel("hypervolume / best-known"); ax.set_ylim(0, 1.02); ax.legend(fontsize=6)
    return fig


def plot_f13(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 70)
    for s, mk, col in (("best_known", "o", ps.LIGHT), ("bo_s0", "s", ACOL), ("bo_s1", "^", "#56B4E9"), ("bo_s2", "D", "#E69F00")):
        ii = [i for i in range(len(d["series"])) if d["series"][i] == s]
        if ii:
            pts = sorted((d["y1"][i], d["y2"][i]) for i in ii)
            ax.plot(*zip(*pts), marker=mk, ms=3, lw=0.8 if s != "best_known" else 2.5, color=col, label=s)
    ax.set_xlabel("log10 micromotion P95 (µm)"); ax.set_ylabel("Gruen 7 |ΔSED| vs intact (%)"); ax.legend(fontsize=6)
    return fig


def plot_f14(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 110, 2, 2)
    for j, q in enumerate(("y1_log10_f1", "y2_g7_abs_dsed")):
        ii = [i for i in range(len(d["objective"])) if d["objective"][i] == q and d["kind"][i] == "calib"]
        axes[0, j].plot([d["nominal"][i] for i in ii], [d["observed"][i] for i in ii], marker="o", ms=2.5, color=ACOL)
        axes[0, j].plot([0, 1], [0, 1], color=ps.GREY, lw=0.6, ls="--")
        axes[0, j].set_xlabel("nominal coverage"); axes[0, j].set_ylabel("observed coverage"); axes[0, j].set_title(q, fontsize=7)
        ii = [i for i in range(len(d["objective"])) if d["objective"][i] == q and d["kind"][i] == "point"]
        fe = np.array([d["fe"][i] for i in ii], float); mu = np.array([d["mu"][i] for i in ii], float)
        sd = np.array([d["sd"][i] for i in ii], float)
        axes[1, j].errorbar(fe, mu, yerr=1.645 * sd, fmt="o", ms=2.5, color=ACOL, ecolor=ps.LIGHT, lw=0.6)
        lo, hi = min(fe.min(), mu.min()), max(fe.max(), mu.max())
        axes[1, j].plot([lo, hi], [lo, hi], color=ps.GREY, lw=0.6, ls="--")
        axes[1, j].set_xlabel("FE value"); axes[1, j].set_ylabel("GP prediction (90% interval)")
    return fig


def plot_f15(csv_path):
    d = ps.read_csv(csv_path)
    ks = sorted(set(d["k"]))
    fig, axes = ps.new_figure("double", 80, 2, len(ks))
    axes = np.atleast_2d(axes).reshape(2, len(ks))
    for c, k in enumerate(ks):
        ii = [i for i in range(len(d["k"])) if d["k"][i] == k]
        sec = np.array([[d["x"][i], d["y"][i]] for i in ii if d["kind"][i] == "section"])
        area = np.array([[d["x"][i], d["y"][i]] for i in ii if d["kind"][i] == "area"])
        meta = [(d["x"][i], d["y"][i]) for i in ii if d["kind"][i] == "meta"][0]
        axes[0, c].fill(sec[:, 0], sec[:, 1], fc="#9BB8D3", ec="#1f4e79", lw=0.6)
        axes[0, c].plot(sec[:, 0], -sec[:, 1], color="#D55E00", lw=0.5, ls=(0, (2, 1.5)))
        axes[0, c].set_aspect("equal"); axes[0, c].set_xlim(-18, 18); axes[0, c].set_ylim(-14, 14); axes[0, c].axis("off")
        axes[0, c].set_title(f"#{k}: α {meta[0]:.0f}°, A0 {meta[1]:.0f} mm²", fontsize=6)
        axes[1, c].plot(area[:, 0], area[:, 1], color=ACOL)
        axes[1, c].set_xlabel("s (mm)", fontsize=6); axes[1, c].set_ylim(0, None)
        if c == 0:
            axes[1, c].set_ylabel("section area (mm²)")
    return fig


# ================================================================== 中期快照（BO 未完成时）
def part_bo_interim() -> dict:
    """从队列直接读 BO 已完成的评估（按种子、按完成先后），与同 n 的 Sobol 重抽基线比超体积比；出两张附加图
    （V2A-X01 超体积比、V2A-X02 前沿，未登记，只出现在报告末尾）。"""
    import re
    import mobo
    import problem_v2a as PB
    import stage_v2a as S
    ref = _load("reference.json")
    if not ref:
        return {}
    rrows = ref["rows"]
    refp = np.array(S.ref_point())
    seeds = {}
    n_pending = {}
    for r in _scan(stage="bo"):
        m = re.match(r"qnehvi_s(\d+)_r(\d+)", r["spec"].get("tag", ""))
        if not m:
            continue
        sd, rd = int(m[1]), int(m[2])
        if r["state"] not in ("DONE", "FAILED"):
            n_pending[sd] = n_pending.get(sd, 0) + 1
            continue
        d = J.QROOT / r["job_id"]
        t = max((d / f).stat().st_mtime for f in ("DONE", "FAILED.json") if (d / f).exists())
        y, c, ok = PB.objectives(r["result"])
        seeds.setdefault(sd, []).append({"round": rd, "t": t, "y": y, "c": c, "ok": ok})
    for sd in seeds:
        seeds[sd].sort(key=lambda e: (e["round"], e["t"]))
    allY = [np.array(x["y"]) for x in rrows if x["ok"] and x["c"] <= 0]
    for ev in seeds.values():
        allY += [np.array(e["y"]) for e in ev if e["ok"] and e["c"] <= 0]
    allY = np.array(allY)
    hv_best = mobo.hypervolume(allY, refp)
    rng = np.random.default_rng(0)
    Ys = [np.array(x["y"]) for x in rrows]; Cs = [x["c"] for x in rrows]; OKs = [x["ok"] for x in rrows]
    sob = np.array([_hv_curve([Ys[i] for i in o], [Cs[i] for i in o], [OKs[i] for i in o], refp, hv_best, 64)
                    for o in (rng.permutation(len(Ys)) for _ in range(200))])
    rows, summ = [], {}
    for n in range(1, sob.shape[1] + 1):
        rows.append({"series": "sobol_median", "n": n, "hv_ratio": float(np.median(sob[:, n - 1])),
                     "lo": float(np.percentile(sob[:, n - 1], 10)), "hi": float(np.percentile(sob[:, n - 1], 90))})
    for sd, ev in sorted(seeds.items()):
        cur = _hv_curve([np.array(e["y"]) for e in ev], [e["c"] for e in ev], [e["ok"] for e in ev], refp, hv_best, 64)
        rows += [{"series": f"bo_s{sd}", "n": n + 1, "hv_ratio": v, "lo": v, "hi": v} for n, v in enumerate(cur)]
        nn = len(cur)
        summ[f"bo_s{sd}"] = {"n_done": len(ev), "n_failed": sum(not e["ok"] for e in ev), "rounds_done": max(e["round"] for e in ev),
                             "n_pending": n_pending.get(sd, 0), "hv_ratio_now": cur[-1] if cur else None,
                             "sobol_median_same_n": float(np.median(sob[:, nn - 1])) if nn else None}
    if seeds:
        ps.publish_figure("V2A-X01", rows, plot_f12,
                          title="Interim (paused run): hypervolume ratio of each BO seed so far against the same-budget Sobol baseline",
                          caption="中期快照：BO 尚未完成，分母为目前已知最佳前沿（参考集 + 目前全部 BO 可行点），最终报告会随新点变化。"
                                  "BO 的前 24 次为初始 Sobol 点（与基线同类），第 25 次起才是 qLogNEHVI 选点。")
        frows = [{"series": "best_known", "y1": float(y[0]), "y2": float(y[1])} for y in allY[mobo.pareto_mask(allY)]]
        for sd, ev in seeds.items():
            Yb = np.array([e["y"] for e in ev if e["ok"] and e["c"] <= 0])
            if len(Yb):
                frows += [{"series": f"bo_s{sd}", "y1": float(y[0]), "y2": float(y[1])} for y in Yb[mobo.pareto_mask(Yb)]]
        ps.publish_figure("V2A-X02", frows, plot_f13, title="Interim (paused run): BO fronts so far against the best-known front",
                          caption="中期快照：各种子目前的非支配前沿与目前已知最佳前沿（灰）。")
    summ["hv_ref_point"] = refp.tolist()
    (J.RESULTS / "interim_bo.json").write_text(json.dumps(summ, indent=1, default=float))
    return summ
