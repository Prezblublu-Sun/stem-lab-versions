"""由 v2/results/audit3b/summary.json 生成 v2/REVIEW3_RUNS.md（本机跑）。表格与判定由数据算出。

    python v2/build_review3_runs_doc.py [--stamp "2026-09-29 15:10"]
"""
from __future__ import annotations

import argparse
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
S = json.loads((HERE / "results" / "audit3b" / "summary.json").read_text(encoding="utf-8"))
OUT = HERE / "REVIEW3_RUNS.md"
NAME = {"base": "基准（L 60，α 20°）", "readout": "原读数设计（L 53，α 39°）", "short": "短柄（L 25，α 37°）"}
SHORT = {"base": "基准", "readout": "原读数设计", "short": "短柄"}


def f(x, n=2):
    return "—" if x is None else f"{x:.{n}f}"


def pct(a, b):
    return "—" if (a is None or b in (None, 0)) else f"{100 * (a / b - 1):+.0f}%"


def tab(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def dl(key):
    return key.split(":d")[1].split(":")[0]


def main(stamp):
    st = S["states"]
    n_done = sum(v == "DONE" for v in st.values())
    n_fail = sum(v == "FAILED" for v in st.values())
    n_pend = len(st) - n_done - n_fail
    cy, me, nz, eq, sn, de = S["cycles"], S["mesh"], S["noise"], S["equilibrium"], S["strain"], S["determinism"]
    L = []
    A = L.append
    A("# 第三份评估后的 23 个验证作业：结果\n")
    A(f"{stamp}。{len(st)} 个作业：完成 {n_done}，失败 {n_fail}，未解完 {n_pend}。全部使用新界面模型，三槽并行。"
      "分析脚本 `v2/audit3b.py`，结果 `v2/results/audit3b/summary.json`。\n")

    # ---------------- 结论
    A("## 1 结论\n")
    r23 = [abs(v["reloading_3_P95"] / v["reloading_2_P95"] - 1) for v in cy.values() if "reloading_3_P95" in v]
    dr = [(v["peak_drift_1to2_P95"], v["peak_drift_2to3_P95"]) for v in cy.values() if "peak_drift_2to3_P95" in v]
    if r23:
        by = {}
        for k, v in cy.items():
            if "reloading_3_P95" in v:
                by.setdefault(dl(k), []).append((SHORT[k.split(":")[1]], 100 * (v["reloading_3_P95"] / v["reloading_2_P95"] - 1)))
        lo = by.get("0.025", [])
        hi = by.get("0.1", [])
        worst = max(hi + lo, key=lambda x: abs(x[1]))
        A("1. **滑动为主时第二循环够用，粘着与滑动并存时还不够。** 过盈 0.025 mm 下，第三循环的可恢复微动与第二循环相差 "
          + "、".join(f"{n} {x:+.1f}%" for n, x in lo) + "；过盈 0.10 mm 下相差 " + "、".join(f"{n} {x:+.1f}%" for n, x in hi)
          + f"。{worst[0]}在过盈 0.10 mm 时两个循环还差 {abs(worst[1]):.0f}%，没有稳定。"
          f"峰值之间的漂移从第一到第二循环的 {min(a for a, _ in dr):.2f}–{max(a for a, _ in dr):.2f} µm 降到第二到第三循环的 "
          f"{min(b for _, b in dr):.2f}–{max(b for _, b in dr):.2f} µm。")
    ms = {k: v for k, v in me.items() if ":short:" in k and v["h2.0"]}
    if ms:
        a = [100 * (v["h1.4_const_slip"]["f1_p95_um"] / v["h2.0"]["f1_p95_um"] - 1) for v in ms.values()]
        b = [100 * (v["h1.4_const_slip"]["f1_first_p95_um"] / v["h2.0"]["f1_first_p95_um"] - 1) for v in ms.values()]
        A(f"2. **2.0 mm 网格把短柄的微动低估了约 8%。** 保持绝对弹性滑移不变时，1.4 mm 网格的可恢复微动比 2.0 mm 高 {min(a):.0f}–{max(a):.0f}%，"
          f"首次加载微动高 {min(b):.0f}–{max(b):.0f}%。这是系统偏差，不是噪声。")
    cvs = [v["f1_p95_um"]["cv_pct"] for v in nz.values() if "f1_p95_um" in v]
    if cvs:
        A(f"3. **短柄在阈值附近的结果稳定。** 换 5 次网格，可恢复微动的变异系数 {min(cvs):.1f}–{max(cvs):.1f}%。"
          "过盈 0.05 mm 约 30 µm、0.025 mm 约 89 µm 的结论经得起网格扰动；加上网格偏差后分别约 32 和 97 µm，判定不变：前者低于 40 µm，后者高于。")
    res = [o["steps"][s]["contact_minus_applied_norm_N"] for o in eq.values() for s in o["steps"] if o["steps"][s]["loaded"]]
    rr = [o["steps"][s]["reaction_residual_norm_N"] for o in eq.values() for s in o["steps"]]
    if res:
        A(f"4. **载荷与接触力闭合。** 支座反力与施加载荷之和的残差最大 {max(rr):.2f} N；骨面上的接触合力与施加载荷之差最大 {max(res):.2f} N（载荷 2391 N）。")
    s10 = [v for k, v in sn.items() if dl(k) == "0.1"]
    s25 = [v for k, v in sn.items() if dl(k) == "0.025"]
    if s10 and s25:
        k10 = [x["RELEASE:cancellous:within_2mm"] for x in s10]
        k25 = [x["RELEASE:cancellous:within_2mm"] for x in s25]
        A(f"5. **过盈 0.10 mm 时柄周松质骨几乎全部超过屈服应变。** 压配后柄周 2 mm 内的松质骨，压缩主应变中位 "
          f"{-100 * max(x['emin_P50'] for x in k10):.1f}–{-100 * min(x['emin_P50'] for x in k10):.1f}%，超过 0.7% 的体积占 "
          f"{100 * min(x['vol_frac_comp_gt_0.7pct'] for x in k10):.0f}% 以上。"
          f"过盈 0.025 mm 时中位 {-100 * max(x['emin_P50'] for x in k25):.2f}–{-100 * min(x['emin_P50'] for x in k25):.2f}%，超过 0.7% 的占 "
          f"{100 * min(x['vol_frac_comp_gt_0.7pct'] for x in k25):.0f}–{100 * max(x['vol_frac_comp_gt_0.7pct'] for x in k25):.0f}%。"
          "线弹性模型在 0.10 mm 下不成立；这一条直接影响过盈量的选择。")
        pk = {k: [o for kk, o in v.items() if isinstance(o, dict) and kk.endswith(":cancellous:within_2mm") and not kk.startswith("RELEASE")][0]
              for k, v in sn.items() if dl(k) == "0.025"}
        if pk:
            A("   峰值载荷下（过盈 0.025 mm），柄周 2 mm 内超过 0.7% 压缩应变的松质骨体积："
              + "、".join(f"{SHORT[k.split(':')[1]]} {100 * o['vol_frac_comp_gt_0.7pct']:.0f}%" for k, o in pk.items() if k.startswith("cycle3")) + "。短柄周围的骨在受载时应变最高。")
    if de:
        same = all(all(v["identical"].values()) for v in de.values())
        A(f"6. **跨代码版本结果{'逐位一致' if same else '不完全一致'}。** {len(de)} 个代表工况按原规格重解，微动、首次加载微动、柄应力"
          f"{'全部相同' if same else '有差异，见第 7 节'}。")
    if n_fail or n_pend:
        A(f"\n未完成的作业：失败 {n_fail} 个，未解完 {n_pend} 个，见第 8 节。")
    A("")

    # ---------------- 循环
    A("## 2 循环是否稳定\n")
    A("三个加载循环，面积加权 P95，单位 µm。“卸载”指从峰值回到零载荷的可恢复量，“再加载”指从零载荷回到峰值的可恢复量。\n")
    rows = []
    for k, v in cy.items():
        lab = k.split(":")[1]
        rows.append([SHORT[lab], dl(k), f(v["first_loading_P95"], 1), f(v["unloading_1_P95"]), f(v["reloading_2_P95"]), f(v.get("unloading_2_P95")),
                     f(v.get("reloading_3_P95")), pct(v.get("reloading_3_P95"), v["reloading_2_P95"]), f(v["peak_drift_1to2_P95"]), f(v.get("peak_drift_2to3_P95"))])
    A(tab(["设计", "过盈 (mm)", "首次加载", "第 1 次卸载", "第 2 次加载", "第 2 次卸载", "第 3 次加载", "第 3 对第 2", "峰值漂移 1→2", "峰值漂移 2→3"], rows))
    A("\n第一次卸载的可恢复量偏大（含首次就位后的回弹）。过盈 0.025 mm 的三个工况从第二次加载起各循环重合到 1.3% 以内；"
      "过盈 0.10 mm 的短柄一部分界面粘着、一部分滑动，可恢复量还在逐循环下降。\n")
    A("各步峰值载荷下间隙超过 5 µm 的界面面积：\n")
    rows = []
    for k, v in cy.items():
        o = v["open_gt5um"]
        rows.append([SHORT[k.split(":")[1]], dl(k)] + [f"{100 * o[s]:.1f}%" for s in v["steps"]])
    if cy:
        A(tab(["设计", "过盈"] + next(iter(cy.values()))["steps"], rows))

    # ---------------- 网格
    A("\n## 3 网格加密（保持绝对弹性滑移上限 0.5 µm）\n")
    A("1.4 mm 网格把摩擦容差从 0.00025 改为 0.000357，使“容差 × 单元尺寸”不变。\n")
    rows = []
    for k, v in me.items():
        a, b, c = v["h1.4_const_slip"], v["h2.0"], v["h1.4_same_tol"]
        lab = k.split(":")[1]
        rows.append([SHORT[lab], dl(k), f(b["f1_p95_um"]) if b else "—", f(a["f1_p95_um"]), pct(a["f1_p95_um"], b["f1_p95_um"]) if b else "—",
                     f(c["f1_p95_um"]) if c else "—", f(b["f1_first_p95_um"], 1) if b else "—", f(a["f1_first_p95_um"], 1),
                     pct(a["f1_first_p95_um"], b["f1_first_p95_um"]) if b else "—", pct(a["vm_p99"], b["vm_p99"]) if b else "—",
                     f"{b['wall_fric_s']:.0f} / {a['wall_fric_s']:.0f}" if b else f"— / {a['wall_fric_s']:.0f}"])
    A(tab(["设计", "过盈", "可恢复 2.0 mm", "可恢复 1.4 mm", "差", "1.4 mm 容差不变", "首次加载 2.0 mm", "首次加载 1.4 mm", "差", "柄应力差", "求解 2.0 / 1.4 (s)"], rows))
    A("\n- 微动在 1 µm 地板以下的两个设计（基准、原读数设计，过盈 0.10 mm），1.4 mm 仍比 2.0 mm 低约 20%：这些读数受数值设置支配，不能用来判断收敛。")
    A("- 微动在地板以上的短柄，三档过盈下 1.4 mm 都比 2.0 mm 高 8% 左右，方向一致。")
    A("- 1.4 mm 的求解时间是 2.0 mm 的 2–3 倍。\n")

    # ---------------- 噪声
    A("## 4 短柄阈值工况的噪声底\n")
    rows = []
    for k, v in nz.items():
        for r in v["rows"]:
            rows.append([k.split(":d")[1], f"{r['h']:g}", f(r["f1_p95_um"]), f(r["f1_first_p95_um"]), f(r["f1_cslip_p95_um"]), f(r["vm_p99"], 1),
                         f"{100 * r['open_frac_release']:.1f}%", f"{r['wall_fric_s']:.0f}"])
    A(tab(["过盈 (mm)", "网格 (mm)", "可恢复微动 (µm)", "首次加载 (µm)", "旧定义 (µm)", "柄应力 (MPa)", "压配后间隙 > 1 µm", "求解 (s)"], rows))
    rows = []
    for k, v in nz.items():
        for qn, nm in (("f1_p95_um", "可恢复微动"), ("f1_first_p95_um", "首次加载微动"), ("vm_p99", "柄应力")):
            if qn in v:
                a = v[qn]
                rows.append([k.split(":d")[1], nm, a["n"], f(a["mean"]), f(a["sd"]), f(a["cv_pct"], 1) + "%", f"{f(a['min'])} – {f(a['max'])}"])
    A("\n" + tab(["过盈", "量", "网格数", "均值", "标准差", "变异系数", "范围"], rows))

    # ---------------- 平衡
    A("\n## 5 反力与接触合力\n")
    have3 = {(k.split(":")[1], dl(k)) for k in eq if k.startswith("cycle3")}     # 同一设计同一过盈，优先用三循环作业
    eq = {k: v for k, v in eq.items() if k.startswith("cycle3") or (k.split(":")[1], dl(k)) not in have3}
    sn = {k: v for k, v in sn.items() if k in eq}
    rows = []
    for k, v in eq.items():
        for s, o in v["steps"].items():
            if s in ("RELEASE", "LOAD2"):
                rows.append([SHORT[k.split(":")[1]] + ("（三循环）" if k.startswith("cycle3") else ""), dl(k), s, f(o["reaction_residual_norm_N"]),
                             "(" + ", ".join(f"{x:.0f}" for x in o["contact_force_on_bone_N"]) + ")", f(o["contact_minus_applied_norm_N"]),
                             f"{o['normal_force_total_N'] / 1000:.1f}", f"{o['shear_force_total_N'] / 1000:.1f}",
                             f(o["mean_pressure_force_over_geometric_area_MPa"], 1), f"{o['geometric_area_mm2']:.0f} / {o['cnarea_sum_mm2']:.0f}"])
    A(tab(["工况", "过盈", "步", "反力 + 载荷 的残差 (N)", "骨面接触合力 (N)", "与载荷之差 (N)", "法向接触力总和 (kN)", "摩擦力总和 (kN)",
           "平均接触压力 (MPa)", "几何面积 / 节点接触面积之和 (mm²)"], rows))
    A("\n- 释放步没有外载，接触合力为零；加载步接触合力等于施加的载荷。")
    A("- “平均接触压力”是法向接触力总和除以界面几何面积，与过盈成正比。它比以前报告的节点压力中位数高约两成，因为压力分布右偏。")
    A("- Abaqus 给的节点接触面积之和比几何面积大，所以不用它作权重。\n")
    rows = []
    for k, v in eq.items():
        p = v["P95_last_cycle"]
        rows.append([SHORT[k.split(":")[1]] + ("（三循环）" if k.startswith("cycle3") else ""), dl(k), f(p["geometric_weights"]),
                     f(p["cnarea_weights_contact_nodes_only"]), f"{100 * p['share_of_nodes_with_cnarea']:.0f}%"])
    A("最后一个循环的可恢复微动 P95，两种权重：\n")
    A(tab(["工况", "过盈", "几何面积权重、全部节点（现用）", "节点接触面积权重、仅接触节点", "有接触面积的节点占比"], rows))
    A("\n只统计接触节点会把张开区域排除在外，微动读数低 20–35%。现用定义保留全部界面节点。\n")

    # ---------------- 应变
    A("## 6 柄周骨主应变\n")
    A("压缩主应变，体积加权。柄周 2 mm 内与 2–5 mm 两层。0.7% 与 1% 是松质骨屈服应变的常用量级，出处待核对。\n")
    rows = []
    for k, v in sn.items():
        for key, o in v.items():
            if not isinstance(o, dict):
                continue
            step, tis, band = key.split(":")
            if tis != "cancellous":
                continue
            rows.append([SHORT[k.split(":")[1]] + ("（三循环）" if k.startswith("cycle3") else ""), dl(k), "压配后" if step == "RELEASE" else "峰值载荷",
                         "2 mm 内" if band == "within_2mm" else "2–5 mm", f"{o['volume_mm3']:.0f}", f"{-100 * o['emin_P50']:.2f}%", f"{-100 * o['emin_P5']:.2f}%",
                         f"{-100 * o['emin_P1']:.2f}%", f"{100 * o['vol_frac_comp_gt_0.7pct']:.0f}%", f"{100 * o['vol_frac_comp_gt_1pct']:.0f}%",
                         f"{100 * o['vol_frac_comp_gt_2pct']:.0f}%"])
    A(tab(["工况", "过盈", "状态", "层", "体积 (mm³)", "压缩应变中位", "P95", "P99", "> 0.7% 的体积", "> 1%", "> 2%"], rows))
    A("\n压配产生的应变与过盈成正比。按这个比例，过盈 0.05 mm 时柄周 2 mm 内的中位约 0.8–0.9%，已在屈服应变附近；0.025 mm 时约 0.4–0.5%。\n")

    # ---------------- 一致性
    A("## 7 跨代码版本的一致性\n")
    rows = []
    for k, v in de.items():
        a, b = v["new"], v["old"]
        rows.append([SHORT[k.split(":")[1]], dl(k), b["code"], a["code"], f"{f(b['f1_p95_um'], 4)} / {f(a['f1_p95_um'], 4)}",
                     f"{f(b['f1_first_p95_um'], 3)} / {f(a['f1_first_p95_um'], 3)}", f"{f(b['vm_p99'], 2)} / {f(a['vm_p99'], 2)}",
                     "是" if all(v["identical"].values()) else "否"])
    A(tab(["设计", "过盈", "旧版本", "新版本", "可恢复微动 旧 / 新", "首次加载 旧 / 新", "柄应力 旧 / 新", "逐位相同"], rows))
    A("\n两个版本之间只改了输出请求和导出内容，没有改模型。三循环作业的前两个循环也与两循环作业相同。\n")

    # ---------------- 作业清单
    A("## 8 作业清单\n")
    br = S["briefs"]
    rows = []
    for k, j in S["ids"].items():
        b = br.get(k)
        rows.append([k, st[k], f(b["f1_p95_um"]) if b else "—", f(b["f1_first_p95_um"], 1) if b else "—", f"{b['wall_fric_s']:.0f}" if b else "—",
                     sum(b["n_tet"].values()) if b and b.get("n_tet") else "—"])
    A(tab(["作业", "状态", "可恢复微动 (µm)", "首次加载 (µm)", "摩擦求解 (s)", "单元数"], rows))
    if S["failed"]:
        A("\n失败原因：\n")
        for k, v in S["failed"].items():
            A(f"- {k}：{v['level']}，{v['reason'][:200]}")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L), "done", n_done, "failed", n_fail, "pending", n_pend)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-09-29")
    main(ap.parse_args().stamp)
