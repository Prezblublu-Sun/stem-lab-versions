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
| 2 批准 | 用户 | `approval.md` | 没有 approval.md，喂料门拒绝；approval 之后 gates.py 冻结 |
| 3 部署 | agent | `ops/deploy.py` | 冻结完好、已提交、已推 |
| 4 喂料 | agent | note.md 记时间 | Linux 侧 `stage_db.py feed`（旧批次）或新喂料器（待建）；版本一致 |
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

`ops/judge.py <批次目录> --db <版本目录>` 调用它、写 `result.json`、打印表。判据写在结果之前：`approval.md` 里要记 gates.py 当时的 sha256，judge 会比对。
