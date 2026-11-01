"""3406 数据库（db3406）的批量提交器 v1.5（D1 = v0 + 审查修正 + 采纳 CD-0 种子 + 第二轮审查修正；D2 = 批次 b2 + 并行喂料；v1.3 = 批次 b1b；v1.4 = 批次 b2b；
v1.5 = 批次 b3 + 已知规律失败的自动确认；v1.6 = 批次 b6（AL-2））。规划：research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md
（第 1.3 / 1.4 节分层与无偏集、第 1.6 节命名 / 查重 / 版本陷阱、第 1.8 节检查 13 / 14、第 2.1–2.7 节、第 3.2 节 CR-T；用户 2026-10-25 批准两天部分）。
不改 8 个哈希文件（code_hash 必须是 6d7af243d0）、不改 jobs.py / stage_neckopt.py / stage_deck.py / stage_v2a.py / tpl_record.py；提交只走 jobs.submit。

    python v2/stage_db.py dry-run b1|b2|b1b|b2b|b3|b4|b5|b6 [--root <只读副本>]  只打印：每个 spec 的键、层、stage、源作业、相对源 spec.json 的变体（键 旧 -> 新）、
                                                          预期 id、查重结果（hash8 / 物理键）、种子采纳、参照与参照核对；末尾 DRY-RUN-JSON。什么都不写
                                                          （b2 另印 G2 核对、CR-1 / CR-T 选点、放宽计数、槽时估计、b1 优先级的当前判断）
    python v2/stage_db.py feed b1|b2 [--once] [--poll 60] 喂料器（只在 Linux 上跑；b1 与 b2 可以同时跑，见"并行喂料"）：
        cd ~/mobo_toy_v2/code && nohup taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed b1 >> ../logs/db_feed.out 2>&1 < /dev/null &
        cd ~/mobo_toy_v2/code && nohup taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed b2 >> ../logs/db_feed_b2.out 2>&1 < /dev/null &
    python v2/stage_db.py status b1|b2 [--root …]         只读：清单 results/db_manifest_<批次>.json + 队列里的状态
    python v2/stage_db.py select b2 [--root …]            写 results/db_crt_selection.json（CR-1 / CR-T 名单，冻结）与 results/db_widened_counts.json；
                                                          不提交（feed b2 第一次启动时也会写选点文件；已有且不同 → 拒绝）

批次 b3（v1.5，2026-10-29，用户批准一周计划 research-log/neck_implant_2026-10-02/3406一周FEA计划_2026-10-29.md 第 3 节；粘接 100 %）= 62 行，全部带粘接：
    CR-T       db_crt  b2 冻结在 results/db_crt_selection.json 的 30 个角落留出设计（不重选；u13 与 cr_points() 逐位核对），参照 sb_intact_h2_9c9d7fb5；
                       source corner_test、selection corner_test，unbiased false、in_E true（A2 的留出测试集）
    NZ-2       db_nz   b2 已 DONE 的 SF-1 6 个 + CR-1 6 个设计（各按 result.json 的 f1_p95_um 分位 (i + 0.5) / 6 取，quantile_pick）× h 1.94 / 2.06，
                       同网格参照 = b1 的 REF_h1.94 / REF_h2.06（必须 DONE）
    FD-1 h1.4  db_fd   B、C、D、a62 + SF-1 4 个（f1 分位 (i + 0.5) / 4，去掉 NZ-2 已选的）× h 1.4（slip_tol = stage_deck.M_SLIP14），参照 b1 的
                       REF_h1.4；重作业（一次一个、旁边可有轻作业；DB_H14_EXCLUSIVE 模式下与 FD-0 h1.4 一样独占），也等 DB_H14_REF_OK
    顺序：CR-T 与 NZ-2 按比例交错，FD-1 再按比例插进去。三层都在 SLOW_START_LAYERS 里。python v2/stage_db.py feed b3（同 b1b 的启动方式）。

批次 b4（v1.5，2026-10-29，同一周计划 b4，并接收从 b3 推来的 BD 次优偏移变体）= 274 行：
    REF        db_ref  起身两档（stage_deck.D13_STS：1714 / 3839 N，前 24°、矢 8°）的 3406 h 2.0 完整股骨参照 = sb_intact_h2_9c9d7fb5 的 spec + cfg.load
                       （重作业，一次一个）；喂料时 REF 行按行键核对计划的作业号（ref_by_key；起身参照与楼梯参照同为 h 2.0）
    CD-1       db_cd   锚点 32 个 = b2 已 DONE 的 SF-1 22 + CR-1 10（f1 分位，去掉 b3 的 NZ-2 / FD-1 已选的）× δ 0.05、δ 0.20（楼梯）、起身 1714、
                       3839（δ 0.10），只解摩擦（粘接与 δ 无关；起身的粘接见 BD sts）；source cond_anchor
    BD sts     db_bo   锚点 × 起身两档的只粘接，参照 = 本批同载荷的 REF；source bond_partner
    CD-1 rand  db_cd   17 维 scrambled Sobol（种子 52401，512 点；u13 全空间 + δ 0.025–0.20 对数均匀、R 1300–3900 N、前 16–24°、矢 4–18°，按
                       CD1R_BOX 的小数位取整）里按 u13 的 0-FE 模板化（results/db_pool/db_cd1r512_s52401.npz，tpl_record batch）可行的前 56 个，
                       各 1 个条件，只解摩擦（SED 要同载荷参照）；source cond_random、selection iid、unbiased true
    BD offset  db_bd   b2 已 DONE、有第二个可用偏移的设计里 e_margin_eff 最小的 SF-1 12 + CR-1 12（SF-1 的模板化记录 = POOL65K 里 u13 逐位相同的那一行，
                       CR-1 = CR_TPL 的 cr_idx 行；prep.json 的 e 必须等于记录的 e*），强制偏移 = 其余可用偏移里 A0 最大的（entry_offset），
                       带粘接（基线载荷，100 %）；source offset_variant（排除集 E）。不是放置误差（规划 1.1）
    顺序：REF 在前；CD-1、CD-1 rand、BD offset、BD sts 按比例交错。新层都在 SLOW_START_LAYERS 里。

批次 b5（v1.5，2026-10-29，同一周计划 AL-1）= stage_al.py 冻结在 results/db_al_al1.json 的 48 个选点（19 优化导向 + 19 全局不确定 + 10 随机），
    各 1 行基线条件、带粘接（stage db_al；spec = Phase(13).spec_of 的物理键，与 SF / CR 同一构造）；稳健问题的选点另加 1 行起身 3839 N
    （只解摩擦，层 AL-1 sts）。核对：选点文件的 essence sha256、每个点的 u13 与它的来源（POOL65K 或 CR_TPL）那一行逐位相同且可行。层 AL-1（opt / global：
    source al_adaptive、selection adaptive、排除集 E）、AL-1 rand（source al_random、selection iid、unbiased true）。b5 在 b4 跑完、
    v0.3 导出后由 stage_al.py 选点再建。
批次 b6（v1.6，2026-11-01，用户 11-01 "继续跑" = 批准 AL-2）= 同一构造读 results/db_al_al2.json（stage_al.py select al2，训练行 = v0.4 导出，
    含 b5 的 54 行）；层 AL-2 / AL-2 sts / AL-2 rand，行键 AL2_<名次>，作业标签 al2_<名次>。b5 的行与作业号不变（AL_BATCHES）。

已知规律失败的自动确认（v1.5，用户 2026-10-29 批准）：按层失败闸门之前，本层每个未确认的 FAILED 行若属于已知规律（known_failure：L4 求解
    "TOO MANY ATTEMPTS" / "TIME INCREMENT … LESS THAN THE MINIMUM" 且 L < 27 mm 或 α < 20° 且 m < 0.6 mm；L3 建模"degenerate tetrahedra"且没有
    "overlapping facets"）→ 自动确认（ack_failed），记 AUTO-ACK 日志与 auto_ack 事件，不停；已因本层失败停着、确认后不再超门槛 → 自动放行。
    本层失败率 > 15 %（AUTO_ACK_MAX_RATE）时不自动确认（像系统性问题），照旧按闸门停。其他失败（如边界网格面片重叠）照旧停住等人。
    "最先 10 行"的批次规则不变。

批次 b2b（v1.4，2026-10-28，用户批准"可以补只粘结作业"）= b2 里每个已 DONE 的只解摩擦设计行（SF-1 / CR-1，含采纳的两臂作业）
    配一个 h 2.0 只粘接作业（层 "BD b2"，stage db_bo，source bond_partner；spec = 源作业的物理键 + bond_only，参照 sb_intact_h2_9c9d7fb5），
    让无偏 / 角落设计都有 SED 与 vM（场级模型要用）。从 results/db_manifest_b2.json 建表：源行还在飞是检查问题（b2 跑完后再建，行集就冻结了）；
    源行 FAILED 或队列里已有可用的 h 2.0 粘接结果的不补。python v2/stage_db.py feed b2b（同 b1b 的启动方式，日志 logs/db_feed_b2b.*）。

批次 b1b（v1.3，2026-10-26）= 粗网格先导换到 h 2.4：b1 的 REF_h2.5 建模失败（L3，松质里 2 个退化四面体；h 2.45 / 2.5 / 2.55 都失败、
    2.4 正常，探针 deck/meshprobe），b1 的 24 行 FD-0 h2.5 被挡住。b1b = REF h 2.4（主会话已提交 db_ref_intact_h2.4_cae476c7，本批采纳；
    results/db_presubmit_REF_h2.4.json）+ 同样 24 个先导设计 × h_int 2.4，带粘接，参照 REF h 2.4（层 "FD-0 h2.4"，source fid_h24）。
    h 2.0 一侧的粘接结果 = 队列里已有的，或 b1 的 BD h2.0 补算（没有就记 WARNING，不补）。b1 的行不变（build 里 full = batch == "b1"）。
    python v2/stage_db.py feed b1b：cd ~/mobo_toy_v2/code && nohup taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed b1b >> ../logs/db_feed_b1b.out 2>&1 < /dev/null &

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

批次 b2 = 规划第 2.4 节的 SF-1 128 + CR-1 32（160 行），基线条件 = PHASES[13]（δ 0.10、楼梯、h_int 2.0、neck_in_shoulder、dense、
ref_cut 16、a_max 2000、3406 isthmus），spec = Phase(13).spec_of(u) 的物理键 + kind variant + stage db_sf / db_cr（不用 sb13：会被阶段 13 收编）。
    SF-1  db_sf  候选池 results/pools/neckopt_p11_n16384_s0_115ae6b5.npz（= gated_pool(Phase(13), 16384, 0)，Sobol 种子 51100）的可行行
                 pool_idx 32..159（Sobol 顺序；0..31 = 32 个初始设计）。source sf、selection iid。层内第 5、10、… 行带粘接（25 行），
                 intact_job sb_intact_h2_9c9d7fb5，其余只解摩擦。采纳：两臂（sb13_a* / sb14_a*）里与某 SF 点"同一设计、同一条件，只差带不带
                 粘接"的作业 → 该行改用那个作业的模型（fric_only 或带粘接），于是物理键查重 existing → 记成那个作业，不再算 FE；
                 manifest 记 sf_bo_overlap 真、bo_twins、adopted_role_from、bonded_planned（原定是否带粘接）；unbiased 假（设计在排除集 E 里，
                 规划 1.4：只进 A3 测试）。两臂状态文件里 pool_idx 落在 32..159 的记录必须正好是被采纳的作业（x 逐位等于池点），否则问题。
    CR-1  db_cr  角落子盒 L 38–45、α 40–45、h_cut 16–18、m 0.5–0.8（其余 9 个全范围）的 4096 个 scrambled Sobol 点（种子 52101，
                 cr_points()：u = a + s·w，阶段 13 的单位坐标），由 tpl_record（0 FE；Linux：tpl_record.py batch --phase 13 --workers 2）
                 模板化为 results/db_pool/db_cr4096_s52101.npz（核对：u13 逐位 = cr_points()、全部算完、0 error、code_hash、选号规则 = 阶段 13）。
                 选点规则 CR_RULE：可行点里离任何已有设计（队列里全部 3406 设计作业 + 本批 SF-1，阶段 13 单位立方体欧氏距离、不截断）
                 ≥ 0.02 的，贪心最大最小，e* = 0 / ≠ 0 交替各 16（第一个点 = e* = 0 组 Sobol 下标最小的候选）。source corner、selection
                 stratum、unbiased 假（在 E 里）。层内第 5、10、… 行带粘接（6 行）。
    CR-T  （不提交）同一贪心最大最小接着选 15 + 15：CR-1 与全部已有设计预先放进"已选"，每次取离它们（和已选的 CR-T）最远的候选；
                 下限 0.02。字面的"离 CR-1 与已有设计都 ≥ CR-1 间距（CR-1 两两最小距离）"在 13 维里是装箱极限、可以一个候选都没有：
                 照算并报告（crt_literal_candidates），不当作选点条件。名单写 results/db_crt_selection.json（select b2，或 feed b2 第一次启动时；
                 同一个文件还冻结 CR-1 名单与当时的"已有设计"清单及其 sha256：重启时按冻结清单重算，名单必须逐项相同；已有 b2 清单而选点
                 文件丢了 → 拒绝，因为从现在的队列重算会把本批自己的作业也当成已有设计）。
    放宽  只做 0-FE 计数（给用户定边界）：α 15–55、m 0.25–2.0（其余同阶段 13）的 4096 个 Sobol 点（种子 52201，wide_points()），两个单 worker
                 进程各算一半（db_wide4096_s52201_a / _b.npz；进程内把 PHASES[99] = 阶段 13 换 α、m 的范围，tpl_record.batch(phase 99)；
                 x13 = wide_physical(u) 核对）。按区域（旧盒内 / 只 α > 45 / 只 m < 0.5 / 两者）与角落（L 38–45、h_cut 16–18、α 40–55、
                 m 0.25–0.8：旧角落子盒内 / 超出旧边界）给 n、可行数、可行率（Wilson 95 %）、e* = 0 占比、A0* 中位，写 results/db_widened_counts.json。
    G2（dry run 与 select 都做；任一条不过 → 问题）：重建 Sobol(13, seed 51100).random(16384)，候选池的 2169 行都逐位在其中、下标递增；
                 6.5 万点池 results/db_pool/pool65k_s51100.npz 在就再核：前 16384 行 u13 = 重建的点，可行下标集合 = 候选池的下标集合；
                 同一种子重放：再生成一次池点、子盒点，再选一次 CR-1 / CR-T，名单逐项相同；CR-T 与 CR-1 不相交。
    顺序（确定、重启幂等）：SF-1 按 pool_idx、CR-1 按最大最小的选择顺序，再按比例交错（SF 第 i 个在 (i+1)/128、CR 第 j 个在 (j+1)/32，
                 相同时 SF 在前）：SF 4 个、CR 1 个、……；键 SF1_p<pool_idx 4 位>、CR1_c<子盒下标 4 位>。清单另记 pool / 模板化文件 /
                 冻结清单的 sha256，重启时不同 → 拒绝。
    槽时（规划成本模型）：新作业 SF 30.75 min、CR 23.25 min，带粘接再加 0.6 min（采纳的不计）；墙钟 = 槽时 ÷ (3 × 85 %)。规划的 30.75 / 23.25
                 已把 20 % × 0.6 摊进去，所以另报一个"粘接在单价里"的口径。

并行喂料（b1 与 b2 同时跑）
    锁：每批一个（b1 = logs/db_feed.lock，与正在跑的 b1 相同；b2 = logs/db_feed_b2.lock）；日志 logs/db_feed.log / logs/db_feed_b2.log；
        STOP_DB_FEED 停全部，STOP_DB_FEED_<批次> 只停那一批。
    全局深度上限：未领取的 db_*（任何批次，NEW + READY）≤ 6，本来就按全部 db_* 数。
    全局提交互斥锁 logs/db_submit.lock：每轮"快照 → 闸门 → 提交 → 写清单"在锁内（120 s 拿不到 → 本轮跳过，记 WARNING）。2026-10-26 01:24 UTC
        起跑的 b1 喂料器是旧代码、不拿这把锁；所以低优先级批次（b2）每轮最多提交 1 个，提交前重新扫一次队列，再核深度与优先级（窗口毫秒级）。
    b1 优先（PRIORITY = {b2: (b1,)}；b4 对 b3 同理，v1.5）：b2 每轮先读 b1 的清单（results/db_manifest_b1.json，只读；没有 = b1 还没启动，按 b1 的作业表现建），
        状态按队列刷新，在副本上跑 b1 的 feed_pass(probe=True)（不提交、不写；同一套闸门：深度、参照、重作业、独占、慢启动、参照优先、h 1.4
        操作员文件）。b1 此刻有可提交的行、b1 的独占行在飞、或 b1 只剩独占行（与依赖它的 h ≤ 1.4 行）且队列一空它就会提交 → b2 本轮不提交
        （最后一种 = 让队列排空，REF_h1.4 才能单独跑）；b1 清单读不了 / 与作业表不符 / 探查会停 → b2 也不提交（WAIT 里有原因）。
        b1 全部 DONE / FAILED / blocked 后不再探查。b1 的 held 行不算可提交。原因变化时记一行 PRIORITY。
    同样的闸门：慢启动（SF-1、CR-1 在 SLOW_START_LAYERS 里）、按层失败闸门与"最先 10 行"（每批各自；DB_RELEASE_SF-1 / DB_RELEASE_CR-1 /
        DB_RELEASE_b2，DB_RELEASE_ALL 对所有批次）、磁盘、aux md5、HEARTBEAT、FAILED 行记录。b2 没有重作业、没有独占行。
    两批里同一物理计算的行 → b2 启动时拒绝（dry run 列为问题）。
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
H14_LAYERS = ("FD-0 h1.4", "FD-1 h1.4")     # 这些层的行在 DB_H14_EXCLUSIVE 模式下也独占
REF_PRIORITY_CAP = 1                        # 参照优先期间其他未领取 db_* 的上限
GATE_MIN_FAILED = 2                         # 按层失败闸门：未确认的 FAILED ≥ 2 …
GATE_MAX_RATE = 0.05                        # … 且失败率 > 5 %
# 已知规律的失败自动确认（用户 2026-10-29 批准，一周计划第 5 节第 2 条）：L4 求解不收敛的短柄（L < 27 mm）或 α、m 都贴下限的设计，
# L3 建模的退化四面体。其余失败（如边界网格面片重叠）照旧停住等人。该层失败率 > AUTO_ACK_MAX_RATE 时也不自动确认（像是系统性问题）。
AUTO_ACK = True
AUTO_ACK_L4_L_MAX = 27.0
AUTO_ACK_L4_LOW = {"alpha": 20.0, "m": 0.6}
AUTO_ACK_L4_TEXT = ("TOO MANY ATTEMPTS", "TIME INCREMENT REQUIRED IS LESS THAN THE MINIMUM")
AUTO_ACK_L3_TEXT = "degenerate tetrahedra"
AUTO_ACK_L3_NOT = "overlapping facets"
AUTO_ACK_MAX_RATE = 0.15
FIRST_N, FIRST_N_MAX_FAILED = 10, 2         # 本批最先完成的 10 个喂料器自己提交的行里 FAILED > 2 → 每层都停（规划 G1）
SLOW_START_LAYERS = ("NZ-1", "FD-0 h2.5", "FD-0 h1.4", "BD mesh", "BD h2.0", "SF-1", "CR-1", "FD-0 h2.4", "BD b2",
                     "CR-T", "NZ-2", "FD-1 h1.4", "CD-1", "CD-1 rand", "BD offset", "BD sts", "AL-1", "AL-1 sts", "AL-1 rand",
                     "AL-2", "AL-2 sts", "AL-2 rand")
                                            # 新层慢启动（REF 串行、CD-0 是种子：不在内）
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
                "BD mesh": "bond_partner", "BD h2.0": "bond_partner", "SF-1": "sf", "CR-1": "corner", "FD-0 h2.4": "fid_h24",
                "BD b2": "bond_partner", "CR-T": "corner_test", "NZ-2": "noise", "FD-1 h1.4": "fid_h14",
                "CD-1": "cond_anchor", "CD-1 rand": "cond_random", "BD offset": "offset_variant", "BD sts": "bond_partner",
                "AL-1": "al_adaptive", "AL-1 sts": "al_adaptive", "AL-1 rand": "al_random",
                "AL-2": "al_adaptive", "AL-2 sts": "al_adaptive", "AL-2 rand": "al_random"}
LAYER_SELECTION = {"REF": "reference", "SF-1": "iid", "CR-T": "corner_test", "CD-1 rand": "iid", "AL-1": "adaptive", "AL-1 sts": "adaptive",
                   "AL-1 rand": "iid", "AL-2": "adaptive", "AL-2 sts": "adaptive", "AL-2 rand": "iid"}          # 其余层 stratum（tools/db_export.DB_STAGE_RULES：db_sf = sf / iid，db_cr = corner / stratum，
                                                # db_crt = corner_test / corner_test，db_bd = offset_variant；AL 的非随机选点在排除集 E）
BATCHES = ("b1", "b2", "b1b", "b2b", "b3", "b4", "b5", "b6")
B2B_SOURCE_BATCHES = ("b2",)                # b2b：这些批次清单里已 DONE 的只解摩擦设计行各配一个 h 2.0 只粘接作业
B2B_LAYER = "BD b2"
B1B_H = 2.4                                 # b1b 的粗网格档（h 2.5 的完整股骨建模失败，见模块说明"批次 b1b"）
B1B_LAYER = "FD-0 h2.4"
SEEDS = {"b1": ("db_seed_CD0.json",)}      # 主会话已提交的种子（results/ 下）：每个种子作业必须被本批一行 1:1 采纳；文件缺失 = 问题（b2 没有种子）
# ---------------------------------------------------------------- 批次 b3（一周计划 2026-10-29 第 3 节，用户 10-29 批准；粘接 100 %）
B3_SOURCE_BATCH = "b2"                      # NZ-2 / FD-1 的 SF-1 与 CR-1 设计：这一批清单里已 DONE 的行
B3_REF_BATCH = "b1"                         # h 1.94 / 2.06 / 1.4 的完整股骨参照：这一批清单里的 REF 行（必须 DONE）
NZ2_H = (1.94, 2.06)
NZ2_PER_LAYER = 6                           # NZ-2：SF-1 6 个 + CR-1 6 个，各按 result.json 的 f1_p95_um 分位 (i + 0.5) / 6 取
FD1_CODES = ("B", "C", "D", "a62")
FD1_SF_N = 4                                # FD-1：另取 SF-1 4 个（f1 分位 (i + 0.5) / 4，去掉 NZ-2 已选的）
# ---------------------------------------------------------------- 批次 b4（一周计划 2026-10-29 第 3 节 b4 + 从 b3 推来的 BD 次优偏移变体；规划 1.1、1.3、3.2）
CD1_ANCHOR_N = {"SF-1": 22, "CR-1": 10}     # CD-1 锚点：b2 已 DONE 的设计按 f1 分位取（去掉 b3 已选的）
CD1_DELTA = (0.05, 0.20)                    # 锚点 × δ（楼梯，只解摩擦）；锚点 × 起身两档 STS_LOADS（δ 0.10，只解摩擦）+ 同载荷只粘接
CD1R_N, CD1R_POINTS, CD1R_SOBOL_SEED = 56, 512, 52401   # CD-1 随机条件：17 维 scrambled Sobol（u13 + 4 个条件，独立种子），只按 u13 的
                                                        # 模板化判可行，按 Sobol 顺序取前 56 个可行
CD1R_TPL = "db_pool/db_cd1r512_s52401.npz"  # results/ 下：tpl_record batch --phase 13 对 cd1r_points()[:, :13] 的输出（0 FE）
CD1R_BOX = (("delta", 0.025, 0.20, "log", 4), ("resultant_N", 1300.0, 3900.0, "lin", 1),
            ("alpha_front_deg", 16.0, 24.0, "lin", 2), ("alpha_sagit_deg", 4.0, 18.0, "lin", 2))   # (名, 下, 上, 刻度, 小数位)：规划 1.1 的条件框
BD_N = {"SF-1": 12, "CR-1": 12}             # 次优偏移变体：b2 已 DONE、有第二个可用偏移的设计里 e_margin_eff 最小的；强制偏移 = 其余可用偏移里
                                            # A0 最大的（规划 1.1 第 3 条：同一个 x 在两支上都有标签；不是放置误差）
U65K = "db_pool/U65536_s51100.npy"          # results/ 下：6.5 万点池的单位坐标（POOL65K 的 u13 必须逐位等于它）
# ---------------------------------------------------------------- 批次 b5（一周计划第 3 节 AL-1；规划 3.4）：读 stage_al.py 冻结的选点文件
AL_BATCHES = {"b5": ("al1", "AL-1", "AL1"), "b6": ("al2", "AL-2", "AL2")}   # 批次 -> (stage_al 轮 = results/db_al_<轮>.json, 层前缀, 行键前缀)
AL_STS = "F3839"                            # 稳健问题的选点另加一行起身 3839 N（δ 0.10，只解摩擦），验收稳健目标用

# ---------------------------------------------------------------- 批次 b2（规划 1.3 / 1.4、2.2 D2、2.4 SF-1 / CR-1、3.2 CR-T、2.5 放宽计数）
B2_PHASE = 13                               # 基线条件 = PHASES[13]（δ 0.10、楼梯、h_int 2.0、neck_in_shoulder、dense、ref_cut 16、a_max 2000）
POOL_N, POOL_SEED_ARG = 16384, 0            # 候选池 = stage_neckopt.gated_pool(Phase(13), 16384, 0) 的文件（pool_phase 11）
POOL_NAME = "neckopt_p11_n16384_s0_115ae6b5.npz"   # results/pools/ 下；= SN.pool_file(Phase(13), 16384, 0).name（build 核对）
POOL_SOBOL_SEED = 51100                     # = 50 000 + 100 × 11 + 0（stage_neckopt.gated_pool 的种子规则）
POOL65K = "db_pool/pool65k_s51100.npz"      # 6.5 万点模板化池（tpl_record，同一种子）：在就用它的前 16384 行再核一次可行性（只读）
N_INIT = 32                                 # pool_idx 0..31 = 阶段 13 的 32 个初始设计
SF1_RANGE = (32, 160)                       # SF-1 = 可行行 pool_idx 32..159（128 个，Sobol 顺序）
BOND_EVERY = 5                              # 每层按层内顺序第 5、10、… 个带粘接（= stage_neckopt.next_bonded，用户 10-23 的 20 % 规则）
ARM_PREFIXES = ("sb13_a", "sb14_a")         # 两臂的 BO 作业：SF 点与它们物理相同（只差粘接与否）→ 采纳，sf_bo_overlap
CR_BOX = {"L": (38.0, 45.0), "alpha": (40.0, 45.0), "h_cut": (16.0, 18.0), "m": (0.5, 0.8)}   # 角落子盒；其余 9 个变量全范围
CR_N, CR_SOBOL_SEED = 4096, 52101           # 子盒 Sobol（scrambled）点数与种子（独立种子，不由数据决定）
CR_TPL = "db_pool/db_cr4096_s52101.npz"     # results/ 下：tpl_record batch --phase 13 对 cr_points() 的输出（0 FE）
CR1_QUOTA = (16, 16)                        # CR-1：e* = 0 / e* ≠ 0 各 16
CRT_QUOTA = (15, 15)                        # CR-T：同一规则 15 / 15（30 个，第 1 周的留出角落测试集，b2 不提交）
CR_EXCL_R = 0.02                            # 候选离任何已有设计（单位坐标欧氏距离）< 0.02 → 去掉（近重复）
WIDE_BOX = {"alpha": (15.0, 55.0), "m": (0.25, 2.0)}   # 放宽边界（其余同阶段 13）：只做 0-FE 计数，给用户定边界
WIDE_N, WIDE_SOBOL_SEED = 4096, 52201
WIDE_TPL = "db_pool/db_wide4096_s52201.npz"  # results/ 下：tpl_record 对 wide_points() 的输出（放宽空间的单位坐标；x13 = 物理值）
CRT_FILE = "db_crt_selection.json"          # results/ 下：CR-1 / CR-T 名单与冻结的"已有设计"清单（select / feed 第一次启动写）
WIDE_COUNTS_FILE = "db_widened_counts.json"  # results/ 下：放宽边界的分区计数（select 写）
COST_MIN = {"SF-1": 30.75, "CR-1": 23.25}   # 规划成本模型：每个作业的槽时（min）；带粘接再加 BOND_MIN
BOND_MIN = 0.6
SLOTS, UPTIME = 3, 0.85                     # 墙钟 = 槽时 ÷ (3 槽 × 85 %)
PRIORITY = {"b2": ("b1",), "b4": ("b3",)}   # b2 只在 b1、b4 只在 b3 此刻没有可提交的行时提交（见模块说明"并行喂料"）
LOW_MAX_SUBMIT = 1                          # 低优先级批次每轮最多提交 1 个，提交前重新核对深度与优先级
SUBMIT_LOCK_TIMEOUT_S = 120.0               # 全局提交互斥锁 logs/db_submit.lock 的等待上限（拿不到 → 本轮跳过，记 WARNING）
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
    elif expect == "b2row":                             # b3 的源：b2 的 SF-1 / CR-1 基线行（stage db_sf / db_cr 的 variant，h 2.0，楼梯）
        if src.get("kind") != "variant" or str(src.get("stage")) not in ("db_sf", "db_cr") or src.get("femur_id") != FEMUR_ID \
                or src.get("h_int") != H_PROD or src.get("cfg") or src.get("bond_only"):
            why.append(f"kind {src.get('kind')!r} stage {src.get('stage')!r} femur_id {src.get('femur_id')!r} h_int {src.get('h_int')!r} "
                       f"cfg {src.get('cfg')!r} bond_only {src.get('bond_only')!r} (want a b2 SF-1 / CR-1 baseline row)")
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
            "selection": LAYER_SELECTION.get(layer, "stratum"), "design_code": code, "source_job": source_job,
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
    if batch == "b2":
        return build_b2()
    if batch == "b2b":
        return build_b2b()
    if batch == "b3":
        return build_b3()
    if batch == "b4":
        return build_b4()
    if batch in AL_BATCHES:
        return build_b5(batch)
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

    full = batch == "b1"                                # b1b：只有 REF h 2.4 与 FD-0 h 2.4（b1 的其余层不建）
    # REF：sb_intact_h2_9c9d7fb5 的 spec 只改 h_int
    ref_src = load_source(REF_H2, "intact", qspecs)
    ref_phys = _phys(ref_src, REF_H2)
    ref_id, ref_key_of = {H_PROD: REF_H2}, {}
    for h in (REF_H if full else (B1B_H,)):
        spec = {**copy.deepcopy(ref_phys), "kind": "intact", "h_int": h, "stage": "db_ref", "tag": f"intact_h{h:g}"}
        k = f"REF_h{h:g}"
        rows.append(_row(k, "REF", spec, REF_H2))
        ref_id[h] = resolve(spec, by_h8, qspecs, by_phys)[0]
        ref_key_of[h] = k
    # CD-0 δ（只解摩擦）
    for c in (CD_PAIR_CODES if full else ()):
        for dl in CD_DELTA_PAIR:
            spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_d{dl:g}", "fric", delta=dl)
            rows.append(_row(f"CD0_d{dl:g}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    for c in (CD_ALL_CODES if full else ()):
        spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_d{CD_DELTA_ALL:g}", "fric", delta=CD_DELTA_ALL)
        rows.append(_row(f"CD0_d{CD_DELTA_ALL:g}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    # CD-0 起身（只解摩擦；cfg.load = stage_deck.D13_STS 原样）
    for c in (STS_CODES if full else ()):
        for ln, L in STS_LOADS.items():
            spec = _variant(phys[c], "db_cd", f"{_tag_of(jobs_of[c])}_{ln}", "fric", cfg={"load": dict(L)})
            rows.append(_row(f"CD0_sts{ln[1:]}_{c}", "CD-0", spec, jobs_of[c], c, extra=info(c)))
    # NZ-1（带粘接，同网格参照）
    for c in (NZ_CODES if full else ()):
        for h in NZ_H:
            spec = _variant(phys[c], "db_nz", f"{_tag_of(jobs_of[c])}_h{h:g}", "full", intact_job=ref_id[h], h_int=h)
            rows.append(_row(f"NZ1_h{h:g}_{c}", "NZ-1", spec, jobs_of[c], c, ref_key=ref_key_of[h], extra=info(c)))
    # FD-0 h 2.5 先导（24）与 h 1.4（2），带粘接
    fd25 = list(FD25_CODES) + list(PILOT16)
    for c in (fd25 if full else ()):
        spec = _variant(phys[c], "db_fd", f"{_tag_of(jobs_of[c])}_h2.5", "full", intact_job=ref_id[2.5], h_int=2.5)
        rows.append(_row(f"FD0_h2.5_{c}", "FD-0 h2.5", spec, jobs_of[c], c, ref_key=ref_key_of[2.5], extra=info(c)))
    for c in (() if full else fd25):                     # b1b：同样 24 个先导设计 × h 2.4，带粘接，参照 REF h 2.4
        spec = _variant(phys[c], "db_fd", f"{_tag_of(jobs_of[c])}_h{B1B_H:g}", "full", intact_job=ref_id[B1B_H], h_int=B1B_H)
        rows.append(_row(f"FD0_h{B1B_H:g}_{c}", B1B_LAYER, spec, jobs_of[c], c, ref_key=ref_key_of[B1B_H], extra=info(c)))
    for c in (FD14_CODES if full else ()):
        spec = _variant(phys[c], "db_fd", f"{_tag_of(jobs_of[c])}_h1.4", "full", intact_job=ref_id[1.4], h_int=1.4, slip_tol=H14_SLIP_TOL)
        rows.append(_row(f"FD0_h1.4_{c}", "FD-0 h1.4", spec, jobs_of[c], c, ref_key=ref_key_of[1.4], extra=info(c)))
    # BD (i)：现有只解摩擦的网格变体的同网格 bond_only（stage db_bo）
    others = sorted(n for n, sp in qspecs.items() if sp and not n.startswith("db_") and sp.get("femur_id") == FEMUR_ID and sp.get("fric_only")
                    and sp.get("kind") in ("design", "variant") and sp.get("h_int") != H_PROD and n not in MESH_SOURCES)
    if others and full:
        warn.append(f"fric_only 3406 mesh variants in the queue that MESH_SOURCES does not cover (no bond_only partner in this batch): {others}")
    for j in (MESH_SOURCES if full else ()):
        s_ = load_source(j, "mesh", qspecs)
        h = float(s_["h_int"])
        if h not in ref_id:
            raise SystemExit(f"mesh source {j}: h_int {h:g} has no db_ref in this batch (REF_H {REF_H})")
        spec = _variant(_phys(s_, j), "db_bo", _tag_of(j), "bond", intact_job=ref_id[h])
        rows.append(_row(f"BD_mesh_{_tag_of(j)}", "BD mesh", spec, j, None, ref_key=ref_key_of[h], extra={"partner_of": j}))
    # BD (i')：v3406 噪声设计的 h 2.0 bond_only（源 = h 2.0 只解摩擦孪生；物理 spec 必须 = 两个噪声网格源只改 h_int）
    if full and NOISE_H2_PARTNER:
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
    b1_ids = {} if full else recorded_ids("b1")[0]       # b1b：h 2.0 一侧也可以是 b1 的 BD h2.0 补算（db_bo，usable_bonded_h2 不看 db_*）
    for c in fd25:
        have = usable_bonded_h2(src[c], qspecs, warn, idents)
        if not full:
            bo = b1_ids.get(f"BD_h2_{c}")
            if bo and J.state(J.QROOT / bo) == "DONE":
                have = list(have) + [bo]
            partner_info[c] = have
            if not have:
                warn.append(f"FD0_h{B1B_H:g}_{c}: the h 2.0 side has no bonded result (no usable job, no DONE b1 BD_h2_{c}); "
                            "its SED / vM pair is missing (not added here)")
            continue
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
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: refs_in_batch.get(j) or _spec_of(j, qspecs), h14_ref=ref_id.get(1.4))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds(batch, rows, qspecs)
    problems += seed_probs
    ids = {r["id"] for r in rows} | {r["expected_id"] for r in rows}
    other = set()                                       # 别的批次清单里记下的作业（b2 的 db_sf / db_cr）不算"不是本批的 db_* 目录"
    for ob in BATCHES:
        if ob != batch:
            other |= {v for v in recorded_ids(ob)[0].values() if v}
    stray = sorted(n for n in qspecs if n.startswith("db_") and n not in ids and n not in other and not n.startswith(("db_sf_", "db_cr_")))
    if stray:
        warn.append(f"db_* queue dirs that are not rows of batch {batch}: {stray}")
    n_partner = sum(r["layer"] == "BD h2.0" for r in rows)
    return {"batch": batch, "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(), "init_median": med,
            "pilot16": pilot16, "ref_id": {f"{h:g}": v for h, v in ref_id.items()}, "partners": partner_info, "n_partner": n_partner,
            "seeds": seeds, "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


# ================================================================ 批次 b2：点集（Sobol 种子 → 单位坐标；与 tpl_record 的输入逐位相同）
def _np():
    import numpy as np
    return np


def sobol(n: int, seed: int, d: int = 13):
    """scipy.stats.qmc.Sobol(d, scramble=True, seed=seed).random(n)（= stage_neckopt.gated_pool 的取法）。"""
    from scipy.stats import qmc
    return qmc.Sobol(d, scramble=True, seed=seed).random(n)


def b2_phase():
    return SN.Phase(B2_PHASE)


def _box_affine(space: dict, box: dict, vars_: list):
    """子盒 box（物理范围，没写的变量 = 全范围）在 space 的单位坐标里的 u = a + s·w（全范围的变量 a = 0、w = 1：u 就是 s 本身）。"""
    np = _np()
    a, w = np.zeros(len(vars_)), np.ones(len(vars_))
    for i, k in enumerate(vars_):
        if k in box:
            lo, hi = space[k]
            blo, bhi = box[k]
            if not (lo - 1e-12 <= blo < bhi <= hi + 1e-12):
                raise SystemExit(f"sub-box {k} {box[k]} is not inside the phase range {space[k]}")
            a[i], w[i] = (blo - lo) / (hi - lo), (bhi - blo) / (hi - lo)
    return a, w


def cr_points():
    """角落子盒的 CR_N 个 scrambled Sobol 点（种子 CR_SOBOL_SEED），换成阶段 13 的单位坐标（列序 = Phase(13).vars）。"""
    ph = b2_phase()
    a, w = _box_affine(ph.space, CR_BOX, ph.vars)
    return a + sobol(CR_N, CR_SOBOL_SEED, len(ph.vars)) * w


def wide_space() -> dict:
    """放宽后的设计空间：阶段 13 的变量，α、m 换成 WIDE_BOX。"""
    return {**b2_phase().space, **WIDE_BOX}


def wide_points():
    """放宽空间的 WIDE_N 个 scrambled Sobol 点（种子 WIDE_SOBOL_SEED；放宽空间的单位坐标，列序 = Phase(13).vars）。"""
    return sobol(WIDE_N, WIDE_SOBOL_SEED, len(b2_phase().vars))


def wide_physical(U):
    """放宽空间的单位坐标 → 物理值（N × 13，列序 = Phase(13).vars；= 把 WIDE_BOX 代进 PHASES 后 Phase.design_of 的换算）。"""
    np = _np()
    ws, vars_ = wide_space(), b2_phase().vars
    lo = np.array([ws[k][0] for k in vars_])
    hi = np.array([ws[k][1] for k in vars_])
    return lo + np.asarray(U, float) * (hi - lo)


WIDE_PARTS = ((WIDE_TPL.replace(".npz", "_a.npz"), 0, 2048), (WIDE_TPL.replace(".npz", "_b.npz"), 2048, 4096))   # 两个进程各算一半（≤ 2 个 worker）


def _sha256_path(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- b2：候选池与 G2 核对
def load_pool() -> dict:
    """阶段 13 的候选池文件（= gated_pool(Phase(13), 16384, 0) 读的那个）：可行行（Sobol 顺序）的单位坐标与去骨量。
    文件名与 SN.pool_file 不同 / 文件缺失 / 旁边的 json 与 npz 不符 → SystemExit。"""
    np = _np()
    ph = b2_phase()
    want = SN.pool_file(ph, POOL_N, POOL_SEED_ARG)
    if want.name != POOL_NAME:
        raise SystemExit(f"pool: stage_neckopt.pool_file(Phase(13), {POOL_N}, {POOL_SEED_ARG}) is {want.name}, not the pinned {POOL_NAME} "
                         "(pool key changed: code hash, space or phase settings); refusing")
    p = J.RESULTS / "pools" / POOL_NAME
    if not p.exists():
        raise SystemExit(f"pool file {p} is missing (SF-1 takes its feasible rows in Sobol order)")
    with np.load(p, allow_pickle=False) as z:
        U, loss = np.asarray(z["U"], float), np.asarray(z["loss"], float)
    meta, err = _read_json(p.with_suffix(".json"))
    if not isinstance(meta, dict):
        raise SystemExit(f"pool meta {p.with_suffix('.json')} unreadable ({err or 'missing'})")
    bad = [f"{k} {meta.get(k)!r} != {v!r}" for k, v in (("phase", 11), ("n", POOL_N), ("seed", POOL_SEED_ARG), ("feasible", len(U)))
           if meta.get(k) != v]
    if bad or U.shape != (len(U), len(ph.vars)) or len(loss) != len(U):
        raise SystemExit(f"pool {p.name}: meta / arrays do not match ({'; '.join(bad) or 'array shapes'})")
    if len(U) < SF1_RANGE[1]:
        raise SystemExit(f"pool {p.name}: {len(U)} feasible rows < {SF1_RANGE[1]} (SF-1 needs pool_idx {SF1_RANGE[0]}..{SF1_RANGE[1] - 1})")
    return {"U": U, "loss": loss, "file": p.name, "sha256": _sha256_path(p), "meta": meta}


def g2_pool_check(pool: dict) -> dict:
    """G2（规划 2.2 D2 / 2.7）：按种子 POOL_SOBOL_SEED 重建 16384 个 Sobol 点，候选池的每个可行行必须逐位等于其中一点，且下标严格递增
    （= 可行行按 Sobol 顺序）；6.5 万点模板化池（POOL65K，在就核）的前 16384 行 u13 必须逐位等于重建的点，其可行行的下标集合必须等于
    候选池的那些下标（两次独立的模板化给出同一个可行集）。返回 {"ok", "problems", ...}。"""
    np = _np()
    D = sobol(POOL_N, POOL_SOBOL_SEED, pool["U"].shape[1])
    idx = {D[i].tobytes(): i for i in range(len(D))}
    pos = [idx.get(np.ascontiguousarray(u).tobytes()) for u in pool["U"]]
    missing = [i for i, q in enumerate(pos) if q is None]
    incr = not missing and all(pos[i] < pos[i + 1] for i in range(len(pos) - 1))
    probs = []
    if missing:
        probs.append(f"G2: {len(missing)} pool rows are not bit-identical to any point of the regenerated Sobol draw (seed {POOL_SOBOL_SEED}); "
                     f"first pool_idx {missing[:5]}")
    elif not incr:
        probs.append("G2: the pool rows are not in Sobol order (their indices in the regenerated draw are not increasing)")
    out = {"seed": POOL_SOBOL_SEED, "n_draw": POOL_N, "n_pool": len(pos), "all_found": not missing, "increasing": incr,
           "sobol_index_of_pool_idx0": pos[0] if pos else None, "sobol_index_of_last": pos[-1] if pos else None,
           "sobol_index_sf1": [pos[SF1_RANGE[0]], pos[SF1_RANGE[1] - 1]] if not missing else None}
    f65 = J.RESULTS / POOL65K
    if f65.exists():
        try:
            with np.load(f65, allow_pickle=False) as z:
                u65, feas, done, errf = z["u13"][:POOL_N], z["feasible"][:POOL_N], z["done"][:POOL_N], z["error"][:POOL_N]
                meta65 = json.loads(str(z["meta_json"]))
        except (OSError, ValueError, KeyError) as e:
            probs.append(f"G2: {f65} unreadable ({type(e).__name__}: {e})")
        else:
            same_u = bool(np.array_equal(u65, D))
            fp = np.flatnonzero(feas & done & ~errf).tolist()
            same_f = (not missing) and fp == pos
            out["pool65k"] = {"file": POOL65K, "complete": meta65.get("complete"), "n": meta65.get("n"), "prefix_u13_equal": same_u,
                              "n_done_prefix": int(done.sum()), "n_error_prefix": int(errf.sum()), "feasible_prefix": len(fp),
                              "feasible_index_set_equal": same_f,
                              "only_in_pool": len(set(p_ for p_ in pos if p_ is not None) - set(fp)), "only_in_65k": len(set(fp) - set(pos))}
            if not same_u:
                probs.append(f"G2: {POOL65K} rows 0..{POOL_N - 1} are not the regenerated Sobol draw (seed {POOL_SOBOL_SEED})")
            elif not done.all() or errf.any():
                probs.append(f"G2: {POOL65K} prefix has {int((~done).sum())} rows not done and {int(errf.sum())} error rows")
            elif not same_f:
                probs.append(f"G2: {POOL65K} feasible rows in the first {POOL_N} ({len(fp)}) differ from the pool's {len(pos)} "
                             f"({out['pool65k']['only_in_pool']} only in the pool, {out['pool65k']['only_in_65k']} only in the 65k file)")
    else:
        out["pool65k"] = {"file": POOL65K, "present": False}
    out["ok"] = not probs
    out["problems"] = probs
    return out


# ---------------------------------------------------------------- b2：tpl_record 文件
def _tpl_rule_expect() -> dict:
    ph = b2_phase()
    import stage_v2a as S2
    return {"femur_id": ph.femur_id, "neck_axis": ph.neck_axis, "margin_check": ph.margin_check, "a_bounds_max": ph.a_bounds_max,
            "ref_cut_mm": float(ph.ref_cut_mm), "min_A0": float(S2.MIN_A0)}


def load_tpl(rel: str, U_expect, phys_expect=None, rows: tuple | None = None) -> dict:
    """tpl_record batch 的输出（results/<rel>）。核对：工具与格式、全部算完、没有 error 行、code_hash、选号规则（= 阶段 13）、
    变量顺序、u13 逐位等于 U_expect（由种子重建的点）、x13 = phys_expect（给了时；放宽空间的物理值）。不符 → SystemExit。"""
    np = _np()
    p = J.RESULTS / rel
    if not p.exists():
        raise SystemExit(f"templating file {p} is missing (0-FE tpl_record run; see the module docstring 'b2 inputs')")
    try:
        with np.load(p, allow_pickle=False) as z:
            d = {k: z[k] for k in z.files}
        meta = json.loads(str(d.pop("meta_json")))
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"templating file {p} unreadable ({type(e).__name__}: {e})") from None
    why = []
    if meta.get("tool") != "tpl_record" or meta.get("format") != 2:
        why.append(f"tool / format {meta.get('tool')}/{meta.get('format')} (want tpl_record/2)")
    if not meta.get("complete") or not bool(np.all(d["done"])):
        why.append(f"incomplete ({int(np.sum(d['done']))}/{len(d['done'])} done)")
    if bool(np.any(d["error"])):
        why.append(f"{int(np.sum(d['error']))} error rows")
    prov = meta.get("provenance") or {}
    if prov.get("code_hash") != DB_CODE_HASH:
        why.append(f"provenance code_hash {prov.get('code_hash')!r} != {DB_CODE_HASH}")
    rule = meta.get("rule") or {}
    exp = _tpl_rule_expect()
    rd = [f"{k} {rule.get(k)!r} != {v!r}" for k, v in exp.items() if _norm(rule.get(k)) != _norm(v)]
    if rd:
        why.append("rule differs from phase 13: " + "; ".join(rd))
    if list(map(str, d["var_names"])) != list(b2_phase().vars):
        why.append(f"var_names {list(map(str, d['var_names']))} != Phase(13).vars")
    if d["u13"].shape != np.shape(U_expect) or not np.array_equal(d["u13"], U_expect):
        why.append("u13 is not the point list regenerated from the seed" + (f" (rows {rows[0]}..{rows[1] - 1})" if rows else ""))
    if phys_expect is not None and (d["x13"].shape != np.shape(phys_expect) or not np.allclose(d["x13"], phys_expect, rtol=0, atol=1e-9)):
        why.append("x13 (physical values) differ from the widened-box mapping")
    if why:
        raise SystemExit(f"templating file {p}: " + "; ".join(why))
    d.update(meta=meta, file=rel, sha256=_sha256_path(p))
    return d


# ---------------------------------------------------------------- b2：已有设计、距离、最大最小选点
def unit13(design: dict, h_cut: float, space: dict | None = None) -> list:
    """设计 → 阶段 13 的单位坐标（不截断：盒外的设计照实给出 < 0 或 > 1 的值）。缺变量 → KeyError。"""
    ph = b2_phase()
    sp = space or ph.space
    out = []
    for k in ph.vars:
        v = float(h_cut) if k == "h_cut" else float(design[k])
        lo, hi = sp[k]
        out.append((v - lo) / (hi - lo))
    return out


def evaluated_designs(qspecs: dict, warn: list) -> list:
    """队列里所有 3406 设计作业（kind design / variant、femur_id sawbone3406、有 design、不是 import_stem；任何 stage、任何状态，失败的也算）
    的不同设计：[{"u13": [...], "jobs": [...]}]（按 u13 排序，确定）。"""
    by = {}
    for n in sorted(qspecs):
        sp = qspecs[n]
        if sp is None or sp.get("kind") not in ("design", "variant") or sp.get("femur_id") != FEMUR_ID or sp.get("import_stem"):
            continue
        d = sp.get("design")
        if not isinstance(d, dict):
            continue
        try:
            u = tuple(unit13(d, float(sp.get("h_cut", 25.0))))
        except (KeyError, TypeError, ValueError) as e:
            warn.append(f"evaluated designs: {n} has no 13-variable design ({type(e).__name__}: {e}); not used for the CR distances")
            continue
        by.setdefault(u, []).append(n)
    return [{"u13": list(u), "jobs": js} for u, js in sorted(by.items())]


def _dist_to(A, B, chunk: int = 256):
    """A (n × d) 每行到 B (m × d) 的最近欧氏距离（m = 0 → inf）；按块算（内存 ≤ chunk × m × d）。"""
    np = _np()
    A, B = np.asarray(A, float), np.asarray(B, float)
    if len(B) == 0:
        return np.full(len(A), np.inf)
    out = np.empty(len(A))
    for i in range(0, len(A), chunk):
        out[i:i + chunk] = np.sqrt(((A[i:i + chunk, None, :] - B[None, :, :]) ** 2).sum(-1)).min(1)
    return out


def maximin_select(U, idx: list, group, quota: tuple, pre=None) -> list:
    """贪心最大最小（规则见 CR_RULE）：候选 idx（升序 = Sobol 顺序），两组（group[i] = 0 → e* = 0，1 → e* ≠ 0）按 0, 1, 0, 1 … 交替
    （一组配额满了就只取另一组）；每一步在该组的候选里取"到已选点（与预先放好的点 pre）的最近距离"最大的那个（平手取下标小的）；
    没有 pre 时第一个点 = 第 0 组下标最小的候选。某组候选不够 → SystemExit。返回选中的下标（选择顺序）。"""
    np = _np()
    U = np.asarray(U, float)
    idx = sorted(int(i) for i in idx)
    cand = {0: [i for i in idx if group[i] == 0], 1: [i for i in idx if group[i] == 1]}
    for g in (0, 1):
        if len(cand[g]) < quota[g]:
            raise SystemExit(f"maximin: group {g} ({'e* = 0' if g == 0 else 'e* != 0'}) has {len(cand[g])} candidates < quota {quota[g]}")
    need = list(quota)
    sel = []
    has_pre = pre is not None and len(pre) > 0
    dmin = {g: (_dist_to(U[cand[g]], pre) if has_pre and len(cand[g]) else np.full(len(cand[g]), np.inf)) for g in (0, 1)}
    taken = {g: np.zeros(len(cand[g]), bool) for g in (0, 1)}
    turn = 0
    while need[0] + need[1] > 0:
        g = turn if need[turn] > 0 else 1 - turn
        turn = 1 - turn
        if not sel and not has_pre:
            j = 0
        else:
            score = np.where(taken[g], -1.0, dmin[g])
            j = int(np.argmax(score))
        i = cand[g][j]
        taken[g][j] = True
        need[g] -= 1
        sel.append(i)
        for h in (0, 1):
            if len(cand[h]):
                dmin[h] = np.minimum(dmin[h], np.sqrt(((U[cand[h]] - U[i]) ** 2).sum(1)))
    return sel


def min_pairwise(U) -> float:
    np = _np()
    U = np.asarray(U, float)
    if len(U) < 2:
        return math.inf
    D = np.sqrt(((U[:, None, :] - U[None, :, :]) ** 2).sum(-1))
    return float(D[np.triu_indices(len(U), 1)].min())


CR_RULE = ("CR candidates = feasible rows (tpl_record feasible, no error) of the CR_N-point scrambled Sobol sample of the corner sub-box "
           "(seed CR_SOBOL_SEED), whose Euclidean distance in the phase-13 unit cube (13 columns = Phase(13).vars, all designs unclipped) "
           "to every evaluated design (each 3406 design job in the queue, any stage / state, plus the SF-1 designs of this batch) is >= "
           "CR_EXCL_R. CR-1 = greedy maximin among them, groups e* == 0 / e* != 0 alternating 0, 1, 0, 1, ... (16 + 16); each step takes the "
           "candidate of the group with the largest distance to the points already chosen (ties: lowest Sobol index); the first point is the "
           "lowest-index candidate of group 0. CR-1 spacing = min pairwise distance in CR-1. CR-T = the same greedy maximin (15 + 15, "
           "alternating) continued on the remaining feasible rows with CR-1 and every evaluated design pre-placed: each CR-T point is the "
           "candidate farthest from CR-1, the evaluated designs and the CR-T points already chosen; hard floor CR_EXCL_R to CR-1 and to the "
           "evaluated designs. The literal requirement 'distance >= the CR-1 spacing to CR-1 and to every evaluated design' is checked and "
           "reported (crt_literal_candidates); in 13 dimensions it is a packing limit and can have no candidate at all.")


def cr_select(tpl: dict, evaluated_u, U=None) -> dict:
    """CR-1 与 CR-T（规则 CR_RULE）。evaluated_u：已有设计的单位坐标（含本批 SF-1）。返回名单与统计（纯计算，不写文件）。"""
    np = _np()
    U = np.asarray(tpl["u13"] if U is None else U, float)
    feas = np.asarray(tpl["feasible"], bool) & ~np.asarray(tpl["error"], bool)
    e = np.asarray(tpl["e_star"], float)
    group = np.where(e == 0.0, 0, 1)
    E = np.asarray(evaluated_u, float).reshape(-1, U.shape[1])
    d_ev = _dist_to(U, E)
    fe = np.flatnonzero(feas)
    near = fe[d_ev[fe] < CR_EXCL_R]
    c1 = fe[d_ev[fe] >= CR_EXCL_R]
    cr1 = maximin_select(U, c1.tolist(), group, CR1_QUOTA)
    spacing = min_pairwise(U[cr1])
    d_c1 = _dist_to(U, U[cr1])
    rest = np.array(sorted(set(fe.tolist()) - set(cr1)), int)
    ok_t = rest[(d_c1[rest] >= CR_EXCL_R) & (d_ev[rest] >= CR_EXCL_R)] if len(rest) else rest
    lit = rest[(d_c1[rest] >= spacing) & (d_ev[rest] >= spacing)] if len(rest) else rest
    stats = {"n": int(len(U)), "feasible": int(feas.sum()), "feasible_e0": int((feas & (group == 0)).sum()),
             "feasible_e_ne0": int((feas & (group == 1)).sum()), "excluded_near_evaluated": int(len(near)),
             "excluded_near_jobs_idx": near.tolist(), "cr1_candidates": int(len(c1)), "cr1_candidates_e0": int((group[c1] == 0).sum()),
             "cr1_spacing": spacing, "crt_candidates": int(len(ok_t)), "crt_candidates_e0": int((group[ok_t] == 0).sum()) if len(ok_t) else 0,
             "crt_literal_candidates": int(len(lit)), "crt_literal_candidates_e0": int((group[lit] == 0).sum()) if len(lit) else 0,
             "crt_literal_feasible": bool((group[lit] == 0).sum() >= CRT_QUOTA[0] and (group[lit] == 1).sum() >= CRT_QUOTA[1]) if len(lit) else False,
             "n_evaluated": int(len(E))}
    try:
        crt = maximin_select(U, ok_t.tolist(), group, CRT_QUOTA, pre=np.vstack([U[cr1], E]))
        crt_err = None
    except SystemExit as ex:
        crt, crt_err = [], f"CR-T: {ex.code} (candidates at distance >= {CR_EXCL_R} from CR-1 and from every evaluated design)"
    stats.update(crt_spacing_own=min_pairwise(U[crt]) if crt else None,
                 crt_min_dist_cr1=float(d_c1[crt].min()) if crt else None, crt_min_dist_evaluated=float(d_ev[crt].min()) if crt else None,
                 crt_min_dist_ratio_to_cr1_spacing=float(min(d_c1[crt].min(), d_ev[crt].min()) / spacing) if crt else None,
                 cr1_min_dist_evaluated=float(d_ev[cr1].min()), crt_overlap_cr1=sorted(set(crt) & set(cr1)))
    return {"cr1": cr1, "crt": crt, "crt_error": crt_err, "stats": stats, "group": group, "d_ev": d_ev, "d_c1": d_c1}


def _wilson(k: int, n: int, z: float = 1.96) -> list | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(c - h, 4), round(c + h, 4)]


def widened_counts(parts: list) -> dict:
    """放宽边界的分区计数（0 FE，只是几何 / 模板化，不含力学）：区域按物理值 α、m 划分；另报角落子盒放宽后的部分。"""
    np = _np()
    X = np.vstack([p_["x13"] for p_ in parts])
    feas = np.concatenate([np.asarray(p_["feasible"], bool) & ~np.asarray(p_["error"], bool) for p_ in parts])
    e = np.concatenate([np.asarray(p_["e_star"], float) for p_ in parts])
    A0 = np.concatenate([np.asarray(p_["A0_star"], float) for p_ in parts])
    bone = np.concatenate([np.asarray(p_["bone_mm3"], float) for p_ in parts])
    v = b2_phase().vars
    col = {k: X[:, v.index(k)] for k in v}
    a_hi, m_lo = col["alpha"] > 45.0, col["m"] < 0.5

    def summ(mask):
        n, k = int(mask.sum()), int((mask & feas).sum())
        f = mask & feas
        return {"n": n, "feasible": k, "rate": round(k / n, 4) if n else None, "rate_ci95": _wilson(k, n),
                "e_star_0_share": round(float((e[f] == 0).mean()), 4) if k else None,
                "A0_star_median_mm2": round(float(np.median(A0[f])), 2) if k else None,
                "bone_median_mm3": round(float(np.median(bone[f])), 1) if k else None}

    corner = (col["L"] >= 38.0) & (col["L"] <= 45.0) & (col["h_cut"] >= 16.0) & (col["h_cut"] <= 18.0) \
        & (col["alpha"] >= 40.0) & (col["m"] <= 0.8)
    regions = {"all": summ(np.ones(len(X), bool)), "inside_old_box": summ(~a_hi & ~m_lo), "alpha_gt_45_only": summ(a_hi & ~m_lo),
               "m_lt_0.5_only": summ(~a_hi & m_lo), "alpha_gt_45_and_m_lt_0.5": summ(a_hi & m_lo),
               "alpha_gt_45_any_m": summ(a_hi), "m_lt_0.5_any_alpha": summ(m_lo)}
    corner_r = {"box": {"L": [38.0, 45.0], "h_cut": [16.0, 18.0], "alpha": [40.0, 55.0], "m": [0.25, 0.8]},
                "all": summ(corner), "old_corner_subbox": summ(corner & ~a_hi & ~m_lo), "beyond_old_bounds": summ(corner & (a_hi | m_lo)),
                "alpha_gt_45": summ(corner & a_hi), "m_lt_0.5": summ(corner & m_lo)}
    return {"regions": regions, "corner": corner_r}


# ---------------------------------------------------------------- b2：作业表
def _rolefree(spec: dict) -> str:
    """物理键去掉 fric_only / intact_job（同一设计、同一条件，只差带不带粘接模型）。bond_only 留着（只粘接的作业没有摩擦结果）。"""
    v = _phys_view(spec)
    for k in ("fric_only", "intact_job"):
        v.pop(k, None)
    return json.dumps(v, sort_keys=True)


def _sf_cr_spec(ph, u, stage: str, tag: str, bonded: bool, intact_job: str | None = None) -> dict:
    """Phase(13).spec_of(u, tag, bonded) 的物理键 + 本层的 stage / tag / kind variant（不直接用 spec_of：它的 stage 是 "sb13"，会被
    阶段 13 的收编 glob 吃进去）。bonded → intact_job（默认 = PHASES[13] 的参照）。"""
    sp = ph.spec_of(u, tag, bonded=bonded)
    phys = _phys(sp, f"{stage} {tag}")
    if bonded:
        return _variant(phys, stage, tag, "full", intact_job=intact_job or sp["intact_job"])
    return _variant(phys, stage, tag, "fric")


def interleave(a: list, b: list) -> list:
    """按比例交错（a 的第 i 个位置 (i + 1) / len(a)，b 的第 j 个 (j + 1) / len(b)，相同时 a 在前）：SF 4 个、CR 1 个、……"""
    from fractions import Fraction
    items = [(Fraction(i + 1, len(a)), 0, k) for i, k in enumerate(a)] + [(Fraction(j + 1, len(b)), 1, k) for j, k in enumerate(b)]
    return [k for _, _, k in sorted(items)]


def crt_file_path() -> pathlib.Path:
    return J.RESULTS / CRT_FILE


def _sel_doc(b: dict) -> dict:
    """db_crt_selection.json 的内容（CR-1 与 CR-T 名单、规则、种子、冻结的已有设计清单）。"""
    s = b["cr"]
    return {"tool": "stage_db", "batch": "b2", "code_hash": b["code_hash"], "rule": CR_RULE, "seed": CR_SOBOL_SEED, "n": CR_N,
            "box": CR_BOX, "excl_r": CR_EXCL_R, "metric": "Euclidean distance in the phase-13 unit cube (columns = Phase(13).vars)",
            "quota_cr1": list(CR1_QUOTA), "quota_crt": list(CRT_QUOTA), "tpl_file": b["cr_tpl"],
            "evaluated": b["evaluated"], "evaluated_sf1": b["sf1_u13_keys"], "evaluated_sha256": b["evaluated_sha256"],
            "stats": {k: v for k, v in s["stats"].items() if k != "excluded_near_jobs_idx"},
            "cr1": s["cr1_list"], "crt": s["crt_list"], "crt_submitted_in_b2": False}


def _ev_sha(evaluated: list) -> str:
    return hashlib.sha256(json.dumps(evaluated, sort_keys=True, default=float).encode()).hexdigest()


def build_b2b() -> dict:
    """b2b（模块说明"批次 b2b"）：B2B_SOURCE_BATCHES 清单里 model_set fric、已 DONE 的行 → 各一个 h 2.0 只粘接作业（stage db_bo，
    参照 REF_H2）。源行在飞 → problems（b2 没跑完，先不建）；源行 FAILED、或队列里已有可用 h 2.0 粘接结果 → 跳过（warnings 记数）。
    查重 / 检查与 build() 相同；没有种子、没有 REF 行。"""
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems, rows = [], [], []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    ref_src = load_source(REF_H2, "intact", qspecs)
    idents = {n: _ident(sp) for n, sp in qspecs.items() if sp is not None}
    skipped = {"failed": [], "has_bonded": [], "not_fric": 0}
    for h in B2B_SOURCE_BATCHES:
        man, err = _read_json(manifest_path(h))
        if not isinstance(man, dict) or not isinstance(man.get("rows"), dict):
            raise SystemExit(f"batch {h}: manifest {manifest_path(h)} unreadable ({err or 'not a JSON object with rows'}); b2b needs it")
        for k in man["order"]:
            m = man["rows"][k]
            if m.get("model_set") != "fric":
                skipped["not_fric"] += 1
                continue
            jid = m.get("id")
            if m.get("status") not in ("submitted", "existing") or not jid:
                problems.append(f"{h}:{k}: source row is {m.get('status')} (not submitted yet): batch {h} has not finished; build b2b after it has")
                continue
            st = J.state(J.QROOT / jid)
            if st == "FAILED":
                skipped["failed"].append(jid)
                continue
            if st != "DONE":
                problems.append(f"{h}:{k}: source {jid} is {st}: batch {h} has not finished; build b2b after it has")
                continue
            src = _spec_of(jid, qspecs)
            if src is None:
                raise SystemExit(f"{h}:{k}: source {jid} has no readable spec.json")
            if not src.get("fric_only") or src.get("kind") not in ("design", "variant") or src.get("femur_id") != FEMUR_ID or src.get("h_int") != H_PROD:
                raise SystemExit(f"{h}:{k}: source {jid} is not a friction-only 3406 h 2.0 design job (fric_only {src.get('fric_only')!r}, "
                                 f"kind {src.get('kind')!r}, h_int {src.get('h_int')!r})")
            have = usable_bonded_h2(src, qspecs, warn, idents)
            if have:
                skipped["has_bonded"].append(f"{jid} -> {have}")
                continue
            spec = _variant(_phys(src, jid), "db_bo", f"{_tag_of(jid)}_h2", "bond", intact_job=REF_H2)
            rows.append(_row(f"BD2_{k}", B2B_LAYER, spec, jid, m.get("design_code"),
                             extra={"pool_idx": m.get("pool_idx"), "partner_of": jid, "src_batch": h, "src_layer": m.get("layer")}))
    if skipped["failed"]:
        warn.append(f"{len(skipped['failed'])} source rows FAILED, no partner: {skipped['failed']}")
    if skipped["has_bonded"]:
        warn.append(f"{len(skipped['has_bonded'])} source designs already have a usable h 2.0 bonded result, no partner: {skipped['has_bonded']}")
    seen = {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch b2b: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs)
    taken = {}
    for r in rows:
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch b2b: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids("b2b")
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: _spec_of(j, qspecs), h14_ref=None)]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds("b2b", rows, qspecs)
    problems += seed_probs
    if not rows and not problems:
        problems.append("b2b: no rows (no finished friction-only design row in " + ", ".join(B2B_SOURCE_BATCHES) + " lacks a bonded result)")
    return {"batch": "b2b", "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{H_PROD:g}": REF_H2}, "ref_src": ref_src, "partners": {}, "n_partner": len(rows), "pilot16": [],
            "seeds": seeds, "skipped": {k: (len(v) if isinstance(v, list) else v) for k, v in skipped.items()},
            "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


def quantile_pick(cands: list, n: int, exclude=frozenset()) -> list:
    """cands = [(值, 键, 作业号)]：去掉键在 exclude 里的，按 (值, 键) 排序，取位置 int((i + 0.5) / n × 个数)，i = 0..n − 1（n ≤ 个数时互不相同）。"""
    c = sorted((x for x in cands if x[1] not in exclude), key=lambda x: (x[0], x[1]))
    if len(c) < n:
        raise SystemExit(f"quantile_pick: {len(c)} candidates < {n} wanted")
    return [c[int((i + 0.5) / n * len(c))] for i in range(n)]


def b2_done_rows(problems: list, warn: list) -> tuple[dict, dict]:
    """b2 清单里已 DONE 的 SF-1 / CR-1 行 → ({层: [(f1_p95_um, 键, 作业号)]}, b2 清单的行)。源行还在飞 → problems（b2 没跑完）；FAILED 跳过；
    没有有限 f1 → warn。b3 / b4 的选点都从这里出发。"""
    man, merr = _read_json(manifest_path(B3_SOURCE_BATCH))
    if not isinstance(man, dict) or not isinstance(man.get("rows"), dict):
        raise SystemExit(f"manifest {manifest_path(B3_SOURCE_BATCH)} unreadable ({merr or 'not a JSON object with rows'})")
    pools = {"SF-1": [], "CR-1": []}
    for k in man["order"]:
        m = man["rows"][k]
        if m.get("layer") not in pools:
            continue
        jid = m.get("id")
        if m.get("status") not in ("submitted", "existing") or not jid:
            problems.append(f"{B3_SOURCE_BATCH}:{k}: source row is {m.get('status')} (batch {B3_SOURCE_BATCH} has not finished)")
            continue
        st = J.state(J.QROOT / jid)
        if st == "FAILED":
            continue
        if st != "DONE":
            problems.append(f"{B3_SOURCE_BATCH}:{k}: source {jid} is {st} (batch {B3_SOURCE_BATCH} has not finished)")
            continue
        res, _ = _read_json(J.QROOT / jid / "result.json")
        f1 = res.get("f1_p95_um") if isinstance(res, dict) else None
        if not isinstance(f1, (int, float)) or isinstance(f1, bool) or not math.isfinite(f1):
            warn.append(f"{B3_SOURCE_BATCH}:{k}: {jid} has no finite f1_p95_um in result.json; not a candidate")
            continue
        pools[m["layer"]].append((float(f1), k, jid))
    return pools, man["rows"]


def b3_picks(pools: dict) -> tuple[dict, list]:
    """b3 的选点（确定性）：NZ-2 = 每层 NZ2_PER_LAYER 个 f1 分位；FD-1 的 SF-1 = FD1_SF_N 个 f1 分位（去掉 NZ-2 已选的）。"""
    nz = {L: quantile_pick(pools[L], NZ2_PER_LAYER) for L in pools}
    return nz, quantile_pick(pools["SF-1"], FD1_SF_N, exclude={x[1] for x in nz["SF-1"]})


def b2_source_phys(jid: str, qspecs: dict) -> dict:
    """b2 一行的源作业的物理键：采纳的两臂作业按 design 核对，其余按 b2row 核对。"""
    return _phys(load_source(jid, "design" if jid.startswith(ARM_PREFIXES) else "b2row", qspecs), jid)


def build_b3() -> dict:
    """b3（一周计划 2026-10-29 第 3 节；模块说明"批次 b3"）：CR-T 30（b2 冻结的名单，stage db_crt）、NZ-2 24（SF-1 6 + CR-1 6 个设计 ×
    h 1.94 / 2.06，stage db_nz）、FD-1 h1.4 8（B、C、D、a62 + SF-1 4 个，stage db_fd，h 1.4 的滑移容差）；全部带粘接（用户 10-29：100 %），
    网格变体用同网格参照（b1 的 REF 行，必须 DONE）。NZ-2 / FD-1 的设计从 b2 清单里已 DONE 的 SF-1 / CR-1 行按 result.json 的 f1_p95_um
    分位取（quantile_pick）。顺序：CR-T 与 NZ-2 按比例交错，FD-1 再按比例插进去（重作业一次一个，旁边有轻作业）。
    查重 / 检查与 build() 相同；没有种子、没有 REF 行。"""
    np = _np()
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems, rows = [], [], []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    # ---- 参照：b1 的 REF 行
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    ref_id, ref_key_of = {H_PROD: REF_H2}, {}
    for h in NZ2_H + (HEAVY_H,):
        k = f"REF_h{h:g}"
        jid = b1_ids.get(k)
        if not jid:
            raise SystemExit(f"b3: the {B3_REF_BATCH} manifest has no submitted {k} (the h {h:g} reference)")
        st = J.state(J.QROOT / jid)
        if st != "DONE":
            problems.append(f"b3: reference {k} = {jid} is {st} (must be DONE)")
        ref_id[h], ref_key_of[h] = jid, k
    # ---- b2 的 SF-1 / CR-1 行（已 DONE，带 f1_p95_um）
    pools, _ = b2_done_rows(problems, warn)
    nz_pick, fd_sf = b3_picks(pools)

    def src_of(jid):
        return b2_source_phys(jid, qspecs)

    # ---- CR-T：b2 冻结的名单（不重选）
    sel, serr = _read_json(crt_file_path())
    if not isinstance(sel, dict) or not sel.get("crt"):
        raise SystemExit(f"b3: {crt_file_path()} unreadable or without a CR-T list ({serr or 'no crt'}); it is frozen by batch b2")
    if _ev_sha(sel.get("evaluated") or []) != sel.get("evaluated_sha256"):
        raise SystemExit(f"b3: {crt_file_path()}: the evaluated-design list does not match its sha256 (edited?)")
    ph = b2_phase()
    U_cr = cr_points()
    crt_keys, nz_keys, fd_keys = [], [], []
    for x in sel["crt"]:
        ci = int(x["cr_idx"])
        if not np.array_equal(np.asarray(x["u13"], float), U_cr[ci]):
            problems.append(f"CR-T c{ci}: the frozen u13 differs from cr_points()[{ci}] (sub-box points changed?)")
        spec = _sf_cr_spec(ph, U_cr[ci], "db_crt", f"c{ci}", True)
        extra = {"cr_idx": ci, "layer_pos": x.get("rank"), "bonded_planned": True, "sf_bo_overlap": False, "bo_twins": [],
                 "e_star": x.get("e_star"), "e_group": x.get("group"), "u13": [float(v) for v in U_cr[ci]]}
        r = _row(f"CRT_c{ci:04d}", "CR-T", spec, None, None, extra=extra)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        crt_keys.append(r["key"])
    # ---- NZ-2：每个设计 × h 1.94 / 2.06，带粘接
    for L, picks in nz_pick.items():
        for f1, k, jid in picks:
            p_ = src_of(jid)
            for h in NZ2_H:
                spec = _variant(p_, "db_nz", f"{_tag_of(jid)}_h{h:g}", "full", intact_job=ref_id[h], h_int=h)
                r = _row(f"NZ2_h{h:g}_{_tag_of(jid)}", "NZ-2", spec, jid, None, ref_key=ref_key_of[h],
                         extra={"src_batch": B3_SOURCE_BATCH, "src_key": k, "src_layer": L, "f1_p95_um_h2": f1})
                rows.append(r)
                nz_keys.append(r["key"])
    # ---- FD-1 h1.4：B、C、D、a62 + SF-1 4 个，带粘接
    fd_src = [(c, CODES[c], None, None) for c in FD1_CODES] + [(None, jid, k, f1) for f1, k, jid in fd_sf]
    for c, jid, k, f1 in fd_src:
        src = load_source(jid, "design", qspecs) if c else None
        p_ = _phys(src, jid) if c else src_of(jid)
        spec = _variant(p_, "db_fd", f"{_tag_of(jid)}_h1.4", "full", intact_job=ref_id[HEAVY_H], h_int=HEAVY_H, slip_tol=H14_SLIP_TOL)
        r = _row(f"FD1_h1.4_{c or _tag_of(jid)}", "FD-1 h1.4", spec, jid, c, ref_key=ref_key_of[HEAVY_H],
                 extra={"src_batch": None if c else B3_SOURCE_BATCH, "src_key": k, "f1_p95_um_h2": f1})
        rows.append(r)
        fd_keys.append(r["key"])
    order = interleave(interleave(crt_keys, nz_keys), fd_keys)
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows):
        raise SystemExit("b3: duplicate row keys")
    rows = [by_key[k] for k in order]
    # ---- 查重 + 批内重复 + 检查（同 b1）
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch b3: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs) if r["source_job"] else None
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch b3: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
            warn.append(f"{r['key']}: already in the queue ({r['dedup']} via {r['dedup_via']}: {r['id']})")
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids("b3")
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: _spec_of(j, qspecs), h14_ref=ref_id[HEAVY_H])]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds("b3", rows, qspecs)
    problems += seed_probs
    return {"batch": "b3", "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{h:g}": v for h, v in ref_id.items()}, "partners": {}, "n_partner": 0, "pilot16": [], "seeds": seeds,
            "picks": {"NZ-2": {L: [(k, j, f) for f, k, j in v] for L, v in nz_pick.items()}, "FD-1 SF-1": [(k, j, f) for f, k, j in fd_sf]},
            "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


def cd1r_points():
    """CD-1 随机条件的 CD1R_POINTS 个 17 维 scrambled Sobol 点（种子 CD1R_SOBOL_SEED）：前 13 列 = 阶段 13 的单位坐标（全空间，列序 =
    Phase(13).vars），后 4 列 = CD1R_BOX 的条件单位坐标。"""
    return sobol(CD1R_POINTS, CD1R_SOBOL_SEED, 17)


def cd1r_condition(v) -> dict:
    """4 个条件的单位坐标 → {"delta": δ, "load": {resultant_N, alpha_front_deg, alpha_sagit_deg}}（CD1R_BOX，δ 按对数均匀，按小数位取整）。"""
    out = {}
    for (name, lo, hi, scale, nd), x in zip(CD1R_BOX, v):
        val = math.exp(math.log(lo) + float(x) * (math.log(hi) - math.log(lo))) if scale == "log" else lo + float(x) * (hi - lo)
        out[name] = round(val, nd)
    return {"delta": out["delta"], "load": {k: out[k] for k in ("resultant_N", "alpha_front_deg", "alpha_sagit_deg")}}


def runner_up_offset(tpl: dict, t: int) -> tuple[float, float] | None:
    """模板化记录第 t 行：除 e* 以外可用偏移里 A0 最大的 (e, A0)；没有第二个可用偏移 → None。"""
    es = float(tpl["e_star"][t])
    best = None
    for j, e in enumerate(tpl["offsets"]):
        if bool(tpl["usable_by_e"][t][j]) and abs(float(e) - es) > 1e-9:
            a0 = float(tpl["A0_by_e"][t][j])
            if best is None or a0 > best[1]:
                best = (float(e), a0)
    return best


def build_b4() -> dict:
    """b4（一周计划 2026-10-29 第 3 节；模块说明"批次 b4"）：
    REF 2        起身两档（STS_LOADS）的 3406 h 2.0 完整股骨参照（= sb_intact_h2_9c9d7fb5 的 spec + cfg.load），本批提交，重作业
    CD-1 128     锚点 32 个（b2 已 DONE 的 SF-1 22 + CR-1 10，f1 分位，去掉 b3 已选的）× {δ 0.05、δ 0.20（楼梯）、起身 1714、3839（δ 0.10）}，只解摩擦
    BD sts 64    锚点 × 起身两档的只粘接（stage db_bo，参照 = 本批的同载荷 REF）
    CD-1 rand 56 17 维 Sobol（u13 + δ、R、两个方向角）里按 u13 的模板化可行的前 56 个，各 1 个条件，只解摩擦（SED 要同载荷参照）；iid
    BD offset 24 b2 已 DONE、有第二个可用偏移的设计里 e_margin_eff 最小的 SF-1 12 + CR-1 12，强制次优偏移（entry_offset），带粘接（基线载荷）
    顺序：REF 在前；CD-1、CD-1 rand、BD offset、BD sts 按比例交错。查重 / 检查与 build() 相同（参照在本批里，按本批的 spec 核对）。"""
    np = _np()
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems, rows = [], [], []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    ph = b2_phase()
    pools, b2rows = b2_done_rows(problems, warn)
    nz, fd_sf = b3_picks(pools)
    taken3 = {x[1] for v in nz.values() for x in v} | {x[1] for x in fd_sf}
    # ---- REF：起身两档
    ref_phys = _phys(load_source(REF_H2, "intact", qspecs), REF_H2)
    ref_sts, ref_by_key, ref_keys = {}, {}, []
    for ln, L in STS_LOADS.items():
        spec = {**copy.deepcopy(ref_phys), "kind": "intact", "cfg": {"load": dict(L)}, "stage": "db_ref", "tag": f"intact_sts{ln[1:]}"}
        k = f"REF_sts{ln[1:]}"
        rows.append(_row(k, "REF", spec, REF_H2))
        ref_sts[ln] = ref_by_key[k] = resolve(spec, by_h8, qspecs, by_phys)[0]
        ref_keys.append(k)
    # ---- CD-1 锚点 + 起身只粘接
    cd_keys, bds_keys = [], []
    for L_, n in CD1_ANCHOR_N.items():
        for f1, k, jid in quantile_pick(pools[L_], n, exclude=taken3):
            p_, tag = b2_source_phys(jid, qspecs), _tag_of(jid)
            ext = {"src_batch": B3_SOURCE_BATCH, "src_key": k, "src_layer": L_, "f1_p95_um_h2": f1}
            for dl in CD1_DELTA:
                spec = _variant(p_, "db_cd", f"{tag}_d{dl:g}", "fric", delta=dl)
                rows.append(_row(f"CD1_d{dl:g}_{tag}", "CD-1", spec, jid, None, extra=ext))
                cd_keys.append(rows[-1]["key"])
            for ln, Ld in STS_LOADS.items():
                spec = _variant(p_, "db_cd", f"{tag}_{ln}", "fric", cfg={"load": dict(Ld)})
                rows.append(_row(f"CD1_sts{ln[1:]}_{tag}", "CD-1", spec, jid, None, extra=ext))
                cd_keys.append(rows[-1]["key"])
                spec = _variant(p_, "db_bo", f"{tag}_{ln}", "bond", intact_job=ref_sts[ln], cfg={"load": dict(Ld)})
                rows.append(_row(f"BDS_sts{ln[1:]}_{tag}", "BD sts", spec, jid, None, ref_key=f"REF_sts{ln[1:]}", extra={**ext, "partner_of": jid}))
                bds_keys.append(rows[-1]["key"])
    # ---- CD-1 随机条件
    U17 = cd1r_points()
    tpl = load_tpl(CD1R_TPL, U17[:, :13])
    feas = [int(i) for i in np.flatnonzero(np.asarray(tpl["feasible"], bool))]
    if len(feas) < CD1R_N:
        problems.append(f"CD-1 rand: only {len(feas)} feasible of {CD1R_POINTS} Sobol points < {CD1R_N}")
    cdr_keys = []
    for i in feas[:CD1R_N]:
        cond = cd1r_condition(U17[i, 13:])
        p_ = _phys(ph.spec_of(U17[i, :13], f"cd1r_{i}", bonded=False), f"db_cd cd1r_{i}")
        spec = _variant(p_, "db_cd", f"cd1r_{i}", "fric", delta=cond["delta"], cfg={"load": cond["load"]})
        r = _row(f"CD1R_{i:04d}", "CD-1 rand", spec, None, None,
                 extra={"sobol_idx": i, "cond": cond, "e_star": float(tpl["e_star"][i]), "u13": [float(x) for x in U17[i, :13]]})
        r.update(unbiased=True, in_E=False)
        rows.append(r)
        cdr_keys.append(r["key"])
    # ---- BD 次优偏移变体
    pool = load_pool()
    tp65 = load_tpl(POOL65K, np.load(J.RESULTS / U65K))
    head = tp65["u13"][:POOL_N]
    tcr = load_tpl(CR_TPL, cr_points())
    cand = {"SF-1": [], "CR-1": []}
    for L_ in cand:
        for f1, k, jid in pools[L_]:
            m = b2rows[k]
            if L_ == "SF-1":
                u = pool["U"][int(m["pool_idx"])]
                hit = np.flatnonzero((head == u).all(1))
                if len(hit) != 1:
                    problems.append(f"BD offset: {k} pool_idx {m['pool_idx']}: {len(hit)} rows of {POOL65K} match its u13 (want 1)")
                    continue
                tp, t = tp65, int(hit[0])
            else:
                tp, t = tcr, int(m["cr_idx"])
            ru = runner_up_offset(tp, t)
            em = float(tp["e_margin_eff"][t])
            if ru is None or not math.isfinite(em):
                continue
            prep, _ = _read_json(J.QROOT / jid / "prep.json")
            e_job = ((prep or {}).get("templating") or {}).get("e")
            if not isinstance(e_job, (int, float)) or abs(float(e_job) - float(tp["e_star"][t])) > 1e-9:
                problems.append(f"BD offset: {k} ({jid}): prep.json entry offset {e_job!r} != the templating record's e* {float(tp['e_star'][t])}")
                continue
            cand[L_].append((em, k, jid, ru, float(tp["e_star"][t]), float(tp["A0_star"][t])))
    bdo_keys = []
    for L_, n in BD_N.items():
        picks = sorted(cand[L_], key=lambda x: (x[0], x[1]))[:n]
        if len(picks) < n:
            problems.append(f"BD offset: {len(picks)} {L_} candidates with a second usable offset < {n}")
        for em, k, jid, (e2, a2), es, a0s in picks:
            p_, tag = b2_source_phys(jid, qspecs), _tag_of(jid)
            spec = _variant(p_, "db_bd", f"{tag}_e{e2:g}", "full", intact_job=REF_H2, entry_offset=e2)
            r = _row(f"BDO_{tag}_e{e2:g}", "BD offset", spec, jid, None,
                     extra={"src_batch": B3_SOURCE_BATCH, "src_key": k, "src_layer": L_, "e_star": es, "e_forced": e2, "e_margin_eff": em,
                            "A0_star": a0s, "A0_forced": a2})
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            bdo_keys.append(r["key"])
    order = ref_keys + interleave(interleave(interleave(cd_keys, cdr_keys), bdo_keys), bds_keys)
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows) or len(order) != len(rows):
        raise SystemExit("b4: duplicate row keys")
    rows = [by_key[k] for k in order]
    # ---- 查重 + 批内重复 + 检查（同 b1：参照在本批里）
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch b4: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs) if r["source_job"] else None
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch b4: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
            warn.append(f"{r['key']}: already in the queue ({r['dedup']} via {r['dedup_via']}: {r['id']})")
    refs_in_batch = {r["id"]: r["spec"] for r in rows if r["layer"] == "REF"}
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids("b4")
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: refs_in_batch.get(j) or _spec_of(j, qspecs))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds("b4", rows, qspecs)
    problems += seed_probs
    return {"batch": "b4", "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{H_PROD:g}": REF_H2}, "ref_by_key": ref_by_key, "partners": {}, "n_partner": len(bds_keys), "pilot16": [],
            "seeds": seeds, "n_feasible_cd1r": len(feas), "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


def build_b5(batch: str = "b5") -> dict:
    """b5 / b6（一周计划 AL-1 / AL-2；模块说明"批次 b5""批次 b6"）：stage_al.py 冻结的 results/db_al_<轮>.json（AL_BATCHES）的选点，
    各 1 行基线条件、带粘接（stage db_al）；稳健问题的选点另加 1 行起身 3839 N（只解摩擦）。选点文件的 essence sha256 与选点、每个点的 u13
    与 POOL65K 的那一行逐位核对、那一行必须可行。层：AL-n（opt / global，selection adaptive，排除集 E）、AL-n sts、AL-n rand（random，iid）。"""
    np = _np()
    import stage_al as AL
    rnd_name, LP, KP = AL_BATCHES[batch]
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems, rows = [], [], []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    p = AL.out_path(rnd_name)
    doc, err = _read_json(p)
    if not isinstance(doc, dict) or not doc.get("picks"):
        raise SystemExit(f"{batch}: {p} unreadable or without picks ({err or 'no picks'}); run stage_al.py select {rnd_name} first")
    if AL.essence(doc) != doc.get("essence_sha256"):
        raise SystemExit(f"{batch}: {p}: the picks do not match their essence sha256 (edited?)")
    ph = b2_phase()
    tps = {"pool65k": (POOL65K, load_tpl(POOL65K, np.load(J.RESULTS / U65K))), "cr4096": (CR_TPL, load_tpl(CR_TPL, cr_points()))}
    keys = {LP: [], f"{LP} sts": [], f"{LP} rand": []}
    for q in doc["picks"]:
        if q.get("source") not in tps:
            problems.append(f"AL pick {q['rank']}: unknown candidate source {q.get('source')!r}")
            continue
        (fname, tp), ci, u = tps[q["source"]], int(q["source_idx"]), np.asarray(q["u13"], float)
        if not np.array_equal(tp["u13"][ci], u):
            problems.append(f"AL pick {q['rank']}: u13 differs from {fname} row {ci}")
        if not bool(tp["feasible"][ci]):
            problems.append(f"AL pick {q['rank']}: {fname} row {ci} is not feasible")
        rnd = q["group"] == "random"
        L_ = f"{LP} rand" if rnd else LP
        tag = f"{rnd_name}_{q['rank']:02d}"
        ext = {"pool_idx": None, "layer_pos": q["rank"], "e_star": q.get("e_star"), "cond": None,
               "al_group": q["group"], "al_problem": q["problem"], "al_score": q.get("score"), "al_p": q.get("p_improve")}
        r = _row(f"{KP}_{q['rank']:02d}", L_, _sf_cr_spec(ph, u, "db_al", tag, True), None, None, extra=ext)
        r.update(unbiased=rnd, in_E=not rnd)
        rows.append(r)
        keys[L_].append(r["key"])
        if q["problem"] == "robust":
            sp = ph.spec_of(u, tag, bonded=False)
            spec = _variant(_phys(sp, f"db_al {tag}"), "db_al", f"{tag}_{AL_STS}", "fric", cfg={"load": dict(STS_LOADS[AL_STS])})
            r = _row(f"{KP}_{q['rank']:02d}_sts{AL_STS[1:]}", f"{LP} sts", spec, None, None, extra={**ext, "cond": {"load": dict(STS_LOADS[AL_STS])}})
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            keys[f"{LP} sts"].append(r["key"])
    order = interleave(interleave(keys[LP], keys[f"{LP} rand"]), keys[f"{LP} sts"])
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows) or len(order) != len(rows):
        raise SystemExit(f"{batch}: duplicate row keys")
    rows = [by_key[k] for k in order]
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch {batch}: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = None
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch {batch}: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
            warn.append(f"{r['key']}: already in the queue ({r['dedup']} via {r['dedup_via']}: {r['id']})")
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids(batch)
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p_}" for p_ in row_problems(r, lambda j: _spec_of(j, qspecs))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds(batch, rows, qspecs)
    problems += seed_probs
    return {"batch": batch, "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{H_PROD:g}": REF_H2}, "partners": {}, "n_partner": 0, "pilot16": [], "seeds": seeds,
            "al_file": str(p), "al_essence": doc["essence_sha256"], "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


def build_b2() -> dict:
    """批次 b2 的作业表（SF-1 128 + CR-1 32，交错）+ 查重（hash8 + 物理键 + 两臂同一设计的采纳）+ CR-T 选点 + G2 + 放宽计数（只算不写）。
    读队列、阶段 13 / 14 状态文件、候选池、tpl_record 文件与（在就读的）results/db_crt_selection.json；不写任何东西。"""
    np = _np()
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems = [], []
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    ph = b2_phase()
    if ph.intact_job != REF_H2 or ph.femur_id != FEMUR_ID or ph.fric.get("delta") != 0.10 or ph.bond_every != BOND_EVERY:
        raise SystemExit(f"PHASES[13] changed (intact_job {ph.intact_job}, femur {ph.femur_id}, fric {ph.fric}, bond_every {ph.bond_every})")
    st13, st14 = _state_file(13), _state_file(14)
    pool = load_pool()
    g2 = g2_pool_check(pool)
    problems += g2["problems"]
    # ---- SF-1：候选池可行行 pool_idx 32..159，基线条件，每第 5 个带粘接；两臂已算过的同一设计 → 采纳
    arm = {}
    for n, sp in qspecs.items():
        if sp is not None and n.startswith(ARM_PREFIXES) and sp.get("kind") in ("design", "variant") and not sp.get("bond_only"):
            arm.setdefault(_rolefree(sp), []).append(n)
    recs = [r for st in (st13, st14) for r in st["records"]]
    rows, sf_keys = [], []
    for pos, pi in enumerate(range(*SF1_RANGE), start=1):
        u = pool["U"][pi]
        planned = pos % BOND_EVERY == 0
        tag = f"p{pi}"
        spec = _sf_cr_spec(ph, u, "db_sf", tag, planned)
        twins = sorted(arm.get(_rolefree(spec), []))
        extra = {"pool_idx": pi, "layer_pos": pos, "bonded_planned": planned, "sf_bo_overlap": bool(twins), "bo_twins": twins,
                 "u13": [float(x) for x in u], "pool_loss_mm3": float(pool["loss"][pi])}
        if twins:
            t = _pick(twins)
            tsp = qspecs[t]
            tb = not tsp.get("fric_only")
            if tb != planned:
                spec = _sf_cr_spec(ph, u, "db_sf", tag, tb, intact_job=tsp.get("intact_job"))
            extra["adopted_role_from"] = t
        r = _row(f"SF1_p{pi:04d}", "SF-1", spec, None, None, extra=extra)
        r.update(unbiased=not twins, in_E=bool(twins))
        rows.append(r)
        sf_keys.append(r["key"])
    for rc in recs:                                     # 两臂记录里 pool_idx 落在 SF-1 的：必须正好是被采纳的那一行
        pi = rc.get("pool_idx")
        if pi is None or not (SF1_RANGE[0] <= int(pi) < SF1_RANGE[1]):
            continue
        r = rows[int(pi) - SF1_RANGE[0]]
        if not np.array_equal(np.asarray(rc.get("x"), float), pool["U"][int(pi)]):
            problems.append(f"{r['key']}: arm record {rc['job_id']} has pool_idx {pi} but its x differs from the pool row (pool changed?)")
        elif rc["job_id"] not in r["bo_twins"]:
            problems.append(f"{r['key']}: arm record {rc['job_id']} (pool_idx {pi}) is not found as a same-physics twin in the queue")
    # ---- CR-1 / CR-T：子盒 4096 个 Sobol 点的模板化记录 → 最大最小选点（冻结的已有设计清单在就用它）
    U_cr = cr_points()
    tpl = load_tpl(CR_TPL, U_cr)
    sel_prev, sel_err = _read_json(crt_file_path())
    if sel_err or (sel_prev is not None and not isinstance(sel_prev, dict)):
        raise SystemExit(f"{crt_file_path()} unreadable ({sel_err or 'not a JSON object'}); restore it (it freezes the CR-1 / CR-T selection)")
    if sel_prev is None and manifest_path("b2").exists():
        raise SystemExit(f"{manifest_path('b2')} exists but {crt_file_path()} is missing: the CR selection was frozen in it at the first start; "
                         "restore it (recomputing from the current queue would see this batch's own jobs as evaluated designs)")
    if sel_prev is not None:
        evaluated = sel_prev.get("evaluated") or []
        ev_src = f"frozen in {CRT_FILE} ({len(evaluated)} designs)"
        if _ev_sha(evaluated) != sel_prev.get("evaluated_sha256"):
            raise SystemExit(f"{crt_file_path()}: the evaluated-design list does not match its sha256 (edited?)")
    else:
        evaluated = evaluated_designs(qspecs, warn)
        ev_src = f"the queue now ({len(evaluated)} designs)"
    sf_u = [r["u13"] for r in rows]
    s = cr_select(tpl, [e_["u13"] for e_ in evaluated] + sf_u, U_cr)
    if s["crt_error"]:
        problems.append(s["crt_error"])
    if s["stats"]["crt_overlap_cr1"]:
        problems.append(f"CR-T overlaps CR-1: {s['stats']['crt_overlap_cr1']}")

    def lst(sel, d_other):
        out = []
        for rank, ci in enumerate(sel, start=1):
            d_, h_ = ph.design_of(U_cr[ci])
            out.append({"rank": rank, "cr_idx": int(ci), "group": "e*=0" if s["group"][ci] == 0 else "e*!=0", "e_star": float(tpl["e_star"][ci]),
                        "A0_star": float(tpl["A0_star"][ci]), "e_margin": float(tpl["e_margin"][ci]), "e_margin_eff": float(tpl["e_margin_eff"][ci]),
                        "bone_mm3": float(tpl["bone_mm3"][ci]), "u13": [float(x) for x in U_cr[ci]],
                        "x13": [float(h_) if k == "h_cut" else float(d_[k]) for k in ph.vars],
                        "min_dist_evaluated": float(s["d_ev"][ci]), **({"min_dist_cr1": float(d_other[ci])} if d_other is not None else {})})
        return out
    s["cr1_list"], s["crt_list"] = lst(s["cr1"], None), lst(s["crt"], s["d_c1"])
    cr_keys = []
    for rank, ci in enumerate(s["cr1"], start=1):
        planned = rank % BOND_EVERY == 0
        spec = _sf_cr_spec(ph, U_cr[ci], "db_cr", f"c{ci}", planned)
        extra = {"cr_idx": int(ci), "layer_pos": rank, "bonded_planned": planned, "sf_bo_overlap": False, "bo_twins": [],
                 "e_star": float(tpl["e_star"][ci]), "e_group": "e*=0" if s["group"][ci] == 0 else "e*!=0", "u13": [float(x) for x in U_cr[ci]]}
        r = _row(f"CR1_c{ci:04d}", "CR-1", spec, None, None, extra=extra)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        cr_keys.append(r["key"])
    order = interleave(sf_keys, cr_keys)
    by_key = {r["key"]: r for r in rows}
    rows = [by_key[k] for k in order]
    # ---- 查重 + 批内重复 + 检查（同 b1）
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch b2: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs) if r["source_job"] else None
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch b2: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
        if r["layer"] == "SF-1" and r["sf_bo_overlap"] and not (r["dedup"] == "existing" and r["id"] in r["bo_twins"]):
            problems.append(f"{r['key']}: same design as arm job(s) {r['bo_twins']} but not adopted (dedup {r['dedup']} -> {r['id']})")
        if r["dedup"] != "new" and r["layer"] == "CR-1":
            warn.append(f"{r['key']}: CR-1 design already in the queue ({r['dedup']} via {r['dedup_via']}: {r['id']})")
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids("b2")
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p}" for p in row_problems(r, lambda j: _spec_of(j, qspecs))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    b = {"batch": "b2", "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(), "ref_id": {},
         "seeds": [], "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs), "g2": g2,
         "pool": {"file": pool["file"], "sha256": pool["sha256"], "n_feasible": len(pool["U"]), "meta": pool["meta"]},
         "cr_tpl": {"file": CR_TPL, "sha256": tpl["sha256"], "n": int(len(tpl["u13"])), "provenance_code_hash": tpl["meta"]["provenance"]["code_hash"],
                    "tpl_femur_geom_key": tpl["meta"]["provenance"].get("femur_geom_key"), "host": tpl["meta"]["provenance"].get("host"),
                    "started_utc": tpl["meta"].get("started_utc"), "updated_utc": tpl["meta"].get("updated_utc")},
         "cr": s, "evaluated": evaluated, "evaluated_source": ev_src, "evaluated_sha256": _ev_sha(evaluated),
         "sf1_u13_keys": [r["key"] for r in rows if r["layer"] == "SF-1"], "sel_prev": sel_prev}
    if sel_prev is not None:                            # 冻结的名单必须与重算的一致
        for k, mine in (("cr1", s["cr1_list"]), ("crt", s["crt_list"])):
            if [x["cr_idx"] for x in sel_prev.get(k) or []] != [x["cr_idx"] for x in mine]:
                problems.append(f"{CRT_FILE}: frozen {k} list {[x['cr_idx'] for x in sel_prev.get(k) or []][:6]}... differs from the recomputed "
                                f"{[x['cr_idx'] for x in mine][:6]}... (same frozen evaluated list); not feeding")
        if sel_prev.get("tpl_file", {}).get("sha256") != tpl["sha256"]:
            problems.append(f"{CRT_FILE}: frozen with templating file sha256 {sel_prev.get('tpl_file', {}).get('sha256')} != current {tpl['sha256']}")
    # ---- 放宽边界计数（只算；select 写 results/db_widened_counts.json）
    try:
        W = wide_points()
        parts = [load_tpl(rel, W[a:z_], wide_physical(W[a:z_]), rows=(a, z_)) for rel, a, z_ in WIDE_PARTS]
        b["wide"] = {"files": [{"file": rel, "rows": [a, z_], "sha256": p_["sha256"]} for (rel, a, z_), p_ in zip(WIDE_PARTS, parts)],
                     **widened_counts(parts)}
    except SystemExit as ex:
        b["wide"] = None
        warn.append(f"widened-box counts not available: {ex.code}")
    b["cost"] = cost_estimate(rows)
    ids = {r["id"] for r in rows} | {r["expected_id"] for r in rows}
    other = set()
    for ob in BATCHES:
        if ob != "b2":
            other |= set(recorded_ids(ob)[0].values())
    stray = sorted(n for n in qspecs if n.startswith(("db_sf_", "db_cr_")) and n not in ids and n not in other)
    if stray:
        warn.append(f"db_sf_* / db_cr_* queue dirs that are not rows of batch b2: {stray}")
    return b


def b2_manifest_info(b: dict) -> dict:
    """清单里记下的 b2 输入（重启时逐项核对）：候选池与子盒模板化文件的 sha256、冻结的已有设计清单的 sha256、交错规则。"""
    return {"pool": b["pool"]["file"], "pool_sha256": b["pool"]["sha256"], "cr_tpl": CR_TPL, "cr_tpl_sha256": b["cr_tpl"]["sha256"],
            "crt_file": CRT_FILE, "evaluated_sha256": b["evaluated_sha256"], "cr_seed": CR_SOBOL_SEED, "pool_sobol_seed": POOL_SOBOL_SEED,
            "order": "interleave SF-1 (pool_idx order) and CR-1 (maximin order) by fractional position (SF i at (i+1)/128, CR j at (j+1)/32; "
                     "ties SF first): 4 SF then 1 CR; bonded = every 5th row of each layer by its own order (adopted SF rows keep the arm job's model)",
            "g2": {k: v for k, v in b["g2"].items() if k != "problems"}}


def _sel_essence(doc: dict) -> str:
    """选点文件里决定名单的部分：种子、点数、子盒、配额、下限、模板化文件 sha256、冻结清单 sha256、CR-1 / CR-T 的下标序列。"""
    return json.dumps({"seed": doc.get("seed"), "n": doc.get("n"), "box": doc.get("box"), "excl_r": doc.get("excl_r"),
                       "quota_cr1": doc.get("quota_cr1"), "quota_crt": doc.get("quota_crt"),
                       "tpl_sha256": (doc.get("tpl_file") or {}).get("sha256"), "evaluated_sha256": doc.get("evaluated_sha256"),
                       "cr1": [x.get("cr_idx") for x in doc.get("cr1") or []], "crt": [x.get("cr_idx") for x in doc.get("crt") or []]},
                      sort_keys=True, default=float)


def _same_doc(a: dict, b: dict, ignore=("created_utc",)) -> bool:
    return json.dumps({k: v for k, v in a.items() if k not in ignore}, sort_keys=True, default=float) == \
        json.dumps({k: v for k, v in b.items() if k not in ignore}, sort_keys=True, default=float)


def write_selection(b: dict, log=None) -> str:
    """results/db_crt_selection.json：不存在 → 写（冻结 CR-1 / CR-T 名单与"已有设计"清单）；存在且内容相同 → 不动；不同 → SystemExit。"""
    p = crt_file_path()
    doc = {**_sel_doc(b), "created_utc": _utc()}
    old, err = _read_json(p)
    if err:
        raise SystemExit(f"{p} unreadable ({err})")
    if old is not None:
        if _sel_essence(old) == _sel_essence(doc):
            return f"{p} already holds this selection (unchanged)"
        raise SystemExit(f"{p} exists with a different CR selection; not overwriting (it freezes CR-1 / CR-T; move it away only if no b2 "
                         "manifest exists)")
    _write_json(p, doc)
    return f"wrote {p}: CR-1 {len(doc['cr1'])} + CR-T {len(doc['crt'])} designs, {len(doc['evaluated'])} evaluated designs frozen"


def write_widened(b: dict) -> str:
    p = J.RESULTS / WIDE_COUNTS_FILE
    if not b.get("wide"):
        raise SystemExit("widened-box templating files missing or invalid (see the warnings); nothing written")
    doc = {"tool": "stage_db", "batch": "b2", "created_utc": _utc(), "code_hash": b["code_hash"], "seed": WIDE_SOBOL_SEED, "n": WIDE_N,
           "space": wide_space(), "old_box": {"alpha": list(b2_phase().space["alpha"]), "m": list(b2_phase().space["m"])},
           "note": "0 FE: templating feasibility only (tpl_record, phase-13 rule), no mechanics; rates with Wilson 95 % intervals; the corner "
                   "region holds few points of a full-box sample", **b["wide"],
           "pool_rate_old_box_16384": round(b["pool"]["n_feasible"] / POOL_N, 4)}
    old, err = _read_json(p)
    if old is not None and not _same_doc(old, doc):
        raise SystemExit(f"{p} exists with different counts; not overwriting")
    if old is None:
        _write_json(p, doc)
        return f"wrote {p}"
    return f"{p} already holds these counts (unchanged)"


def cost_estimate(rows: list) -> dict:
    """规划成本模型的槽时：每层 新作业数 × COST_MIN[层] + 新作业里带粘接的 × BOND_MIN（采纳的已有作业不计）；墙钟 = 槽时 ÷ (3 × 85 %)。
    另给"粘接已摊进 COST_MIN"的口径（规划的 30.75 / 23.25 = 求解 + 20 s 空闲 + 20 % × 0.6）。"""
    out, tot, tot_in = {}, 0.0, 0.0
    for L in COST_MIN:
        rs = [r for r in rows if r["layer"] == L]
        new = [r for r in rs if r["dedup"] == "new"]
        nb = sum(r["bonded"] for r in new)
        sh = (len(new) * COST_MIN[L] + nb * BOND_MIN) / 60.0
        sh_in = len(new) * COST_MIN[L] / 60.0
        out[L] = {"rows": len(rs), "new": len(new), "adopted": len(rs) - len(new), "new_bonded": nb, "bonded_all_rows": sum(r["bonded"] for r in rs),
                  "slot_h": round(sh, 2), "slot_h_bond_in_rate": round(sh_in, 2)}
        tot += sh
        tot_in += sh_in
    out["total"] = {"slot_h": round(tot, 2), "wall_h": round(tot / (SLOTS * UPTIME), 1), "slot_h_bond_in_rate": round(tot_in, 2),
                    "wall_h_bond_in_rate": round(tot_in / (SLOTS * UPTIME), 1),
                    "model": f"slot-min per new job SF {COST_MIN['SF-1']} / CR {COST_MIN['CR-1']} + {BOND_MIN} if bonded; wall = slot-h / "
                             f"({SLOTS} slots x {UPTIME:.0%}); 'bond_in_rate' = the plan's per-job figure already averaging the 20 % bonded share"}
    return out


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
    ids = {row.get("expected_id") or expected_id(s), row.get("id") or expected_id(s)}
    if row.get("sf_bo_overlap") and row.get("id") in (row.get("bo_twins") or []):
        ids.discard(row["id"])                          # b2：SF 行采纳两臂已算过的同一设计（那个作业本来就是 sb13_ / sb14_ 的，不新提交）
    for jid in ids:
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
def replay_b2(b: dict) -> dict:
    """G2"同一种子重放"：从种子重新生成候选池的 Sobol 点、子盒点，重新选 CR-1 / CR-T（同一冻结的已有设计清单），与 b 的名单逐项比。"""
    np = _np()
    U2 = cr_points()
    U3 = cr_points()
    same_pts = bool(np.array_equal(U2, U3))
    tpl = load_tpl(CR_TPL, U2)
    sf_u = [r["u13"] for r in b["rows"] if r["layer"] == "SF-1"]
    s2 = cr_select(tpl, [e_["u13"] for e_ in b["evaluated"]] + sf_u, U2)
    pool = load_pool()
    D1, D2 = sobol(POOL_N, POOL_SOBOL_SEED), sobol(POOL_N, POOL_SOBOL_SEED)
    sf_same = [r["u13"] for r in b["rows"] if r["layer"] == "SF-1"] == [[float(x) for x in pool["U"][i]] for i in range(*SF1_RANGE)]
    return {"cr_points_identical": same_pts, "pool_draw_identical": bool(np.array_equal(D1, D2)), "sf1_rows_identical": sf_same,
            "cr1_identical": s2["cr1"] == b["cr"]["cr1"], "crt_identical": s2["crt"] == b["cr"]["crt"],
            "ok": same_pts and bool(np.array_equal(D1, D2)) and sf_same and s2["cr1"] == b["cr"]["cr1"] and s2["crt"] == b["cr"]["crt"]}


def dry_run_b2() -> int:
    """b2 的 dry run：只打印（不建作业目录、不写清单 / 日志 / 选点文件 / 计数文件）。退出码 0 = 没有问题，1 = 有问题。"""
    b = build("b2")
    rows = b["rows"]
    gk = femur_geom_key()
    aux = aux_md5()
    rp = replay_b2(b)
    if not rp["ok"]:
        b["problems"].append(f"G2 replay: the same seeds do not give the same lists ({rp})")
    hi = {}
    snap0 = queue_snapshot()
    try:
        hi["b1"] = build("b1")
        dups = cross_batch_dups(b, hi)
        b["problems"] += dups
        pr = priority_wait("b2", hi, snap0)
    except SystemExit as e:
        pr = f"(b1 could not be built here: {e.code})"
        b["warnings"].append(f"b1 build for the priority probe failed: {e.code}")
    depth_now = f"unclaimed db_* now {len(snap0['unclaimed_db'])} of {MAX_UNCLAIMED}"
    s, st = b["cr"], b["cr"]["stats"]
    g2 = b["g2"]
    print("dry run: batch b2; nothing written (no job directories, manifest, log, selection or counts file)")
    print(f"queue {J.QROOT} ({b['n_queue_dirs']} dirs); results {J.RESULTS}; code_hash {b['code_hash']} (required {DB_CODE_HASH}); "
          f"femur_geom_key {gk['key']}; femur_model_version {FEMUR_MODEL_VERSION}")
    print(f"aux files (md5 on this host): {json.dumps(aux)}")
    print(f"pool {b['pool']['file']} sha256 {b['pool']['sha256'][:16]}..: {b['pool']['n_feasible']} feasible of {POOL_N}")
    print(f"G2 pool: regenerated Sobol({POOL_N}, seed {g2['seed']}) contains every pool row bit-identically: {g2['all_found']}; in Sobol order: "
          f"{g2['increasing']}; pool_idx 0 = Sobol index {g2['sobol_index_of_pool_idx0']}, SF-1 pool_idx {SF1_RANGE[0]}..{SF1_RANGE[1] - 1} = "
          f"Sobol indices {g2['sobol_index_sf1']}")
    print(f"G2 pool65k ({POOL65K}): {json.dumps(g2.get('pool65k'))}")
    print(f"G2 replay (same seeds again): {json.dumps(rp)}")
    print(f"CR templating {CR_TPL} sha256 {b['cr_tpl']['sha256'][:16]}.. (tpl_record code_hash {b['cr_tpl']['provenance_code_hash']}, host "
          f"{b['cr_tpl']['host']}, {b['cr_tpl']['started_utc']} .. {b['cr_tpl']['updated_utc']})")
    print(f"evaluated designs for the CR distances: {b['evaluated_source']} + {SF1_RANGE[1] - SF1_RANGE[0]} SF-1 designs; sha256 "
          f"{b['evaluated_sha256'][:16]}..")
    print(f"CR rule: {CR_RULE}")
    print(f"CR sub-box {json.dumps(CR_BOX)}, seed {CR_SOBOL_SEED}, n {CR_N}: feasible {st['feasible']} ({st['feasible_e0']} e*=0, "
          f"{st['feasible_e_ne0']} e*!=0); within {CR_EXCL_R} of an evaluated design: {st['excluded_near_evaluated']}; CR-1 candidates "
          f"{st['cr1_candidates']} ({st['cr1_candidates_e0']} e*=0)")
    print(f"CR-1: {len(s['cr1'])} designs, spacing (min pairwise) {st['cr1_spacing']:.4f}, min distance to evaluated {st['cr1_min_dist_evaluated']:.4f}")
    print(f"CR-T: literal rule (>= the CR-1 spacing {st['cr1_spacing']:.4f} from CR-1 and from every evaluated design): "
          f"{st['crt_literal_candidates']} candidates ({st['crt_literal_candidates_e0']} e*=0) -> feasible {st['crt_literal_feasible']}; used "
          f"rule: maximin continued with CR-1 + evaluated pre-placed, floor {CR_EXCL_R}: {st['crt_candidates']} candidates "
          f"({st['crt_candidates_e0']} e*=0); selected {len(s['crt'])}; own spacing {st['crt_spacing_own']}; min distance to CR-1 "
          f"{st['crt_min_dist_cr1']}; to evaluated {st['crt_min_dist_evaluated']} (= {st['crt_min_dist_ratio_to_cr1_spacing']} x CR-1 spacing); "
          f"overlap with CR-1 {st['crt_overlap_cr1']} -> disjoint {not st['crt_overlap_cr1'] and bool(s['crt'])}"
          f"{' -- ' + s['crt_error'] if s['crt_error'] else ''}")
    print(f"CR-T list (would be written to results/{CRT_FILE} by 'select b2' or at the first feed start; NOT submitted in b2): "
          + ", ".join(f"c{x['cr_idx']}({x['group']})" for x in s["crt_list"]))
    print(f"jobs ({len(rows)}; interleaved 4 SF : 1 CR): key | layer | stage | pool_idx / cr_idx | bonded (planned) | expected id | dedup")
    for r in rows:
        dd = r["dedup"] if r["dedup"] != "existing" else f"existing ({r['dedup_via']}) -> {r['id']}"
        ix = f"p{r['pool_idx']}" if r["layer"] == "SF-1" else f"c{r['cr_idx']} {r['e_group']}"
        print(f"  {r['key']} | {r['layer']} | {r['stage']} | {ix} | {r['model_set']} ({'bonded' if r['bonded_planned'] else 'fric'} planned) | "
              f"{r['expected_id']} | {dd}{' | sf_bo_overlap ' + ','.join(r['bo_twins']) if r['sf_bo_overlap'] else ''}")
    c = b["cost"]
    for L in COST_MIN:
        print(f"{L}: {c[L]['rows']} rows = {c[L]['new']} new + {c[L]['adopted']} adopted (no FE); bonded rows {c[L]['bonded_all_rows']} "
              f"(new bonded {c[L]['new_bonded']}); {c[L]['slot_h']} slot-h ({c[L]['slot_h_bond_in_rate']} if the bonded share is already in the "
              "per-job rate)")
    print(f"total: {c['total']['slot_h']} slot-h, {c['total']['wall_h']} h wall ({c['total']['slot_h_bond_in_rate']} / "
          f"{c['total']['wall_h_bond_in_rate']} h with the bonded share inside the rate); {c['total']['model']}")
    if b.get("wide"):
        print("widened box (alpha 15-55, m 0.25-2.0; 0 FE; would be written to results/" + WIDE_COUNTS_FILE + " by 'select b2'):")
        for k, v in {**b["wide"]["regions"], **{f"corner {k2}": v2 for k2, v2 in b["wide"]["corner"].items() if k2 != "box"}}.items():
            print(f"    {k:<28} n {v['n']:>5}  feasible {v['feasible']:>5}  rate {v['rate']}  CI95 {v['rate_ci95']}  e*=0 share "
                  f"{v['e_star_0_share']}  A0* median {v['A0_star_median_mm2']}")
    print(f"concurrency with b1: per-batch lock {lock_path('b2')} / log {log_path('b2')}; stop {', '.join(str(x) for x in stop_files('b2'))}; "
          f"global depth cap {MAX_UNCLAIMED}; b1 priority now: {pr or 'clear (b1 has no row submittable right now)'}; {depth_now}")
    lay = [L for L in SLOW_START_LAYERS if any(r["layer"] == L for r in rows)]
    print(f"slow start: layers {lay} keep at most {SLOW_START_CAP} rows in flight until {SLOW_START_DONE} of their rows are DONE; failure holds "
          f"per layer (release {RELEASE_PREFIX}SF-1 / {RELEASE_PREFIX}CR-1, first-10: {RELEASE_PREFIX}{RELEASE_ALL} or {RELEASE_PREFIX}b2)")
    for w in b["warnings"]:
        print("WARNING: " + w)
    if b["problems"]:
        print(f"PROBLEMS ({len(b['problems'])}; feed would refuse):")
        for p in b["problems"]:
            print("  " + p)
    else:
        print("checks: all rows pass (stage prefix, job id prefix, not in any phase 11-14 family, role keys, reference match, adoption, G2)")
    nl = {L: sum(r["layer"] == L for r in rows) for L in COST_MIN}
    print("DRY-RUN-JSON")
    print(json.dumps({"batch": "b2", "n_jobs": len(rows), "per_layer": nl, "problems": b["problems"], "warnings": b["warnings"],
                      "code_hash": b["code_hash"], "femur_geom_key": gk["key"], "aux_md5": aux, "g2": {k: v for k, v in g2.items()},
                      "replay": rp, "cost": c, "cr_stats": {k: v for k, v in st.items() if k != "excluded_near_jobs_idx"},
                      "cr1": s["cr1_list"], "crt": s["crt_list"], "crt_error": s["crt_error"], "wide": b.get("wide"),
                      "b1_priority_now": pr, "unclaimed_db_now": len(snap0["unclaimed_db"]), "evaluated_source": b["evaluated_source"],
                      "jobs": [{k: r.get(k) for k in ("key", "layer", "stage", "source", "selection", "pool_idx", "cr_idx", "e_group", "layer_pos",
                                                      "bonded_planned", "bonded", "model_set", "intact_job", "sf_bo_overlap", "bo_twins",
                                                      "adopted_role_from", "unbiased", "in_E", "expected_id", "id", "dedup", "dedup_via")}
                               for r in rows]}, indent=1, default=float))
    return 1 if b["problems"] else 0


def select_b2() -> int:
    """写 results/db_crt_selection.json 与 results/db_widened_counts.json（不提交任何作业）。有问题 → 不写，退出码 1。"""
    b = build("b2")
    rp = replay_b2(b)
    if not rp["ok"]:
        b["problems"].append(f"G2 replay: the same seeds do not give the same lists ({rp})")
    if b["problems"]:
        print(f"PROBLEMS ({len(b['problems'])}); nothing written:")
        for p in b["problems"]:
            print("  " + p)
        return 1
    print(write_selection(b))
    print(write_widened(b))
    return 0


def dry_run(batch: str = "b1") -> int:
    """只打印，不写任何文件（不建作业目录、不写清单、不写日志）。返回退出码：0 = 没有问题，1 = 有问题（列在 PROBLEMS）。"""
    if batch == "b2":
        return dry_run_b2()
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
    m = b.get("init_median")
    if m:
        print(f"init median design: {m['job_id']} rot {m['rot_first_deg']:.4f} deg; rule: {INIT_MEDIAN_RULE}")
    if b.get("pilot16"):
        print(f"pilot16 resolved from the queue: {', '.join(b['pilot16'])}")
    print("references: " + ", ".join(f"h{h} -> {j}" for h, j in b["ref_id"].items()))
    if b.get("partners"):
        print("h 2.0 usable bonded results of the 24 pilot designs (a design without one gets a BD h2.0 bond_only partner):")
    for c, have in b.get("partners", {}).items():
        print(f"    {c:<20} {', '.join(have) if have else '-  (partner)'}")
    if b.get("skipped"):
        print(f"b2b sources skipped: {json.dumps(b['skipped'])} (source batches {list(B2B_SOURCE_BATCHES)})")
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
    print(f"per layer: {json.dumps(by_layer)}; total {len(rows)}; h 2.0 bond_only partners {b['n_partner']}"
          + (f" (of at most {len(FD25_CODES) + len(PILOT16)})" if batch == "b1" else ""))
    print(f"dedup: {n_new} new, {sum(r['dedup'] == 'queued' for r in rows)} already queued under the expected id, "
          f"{n_ex_h8 + n_ex_ph} existing ({n_ex_h8} via hash8, {n_ex_ph} via the physics key)"
          + ("".join(f"\n    {r['key']}: {r['dedup']} ({r['dedup_via']}) {r['id']} (queue state {J.state(J.QROOT / r['id'])}; hits {r['dedup_hits']})"
                     for r in hits)))
    h14x, h14why = h14_mode()
    print(f"heavy rows (one at a time): {[r['key'] for r in rows if r['heavy']]}; exclusive (idle queue only, holds every other db "
          f"submission while in flight): {list(EXCLUSIVE)}; FD0_h1.4_* also wait for the operator file {H14_OK_NAME}; FD-0 h1.4 mode now: "
          f"{h14why}")
    lay = [L for L in SLOW_START_LAYERS if any(r["layer"] == L for r in rows)]          # 本批的层（b1：NZ-1 … BD h2.0）
    print(f"slow start: layers {lay} keep at most {SLOW_START_CAP} rows in flight (NEW / READY / CLAIMED / SOLVED) until "
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
                      "init_median": m["job_id"] if m else None, "h14_mode": "exclusive" if h14x else "heavy",
                      "slow_start": {"layers": lay, "cap": SLOW_START_CAP, "until_done": SLOW_START_DONE},
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
    for i in range(6):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            # Windows only（测试机）：目标文件正被别的句柄打开（杀毒 / 索引扫描刚写的文件）时 os.replace 报 WinError 5；短暂重试，
            # 6 次都不行照样抛出。Linux 上 rename 是原子的、不会这样失败：立即抛出（行为不变）
            if os.name == "posix" or i == 5:
                raise
            time.sleep(0.2 * (i + 1))


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
            "state": None, "submitted_utc": None, "times_utc": {}, "finished_ts": None, "held_reason": None, "failed_logged": False,
            **({k: r.get(k) for k in B2_ROW_FIELDS} if r["layer"] in B2_LAYERS else {})}


B2_LAYERS = ("SF-1", "CR-1", "CR-T", "CD-1 rand", "BD offset", "AL-1", "AL-1 sts", "AL-1 rand", "AL-2", "AL-2 sts", "AL-2 rand")
B2_ROW_FIELDS = ("cr_idx", "layer_pos", "bonded_planned", "sf_bo_overlap", "bo_twins", "adopted_role_from", "unbiased", "in_E", "e_star", "e_group",
                 "e_forced", "e_margin_eff", "sobol_idx", "cond", "al_group", "al_problem", "al_score", "al_p")


def open_manifest(batch: str, b: dict, gk: dict, log, aux: dict | None = None) -> dict:
    """读已有清单并与当前作业表核对（键集合、每行的预期 id、code_hash、股骨几何键、aux md5），不同 → SystemExit；没有 → 新建。"""
    p = manifest_path(batch)
    rows = b["rows"]
    aux = aux_md5() if aux is None else aux
    if not p.exists():
        man = {"batch": batch, "created_utc": _utc(), "updated_utc": None, "code_hash": b["code_hash"], "femur_geom_key": gk,
               "aux_md5": aux, "aux_root": str(CODE_ROOT), "femur_model_version": FEMUR_MODEL_VERSION, "hollow_core": HOLLOW_CORE,
               "seeds": b["seeds"], "order": [r["key"] for r in rows], "rows": {r["key"]: _man_row(r) for r in rows}, "gates": {}, "events": []}
        if "init_median" in b:
            man.update(init_median=b["init_median"]["job_id"], init_median_rule=INIT_MEDIAN_RULE)
        if batch == "b2":
            man["b2"] = b2_manifest_info(b)
        return man
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
    if batch == "b2":
        old_i, new_i = man.get("b2") or {}, b2_manifest_info(b)
        for k in ("pool_sha256", "cr_tpl_sha256", "evaluated_sha256", "order"):
            if old_i.get(k) != new_i.get(k):
                diff.append(f"b2 input {k} changed since the manifest was written ({str(old_i.get(k))[:40]} -> {str(new_i.get(k))[:40]})")
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


def known_failure(jid: str) -> str | None:
    """已知规律的失败（AUTO_ACK_*，用户 10-29 批准）→ 说明；其他（读不了也算）→ None。只读 FAILED.json 与 spec.json。"""
    d = J.QROOT / jid
    f, _ = _read_json(d / "FAILED.json")
    sp, _ = _read_spec(d / "spec.json")
    if not isinstance(f, dict) or not isinstance(sp, dict):
        return None
    lv, stg, why = f.get("level"), f.get("stage"), str(f.get("reason") or "")
    dsg = sp.get("design") if isinstance(sp.get("design"), dict) else {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)   # noqa: E731
    if lv == "L4" and stg == "solve" and any(t in why for t in AUTO_ACK_L4_TEXT):
        L, a, m = dsg.get("L"), dsg.get("alpha"), dsg.get("m")
        if num(L) and L < AUTO_ACK_L4_L_MAX:
            return f"L4 short stem (L {L:.1f} mm < {AUTO_ACK_L4_L_MAX:g})"
        if num(a) and num(m) and a < AUTO_ACK_L4_LOW["alpha"] and m < AUTO_ACK_L4_LOW["m"]:
            return f"L4 with alpha {a:.1f} < {AUTO_ACK_L4_LOW['alpha']:g} and m {m:.2f} < {AUTO_ACK_L4_LOW['m']:g}"
        return None
    if lv == "L3" and stg == "prep" and AUTO_ACK_L3_TEXT in why and AUTO_ACK_L3_NOT not in why:
        return "L3 degenerate tetrahedra"
    return None


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

        if AUTO_ACK:                                        # 已知规律的失败：自动确认，不停（该层失败率过高时不确认，照旧按闸门停）
            auto = g.setdefault("auto_acked", [])
            rate_all = len(st["failed"]) / st["finished"] if st["finished"] else 0.0
            new_known = [(k, n_) for k in st["failed"] if k not in g["ack_failed"] and not man["rows"][k].get("ack_failed")
                         and k not in auto and (n_ := known_failure(man["rows"][k]["id"]))]
            if new_known and rate_all <= AUTO_ACK_MAX_RATE:
                for k, note in new_known:
                    g["ack_failed"] = sorted(set(g["ack_failed"]) | {k})
                    auto.append(k)
                    man["events"].append({"utc": _utc(), "event": "auto_ack", "layer": L, "key": k, "id": man["rows"][k]["id"], "why": note})
                    log(f"AUTO-ACK layer {L}: {k} {man['rows'][k]['id']} FAILED by a known pattern ({note}); acknowledged, no hold "
                        f"(layer failure rate {100 * rate_all:.1f} % <= {100 * AUTO_ACK_MAX_RATE:g} %)")
                if g["held"] and g.get("kinds") == ["layer"] and not layer_why():
                    n = unhold("auto", J.QROOT.parent / "AUTO_ACK", time.time())
                    log(f"RELEASE layer {L}: every unacknowledged FAILED row matches a known pattern -> {n} held rows pending again")
            elif new_known and g.get("auto_rate_warned") != len(new_known):
                g["auto_rate_warned"] = len(new_known)
                log(f"WARNING layer {L}: {len(new_known)} FAILED rows match a known pattern but the layer failure rate {100 * rate_all:.1f} % > "
                    f"{100 * AUTO_ACK_MAX_RATE:g} %: not acknowledged automatically (the gate decides as usual)")

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
    return list(EXCLUSIVE) + ([r["key"] for r in b["rows"] if r["layer"] in H14_LAYERS] if h14_exclusive else [])


class ProbeHalt(Exception):
    """探查（probe）时 feed_pass 走到了会停喂料器的地方（_halt）：不写清单，只把原因交给调用方。"""


def feed_pass(b: dict, man: dict, snap: dict, log, max_unclaimed: int = MAX_UNCLAIMED, waits: dict | None = None,
              h14_exclusive: bool | None = None, probe: bool = False, gate=None, max_submit: int | None = None) -> list:
    """一轮提交（规则见模块说明）：按作业表顺序；独占行在飞 → 整轮不提交；未领取 db_* ≥ max_unclaimed 就停；等参照 / 重作业 / 参照优先 /
    独占 / 操作员文件 / 慢启动的行跳过（不挡后面的行）。waits：{原因键: {"text", "keys"}}（本轮各行等待的原因，给 WAIT 日志）。
    h14_exclusive：FD0_h1.4_* 是否独占（None = 现读 h14_mode()）。提交前对活队列再查一次重：命中的核对（hit_checks）出问题、或 REF 行
    查重到与建表时不同的 id → 写清单并停止（_halt）。返回这轮提交的键。
    probe = True（并行喂料的优先级探查，man 是清单的副本）：不提交、不写清单、不记日志（log 照调，调用方给空函数），会停的地方抛
    ProbeHalt；返回"此刻会提交"的键。gate：提交每一行之前调用，返回 None = 可以，否则 = 原因（本轮不再提交，记进 waits["gate"]）。
    max_submit：本轮最多提交几行（None = 不限）。"""
    rows = {r["key"]: r for r in b["rows"]}
    waits = {} if waits is None else waits
    mp = manifest_path(b["batch"])
    if h14_exclusive is None:
        h14_exclusive = h14_mode()[0]
    excl = exclusive_keys(b, h14_exclusive)

    def halt(msg):
        if probe:
            raise ProbeHalt(msg)
        _halt(man, mp, msg)

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
        if L == "REF":                                   # b4 的起身参照与楼梯参照同为 h 2.0：按行键查计划的作业号（ref_by_key），没有再按 h_int
            want = (b.get("ref_by_key") or {}).get(key) or b["ref_id"].get(f"{float(s['h_int']):g}")
            if jid != want:
                deps = [k for k in order if rows[k]["spec"].get("intact_job") == want]
                halt(f"{key}: at feed time this reference resolves to {jid} ({status} via {via}), not to {want}, the intact_job "
                     f"its {len(deps)} dependents were built with ({', '.join(deps[:4])}{', ...' if len(deps) > 4 else ''}); they would "
                     f"wait for {want} forever. Stopped: an identical intact spec ({jid}) entered the queue after this batch was built; "
                     "check it, then start a new batch name (a restart is refused: the dependents' expected ids change)")
        if status != "new":
            probs, notes, ack = hit_checks(key, jid, _spec_of(jid))
            if probs:
                halt("feed-time dedup: " + "; ".join(probs) + "; stopped before submitting (the manifest is written)")
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
        if gate is not None and not probe:
            why = gate()
            if why:
                for p in order[i:]:
                    if man["rows"][p]["status"] == "pending":
                        wait("gate", why, p)
                break
        if probe:                                               # 探查：不提交、不动 snap（调用方的快照）
            got = m["expected_id"]
        else:
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
        if not probe:
            log(f"submit {key} -> {got} ({L}, {r['model_set']}{', heavy' if r['heavy'] else ''}{', exclusive' if key in excl else ''})")
        if key in excl:
            if not probe:
                log(f"{key} is exclusive: no other db submission until {got} is DONE / FAILED")
            break
        if max_submit is not None and len(out) >= max_submit:
            rest = [p for p in order[i + 1:] if man["rows"][p]["status"] == "pending"]
            for p in rest:
                wait("per_pass", f"at most {max_submit} submission(s) per pass for a lower-priority batch", p)
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


# ================================================================ 并行喂料（b1 与 b2 同时跑；模块说明"并行喂料"）
def lock_path(batch: str) -> pathlib.Path:
    """每批一个喂料器锁：b1 沿用 logs/db_feed.lock（正在跑的 b1 喂料器用的就是它），其他批 logs/db_feed_<批次>.lock。"""
    return J.QROOT.parent / "logs" / ("db_feed.lock" if batch == "b1" else f"db_feed_{batch}.lock")


def log_path(batch: str) -> pathlib.Path:
    return J.QROOT.parent / "logs" / ("db_feed.log" if batch == "b1" else f"db_feed_{batch}.log")


def stop_files(batch: str) -> list:
    """STOP_DB_FEED（全部喂料器）与 STOP_DB_FEED_<批次>（只这一批）。"""
    root = J.QROOT.parent
    return [root / STOP_NAME, root / f"{STOP_NAME}_{batch}"]


def submit_lock_path() -> pathlib.Path:
    return J.QROOT.parent / "logs" / "db_submit.lock"


@contextlib.contextmanager
def submit_mutex(path: pathlib.Path | None = None, timeout: float | None = None):
    """全局提交互斥锁（logs/db_submit.lock）：一轮的"快照 → 提交 → 写清单"在锁内做，两个喂料器的提交不会交错（全局深度上限不会被
    同时越过）。等不到 timeout 秒 → yield False（调用方本轮跳过并记 WARNING）。注意：2026-10-26 01:24 起跑的 b1 喂料器是旧代码，不拿这把锁；
    低优先级批次因此在每次提交前再扫一次队列、再探查一次优先级（窗口只剩毫秒级）。"""
    path = path or submit_lock_path()
    timeout = SUBMIT_LOCK_TIMEOUT_S if timeout is None else timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    got = False
    t0 = time.monotonic()
    try:
        while True:
            try:
                if os.name == "posix":
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                got = True
                break
            except OSError:
                if time.monotonic() - t0 >= timeout:
                    break
                time.sleep(0.05)
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                if os.name == "posix":
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                else:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        fh.close()


def _null_log(_msg: str) -> None:
    return None


def hi_manifest(h: str, bh: dict) -> tuple[dict | None, str | None]:
    """高优先级批次 h 的清单副本（只读；状态按队列刷新）。没有清单 = 它的喂料器还没启动：按 bh 现建一个（全部按建表时的查重：多半是 pending）。
    清单读不了、或它的键 / 预期 id 与 bh 不同 → (None, 原因)。"""
    p = manifest_path(h)
    man, err = _read_json(p)
    if man is None and err is None:
        man = {"batch": h, "order": [r["key"] for r in bh["rows"]], "rows": {r["key"]: _man_row(r) for r in bh["rows"]}, "gates": {},
               "events": [], "_absent": True}
    elif not isinstance(man, dict) or not isinstance(man.get("rows"), dict) or not isinstance(man.get("order"), list):
        return None, f"manifest {p} unreadable ({err or 'not a manifest'})"
    else:
        man = copy.deepcopy(man)
        want = {r["key"]: r["expected_id"] for r in bh["rows"]}
        got = {k: (m or {}).get("expected_id") for k, m in man["rows"].items()}
        if got != want or list(man["order"]) != [r["key"] for r in bh["rows"]]:
            return None, f"manifest {p} does not match batch {h} as built now (keys / order / expected ids differ)"
    refresh(man)
    return man, None


def _finished(man: dict) -> bool:
    return all(m["status"] == "blocked" or (m["status"] in ("submitted", "existing") and m.get("state") in ("DONE", "FAILED"))
               for m in man["rows"].values())


def probe_pass(bh: dict, man: dict, snap: dict) -> tuple[list | None, dict, str | None]:
    """高优先级批次此刻会提交哪些行（feed_pass(probe=True) 在清单副本上跑；不提交、不写）。返回 (键, waits, 探查不了的原因)。"""
    waits = {}
    try:
        keys = feed_pass(bh, copy.deepcopy(man), snap, _null_log, MAX_UNCLAIMED, waits, probe=True)
    except ProbeHalt as e:
        return None, waits, f"its feeder would stop here: {e}"
    except SystemExit as e:
        return None, waits, f"its feed pass would refuse: {e.code}"
    return keys, waits, None


def exclusive_due(bh: dict, man: dict, snap: dict) -> str | None:
    """高优先级批次只剩独占行（与依赖它的 h ≤ 1.4 行）待提交、且队列一空它就会提交独占行 → 返回那一行（低优先级批次停下来让队列排空）。"""
    excl = exclusive_keys(bh, h14_mode()[0])
    rows = {r["key"]: r for r in bh["rows"]}
    pend = [k for k in man["order"] if man["rows"][k]["status"] == "pending"]
    if not any(k in excl for k in pend):
        return None
    if any(k not in excl and not (rows[k]["spec"].get("kind") != "intact" and float(rows[k]["spec"]["h_int"]) <= HEAVY_H + 1e-9) for k in pend):
        return None
    idle = {**snap, "unclaimed_db": [], "heavy_inflight": [], "busy_any": []}
    keys, _, why = probe_pass(bh, man, idle)
    if keys and keys[0] in excl:
        return keys[0]
    return None


def feeder_pids(batch: str) -> list | None:
    """本机上 "stage_db.py feed <批次>" 进程的 pid（读 /proc/*/cmdline，只读）；没有 /proc（Windows）→ None（不知道）。"""
    if not os.path.isdir("/proc"):
        return None
    out = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as fh:
                args = [c.decode(errors="replace") for c in fh.read().split(b"\0") if c]
        except OSError:
            continue
        if any(a.endswith("stage_db.py") for a in args) and "feed" in args and batch in args:
            out.append(int(d))
    return sorted(out)


def _alive_txt(h: str) -> str:
    p = feeder_pids(h)
    if p is None:
        return f"{h} feeder process: unknown on this host"
    return f"{h} feeder process: pid {', '.join(map(str, p))}" if p else f"{h} feeder process: NOT RUNNING (no 'stage_db.py feed {h}' found)"


def priority_wait(batch: str, hi_builds: dict, snap: dict) -> str | None:
    """低优先级批次这一刻能不能提交（PRIORITY）：任何一个高优先级批次 此刻有可提交的行 / 独占行在飞 / 只剩独占行要排空队列 / 清单读不了
    或探查不了 → 返回等待原因；都没有 → None。"""
    for h, bh in hi_builds.items():
        man, err = hi_manifest(h, bh)
        if err:
            return f"{h} priority: {err}; not submitting (fix or finish {h} first)"
        if _finished(man):
            continue
        keys, waits, why = probe_pass(bh, man, snap)
        if why:
            return f"{h} priority: probe failed ({why}); not submitting"
        if "exclusive_inflight" in waits:
            return f"{h} priority: {waits['exclusive_inflight']['text']}"
        if keys:
            absent = " (no manifest yet: its feeder has not started)" if man.get("_absent") else ""
            return (f"{h} priority: {len(keys)} row(s) of {h} submittable now{absent} ({', '.join(keys[:3])}{', ...' if len(keys) > 3 else ''}); "
                    f"{_alive_txt(h)}")
        due = exclusive_due(bh, man, snap)
        if due:
            return f"{h} priority: only exclusive / h 1.4 rows left in {h}; its exclusive {due} goes on an idle queue: draining (no submission)"
    return None


def cross_batch_dups(b: dict, others: dict) -> list:
    """同一物理计算出现在两个批次里 → 问题（两个喂料器可能各提交一次）。"""
    mine = {phys_key(r["spec"]): r["key"] for r in b["rows"]}
    out = []
    for h, bh in others.items():
        for r in bh["rows"]:
            k = mine.get(phys_key(r["spec"]))
            if k:
                out.append(f"{k}: same physics as row {r['key']} of batch {h}")
    return out


def feed(batch: str = "b1", poll: float = POLL_S, once: bool = False, max_unclaimed: int = MAX_UNCLAIMED, sleep=time.sleep) -> int:
    """喂料器主循环（规则见模块说明）。返回退出码：0 = 全部 DONE / FAILED、STOP 或 --once 一轮结束；3 = 有 blocked 行。
    任何拒绝（检查、磁盘、代码哈希、股骨几何、aux md5、清单不符、碰撞）→ SystemExit 带原因（日志里也有）；其他异常记 "ERROR crashed" 再抛出。"""
    if not sys.platform.startswith("linux") and not _ALLOW_NON_LINUX:
        raise SystemExit("feed runs on the Linux queue host only (cd ~/mobo_toy_v2/code && taskset -c 4-11 nice -n 19 ../run.sh v2/stage_db.py feed ...)")
    if not J.QROOT.is_dir():
        raise SystemExit(f"queue {J.QROOT} does not exist")
    root = J.QROOT.parent
    stops = stop_files(batch)
    for stop in stops:
        if stop.exists():
            raise SystemExit(f"{stop} exists: remove it to start the feeder")
    with feed_lock(lock_path(batch)):
        log = _Log(log_path(batch))
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
            with submit_mutex() as got_lock:                # 建表时读别的批次的清单：在锁内读，不会撞上它写到一半（Windows 上 os.replace 会失败）
                if not got_lock:
                    raise SystemExit(f"the pass mutex {submit_lock_path()} was not free within {SUBMIT_LOCK_TIMEOUT_S:g} s at start")
                b = build(batch)
                hi_builds = {h: build(h) for h in PRIORITY.get(batch, ())} if not b["problems"] else {}   # 高优先级批次的作业表（探查用）
            if b["problems"]:
                raise SystemExit(f"batch {batch}: {len(b['problems'])} check problem(s); nothing submitted:\n" + "\n".join("  " + p for p in b["problems"]))
            dups = cross_batch_dups(b, hi_builds)
            if dups:
                raise SystemExit(f"batch {batch}: rows with the same physics as rows of a higher-priority batch: " + "; ".join(dups[:5]))
            for w in b["warnings"]:
                log("WARNING " + w)
            gk = femur_geom_key()
            aux = aux_md5()
            if not mp.exists():
                check_first_start_disk(disk_free_gib())
                if batch == "b2":
                    log(write_selection(b, log))
            man = open_manifest(batch, b, gk, log, aux)
            man["events"].append({"utc": _utc(), "event": "start", "pid": os.getpid()})
            n_rows = len(b["rows"])
            sd = "; ".join(f"seed {s['file']}: {len(s['adopted'])} of {s['n_jobs']} adopted" for s in b["seeds"] if s["present"])
            log(f"batch {batch}: {n_rows} rows; {sum(m['status'] == 'pending' for m in man['rows'].values())} pending, "
                f"{sum(m['status'] == 'existing' for m in man['rows'].values())} existing, {sum(m['status'] == 'held' for m in man['rows'].values())} held"
                f"{'; ' + sd if sd else ''}; femur_geom_key {gk['key']}; aux md5 {json.dumps(man['aux_md5'])}")
            lay = [L for L in SLOW_START_LAYERS if any(r["layer"] == L for r in b["rows"])]
            log(f"slow start: layers {lay} keep at most {SLOW_START_CAP} rows in flight until {SLOW_START_DONE} of their "
                f"rows are DONE; first-10 gate window = rows submitted by this feeder only; heartbeat every {HEARTBEAT_S / 60:g} min")
            if hi_builds:
                log(f"priority: batch {batch} submits only when {list(hi_builds)} has no row submittable right now (and none of its exclusive rows "
                    f"is in flight or due on an idle queue); at most {LOW_MAX_SUBMIT} submission per pass, depth and priority re-checked on a fresh "
                    f"queue scan right before it; global depth cap {max_unclaimed} unclaimed db_* (all batches); pass mutex {submit_lock_path()}")
            idle, announced = 0, set()
            h14_txt, hb_last, pr_last = None, None, None
            while True:
                hit = next((s_ for s_ in stops if s_.exists()), None)
                if hit is not None:
                    refresh(man)
                    man["updated_utc"] = _utc()
                    man["events"].append({"utc": _utc(), "event": "stop file", "file": hit.name})
                    _write_json(mp, man)
                    log(f"{hit} found: manifest written, exiting cleanly; {json.dumps(_counts(man))}")
                    return 0
                check_code()
                if femur_geom_key()["key"] != man["femur_geom_key"]["key"]:
                    raise SystemExit("femur geometry files changed while feeding (femur_geom_key differs from the manifest); refusing")
                ch = aux_changes(man["aux_md5"], aux_md5())
                if ch:
                    _halt(man, mp, "aux code files changed while feeding (not in code_hash, but they affect results): " + "; ".join(ch)
                          + "; stopped (restore them, or start a new batch name)")
                with submit_mutex() as got_lock:
                    if not got_lock:
                        log(f"WARNING pass skipped: the pass mutex {submit_lock_path()} was not free within {SUBMIT_LOCK_TIMEOUT_S:g} s")
                        if once:
                            return 0
                        sleep(poll)
                        continue
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
                        pr = priority_wait(batch, hi_builds, snap) if hi_builds else None
                        pr_cat = re.sub(r"\d+", "#", pr.split(" (")[0]) if pr else None
                        if pr_cat != pr_last:                   # 优先级等待的原因类别变化时记一行（含"不再等"）；完整原因在 WAIT 行里
                            log(f"PRIORITY {pr}" if pr else "PRIORITY clear: no higher-priority row is submittable now")
                            pr_last = pr_cat
                        if pr:
                            waits["priority"] = {"text": pr, "keys": [k for k in man["order"] if man["rows"][k]["status"] == "pending"]}
                        else:
                            def fresh_gate():                   # 低优先级批次：提交前重新扫队列，再核深度与优先级
                                fs = queue_snapshot()
                                if len(fs["unclaimed_db"]) >= max_unclaimed:
                                    return f"depth cap (fresh scan): {len(fs['unclaimed_db'])} unclaimed db_* jobs >= {max_unclaimed}"
                                return priority_wait(batch, hi_builds, fs)
                            sub = feed_pass(b, man, snap, log, max_unclaimed, waits, h14_exclusive=h14x,
                                            gate=fresh_gate if hi_builds else None, max_submit=LOW_MAX_SUBMIT if hi_builds else None)
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
    ap = argparse.ArgumentParser(description="db3406 batch submitter v1.2 (dry-run / feed / status; select for b2)")
    ap.add_argument("cmd", choices=["dry-run", "feed", "status", "select"])
    ap.add_argument("batch", choices=list(BATCHES))
    ap.add_argument("--root", help="dry-run / status / select only: read <root>/queue and <root>/results (a copy) instead of ~/mobo_toy_v2 "
                                   "(select writes into <root>/results)")
    ap.add_argument("--once", action="store_true", help="feed only: one pass, then exit")
    ap.add_argument("--poll", type=float, default=POLL_S, help="feed only: seconds between passes (default 60)")
    a = ap.parse_args(argv)
    if a.root:
        if a.cmd == "feed":
            ap.error("--root is for dry-run / status / select only (the feeder works on the live ~/mobo_toy_v2 queue)")
        J.QROOT, J.RESULTS = pathlib.Path(a.root) / "queue", pathlib.Path(a.root) / "results"
    if a.cmd != "feed" and (a.once or a.poll != POLL_S):
        ap.error("--once / --poll are feed options")
    if a.cmd == "select":
        if a.batch != "b2":
            ap.error("select is for batch b2 (CR-1 / CR-T selection file and widened-box counts)")
        return select_b2()
    if a.cmd == "dry-run":
        return dry_run(a.batch)
    if a.cmd == "status":
        status(a.batch)
        return 0
    return feed(a.batch, poll=a.poll, once=a.once)


if __name__ == "__main__":
    sys.exit(main())
