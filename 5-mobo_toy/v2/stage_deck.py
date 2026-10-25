"""导师汇报的补算作业（用户 2026-10-05；清单 research-log/neck_implant_2026-10-02/deck_plan/补算实验清单_2026-10-05.md）。
全部 kind = variant，不进任何优化数据集；现行生产设置（M1、δ 0.025、μ 0.3、爬楼 2391 N + 扭矩、2.0 mm、平端、统一截骨面）。

    python v2/stage_deck.py submit A|B|C       → results/deck_<批次>_ids.json（可重复提交，已有的作业复用）
    python v2/stage_deck.py status A|B|C
批次
    A  领只受压：7 个设计 × 粘接模型两种领（tied 共节点 / contact 只受压），只解粘接模型（bond_only）
    B  演示重算：完整股骨参照 + FI、FI-0、J1、R1、R2、LA、B2，摩擦模型 + 粘接模型（tied），另各一个 contact 粘接模型；保留 odb
    C  单因素扫描：B1 = FI、B2 = neck5_r10，按清单水平表，每个水平摩擦 + tied 粘接，另一个 contact 粘接（bond_only）
    E  领的新规则 wrap_fit（领包住假体颈、整圈落在骨截面上）：8 个设计，摩擦 + tied 粘接，另一个 contact 粘接
    BW 演示素材按 wrap_fit 重做（6 个设计，保留 odb）；CW 领宽扫描按 wrap_fit 重算（两个基线 × 2/4/6 mm）
    D13 50 h 计划段 D（阶段 13 / 14 两臂跑完后的前沿核查）：设计在提交时从最终状态文件与队列里选（d13_select），见批次 D13 的说明

    python v2/stage_deck.py submit D13 --dry-run [--root <本地副本>]   → 只打印作业表（键、源作业、相对源 spec 的变体、stage、tag、预期 id），什么都不写
    python v2/stage_deck.py submit D13                               → 两臂没跑完（pending / 记录 < budget / 队列里有没算完的 sb13_* sb14_*）就拒绝
        [--allow-unfinished]  照样提交（D13 作业 d13* 会排在 sb13_* / sb14_* 前面建模、求解，拖慢两臂）
        [--reselect]          选择里有 deck_D13_ids.json 没有的键时照样提交（过时键与其作业保留）
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

# 设计代号 → 来源作业（FI / FI-0 来自 10-02 的旧设置作业，按现行设置重建：平端、截深 25，截骨面由现行代码统一）
SOURCES = {"FI": "collar_neck_w3_36c2bb73", "FI0": "collar_neck_w0_9e92d3e1", "J1": "neck3_a40_967145a2",
           "B2": "neck5_r10_dad61bcd", "S1B": "neck1_r6_102aba81", "LA": "neck5_r7_5df27b13", "R1": "neck5_r3_9f0000eb",
           "R2": "neck3_a45_639d489d", "P2": "neck3_a48_f9ed1d41", "T2": "neck1_init_3d14a026"}
A_CODES = ("FI", "J1", "B2", "S1B", "LA", "R1", "R2")
B_CODES = ("FI", "FI0", "J1", "R1", "R2", "LA", "B2")
# 批次 E（用户 2026-10-06）：领的新规则 wrap_fit（collar_rule.py）。J1、R2 的原领宽在新规则下放不下，取新规则下能放下的最大领宽
E_CODES = ("FI", "R1", "J1", "R2", "B2", "LA", "P2", "T2")
E_COLLAR_W = {"J1": 3.42, "R2": 4.31}
CURRENT = {"h_int": 2.0, "min_A0": 153.93804002589985, "model": "m1", "slip_tol": 0.00025, "delta": 0.025}


def base_spec(code: str) -> dict:
    """现行设置下的设计规格（不含 stage / tag）。"""
    src = json.loads((J.QROOT / SOURCES[code] / "spec.json").read_text())
    d = dict(src["design"])
    if code in ("FI", "FI0"):
        d["cap_h"] = G.CAP_FLAT                                 # 旧作业是圆头；现行 = 平端
    return {**CURRENT, "design": d, "h_cut": float(src.get("h_cut", 25.0))}


# 截面类型（与阶段 0 相同的定义，stage_collar.NECK_SETS）：圆 = 椭圆公式 λ 1.0；非对称 = stage_v2a.BASE 的截面参数、λ 1.3
SECTION_KEYS = ("lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
SECTIONS = {"circ": {"lam": 1.0, "g_ml": 0.5, "g_ap": 0.5, "n_a": 2.0, "n_p": 2.0, "tau_a": 0.0, "tau_p": 0.0},
            "asym": {"lam": 1.3, "g_ml": 0.62, "g_ap": 0.42, "n_a": 5.0, "n_p": 3.0, "tau_a": 0.25, "tau_p": 0.05}}
# 单因素扫描的水平表（清单批次 C）；"design" 类改设计变量，"model" 类改模型假设
OFAT = {"B1": {"base": "FI", "L": (25.0, 35.0, 40.0, 45.0), "alpha": (25.0, 30.0, 35.0, 45.0), "m": (0.0, 0.5, 1.0, 1.5),
               "collar_w": (0.0, 2.0, 4.0, 6.0), "rho_tip": (0.33, 0.7), "section": ("circ", "asym"), "mu": (0.5, 0.8), "delta": (0.05, 0.01)},
        "B2": {"base": "B2", "L": (38.0, 43.0, 53.0, 58.0), "alpha": (25.6, 30.6, 40.6, 45.0), "m": (-0.25, 0.5, 1.0, 1.5),
               "collar_w": (0.0, 2.0, 4.0, 6.0), "rho_tip": (0.33, 0.7), "section": ("circ", "asym"), "mu": (0.5, 0.8)}}


def ofat_level(base: dict, factor: str, level) -> dict:
    s = json.loads(json.dumps(base))
    d = s["design"]
    if factor in ("mu", "delta"):
        s[factor] = float(level)
    elif factor == "section":
        d.update(SECTIONS[level])
    elif factor == "collar_w":
        if level > 0:
            d["collar_w"] = float(level)
            d.setdefault("collar_t", G.COLLAR_T)
        else:
            d.pop("collar_w", None)
            d.pop("collar_t", None)
    else:
        d[factor] = float(level)
    return s


# 批次 F（用户 2026-10-06 中午："再设计一批实验，今天做完"）
F1_FRONT = ("neck3_a53_89e60afc", "neck3_a74_e72c4e70", "neck3_a55_639b1448", "neck6_r1_b5abb5d4", "neck6_r4_76c23a8e", "neck3_r6_dc9dfb8a",
            "neck6_r4_a4a804e8", "neck6_r6_2df962ef", "neck3_a54_bbe8444b", "neck3_a41_9cf9f12f", "neck3_r7_408dc339", "neck3_a68_9ec845c7",
            "neck3_a45_639d489d", "neck3_a81_cb5ce57b", "neck2_r2_cabafb5f", "neck3_a83_4f3a1387", "neck3_a60_ae1a0793", "neck3_a49_fceb10b0",
            "neck3_a76_26358701", "neck2_r11_8687e375", "neck2_r9_60bd1d12", "neck3_a40_967145a2")   # 新口径（柄身微动 2 µm 截断）前沿，主表 2026-10-06
F2_CODES = ("J1", "B2", "LA", "S1B", "R1", "FI", "R2", "FI0")
LOADS = {"iso": {"cfg": {"load": {"resultant_N": 2300.0, "alpha_front_deg": 10.0, "alpha_sagit_deg": 9.0}}, "intact": "ata_intact_h2_iso_S_4a1cdfa6"},
         "high": {"cfg": {"load": {"resultant_N": 3606.0}}, "intact": None}}                 # high = HIGH100 合力，方向同爬楼
# 批次 G（用户 2026-10-06 18:20："再设计一批，到明天早上"）
# G1 入口偏移诊断：B1 余量扫描在两种领规则下差 3.9 倍对 1.37 倍，号和领面积相近，只剩入口偏移 e 不同（现行 −2、新规则 0）
G1_CASES = {"cur_base_e0": (None, -0.25, 0.0), "cur_m1.0_e0": (None, 1.0, 0.0), "cur_m1.5_e0": (None, 1.5, 0.0),
            "wrap_base_em2": ("wrap_fit", -0.25, -2.0), "wrap_m1.5_em2": ("wrap_fit", 1.5, -2.0)}       # (领规则, 余量 m, 固定的 e)
# G2 载荷方向分解：爬楼（前 20°、矢 18°）与 ISO 类（10°、9°）之间的两个角，合力都取 2391 N；另补 ISO 角度 × 2391 N 去掉合力差
G2_CODES = ("FI", "J1", "R2", "B2")
G2_LOADS = {"front10": {"resultant_N": 2391.0, "alpha_front_deg": 10.0, "alpha_sagit_deg": 18.0},
            "sag9": {"resultant_N": 2391.0, "alpha_front_deg": 20.0, "alpha_sagit_deg": 9.0},
            "iso2391": {"resultant_N": 2391.0, "alpha_front_deg": 10.0, "alpha_sagit_deg": 9.0}}
# G3 重新划网格的噪声：柄长 ±0.002 mm（几何几乎不变，网格重划），与 BW 的原作业一起每个设计 3 个样本
G3_CODES = ("FI", "J1", "R2", "B2")
G3_JITTER = (0.002, -0.002)
# 批次 P9D（阶段 9 设计文档第 2.2 节：压配能不能补上领的缺口）：无领前沿与有领前沿各 5 个代表设计（沿前沿按去骨量 0、25、50、75、100 % 位置取），
# 过盈 0.025 → 0.05 mm，其余与源作业完全相同。kind = variant，δ ≠ 0.025 也不会进任何优化数据集。
P9D_SOURCES = {"nocollar_1": "neck9_a70_c7ef19ee", "nocollar_2": "neck9_a37_528b7df7", "nocollar_3": "neck9_a44_5d5deeb7",
               "nocollar_4": "neck9_a71_099d9916", "nocollar_5": "neck9_a96_c888e6c4",
               "collar_1": "front_wrap_a53_89e60afc_ad3918b3", "collar_2": "neck8_a67_e47ce03b", "collar_3": "front_wrap_a81_cb5ce57b_8404a846",
               "collar_4": "front_wrap_a60_ae1a0793_cc3f72d5", "collar_5": "front_wrap_a40_967145a2_566aee4e"}
P9D_DELTA = 0.05
# 批次 MI / M / M14（用户 2026-10-23："现在就开始进行"；计划 research-log/neck_implant_2026-10-02/计算计划_2026-10-24.md 第 1 节）：
# 方法闸门 —— 6 个参考设计（RS6 = 阶段 10 严格余量下 A0 不变的前沿 4 个 + 中等 a12 + 固定差 e2a）的网格 / 滑移容差变体，其余与源作业相同。
# kind = variant 且 h_int / slip_tol ≠ 生产值，不进任何优化数据集。MI = 对应网格的完整股骨参照（显式 intact_job，不用 2.0 代替）。
RS6 = {"a69": "neck10_a69_e394e85c", "a24": "neck10_a24_41b88dd9", "a12": "neck10_a12_b1fbfd1c", "e2a": "neck9_init_e2a68dea",
       "a36": "neck10_a36_0911f520", "a19": "neck10_a19_c15fe9c6"}
M_A3 = ("a69", "a24", "a12", "e2a")               # A3 重网格噪声：h_int 1.94 / 2.06（真正重划网格；ΔL 抖动不改界面节点对数）
MI_H = (1.94, 2.06, 2.5)                         # 需要新参照的网格档；h 1.4 已有 ref_intact_h1.4_dad6d1ae（verify 批用过）
M_SLIP14 = 0.000357143                           # = 2.5e-4 × 2.0/1.4，与 verify_mesh14 相同的字面值（弹性滑移上限仍 0.5 µm）
M_REF14 = "ref_intact_h1.4_dad6d1ae"


# 批次 SB（2026-10-24，用户"按你建议的继续"；计划 计算计划_2026-10-24.md 第 2 节 S8）：Sawbones 3406 上的第一批作业。
# SB_ref = 3406 完整股骨参照（stage "sb"，jobs.submit 禁止 femur_id 作业用 "ref" / "neck*"）；SB_smoke = 两个冒烟设计，按 Phase(11).spec_of
# 生成（stage "sb11"，fric_only，不需要参照），设计 = S6 / hcut16 已验证能建模的 a69（L 缩到 35），截骨 16 与 20。参照解完后把 id 填到
# stage_neckopt.PHASES[11]["intact_job"]，再交一个带粘接模型的冒烟作业（批次 SBb）。
SB_INTACT = {"kind": "intact", "h_int": 2.0, "stage": "sb", "tag": "intact_h2", "femur_id": "sawbone3406", "neck_axis": "isthmus"}
SB_SMOKE_DESIGN = "neck10_a69_e394e85c"
SB_SMOKE_L = 35.0
SB_SMOKE_H = (16.0, 20.0)


def _sb_smoke(bonded: bool) -> dict:
    import stage_neckopt as SN
    ph = SN.Phase(11)
    src = json.loads((J.QROOT / SB_SMOKE_DESIGN / "spec.json").read_text())
    d = {**src["design"], "L": SB_SMOKE_L}
    out = {}
    for h in SB_SMOKE_H:
        u = ph.to_unit(d, h)
        tag = f"smoke_{'b' if bonded else 'f'}_h{h:g}"
        out[f"SB_{tag}"] = {**ph.spec_of(u, tag, bonded=bonded), "source_job": SB_SMOKE_DESIGN}
    return out


def _m_src(job: str) -> dict:
    src = json.loads((J.QROOT / job / "spec.json").read_text())
    if not (J.QROOT / job / "DONE").exists():
        raise SystemExit(f"M source {job} is not DONE")
    return {k: v for k, v in src.items() if k not in ("created", "stage", "tag", "kind", "bond_only")}


def _mi_ref(h: float) -> str:
    f = J.RESULTS / "deck_MI_ids.json"
    if not f.exists():
        raise SystemExit("submit MI first (deck_MI_ids.json missing)")
    return json.loads(f.read_text())["jobs"][f"MI_h{h:g}"]


def wrap_fit_design(base: dict) -> dict:
    """新领规则下可行的设计：放不下就把领宽二分到能放下的最大值（记 collar_w_original）。"""
    import collar_rule as CR
    d = dict(base["design"])
    if not d.get("collar_w"):
        return d
    fm = J.femur_for(base)
    ok = lambda w: CR.template_wrap_fit(G.Stem3D(**{**d, "collar_w": float(w)}), fm, margin=base.get("margin"),  # noqa: E731
                                        min_A0=float(base.get("min_A0", 0.0))).get("fit", False)
    if ok(d["collar_w"]):
        return d
    lo, hi = 0.0, float(d["collar_w"])
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        (lo, hi) = (mid, hi) if ok(mid) else (lo, mid)
    lo = math.floor(lo * 1000) / 1000                     # 向下取整：四舍五入会越过"放得下"的边界（2026-10-06 neck3_a53：4.938 判不可行）
    return {**d, "collar_w_original": d["collar_w"], "collar_w": lo} if lo > 0.05 else {**d, "collar_w_original": d["collar_w"], "collar_w": 0.0}


def spec_of_job(job: str) -> dict:
    src = json.loads((J.QROOT / job / "spec.json").read_text())
    return {**CURRENT, "design": dict(src["design"]), "h_cut": float(src.get("h_cut", 25.0))}


# 批次 D13（2026-10-25；计算计划_50h_2026-10-24.md 第 2 节段 D 与第 7 节修订；p13_3406/snap_2026-10-25_0340_half/角落设计核查_2026-10-25.md；
# 同日按审查 w5g2teby3 修订：粘接补算全覆盖 + 安全上限 25、跨提交累积、真提交也打印警告、一次调用只选一次；起身改为 3 个对比设计——主会话批准）：
# 阶段 13 / 14 两臂跑完后的前沿核查，一条命令提交。设计不写死，提交时从最终状态文件 results/neckopt_p13.json / neckopt_p14.json 选
# （d13_select，纯函数，不读队列；prior = 已有 results/deck_D13_ids.json 的 jobs）：
#   F13 = 阶段 13（2 目标 v3：log10 转动、−完全接触面积）可行记录（ok 且 c ≤ 0）的非支配集；
#   F14 = 阶段 14（3 目标 v4：再加去骨量）的非支配集，数据 = 自有可行记录 + 冻结热启动行（warm_start_ids 指向的阶段 13 记录，
#         y = 阶段 13 的 y + bone_mm3，即阶段 14 按 v4 / mm_limit None / sed none 重打分的值；角落设计核查：两个阶段 13 目标同序，
#         2 目标前沿只有几个点，3 目标集沿去骨量展开）。热启动 id 不在阶段 13 的记录里 → SystemExit（两个状态文件不配套）；
#   两臂可能各解同一个池点：按单位立方体坐标 x 去重（两臂同一设计空间，状态文件的 space / fixed 必须相同），同一设计只出一组变体，
#   代表作业 = 前沿行里阶段号小、作业号小的那个（源作业进 spec 的 source_job，所以选法固定 = 作业 id 固定）。
# 1. 应力屏蔽补算（SED / 柄 vM 只记录）：F13 ∪ F14 里每个还没有可用粘接结果的设计 → bond_only 变体。"可用" = 该设计在两个状态文件里
#    任一记录 bonded 且 ok，且 sed_chg_pct、vm_p99 都不是 None（bond_every 5：每 5 个提交第 5 个带粘接模型；bonded ok 却缺这两个值之一——
#    stage_neckopt._calcar 出错时返回 None——→ 警告，该设计按没有粘接结果算）。bond_only = 只解粘接模型：jobs.prep 按同一 spec 重新模板化、
#    重新划网格（不复用摩擦作业的网格；不假设两个作业的节点编号一致——SED / vM 全部来自本作业自己的粘接模型，SED 与完整股骨参照在
#    resorption 的规则网格上比较），删 m_fric.inp。显式 intact_job = PHASES[p]["intact_job"]（3406 完整股骨参照；jobs.ref_for 对 femur_id
#    作业必须有，且须与状态文件记的相同）；fric_only 去掉（与 bond_only 互斥，jobs.prep 判 L1）。
#    累积：deck_D13_ids.json 里已有的每个 D13_bond_<源作业> 键按源作业的 x（状态文件记录里的单位立方体坐标）对到设计——设计还在前沿上 =
#    已覆盖，键原样再出（同一 spec = 同一 id，不新建作业）；不在前沿上 = 过时键（不再出，留在 ids 文件里）；两种都计入上限。
#    源作业不在任何一个状态文件的记录里 → SystemExit。
#    上限 D13_BOND_CAP = 25 个 D13 bond_only 作业（含以前提交的；安全上限）：放得下就全部覆盖；放不下时 F13 的设计先入选（按转动），
#    再给 F14 的设计按转动 D13_BOND_ROT_SLOTS = 3 个名额，余下名额在归一化二维（log10 转动、去骨量，各按全部前沿设计的最小 / 最大值归一）
#    里贪心最远点铺开（锚 = 已覆盖的前沿设计与已选设计；每次取离最近锚最远的，并列取转动小的）；没选上的打印出来（dropped by the cap）。
# 2. 起身（sit-to-stand；U6 未定 → 两档都算）：3 个对比前沿设计 × 合力 {1714, 3839} N，方向 α_front 24° / α_sagit 8°
#    （Bergmann 2016 表 5 起身；1714 = AVER75 1600 × 2391 / 2232，与现在楼梯载荷同缩放；3839 = HIGH100）。设计：
#    (a) F13 ∪ F14 里转动最小的；(b) F14 里（不含 a）去骨量 ≤ D13_STS_BONE_MAX = 6000 mm³ 的转动最小者，没有就取 F14 里转动 < D13_STS_ROT_MAX
#    = 1° 的去骨量最小者，再没有 → 警告、不出 (b)；(c) F14 里（不含 a、b）去骨量居中的（偶数个取下中位）。原规则"转动前 3 个"选出的是三个
#    几乎相同的角落设计（04:36：a62 / a70 / a71），回答不了"楼梯载荷下的排序在起身载荷下是否保持"。
#    spec 键 cfg = {"load": …}：jobs.femur_for 把它合并进本作业 fm.cfg 的副本（3406 的 cfg = config_v2a.yaml 的深拷贝，同样的 load 节），
#    model3d_m1 从 fm.cfg["load"] 算头力（model3d_v2.load_vector）——不改任何哈希文件；cfg 进作业 id。torque 不写 = 默认 True（头力全部分量，
#    力矩由头心偏距产生；B16 的起身 Mts 19.3 / Mbs 46.4 N·m 对上楼 47.0 / 113.1 是常规柄上的值，这里不另加力矩）。只算摩擦（fric_only，不需要参照）。
# 3. 网格噪声：2 个前沿设计（F13 ∪ F14 里转动最小的 + F14 里（不含前者）去骨量居中的）× h_int {1.94, 2.06}，只算摩擦（与批次 V3406 相同的做法）。
# stage "d13bond" / "d13sts" / "d13mesh"：不以 "sb" / "neck" 开头、不是 "ref"——in_family（femur_id 阶段只收 "sb*"）不收，bo_async 的收编
# glob（sb13_* / sb14_*）不收；bond_only、cfg、h_int ≠ 2.0 也各自让 in_family 排除。全部 kind variant；_d13_check 对每个 spec 再核对一遍。
# 一次调用（submit 或 dry run）只读一次状态文件、只选一次（d13_build）：作业表、报告、警告与拒绝理由都来自同一个快照；真提交也打印警告与一行摘要。
# 提交前（d13_unfinished）：状态文件 pending 非空、记录数 < budget（且没有 stopped_early）、队列里还有没算完的 sb13_* / sb14_*，或有算完
# 却不在记录里的 → 拒绝提交（--allow-unfinished 才放行；代价见 D13_QUEUE_NOTE）；--dry-run 照样列出并给出这些警告，什么都不写。
# 重复提交：新选择里有 deck_D13_ids.json 没有的键 → 列出新键与过时键并拒绝，--reselect 才提交（新键提交；过时键与其作业留着，不删）。
D13_PHASES = (13, 14)
D13_BOND_CAP = 25
D13_BOND_ROT_SLOTS = 3
D13_BOND_PREFIX = "D13_bond_"
D13_STS_BONE_MAX = 6000.0
D13_STS_ROT_MAX = 1.0
D13_STS = {"F1714": {"resultant_N": 1714.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0},
           "F3839": {"resultant_N": 3839.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0}}
D13_MESH_H = (1.94, 2.06)
D13_STAGE = {"bond": "d13bond", "sts": "d13sts", "mesh": "d13mesh"}
D13_DROP = ("created", "stage", "tag", "kind", "bond_only", "fric_only", "intact_job")   # 源 spec 去掉这些，变体自己再写
# stage_v2a.serve 按 sorted(name) 建模 NEW 作业，solve_worker 按 READY 时间（ls -tr）先来先服务
D13_QUEUE_NOTE = ("D13 jobs (names d13bond_* / d13sts_* / d13mesh_*) sort before sb13_* / sb14_*: stage_v2a.serve preps NEW jobs in name order "
                  "and solve_worker takes READY jobs first come first served, so the D13 jobs would be prepped and solved ahead of the "
                  "arms' jobs and slow the arms down")


def _d13_state(p: int) -> dict:
    f = J.RESULTS / f"neckopt_p{p}.json"
    if not f.exists():
        raise SystemExit(f"D13: {f} missing (the phase {p} arm has not saved a state file)")
    st = json.loads(f.read_text())
    if st.get("phase") != p:
        raise SystemExit(f"D13: {f} holds phase {st.get('phase')!r}, expected {p}")
    return st


def _d13_row(r: dict, phase: int, y: list) -> dict:
    yy = [math.nan if v is None else float(v) for v in y]
    c = (r.get("c") or [None])[0]
    c = math.nan if c is None else float(c)
    feas = bool(r.get("ok")) and all(math.isfinite(v) for v in yy) and math.isfinite(c) and c <= 0
    return {"job_id": r["job_id"], "phase": phase, "key": tuple(round(float(v), 9) for v in r["x"]), "y": yy, "feasible": feas,
            "ok": bool(r.get("ok")), "bonded": r.get("bonded"), "rot_deg": r.get("rot_first_deg"), "area_mm2": r.get("contact_area_load2_mm2"),
            "bone_mm3": r.get("bone_mm3"), "vm_p99": r.get("vm_p99"), "sed_chg_pct": r.get("sed_chg_pct")}


def _d13_nd(rows: list) -> list:
    """非支配集（全部目标最小化）；y 完全相同的两行互不支配，都保留。"""
    Y = [r["y"] for r in rows]
    return [r for i, r in enumerate(rows)
            if not any(all(a <= b for a, b in zip(Y[j], Y[i])) and any(a < b for a, b in zip(Y[j], Y[i])) for j in range(len(rows)) if j != i)]


def _d13_entry(d: dict, r: dict | None = None, **extra) -> dict:
    """列表项：r = 前沿上的那一行（默认 = 该设计的代表作业），fronts / bonded_jobs / d13_keys 是设计层面的。"""
    r = d["rep"] if r is None else r
    return {"job_id": r["job_id"], "phase": r["phase"], "rot_deg": r["rot_deg"], "area_mm2": r["area_mm2"], "bone_mm3": r["bone_mm3"],
            "fronts": sorted(d["fronts"]), "bonded_jobs": list(d["bonded_jobs"]), "d13_keys": list(d.get("prior_keys") or []), **extra}


def _d13_usable_bond(r: dict) -> bool:
    """可用的粘接结果：bonded、ok，且 sed_chg_pct 与 vm_p99 都在（_calcar 出错时 sed_chg_pct 为 None，ok 不要求它）。"""
    return bool(r["bonded"]) and r["ok"] and r["sed_chg_pct"] is not None and r["vm_p99"] is not None


def _d13_farthest(rest: list, anchors: list, n: int, pt) -> tuple:
    """贪心最远点：从 rest（已按转动排好）里取 n 个，每次取离最近锚最远的（并列取 rest 里靠前的 = 转动小的）。返回 (选中, 余下)。"""
    rest, anchors, got = list(rest), list(anchors), []
    while len(got) < n and rest:
        dist = [min(math.dist(pt(d), a) for a in anchors) if anchors else 0.0 for d in rest]
        got.append(rest.pop(dist.index(max(dist))))
        anchors.append(pt(got[-1]))
    return got, rest


def d13_select(st13: dict, st14: dict, bond_cap: int = D13_BOND_CAP, prior: dict | None = None,
               sts_bone_max: float = D13_STS_BONE_MAX, sts_rot_max: float = D13_STS_ROT_MAX) -> dict:
    """纯函数：阶段 13 / 14 的状态文件（+ prior = 已有 deck_D13_ids.json 的 jobs）→ 前沿与三组选择（bond / sts / mesh），
    不读队列、不写文件。规则见批次 D13 的说明。"""
    for p, st in ((13, st13), (14, st14)):
        if st.get("phase") != p:
            raise SystemExit(f"D13: state file for phase {p} holds phase {st.get('phase')!r}")
    if st13.get("space") != st14.get("space") or st13.get("fixed") != st14.get("fixed"):
        raise SystemExit("D13: the phase 13 / 14 state files have different design spaces; designs cannot be matched by x")
    warn = []
    by13 = {r["job_id"]: r for r in st13["records"]}
    rows13 = [_d13_row(r, 13, list(r["y"])) for r in st13["records"]]
    rows14 = [_d13_row(r, 14, list(r["y"])) for r in st14["records"]]
    bad = [r["job_id"] for r in rows13 if r["ok"] and len(r["y"]) != 2] + [r["job_id"] for r in rows14 if r["ok"] and len(r["y"]) != 3]
    if bad:
        raise SystemExit(f"D13: records with the wrong number of objectives (phase 13 = 2, phase 14 = 3): {bad[:5]}")
    warm_ids = list(st14.get("warm_start_ids") or [])
    missing = [j for j in warm_ids if j not in by13]
    if missing:
        raise SystemExit(f"D13: {len(missing)} phase-14 warm-start id(s) are not phase-13 records ({', '.join(missing[:5])}); "
                         "the two state files do not belong together")
    warm = [_d13_row(by13[j], 13, list(by13[j]["y"])[:2] + [by13[j].get("bone_mm3")]) for j in warm_ids]
    F13 = _d13_nd([r for r in rows13 if r["feasible"]])
    F14 = _d13_nd([r for r in rows14 + warm if r["feasible"]])
    allrows, by_job = {}, {}
    for r in rows13 + rows14:
        allrows.setdefault(r["key"], []).append(r)
        by_job.setdefault(r["job_id"], r)
        if r["bonded"] is None and r["ok"]:
            warn.append(f"{r['job_id']}: record has bonded None (spec.json was missing when it was recorded); counted as not bonded")
        elif r["bonded"] and r["ok"] and not _d13_usable_bond(r):
            miss = " and ".join(k for k in ("sed_chg_pct", "vm_p99") if r[k] is None)
            warn.append(f"{r['job_id']}: bonded ok record has no {miss}; its design counts as not bonded")
    designs = {}
    for name, front in (("F13", F13), ("F14", F14)):
        for r in front:
            d = designs.setdefault(r["key"], {"key": r["key"], "rows": [], "fronts": set()})
            d["fronts"].add(name)
            if r["job_id"] not in [x["job_id"] for x in d["rows"]]:
                d["rows"].append(r)
    if not designs:
        raise SystemExit("D13: no feasible design on either front")
    for d in designs.values():
        d["rep"] = sorted(d["rows"], key=lambda r: (r["phase"], r["job_id"]))[0]
        d["bonded_jobs"] = sorted({r["job_id"] for r in allrows.get(d["key"], []) if _d13_usable_bond(r)})
        d["prior_keys"] = []
        if d["rep"]["bone_mm3"] is None:
            raise SystemExit(f"D13: front design {d['rep']['job_id']} has no bone_mm3")
    prior_bond = sorted(k for k in (prior or {}) if k.startswith(D13_BOND_PREFIX))   # 以前提交的 D13 bond_only 作业：按源作业的 x 对到设计
    stale = []
    for k in prior_bond:
        src = k[len(D13_BOND_PREFIX):]
        r = by_job.get(src)
        if r is None:
            raise SystemExit(f"D13: deck_D13_ids.json key {k}: source job {src} is in neither state file's records, so its design cannot be matched by x")
        if r["key"] in designs:
            designs[r["key"]]["prior_keys"].append(k)
        else:
            stale.append({"key": k, "job_id": src, "phase": r["phase"], "rot_deg": r["rot_deg"], "area_mm2": r["area_mm2"], "bone_mm3": r["bone_mm3"],
                          "fronts": [], "bonded_jobs": [], "d13_keys": [k]})
    by_rot = sorted(designs.values(), key=lambda d: (d["rep"]["y"][0], d["rep"]["job_id"]))
    covered = [d for d in by_rot if d["bonded_jobs"]]
    kept = [d for d in by_rot if d["prior_keys"]]
    cand = [d for d in by_rot if not d["bonded_jobs"] and not d["prior_keys"]]
    slots = max(0, bond_cap - len(prior_bond))
    if len(prior_bond) > bond_cap:
        warn.append(f"deck_D13_ids.json already holds {len(prior_bond)} D13 bond_only jobs, more than the cap {bond_cap}: no new bond_only job")
    f13c = [d for d in cand if "F13" in d["fronts"]]
    if len(cand) <= slots:                                                            # 放得下：全部覆盖（F13 在前，各按转动）
        chosen, rest = f13c + [d for d in cand if "F13" not in d["fronts"]], []
    else:                                                                             # 放不下：F13 → F14 按转动 3 个 → 归一化二维最远点
        chosen = f13c[:slots]
        rest = [d for d in cand if all(d is not c for c in chosen)]
        rot_pick = [d for d in rest if "F14" in d["fronts"]][:max(0, min(D13_BOND_ROT_SLOTS, slots - len(chosen)))]
        chosen = chosen + rot_pick
        rest = [d for d in rest if all(d is not c for c in rot_pick)]
        lo = (min(d["rep"]["y"][0] for d in by_rot), min(d["rep"]["bone_mm3"] for d in by_rot))
        span = tuple((h - l_) or 1.0 for l_, h in zip(lo, (max(d["rep"]["y"][0] for d in by_rot), max(d["rep"]["bone_mm3"] for d in by_rot))))

        def pt(d):
            return ((d["rep"]["y"][0] - lo[0]) / span[0], (d["rep"]["bone_mm3"] - lo[1]) / span[1])
        got, rest = _d13_farthest(rest, [pt(d) for d in covered + kept + chosen], slots - len(chosen), pt)
        chosen = chosen + got
    # 起身：3 个对比设计
    a = by_rot[0]
    f14 = [d for d in by_rot if "F14" in d["fronts"] and d is not a]

    def rot(d):
        return d["rep"]["rot_deg"] if d["rep"]["rot_deg"] is not None else 10.0 ** d["rep"]["y"][0]
    b = next((d for d in f14 if d["rep"]["bone_mm3"] <= sts_bone_max), None)
    b_rule = f"lowest-rotation F14 design with bone removal <= {sts_bone_max:g} mm3"
    if b is None:
        low = sorted((d for d in f14 if rot(d) < sts_rot_max), key=lambda d: (d["rep"]["bone_mm3"], d["rep"]["job_id"]))
        b = low[0] if low else None
        b_rule = f"lowest-bone F14 design with rotation < {sts_rot_max:g} deg (no F14 design with bone removal <= {sts_bone_max:g} mm3)"
        if b is None:
            warn.append(f"sit-to-stand (b): no F14 design other than (a) with bone removal <= {sts_bone_max:g} mm3 or rotation < {sts_rot_max:g} deg; "
                        "(b) left out")
    mids = sorted((d for d in f14 if d is not b), key=lambda d: (d["rep"]["bone_mm3"], d["rep"]["job_id"]))
    c = mids[(len(mids) - 1) // 2] if mids else None
    if c is None:
        warn.append("sit-to-stand (c): no F14 design other than (a) and (b); (c) left out")
    sts = [_d13_entry(a, role="a", rule="lowest rotation on F13 + F14")]
    sts += [_d13_entry(b, role="b", rule=b_rule)] if b is not None else []
    sts += [_d13_entry(c, role="c", rule="median bone removal among F14 (excluding a and b)")] if c is not None else []
    mesh = [by_rot[0]]
    mid = sorted([d for d in designs.values() if "F14" in d["fronts"] and d is not by_rot[0]], key=lambda d: (d["rep"]["bone_mm3"], d["rep"]["job_id"]))
    if mid:
        mesh.append(mid[(len(mid) - 1) // 2])
    elif len(by_rot) > 1:
        mesh.append(by_rot[1])
    return {"F13": [_d13_entry(designs[r["key"]], r) for r in sorted(F13, key=lambda r: (r["y"][0], r["job_id"]))],
            "F14": [_d13_entry(designs[r["key"]], r) for r in sorted(F14, key=lambda r: (r["y"][2], r["job_id"]))],
            "covered": [_d13_entry(d) for d in covered],
            "bond_kept": [_d13_entry(d, by_job[k[len(D13_BOND_PREFIX):]], d13_key=k) for d in kept for k in d["prior_keys"]],
            "bond_stale": stale,
            "bond": [_d13_entry(d) for d in chosen], "bond_left_out": [_d13_entry(d) for d in rest],
            "sts": sts, "mesh": [_d13_entry(d) for d in mesh],
            "n_designs": len(designs), "bond_cap": bond_cap, "bond_slots": slots, "n_prior_bond": len(prior_bond), "warnings": warn}


def d13_unfinished(st13: dict, st14: dict) -> list:
    """两臂是否跑完：返回问题列表（空 = 跑完）。只读状态文件与队列的标记文件。"""
    probs = []
    for p, st in ((13, st13), (14, st14)):
        if st.get("pending"):
            probs.append(f"phase {p}: {len(st['pending'])} pending in the state file ({', '.join(sorted(st['pending']))})")
        n, b = len(st.get("records") or []), st.get("budget")
        if b is not None and n < int(b) and st.get("stopped_early") is None:
            probs.append(f"phase {p}: {n} records < budget {b} (the arm is still running, or stopped before its budget)")
        rec_ids = {r["job_id"] for r in st.get("records") or []}
        for d in sorted(J.QROOT.glob(f"{st.get('stage') or f'sb{p}'}_*")):
            if not (d / "spec.json").exists():                          # 正在建或已损坏：不默默跳过（CLAUDE.md §11）
                probs.append(f"phase {p}: queue dir {d.name} has no spec.json (being created or damaged)")
                continue
            s_ = J.state(d)
            if s_ not in ("DONE", "FAILED"):
                probs.append(f"phase {p}: queue job {d.name} is {s_}")
            elif d.name not in rec_ids:
                probs.append(f"phase {p}: queue job {d.name} is {s_} but not in the state file's records (state file stale?)")
    return probs


def _d13_src(job: str) -> dict:
    d = J.QROOT / job
    if not (d / "DONE").exists():
        raise SystemExit(f"D13 source {job} is not DONE")
    src = json.loads((d / "spec.json").read_text())
    if src.get("kind") != "design" or not str(src.get("stage", "")).startswith(tuple(f"sb{p}" for p in D13_PHASES)):
        raise SystemExit(f"D13 source {job}: kind {src.get('kind')!r} stage {src.get('stage')!r} is not a phase 13 / 14 design job")
    return {k: v for k, v in src.items() if k not in D13_DROP}


def _d13_tag(job: str) -> str:
    stage, rest = job.split("_", 1)                                      # "sb13_a62_1e4338ee" → "p13_a62_1e4338ee"
    return f"p{stage[2:]}_{rest}"


def _d13_check(out: dict) -> None:
    """每个 D13 spec：kind variant、stage 是 D13 的（不以 sb / neck 开头、不是 ref）、作业号不以 sb13_ / sb14_ 开头、bond_only 与 fric_only
    恰有一个、bond_only 带 intact_job 而 fric_only 不带、model m1，且不在阶段 11–14 的任何族里（不进任何优化数据集）。不通过 → SystemExit。"""
    import stage_neckopt as SN
    phases = [SN.Phase(p) for p in (11, 12, 13, 14)]
    bad = []
    for k, s in out.items():
        jid = J.job_id({**s, "created": ""})
        st = str(s.get("stage", ""))
        why = [w for w, cond in (
            ("kind != variant", s.get("kind") != "variant"),
            (f"stage {st!r}", st not in D13_STAGE.values() or st.startswith(("sb", "neck")) or st == "ref"),
            (f"job id {jid}", jid.startswith(("sb13_", "sb14_"))),
            ("bond_only / fric_only not exactly one", bool(s.get("bond_only")) == bool(s.get("fric_only"))),
            ("bond_only without intact_job", bool(s.get("bond_only")) and not s.get("intact_job")),
            ("fric_only with intact_job", bool(s.get("fric_only")) and "intact_job" in s),
            ("model != m1", s.get("model") != "m1"),
            ("in an optimisation family", any(ph.in_family(s) for ph in phases))) if cond]
        if why:
            bad.append(f"{k}: {'; '.join(why)}")
    if bad:
        raise SystemExit("D13 spec check failed:\n" + "\n".join("  " + b for b in bad))


def _d13_specs(sel: dict) -> dict:
    import stage_neckopt as SN
    out = {}
    meta = {"kind": "variant", "gate": "segD"}
    for e in sel["bond_kept"] + sel["bond"]:                             # 以前提交的（键原样）+ 新选的
        job, p = e["job_id"], e["phase"]
        k = f"{D13_BOND_PREFIX}{job}"
        if e.get("d13_key", k) != k:
            raise SystemExit(f"D13: kept key {e['d13_key']} does not match its source job {job}")
        out[k] = {**_d13_src(job), **meta, "stage": D13_STAGE["bond"], "tag": _d13_tag(job), "bond_only": True,
                  "intact_job": SN.PHASES[p]["intact_job"], "source_job": job}
    for e in sel["sts"]:
        job = e["job_id"]
        for ln, L in D13_STS.items():
            out[f"D13_sts_{ln}_{job}"] = {**_d13_src(job), **meta, "stage": D13_STAGE["sts"], "tag": f"{_d13_tag(job)}_{ln}", "fric_only": True,
                                          "cfg": {"load": dict(L)}, "load_case": "sit_to_stand", "source_job": job}
    for e in sel["mesh"]:
        job = e["job_id"]
        for h in D13_MESH_H:
            out[f"D13_mesh_h{h:g}_{job}"] = {**_d13_src(job), **meta, "stage": D13_STAGE["mesh"], "tag": f"{_d13_tag(job)}_h{h:g}", "fric_only": True,
                                             "h_int": h, "source_job": job}
    _d13_check(out)
    return out


def _d13_ids() -> dict:
    f = J.RESULTS / "deck_D13_ids.json"
    return json.loads(f.read_text())["jobs"] if f.exists() else {}


def _d13_prior_warnings(old: dict) -> list:
    """以前提交的 D13 作业在队列里的状态：FAILED（同一 spec = 同一 id，重交不会重算）或不在队列里 → 警告。"""
    out = []
    for k, j in sorted(old.items()):
        s_ = J.state(J.QROOT / j)
        if s_ == "FAILED":
            out.append(f"{k}: earlier D13 job {j} is FAILED; resubmitting gives the same id and does not retry it (see its FAILED.json)")
        elif s_ == "MISSING":
            out.append(f"{k}: earlier D13 job {j} (in deck_D13_ids.json) is not in the queue")
    return out


def d13_build(prior: dict | None = None) -> dict:
    """一次调用 = 读一次状态文件 + 选一次：st13 / st14、sel（d13_select）、specs、probs（d13_unfinished，同一份状态）、
    prior_warnings（以前 D13 作业的队列状态）。submit 与 dry run 都只用这一份。"""
    st13, st14 = _d13_state(13), _d13_state(14)
    import stage_neckopt as SN
    for p, st in ((13, st13), (14, st14)):
        if st.get("intact_job") != SN.PHASES[p]["intact_job"]:
            raise SystemExit(f"D13: phase {p} state file intact_job {st.get('intact_job')!r} != PHASES[{p}]['intact_job'] {SN.PHASES[p]['intact_job']!r}")
    prior = dict(prior or {})
    sel = d13_select(st13, st14, prior=prior)
    return {"st13": st13, "st14": st14, "sel": sel, "specs": _d13_specs(sel), "probs": d13_unfinished(st13, st14),
            "prior_warnings": _d13_prior_warnings(prior)}


def d13_specs(prior: dict | None = None) -> dict:
    """批次 D13 的全部 spec：读当前状态文件（J.RESULTS）选设计，源 spec 从 J.QROOT 读；prior 默认 = 现有的 deck_D13_ids.json。"""
    return d13_build(_d13_ids() if prior is None else prior)["specs"]


def specs(batch: str) -> dict:
    out = {}
    if batch == "A":
        for c in A_CODES:
            for mode in ("tied", "contact"):
                out[f"{c}_{mode}"] = {**base_spec(c), "kind": "variant", "stage": "collar_contact", "tag": f"{c}_{mode}",
                                      "bond_only": True, "bond_collar": mode, "deck_code": c}
    elif batch == "B":                                          # 演示重算：保留 odb
        out["intact"] = {"kind": "intact", "h_int": 2.0, "export": "S", "stage": "demo", "tag": "intact", "keep_odb": True}
        for c in B_CODES:
            out[c] = {**base_spec(c), "kind": "variant", "stage": "demo", "tag": c, "bond_collar": "tied", "keep_odb": True, "deck_code": c}
            out[f"{c}_contact"] = {**base_spec(c), "kind": "variant", "stage": "demo", "tag": f"{c}_contact", "bond_only": True,
                                   "bond_collar": "contact", "keep_odb": True, "deck_code": c}
    elif batch == "E":
        for c in E_CODES:
            b = base_spec(c)
            if c in E_COLLAR_W:
                b["design"]["collar_w"] = E_COLLAR_W[c]
            meta = {"kind": "variant", "stage": "collar_rule", "collar_rule": "wrap_fit", "deck_code": c}
            out[c] = {**b, **meta, "tag": c, "bond_collar": "tied"}
            out[f"{c}_contact"] = {**b, **meta, "tag": f"{c}_contact", "bond_only": True, "bond_collar": "contact"}
    elif batch == "BW":                                         # 演示素材按新领规则重做（用户 2026-10-06）：保留 odb
        for c in ("FI", "J1", "R1", "R2", "B2", "LA"):
            b = base_spec(c)
            if c in E_COLLAR_W:
                b["design"]["collar_w"] = E_COLLAR_W[c]
            meta = {"kind": "variant", "stage": "demo_wrap", "collar_rule": "wrap_fit", "keep_odb": True, "deck_code": c}
            out[c] = {**b, **meta, "tag": c, "bond_collar": "tied"}
            out[f"{c}_contact"] = {**b, **meta, "tag": f"{c}_contact", "bond_only": True, "bond_collar": "contact"}
    elif batch == "CW":                                         # 领宽扫描按新领规则重算（无领水平不受规则影响，沿用批次 C）
        for b, code in (("B1", "FI"), ("B2", "B2")):
            base = base_spec(code)
            for w in (2.0, 4.0, 6.0):
                s_ = ofat_level(base, "collar_w", w)
                meta = {"kind": "variant", "stage": f"ofatw_{b.lower()}", "collar_rule": "wrap_fit",
                        "ofat": {"baseline": b, "base_code": code, "factor": "collar_w", "level": w, "rule": "wrap_fit"}}
                out[f"{b}_collar_w_{w}"] = {**s_, **meta, "tag": f"collar_w_{w}", "bond_collar": "tied"}
                out[f"{b}_collar_w_{w}_contact"] = {**s_, **meta, "tag": f"collar_w_{w}_contact", "bond_only": True, "bond_collar": "contact"}
    elif batch == "F":
        wf = {"kind": "variant", "collar_rule": "wrap_fit"}
        for job in F1_FRONT:                                      # F1 前沿复核
            b = spec_of_job(job)
            d = wrap_fit_design(b)
            orig_w = d.pop("collar_w_original", None)
            if not d.get("collar_w"):
                d.pop("collar_w", None); d.pop("collar_t", None)
            meta = {**wf, "stage": "front_wrap", "source_job": job, "collar_w_original": orig_w}
            out[f"F1_{job}"] = {**b, "design": d, **meta, "tag": job.split("_", 1)[1], "bond_collar": "tied"}
            if d.get("collar_w"):
                out[f"F1_{job}_contact"] = {**b, "design": d, **meta, "tag": job.split("_", 1)[1] + "_contact", "bond_only": True, "bond_collar": "contact"}
        hi_ref = {"kind": "intact", "h_int": 2.0, "export": "S", "stage": "load_ref", "tag": "intact_high", "cfg": LOADS["high"]["cfg"]}
        out["F2_intact_high"] = hi_ref
        hi_id = J.job_id({**hi_ref, "created": ""})
        for c in F2_CODES:                                        # F2 载荷稳健性（新领规则）
            b = base_spec(c)
            if c in E_COLLAR_W:
                b["design"]["collar_w"] = E_COLLAR_W[c]
            elif b["design"].get("collar_w"):
                b["design"] = wrap_fit_design(b)
                b["design"].pop("collar_w_original", None)
            if c == "S1B":                                        # S1B 的标准载荷基线在 BW / E 里没有，补一个
                out["F2_S1B_stair"] = {**b, **wf, "stage": "load_wrap", "tag": "S1B_stair", "bond_collar": "tied", "deck_code": c}
            for ln, L in LOADS.items():
                ref = L["intact"] or hi_id
                out[f"F2_{c}_{ln}"] = {**b, **wf, "stage": "load_wrap", "tag": f"{c}_{ln}", "cfg": L["cfg"], "intact_job": ref,
                                       "bond_collar": "tied", "deck_code": c, "load_case": ln}
        base = base_spec("FI")                                    # F3 B1 单因素扫描补齐（新领规则）
        for factor, levels in OFAT["B1"].items():
            if factor in ("base", "collar_w"):
                continue
            for lv in levels:
                s_ = ofat_level(base, factor, lv)
                meta = {**wf, "stage": "ofatw_b1", "ofat": {"baseline": "B1", "base_code": "FI", "factor": factor, "level": lv, "rule": "wrap_fit"}}
                out[f"F3_B1_{factor}_{lv}"] = {**s_, **meta, "tag": f"{factor}_{lv}", "bond_collar": "tied"}
                if factor != "delta":
                    out[f"F3_B1_{factor}_{lv}_contact"] = {**s_, **meta, "tag": f"{factor}_{lv}_contact", "bond_only": True, "bond_collar": "contact"}
    elif batch == "G":
        wf = {"kind": "variant", "collar_rule": "wrap_fit"}
        base = base_spec("FI")
        for key, (rule, m, e) in G1_CASES.items():                # G1 入口偏移诊断（B1 = FI）
            s_ = ofat_level(base, "m", m)
            meta = {"kind": "variant", "stage": "diag_e", "entry_offset": e, **({"collar_rule": rule} if rule else {}),
                    "ofat": {"baseline": "B1", "base_code": "FI", "factor": "m", "level": m, "rule": rule or "current", "entry_offset": e}}
            out[f"G1_{key}"] = {**s_, **meta, "tag": key, "bond_collar": "tied"}

        def wrap_base(c):
            b_ = base_spec(c)
            if c in E_COLLAR_W:
                b_["design"]["collar_w"] = E_COLLAR_W[c]
            elif b_["design"].get("collar_w"):
                b_["design"] = wrap_fit_design(b_)
                b_["design"].pop("collar_w_original", None)
            return b_
        for ln, L in G2_LOADS.items():                           # G2 载荷方向分解
            ref = {"kind": "intact", "h_int": 2.0, "export": "S", "stage": "load_ref", "tag": f"intact_{ln}", "cfg": {"load": L}}
            out[f"G2_intact_{ln}"] = ref
            ref_id = J.job_id({**ref, "created": ""})
            for c in G2_CODES:
                out[f"G2_{c}_{ln}"] = {**wrap_base(c), **wf, "stage": "load_dir", "tag": f"{c}_{ln}", "cfg": {"load": L}, "intact_job": ref_id,
                                       "bond_collar": "tied", "deck_code": c, "load_case": ln}
        for c in G3_CODES:                                       # G3 重新划网格的噪声
            for dl in G3_JITTER:
                b_ = wrap_base(c)
                b_["design"]["L"] = float(b_["design"]["L"]) + dl
                out[f"G3_{c}_L{dl:+.3f}"] = {**b_, **wf, "stage": "remesh_noise", "tag": f"{c}_L{dl:+.3f}", "bond_collar": "tied", "deck_code": c,
                                            "jitter": {"L": dl}}
    elif batch == "U":                                           # 用户的外部柄设计（import_stem.py；用户 2026-10-08："把 Part3-1 放在当前骨中计算一遍"）
        import import_stem as IS
        for name in IS.PARTS:
            p = IS.PARTS[name]
            base = {**CURRENT, "h_cut": 25.0, "import_stem": name, "import_e": 0.0}
            fm_ = J.femur_for({**base, "design": p["design"]})
            d = {**p["design"], "alpha": round(IS.neck_angle_deg(fm_), 4)}
            meta = {"kind": "variant", "stage": "user_part", "deck_code": name}
            out[f"U_{name}"] = {**base, **meta, "design": d, "tag": name, "bond_collar": "tied"}
            out[f"U_{name}_contact"] = {**base, **meta, "design": d, "tag": f"{name}_contact", "bond_only": True, "bond_collar": "contact"}
    elif batch == "P9D":
        for key, job in P9D_SOURCES.items():
            src = json.loads((J.QROOT / job / "spec.json").read_text())
            if not (J.QROOT / job / "DONE").exists():
                raise SystemExit(f"P9D source {job} is not DONE")
            s_ = {k: v for k, v in src.items() if k not in ("created", "stage", "tag", "kind", "bond_only")}
            out[f"P9D_{key}"] = {**s_, "kind": "variant", "stage": "delta05", "tag": key, "delta": P9D_DELTA, "source_job": job}
    elif batch == "SB":
        out["SB_intact_h2"] = dict(SB_INTACT)
        out.update(_sb_smoke(bonded=False))
    elif batch == "SBd":                                         # 2026-10-24 01:35 诊断：3406 冒烟微动 398–522 µm（CT 同类 9 µm），分离材料 / 股骨 / 柄长截骨
        base = _sb_smoke(bonded=False)["SB_smoke_f_h16"]
        base = {k: v for k, v in base.items() if k not in ("stage", "tag")}
        ct = {k: v for k, v in base.items() if k not in ("femur_id", "neck_axis")}
        meta = {"kind": "variant", "gate": "diag3406"}
        out["SBd_3406_E400_h16"] = {**base, **meta, "stage": "sbdiag", "tag": "E400_h16", "E_canc": 400.0}
        out["SBd_CT_L35_h16"] = {**ct, **meta, "stage": "mgdiag", "tag": "ct_L35_h16"}
        out["SBd_CT_L35_h25"] = {**ct, **meta, "stage": "mgdiag", "tag": "ct_L35_h25", "h_cut": 25.0}
    elif batch == "V3406":                                       # 2026-10-24 50 h 计划段 A 尾部（审查意见）：3406 上的网格噪声与起始 / 默认设计参照
        # stage "v3406"（不是 "sb*"：不被阶段 11 / 12 收编或热启动；也不是 "ref" / "neck*"），kind variant，全部 fric_only
        base = _sb_smoke(bonded=False)["SB_smoke_f_h16"]
        base = {k: v for k, v in base.items() if k not in ("stage", "tag")}
        meta = {"kind": "variant", "stage": "v3406", "gate": "p11_reference"}
        for h_int in (1.94, 2.06):
            out[f"V3406_noise_smoke_h16_h{h_int:g}"] = {**base, **meta, "tag": f"noise_smoke_h16_hint{h_int:g}", "h_int": h_int}
        e2a = json.loads((J.QROOT / "neck9_init_e2a68dea" / "spec.json").read_text())["design"]
        for h in (16.0, 25.0):
            out[f"V3406_e2a_h{h:g}"] = {**base, **meta, "design": dict(e2a), "h_cut": h, "tag": f"e2a_h{h:g}", "source_job": "neck9_init_e2a68dea"}
    elif batch == "SBdelta":                                     # 2026-10-24 03:25：3406 上 δ 0.025 的初始设计全部松动（微动 0.8–2.5 mm、转动 2.6–8.3°）→ 过盈量敏感性
        base = _sb_smoke(bonded=False)["SB_smoke_f_h16"]
        base = {k: v for k, v in base.items() if k not in ("stage", "tag")}
        meta = {"kind": "variant", "stage": "v3406", "gate": "delta_sweep"}
        for dl in (0.05, 0.10, 0.20):
            out[f"SBdelta_smoke_h16_d{dl:g}"] = {**base, **meta, "tag": f"delta_smoke_h16_d{dl:g}", "delta": dl}
        src = json.loads((J.QROOT / "sb11_init_07cbf783" / "spec.json").read_text())
        s2 = {k: v for k, v in src.items() if k not in ("stage", "tag", "created", "kind", "bond_only", "intact_job")}
        s2["fric_only"] = True
        out["SBdelta_init07cb_d0.1"] = {**s2, **meta, "tag": "delta_init07cb_d0.1", "delta": 0.10, "source_job": "sb11_init_07cbf783"}
    elif batch == "SBdx":                                        # 2026-10-24 11:05：段 A 30 个设计 δ 0.025 全部 > 150 µm → 8 个设计 × δ 0.10 / 0.20，看排序是否随 δ 保持
        st = json.loads((J.RESULTS / "neckopt_p11.json").read_text())
        ok = sorted([r for r in st["records"] if r.get("ok") and r.get("round") == 0], key=lambda r: r.get("f1_body_p95_um") or r.get("f1_p95_um") or 1e9)
        pick = [ok[i] for i in sorted({0, 1, 2, 7, 14, 21, len(ok) - 1}) if i < len(ok)]
        best_area = max(ok, key=lambda r: r.get("contact_area_load2_mm2") or 0)
        if best_area not in pick:
            pick.append(best_area)
        meta = {"kind": "variant", "stage": "v3406", "gate": "delta_x_design"}
        for r in pick:
            src = json.loads((J.QROOT / r["job_id"] / "spec.json").read_text())
            s2 = {k: v for k, v in src.items() if k not in ("stage", "tag", "created", "kind", "bond_only", "intact_job")}
            s2["fric_only"] = True
            short = r["job_id"].split("_")[2]
            for dl in (0.10, 0.20):
                out[f"SBdx_{short}_d{dl:g}"] = {**s2, **meta, "tag": f"dx_{short}_d{dl:g}", "delta": dl, "source_job": r["job_id"]}
    elif batch == "D13":                                         # 2026-10-25 50 h 计划段 D：阶段 13 / 14 跑完后的前沿核查（选设计见 d13_select）
        out.update(d13_specs())
    elif batch == "SBb":                                         # 参照填进 PHASES[11]["intact_job"] 之后
        out.update({k: v for k, v in _sb_smoke(bonded=True).items() if k.endswith("_h20")})
    elif batch == "MI":
        for h in MI_H:
            out[f"MI_h{h:g}"] = {"kind": "intact", "h_int": h, "export": "S", "stage": "mg_ref", "tag": f"intact_h{h:g}"}
    elif batch in ("M", "M14"):
        for key, job in RS6.items():
            base = {**_m_src(job), "kind": "variant", "source_job": job, "gate": "method"}
            if batch == "M":
                if key in M_A3:
                    for h in (1.94, 2.06):
                        out[f"M_A3_{key}_h{h:g}"] = {**base, "stage": "mg_remesh", "tag": f"{key}_h{h:g}", "h_int": h, "intact_job": _mi_ref(h)}
                out[f"M_C3slip_{key}"] = {**base, "stage": "mg_slip", "tag": f"{key}_tol1e-4", "slip_tol": 1e-4}
                out[f"M_C3coarse_{key}"] = {**base, "stage": "mg_coarse", "tag": f"{key}_h2.5", "h_int": 2.5, "intact_job": _mi_ref(2.5)}
            else:                                                 # M14 最后提交：页面文件未移出 D: 时只开 2 槽
                out[f"M14_{key}"] = {**base, "stage": "mg_fine", "tag": f"{key}_h1.4", "h_int": 1.4, "slip_tol": M_SLIP14, "intact_job": M_REF14}
    elif batch == "C":
        for b, tab in OFAT.items():
            base = base_spec(tab["base"])
            for factor, levels in tab.items():
                if factor == "base":
                    continue
                for lv in levels:
                    s = ofat_level(base, factor, lv)
                    key = f"{b}_{factor}_{lv}"
                    meta = {"kind": "variant", "stage": f"ofat_{b.lower()}", "ofat": {"baseline": b, "base_code": tab["base"], "factor": factor, "level": lv}}
                    out[key] = {**s, **meta, "tag": f"{factor}_{lv}", "bond_collar": "tied"}
                    if factor != "delta":                        # 过盈只进摩擦模型；接触领的粘接模型与基线相同
                        out[f"{key}_contact"] = {**s, **meta, "tag": f"{factor}_{lv}_contact", "bond_only": True, "bond_collar": "contact"}
    return out


VARIANT_IGNORE = ("created", "stage", "tag", "kind", "gate", "source_job")   # dry run 的"变体"列不比这些键


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


def _variant_keys(s: dict) -> str:
    """没有源作业时的"变体"列：与优化作业不同的那几个键。"""
    parts = [k for k in ("bond_only", "fric_only") if s.get(k)]
    if s.get("cfg"):
        parts.append("cfg " + json.dumps(s["cfg"], sort_keys=True))
    parts += [f"{k} {s[k]:g}" for k in ("h_int", "delta", "E_canc", "h_cut") if isinstance(s.get(k), (int, float))]
    if s.get("intact_job"):
        parts.append(f"intact_job {s['intact_job']}")
    return ", ".join(parts)


def _variant_of(s: dict) -> str:
    """dry run 的"变体"列 = 与源作业 spec.json 的差别（键 旧 -> 新；absent = 没有这个键；嵌套键写成 cfg.load.resultant_N），
    不比 created / stage / tag / kind / gate / source_job。没有 source_job 的作业（参照、冒烟……）列出变体键（_variant_keys）。"""
    src = s.get("source_job")
    if not src:
        return _variant_keys(s)
    f = J.QROOT / src / "spec.json"
    if not f.exists():
        return f"(source spec.json of {src} not found; variant keys) {_variant_keys(s)}"
    a = _flat({k: v for k, v in json.loads(f.read_text()).items() if k not in VARIANT_IGNORE})
    b = _flat({k: v for k, v in s.items() if k not in VARIANT_IGNORE})
    parts = []
    for k in sorted(set(a) | set(b)):
        if k not in b:
            parts.append(f"{k} {_fmt(a[k])} -> absent")
        elif k not in a:
            parts.append(f"{k} absent -> {_fmt(b[k])}")
        elif a[k] != b[k]:
            parts.append(f"{k} {_fmt(a[k])} -> {_fmt(b[k])}")
    return ", ".join(parts) or "(same as the source spec)"


def _d13_summary(sel: dict) -> str:
    """一行选择摘要（dry run 与真提交都打印）。"""
    def ids(es):
        return ", ".join(e["job_id"] for e in es) or "-"
    sts = " / ".join(f"{e['role']} {e['job_id']}" for e in sel["sts"])
    return (f"D13 selection: F13 {len(sel['F13'])}, F14 {len(sel['F14'])}, {sel['n_designs']} distinct designs; already bonded {len(sel['covered'])}; "
            f"kept from deck_D13_ids.json {len(sel['bond_kept'])}, stale bond keys {len(sel['bond_stale'])}; new bond_only {len(sel['bond'])} "
            f"(cap {sel['bond_cap']} - {sel['n_prior_bond']} earlier = {sel['bond_slots']} slots); dropped by the cap {len(sel['bond_left_out'])} "
            f"[{ids(sel['bond_left_out'])}]; sit-to-stand {sts}; mesh {ids(sel['mesh'])}")


def _d13_report(d13: dict) -> None:
    sel, probs = d13["sel"], d13["probs"]

    def num(v, fmt):
        return "None" if v is None else format(v, fmt)

    def line(e):
        d13k = f"  D13 {','.join(e['d13_keys'])}" if e.get("d13_keys") else ""
        return (f"    {e['job_id']:<24} rot {num(e['rot_deg'], '.4f'):>7} deg  area {num(e['area_mm2'], '.0f'):>5} mm2  "
                f"bone {num(e['bone_mm3'], '.0f'):>6} mm3  {'+'.join(e['fronts']) or '-':<7}  bonded jobs {','.join(e['bonded_jobs']) or '-'}{d13k}")
    if probs:
        print(f"WARNING: the phase 13 / 14 arms have not finished (submit would refuse without --allow-unfinished; {D13_QUEUE_NOTE}):")
        for p in probs:
            print("  " + p)
    for w in sel["warnings"] + d13["prior_warnings"]:
        print("WARNING: " + w)
    print(f"F13 = phase-13 2-objective non-dominated set ({len(sel['F13'])}), by rotation:")
    for e in sel["F13"]:
        print(line(e))
    print(f"F14 = phase-14 3-objective non-dominated set incl. its frozen warm-start rows ({len(sel['F14'])}), by bone removal:")
    for e in sel["F14"]:
        print(line(e))
    print(f"{sel['n_designs']} distinct front designs; already bonded (a bonded ok record with sed_chg_pct and vm_p99; no new job): {len(sel['covered'])}")
    for e in sel["covered"]:
        print(line(e))
    print(f"covered by an earlier D13 submission (key kept, same id, no new job; counted against the cap): {len(sel['bond_kept'])}")
    for e in sel["bond_kept"]:
        print(line(e))
    print(f"stale D13 bond keys (design no longer on F13 / F14; the job stays; counted against the cap): {len(sel['bond_stale'])}")
    for e in sel["bond_stale"]:
        print(line(e))
    rule = ("every uncovered front design fits" if not sel["bond_left_out"] else
            f"F13 first, then {D13_BOND_ROT_SLOTS} F14 by rotation, then farthest point in normalised (log10 rotation, bone removal)")
    print(f"bond_only picks ({len(sel['bond'])}; cap {sel['bond_cap']} - {sel['n_prior_bond']} earlier = {sel['bond_slots']} slots; {rule}):")
    for e in sel["bond"]:
        print(line(e))
    print(f"dropped by the cap ({len(sel['bond_left_out'])}):")
    for e in sel["bond_left_out"]:
        print(line(e))
    print(f"sit-to-stand: {len(sel['sts'])} contrasting designs x {list(D13_STS)}:")
    for e in sel["sts"]:
        print(line(e) + f"  ({e['role']}: {e['rule']})")
    print(f"mesh noise: {len(sel['mesh'])} designs (min rotation; F14 median bone removal) x h_int {list(D13_MESH_H)}:")
    for e in sel["mesh"]:
        print(line(e))
    print(_d13_summary(sel))


def dry_run(batch: str, sp: dict, old: dict, clash: dict, d13: dict | None = None, reselect: bool = False) -> None:
    """只打印：键、源作业、变体、stage、tag、预期 id、该 id 在队列里的状态、ids 文件里是否已有。不写任何文件。
    D13：报告与作业表来自同一个 d13_build（同一份状态、同一个选择）。"""
    print(f"dry run: batch {batch}; nothing written (no job directories, no deck_{batch}_ids.json)")
    print(f"queue {J.QROOT}; results {J.RESULTS}; code_hash {J.code_hash()}")
    if d13 is not None:
        st13, st14 = d13["st13"], d13["st14"]
        print(f"state files: phase 13 updated {st13.get('updated')} ({len(st13['records'])} records, budget {st13.get('budget')}), "
              f"phase 14 updated {st14.get('updated')} ({len(st14['records'])} records + {len(st14.get('warm_start_ids') or [])} warm, "
              f"budget {st14.get('budget')})")
        _d13_report(d13)
    rows = []
    for k, v in sp.items():
        jid = J.job_id({**v, "created": ""})
        q = J.state(J.QROOT / jid)
        q = "absent" if q == "MISSING" else q                    # 还不在队列里（提交后才有作业目录）
        rows.append({"key": k, "source_job": v.get("source_job"), "variant": _variant_of(v), "kind": v.get("kind"), "stage": v.get("stage"),
                     "tag": v.get("tag"), "expected_id": jid, "queue": q, "in_ids_file": k in old})
    print(f"jobs ({len(rows)}): key | source job | variant (vs the source spec.json) | stage | tag | expected id | queue state | in ids file")
    for r in rows:
        print(f"  {r['key']} | {r['source_job']} | {r['variant']} | {r['stage']} | {r['tag']} | {r['expected_id']} | {r['queue']} | {r['in_ids_file']}")
    if clash:
        print("CLASH (submit would refuse): spec changed for existing keys:\n" + "\n".join(f"  {k}: {a_} -> {b_}" for k, (a_, b_) in clash.items()))
    new_keys, stale = sorted(set(sp) - set(old)), sorted(set(old) - set(sp))
    if stale:
        print(f"stale keys in deck_{batch}_ids.json (this selection no longer produces them; kept on submit): {stale}")
    if batch == "D13" and old and new_keys:
        print(f"the selection has {len(new_keys)} keys that deck_D13_ids.json does not: a real submit "
              + ("would submit them (--reselect)" if reselect else "would refuse without --reselect") + f": {new_keys}")
    print("DRY-RUN-JSON")
    print(json.dumps({"batch": batch, "n_jobs": len(rows), "jobs": rows, "clash": {k: list(v) for k, v in clash.items()},
                      "new_keys": new_keys if old else [], "stale_keys": stale}, indent=1))


def _d13_gate(d13: dict, sp: dict, old: dict, allow_unfinished: bool, reselect: bool) -> None:
    """真提交前（与 dry run 同一个选择）：打印警告与一行摘要；两臂没跑完 → 拒绝（--allow-unfinished 放行）；
    新选择里有 ids 文件没有的键 → 列出新键与过时键并拒绝（--reselect 放行）。过时键总是打印。"""
    for w in d13["sel"]["warnings"] + d13["prior_warnings"]:
        print("WARNING: " + w, flush=True)
    print(_d13_summary(d13["sel"]), flush=True)
    probs = d13["probs"]
    if probs and not allow_unfinished:
        raise SystemExit("D13: the phase 13 / 14 arms have not finished; nothing submitted (look with --dry-run; override with --allow-unfinished, "
                         f"but {D13_QUEUE_NOTE}):\n" + "\n".join("  " + p for p in probs))
    if probs:
        print(f"D13: submitting although the arms have not finished (--allow-unfinished); {D13_QUEUE_NOTE}:\n"
              + "\n".join("  " + p for p in probs), flush=True)
    new_keys, stale = sorted(set(sp) - set(old)), sorted(set(old) - set(sp))
    if stale:
        print(f"D13: {len(stale)} stale keys in deck_D13_ids.json (not in this selection; they and their jobs stay): {stale}", flush=True)
    if old and new_keys:
        msg = f"D13: the selection differs from deck_D13_ids.json: {len(new_keys)} new keys {new_keys}; {len(stale)} stale keys"
        if not reselect:
            raise SystemExit(msg + "\nnothing submitted; submit again with --reselect to add the new keys (stale keys and their jobs stay)")
        print(msg + "\n--reselect: submitting the new keys", flush=True)


def submit(batch: str, dry: bool = False, allow_unfinished: bool = False, reselect: bool = False) -> None:
    f = J.RESULTS / f"deck_{batch}_ids.json"
    old = json.loads(f.read_text())["jobs"] if f.exists() else {}
    d13 = d13_build(prior=old) if batch == "D13" else None       # D13：一次调用只读一次状态文件、只选一次
    sp = d13["specs"] if d13 is not None else specs(batch)
    clash = {k: (old[k], J.job_id({**v, "created": ""})) for k, v in sp.items() if k in old and old[k] != J.job_id({**v, "created": ""})}
    if dry:
        dry_run(batch, sp, old, clash, d13=d13, reselect=reselect)
        return
    if d13 is not None:                                          # 两臂跑完才提交（前沿要用最终状态）；选择变了要 --reselect
        _d13_gate(d13, sp, old, allow_unfinished, reselect)
    if clash:                                                    # 2026-10-06 批次 F：改了建规格的代码后重交，覆盖了已解作业的键
        raise SystemExit("spec changed for existing keys (job id would change); not resubmitting:\n"
                         + "\n".join(f"  {k}: {a_} -> {b_}" for k, (a_, b_) in clash.items()))
    ids = {**old, **{k: J.submit(v) for k, v in sp.items()}}
    f.write_text(json.dumps({"jobs": ids, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    print(json.dumps(ids, indent=1))


def status(batch: str) -> None:
    ids = json.loads((J.RESULTS / f"deck_{batch}_ids.json").read_text())["jobs"]
    st = {}
    for k, j in ids.items():
        s = J.state(J.QROOT / j)
        st.setdefault(s, []).append(k)
        if s == "FAILED":
            fl = json.loads((J.QROOT / j / "FAILED.json").read_text())
            print("FAILED", k, j, fl.get("level"), (fl.get("reason") or "")[:240].replace("\n", " | "))
    print(json.dumps({k: len(v) for k, v in st.items()}), json.dumps({k: v for k, v in st.items() if k not in ("DONE", "FAILED")}))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status"])
    ap.add_argument("batch", choices=["A", "B", "C", "E", "BW", "CW", "F", "G", "P9D", "U", "MI", "M", "M14", "SB", "SBb", "SBd", "V3406", "SBdelta", "SBdx",
                                      "D13"])
    ap.add_argument("--dry-run", action="store_true",
                    help="submit only: print the job list (key, source job, variant vs the source spec, stage, tag, expected id) and write nothing")
    ap.add_argument("--allow-unfinished", action="store_true",
                    help="submit D13 only: submit although the phase 13 / 14 arms have not finished (pending jobs, records < budget). "
                         "Caution: " + D13_QUEUE_NOTE)
    ap.add_argument("--reselect", action="store_true",
                    help="submit D13 only: submit although the selection has keys that results/deck_D13_ids.json does not "
                         "(the new keys are submitted; stale keys and their jobs stay)")
    ap.add_argument("--root", help="submit --dry-run only: read <root>/queue and <root>/results instead of ~/mobo_toy_v2 (a local copy of the Linux state)")
    a = ap.parse_args()
    if a.root:
        if not (a.cmd == "submit" and a.dry_run):
            ap.error("--root is only for submit --dry-run (a dry run against a local copy of the queue / results)")
        J.QROOT, J.RESULTS = pathlib.Path(a.root) / "queue", pathlib.Path(a.root) / "results"
    if a.cmd == "status" and (a.dry_run or a.allow_unfinished or a.reselect):
        ap.error("--dry-run / --allow-unfinished / --reselect are submit options")
    if (a.allow_unfinished or a.reselect) and a.batch != "D13":
        ap.error("--allow-unfinished / --reselect are only for batch D13")
    if a.cmd == "submit":
        submit(a.batch, dry=a.dry_run, allow_unfinished=a.allow_unfinished, reselect=a.reselect)
    else:
        status(a.batch)
