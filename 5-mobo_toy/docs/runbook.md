# 运行手册（runbook）

只写"怎么做"和"踩过的坑"。目标在 `docs/goal.md`，规则在 `AGENTS.md`，模型在 `docs/freeze/M1-3406-v1.md`。
每条都写明来源日期；过时就改，不留旧说法。

## 1 地图

| 东西 | 位置 | 说明 |
|---|---|---|
| 代码仓库 | `H:\projects\Femoral implant generation\sandbox\mobo_toy`，git master，远程 `j` = `J:\Backup 2026\02_备份_活跃项目\git\mobo_toy.git` | `v2/runs` 和 `.venv-mobo` 是指向 `G:\projects\Femoral implant generation\sandbox\mobo_toy\...` 的 junction；G: 上那份代码是 10-10 的旧副本，**永远不要从 G: 启动 worker** |
| Linux 建模机 | `linux-user@<linux-ip>`，`~/mobo_toy_v2/{code,data,queue,results,logs,adhoc,deck}`，入口 `~/mobo_toy_v2/run.sh`（带 libGLU 的 venv python） | 做 prep（gmsh、模板化）、post、GP/BO、喂料；没有 Abaqus |
| 求解 | 本机 Windows，`v2/solve_worker.py`，Abaqus 2025 在 D:（坏扇区盘） | 3 槽 × 5 核，许可在本机 |
| 数据库 | `H:\projects\Femoral implant generation\db3406`（仓库之外） | 工具和流程见 `db3406/README.md` |
| NN | `H:\projects\Femoral implant generation\ml3406`（git），Linux `~/ml3406` 在 NVMe 上（`/mnt/nvme`，非永久挂载） | |
| 研究日志 | `H:\projects\application\research-log\neck_implant_2026-10-02` | 计划、判据、执行记录（只追加）；索引见 `docs/research-log.md` |
| 备份 | `J:\Backup 2026\02_备份_活跃项目\H\projects\...`，robocopy，日志在 `_MANIFEST` | 每次导出后做 |

## 2 连接 Linux

```bash
"/c/Program Files/Git/usr/bin/ssh.exe" -o BatchMode=yes -i ~/.ssh/id_ed25519_lrlbackup linux-user@<linux-ip> '<命令>' < /dev/null
```

- 必须写用户名和这把私钥；默认密钥不被接受；Tailscale 名字按策略拒绝，用 LAN IP（10-23、11-02）。
- 只读命令随时可跑。**向 Linux 写文件要用户在对话里明确授权**，一次授权不沿用（11-02）。
- 远程起后台进程：`(setsid nohup <cmd> >> log 2>&1 < /dev/null & echo $! > pid)`，ssh 本身要 `< /dev/null`，否则通道挂着不退（10-24）。
- `pgrep -f <模式>` 可能匹配到 ssh 的 shell 自己（pid 回绕），模式要锚定，如 `^.*/.venv/bin/python v2/stage_db.py feed`（11-01）。
- 只读评估脚本的跑法：`ssh ... 'cd ~/mobo_toy_v2/code/v2 && OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 timeout 200 taskset -c 4-7 nice -n 19 ../../run.sh -' < script.py`。

## 3 求解 worker（Windows）

| 动作 | 做法 |
|---|---|
| 启动 | `powershell -NoProfile -ExecutionPolicy Bypass -File "v2\runs\start_worker.ps1"`（默认 3 × 5，环境变量 `MOBO_SLOTS`/`MOBO_CPUS` 可改；有 `worker.STOP` 或 pid 活着就不启动） |
| 优雅停 | 建 `v2\runs\worker.STOP`，在跑的单元算完才退；下次启动前删掉 |
| 立刻停 | 杀 worker 进程树和 `standard.exe`；被杀的作业在 Linux 上 `mv CLAIMED READY`（不要写成 FAILED），恢复后从头算（11-04） |
| 看状态 | `v2\runs\worker.pid`、`worker.log`（claimed / OK / pushed, SOLVED）、`tasklist | findstr standard` |
| 重启后 | 登录任务 `MoboSolveWorker` 11-04 00:32 重启后**没有**把 worker 带起来，b24 的行在 READY 上停了 13 小时。重启后手动跑 start_worker.ps1，并核对 READY 是否有人领 |

- venv 的 `python.exe` 是启动器：同一命令行出现两个 python.exe 是正常的，判重复 worker要看 `worker.log` 里有没有重复 claimed（10-23）。
- 偶发 `PermissionError [WinError 5]` 启动 standard.exe 失败是瞬态；把该作业在 Linux 上重置为 NEW/READY 再算；多次出现怀疑 360 拦截（10-24）。
- h 1.4 的作业每个求解进程 4.4–6.0 GB 内存；桌面应用占 45 GB 时只剩约 22 GB 可用（10-24）。

## 4 Linux 侧：serve、喂料器、队列

- serve：`cd ~/mobo_toy_v2 && (setsid nohup taskset -c 4-11 nice -n 19 ./run.sh code/v2/stage_v2a.py serve --n-prep 2 >> logs/serve.log 2>&1 < /dev/null &)`。serve 给每个 NEW 作业起独立子进程、子进程重新 import，所以 `jobs.py` 和钩子模块的改动**不用重启 serve**就生效（11-04 读代码确认）。改 post 侧的常驻代码才要重启，重启要用户批准。
- 喂料器：`./run.sh code/v2/stage_db.py feed <批次>`（同样 setsid nohup，日志 `logs/db_feed_<批次>.{out,log,pid,lock}`）。先 `dry-run <批次>` 看预期 id、查重、problems 为空。
- 操作标记文件（在 `~/mobo_toy_v2`）：`STOP_DB_FEED` 停全部喂料器，`STOP_DB_FEED_<批次>` 只停一个；`DB_RELEASE_<层>` / `DB_RELEASE_ALL` 放行被门挡住的层；`DB_ACK_FAILED_<键>` 确认已知失败；`DB_H14_REF_OK` / `DB_H14_EXCLUSIVE` 管 h 1.4 重作业。
- 喂料器规则：全部喂料器合计未认领 db_* 作业不超过 6 个；每层慢启动 2 行；第一次启动要根分区 ≥ 30 GB（10-28 曾因此拒绝启动）；`code_hash` 不符就退出。
- 队列状态按文件：`NEW → READY（prep 完） → CLAIMED（worker 领走） → SOLVED → DONE`，失败 `FAILED.json`。
- **挂起一个作业**：`touch -d '2030-01-01' <job>/READY`（worker 按 READY 的 mtime 从旧到新领）。**不要改名 READY**，否则 serve 当它是 NEW 重新 prep（10-24）。提前：`touch -d '<旧日期>' READY`。
- 根分区：导出闸门 15 GiB，喂料器首启 30 GB；11-04 剩 35 GB（93 %）。大文件去 NVMe：`/mnt/nvme/mobo_raw`（原始 CSV 经软链接）、`/mnt/nvme/ml3406`。**NVMe 重启后不自动挂载**，用户跑 `sudo ~/ml3406/mount_nvme.sh`。

## 5 部署代码到 Linux

- 同步列表在 `v2/remote.py` 的 `SYNC`；`remote.sync_code()` 整包推送并写 `~/mobo_toy_v2/code/VERSION`；`remote.put()` 推单个文件（**不更新 VERSION**，所以 VERSION 会过时：11-04 发现它停在 10-24）。
- **11-04 起用 `ops/deploy.py`**：`--check` 随时可跑（只读，比 HEAD / 本地 / Linux 三方 LF md5 并打印 Linux VERSION）；`--files a b c` 推文件，前提是冻结完好、文件已提交且与 HEAD 相同、HEAD 已推到 j/master，推完逐文件比 md5，再写 VERSION（提交号、UTC）和 `deployed_md5.txt`。`--allow-dirty` 只在用户明确要推未提交文件时用，VERSION 记 dirty。推之前仍要用户授权写 Linux。
- **git 钩子**（`git config core.hooksPath ops/githooks`，11-04 已设）：pre-commit 查冻结（工作区字节 + 暂存区 LF 内容）、产物/日志/密钥/大于 5 MB 的文件、AGENTS.md 字数；pre-push 再查冻结并跑 `ops/test_all.py`（11-04 实测 29 个测试文件全过、590 s；只改文档和 ops 时只查冻结；`SKIP_TESTS=1` 跳过要写进记录）。
- **写入保护钩子** `ops/guard_pretooluse.py`：Claude Code 的 PreToolUse，挡 Write/Edit 8 个哈希文件、`docs/freeze/`、已批准批次的 `gates.py`，以及 Bash 里对这些文件的写、删、重定向。注册在三处项目级 `.claude/settings.json`：仓库目录、`G:\projects`、`G:\projects\application`（后两处是实验会话和重组会话的启动目录；用户 11-04 决定只保护有关的会话，不装用户级）。从这三个目录启动的会话才受保护，已开着的会话要重启才加载。
- **冻结核对** `ops/check_freeze.py`：`--staged` 提交前用；`--restore` 从 `docs/freeze/M1-3406-v1_files.tar` 写回 8 个文件的原字节（新 clone 后必须做，否则 code_hash 不对）。
- 换行：仓库 `core.autocrlf=true`，Windows 工作区是 CRLF、git 对象是 LF。Linux 上**混着**：10-24 `sync_code` 整包推上去的 33 个 `v2/*.py` 带 CRLF（如 stage_v2a、resorption、shielding），之后单文件 `put` 的是 LF（11-04 核对，内容去 CR 后全同）。所以比 md5 一律两边都 `tr -d '\r'` 后再比，`ops/state.py` 已这样做。`code_hash` 按字节算，8 个哈希文件两边已核对一致（10-24），**不要加 .gitattributes 或跑格式化器**，除非先把 8 个文件标成不转换并重新核对哈希。
- **8 个哈希文件本身也是混的**（11-04 核对）：geom3d、fe3d_geom、model3d_v2、model3d_m1、post_m1 在工作区是 CRLF，femur_real、post、config_v2a 是 LF；`code_hash 6d7af243d0` 就是对这组字节算的。git 对象一律 LF，所以**从 git 重新检出算不出 6d7af243d0**（全 LF 是 ebefa65488），Linux 上那份也是原字节复制来的。冻结的真身是 `docs/freeze/M1-3406-v1.json` 的 sha256 加同目录的 `M1-3406-v1_files.tar`；`ops/check_freeze.py` 核对，`--restore` 写回。
- 规格构建代码（stage_db、tpl_record、collar_rule）改了之后**不要盲目重提交同名批次**：job id 会变，旧 ids 文件会被覆盖（10-06 批次 F 的教训）。

## 6 导出、QA、归档、备份

按 `db3406/README.md` 的 1–6 条：冻结清单 → 分批 pull（Windows 上跑，流经 ssh）→ finalize → `db_qa.py` → `db_archive.py archive/results` → CHANGELOG 和 DATA_CARD 写条目 → robocopy 到 J:（`_MANIFEST` 记日志）→ `git push j`。
- QA 第 1、7、13 条从 v0.6 起一直 FAIL，都是已知行（cpress 尖峰、网格重试 1.94 的 CR-T 两行、Bath 行误报）。判断新版本好坏看**是否新增失败**：`ops/qa_compare.py --db <版本目录>` 对照 `ops/qa_baseline.json`（v0.9 的已知失败行），只有新增才退出码 1；要接受新例外，先在 CHANGELOG 写理由再 `--accept`。
- 导出半成品目录带点（`.BAD`、`.replaced.<UTC>`）会被 finalize 和 QA 跳过；可删。
- Linux `~/mobo_toy_v2/results`（BO 记录、AL 选点、候选池、`db_manifest_*.json`）只有 Linux 一份，第 0 步拉回备份。

## 7 监视器

- 全局规则（`C:\Users\sun\.claude\CLAUDE.md`）：不在 Windows 上用 Monitor 或本地循环轮询远程；用一条 ssh 长连接，循环跑在 Linux 端，事件发生就退出；换监视器先停旧的，用进程表核对已退出；一个项目只留一个。
- 11-02 事故：旧会话累积 107 个 `mon_*.sh` 循环，每 5 分钟弹一批 `bash.exe` 窗口。
- 监视器要看：FAILED 新增、喂料器退出、STOP 出现、**READY 长时间没人领**（11-04 漏报的一种）。

## 8 暂停与恢复

| 用户说 | 做 | 记 |
|---|---|---|
| 暂停求解 / 空出 CPU | 放 `worker.STOP`；要立刻就杀进程并把 CLAIMED 改回 READY | 第三版第 12 节一条：时间、哪些作业被打断 |
| 停止模拟任务 | 上一条 + Linux 放 `STOP_DB_FEED`，喂料器 SIGTERM；serve 可留 | 同上，加恢复办法 |
| 继续 | 删 STOP 文件，重置被打断的作业，`start_worker.ps1`，重启喂料器 | 同上 |

恢复只按用户的话来，不按旧链脚本整条重跑（11-01 的 chain_al3.sh 作废就是例子）。

## 9 H: 掉线

H: 是 USB 盒里的 2 TB 盘，11-01 掉过一次。worker 的 cwd、代码、`worker.log` 都在 H:，掉线后 worker 写不了日志也推不回结果，在跑的作业留在 CLAIMED。恢复：H: 回来、旧 PID 已退，再在 Linux 上 `mv CLAIMED READY`，然后 `start_worker.ps1`。监视器读 `worker.pid` 走 G: 路径，所以掉线时它还能报。

## 10 本机风险（用户处理）

- D:（含 E:）有坏扇区，页面文件和 Abaqus、SolidWorks 还在上面；大作业前把 Abaqus scratch 指到 G:，并设 `memory=`（10-24）。
- C: 常年快满（Abaqus 默认 scratch 在 C:）。
- `_fe_backup` 47 GB（10-23 的 FE 原始备份）不在 J: 上。
