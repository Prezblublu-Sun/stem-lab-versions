"""对照 Naghavi 2023 论文之后的四项零求解改进：结果文档（本机跑）。

数字全部取自 results/resorption/{zones.csv, zones_k6.csv, stem.csv, null.json, summary.json}（由 v2/resorption.py 在 Linux 上生成）。
论文数字是抄录的常量，带页码。

    python v2/build_ata_followup_doc.py [--stamp "2026-09-29 16:00"]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib

import numpy as np
from scipy.stats import spearmanr

HERE = pathlib.Path(__file__).resolve().parent
R = HERE / "results" / "resorption"
OUT = HERE / "ATA_FOLLOWUP_2026-09-29.md"
ZONES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "total")
S_LIST = ("0.4", "0.6", "0.75")
SCH = {"stem": "柄坐标系", "femur": "股骨坐标系，随柄定位", "fixed": "股骨坐标系，固定"}

# 论文常量（Naghavi 2023）
T_RES = {"实心钛": {"G1": "约 73", "G6": "约 73", "G7": "89", "G2": "10–20", "G3": "10–20", "G5": "10–20", "total": "41"},
         "多孔钛": {"G1": "约 44", "G7": "约 44", "total": "16"}, "PEEK": {"G1": "约 31", "G7": "约 31", "total": "12"}}     # p.239
T_SSI = {"G1": 69, "G6": 45, "G7": 68, "total": 32}                                                                # p.237，实心钛
T_N, T_Y, T_UT = 375.0, 788.0, 882.0                                                                               # p.224–225
LOADS = (("本项目工况 2391 N", 1.0), ("放大到上楼高载荷档 3606 N", 3606.0 / 2391.0))


def read(name):
    with open(R / name, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in r.items():
            if k not in ("job_id", "version", "scheme", "zone", "tissue"):
                r[k] = float(v) if v not in ("", "nan", "None") else math.nan
    return [r for r in rows if r["version"] == "current"]


def tab(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def vals(rows, sc, z, key, tis="cortex"):
    v = np.array([r.get(key, math.nan) for r in rows if r["scheme"] == sc and r["zone"] == z and r["tissue"] == tis])
    return v[np.isfinite(v)]


def num(x, n=0):
    t = f"{x:.{n}f}"
    return t.lstrip("-") if float(t) == 0 else t


def med(v, n=0):
    return num(np.median(v), n) if len(v) else "—"


def rng(v, n=0):
    return f"{num(v.min(), n)} 到 {num(v.max(), n)}" if len(v) else "—"


def iqr(v, n=0):
    return f"{num(np.percentile(v, 25), n)} 到 {num(np.percentile(v, 75), n)}" if len(v) else "—"


def rho(rows, sc, z, key, var):
    rr = [r for r in rows if r["scheme"] == sc and r["zone"] == z and r["tissue"] == "cortex" and np.isfinite(r.get(key, math.nan))]
    return spearmanr([r[var] for r in rr], [r[key] for r in rr])[0]


def fos(smax, kind):
    sa, sm = 0.45 * smax, 0.55 * smax                       # R = 0.1
    if kind == "fatigue":
        return T_N / smax
    return 1.0 / (sa / T_N + sm / (T_UT if kind == "goodman" else T_Y))


def main(stamp):
    Z, Z6, ST = read("zones.csv"), read("zones_k6.csv"), read("stem.csv")
    NUL = json.loads((R / "null.json").read_text(encoding="utf-8"))
    SUM = json.loads((R / "summary.json").read_text(encoding="utf-8"))
    n = len({r["job_id"] for r in Z})
    L = []
    A = L.append
    g = lambda z, s, sc="femur": vals(Z, sc, z, f"res_{s}")
    A("# 对照论文之后的四项改进：结果\n")
    A(f"生成时间：{stamp}。没有新的求解。数据是 {n} 个现行版本设计的粘接模型结果，加一个完整股骨参照。"
      "论文指 Naghavi 2023 博士论文，对照本身见 `v2/ATA_THESIS_COMPARISON_2026-09-29.pdf`。\n")

    # ---------------------------------------------------------------- 1
    body, neck, junc = (np.array([r[f"vm_max_{k}"] for r in ST]) for k in ("body_deep", "neck_free", "junction"))
    A("## 1 结论\n")
    A(f"1. **骨吸收**已按论文的口径算出。死区取 0.6 时，皮质骨被判为吸收的比例，{n} 个设计的中位数是："
      f"7 区 {med(g('G7', '0.6'))}%，6 区 {med(g('G6', '0.6'))}%，1 区 {med(g('G1', '0.6'))}%，总值 {med(g('total', '0.6'))}%。")
    A("2. **分区口径**换成股骨坐标系之后，7 区的结果基本不变，2 区和 6 区变化明显。固定分区下只有 7 区有成规模的屏蔽。")
    A(f"3. **柄应力**的最大值都落在截骨面上颈与柄体的交界，那里是模型的尖角，数值不能用。"
      f"离开交界 3 mm 之外，柄体最大 {body.min():.0f}–{body.max():.0f} MPa，假体颈最大 {neck.min():.0f}–{neck.max():.0f} MPa。现行约束没有覆盖假体颈。")
    A("4. **名称**已在现行文档里统一为“去骨体积”。带日期的旧报告没有改。\n")

    # ---------------------------------------------------------------- 2
    A("## 2 算法与本底\n")
    A(f"- 在骨内每 {SUM['grid_mm']} mm 取一个采样点，共 {NUL['n_points']} 个，按距离场判定皮质或松质。")
    A("- 每个点取同一骨质里最近单元的应变能密度和 von Mises 应力。完整股骨和植入股骨用同一组点，两套网格因此可以逐点比较。")
    A("- 逐点算应变能密度之比。比值低于 1 − s 判为吸收，高于 1 + s 判为增生，s 是死区。这是论文第 222–223 页的规则。")
    A("- 只统计两个模型里都存在的骨：截骨面以下，柄体之外。每个点代表相同体积，皮质骨内密度均匀，体积分数就是质量分数。\n")
    A("**空白对照。** 用完整股骨的 1.4 mm 网格对 2.0 mm 网格。两者是同一个模型，算出的比例就是网格和映射造成的本底。皮质骨，固定分区：\n")
    nk = {r["zone"]: r for r in NUL["k"]["1"] if r["tissue"] == "cortex"}
    A(tab(["分区", "平均应变能密度之差（%）", "吸收，死区 0.4（%）", "死区 0.6（%）", "死区 0.75（%）", "增生，死区 0.6（%）"],
          [["总值" if z == "total" else z[1] + " 区", f"{nk[z]['sed_chg_pct']:+.1f}", f"{nk[z]['res_0.4']:.1f}", f"{nk[z]['res_0.6']:.1f}",
            f"{nk[z]['res_0.75']:.1f}", f"{nk[z]['gain_0.6']:.1f}"] for z in ZONES]))
    gv = SUM["grid_vs_element_vm_change_pct_points"]
    A(f"\n死区 0.6 下本底不超过 {max(nk[z]['res_0.6'] for z in ZONES):.1f}%，可以忽略。死区 0.4 下个别区达到 "
      f"{max(nk[z]['res_0.4'] for z in ZONES):.1f}%，读数时要留这个余量。\n")
    A(f"**与原有统计的一致性。** 采样网格算出的分区应力变化，与此前逐单元算的相比，{gv['n']} 个分区的差的中位数是 "
      f"{gv['median']:+.1f} 个百分点，P5 到 P95 是 {gv['p05']:+.1f} 到 {gv['p95']:+.1f}。两种算法一致。\n")
    d6 = [a - b for a, b in zip(vals(Z6, "femur", "total", "res_0.6"), vals(Z, "femur", "total", "res_0.6"))]
    d7 = [a - b for a, b in zip(vals(Z6, "femur", "G7", "res_0.6"), vals(Z, "femur", "G7", "res_0.6"))]
    A(f"**平滑的影响。** 每个点改取最近 6 个单元的平均，总值的中位变化 {np.median(d6):+.1f} 个百分点，7 区 {np.median(d7):+.1f} 个百分点。"
      "下文用不平滑的结果。\n")

    # ---------------------------------------------------------------- 3
    A("## 3 骨吸收质量分数\n")
    A("皮质骨，股骨坐标系分区，数字是被判为吸收的骨占该区的百分比：\n")
    A(tab(["分区", "死区 0.4 中位", "死区 0.6 中位", "死区 0.6 范围", "死区 0.75 中位", "论文实心钛柄，死区 0.6"],
          [["总值" if z == "total" else z[1] + " 区", med(g(z, "0.4")), med(g(z, "0.6")), rng(g(z, "0.6")), med(g(z, "0.75")),
            T_RES["实心钛"].get(z, "—")] for z in ZONES]))
    A("\n论文的总值：实心钛 41%，多孔钛 16%，PEEK 12%（第 239 页）。\n")
    A("![骨吸收](results/resorption/figs/R2_resorption_zones.png)\n")
    A("*各 Gruen 区被判为吸收的皮质骨比例，三个死区取值。箱体是四分位范围，须线不含离群点。*\n")
    A("读这张表要注意三点。\n")
    A("- 本项目的总值只有论文实心钛柄的三分之一左右，与论文的多孔钛柄相当。原因之一是柄短：分区跟着柄走，短柄的分区只覆盖近端一小段骨。"
      "两边的股骨、载荷、柄型都不同，这个比较只说明量级。")
    A("- 7 区在所有死区下都是吸收最重的区，这一点与论文一致。")
    A("- 每个区里同时有约两成的皮质骨被判为增生。论文没有统计增生。\n")
    A("固定分区下，哪些设计变量与总吸收量相关（Spearman 相关系数，死区 0.6）：\n")
    A(tab(["变量", "总值", "7 区", "1 区"],
          [[nm] + [f"{rho(Z, 'fixed', z, 'res_0.6', var):+.2f}" for z in ("total", "G7", "G1")]
           for nm, var in (("柄长", "L"), ("插入角", "alpha"), ("截骨高度", "h_cut"), ("皮质余量", "m"), ("肩部面积", "A0"))]))
    A("\n固定分区对所有设计统计的是同一块骨，所以这张表可以用来比较设计。\n")

    # ---------------------------------------------------------------- 4
    A("## 4 分区口径\n")
    A("三套分区：\n")
    A("- **柄坐标系**：沿柄轴三等分，按柄轴分内外侧。本项目此前一直用这一套。")
    A("- **股骨坐标系，随柄定位**：柄入口到柄尖的竖直范围三等分，水平切分，按柄轴线分内外侧。这是论文图 5-9 的做法。")
    A("- **股骨坐标系，固定**：以小转子为零点，分界在 −10、−40、−70、−100 mm，按股骨干轴线分内外侧。不随设计变化。分界是我定的，可以改。\n")
    A("皮质骨应力屏蔽的中位数与四分位范围，正值表示被屏蔽（%）：\n")
    A(tab(["分区"] + [SCH[s] for s in SCH] + ["论文实心钛柄"],
          [["总值，按体积加权" if z == "total" else z[1] + " 区"]
           + [f"{med(vals(Z, s, z, 'ssi_vw_pct' if z == 'total' else 'ssi_pct'))}（{iqr(vals(Z, s, z, 'ssi_vw_pct' if z == 'total' else 'ssi_pct'))}）"
              for s in SCH] + [T_SSI.get(z, "—")] for z in ZONES]))
    A("\n![分区口径](results/resorption/figs/R1_ssi_schemes.png)\n")
    A("*三套分区下各 Gruen 区的皮质应力屏蔽。*\n")
    A("7 区应力屏蔽与设计变量的相关系数，三套分区对照：\n")
    A(tab(["分区口径", "对柄长", "对插入角", "对截骨高度"],
          [[SCH[s]] + [f"{rho(Z, s, 'G7', 'ssi_pct', v):+.2f}" for v in ("L", "alpha", "h_cut")] for s in SCH]))
    A("\n随柄定位的两套分区里，7 区的骨随设计变化，相关系数混进了“统计范围变了”的影响。要回答“哪个变量控制股骨距的屏蔽”，应当看固定分区那一行。\n")
    A("建议：报告里用“股骨坐标系，随柄定位”与文献对照，用“固定”比较设计。柄坐标系的那一套不再作为主口径。\n")

    # ---------------------------------------------------------------- 5
    A("## 5 柄应力\n")
    A("现行约束用的是截骨面以下柄体的 von Mises P99。这次把柄分成三段分别统计，应力取单元质心值，载荷 2391 N：\n")
    rows = []
    for nm, k in (("柄体，离交界 3 mm 以上", "body_deep"), ("交界，截骨面两侧各 3 mm", "junction"), ("假体颈，离交界 3 mm 以上", "neck_free")):
        mx, p99 = np.array([r[f"vm_max_{k}"] for r in ST]), np.array([r[f"vm_p99_{k}"] for r in ST])
        rows.append([nm, f"{np.median(p99):.0f}", f"{p99.min():.0f}–{p99.max():.0f}", f"{np.median(mx):.0f}", f"{mx.min():.0f}–{mx.max():.0f}"])
    A(tab(["部位", "P99 中位", "P99 范围", "最大值中位", "最大值范围"], rows))
    tj = np.array([r["t_at_max_junction"] for r in ST])
    A(f"\n交界处最大应力的位置离截骨面只有 {np.percentile(np.abs(tj), 50):.1f} mm（中位）。那里是圆柱形假体颈与柄肩直接相接的尖角，"
      "同时是粘接界面的边缘，两者都会造成应力奇异。这个数值随网格加密会继续升高，不能当作强度依据。\n")
    A("按论文的判据重新判断。论文对增材制造钛合金取疲劳极限 375 MPa、屈服 788 MPa、抗拉 882 MPa，要求安全系数不低于 2（第 224–225 页）。"
      "下表用交界以外的最大应力，应力比取 0.1：\n")
    rows = []
    for nm, sc in LOADS:
        for pn, arr in (("柄体", body), ("假体颈", neck)):
            s = arr * sc
            rows.append([nm, pn, f"{np.median(fos(s, 'fatigue')):.1f}", f"{100 * np.mean(fos(s, 'fatigue') < 2):.0f}%",
                         f"{np.median(fos(s, 'soderberg')):.1f}", f"{100 * np.mean(fos(s, 'soderberg') < 2):.0f}%",
                         f"{100 * np.mean(fos(s, 'soderberg') < 1):.0f}%"])
    A(tab(["载荷", "部位", "疲劳安全系数中位", "低于 2 的设计", "Soderberg 安全系数中位", "低于 2 的设计", "低于 1 的设计"], rows))
    A("\n疲劳安全系数是疲劳极限除以最大应力。Soderberg 安全系数把一个循环里的平均应力和交变应力分开计，数值更高。"
      "论文两个都给了，判定用 Soderberg。\n")
    A("对照文档第 4.2 节的 19% 和 72% 用的是含交界的柄体 P99 对 188 MPa，是粗估。这张表去掉了交界，改用最大值，以这张表为准。\n")
    A("放大到 3606 N 用的是线性比例，绑定模型是线弹性的，可以这样放大。载荷方向没有变。\n")
    A("由此得到四条。\n")
    A("1. 现行的 440 MPa 约束从不起作用，是因为许用值宽，而且只看柄体的 P99。")
    A("2. 假体颈的应力与柄体同量级，但不在现行约束里。截骨越低，露在骨外的颈越长，颈部应力越高。")
    nl = np.array([r["neck_len"] for r in ST])
    A(f"   本批设计里骨外颈长 {nl.min():.0f}–{nl.max():.0f} mm，颈部最大应力与它的相关系数是 "
      f"{spearmanr(nl, neck)[0]:+.2f}。")
    A("3. 交界处的应力要等假体颈改成带圆角的真实形状之后才能评价。这需要改建模，也会改变代码版本。")
    A("4. 论文的多孔柄模型安全系数 4.7，疲劳试验却只撑了目标寿命的约 10%（第 254 页）。静力安全系数只能作筛选，不能当作疲劳寿命的证明。\n")
    A("许用值取多少，取决于你打算用的制造方式。增材制造可以沿用论文的 375 MPa。锻造或机加工的钛合金疲劳极限更高，需要另找出处。\n")

    # ---------------------------------------------------------------- 6
    A("## 6 名称\n")
    A(tab(["文件", "处理"], [
        ["`PROJECT_HISTORY_base.md` 与 `build_history.py`", "“骨量损失”全部改为“去骨体积”，开头加了术语说明"],
        ["`v2/REVISION_PLAN_V4.md`", "同上"],
        ["`v2/METHODS_draft.md`", "bone loss 改为 bone removal volume"],
        ["`REPORTING_SPEC.md`", "加了一条术语规定，今后的报告都按它执行"],
        ["V3 报告、09-28 日报、应力屏蔽报告、第三份评估复核", "没有改。它们是带日期的记录，其中 V3 的结论已经撤回"],
        ["结果文件里的字段名 `bone_loss`", "没有改。改了会使已有结果读不出来"]]))

    # ---------------------------------------------------------------- 7
    A("\n## 7 对后续计划的影响\n")
    A("- 应力屏蔽仍然只报告、不进优化，这是你此前的决定。报告的量增加两个：骨吸收质量分数，和按体积加权的总值。")
    A("- 柄强度约束建议改为：交界以外的最大应力，柄体与假体颈都算，许用值按制造方式定。这一条需要你决定。")
    A("- 假体颈与柄肩的交界需要重新建模。在那之前，强度结论只对交界以外的部分成立。\n")
    A("还需要新求解的事项，与对照文档第 8 节相同：\n")
    A(tab(["事项", "作业数", "状态"], [
        ["植入模型的皮质分区应力网格检查", "约 8 个绑定作业", "完整股骨的部分已由本文的空白对照覆盖，两套网格的分区平均值相差不到 2%"],
        ["2300 N 对照工况", "约 4 个绑定作业", "需要加一个载荷选项"],
        ["柄模量敏感性", "约 9 个", "需要加一个柄模量选项"],
        ["肌力与步行工况", "8 个", "需要肌肉附着点和载荷表"],
        ["Reimeringer 2013 对标", "2–4 个", "需要 Sawbones 几何"],
        ["水泥包埋工况的强度校核", "3 个", "需要新的建模和标准原文"]]))
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stamp", default="2026-09-29")
    main(ap.parse_args().stamp)
