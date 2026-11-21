# 历史：2D 探针实验（2026-09-26 至 09-28，原 README.md 内容）

> 2026-11-04 从仓库 `README.md` 原样移来。这是仓库最初的 2D 三型股骨 × 弧形短柄探针实验，阶段 S0–S7 的脚本在仓库根目录，报告在 `reports/`。
> 2026-09-28 起工作转到 `v2/`（真实股骨 3D，V2A），2026-10-23 起转到 Sawbones 3406。现行说明见 `README.md` 和 `AGENTS.md`。

---

# mobo_toy — FEA → 代理 → 多目标贝叶斯优化 简单模型测试

场景：Dorr A/B/C 三型 2D 冠状面股骨 × 保颈斜插（圆弧中轴）短柄；双目标为初始微动（P95）与近端遮挡（Gruen 7 SED 下降率）。
计划：`C:\Users\sun\.claude\plans\fea-dorr-adaptive-crab.md`；报告规范：`REPORTING_SPEC.md`（用户 2026-09-26 确认）。
探针实验，不进正式 nTop 流水线；沿用上级 `CLAUDE.md` 的单位、.inp 双模型、runs.csv 与失败分级规定。

## 阶段与报告

| 阶段 | 脚本 | 报告 | 状态 |
|---|---|---|---|
| S-1 | `report.py`, `plotstyle.py` | `REPORTING_SPEC.md` | 已确认 |
| S0 | `stage_s0.py` | R0 环境与冒烟 | PASS |
| S1 | `stage_s1.py` | R1 几何与设计空间 | R1-A4 不通过（C 型几何门通过率 16 %），待用户决定 |
| S2 | `stage_s2.py` | R2 FE 模型与验证 | 见报告；R2-A2（f1 网格收敛）不通过，待用户决定 |
| S3 | `stage_s3.py` | R3 优化器自检 | 运行/已完成 |
| S4 | `stage_s4.py`, `reference_sweep.py` | R4 参考扫描 | 代码就绪，等 R1/R2 的处置确认 |
| S5 | `stage_s5.py`, `mobo.py`, `mobo_fe.py` | R5 BO 结果与代理诊断 | 代码就绪，同上 |
| S7 | `stage_s7.py`, `spot3d/` | R6 3D 抽检 | 3D 几何与网格已通，等 S5 |
| 收尾 | `stage_r7.py` | R7 总结与可信度 | 代码就绪 |

## 模型要点（相对已批准计划的修改，均写进对应报告）

1. 设计变量改为由尖端位置定义圆弧（`tip_depth`, `tip_lat`, `w_prox`, `taper`, `theta_in`）；原 (L, κ) 空间 98 % 不可行。
2. 加 3 mm 前后皮质侧板：无侧板时 2D 骨在截骨面处开口，压配后 90 % 界面张开。
3. 压配三步：固定假体头压配 → 释放 → 加载；微动 = 加载相对释放的滑移增量。
4. 头心载荷均分到 14 mm 圆盘内节点（替代分布耦合，求解快 5 倍）。

## 常用命令

```bash
.venv-mobo/Scripts/python.exe stage_s2.py          # 各阶段脚本同理
.venv-mobo/Scripts/python.exe report.py --stage S2  # 重建某阶段报告
.venv-mobo/Scripts/python.exe report.py --replot R2-F03
.venv-mobo/Scripts/python.exe -m pytest tests
```

运行记录：`results/runs.csv`（一行一设计，含几何门失败）；设计目录 `runs/<design_id>/`（成功设计只留 gzip 的 inp、所需 CSV、日志与网格）。
缓存键含配置与建模源码哈希，代码一改旧结果不再命中。
