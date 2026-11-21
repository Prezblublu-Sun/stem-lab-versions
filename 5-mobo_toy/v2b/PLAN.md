# 【本会话】V2B 计划：理想化股骨 Dorr B × 直轴短柄，本机只做求解 → 出一版报告 V2B

> 2026-09-27 获用户批准。原写在共用计划文件 `C:\Users\sun\.claude\plans\fea-dorr-adaptive-crab.md` 中，按用户要求"新开一个文件夹进行计划"移到这里；共用文件已恢复为另一会话的 V2A 计划原文。

## Context

v2 测试设计（`v2\TEST_DESIGN.md` v0.2，commit 785ccdc）：
- 直轴短柄，11 个设计变量：长度、面积降低曲线 2、前后不对称截面 7、插入角 α；
- 尺寸与入口偏移由模板化决定；
- 3D FE 为主。

用户要求：本机只做求解；先做 Dorr 一型；出一版报告；评估工作量与时间。

本会话中用户的决定：
- **Dorr B**，理想化股骨。D5 对 B 几乎无影响，沿用现有 B 参数。
- **加扭转载荷 Fy**。
- **标准范围**：验证 + 64 点参考集 + BO 3 种子 × 64，约 300 次 FE。
- **PDF 在本机 Chrome 打印**。
- **新开文件夹**。

## 隔离（与 V2A 会话互不干扰）

- **本机**：全部新代码、配置、结果、报告放 `sandbox\mobo_toy\v2b\`。
  - 把 `v2/geom3d.py`、`v2/fe3d_geom.py` 按 commit 785ccdc 复制进 `v2b/`（V2A 计划要改 `v2/geom3d.py`），v2b 不再 import `v2/`。
  - v1 共享模块只读复用，不修改：`run_abaqus.py`、`abaqus/odb_export.py`、`inp_writer.py`、`spot3d/qoi3d.py`、`mobo.py`、`plotstyle.py`、`report.py`。
  - 需要的小改动在 v2b 内做：
    - `mobo.fit_gp` 的 [0,1] 输入边界：在 v2b 里替换模块属性，不改文件；
    - `plotstyle` 的 REPORTS / SPEC_PATH / CONFIG_PATH 指向 v2b（`v2b/psv2b.py`）。
- **Linux**：用 `~/mobo_toy_v2b/`（V2A 用 `~/mobo_toy_v2/`）。
- **配置**：`v2b/config.yaml` 复制 v1 配置后加 Fy、kappa_ap、模板化容差、α 范围；v1 的 config.yaml 不动。
- **本机 Abaqus 两会话共用**：两边同时求解会抢 8 个核，机时约翻倍。worker 设槽位上限，同一时间只让一个会话求解，或各分一半核，由用户安排。
- **git 共用同一个仓库**：另一会话有未提交的 `straight3d/`、`results/straight/`。本会话提交时只 `git add v2b/…` 的明确路径，绝不用 `git add -A` 或 `-u`；提交前先看 `git status`，不碰别人的改动。

## 架构（按审查意见修订：控制放 Linux，本机只做 worker）

- **Linux 编排**（tmux/nohup 常驻，不依赖 Claude 会话与 WiFi）：
  - 3 个 BO 进程，每个种子一个，调用未改的 `mobo.run`，其 `evaluate` 入队后阻塞等待结果；
  - 4–5 个网格进程：gmsh 子进程，设硬超时，`General.NumThreads=1`；
  - post 进程；
  - S4′ 作为低优先级填充。
  - **文件队列**：`queue/ → claimed/ → done/`，用原子 mv，claim 过期后收回；作业号 = inp 的 sha256。
- **本机 worker**（`v2b/worker.py`，只用标准库 + PyYAML，不 import numpy、shapely、gmsh、matplotlib）：
  - 用 Start-Process 后台启动，不建计划任务；
  - 循环：ssh mv 认领 → 用 Python subprocess + tarfile 拉作业包（不用 PowerShell 管道）→ `run_abaqus.run_and_export` 求解（显式传 cpus；timeout 取该网格档中位耗时的 3 倍）→ 推回 RELEASE_CONTACT / LOAD_CONTACT / LOAD_ENER / LOAD_S 四个 CSV → 删 odb。
  - 本地预取 2 × 槽位个作业；推送失败的结果放 outbox 重试。
  - ssh 参数：`ConnectTimeout=15`、`ServerAliveInterval=15`、`ServerAliveCountMax=4`。
  - 求解时 `TEMP/TMP=D:\abq_scratch`（C 盘只剩 25 GB）。
  - 启动时只清理**自己 pid 文件记录的**孤儿 standard.exe / pre.exe，不碰别的会话的作业。
  - 运行期间请用户保持本机不睡眠、暂缓 Windows 更新重启。
- **代码同步**：把 `git ls-files -co --exclude-standard` 打包 → `~/mobo_toy_v2b/code/<sha>/`，建 `current` 软链；哈希前统一行尾。
- **分段缓存键**：
  - 网格键 = 设计 + 分型 + 网格档 + 几何/网格代码 + 配置；
  - 求解键 = inp sha256 + cpus + Abaqus 版本；
  - 后处理键 = 求解键 + QoI 代码。
  - 这样改作图或 QoI 不会作废已有的求解。
- **Linux 环境**：`~/mobo_toy_v2b/.venv`，CPU 版 torch，版本按 `requirements-lock.txt`。
  - 先试 `import gmsh`：pip 轮子要 X/GLU 库，Linux 没有 sudo；缺库就用 micromamba 装 conda-forge 的 gmsh。
  - 作图字体用 Liberation Sans。

## 模型修正（审查发现）

- **假体颈**：不照搬 v1 `stem_neck`，因为它从截骨面下 2 mm 沿过 C0 的颈轴，e ≠ 0 时会压进骨，Ø14 也比小号肩部宽。
  - 改为颈轴从肩部中心 P0 到头心 H；
  - 截骨面以上 5 mm 从肩部截面放样过渡到颈圆；
  - 颈半径不超过肩部半厚。
- **Fy 符号**：在 S2′ 之前由文献坐标系定。FE 符号检查分不出 ±Fy，两个方向都会让 f1 升高。
  - 本模型 +x 内侧、+y 前方、+z 向上，右手系，对应左股骨；
  - 对照 Bergmann 2016 的股骨坐标（+x 外侧）换算，写进报告。
  - kappa_ap ≠ 0 时 ±Fy 结果不同。
- **柄应力约束**：取粘接模型 LOAD_S 的 mises，只统计截骨面以下柄体单元，按 EVOL 加权取 P99，排除颈与头。这个量同样纳入收敛研究与噪声底。
- **QoI 补项**：
  - 补 > 50 µm、> 150 µm 面积占比；
  - "扭转单独贡献"只在 S2′ 的符号检查设计上算，不对全部设计。
- **zone_sed**：断言截骨面 C03 与 `femur2d.cut` 一致；Gruen 区固定为 z ≥ −10，写进方法。
- **完整股骨参照**：把加密盒缩到 Gruen 区；1.0 mm 档单独跑。
- **网格试划**：本机求解前，先在 Linux 上对 ≥ 32 个池内设计在 2.0、1.4 mm 各试划一次。
  - v1 在 2 mm 的网格失败率已是 21%；v2 模板化让柄贴皮质，更容易产生细长楔形四面体。
  - 失败率 > 10% 就先修再往下走。

## 阶段与规则

- **S2′ 验证**：
  - E2E 1 个设计；
  - 并发对比（8 × 1、4 × 2、2 × 4 核），比完冻结 cpus 设置；
  - 符号检查；重跑一致性，多线程若不能逐位相同则用容差；
  - 网格收敛：2 个设计 × {2.0, 1.4, 1.0}，给出 GCI；
  - 排序保持：S4′ 的前 12 个设计 × {2.0, 1.4}，之后命中缓存；
  - 噪声底；
  - 3D Lamé 压配对照（圆柱套管，小模型）；
  - R3′ 的 11 维解析基准，只在 Linux 上跑。
- **生产网格规则**（事先约定，夜间可自动续跑）：12 设计上 2.0 与 1.4 mm 的 f1、f2 Spearman 都 ≥ 0.9，且中位相对变化 < 10%，则用 2.0 mm；否则用 1.4 mm。
- **S4′**：64 个设计取自与 BO 不同的池种子（99），兼作同预算 Sobol 基线与 GP 测试集。
- **S5′**：3 种子 × (24 + 10 × 4)。
  - 先把三个种子的初始点全部入队，参考点要用到它们；S4′ 填空闲槽。
  - L3 失败不占预算，由下一个池点补上，BO 与 Sobol 同一规则。
- **报告 V2B**：
  - `v2b/report_v2b.py` 包装：先 import psv2b，再调 `report.main`；
  - v1 作图函数复制到 `v2b/plots.py`，改为单型、11 变量（LABEL 覆盖）；
  - spec 写全必需键；Dorr A/C、Q3、Q4 对照等超出本轮的项登记为 NA 并注明原因；
  - HTML 在 Linux 生成，本机 Chrome 按 `report.to_pdf` 的参数打印。

## 工作量与时间（审查后修订）

吞吐（含扭转）：2.0 mm 每小时 12–17 个设计，1.4 mm 每小时 4.5–6 个。v1 3D 在 2 mm 下 f1 变化达 34%，所以把 1.4 mm 当作基准情形。

| 工作包 | 内容 | 开发 | 机时 |
|---|---|---|---|
| WP0 | 新文件夹、Linux 环境、代码同步、worker 骨架 | 2–3 h | — |
| WP1 | 建模器（假体颈/头、Fy、接触面、完整股骨）+ 网格试划 ≥ 32 设计 | 6–10 h | Linux 1–2 h |
| WP2 | 队列协议、Linux 编排、post、分段缓存 | 4–6 h | — |
| WP3 | E2E、并发对比、符号检查 | 2–3 h | 约 2 h |
| WP4 | S2′ 验证（含 1.0 mm、Lamé、噪声底）+ R3′ 基准 | 3–5 h | 6–8 h |
| WP5 | BO 问题类、可行池、阶段脚本 | 3–4 h | — |
| WP6 | S4′ 64 + S5′ 192（减 12 次缓存命中）；看护 2–4 h | 2–4 h | 2.0 mm 约 16–20 h / 1.4 mm 约 42–55 h |
| WP7 | V2B 报告 | 7–10 h | — |
| **合计** | 约 300 次 FE | **29–40 h** | **2.0 mm 约 25–34 h / 1.4 mm 约 52–72 h** |

**日历**：2.0 mm 约 **5–6 天**；1.4 mm 约 **7–8 天**。若 V2A 会话同时占用本机求解，机时约翻倍。

**最大风险**（按影响排序）：
1. S2′ 要求 1.4 mm；
2. v2 网格失败率；
3. 扭转导致不收敛或变慢；
4. WP1 超时；
5. 无人值守中断（睡眠、更新、WiFi）；
6. 报告改造量。

## 验证

1. `worker.py --once` 完成一个作业的认领、拉取、求解、推回；Linux post 输出 f1、f2、柄 vM P99，与 v1 3D 同量级。
2. 断开 WiFi 或杀掉 worker 后重启：队列能收回过期的认领，不丢结果，不重复求解。
3. 符号检查方向全部正确；Fy 符号有文献推导记录。
4. CAD 中柄 ∩ 皮质 ≤ 0.5%；零过切为 0 个点在柄外；网格试划失败率 ≤ 10%。
5. S2′：GCI 表；按生产网格规则自动定档。
6. S5′：中位 HV 比 ≥ 0.90；3 个种子都优于 Sobol；GP 覆盖率 0.80–0.97。
7. `v2b/report_v2b.py` 对 V2B 的判定不是 INCOMPLETE；本机打印 PDF 成功。

## 关键文件

- **新建（全在 `v2b/`）**：
  - `PLAN.md`、`config.yaml`、`geom3d.py` 与 `fe3d_geom.py`（785ccdc 快照）；
  - `model3d_v2b.py`（从 `spot3d/model3d._build` 抽出通用部分）、`prep.py`、`post.py`；
  - `orchestrator.py`、`worker.py`、`problem.py`、`stages.py`；
  - `plots.py`、`psv2b.py`、`report_v2b.py`；
  - `reports/spec.yaml`、`reports/V2B/text/{summary,methods}.md`。
- **只读复用**：`run_abaqus.py`、`abaqus/odb_export.py`、`inp_writer.py`、`spot3d/qoi3d.py`、`spot3d/model3d.py`、`mobo.py`、`plotstyle.py`、`report.py`。
