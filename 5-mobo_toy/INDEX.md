# 项目索引

生成时间：2026-09-29。项目目录 `G:\projects\Femoral implant generation\sandbox\mobo_toy\`。

这份索引回答三个问题：一个标签指什么；它的文档、脚本、结果各在哪里；现在还算不算数。标签的含义是手写的，文件是否存在和作业数由 `build_index.py` 现查。

结果有两处。本机的在项目目录里。Linux 的在 `~/mobo_toy_v2/` 下，其中 `queue/` 是全部作业，`results/` 是各阶段的汇总。Linux 上的内容不在 git 里。

## 1 模型代次与分支

| 标签 | 含义 | 位置 | 状态 |
|---|---|---|---|
| v1 | 二维冠状面模型。三种理想化股骨，圆弧中轴短柄，5 个变量 | `stage_s0.py`<br>`reports/`<br>`results/`<br>`runs/` | 已完成，报告 R0 到 R7 |
| v2 | 直轴短柄的测试设计，11 个变量，理想化三维股骨。只做了几何 | `v2/TEST_DESIGN.md`<br>`v2/geom3d.py`<br>`v2/fe3d_geom.py`<br>`v2/cases.py`<br>`v2/dorr_revision.py`<br>`v2/out/` | 被 V2A 取代 |
| V2A | v2 的柄放进一根真实股骨。此后所有三维实验都在它上面 | `v2/` | 现行 |
| V2B | v2 的柄放进理想化的 Dorr B 股骨。另一个会话的计划 | `v2b/` | 没有跑过。Linux 上的 `~/mobo_toy_v2b` 只有运行环境 |
| straight3d | 另一个会话对直柄的独立实现 | `..\mobo_straight\` | 已停用。其中 9 个公共模块与本项目根目录相同 |
| explore | 柄型变更时给用户看的几何案例 | `explore/` | 一次性，不进流程 |
| 重新设计方案 | 从头再做一遍的方案，没有求解 | `REDESIGN_PROPOSAL_2026-09-29.md` | 提议 |


## 2 第一阶段 v1 的阶段与报告

阶段用 S 编号，报告用 R 编号。两套编号不是一一对齐的：S7 对应 R6，没有 S6。

| 阶段 | 报告 | 内容 | 脚本 | 结果 |
|---|---|---|---|---|
| S0 | R0 | 环境与冒烟，悬臂梁对解析解 | `stage_s0.py` | `reports/R0_env_smoke/` |
| S1 | R1 | 几何与设计空间 | `stage_s1.py`<br>`femur2d.py`<br>`stem2d.py` | `reports/R1_geometry/` |
| S2 | R2 | 有限元模型与验证 | `stage_s2.py`<br>`stage_s2cal.py`<br>`fe_model.py`<br>`mesh2d.py` | `reports/R2_fe_verification/`<br>`results/noise_floor.json`<br>`results/tie_check.json`<br>`results/S2_sideplate_calibration.json`<br>`results/S2_3d_probe.json` |
| S3 | R3 | 优化器在解析基准上的自检 | `stage_s3.py`<br>`mobo.py` | `reports/R3_optimizer_selftest/`<br>`results/S3_selftest.json` |
| S4 | R4 | 参考扫描，得到参考前沿 | `stage_s4.py`<br>`reference_sweep.py`<br>`evaluate.py` | `reports/R4_reference_sweep/`<br>`results/S4_groups.json`<br>`results/S4_sobol_indices.json`<br>`results/runs.csv` |
| S5 | R5 | 贝叶斯优化对同预算随机采样 | `stage_s5.py`<br>`mobo_fe.py` | `reports/R5_bo_results/`<br>`results/S5_runs.json`<br>`results/S5_summary.json`<br>`results/pools/` |
| S7 | R6 | 三维抽检 | `stage_s7.py`<br>`spot3d/` | `reports/R6_spot3d/`<br>`results/runs3d.jsonl` |
| 收尾 | R7 | 总结与可信度 | `stage_r7.py` | `reports/R7_summary/` |
| — | RD | 报告流水线演示，全部是合成数据 | `demo_report.py` | `reports/_demo_pipeline/` |


每个设计的运行目录在 `runs/`，目录名是 `d` 加六位序号加哈希前四位。完整股骨参照在 `results/intact/`。

## 3 第二阶段的实验，旧界面模型

这一节的实验都用旧界面模型。它们的设计结论已经撤回，数据留作记录。“Linux”一行指 `~/mobo_toy_v2/results/` 里的汇总文件。

| 标签 | 含义 | 文件 |
|---|---|---|
| V2A | 真实股骨上的验证、64 点参考集、贝叶斯优化 | **文档** `v2/reports/V2A_real_femur/`<br>**脚本** `v2/stage_v2a.py` `v2/model3d_v2.py` `v2/post.py` `v2/problem_v2a.py` `v2/femur_real.py` `v2/cases_real.py` `v2/report_v2a.py` `v2/report_v2a_fe.py` `v2/report_v2a_bo.py` `v2/build_report_v2a.py`<br>**Linux** `e2e.json` `signs.json` `convergence.json` `mesh_decision.json` `reference.json` `bo_s0.json` `final_bo_summary.json` `feasibility_*.json` `overcut_cad.json`<br>**作业前缀** `e2e` `signs` `conv` `ref_r` `bo_` |
| V2A-2 | 柄长下限从 40 扩到 20 mm，加 32 个短柄探针 | **文档** 并入 V2A 报告<br>**脚本** `v2/stage_v2a2.py`<br>**Linux** 重映射后的 `reference.json` `bo_s0.json`<br>**作业前缀** `probe_` |
| V2A-C | 只接触松质骨的尺寸规则，留 1 mm 松质层 | **文档** 项目总结第 5.3 节<br>**脚本** `v2/stage_v2ac.py`<br>**Linux** 没有汇总文件，结果在作业里<br>**作业前缀** `cref` `cprobe` |
| V2A-U | 把皮质余量并入设计变量的热启动优化 | **文档** 项目总结第 5.3 节<br>**脚本** `v2/stage_v2au.py`<br>**作业前缀** 没有产生作业 |
| V3 | 稳定性对去骨体积，9 个变量，两个种子 | **文档** `v2/reports/V3_short_stem/`<br>**脚本** `v2/stage_v3.py` `v2/report_v3.py`<br>**Linux** `v3_bo_s0.json` `v3_bo_s1.json` `v3_summary.json` `pools/`<br>**作业前缀** `v3_` |
| V3 敏感性 | 松质骨模量 200 MPa 和过盈 0.05 mm 各重算一批 | **文档** V3 报告的图 F03、表 T02<br>**脚本** `v2/stage_v3sens.py`<br>**Linux** `v3_sens.json`<br>**作业前缀** `v3sens` |
| 原始数据导出 | 每个设计一行的总表 | **脚本** `v2/rawdata.py`<br>**Linux** `raw/` |


本机只有 V3 的四个汇总文件：`v2/results/v3_bo_s0.json`、`v2/results/v3_bo_s1.json`、`v2/results/v3_sens.json`、`v2/results/v3_summary.json`。V2A 的汇总只在 Linux 上。

## 4 评审之后的工作

| 标签 | 含义 | 文件 |
|---|---|---|
| 修改方案 V4 | V3 之后的修改方案。它是方案，不是实验 | **文档** `v2/REVISION_PLAN_V4.md` |
| 应力屏蔽 | 210 个设计的粘接模型对完整股骨 | **文档** `v2/STRESS_SHIELDING_2026-09-29_corrected.md` `v2/STRESS_SHIELDING_2026-09-28.md`<br>**脚本** `v2/shielding.py`<br>**结果** `v2/results/shielding/` |
| M1 | 重建的界面模型和它的验证 | **文档** `v2/M1_VERIFICATION.md` `v2/M1_RUN_STATE.md`<br>**脚本** `v2/model3d_m1.py` `v2/post_m1.py` `v2/stage_m1.py` `v2/report_m1.py` `v2/build_m1_doc.py`<br>**结果** `v2/results/m1_report/`<br>**Linux** `m1_lame.json` `m1_friction.json` `m1_noise.json` `m1_compare_d0.05.json` `m1_signs.json` `m1_mesh.json` `m1_delta.json` `m1_smoke.json`<br>**作业前缀** `m1_` `m1lame` |
| audit3 | 第三份评审意见的复核，只用已有结果 | **文档** `v2/REVIEW3_AUDIT.md`<br>**脚本** `v2/audit3.py` `v2/build_audit3_doc.py`<br>**结果** `v2/results/audit3/` |
| review3，也叫 audit3b | 第三份评审之后补跑的 23 个验证作业 | **文档** `v2/REVIEW3_RUNS.md`<br>**脚本** `v2/stage_m1.py` 的 review3 命令 `v2/audit3b.py` `v2/build_review3_runs_doc.py`<br>**结果** `v2/results/audit3b/`<br>**Linux** `m1_review3_ids.json` `m1_review3.json`<br>**作业前缀** `m1_` |
| 整体评估 | 各环节可信度、结论清单、后续试验计划 | **文档** `v2/PROJECT_ASSESSMENT_2026-09-29.md`<br>**脚本** `v2/build_assessment_doc.py`<br>**结果** 读 audit3、audit3b、m1_report |
| ata：对照 | 对照 Naghavi 2023 博士论文检查本项目 | **文档** `v2/ATA_THESIS_COMPARISON_2026-09-29.md`<br>**脚本** `v2/build_ata_doc.py`<br>**结果** 读 shielding、m1_report |
| ata：零求解 | 骨吸收比例、三套分区、柄应力分段 | **文档** `v2/ATA_FOLLOWUP_2026-09-29.md`<br>**脚本** `v2/resorption.py` `v2/build_ata_followup_doc.py`<br>**结果** `v2/results/resorption/` |
| ata：求解 | 网格检查、2300 N 工况、柄模量，共 27 个作业 | **文档** `v2/ATA_RUNS_2026-09-29.md`<br>**脚本** `v2/stage_ata.py` `v2/build_ata_runs_doc.py`<br>**结果** `v2/results/ata/` `v2/results/ata_ids.json`<br>**作业前缀** `ata_` |
| ata：图表 | 论文里用有限元评估柄的图表总结，原页摘录 | **文档** `v2/ATA_FE_FIGURES_2026-09-29.md`<br>**脚本** `v2/build_ata_figs_doc.py`<br>**结果** `v2/refs_pdf/11_*.pdf`，不进 git |
| doe_evidence | 试验设计论证：样本量、采集什么，用已有数据上的实测作依据。是重新设计方案的补充 | **文档** `DOE_JUSTIFICATION_2026-09-29.md`<br>**脚本** `v2/doe_evidence.py` `v2/build_doe_doc.py`<br>**结果** `v2/results/doe_evidence/` |
| collar：领与椭圆截面 | 2026-10-02 加入领（有无与外伸宽度）、椭圆截面、领与截骨面的接触；截骨范围的解剖量；6 个验证作业。之后追加颈部柄第一阶段筛选网格（长 25/30/35 mm × 领 0/2/4 mm × 圆、椭圆、非对称截面，27 个设计，另加 3 个 3 mm 领的探针）与第二阶段优化（`v2/stage_neck2.py`：截面形状与截骨高度 25–40 mm） | **文档** `v2/COLLAR_ELLIPSE_2026-10-02.md`<br>**脚本** `v2/stage_collar.py` `v2/build_collar_doc.py` `v2/stage_neck2.py`<br>**结果** `v2/results/collar/`<br>**作业前缀** `collar_` |
| 项目总结 | 全过程的时间线记录 | **文档** `PROJECT_HISTORY_2026-09-29.md`<br>**脚本** `build_history.py` `PROJECT_HISTORY_base.md`<br>**结果** 读各阶段结果 |
| 日报 | 9 月 28 日一天的操作与结果，含更正 | **文档** `v2/DAILY_REPORT_2026-09-28.md`<br>**脚本** 手写 |
| Methods 草稿 | 方法部分的英文草稿，配参考文献原文 | **文档** `v2/METHODS_draft.md`<br>**脚本** `v2/build_methods_bundle.py` |
| 报告规范 | 所有正式报告的结构、作图、验收规则 | **文档** `REPORTING_SPEC.md` `reports/spec.yaml` `v2/reports/spec.yaml`<br>**脚本** `report.py` `plotstyle.py` `v2/psv2.py` |


修改方案 V4 里还有两套编号：

| 编号 | 含义 |
|---|---|
| M1 到 M6 | 六项修改内容。M1 界面模型，M2 验证补齐，M3 生理与材料，M4 设计空间，M5 代理与优化，M6 冻结与重跑 |
| P0 到 P6 | 七个执行步骤。P1 对应 M1，P2 对应 M2。P3 到 P6 后来被整体评估里的阶段 A 到 D 取代 |
| 阶段 A 到 D | 整体评估里的后续计划。A 定标，B 冻结与参考集，C 优化，D 推广 |
| A1 到 A6 | 阶段 A 里的六组试验 |


## 5 作业前缀

作业号的格式是“阶段_标签_哈希”。哈希由设计、设置、网格和代码版本算出，同样的输入得到同样的作业号。作业数来源：现查。

| 前缀 | 作业数 | 含义 | 属于 |
|---|---|---|---|
| `ref_r` | 64 | 64 点参考集里的设计 | V2A |
| `ref_intact` | 12 | 完整股骨参照，各档网格 | V2A 起共用 |
| `e2e` | 1 | 端到端试跑 | V2A |
| `signs` | 5 | 方向性检查 | V2A |
| `conv` | 18 | 网格收敛与排序保持 | V2A |
| `bo_` | 82 | 贝叶斯优化选的点 | V2A |
| `probe_` | 32 | 20 到 40 mm 短柄探针 | V2A-2 |
| `cref` | 43 | 参考集在留松质层规则下重算 | V2A-C |
| `cprobe` | 6 | 短柄探针在留松质层规则下重算 | V2A-C |
| `v3_` | 80 | V3 优化选的点 | V3 |
| `v3sens` | 16 | V3 敏感性补跑 | V3 |
| `m1_` | 75 | 新界面模型的设计作业，含 review3 的 23 个 | M1 |
| `m1lame` | 24 | 压配解析对照 | M1 |
| `ata_` | 27 | 对照论文之后的三组求解和三个参照 | ata |
| `collar_` | 34 | 领与椭圆截面的验证 | collar |


前缀 `ref` 有两个意思：`ref_r` 是参考设计，`ref_intact` 是完整股骨参照。

## 6 作业类型、模型、状态、失败等级

| 类别 | 取值 | 含义 |
|---|---|---|
| 作业类型 | design | 一个设计，解摩擦和粘接两个模型 |
| 作业类型 | intact | 完整股骨参照 |
| 作业类型 | bench | 压配解析对照 |
| 作业类型 | variant | 带配置覆盖的设计，不进任何常规数据集 |
| 模型 | fric，摩擦模型 | 算微动 |
| 模型 | bond，粘接模型，也叫绑定 | 算应力屏蔽、骨吸收、柄应力 |
| 界面版本 | 旧界面模型 | `v2/model3d_v2.py`。腔是柄内缩，两套网格不重合 |
| 界面版本 | M1，新界面模型 | `v2/model3d_m1.py`。共用界面网格，逐节点给过盈 |
| 作业状态 | NEW、READY、CLAIMED、SOLVED、DONE、FAILED | 作业目录里的标记文件 |
| 失败等级 | L1 | 参数或模板化不成立 |
| 失败等级 | L2 | 几何不成立 |
| 失败等级 | L3 | 建网格失败 |
| 失败等级 | L4 | 求解不收敛、超时或内存不足 |
| 失败等级 | L5 | 导出或后处理失败 |
| 代码版本 | 10 位哈希 | 由 8 个建模与后处理文件算出，写进每个作业的 `prep.json` |


假体颈起点修正之前的两个代码版本是 `af2719da27` 和 `3edd9887e5`，文档里叫“修正前”，其余叫“现行版本”。

## 7 关注量、分区、参数

| 名称 | 含义 | 数据里的字段 |
|---|---|---|
| f1，微动 | 旧模型：接触滑移增量的 P95。新模型：第二循环可恢复的切向相对位移 P95 | `f1_p95_um` |
| 首次加载微动 | 新模型里第一次加载的量，含就位位移 | `f1_first_p95_um` |
| f2 | 旧的约束量：固定区、皮质与松质混合的应变能密度变化。已停用 | `f2_g7_loss_pct` |
| 应力屏蔽 | 分区内皮质 von Mises 的体积平均，相对完整股骨 | `ssi_pct`，旧文件里是 `chg_vm_pct`，符号相反 |
| 骨吸收比例 | 逐点应变能密度之比低于 1 减死区的骨所占比例 | `res_0.4` `res_0.6` `res_0.75` |
| 去骨体积 | 截骨加锉骨去掉的骨量。2026-09-29 之前叫“骨量损失” | `bone_loss`，字段名没有改 |
| 柄应力 | 粘接模型里柄的 von Mises | `vm_p99`，分段后是 `vm_max_body_deep` 等 |
| G1 到 G7 | Gruen 分区 | — |
| calcar_fixed | 固定的股骨距区：内侧、小转子下 10 mm 以上 | — |
| stem、femur、fixed | 三套分区：柄坐标系；股骨坐标系随柄定位；股骨坐标系固定 | `scheme` |
| δ，过盈量 | 也写作 delta、interference | `delta` |
| μ，摩擦系数 | 默认 0.3 | `mu` |
| 摩擦容差 | 罚函数摩擦的弹性滑移参数，生产值 0.00025 | `slip_tol` |
| h_cut，截骨高度 | 截骨面到头心的距离，沿颈轴 | `h_cut` |
| m，皮质余量 | 柄面到内膜面的距离，负值表示允许贴皮质 | `margin` |
| collar_w，领宽 | 领超出柄截口的外伸宽度，0 为无领；领厚 `collar_t` 默认 2.5 mm | `design.collar_w` |
| 椭圆截面 | 截面公式的特例：n_a = n_p = 2，γ_ml = γ_ap = 0.5，τ_a = τ_p = 0 | `geom3d.is_ellipse` |
| 领的结果 | 领承担的接触力比例、领面滑移、领掀起面积；带领时微动只统计柄身 | `collar_force_share_load2` 等 |


## 8 代表设计

| 名称 | 柄长 | 插入角 | 来历 | 对应的作业 |
|---|---|---|---|---|
| 基准，base | 60 mm | 20° | 人为设定的基线 | `v2/stage_v2a.py` 里的 BASE |
| 原读数，readout | 53 mm | 39° | V2A 里读出的“最优”设计。结论已撤回，设计仍用作对照 | `bo_qnehvi_s1_r0_62bbf792` |
| 短柄，short | 25 mm | 37° | 短柄探针里的一个 | `probe_L25_12_e265f0bf` |
| cmp 加 8 位哈希 | 各不相同 | 各不相同 | 新旧界面对比用的 12 个设计 | `m1_cmp*` |


## 9 编号规则

| 编号 | 格式 | 例子 |
|---|---|---|
| 报告里的图 | 报告号-F 加两位序号 | R5-F01，V2A-F11，V3-F03 |
| 报告里的表 | 报告号-T 加两位序号 | R4-T02，V2A-T06 |
| 验收项 | 报告号-A 加序号 | R5-A1，V2A-A4 |
| v1 的设计号 | d 加六位序号加哈希前四位 | d000001_f506 |
| 三维作业号 | 阶段_标签_八位哈希 | m1_short_h2_tol0.00025_delta0.05_e43ffe63 |


## 10 公共模块与基础设施

| 文件 | 作用 | 谁在用 |
|---|---|---|
| `report.py`<br>`plotstyle.py` | 报告生成与作图样式 | v1 和 V2A、V3 的正式报告 |
| `v2/psv2.py` | 把报告的路径指到 v2 | V2A、V3 报告 |
| `v2/build_doc.py` | 把独立的文档转成 PDF | 第 4 节的全部文档 |
| `inp_writer.py`<br>`run_abaqus.py`<br>`abaqus/odb_export.py` | 写输入文件、提交求解、导出结果 | v1 和三维阶段共用 |
| `qoi.py`<br>`spot3d/qoi3d.py` | 由导出的表算关注量 | v1 和旧界面模型 |
| `mobo.py` | 高斯过程与多目标贝叶斯优化 | S3、S5、V2A、V3 |
| `v2/remote.py` | 本机与 Linux 之间同步代码、执行命令、取回文件 | 三维阶段 |
| `v2/jobs.py`<br>`v2/maint.py` | 作业队列、建模与后处理的调度、队列维护 | 三维阶段，在 Linux 上 |
| `v2/solve_worker.py` | 本机求解进程 | 三维阶段，在本机 |
| `config.yaml`<br>`v2/config_v2a.yaml` | v1 与 V2A 的配置 | — |
| `tests/` | 几何与报告工具的测试 | v1 |
| `README.md` | 项目说明 | 只写到 v1，已过时 |


本机求解进程的日志和重启脚本在 `v2/runs/` 下。这个目录被 git 忽略，里面的两个脚本不受版本管理。

## 11 同一件事的不同叫法

| 现在用的叫法 | 别的叫法 |
|---|---|
| 去骨体积 | 骨量损失，bone loss，`bone_loss` |
| 骨吸收 | bone resorption。文献里也写作 bone loss |
| 应力屏蔽 | 应力遮挡，stress shielding，SSI |
| 粘接模型 | 绑定，bond，TIE |
| 过盈量 | δ，delta，interference，压配量 |
| 第三份评审的复核 | audit3，REVIEW3_AUDIT |
| 第三份评审后的验证作业 | review3，audit3b，REVIEW3_RUNS |
| 对照 Naghavi 论文 | ata，Ata |
| 原读数设计 | readout，读数设计 |
| 现行版本 | 修正后，current |
| 柄坐标系分区 | 随柄移动的分区，stem |


## 12 本机与 Linux 的对应

| 内容 | 本机 | Linux |
|---|---|---|
| 代码 | 项目目录，git 管理 | `~/mobo_toy_v2/code/`，由本机同步过去 |
| 股骨几何 | `v2/data/` | `~/mobo_toy_v2/data/` |
| 全部作业 | 没有 | `~/mobo_toy_v2/queue/`，5.6 GB |
| 各阶段的汇总 | `v2/results/`，只有一部分 | `~/mobo_toy_v2/results/`，39 项 |
| 求解时的工作目录 | `v2/runs/q/`，求解完只留日志 | — |
| v1 的运行目录 | `runs/`，13 GB | — |
| 参考文献原文 | `v2/refs_pdf/`，不进 git | — |


## 13 没有归入索引的文件

根目录和 `v2` 下的脚本与文档都已归入。

