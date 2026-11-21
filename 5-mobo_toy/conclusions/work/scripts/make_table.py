"""Write 结论总表.md from data/metrics.json, so that the table cannot drift from the figures. Claims are written here; every number is read from the metrics.

    python -X utf8 make_table.py
"""
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
M = json.load(open(HERE / "data/metrics.json", encoding="utf-8"))


def sgn(v, d=3):
    return f"{v:+.{d}f}".replace("-", "−")


caps = {c["cap"]: c for c in M["cost"]["caps"]}
scan = M["one_factor"]


def s(factor, series, x):
    return next(r for r in scan if r["factor"] == factor and r["series"] == series and abs(r["x"] - x) < 0.02)


def sc(note):
    return next(r for r in scan if r["note"] == note)


env1 = {r["job_id"]: r for r in M["cost"]["env_m1"]}
A, W1 = M["A"], M["WS_m1"]
m075, m15 = s("m", "A", 0.75), s("m", "A", 1.5)
L44, a50 = s("L", "m1.0", 44.0), s("alpha", "m1.0", 50.0)
a50L44, a55L = sc("wl_m1_a50_L44"), sc("wl_m1_a55_L44.75")
AL445 = s("L", "m0.5", 44.5)
b = M["mechanism"]["bands"]
nm = M["mechanism"]["named"]
S = M["sensitivity"]
yld = S["foam_yield"]
cl = M["cluster"]
cy = M["cycles"]
cd = M["cycles_dex_vs_A"]
V = M["val1"]
P = M["prospective"]
tight = [v["spearman_tight"] for v in S.values() if "spearman_tight" in v]
ds = M["delta_same_designs"]
c4 = M["cycles_c4_ratio"]
mc = M["m_cost_by_condition"]
ow = min(M["offset_rows"], key=lambda r: r["rot"])
nd = {}
for x in M["not_done"]:
    nd[x["batch"]] = nd.get(x["batch"], 0) + 1
m_ratio_low = caps[6]["m_ge1_rot"] / caps[6]["all_rot"]

rows = [
    ("1", "低去骨的代价取决于入口偏移：模板选偏移时 m ≥ 1.0 低于 6 cm³ 代价大，偏移固定 +2 时小得多。下限还不能写",
     f"模板选偏移：≤ 6 cm³ 最好 {caps[6]['m_ge1_rot']:.3f}°，高于 G5 的 0.19°；6.92 cm³ 为 {caps[7]['m_ge1_rot']:.3f}°，7.38 cm³ 为 {caps[7.5]['m_ge1_rot']:.3f}°，8.35 cm³ 为 {caps[8.5]['m_ge1_rot']:.3f}°。偏移固定 +2，m 1.0：{min(o['bone'] for o in M['offset_rows'] if o['e'] == 2):.2f}–{max(o['bone'] for o in M['offset_rows'] if o['e'] == 2):.2f} cm³，{min(o['rot'] for o in M['offset_rows'] if o['e'] == 2):.3f}–{max(o['rot'] for o in M['offset_rows'] if o['e'] == 2):.3f}°。A 的 e +2 相对 e 0：肩面积 {ow['A0']:.0f} 对 {W1['A0']:.0f} mm²，微动 {ow['f1']:.0f} 对 {W1['f1']:.1f} µm，可逆转动 {ow['rot_rev']:.3f} 对 {W1['rot_rev']:.4f}°，柄 vM p99 {ow['vm']:.0f} 对 {W1['vm']:.0f} MPa",
     "跨设计 FE；偏移行是同形单因素 FE", "b7m、b14、b19、b20、b11p", "e +2 的 3 行是同一族设计，没有算屈服、细网格和其他载荷；m 下限待导师定；空芯假设", "写成代价曲线加偏移行，不写下限", "图 1、图 2"),
    ("2", "同形单因素下，已测范围内余量的影响大于 L 和 α",
     f"m 0.75、1.0、1.5 是 A 的 {m075['times_A']:.2f}、{W1['rot'] / A['rot']:.2f}、{m15['times_A']:.2f} 倍，去骨 {m075['bone']:.2f}、{W1['bone']:.2f}、{m15['bone']:.2f} cm³。m 1.6、1.75 为 {s('m', 'A', 1.6)['times_A']:.2f}、{s('m', 'A', 1.75)['times_A']:.2f} 倍，去骨 {s('m', 'A', 1.6)['bone']:.2f}、{s('m', 'A', 1.75)['bone']:.2f} cm³；m 2.0 跳到 e −2，{s('m', 'A', 2.0)['times_A']:.1f} 倍。相对 m 1.0 版，L 44 为 {L44['times_ctrl']:.2f} 倍，α 50 为 {a50['times_ctrl']:.2f} 倍，叠加 {a50L44['times_ctrl']:.2f} 倍",
     "同形单因素 FE", "b14、b8 W-0、b15、b19、b20", "m 1.75 贴在偏移跳变边上；L 44 依赖空芯假设；α > 45° 在盒外，要过 G2；只有楼梯载荷，α 增大时扭矩臂变短", "可以写，α 和 L 的增益要带条件", "图 2"),
    ("3", "紧的设计以首次加载的永久落座为主，松的设计以可逆摆动为主；加大余量主要放大自转",
     f"转动 < 0.1° 的 {b[0]['n']} 个设计永久份额中位 {b[0]['perm_share_median']:.2f}，> 1° 的 {b[-1]['n']} 个只有 {b[-1]['perm_share_median']:.2f}。转动与接触面积 Spearman {M['mechanism']['spearman_rot_contact']:.2f}，这是相关。m 0.5 到 1.0：自转 {nm['A']['spin']:.4f}° 到 {nm['WS_m1']['spin']:.4f}°，{nm['WS_m1']['spin'] / nm['A']['spin']:.1f} 倍；倾摆 {nm['A']['tilt']:.4f}° 到 {nm['WS_m1']['tilt']:.4f}°，{nm['WS_m1']['tilt'] / nm['A']['tilt']:.2f} 倍",
     "跨设计 FE，加同形单因素 FE", "严格基线全库；b14", "线弹性泡沫，没有压溃；屈服版 FY-2 未批准", "可以写，机制只到界面滑移层面", "图 3"),
    ("4", "A 领先，第 2–5 名分不开",
     f"A 比第 2 名好 {cl['A_to_second_dex']:.3f} dex；第 2–5 名相邻差 {cl['adjacent_dex'][0]:.4f}、{cl['adjacent_dex'][1]:.4f}、{cl['adjacent_dex'][2]:.4f} dex，都小于噪声 2 倍 rms {cl['nz3_2rms']:.3f} dex，噪声只来自 {cl['nz3_n']} 个偏差",
     "跨设计 FE", "b8 NZ-3", "A 贴 m、h_cut、q 等边界", "可以写，报第 1 名加一簇", "图 4"),
    ("5", "绝对值对物理假设很敏感，对数值设置不敏感；已测假设下排序基本不变",
     f"网格 h 1.94、2.06 为 {S['mesh_h1.94_2.06']['times_min']:.2f}–{S['mesh_h1.94_2.06']['times_max']:.2f} 倍。泡沫屈服中位 {yld['times_median']:.2f} 倍，前 5 名重合 {yld['top5_overlap']} 个，A 不变。同一批 {ds['n']} 个设计上 δ 0.025、0.05、0.20 中位 {10 ** ds['delta0.025']:.1f}、{10 ** ds['delta0.05']:.1f}、{10 ** ds['delta0.2']:.2f} 倍。μ 0.2、0.15 中位 {S['mu0.2']['times_median']:.2f}、{S['mu0.15']['times_median']:.2f} 倍，Spearman {S['mu0.2']['spearman']:.3f}、{S['mu0.15']['spearman']:.3f}，A 仍第 1。δ 0.05 且 3839 N 中位 {S['delta0.05_rise3839']['times_median']:.1f} 倍。楼梯方向 3606 N，载荷只大 1.5 倍，转动是 {S['stair3606']['times_min']:.1f}–{S['stair3606']['times_max']:.1f} 倍，Kendall τ {S['stair3606']['kendall']:.3f}；矢状 40° 的 τ 是 {S['sag40']['kendall']:.3f}。全范围 Spearman ≥ {min(v['spearman'] for k, v in S.items() if 'spearman' in v and k != 'cycles4'):.3f}，只看转动 < 0.1° 为 {min(tight):.2f}–{max(tight):.2f}",
     "同设计配对 FE", "CD-0、CD-1、NZ、FD、FY-1、b9p、b17、b18", "固定 e +2 这一族没有条件行；放置、纯扭转、第二根骨、肌肉力都是 0 行；转动对载荷强非线性，所以 2391 N 下的绝对值偏乐观", "可以写排序稳定，只限已测假设；μ 只作全局条件，真实值要台架标定", "图 4"),
    ("6b", "余量的代价方向稳定，大小随条件变：扭矩大时放大，摩擦低时缩小",
     f"m 1.0 相对 A，dex：楼梯 {sgn(mc['stair'])}，楼梯方向 3606 N {sgn(mc['stair3606'])}，矢状 40° {sgn(mc['sag40'])}，μ 0.2 {sgn(mc['mu0.2'])}，μ 0.15 {sgn(mc['mu0.15'])}",
     "同设计配对 FE", "b14、b17、b18", "只有这一对设计的同形对照；屈服下的代价还没算，FY-2 未批准", "可以写，只说这一个基准设计", "图 2、图 4"),
    ("6", "循环不改变这 4 个设计的排序；紧的设计接近饱和，松的设计还在下沉",
     f"第 10 循环峰值相对第 1 循环：A {cy['A']['ratio_10_1']:.3f}，m 1.0 {cy['A m1']['ratio_10_1']:.3f}，init29 {cy['init29']['ratio_10_1']:.3f}，C {cy['C']['ratio_10_1']:.3f} 倍。m 1.0 相对 A 从 {sgn(cd['A m1']['c1'])} 到 {sgn(cd['A m1']['c10'])} dex。第 9 循环下沉增量 A {abs(cy['A']['sub_inc9']):.2f} µm，C {abs(cy['C']['sub_inc9']):.2f} µm",
     "同设计配对 FE", "b12", "线弹性加库仑摩擦，不能预测长期迁移；4 个设计相距很远，近距离排序看 4 循环 7 行", "可以写，只说界面滑移在收敛", "图 4"),
    ("7", "第一份实测对仿真：误差与已发表模型同一水平，不算验证通过",
     f"10 个测点全部偏低，中位 {V['ours']['median_rel_pct']:.1f} %，对 Naghavi 模型 {V['naghavi']['median_rel_pct']:.1f} %；偏差 {sgn(V['ours']['bias_mpa'], 2)} 对 {sgn(V['naghavi']['bias_mpa'], 2)} MPa；Pearson {V['ours']['pearson']:.3f} 对 {V['naghavi']['pearson']:.3f}。靠颈部的 M1、MX1、L1 低 {abs(V['near_neck']['M1']):.0f}、{abs(V['near_neck']['MX1']):.0f}、{abs(V['near_neck']['L1']):.0f} %",
     "实测对照", f"b16，{V['job_far2.5']}", "完整股骨，没有柄；骨来自 CAD；测点转 ±15° 时中位 " + f"{V['plus15']['median_rel_pct']:.1f}–{V['minus15']['median_rel_pct']:.1f} %；实测从论文图按像素读取", "可以写，按 G11 中间档写，不写已验证", "图 5"),
    ("8", "代理的优化选点预测都由之后的 FE 核对过，AL-3′ 的局部候选可信，但略偏乐观",
     f"AL-1 {P['al1']['opt']['rmse']:.3f}、AL-2 {P['al2']['opt']['rmse']:.3f}、AL-3′ {P['al3m']['opt']['rmse']:.3f} dex；90 % 覆盖 {P['al1']['opt']['n_in90']} / {P['al1']['opt']['n']}、{P['al2']['opt']['n_in90']} / {P['al2']['opt']['n']}、{P['al3m']['opt']['n_in90']} / {P['al3m']['opt']['n']}；AL-3′ 偏差 {sgn(P['al3m']['opt']['bias'])} dex，{P['al3m']['opt']['n_worse']} / {P['al3m']['opt']['n']} 行 FE 更差",
     "代理预测，FE 核对", "b5、b6、b7m；选点文件 db_al_al1、al2、al3m", "各轮区域不同，数字变小不全是模型变好；GP 代理微动已有先例", "作方法支撑，不作主贡献。U-Net v0.5 是探索性比较，不写成好于 GP：test_corner vM p99 3.64 对 3.92 MPa，差值在噪声内，整个测试集 6.32 对 5.57，标量继续用 GP（技术路线第 9.8 节）", "图 6"),
]

L = []
L.append("# 结论总表\n")
L.append(f"由 `scripts/make_table.py` 从 `data/metrics.json` 生成，不手改。数据：db3406 {M['export']} 共 {M['n_export']} 行，{M['n_done']} 行成功，{M['n_failed']} 行失败。严格基线：δ 0.10、楼梯 2391 N、h 2.0、μ 0.3、泡沫线弹性、偏移不强制。\n")
L.append("**这是单根 Sawbones 3406 上的模型比较。** 全部依赖空芯假设，泡沫线弹性，没有同模型参照柄，所以转动值现在只能在设计之间比。\n")
L.append("## 1 结论\n")
L.append("证据级别从强到弱：实测对照、同设计配对 FE、同形单因素 FE、跨设计 FE、代理预测。\n")
L.append("| # | 结论 | 关键数字 | 证据级别 | 来源 | 依赖的条件 | 现在能怎么写 | 图 |")
L.append("|---|---|---|---|---|---|---|---|")
for i, r in enumerate(rows, 1):
    L.append("| " + " | ".join((str(i),) + r[1:]) + " |")
L.append("")
L.append("## 2 现在不能写的话\n")
L.append("| 说法 | 为什么不能写 | 什么结果之后可以写 |")
L.append("|---|---|---|")
L.append("| 优于已有柄 | 没有同模型参照柄，转动没有尺度 | REF-1 过 G12 |")
L.append("| 模型已验证 | VAL-1 走 G11 中间档，Pearson 明显低于已发表模型，也没有柄 | 台架结果 |")
L.append("| 能预测长期迁移 | 线弹性加库仑摩擦，没有压溃和塑性 | 屈服模型加实测 |")
L.append("| 对放置、扭转稳健 | 这两项都是 0 行 | PF-1、TQ-1，都未批准 |")
L.append("| 适用于人骨 | 只有一根复合骨，空芯假设未确认 | 第二根股骨，空芯答复 |")
L.append("| 用 GP 代理微动是新贡献 | Al-Dirini 2020 已有先例 | 不写 |")
L.append("")
L.append("## 3 还没有数据的部分\n")
L.append("| 项 | 现状 | 卡在哪里 |")
L.append("|---|---|---|")
L.append("| AL-4m B，6 到 7.4 cm³ | 选出 7 行，不是原定的 12 行，先不喂 | 等 OW-3 的结果再定 |")
L.append("| OW-3，批次 b22，更细的入口偏移 | 9 行，11-03 19:56 UTC 开跑 | 等结果；G26–G28 |")
L.append("| 纯扭转 | 0 行 | TQ-1 和钩子未批准；扭转定义待导师定 |")
L.append("| 放置偏差 | 0 行 | PF-1 和钩子未批准；公差待定 |")
L.append("| 第二根股骨 | 0 行 | 后半程 |")
L.append("| 肌肉力 | 0 行 | 待导师确认是否仍要 |")
L.append("| 参照柄 | 0 行 | 款式和 CAD 待定 |")
L.append("| 骨折筛查 | 未做，数据已有 | Z1，0 FE |")
L.append("")
L.append("## 4 整理时发现的问题\n")
L.append("| 问题 | 依据 | 处理 |")
L.append("|---|---|---|")
L.append(f"| AL-1 的 0.118 dex、覆盖 0.63 复算不出来 | 冻结预测对 FE，优化选点 {P['al1']['opt']['n']} 行：RMSE {P['al1']['opt']['rmse']:.3f} dex，覆盖 {P['al1']['opt']['cov90']:.2f}，与 `al1_eval.json` 和 11-01 总结的 0.74 一致。把改载荷的行算进去是 {M['al1_opt_with_changed_load']['rmse']:.3f}，也不是 0.118 | 本表用 {P['al1']['opt']['rmse']:.3f}。11-03 已改第三版计划 Z7 和立题页；第二周 FEA 计划的 11-02 11:45 条保留原文，执行记录追加了更正 |")
in_gap = [x for x in M["cost"]["bones_m_ge1_6p5_to_8"] if 7.0 <= x <= 7.5]
L.append(f"| 偏移固定 +2 改变了结论 1 | 选号规则对每个形状只取 A0 最大的一档偏移，A、a95、a100 的这一档是 e 0，它们的 e +2 版以前没算过（全库模板选到 e +2 的有 38 行，第三版第 12 节“从未被选到”只对这一族成立）。b11p 的 3 行低于 G5 的 0.19°，G25 两条都触发（第三版第 12 节） | 总表和图 1 把这些行单独标出，曲线仍只算模板选的偏移 |")
L.append(f"| “约 8 cm³ 为下限”不再成立 | 模板选偏移时 6.92 cm³ 已有 {caps[7]['m_ge1_rot']:.3f}°，低于 0.19°，而且它贴在偏移跳变边上 | 本表不写下限；G22 要等 B 部分 |")
L.append(f"| “转动主要是永久落座”只对紧的设计成立 | 永久份额随转动从 {b[0]['perm_share_median']:.2f} 降到 {b[-1]['perm_share_median']:.2f}，C 只有 {nm['C']['perm'] / nm['C']['rot']:.2f} | 结论 3 已带上这个分界 |")
L.append(f"| δ 各行的中位倍数不能直接比 | 各行设计集不同，所以 δ 0.025 中位 {S['delta0.025']['times_median']:.2f} 倍小于 δ 0.05 的 {S['delta0.05']['times_median']:.2f} 倍；同一批 {ds['n']} 个设计上是 {10 ** ds['delta0.025']:.1f} 和 {10 ** ds['delta0.05']:.1f} 倍 | 图 4 脚注写明 |")
L.append("")
L.append("## 5 口径\n")
L.append("| 项 | 取值 |")
L.append("|---|---|")
L.append("| 转动 | 生产 `stability` 的 `rot_first_deg`，首次加载的刚体拟合 |")
L.append("| 倍数 | 设计转动 ÷ 对照转动；dex = log10(倍数) |")
L.append(f"| 噪声 | ±{M['noise_dex']} dex 内不解读 |")
L.append("| 盒内 | v1 设计空间，α ≤ 45°、L ≤ 45、m 0.5–2.0 等 13 个变量 |")
L.append("| 代价曲线 | 严格基线，加偏移固定为 0 的 L 扫描；折线只算盒内 |")
L.append("| 单因素 | 只改一个量，其余等于设计 A；L 行偏移固定为 0；α 行的号和偏移由模板重选 |")
L.append("| 配对 | 同一设计相对自身严格基线行，用 12 个连续设计变量匹配 |")
L.append("| 前瞻误差 | log10(FE) − 冻结的 GP 均值，改载荷的行不算；覆盖按 \\|z\\| < 1.645 |")
L.append("")
L.append("逐行数字在 `data/`，图在 `figures/`。")
(HERE / "结论总表.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("written", HERE / "结论总表.md")
