"""由 v2/results/audit3/summary.json 生成 v2/REVIEW3_AUDIT.md（本机跑）。表格数字全部由数据算出。"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
S = json.loads((HERE / "results" / "audit3" / "summary.json").read_text(encoding="utf-8"))
OUT = HERE / "REVIEW3_AUDIT.md"
NAME = {"base": "基准（L 60，α 20°）", "readout": "原读数设计（L 53，α 39°）", "short": "短柄（L 25，α 37°）"}
CAD = [  # 2026-09-29 10:20 在 Linux 上用 gmsh OCC 实体布尔算出（scratch/cadvol.py），单位 mm³
    ("原读数设计 L 53", 4383, 4410, 4552), ("原前沿 L 62", 4664, 4589, 4552), ("原前沿 L 48", 4979, 4958, 5203),
    ("原前沿 L 58", 7885, 7799, 7625), ("基准 L 60", 7379, 7036, 7382)]


def f(x, n=2):
    return "—" if x is None else f"{x:.{n}f}"


def tab(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def main():
    M = S["micromotion"]
    L = []
    A = L.append
    A("# 第三份评估意见的复核\n")
    A("2026-09-29 10:30。复核只用已有结果重算，没有新增有限元求解。脚本 `v2/audit3.py`，结果 `v2/results/audit3/summary.json`。"
      "被复核的是三个代表设计在四档过盈下的 12 个新界面模型作业、272 个旧模型设计的去骨体积、全部作业的版本记录。\n")
    A("## 1 结论\n")
    A("这份意见基本成立。八类数据里，四类我们已经按它要求的方式在做，三类复核后发现我以前的说法要更正，五项必须新解才能回答。\n")
    A("**要更正的三处**：\n")
    sh = S["shielding_fixed_zone"]
    A(f"1. **“插入角决定股骨距遮挡”只在随柄移动的分区里成立。** 分区跟着柄走时，股骨距皮质应力变化与插入角的秩相关是 "
      f"{sh['G7:chg_vm_pct']['spearman_alpha']:+.2f}、与柄长 {sh['G7:chg_vm_pct']['spearman_L']:+.2f}；换成固定的解剖区域，"
      f"与插入角只有 {sh['calcar_fixed:chg_vm_pct']['spearman_alpha']:+.2f}，与柄长是 {sh['calcar_fixed:chg_vm_pct']['spearman_L']:+.2f}。"
      "固定区里起主导作用的是柄长，柄越长遮挡越重。")
    lo = {k: M[f"{k}:delta0.1"]["load"] for k in NAME}
    A(f"2. **绕柄轴的扭矩不是约 28 N·m。** 三个代表设计绕柄自身轴线的扭矩是 {lo['base']['torsion_about_stem_axis_Nm']:+.1f}、"
      f"{lo['readout']['torsion_about_stem_axis_Nm']:+.1f}、{lo['short']['torsion_about_stem_axis_Nm']:+.1f} N·m。28 N·m 是绕股骨干轴的力矩。"
      "保颈柄的轴线靠近颈轴，头心离柄轴只有 3–13 mm。所以“去扭转”变体实际去掉的是前后向分力：合力从 2391 降到 2287 N，扭矩和弯矩同时改变。")
    ver = S["versions"]
    pre = [v for v in ver if v["code_hash"] in ("af2719da27", "3edd9887e5")]
    npre = sum(v["n_jobs"] for v in pre)
    A(f"3. **V2A 的验证是在假体颈修正前的模型上做的。** 修正前的两个代码版本共 {npre} 个作业，包含全部符号检查、网格收敛、排序保持、端到端试跑和 61 个参考设计。"
      "修正后这些验证没有重做。旧模型已被新界面模型取代，这一条不影响以后，但 V2A 报告里“验证通过”只对修正前的几何成立。\n")
    A("**复核后站得住的**：存档的微动值可以从节点对位移原样重算；微动是逐节点求差再取 P95；张开的节点留在分母里；没有重复施加力矩；"
      "载荷坐标变换与 Bergmann 2016 原文一致；超体积参考点确实是 35.7 µm。\n")
    A("**必须新解才能回答的**（第 9 节，约 25 个作业、3–4 小时）：循环是否稳定；网格加密时保持绝对弹性滑移不变；短柄在过盈 0.05 与 0.025 mm 下的噪声底；"
      "反力、接触合力与骨应变的导出；文献对标。\n")

    A("## 2 逐项复核\n")
    vs = S["volume_summary"]
    hv = S["hypervolume"]
    A(tab(["意见", "复核结果", "判定"], [
        ["微动应逐节点求差后再取 P95", "代码就是这样做的。若改成“两个 P95 相减”，短柄过盈 0.025 mm 会得到 "
         f"{f(M['short:delta0.025']['wrong_way_difference_of_P95'], 1)} µm，正确值 {f(M['short:delta0.025']['stored_f1'], 1)} µm", "已满足"],
        ["张开区域不能从分母删除", "全部界面节点对都计入；另报仅闭合节点的值", "已满足"],
        ["明确比较的两个状态", "主指标是第二次加载对卸载；另存首次加载对释放。第 3 节补了首次卸载、残余迁移、峰对峰漂移", "已满足，已补充"],
        ["检查循环是否稳定", "粘着为主的工况不稳定：短柄过盈 0.10 mm 首次卸载 "
         f"{f(M['short:delta0.1']['P95']['reversible_cycle1_unloading'], 1)} µm，再加载 {f(M['short:delta0.1']['P95']['reversible_cycle2'], 1)} µm。滑动为主的工况两者相差 7% 以内", "**成立**，需第三循环"],
        ["面积权重", f"两种面积权重在微动 > 5 µm 时相差 2% 以内；低于地板时相差 12–22%；不加权最多差 5 倍", "成立，已量化"],
        ["摩擦容差与网格尺寸耦合", "低于地板的读数随单元尺寸按 1.43 倍缩放，已在验证报告中指出；保持绝对滑移不变的加密还没做", "成立，需新解"],
        ["实现的过盈场", f"过盈施加在 {100 * M['base:delta0.1']['interference']['area_with_delta']:.1f}–{100 * M['readout:delta0.1']['interference']['area_with_delta']:.1f}% 的界面上，"
         "其余是皮质相邻节点，过盈为 0", "已记录"],
        ["各阶段接触与张开面积", "第 4 节逐步列出。过盈越小，峰值载荷下张开越多，短柄过盈 0.025 mm 时 34%", "已补充"],
        ["接触压力如何加权", "表中是闭合节点的面积加权分位数。算术平均被奇异节点支配（基准设计 151 对 9.5 MPa），不能用", "成立，已说明"],
        ["接触合力、力矩、骨主应变", "没有导出，现有数据算不出", "**缺**，需改导出后重解"],
        ["载荷与力矩", f"只有节点力，没有附加力矩。合力 2391.0 N；载荷作用点偏离头心 {f(lo['base']['offset_norm_mm'])} mm，附带力矩 {f(lo['base']['parasitic_moment_norm_Nm'])} N·m", "无重复计入"],
        ["坐标变换", "Bergmann 2016 原文：+y 指向前方；Fx 恒为正，力从内侧作用；Fy 基本为负，力从前方作用。模型里的力指向外、后、下，一致", "已核实"],
        ["反力与反力矩", "没有导出", "**缺**"],
        ["“去扭转”的命名", "它去掉的是前后向分力，同时改变了合力与弯矩", "成立，改名"],
        ["去骨体积复核", f"{vs['n']} 个设计用体素独立计算：与旧定义的比值中位 {f(vs['ratio_voxel_to_old']['median'], 3)}，"
         f"90% 的设计在 {f(vs['ratio_voxel_to_old']['P5'], 2)}–{f(vs['ratio_voxel_to_old']['P95'], 2)}，极端 {f(vs['ratio_voxel_to_old']['min'], 2)} 与 {f(vs['ratio_voxel_to_old']['max'], 2)}；秩相关 {f(vs['spearman_old_vs_voxel'], 3)}", "基本可靠，有 ±5% 的不确定"],
        ["截骨与锉腔重叠", "两者被截骨面隔开，不重叠。但解析柄体积里有一部分在截骨面以上（中位 "
         f"{100 * vs['stem_body_above_cut_share']['median']:.1f}%，最大 {100 * vs['stem_body_above_cut_share']['max']:.0f}%）", "无重复计数，有漏计与多计"],
        ["皮质与松质骨去除量", f"锉掉的骨里皮质中位占 {100 * vs['cortex_share_of_reamed']['median']:.2f}%，最大 {100 * vs['cortex_share_of_reamed']['max']:.1f}%", "已拆分"],
        ["模型身份", "第 7 节逐版本列表。新界面模型 47 个作业是同一个版本", "成立，见更正 3"],
        ["应力屏蔽的分区", "见更正 1", "**成立**"],
        ["超体积参考点", f"微动参考值 {f(hv['s0']['ref_f1_um'], 1)} µm。旧模型 {hv['all_old_designs']['n']} 个设计里 {hv['all_old_designs']['f1_gt_ref']} 个超过它，"
         f"其中满足旧约束的 {hv['all_old_designs']['f1_gt_ref_and_sed_le30']} 个", "成立"]]))

    A("## 3 微动\n")
    A("存档值与从节点对位移重算的值逐位一致（12 个作业）。下表都是面积加权 P95，单位 µm。\n")
    rows = []
    for k in ("base", "readout", "short"):
        for d in ("0.1", "0.05", "0.025", "0.01"):
            a = M.get(f"{k}:delta{d}")
            if a:
                p = a["P95"]
                rows.append([NAME[k].split("（")[0], d, f(p["first_loading"], 1), f(p["residual_after_cycle1"], 1), f(p["reversible_cycle1_unloading"]),
                             f(p["reversible_cycle2"]), f"{100 * (p['reversible_cycle2'] / p['reversible_cycle1_unloading'] - 1):+.0f}%", f(p["peak_to_peak_drift"])])
    A(tab(["设计", "过盈 (mm)", "首次加载", "首循环后残余", "首次卸载的可恢复量", "再加载的可恢复量", "两者之差", "两次峰值之间的漂移"], rows))
    A("\n- **首次加载 ≈ 一次性就位 + 可恢复运动。** 基准设计过盈 0.10 mm：首次加载 6.1 µm 里，5.3 µm 在卸载后留下不回来。")
    A("- **粘着为主时循环还没稳定。** 过盈 0.10 mm 下再加载的可恢复量比首次卸载小 36–45%。")
    A("- **滑动为主时两个循环接近。** 过盈 ≤ 0.025 mm 以及短柄过盈 0.05 mm，两者相差 7% 以内；但每个循环峰值位置还在漂移 1–6 µm，是否收敛要看第三循环。\n")
    A("**权重敏感性**（可恢复微动 P95，µm）：\n")
    rows = []
    for k in ("base", "readout", "short"):
        for d in ("0.1", "0.05", "0.025", "0.01"):
            a = M.get(f"{k}:delta{d}")
            if a:
                w = a["weights"]
                rows.append([NAME[k].split("（")[0], d, f(w["A/6 all nodes"]), f(w["consistent (midside A/3)"]), f(w["unweighted"]),
                             f(a["quantiles_rev2"]["P50"]), f(a["quantiles_rev2"]["P99"], 1), f(a["quantiles_rev2"]["max"], 1),
                             f"{100 * a['area_frac_rev2_gt']['40']:.0f}%"])
    A(tab(["设计", "过盈", "现用权重（每面六节点均分）", "一致节点面积", "不加权", "中位", "P99", "最大", "> 40 µm 的面积"], rows))
    A("\n微动低、分布尾部重的工况，P95 对权重很敏感：短柄过盈 0.10 mm 不加权是 23.5 µm，面积加权是 4.6 µm。高微动集中在面积很小的单元上。"
      "以后每个设计除 P95 外同时报中位、P99 和超阈值面积比例。\n")
    A("**高微动在哪里**（微动最高的 5% 面积落在各区域的份额）：\n")
    rows = []
    for k in ("base", "readout", "short"):
        for d in ("0.1", "0.025"):
            a = M.get(f"{k}:delta{d}")
            if a:
                r = a["regions"]
                rows.append([NAME[k].split("（")[0], d] + [f"{100 * r[z]['share_of_top5pct_area']:.0f}%" for z in
                                                         ("proximal third", "middle third", "distal third + tip", "medial", "lateral", "anterior", "posterior")])
    A(tab(["设计", "过盈", "近段", "中段", "远段与柄尖", "内侧", "外侧", "前方", "后方"], rows))
    A("\n短柄在过盈 0.10 mm 时高微动在近段，降到 0.025 mm 后转到远段、内侧、后方：压配不足时柄绕近端摆动。\n")

    A("## 4 压配与接触状态\n")
    A("间隙超过 5 µm 的界面面积，按步：\n")
    rows = []
    for k in ("base", "readout", "short"):
        for d in ("0.1", "0.05", "0.025", "0.01"):
            a = M.get(f"{k}:delta{d}")
            if a:
                o = a["open_area"]
                rows.append([NAME[k].split("（")[0], d, f(a["interference"]["area_weighted_mean_mm"], 4)] +
                            [f"{100 * o[s]['gt5um']:.1f}%" for s in ("RELEASE", "LOAD", "UNLOAD", "LOAD2")] + [f(o["LOAD2"]["gap_P95"], 1), f(o["LOAD2"]["gap_max"], 0)])
    A(tab(["设计", "名义过盈", "面积加权实现过盈 (mm)", "释放后", "首次加载", "卸载后", "再加载", "再加载时间隙 P95 (µm)", "最大 (µm)"], rows))
    c = M["base:delta0.1"]["cpress_release"]
    A(f"\n**接触压力的加权**（基准设计，释放后）：闭合节点面积加权中位 {f(c['area_weighted_P50_contact_nodes'], 1)} MPa；全界面面积加权平均 {f(c['area_weighted_mean_all'], 1)} MPa；"
      f"闭合节点算术平均 {f(c['arithmetic_mean_contact_nodes'], 0)} MPa，被少数奇异节点支配。报告里用的是第一个。按面积积分的法向接触力约 {c['normal_force_N_A6'] / 1000:.0f} kN。\n")

    A("## 5 载荷与力矩\n")
    rows = []
    for k in NAME:
        x = lo[k]
        rows.append([NAME[k], f"({x['F_N'][0]:.0f}, {x['F_N'][1]:.0f}, {x['F_N'][2]:.0f})", f(x["resultant_N"], 1), x["n_head_nodes"], f(x["offset_norm_mm"]),
                     f(x["parasitic_moment_norm_Nm"]), f(x["moment_norm_Nm"], 1), f(x["torsion_about_stem_axis_Nm"], 1), f(x["bending_about_AP_axis_Nm"], 1),
                     f(x["bending_about_ML_axis_Nm"], 1), f(x["lever_arm_head_to_stem_axis_mm"], 1)])
    A(tab(["设计", "力 (N)，模型坐标", "合力 (N)", "受力节点数", "作用点偏离头心 (mm)", "附带力矩 (N·m)", "对肩部中心的合力矩 (N·m)", "绕柄轴扭矩", "绕前后轴弯矩",
           "绕内外轴弯矩", "头心到柄轴距离 (mm)"], rows))
    A("\n模型坐标 +x 内侧、+y 后方、+z 近端。载荷只以节点力施加在假体头的全部节点上，没有附加力矩。"
      "Bergmann 2016 的 47 N·m 是对常规柄轴（头心下 80 mm 处的柄坐标系）的内力矩，本模型没有把它作为独立载荷施加。\n")

    A("## 6 去骨体积\n")
    A(f"对 {vs['n']} 个设计在 0.4 mm 体素上独立计算“柄体内、截骨面以下、骨外表面以内”的体积，并按髓腔距离场拆成皮质与松质骨。\n")
    A(tab(["项", "值"], [
        ["体素法 / 旧定义（解析柄体积 + 截骨）", f"中位 {f(vs['ratio_voxel_to_old']['median'], 3)}，P5–P95 {f(vs['ratio_voxel_to_old']['P5'], 3)}–{f(vs['ratio_voxel_to_old']['P95'], 3)}，"
         f"范围 {f(vs['ratio_voxel_to_old']['min'], 3)}–{f(vs['ratio_voxel_to_old']['max'], 3)}"],
        ["两种算法对设计排序的秩相关", f(vs["spearman_old_vs_voxel"], 3)],
        ["体素法对解析柄体积的自检（只算柄体本身）", f"中位 {f(vs['voxel_vs_analytic_body_check_median'], 3)}"],
        ["解析柄体积里位于截骨面以上的份额", f"中位 {100 * vs['stem_body_above_cut_share']['median']:.1f}%，最大 {100 * vs['stem_body_above_cut_share']['max']:.0f}%"],
        ["锉掉的骨里皮质所占份额", f"中位 {100 * vs['cortex_share_of_reamed']['median']:.2f}%，最大 {100 * vs['cortex_share_of_reamed']['max']:.1f}%"]]))
    A("\n三种算法对同一设计（mm³）：\n")
    A(tab(["设计", "解析（旧定义）", "体素", "CAD 实体布尔", "体素 / 解析", "CAD / 解析"],
          [[n, a, v, c_, f(v / a, 3), f(c_ / a, 3)] for n, a, v, c_ in CAD]))
    A("\n- 三种算法相差 ±5%。原前沿三个点的骨量损失是 4.38、4.66、4.98 cm³，彼此只差 6–7%，与算法之间的差同量级。")
    A("- CAD 布尔在一个设计上给出“交集比柄体本身还大”的结果（7625 对 7446 mm³），说明它自己有数值问题，暂时不能当基准。")
    A("- 松质骨实体填满了整个髓腔，包括骨干里实际是骨髓的部分。长柄伸进骨干的那段也被算成“去骨”。分区赋值时要一并处理。")
    A("- 截骨体积与锉腔体积被截骨面隔开，没有重复计数。\n")

    A("## 7 模型版本\n")
    note = {"af2719da27": "初始；假体颈从截骨面下 3 mm 起", "3edd9887e5": "退化单元门槛改为 1e-7；假体颈同上", "ea90746e0c": "假体颈改从截骨面起，加网格重试",
            "abc53909a8": "柄长下限改 20 mm", "7c996f0993": "加皮质余量", "65283e029c": "加截骨高度", "08d6683fd6": "加松质骨模量变体", "45a3906c22": "新界面模型"}
    A(tab(["模型", "代码版本", "作业数", "完成时间", "所含阶段", "柄应力中位 (MPa)", "改动"],
          [[{"old": "旧界面", "m1": "新界面"}[v["model"]], v["code_hash"], v["n_jobs"], f"{v['first_done'][5:16]} → {v['last_done'][5:16]}",
            "、".join(f"{k} {n}" for k, n in v["stages"].items()), f(v["vm_median_standard"], 0), note.get(v["code_hash"], "")] for v in ver]))
    A("\n“改动”一栏按提交时间与柄应力的变化推断。前两个版本是假体颈修正前的几何。修正后的五个旧版本只改了设计空间或加了变体通道，按代码差异判断标准设计的模型相同，但没有用同一规格跨版本重解来证实。\n")

    A("## 8 超体积参考点\n")
    A(f"V3 的参考点是 (log10 微动, 骨量损失) = ({f(hv['s0']['ref_log10_f1'], 3)}, {hv['s0']['ref_bone_loss_mm3']:.0f} mm³)，即微动 {f(hv['s0']['ref_f1_um'], 1)} µm。"
      "它取自可行热启动点各目标最大值加 10% 范围。\n")
    A(f"- 旧模型 {hv['all_old_designs']['n']} 个设计里，微动超过参考值的 {hv['all_old_designs']['f1_gt_ref']} 个、超过 40 µm 的 {hv['all_old_designs']['f1_gt_40']} 个，"
      f"其中满足旧约束的都是 {hv['all_old_designs']['f1_gt_ref_and_sed_le30']} 个。")
    A("- 也就是说，“微动更高但更省骨”的区域被挡了两次：先被那条量反了的约束判为不可行，再被参考点排除在超体积之外。")
    A("- 所以“两个种子超体积不动”不能解读为优化停滞。它有三个原因：面积曲线变量被固定、约束量反了、参考点把要研究的区域排除了。\n")

    A("## 9 需要新解才能回答的\n")
    A(tab(["问题", "做法", "作业数"], [
        ["循环是否稳定", "加第三次卸载–加载；三个代表设计 × 过盈 0.10 与 0.025 mm", 6],
        ["网格加密时保持绝对弹性滑移", "1.4 mm 网格，容差改为 0.000357，使上限仍是 0.5 µm；三个代表设计", 3],
        ["短柄阈值工况的噪声底", "短柄过盈 0.05 与 0.025 mm，各 5 个网格（已有各 1 个）", 8],
        ["短柄阈值工况的网格", "短柄过盈 0.05 与 0.025 mm，1.4 mm 网格", 2],
        ["反力、接触合力、骨应变", "导出脚本加反力、接触力与应变；重解四个代表工况", 4],
        ["文献对标", "复现 1–2 个已发表案例", "待定"]]))
    A("\n前五项共 23 个作业，三槽并行约 3–4 小时。这些都不涉及优化，属于修改方案里的验证阶段。\n")

    A("## 10 原始数据包\n")
    A("`v2/results/audit3/packages/` 下五个压缩包，每个约 10 MB：基准过盈 0.10、原读数设计过盈 0.10、短柄过盈 0.05、短柄过盈 0.025、"
      "原读数设计过盈 0.01（可恢复微动 44 µm，最接近 40 µm）。每个包含作业说明与版本、网格与节点对（法向、面积权重、逐节点过盈）、"
      "四个步末的节点位移与接触输出、粘接模型的应力与应变能、结果文件，以及本次复核算出的微动、接触、载荷与体积。**缺反力**：当时没有导出。\n")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("written", OUT, len(L))


if __name__ == "__main__":
    main()
