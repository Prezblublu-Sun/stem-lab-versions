# 第二模型审查（批准前）

| 项 | 值 |
|---|---|
| 审查模型 | Claude Sonnet 5.5（写这批的是 Claude Opus 5.5） |
| 审查日期 | 2026-11-08 UTC |
| 审查包 | 第一轮 `ops/review_packet.py b32` 打印的 sha256 前 16 位 321051e088c7385c，加 `_packet/hook.md`（foam_refine.py 全文和 jobs.py、db_export.py、stage_db.py 的 diff）；第二轮 9dc72c8817217a0c，加改后的 hook.md 和第一轮意见 |
| 审查者看到的 | 审查包、补充文件和它点名去读的源文件（model3d_v2.py、model3d_m1.py、stage_v2a.py、solve_worker.py，只读），没有对话 |

## 第一轮：问题和处理

结论"改完再批"。

| 编号 | 严重度 | 问题（审查者） | 处理（写这批的模型） |
|---|---|---|---|
| 1 | 中 | 已在跑的旧喂料器内存里是旧 is_heavy，看不到 F5 行 | 在跑的是 b29 到 b31 的喂料器，75 行都不是重作业（复核者核过 rows.json），b28c 已结束，所以没有旧喂料器会提交重作业。b32 由新喂料器提交，看得见。喂前实查 Linux 上在跑的喂料器和队列里没有别的重作业 |
| 2 | 中 | 导出器会把 F5 行当成底行的摩擦复算 | 带键行的 fidelity 写 `h2+f5h<h>`，cond_key 加 foam_refine，`stage_db.cond_id` 加 `|f5h<h>`；不带键的行逐位不变 |
| 3 | 中 | slip_tol 没按单元尺寸放大，和 h 1.4 比会混进这个差 | 按 2.0 / h 放大：h 1.0 是 5e-4，h 0.7 是 0.000714286，和 h 1.4 的 0.000357143 同一规则；builder 核底行是 2.5e-4，G52 核导出值 |
| 4 | 中 | 导出的 foam_refine 只是 spec 原样，钩子静默不生效也能过 | G52 加接触对数门槛：h 1.0 至少是底行的 2.0 倍，h 0.7 至少 4.0 倍。本机 e +2 的真 spec 是 3.0 和 5.8 倍 |
| 5 | 中 | h 0.7 可能碰到 worker 的 6 h 上限，超时会被当成钩子错 | 拆成 b32（h 1.0）和 b32b（h 0.7），b32b 等 b32 的实测时间出来再喂；外推超过 5 h 先问用户。G52 里求解超时判不适用 |
| 6 | 低 | 冒烟证据是 e 0 的行和旧代码；跨平台节点数不同 | 本机用当前代码 prep 了两个真 spec 和底行（`prep_local.py`，`data/prep_local.json`）。部署后在 Linux 跑 `linux_check.py`：底行副本的节点、四面体、接触对、面数要等于记录，两档接触对比值要过门槛，否则退出码 1，不喂 |
| 7 | 低 | db3406/schema.json 没有 foam_refine 列 | 下次导出前重生 schema，写进提议 |
| 8 | 低 | 钩子进程级；intact、bench 带键被忽略；一行失败另一行没完时给 NA | jobs.prep 建完一定还原；非 design、variant 带键判 L1；任一行算失败（不是超时）就判不过。测试 E 节用替身走过 |
| 9 | 低 | 文字：重试倍数、4 mm 处的台阶、stage_db 头部 | 都改了 |

## 第二轮：复核改后的版本

结论"可以批"：第一轮 7 条已解决，1、5、6 条靠喂前检查补足；没有高、中严重度的新问题。7 条低严重度意见：

| 编号 | 问题（复核者） | 处理 |
|---|---|---|
| N1 | "timeout" 也会匹配 odb 导出超时；测试用的串和实际不同 | 超时还要 fail_stage 是 solve；测试改用 run_abaqus 实际写的 `m_fric: timeout > 21600 s`，另测导出超时判不过 |
| N2 | h 0.7 超时、h 1.0 已完时整体判不适用，h 1.0 的检查不出；b32b 不喂时 MC-1 怎么办没写 | 不适用时也把已算完那几行的检查写进 note；回退规则写进提议 |
| N3 | linux_check 只做 h 1.0，比值只打印 | 两档都 prep，比值不够或底行副本对不上就退出码 1 |
| N4 | b32b 的目录不存在 | b32 算完、决定喂 b32b 时补（gates.py 逐字节复制、批准记录、干跑） |
| N5 | finally 里再 import 可能盖掉返回值 | 改成只在 `foam_refine` 已在 sys.modules 时调 uninstall |
| N6 | 缺无键作业中性、成功路径的桩测试 | 加了无键作业走成功路径的桩测试（READY，prep.json 没有这个键，尺寸场没被碰）；带键的成功路径由 prep_local 的真建网覆盖 |
| N7 | fidelity 只带 h，不带带宽 | cond_key 能区分；MC-1 若改带宽再处理 |

测试：`v2/tests/test_foam_refine.py` 16/16，`v2/tests/test_stage_db_b32.py` 11/11，`experiments/b32_f5smoke/test_gates_b32.py` 22/22，`v2/tests/test_stage_db_b24.py` 36/36。

## 结论

两轮的问题都已处理，没有未关的高、中严重度问题。喂 b32 前还要过 linux_check 和队列实查。
