# mobo_toy：Sawbones 3406 颈部柄的 FE 数据库与优化流水线

规则和入口见 `AGENTS.md`（每次必读）。目标与交付物见 `docs/goal.md`，运行手册 `docs/runbook.md`，冻结模型 `docs/freeze/M1-3406-v1.md`。
仓库名 `mobo_toy` 来自 2026-09 的 2D 探针实验（`docs/history_2d_probe_2026-09.md`），Gate 1 之后再改名。

## 现在在做什么（2026-11-04）

单根 Sawbones 3406 上、只靠股骨颈固定的无骨水泥柄：13 个设计量，Abaqus 压配摩擦模型，GP 代理 + 主动学习选点，数据库 db3406（v0.9，1292 个作业）。所有结果是设计之间的比较。

## 布局

```
AGENTS.md  CLAUDE.md(@AGENTS.md)  STATE.md(脚本生成)
docs/        goal.md  runbook.md  glossary.md  vision.md  research-log.md  decisions_log.md  freeze/  adr/
ops/         state.py（STATE.md）check_freeze.py  test_all.py  deploy.py  qa_compare.py + qa_baseline.json  judge.py  guard_pretooluse.py  githooks/
experiments/ 每批一个目录：proposal.md  gates.py  approval.md  batch.py  rows.json  result.json  note.md（模板 _template/，试点 b23_ow4/）
conclusions/ 结论总表的数字复算
v2/          FE 流水线（冻结的 8 个哈希文件 + jobs.py + 钩子 + stage_*.py + tests/）
tools/       db_export.py  db_qa.py  db_archive.py（数据库工具，Windows 上跑）
abaqus/      odb_export.py（Abaqus 内置 Python）
reports/ results/ runs/(junction→G:)  2026-09 探针实验的产物，不再新增
```

## 三台机器

| 机器 | 做什么 | 入口 |
|---|---|---|
| Windows 本机 | Abaqus 求解（`v2/solve_worker.py`）、导出、QA、git | `v2/runs/start_worker.ps1` |
| Linux `linux-user@<linux-ip>` | prep、post、模板化、GP/BO、喂料（`~/mobo_toy_v2`） | `~/mobo_toy_v2/run.sh` |
| J: | 备份（robocopy + 裸仓库远程 `j`） | `git push j master` |

## 常用命令

```bash
PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/state.py              # 生成 STATE.md
PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_b23.py   # 单个测试文件
python v2/stage_db.py dry-run b24 --root ~/mobo_toy_v2                # Linux 上，干跑批次
python tools/db_qa.py --db "../../db3406/v0.9"                        # QA 一个版本
```

数据库的导出、归档、QA 流程在 `../../db3406/README.md`。
