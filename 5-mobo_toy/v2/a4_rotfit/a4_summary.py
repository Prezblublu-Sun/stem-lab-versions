"""A4 一页摘要（中文）：所有数字从 plan/a4/a4_stats.json 取，不手抄。输出 plan/a4/a4_summary.md。"""
from __future__ import annotations

import json
import pathlib

A4 = pathlib.Path(r"H:/projects/application/research-log/neck_implant_2026-10-02/ml_efficiency_2026-10-22/plan/a4")
S = json.loads((A4 / "a4_stats.json").read_text(encoding="utf-8"))
D, B, R, C = S["domains_first"], S["bench"], S["robustness_across_domains"], S["spin_circ_vs_all_axial"]
F, K = S["front_ranking"], S["rank_in_129"]
meta = json.loads((A4 / "rotfit_rows_meta.json").read_text(encoding="utf-8"))
n = S["n_phase10_set"]


def f(x, d=4):
    return f"{x:.{d}f}"


def pc(x):
    return f"{100 * x:.0f} %"


def cnt(x):
    return f"{round(x * n)}/{n}"


def order(name):
    return " < ".join(F[name]["order"])


dom_cn = {"all": "全柄身（生产口径）", "prox": "近端半段", "dist": "远端半段", "unw": "全柄身不加权"}
rows = []
for d in ("all", "prox", "dist", "unw"):
    x = D[d]
    rows.append(f"| {dom_cn[d]} | {f(x['axial_med_deg'])} | {f(x['tilt_med_deg'])} | {f(x['axial_over_tilt_med'], 2)} | {cnt(x['frac_axial_gt_tilt'])} | "
                f"{f(x['axial_ratio_to_all']['med'], 2)}（{f(x['axial_ratio_to_all']['p10'], 2)}–{f(x['axial_ratio_to_all']['p90'], 2)}） | "
                f"{f(x['tilt_ratio_to_all']['med'], 2)}（{f(x['tilt_ratio_to_all']['p10'], 2)}–{f(x['tilt_ratio_to_all']['p90'], 2)}） | "
                f"{f(x['spearman_rot_vs_all'], 3)} / {f(x['spearman_axial_vs_all'], 3)} / {f(x['spearman_tilt_vs_all'], 3)} | {x['top10_overlap_with_all']}/10 | "
                f"{order(d)} | {K[d]['a69']} |")
bf, bp, cf, cp = B["bench"]["first"], B["bench"]["perm"], B["bench_cx"]["first"], B["bench_cx"]["perm"]
brows = [
    f"| 首次加载，骨环 = 界面节点 B5 | {f(bf['rot_med_deg'])} | {f(bf['ratio_rot_to_all_med'], 1)}（{f(bf['ratio_rot_to_all_p10'], 1)}–{f(bf['ratio_rot_to_all_p90'], 1)}） | {f(bf['spearman_rot_vs_all'], 2)} / {f(bf['spearman_axial_vs_all'], 2)} / {f(bf['spearman_tilt_vs_all'], 2)} | {cnt(1 - bf['frac_axial_gt_tilt'])} | {order('bench_first')} | {K['bench_first']['a69']} |",
    f"| 首次加载，骨环 = 皮质 CX5 | {f(cf['rot_med_deg'])} | {f(cf['ratio_rot_to_all_med'], 1)}（{f(cf['ratio_rot_to_all_p10'], 1)}–{f(cf['ratio_rot_to_all_p90'], 1)}） | {f(cf['spearman_rot_vs_all'], 2)} / {f(cf['spearman_axial_vs_all'], 2)} / {f(cf['spearman_tilt_vs_all'], 2)} | {cnt(1 - cf['frac_axial_gt_tilt'])} | {order('bench_cx_first')} | {K['bench_cx_first']['a69']} |",
    f"| 卸载后残留，骨环 = B5 | {f(bp['rot_med_deg'])} | {f(bp['ratio_rot_to_all_med'], 1)}（{f(bp['ratio_rot_to_all_p10'], 1)}–{f(bp['ratio_rot_to_all_p90'], 1)}）* | {f(bp['spearman_rot_vs_all'], 2)} / {f(bp['spearman_axial_vs_all'], 2)} / {f(bp['spearman_tilt_vs_all'], 2)}* | {cnt(1 - bp['frac_axial_gt_tilt'])} | {order('bench_perm')} | {K['bench_perm']['a69']} |",
    f"| **卸载后残留，骨环 = CX5** | {f(cp['rot_med_deg'])} | **{f(cp['ratio_rot_to_all_med'], 2)}（{f(cp['ratio_rot_to_all_p10'], 2)}–{f(cp['ratio_rot_to_all_p90'], 2)}）*** | **{f(cp['spearman_rot_vs_all'], 3)} / {f(cp['spearman_axial_vs_all'], 3)} / {f(cp['spearman_tilt_vs_all'], 3)}*** | {cnt(1 - cp['frac_axial_gt_tilt'])} | {order('bench_cx_perm')} | {K['bench_cx_perm']['a69']} |",
]
abs_rot, abs_rms, dec = B["absolute_rotation_first_deg_med"], B["absolute_rms_first_um_med"], B["decomp_first_med"]
c10 = S["critic10_check"]
txt = f"""# A4 转动拟合口径与虚拟台架——一页摘要（2026-10-23）

**做了什么。** 对阶段 10 集合的 {n} 个无领设计（`metrics_all.csv` 筛选：neck_in_shoulder、m ≥ 0.5、当前代码、无变体）加有领对照 J1，共 {S['n_rows']} 个作业，在 Linux 上只读 `queue/<job>/{{mesh3d.npz, m_fric_csv/*_U.csv}}` 重做首次加载（LOAD − RELEASE）的刚体拟合（`stability.rigid_fit`，未改 `stability.py`），比较四种拟合域，另加周向自转估计与"虚拟台架"读数。计算：{meta['procs']} 进程、CPU 4–11、nice 19，墙钟 {meta['wall_s']:.0f} s，0 错误；代码哈希 `{meta['jobs_code_hash']}`。脚本与逐作业表在 `plan/a4/`（`a4_table.csv`、`a4_table.json`、`a4_stats.json`）。

**核对。** "全柄身"域对 {S['n_rows']} 个作业全部逐位复现 `metrics_all.csv` 的 11 个存值（rot/axial/tilt/rms/下沉/侧移，三段），最大绝对差 {max(S['repro_max_abs_diff_all_130'].values()):.1e}。

## 1. 四种拟合域下的自转 / 摆动（首次加载，{n} 个设计，中位数）

| 拟合域 | 自转 (°) | 摆动 (°) | 自转/摆动 | 自转 > 摆动 | 自转相对全柄（中位，p10–p90） | 摆动相对全柄 | Spearman 对全柄：总/自转/摆动 | 前 10 重合 | 前沿排序 | a69 在 {n} 中名次 |
|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

- **"自转稳健、摆动看域"在全部 {n} 个设计上成立。** 逐设计看四个域的离散：自转的最大/最小比中位 {f(R['axial_maxmin_ratio_med'], 2)}（p90 {f(R['axial_maxmin_ratio_p90'], 2)}），摆动 {f(R['tilt_maxmin_ratio_med'], 2)}（p90 {f(R['tilt_maxmin_ratio_p90'], 1)}）；{cnt(R['frac_tilt_more_variable_than_axial'])} 个设计摆动比自转更随域变化。自转的**排序**几乎不变（Spearman 近端 {f(D['prox']['spearman_axial_vs_all'], 3)}、不加权 {f(D['unw']['spearman_axial_vs_all'], 3)}、远端 {f(D['dist']['spearman_axial_vs_all'], 2)}），但**大小**有系统偏移：近端 ×{f(D['prox']['axial_ratio_to_all']['med'], 2)}，远端 ×{f(D['dist']['axial_ratio_to_all']['med'], 2)}——柄相对骨的扭转沿柄长递减，不是均匀的刚体自转。
- **只拟合近端时，摆动是全柄的 {f(D['prox']['tilt_ratio_to_all']['med'], 1)} 倍（{f(D['prox']['tilt_ratio_to_all']['p10'], 1)}–{f(D['prox']['tilt_ratio_to_all']['p90'], 1)}），{cnt(R['frac_prox_tilt_dominant'])} 个设计变成摆动为主**（全柄口径下 {cnt(R['frac_all_tilt_dominant'])}）；主次翻转的设计占 {pc(R['frac_dominance_flips_prox_vs_all'])}。远端半段的摆动散得最开（{f(D['dist']['tilt_ratio_to_all']['p10'], 2)}–{f(D['dist']['tilt_ratio_to_all']['p90'], 2)} 倍），与全柄的 Spearman 只有 {f(D['dist']['spearman_tilt_vs_all'], 2)}。不加权与加权几乎一样（总转动 Spearman {f(D['unw']['spearman_rot_vs_all'], 3)}）。
- **前沿 a69 / a24 / a36 / a19。** 全柄、近端、不加权三种口径下顺序都是 {order('all')}；远端把 a36、a19 对调。近端口径把四个压到一起（a69 {f(F['prox']['a69']['value'])}°，a24 {f(F['prox']['a24']['value'])}°），a69 在 {n} 个中从第 {K['all']['a69']} 名退到第 {K['prox']['a69']} 名（审查在其 10 个设计里看到的"第 1 → 第 {c10['prox']['a69_rank']}"在本数据上复现：{' < '.join(c10['prox']['order'])}）。
- 周向自转估计（Σw·u_θ·r / Σw·r²）与拟合自转：相对差中位 {pc(C['rel_diff_med'])}，p90 {pc(C['rel_diff_p90'])}，{cnt(C['frac_within_15pct'])} 在 15 % 内，Spearman {f(C['spearman'], 3)}，符号一致 {pc(C['sign_agree_frac'])}。有效半径处的弧长中位 {f(C['arc_med_um_med'], 1)} µm，{cnt(C['frac_arc_lt_rms'])} 个设计小于拟合残差 RMS（全柄 RMS 中位 {f(D['all']['rms_med_um'], 1)} µm）。
- 摆动的方向：全柄口径下 {pc(1 - D['all']['tilt_dir']['frac_ml_dominant'])} 的设计以绕前后轴（冠状面内，内外翻向）为主，且 {n} 个设计符号全部相同；近端口径加进来的那部分主要是绕内外侧轴（屈伸向）的分量（|ω·e_ml| 中位 {f(D['prox']['tilt_dir']['abs_ml_med'], 3)}° 对全柄的 {f(D['all']['tilt_dir']['abs_ml_med'], 3)}°）。

## 2. 虚拟台架读数

**定义**（`a4_rotfit_linux.py` 文档串，h = (x − C03)·u3，u3 为颈轴 = 截骨面法向）：柄颈标记 S10 = 柄的全部节点中 0 < h ≤ 10 mm（中位 {B['marker_counts_med']['n_S10']:.0f} 个节点）；骨环 B5 = 界面骨侧节点中 −5 ≤ h < 0 且非领面（{B['marker_counts_med']['n_B5']:.0f} 个）；备选骨环 CX5 = 皮质单元全部节点中 −5 ≤ h < 0（{B['marker_counts_med']['n_CX5']:.0f} 个）。每个标记集单独对**绝对位移增量**做不加权刚体拟合，读数 = ω_S10 − ω_骨环，按柄轴分解；柄肩平动 = 两个刚体在 P0 处的速度差。

| 读数 | 中位 (°) | 相对界面拟合（中位，p10–p90） | Spearman 对同段界面拟合：总/自转/摆动 | 摆动为主 | 前沿排序 | a69 名次 |
|---|---|---|---|---|---|---|
{chr(10).join(brows)}

\\* 残留段两行与界面拟合的**残留段**（`rot_perm_deg`，中位 {f(S['all_perm']['rot_med_deg'])}°）相比；这两行的总转动对首次加载界面拟合（优化指标 `rot_first_deg`）的 Spearman 分别为 {f(bp['spearman_rot_vs_all_first'], 2)}（B5）和 {f(cp['spearman_rot_vs_all_first'], 2)}（CX5）。

- **首次加载的台架读数不是界面相对转动。** 四个标记集的绝对转动中位都在 {f(abs_rot['CX5'], 2)}–{f(abs_rot['S10'], 2)}°（整根股骨在 1714 N 下的弯曲，远端固定），两者之差 {f(dec['bench_rot'], 3)}° 由三部分组成：假体颈相对整柄的弯曲 {f(dec['neck_bend'], 3)}°、整柄相对骨环 {f(dec['stemall_vs_B5'], 3)}°（含柄长范围内骨的弯曲），而界面拟合给出的柄–骨相对转动只有 {f(dec['interface_fit_all'], 3)}°。逐设计算，台架首次读数中 {pc(dec['bench_minus_interface_over_bench_med'])}（中位）不是界面相对运动；{cnt(1 - bf['frac_axial_gt_tilt'])} 个设计读成摆动为主；前沿四个几乎分不开（{f(F['bench_first']['a19']['value'])}–{f(F['bench_first']['a69']['value'])}°），顺序反转为 {order('bench_first')}。骨环放在皮质上（CX5）更大（×{f(cf['ratio_rot_to_all_med'], 1)}），因为皮质环到柄之间还有 5 mm 松质在变形。
- **卸载后的残留转动才是可比的量，骨环要放在皮质上。** S10 相对 CX5 的残留转动 = 界面拟合残留转动的 {f(cp['ratio_rot_to_all_med'], 2)} 倍（p10–p90 {f(cp['ratio_rot_to_all_p10'], 2)}–{f(cp['ratio_rot_to_all_p90'], 2)}，{cnt(B['bench_cx_perm_ratio_frac_within_25pct'])} 在 ±25 % 内），Spearman {f(cp['spearman_rot_vs_all'], 3)}（自转 {f(cp['spearman_axial_vs_all'], 3)}，摆动 {f(cp['spearman_tilt_vs_all'], 2)}），与首次加载的优化指标 Spearman {f(cp['spearman_rot_vs_all_first'], 2)}，前 10 重合 {B['top10_overlap_with_all_first']['bench_cx_rot_perm_deg']}/10，a69 第 {K['bench_cx_perm']['a69']} 名。分项上摆动被放大 ×{f(cp['ratio_tilt_to_all_med'], 2)}、自转 ×{f(cp['ratio_axial_to_all_med'], 2)}，所以残留段台架读数里自转 / 摆动的主次约各半（{cnt(1 - cp['frac_axial_gt_tilt'])} 摆动为主），而界面拟合的残留段是 {cnt(1 - S['all_perm']['frac_axial_gt_tilt'])}——总量可比，分项的主次不要拿台架残留读数去定。用界面节点做骨环（B5）不行：它在接触区里，卸载后仍带着压配残余变形（B5 自身残留绝对转动 {f(B['absolute_rotation_perm_deg_med']['B5'], 3)}°，CX5 只有 {f(B['absolute_rotation_perm_deg_med']['CX5'], 4)}°），读数被放大 ×{f(bp['ratio_rot_to_all_med'], 1)}。
- 柄肩轴向位移同样：首次加载台架读数中位 {f(S['subsid_med_um']['bench_first'], 1)} µm（CX5 环 {f(S['subsid_med_um']['bench_cx_first'], 1)} µm，含骨的弹性压缩），界面拟合 {f(S['subsid_med_um']['all_first'], 1)} µm；残留段 CX5 环 {f(S['subsid_med_um']['bench_cx_perm'], 1)} µm 对界面 {f(S['subsid_med_um']['all_perm'], 1)} µm，Spearman {f(cp['spearman_subsid_vs_all'], 3)}。
- J1（有领）：界面拟合 {f(S['reference_designs']['J1']['all_rot_first_deg'])}°，台架首次 {f(S['reference_designs']['J1']['bench_rot_first_deg'])}°，同样被弹性变形放大；e2a（固定差）界面 {f(S['reference_designs']['e2a']['all_rot_first_deg'], 3)}°，台架 {f(S['reference_designs']['e2a']['bench_rot_first_deg'], 3)}°，两者都认得出它差。

## 3. 建议

1. **优化指标：保留现在的全柄身、面积加权、首次加载的总转动（自转 + 摆动）**，即 `stability.py` 的 `rot_first_deg`。理由：它逐位可复现；对加权与否不敏感（Spearman {f(D['unw']['spearman_rot_vs_all'], 3)}）；剔除了整根股骨的弯曲（台架读数里约 {pc(dec['bench_minus_interface_over_bench_med'])} 是弹性变形）；自转和摆动都算进去（e2a 只看自转排第 {K['all_axial']['e2a']} 名，看总转动排第 {K['all']['e2a']} 名）。不要换成近端半段：它按构造把 {pc(R['frac_prox_tilt_dominant'])} 的设计做成摆动为主、把前沿压成一团，而且 a69 从第 1 掉到第 {K['prox']['a69']}。
2. **自转 / 摆动的分项只作诊断，引用时必须带拟合域**："全柄口径下自转/摆动中位 {f(D['all']['axial_over_tilt_med'], 2)}、{cnt(D['all']['frac_axial_gt_tilt'])} 自转为主"与"近端口径下 {cnt(R['frac_prox_tilt_dominant'])} 摆动为主"都对，差别在域。更正说明第 1 条按此定稿：数字用全柄口径，加一句近端口径的结果与原因（近端是加载时间隙张开、柄在孔口里杠杆的那一段，摆动分量集中在那里；自转沿柄长递减 ×{f(D['prox']['axial_ratio_to_all']['med'], 2)} → ×{f(D['dist']['axial_ratio_to_all']['med'], 2)}）。
3. **与台架对比的量：卸载后、柄颈标记相对截骨面皮质环的残留转动（`bench_cx_rot_perm_deg`）与残留轴向位移（`bench_cx_subsid_perm_um`）**。它们与界面拟合的残留段同量级（×{f(cp['ratio_rot_to_all_med'], 2)}），排序一致（{f(cp['spearman_rot_vs_all'], 3)}）。台架若只能报"加载中"的可诱发位移，就拿 FE 的 `bench_cx_rot_first_deg` 去比（同一标记定义），不要拿 `rot_first_deg` 去比——后者小 {f(cf['ratio_rot_to_all_med'], 1)} 倍，不是同一个量。台架实现上：骨标记贴在截骨面以下 5 mm 内的皮质上，柄标记贴在截骨面以上 10 mm 内的假体颈上，远端固定方式与 FE 一致，每个循环记录卸载态。
4. 自转单独要对比时，台架首次加载的自转分量尚可（×{f(bf['ratio_axial_to_all_med'], 1)}，Spearman {f(bf['spearman_axial_vs_all'], 2)}），摆动分量不行（×{f(bf['ratio_tilt_to_all_med'], 1)}）。

## 4. 不改 stability.py 时建议的补丁（文字，待批准后再做）

- 在 `stability.stability()` 返回值里**不改任何现有键**，新增三类键：(a) `rot_tilt_ap_first_deg` / `rot_tilt_ml_first_deg`（有符号，绕 e_ap、e_ml 的分量，现在只有模长）；(b) `rot_first_prox_deg` 与 `rot_tilt_first_prox_deg`（近端半段，s ≤ 中位数，供诊断，键名带域）；(c) 新函数 `bench(d, h_stem=10.0, h_bone=5.0)` 返回 `bench_cx_rot_{{first,rev,perm}}_deg`、`bench_cx_rot_axial_*`、`bench_cx_rot_tilt_*`、`bench_cx_subsid_*_um`，实现即 `a4_rotfit_linux.py` 的 S10 / CX5 段（约 40 行；需要 `mesh3d.npz` 的 `stem_conn`、`cortex_conn`，生产作业都有）。
- 文档串里写明口径："转动 = 柄身界面节点对相对位移的面积加权刚体拟合，全柄身；摆动大小随拟合域变化（A4）"。
- `stage_neckopt` 的目标 `log10(max(rot_first_deg, 1e-3))` 不动；`build_table.py` 多存上述新键即可。
- 这些改动都不进哈希文件，不影响已解作业的 id。

## 5. 限制

- 只有一根股骨、一种楼梯载荷、一套材料、当前代码；{n} 个设计都是无领 neck_in_shoulder。
- 近端 / 远端按柄身节点对沿柄轴坐标的**中位数**对半分（与审查脚本一致），不是按长度或面积对半。
- 虚拟台架的"标记"是节点集，不是物理标记：CX5 用的是 5 mm 皮质层内的全部节点（含髓腔侧），物理标记只能贴外表面；差别未量化。读数中的"柄颈相对整柄弯曲"（中位 {f(B['neck_bend_deg_med']['first'], 3)}°）在真实台架里同样存在。
- 没有提交 FE，没有改 `stability.py`，没有写 Linux 的 queue / results / code / data。
"""
(A4 / "a4_summary.md").write_text(txt, encoding="utf-8")
print(txt)
