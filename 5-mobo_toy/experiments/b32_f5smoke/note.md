# 执行记录（只追加）

## 2026-11-08 13:09 UTC 部署 F5 钩子，三个在喂的喂料器停了

- 13:09:42 UTC 用 `ops/deploy.py` 部署了 9ea92c3 的 `v2/foam_refine.py`、`v2/jobs.py`、`v2/stage_db.py`。
- 部署后的 Linux 检查（`linux_check.py`）过了：底行副本的节点、四面体、接触对、面数和记录逐项相同，h 1.0、h 0.7 的接触对是底行的 2.99、5.76 倍，gmsh 4.15.2，code_hash 6d7af243d0。
- 但 b29、b30、b31 的喂料器在 13:09:50 到 13:10:28 之间都停了："aux code files changed while feeding"：jobs.py 的 md5 从 899c370d 变成 aa61a884。喂料器每轮核对 AUX_FILES（jobs.py 不在 code_hash 里但影响结果），变了就停，要么还原，要么换批次名。这个规则在部署前没有想到，两轮审查也没提。
- 停之前已提交的行照常求解。部署后才写 prep.json 的只有 `db_al_rs1_13_e+0_be8cddd2`（13:10:10，READY）；它的 prep 子进程可能在 13:09:42 之前就起了，用的是旧 jobs.py。就算用了新的，新 jobs.py 对不带 foam_refine 的作业网格逐项不变（上面的检查）。
- 处理：jobs.py 在仓库里换回 f2e5fbe 的内容（md5 899c370d），推送后用 deploy.py 部署，再用 `ops/feed_gate.py --start` 重启三个喂料器。b29 到 b31 全部算完后，再把 F5 版的 jobs.py 提交、部署，然后喂 b32。这期间 `v2/tests/test_foam_refine.py` 的 E 节跳过并打印原因。
- 以后要部署 AUX_FILES 里的文件，先确认没有喂料器在跑。`v2/foam_refine.py` 也影响结果，喂 b32 前把它加进 stage_db 的 AUX_FILES（b29 到 b31 的清单里没有它，那时它们已经结束）。

## 2026-11-08 13:58 UTC 重启

- 2ba5272 推到 J:（37/37），13:55 UTC 用 deploy.py 部署 jobs.py，Linux 上 md5 回到 899c370d。三批都过了 `feed_gate --check --require-review`，13:55 到 13:57 UTC 用 `--start` 重启喂料器，清单接上：b29 DONE 11、b30 DONE 9、b31 DONE 6，没有失败。监视器 13:58 UTC 重新挂上。

## 2026-11-08 部署门 5

- 用户"加上"：`ops/deploy.py` 加了门 5（6dccbf7）。要推的文件属于辅助代码（stage_db 和 db_export 两份 AUX_FILES 的并集，含 jobs.py、foam_refine.py），而 Linux 上有喂料器活着，就拒绝；只有用户明确说时才用 `--allow-aux-with-feeders`。ops 测试 25/25。

## 2026-11-08 20:01 UTC 喂 b32

- b29 19:59 UTC 结束（b29 到 b31 共 75 行全 DONE），20:00 UTC 起导出 v0.13，作业清单冻住（1423 个）后部署 99c1610（F5 版 jobs.py md5 aa61a884，foam_refine.py 进 AUX_FILES）。b32 干跑 1 行新行、没有问题；队列里没有别的作业；rows.json 提交 d34b33e；喂料门全过，20:01 UTC 起喂料器，h 1.0 一行标成重作业提交。根盘余 31 GB。
