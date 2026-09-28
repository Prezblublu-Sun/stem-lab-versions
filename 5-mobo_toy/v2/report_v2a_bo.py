"""V2A 报告的 BO 部分（最终版，替换 report_v2a_fe.part_bo）：合并原设计空间（L 40–90）的 BO 种子 0、
扩展空间（L 20–90，2026-09-28 12:30 起）的短柄探针与热启动 BO。

数据来源：队列里全部已解设计（stage_v2a2.solved_dataset，去重，新单位坐标）、results/bo_s0.json（已重映射）、
results/bo_warm_s{0,1}.json、results/probe_short.json、results/reference.json。

口径
* BO 对 Sobol（F12、T06、A10/A11）：只有种子 0 跑满 64 次；种子 1、2 按用户 12:30 的决定停在 16 / 2 次，只画部分曲线。
  分母 = 原设计空间（阶段 ref/bo 的设计）的已知最佳超体积，保证与 Sobol 基线（参考集重排）同一空间。
* 已知最佳前沿（F13、F15、T07）：全部已解设计，含探针与热启动。
* 热启动 BO 的效果（T06）：热启动集（全部此前已解设计）的超体积，对加入其 32 次评估后的超体积；分母为全部数据的已知最佳。
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
import report_v2a_fe as RF  # noqa: E402

plt = ps.plt
ACOL = ps.DORR["A"]
STYLE = {"best_known": ("o", ps.LIGHT, 2.5), "best_known_original_box": ("o", ps.GREY, 1.2), "bo_s0": ("s", ACOL, 0.8),
         "warm_s0": ("^", "#56B4E9", 0.8), "warm_s1": ("D", "#E69F00", 0.8)}


def _source(job_id: str) -> str:
    for k in ("ref_", "bo_", "probe_", "warm_", "e2e_", "signs_", "conv_"):
        if job_id.startswith(k):
            return {"ref_": "reference", "bo_": "bo", "probe_": "probe", "warm_": "warm", "e2e_": "base", "signs_": "base",
                    "conv_": "reference"}[k]
    return "other"


def _seed_curves() -> dict:
    """各 BO 种子按完成先后的 (y, c, ok) 序列（从队列读，种子 0 与 bo_s0.json 一致）。"""
    import re
    seeds = {}
    for r in RF._scan(stage="bo"):
        m = re.match(r"qnehvi_s(\d+)_r(\d+)", r["spec"].get("tag", ""))
        if not m or r["state"] not in ("DONE", "FAILED"):
            continue
        d = J.QROOT / r["job_id"]
        t = max((d / f).stat().st_mtime for f in ("DONE", "FAILED.json") if (d / f).exists())
        import problem_v2a as PB
        y, c, ok = PB.objectives(r["result"])
        seeds.setdefault(int(m[1]), []).append((int(m[2]), t, y, c, ok))
    return {s: sorted(v, key=lambda e: (e[0], e[1])) for s, v in seeds.items()}


def part_bo(fm) -> list[dict]:
    import mobo
    import stage_v2a as S
    import stage_v2a2 as S2
    items = []
    ref = RF._load("reference.json")
    if not ref:
        return items
    rrows = ref["rows"]
    refp = np.array(S.ref_point())
    Xall, Yall, Call, idsall = S2.solved_dataset()
    src = np.array([_source(j) for j in idsall])
    feas = Call[:, 0] <= 0
    Xa, Ya, ida, srca = Xall[feas], Yall[feas], [j for j, f in zip(idsall, feas) if f], src[feas]
    pm_all = mobo.pareto_mask(Ya)
    hv_all = mobo.hypervolume(Ya, refp)
    old = np.isin(srca, ["reference", "bo", "base"])
    hv_old = mobo.hypervolume(Ya[old], refp)
    pm_old = mobo.pareto_mask(Ya[old])

    # ---- F12：种子 0（完整）与种子 1、2（部分）对 Sobol 基线，分母 = 原空间已知最佳
    rng = np.random.default_rng(0)
    Ys = [np.array(x["y"]) for x in rrows]; Cs = [x["c"] for x in rrows]; OKs = [x["ok"] for x in rrows]
    sob = np.array([RF._hv_curve([Ys[i] for i in o], [Cs[i] for i in o], [OKs[i] for i in o], refp, hv_old, 64)
                    for o in (rng.permutation(len(Ys)) for _ in range(200))])
    rows = [{"series": "sobol_median", "n": n, "hv_ratio": float(np.median(sob[:, n - 1])),
             "lo": float(np.percentile(sob[:, n - 1], 10)), "hi": float(np.percentile(sob[:, n - 1], 90))} for n in range(1, 65)]
    curves = _seed_curves()
    final, sob_same = {}, {}
    for sd, ev in sorted(curves.items()):
        cur = RF._hv_curve([np.array(e[2]) for e in ev], [e[3] for e in ev], [e[4] for e in ev], refp, hv_old, 64)
        rows += [{"series": f"bo_s{sd}", "n": n + 1, "hv_ratio": v, "lo": v, "hi": v} for n, v in enumerate(cur)]
        final[sd] = cur[-1]; sob_same[sd] = float(np.median(sob[:, len(cur) - 1]))
    s0 = final.get(0, float("nan")); s0n = len(curves.get(0, []))
    ps.publish_figure("V2A-F12", rows, RF.plot_f12,
                      title=f"BO seed 0 reaches {s0:.2f} of the best-known hypervolume of the original design space in {s0n} FE runs; "
                            f"same-budget Sobol median {sob_same.get(0, float('nan')):.2f}",
                      caption="超体积比 = 前 n 次评估中可行点的超体积 / 原设计空间（L 40–90 mm；参考集 + 全部 BO 种子的可行点）的已知最佳。"
                              "Sobol 基线：64 点参考集随机排序 200 次，中位与 10–90% 区间。种子 0 跑满 64 次；种子 1、2 按用户 2026-09-28 12:30 的决定"
                              "分别停在 16 与 2 次，只画到停止处。BO 的前 24 次是初始 Sobol 点。")

    # ---- T06
    trows = []
    for sd in sorted(curves):
        ev = curves[sd]
        trows.append({"series": f"bo_s{sd} (original box, L 40–90)", "n_eval": len(ev), "n_ok": int(sum(e[4] for e in ev)),
                      "hv_ratio_vs_original_best": round(final[sd], 3), "sobol_median_same_n": round(sob_same[sd], 3),
                      "note": "complete" if len(ev) >= 64 else "stopped 12:30 (user decision)"})
    trows.append({"series": "sobol (median of 200 orders of the 64-point reference set)", "n_eval": 64, "n_ok": int(sum(OKs)),
                  "hv_ratio_vs_original_best": round(float(np.median(sob[:, -1])), 3), "sobol_median_same_n": "", "note": ""})
    warm = {s: RF._load(f"bo_warm_s{s}.json") for s in (0, 1)}
    warm = {s: w for s, w in warm.items() if w}
    for s, w in warm.items():
        wid = set(w.get("warm_start_ids", []))
        mask_ws = np.array([j in wid for j in ida])
        hv_ws = mobo.hypervolume(Ya[mask_ws], refp) if mask_ws.any() else float("nan")
        Yw = np.array([y for y, c, ok in zip(w["y"], w["c"], w["ok"]) if ok and c[0] <= 0])
        hv_after = mobo.hypervolume(np.vstack([Ya[mask_ws], Yw]) if len(Yw) else Ya[mask_ws], refp)
        n_front = int(sum(1 for j, p in zip(ida, pm_all) if p and j.startswith("warm_") and f"_s{s}_" in j))
        trows.append({"series": f"warm-start BO seed {s} (extended box, L 20–90)", "n_eval": len(w["x"]), "n_ok": int(sum(w["ok"])),
                      "hv_ratio_vs_original_best": f"HV/best(all): {hv_ws / hv_all:.3f} → {hv_after / hv_all:.3f}",
                      "sobol_median_same_n": "", "note": f"warm start on {w['warm_start_n']} solved designs; {n_front} points on the final front"})
    ps.publish_table("V2A-T06", trows, title="BO against the same-budget Sobol baseline; warm-started BO in the extended space",
                     caption="原空间的比较只有种子 0 完整。热启动 BO 的两列给出加入其评估前后的全数据超体积比（分母为全部已解设计的已知最佳）。")

    # ---- F13 前沿叠图
    frows = [{"series": "best_known", "y1": float(y[0]), "y2": float(y[1])} for y in Ya[pm_all]]
    frows += [{"series": "best_known_original_box", "y1": float(y[0]), "y2": float(y[1])} for y in Ya[old][pm_old]]
    if 0 in curves:
        Y0 = np.array([e[2] for e in curves[0] if e[4] and e[3] <= 0])
        frows += [{"series": "bo_s0", "y1": float(y[0]), "y2": float(y[1])} for y in Y0[mobo.pareto_mask(Y0)]]
    for s, w in warm.items():
        Yw = np.array([y for y, c, ok in zip(w["y"], w["c"], w["ok"]) if ok and c[0] <= 0])
        if len(Yw):
            frows += [{"series": f"warm_s{s}", "y1": float(y[0]), "y2": float(y[1])} for y in Yw[mobo.pareto_mask(Yw)]]
    n_new = int(sum(1 for j, p in zip(ida, pm_all) if p and _source(j) in ("probe", "warm")))
    ps.publish_figure("V2A-F13", frows, plot_f13,
                      title=f"Best-known front has {int(pm_all.sum())} points, {n_new} of them from the extended-length campaign "
                            f"(hypervolume {hv_all / hv_old:.3f}× the original-space best)",
                      caption="灰实线：全部已解设计的非支配前沿；灰细线：只用原空间（L 40–90）设计的前沿；方块：种子 0 的 64 次评估自身的前沿；"
                              "三角/菱形：热启动 BO 两个种子各自 32 次评估的前沿。")

    # ---- F14 校准：训练 = 种子 0 + 热启动 BO 的评估（都不含参考集），测试 = 参考集
    b0 = RF._load("bo_s0.json")
    Xtr, Ytr = [], []
    if b0:
        Xtr += [x for x, ok in zip(b0["x"], b0["ok"]) if ok]; Ytr += [y for y, ok in zip(b0["y"], b0["ok"]) if ok]
    for w in warm.values():
        Xtr += [x for x, ok in zip(w["x"], w["ok"]) if ok]; Ytr += [y for y, ok in zip(w["y"], w["ok"]) if ok]
    Xte = np.array([r["x"] for r in rrows if r["ok"]]); Yte = np.array([r["y"] for r in rrows if r["ok"]])
    cover90 = {}
    if len(Xtr) >= 20:
        crow, cover90 = RF._calibration(np.array(Xtr), np.array(Ytr), Xte, Yte)
        ps.publish_figure("V2A-F14", crow, RF.plot_f14,
                          title=f"GP trained on {len(Xtr)} BO evaluations covers {100 * np.mean(list(cover90.values())):.0f}% of the "
                                f"independent reference set at the nominal 90% level",
                          caption="训练：种子 0 的 64 次评估 + 热启动 BO 的评估（选点时用过参考集，但这些点本身不在参考集里）；"
                                  "测试：64 点参考集。上：名义覆盖率对实际覆盖率；下：预测均值（90% 区间）对 FE 值。")

    # ---- F15 / T07 前沿设计
    idx = np.nonzero(pm_all)[0]
    order = idx[np.argsort(Ya[idx, 0])]
    pick = order if len(order) <= 6 else order[np.linspace(0, len(order) - 1, 6).round().astype(int)]
    arows, t7 = [], []
    for k, i in enumerate(pick):
        dd = G.from_unit(Xa[i]); st = G.Stem3D(**dd)
        pl = G.template(st, fm)
        sec = G.unit_section(dd, 120) * math.sqrt(pl["A0"])
        arows += [{"k": k, "kind": "section", "x": float(x), "y": float(y)} for x, y in sec]
        s = np.linspace(0, st.L, 40)
        arows += [{"k": k, "kind": "area", "x": float(si), "y": float(pl["A0"] * st.area_ratio(si))} for si in s]
        arows.append({"k": k, "kind": "meta", "x": float(st.alpha), "y": float(pl["A0"])})
        t7.append({"k": k, "source": srca[i], **{v: round(dd[v], 3) for v in G.VARS}, "A0_mm2": round(pl["A0"], 1),
                   "f1_um": round(10 ** Ya[i, 0], 2), "g7_abs_dsed_pct": round(Ya[i, 1], 2)})
    Lf = [20 + 70 * Xa[i][0] for i in idx]
    ps.publish_figure("V2A-F15", arows, RF.plot_f15,
                      title=f"{len(pick)} designs along the best-known front; front lengths span {min(Lf):.0f}–{max(Lf):.0f} mm",
                      caption="沿前沿按 f1 从小到大等距取点（最多 6 个）。上：肩部截面（按模板化尺寸，内侧向右、前方向上，橙虚线为前后镜像）；"
                              "下：截面积沿长度。面板标题给插入角与肩部面积。")
    ps.publish_table("V2A-T07", t7, title="Designs on the best-known front", caption="变量为物理量；f1 为 P95 微动，g7 为 Gruen 7 区 |ΔSED|。")

    # ---- F16 目标对长度；T08 探针
    probe = RF._load("probe_short.json")
    L_all = 20 + 70 * Xall[:, 0]
    front_ids = {ida[i] for i in idx}
    r16 = [{"job_id": j, "source": s, "L": float(l), "f1_um": float(10 ** y[0]), "dsed_pct": float(y[1]), "feasible": bool(f),
            "front": j in front_ids} for j, s, l, y, f in zip(idsall, src, L_all, Yall, feas)]
    short = [r for r in r16 if r["L"] < 40]
    med_short = np.median([r["f1_um"] for r in short]) if short else float("nan")
    med_mid = np.median([r["f1_um"] for r in r16 if 50 <= r["L"] < 65])
    ps.publish_figure("V2A-F16", r16, plot_f16,
                      title=f"Micromotion vs length: median {med_short:.1f} µm below 40 mm against {med_mid:.1f} µm at 50–65 mm; "
                            f"front designs lie at {min(Lf):.0f}–{max(Lf):.0f} mm",
                      caption="全部已解设计（2.0 mm 网格）的两个目标对柄长度，按来源着色：参考集与 BO 种子（L 40–90）、"
                              "20–40 mm 探针、热启动 BO（L 20–90）。黑圈为已知最佳前沿上的点。")
    if probe:
        t8 = []
        for lo in (20.0, 25.0, 30.0, 35.0):
            rs = [r for r in probe["rows"] if lo <= r["design"]["L"] < lo + 5]
            ok = [r for r in rs if r["ok"]]
            t8.append({"L_bin": f"{lo:.0f}–{lo + 5:.0f} mm", "n": len(rs), "n_ok": len(ok),
                       "f1_median_um": round(float(np.median([r["f1_um"] for r in ok])), 1) if ok else "",
                       "f1_min_um": round(float(min(r["f1_um"] for r in ok)), 1) if ok else "",
                       "dsed_median_pct": round(float(np.median([r["dsed_pct"] for r in ok])), 1) if ok else "",
                       "dsed_min_pct": round(float(min(r["dsed_pct"] for r in ok)), 1) if ok else "",
                       "A0_median_mm2": round(float(np.median([r["A0"] for r in ok if r["A0"]])), 0) if ok else "",
                       "failed": ", ".join(sorted({r["failed"]["level"] for r in rs if r["failed"]})) or "none"})
        ps.publish_table("V2A-T08", t8, title="Short-stem probe (20–40 mm) by length bin",
                         caption="每 5 mm 取 8 个可行的随机设计（其余 10 个变量 Sobol），生产网格。")

    # ---- 验收
    if 0 in final:
        ok10 = final[0] >= 0.90
        items.append({"id": "V2A-A10", "measured": f"seed 0: {final[0]:.3f} at n = {s0n} (single complete seed; seeds 1, 2 stopped at "
                      f"{len(curves.get(1, []))} / {len(curves.get(2, []))} evaluations)", "status": "PASS" if ok10 else "FAIL",
                      "note": "" if ok10 else "种子 0 的超体积比低于 0.90"})
        above = [sd for sd in final if len(curves[sd]) >= 64 and final[sd] > sob_same[sd]]
        items.append({"id": "V2A-A11", "measured": f"{len(above)} of 1 complete seed above the Sobol median "
                      f"(seed 0: {final[0]:.3f} vs {sob_same[0]:.3f}); criterion needs 3 seeds",
                      "status": "FAIL", "approved": "2026-09-28",
                      "note": "用户 2026-09-28 12:30 决定停掉种子 1、2，把机时转给 20–40 mm 探针与扩展空间的热启动 BO（中期结果：BO 与 Sobol 持平，"
                              "64 个随机设计已达已知最佳的 98%）。3/3 的判据因此不可判，按 FAIL-APPROVED 记。"})
    if cover90:
        cv = float(np.mean(list(cover90.values())))
        items.append({"id": "V2A-A12", "measured": ", ".join(f"{k} {100 * v:.0f}%" for k, v in cover90.items()),
                      "status": "PASS" if 0.80 <= cv <= 0.97 else "FAIL", "note": "" if 0.80 <= cv <= 0.97 else "覆盖率不在 0.80–0.97"})
    (J.RESULTS / "final_bo_summary.json").write_text(json.dumps(
        {"hv_all": hv_all, "hv_original_box": hv_old, "n_solved": int(len(Xall)), "n_feasible": int(feas.sum()), "n_front": int(pm_all.sum()),
         "front_L_range": [min(Lf), max(Lf)], "seed_final_hv_ratio": final, "sobol_same_n": sob_same, "coverage90": cover90,
         "n_by_source": {k: int((src == k).sum()) for k in set(src)}}, indent=1, default=float))
    return items


def plot_f13(csv_path):
    d = ps.read_csv(csv_path)
    fig, ax = ps.new_figure("single", 72)
    for s, (mk, col, lw) in STYLE.items():
        ii = [i for i in range(len(d["series"])) if d["series"][i] == s]
        if ii:
            pts = sorted((d["y1"][i], d["y2"][i]) for i in ii)
            ax.plot(*zip(*pts), marker=mk, ms=3, lw=lw, color=col, label=s.replace("_", " "))
    ax.set_xlabel("log10 micromotion P95 (µm)"); ax.set_ylabel("Gruen 7 |ΔSED| vs intact (%)"); ax.legend(fontsize=5.5)
    return fig


def plot_f16(csv_path):
    d = ps.read_csv(csv_path)
    fig, axes = ps.new_figure("double", 62, 1, 2)
    L = np.array(d["L"], float); f1 = np.array(d["f1_um"], float); ds = np.array(d["dsed_pct"], float)
    src = np.array(d["source"]); front = np.array([str(v) == "True" for v in d["front"]])
    cols = {"reference": ps.GREY, "bo": ACOL, "base": ps.GREY, "probe": "#D55E00", "warm": "#E69F00", "other": ps.LIGHT}
    for ax, y, lab in ((axes[0], f1, "micromotion P95 (µm)"), (axes[1], ds, "Gruen 7 |ΔSED| vs intact (%)")):
        for s in ("reference", "bo", "probe", "warm"):
            m = src == s
            if m.any():
                ax.scatter(L[m], y[m], s=9, color=cols[s], lw=0, alpha=0.8, label=s)
        ax.scatter(L[front], y[front], s=26, facecolors="none", edgecolors="black", lw=0.7, label="on front")
        ax.axvline(40, color=ps.LIGHT, lw=0.6, ls=":")
        ax.set_xlabel("stem length L (mm)"); ax.set_ylabel(lab); ax.set_xlim(18, 92)
    axes[0].set_yscale("log"); ps.plain_log(axes[0], "y")
    axes[0].legend(fontsize=5.5)
    return fig
