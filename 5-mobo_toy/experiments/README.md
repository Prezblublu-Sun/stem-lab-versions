# experiments/：每批一个目录

2026-11-04 起，新的 FE 批次按这里的模板走；旧批次（b1–b24）留在 `v2/stage_db.py`，不再往里加。
一个批次目录 = 一次实验的全部自证：提议、判据、批准、结果、判定、记录。缺前一步的产物，下一步就拒绝。

```
experiments/
  README.md                 本文件
  _template/                复制它开新批次
  b23_ow4/                  试点：用已完成的 b23 回放（第 3 步）
  <bNN_简名>/
    proposal.md             提议：目的、绑定的交付物 D 编号、行数、槽时估计、依赖、风险
    gates.py                判据：纯函数，输入冻结的数据版本目录，输出每条判据的 PASS / FAIL / NA 和数字；批准后不能改（PreToolUse 钩子挡）
    approval.md             批准记录：用户原话、日期、批准的行数与槽时上限、是否改过 gates；由人填
    batch.py                行规格：产出 rows.json（每行一个 spec 的物理键和条件），干跑在 Linux 上做；现阶段可以只是对 stage_db 批次号的引用
    rows.json               batch.py 的产物，喂料前冻结
    result.json             ops/judge.py 的产物：数据版本、每条判据的结果、用到的行 id、生成时间
    note.md                 只追加的记录：喂料时间、异常、更正、判定后的结论（人写）
```

## 流程

| 步 | 谁 | 产物 | 门 |
|---|---|---|---|
| 1 提议 | agent | `proposal.md`、`gates.py`、`batch.py` → `rows.json` | 提议里必须有 D 编号和槽时估计 |
| 1b 审查 | 另一个模型 | `review.md`（模板 `_template/review.md`） | `ops/review_packet.py <批次>` 生成审查包，审查者只读它；高严重度问题没关闭不能批准。11-04 起加 |
| 2 批准 | 用户 | `approval.md` | 没有 approval.md，喂料门拒绝；approval 之后 gates.py 冻结 |
| 3 部署 | agent | `ops/deploy.py` | 冻结完好、已提交、已推 |
| 4 喂料 | agent | note.md 记时间 | `ops/feed_gate.py <批次> --check` 过六道门（冻结、批次目录和 sha256、review、已提交已推、Linux VERSION 和 stage_db 一致、无喂料器无 STOP 磁盘够）再 `--start`；监视器用 `ops/watch_remote.sh`，一个项目一个，登记在 Linux `logs/watcher.lock` |
| 5 导出 | agent | db3406 新版本 | `ops/qa_compare.py` 无新增失败 |
| 6 判定 | `ops/judge.py` | `result.json` | 读冻结的数据版本；agent 不改 gates.py |
| 7 记录 | agent / 用户 | note.md 追加；第三版计划第 12 节追加一条 | 只追加 |

## gates.py 的接口

```python
GATES = {"G30": "一句话说明", ...}          # 判据编号 → 说明（与计划第 7 节一致）
def judge(db_dir: str) -> dict:
    """返回 {"G30": {"status": "PASS"|"FAIL"|"NA", "value": 数字或None, "threshold": ..., "rows": [job_id...], "note": "..."}, ...}
    只读 db_dir 下的 scalars.csv（必要时 fields/）；不读 Linux、不读对话。"""
```

`ops/judge.py <批次目录> --db <版本目录>` 调用它、写 `result.json`、打印表。判据写在结果之前：`approval.md` 里要记 gates.py 当时的 sha256，judge 会比对（11-11 起真的比对：对不上就拒绝判定，`--replay` 时只提醒；`approval.md` 里一个哈希都没有的旧批次只提醒）。

## 判据里要用 F：读数据库的列（导出器 0.2.6 起）

数据库从导出器 0.2.6 起有 `F` 这一列（床支撑，网格版），另有 4 列它用到的量：`F_area_mm2`、`F_n_nodes`、`F_t_min_mm`、`F_frac_floor`。新批次的 `gates.py` 直接读 `scalars.csv` 的 `F`，不要再带一份 `mesh_F`、颈轴和参考点。

- 定义和 b28 以后各批判据里的 `mesh_F` 逐字相同。在 v0.14 的 1158 行上和 8 个判据文件逐行比过，逐位相同。
- 常数只在一处：`tools/db_export.py` 的 `BED_F`，`ops/facts.json` 的 `bed_F_*` 是同一组数，有测试把两处绑在一起。
- 没有界面点云的行（只解粘接的行、失败的行、完整股骨）`F` 是空的。
- 截骨比 A 深 15 mm 以上的设计（截骨高度大于约 31 mm），算 F 的区域里没有节点，`F` 是 0，`F_n_nodes` 是 0。这是定义的结果，不是错。
- 已冻结的判据文件不动。b25 的判据用的是旧轴，它算的 F 和这一列不同（平均差 1.6 mm，最大 5.9 mm），这是预期的，`ops/facts.json` 里记着。
- 这是网格版。选点脚本用的 0 FE 版（`b28_fam/prep/data/opt3_geom.py`）还不是数据库的列。

## 行文件批次（11-11 起，`v2/stage_db.py` v1.26）

"取一个已经 DONE 的行，换一个条件"这种批次不用再往 `stage_db.py` 里加构造函数。在批次目录里放一个 `rows_in.json`（模板 `_template/rows_in.example.json`），批次名不要用 `BATCHES` 里已有的名字。

| 条件 | 写法 | 得到的行 |
|---|---|---|
| 网格 | `{"mesh": 1.94}`，可选 1.94、2.06、1.4 | 带粘接，用同网格的完整股骨参照；1.4 是重作业 |
| 载荷 | `{"load": "F1714"}`，可选 F1714、F3839 | 只解摩擦 |
| 扭转 | `{"torsion": {"def": "A", "T_Nm": 10}}`，定义 A 或 B | 只解摩擦；A 的预载 1000 N 沿柄轴，B 用 F3839 |
| 位姿 | `{"pose": {"de": 1.0}}`，四个量 `de`、`ds`、`rot_deg`、`dalpha_deg` | 只解摩擦，号固定 |
| 泡沫加密 | `{"foam_refine": {"h": 1.0}}` | 只解摩擦，重作业，`slip_tol` 按 2.0 / h 放大 |

规则：

- 每行恰好一个条件。两个条件叠在一行、带载荷的网格行，现在不支持。
- 基线行必须是 3406、m1、h 2.0、楼梯载荷、没有任何条件键的行，并且已经 DONE。
- 新的一种条件是新代码（`build_file` 里加一个分支和测试），不是新数据。
- 新层要在 `layers` 里声明来源，取值只能是已有的来源之一。新层一律慢启动。
- `rows_in.json` 和判据一起冻结：`approval.md` 要记它的 sha256（去掉 CR 后算），批准后守护钩子不让改，喂料门会比对。
- 它要先部署到 Linux：`ops/deploy.py --files experiments/<批次目录>/rows_in.json`。往 Linux 写要用户明说。
- 干跑、`rows.json`、喂料、判定都和原来一样：`stage_db.py dry-run <批次>`，再用 `batch.py --from-dry-run` 存 `rows.json`。
- 喂料中 `rows_in.json` 变了或没了，喂料器写清单后停止，和辅助代码变了同样处理。

### 新设计也可以写成行文件

`"form": "new_designs"`（模板 `_template/rows_in.new_designs.example.json`）：每行是一个新设计，给 13 个单位坐标、入口偏移、0 FE 模板化得到的号和去骨量。原来 b25、b29、b30、b31 那种批次就是这个形状。

- 原来的检查一条不减：A 的 m 1.0 版必须 DONE；m 不小于 1；物理键只许在设计、截骨、入口偏移上和 A 行不同；`stage_db.py` 重新做 0 FE 模板化，和文件里的号、去骨量比对。
- `requires_done` 列出必须已经 DONE 的作业，比如判据要对照的 A 族曲线 7 行。
- 新层可以声明 `selection`：`stratum` 或 `adaptive`。不许声明 `iid`：独立同分布的行必须由代码里带种子的规则抽。
- b30 那种"恰好只改一个因素"的检查不在这里，要的话是新代码。

### 选点策略和 FE 之间的接口

换一个选点策略，就是换一个写 `rows_in.json` 的脚本。`stage_db.py` 不用动。

| 方向 | 是什么 | 在哪里 |
|---|---|---|
| 策略读 | 一版数据库，只读 | `db3406/<版本>/scalars.csv` |
| 策略问 | 要算哪些行 | `experiments/<批次>/rows_in.json`，随提议一起冻结 |
| FE 答 | 每行的结局，和该告诉策略什么 | `ops/outcomes.py experiments/<批次> --db <版本> --json` |

"答"里每行有一项 `tell`：

| `tell` | 含义 | 策略该怎么用 |
|---|---|---|
| `result` | 算完了 | 按作业号去数据库读数 |
| `infeasible` | 这个设计在这根骨上放不进去 | 可以当作约束的信息 |
| `failed` | 网格或求解在数值上失败 | 可能有物理含义，由策略自己定怎么用 |
| 空 | 环境问题、代码出错、有意跳过、待查、或这版数据库里没有 | **不要当成设计失败** |

保证：同一个基线行、同一个条件，行文件得到的作业号和原来各批的构造函数逐个相同。新设计也一样：b25、b30、b31 的 35 行写成行文件后作业号逐个相同。`v2/tests/test_stage_db_rows_in.py` 用 b24、b26、b28c、b32、b32b、b33 的 45 行比对，也和冻结的 `rows.json` 比对。
