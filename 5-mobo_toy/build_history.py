"""把项目全过程总结扩写为"叙述 + 数据"版：叙述取自 PROJECT_HISTORY_base.md，各节末尾插入由结果文件自动生成的表与图。

    python build_history.py        → PROJECT_HISTORY_2026-09-29.md（再用 v2/build_doc.py 出 PDF）
所有表格数字直接读自报告 CSV、队列导出与结果 JSON，不手抄。
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import re
import statistics as st

ROOT = pathlib.Path(__file__).resolve().parent
BASE = ROOT / "PROJECT_HISTORY_base.md"
OUT = ROOT / "PROJECT_HISTORY_2026-09-29.md"
R = ROOT / "reports"
V = ROOT / "v2"


# ------------------------------------------------------------------------------------------------ 工具
def rd(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def fmt(x, n=2):
    v = num(x)
    if v is None:
        return "—" if x in (None, "", "nan") else str(x)
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.{n}f}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def titles(rep_dir, ids=None):
    out = []
    for f in sorted((rep_dir / "figures").glob("*.json")):
        if ids and f.stem not in ids:
            continue
        m = json.loads(f.read_text(encoding="utf-8"))
        out.append(f"- {f.stem}：{m.get('title', '')}")
    return "\n".join(out) + "\n"


def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else None


def q(v, p):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def img(cap, rel):
    return f"\n![{cap}]({rel})\n" if (ROOT / rel).exists() else ""


# ------------------------------------------------------------------------------------------------ v1
def b_v1_geometry():
    t = rd(R / "R1_geometry/tables/R1-T01.csv")
    s = "#### 数据：三型股骨的实测尺寸（R1-T01）\n\n"
    s += table(["Dorr", "CFI 预设 / 实测", "皮质指数 预设 / 实测", "小转子上 20 mm 髓腔宽 (mm)", "峡部髓腔宽 (mm)", "内 / 外侧壁厚 (mm)",
                "截骨处髓腔半宽 (mm)", "松质骨模量 (MPa)"],
               [[r["dorr"], f"{fmt(r['CFI_preset'], 1)} / {fmt(r['CFI_measured'], 3)}", f"{fmt(r['CI_preset'])} / {fmt(r['CI_measured'], 3)}",
                 fmt(r["canal_LT20_mm"], 1), fmt(r["canal_isthmus_mm"], 1), f"{fmt(r['wall_LT20_medial_mm'], 1)} / {fmt(r['wall_LT20_lateral_mm'], 1)}",
                 fmt(r["canal_halfwidth_cut_mm"], 1), fmt(r["E_cancellous_MPa"], 0)] for r in t])
    s += "\n内 / 外侧壁厚从 A 到 C 变厚（3.3 / 2.6 → 9.9 / 8.0 mm），就是后来发现的“Dorr C 干骺端皮质最厚”的问题。\n\n"
    g = rd(R / "R1_geometry/tables/R1-T03.csv")
    s += "#### 数据：几何门结果（每型 1,024 个 Sobol 设计，R1-T03）\n\n"
    s += table(["结果", "原因", "Dorr A", "Dorr B", "Dorr C"], [[r["level"] or "—", r["reason"], r["Dorr_A"], r["Dorr_B"], r["Dorr_C"]] for r in g])
    s += "\n#### 图题（由数据算出的结论）\n\n" + titles(R / "R1_geometry")
    return s


def b_v1_fe():
    s = "#### 数据：网格收敛指数（Celik 2008，R2-T02）\n\n三档网格界面单元 1.5 / 0.75 / 0.375 mm，细化比 2。\n\n"
    t = rd(R / "R2_fe_verification/tables/R2-T02.csv")
    s += table(["Dorr", "量", "单元数 细 / 中 / 粗", "细", "中（生产）", "粗", "表观阶 p", "外推值", "中对细相对差", "细网格 GCI", "行为"],
               [[r["dorr"], r["quantity"], f"{int(float(r['N1'])):,} / {int(float(r['N2'])):,} / {int(float(r['N3'])):,}", fmt(r["phi1"]), fmt(r["phi2"]),
                 fmt(r["phi3"]), fmt(r["p"]), fmt(r["phi_ext"]), fmt(r["e_a21_pct"], 1) + "%", fmt(r["GCI_fine_pct"], 1) + "%",
                 {"monotonic": "单调", "oscillatory": "振荡"}.get(r["behaviour"], r["behaviour"])] for r in t])
    s += "\n#### 数据：符号检查（Dorr B 基线设计，R2-F04）\n\n"
    c = rd(R / "R2_fe_verification/figures/R2-F04.csv")
    s += table(["检查", "量", "变体", "值", "预期", "符合"],
               [[r["check"], r["quantity"], r["variant"], fmt(r["value"], 2), r["expected"].replace("expect: ", ""),
                 "—" if "no expected sign" in r["expected"] else ("✓" if r["ok"] == "1" else "✗")] for r in c])
    p = rd(R / "R2_fe_verification/figures/R2-F11.csv")
    s += "\n#### 数据：侧板厚度校准（2D 对 3D 的秩相关，R2-F11）\n\n"
    th = sorted({float(r["side_plate"]) for r in p})
    rows = []
    for x in th:
        rr = [r for r in p if float(r["side_plate"]) == x]
        v = [float(r["rho"]) for r in rr]
        cell = {(r["dorr"], r["objective"]): float(r["rho"]) for r in rr}
        rows.append([fmt(x, 1)] + [fmt(cell.get((d, o)), 2) for d in "ABC" for o in ("f1", "f2")] + [fmt(st.mean(v), 2), fmt(min(v), 2)])
    s += table(["侧板 (mm)", "A f1", "A f2", "B f1", "B f2", "C f1", "C f2", "平均", "最差"], rows)
    s += "\n#### 图题\n\n" + titles(R / "R2_fe_verification")
    return s


def b_v1_selftest():
    t = rd(R / "R3_optimizer_selftest/tables/R3-T01.csv")
    s = "#### 数据：60 次评估时的超体积比与 IGD（5 个种子，R3-T01）\n\n"
    s += table(["基准", "方法", "超体积比 中位", "均值 ± 标准差", "IGD 均值 ± 标准差", "候选池上限"],
               [[r["benchmark"], r["method"], fmt(r["HV_ratio_median"], 3), f"{fmt(r['HV_ratio_mean'], 3)} ± {fmt(r['HV_ratio_sd'], 3)}",
                 f"{fmt(r['IGD_mean'], 3)} ± {fmt(r['IGD_sd'], 3)}", fmt(r["pool_oracle_HV_ratio"], 3)] for r in t])
    s += "\n“候选池上限”是离散候选池里最优子集能达到的超体积比：BO 在两个基准上都已贴近这个上限。\n"
    return s


def b_v1_sweep():
    t = rd(R / "R4_reference_sweep/tables/R4-T02.csv")
    s = "#### 数据：失败分级计数（R4-T02）\n\n"
    s += table(["组", "尝试", "成功", "L1 尖端比髓腔宽", "L2 切入皮质", "L3 建网", "L4 求解", "过几何门", "FE 失败率"],
               [[r["group"], r["attempts"], r["OK"], r["L1"], r["L2"], r["L3"], r["L4"], r["gate_passed"], fmt(r["fe_fail_rate_pct"], 2) + "%"] for r in t])
    t = rd(R / "R4_reference_sweep/tables/R4-T03.csv")
    s += "\n#### 数据：单设计耗时（网格 + 两个 Abaqus 作业 + 关注量，R4-T03）\n\n"
    s += table(["组", "设计数", "中位 (s)", "P95 (s)", "总机时 (h)"], [[r["group"], r["n"], fmt(r["median_s"], 1), fmt(r["p95_s"], 1), fmt(r["total_machine_h"], 2)] for r in t])
    f = rd(R / "R4_reference_sweep/tables/R4-T01.csv")
    s += "\n#### 数据：参考前沿设计清单（R4-T01，全部 37 个）\n\n"
    s += table(["组", "尖端深度 (mm)", "尖端横向位置", "近端宽比", "锥度", "入柄角 (°)", "f1 (µm)", "f2 (%)", "柄应力 (MPa)"],
               [[r["group"], fmt(r["tip_depth"], 1), fmt(r["tip_lat"]), fmt(r["w_prox"]), fmt(r["taper"]), fmt(r["theta_in"], 1), fmt(r["f1_um"]),
                 fmt(r["f2_pct"], 1), fmt(r["vm_p99"], 0)] for r in f])
    s += "\n#### 图题\n\n" + titles(R / "R4_reference_sweep")
    s += img("v1 参考前沿：三型各自的非支配设计（R4-F01）", "reports/R4_reference_sweep/figures/R4-F01.png")
    return s


def b_v1_bo():
    h = rd(R / "R5_bo_results/figures/R5-F01.csv")
    nmax = max(int(float(r["n_fe"])) for r in h)
    s = f"#### 数据：每个种子在 {nmax} 次 FE 时的超体积比（R5-F01）\n\n"
    rows = []
    for d in "ABC":
        for m in sorted({r["method"] for r in h}):
            v = {int(float(r["seed"])): float(r["hv_ratio"]) for r in h if r["dorr"] == d and r["method"] == m and int(float(r["n_fe"])) == nmax}
            first90 = []
            for sd in sorted(v):
                tr = sorted((int(float(r["n_fe"])), float(r["hv_ratio"])) for r in h if r["dorr"] == d and r["method"] == m and int(float(r["seed"])) == sd)
                hit = [n for n, x in tr if x >= 0.90]
                first90.append(str(hit[0]) if hit else "未达到")
            rows.append([d, m] + [fmt(v[k], 3) for k in sorted(v)] + [fmt(st.median(v.values()), 3), " / ".join(first90)])
    s += table(["Dorr", "方法", "种子 0", "种子 1", "种子 2", "中位", "首次达到 0.90 的 FE 次数（各种子）"], rows)
    t = rd(R / "R5_bo_results/tables/R5-T01.csv")
    s += "\n#### 数据：代理指标（留出集约 500 个设计；三个种子的范围，R5-T01）\n\n"
    rows = []
    for d in "ABC":
        for o in ("log10 f1", "f2 (%)", "vm P99 (MPa)"):
            rr = [r for r in t if r["dorr"] == d and r["output"] == o]
            if rr:
                rows.append([d, o, f"{rr[0]['n_train']} / {rr[0]['n_test']}"] +
                            [f"{fmt(min(float(r[k]) for r in rr))} – {fmt(max(float(r[k]) for r in rr))}" for k in ("R2", "spearman", "coverage90")])
    s += table(["Dorr", "输出", "训练 / 测试点数", "R²", "秩相关", "90% 区间覆盖率"], rows)
    t = rd(R / "R5_bo_results/tables/R5-T02.csv")
    s += "\n#### 数据：成本账本（三个种子合计，R5-T02）\n\n"
    s += table(["Dorr", "方法", "FE 设计数", "FE 机时 (h)", "选点耗时 (h)", "参考扫描机时 (h)", "相对参考扫描节省"],
               [[r["dorr"], r["method"], r["fe_designs_3_seeds"], fmt(r["fe_machine_h"]), fmt(r["acquisition_h"]), fmt(r["reference_sweep_machine_h"]),
                 fmt(r["fe_saving_vs_sweep_pct"], 1) + "%"] for r in t])
    s += "\n#### 图题\n\n" + titles(R / "R5_bo_results")
    s += img("v1：BO 与同预算 Sobol 的超体积比随 FE 次数（R5-F01）", "reports/R5_bo_results/figures/R5-F01.png")
    return s


def b_v1_spot():
    t = rd(R / "R6_spot3d/tables/R6-T01.csv")
    s = "#### 数据：抽检设计的 2D 与 3D 目标值（R6-T01）\n\n"
    s += table(["Dorr", "设计", "f1 2D (µm)", "f1 3D (µm)", "f2 2D (%)", "f2 3D (%)"],
               [[r["dorr"], r["design_id_2d"], fmt(r["f1_2d"]), fmt(r["f1_3d"]), fmt(r["f2_2d"], 1), fmt(r["f2_3d"], 1)] for r in t])
    s += "\nC 型在 3D 里的微动是 2D 的 2–3 倍（8.0–14.7 对 3.2–6.5 µm），A、B 两型量级接近。\n"
    return s


def b_v1_close():
    s = "#### 数据：局限清单与在真实模型中的处置（R7-T03）\n\n"
    t = rd(R / "R7_summary/tables/R7-T03.csv")
    s += table(["局限", "影响", "真实模型中的处置"], [[r["limitation"], r["effect"], r["in_real_model"]] for r in t])
    t = rd(R / "R7_summary/tables/R7-T04.csv")
    s += "\n#### 数据：R0–R6 验收逐项（R7-T04）\n\n"
    s += table(["编号", "判定", "实测"], [[r["id"], r["status"], r["measured"][:90]] for r in t])
    return s


# ------------------------------------------------------------------------------------------------ V2A / V3（旧界面模型）
def designs():
    z = rd(V / "results/shielding/zones.csv")
    seen, out = set(), []
    for r in z:
        if r["job_id"] in seen:
            continue
        seen.add(r["job_id"])
        out.append({"job_id": r["job_id"], "stage": r["stage"], "version": r["version"], "L": float(r["L"]), "alpha": float(r["alpha"]),
                    "m": float(r["m"]), "h_cut": float(r["h_cut"]), "A0": float(r["A0"]), "f1": float(r["f1_um"]),
                    "dsed": abs(float(r["f2_loss_pct"])), "loss": float(r["f2_loss_pct"]), "vm": float(r["vm_stem_p99"])})
    return out


def stat_rows(groups):
    rows = []
    for name, d in groups:
        if not d:
            continue
        f1 = [x["f1"] for x in d]
        ds = [x["dsed"] for x in d]
        rows.append([name, len(d), fmt(med(f1), 1), f"{fmt(q(f1, .25), 1)} – {fmt(q(f1, .75), 1)}", f"{fmt(min(f1), 1)} – {fmt(max(f1), 0)}",
                     fmt(med(ds), 1), fmt(med([x['vm'] for x in d]), 0), f"{100 * sum(x['f1'] < 10 for x in d) / len(d):.0f}%",
                     f"{100 * sum(x['dsed'] > 30 for x in d) / len(d):.0f}%"])
    return rows


HEAD_STAT = ["分组", "设计数", "微动中位 (µm)", "四分位", "范围", "偏离中位 (%)", "柄应力中位 (MPa)", "微动 < 10 µm", "偏离 > 30%"]


def b_v2a():
    s = "#### 数据：符号检查与重跑（V2A-T04）\n\n"
    t = rd(V / "reports/V2A_real_femur/tables/V2A-T04.csv")
    s += table(["检查", "结果"], [[r["check"], r["observed"]] for r in t])
    t = rd(V / "reports/V2A_real_femur/tables/V2A-T05.csv")
    s += "\n#### 数据：网格收敛（基准设计，V2A-T05）\n\n"
    s += table(["量", "1.0 mm", "1.4 mm", "2.0 mm", "程序给出的表观阶", "细网格 GCI", "2.0 对 1.0 相对差"],
               [[r["quantity"].replace("base:", ""), r["h1.0"], r["h1.4"], r["h2.0"], r["p"], f"{100 * float(r['gci_fine']):.1f}%",
                 f"{100 * float(r['rel_change_2.0_vs_1.0']):.1f}%"] for r in t])
    s += "\n微动三档非单调（7.00 / 7.70 / 7.34），表观阶与 GCI 没有意义；保留这张表是为了记录当时程序的输出。\n"
    g = rd(V / "reports/V2A_real_femur/figures/V2A-F11.csv")
    s += "\n#### 数据：全局敏感性（64 点参考集上的代理，总效应指数，V2A-F11）\n\n"
    names = [r["name"] for r in g if r["objective"] == g[0]["objective"]]
    objs = sorted({r["objective"] for r in g})
    s += table(["层级", "变量或变量组"] + objs,
               [[next(r["level"] for r in g if r["name"] == n), n] + [fmt(next((r["ST"] for r in g if r["name"] == n and r["objective"] == o), None), 3) for o in objs]
                for n in names])
    s += "\n代理没有做过交叉验证，且一半以上的单位立方体不可行，这些指数只能作定性排序。\n"
    t = rd(V / "reports/V2A_real_femur/tables/V2A-T06.csv")
    s += "\n#### 数据：BO 对同预算 Sobol（V2A-T06）\n\n"
    s += table(["系列", "评估数", "成功数", "超体积比", "同预算 Sobol 中位", "说明"],
               [[r["series"], r["n_eval"], r["n_ok"], r["hv_ratio_vs_original_best"], r["sobol_median_same_n"] or "—", r["note"] or "—"] for r in t])
    t = rd(V / "reports/V2A_real_femur/tables/V2A-T07.csv")
    s += "\n#### 数据：V2A 当时的前沿设计（微动对偏离绝对值，V2A-T07；已撤回，留作记录）\n\n"
    s += table(["来源", "L", "ρ_tip", "q", "λ", "γ_ml", "γ_ap", "n_a", "n_p", "τ_a", "τ_p", "α", "A0 (mm²)", "f1 (µm)", "偏离 (%)"],
               [[r["source"], fmt(r["L"], 1), r["rho_tip"], r["q"], r["lam"], r["g_ml"], r["g_ap"], r["n_a"], r["n_p"], r["tau_a"], r["tau_p"],
                 fmt(r["alpha"], 1), fmt(r["A0_mm2"], 0), r["f1_um"], r["g7_abs_dsed_pct"]] for r in t])
    d = designs()
    s += (f"\n#### 数据：旧界面模型下全部 {len(d)} 个已解设计的统计\n\n这些微动值的数值地板约 10 µm，低于 10 µm 的读数不能用来排序；"
          "“偏离”是旧约束量（固定区、皮质与松质骨混合）的绝对值。\n\n按阶段：\n\n")
    order = [("ref", "参考集 ref"), ("bo", "V2A 的 BO"), ("conv", "收敛研究 conv"), ("probe", "20–40 mm 探针"), ("cref", "留 1 mm：参考 cref"),
             ("cprobe", "留 1 mm：探针 cprobe"), ("warm", "热启动 BO"), ("uwarm", "12 维热启动"), ("v3", "V3")]
    known = {k for k, _ in order}
    groups = [(nm, [x for x in d if x["stage"] == k]) for k, nm in order] + [("其他", [x for x in d if x["stage"] not in known])]
    s += table(HEAD_STAT, stat_rows(groups))
    s += "\n按柄长：\n\n"
    s += table(HEAD_STAT, stat_rows([(f"{a}–{b} mm", [x for x in d if a <= x["L"] < b]) for a, b in ((20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 91))]))
    s += "\n按插入角：\n\n"
    s += table(HEAD_STAT, stat_rows([(f"{a}–{b}°", [x for x in d if a <= x["alpha"] < b]) for a, b in ((5, 15), (15, 25), (25, 35), (35, 41))]))
    s += "\n按皮质余量：\n\n"
    s += table(HEAD_STAT, stat_rows([("m < 0（贴皮质）", [x for x in d if x["m"] < 0]), ("0 – 0.5 mm", [x for x in d if 0 <= x["m"] < 0.5]),
                                     ("0.5 – 1.0 mm", [x for x in d if 0.5 <= x["m"] < 1.0]), ("≥ 1.0 mm", [x for x in d if x["m"] >= 1.0])]))
    s += "\n按模型版本（假体颈起点修正前后）：\n\n"
    s += table(HEAD_STAT, stat_rows([("修正前", [x for x in d if x["version"] == "pre-fix"]), ("修正后", [x for x in d if x["version"] == "current"])]))
    s += "\n#### 图题\n\n" + titles(V / "reports/V2A_real_femur", {f"V2A-F{k:02d}" for k in (1, 2, 5, 7, 8, 9, 10, 11, 12, 13, 15)})
    s += img("真实股骨的颈平面切面与 8 个横断面（V2A-F01）", "v2/reports/V2A_real_femur/figures/V2A-F01.png")
    s += img("64 点参考集在目标空间的分布（V2A-F10，旧界面模型）", "v2/reports/V2A_real_femur/figures/V2A-F10.png")
    return s


def b_pivot():
    d = designs()
    s = "#### 数据：20–40 mm 探针逐档（旧界面模型）\n\n"
    pr = [x for x in d if x["stage"] == "probe"]
    s += table(HEAD_STAT, stat_rows([(f"{a}–{b} mm", [x for x in pr if a <= x["L"] < b]) for a, b in ((20, 25), (25, 30), (30, 35), (35, 41))]))
    s += "\n#### 数据：留 1 mm 松质层的配对设计（cref、cprobe）\n\n"
    c = sorted([x for x in d if x["stage"] in ("cref", "cprobe")], key=lambda x: x["L"])
    s += table(["阶段", "L (mm)", "α (°)", "A0 (mm²)", "f1 (µm)", "旧约束量 (%)", "柄应力 (MPa)"],
               [[x["stage"], fmt(x["L"], 1), fmt(x["alpha"], 1), fmt(x["A0"], 0), fmt(x["f1"], 1), fmt(x["loss"], 1), fmt(x["vm"], 0)] for x in c])
    s += "\n43 + 6 个提交里 28 个模板化不可行（L1），上表是能放进去并解完的 21 个。\n"
    return s


def b_v3():
    s = ""
    for sd in (0, 1):
        p = V / f"results/v3_bo_s{sd}.json"
        if not p.exists():
            continue
        b = json.loads(p.read_text(encoding="utf-8"))
        s += (f"#### 数据：V3 种子 {sd} 逐个评估（热启动 {b['warm_start_n']} 个设计，候选池 {b['pool_size']} 个，"
              f"参考点 (log10 f1, 骨量损失) = ({b['ref_point'][0]:.3f}, {b['ref_point'][1]:.0f} mm³)）\n\n")
        rows = []
        for r in b["records"]:
            if r["ok"]:
                rows.append([r["round"], fmt(r["L"], 1), fmt(r["h_cut"], 1), fmt(r["alpha"], 1), fmt(r["m"], 2), fmt(10 ** r["y"][0], 1),
                             fmt(r["y"][1] / 1000, 2), "是" if r["c"][0] <= 0 else "否", fmt(r["c"][0], 2)])
            else:
                rows.append([r["round"], fmt(r["L"], 1), fmt(r["h_cut"], 1), fmt(r["alpha"], 1), fmt(r["m"], 2), "失败", "—", "—", "—"])
        s += table(["轮", "L (mm)", "截骨 (mm)", "α (°)", "余量 (mm)", "f1 (µm)", "骨量损失 (cm³)", "满足约束", "归一化违反量"], rows)
        s += f"\n选点耗时每轮 {min(b['acq_s']):.0f}–{max(b['acq_s']):.0f} s。\n\n"
    t = rd(V / "reports/V3_short_stem/tables/V3-T01.csv")
    s += "#### 数据：V3 报告里的前沿设计（V3-T01；已撤回，留作记录）\n\n"
    s += table(["作业", "L", "截骨", "α", "余量", "λ", "γ_ml", "γ_ap", "n", "τ", "A0", "f1 (µm)", "偏离 (%)", "柄应力", "锉骨 (mm³)", "骨量损失 (mm³)"],
               [[r["job_id"][:22], r["L"], r["h_cut"], r["alpha"], r["m"], r["lam"], r["g_ml"], r["g_ap"], r["n"], r["tau"], r["A0_mm2"], r["f1_um"],
                 r["abs_dsed_pct"], r["vm_p99"], fmt(r["reamed_mm3"], 0), fmt(r["bone_loss_mm3"], 0)] for r in t])
    t = rd(V / "reports/V3_short_stem/tables/V3-T02.csv")
    s += "\n#### 数据：敏感性补跑逐设计（旧界面模型，V3-T02）\n\n"
    s += table(["设计", "前沿", "L", "截骨", "余量", "f1 基线", "f1 E 200", "f1 δ 0.05", "偏离 基线", "偏离 E 200", "偏离 δ 0.05", "柄应力 基线", "柄应力 E 200"],
               [[r["job_id"][:20], "是" if r["front"] == "True" else "否", r["L"], r["h_cut"], r["m"], r["f1_base"], r["f1_Ecanc200"], r["f1_delta005"],
                 r["dsed_base"], r["dsed_Ecanc200"], r["dsed_delta005"], r["vm_base"], r["vm_Ecanc200"]] for r in t])
    s += "\n柄应力在基线与变体之间从 61–110 跳到 134–202 MPa 的三行，就是假体颈修正前解的参考设计。\n"
    s += "\n#### 图题\n\n" + titles(V / "reports/V3_short_stem")
    s += img("V3 目标空间：骨量损失对微动（V3-F01，旧界面模型，结论已撤回）", "v2/reports/V3_short_stem/figures/V3-F01.png")
    return s


# ------------------------------------------------------------------------------------------------ 应力屏蔽
def b_shield():
    z = [r for r in rd(V / "results/shielding/zones.csv") if r["version"] == "current"]
    s = f"#### 数据：Gruen 分区统计，皮质与松质骨（{len({r['job_id'] for r in z})} 个设计）\n\n变化量 = (植入 − 完整) / 完整。\n\n"
    rows = []
    for zn in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "calcar_fixed"):
        for t in ("cortex", "cancellous"):
            rr = [r for r in z if r["zone"] == zn and r["tissue"] == t]
            vm = [num(r["chg_vm_pct"]) for r in rr]
            sd = [num(r["chg_sed_pct"]) for r in rr]
            sdv = [x for x in sd if x is not None]
            if not sdv:
                continue
            rows.append([{"calcar_fixed": "固定区"}.get(zn, zn[1:] + " 区"), {"cortex": "皮质", "cancellous": "松质"}[t], fmt(med([num(r["vol_impl"]) for r in rr]), 0),
                         fmt(med([num(r["vm_intact"]) for r in rr]), 2), f"{fmt(med(vm), 0)} [{fmt(q(vm, .25), 0)}, {fmt(q(vm, .75), 0)}]",
                         f"{fmt(min(x for x in vm if x is not None), 0)} – {fmt(max(x for x in vm if x is not None), 0)}",
                         f"{fmt(med(sd), 0)} [{fmt(q(sd, .25), 0)}, {fmt(q(sd, .75), 0)}]",
                         f"{100 * sum(x < -30 for x in sdv) / len(sdv):.0f}% / {100 * sum(x < -50 for x in sdv) / len(sdv):.0f}% / {100 * sum(x < -75 for x in sdv) / len(sdv):.0f}%",
                         f"{100 * sum(x > 30 for x in sdv) / len(sdv):.0f}%"])
    s += table(["分区", "骨质", "区域体积中位 (mm³)", "完整股骨应力中位 (MPa)", "应力变化 中位 [四分位] (%)", "应力变化范围 (%)",
                "应变能密度变化 中位 [四分位] (%)", "应变能密度降 > 30 / 50 / 75% 的设计", "升 > 30% 的设计"], rows)
    g7 = [r for r in z if r["zone"] == "G7" and r["tissue"] == "cortex"]
    s += "\n#### 数据：股骨距皮质应力变化按设计变量分箱\n\n"
    rows = []
    for nm, key, bins in (("插入角 (°)", "alpha", ((5, 15), (15, 25), (25, 35), (35, 41))), ("柄长 (mm)", "L", ((20, 30), (30, 40), (40, 50), (50, 60), (60, 91))),
                          ("皮质余量 (mm)", "m", ((-1, 0), (0, 0.5), (0.5, 1.0), (1.0, 3))), ("截骨高度 (mm)", "h_cut", ((24, 26), (26, 30), (30, 46)))):
        for a, b in bins:
            rr = [r for r in g7 if a <= float(r[key]) < b]
            if rr:
                rows.append([nm, f"{a:g} – {b:g}", len(rr), fmt(med([num(r["chg_vm_pct"]) for r in rr]), 0), fmt(med([num(r["chg_sed_pct"]) for r in rr]), 0)])
    s += table(["变量", "范围", "设计数", "应力变化中位 (%)", "应变能密度变化中位 (%)"], rows)
    sm = json.loads((V / "results/shielding/summary.json").read_text(encoding="utf-8"))["measure"]
    s += "\n#### 数据：旧约束量对皮质口径（固定区）\n\n"
    s += table(["项", "值"], [["比较的设计数", sm["n"]], ["区域应变能中松质骨所占份额（中位）", fmt(sm["cancellous_energy_share_median_pct"], 1) + "%"],
                            ["区域内皮质体积中位", fmt(sm["cortex_volume_median_mm3"], 0) + " mm³"],
                            ["旧约束量超过 30% 的设计", f"{sm['violate30_mixed']}（其中过载 {sm['over30_mixed']}，遮挡 {sm['shield30_mixed']}）"],
                            ["同一区域皮质口径超过 30% 的设计", f"{sm['violate30_cortex_abs']}（其中过载 {sm['over30_cortex']}，遮挡 {sm['shield30_cortex']}）"],
                            ["两种口径符号相反的设计", sm["sign_disagree"]]])
    mp = json.loads((V / "results/shielding/maps.json").read_text(encoding="utf-8"))
    s += "\n#### 数据：出对比图的六个设计\n\n"
    s += table(["选取理由", "L (mm)", "α (°)", "余量 (mm)", "A0 (mm²)", "7 区皮质应力变化", "7 区皮质应变能密度变化", "1 区皮质应力变化"],
               [[{"most shielded calcar cortex": "股骨距遮挡最重", "median": "中位", "most overloaded calcar cortex": "股骨距遮挡最轻", "shortest stem": "最短的柄",
                  "longest stem": "最长的柄", "former read-out design": "原读数设计"}.get(m["why"], m["why"]), fmt(m["L"], 1), fmt(m["alpha"], 1), fmt(m["m"], 2),
                 fmt(m["A0"], 0), fmt(m["g7_cortex_vm"], 0) + "%", fmt(m["g7_cortex_sed"], 0) + "%", fmt(m["g1_cortex_vm"], 0) + "%"] for m in mp])
    s += img("各 Gruen 区皮质骨的变化量分布（左：应力；右：应变能密度）", "v2/results/shielding/figs/S1_zones_box.png")
    s += img("股骨距遮挡最重的设计：完整、植入、变化三联图", "v2/results/shielding/maps/" + mp[0]["file"])
    s += img("旧约束量（横轴）对同一区域的皮质与松质骨口径", "v2/results/shielding/figs/S3_measure_comparison.png")
    return s


# ------------------------------------------------------------------------------------------------ M1
def b_m1():
    S = json.loads((V / "results/m1_report/summary.json").read_text(encoding="utf-8"))
    rows_ = S["rows"]
    ok = [r for r in rows_ if "f1_p95_um" in r]
    NAME = {"base": "基准", "readout": "原读数", "short": "短柄"}

    def lab(r):
        return NAME.get(r["label"], "对比 " + r["label"][3:])
    s = "#### 数据：解析对照 8 个作业\n\n"
    s += table(["过盈写法", "摩擦", "网格 (mm)", "解析解 (MPa)", "反推压力 (MPa)", "误差", "节点接触压力均值 [最小, 最大] (MPa)", "其偏差",
                "骨侧法向位移 均值 ± 标准差 (µm)", "节点对数", "求解 (s)"],
               [[{"clearance": "逐节点给定", "offset": "几何平移"}[k.split("_")[0]], k.split("_")[1][2:], k.split("_")[2][1:], fmt(v["p_lame_MPa"], 3),
                 fmt(v["p_inferred_MPa"], 3), f"{v['err_pct']:+.2f}%", f"{fmt(v['p_fe_mean_mid_MPa'])} [{fmt(v['p_fe_min_mid'])}, {fmt(v['p_fe_max_mid'])}]",
                 f"{v['err_cpress_pct']:+.1f}%", f"{fmt(v['bone_normal_disp_mean_um'])} ± {fmt(v['bone_normal_disp_sd_um'])}", v["n_pairs"],
                 v["wall_s"]["lame_fric"]] for k, v in S["lame"]["runs"].items() if "err_pct" in v])
    s += "\n解析的骨侧法向位移是 99.85 µm（过盈 100 µm 里钛柱只压缩 0.15 µm）。\n"
    s += f"\n#### 数据：M1 全部 {len(ok)} 个已解设计作业\n\n"
    s += ("列说明：可恢复 = 第二循环可恢复切向相对位移 P95；首次 = 首次加载 P95；旧定义 = 同一模型上按接触滑移增量算；"
          "张开 = 压配后间隙 > 5 µm 的面积；粘着滑移 = 粘着节点的滑移 P95。\n\n")
    ok_s = sorted(ok, key=lambda r: (not r["label"] in NAME, r["label"], r["h"], -r["delta"], r["lagrange"], -(r["slip_tol"] or 0), r["mu"], not r["torque"]))
    s += table(["设计", "L", "α", "余量", "网格", "过盈", "摩擦", "扭转", "容差", "可恢复 (µm)", "中位 (µm)", "首次 (µm)", "旧定义 (µm)", "> 40 µm 面积",
                "张开", "粘着滑移 (µm)", "压力中位 / P95 (MPa)", "柄应力 (MPa)", "摩擦求解 (s)"],
               [[lab(r), fmt(r["L"], 0), fmt(r["alpha"], 0), fmt(r["m"], 2), f"{r['h']:g}", f"{r['delta']:g}", f"{r['mu']:g}", "有" if r["torque"] else "无",
                 f"{r['slip_tol']:g}", fmt(r["f1_p95_um"], 2), fmt(r["f1_rev_p50_um"], 2), fmt(r["f1_first_p95_um"], 1), fmt(r["f1_cslip_p95_um"], 1),
                 f"{100 * r['area_frac_gt40']:.0f}%", f"{100 * r.get('open5_frac_release', float('nan')):.1f}%", fmt(r["stick_cslip_p95_um"], 2),
                 f"{fmt(r['cpress_release_p50'], 1)} / {fmt(r['cpress_release_p95'], 1)}", fmt(r["vm_p99"], 0), fmt(r["wall_fric_s"], 0)] for r in ok_s])
    fl = [r for r in rows_ if "failed" in r]
    s += "\n#### 数据：失败或跳过的 M1 作业\n\n"
    s += table(["设计", "过盈", "摩擦设置", "等级", "原因"],
               [[lab(r), f"{r['delta']:g}", "Lagrange" if r["lagrange"] else f"容差 {r['slip_tol']:g}", r["failed"]["level"],
                 r["failed"]["reason"][:110].replace("|", "/")] for r in fl])
    nz = S["noise"]
    s += "\n#### 数据：噪声底逐网格\n\n"
    rows = []
    for k in ("base", "readout", "short"):
        o = nz.get(k, {})
        if o.get("n", 0) >= 3:
            for qn, nm in (("f1_p95_um", "可恢复微动 (µm)"), ("f1_first_p95_um", "首次加载微动 (µm)"), ("f1_cslip_p95_um", "旧定义微动 (µm)"),
                           ("f2_g7_loss_pct", "旧约束量 (%)"), ("vm_p99", "柄应力 (MPa)"), ("open_frac_release", "间隙 > 1 µm 面积")):
                a = o[qn]
                rows.append([NAME[k], nm] + [fmt(v, 3 if qn == "open_frac_release" else 2) for v in a["values"]] + [fmt(a["mean"], 2), fmt(a["sd"], 3), fmt(a["cv_pct"], 1) + "%"])
    s += table(["设计", "量", "1.94", "1.97", "2.00", "2.03", "2.06 mm", "均值", "标准差", "变异系数"], rows)
    c = S["compare"]
    if c:
        s += (f"\n新旧对比（{c['n']} 个设计，过盈 0.05 mm）：旧微动对新可恢复微动秩相关 {c['spearman_f1_p95_um']:.3f}、比值中位 {c['median_ratio_f1_p95_um']:.2f}；"
              f"对新首次加载微动秩相关 {c['spearman_f1_first_p95_um']:.3f}、比值中位 {c['median_ratio_f1_first_p95_um']:.2f}。\n")
    s += img("过盈量扫描：可恢复微动与首次加载微动", "v2/results/m1_report/F1_delta.png")
    s += img("新旧界面对比", "v2/results/m1_report/F2_compare.png")
    s += img("噪声底", "v2/results/m1_report/F3_noise.png")
    return s


def b_times():
    log = (V / "runs/worker.log").read_text(encoding="utf-8", errors="replace").splitlines()
    pat = re.compile(r"^(\S+ \S+)\s+(\S+?)/(\S+): OK (\d+) s")
    acc = {}
    for ln in log:
        m = pat.match(ln)
        if not m:
            continue
        job, unit, t = m.group(2), m.group(3), int(m.group(4))
        stage = "m1 解析对照" if job.startswith("m1lame") else ("m1 设计" if job.startswith("m1_") else job.split("_")[0])
        kind = "摩擦" if unit.endswith("fric") else ("粘接" if unit.endswith("bond") else "完整股骨")
        acc.setdefault((stage, kind), []).append(t)
    s = "#### 数据：本机求解时间（取自 worker 日志）\n\n"
    rows = [[k[0], k[1], len(v), fmt(st.median(v), 0), f"{min(v)} – {max(v)}", fmt(sum(v) / 3600, 1)] for k, v in sorted(acc.items())]
    s += table(["阶段", "模型", "次数", "中位 (s)", "范围 (s)", "累计 (h)"], rows)
    tot = sum(sum(v) for v in acc.values())
    s += f"\n合计 {sum(len(v) for v in acc.values())} 次求解，累计 {tot / 3600:.1f} h 求解时间（多槽并行，墙钟更短）。\n"
    return s


BLOCKS = [("### 2.2 FE 模型与验证", b_v1_geometry), ("### 2.3 优化器自检", b_v1_fe), ("### 2.4 参考扫描", b_v1_selftest),
          ("### 2.5 BO 结果", b_v1_sweep), ("### 2.6 3D 抽检", b_v1_bo), ("### 2.7 v1 收尾", b_v1_spot), ("## 3 柄型变更", b_v1_close),
          ("## 5 09-28 中午到傍晚的三次转向", b_v2a), ("## 6 V3 的结果与敏感性", b_pivot), ("## 7 文献核对与 Methods", b_v3),
          ("## 10 M1 界面模型与七小时验证", b_shield), ("## 10A 第三份评估意见的复核", b_m1), ("## 12 经验教训", b_times)]


def main():
    base = BASE.read_text(encoding="utf-8")
    for anchor, fn in BLOCKS:
        n = base.count("\n" + anchor)
        if n != 1:
            raise SystemExit(f"anchor {anchor!r}: {n} matches")
        base = base.replace("\n" + anchor, "\n" + fn().rstrip() + "\n\n" + anchor)
    base = base.replace("本文按时间顺序写每个阶段做了什么、怎么做的、得到什么数、谁做了什么决定、哪里出过错。数字全部取自报告、队列记录与结果文件。",
                        "本文按时间顺序写每个阶段做了什么、怎么做的、得到什么数、谁做了什么决定、哪里出过错。每节末尾标“数据”的表与图由 "
                        "`build_history.py` 直接从报告 CSV、队列导出与结果 JSON 生成，没有手抄。")
    OUT.write_text(base, encoding="utf-8")
    print("written", OUT, len(base.splitlines()), "lines")


if __name__ == "__main__":
    main()
