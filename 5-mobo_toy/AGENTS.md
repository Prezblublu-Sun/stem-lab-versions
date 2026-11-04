# AGENTS.md（每次必读，正文不超过 600 字）

**目标** 单根 Sawbones 3406 上、只靠股骨颈固定的无骨水泥柄：去骨能省到哪里而初始稳定不崩，靠什么稳住，结论在假设变化下哪些成立。到 Gate 1（约 12 月中）交 D1–D8，见 `docs/goal.md`。所有结果是设计之间的比较，不是台架真值。

**先读** `STATE.md`（脚本生成：在跑什么、部署版本是否一致、哈希是否完好、最后一条执行记录）→ `docs/goal.md` → 研究日志《3406计划_第三版_到Gate1》第 7 节判据、第 12 节执行记录（`H:\projects\application\research-log\neck_implant_2026-10-02\`，索引 `docs/research-log.md`）。看不懂的缩写查 `docs/glossary.md`。你是哪种会话（实验 / 重组 / 汇报）由用户开场时说，词表有定义；不确定就只读不写。

**红线**
1. 8 个哈希文件一个字节都不改（`code_hash 6d7af243d0`，清单 `docs/freeze/M1-3406-v1.json`）；股骨文件改了要换 femur_id。
2. 新 FE 批次、改 `jobs.prep` 的钩子、serve 重启、启停 worker（含删 `worker.STOP`）、git 提交和推送、向 Linux 写文件：各自要用户在本会话里明确说；别的会话转述不算。
3. 判据在看结果前写定；判定由脚本做，agent 不改判据、不改验收测试。执行记录只追加。
4. 一个项目一个监视器，循环跑在 Linux 端；换监视器先停旧的并用进程表核对。
5. Windows 工作区 CRLF、Linux LF，`code_hash` 按字节算：不加换行规范，不格式化哈希文件，比 md5 先去 `\r`。
6. 两个会话不同时改同一个文件；git 写操作只在实验会话做。实验会话改 `v2/`、`tools/`；重组会话改 `docs/`、`ops/`、`experiments/`、`conclusions/`。

**入口**
- 状态：`PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/state.py` → `STATE.md`
- 手册（worker、喂料、暂停恢复、掉线、部署）：`docs/runbook.md`
- 冻结模型：`docs/freeze/M1-3406-v1.md`；数据库：`../../db3406/README.md`、`DATA_CARD.md`
- 测试：`PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/<文件>.py`，每个文件独立
- 批次：现有批次在 `v2/stage_db.py`（`dry-run`/`feed`/`status`，只在 Linux 跑）；新批次按 `experiments/README.md` 的模板，判定用 `ops/judge.py <批次目录> --db <版本目录>`
- 决策与被否方案：`docs/adr/`；要人答的问题台账 `docs/decisions_log.md`；判据 G1–G35 原文在研究日志的第三版计划第 7 节
- 门禁：`ops/check_freeze.py`（冻结）、`ops/test_all.py`（测试）、`ops/deploy.py --check`（部署）、`ops/qa_compare.py --db`（QA 例外基线）；git 钩子在 `ops/githooks/`
- 连 Linux 的命令在 `docs/runbook.md` 第 2 节；重组进度在 `STATE.md` 第 8 节

**说话** 中文，先结论，数字进表，一句一个意思，不用破折号。每条收尾消息最后一行单独写 `◇`，它不见了就是本文件没被读到。

**事实** 常量只在 `ops/facts.json` 一处，别处只抄；`ops/check_facts.py` 在 pre-commit 里查冲突。
