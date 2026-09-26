# mobo_toy — FEA → 代理 → 多目标贝叶斯优化 简单模型测试

场景：Dorr A/B/C 三型 2D 冠状面股骨 × 保颈斜插（圆弧中轴）短柄；双目标为初始微动与近端遮挡。
计划全文：`C:\Users\sun\.claude\plans\fea-dorr-adaptive-crab.md`。探针实验，不进正式 nTop 流水线；
沿用上级 `CLAUDE.md` 的单位、.inp 双模型、runs.csv 与失败分级规定。

## 当前阶段

**S-1 报告规范**：`REPORTING_SPEC.md` 待用户确认，确认后进入 S0。

## 报告工具

```bash
python report.py --render-spec     # spec.yaml → REPORTING_SPEC.md 第 6 节
python report.py --demo            # 合成数据演示整条报告流水线
python report.py --stage S2        # 生成某阶段报告（md + html + pdf）
python report.py --check R2        # 查缺项
python report.py --replot R2-F03   # 只凭 CSV 重画
python -m pytest tests
```

| 文件 | 作用 |
|---|---|
| `REPORTING_SPEC.md` | 报告规范（人读） |
| `reports/spec.yaml` | 报告登记表：每份报告的必备图、表、验收项（唯一真源） |
| `reports/checklists/erdemir2012_checklist.csv` | Erdemir 2012 FEA 报告清单 80 项与本项目落点 |
| `plotstyle.py` | 配色、尺寸、轴标签；`publish_figure/table/acceptance/inputs`；`replot` |
| `report.py` | 组装报告、缺项检查、PDF |
| `demo_report.py` | 合成数据演示 |
| `refs/` | 规范原文（Erdemir 2012 PMC 全文 XML） |

S-1 用系统 Python 3.12 即可（matplotlib、markdown、PyYAML、shapely 已装）；S0 起建 `.venv-mobo`。
