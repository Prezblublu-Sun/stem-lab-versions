"""3406 数据库（db3406）的批量提交器 v1.1（D1 = v0 + 审查修正 + 采纳 CD-0 种子 + 第二轮审查修正）。规划：research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md
（第 1.6 节命名 / 查重 / 版本陷阱、第 1.8 节检查 13 / 14、第 2.1–2.7 节；用户 2026-10-25 批准两天部分）。
不改 8 个哈希文件（code_hash 必须是 6d7af243d0）、不改 jobs.py / stage_neckopt.py / stage_deck.py / stage_v2a.py；提交只走 jobs.submit。

    python v2/stage_db.py dry-run b1 [--root <只读副本>]   只打印：每个 spec 的键、层、stage、源作业、相对源 spec.json 的变体（键 旧 -> 新）、
                                                          预期 id、查重结果（hash8 / 物理键）、种子采纳、参照与参照核对；末尾 DRY-RUN-JSON。什么都不写
    python v2/stage_db.py feed b1 [--once] [--poll 60]    喂料器（只在 Linux 上跑）：
        cd ~/mobo_toy_v2/code && nohup taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed b1 >> ../logs/db_feed.out 2>&1 < /dev/null &
    python v2/stage_db.py status b1 [--root …]            只读：清单 results/db_manifest_b1.json + 队列里的状态

批次 b1 = 规划第 2.4 节的第一批（"首批 95 个"；只粘接补算的个数由队列决定，见下：84 行）。全部 kind variant（参照 kind intact），stage db_*：
    REF   db_ref  完整股骨参照 h_int 1.94 / 2.06 / 2.5 / 1.4 = sb_intact_h2_9c9d7fb5 的 spec 只改 h_int（3406 参照就是
                  {kind intact, h_int, femur_id, neck_axis}：jobs.prep → model3d_v2.build_intact(h_roi = h_int, h_far = spec 或 6.0, E_canc)）
    CD-0  db_cd   δ：A、B、B′、C、D、a62 × δ 0.025 / 0.20（12）+ 这 6 个与 init29 × δ 0.05（7）；起身：B、D、a62、init29 × stage_deck.D13_STS
                  （1714 / 3839 N，前 24°、矢 8°，原样，8）；全部只解摩擦（fric_only）。这 27 行已由主会话在 2026-10-25 22:50–23:02 UTC
                  作为种子提交（results/db_seed_CD0.json；spec 多带 db_layer / db_cond / femur_model_version / source_job / load_case 等元数据键，
                  所以 hash8 与本模块的不同）：查重的物理键认出它们，每行记成 existing、指向种子作业（见"查重"与"种子采纳"）
    NZ-1  db_nz   B、B′、C、D × h_int 1.94 / 2.06，带粘接（摩擦 + 粘接），intact_job = 同网格的 db_ref（8）
    FD-0  db_fd   h 2.5 先导 24 个设计（A、B、B′、C、D、a62、init29、init 中位 INIT_MEDIAN + 两臂落在角落子盒里的 16 个 PILOT16，
                  修订 h25_pilot_design 的 picked16_job_ids）× h_int 2.5，带粘接，参照 db_ref h2.5；h 1.4：A、init29，带粘接，参照 db_ref h1.4，
                  slip_tol = stage_deck.M_SLIP14（= 2.5e-4 × 2.0 / 1.4，与 M14 / verify_mesh14 相同的字面值：弹性滑移上限仍 0.5 µm）
    BD    db_bo   只粘接补算（stage db_bo：规划 1.6 的 db_bd 留给边界 / 跳变层；层名 "BD mesh" / "BD h2.0" 沿用 v0 的键）：
                  (i) 现有 6 个只解摩擦的网格变体（d13mesh 4、v3406 噪声 2，δ 0.025 照旧）各一个同网格 bond_only，参照 = 该网格的 db_ref；
                  外加 v3406 噪声设计的 h 2.0 一个 bond_only（源 = 它 h 2.0 的只解摩擦孪生作业 sb11_smoke_f_h16_898709ba，参照
                  sb_intact_h2_9c9d7fb5），使噪声对的 SED 有 h 1.94 / 2.0 / 2.06 三点（审查第 6 条）；
                  (ii) 先导 24 个设计里 h 2.0 一侧没有可用粘接结果的，各一个 h 2.0 bond_only，参照 sb_intact_h2_9c9d7fb5。
                  "可用" = 队列里（不含 db_* 作业）DONE、物理 spec 与源作业相同、带粘接模型（不是 fric_only）、intact_job = sb_intact_h2_9c9d7fb5、
                  result.json 的 vm_p99 与 f2_g7_loss_pct 都是有限数（阶段 13 / 14 的 20 % 粘接作业与 D13 的 bond_only 都算）。
    spec 构造照 stage_deck D13：源 spec.json 去掉 created / stage / tag / kind / bond_only / fric_only / intact_job / source_job / gate 等
    （PHYS_KEYS 以外已知的元数据键），再写本层的变体与角色键。spec 里只放物理键：同一物理计算 = 同一 hash8。
    来源、selection、层、条件 id、是否带粘接、intact_job、股骨版本、源作业记在作业表与清单里，不进 spec。
    源 spec 里有未分类的键 → SystemExit（不默默丢掉一个可能影响结果的键）。

作业表 / 清单的词汇（规划 1.6 与 DATA_CARD 要补进去，D4 / D5 按此归类）：
    source     intact_ref（REF：完整股骨参照）| cond_anchor（CD-0）| noise（NZ-1）| fid_h25 / fid_h14（FD-0）|
               bond_partner（BD：只粘接补算，给已有只解摩擦的作业配 SED / vM）
    selection  reference（REF 行）| stratum（其余各层：按层的设计 / 条件清单选出）
    model_set  intact | fric | fric+bond | bond；condition_id = δ | 载荷 | 网格 | slip_tol（参照：intact | 载荷 | 网格）

查重（规划 1.6；v1 加物理键，审查第 8 条）：
    (1) hash8：同一 hash8 的队列目录逐个读 spec.json，去掉 stage / tag / created 后与本 spec 逐键比：相同 → queued（预期 id 已在）或
        existing（别的 stage 下同一 spec）；不同 → hash8 碰撞 → SystemExit；同一 hash8 的目录没有可读的 spec.json → SystemExit。
    (2) 物理键：spec 去掉 META_KEYS 与 stage / tag / created、kind design 与 variant 视为同一个（"design|variant"；intact / bench 不并）
        之后的规范 JSON（数值表示也要相同：2 与 2.0 不算相同，宁可重算也不错用）。队列按它建索引；命中的目录再逐键比一次（phys_diff 为空）
        → existing（dedup_via "physics"），不再提交。未分类的键留在物理键里，所以带未知键的作业永远不会被认成同一物理计算。
        已有作业带 femur_model_version 且不是本模块的 → 问题（拒绝）。kind 只影响 jobs.prep / post 的分支 bench / intact：design 与 variant
        走同一条建模（else 分支）、同一条后处理、serve 同样等参照（stage_v2a.serve：kind in (design, variant)），所以并起来不改物理。
    种子采纳：results/<SEEDS[批次]> 存在时，每个种子键（CD0_delta0.025_A → CD0_d0.025_A，CD0_sts_F1714_B → CD0_sts1714_B）都必须正好
        对应本批一行，且该行经物理键查重 existing 到同一个种子作业（1:1）；种子文件里的 spec 必须等于队列里的 spec.json（去 created）；
        code_hash 相同。任何一条不符 → 问题（dry run 退出 1、feed 拒绝）。SEEDS[批次] 声明的种子文件不存在 → 问题（1:1 采纳无从核对；
        不要这个核对只能从 SEEDS 里明确删掉该文件）。
    命中已有作业的核对（hit_checks；build 与 feed 时对活队列再查重都用它）：查重得到 existing / queued（hash8 或物理键）的行，
        该作业带 femur_model_version 且不是本模块的 → 问题；该作业 FAILED → 问题（同一物理 = 永远不会再算，留一个洞），除非操作员写了
        ~/mobo_toy_v2/DB_ACK_FAILED_<键>（接受这个 FAILED 作为该行的结果：不重算，按层闸门里算已确认）。清单已把该行记成这个作业
        （之前某次启动时采纳或提交的，例如种子之后才 FAILED）→ 不是问题，它是该层一个普通的 FAILED 行（按层闸门照算）。
        feed 时查重出问题 → 写清单、停止（_halt）；REF 行在 feed 时查重到与建表时不同的 id（建表之后有人提交了同样的完整股骨 spec）
        → 停止：依赖它的行的 intact_job 是建表时的 id，会一直等一个不会出现的目录；重启也会因为预期 id 变了被拒绝 → 换批次名。

提交前的检查（任何一条不过 → 拒绝，SystemExit 带原因；dry run 列出全部问题，退出码 1）
    stage 以 "db_" 开头且在 DB_STAGES 里（不以 sb / neck 开头、不是 ref）；作业号（预期与查重后的）不以 sb13_ / sb14_ 开头；
    对阶段 11–14 的 Phase 都 in_family(spec) 为假（stage_neckopt 只读导入）；kind / model / fric_only / bond_only / intact_job 的组合；
    网格变体（h_int ≠ 2.0）不能只解摩擦（10-23 规则），带粘接的网格变体必须指向同网格的 db_ref；h 1.4 的行要有本批的 h 1.4 参照；
    参照核对（陷阱 4）：带粘接 / 只粘接的 spec 读出 intact_job 的 spec，kind intact，femur_id、h_int、cfg.load（楼梯 = 两边都没有 cfg）、
    E_canc、neck_axis、h_far 都相同，cfg 里不能有 load 以外的键；批内两个键得到同一 id → 报错；
    磁盘闸门：队列所在文件系统剩余 < 15 GiB → 拒绝提交；第一次启动（还没有清单）剩余 < 30 GB（27.9 GiB，规划 G0）→ 拒绝启动；
    code_hash ≠ 6d7af243d0 → 拒绝；股骨几何键（femur_3406.py + 两个 STEP 的 sha256）与清单里记的不同 → 拒绝；
    不计入 code_hash、但影响结果的代码文件 AUX_FILES（inp_writer.py、collar_rule.py、jobs.py、stability.py、femur_3406.py、
    abaqus/odb_export.py；相对代码根 ~/mobo_toy_v2/code；在本机不存在的记 null，例如 odb_export.py 只在 Windows 求解端）的 md5：
    第一次启动记进清单（陷阱 2 aux_code_md5），重启时不同 → 拒绝；每一轮再核对，变了 → ERROR + 事件 + 写清单后停止。

喂料器（feed）：按作业表顺序提交，跳过暂时不能放的行（不挡后面的行）：
    队列深度：未领取的 db_* 作业（NEW + READY，含种子）≤ MAX_UNCLAIMED = 6（serve 按名字排序建模，db_* 排在 sb* 前面：少量入队）；
    参照优先（审查第 4 条）：REF_h1.94 / 2.06 / 2.5 里有一行还没提交（pending）或在 NEW / READY 时，其他未领取的 db_* 作业最多
        REF_PRIORITY_CAP = 1 个（worker 按 READY 先后认领，参照因此排在前面）。独占的 REF_h1.4 不触发这条（它要等队列全空，
        触发的话整批会被压到 1 个直到最后）；
    依赖闸门：带粘接 / 只粘接的行等 intact_job DONE（参照 FAILED → 该行 blocked，记 ERROR，不重试）；
    重作业闸门：完整股骨参照与 h_int ≤ 1.4 的作业算重作业，全队列（任何 stage）NEW / READY / CLAIMED 的重作业 ≥ 1 时不放新的重作业；
    独占（审查第 1 条；规划 2.1 "h 1.4 单独跑"）：EXCLUSIVE = REF_h1.4 只在一轮开始时全队列（任何 stage）没有 NEW / READY / CLAIMED（与没有
        spec 的目录）时提交，提交后本轮立即结束；它在 NEW / READY / CLAIMED 期间，其他 db 提交一律暂停。喂料器平时一直有轻作业在飞，
        所以它通常在队列排空时才跑（批次末尾；若中途某一轮恰好队列全空，就在那时跑，轻作业等它）；
    h 1.4 的行（FD0_h1.4_*）还要等本批的 h 1.4 参照 DONE，并等操作员文件 ~/mobo_toy_v2/DB_H14_REF_OK（看过参照 .dat 的内存估计后写；
        文件比 h 1.4 参照的 spec.json 旧 = 上一次留下的，不算），没有就记 WAIT。FD0_h1.4_* 平时是重作业（一次一个、旁边可有轻作业）；
        操作员文件 ~/mobo_toy_v2/DB_H14_EXCLUSIVE 存在、或 DB_H14_REF_OK 里写了 exclusive 一词（不论新旧，保守）→ 它们也像 REF_h1.4
        一样独占（同一条空队列规则，在飞时其他 db 提交暂停）；每轮读一次，模式（heavy / exclusive 与理由）在启动和变化时记一行与事件；
    按层慢启动（第二轮审查第 6 条）：SLOW_START_LAYERS（NZ-1、FD-0 h2.5、FD-0 h1.4、BD mesh、BD h2.0；REF 本来就串行，CD-0 是种子）
        里的一层，DONE 的行不到 2 个之前，该层在飞的行（NEW + READY + CLAIMED，保守起见也算 SOLVED：已解完、还没后处理）最多 2 个；
    按层失败闸门（审查第 2 条；规划 2.7 G1 / G3）：一层 FAILED ≥ 2 且失败率（FAILED / 已完成）> 5 %（种子与采纳的已有作业都算），或
        本批最先完成的 10 个喂料器自己提交的行（清单 dedup == "new"；种子、采纳的已有作业不进这个窗口）里 ≥ 3 行 FAILED（此时每一层都停）
        → 该层还没提交的行标 held（不提交），记 ERROR HOLD（附各 FAILED.json 的原因与放行文件）与事件；放行 = 在停下之后
        touch ~/mobo_toy_v2/DB_RELEASE_<层名，空格换成 _>（DB_RELEASE_CD-0、DB_RELEASE_FD-0_h2.5、DB_RELEASE_BD_mesh …）：held 行回到
        pending，当时的 FAILED 行记为已确认；之后同一层再有 ≥ 2 个新的 FAILED（且失败率仍 > 5 %）会再停，需要再 touch 一次。
        "最先 10 行"停下的层也可以一次放行：touch ~/mobo_toy_v2/DB_RELEASE_ALL 或 DB_RELEASE_<批次>（DB_RELEASE_b1）→ 每个因这条停下的层
        确认这一条；同时也因本层自己的失败停下的层仍然停着（只剩本层原因），要再 touch 它自己的 DB_RELEASE_<层>。
        DB_ACK_FAILED_<键> 接受的行在按层闸门里算已确认。有 held 行时喂料器不退出，等放行或 STOP；
    每 60 s 一轮；日志 logs/db_feed.log（UTC）：每次提交一行、没有提交时第 1 轮及之后每 WAIT_EVERY = 10 轮一行 WAIT（各原因的行数、
        占着重作业闸门的作业、参照及其状态、独占、操作员文件、慢启动、held 的层与放行文件、全队列最老的 READY 作业等了多久）；需要操作员的等待
        （DB_H14_REF_OK、独占）第一次出现时单独记一行；不论有没有待提交的行，每 HEARTBEAT_S = 600 s 一行 HEARTBEAT（本批在飞的行按状态、
        各状态计数、全队列最老的 READY 等了多久、全队列最近一次认领（CLAIMED 的 ctime）距今多久）；喂料器内任何未预料的异常记
        "ERROR crashed" + traceback 再抛出。
    读 spec.json / FAILED.json 遇到写了一半或坏的 JSON 不崩：该目录本轮按没有 spec 处理（算重作业、db_* 算未领取、算队列不空），
        记 WARNING；若它与某行同 hash8 → SystemExit（无法比对）。
    清单 results/db_manifest_<批次>.json（每行：键、id、预期 id、查重结果与途径、种子、状态、提交时刻与各标记文件 mtime，全部 UTC；
        gates：各层的 held / 原因 / 已确认的 FAILED / 放行记录；aux_md5；events）；重启幂等（读清单 + 队列；作业表的键或预期 id、
        code_hash、股骨几何键、aux md5 与清单不同 → 拒绝）；<root>/STOP_DB_FEED 存在 → 写清单后正常退出（启动时存在 → 拒绝启动）；
        同一时刻只能有一个喂料器（logs/db_feed.lock）。全部行 DONE / FAILED / blocked（没有 held、没有 pending）后退出（有 blocked → 退出码 3）。
默认（用户批准的规划 2.1）：空芯股骨记 femur_model_version 3406R_v1_hollowcore、hollow_core 真；网格变体全部带粘接、用同网格参照；
δ 与载荷是条件变量；求解端 3 槽 × 5 核不变（不归这里管）。
"""
from __future__ import annotations

import contextlib
import copy
import datetime
import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_deck as D  # noqa: E402   只读：D13_STS（起身载荷）、M_SLIP14（h 1.4 的 slip_tol）
import stage_neckopt as SN  # noqa: E402   只读：Phase(p).in_family、_axis_key

DB_CODE_HASH = "6d7af243d0"                 # 8 个哈希文件的代码哈希；变了 = 所有预期 id 都变，拒绝提交（规划 1.6 陷阱 1）
FEMUR_ID = "sawbone3406"
FEMUR_MODEL_VERSION = "3406R_v1_hollowcore"  # 规划 2.1：松质芯底按"空"建模；实物若是实心 / 换了几何 → 新 femur_id，这批留作另一个股骨版本
HOLLOW_CORE = True
REF_H2 = "sb_intact_h2_9c9d7fb5"             # 3406 完整股骨参照 h 2.0、楼梯载荷（= stage_neckopt.PHASES[11..14]["intact_job"]）
H_PROD = 2.0
DB_STAGES = ("db_ref", "db_sf", "db_cr", "db_crt", "db_cd", "db_nz", "db_fd", "db_bd", "db_bo", "db_al", "db_opt")   # 规划 1.6 + db_bo（只粘接补算）
CHECK_PHASES = (11, 12, 13, 14)
MAX_UNCLAIMED = 6
POLL_S = 60.0
DISK_MIN_GIB = 15.0                         # GiB（df -h 的单位）：每轮提交前
FIRST_START_MIN_GB = 30.0                   # GB（规划 G0 "≥ 30 GB"）：第一次启动（还没有清单）
FIRST_START_MIN_GIB = FIRST_START_MIN_GB * 1e9 / 2 ** 30     # = 27.94 GiB
HEAVY_MAX = 1
HEAVY_H = 1.4
STOP_NAME = "STOP_DB_FEED"
H14_OK_NAME = "DB_H14_REF_OK"               # 操作员文件：看过 h 1.4 参照 .dat 的内存估计后写，FD0_h1.4_* 才提交
RELEASE_PREFIX = "DB_RELEASE_"              # 操作员文件：DB_RELEASE_<层名，空格换成 _> 放行该层 held 的行
RELEASE_ALL = "ALL"                         # 操作员文件 DB_RELEASE_ALL（或 DB_RELEASE_<批次>）：放行每个因"最先 10 行"停下的层
ACK_FAILED_PREFIX = "DB_ACK_FAILED_"        # 操作员文件 DB_ACK_FAILED_<键>：接受该行查重到的 FAILED 作业（不重算，留洞）
H14_EXCL_NAME = "DB_H14_EXCLUSIVE"          # 操作员文件：FD0_h1.4_* 也独占（或 DB_H14_REF_OK 里写 exclusive 一词）
EXCLUSIVE = ("REF_h1.4",)                   # 独占：只在全队列空时提交；它在飞时其他 db 提交暂停
H14_LAYER = "FD-0 h1.4"                     # 这一层的行在 DB_H14_EXCLUSIVE 模式下也独占
REF_PRIORITY_CAP = 1                        # 参照优先期间其他未领取 db_* 的上限
GATE_MIN_FAILED = 2                         # 按层失败闸门：未确认的 FAILED ≥ 2 …
GATE_MAX_RATE = 0.05                        # … 且失败率 > 5 %
FIRST_N, FIRST_N_MAX_FAILED = 10, 2         # 本批最先完成的 10 个喂料器自己提交的行里 FAILED > 2 → 每层都停（规划 G1）
SLOW_START_LAYERS = ("NZ-1", "FD-0 h2.5", "FD-0 h1.4", "BD mesh", "BD h2.0")   # 新层慢启动（REF 串行、CD-0 是种子：不在内）
SLOW_START_CAP = 2                          # … DONE 不到 SLOW_START_DONE 行之前，该层在飞（NEW / READY / CLAIMED / SOLVED）最多 2 行
SLOW_START_DONE = 2
WAIT_EVERY = 10                             # 没有提交时：第 1 轮及之后每 10 轮记一行 WAIT
HEARTBEAT_S = 600.0                         # 不论有没有待提交的行：每 10 min 一行 HEARTBEAT
_mono = time.monotonic                      # HEARTBEAT 的计时（测试换成假时钟）
CODE_ROOT = HERE.parent                     # Linux：~/mobo_toy_v2/code
AUX_FILES = ("inp_writer.py", "v2/collar_rule.py", "v2/jobs.py", "v2/stability.py", "v2/femur_3406.py", "abaqus/odb_export.py")
_ALLOW_NON_LINUX = False                    # 只给测试：feed 默认只在 Linux 上跑

# 规格键分类：物理键进 spec（影响建模 / 求解 / 后处理）；角色键由本模块重写；元数据键丢掉。三者之外的键 → SystemExit
PHYS_KEYS = frozenset({"design", "h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "mu", "torque", "E_canc", "interference",
                       "lagrange", "cycles", "collar_rule", "femur_id", "neck_axis", "margin_check", "ref_cut_mm", "a_bounds_max", "cfg",
                       "entry_offset", "margin", "h_far", "bond_collar", "import_stem", "import_e", "export", "intact_substituted_h"})
ROLE_KEYS = frozenset({"kind", "bond_only", "fric_only", "intact_job"})
META_KEYS = frozenset({"created", "stage", "tag", "gate", "source_job", "load_case", "deck_code", "ofat", "jitter", "collar_w_original",
                       "keep_odb", "db_layer", "db_cond", "femur_model_version"})   # 后三个：主会话 CD-0 种子 spec 里的记录键（jobs.prep / post 不读）
ID_IGNORE = ("stage", "tag", "created")    # = jobs.job_id 不计入哈希的键（查重逐键比对时也去掉）

# ---------------------------------------------------------------- 批次 b1 的设计清单（规划 2.4 / 1.9；50 h 进展与角落核查里的代号）
CODES = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
         "D": "sb14_a26_96c5ab9b", "a62": "sb13_a62_1e4338ee", "init29": "sb13_init_2943f28a"}
# init 中位（h 2.5 先导的第 8 个设计）：阶段 13 状态文件 round 0 的记录里 ok 且有 rot_first_deg 的、去掉 init29，按 (rot_first_deg, job_id)
# 排序取下中位（下标 (n − 1) // 2；2026-10-25 22:12 UTC 的只读副本 n = 31 → 3.579°，= 规划 2.3 引的初始批转动中位 3.58°）。
# 钉死在这里；build 时按同一规则从 results/neckopt_p13.json 重算，不同 → SystemExit（状态文件变了）。
INIT_MEDIAN = "sb13_init_4bb091df"
INIT_MEDIAN_RULE = ("phase-13 state file, round-0 records that are ok with a rot_first_deg, excluding init29 (sb13_init_2943f28a), "
                    "sorted by (rot_first_deg, job_id); lower median = index (n - 1) // 2")
# 两臂里落在角落子盒、已有 h 2.0 结果的 16 个设计（修订 h25_pilot_design：子盒 124 个，按转动等距取秩，0.039–0.76°）。短名在队列里解析成
# 完整作业号（"<短名>_<8 位十六进制>" 必须恰有一个），再与修订脚本记下的完整作业号 PILOT16_PLAN 比对，不同 → SystemExit
PILOT16 = ("sb13_a82", "sb13_a103", "sb13_a70", "sb14_a63", "sb13_a90", "sb14_a48", "sb14_a25", "sb14_a74", "sb14_a41", "sb14_a37",
           "sb14_a38", "sb13_a56", "sb14_a58", "sb14_a17", "sb13_a44", "sb14_a70")
PILOT16_PLAN = ("sb13_a82_cd8c77ad", "sb13_a103_f429bcc9", "sb13_a70_1a523560", "sb14_a63_c051bbe6", "sb13_a90_a0ddbfd3", "sb14_a48_d2c4c39a",
                "sb14_a25_69b437e2", "sb14_a74_64bd6659", "sb14_a41_baf76af6", "sb14_a37_80b968d3", "sb14_a38_0f67e5a8", "sb13_a56_db729ce1",
                "sb14_a58_ac4b5e88", "sb14_a17_bae47d1d", "sb13_a44_a68d0a4f", "sb14_a70_fdb6e1e1")
REF_H = (1.94, 2.06, 2.5, 1.4)              # 参照的提交顺序：h 1.4 最后（独占，先看 .dat 的内存估计）
CD_DELTA_PAIR = (0.025, 0.20)
CD_PAIR_CODES = ("A", "B", "Bp", "C", "D", "a62")
CD_DELTA_ALL = 0.05
CD_ALL_CODES = ("A", "B", "Bp", "C", "D", "a62", "init29")
STS_CODES = ("B", "D", "a62", "init29")
STS_LOADS = D.D13_STS                       # {"F1714": {...}, "F3839": {...}}，与批次 D13 的起身载荷逐字相同
NZ_CODES = ("B", "Bp", "C", "D")
NZ_H = (1.94, 2.06)
FD25_CODES = ("A", "B", "Bp", "C", "D", "a62", "init29", "initmed")
FD14_CODES = ("A", "init29")
H14_SLIP_TOL = D.M_SLIP14
MESH_SOURCES = ("d13mesh_p13_a105_91e458e3_h1.94_1d526bc8", "d13mesh_p13_a105_91e458e3_h2.06_41dfb5ab",
                "d13mesh_p14_a36_1a865f38_h1.94_ae53ac39", "d13mesh_p14_a36_1a865f38_h2.06_bca417d1",
                "v3406_noise_smoke_h16_hint1.94_1de5bb9e", "v3406_noise_smoke_h16_hint2.06_73a2c8bf")
# v3406 噪声设计（L 35、截骨 16）的 h 2.0 只粘接：源 = 它 h 2.0 的只解摩擦孪生作业（物理 spec = 两个噪声网格源只改 h_int 2.0，build 核对）
NOISE_H2_PARTNER = True
NOISE_H2_SOURCE = "sb11_smoke_f_h16_898709ba"
NOISE_MESH = ("v3406_noise_smoke_h16_hint1.94_1de5bb9e", "v3406_noise_smoke_h16_hint2.06_73a2c8bf")
NOISE_H2_TAG = "v3406_noise_smoke_h16_hint2"
LAYER_SOURCE = {"REF": "intact_ref", "CD-0": "cond_anchor", "NZ-1": "noise", "FD-0 h2.5": "fid_h25", "FD-0 h1.4": "fid_h14",
                "BD mesh": "bond_partner", "BD h2.0": "bond_partner"}
BATCHES = ("b1",)
SEEDS = {"b1": ("db_seed_CD0.json",)}      # 主会话已提交的种子（results/ 下）：每个种子作业必须被本批一行 1:1 采纳；文件缺失 = 问题
if {L.replace(" ", "_") for L in LAYER_SOURCE} & {RELEASE_ALL, *BATCHES}:      # DB_RELEASE_ALL / DB_RELEASE_<批次> 不能与某层的放行文件同名
    raise RuntimeError("a layer slug equals a batch-wide release name")


# ================================================================ 小工具
def _utc(ts: float | None = None) -> str:
    return datetime.datetime.fromtimestamp(time.time() if ts is None else ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(x):
    """JSON 往返：与 jobs.job_id / spec.json 同一种数值表示（default=float），便于逐键比对。"""
    return json.loads(json.dumps(x, sort_keys=True, default=float))


def _core(spec: dict) -> dict:
    return _norm({k: v for k, v in spec.items() if k not in ID_IGNORE})


def expected_id(spec: dict) -> str:
    return J.job_id({**spec, "created": ""})


def _h8(name: str) -> str:
    return name.rsplit("_", 1)[-1]


def _flat(d: dict, pre: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and v:
            out.update(_flat(v, f"{pre}{k}."))
        else:
            out[pre + k] = v
    return out


def _fmt(v) -> str:
    if isinstance(v, str):
        return v
    return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else repr(v)


def variant_diff(src: dict | None, spec: dict) -> str:
    """相对源 spec.json 的差别：'键 旧 -> 新'（absent = 没有这个键；嵌套键写成 cfg.load.resultant_N）；只不比 created / stage / tag。"""
    if src is None:
        return "(no source spec)"
    a = _flat({k: v for k, v in _norm(src).items() if k not in ID_IGNORE})
    b = _flat({k: v for k, v in _norm(spec).items() if k not in ID_IGNORE})
    parts = []
    for k in sorted(set(a) | set(b)):
        if k not in b:
            parts.append(f"{k} {_fmt(a[k])} -> absent")
        elif k not in a:
            parts.append(f"{k} absent -> {_fmt(b[k])}")
        elif a[k] != b[k]:
            parts.append(f"{k} {_fmt(a[k])} -> {_fmt(b[k])}")
    return ", ".join(parts) or "(same as the source spec)"


def _phys_view(spec: dict) -> dict:
    """物理视图：去掉 META_KEYS 与 stage / tag / created，kind design / variant 并成 "design|variant"（jobs.prep / post / serve 对两者同一路径）。
    未分类的键留着（不同就不相同）。"""
    d = {k: v for k, v in spec.items() if k not in META_KEYS and k not in ID_IGNORE}
    if d.get("kind") in ("design", "variant"):
        d["kind"] = "design|variant"
    return _norm(d)


def phys_key(spec: dict) -> str:
    """物理键 = 物理视图的规范 JSON（sort_keys；数值表示照 spec.json：2 与 2.0 不同 → 不并，宁可重算）。"""
    return json.dumps(_phys_view(spec), sort_keys=True)


def phys_diff(a: dict, b: dict | None) -> list:
    """两个 spec 的物理视图逐键（嵌套键展开）比对：'键 a -> b'；空 = 同一物理计算。b 读不到 → 一条说明（不相同）。"""
    if b is None:
        return ["(no readable spec.json)"]
    x, y = _flat(_phys_view(a)), _flat(_phys_view(b))
    out = []
    for k in sorted(set(x) | set(y)):
        if k not in y:
            out.append(f"{k} {_fmt(x[k])} -> absent")
        elif k not in x:
            out.append(f"{k} absent -> {_fmt(y[k])}")
        elif json.dumps(x[k], sort_keys=True) != json.dumps(y[k], sort_keys=True):
            out.append(f"{k} {_fmt(x[k])} -> {_fmt(y[k])}")
    return out


def is_heavy(spec: dict | None) -> bool:
    """重作业：完整股骨参照（3406 h 2.0 时内存估计约 7 GB）与 h_int ≤ 1.4 的作业。spec 读不到 → 按重作业算（保守）。"""
    if spec is None:
        return True
    h = spec.get("h_int")
    return spec.get("kind") == "intact" or (isinstance(h, (int, float)) and float(h) <= HEAVY_H + 1e-9)


def needs_ref(spec: dict) -> bool:
    return spec.get("kind") != "intact" and not spec.get("fric_only")


def cond_id(spec: dict) -> str:
    """条件 id：δ | 载荷 | 界面网格 | slip_tol（参照：intact | 载荷 | 网格）。由 spec 算，不手写。"""
    def g(v):
        return "-" if v is None else f"{float(v):g}"
    L = (spec.get("cfg") or {}).get("load")
    load = "stair" if not L else f"R{g(L.get('resultant_N'))}_af{g(L.get('alpha_front_deg'))}_as{g(L.get('alpha_sagit_deg'))}"
    h = f"h{float(spec['h_int']):g}"
    if spec.get("kind") == "intact":
        return f"intact|{load}|{h}"
    return f"d{float(spec['delta']):g}|{load}|{h}|slip{float(spec['slip_tol']):g}"


def model_set(spec: dict) -> str:
    if spec.get("kind") == "intact":
        return "intact"
    return "bond" if spec.get("bond_only") else ("fric" if spec.get("fric_only") else "fric+bond")


def layer_slug(layer: str) -> str:
    """层名 → 文件名用的记号（DB_RELEASE_<记号>）：空格换成 _（"FD-0 h2.5" → "FD-0_h2.5"）。"""
    return layer.replace(" ", "_")


def disk_free_gib(path: pathlib.Path | None = None) -> float:
    return shutil.disk_usage(str(path or J.QROOT)).free / 2 ** 30


_SHA_CACHE: dict = {}


def _sha256_file(p: pathlib.Path) -> str:
    """文件 sha256；按 (路径, 大小, mtime_ns) 缓存（喂料器每轮都核对股骨几何键，不必每分钟重读 28 MB 的 STEP）。"""
    st = p.stat()
    k = (str(p), st.st_size, st.st_mtime_ns)
    if k not in _SHA_CACHE:
        _SHA_CACHE[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    return _SHA_CACHE[k]


def femur_geom_key() -> dict:
    """股骨几何键 = femur_3406.py 与它装进 cfg 的两个 STEP（皮质、松质 v2）的 sha256（规划 1.6 陷阱 3：股骨几何不进作业 id）。
    文件缺失 → SystemExit。"""
    import femur_3406 as F3
    fc = F3.load_cfg()["femur"]
    files = {"femur_3406.py": HERE / "femur_3406.py", "step_cortical": pathlib.Path(fc["step_cortical"]),
             "step_cancellous": pathlib.Path(fc["step_cancellous"])}
    out = {}
    for k, p in files.items():
        if not p.exists():
            raise SystemExit(f"femur geometry key: {k} file {p} is missing")
        out[k] = {"path": p.name, "sha256": _sha256_file(p)}
    h = hashlib.sha256("".join(f"{k}:{v['sha256']}\n" for k, v in sorted(out.items())).encode()).hexdigest()[:16]
    return {"key": h, "files": out}


def aux_md5() -> dict:
    """AUX_FILES（相对 CODE_ROOT）的 md5；本机没有这个文件 → None（例如 abaqus/odb_export.py 只在 Windows 求解端）。"""
    out = {}
    for rel in AUX_FILES:
        p = CODE_ROOT / rel
        out[rel] = hashlib.md5(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


def aux_changes(old: dict, new: dict) -> list:
    return [f"{k}: {old.get(k) or 'absent'} -> {new.get(k) or 'absent'}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]


# ================================================================ 队列只读
def _read_json(p: pathlib.Path):
    """读 JSON 文件 → (对象, None)；文件不存在 → (None, None)；读不了 / 坏的 JSON（写了一半）→ (None, 原因)。不抛异常。"""
    try:
        return json.loads(p.read_text()), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:              # ValueError 包括 json.JSONDecodeError 与 UnicodeDecodeError
        return None, f"{type(e).__name__}: {e}"


def _read_spec(p: pathlib.Path):
    sp, err = _read_json(p)
    if sp is None and err is None and p.exists():
        return None, "spec.json holds JSON null"
    if sp is not None and not isinstance(sp, dict):
        return None, f"spec.json holds a JSON {type(sp).__name__}, not an object"
    return sp, err


def scan_queue(bad: list | None = None) -> dict:
    """队列里每个目录 → 它的 spec.json（没有或读不了 → None；读不了的目录名与原因追加到 bad）。build 时读一次。"""
    if not J.QROOT.is_dir():
        raise SystemExit(f"queue {J.QROOT} does not exist")
    out = {}
    for e in os.scandir(J.QROOT):
        if e.is_dir():
            sp, err = _read_spec(pathlib.Path(e.path) / "spec.json")
            out[e.name] = sp
            if err:
                if bad is None:
                    raise SystemExit(f"queue dir {e.name}: unreadable spec.json ({err})")
                bad.append(f"{e.name} ({err})")
    return out


def _by_h8(names) -> dict:
    out = {}
    for n in names:
        out.setdefault(_h8(n), []).append(n)
    return out


def _spec_of(name: str, qspecs: dict | None = None) -> dict | None:
    """作业的 spec.json；没有或读不了 → None（调用方都按"不能比对"保守处理：拒绝或等待）。"""
    if qspecs is not None and name in qspecs:
        return qspecs[name]
    return _read_spec(J.QROOT / name / "spec.json")[0]


_STATE_RANK = {"DONE": 0, "SOLVED": 1, "CLAIMED": 2, "READY": 3, "NEW": 4, "FAILED": 5}


def _pick(names: list) -> str:
    return sorted(names, key=lambda n: (_STATE_RANK.get(J.state(J.QROOT / n), 9), n))[0]


def resolve(spec: dict, by_h8: dict, qspecs: dict | None = None, by_phys: dict | None = None) -> tuple[str, str, list, str | None]:
    """查重（规划 1.6；模块说明"查重"）。返回 (id, status, hits, via)：status "new"（队列里没有）| "queued"（预期 id 的目录已在，
    = 已提交过）| "existing"（同一物理计算在别的作业下已有，记它的 id，不再提交）；via "hash8" | "physics" | None。
    hash8 相同而 spec 不同（碰撞）或同一 hash8 的目录没有可读的 spec.json → SystemExit。by_phys：物理键 → 目录名（None = 不查物理键）。"""
    eid = expected_id(spec)
    hits = sorted(by_h8.get(_h8(eid), []))
    same, bad = [], []
    want = _core(spec)
    for n in hits:
        sp = _spec_of(n, qspecs)
        if sp is None:
            raise SystemExit(f"dedup: queue dir {n} shares hash8 {_h8(eid)} with {eid} but has no readable spec.json (being created, damaged "
                             "or partly written); cannot compare, refusing")
        (same if _core(sp) == want else bad).append(n)
    if bad:
        raise SystemExit(f"dedup: hash8 collision: {eid} and existing job(s) {bad} share hash8 {_h8(eid)} but their specs differ "
                         "(minus stage / tag / created); refusing (a hash8 hit alone would silently reuse the wrong result)")
    if eid in same:
        return eid, "queued", hits, "hash8"
    if same:
        return _pick(same), "existing", hits, "hash8"
    if by_phys is not None:
        cands = sorted(n for n in by_phys.get(phys_key(spec), []) if n != eid)
        conf = [n for n in cands if not phys_diff(spec, _spec_of(n, qspecs))]       # 逐键再比一次（物理键相同 ⇒ 应为空）
        if conf:
            return _pick(conf), "existing", sorted(set(hits) | set(conf)), "physics"
    return eid, "new", hits, None


# ================================================================ 源作业与 spec 构造
def _phys(src: dict, job: str) -> dict:
    unknown = sorted(set(src) - PHYS_KEYS - ROLE_KEYS - META_KEYS)
    if unknown:
        raise SystemExit(f"source {job}: spec keys {unknown} are not classified in stage_db (PHYS_KEYS / ROLE_KEYS / META_KEYS); "
                         "classify them before copying this spec (an unknown key may change the result)")
    return copy.deepcopy({k: src[k] for k in src if k in PHYS_KEYS})


def load_source(job: str, expect: str, qspecs: dict | None = None) -> dict:
    """源作业的 spec.json（必须 DONE）。expect：design = 阶段 13 / 14 的基线设计作业（kind design、stage sb13 / sb14、在阶段 13 的族里：
    δ 0.10、h 2.0、楼梯、3406）；mesh = 只解摩擦的网格变体（kind variant、fric_only、3406、h_int ≠ 2.0）；intact = 3406 h 2.0 楼梯参照；
    h2twin = 只解摩擦的 3406 h 2.0 作业（kind design / variant、没有 cfg）。"""
    d = J.QROOT / job
    src = _spec_of(job, qspecs)
    if src is None:
        raise SystemExit(f"source {job}: no readable spec.json under {J.QROOT}")
    st = J.state(d)
    if st != "DONE":
        raise SystemExit(f"source {job} is {st}, not DONE")
    why = []
    if expect == "design":
        if src.get("kind") != "design" or str(src.get("stage")) not in ("sb13", "sb14"):
            why.append(f"kind {src.get('kind')!r} stage {src.get('stage')!r} (want a phase 13 / 14 design job)")
        elif not SN.Phase(13).in_family(src):
            why.append("not in the phase 13 / 14 family (not a baseline row: delta 0.10, h 2.0, stair, 3406)")
    elif expect == "mesh":
        if src.get("kind") != "variant" or not src.get("fric_only") or src.get("femur_id") != FEMUR_ID or src.get("h_int") == H_PROD:
            why.append(f"kind {src.get('kind')!r} fric_only {src.get('fric_only')!r} femur_id {src.get('femur_id')!r} h_int {src.get('h_int')!r} "
                       "(want a fric_only 3406 mesh variant)")
    elif expect == "h2twin":
        if src.get("kind") not in ("design", "variant") or not src.get("fric_only") or src.get("femur_id") != FEMUR_ID \
                or src.get("h_int") != H_PROD or src.get("cfg"):
            why.append(f"kind {src.get('kind')!r} fric_only {src.get('fric_only')!r} femur_id {src.get('femur_id')!r} h_int {src.get('h_int')!r} "
                       f"cfg {src.get('cfg')!r} (want a fric_only 3406 h 2.0 stair job)")
    elif expect == "intact":
        if src.get("kind") != "intact" or src.get("femur_id") != FEMUR_ID or src.get("h_int") != H_PROD or src.get("cfg"):
            why.append("not the 3406 h 2.0 stair intact reference")
    else:
        raise ValueError(expect)
    if why:
        raise SystemExit(f"source {job}: " + "; ".join(why))
    return src


def _tag_of(job: str) -> str:
    """sb13_a62_1e4338ee → p13_a62_1e4338ee（同 stage_deck._d13_tag）；其他源作业名去掉末尾的 hash8。"""
    stage, rest = job.split("_", 1)
    if stage in ("sb13", "sb14"):
        return f"p{stage[2:]}_{rest}"
    return job.rsplit("_", 1)[0]


def _variant(phys: dict, stage: str, tag: str, mode: str, intact_job: str | None = None, **changes) -> dict:
    s = {**copy.deepcopy(phys), **copy.deepcopy(changes), "kind": "variant", "stage": stage, "tag": tag}
    if mode == "fric":
        s["fric_only"] = True
    elif mode == "bond":
        s["bond_only"] = True
        s["intact_job"] = intact_job
    elif mode == "full":
        s["intact_job"] = intact_job
    else:
        raise ValueError(mode)
    return s


def resolve_pilot16(qspecs: dict) -> list:
    full = []
    for s in PILOT16:
        hits = sorted(n for n in qspecs if n.startswith(s + "_") and len(n) == len(s) + 9
                      and all(c in "0123456789abcdef" for c in n[-8:]))
        if len(hits) != 1:
            raise SystemExit(f"pilot design {s}: {len(hits)} queue jobs match {s}_<hash8> ({hits}); need exactly one")
        full.append(hits[0])
    if tuple(full) != PILOT16_PLAN:
        raise SystemExit(f"pilot designs resolved from the queue {full} differ from the plan's picked16_job_ids {list(PILOT16_PLAN)}")
    return full


def _state_file(p: int) -> dict:
    f = J.RESULTS / f"neckopt_p{p}.json"
    if not f.exists():
        raise SystemExit(f"{f} missing (needed for the init-median rule and the record fields)")
    st, err = _read_json(f)
    if st is None:
        raise SystemExit(f"{f} unreadable ({err})")
    if st.get("phase") != p:
        raise SystemExit(f"{f} holds phase {st.get('phase')!r}, expected {p}")
    return st


def init_median_pick(st13: dict) -> dict:
    rows = sorted([r for r in st13["records"] if r.get("round") == 0 and r.get("ok") and r.get("rot_first_deg") is not None
                   and r["job_id"] != CODES["init29"]], key=lambda r: (float(r["rot_first_deg"]), r["job_id"]))
    if not rows:
        raise SystemExit("init median: no ok round-0 record with a rotation in the phase-13 state file")
    return rows[(len(rows) - 1) // 2]


def _ident(spec: dict) -> str:
    return json.dumps({k: v for k, v in spec.items() if k in PHYS_KEYS}, sort_keys=True, default=float)


def usable_bonded_h2(src: dict, qspecs: dict, warn: list, idents: dict | None = None) -> list:
    """队列里（不含 db_*）该设计 h 2.0 的可用粘接结果（定义见模块说明 BD (ii)）。DONE 却没有 result.json → SystemExit。
    idents：预先算好的 {目录名: _ident(spec)}（build 只算一次）。"""
    ident, out = _ident(src), []
    for name in sorted(qspecs):
        sp = qspecs[name]
        if sp is None or name.startswith("db_") or sp.get("kind") not in ("design", "variant") or sp.get("fric_only"):
            continue
        if (idents[name] if idents is not None else _ident(sp)) != ident or sp.get("intact_job") != REF_H2:
            continue
        extra = sorted(set(sp) - PHYS_KEYS - ROLE_KEYS - META_KEYS)
        if extra:
            warn.append(f"{name}: same physical spec as a pilot design but unclassified keys {extra}; not counted as a usable bonded result")
            continue
        d = J.QROOT / name
        if J.state(d) != "DONE":
            continue
        rp = d / "result.json"
        if not rp.exists():
            raise SystemExit(f"{name} is DONE but has no result.json (needed to decide the h 2.0 bond_only partners)")
        r, err = _read_json(rp)
        if r is None:
            raise SystemExit(f"{name}: result.json unreadable ({err}); needed to decide the h 2.0 bond_only partners")
        if all(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) and math.isfinite(r[k]) for k in ("vm_p99", "f2_g7_loss_pct")):
            out.append(name)
        else:
            warn.append(f"{name}: bonded DONE but vm_p99 / f2_g7_loss_pct missing; not counted as a usable bonded result")
    return out


def _row(key, layer, spec, source_job, code=None, ref_key=None, extra=None) -> dict:
    return {"key": key, "layer": layer, "stage": spec["stage"], "source": LAYER_SOURCE[layer],
            "selection": "reference" if layer == "REF" else "stratum", "design_code": code, "source_job": source_job,
            "condition_id": cond_id(spec), "bonded": model_set(spec) in ("fric+bond", "bond"), "model_set": model_set(spec),
            "intact_job": spec.get("intact_job"), "ref_key": ref_key, "heavy": is_heavy(spec), "exclusive": key in EXCLUSIVE,
            "femur_model_version": FEMUR_MODEL_VERSION, "hollow_core": HOLLOW_CORE, "seed": None, "spec": spec, **(extra or {})}


def seed_row_key(sk: str) -> str:
    """种子文件的键 → 本批的键：CD0_delta0.025_A → CD0_d0.025_A；CD0_sts_F1714_B → CD0_sts1714_B。认不出 → ValueError。"""
    if sk.startswith("CD0_delta"):
        dl, code = sk[len("CD0_delta"):].split("_", 1)
        return f"CD0_d{float(dl):g}_{code}"
    if sk.startswith("CD0_sts_F"):
        ln, code = sk[len("CD0_sts_F"):].split("_", 1)
        return f"CD0_sts{ln}_{code}"
    raise ValueError(f"seed key {sk!r}: no row-key mapping")


def check_seeds(batch: str, rows: list, qspecs: dict) -> tuple[list, list]:
    """种子采纳核对（模块说明"种子采纳"）。返回 (每个种子文件的信息, 问题)；通过的行记 r["seed"] = 文件名。"""
    by_key = {r["key"]: r for r in rows}
    info, probs = [], []
    for fn in SEEDS.get(batch, ()):
        p = J.RESULTS / fn
        if not p.exists():
            info.append({"file": fn, "present": False})
            probs.append(f"declared seed file {p} (SEEDS[{batch!r}]) is missing: the 1:1 adoption of its seed jobs cannot be checked "
                         "(restore it; to skip the check remove it from SEEDS explicitly)")
            continue
        sd, err = _read_json(p)
        if not isinstance(sd, dict):
            probs.append(f"seed file {p} unreadable ({err or 'not a JSON object'})")
            continue
        if sd.get("code_hash") != DB_CODE_HASH:
            probs.append(f"seed file {fn}: code_hash {sd.get('code_hash')!r} != {DB_CODE_HASH}")
        adopted, used = {}, {}
        for sk, sid in (sd.get("jobs") or {}).items():
            try:
                rk = seed_row_key(sk)
            except ValueError as e:
                probs.append(f"seed file {fn}: {e}")
                continue
            r = by_key.get(rk)
            if r is None:
                probs.append(f"seed file {fn}: {sk} -> {rk} is not a row of batch {batch}")
                continue
            if rk in adopted or sid in used:
                probs.append(f"seed file {fn}: {sk} ({sid}) is not 1:1 (row {rk} or job {sid} already taken by {used.get(sid)})")
                continue
            qsp = qspecs.get(sid)
            if qsp is None:
                probs.append(f"seed file {fn}: {sk} job {sid} has no readable spec.json in the queue")
                continue
            fsp = (sd.get("specs") or {}).get(sk)
            if fsp is None or _core(fsp) != _core(qsp):
                probs.append(f"seed file {fn}: {sk}: the spec in the seed file {'is missing' if fsp is None else 'differs from'} "
                             f"the queue's spec.json of {sid}")
            if r["dedup"] != "existing" or r["id"] != sid:
                probs.append(f"seed file {fn}: {sk} ({sid}) is not adopted by row {rk} (dedup {r['dedup']} -> {r['id']}; "
                             f"physics diff row -> seed: {phys_diff(r['spec'], qsp) or 'none'})")
                continue
            r["seed"] = fn
            adopted[rk] = sid
            used[sid] = rk
        info.append({"file": fn, "present": True, "submitted_utc": sd.get("submitted_utc"), "n_jobs": len(sd.get("jobs") or {}),
                     "adopted": adopted})
    return info, probs


def ack_failed_file(key: str) -> pathlib.Path:
    return J.QROOT.parent / f"{ACK_FAILED_PREFIX}{key}"


def hit_checks(key: str, jid: str, sp: dict | None, recorded: bool = False) -> tuple[list, list, dict | None]:
    """一行查重命中队列里已有的作业 jid（existing / queued，hash8 或物理键）时的核对；build 与 feed 时对活队列再查重都用它（模块说明）。
    jid 的 femur_model_version 不是本模块的 → 问题；jid FAILED → 问题，除非 DB_ACK_FAILED_<键> 存在（接受：返回 ack 记录）或
    recorded（清单已把该行记成 jid：之前某次启动时采纳 / 提交的，FAILED 是该层一个普通的结果）。返回 (问题, 说明, ack)。"""
    probs, notes, ack = [], [], None
    fmv = (sp or {}).get("femur_model_version")
    if fmv is not None and fmv != FEMUR_MODEL_VERSION:
        probs.append(f"{key}: existing job {jid} carries femur_model_version {fmv!r} != {FEMUR_MODEL_VERSION!r}")
    if J.state(J.QROOT / jid) == "FAILED":
        f = ack_failed_file(key)
        try:
            mt = f.stat().st_mtime
        except FileNotFoundError:
            mt = None
        if recorded:
            notes.append(f"{key}: job {jid} is FAILED ({_fail_reason(jid)}); the manifest already records this row as that job (resolved at an "
                         "earlier feeder start), so it is an ordinary FAILED row of its layer (layer gate)")
        elif mt is not None:
            ack = {"file": str(f), "mtime_utc": _utc(mt)}
            notes.append(f"{key}: resolves to existing job {jid}, which is FAILED ({_fail_reason(jid)}); accepted by the operator file {f} "
                         f"({_utc(mt)}): not computed again, acknowledged in the layer gate")
        else:
            probs.append(f"{key}: resolves to existing job {jid}, which is FAILED ({_fail_reason(jid)}); same physics = this row would never be "
                         f"computed (a permanent hole). Check the failure; to accept it as this row's result touch {f}")
    return probs, notes, ack


def recorded_ids(batch: str) -> tuple[dict, str | None]:
    """清单（只读）里已记成 submitted / existing 的行 → 它的作业号（还没有清单 → {}）。读不了 → ({}, 说明；feed 的 open_manifest 会拒绝)。"""
    p = manifest_path(batch)
    man, err = _read_json(p)
    if man is None and err is None:
        return {}, None
    if not isinstance(man, dict) or not isinstance(man.get("rows"), dict):
        return {}, (f"manifest {p} unreadable ({err or 'not a JSON object with rows'}): rows resolving to FAILED jobs are judged as if no "
                    "feeder had started (feed refuses a damaged manifest)")
    return {k: m.get("id") for k, m in man["rows"].items() if isinstance(m, dict) and m.get("status") in ("submitted", "existing")}, None


def build(batch: str = "b1") -> dict:
    """批次的作业表（有序）+ 查重（hash8 + 物理键）+ 种子采纳 + 检查。读一次队列（全部 spec.json）与阶段 13 / 14 状态文件，不写任何东西。
    结构性问题（源作业缺失 / 没 DONE / 未分类的键 / 查重碰撞 / 批内重复 id）→ SystemExit；逐行检查与种子的问题收进 problems。"""
    if batch not in BATCHES:
        raise SystemExit(f"unknown batch {batch!r} (known: {list(BATCHES)})")
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    st13, st14 = _state_file(13), _state_file(14)
    rec = {r["job_id"]: r for st in (st13, st14) for r in st["records"]}
    warn = []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    med = init_median_pick(st13)
    if med["job_id"] != INIT_MEDIAN:
        raise SystemExit(f"init median: the rule picks {med['job_id']} ({med['rot_first_deg']:.4f} deg) but INIT_MEDIAN is {INIT_MEDIAN}; "
                         "the phase-13 state file changed")
    pilot16 = resolve_pilot16(qspecs)
    jobs_of = {**CODES, "initmed": INIT_MEDIAN, **dict(zip(PILOT16, pilot16))}      # 设计代号（两臂的 16 个用短名）→ 源作业
    src = {c: load_source(j, "design", qspecs) for c, j in jobs_of.items()}
    phys = {c: _phys(s, jobs_of[c]) for c, s in src.items()}
    rows = []

    def info(c):
        r = rec.get(jobs_of[c]) or {}
        return {"pool_idx": r.get("pool_idx"), "rot_first_deg_h2": r.get("rot_first_deg")}

    # REF：sb_intact_h2_9c9d7fb5 的 spec 只改 h_int
    ref_src = load_source(REF_H2, "intact", qspecs)
    ref_phys = _phys(ref_src, REF_H2)
    ref_id, ref_key_of = {H_PROD: REF_H2}, {}
    for h in REF_H:
        spec = {**copy.deepcopy(ref_phys), "kind": "intact", "h_int": h, "stage": "db_ref", "tag": f"intact_h{h:g}"}
        k = f"REF_h{h:g}"
        rows.append(_row(k, "REF", spec, REF_H2))
        ref_id[h] = resolve(spec, by_h8, qspecs, by_phys)[0]
        ref_key_of[h] = k
    # CD-0 δ（只解摩擦）
    for c in CD_PAIR_CODES:
        for dl in CD_DELTA_PAIR:
            spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_d{dl:g}", "fric", delta=dl)
            rows.append(_row(f"CD0_d{dl:g}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    for c in CD_ALL_CODES:
        spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_d{CD_DELTA_ALL:g}", "fric", delta=CD_DELTA_ALL)
        rows.append(_row(f"CD0_d{CD_DELTA_ALL:g}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    # CD-0 起身（只解摩擦；cfg.load = stage_deck.D13_STS 原样）
    for c in STS_CODES:
        for ln, L in STS_LOADS.items():
            spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_{ln}", "fric", cfg={"load": dict(L)})
            rows.append(_row(f"CD0_sts{ln[1:]}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    # NZ-1（带粘接，同网格参照）
    for c in NZ_CODES:
        for h in NZ_H:
            spec = _variant(phys[c], "db_nz", f"{_tag_of(jobs_of[c])}_h{h:g}", "full", intact_job=ref_id[h], h_int=h)
            rows.append(_row(f"NZ1_h{h:g}_{c}", "NZ-1", spec, jobs_of[c], c, ref_key=ref_key_of[h], extra=info(c)))
    # FD-0 h 2.5 先导（24）与 h 1.4（2），带粘接
    fd25 = list(FD25_CODES) + list(PILOT16)
    for c in fd25:
        spec = _variant(phys[c], "db_fd", f"{_tag_of(jobs_of[c])}_h2.5", "full", intact_job=ref_id[2.5], h_int=2.5)
        rows.append(_row(f"FD0_h2.5_{c}", "FD-0 h2.5", spec, jobs_of[c], c, ref_key=ref_key_of[2.5], extra=info(c)))
    for c in FD14_CODES:
        spec = _variant(phys[c], "db_fd", f"{_tag_of(jobs_of[c])}_h1.4", "full", intact_job=ref_id[1.4], h_int=1.4, slip_tol=H14_SLIP_TOL)
        rows.append(_row(f"FD0_h1.4_{c}", "FD-0 h1.4", spec, jobs_of[c], c, ref_key=ref_key_of[1.4], extra=info(c)))
    # BD (i)：现有只解摩擦的网格变体的同网格 bond_only（stage db_bo）
    others = sorted(n for n, sp in qspecs.items() if sp and not n.startswith("db_") and sp.get("femur_id") == FEMUR_ID and sp.get("fric_only")
                    and sp.get("kind") in ("design", "variant") and sp.get("h_int") != H_PROD and n not in MESH_SOURCES)
    if others:
        warn.append(f"fric_only 3406 mesh variants in the queue that MESH_SOURCES does not cover (no bond_only partner in this batch): {others}")
    for j in MESH_SOURCES:
        s_ = load_source(j, "mesh", qspecs)
        h = float(s_["h_int"])
        if h not in ref_id:
            raise SystemExit(f"mesh source {j}: h_int {h:g} has no db_ref in this batch (REF_H {REF_H})")
        spec = _variant(_phys(s_, j), "db_bo", _tag_of(j), "bond", intact_job=ref_id[h])
        rows.append(_row(f"BD_mesh_{_tag_of(j)}", "BD mesh", spec, j, None, ref_key=ref_key_of[h], extra={"partner_of": j}))
    # BD (i')：v3406 噪声设计的 h 2.0 bond_only（源 = h 2.0 只解摩擦孪生；物理 spec 必须 = 两个噪声网格源只改 h_int）
    if NOISE_H2_PARTNER:
        tw = load_source(NOISE_H2_SOURCE, "h2twin", qspecs)
        tw_phys = _phys(tw, NOISE_H2_SOURCE)
        for j in NOISE_MESH:
            mp_ = {**_phys(load_source(j, "mesh", qspecs), j), "h_int": H_PROD}
            if _norm(mp_) != _norm(tw_phys):
                raise SystemExit(f"noise h 2.0 partner: {NOISE_H2_SOURCE} is not the h 2.0 twin of {j} "
                                 f"(physical keys differ: {variant_diff(mp_, tw_phys)})")
        spec = _variant(tw_phys, "db_bo", NOISE_H2_TAG, "bond", intact_job=REF_H2)
        rows.append(_row(f"BD_mesh_{NOISE_H2_TAG}", "BD mesh", spec, NOISE_H2_SOURCE, None, extra={"partner_of": NOISE_H2_SOURCE}))
    # BD (ii)：先导设计 h 2.0 一侧没有可用粘接结果的 → h 2.0 bond_only（参照 sb_intact_h2_9c9d7fb5）
    partner_info = {}
    idents = {n: _ident(sp) for n, sp in qspecs.items() if sp is not None}
    for c in fd25:
        have = usable_bonded_h2(src[c], qspecs, warn, idents)
        partner_info[c] = have
        if not have:
            spec = _variant(phys[c], "db_bo", f"{_tag_of(jobs_of[c])}_h2", "bond", intact_job=REF_H2)
            rows.append(_row(f"BD_h2_{c}", "BD h2.0", spec, jobs_of[c], c, extra={**info(c), "partner_of": jobs_of[c]}))
    # 查重（每行：hash8 + 物理键）+ 批内重复
    seen = {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch {batch}: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']} (same physical spec twice)")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs)
    taken = {}
    for r in rows:
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch {batch}: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
    refs_in_batch = {r["id"]: r["spec"] for r in rows if r["layer"] == "REF"}
    problems = []
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids(batch)
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: refs_in_batch.get(j) or _spec_of(j, qspecs), h14_ref=ref_id[1.4])]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds(batch, rows, qspecs)
    problems += seed_probs
    ids = {r["id"] for r in rows} | {r["expected_id"] for r in rows}
    stray = sorted(n for n in qspecs if n.startswith("db_") and n not in ids)
    if stray:
        warn.append(f"db_* queue dirs that are not rows of batch {batch}: {stray}")
    n_partner = sum(r["layer"] == "BD h2.0" for r in rows)
    return {"batch": batch, "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(), "init_median": med,
            "pilot16": pilot16, "ref_id": {f"{h:g}": v for h, v in ref_id.items()}, "partners": partner_info, "n_partner": n_partner,
            "seeds": seeds, "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


# ================================================================ 检查
def ref_mismatch(spec: dict, ref: dict | None) -> list:
    """参照核对（规划 1.6 陷阱 4；jobs.explicit_ref 只比 femur_id）：kind intact，femur_id、h_int、E_canc、h_far、neck_axis、cfg.load 都相同；
    cfg 里 load 以外的键还没有规则 → 也算不匹配。"""
    if ref is None:
        return ["intact reference spec not found"]
    out = []
    if ref.get("kind") != "intact":
        out.append(f"reference kind {ref.get('kind')!r} != 'intact'")
    for k in ("femur_id", "h_int", "E_canc", "h_far"):
        if ref.get(k) != spec.get(k):
            out.append(f"{k}: job {spec.get(k)!r} != reference {ref.get(k)!r}")
    if SN._axis_key(ref.get("neck_axis")) != SN._axis_key(spec.get("neck_axis")):
        out.append(f"neck_axis: job {spec.get('neck_axis')!r} != reference {ref.get('neck_axis')!r}")
    jl, rl = (spec.get("cfg") or {}).get("load"), (ref.get("cfg") or {}).get("load")
    if _norm(jl) != _norm(rl):
        out.append(f"cfg.load: job {jl or 'stair (no cfg)'} != reference {rl or 'stair (no cfg)'}")
    xk = sorted((set(spec.get("cfg") or {}) | set(ref.get("cfg") or {})) - {"load"})
    if xk:
        out.append(f"cfg keys {xk} besides load: no reference-matching rule for them")
    return out


def row_problems(row: dict, ref_spec_of, h14_ref: str | None = None) -> list:
    """一行的检查（规划 1.6、1.8 第 13 / 14 条）；返回问题列表，空 = 通过。ref_spec_of(job_id) → 参照的 spec 或 None。"""
    s = row["spec"]
    st = str(s.get("stage", ""))
    p = []
    if not st.startswith("db_") or st not in DB_STAGES:
        p.append(f"stage {st!r} is not a database stage {DB_STAGES}")
    if st.startswith(("sb", "neck")) or st == "ref":
        p.append(f"stage {st!r} starts with sb / neck or is 'ref' (optimisation / CT-reference namespaces)")
    for jid in {row.get("expected_id") or expected_id(s), row.get("id") or expected_id(s)}:
        if jid.startswith(("sb13_", "sb14_")):
            p.append(f"job id {jid} starts with sb13_ / sb14_ (the arms' adoption globs)")
    fam = [ph for ph in CHECK_PHASES if SN.Phase(ph).in_family(s)]
    if fam:
        p.append(f"in the optimisation family of phase(s) {fam}")
    kind = s.get("kind")
    if st == "db_ref":
        if kind != "intact":
            p.append(f"db_ref row has kind {kind!r}")
    elif kind != "variant":
        p.append(f"kind {kind!r} != 'variant'")
    if kind == "variant":
        if s.get("model") != "m1":
            p.append(f"model {s.get('model')!r} != 'm1'")
        if s.get("fric_only") and s.get("bond_only"):
            p.append("fric_only and bond_only both set")
        if s.get("fric_only") and "intact_job" in s:
            p.append("fric_only with an intact_job")
        if needs_ref(s) and not s.get("intact_job"):
            p.append("bonded / bond_only without intact_job")
        if s.get("h_int") != H_PROD and s.get("fric_only"):
            p.append(f"mesh variant h_int {s.get('h_int')} solved friction-only (10-23 rule: mesh variants carry the bond model)")
    if needs_ref(s) and s.get("intact_job"):
        ref = ref_spec_of(s["intact_job"])
        p += [f"intact_job {s['intact_job']}: {m}" for m in ref_mismatch(s, ref)]
        if s.get("h_int") != H_PROD and ref is not None and ref.get("stage") != "db_ref":
            p.append(f"mesh variant h_int {s.get('h_int')} references {s['intact_job']} (stage {ref.get('stage')!r}), not a db_ref of its own mesh")
    h = s.get("h_int")
    if kind != "intact" and isinstance(h, (int, float)) and float(h) <= HEAVY_H + 1e-9 and not h14_ref:
        p.append("h 1.4 row without an h 1.4 reference in the batch")
    return p


def check_disk(free_gib: float) -> None:
    if not (free_gib >= DISK_MIN_GIB):
        raise SystemExit(f"disk gate: {free_gib:.1f} GiB free on the queue filesystem < {DISK_MIN_GIB:g} GiB; refusing to submit")


def check_first_start_disk(free_gib: float) -> None:
    if not (free_gib >= FIRST_START_MIN_GIB):
        raise SystemExit(f"first start: {free_gib:.1f} GiB free on the queue filesystem < {FIRST_START_MIN_GB:g} GB "
                         f"({FIRST_START_MIN_GIB:.1f} GiB, plan G0); refusing to start the batch")


def check_code() -> None:
    ch = J.code_hash()
    if ch != DB_CODE_HASH:
        raise SystemExit(f"code_hash {ch} != {DB_CODE_HASH}: one of the 8 hashed files changed, every expected id would change; refusing")


# ================================================================ dry run
def dry_run(batch: str = "b1") -> int:
    """只打印，不写任何文件（不建作业目录、不写清单、不写日志）。返回退出码：0 = 没有问题，1 = 有问题（列在 PROBLEMS）。"""
    b = build(batch)
    gk = femur_geom_key()
    aux = aux_md5()
    rows = b["rows"]
    try:
        free = disk_free_gib()
    except OSError as e:                                                  # noqa: PERF203
        free = float("nan")
        b["warnings"].append(f"disk usage of {J.QROOT} unreadable: {e}")
    print(f"dry run: batch {batch}; nothing written (no job directories, no manifest, no log)")
    print(f"queue {J.QROOT} ({b['n_queue_dirs']} dirs); results {J.RESULTS}; code_hash {b['code_hash']} (required {DB_CODE_HASH}); "
          f"femur_geom_key {gk['key']}; femur_model_version {FEMUR_MODEL_VERSION}; hollow_core {HOLLOW_CORE}")
    print(f"disk: {free:.1f} GiB free on the filesystem of {J.QROOT} (gates: {DISK_MIN_GIB:g} GiB before every pass, {FIRST_START_MIN_GB:g} GB = "
          f"{FIRST_START_MIN_GIB:.1f} GiB at the first start; on Linux the feeder checks ~/mobo_toy_v2/queue; a dry run against a local copy "
          "measures the local disk)")
    print(f"aux files (md5 on this host, relative to {CODE_ROOT}; null = absent here): {json.dumps(aux)}")
    m = b["init_median"]
    print(f"init median design: {m['job_id']} rot {m['rot_first_deg']:.4f} deg; rule: {INIT_MEDIAN_RULE}")
    print(f"pilot16 resolved from the queue: {', '.join(b['pilot16'])}")
    print("references: " + ", ".join(f"h{h} -> {j}" for h, j in b["ref_id"].items()))
    print("h 2.0 usable bonded results of the 24 pilot designs (a design without one gets a BD h2.0 bond_only partner):")
    for c, have in b["partners"].items():
        print(f"    {c:<20} {', '.join(have) if have else '-  (partner)'}")
    if not b["seeds"]:
        print(f"seed files declared for batch {batch}: none (SEEDS)")
    for s in b["seeds"]:
        if not s["present"]:
            print(f"seed file {s['file']}: MISSING under {J.RESULTS} (declared in SEEDS: a problem, see PROBLEMS)")
        else:
            print(f"seed file {s['file']} (submitted {s['submitted_utc']}): {s['n_jobs']} seed jobs, {len(s['adopted'])} adopted 1:1 by rows "
                  "(dedup existing via the physics key):")
            for k, sid in s["adopted"].items():
                print(f"    {k:<22} -> {sid} (queue state {J.state(J.QROOT / sid)})")
    print(f"jobs ({len(rows)}): key | layer | stage | source job | variant (vs the source spec.json) | expected id | dedup | ref (intact_job) | heavy")
    for r in rows:
        ref = r["spec"].get("intact_job") or "-"
        dd = r["dedup"] if r["dedup"] != "existing" else f"existing ({r['dedup_via']}) -> {r['id']}"
        print(f"  {r['key']} | {r['layer']} | {r['stage']} | {r['source_job']} | {variant_diff(r['source_spec'], r['spec'])} | "
              f"{r['expected_id']} | {dd} | {ref} | {'heavy' if r['heavy'] else ''}{' exclusive' if r['exclusive'] else ''}")
    by_layer = {}
    for r in rows:
        by_layer[r["layer"]] = by_layer.get(r["layer"], 0) + 1
    hits = [r for r in rows if r["dedup"] != "new"]
    n_new = len(rows) - len(hits)
    n_ex_h8 = sum(r["dedup"] == "existing" and r["dedup_via"] == "hash8" for r in rows)
    n_ex_ph = sum(r["dedup"] == "existing" and r["dedup_via"] == "physics" for r in rows)
    fam_legacy = {r["key"]: [p for p in CHECK_PHASES if SN.Phase(p).in_family(r["spec"], legacy=True)] for r in rows}
    fam_legacy = {k: v for k, v in fam_legacy.items() if v}
    print(f"per layer: {json.dumps(by_layer)}; total {len(rows)}; h 2.0 bond_only partners {b['n_partner']} (of at most {len(FD25_CODES) + len(PILOT16)})")
    print(f"dedup: {n_new} new, {sum(r['dedup'] == 'queued' for r in rows)} already queued under the expected id, "
          f"{n_ex_h8 + n_ex_ph} existing ({n_ex_h8} via hash8, {n_ex_ph} via the physics key)"
          + ("".join(f"\n    {r['key']}: {r['dedup']} ({r['dedup_via']}) {r['id']} (queue state {J.state(J.QROOT / r['id'])}; hits {r['dedup_hits']})"
                     for r in hits)))
    h14x, h14why = h14_mode()
    print(f"heavy rows (one at a time): {[r['key'] for r in rows if r['heavy']]}; exclusive (idle queue only, holds every other db "
          f"submission while in flight): {list(EXCLUSIVE)}; FD0_h1.4_* also wait for the operator file {H14_OK_NAME}; FD-0 h1.4 mode now: "
          f"{h14why}")
    print(f"slow start: layers {list(SLOW_START_LAYERS)} keep at most {SLOW_START_CAP} rows in flight (NEW / READY / CLAIMED / SOLVED) until "
          f"{SLOW_START_DONE} of their rows are DONE")
    print(f"operator files (under {J.QROOT.parent}): {H14_OK_NAME} (FD0_h1.4_* may go); {H14_EXCL_NAME} or the word 'exclusive' in "
          f"{H14_OK_NAME} (FD0_h1.4_* exclusive like REF_h1.4); {RELEASE_PREFIX}<layer, spaces as _> (release that layer's hold); "
          f"{RELEASE_PREFIX}{RELEASE_ALL} or {RELEASE_PREFIX}{batch} (release every layer held for the first-10 reason); "
          f"{ACK_FAILED_PREFIX}<key> (accept a row resolving to a FAILED existing job); {STOP_NAME} (stop the feeder)")
    for r in rows:
        if r.get("ack_failed"):
            print(f"FAILED existing job accepted: {r['key']} -> {r['id']} by {r['ack_failed']['file']} ({r['ack_failed']['mtime_utc']})")
    if fam_legacy:
        print(f"NOTE: {len(fam_legacy)} rows would be in a phase-11..14 family only under --warm legacy (stage prefix ignored), which "
              f"check_warm_source / warm_from forbid for phases 11-14: {sorted(fam_legacy)}")
    for w in b["warnings"]:
        print("WARNING: " + w)
    if b["problems"]:
        print(f"PROBLEMS ({len(b['problems'])}; feed would refuse):")
        for p in b["problems"]:
            print("  " + p)
    else:
        print("checks: all rows pass (stage prefix, job id prefix, not in any phase 11-14 family, role keys, 10-23 mesh rule, reference match, "
              "seed adoption, existing hits: femur_model_version and not FAILED unless acknowledged)")
    print("DRY-RUN-JSON")
    print(json.dumps({"batch": batch, "n_jobs": len(rows), "per_layer": by_layer, "n_partner": b["n_partner"], "n_new": n_new,
                      "n_existing": n_ex_h8 + n_ex_ph, "n_existing_physics": n_ex_ph, "seeds": b["seeds"], "problems": b["problems"],
                      "warnings": b["warnings"], "code_hash": b["code_hash"], "femur_geom_key": gk["key"], "aux_md5": aux,
                      "init_median": m["job_id"], "h14_mode": "exclusive" if h14x else "heavy",
                      "slow_start": {"layers": list(SLOW_START_LAYERS), "cap": SLOW_START_CAP, "until_done": SLOW_START_DONE},
                      "jobs": [{k: r[k] for k in ("key", "layer", "stage", "source", "selection", "design_code", "source_job", "condition_id",
                                                  "bonded", "model_set", "intact_job", "ref_key", "heavy", "exclusive", "femur_model_version",
                                                  "hollow_core", "expected_id", "id", "dedup", "dedup_via", "seed", "ack_failed")}
                               | {"variant": variant_diff(r["source_spec"], r["spec"])} for r in rows]}, indent=1, default=float))
    return 1 if b["problems"] else 0


# ================================================================ 清单与喂料器
def manifest_path(batch: str) -> pathlib.Path:
    return J.RESULTS / f"db_manifest_{batch}.json"


def _write_json(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, default=float))
    os.replace(tmp, p)


class _Log:
    def __init__(self, path: pathlib.Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{_utc()} {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


@contextlib.contextmanager
def feed_lock(path: pathlib.Path):
    """同一时刻只许一个喂料器：logs/db_feed.lock 上的独占锁（POSIX flock / Windows msvcrt），进程退出即释放。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit(f"another db feeder holds {path}; not starting a second one") from None
        yield
    finally:
        fh.close()


def _marker_times(jid: str) -> dict:
    """作业目录标记文件的时刻（UTC）：spec / ready / claimed / solved / done / failed。solve_worker 用 `mv READY CLAIMED` 认领，改名保留 mtime：
    ready = READY（还没认领）或 CLAIMED 的 mtime（= 建模完成），claimed = CLAIMED 的 ctime（Linux 上改名会更新 ctime = 认领时刻）。
    标记文件在两次 stat 之间消失（READY 刚被改名）→ 这一项本轮不记（下一轮再读）。"""
    d, out = J.QROOT / jid, {}
    for f, k in (("spec.json", "spec"), ("READY", "ready"), ("SOLVED", "solved"), ("DONE", "done"), ("FAILED.json", "failed")):
        with contextlib.suppress(FileNotFoundError):
            out[k] = _utc((d / f).stat().st_mtime)
    with contextlib.suppress(FileNotFoundError):
        st = (d / "CLAIMED").stat()
        out.setdefault("ready", _utc(st.st_mtime))
        out["claimed"] = _utc(st.st_ctime)
    return out


def _finished_ts(jid: str) -> float | None:
    d = J.QROOT / jid
    for f in ("DONE", "FAILED.json"):
        with contextlib.suppress(FileNotFoundError):
            return (d / f).stat().st_mtime
    return None


def _man_row(r: dict) -> dict:
    return {"key": r["key"], "layer": r["layer"], "stage": r["stage"], "source": r["source"], "selection": r["selection"],
            "design_code": r["design_code"], "source_job": r["source_job"], "condition_id": r["condition_id"], "bonded": r["bonded"],
            "model_set": r["model_set"], "intact_job": r["intact_job"], "heavy": r["heavy"], "exclusive": r["exclusive"],
            "femur_model_version": r["femur_model_version"], "hollow_core": r["hollow_core"], "pool_idx": r.get("pool_idx"),
            "partner_of": r.get("partner_of"), "expected_id": r["expected_id"], "id": r["id"], "dedup": r["dedup"],
            "dedup_via": r["dedup_via"], "seed": r["seed"], "ack_failed": r.get("ack_failed"),
            "status": "existing" if r["dedup"] == "existing" else ("submitted" if r["dedup"] == "queued" else "pending"),
            "state": None, "submitted_utc": None, "times_utc": {}, "finished_ts": None, "held_reason": None, "failed_logged": False}


def open_manifest(batch: str, b: dict, gk: dict, log, aux: dict | None = None) -> dict:
    """读已有清单并与当前作业表核对（键集合、每行的预期 id、code_hash、股骨几何键、aux md5），不同 → SystemExit；没有 → 新建。"""
    p = manifest_path(batch)
    rows = b["rows"]
    aux = aux_md5() if aux is None else aux
    if not p.exists():
        return {"batch": batch, "created_utc": _utc(), "updated_utc": None, "code_hash": b["code_hash"], "femur_geom_key": gk,
                "aux_md5": aux, "aux_root": str(CODE_ROOT), "femur_model_version": FEMUR_MODEL_VERSION, "hollow_core": HOLLOW_CORE,
                "init_median": b["init_median"]["job_id"], "init_median_rule": INIT_MEDIAN_RULE, "seeds": b["seeds"],
                "order": [r["key"] for r in rows], "rows": {r["key"]: _man_row(r) for r in rows}, "gates": {}, "events": []}
    man, err = _read_json(p)
    if not isinstance(man, dict):
        raise SystemExit(f"{p} is unreadable ({err or 'not a JSON object'}); not feeding (restore it from the job dirs or start a new batch name)")
    if man.get("batch") != batch:
        raise SystemExit(f"{p} holds batch {man.get('batch')!r}")
    old, new = set(man["rows"]), {r["key"] for r in rows}
    diff = []
    if old != new:
        diff.append(f"keys only in the manifest {sorted(old - new)}; keys only in the current batch {sorted(new - old)}")
    for r in rows:
        m = man["rows"].get(r["key"])
        if m is not None and m["expected_id"] != r["expected_id"]:
            diff.append(f"{r['key']}: manifest expected id {m['expected_id']} != current {r['expected_id']}")
        if m is not None and r["layer"] == "REF" and m["status"] == "pending" and r["id"] != m["id"]:
            diff.append(f"{r['key']}: still pending in the manifest as {m['id']}, but now resolves to the existing job {r['id']} (an identical "
                        "intact spec appeared in the queue): its dependents' intact_job, and so their expected ids, would change")
    if man.get("code_hash") != b["code_hash"]:
        diff.append(f"manifest code_hash {man.get('code_hash')} != current {b['code_hash']}")
    if (man.get("femur_geom_key") or {}).get("key") != gk["key"]:
        diff.append(f"manifest femur_geom_key {(man.get('femur_geom_key') or {}).get('key')} != current {gk['key']}")
    if "aux_md5" in man and man["aux_md5"] != aux:
        diff.append("aux file md5 changed since the manifest was written: " + "; ".join(aux_changes(man["aux_md5"], aux)))
    if diff:
        raise SystemExit(f"{p}: the batch changed since the manifest was written; not feeding (start a new batch name, or restore the code):\n"
                         + "\n".join("  " + d for d in diff))
    if "aux_md5" not in man:
        man["aux_md5"], man["aux_root"] = aux, str(CODE_ROOT)
        log(f"manifest had no aux_md5: recorded the current md5 of {list(AUX_FILES)}")
    man.setdefault("gates", {})
    for m in man["rows"].values():
        for k, v in (("dedup_via", None), ("seed", None), ("finished_ts", None), ("held_reason", None), ("exclusive", False),
                     ("failed_logged", False), ("ack_failed", None)):
            m.setdefault(k, v)
    for r in rows:                                     # 还没提交的行：按这次的查重结果（例如别的作业里刚出现同一物理计算）
        m = man["rows"][r["key"]]
        if m["status"] == "pending" and r["dedup"] != "new":
            m.update(id=r["id"], dedup=r["dedup"], dedup_via=r["dedup_via"], seed=r["seed"], ack_failed=r.get("ack_failed"),
                     status="existing" if r["dedup"] == "existing" else "submitted")
            log(f"{r['key']}: was pending, now {r['dedup']} ({r['dedup_via']}) {r['id']} (dedup at restart)")
    return man


_SPEC_CACHE: dict = {}


def _cached_spec(d: pathlib.Path):
    """喂料器每轮的 spec 读取：按 (路径, mtime_ns, 大小) 缓存（spec.json 由 jobs.submit 写一次，不再改）。返回 (spec, 错误)。"""
    p = d / "spec.json"
    try:
        st = p.stat()
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, f"{type(e).__name__}: {e}"
    k = (str(p), st.st_mtime_ns, st.st_size)
    if k in _SPEC_CACHE:
        return _SPEC_CACHE[k], None
    sp, err = _read_spec(p)
    if sp is not None:
        _SPEC_CACHE[k] = sp
    return sp, err


def queue_snapshot() -> dict:
    """一轮的队列快照：hash8 → 目录名、物理键 → 目录名、未领取的 db_* 作业、全队列在飞的重作业、全队列 NEW / READY / CLAIMED（与没有 spec
    的目录）、READY 作业的 READY 时刻、没有 / 读不了 spec.json 的目录（读不了的按没有 spec 处理：算重作业、db_* 算未领取、算队列不空）。"""
    names, unclaimed, heavy, missing, unreadable, busy, ready = [], [], [], [], [], [], []
    by_phys = {}
    for e in os.scandir(J.QROOT):
        if not e.is_dir():
            continue
        n, d = e.name, pathlib.Path(e.path)
        names.append(n)
        sp, err = _cached_spec(d)
        st = J.state(d)
        if err:
            unreadable.append(f"{n} ({err})")
            if st == "NEW":
                st = "MISSING"
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
        if st in ("NEW", "READY", "CLAIMED", "MISSING"):
            busy.append(n)
            if st == "MISSING":
                missing.append(n)
            if n.startswith("db_") and st in ("NEW", "READY", "MISSING"):
                unclaimed.append(n)
            if is_heavy(sp):
                heavy.append(n)
        if st == "READY":
            with contextlib.suppress(FileNotFoundError):      # READY 刚被 worker 改名成 CLAIMED：已不是 READY，本轮不计
                ready.append(((d / "READY").stat().st_mtime, n))
    return {"by_h8": _by_h8(names), "by_phys": by_phys, "unclaimed_db": sorted(unclaimed), "heavy_inflight": sorted(heavy),
            "missing": sorted(missing), "unreadable": sorted(unreadable), "busy_any": sorted(busy), "ready": sorted(ready)}


def refresh(man: dict) -> None:
    for m in man["rows"].values():
        if m["status"] in ("submitted", "existing"):
            m["state"] = J.state(J.QROOT / m["id"])
            m["times_utc"] = _marker_times(m["id"])
            m["finished_ts"] = _finished_ts(m["id"]) if m["state"] in ("DONE", "FAILED") else None


def _fail_reason(jid: str) -> str:
    fl, err = _read_json(J.QROOT / jid / "FAILED.json")
    if not isinstance(fl, dict):
        return f"FAILED.json unreadable ({err or 'missing or not an object'})"
    return f"{fl.get('level')} {fl.get('stage')}: {(fl.get('reason') or '')[:200]!r}"


def release_all_files(batch: str) -> list:
    """批次级放行文件：DB_RELEASE_ALL 与 DB_RELEASE_<批次>（任一个都行），放行每个因"最先 10 行"停下的层。"""
    root = J.QROOT.parent
    return [root / f"{RELEASE_PREFIX}{RELEASE_ALL}", root / f"{RELEASE_PREFIX}{batch}"]


def _mtime(p: pathlib.Path) -> float | None:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return None


def _release_hint(rel: pathlib.Path, kinds: list, batch: str) -> str:
    h = f"touch {rel}"
    if "first10" in kinds:
        a, c = release_all_files(batch)
        h += f" (this layer only), or touch {a} or {c} (every layer held for the first-10 reason)"
    return h


def gate_pass(b: dict, man: dict, log) -> None:
    """按层失败闸门（模块说明）：先处理放行文件（本层的 / 批次级的），再按当前状态判断要不要停；停 = 该层 pending 行 → held，记 ERROR 与事件。
    按层规则数该层全部已完成的行（种子与采纳的已有作业也算）；"最先 10 行"的窗口只数喂料器自己提交的行（清单 dedup == "new"）。"""
    rows = {r["key"]: r for r in b["rows"]}
    gates = man.setdefault("gates", {})
    batch = man.get("batch", b["batch"])
    per, fin = {}, []
    for k in man["order"]:
        m = man["rows"][k]
        if m["status"] in ("submitted", "existing") and m["state"] in ("DONE", "FAILED"):
            s = per.setdefault(rows[k]["layer"], {"failed": [], "finished": 0})
            s["finished"] += 1
            if m["state"] == "FAILED":
                s["failed"].append(k)
            if m.get("dedup") == "new":                      # 喂料器自己提交的行（种子 / 采纳的已有作业只受按层规则管）
                fin.append((m.get("finished_ts") or 0.0, k, m["state"] == "FAILED"))
    fin.sort()
    first = fin[:FIRST_N]
    first_failed = [k for _, k, f in first if f]
    first_trip = len(first_failed) > FIRST_N_MAX_FAILED
    all_files = release_all_files(batch)
    for L in dict.fromkeys(r["layer"] for r in b["rows"]):
        slug = layer_slug(L)
        g = gates.setdefault(slug, {"layer": L, "held": False, "held_utc": None, "held_ts": None, "reasons": [], "kinds": [], "ack_failed": [],
                                    "first10_ack": False, "releases": []})
        if "kinds" not in g:                                # 旧清单：从原因文字推断
            g["kinds"] = ["first10" if x.startswith("batch:") else "layer" for x in g.get("reasons") or []]
        st = per.get(L, {"failed": [], "finished": 0})
        rel = J.QROOT.parent / f"{RELEASE_PREFIX}{slug}"

        def layer_why():
            unack = [k for k in st["failed"] if k not in g["ack_failed"] and not man["rows"][k].get("ack_failed")]
            rate = len(st["failed"]) / st["finished"] if st["finished"] else 0.0
            if len(unack) >= GATE_MIN_FAILED and rate > GATE_MAX_RATE:
                return [f"layer {L}: {len(st['failed'])} FAILED of {st['finished']} finished ({100 * rate:.1f} % > {100 * GATE_MAX_RATE:g} %; "
                        f"{len(unack)} not released yet)"]
            return []

        def unhold(how: str, file: pathlib.Path, mt: float) -> int:
            n = 0
            for k in man["order"]:
                m = man["rows"][k]
                if rows[k]["layer"] == L and m["status"] == "held":
                    m.update(status="pending", held_reason=None)
                    n += 1
            g.update(held=False, kinds=[])
            g["releases"].append({"utc": _utc(), "file": str(file), "file_mtime_utc": _utc(mt), "rows": n, "how": how})
            man["events"].append({"utc": _utc(), "event": "release", "layer": L, "rows": n, "file": file.name})
            return n

        if g["held"]:
            mt = _mtime(rel)
            if mt is not None and mt >= g["held_ts"]:      # 停下之前就有的文件（旧的）不算放行
                g.update(ack_failed=sorted(set(g["ack_failed"]) | set(st["failed"])),
                         first10_ack=g["first10_ack"] or first_trip or "first10" in g["kinds"])
                n = unhold("layer", rel, mt)
                log(f"RELEASE layer {L}: {rel} (written {_utc(mt)}) -> {n} held rows pending again; FAILED rows acknowledged: {g['ack_failed']}")
            elif "first10" in g["kinds"]:
                hit = next(((p, t) for p in all_files if (t := _mtime(p)) is not None and t >= g["held_ts"]), None)
                if hit is not None:
                    fa, ta = hit
                    g["first10_ack"] = True
                    lw = layer_why()
                    if lw:                                  # 也因本层自己的失败停着：只确认"最先 10 行"这一条
                        g.update(kinds=["layer"], reasons=lw)
                        for k in man["order"]:
                            if rows[k]["layer"] == L and man["rows"][k]["status"] == "held":
                                man["rows"][k]["held_reason"] = "; ".join(lw)
                        man["events"].append({"utc": _utc(), "event": "release_first10", "layer": L, "file": fa.name, "still_held": lw})
                        log(f"RELEASE {fa} (written {_utc(ta)}): first-10 reason acknowledged for layer {L}; still held for its own failures "
                            f"({'; '.join(lw)}); release after checking: touch {rel}")
                    else:
                        n = unhold("batch", fa, ta)
                        log(f"RELEASE layer {L}: {fa} (written {_utc(ta)}; first-10 reason acknowledged) -> {n} held rows pending again")
        why, kinds = layer_why(), []
        if why:
            kinds.append("layer")
        if first_trip and not g["first10_ack"]:
            why.append(f"batch: {len(first_failed)} of the first {len(first)} finished rows submitted by the feeder FAILED ({first_failed}; "
                       f"more than {FIRST_N_MAX_FAILED})")
            kinds.append("first10")
        pend = [k for k in man["order"] if rows[k]["layer"] == L and man["rows"][k]["status"] == "pending"]
        if why and not g["held"] and pend:
            now = time.time()
            for k in pend:
                man["rows"][k].update(status="held", held_reason="; ".join(why))
            g.update(held=True, held_utc=_utc(now), held_ts=now, reasons=why, kinds=kinds)
            failed_keys = sorted(set(st["failed"]) | (set(first_failed) if "first10" in kinds else set()))
            det = "; ".join(f"{k} {man['rows'][k]['id']} {_fail_reason(man['rows'][k]['id'])}" for k in failed_keys)
            man["events"].append({"utc": _utc(now), "event": "hold", "layer": L, "rows": len(pend), "reasons": why, "kinds": kinds,
                                  "failed": failed_keys})
            log(f"ERROR HOLD layer {L}: {'; '.join(why)}; {len(pend)} pending rows held (not submitted); FAILED rows: {det}; "
                f"release after checking: {_release_hint(rel, kinds, batch)}")


def _h14_ok(h14_ref: str) -> str | None:
    """FD0_h1.4_* 的操作员文件：没有 / 比 h 1.4 参照的 spec.json 旧 → 等待原因；可以 → None。"""
    f = J.QROOT.parent / H14_OK_NAME
    try:
        mt = f.stat().st_mtime
    except FileNotFoundError:
        return f"operator file {f} missing (write it after reading the h 1.4 reference's .dat memory estimate)"
    try:
        ref_t = (J.QROOT / h14_ref / "spec.json").stat().st_mtime
    except FileNotFoundError:
        return f"h 1.4 reference {h14_ref} has no spec.json (cannot date the operator file {f})"
    if mt < ref_t:
        return (f"operator file {f} ({_utc(mt)}) is older than the h 1.4 reference's submission ({_utc(ref_t)}); "
                "touch it again after reading the .dat estimate")
    return None


def h14_mode() -> tuple[bool, str]:
    """FD0_h1.4_* 的运行模式：(True, 理由) = 独占（像 REF_h1.4）：DB_H14_EXCLUSIVE 存在，或 DB_H14_REF_OK 里有 exclusive 一词（不论文件新旧；
    读不了 → 也按独占，较安全）；否则 (False, 理由) = 重作业（一次一个，旁边可有轻作业）。"""
    root = J.QROOT.parent
    fx, fo = root / H14_EXCL_NAME, root / H14_OK_NAME
    if fx.exists():
        return True, f"exclusive ({fx} present)"
    try:
        txt = fo.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False, f"heavy (one heavy job at a time beside light jobs; {fx.name} absent, {fo.name} absent)"
    except OSError as e:
        return True, f"exclusive ({fo} exists but cannot be read: {type(e).__name__}: {e}; the safer mode)"
    if re.search(r"\bexclusive\b", txt, re.IGNORECASE):
        return True, f"exclusive (the word 'exclusive' in {fo})"
    return False, f"heavy (one heavy job at a time beside light jobs; {fx.name} absent, no word 'exclusive' in {fo.name})"


def exclusive_keys(b: dict, h14_exclusive: bool) -> list:
    """这一轮独占的行：EXCLUSIVE（REF_h1.4），DB_H14_EXCLUSIVE 模式下再加 FD0_h1.4_*（作业表顺序）。"""
    return list(EXCLUSIVE) + ([r["key"] for r in b["rows"] if r["layer"] == H14_LAYER] if h14_exclusive else [])


def feed_pass(b: dict, man: dict, snap: dict, log, max_unclaimed: int = MAX_UNCLAIMED, waits: dict | None = None,
              h14_exclusive: bool | None = None) -> list:
    """一轮提交（规则见模块说明）：按作业表顺序；独占行在飞 → 整轮不提交；未领取 db_* ≥ max_unclaimed 就停；等参照 / 重作业 / 参照优先 /
    独占 / 操作员文件 / 慢启动的行跳过（不挡后面的行）。waits：{原因键: {"text", "keys"}}（本轮各行等待的原因，给 WAIT 日志）。
    h14_exclusive：FD0_h1.4_* 是否独占（None = 现读 h14_mode()）。提交前对活队列再查一次重：命中的核对（hit_checks）出问题、或 REF 行
    查重到与建表时不同的 id → 写清单并停止（_halt）。返回这轮提交的键。"""
    rows = {r["key"]: r for r in b["rows"]}
    waits = {} if waits is None else waits
    mp = manifest_path(b["batch"])
    if h14_exclusive is None:
        h14_exclusive = h14_mode()[0]
    excl = exclusive_keys(b, h14_exclusive)

    def wait(rk, text, key):
        w = waits.setdefault(rk, {"text": text, "keys": []})
        w["text"] = text
        w["keys"].append(key)

    unclaimed = list(snap["unclaimed_db"])
    heavy = list(snap["heavy_inflight"])
    busy = list(snap["busy_any"])
    h14_ref = b["ref_id"].get(f"{HEAVY_H:g}")
    order = man["order"]
    pending = [k for k in order if man["rows"][k]["status"] == "pending"]
    for k in excl:                                              # 独占行在飞：其他 db 提交一律暂停
        m = man["rows"].get(k)
        if m and m["status"] in ("submitted", "existing"):
            st = J.state(J.QROOT / m["id"])
            if st in ("NEW", "READY", "CLAIMED", "MISSING"):
                for p in pending:
                    wait("exclusive_inflight", f"exclusive {k} ({m['id']}) is {st}: every other db submission is held until it is DONE / FAILED", p)
                return []
    ss_done, ss_fly = {}, {}                                    # 慢启动：各层 DONE 的行数、在飞（NEW / READY / CLAIMED / SOLVED / MISSING）的行数
    for k in order:
        m, L = man["rows"][k], rows[k]["layer"]
        if L in SLOW_START_LAYERS and m["status"] in ("submitted", "existing"):
            st = m.get("state") or J.state(J.QROOT / m["id"])
            if st == "DONE":
                ss_done[L] = ss_done.get(L, 0) + 1
            elif st != "FAILED":
                ss_fly[L] = ss_fly.get(L, 0) + 1
    ref_keys = [k for k in order if rows[k]["layer"] == "REF"]
    ref_ids = {man["rows"][k]["id"] for k in ref_keys} | {man["rows"][k]["expected_id"] for k in ref_keys}
    prio = []
    for k in ref_keys:
        m = man["rows"][k]
        if k in EXCLUSIVE:
            continue
        if m["status"] == "pending" or (m["status"] in ("submitted", "existing") and J.state(J.QROOT / m["id"]) in ("NEW", "READY", "MISSING")):
            prio.append(k)
    out = []
    for i, key in enumerate(order):
        m, r = man["rows"][key], rows[key]
        if m["status"] != "pending":
            continue
        if len(unclaimed) >= max_unclaimed:
            for p in order[i:]:
                if man["rows"][p]["status"] == "pending":
                    wait("depth", f"depth cap: {len(unclaimed)} unclaimed db_* jobs >= {max_unclaimed}", p)
            break
        s = r["spec"]
        if needs_ref(s):
            rst = J.state(J.QROOT / s["intact_job"])
            if rst == "FAILED":
                m["status"] = "blocked"
                log(f"ERROR {key}: intact reference {s['intact_job']} FAILED; row blocked (not submitted, not retried)")
                continue
            if rst != "DONE":
                wait(f"ref:{s['intact_job']}", f"reference {s['intact_job']} is {rst}", key)
                continue
        if s.get("kind") != "intact" and float(s["h_int"]) <= HEAVY_H + 1e-9:
            hst = J.state(J.QROOT / h14_ref)
            if hst != "DONE":
                wait("h14ref", f"h 1.4 reference {h14_ref} is {hst}", key)
                continue
            why = _h14_ok(h14_ref)
            if why:
                wait("h14ok", why, key)
                continue
        L = r["layer"]
        if L in SLOW_START_LAYERS and ss_done.get(L, 0) < SLOW_START_DONE and ss_fly.get(L, 0) >= SLOW_START_CAP:
            wait(f"slow:{L}", f"slow start {L}: {ss_fly.get(L, 0)} rows in flight >= {SLOW_START_CAP} until {SLOW_START_DONE} of its rows are "
                              f"DONE ({ss_done.get(L, 0)} DONE)", key)
            continue
        if key in excl:
            if busy:
                wait("exclusive_wait", f"exclusive {key} waits for an idle queue: {len(busy)} jobs NEW / READY / CLAIMED of any stage "
                                       f"(e.g. {', '.join(busy[:3])})", key)
                continue
        elif prio and L != "REF":
            other = [n for n in unclaimed if n not in ref_ids]
            if len(other) >= REF_PRIORITY_CAP:
                wait("ref_priority", f"REF priority ({', '.join(prio)} pending / NEW / READY): {len(other)} other unclaimed db_* >= "
                                     f"{REF_PRIORITY_CAP}", key)
                continue
        if r["heavy"] and len(heavy) >= HEAVY_MAX:
            wait("heavy", f"heavy gate: {', '.join(heavy[:3])} in flight", key)
            continue
        jid, status, hits, via = resolve(s, snap["by_h8"], by_phys=snap["by_phys"])   # 提交前对活队列再查一次重（碰撞 → SystemExit）
        if L == "REF":
            want = b["ref_id"].get(f"{float(s['h_int']):g}")
            if jid != want:
                deps = [k for k in order if rows[k]["spec"].get("intact_job") == want]
                _halt(man, mp, f"{key}: at feed time this reference resolves to {jid} ({status} via {via}), not to {want}, the intact_job "
                               f"its {len(deps)} dependents were built with ({', '.join(deps[:4])}{', ...' if len(deps) > 4 else ''}); they would "
                               f"wait for {want} forever. Stopped: an identical intact spec ({jid}) entered the queue after this batch was built; "
                               "check it, then start a new batch name (a restart is refused: the dependents' expected ids change)")
        if status != "new":
            probs, notes, ack = hit_checks(key, jid, _spec_of(jid))
            if probs:
                _halt(man, mp, "feed-time dedup: " + "; ".join(probs) + "; stopped before submitting (the manifest is written)")
            m.update(id=jid, dedup=status, dedup_via=via, status="existing" if status == "existing" else "submitted", ack_failed=ack,
                     state=J.state(J.QROOT / jid))
            log(f"{key}: found in the queue before submitting ({status} via {via}: {jid}); not submitted again")
            for n in notes:
                log("NOTE " + n)
            if L in SLOW_START_LAYERS and m["state"] not in ("DONE", "FAILED"):
                ss_fly[L] = ss_fly.get(L, 0) + 1
            continue
        if needs_ref(s):
            mm = ref_mismatch(s, _spec_of(s["intact_job"]))
            if mm:
                raise SystemExit(f"{key}: intact_job {s['intact_job']} does not match: " + "; ".join(mm))
        got = J.submit(s)
        if got != m["expected_id"]:
            raise SystemExit(f"{key}: jobs.submit returned {got}, expected {m['expected_id']}")
        m.update(status="submitted", id=got, submitted_utc=_utc())
        snap["by_h8"].setdefault(_h8(got), []).append(got)
        snap["by_phys"].setdefault(phys_key(s), []).append(got)
        unclaimed.append(got)
        busy.append(got)
        if r["heavy"]:
            heavy.append(got)
        if L in SLOW_START_LAYERS:
            ss_fly[L] = ss_fly.get(L, 0) + 1
        out.append(key)
        log(f"submit {key} -> {got} ({L}, {r['model_set']}{', heavy' if r['heavy'] else ''}{', exclusive' if key in excl else ''})")
        if key in excl:
            log(f"{key} is exclusive: no other db submission until {got} is DONE / FAILED")
            break
    return out


def _counts(man: dict) -> dict:
    c = {}
    for m in man["rows"].values():
        k = m["status"] if m["status"] in ("pending", "blocked", "held") else (m["state"] or "?")
        c[k] = c.get(k, 0) + 1
    return c


def wait_line(man: dict, waits: dict, snap: dict, idle: int) -> str:
    np_ = sum(m["status"] == "pending" for m in man["rows"].values())
    nh = sum(m["status"] == "held" for m in man["rows"].values())
    parts = []
    for w in waits.values():
        ks = w["keys"]
        parts.append(f"{w['text']} [{len(ks)}: {', '.join(ks[:3])}{', ...' if len(ks) > 3 else ''}]")
    hg = [g for g in man.get("gates", {}).values() if g.get("held")]
    if hg:
        txt = f"held layers {[g['layer'] for g in hg]} (release: touch {J.QROOT.parent}/{RELEASE_PREFIX}<layer, spaces as _>"
        f10 = [g["layer"] for g in hg if "first10" in (g.get("kinds") or [])]
        if f10:
            a, c = release_all_files(man.get("batch", "b1"))
            txt += f"; held for the first-10 reason {f10}: touch {a} or {c} to release them all"
        parts.append(txt + ")")
    return (f"WAIT idle pass {idle}: {np_} pending, {nh} held; " + "; ".join(parts or ["no wait reason recorded"])
            + f"; {_oldest_ready(snap)}; unclaimed db_* {len(snap['unclaimed_db'])}; NEW / READY / CLAIMED of any stage {len(snap['busy_any'])}")


def _oldest_ready(snap: dict) -> str:
    if snap["ready"]:
        ts, n = snap["ready"][0]
        return f"oldest READY {n} for {(time.time() - ts) / 60:.0f} min"
    return "no READY job"


def last_claim() -> tuple[float, str] | None:
    """全队列最近一次认领：各目录 CLAIMED 的 ctime 的最大值（worker `mv READY CLAIMED`；Linux 上改名更新 ctime；CLAIMED 认领后一直留着）。"""
    best = None
    for e in os.scandir(J.QROOT):
        if e.is_dir():
            try:
                t = os.stat(os.path.join(e.path, "CLAIMED")).st_ctime
            except FileNotFoundError:
                continue
            if best is None or t > best[0]:
                best = (t, e.name)
    return best


def heartbeat_line(man: dict, snap: dict, n_sub: int, h14_txt: str | None = None) -> str:
    """HEARTBEAT（每 HEARTBEAT_S 一行，不论有没有待提交的行）：本批在飞的行（按状态）、各状态计数、最老的 READY、最近一次认领距今多久。"""
    fly = {}
    for m in man["rows"].values():
        if m["status"] in ("submitted", "existing") and m["state"] not in ("DONE", "FAILED"):
            fly[str(m["state"])] = fly.get(str(m["state"]), 0) + 1
    lc = last_claim()
    lct = "no claim seen in the queue" if lc is None else f"last claim {lc[1]} at {_utc(lc[0])} ({(time.time() - lc[0]) / 60:.0f} min ago)"
    return (f"HEARTBEAT batch {man.get('batch')}: {sum(fly.values())} batch rows in flight {json.dumps(fly, sort_keys=True)}; "
            f"rows {json.dumps(_counts(man), sort_keys=True)}; {_oldest_ready(snap)}; {lct}; NEW / READY / CLAIMED of any stage "
            f"{len(snap['busy_any'])}; {n_sub} submitted this pass" + (f"; FD-0 h1.4 mode {h14_txt}" if h14_txt else ""))


ANNOUNCE = ("h14ok", "exclusive_wait", "exclusive_inflight")    # 需要操作员知道的等待：第一次出现时单独记一行


def _halt(man: dict, mp: pathlib.Path, msg: str) -> None:
    man["events"].append({"utc": _utc(), "event": "halt", "reason": msg})
    man["updated_utc"] = _utc()
    _write_json(mp, man)
    raise SystemExit(msg)


def feed(batch: str = "b1", poll: float = POLL_S, once: bool = False, max_unclaimed: int = MAX_UNCLAIMED, sleep=time.sleep) -> int:
    """喂料器主循环（规则见模块说明）。返回退出码：0 = 全部 DONE / FAILED、STOP 或 --once 一轮结束；3 = 有 blocked 行。
    任何拒绝（检查、磁盘、代码哈希、股骨几何、aux md5、清单不符、碰撞）→ SystemExit 带原因（日志里也有）；其他异常记 "ERROR crashed" 再抛出。"""
    if not sys.platform.startswith("linux") and not _ALLOW_NON_LINUX:
        raise SystemExit("feed runs on the Linux queue host only (cd ~/mobo_toy_v2/code && taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed ...)")
    if not J.QROOT.is_dir():
        raise SystemExit(f"queue {J.QROOT} does not exist")
    root = J.QROOT.parent
    stop = root / STOP_NAME
    if stop.exists():
        raise SystemExit(f"{stop} exists: remove it to start the feeder")
    with feed_lock(root / "logs" / "db_feed.lock"):
        log = _Log(root / "logs" / "db_feed.log")
        pin = ""
        if hasattr(os, "sched_getaffinity"):
            pin = f"; cpus {sorted(os.sched_getaffinity(0))}; nice {os.nice(0)}"
        log(f"feed start batch {batch} pid {os.getpid()} queue {J.QROOT}{pin}")
        try:
            check_code()
            mp = manifest_path(batch)
            if mp.exists():                                 # 坏的清单先拒绝（build 读它判断"之前采纳过"，读不了会把已有的 FAILED 行误报成问题）
                man0, err0 = _read_json(mp)
                if not isinstance(man0, dict):
                    raise SystemExit(f"{mp} is unreadable ({err0 or 'not a JSON object'}); not feeding (restore it from the job dirs or "
                                     "start a new batch name)")
            b = build(batch)
            if b["problems"]:
                raise SystemExit(f"batch {batch}: {len(b['problems'])} check problem(s); nothing submitted:\n" + "\n".join("  " + p for p in b["problems"]))
            for w in b["warnings"]:
                log("WARNING " + w)
            gk = femur_geom_key()
            aux = aux_md5()
            if not mp.exists():
                check_first_start_disk(disk_free_gib())
            man = open_manifest(batch, b, gk, log, aux)
            man["events"].append({"utc": _utc(), "event": "start", "pid": os.getpid()})
            n_rows = len(b["rows"])
            sd = "; ".join(f"seed {s['file']}: {len(s['adopted'])} of {s['n_jobs']} adopted" for s in b["seeds"] if s["present"])
            log(f"batch {batch}: {n_rows} rows; {sum(m['status'] == 'pending' for m in man['rows'].values())} pending, "
                f"{sum(m['status'] == 'existing' for m in man['rows'].values())} existing, {sum(m['status'] == 'held' for m in man['rows'].values())} held"
                f"{'; ' + sd if sd else ''}; femur_geom_key {gk['key']}; aux md5 {json.dumps(man['aux_md5'])}")
            log(f"slow start: layers {list(SLOW_START_LAYERS)} keep at most {SLOW_START_CAP} rows in flight until {SLOW_START_DONE} of their "
                f"rows are DONE; first-10 gate window = rows submitted by this feeder only; heartbeat every {HEARTBEAT_S / 60:g} min")
            idle, announced = 0, set()
            h14_txt, hb_last = None, None
            while True:
                if stop.exists():
                    refresh(man)
                    man["updated_utc"] = _utc()
                    man["events"].append({"utc": _utc(), "event": "stop file"})
                    _write_json(mp, man)
                    log(f"{stop} found: manifest written, exiting cleanly; {json.dumps(_counts(man))}")
                    return 0
                check_code()
                if femur_geom_key()["key"] != man["femur_geom_key"]["key"]:
                    raise SystemExit("femur geometry files changed while feeding (femur_geom_key differs from the manifest); refusing")
                ch = aux_changes(man["aux_md5"], aux_md5())
                if ch:
                    _halt(man, mp, "aux code files changed while feeding (not in code_hash, but they affect results): " + "; ".join(ch)
                          + "; stopped (restore them, or start a new batch name)")
                snap = queue_snapshot()
                refresh(man)
                lost = [m["key"] for m in man["rows"].values() if m["status"] in ("submitted", "existing") and m["state"] == "MISSING"]
                if lost:
                    raise SystemExit(f"job directories vanished from the queue: {lost}")
                if snap["missing"] or snap["unreadable"]:
                    log(f"WARNING queue dirs without a readable spec.json this pass (counted as heavy, busy and, if db_*, unclaimed): "
                        f"missing {snap['missing']}; unreadable {snap['unreadable']}")
                for k in man["order"]:                      # 每个 FAILED 的行记一次（原因来自 FAILED.json）
                    m = man["rows"][k]
                    if m["state"] == "FAILED" and not m.get("failed_logged"):
                        m["failed_logged"] = True
                        log(f"FAILED {k} {m['id']} ({m['layer']}): {_fail_reason(m['id'])}")
                gate_pass(b, man, log)
                h14x, h14_now = h14_mode()
                if h14_now != h14_txt:                      # 模式（与理由）在启动和变化时记一行
                    log(f"FD-0 h1.4 mode: {h14_now}")
                    man["events"].append({"utc": _utc(), "event": "h14_mode", "mode": "exclusive" if h14x else "heavy", "why": h14_now})
                    h14_txt = h14_now
                pending = [m for m in man["rows"].values() if m["status"] == "pending"]
                held = [m for m in man["rows"].values() if m["status"] == "held"]
                sub, waits = [], {}
                if pending:
                    check_disk(disk_free_gib())
                    sub = feed_pass(b, man, snap, log, max_unclaimed, waits, h14_exclusive=h14x)
                refresh(man)
                man["updated_utc"] = _utc()
                _write_json(mp, man)
                t_hb = _mono()
                if hb_last is None or t_hb - hb_last >= HEARTBEAT_S:
                    hb_last = t_hb
                    log(heartbeat_line(man, snap, len(sub), "exclusive" if h14x else "heavy"))
                ms = list(man["rows"].values())
                if all(m["status"] == "blocked" or m["state"] in ("DONE", "FAILED") for m in ms):
                    nb = sum(m["status"] == "blocked" for m in ms)
                    log(f"batch {batch} finished: {json.dumps(_counts(man))}" + (f"; {nb} rows blocked by a FAILED reference" if nb else ""))
                    return 3 if nb else 0
                for rk, w in waits.items():
                    if rk in ANNOUNCE and rk not in announced:
                        announced.add(rk)
                        log(f"WAIT {', '.join(w['keys'])}: {w['text']}")
                if sub:
                    idle = 0
                    log(f"pass: submitted {len(sub)}; {json.dumps(_counts(man))}; unclaimed db_* {len(snap['unclaimed_db']) + len(sub)}")
                elif pending or held:
                    idle += 1
                    if (idle - 1) % WAIT_EVERY == 0:
                        log(wait_line(man, waits, snap, idle))
                if once:
                    return 0
                sleep(poll)
        except SystemExit as e:
            log(f"ERROR refused / stopped: {e.code}")
            raise
        except Exception:
            log("ERROR crashed: " + traceback.format_exc())
            raise


def status(batch: str = "b1") -> None:
    p = manifest_path(batch)
    if not p.exists():
        raise SystemExit(f"{p} does not exist (feed has not started batch {batch})")
    man, err = _read_json(p)
    if not isinstance(man, dict):
        raise SystemExit(f"{p} unreadable ({err or 'not a JSON object'})")
    refresh(man)
    print(f"batch {batch}: manifest updated {man.get('updated_utc')}; {json.dumps(_counts(man))}")
    for slug, g in (man.get("gates") or {}).items():
        if g.get("held"):
            print(f"  HELD layer {g['layer']} since {g['held_utc']}: {'; '.join(g['reasons'])} (release: "
                  f"{_release_hint(J.QROOT.parent / (RELEASE_PREFIX + slug), g.get('kinds') or [], batch)})")
    print(f"  FD-0 h1.4 mode: {h14_mode()[1]}")
    for k in man["order"]:
        m = man["rows"][k]
        print(f"  {k:<34} {m['status']:<9} {str(m['state']):<7} {m['id']}  submitted {m['submitted_utc'] or '-'}  {json.dumps(m['times_utc'])}")
        if m["state"] == "FAILED":
            print(f"      FAILED {_fail_reason(m['id'])}")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="db3406 batch submitter v1.1 (dry-run / feed / status)")
    ap.add_argument("cmd", choices=["dry-run", "feed", "status"])
    ap.add_argument("batch", choices=list(BATCHES))
    ap.add_argument("--root", help="dry-run / status only: read <root>/queue and <root>/results (a read-only copy) instead of ~/mobo_toy_v2")
    ap.add_argument("--once", action="store_true", help="feed only: one pass, then exit")
    ap.add_argument("--poll", type=float, default=POLL_S, help="feed only: seconds between passes (default 60)")
    a = ap.parse_args(argv)
    if a.root:
        if a.cmd == "feed":
            ap.error("--root is for dry-run / status only (the feeder works on the live ~/mobo_toy_v2 queue)")
        J.QROOT, J.RESULTS = pathlib.Path(a.root) / "queue", pathlib.Path(a.root) / "results"
    if a.cmd != "feed" and (a.once or a.poll != POLL_S):
        ap.error("--once / --poll are feed options")
    if a.cmd == "dry-run":
        return dry_run(a.batch)
    if a.cmd == "status":
        status(a.batch)
        return 0
    return feed(a.batch, poll=a.poll, once=a.once)


if __name__ == "__main__":
    sys.exit(main())
