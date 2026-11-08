"""3406 数据库（db3406）的批量提交器 v1.5（D1 = v0 + 审查修正 + 采纳 CD-0 种子 + 第二轮审查修正；D2 = 批次 b2 + 并行喂料；v1.3 = 批次 b1b；v1.4 = 批次 b2b；
v1.5 = 批次 b3 + 已知规律失败的自动确认；v1.6 = 批次 b6（AL-2）；v1.7 = 批次 b7（AL-3，局部候选）；v1.8 = 批次 b14（候选 A 的 m / α 单因素扫描）；v1.9 = 批次 b8、b12（第二周计划第二版）；v1.10 = 批次 b7m（AL-3′，m ≥ 1.0）；v1.11 = 批次 b15（A 的 m 1.0 版 × α）；v1.12 = 批次 b16、b17、b18（第三版计划的 VAL-1、TQ-0、MU-1）；v1.13 = 批次 b19（WL-1）；v1.14 = 批次 b9p、b11p（CD-2″、OW-2）；v1.15 = 批次 b20、b21（AL-4m）；v1.16 = 批次 b22（OW-3）；v1.17 = 批次 b23（OW-4）；v1.18 = 批次 b24（TQ-1、PF-1 的冒烟）；v1.19 = 批次 b25（OPT-1，F、微动、去骨三目标）；v1.20 = 批次 b26、b27（STS-1，候选 × 坐起 1714 N）；v1.21 = 批次 b28（FAM-1，离 A 0.25 到 0.75 的环带）；v1.22 = 批次 b28c（b28 初判赢家的条件行）；v1.23 = 批次 b29、b30、b31（RS-1 环带随机、OF-1 单因素、R2 第二轮））。规划：research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md
（第 1.3 / 1.4 节分层与无偏集、第 1.6 节命名 / 查重 / 版本陷阱、第 1.8 节检查 13 / 14、第 2.1–2.7 节、第 3.2 节 CR-T；用户 2026-10-25 批准两天部分）。
不改 8 个哈希文件（code_hash 必须是 6d7af243d0）、不改 jobs.py / stage_neckopt.py / stage_deck.py / stage_v2a.py / tpl_record.py；提交只走 jobs.submit。

    python v2/stage_db.py dry-run b1|b2|b1b|b2b|b3|b4|b5|b6|b7|b7m|b14|b8|b12|b15|b16|b17|b18|b19|b9p|b11p|b20|b21|b22|b23|b24|b25|b26|b27|b28|b28c|b29|b30|b31 [--root <只读副本>]  只打印：每个 spec 的键、层、stage、源作业、相对源 spec.json 的变体（键 旧 -> 新）、
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
批次 b7（v1.7，2026-11-01，用户批准 AL-3）= 同一构造读 results/db_al_al3.json；选点可以来自局部候选来源（stage_al.LOCAL_SOURCES，
    模板化文件里的 error 行允许但必须不可行），每个点同样与它的来源那一行逐位核对且可行。层 AL-3 / AL-3 sts / AL-3 rand。

批次 b14（v1.8，2026-11-02，用户要求"写 m/α 扫描批次"；只写批次与干跑，喂料另行决定）= 候选 A（sb13_a105_91e458e3）的单因素边界扫描，6 行，全部带粘接，
    其余设计量与 h_cut、δ、载荷、网格都与 A 相同（spec = A 的物理键只改 design 的一个键）：
    WS m      db_ws  m 0.75 / 1.0 / 1.5（A 是 0.5）：A 家族的转动有多少靠"擦着皮质压配"。m 变大时模板化同时把肩面积 A0 压小（0-FE：519.6 → 492.5 / 466.1 / 414.1 mm²），
                     所以结果是"余量 + 尺寸"的合并效应，不是纯余量效应
    WS alpha  db_ws  α 50 / 55 / 60°（A 是 44.35°，盒子上限 45°）：3406 的颈轴（isthmus 法）与干轴夹角约 67.6°，盒子不含它。这 3 行在 v1 盒外（in_bounds_v1 false），
                     stage_al.load_training 不用它们训练
    source bound_scan、selection stratum、unbiased false、in_E true（设计来自 BO）。build 对每行跑 0-FE 模板化（tpl_record.record_spec，股骨缓存只读，不建模不求解）：
    不可行、入口偏移离开 A 的 e*（会混入偏移跳变）、模板化报错、或 A 自身与它的 prep.json 不符 → 问题，feed 拒绝。层都慢启动；失败门不改（α > 45° 的建模没测过，
    2 行失败会停住第 3 行等人看）。决策规则在看结果前写定：research-log/neck_implant_2026-10-02/3406_m_alpha扫描_b14_2026-11-02.md。

批次 b15（v1.11，2026-11-02，用户"先补 3 行"，放宽 α 之前的检查）= 候选 A 的 m 1.0 版 × α 50 / 55 / 60，3 行，全部带粘接，层 WS m alpha，source bound_scan，stage db_ws。
    b14 的 α 收益是在 m 0.5 上测的，而台架用 m 1.0 版。对照 = b14 的 WS_m1（必须 DONE），所以这里只改 m 和 α 两个键，其余物理都与 A 相同。这 3 行都在 v1 盒外，stage_al.load_training 不用它们训练。
    不可行、入口偏移离开 A 的 e*、模板化报错、对照 WS_m1 不是 DONE → 问题，feed 拒绝。规则在看结果前写定：3406_m_alpha扫描_b14_2026-11-02.md 第 8 节。

批次 b28（v1.21，2026-11-08，experiments/b28_fam/，用户"批准 17 行"）：
    b28 = FAM-1，层 FAM-1，stage db_al，source al_adaptive，只解摩擦，基线条件，15 行：离 A 单位距离 0.25 到 0.75 的环带里按"离开 A 的方向"分 5 族，每族 3 行
       （打分最好、距离 ≥ 0.45 里最好、不确定度最大）。选点在 experiments/b28_fam/prep/（0 FE）：打分规则 = G41 的两条路线，m ≥ 1，盒内，8 个位姿过放置检查。
       这里写死 u13、e，以及放置复查时模板化的号和去骨量，build 核对。另加层 FAM-1 ctrl 2 行，stage db_nz，source noise，带粘接：A 的 m 1.0 版 e +1、+2 × h 1.94，
       参照 b1 的 REF_h1.94（楼梯），阴性对照。A 的 m 1.0 版必须 DONE。判据是 experiments/b28_fam/gates.py 的 G41–G45。

批次 b29、b30、b31（v1.23，2026-11-08，五天计划，用户"整份批准"）：三批都是写死 u13、入口偏移、0 FE 模板化的号和去骨量的新设计，只解摩擦，基线条件，
    build 核对模板化结果和记录一致、m ≥ 1、物理键相对 A 的 m 1.0 版只改设计、截骨和入口偏移。A 的 m 1.0 版和 A 族曲线 7 行（UROW_CURVE）必须 DONE。
    b29 = RS-1，层 RS-1，stage db_al，source corner（环带是按 A 定的子区，同 CR 角落，进排除集 E，不进无偏集），48 行，从 b28 的环带候选不看分数随机抽取，
       判据 experiments/b29_rs1/gates.py 的 G46。al_problem 叫 F_f1_bone_ring_rand：环带里随机，但不是全空间的无偏样本。
    b30 = OF-1，层 OF-1，stage db_ws，source bound_scan，12 行：10 行是 A 的 m 1.0 版只改一个形状量（ρ_tip、q、n_a、g_ap、τ_a 各 2 档），入口偏移 0；
       2 行（审查后加）是 b28 的 3b 只把 n_a 或 τ_a 放回 A 的值，入口偏移 +1.5。build 核对每行恰好改了标签写的那个坐标、那一步（_of1_single_factor）。
       截骨 18、20、22 mm 在 e 0 都装不下，没有放进来。判据 experiments/b30_of1/gates.py 的 G48、G51。
    b31 = R2，层 R2，stage db_al，source al_adaptive，15 行：b28 的 3b 周围单位距离 0.15 以内，按"比 3b 更好"的概率选，过 8 个位姿的放置检查。
       判据 experiments/b31_r2/gates.py 的 G49、G50。

批次 b28c（v1.22，2026-11-08，experiments/b28c_cond/，用户"批准 17 行"里的条件行，最多 15 行）：
    b28 的 15 行算完后，按 experiments/b28_fam/proposal.md 第 4 节写定的初判规则选出赢家（FAM1C_WINNERS，最多 5 个）。每个赢家 3 行：
       层 FAM-1 rep，stage db_nz，source noise，h 1.94 重划复算，带粘接，参照 b1 的 REF_h1.94；层 FAM-1 h1.4，stage db_fd，source fid_h14，带粘接，参照 REF_h1.4，重作业；
       层 FAM-1 sts，stage db_cd，source cond_anchor，坐起 1714 N，只解摩擦。物理都从 b28 的主行来，只改 h_int（和 h 1.4 的 slip_tol）或 cfg.load。
       赢家的 b28 主行必须 DONE。tag = 主行 tag + "_h1.94" / "_h1.4" / "_F1714"，与 b28 的 gates.py 一致。

批次 b26、b27（v1.20，2026-11-04，experiments/b26_sts1714/，用户"批准 19 行"）：
    b26 = STS-1，层 STS-1，stage db_cd，source cond_anchor，只解摩擦，15 行：当前候选只把头力换成坐起 1714 N（D13_STS），其余同基线行。基线行必须 DONE。
    b27 = STS-1 mesh，stage db_nz，source noise，带粘接：A 的 m 1.0、e +2 × h 1.94、2.06，4 行；另加 h 1.94、2.06 × 1714 N 的完整股骨参照 2 行（层 REF）。网格变体不能只解摩擦（10-23 规则），
       粘接要同网格、同载荷的参照，库里没有，所以多这 2 行。这 2 行不在批准的 19 行里，b27 等用户说了再喂。判据是 experiments/b26_sts1714/gates.py 的 G38–G40。

批次 b25（v1.19，2026-11-04，experiments/b25_opt1/，用户"批准 8 行"）：
    b25 = OPT-1，层 OPT-1，stage db_al，source al_adaptive，带粘接，基线条件，8 行。选点在 research-log/neck_implant_2026-10-02/opt_F微动去骨_2026-11-04/（0 FE）：
       F 大、微动小、去骨少，m ≥ 1，盒内，入口偏移 0 到 +2 固定，8 个位姿不进皮质、颈底伸出 ≤ 2 mm²。这里写死 u13、e，以及 0 FE 算出的号和去骨量，build 核对。
       对照 A 的 m 1.0（WS_m1）必须 DONE。判据是 experiments/b25_opt1/gates.py 的 G36、G37。

批次 b24（v1.18，2026-11-04，第三版计划第 3.3、5.2、5.3 节，用户"批准写钩子和冒烟"）：
    b24 = TQ-1、PF-1 的冒烟，共 10 行，stage db_cd，只解摩擦。正式行没有批准。
       TQ-1 smoke：A 的 m 1.0 版 e 0、e +1.5、e +2.5 × 定义 A（绕柄轴 10 N·m，加 1 kN 沿柄轴的预载）、定义 B（3839 N 起身头力，加绕颈轴 10 N·m），6 行。
       PF-1 smoke：e 0、e +1.5 × 号固定时入口偏移 −1、+1 mm，4 行。这回答悬崖是不是放置误差。坐深、转角、插入角只查 0 FE 和建模，不解。
       基线 e 行必须 DONE。10 N·m 和公差都是默认值，等用户或导师定。判据是第三版 G33–G35。

批次 b23（v1.17，2026-11-03，第三版计划第 3.2 节，用户"批准 OW-4"）：
    b23 = OW-4：A 的 m 1.0 版在固定入口偏移上的稳健性。e +1、+2、+2.5 × δ 0.05、3839 N、两者、S40 共 12 行，层 OW-4，stage db_cd，只解摩擦；
       e +2 × 10 循环 1 行，层 OW-4 cy，stage db_cd，只解摩擦；e +2 × h 1.4 1 行，层 OW-4 h1.4，stage db_fd，带粘接，参照 b1 的 REF_h1.4，重作业。共 14 行。
       基线是 b11p、b22 的 e 行，必须 DONE。判据是第三版 G17、G30、G31、G32。

批次 b22（v1.16，2026-11-03，第三版计划第 3.2 节，用户"先跑 OW-3"）：
    b22 = OW-3，层 OW-3，stage db_ws，source bound_scan，带粘接：m 1.0 版的 A × e −1、−0.5、+0.5、+1、+1.5、+2.5，a95 × e +1、+1.5、+2.5，共 9 行。提议里的第 10 行 WL_m1_L44 × e +2 不可行：L 44 在 e > 0 时号都低于下限，所以去掉，没有换别的行。
       G25 触发后加的：b11p 的 e +2 在 ≤ 6 cm³ 过了 0.19°，要知道 e 0 到 +2.5 之间是不是连续的代价曲线，以及 e 0 往负方向多远开始掉悬崖。这些偏移大多不在生产选号的 2 mm 档上，
       模板化核对走 tpl_record.offgrid_view（jobs.prep 对 entry_offset 本来就接受任意值）。号都在该偏移下重新模板化，这不是放置误差。判据是第三版 G26–G29。

批次 b20、b21（v1.15，2026-11-03，第三版计划第 3.4 节，用户"批准 A 和 B"，《AL-4m补点提议_2026-11-03》）：
    b20 = AL-4m 的 A 部分，层 WS m2，stage db_ws，source bound_scan，全部带粘接，3 行：设计 A 的形状 × m 1.6、1.75、2.0，只改 design.m，接着 b14 的 m 扫描。对照 = b14 的 WS_m1.5（必须 DONE）。
    m 1.6、1.75 的入口偏移必须等于 A 的 e*。m 2.0 的模板跳到 e −2，是用户批准的例外（WM2_E_JUMP），所以这一行不是纯单因素；它的 e* 不是 −2 同样算问题。不可行、模板化报错 → 问题，feed 拒绝。
    b21 = B 部分，层 AL-4m，stage db_al，读 stage_al.py select al4m 冻结的 results/db_al_al4m.json，构造同 b5；选点先给用户核对再喂。判据写在第三版第 7 节 G22–G24。

批次 b9p、b11p（v1.14，2026-11-03，第三版计划第 3.2 节，用户"导出并写批次"）：
    b9p = CD-2″，层 CD-2，stage db_cd，只解摩擦：13 个形状不同的设计 × δ 0.05、3839 N 起身（第二版第 3 节的 9 个，加 b7m 选点 11、1、4，加台架候选 WL_m1_L44），
       另有 8 个紧设计 × δ 0.05 与 3839 N 同时变。已有的行由物理键查重采纳，不重算（AL 选点的 3839 N 行就是这样）。判据是第三版 G18，用整个集合的 Kendall τ。
    b11p = OW-2，层 OW-2，stage db_ws，source bound_scan，带粘接：m 1.0 版的 A、a100、a95、a82、a96，入口偏移固定为 0、−2、+2，共 12 行，都是模板化可行的。
       A 的 e 0 就是 b14 的 WS_m1，不重复。a82、a96 的 e +2 不可行，c4055 的 ±2 也不可行，所以不提交。e 变了 A0 也会变，这不是放置误差。判据是第三版 G25。

批次 b19（v1.13，2026-11-02，第三版计划第 3.4 节，用户"批准 WL-1"）= WL-1，层 WL-1，stage db_ws，source bound_scan，全部带粘接，5 行：
    A 的 m 1.0 版 × L 43.5、44 × α 44.35、50，再加 α 55 × L 44.75。entry_offset 固定为 0。b8 的 W-0 L 显示偏移固定时 L 变长转动持续下降，这批回答
    这个增益在 m 1.0 上还在不在、能不能和 α 叠加。对照 = 同 α 的 WS_m1（b14、b15，必须 DONE）。不可行、偏移不是 0、A0 比对照小 5 % 以上、模板化报错 → 问题。
    标签用 _wl_ 开头，所以 m1_a* 这类通配符不会把它们算进 b15。判据写在第三版第 7 节 G21。

批次 b16、b17、b18（v1.12，2026-11-02，第三版计划第 3.3 节，用户"批准这三批"；不改 jobs.py，都排在 b7m 之后）：
    b16 = VAL-1，层 VAL-1，stage db_ref，kind intact：3406 h 2.0 完整股骨只改 cfg.load 和 h_far。第一份实测对仿真，判据是第三版第 7 节 G11。
       Naghavi 2023 第 5 章：1200 N，ISO 7206-4 的 10° 内收、9° 屈曲，方向符号与楼梯相同（力指向外、后、下），远场 6 mm 和 2.5 mm 各一行（测点高度的皮质单元边长约 5.0 和 2.8 mm；4 mm 只到 4.1 mm）。
       Bath F10：500 N，力沿 F10 的 CT z 轴，换到它的干轴系是 α_front −2.45°（偏内）、α_sagit +3.28°（偏后），远场 2.5 mm。
       F10 比 3406 小，且力线偏头心 7.1 mm，所以 Bath 行只报告，不作判据。
    b17 = TQ-0，层 TQ-0，stage db_cd，只解摩擦：A、A 的 m 1.0 和 m 1.5 版、A 的 α 60 版、init29、al1_07 × 楼梯方向 3606 N、20° / 40° 2391 N。
       只改头力，不用钩子。stage_al.load_training 不用 α_sagit > 18° 的行（超出条件框）；3606 N 的行在框内，照常用。
    b18 = MU-1，层 MU-1，stage db_cd，只解摩擦（粘接模型与 μ 无关）：13 个设计 × μ 0.2，其中 7 个再 × μ 0.15。stage_al.load_training 本来就不用 μ ≠ 0.3 的行。
    b17、b18 的 A 单因素版以 b14 的同名作业作基线，基线不是 DONE → 问题。b17、b18 等 b16 过 G11 之后才启动。

批次 b8、b12（v1.9，2026-11-02，第二周计划第二版，用户"按这个改"；只写批次与干跑，喂料顺序等 b14 的结果定）：
    b8 = NZ-3 + W-0′。NZ-3 db_nz：第 2–5 名（a82、a96、a100、a95）× h 1.94 / 2.06，带粘接，同网格参照 = b1 的 REF 行（必须 DONE），定噪声值。
       W-0 alpha db_ws：A × α 47、a62 × α 47 / 50（A × α 50 就是 b14 的 WS_a50，不重复），入口偏移由模板化决定，离开基准 e* = 问题。
       W-0 L db_ws：A、a62 × L 42.5 / 43.5 / 44 / 44.5，entry_offset 固定为基准 e*（A0 仍会重新模板化，所以 L 悬崖只拆开一半）；0-FE 不可行的行不提交，记 WARNING。
       原计划的 m 0.35 / 0.25（h 1.4）4 行删掉：往更薄推手术做不到，网格也分辨不了。W-0 全部带粘接，source bound_scan。
    b12 = CY-1：只解摩擦（粘接模型与循环无关），stage db_cd，source cycle_variant。4 循环：A、A 的 m 1.0 版、a82、a96、a100、a95、db_al_al1_07；
       10 循环：A、A 的 m 1.0 版、init29、C。4 循环在前，层慢启动，所以最先的 2 行就是多循环后处理的冒烟。stage_al.load_training 不用 cycles ≠ 2 的行。
       线弹性加库仑摩擦不能预测长期迁移，这批只回答残留是否饱和、循环后排序变不变。

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
DB_STAGES = ("db_ref", "db_sf", "db_cr", "db_crt", "db_cd", "db_nz", "db_fd", "db_bd", "db_bo", "db_al", "db_opt", "db_ws")   # 规划 1.6 + db_bo（只粘接补算）
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
H14_LAYERS = ("FD-0 h1.4", "FD-1 h1.4", "OW-4 h1.4")     # 这些层的行在 DB_H14_EXCLUSIVE 模式下也独占
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
                     "AL-2", "AL-2 sts", "AL-2 rand", "AL-3", "AL-3 sts", "AL-3 rand", "WS m", "WS alpha", "NZ-3", "W-0 alpha", "W-0 L", "CY-1", "AL-3m", "AL-3m sts", "AL-3m rand", "WS m alpha", "TQ-0", "MU-1", "WL-1", "CD-2", "OW-2", "OW-3", "OW-4", "OW-4 cy", "OW-4 h1.4", "TQ-1 smoke", "PF-1 smoke", "WS m2", "AL-4m", "AL-4m sts", "AL-4m rand", "OPT-1", "STS-1", "STS-1 mesh", "FAM-1", "FAM-1 ctrl", "FAM-1 rep", "FAM-1 h1.4", "FAM-1 sts", "RS-1", "OF-1", "R2")
                                            # 新层慢启动（REF 串行、CD-0 是种子：不在内）
SLOW_START_CAP = 2                          # … DONE 不到 SLOW_START_DONE 行之前，该层在飞（NEW / READY / CLAIMED / SOLVED）最多 2 行
SLOW_START_DONE = 2
WAIT_EVERY = 10                             # 没有提交时：第 1 轮及之后每 10 轮记一行 WAIT
HEARTBEAT_S = 600.0                         # 不论有没有待提交的行：每 10 min 一行 HEARTBEAT
_mono = time.monotonic                      # HEARTBEAT 的计时（测试换成假时钟）
CODE_ROOT = HERE.parent                     # Linux：~/mobo_toy_v2/code
AUX_FILES = ("inp_writer.py", "v2/collar_rule.py", "v2/jobs.py", "v2/stability.py", "v2/femur_3406.py", "abaqus/odb_export.py", "v2/torsion_load.py", "v2/pose_fixed.py")
_ALLOW_NON_LINUX = False                    # 只给测试：feed 默认只在 Linux 上跑

# 规格键分类：物理键进 spec（影响建模 / 求解 / 后处理）；角色键由本模块重写；元数据键丢掉。三者之外的键 → SystemExit
PHYS_KEYS = frozenset({"design", "h_int", "min_A0", "model", "h_cut", "slip_tol", "delta", "mu", "torque", "E_canc", "interference",
                       "lagrange", "cycles", "collar_rule", "femur_id", "neck_axis", "margin_check", "ref_cut_mm", "a_bounds_max", "cfg",
                       "entry_offset", "margin", "h_far", "bond_collar", "import_stem", "import_e", "export", "intact_substituted_h", "torsion", "pose_fixed"})
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
                "AL-2": "al_adaptive", "AL-2 sts": "al_adaptive", "AL-2 rand": "al_random",
                "AL-3": "al_adaptive", "AL-3 sts": "al_adaptive", "AL-3 rand": "al_random",
                "AL-3m": "al_adaptive", "AL-3m sts": "al_adaptive", "AL-3m rand": "al_random",
                "WS m": "bound_scan", "WS alpha": "bound_scan", "WS m alpha": "bound_scan",
                "NZ-3": "noise", "W-0 alpha": "bound_scan", "W-0 L": "bound_scan", "CY-1": "cycle_variant",
                "VAL-1": "intact_ref", "TQ-0": "cond_anchor", "MU-1": "cond_anchor", "WL-1": "bound_scan",
                "CD-2": "cond_anchor", "OW-2": "bound_scan", "OW-3": "bound_scan", "OW-4": "cond_anchor", "OW-4 cy": "cycle_variant", "OW-4 h1.4": "fid_h14", "TQ-1 smoke": "cond_anchor", "PF-1 smoke": "cond_anchor",
                "WS m2": "bound_scan", "AL-4m": "al_adaptive", "AL-4m sts": "al_adaptive", "AL-4m rand": "al_random", "OPT-1": "al_adaptive", "STS-1": "cond_anchor", "STS-1 mesh": "noise",
                "FAM-1": "al_adaptive", "FAM-1 ctrl": "noise", "FAM-1 rep": "noise", "FAM-1 h1.4": "fid_h14", "FAM-1 sts": "cond_anchor",
                "RS-1": "corner", "OF-1": "bound_scan", "R2": "al_adaptive"}
LAYER_SELECTION = {"REF": "reference", "VAL-1": "reference", "SF-1": "iid", "CR-T": "corner_test", "CD-1 rand": "iid", "AL-1": "adaptive", "AL-1 sts": "adaptive",
                   "AL-1 rand": "iid", "AL-2": "adaptive", "AL-2 sts": "adaptive", "AL-2 rand": "iid",
                   "AL-3": "adaptive", "AL-3 sts": "adaptive", "AL-3 rand": "iid",
                   "AL-3m": "adaptive", "AL-3m sts": "adaptive", "AL-3m rand": "iid",
                   "AL-4m": "adaptive", "AL-4m sts": "adaptive", "AL-4m rand": "iid", "OPT-1": "adaptive", "FAM-1": "adaptive", "R2": "adaptive"}          # 其余层 stratum（tools/db_export.DB_STAGE_RULES：db_sf = sf / iid，db_cr = corner / stratum，
                                                # db_crt = corner_test / corner_test，db_bd = offset_variant；AL 的非随机选点在排除集 E）
BATCHES = ("b1", "b2", "b1b", "b2b", "b3", "b4", "b5", "b6", "b7", "b14", "b8", "b12", "b7m", "b15", "b16", "b17", "b18", "b19", "b9p", "b11p", "b20", "b21", "b22", "b23", "b24", "b25", "b26", "b27", "b28", "b28c", "b29", "b30", "b31")
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
AL_BATCHES = {"b5": ("al1", "AL-1", "AL1"), "b6": ("al2", "AL-2", "AL2"), "b7": ("al3", "AL-3", "AL3"), "b7m": ("al3m", "AL-3m", "AL3M"),
              "b21": ("al4m", "AL-4m", "AL4M")}   # 批次 -> (stage_al 轮 = results/db_al_<轮>.json, 层前缀, 行键前缀)
WS_BASE = "A"                               # b14：扫描的基准设计（CODES 的键）
WS_M = (0.75, 1.0, 1.5)                     # b14：余量（A 是 0.5，盒子下限）
WS_ALPHA = (50.0, 55.0, 60.0)               # b14：插入角（A 是 44.35°，盒子上限 45°；α 65° 时 e* 跳到 −2，所以停在 60°）
NZ3_JOBS = ("sb13_a82_cd8c77ad", "sb13_a96_429a3bcc", "sb13_a100_b1cce588", "sb13_a95_173c181a")   # b8：第 2–5 名（v0.5 基线）
NZ3_H = (1.94, 2.06)
WS2_M = 1.0                                 # b15：A 的 m 1.0 版，台架用的余量
WS2_ALPHA = (50.0, 55.0, 60.0)              # b15：与 b14 的 α 行同样三档
WM2_M = (1.6, 1.75, 2.0)                    # b20：接着 b14 的 m 扫描，去骨 7.19、6.92、6.67 cm³
WM2_CONTROL = 1.5                           # b20：对照 = b14 的 WS_m1.5
WM2_E_JUMP = {2.0: -2.0}                    # b20：m 2.0 的模板跳到 e −2，用户 11-03 批准的例外；其余行的 e* 必须等于 A 的
W0_ALPHA = (("A", 47.0), ("a62", 47.0), ("a62", 50.0))   # b8：A × α 50 是 b14 的 WS_a50
W0_L = (42.5, 43.5, 44.0, 44.5)
W0_L_CODES = ("A", "a62")
CY_EXTRA = {"a82": "sb13_a82_cd8c77ad", "a96": "sb13_a96_429a3bcc", "a100": "sb13_a100_b1cce588", "a95": "sb13_a95_173c181a",
            "al1_07": "db_al_al1_07_b4ea44f0"}
CY_C4 = ("A", "Am1", "a82", "a96", "a100", "a95", "al1_07")   # b12：Am1 = A 的 m 1.0 版
CY_C10 = ("A", "Am1", "init29", "C")
# ---------------------------------------------------------------- 批次 b16、b17、b18（第三版计划第 3.3 节；模块说明）
VAL_LOADS = {"n1200": {"resultant_N": 1200.0, "alpha_front_deg": 10.0, "alpha_sagit_deg": 9.0},    # Naghavi 2023：ISO 7206-4，1200 N
             "b500": {"resultant_N": 500.0, "alpha_front_deg": -2.45, "alpha_sagit_deg": 3.28}}    # Bath F10：力沿 CT z 轴，换到它的干轴系
VAL_ROWS = (("n1200", None), ("n1200", 2.5), ("b500", 2.5))   # (载荷, 远场网格 mm；None = 不写 h_far，jobs.prep 用默认 6.0)
TQ0_LOADS = {"F3606": {"resultant_N": 3606.0, "alpha_front_deg": 20.0, "alpha_sagit_deg": 18.0},   # 楼梯方向，Bergmann HIGH100 的合力
             "S40": {"resultant_N": 2391.0, "alpha_front_deg": 20.0, "alpha_sagit_deg": 40.0}}     # 矢状角加大，绕柄轴扭矩约翻倍
TQ0_CODES = ("A", "Am1", "Am1.5", "Aa60", "init29", "al1_07")
A_WS = {"Am0.75": {"m": 0.75}, "Am1": {"m": 1.0}, "Am1.5": {"m": 1.5}, "Aa60": {"alpha": 60.0}}   # A 的单因素版 = b14 的 WS 行
MU1_CODES = ("A", "Am0.75", "Am1", "Am1.5", "a82", "a96", "a62", "B", "Bp", "D", "init29", "C", "al1_07")
MU1_LOW = ("A", "Am1", "Am1.5", "a62", "init29", "C", "al1_07")
MU1_MU, MU1_MU_LOW = 0.2, 0.15
WL1_ROWS = ((None, 44.0), (50.0, 44.0), (None, 43.5), (50.0, 43.5), (55.0, 44.75))   # b19：(α，None = A 自己的；L)
WL1_E = 0.0                                 # b19：入口偏移固定为 0
WL1_A0_MIN = 0.95                           # b19：A0 比同 α 对照小 5 % 以上 = 跳变（α 50 × L 44.25 时 A0 从 488 掉到 401）
CD2_EXTRA = {"al2_08": "db_al_al2_08_92f70858", "al1_13": "db_al_al1_13_3f55946f", "c4055": "db_cr_c4055_bdc4dc11", "a24": "sb14_a24_4dd6e4a2",
             "al3m_11": "db_al_al3m_11_b7f5e0eb", "al3m_01": "db_al_al3m_01_a6949792", "al3m_04": "db_al_al3m_04_b4c86b5f"}   # b9p 的源作业
CD2_SINGLE = ("Am1", "Am0.75", "al1_07", "al2_08", "al1_13", "c4055", "a82", "a96", "a24", "al3m_11", "al3m_01", "al3m_04", "AL44")
CD2_JOINT = ("A", "Am1", "Am0.75", "a82", "a96", "a62", "B", "al3m_11")
CD2_DELTA = 0.05
CD2_LOAD = "F3839"
OW2_ROWS = (("A", -2.0), ("A", 2.0), ("a100", 0.0), ("a100", -2.0), ("a100", 2.0), ("a95", 0.0), ("a95", -2.0), ("a95", 2.0), ("a82", 0.0), ("a82", -2.0), ("a96", 0.0), ("a96", -2.0))   # b11p：(设计，入口偏移)
OW3_ROWS = (("A", -1.0), ("A", -0.5), ("A", 0.5), ("A", 1.0), ("A", 1.5), ("A", 2.5), ("a95", 1.0), ("a95", 1.5), ("a95", 2.5))   # b22：(设计，入口偏移)
OW4_E = (1.0, 2.0, 2.5)                     # b23：A 的 m 1.0 版的入口偏移
OW4_CY_E, OW4_CY_N = 2.0, 10                # b23：10 循环的一行
OW4_H14_E = 2.0                             # b23：h 1.4 的一行
TQ1S_E = (None, 1.5, 2.5)                   # b24：A 的 m 1.0 版的入口偏移，None = 规则选的 e 0（= WS_m1，spec 没有 entry_offset）
TQ1S_T, TQ1S_PRELOAD = 10.0, 1000.0         # b24：扭矩 N·m，定义 A 的预载 N
PF1S_ROWS = ((None, -1.0), (None, 1.0), (1.5, -1.0), (1.5, 1.0))   # b24：(名义入口偏移，号固定时的 de)
STS1_LOAD = "F1714"                         # b26、b27：坐起载荷
_A = "db_ws_p13_a105_91e458e3_"
STS1_ROWS = (("A_m1_L44", _A + "wl_m1_L44_08f4c01a"), ("A_m1", _A + "m1_2a79b613"), ("A_m1_e+0.5", _A + "ow_m1_e+0.5_c17f7b2a"), ("a96_m1", "db_ws_p13_a96_429a3bcc_ow_m1_e+0_4107fde2"),
             ("A_m1_e+1", _A + "ow_m1_e+1_fea69910"), ("A_m1_e+1.5", _A + "ow_m1_e+1.5_52dc478a"), ("A_m1_e+2", _A + "ow_m1_e+2_c9ca96c8"), ("A_m1.5", _A + "m1.5_96e9b62a"),
             ("a95_m1_e+2.5", "db_ws_p13_a95_173c181a_ow_m1_e+2.5_67a9f0f2"), ("A_m1_e+2.5", _A + "ow_m1_e+2.5_8a2bd628"), ("A_m1.75", _A + "m1.75_3bd4ac69"),
             ("al3m_01", "db_al_al3m_01_a6949792"), ("al3m_06", "db_al_al3m_06_7d0063e3"), ("al3m_04", "db_al_al3m_04_b4c86b5f"), ("opt1_08", "db_al_opt1_08_e+0_68d23c0c"))   # b26：(标签，基线行)
STS1M_ROWS = (("A_m1", _A + "m1_2a79b613"), ("A_m1_e+2", _A + "ow_m1_e+2_c9ca96c8"))   # b27 的网格行
STS1M_H = (1.94, 2.06)
# b25：(入口偏移, 0 FE 的号 mm², 0 FE 的去骨 mm³, u13)，按去骨量排，来自 opt_F微动去骨_2026-11-04/data/opt1_rows.json
OPT1_ROWS = ((1.75, 307.553, 5520.15, (0.9238734473034518, 0.9880550814685174, 0.0009155371515778537, 0.3333333333333333, 0.26948536016971436, 0.9633428826385353, 0.11927481159104074, 0.6631797347238787, 0.3400441851509651, 0.6166302108848943, 0.2277420214103016, 0.0243847290220348, 0.08446748167943234)),
             (0.75, 338.585, 5707.28, (0.9062866845697284, 0.963108334720332, 0.0006199042520656601, 0.33490138406247505, 0.19503403252161028, 0.9490847917701033, 0.09603108221001742, 0.7895932052821071, 0.39119710883620185, 0.636480529738682, 0.180634829524856, 0.09772494131541568, 0.07696422299523359)),
             (1.0, 379.194, 6607.41, (0.8868491782424296, 0.9804531673100162, 0.000503291146435535, 0.3333333333333333, 0.265177035500872, 0.9743912200517568, 0.11370196092015283, 0.6407204725688732, 0.37049528926622577, 0.601804089992552, 0.22659777201378833, 0.030196448375811754, 0.1033176512358316)),
             (0.75, 400.108, 7233.92, (0.9487862966417365, 0.994959982342021, 0.0008249149177926827, 0.3333333333333333, 0.27516976046386243, 0.9968314996854876, 0.10778157067750752, 0.6376176486058804, 0.38112553313942593, 0.6577189628761205, 0.21965723308830518, 0.005155062498427006, 0.08481495552510232)),
             (0.25, 418.395, 7354.66, (0.9066468350575939, 0.9628233466401147, 0.002287864415936821, 0.3333333333333333, 0.26430908215971516, 0.9944180635027176, 0.12076371820843472, 0.6699817562214433, 0.39705982215445296, 0.5559465877812302, 0.26279999198380627, 0.09016779045633572, 0.14777171093942437)),
             (0.5, 425.391, 7695.43, (0.9341569996053715, 0.9873188003607447, 0.005681831748659506, 0.3333333333333333, 0.26754467144631905, 0.984853255553452, 0.1080535987507047, 0.6309090423837912, 0.3606274717609309, 0.6315438489117637, 0.23640153101577277, 0.025287237519955638, 0.11624080821406796)),
             (0.25, 423.483, 7966.38, (0.9540817222306555, 0.9803405568860086, 0.006949525841130198, 0.3333333333333333, 0.30664190807811126, 0.9966706768647708, 0.07946121323748254, 0.6835860418864987, 0.33349636910683983, 0.6256084119439757, 0.23251368939551958, 0.019578439336608404, 0.10046854237054983)),
             (0.0, 468.445, 8410.79, (0.9295018662433129, 0.9996995317168558, 0.0009951799356235995, 0.3333333333333333, 0.2757106676371542, 0.9851306897367607, 0.09503493719216276, 0.6506385821989001, 0.3729435879868641, 0.6211644224335073, 0.21092460454500472, 0.005803008392504591, 0.10503181932260096)))
# b28：(标签, 入口偏移, 放置复查时模板化的号 mm², 去骨 mm³, u13)，标签 = 族号 + 角色（b 最好、o 外圈、x 探索），来自 experiments/b28_fam/prep/data/fam1_rows.json
FAM1_ROWS = (("0b", 1.5, 316.943, 5319.45, (0.8151747744098643, 0.9792145560442088, 0.0005097931495173641, 0.3651743841221586, 0.27686167971822156, 0.9862890039465495, 0.10011370354591215, 0.7243739245236769, 0.433782565637235, 0.7168606631937815, 0.4326824442554854, 0.06492109018568895, 0.16003012212603243)),
             ("0o", 1.0, 291.313, 5136.56, (0.7416029752764219, 0.9452041072361137, 0.0049672315550910685, 0.35798003031185527, 0.38696940213153574, 0.9816862074530162, 0.21127914632429334, 0.7707893541048161, 0.609269558034536, 0.3734362568222404, 0.21973870923432792, 0.004645930791640071, 0.17775637209881756)),
             ("0x", 2.0, 245.482, 4922.81, (0.719098743403547, 0.9770657345546347, 0.024072315066181613, 0.33814026335662944, 0.40840760860471925, 0.7814399903595854, 0.28164562761847467, 0.5820334636159936, 0.6295745645541458, 0.5693665286023428, 0.23073253440139802, 0.04756408671945648, 0.036998230245107185)),
             ("1b", 2.0, 349.708, 5310.19, (0.7851727428209799, 0.9932991211511448, 0.015288544061092117, 0.3380577981781537, 0.09952512294121321, 0.9584060145972627, 0.02222323345147066, 0.6668040315496991, 0.32909420977400367, 0.8103021751399987, 0.20854089634176312, 0.10244429627364429, 0.20681407962131204)),
             ("1o", 0.5, 307.294, 4686.74, (0.6004595343152879, 0.8924146805718808, 0.00011299972387193678, 0.34690720687714444, 0.12230745578330765, 0.6060593354119055, 0.008569945439368384, 0.8412975698365481, 0.4706635484364171, 0.8860304853238422, 0.18017619779954863, 0.07847710805294701, 0.3941575376888594)),
             ("1x", 0.5, 309.547, 5630.77, (0.7973766083225152, 0.9584225697839849, 0.03319191067626582, 0.3832388958289568, 0.22290505619493875, 0.9043696092241611, 0.14669189022948728, 0.8392646084764447, 0.6663358325277611, 0.6464749010722304, 0.07642717376034072, 0.06994295937302089, 0.11748609502378163)),
             ("2b", 0.5, 289.111, 6181.92, (0.9022200369822886, 0.9993217867484465, 0.012361893540560392, 0.3339484512325495, 0.42628767874211004, 0.8012637073428658, 0.15402217956131198, 0.8605487368774485, 0.2706981891666819, 0.6386366435554924, 0.20077171626561097, 0.053341161287702187, 0.44128456835080854)),
             ("2o", 0.0, 319.986, 6819.32, (0.9022200369822886, 0.9993217867484465, 0.012361893540560392, 0.3339484512325495, 0.42628767874211004, 0.8012637073428658, 0.15402217956131198, 0.8605487368774485, 0.2706981891666819, 0.6386366435554924, 0.20077171626561097, 0.053341161287702187, 0.44128456835080854)),
             ("2x", 2.0, 264.316, 4677.33, (0.7470245893333101, 0.9606546669388001, 0.03462210060999056, 0.4401208470076896, 0.2213979679309333, 0.975004365766363, 0.24413272684930323, 0.6898032984360125, 0.2344615519999725, 0.6053609633288533, 0.0994712172742158, 0.006900820146572424, 0.19991816240510385)),
             ("3b", 1.5, 305.313, 5361.64, (0.8911481315067205, 0.9934411425099255, 0.0029234742922938485, 0.37084252264237794, 0.26286437405138124, 0.9780866915772244, 0.11918235342362452, 0.7523666282135032, 0.28640972175110246, 0.46547128019726336, 0.19274979271519735, 0.10459201785394324, 0.2024907419248294)),
             ("3o", 0.5, 334.423, 6623.28, (0.9097908741179369, 0.9932482251431306, 0.030260296682760028, 0.3346667272012543, 0.28004431614321157, 0.9005172842835136, 0.03009945576080436, 0.9090286441966418, 0.31319504318750413, 0.38905310770906915, 0.1487970879394891, 0.23042916150497655, 0.021928898628228985)),
             ("3x", 0.5, 360.082, 5541.68, (0.5159044311089684, 0.9968382670757313, 0.027166300360043322, 0.4444297523926939, 0.21000839142118882, 0.7666087133788168, 0.033976298486097414, 0.8762769466421393, 0.6067769078816451, 0.5435325573439871, 0.14166647596288057, 0.07806579641078404, 0.11153889209782719)),
             ("4b", 2.0, 340.398, 5088.77, (0.7899223370966193, 0.9714865194921449, 0.0004679497542485134, 0.371776564033574, 0.11425869290686308, 0.9109415966912181, 0.13396830255166817, 0.5610573023608824, 0.35458966750911197, 0.5432410061680841, 0.13466082400417745, 0.014634466587615793, 0.12360593789804826)),
             ("4o", 2.5, 299.029, 4859.14, (0.8270292986795835, 0.9018448599120685, 0.03134338173132872, 0.36918084395530026, 0.08073576981358646, 0.9792461817627999, 0.18895207563147315, 0.5092004099408287, 0.3043730029392667, 0.6523614546106055, 0.5271724004375096, 0.1391037541208775, 0.2264503828061699)),
             ("4x", 2.5, 298.105, 5162.05, (0.6876255268674525, 0.9589231335342329, 0.0444754547814674, 0.3976104770901137, 0.17100727152264, 0.8838044994257479, 0.14165991909780135, 0.5651933896685438, 0.37708664610395387, 0.4784255731877985, 0.26633789302980226, 0.1739454412648285, 0.0610778919808741)))
FAM1_CTRL = (("e+1", _A + "ow_m1_e+1_fea69910"), ("e+2", _A + "ow_m1_e+2_c9ca96c8"))   # b28 的阴性对照：基线行 × h 1.94
FAM1_CTRL_H = 1.94
FAM1C_WINNERS = ("3b", "1b", "0b")         # b28c：b28 的初判赢家标签（FAM1_ROWS 的第一列），b28 的 15 行算完后按 proposal 第 4 节的规则填，最多 5 个
# b29 / b30 / b31（五天计划，用户 11-08"整份批准"）：(标签, 入口偏移, 模板化的号 mm², 去骨 mm³, u13)，来自 experiments/prep_2026-11-08/data/
RS1_ROWS = (('rs01', 0.0, 250.078, 9035.26, (0.7726685171981609, 0.7391975123134441, 0.27728865748083464, 0.49450709057455866, 0.42161318394519365, 0.8893279294175483, 0.28541087640990337, 0.7448212889670717, 0.5514812233526453, 0.92071513101912, 0.1348967045000517, 0.16374574833852393, 0.15686043000631442)),
            ('rs02', 0.0, 342.606, 7206.72, (0.8602192163717151, 0.9335276799506885, 0.06309341990767266, 0.3682098629521757, 0.32515251667524775, 0.9714224104077871, 0.1817055283757869, 0.8374690267606715, 0.37629025731748617, 0.718688867478505, 0.22600942894045353, 0.022015111413723476, 0.09623815562929608)),
            ('rs03', 2.0, 319.178, 6960.0, (0.8269151078424363, 0.9010382945346147, 0.1420885598287497, 0.41651552360866545, 0.05140127902365968, 0.9147758712511176, 0.3075352331660488, 0.5139075220841441, 0.35697644757344, 0.5822143779372653, 0.35589540472982284, 0.1394850907076299, 0.16193800433192607)),
            ('rs04', 2.0, 246.658, 4158.0, (0.7800488084861409, 0.9126753212975381, 0.010951584874304763, 0.3515408028965341, 0.2422564351239589, 0.9640261113231413, 0.2141108428840128, 0.7267273942040883, 0.4260264561122843, 0.4063191574620947, 0.3442138550472613, 0.1041143251935813, 0.11218205516804283)),
            ('rs05', 1.0, 381.761, 6901.98, (0.8086273044367036, 0.9844536568669205, 0.008612904341519926, 0.3640643566592654, 0.3399668777638607, 0.9437298876765363, 0.061148942699120294, 0.5544248140345536, 0.5276377699565601, 0.6442265873067202, 0.174298141446305, 0.07262864144904801, 0.22291937382227855)),
            ('rs06', 1.0, 378.875, 7213.9, (0.9023182862388126, 0.9382952096029802, 0.007999811880186105, 0.42966942567983907, 0.3332326737189032, 0.933348193278478, 0.1386904491525396, 0.28750798615430184, 0.1303559072440617, 0.3873866756032161, 0.4256960333084906, 0.17590586631708488, 0.07078883459394109)),
            ('rs07', 2.0, 315.965, 5489.52, (0.9250323074828107, 0.9592711039444771, 0.0021782399395506805, 0.4265035583025408, 0.08242852172146434, 0.7133092889132572, 0.06567128702849769, 0.3706990923077118, 0.2435373384801454, 0.8091394238279225, 0.2860472075216758, 0.14767657934136852, 0.3415470730313235)),
            ('rs08', 0.0, 207.094, 5878.03, (0.7378616545934633, 0.7312663938285243, 0.12735890310278306, 0.5350516075602116, 0.40929672388636884, 0.8519177375596845, 0.07459161920932873, 0.8877882407642899, 0.5878568529107702, 0.758414778317799, 0.14006992289267983, 0.047740007411960654, 0.3475658022403888)),
            ('rs09', 1.0, 374.534, 7343.68, (0.8096718044011456, 0.9092686421441493, 0.03314510787482144, 0.3823237590704712, 0.3855102479792864, 0.9780469916444513, 0.16198238476079518, 0.45211953161789387, 0.3643543110471836, 0.5714532943695217, 0.21894284252808893, 0.0914841050837357, 0.17349202177469647)),
            ('rs10', 0.0, 440.603, 8377.6, (0.6959176536133717, 0.8968364430704358, 0.08076779787773537, 0.3759757830270823, 0.3158558051848538, 0.999374266218255, 0.045621877298496594, 0.7554281911273736, 0.4487205968932534, 0.5290578464167509, 0.26063220658562325, 0.00468346935544945, 0.016627954785893004)),
            ('rs11', 1.0, 240.293, 6086.23, (0.9499604853835116, 0.8116070643106319, 0.11868822388242738, 0.5012111391977276, 0.20315310867191763, 0.99012341874018, 0.018656165297864596, 0.6538553373307784, 0.3007810503717452, 0.5282949391938592, 0.056432871313225746, 0.1417045545028285, 0.008430167117047555)),
            ('rs12', 2.0, 228.888, 6611.95, (0.8915100492962013, 0.8628020898269964, 0.11836993161553301, 0.35119693692176446, 0.4702683608407183, 0.9392644823079903, 0.07905736506116076, 0.5386226260284193, 0.32485860316875503, 0.7220669101928693, 0.15524862808644221, 0.004212024031557284, 0.14190406828228697)),
            ('rs13', 0.0, 399.322, 8313.47, (0.7137188377043293, 0.9401913350657262, 0.08603632364131945, 0.4737151998406033, 0.3281418527326653, 0.8162749007405664, 0.1742072672930228, 0.6551985227310717, 0.31690962699996383, 0.5599436454997985, 0.16610850935223687, 0.0762033818016566, 0.14437563134046716)),
            ('rs14', 0.0, 438.503, 6552.09, (0.8279275253334628, 0.984222789841259, 0.014835504291661751, 0.42530280942379417, 0.06182071048125462, 0.9561263266200731, 0.2099909140095581, 0.6813483205795635, 0.32261604387627846, 0.4411164600335762, 0.22279589012959916, 0.01818513285356321, 0.023432634443942918)),
            ('rs15', 2.0, 239.889, 5541.51, (0.9039725837802659, 0.9128985429530304, 0.11909360353685128, 0.37334872544278563, 0.057539783549511836, 0.974434453702597, 0.1015051128966491, 0.5507326736448264, 0.4184024598483718, 0.5635572627874822, 0.1853631007054589, 0.20228934189900036, 0.15571364791577613)),
            ('rs16', 1.0, 338.395, 8829.03, (0.6702789467926379, 0.9619378020329525, 0.19029374448571645, 0.4533406587589277, 0.41954197431552265, 0.9715968697742701, 0.19284347085644993, 0.6109782261200454, 0.09847271226780963, 0.899123836872733, 0.050860198163750175, 0.1897155454716504, 0.4012827390256053)),
            ('rs17', 1.0, 218.331, 6544.91, (0.7872892996314774, 0.6758525074723067, 0.15689602193972904, 0.34247025442566087, 0.3793784528506304, 0.8947569142121911, 0.005441832557588858, 0.6500724433747953, 0.3237134372655195, 0.81612597990804, 0.27610082310247686, 0.07022282546897668, 0.0745687736099633)),
            ('rs18', 1.0, 298.105, 10144.79, (0.7953003898928097, 0.751118644768117, 0.30463162929456394, 0.34502709902901635, 0.2701095491074648, 0.7402364085916429, 0.2553481371618287, 0.58093346403651, 0.31846771555298264, 0.4690809686801872, 0.27354109181159153, 0.019088605941598648, 0.03811388714410266)),
            ('rs19', 1.0, 262.761, 5815.04, (0.745138078549787, 0.8891209544726388, 0.06988179181750119, 0.45382513349752074, 0.3943384419897068, 0.9453106895073647, 0.12214520332915699, 0.7812193906257577, 0.4949057767735607, 0.7066903188862464, 0.23834577605222776, 0.05270446747513053, 0.0915101213995823)),
            ('rs20', 1.0, 239.956, 7922.18, (0.7913278493513471, 0.791849930458361, 0.21687821296346144, 0.5081661822635786, 0.31381233615139886, 0.7306909165975859, 0.2037745899466525, 0.6563069490429632, 0.421947158153942, 0.6844613361127445, 0.32162638020340756, 0.21239844762196802, 0.20235736375273525)),
            ('rs21', 2.0, 260.847, 6060.99, (0.6239059342805846, 0.943190166214193, 0.09899708507409109, 0.6041546590372436, 0.4529899873257051, 0.9506772357871465, 0.15737123323191132, 0.5748935871573662, 0.6810636351653852, 0.6060315678012764, 0.506712787715317, 0.06400373436402985, 0.271110069877738)),
            ('rs22', 0.0, 362.213, 7511.94, (0.6624840182210798, 0.9553338969695365, 0.10810922613937823, 0.3521502456782514, 0.22070329598578678, 0.7656460324939437, 0.43269185296638, 0.6434503368852714, 0.21917481542592238, 0.6080483900108062, 0.24589427283419135, 0.09667766339639615, 0.4504042662256603)),
            ('rs23', 1.0, 266.479, 4442.98, (0.7139819728962303, 0.780832746560731, 0.026423917903624826, 0.47578498575790606, 0.1974602608137596, 0.9508072943870924, 0.08126611659431168, 0.6533651000238909, 0.4944144663160577, 0.6055911810337774, 0.13677894243991484, 0.09927350029609514, 0.1334043961169944)),
            ('rs24', 0.0, 373.903, 7476.48, (0.7583225657733735, 0.8919671923898211, 0.05528103665519694, 0.34398060393787083, 0.34271324324895036, 0.8844883890806968, 0.24651429073399064, 0.647977823556581, 0.36798765696160846, 0.6570084794651614, 0.23107674537411954, 0.017813803542721853, 0.04556696226732624)),
            ('rs25', 0.0, 226.648, 5744.68, (0.8934116250955927, 0.8856866134596847, 0.038743388204780994, 0.6022637765349427, 0.6350565085491956, 0.9448440526972004, 0.20990228721156906, 0.6923725467716525, 0.4799013932563854, 0.6653772496416196, 0.18078617933795318, 0.24803141713060697, 0.32295924992782565)),
            ('rs26', 2.0, 313.929, 6711.32, (0.7501976036357155, 0.8295477274385629, 0.1560232983302902, 0.4784907031786554, 0.008567969232400663, 0.9255830564370028, 0.15125351794046132, 0.5667003231341375, 0.3698258346417393, 0.6424274096303078, 0.21774504340187867, 0.14272901919730258, 0.17946177123685658)),
            ('rs27', 0.0, 423.959, 7838.22, (0.9393872563618754, 0.9896636777729778, 0.011163951289384286, 0.4754520760280102, 0.2724112413092489, 0.9748434955689682, 0.027337762509791252, 0.6132602784940294, 0.48927477501157945, 0.6957424003703798, 0.2790042964405434, 0.15124030482822415, 0.24731061265341792)),
            ('rs28', 2.0, 253.546, 6183.98, (0.8035210426685081, 0.8839885417214021, 0.0964163921642767, 0.39580926485479173, 0.2934144692346022, 0.7797668807688518, 0.013771259792264998, 0.6710073927153961, 0.269449172648856, 0.7084680525968164, 0.24168418074890585, 0.06214716514206962, 0.15719759108701237)),
            ('rs29', 0.0, 311.205, 6923.34, (0.8081577693106976, 0.7765486993052397, 0.05943878361670021, 0.3919468341993757, 0.25441261635049567, 0.6005259894139169, 0.00016249832499093397, 0.4958511205043955, 0.040638847079395135, 0.8277473831084877, 0.27967139647136674, 0.04046156193102883, 0.024012355504198828)),
            ('rs30', 1.0, 283.08, 5299.87, (0.939943598050308, 0.887361057250725, 0.03981622295122446, 0.38163591668117813, 0.09033488010333024, 0.865050499287356, 0.11069709013021271, 0.7672325957794945, 0.45949674556705006, 0.7286908141310142, 0.1344713384709521, 0.057543943120882776, 0.10182883161302156)),
            ('rs31', 1.0, 276.164, 4947.83, (0.9552933541051654, 0.8065931950890892, 0.0390863476983269, 0.35147587516701867, 0.0730379383786392, 0.9763193674644061, 0.13331784903522242, 0.7174863934068352, 0.5885610276444937, 0.8246463943549972, 0.2603301253361627, 0.011750329049119514, 0.27957658480027087)),
            ('rs32', 0.0, 410.936, 7600.66, (0.7371797425016999, 0.9776415166524901, 0.020345715377503227, 0.3827671908319247, 0.38900564295230305, 0.912642216265253, 0.14895334512090647, 0.6295887256354424, 0.5026872259308544, 0.6226614862675841, 0.13953641666004873, 0.07350832564997556, 0.08124631371053494)),
            ('rs33', 1.0, 342.028, 7119.67, (0.9115977416954464, 0.9558719571483598, 0.036511026370279594, 0.44514681520306987, 0.3522221787227897, 0.9397589136537593, 0.011079845823045512, 0.7025940599026514, 0.17959957563714052, 0.7578625492696555, 0.203892280040201, 0.019094592429084477, 0.04187206523884568)),
            ('rs34', 0.0, 343.474, 7153.91, (0.9324338472983659, 0.894567272781394, 0.0391458476468589, 0.3949728388456146, 0.336571901070479, 0.9630717529479853, 0.08761772217322952, 0.6039388868301026, 0.5675116307219358, 0.5564473753586515, 0.11875300181964604, 0.21405919304296778, 0.24423954091757505)),
            ('rs35', 2.0, 252.054, 6641.63, (0.6414975951010186, 0.8557905789348252, 0.1801222079854904, 0.3489913685478325, 0.18962915699857502, 0.8484403144542241, 0.051922350833897866, 0.5373548628651051, 0.5459373921373246, 0.7686630556377736, 0.1753835228675547, 0.5638082442962835, 0.2343204514968137)),
            ('rs36', 0.0, 383.374, 6528.58, (0.7442653400930362, 0.9570689677944164, 0.0465353502980067, 0.428565168237792, 0.17376370761011833, 0.9552631563735665, 0.030708391861512613, 0.8981625914149658, 0.504555497445253, 0.6603192678549398, 0.21446301964274878, 0.17898255262185275, 0.04627684153974032)),
            ('rs37', 1.0, 313.4, 7178.49, (0.8710094164289667, 0.8046584969446462, 0.09496689108777469, 0.3647824436320344, 0.31691772154643244, 0.988849797206574, 0.08830336828978695, 0.5186286608696578, 0.417359642894665, 0.7914147221914749, 0.3260127092510039, 0.09270978368720365, 0.17207777135655333)),
            ('rs38', 1.0, 298.273, 7058.87, (0.7568092162249457, 0.8878258437154256, 0.08466420420814767, 0.3434418947941293, 0.4470790324945654, 0.8463867330761605, 0.14450679179853965, 0.6764114873642181, 0.2926308475288171, 0.6455424582333941, 0.34381345223298154, 0.015374383161462791, 0.15232821184244863)),
            ('rs39', 0.0, 427.549, 8759.86, (0.8611677445770757, 0.9418581119458659, 0.062097478235237986, 0.3739570827473988, 0.33887310785721, 0.9858440633222232, 0.023409098463372274, 0.6884422210946581, 0.36994075599193893, 0.8163021527533966, 0.3678269154826842, 0.04738685879694287, 0.15258313614822083)),
            ('rs40', 0.0, 373.273, 6966.03, (0.791150454310489, 0.9927096104106643, 0.0031735515531152113, 0.4178984318711114, 0.36654874854505065, 0.8170362736067751, 0.08748760275204881, 0.6907092250228934, 0.4685494006110616, 0.757797311210132, 0.08225610268329306, 0.029507590940908747, 0.03290059772384069)),
            ('rs41', 0.0, 239.148, 8461.01, (0.8182654677132112, 0.8379635686911366, 0.24943711959719292, 0.3578768593250622, 0.38536727397343945, 0.8727398183549364, 0.0737366808903901, 0.6235076442029306, 0.3634740885824767, 0.5222592357930941, 0.28051789066193433, 0.0785577285635053, 0.1802340590426169)),
            ('rs42', 2.0, 223.736, 4817.07, (0.7998137004656107, 0.8518828309511217, 0.04189031628165869, 0.527312194041609, 0.40952173775133505, 0.9668834409737884, 0.12342253502653652, 0.5145960738391336, 0.35817442495243, 0.6188192891135699, 0.3395127533317441, 0.08610549097556808, 0.3742211862175375)),
            ('rs43', 0.0, 383.159, 8541.02, (0.901571915561972, 0.9652204740800105, 0.057640907816002084, 0.4515749327222545, 0.37563799559622435, 0.8430938341205475, 0.11281298587781102, 0.4746534678079867, 0.4616945909888792, 0.747830838493418, 0.2844747442712394, 0.26976224313447705, 0.038716915803918873)),
            ('rs44', 1.0, 318.461, 5109.28, (0.4928013686761555, 0.979269308394918, 0.029930048749067285, 0.565580530608167, 0.3780691955941593, 0.9971071598101057, 0.5120191392209305, 0.5671506548057113, 0.47146268293067567, 0.647369234064107, 0.1855507937436341, 0.03866737346929026, 0.15271838390577902)),
            ('rs45', 2.0, 296.018, 5844.04, (0.816440202637167, 0.9708716147624061, 0.04603233867550205, 0.4981775425406766, 0.2636430480303177, 0.8966026493939248, 0.1135763359545327, 0.5869292048161574, 0.3640774874458381, 0.6351679272586248, 0.2780547194555212, 0.06463185691727028, 0.13885146497104411)),
            ('rs46', 2.0, 299.029, 6430.69, (0.7279100524588968, 0.9585025539021791, 0.0899971799272982, 0.35846639865415547, 0.27826176171625594, 0.8740798710635223, 0.07654028796769015, 0.6714251395661935, 0.351723346721715, 0.7343860362043128, 0.26020289973000904, 0.10748718797090426, 0.09018592267246399)),
            ('rs47', 1.0, 388.909, 9052.56, (0.755816299513286, 0.9988954994337198, 0.14119901421669068, 0.4317384613881219, 0.34418509368290023, 0.9186246989117485, 0.008703993618180764, 0.6729274169928017, 0.2792991801719951, 0.6219343650575805, 0.003947163674581117, 0.05853906222005391, 0.08564817632067778)),
            ('rs48', 0.0, 240.767, 6428.8, (0.9649229983655335, 0.7566159378652771, 0.15510666942149395, 0.5265486614576474, 0.07882147515845472, 0.9040167113616282, 0.1393957907384473, 0.6654046902251071, 0.40638125315571194, 0.5717266569061137, 0.29002474982999954, 0.37377476575669266, 0.1490336654125629)))
OF1_ROWS = (('rho_tip-0.15', 0.0, 498.888, 7891.08, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.1291256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('rho_tip+0.15', 0.0, 424.794, 8416.16, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.42912568265727147, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('q-0.15', 0.0, 429.356, 8026.1, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.8494729461601735, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('q-0.30', 0.0, 392.203, 7755.7, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.6994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('n_a-0.15', 0.0, 475.075, 8463.39, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.4895583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('n_a+0.15', 0.0, 457.258, 8145.97, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.7895583174132405, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('g_ap-0.15', 0.0, 450.243, 8021.01, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.22327445342763272, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('g_ap+0.15', 0.0, 448.097, 7982.77, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.5232744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)),
            ('tau_a+0.15', 0.0, 443.585, 7902.4, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.15, 0.08621872496401692)),
            ('tau_a+0.30', 0.0, 420.163, 7485.13, (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.3, 0.08621872496401692)),
            ('3b_back_n_a', 1.5, 300.292, 5274.28, (0.8911481315067205, 0.9934411425099255, 0.0029234742922938485, 0.37084252264237794, 0.26286437405138124, 0.9780866915772244, 0.11918235342362452, 0.7523666282135032, 0.28640972175110246, 0.6395583174132404, 0.19274979271519735, 0.10459201785394324, 0.2024907419248294)),
            ('3b_back_tau_a', 1.5, 308.679, 5420.18, (0.8911481315067205, 0.9934411425099255, 0.0029234742922938485, 0.37084252264237794, 0.26286437405138124, 0.9780866915772244, 0.11918235342362452, 0.7523666282135032, 0.28640972175110246, 0.46547128019726336, 0.19274979271519735, 0.0, 0.2024907419248294)))
R2_ROWS = (('r2_01', 1.5, 305.228, 5378.68, (0.901301582867005, 0.9822830595759832, 0.0009294791597059672, 0.3475536001839518, 0.25521231844892045, 0.9472890928543826, 0.11247207069270415, 0.7463406789435526, 0.29129654451179615, 0.45079393242480675, 0.2263855511635967, 0.1013596563868885, 0.24063246326026852)),
           ('r2_02', 1.5, 319.807, 5597.16, (0.8702724068036358, 0.9953888573126235, 0.007572725804663523, 0.35209539384036836, 0.25465879908816885, 0.9758816154908511, 0.0722336351418306, 0.7719060935046652, 0.2869020986015642, 0.4652736304382381, 0.22226688351124793, 0.12827056958608876, 0.18416382752395435)),
           ('r2_03', 1.5, 318.282, 5466.85, (0.9259028756769366, 0.9629605380496665, 0.003962356374049511, 0.3419727248843792, 0.2065559998847337, 0.985057862922747, 0.06241567422531547, 0.7566300714411536, 0.25547467224019205, 0.48797361126000083, 0.23710915741969513, 0.13731148752940286, 0.18420670709834897)),
           ('r2_04', 1.0, 347.259, 6057.27, (0.9072956175942767, 0.9931032676155755, 0.005617220613111301, 0.3579559175210595, 0.23841814206873163, 0.9920345295617987, 0.11641133412360131, 0.7550308617246201, 0.2968314928046521, 0.4380254364527261, 0.19162729769485154, 0.10665463228398557, 0.21180804285112406)),
           ('r2_05', 1.5, 312.432, 5327.37, (0.8761956195112782, 0.9947741659423346, 0.001455645107177902, 0.35848932880107937, 0.24538181504207865, 0.9866316212505094, 0.12483288526617461, 0.7488808011148291, 0.2993578660037346, 0.45119778419931583, 0.19796520939038564, 0.09858230875073667, 0.20828069657313078)),
           ('r2_06', 1.0, 322.605, 5818.07, (0.9228853171655098, 0.9989589888602871, 0.005374068534506856, 0.3712730892445265, 0.2511191478829945, 0.9456817272604693, 0.13884826715224372, 0.783312789781708, 0.21659554737420827, 0.4369558182741013, 0.18826135479683462, 0.10065698900548382, 0.24435052343883507)),
           ('r2_07', 1.0, 325.063, 5917.73, (0.9199889227570129, 0.979660890381549, 0.00609998812217785, 0.3558744867353779, 0.2714042379555027, 0.9641631909550549, 0.10574130888249968, 0.7924128680520643, 0.29625795613454625, 0.39186363360341914, 0.20238254483640955, 0.11527484578408143, 0.24148279671018102)),
           ('r2_08', 1.5, 305.829, 5152.51, (0.8764651996705428, 0.9770761333477032, 0.0005430106113279037, 0.37265367615982997, 0.22948796138846114, 0.977851722490706, 0.10732454778627787, 0.7743122389934776, 0.25005824978698404, 0.45443974695953826, 0.20450395625698398, 0.05110609668543017, 0.19634537763667329)),
           ('r2_09', 1.5, 310.855, 5471.66, (0.8961456355669847, 0.9885045861274857, 0.00152495051824004, 0.3477291621112321, 0.25182205982243516, 0.9393755408958562, 0.10693770215750185, 0.7352268720375918, 0.2857942490145323, 0.4617359860997611, 0.20475341913241854, 0.09957145699332026, 0.19834745732070758)),
           ('r2_10', 1.0, 337.16, 5928.74, (0.9213451728720732, 0.9767629325490802, 0.0017392546485434368, 0.3591917754299352, 0.2519636919128408, 0.9894960009573092, 0.10037786280936384, 0.7689709277534893, 0.2899171092387168, 0.4588011808635808, 0.2038851633896188, 0.10475340082196917, 0.18409016973090375)),
           ('r2_11', 1.0, 344.731, 5978.45, (0.8890876766605027, 0.9951995725530334, 0.00024276236696417182, 0.3668673543916305, 0.2605610153044465, 0.9808410222281295, 0.11821909084765964, 0.7520444777054095, 0.27081113763456255, 0.4696737887009442, 0.19907729978085079, 0.09300408876268865, 0.19557087950296764)),
           ('r2_12', 1.5, 322.605, 5594.93, (0.8909267119641295, 0.995161491797652, 0.0004362005031048389, 0.36241915938765856, 0.26511703269375275, 0.9974499172979726, 0.08472322884985414, 0.7442576171043714, 0.307570599929082, 0.4561615671899413, 0.22153700144722094, 0.0990857999171612, 0.21369286391811285)),
           ('r2_13', 1.5, 283.159, 4853.67, (0.9224077181544471, 0.9218110012721277, 0.008971700544790837, 0.33742022908079394, 0.17641315172471073, 0.9740883160043616, 0.13505540674714822, 0.7714783363401461, 0.2633453659435588, 0.47254774196939214, 0.1596892657989509, 0.044872301385473615, 0.19212057012184838)),
           ('r2_14', 1.0, 352.967, 6055.19, (0.9259028756769366, 0.9629605380496665, 0.003962356374049511, 0.3419727248843792, 0.2065559998847337, 0.985057862922747, 0.06241567422531547, 0.7566300714411536, 0.25547467224019205, 0.48797361126000083, 0.23710915741969513, 0.13731148752940286, 0.18420670709834897)),
           ('r2_15', 1.0, 354.757, 6194.49, (0.8702724068036358, 0.9953888573126235, 0.007572725804663523, 0.35209539384036836, 0.25465879908816885, 0.9758816154908511, 0.0722336351418306, 0.7719060935046652, 0.2869020986015642, 0.4652736304382381, 0.22226688351124793, 0.12827056958608876, 0.18416382752395435)))
# 11-08 审查：b29–b31 的判据都和 A 族曲线这 7 行比，提交前要全是 DONE；OF-1 单因素的基点 = A 的 m 1.0 版的 u13（u_m = 1/3）
UROW_CURVE = tuple(_A + s for s in ("ow_m1_e+2.5_8a2bd628", "ow_m1_e+2_c9ca96c8", "ow_m1_e+1.5_52dc478a", "ow_m1_e+1_fea69910", "ow_m1_e+0.5_c17f7b2a", "m1_2a79b613", "ow_m1_e-0.5_03b0a7bc"))
OF1_U_A = (0.9224089721043953, 0.9784708535831516, 0.0, 0.3333333333333333, 0.2791256826572715, 0.9994729461601736, 0.0988668021424858, 0.6404879353047572, 0.3732744534276327, 0.6395583174132404, 0.2160783393538479, 0.0, 0.08621872496401692)
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
        far = f"|far{float(spec['h_far']):g}" if spec.get("h_far") is not None else ""
        return f"intact|{load}|{h}{far}"
    cyc = f"|c{int(spec['cycles'])}" if spec.get("cycles") else ""
    mu = f"|mu{float(spec['mu']):g}" if spec.get("mu") is not None else ""
    tq = f"|T{spec['torsion']['def']}{float(spec['torsion']['T_Nm']):g}" if spec.get("torsion") else ""
    pf = "|pose" + ",".join(f"{k}{float(v):+g}" for k, v in sorted(spec["pose_fixed"].items())) if spec.get("pose_fixed") else ""
    return f"d{float(spec['delta']):g}|{load}|{h}|slip{float(spec['slip_tol']):g}{cyc}{mu}{tq}{pf}"


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
    elif expect == "base_row":                          # b26、b27 的源：db_ws / db_al 的基线行（variant，h 2.0，楼梯，带或不带固定偏移）
        if src.get("kind") != "variant" or str(src.get("stage")) not in ("db_ws", "db_al") or src.get("femur_id") != FEMUR_ID \
                or src.get("h_int") != H_PROD or src.get("cfg") or src.get("bond_only") or src.get("torsion") or src.get("pose_fixed"):
            why.append(f"kind {src.get('kind')!r} stage {src.get('stage')!r} femur_id {src.get('femur_id')!r} h_int {src.get('h_int')!r} "
                       f"cfg {src.get('cfg')!r} bond_only {src.get('bond_only')!r} (want a db_ws / db_al baseline row)")
    elif expect == "alrow":                             # b12 的源：AL 的基线行（stage db_al 的 variant，h 2.0，楼梯）
        if src.get("kind") != "variant" or str(src.get("stage")) != "db_al" or src.get("femur_id") != FEMUR_ID \
                or src.get("h_int") != H_PROD or src.get("cfg") or src.get("bond_only"):
            why.append(f"kind {src.get('kind')!r} stage {src.get('stage')!r} femur_id {src.get('femur_id')!r} h_int {src.get('h_int')!r} "
                       f"cfg {src.get('cfg')!r} bond_only {src.get('bond_only')!r} (want an AL baseline row)")
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
    if batch == "b14":
        return build_b14()
    if batch == "b8":
        return build_b8()
    if batch == "b12":
        return build_b12()
    if batch == "b15":
        return build_b15()
    if batch == "b16":
        return build_b16()
    if batch == "b17":
        return build_b17()
    if batch == "b18":
        return build_b18()
    if batch == "b19":
        return build_b19()
    if batch == "b20":
        return build_b20()
    if batch == "b9p":
        return build_b9p()
    if batch == "b11p":
        return build_b11p()
    if batch == "b22":
        return build_b22()
    if batch == "b23":
        return build_b23()
    if batch == "b24":
        return build_b24()
    if batch == "b25":
        return build_b25()
    if batch == "b26":
        return build_b26()
    if batch == "b27":
        return build_b27()
    if batch == "b28":
        return build_b28()
    if batch == "b28c":
        return build_b28c()
    if batch in UROW_BATCHES:
        return build_urows(batch)
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


def load_tpl(rel: str, U_expect, phys_expect=None, rows: tuple | None = None, allow_errors: bool = False) -> dict:
    """tpl_record batch 的输出（results/<rel>）。核对：工具与格式、全部算完、没有 error 行、code_hash、选号规则（= 阶段 13）、
    变量顺序、u13 逐位等于 U_expect（由种子重建的点）、x13 = phys_expect（给了时；放宽空间的物理值）。不符 → SystemExit。
    allow_errors（AL 局部候选）：error 行允许，但必须都标为不可行。"""
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
    if bool(np.any(d["error"])) and not allow_errors:
        why.append(f"{int(np.sum(d['error']))} error rows")
    if allow_errors and bool(np.any(np.asarray(d["error"], bool) & np.asarray(d["feasible"], bool))):
        why.append("error rows marked feasible")
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
    for name in sorted({q.get("source") for q in doc["picks"]} & set(AL.LOCAL_SOURCES)):     # 局部候选（al3 起）：只在选点用到时读
        d_ = AL.LOCAL_SOURCES[name]
        tps[name] = (d_["tpl"], load_tpl(d_["tpl"], np.load(J.RESULTS / d_["u"]), allow_errors=True))
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


def ws_templating(spec: dict) -> dict:
    """b14：一行的 0-FE 模板化（tpl_record.record_spec：与 jobs.prep 同一选号调用；股骨缓存只读，不建模、不求解）。"""
    import tpl_record as TR
    fe = spec.get("entry_offset")
    if fe is not None and float(fe) not in TR.OFFSETS:  # 固定偏移不在 2 mm 一档（b22）：记录里没有这一档，生产选号单独调一次
        v = TR.offgrid_view(spec)
        r = TR.record_spec({k: x for k, x in spec.items() if k != "entry_offset"})
        return {"feasible": bool(v["fit"]), "reason": str(v["reason"]), "e_star": float(v["e"]), "A0_star": float(v["A0"]),
                "bone_mm3": float(v["bone_total_mm3"]), "e_margin_eff": float(r["e_margin_eff"])}
    r = TR.record_spec(spec)
    if fe is not None:                                  # 固定偏移：结果取记录里该偏移那一档（= jobs.prep 对这个 spec 的模板化）
        v = r["prep_view"]
        return {"feasible": bool(v["fit"]), "reason": str(r["reason"]), "e_star": float(v["e"]), "A0_star": float(v["A0"]),
                "bone_mm3": float(v["bone_total_mm3"]), "e_margin_eff": float(r["e_margin_eff"])}
    return {"feasible": bool(r["feasible"]), "reason": str(r["reason"]), "e_star": float(r["e_star"]), "A0_star": float(r["A0_star"]),
            "bone_mm3": float(r["bone_mm3"]), "e_margin_eff": float(r["e_margin_eff"])}


def build_b14() -> dict:
    """b14（模块说明"批次 b14"）：候选 A 的 m / α 单因素扫描。每行 = A 的物理键只改 design 的一个键，带粘接，参照 REF_H2。
    0-FE 模板化不可行、入口偏移离开 A 的 e*、模板化报错、A 自身与 prep.json 不符 → problems（dry run 退出 1、feed 拒绝）。"""
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_h8 = _by_h8(qspecs)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn, problems, rows, ws_tpl = [], [], [], {}
    if unreadable:
        warn.append(f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}")
    base = CODES[WS_BASE]
    src = load_source(base, "design", qspecs)
    phys = _phys(src, base)
    load_source(REF_H2, "intact", qspecs)
    tag = _tag_of(base)
    base_e = None
    try:
        t0 = ws_templating(src)
        ws_tpl[WS_BASE] = t0
        base_e = t0["e_star"]
        prep, perr = _read_json(J.QROOT / base / "prep.json")
        tp = (prep or {}).get("templating") or {}
        if not isinstance(tp.get("e"), (int, float)) or not isinstance(tp.get("A0"), (int, float)):
            problems.append(f"b14: {base}: no templating record in prep.json ({perr or 'missing e / A0'}); cannot check that tpl_record reproduces production")
        elif abs(float(tp["e"]) - t0["e_star"]) > 1e-9 or abs(float(tp["A0"]) - t0["A0_star"]) > 1e-6:
            problems.append(f"b14: tpl_record does not reproduce {base}: prep.json e {tp['e']} A0 {tp['A0']} vs e* {t0['e_star']} A0* {t0['A0_star']}")
    except Exception as e:                              # noqa: BLE001  模板化核对不了 = 不提交
        problems.append(f"b14: 0-FE templating of the base design {base} failed: {type(e).__name__}: {str(e)[:300]}")
    scan = {"WS m": [("m", float(v), f"m{v:g}") for v in WS_M], "WS alpha": [("alpha", float(v), f"a{v:g}") for v in WS_ALPHA]}
    keys = {L: [] for L in scan}
    for L, items in scan.items():
        for var, val, lab in items:
            spec = _variant(phys, "db_ws", f"{tag}_{lab}", "full", intact_job=REF_H2, design={**phys["design"], var: val})
            ext = {"cond": None, "e_star": None, "e_forced": None}
            try:
                t = ws_templating(spec)
                ws_tpl[lab] = t
                ext["e_star"] = t["e_star"]
                if not t["feasible"]:
                    problems.append(f"WS_{lab}: 0-FE templating is not feasible ({t['reason']}); prep would fail, no FE can run")
                elif base_e is not None and abs(t["e_star"] - base_e) > 1e-9:
                    problems.append(f"WS_{lab}: entry offset e* {t['e_star']:g} != {base_e:g} of {base} (an offset jump would be mixed into the one-factor comparison)")
            except Exception as e:                      # noqa: BLE001
                problems.append(f"WS_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
            r = _row(f"WS_{lab}", L, spec, base, WS_BASE, extra=ext)
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            keys[L].append(r["key"])
    order = interleave(keys["WS m"], keys["WS alpha"])
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows) or len(order) != len(rows):
        raise SystemExit("b14: duplicate row keys")
    rows = [by_key[k] for k in order]
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch b14: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs)
        if r["dedup"] != "new":
            if r["id"] in taken:
                raise SystemExit(f"batch b14: keys {taken[r['id']]} and {r['key']} both resolve to queue job {r['id']}")
            taken[r["id"]] = r["key"]
            warn.append(f"{r['key']}: already in the queue ({r['dedup']} via {r['dedup_via']}: {r['id']})")
    if J.code_hash() != DB_CODE_HASH:
        problems.append(f"code_hash {J.code_hash()} != {DB_CODE_HASH} (one of the 8 hashed files changed; every expected id differs)")
    recorded, rec_err = recorded_ids("b14")
    if rec_err:
        warn.append(rec_err)
    for r in rows:
        problems += [f"{r['key']}: {p_}" for p_ in row_problems(r, lambda j: _spec_of(j, qspecs))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds("b14", rows, qspecs)
    problems += seed_probs
    return {"batch": "b14", "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{H_PROD:g}": REF_H2}, "partners": {}, "n_partner": 0, "pilot16": [], "seeds": seeds, "ws_tpl": ws_tpl,
            "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs)}


def _batch_ctx() -> tuple:
    """队列一次读全：(qspecs, by_h8, by_phys, warn)。"""
    unreadable = []
    qspecs = scan_queue(unreadable)
    by_phys = {}
    for n, sp in qspecs.items():
        if sp is not None:
            by_phys.setdefault(phys_key(sp), []).append(n)
    warn = [f"queue dirs with an unreadable spec.json (treated as having no spec; a hash8 hit on one refuses): {unreadable}"] if unreadable else []
    return qspecs, _by_h8(qspecs), by_phys, warn


def _finish_batch(batch: str, rows: list, order: list, qspecs: dict, by_h8: dict, by_phys: dict, warn: list, problems: list, ref_id: dict, **extra) -> dict:
    """b8 / b12 共用：按 order 排行、查重、批内重复、逐行检查、种子核对，返回 build 的结果。"""
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows) or sorted(order) != sorted(by_key):
        raise SystemExit(f"{batch}: duplicate row keys or an order that does not match the rows")
    rows = [by_key[k] for k in order]
    seen, taken = {}, {}
    for r in rows:
        r["expected_id"] = expected_id(r["spec"])
        r["id"], r["dedup"], r["dedup_hits"], r["dedup_via"] = resolve(r["spec"], by_h8, qspecs, by_phys)
        if r["expected_id"] in seen:
            raise SystemExit(f"batch {batch}: keys {seen[r['expected_id']]} and {r['key']} give the same job id {r['expected_id']}")
        seen[r["expected_id"]] = r["key"]
        r["source_spec"] = _spec_of(r["source_job"], qspecs)
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
        problems += [f"{r['key']}: {p_}" for p_ in row_problems(r, lambda j: _spec_of(j, qspecs), h14_ref=ref_id.get(HEAVY_H))]
        r["ack_failed"] = None
        if r["dedup"] != "new":
            pr, notes, r["ack_failed"] = hit_checks(r["key"], r["id"], _spec_of(r["id"], qspecs), recorded=recorded.get(r["key"]) == r["id"])
            problems += pr
            warn += notes
    seeds, seed_probs = check_seeds(batch, rows, qspecs)
    problems += seed_probs
    return {"batch": batch, "rows": rows, "problems": problems, "warnings": warn, "code_hash": J.code_hash(),
            "ref_id": {f"{h:g}": v for h, v in ref_id.items()}, "partners": {}, "n_partner": 0, "pilot16": [], "seeds": seeds,
            "queue_root": str(J.QROOT), "n_queue_dirs": len(qspecs), **extra}


def build_b15() -> dict:
    """b15（模块说明"批次 b15"）：A 的 m 1.0 版 × α 50 / 55 / 60。对照 WS_m1 必须 DONE；不可行、偏移跳变、模板化报错 → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, ws_tpl = [], [], {}
    base = CODES[WS_BASE]
    src = load_source(base, "design", qspecs)
    phys = _phys(src, base)
    load_source(REF_H2, "intact", qspecs)
    tag = _tag_of(base)
    base_e = None
    try:
        t0 = ws_templating(src)
        ws_tpl[WS_BASE] = t0
        base_e = t0["e_star"]
    except Exception as e:                              # noqa: BLE001  模板化核对不了 = 不提交
        problems.append(f"b15: 0-FE templating of the base design {base} failed: {type(e).__name__}: {str(e)[:300]}")
    lab_m = f"m{WS2_M:g}"
    ctrl = _variant(phys, "db_ws", f"{tag}_{lab_m}", "full", intact_job=REF_H2, design={**phys["design"], "m": WS2_M})
    ctrl_id = expected_id(ctrl)
    ctrl_state = J.state(J.QROOT / ctrl_id) if (J.QROOT / ctrl_id).is_dir() else "absent"
    if ctrl_state != "DONE":
        problems.append(f"b15: the control WS_{lab_m} = {ctrl_id} is {ctrl_state} (must be DONE: every row is compared with it)")
    keys = []
    for val in WS2_ALPHA:
        lab = f"{lab_m}_a{val:g}"
        spec = _variant(phys, "db_ws", f"{tag}_{lab}", "full", intact_job=REF_H2, design={**phys["design"], "m": WS2_M, "alpha": float(val)})
        ext = {"cond": None, "e_star": None, "e_forced": None}
        try:
            t = ws_templating(spec)
            ws_tpl[lab] = t
            ext["e_star"] = t["e_star"]
            if not t["feasible"]:
                problems.append(f"WS_{lab}: 0-FE templating is not feasible ({t['reason']}); prep would fail, no FE can run")
            elif base_e is not None and abs(t["e_star"] - base_e) > 1e-9:
                problems.append(f"WS_{lab}: entry offset e* {t['e_star']:g} != {base_e:g} of {base} (an offset jump would be mixed into the comparison)")
        except Exception as e:                          # noqa: BLE001
            problems.append(f"WS_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
        r = _row(f"WS_{lab}", "WS m alpha", spec, base, WS_BASE, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b15", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_id)


def build_b8() -> dict:
    """b8（模块说明"批次 b8、b12"）：NZ-3 + W-0′。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, ws_tpl = [], [], {}
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    ref_id, ref_key_of = {H_PROD: REF_H2}, {}
    for h in NZ3_H:
        k = f"REF_h{h:g}"
        jid = b1_ids.get(k)
        if not jid:
            raise SystemExit(f"b8: the {B3_REF_BATCH} manifest has no submitted {k} (the h {h:g} reference)")
        st = J.state(J.QROOT / jid)
        if st != "DONE":
            problems.append(f"b8: reference {k} = {jid} is {st} (must be DONE)")
        ref_id[h], ref_key_of[h] = jid, k
    nz_keys, a_keys, l_keys = [], [], []
    for j in NZ3_JOBS:
        p_, tag = _phys(load_source(j, "design", qspecs), j), _tag_of(j)
        for h in NZ3_H:
            spec = _variant(p_, "db_nz", f"{tag}_h{h:g}", "full", intact_job=ref_id[h], h_int=h)
            r = _row(f"NZ3_h{h:g}_{tag}", "NZ-3", spec, j, None, ref_key=ref_key_of[h])
            rows.append(r)
            nz_keys.append(r["key"])
    srcs = {c: load_source(CODES[c], "design", qspecs) for c in W0_L_CODES}
    phys = {c: _phys(s, CODES[c]) for c, s in srcs.items()}
    base_e = {}
    for c in W0_L_CODES:
        try:
            t0 = ws_templating(srcs[c])
            ws_tpl[c] = t0
            base_e[c] = t0["e_star"]
        except Exception as e:                          # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"b8: 0-FE templating of the base design {CODES[c]} failed: {type(e).__name__}: {str(e)[:300]}")
    for c, val in W0_ALPHA:
        lab, tag = f"a{val:g}", _tag_of(CODES[c])
        spec = _variant(phys[c], "db_ws", f"{tag}_{lab}", "full", intact_job=REF_H2, design={**phys[c]["design"], "alpha": float(val)})
        ext = {"cond": None, "e_star": None, "e_forced": None}
        try:
            t = ws_templating(spec)
            ws_tpl[f"{c}_{lab}"] = t
            ext["e_star"] = t["e_star"]
            if not t["feasible"]:
                problems.append(f"W0_{c}_{lab}: 0-FE templating is not feasible ({t['reason']})")
            elif c in base_e and abs(t["e_star"] - base_e[c]) > 1e-9:
                problems.append(f"W0_{c}_{lab}: entry offset e* {t['e_star']:g} != {base_e[c]:g} of {CODES[c]} (an offset jump would be mixed in)")
        except Exception as e:                          # noqa: BLE001
            problems.append(f"W0_{c}_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
        r = _row(f"W0_{c}_{lab}", "W-0 alpha", spec, CODES[c], c, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        a_keys.append(r["key"])
    for c in W0_L_CODES:
        if c not in base_e:
            continue
        for val in W0_L:
            lab, tag = f"L{val:g}", _tag_of(CODES[c])
            spec = _variant(phys[c], "db_ws", f"{tag}_{lab}", "full", intact_job=REF_H2, design={**phys[c]["design"], "L": float(val)},
                            entry_offset=base_e[c])
            ext = {"cond": None, "e_star": base_e[c], "e_forced": base_e[c]}
            try:
                t = ws_templating(spec)
            except Exception as e:                      # noqa: BLE001
                problems.append(f"W0_{c}_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
                continue
            ws_tpl[f"{c}_{lab}"] = t
            if not t["feasible"]:
                warn.append(f"W0_{c}_{lab}: not feasible at the fixed entry offset {base_e[c]:g} ({t['reason']}); row not submitted")
                continue
            r = _row(f"W0_{c}_{lab}", "W-0 L", spec, CODES[c], c, extra=ext)
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            l_keys.append(r["key"])
    order = interleave(nz_keys, interleave(a_keys, l_keys))
    return _finish_batch("b8", rows, order, qspecs, by_h8, by_phys, warn, problems, ref_id, ws_tpl=ws_tpl)


def build_b12() -> dict:
    """b12（模块说明"批次 b8、b12"）：多循环 CY-1，只解摩擦；4 循环在前，最先的 2 行是后处理的冒烟。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    jobs = {"A": CODES["A"], "Am1": CODES["A"], "init29": CODES["init29"], "C": CODES["C"], **CY_EXTRA}

    def phys_of(c):
        j = jobs[c]
        p_ = _phys(load_source(j, "alrow" if j.startswith("db_al_") else "design", qspecs), j)
        if c == "Am1":
            p_["design"] = {**p_["design"], "m": 1.0}
        return p_

    for n, codes in ((4, CY_C4), (10, CY_C10)):
        for c in codes:
            tag = _tag_of(jobs[c]) + ("_m1" if c == "Am1" else "")
            spec = _variant(phys_of(c), "db_cd", f"{tag}_c{n}", "fric", cycles=n)
            r = _row(f"CY_c{n}_{c}", "CY-1", spec, jobs[c], c if c in CODES else None)
            rows.append(r)
            order.append(r["key"])
    return _finish_batch("b12", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2})


def build_b16() -> dict:
    """b16 = VAL-1（模块说明"批次 b16、b17、b18"）：完整股骨 × 实测工况，只改 cfg.load 和 h_far。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    ref_phys = _phys(load_source(REF_H2, "intact", qspecs), REF_H2)
    rows, order = [], []
    for ln, far in VAL_ROWS:
        lab = ln if far is None else f"{ln}_far{far:g}"
        spec = {**copy.deepcopy(ref_phys), "kind": "intact", "cfg": {"load": dict(VAL_LOADS[ln])}, "stage": "db_ref", "tag": f"intact_val_{lab}"}
        if far is not None:
            spec["h_far"] = float(far)
        r = _row(f"VAL_{lab}", "VAL-1", spec, REF_H2)
        rows.append(r)
        order.append(r["key"])
    return _finish_batch("b16", rows, order, qspecs, by_h8, by_phys, warn, [], {H_PROD: REF_H2})


def _cond_design(code: str, qspecs: dict, problems: list) -> tuple:
    """b17、b18 的设计 → (物理键, 标签, 源作业, 设计码)。A 的单因素版的基线是 b14 的同名作业，不是 DONE → 问题。"""
    base = "A" if code in A_WS else code
    j = {**CODES, **CY_EXTRA}[base]
    p_ = _phys(load_source(j, "alrow" if j.startswith("db_al_") else "design", qspecs), j)
    tag = _tag_of(j)
    if code in A_WS:
        p_["design"] = {**p_["design"], **A_WS[code]}
        (k, v), = A_WS[code].items()
        tag = f"{tag}_{'m' if k == 'm' else 'a'}{v:g}"
        ctrl = expected_id(_variant(p_, "db_ws", tag, "full", intact_job=REF_H2))
        st = J.state(J.QROOT / ctrl) if (J.QROOT / ctrl).is_dir() else "absent"
        if st != "DONE":
            problems.append(f"{code}: its baseline {ctrl} is {st} (must be DONE: every row of this design is compared with it)")
    return p_, tag, j, base if base in CODES else None


def build_b17() -> dict:
    """b17 = TQ-0（模块说明"批次 b16、b17、b18"）：只解摩擦，只改头力。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    for code in TQ0_CODES:
        p_, tag, j, c = _cond_design(code, qspecs, problems)
        for ln, L in TQ0_LOADS.items():
            spec = _variant(p_, "db_cd", f"{tag}_{ln}", "fric", cfg={"load": dict(L)})
            r = _row(f"TQ0_{ln}_{code}", "TQ-0", spec, j, c)
            rows.append(r)
            order.append(r["key"])
    return _finish_batch("b17", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2})


def build_b18() -> dict:
    """b18 = MU-1（模块说明"批次 b16、b17、b18"）：只解摩擦，只改 μ。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    for code in MU1_CODES:
        p_, tag, j, c = _cond_design(code, qspecs, problems)
        for mu in (MU1_MU, MU1_MU_LOW) if code in MU1_LOW else (MU1_MU,):
            spec = _variant(p_, "db_cd", f"{tag}_mu{mu:g}", "fric", mu=mu)
            r = _row(f"MU1_mu{mu:g}_{code}", "MU-1", spec, j, c)
            rows.append(r)
            order.append(r["key"])
    return _finish_batch("b18", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2})


def build_b19() -> dict:
    """b19 = WL-1（模块说明"批次 b19"）：A 的 m 1.0 版 × L（× α），入口偏移固定为 0。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl, ctrl_ids = [], [], [], {}, {}
    base = CODES[WS_BASE]
    phys = _phys(load_source(base, "design", qspecs), base)
    load_source(REF_H2, "intact", qspecs)
    tag, lab_m = _tag_of(base), f"m{WS2_M:g}"
    for alpha, L in WL1_ROWS:
        a_lab = "" if alpha is None else f"_a{alpha:g}"
        d_ctrl = {**phys["design"], "m": WS2_M, **({} if alpha is None else {"alpha": float(alpha)})}
        ctrl = _variant(phys, "db_ws", f"{tag}_{lab_m}{a_lab}", "full", intact_job=REF_H2, design=d_ctrl)
        cid = ctrl_ids[a_lab] = expected_id(ctrl)
        st = J.state(J.QROOT / cid) if (J.QROOT / cid).is_dir() else "absent"
        if st != "DONE":
            problems.append(f"b19: the control {cid} is {st} (must be DONE: the rows with this alpha are compared with it)")
        lab = f"{lab_m}{a_lab}_L{L:g}"
        spec = _variant(phys, "db_ws", f"{tag}_wl_{lab}", "full", intact_job=REF_H2, design={**d_ctrl, "L": float(L)}, entry_offset=WL1_E)
        ext = {"cond": None, "e_star": WL1_E, "e_forced": WL1_E}
        try:
            t0, t = ws_templating(ctrl), ws_templating(spec)
            ws_tpl[f"ctrl{a_lab}"], ws_tpl[lab] = t0, t
            if not t["feasible"]:
                problems.append(f"WL_{lab}: 0-FE templating is not feasible at entry offset {WL1_E:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != WL1_E:
                problems.append(f"WL_{lab}: entry offset {t['e_star']:g} != {WL1_E:g}")
            elif t["A0_star"] < WL1_A0_MIN * t0["A0_star"]:
                problems.append(f"WL_{lab}: A0 {t['A0_star']:.1f} is more than 5 % below the control's {t0['A0_star']:.1f} (a size jump would be mixed into the comparison)")
        except Exception as e:                          # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"WL_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
        r = _row(f"WL_{lab}", "WL-1", spec, base, WS_BASE, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b19", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_ids)


def _cd2_design(code: str, qspecs: dict, problems: list) -> tuple:
    """b9p 的设计 → (物理键, 标签, 源作业, 设计码)。AL44 = 台架候选 WL_m1_L44（b19，必须 DONE），其余见 _cond_design 与 CD2_EXTRA。"""
    if code == "AL44":
        base = CODES[WS_BASE]
        p_ = _phys(load_source(base, "design", qspecs), base)
        p_["design"] = {**p_["design"], "m": WS2_M, "L": 44.0}
        p_["entry_offset"] = WL1_E
        tag = f"{_tag_of(base)}_wl_m{WS2_M:g}_L44"
        ctrl = expected_id(_variant(p_, "db_ws", tag, "full", intact_job=REF_H2))
        st = J.state(J.QROOT / ctrl) if (J.QROOT / ctrl).is_dir() else "absent"
        if st != "DONE":
            problems.append(f"{code}: its baseline {ctrl} is {st} (must be DONE)")
        return p_, tag, base, WS_BASE
    if code in CD2_EXTRA:
        j = CD2_EXTRA[code]
        kind = "alrow" if j.startswith("db_al_") else "b2row" if j.startswith("db_cr_") else "design"
        return _phys(load_source(j, kind, qspecs), j), _tag_of(j), j, None
    return _cond_design(code, qspecs, problems)


def build_b9p() -> dict:
    """b9p = CD-2″（模块说明"批次 b9p、b11p"）：只解摩擦，只改 δ、载荷或两者。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    L = {"load": dict(STS_LOADS[CD2_LOAD])}

    def add(key, code, lab, **ch):
        p_, tag, j, c = _cd2_design(code, qspecs, problems)
        spec = _variant(p_, "db_cd", f"{tag}_{lab}", "fric", **ch)
        r = _row(key, "CD-2", spec, j, c)
        rows.append(r)
        order.append(r["key"])

    for code in CD2_SINGLE:
        add(f"CD2_d{CD2_DELTA:g}_{code}", code, f"d{CD2_DELTA:g}", delta=CD2_DELTA)
        add(f"CD2_{CD2_LOAD}_{code}", code, CD2_LOAD, cfg=copy.deepcopy(L))
    for code in CD2_JOINT:
        add(f"CD2_both_{code}", code, f"d{CD2_DELTA:g}_{CD2_LOAD}", delta=CD2_DELTA, cfg=copy.deepcopy(L))
    return _finish_batch("b9p", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2})


def build_b11p() -> dict:
    """b11p = OW-2（模块说明"批次 b9p、b11p"）：m 1.0 版 × 入口偏移，带粘接。不可行、偏移不符、模板化报错 → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl = [], [], [], {}
    load_source(REF_H2, "intact", qspecs)
    lab_m = f"m{WS2_M:g}"
    jobs = {**CODES, **CY_EXTRA}
    base_ctrl = expected_id(_variant(_phys(load_source(CODES[WS_BASE], "design", qspecs), CODES[WS_BASE]), "db_ws", f"{_tag_of(CODES[WS_BASE])}_{lab_m}", "full", intact_job=REF_H2,
                                     design={**_phys(load_source(CODES[WS_BASE], "design", qspecs), CODES[WS_BASE])["design"], "m": WS2_M}))
    st = J.state(J.QROOT / base_ctrl) if (J.QROOT / base_ctrl).is_dir() else "absent"
    if st != "DONE":
        problems.append(f"b11p: the control WS_{lab_m} = {base_ctrl} is {st} (must be DONE)")
    for code, e in OW2_ROWS:
        j = jobs[code]
        p_ = _phys(load_source(j, "design", qspecs), j)
        lab = f"{code}_{lab_m}_e{e:+g}"
        spec = _variant(p_, "db_ws", f"{_tag_of(j)}_ow_{lab_m}_e{e:+g}", "full", intact_job=REF_H2, design={**p_["design"], "m": WS2_M}, entry_offset=float(e))
        ext = {"cond": None, "e_star": float(e), "e_forced": float(e)}
        try:
            t = ws_templating(spec)
            ws_tpl[lab] = t
            if not t["feasible"]:
                problems.append(f"OW2_{lab}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != float(e):
                problems.append(f"OW2_{lab}: entry offset {t['e_star']:g} != {e:g}")
        except Exception as ex:                         # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"OW2_{lab}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        r = _row(f"OW2_{lab}", "OW-2", spec, j, code if code in CODES else None, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b11p", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=base_ctrl)


def build_b22() -> dict:
    """b22 = OW-3（模块说明"批次 b22"）：m 1.0 版 × 更细的入口偏移，带粘接。对照没 DONE、不可行、偏移不符、模板化报错 → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl, ctrl_ids = [], [], [], {}, {}
    load_source(REF_H2, "intact", qspecs)
    lab_m = f"m{WS2_M:g}"
    jobs = {**CODES, **CY_EXTRA}

    def control(lab, spec):
        ctrl_ids[lab] = expected_id(spec)
        st = J.state(J.QROOT / ctrl_ids[lab]) if (J.QROOT / ctrl_ids[lab]).is_dir() else "absent"
        if st != "DONE":
            problems.append(f"b22: the control {lab} = {ctrl_ids[lab]} is {st} (must be DONE)")

    p_a = _phys(load_source(CODES[WS_BASE], "design", qspecs), CODES[WS_BASE])
    control(f"A_{lab_m}", _variant(p_a, "db_ws", f"{_tag_of(CODES[WS_BASE])}_{lab_m}", "full", intact_job=REF_H2, design={**p_a["design"], "m": WS2_M}))
    p_95 = _phys(load_source(jobs["a95"], "design", qspecs), jobs["a95"])
    control(f"a95_{lab_m}_e+0", _variant(p_95, "db_ws", f"{_tag_of(jobs['a95'])}_ow_{lab_m}_e+0", "full", intact_job=REF_H2, design={**p_95["design"], "m": WS2_M}, entry_offset=0.0))
    for code, e in OW3_ROWS:
        lab = f"{code}_{lab_m}_e{e:+g}"
        j = jobs[code]
        p_ = _phys(load_source(j, "design", qspecs), j)
        spec = _variant(p_, "db_ws", f"{_tag_of(j)}_ow_{lab_m}_e{e:+g}", "full", intact_job=REF_H2, design={**p_["design"], "m": WS2_M}, entry_offset=float(e))
        ext = {"cond": None, "e_star": float(e), "e_forced": float(e)}
        try:
            t = ws_templating(spec)
            ws_tpl[lab] = t
            if not t["feasible"]:
                problems.append(f"OW3_{lab}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != float(e):
                problems.append(f"OW3_{lab}: entry offset {t['e_star']:g} != {e:g}")
        except Exception as ex:                         # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"OW3_{lab}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        r = _row(f"OW3_{lab}", "OW-3", spec, j, code if code in CODES else None, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b22", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_ids)


def build_b23() -> dict:
    """b23 = OW-4（模块说明"批次 b23"）：A 的 m 1.0 版 × 固定入口偏移，稳健性。基线没 DONE、不可行、偏移不符、模板化报错、h 1.4 参照没 DONE → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order, ws_tpl, ctrl_ids = [], [], [], {}, {}
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    ref14 = b1_ids.get(f"REF_h{HEAVY_H:g}")
    if not ref14:
        raise SystemExit(f"b23: the {B3_REF_BATCH} manifest has no submitted REF_h{HEAVY_H:g} (the h {HEAVY_H:g} reference)")
    st14 = J.state(J.QROOT / ref14)
    if st14 != "DONE":
        problems.append(f"b23: reference REF_h{HEAVY_H:g} = {ref14} is {st14} (must be DONE)")
    load_source(REF_H2, "intact", qspecs)
    base = CODES[WS_BASE]
    lab_m = f"m{WS2_M:g}"
    src = load_source(base, "design", qspecs)

    def at(e):
        p_ = _phys(src, base)
        p_["design"] = {**p_["design"], "m": WS2_M}
        p_["entry_offset"] = float(e)
        tag = f"{_tag_of(base)}_ow_{lab_m}_e{e:+g}"
        lab = f"e{e:+g}"
        if lab not in ctrl_ids:
            ctrl = _variant(p_, "db_ws", tag, "full", intact_job=REF_H2)
            ctrl_ids[lab] = expected_id(ctrl)
            st = J.state(J.QROOT / ctrl_ids[lab]) if (J.QROOT / ctrl_ids[lab]).is_dir() else "absent"
            if st != "DONE":
                problems.append(f"b23: the baseline {lab} = {ctrl_ids[lab]} is {st} (must be DONE)")
            try:
                t = ws_templating(ctrl)
                ws_tpl[lab] = t
                if not t["feasible"]:
                    problems.append(f"OW4 {lab}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
                elif t["e_star"] != float(e):
                    problems.append(f"OW4 {lab}: entry offset {t['e_star']:g} != {e:g}")
            except Exception as ex:                     # noqa: BLE001  模板化核对不了 = 不提交
                problems.append(f"OW4 {lab}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        return p_, tag, lab

    def add(key, layer, spec, ref_key=None):
        r = _row(key, layer, spec, base, WS_BASE, ref_key=ref_key, extra={"e_forced": spec["entry_offset"]})
        rows.append(r)
        order.append(r["key"])

    F3839, S40 = {"load": dict(STS_LOADS[CD2_LOAD])}, {"load": dict(TQ0_LOADS["S40"])}
    for e in OW4_E:
        p_, tag, lab = at(e)
        add(f"OW4_d{CD2_DELTA:g}_{lab}", "OW-4", _variant(p_, "db_cd", f"{tag}_d{CD2_DELTA:g}", "fric", delta=CD2_DELTA))
        add(f"OW4_{CD2_LOAD}_{lab}", "OW-4", _variant(p_, "db_cd", f"{tag}_{CD2_LOAD}", "fric", cfg=copy.deepcopy(F3839)))
        add(f"OW4_both_{lab}", "OW-4", _variant(p_, "db_cd", f"{tag}_d{CD2_DELTA:g}_{CD2_LOAD}", "fric", delta=CD2_DELTA, cfg=copy.deepcopy(F3839)))
        add(f"OW4_S40_{lab}", "OW-4", _variant(p_, "db_cd", f"{tag}_S40", "fric", cfg=copy.deepcopy(S40)))
    p_, tag, lab = at(OW4_CY_E)
    add(f"OW4_c{OW4_CY_N}_{lab}", "OW-4 cy", _variant(p_, "db_cd", f"{tag}_c{OW4_CY_N}", "fric", cycles=OW4_CY_N))
    p_, tag, lab = at(OW4_H14_E)
    add(f"OW4_h{HEAVY_H:g}_{lab}", "OW-4 h1.4", _variant(p_, "db_fd", f"{tag}_h{HEAVY_H:g}", "full", intact_job=ref14, h_int=HEAVY_H, slip_tol=H14_SLIP_TOL), ref_key=f"REF_h{HEAVY_H:g}")
    return _finish_batch("b23", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2, HEAVY_H: ref14}, ws_tpl=ws_tpl, ws_control=ctrl_ids)


def build_b24() -> dict:
    """b24 = TQ-1、PF-1 的冒烟（模块说明"批次 b24"）。基线没 DONE、不可行、偏移不符、模板化报错 → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order, ws_tpl, ctrl_ids = [], [], [], {}, {}
    load_source(REF_H2, "intact", qspecs)
    base = CODES[WS_BASE]
    lab_m = f"m{WS2_M:g}"
    src = load_source(base, "design", qspecs)
    import torsion_load as TL
    import tpl_record as TR
    rule_ = TR.spec_rule(src)
    fm = TR.base_femur(rule_.femur_id, rule_.neck_axis)

    def at(e):
        p_ = _phys(src, base)
        p_["design"] = {**p_["design"], "m": WS2_M}
        if e is None:
            tag, lab = f"{_tag_of(base)}_{lab_m}", "e0"
        else:
            p_["entry_offset"] = float(e)
            tag, lab = f"{_tag_of(base)}_ow_{lab_m}_e{e:+g}", f"e{e:+g}"
        if lab not in ctrl_ids:
            ctrl = _variant(p_, "db_ws", tag, "full", intact_job=REF_H2)
            ctrl_ids[lab] = expected_id(ctrl)
            st = J.state(J.QROOT / ctrl_ids[lab]) if (J.QROOT / ctrl_ids[lab]).is_dir() else "absent"
            if st != "DONE":
                problems.append(f"b24: the baseline {lab} = {ctrl_ids[lab]} is {st} (must be DONE)")
            try:
                t = ws_templating(ctrl)
                ws_tpl[lab] = t
                if not t["feasible"]:
                    problems.append(f"b24 {lab}: 0-FE templating is not feasible ({t['reason']}); prep would fail, no FE can run")
                elif t["e_star"] != (0.0 if e is None else float(e)):
                    problems.append(f"b24 {lab}: entry offset {t['e_star']:g} is not the written one")
            except Exception as ex:                     # noqa: BLE001  模板化核对不了 = 不提交
                problems.append(f"b24 {lab}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        return p_, tag, lab

    def add(key, layer, spec):
        r = _row(key, layer, spec, base, WS_BASE)
        rows.append(r)
        order.append(r["key"])

    F3839 = {"load": dict(STS_LOADS[CD2_LOAD])}
    for e in TQ1S_E:
        p_, tag, lab = at(e)
        axial = {"load": TL.axial_load(fm.pose(p_["design"]["alpha"], 0.0)[1], TQ1S_PRELOAD)}   # 预载沿柄轴；柄轴不随 e 变
        add(f"TQ1S_A_{lab}", "TQ-1 smoke", _variant(p_, "db_cd", f"{tag}_TA{TQ1S_T:g}", "fric", cfg=axial, torsion={"def": "A", "T_Nm": TQ1S_T}))
        add(f"TQ1S_B_{lab}", "TQ-1 smoke", _variant(p_, "db_cd", f"{tag}_TB{TQ1S_T:g}", "fric", cfg=copy.deepcopy(F3839), torsion={"def": "B", "T_Nm": TQ1S_T}))
    for e, de in PF1S_ROWS:
        p_, tag, lab = at(e)
        add(f"PF1S_{lab}_de{de:+g}", "PF-1 smoke", _variant(p_, "db_cd", f"{tag}_pf_de{de:+g}", "fric", pose_fixed={"de": float(de)}))
    return _finish_batch("b24", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_ids)


def build_b25() -> dict:
    """b25 = OPT-1（模块说明"批次 b25"）：8 个新设计，入口偏移固定，带粘接。对照没 DONE、m < 1、不可行、偏移或号或去骨量和 0 FE 记录不符、模板化报错 → problems。"""
    np = _np()
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl = [], [], [], {}
    load_source(REF_H2, "intact", qspecs)
    base = CODES[WS_BASE]
    p_a = _phys(load_source(base, "design", qspecs), base)
    ctrl_id = expected_id(_variant(p_a, "db_ws", f"{_tag_of(base)}_m{WS2_M:g}", "full", intact_job=REF_H2, design={**p_a["design"], "m": WS2_M}))
    st = J.state(J.QROOT / ctrl_id) if (J.QROOT / ctrl_id).is_dir() else "absent"
    if st != "DONE":
        problems.append(f"b25: the control WS_m{WS2_M:g} = {ctrl_id} is {st} (must be DONE)")
    ph = b2_phase()
    for n, (e, A0, bone, u) in enumerate(OPT1_ROWS, 1):
        tag = f"opt1_{n:02d}_e{e:+g}"
        key = f"OPT1_{n:02d}"
        spec = _variant(_phys(ph.spec_of(np.asarray(u, float), tag, bonded=True), f"db_al {tag}"), "db_al", tag, "full", intact_job=REF_H2, entry_offset=float(e))
        if float(spec["design"]["m"]) < WS2_M - 1e-9:
            problems.append(f"{key}: m {spec['design']['m']:g} < {WS2_M:g}")
        try:
            t = ws_templating(spec)
            ws_tpl[tag] = t
            if not t["feasible"]:
                problems.append(f"{key}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != float(e):
                problems.append(f"{key}: entry offset {t['e_star']:g} != {e:g}")
            elif abs(t["A0_star"] - A0) > 0.01 or abs(t["bone_mm3"] - bone) > 0.5:
                problems.append(f"{key}: size {t['A0_star']:.3f} or bone {t['bone_mm3']:.2f} differs from the 0-FE record {A0:.3f}, {bone:.2f}")
        except Exception as ex:                         # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"{key}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        r = _row(key, "OPT-1", spec, ctrl_id, None, extra={"pool_idx": None, "layer_pos": n, "cond": None, "e_star": float(e), "e_forced": float(e), "al_group": "opt1", "al_problem": "F_f1_bone"})
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(key)
    return _finish_batch("b25", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_id)


def _sts1_tag(job: str) -> str:
    """db_ws_p13_a105_91e458e3_m1_2a79b613 → p13_a105_91e458e3_m1：去掉 stage 和 hash8。"""
    return job.split("_", 2)[2].rsplit("_", 1)[0]


def build_b26() -> dict:
    """b26 = STS-1（模块说明"批次 b26、b27"）：基线行只把头力换成坐起 1714 N，只解摩擦。基线行没 DONE → SystemExit（load_source）。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    for lab, j in STS1_ROWS:
        p_ = _phys(load_source(j, "base_row", qspecs), j)
        spec = _variant(p_, "db_cd", f"{_sts1_tag(j)}_{STS1_LOAD}", "fric", cfg={"load": dict(STS_LOADS[STS1_LOAD])})
        r = _row(f"STS1_{lab}", "STS-1", spec, j, None, extra={"e_forced": spec.get("entry_offset")})
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        order.append(r["key"])
    return _finish_batch("b26", rows, order, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2})


def build_b27() -> dict:
    """b27 = STS-1 mesh（模块说明"批次 b26、b27"）：h 1.94、2.06 × 1714 N 的完整股骨参照 2 行，加网格行 4 行。楼梯参照没 DONE → problems；基线行没 DONE → SystemExit。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, order = [], [], []
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    ln = STS1_LOAD[1:]
    ref_id, ref_by_key, q2 = {H_PROD: REF_H2}, {}, dict(qspecs)
    for h in STS1M_H:
        j0 = b1_ids.get(f"REF_h{h:g}")
        if not j0:
            raise SystemExit(f"b27: the {B3_REF_BATCH} manifest has no submitted REF_h{h:g} (the h {h:g} stair reference)")
        st = J.state(J.QROOT / j0)
        if st != "DONE":
            problems.append(f"b27: reference REF_h{h:g} = {j0} is {st} (must be DONE)")
        src = _spec_of(j0, qspecs)
        if src is None or src.get("kind") != "intact" or src.get("h_int") != h or src.get("cfg"):
            raise SystemExit(f"b27: {j0} is not the h {h:g} stair intact reference")
        spec = {**_phys(src, j0), "kind": "intact", "cfg": {"load": dict(STS_LOADS[STS1_LOAD])}, "stage": "db_ref", "tag": f"intact_h{h:g}_sts{ln}"}
        k = f"REF_h{h:g}_sts{ln}"
        rows.append(_row(k, "REF", spec, j0))
        order.append(k)
        ref_id[h] = ref_by_key[k] = resolve(spec, by_h8, qspecs, by_phys)[0]
        q2.setdefault(ref_id[h], spec)                  # 参照在本批里：row_problems 按本批的 spec 核对
    for lab, j in STS1M_ROWS:
        p_ = _phys(load_source(j, "base_row", qspecs), j)
        for h in STS1M_H:
            spec = _variant(p_, "db_nz", f"{_sts1_tag(j)}_h{h:g}_{STS1_LOAD}", "full", intact_job=ref_id[h], h_int=h, cfg={"load": dict(STS_LOADS[STS1_LOAD])})
            r = _row(f"STS1M_h{h:g}_{lab}", "STS-1 mesh", spec, j, None, ref_key=f"REF_h{h:g}_sts{ln}", extra={"e_forced": spec.get("entry_offset")})
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            order.append(r["key"])
    return _finish_batch("b27", rows, order, q2, by_h8, by_phys, warn, problems, ref_id, ref_by_key=ref_by_key)


def build_b28() -> dict:
    """b28 = FAM-1（模块说明"批次 b28"）：环带 15 个新设计，入口偏移固定，只解摩擦；加 2 行阴性对照（h 1.94，带粘接）。
    A 的 m 1.0 版没 DONE、m < 1、不可行、偏移或号或去骨量和 0 FE 记录不符、模板化报错、h 1.94 参照没 DONE → problems；对照基线没 DONE → SystemExit（load_source）。"""
    np = _np()
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl = [], [], [], {}
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    ref = b1_ids.get(f"REF_h{FAM1_CTRL_H:g}")
    if not ref:
        raise SystemExit(f"b28: the {B3_REF_BATCH} manifest has no submitted REF_h{FAM1_CTRL_H:g} (the h {FAM1_CTRL_H:g} stair reference)")
    st_ref = J.state(J.QROOT / ref)
    if st_ref != "DONE":
        problems.append(f"b28: reference REF_h{FAM1_CTRL_H:g} = {ref} is {st_ref} (must be DONE)")
    base = CODES[WS_BASE]
    p_a = _phys(load_source(base, "design", qspecs), base)
    ctrl_id = expected_id(_variant(p_a, "db_ws", f"{_tag_of(base)}_m{WS2_M:g}", "full", intact_job=REF_H2, design={**p_a["design"], "m": WS2_M}))
    st = J.state(J.QROOT / ctrl_id) if (J.QROOT / ctrl_id).is_dir() else "absent"
    if st != "DONE":
        problems.append(f"b28: the A family row WS_m{WS2_M:g} = {ctrl_id} is {st} (must be DONE)")
    ref_phys = {k: v for k, v in {**p_a, "design": {**p_a["design"], "m": WS2_M}}.items() if k in PHYS_KEYS}
    allowed = {"design", "h_cut", "entry_offset"}             # 审查 R8：环带行相对 A 的 m 1.0 版只能改设计、截骨和入口偏移，条件全同
    ph = b2_phase()
    for n, (lab, e, A0, bone, u) in enumerate(FAM1_ROWS, 1):
        tag = f"fam1_{lab}_e{e:+g}"
        key = f"FAM1_{lab}"
        spec = _variant(_phys(ph.spec_of(np.asarray(u, float), tag, bonded=True), f"db_al {tag}"), "db_al", tag, "fric", entry_offset=float(e))
        if float(spec["design"]["m"]) < WS2_M - 1e-9:
            problems.append(f"{key}: m {spec['design']['m']:g} < {WS2_M:g}")
        sp = {k: v for k, v in spec.items() if k in PHYS_KEYS}
        extra_keys = sorted(k for k in set(ref_phys) | set(sp) if ref_phys.get(k) != sp.get(k) and k not in allowed)
        if extra_keys:
            problems.append(f"{key}: physics differs from the A row outside {sorted(allowed)}: {extra_keys}")
        try:
            t = ws_templating(spec)
            ws_tpl[tag] = t
            if not t["feasible"]:
                problems.append(f"{key}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != float(e):
                problems.append(f"{key}: entry offset {t['e_star']:g} != {e:g}")
            elif abs(t["A0_star"] - A0) > 0.01 or abs(t["bone_mm3"] - bone) > 0.5:
                problems.append(f"{key}: size {t['A0_star']:.3f} or bone {t['bone_mm3']:.2f} differs from the 0-FE record {A0:.3f}, {bone:.2f}")
        except Exception as ex:                         # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"{key}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        r = _row(key, "FAM-1", spec, ctrl_id, None, extra={"pool_idx": None, "layer_pos": n, "cond": None, "e_star": float(e), "e_forced": float(e), "al_group": "fam1", "al_problem": "F_f1_bone_ring"})
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(key)
    for lab, j in FAM1_CTRL:
        p_ = _phys(load_source(j, "base_row", qspecs), j)
        spec = _variant(p_, "db_nz", f"{_sts1_tag(j)}_h{FAM1_CTRL_H:g}", "full", intact_job=ref, h_int=FAM1_CTRL_H)
        r = _row(f"FAM1C_{lab}", "FAM-1 ctrl", spec, j, None, ref_key=f"REF_h{FAM1_CTRL_H:g}", extra={"e_forced": spec.get("entry_offset")})
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b28", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2, FAM1_CTRL_H: ref}, ws_tpl=ws_tpl, ws_control=ctrl_id)


UROW_BATCHES = {"b29": ("RS-1", "db_al", "rs1", "RS1_ROWS", "rs1", "F_f1_bone_ring_rand"),         # 批次 → (层, stage, tag 前缀, 行常量名, al_group, al_problem)
                "b30": ("OF-1", "db_ws", "of1", "OF1_ROWS", "of1", "one_factor_shape"),
                "b31": ("R2", "db_al", "r2", "R2_ROWS", "r2", "F_f1_bone_near_3b")}


def _urow_tag(prefix: str, lab: str, e: float) -> str:
    """rs1_01_e+0、of1_n_a-0.15_e+0、r2_01_e+1.5：标签去掉与前缀重复的开头（rs01 → 01，r2_01 → 01）。"""
    for p in (prefix + "_", prefix[:2]):
        if lab.startswith(p) and p:
            lab = lab[len(p):]
            break
    return f"{prefix}_{lab}_e{e:+g}"


def _of1_single_factor(rows_def, ph, ref_phys: dict) -> list:
    """OF-1（11-08 审查 30-6）：OF1_U_A 给出 A 的 m 1.0 版的设计和截骨；"量±步"行比 OF1_U_A 恰好改这一个坐标、改这一步，入口偏移 0；
    "3b_back_量"行比 b28 的 3b（FAM1_ROWS）恰好改这一个坐标、改成 OF1_U_A 的值，入口偏移同 3b。不符 → problems。"""
    np = _np()
    names, out = list(ph.vars), []
    uA = np.asarray(OF1_U_A, float)
    pa = _phys(ph.spec_of(uA, "of1_base", bonded=True), "of1_base")
    da, dr = pa["design"], ref_phys["design"]
    if set(da) != set(dr) or any(abs(float(da[k]) - float(dr[k])) > 1e-6 for k in dr) or pa.get("h_cut") != ref_phys.get("h_cut"):
        out.append(f"OF-1: OF1_U_A does not give the A row at m {WS2_M:g}: {da}, h_cut {pa.get('h_cut')} vs {dr}, h_cut {ref_phys.get('h_cut')}")
    f3 = {x[0]: x for x in FAM1_ROWS}["3b"]
    u3b = np.asarray(f3[4], float)
    for lab, e, _, _, u in rows_def:
        u = np.asarray(u, float)
        if lab.startswith("3b_back_"):
            name, base, step = lab[len("3b_back_"):], u3b, None
        else:
            i = max(lab.rfind("+"), lab.rfind("-"))
            name, base, step = lab[:i], uA, float(lab[i:]) if i > 0 else None
            if step is None:
                out.append(f"OF-1 {lab}: label has no step")
                continue
        if name not in names:
            out.append(f"OF-1 {lab}: unknown factor {name!r}")
            continue
        k = names.index(name)
        moved = [j for j in range(len(names)) if abs(u[j] - base[j]) > 1e-12]
        if moved != [k]:
            out.append(f"OF-1 {lab}: coordinates changed {[names[j] for j in moved]}, want only {name}")
        elif step is None and (abs(u[k] - uA[k]) > 1e-12 or float(e) != float(f3[1])):
            out.append(f"OF-1 {lab}: {name} {u[k]:.6f} != A's {uA[k]:.6f} or entry offset {e:g} != 3b's {f3[1]:g}")
        elif step is not None and abs((u[k] - base[k]) - step) > 1e-9:
            out.append(f"OF-1 {lab}: {name} moved {u[k] - base[k]:+.6f}, label says {step:+g}")
        elif step is not None and float(e) != 0.0:
            out.append(f"OF-1 {lab}: entry offset {e:g}, one-factor rows of A at m {WS2_M:g} must be at 0")
    return out


def build_urows(batch: str) -> dict:
    """b29、b30、b31（模块说明"批次 b29、b30、b31"）：写死 u13 和入口偏移的新设计，只解摩擦。
    A 的 m 1.0 版或 A 族曲线 7 行（UROW_CURVE）没 DONE、m < 1、物理键在设计 / 截骨 / 入口偏移之外不同、不可行、偏移或号或去骨量和 0 FE 记录不符、
    模板化报错、b30 不是单因素（_of1_single_factor） → problems。"""
    np = _np()
    layer, stage, prefix, const, group, problem = UROW_BATCHES[batch]
    rows_def = globals()[const]
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl = [], [], [], {}
    base = CODES[WS_BASE]
    p_a = _phys(load_source(base, "design", qspecs), base)
    ctrl_id = expected_id(_variant(p_a, "db_ws", f"{_tag_of(base)}_m{WS2_M:g}", "full", intact_job=REF_H2, design={**p_a["design"], "m": WS2_M}))
    st = J.state(J.QROOT / ctrl_id) if (J.QROOT / ctrl_id).is_dir() else "absent"
    if st != "DONE":
        problems.append(f"{batch}: the A family row WS_m{WS2_M:g} = {ctrl_id} is {st} (must be DONE)")
    for j in UROW_CURVE:
        s = J.state(J.QROOT / j) if (J.QROOT / j).is_dir() else "absent"
        if s != "DONE":
            problems.append(f"{batch}: the A family curve row {j} is {s} (must be DONE, the gates compare against the curve)")
    ref_phys = {k: v for k, v in {**p_a, "design": {**p_a["design"], "m": WS2_M}}.items() if k in PHYS_KEYS}
    allowed = {"design", "h_cut", "entry_offset"}
    ph = b2_phase()
    if batch == "b30":
        problems += _of1_single_factor(rows_def, ph, ref_phys)
    for n, (lab, e, A0, bone, u) in enumerate(rows_def, 1):
        tag = _urow_tag(prefix, lab, e)
        key = f"{prefix.upper()}_{tag[len(prefix) + 1:tag.rindex('_e')]}"
        spec = _variant(_phys(ph.spec_of(np.asarray(u, float), tag, bonded=True), f"{stage} {tag}"), stage, tag, "fric", entry_offset=float(e))
        if float(spec["design"]["m"]) < WS2_M - 1e-9:
            problems.append(f"{key}: m {spec['design']['m']:g} < {WS2_M:g}")
        sp = {k: v for k, v in spec.items() if k in PHYS_KEYS}
        extra_keys = sorted(k for k in set(ref_phys) | set(sp) if ref_phys.get(k) != sp.get(k) and k not in allowed)
        if extra_keys:
            problems.append(f"{key}: physics differs from the A row outside {sorted(allowed)}: {extra_keys}")
        try:
            t = ws_templating(spec)
            ws_tpl[tag] = t
            if not t["feasible"]:
                problems.append(f"{key}: 0-FE templating is not feasible at entry offset {e:g} ({t['reason']}); prep would fail, no FE can run")
            elif t["e_star"] != float(e):
                problems.append(f"{key}: entry offset {t['e_star']:g} != {e:g}")
            elif abs(t["A0_star"] - A0) > 0.01 or abs(t["bone_mm3"] - bone) > 0.5:
                problems.append(f"{key}: size {t['A0_star']:.3f} or bone {t['bone_mm3']:.2f} differs from the 0-FE record {A0:.3f}, {bone:.2f}")
        except Exception as ex:                         # noqa: BLE001  模板化核对不了 = 不提交
            problems.append(f"{key}: 0-FE templating failed: {type(ex).__name__}: {str(ex)[:300]}")
        r = _row(key, layer, spec, ctrl_id, None, extra={"pool_idx": None, "layer_pos": n, "cond": None, "e_star": float(e), "e_forced": float(e), "al_group": group, "al_problem": problem})
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(key)
    return _finish_batch(batch, rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_id)


def build_b28c() -> dict:
    """b28c = b28 初判赢家的条件行（模块说明"批次 b28c"）：每个赢家 h 1.94 复算、h 1.4、坐起 1714 N。
    名单为空、超过 5 个、有重复或未知标签、参照不在 b1 清单里 → SystemExit；赢家的主行没 DONE、参照没 DONE → problems。"""
    np = _np()
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys = [], [], []
    known = {x[0]: x for x in FAM1_ROWS}
    if not FAM1C_WINNERS or len(FAM1C_WINNERS) > 5 or len(set(FAM1C_WINNERS)) != len(FAM1C_WINNERS) or set(FAM1C_WINNERS) - set(known):
        raise SystemExit(f"b28c: FAM1C_WINNERS {FAM1C_WINNERS!r} must be 1 to 5 distinct labels of FAM1_ROWS")
    b1_ids, err = recorded_ids(B3_REF_BATCH)
    if err:
        raise SystemExit(err)
    refs = {}
    for h in (FAM1_CTRL_H, HEAVY_H):
        j0 = b1_ids.get(f"REF_h{h:g}")
        if not j0:
            raise SystemExit(f"b28c: the {B3_REF_BATCH} manifest has no submitted REF_h{h:g}")
        st = J.state(J.QROOT / j0)
        if st != "DONE":
            problems.append(f"b28c: reference REF_h{h:g} = {j0} is {st} (must be DONE)")
        refs[h] = j0
    ph = b2_phase()
    for lab in FAM1C_WINNERS:
        _, e, _a0, _bone, u = known[lab]
        tag = f"fam1_{lab}_e{e:+g}"
        main = _variant(_phys(ph.spec_of(np.asarray(u, float), tag, bonded=True), f"db_al {tag}"), "db_al", tag, "fric", entry_offset=float(e))
        main_id = expected_id(main)
        st = J.state(J.QROOT / main_id) if (J.QROOT / main_id).is_dir() else "absent"
        if st != "DONE":
            problems.append(f"b28c {lab}: the b28 row {main_id} is {st} (must be DONE)")
        p_ = _phys(main, main_id)
        for key, layer, spec, ref_key in (
                (f"FAM1R_{lab}", "FAM-1 rep", _variant(p_, "db_nz", f"{tag}_h{FAM1_CTRL_H:g}", "full", intact_job=refs[FAM1_CTRL_H], h_int=FAM1_CTRL_H), f"REF_h{FAM1_CTRL_H:g}"),
                (f"FAM1H_{lab}", "FAM-1 h1.4", _variant(p_, "db_fd", f"{tag}_h{HEAVY_H:g}", "full", intact_job=refs[HEAVY_H], h_int=HEAVY_H, slip_tol=H14_SLIP_TOL), f"REF_h{HEAVY_H:g}"),
                (f"FAM1S_{lab}", "FAM-1 sts", _variant(p_, "db_cd", f"{tag}_{STS1_LOAD}", "fric", cfg={"load": dict(STS_LOADS[STS1_LOAD])}), None)):
            r = _row(key, layer, spec, main_id, None, ref_key=ref_key, extra={"e_forced": float(e)})
            r.update(unbiased=False, in_E=True)
            rows.append(r)
            keys.append(key)
    return _finish_batch("b28c", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2, FAM1_CTRL_H: refs[FAM1_CTRL_H], HEAVY_H: refs[HEAVY_H]})


def build_b20() -> dict:
    """b20 = AL-4m 的 A 部分（模块说明"批次 b20、b21"）：设计 A 的形状 × m 1.6、1.75、2.0。对照 WS_m1.5 必须 DONE；不可行、模板化报错、偏移不是写定的值 → problems。"""
    qspecs, by_h8, by_phys, warn = _batch_ctx()
    problems, rows, keys, ws_tpl = [], [], [], {}
    base = CODES[WS_BASE]
    src = load_source(base, "design", qspecs)
    phys = _phys(src, base)
    load_source(REF_H2, "intact", qspecs)
    tag = _tag_of(base)
    base_e = None
    try:
        t0 = ws_templating(src)
        ws_tpl[WS_BASE] = t0
        base_e = t0["e_star"]
    except Exception as e:                              # noqa: BLE001  模板化核对不了 = 不提交
        problems.append(f"b20: 0-FE templating of the base design {base} failed: {type(e).__name__}: {str(e)[:300]}")
    ctrl = _variant(phys, "db_ws", f"{tag}_m{WM2_CONTROL:g}", "full", intact_job=REF_H2, design={**phys["design"], "m": WM2_CONTROL})
    ctrl_id = expected_id(ctrl)
    ctrl_state = J.state(J.QROOT / ctrl_id) if (J.QROOT / ctrl_id).is_dir() else "absent"
    if ctrl_state != "DONE":
        problems.append(f"b20: the control WS_m{WM2_CONTROL:g} = {ctrl_id} is {ctrl_state} (must be DONE: the scan continues from it)")
    for val in WM2_M:
        lab = f"m{val:g}"
        spec = _variant(phys, "db_ws", f"{tag}_{lab}", "full", intact_job=REF_H2, design={**phys["design"], "m": float(val)})
        ext = {"cond": None, "e_star": None, "e_forced": None}
        try:
            t = ws_templating(spec)
            ws_tpl[lab] = t
            ext["e_star"] = t["e_star"]
            want = WM2_E_JUMP.get(val, base_e)
            if not t["feasible"]:
                problems.append(f"WS_{lab}: 0-FE templating is not feasible ({t['reason']}); prep would fail, no FE can run")
            elif want is not None and abs(t["e_star"] - want) > 1e-9:
                problems.append(f"WS_{lab}: entry offset e* {t['e_star']:g} != the {want:g} written for this row (an unplanned offset jump would be mixed into the scan)")
        except Exception as e:                          # noqa: BLE001
            problems.append(f"WS_{lab}: 0-FE templating failed: {type(e).__name__}: {str(e)[:300]}")
        r = _row(f"WS_{lab}", "WS m2", spec, base, WS_BASE, extra=ext)
        r.update(unbiased=False, in_E=True)
        rows.append(r)
        keys.append(r["key"])
    return _finish_batch("b20", rows, keys, qspecs, by_h8, by_phys, warn, problems, {H_PROD: REF_H2}, ws_tpl=ws_tpl, ws_control=ctrl_id)


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
    if b.get("ws_tpl"):
        print("0-FE templating (tpl_record.record_spec; femur cache read-only; no model built, nothing solved):")
        for k, t in b["ws_tpl"].items():
            print(f"    {k:<12} feasible {t['feasible']} e* {t['e_star']:g} A0* {t['A0_star']:.1f} mm2 bone {t['bone_mm3'] / 1000:.2f} cm3 "
                  f"e_margin_eff {t['e_margin_eff']:.3f}")
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
                      **({"ws_tpl": b["ws_tpl"]} if b.get("ws_tpl") else {}),
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


B2_LAYERS = ("SF-1", "CR-1", "CR-T", "CD-1 rand", "BD offset", "AL-1", "AL-1 sts", "AL-1 rand", "AL-2", "AL-2 sts", "AL-2 rand",
             "AL-3", "AL-3 sts", "AL-3 rand", "WS m", "WS alpha", "W-0 alpha", "W-0 L", "AL-3m", "AL-3m sts", "AL-3m rand", "WS m alpha", "WL-1", "OW-2", "OW-3", "WS m2", "AL-4m", "AL-4m sts", "AL-4m rand", "OPT-1", "FAM-1")
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
