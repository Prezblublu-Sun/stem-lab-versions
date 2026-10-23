"""颈部柄的两阶段优化（用户 2026-10-02 13:20 的方案；Linux 上跑，本机只求解）。

阶段 1（术式相关的基本形状要素，其余默认：椭圆 λ 1.3、皮质余量 −0.25、平端）：柄长 L、插入角 α、领宽 collar_w、截骨深度 h_cut —— 4 个变量。
阶段 2（围绕阶段 1 选定的参考设置）：截面形状 λ、γ_ml、γ_ap、n_a、n_p、τ_a、τ_p + 皮质余量 m（= 粗细）+ 锥度 ρ_tip、q —— 10 个变量；
    柄长、插入角、领宽、截骨深度取 --ref 作业的值。（用户 2026-10-02 15:50：余量移到第二轮；应力屏蔽两轮都只作约束。）
全程不变：领厚 2.5 mm、尖端平端（cap_h 1.5 mm）；锥度在阶段 1 固定（ρ_tip 0.5、q 1.0）、阶段 2 放开、M1 界面模型（过盈 0.025、slip_tol 2.5e-4、
    网格 2.0）、上楼载荷含扭转、四项指标。之后的多孔 / 变模量优化在此之外。

目标（最小化）
    y1 = log10(植入物–骨界面可恢复微动 P95, µm)：柄身 + 领面一起算（post_m1 的 f1_all_p95_um；无领时 = 柄身值）。
         领面也是界面，只算柄身会让领没有任何代价（审查 2026-10-02 15:00 第 3 条）。
    y2 = 骨量损失 = 截骨 + 锉骨（mm³）。确定的几何量：候选池建池时按模板化精确算出，代理模型不拟合它
         （BoTorch 确定性目标通道），只拟合 y1 与约束（审查第 5 条）。
约束（≤ 0，合成一条归一化违反量）
    柄 von Mises P99 ≤ 440 MPa；
    股骨距屏蔽指数 ssi = 1 − 植入 / 完整 的应变能密度均值（%），resorption 的"固定解剖区 G7、只算皮质、设计截骨面以下同一组采样点"
    （正 = 屏蔽，负 = 过载）。形式由 --sed 定：abs（用户 2026-10-02 14:20 定）|ssi| ≤ 30 %；one-sided 只限 ssi ≤ +30 %；none 不限。
    不再用 post_m1 的 f2_g7_loss_pct：它皮质 + 松质混算，且完整股骨对照固定按 25 mm 截骨取区（审查第 1 条）。
代理：高斯过程（输入 = 本阶段变量，归一化）；候选池 Sobol 8192 过模板化；qLogNEHVI，每轮 q 个；超体积参考点在初始批之后固定。
热启动：只用同一几何族（椭圆 λ 1.3、ρ 0.5、q 1、平端、新截骨面）的已解作业；旧作业不混入（--warm legacy 可包含）。

阶段 11 的几处改动（2026-10-23；计算计划_2026-10-24 §2.2，实验设计与效率_终稿 §6.3 的"20 % 参照"规则；PHASES[11] 只是占位，未启动）
    * 约束形式可由阶段定义给出（PHASES[p]["sed"]；CLI --sed 仍可覆盖）：阶段 11 为 "none"，不再有 |ΔSED| 约束。
    * bond_every = 5：每提交 5 个设计，第 5 个带粘接模型（SED、柄 vM 只记录不约束），其余 fric_only（规格键，见 jobs.py：只解摩擦模型）。
      计数器 n_submitted 持久在阶段状态文件 results/neckopt_p<phase>.json 里，续跑接着数；每条 pending / record 记 bonded。
    * objectives()：fric_only 记录没有 vm_p99，不再判不可行——vM 项跳过（c_vm = −1）；sed "none" 时 c_sed = −1；有 vm_p99 的记录行为不变。
      fric_only 记录在 sed abs / one-sided 的阶段仍判 ok=False（没有 SED 可查），所以 fric_only 只配 sed "none" 的阶段。
    * 数据集规则（in_family）：fric_only 不改摩擦模型，不在 MODEL_KEYS 里，in_family 不排除它；能否进数据集由 objectives 决定——
      sed "none" 的阶段（11 起）接受 fric_only 记录（阶段 11 自己的 fric_only 设计因此进自己的记录 / 数据集），sed abs / one-sided 的
      旧阶段因缺 SED 判 ok=False 而自然排除。femur_id 与 margin_check 则必须与阶段一致（不同股骨、不同余量检查 = 不同族）。
    * femur_id（None = 现在的 CT 股骨）与 margin_check（"sparse" 默认 | "dense"，collar_rule.py）进 spec、in_family 与候选池缓存键；
      3406 接入后把 PHASES[11]["femur_id"] 改为 "sawbone3406"（jobs.femur_for 按 femur_id 分派，侦察 S3/S7，尚未做）。
    * 截骨深度从头心下 16 mm 起搜索（用户 2026-10-23 最终定："那就从16mm开始搜索"）：PHASES[11] 的 h_cut 16–32。随之两个阶段字段
      ref_cut_mm（骨量损失的截骨参照，阶段 11 为 16；默认 25）与 a_bounds_max（肩部面积二分上限，阶段 11 为 2000；默认 None = 哈希值 900）：
      spec_of 写进 spec（jobs.prep 按它们算 bone_loss、在模板化期间换上限）、in_family 要求一致、候选池键含之；候选池 _feasible 与 jobs.prep
      共用 jobs.a_bounds_cap（只在模板化调用期间换上限、之后恢复）与同一 resected_volume(ref_cut_mm) 口径，两边一致。

    python v2/stage_neckopt.py pool --phase 1
    python v2/stage_neckopt.py bo --phase 1 --init 16 --rounds 12 --q 4 --sed abs    → results/neckopt_p1.json（每轮覆盖，可续跑）
    python v2/stage_neckopt.py bo --phase 2 --ref <job_id> ...                        → results/neckopt_p2.json
    python v2/stage_neckopt.py status --phase 1
    python v2/stage_neckopt.py selftest        （不提交作业：合成数据跑一次 确定性目标 + GP + 采集）
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
import time
from multiprocessing import Pool

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402

PHASES = {
    # 柄长 20–60（用户 15:05）：> 45 mm 只有小插入角放得进，所以 α 下限 15°；截骨深度上限 32：更深的无限截骨面会切到大转子（审查第 2 条）
    1: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "collar_w": (0.0, 6.0), "h_cut": (25.0, 32.0)},
        "fixed": {"rho_tip": 0.5, "q": 1.0, "lam": 1.3, **G.ELLIPSE, "m": G.M_LEGACY}},
    2: {"vars": {"lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0), "n_p": (2.0, 6.0),
                 "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30), "m": (-0.25, 2.0),
                 "rho_tip": (0.10, 0.50), "q": (0.5, 3.0)},     # 锥度也进第二轮（用户 2026-10-02 16:00）
        "fixed": {}},                                           # 其余（L、alpha、collar_w、h_cut）来自 --ref
    # 阶段 3（用户 2026-10-03 11:30）：14 个变量一轮联合优化，热启动 = 阶段 1 + 阶段 2 的全部设计（同一几何族），用于和两阶段对比
    3: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "collar_w": (0.0, 6.0), "h_cut": (25.0, 32.0), "m": (-0.25, 2.0),
                 "rho_tip": (0.10, 0.50), "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65),
                 "n_a": (2.0, 6.0), "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
        "fixed": {}},
    # 阶段 5 / 6（用户 2026-10-04 12:00）：按方差分解给出的新分法、从零开始的两阶段测试（不用任何已有结果热启动）。
    # 第一阶段 = 柄长、插入角、皮质余量（三者通过"放得进去"互相牵连，且是两个目标里最重要的）+ 截骨深度（术式变量，用户 12:20 要求保留为变量，
    # 不按已有结果固定在 25：从零开始的测试不应借用已有结果的结论）；
    # 第一阶段里第二阶段变量取先验默认：椭圆 λ 1.3、领 3 mm（0–6 的中点）、锥度 0.5 / 1.0。
    5: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "m": (-0.25, 2.0), "h_cut": (25.0, 32.0)},
        "fixed": {"rho_tip": 0.5, "q": 1.0, "lam": 1.3, **G.ELLIPSE, "collar_w": 3.0}},
    # 第二阶段 = 截面 7 个 + 领宽 + 锥度 2 个（截面不精简）；柄长、插入角、余量、截骨深度取第一阶段的参考设计
    6: {"vars": {"lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0), "n_p": (2.0, 6.0),
                 "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30), "collar_w": (0.0, 6.0), "rho_tip": (0.10, 0.50), "q": (0.5, 3.0)},
        "fixed": {}},
    # 阶段 7（批次 G，2026-10-06 晚）：领的新规则 wrap_fit + 新口径（metric v2）下从零重跑。5 个变量 = 两个目标里最重要的
    # （柄长、插入角、余量、领宽，领宽在新规则下和选号直接取舍）+ 锥度；截骨固定 25（h_cut 扫描：更深只多去骨、微动不降），
    # 截面固定椭圆 λ 1.3（单因素扫描里截面影响最小）。
    7: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "m": (-0.25, 2.0), "collar_w": (0.0, 6.0), "rho_tip": (0.10, 0.50)},
        "fixed": {"q": 1.0, "lam": 1.3, **G.ELLIPSE, "h_cut": 25.0}, "collar_rule": "wrap_fit", "metric": "v2"},
    # 阶段 8（用户 2026-10-07 10:50 同意）：阶段 7 固定了 q、λ，前沿被旧前沿（批次 F1 按新规则复核的 22 个设计，全是 q 1.7–3.0）支配。
    # 这里与阶段 3 相同的 14 个变量全部放开，领规则 wrap_fit + 新口径；热启动 = 阶段 7 的 72 个 + 批次 F1 的 22 个（stage front_wrap，
    # 同为 wrap_fit、生产设置、标准载荷）。
    8: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "collar_w": (0.0, 6.0), "h_cut": (25.0, 32.0), "m": (-0.25, 2.0),
                 "rho_tip": (0.10, 0.50), "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65),
                 "n_a": (2.0, 6.0), "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
        "fixed": {}, "collar_rule": "wrap_fit", "metric": "v2", "warm_stages": ("front_wrap",)},
    # 阶段 9（无领优化，设计见 mechanism_2026-10-07/无领优化设计_2026-10-07.md，2026-10-07 晚拟定、待用户在原会话启动）：
    # 与阶段 8 同一设计空间、同一口径、同一预算，只把领宽固定为 0。目的：(1) 无领能做到的前沿；(2) 领在前沿层面的贡献 = 两条前沿之差；
    # (3) 无领时哪些变量主导（预期是决定柄身压配的 m、号、柄长）。不热启动（已解的真正无领设计只有 4 个），从零开始。
    # 选号（用户 2026-10-07 定，启动前检查后改）：collar_rule = "neck_in_shoulder" —— 假体颈底面（r 7）须整个落在柄截口里，
    # 在满足的入口偏移里取号最大。原设计不设规则时，阶段 9 设计空间里 58 % 的可行设计颈底伸出截口 > 10 mm²（小号柄全部伸出、中位 35 mm²），
    # M1 把伸出部分当普通界面（带过盈），等于一块小领，"无领"就不干净了（deck_data/scripts/collarless_neck_check.py）。
    9: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "h_cut": (25.0, 32.0), "m": (-0.25, 2.0),
                 "rho_tip": (0.10, 0.50), "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65),
                 "n_a": (2.0, 6.0), "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
        "fixed": {"collar_w": 0.0}, "collar_rule": "neck_in_shoulder", "metric": "v2"},
    # 阶段 10（用户 2026-10-10 会议后）：无领；松质骨不能单独承重，柄要靠近皮质、但不直接接触 —— 皮质余量 m ≥ 0.5 mm（下限暂定）；
    # 可以接受受压下沉，但必须避免转动。目标 metric v3：(1) 柄相对骨的刚体转动（首次加载，度）最小；(2) 完全接触面积（LOAD2，mm²）最大。
    # 约束：柄身微动 P95 ≤ 150 µm、柄应力 ≤ 440 MPa、股骨距 |SED 变化| ≤ 30 %。下沉只记录。转动与接触面积由 stability.py 从已有结果算。
    10: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "h_cut": (25.0, 32.0), "m": (0.5, 2.0),
                  "rho_tip": (0.10, 0.50), "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65),
                  "n_a": (2.0, 6.0), "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
         "fixed": {"collar_w": 0.0}, "collar_rule": "neck_in_shoulder", "metric": "v3"},
}
# 阶段 11（2026-10-23，未启动）：= 阶段 10 去掉 SED 约束（sed "none"），metric v3 不变；每提交 5 个设计第 5 个带粘接模型
# （bond_every 5，其余 fric_only：只解摩擦模型，SED / vM 只在那 20 % 上记录、不约束；用户 10-23 决定）；femur_id None = 现在的 CT 股骨，
# 3406 接入后改为 "sawbone3406"。margin_check "dense"（截骨面下每 0.25 mm 一环的严格余量检查；B1 重放：候选池 1750 → 1542，用户 2026-10-24 采纳）。
# 截骨深度（用户 2026-10-23 最终定："那就从16mm开始搜索"）：h_cut 16–32，从头心下 16 mm 起宽搜索（阶段 10 是 25–32；变量顺序不变）。
#   h ≥ 16 时假体头（r 14）整个在截骨面以上，HEADN 耦合半径（14）够不到界面，所以不需要头帽钩子。
#   ref_cut_mm 16：骨量损失的截骨参照（femur_real.resected_volume(ref_cut_mm)：cut ≤ ref 记 0，只数 ref 与 cut 之间的骨；阶段 10 及以前
#     用默认 25 不变）。进 spec（jobs.prep 的 bone_loss 按它算并记 bone_loss.ref_cut_mm）、in_family（参照不同 = 损失口径不同，不混入）、候选池键。
#   a_bounds_max 2000：肩部面积二分上限（geom3d.A_BOUNDS 哈希值 (20, 900)，template 按调用时读取）。浅截骨的截口大：CT 股骨 h 10 时 A0 ≈ 508 mm²
#     （hcut10 扫描），3406 髓腔截面 h25 ≈ 760、h32 ≈ 1370 mm²，上限 900 会判 "canal larger than largest size"。候选池（_feasible）与 jobs.prep
#     用同一个 jobs.a_bounds_cap 只在模板化调用期间把上限换成 (A_BOUNDS[0], 2000)、之后恢复（对所有股骨一样；3406 的 femur_3406.install 不受影响）。
#     进 spec、in_family、候选池键。二分 14 次的几何步长随上限略变（900：0.023 %，2000：0.028 %），同一设计的 A0 第 4 位可与阶段 10 不同。
PHASES[11] = {**PHASES[10], "vars": {**PHASES[10]["vars"], "h_cut": (16.0, 32.0)}, "sed": "none", "bond_every": 5, "femur_id": None, "margin_check": "dense",
              "ref_cut_mm": 16.0, "a_bounds_max": 2000.0}
REF_CUT_DEFAULT = 25.0      # 骨量损失的截骨参照默认值（= femur_real.resected_volume 的 ref_cut_mm 默认；阶段 10 及以前的 spec 不写这个键）
MM_LIMIT = 150.0            # metric v3：柄身微动 P95 上限（µm，骨长入的经典阈值；会议 2026-10-10）
ROT_FLOOR = 1e-3            # metric v3：转动的数值下限（度）
MODEL_KEYS = ("mu", "E_canc", "interference", "lagrange", "cycles", "torque", "h_far", "margin")   # 改模型假设的规格键：带了就不进优化数据集
REF_KEYS = {2: ("L", "alpha", "collar_w", "h_cut"), 6: ("L", "alpha", "m", "h_cut")}     # 第二阶段从参考设计继承的变量
CONST = {"collar_t": G.COLLAR_T, "cap_h": G.CAP_FLAT}
FRIC = {"slip_tol": 2.5e-4, "delta": 0.025}
SED_LIMIT, VM_LIMIT = 30.0, 440.0
MM_FLOOR = 2.0              # metric v2：柄身微动 P95 低于 2 µm 是数值下限（v2/M1_VERIFICATION.md），目标里统一记 2
_FM = {}
_SSI = {}


def out_path(phase: int) -> pathlib.Path:
    return J.RESULTS / f"neckopt_p{phase}.json"


class Phase:
    def __init__(self, phase: int, ref: dict | None = None, sed: str | None = None):
        self.phase, self.space = phase, PHASES[phase]["vars"]
        self.sed = PHASES[phase].get("sed", "abs") if sed is None else sed   # None = 阶段自带的约束形式（阶段 11 起 "none"）；CLI --sed 覆盖
        self.vars = list(self.space)
        self.fixed = dict(PHASES[phase]["fixed"])
        self.rule = PHASES[phase].get("collar_rule")                    # None = 现行领规则；"wrap_fit" 见 collar_rule.py
        self.metric = PHASES[phase].get("metric", "v1")                 # v1 = 整界面微动 + 应力屏蔽 ssi；v2 = 柄身微动（2 µm 下限）+ SED 变化
        self.warm_stages = tuple(PHASES[phase].get("warm_stages", ()))  # 除 neck* 之外允许热启动的阶段名
        self.bond_every = PHASES[phase].get("bond_every")               # 每提交 bond_every 个设计第 bond_every 个带粘接模型，其余 fric_only；None = 全带
        self.femur_id = PHASES[phase].get("femur_id")                   # None = CT 股骨（jobs.femur_for 默认）；进 spec、in_family、候选池键
        self.margin_check = PHASES[phase].get("margin_check", "sparse")  # 余量检查密度（collar_rule.MARGIN_CHECK）；进 spec、in_family、候选池键
        self.ref_cut_mm = float(PHASES[phase].get("ref_cut_mm", REF_CUT_DEFAULT))   # 骨量损失的截骨参照（阶段 11：16；默认 25 不进 spec）
        a_max = PHASES[phase].get("a_bounds_max")                         # 肩部面积二分上限（阶段 11：2000；None = 哈希值 geom3d.A_BOUNDS[1]）
        self.a_bounds_max = None if a_max is None else float(a_max)
        if phase in REF_KEYS:
            if not ref:
                raise ValueError(f"phase {phase} needs --ref <job_id> (the first-stage design whose {REF_KEYS[phase]} are kept)")
            self.fixed.update({k: ref[k] for k in REF_KEYS[phase]})
        self.ref = ref

    # 单位立方体 ↔ 设计
    def design_of(self, u) -> tuple[dict, float]:
        p = {k: self.space[k][0] + float(x) * (self.space[k][1] - self.space[k][0]) for k, x in zip(self.vars, u)}
        v = {**self.fixed, **p}
        d = {k: float(v[k]) for k in ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m")}
        d["cap_h"] = CONST["cap_h"]
        if v.get("collar_w", 0.0) > 1e-6:
            d.update(collar_w=float(v["collar_w"]), collar_t=CONST["collar_t"])
        return d, float(v["h_cut"])

    def to_unit(self, d: dict, h_cut: float) -> np.ndarray:
        v = {**d, "collar_w": d.get("collar_w", 0.0), "m": d.get("m", G.M_LEGACY), "h_cut": h_cut}
        return np.clip(np.array([(v[k] - self.space[k][0]) / (self.space[k][1] - self.space[k][0]) for k in self.vars], float), 0, 1)

    def in_family(self, spec: dict, legacy: bool = False) -> bool:
        d = spec.get("design") or {}
        if spec.get("model") != "m1" or spec.get("h_int") != S.H_PROD or spec.get("slip_tol") != FRIC["slip_tol"] or spec.get("delta") != FRIC["delta"]:
            return False
        if spec.get("collar_rule") != self.rule or spec.get("cfg") or spec.get("entry_offset") is not None:   # 领规则不同、换载荷、固定偏移的不混入
            return False
        if any(spec.get(k) is not None for k in MODEL_KEYS) or spec.get("bond_only"):                       # 改了模型假设的、只解粘接模型的不混入
            return False
        # fric_only 不排除：摩擦模型相同，能否用由 objectives 决定（sed "none" 的阶段接受，abs / one-sided 因缺 SED 判 ok=False）
        if spec.get("femur_id") != self.femur_id or spec.get("margin_check", "sparse") != self.margin_check:   # 不同股骨 / 余量检查 = 不同族
            return False
        # 骨量损失参照与选号上限也要一致（阶段 11：16 / 2000；没写 = 25 / None）：参照不同 = 损失口径不同，上限不同 = 同一设计可能选到不同号
        if abs(float(spec.get("ref_cut_mm", REF_CUT_DEFAULT)) - self.ref_cut_mm) > 1e-9:
            return False
        a_max = spec.get("a_bounds_max")
        if (a_max is None) != (self.a_bounds_max is None) or (a_max is not None and abs(float(a_max) - self.a_bounds_max) > 1e-9):
            return False
        stage = str(spec.get("stage", ""))
        if not legacy and (float(d.get("cap_h", -1.0)) != CONST["cap_h"] or not (stage.startswith("neck") or stage in self.warm_stages)):
            return False
        full = {**d, "h_cut": float(spec.get("h_cut", 25.0)), "collar_w": float(d.get("collar_w", 0.0)), "m": float(d.get("m", G.M_LEGACY))}
        for k, val in self.fixed.items():
            if abs(float(full.get(k, -999.0)) - float(val)) > 1e-6:
                return False
        return all(self.space[k][0] - 1e-9 <= float(full[k]) <= self.space[k][1] + 1e-9 for k in self.vars)

    def spec_of(self, u, tag: str, bonded: bool | None = None) -> dict:
        """bonded None / True：带粘接模型（原样）；False：fric_only（只解摩擦模型，jobs.py）。femur_id、非默认的 margin_check、
        非默认的 ref_cut_mm（阶段 11：16）与设了的 a_bounds_max（阶段 11：2000）一并进 spec；阶段 10 及以前的 spec 逐字不变（作业 id 不变）。"""
        d, h = self.design_of(u)
        extra = {"collar_rule": self.rule} if self.rule else {}
        if self.femur_id:
            extra["femur_id"] = self.femur_id
        if self.margin_check != "sparse":
            extra["margin_check"] = self.margin_check
        if abs(self.ref_cut_mm - REF_CUT_DEFAULT) > 1e-9:
            extra["ref_cut_mm"] = self.ref_cut_mm
        if self.a_bounds_max is not None:
            extra["a_bounds_max"] = self.a_bounds_max
        if bonded is False:
            extra["fric_only"] = True
        return {**S.design_spec(d, f"neck{self.phase}", tag), "model": "m1", "h_cut": h, **FRIC, **extra}

    def template(self, st, fm):
        """候选池用的模板化 = jobs.prep 对本阶段 spec 会做的模板化（同规则、同余量检查密度）。"""
        if self.rule == "wrap_fit":
            import collar_rule as CR
            return CR.template_wrap_fit(st, fm, min_A0=S.MIN_A0, margin_check=self.margin_check)
        if self.rule == "neck_in_shoulder":
            import collar_rule as CR
            return CR.template_neck_in_shoulder(st, fm, min_A0=S.MIN_A0, margin_check=self.margin_check)
        if self.margin_check != "sparse":
            import collar_rule as CR
            return CR.template_base(st, fm, margin_check=self.margin_check)
        return G.template(st, fm)


def next_bonded(state: dict, bond_every: int | None) -> bool:
    """bond_every 计数器（持久在阶段状态文件的 n_submitted 里）：第 bond_every、2·bond_every … 个提交带粘接模型，其余 fric_only。
    bond_every 为 None / 0 时全部带粘接模型（阶段 10 及以前的行为）。"""
    n = int(state.get("n_submitted", 0)) + 1
    state["n_submitted"] = n
    return (not bond_every) or n % int(bond_every) == 0


def _bonded_of(job_id: str) -> bool | None:
    """作业是否带粘接模型（按 spec.json 的 fric_only；没有 spec 时 None）。"""
    p = J.QROOT / job_id / "spec.json"
    if not p.exists():
        return None
    return not json.loads(p.read_text()).get("fric_only")


# ------------------------------------------------------------------------------------------------- 指标
def _calcar(job_id: str) -> tuple[float | None, float | None]:
    """固定解剖区 G7、只算皮质，设计截骨面以下同一组采样点：(屏蔽指数 ssi %，1 − 植入 / 完整 的应力口径；应变能变化 sed_chg %，负 = 屏蔽)。"""
    if job_id in _SSI:
        return _SSI[job_id]
    try:
        import resorption as RS
        rows, _ = RS.design_rows(job_id)
        g7 = next((r for r in rows if r["scheme"] == "fixed" and r["zone"] == "G7" and r["tissue"] == "cortex"), {})
        v = tuple(None if g7.get(k) is None or not np.isfinite(g7[k]) else float(g7[k]) for k in ("ssi_pct", "sed_chg_pct"))
    except Exception as e:                                           # noqa: BLE001
        print(f"[neckopt] calcar {job_id}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        v = (None, None)
    _SSI[job_id] = v
    return v


def calcar_ssi(job_id: str) -> float | None:
    return _calcar(job_id)[0]


def objectives(r: dict | None, sed: str, ssi: float | None, metric: str = "v1", sed_chg: float | None = None) -> tuple[list[float], float, bool]:
    """v1：y1 = log10 整界面微动，股骨距 = ssi（正 = 屏蔽）。v2：y1 = log10 max(柄身微动, 2 µm)，股骨距 = −sed_chg（同样正 = 屏蔽）。
    fric_only 记录（jobs.py，没有粘接模型）：vm_p99 缺失不判不可行，vM 项取 c_vm = −1；SED 同样缺失，所以只有 sed "none"（c_sed = −1）
    时才 ok。有 vm_p99 的记录行为不变（缺 vm_p99 仍判 ok=False）。"""
    if not r or "failed" in r or "f1_p95_um" not in r:
        return [math.nan, math.nan], math.nan, False
    fric_only = bool(r.get("fric_only"))
    if metric == "v3":
        stab = r.get("_stability") or {}
        rot, area, f1, vm = stab.get("rot_first_deg"), stab.get("contact_area_load2_mm2"), r.get("f1_p95_um"), r.get("vm_p99")
        cal = None if sed_chg is None else -float(sed_chg)
        if rot is None or area is None or f1 is None or (vm is None and not fric_only) or (sed != "none" and cal is None):
            return [math.nan, math.nan], math.nan, False
        y = [math.log10(max(float(rot), ROT_FLOOR)), -float(area)]
        c_vm = -1.0 if vm is None else (float(vm) - VM_LIMIT) / VM_LIMIT
        c_sed = {"one-sided": (cal - SED_LIMIT) / SED_LIMIT, "abs": (abs(cal) - SED_LIMIT) / SED_LIMIT, "none": -1.0}[sed] if cal is not None else -1.0
        c = max((float(f1) - MM_LIMIT) / MM_LIMIT, c_vm, c_sed)
        return y, float(c), all(np.isfinite(y))
    if metric == "v2":
        f1 = r.get("f1_p95_um")
        f1 = None if f1 is None else max(float(f1), MM_FLOOR)
        cal = None if sed_chg is None else -float(sed_chg)
    else:
        f1 = r.get("f1_all_p95_um", r.get("f1_p95_um"))
        cal = ssi
    bl = r.get("bone_loss") or {}
    loss = bl.get("total_mm3")
    if loss is None:
        loss = (r.get("templating") or {}).get("volume")
    if f1 is None or loss is None or (r.get("vm_p99") is None and not fric_only) or (sed != "none" and cal is None):
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(float(f1), 1e-3)), float(loss)]
    c_vm = -1.0 if r.get("vm_p99") is None else (r["vm_p99"] - VM_LIMIT) / VM_LIMIT
    c_sed = {"one-sided": (cal - SED_LIMIT) / SED_LIMIT, "abs": (abs(cal) - SED_LIMIT) / SED_LIMIT, "none": -1.0}[sed] if cal is not None else -1.0
    return y, float(max(c_vm, c_sed)), all(np.isfinite(y))


_STAB = {}


def stability_of(job_id: str) -> dict:
    if job_id not in _STAB:
        try:
            import stability as ST
            _STAB[job_id] = ST.stability(J.QROOT / job_id)
        except Exception as e:                                       # noqa: BLE001
            print(f"[neckopt] stability {job_id}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            _STAB[job_id] = {}
    return _STAB[job_id]


def record_of(job_id: str, sed: str, metric: str = "v1") -> dict:
    res = J.result(job_id) or {}
    fric_only = bool(res.get("fric_only"))                                   # 没有粘接模型：不算股骨距（resorption 要 m_bond_csv）
    ssi, sed_chg = _calcar(job_id) if (res and "f1_p95_um" in res and not fric_only) else (None, None)
    stab = stability_of(job_id) if (metric == "v3" and res and "f1_p95_um" in res) else {}
    y, c, ok = objectives({**res, "_stability": stab} if stab else res, sed, ssi, metric, sed_chg)
    extra = {k: stab.get(k) for k in ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_rev_deg", "subsid_first_um",
                                      "subsid_perm_um", "lateral_first_um", "slip_axial_p95_um", "slip_circ_p95_um",
                                      "contact_area_load2_mm2", "contact_frac_load2")} if stab else {}
    bl = (res.get("bone_loss") or {}).get("total_mm3")
    return {"y": [float(v) for v in y], "c": [float(c)], "ok": bool(ok), "metric": metric, "ssi_pct": ssi, "sed_chg_pct": sed_chg,
            "bone_mm3": bl, "fric_only": fric_only, **extra,
            "g7_mixed_pct": res.get("f2_g7_loss_pct"), "vm_p99": res.get("vm_p99"), "f1_all_p95_um": res.get("f1_all_p95_um"),
            "f1_body_p95_um": res.get("f1_p95_um"), "collar_open_frac_load2": res.get("collar_open_frac_load2"),
            "collar_force_share_load2": res.get("collar_force_share_load2"), "A0": (res.get("templating") or {}).get("A0"),
            "entry_offset_e": (res.get("templating") or {}).get("e")}


def _empty(ph: Phase):
    n = len(ph.vars)
    return np.zeros((0, n)), np.zeros((0, 2)), np.zeros((0, 1)), []


def dataset(ph: Phase, legacy: bool = False):
    seen, X, Y, C, ids = set(), [], [], [], []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") not in ("design", "variant") or not ph.in_family(spec, legacy):
            continue
        if spec.get("stage") == f"neck{ph.phase}":                        # 本阶段自己的作业由 records 续跑接管，不作热启动（否则重复计入）
            continue
        dsg = dict(spec["design"])
        h = float(spec.get("h_cut", 25.0))
        key = json.dumps({**dsg, "h_cut": h}, sort_keys=True)
        if key in seen:
            continue
        rec = record_of(d.name, ph.sed, ph.metric)
        if not rec["ok"]:
            continue
        seen.add(key)
        X.append(ph.to_unit(dsg, h)); Y.append(rec["y"]); C.append(rec["c"]); ids.append(d.name)
    n = len(ph.vars)
    return (np.array(X).reshape(-1, n), np.array(Y).reshape(-1, 2), np.array(C).reshape(-1, 1), ids)


# ------------------------------------------------------------------------------------------------- 候选池（含确定的骨量损失）
def _feasible(args):
    u, phase, ref = args
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    ph = Phase(phase, ref)
    d, h = ph.design_of(u)
    fm = _FM["fm"].with_cut(h)
    with J.a_bounds_cap(ph.a_bounds_max):                         # 与 jobs.prep 同一个上限补丁（阶段 11：2000），只在模板化期间生效、之后恢复
        r = ph.template(G.Stem3D(**d), fm)
    ok = bool(r["fit"] and r["A0"] >= S.MIN_A0)
    loss = float(fm.resected_volume(ref_cut_mm=ph.ref_cut_mm) + r["volume"]) if ok else math.nan   # 截骨参照与 prep 的 bone_loss 同口径
    return ok, loss


def pool_key(ph: Phase, n: int, seed: int) -> str:
    """候选池缓存键：代码哈希 + 设计空间 + 固定值 + 常数 + n / seed + 领规则；femur_id、非默认的 margin_check、非默认的 ref_cut_mm、
    设了的 a_bounds_max 另加（默认值不改旧键）。"""
    s = (J.code_hash() + json.dumps(ph.space, sort_keys=True) + json.dumps(ph.fixed, sort_keys=True) + json.dumps(CONST) + f"{n}_{seed}_v2"
         + (f"_{ph.rule}" if ph.rule else "") + (f"_{ph.femur_id}" if ph.femur_id else "")
         + (f"_mc{ph.margin_check}" if ph.margin_check != "sparse" else "")
         + (f"_ref{ph.ref_cut_mm:g}" if abs(ph.ref_cut_mm - REF_CUT_DEFAULT) > 1e-9 else "")
         + (f"_amax{ph.a_bounds_max:g}" if ph.a_bounds_max is not None else ""))
    return hashlib.sha1(s.encode()).hexdigest()[:8]


def gated_pool(ph: Phase, n: int = 8192, seed: int = 0, workers: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """返回 (可行候选的单位坐标, 各自的骨量损失 mm³)。"""
    from scipy.stats import qmc
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    key = pool_key(ph, n, seed)
    f = J.RESULTS / "pools" / f"neckopt_p{ph.phase}_n{n}_s{seed}_{key}.npz"
    if f.exists():
        z = np.load(f)
        return z["U"], z["loss"]
    U = qmc.Sobol(len(ph.vars), scramble=True, seed=50_000 + 100 * ph.phase + seed).random(n)
    with Pool(workers) as p:
        res = p.map(_feasible, [(u, ph.phase, ph.ref) for u in U], chunksize=32)
    keep = np.array([r[0] for r in res])
    loss = np.array([r[1] for r in res], float)
    f.parent.mkdir(exist_ok=True)
    np.savez(f, U=U[keep], loss=loss[keep])
    f.with_suffix(".json").write_text(json.dumps({"phase": ph.phase, "n": n, "seed": seed, "feasible": int(keep.sum()), "rate": float(keep.mean()),
                                                  "space": ph.space, "fixed": ph.fixed, "loss_range_mm3": [float(np.nanmin(loss[keep])), float(np.nanmax(loss[keep]))],
                                                  "ref_cut_mm": ph.ref_cut_mm, "a_bounds_max": ph.a_bounds_max}))
    print(f"[neckopt p{ph.phase}] pool: {int(keep.sum())}/{n} feasible; bone loss {np.nanmin(loss[keep]):.0f}–{np.nanmax(loss[keep]):.0f} mm³", flush=True)
    return U[keep], loss[keep]


def refresh_pool(ph: Phase, centres: np.ndarray, k: int = 64, rad: float = 0.08, workers: int = 6, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """前沿邻域补点：每个中心周围 [x−rad, x+rad]^d 内均匀取 k 个点，过模板化，返回 (可行点, 骨量损失)。离散池的局部加密。"""
    rng = np.random.default_rng(seed)
    U = np.clip(np.vstack([c + rng.uniform(-rad, rad, size=(k, len(ph.vars))) for c in np.atleast_2d(centres)]), 0.0, 1.0)
    with Pool(workers) as p:
        res = p.map(_feasible, [(u, ph.phase, ph.ref) for u in U], chunksize=16)
    keep = np.array([r[0] for r in res]); loss = np.array([r[1] for r in res], float)
    return U[keep], loss[keep]


def lengthscales(model, ph: Phase) -> dict:
    """微动 GP 与约束 GP 的 ARD 长度尺度（归一化输入空间；越短越重要）。"""
    out = {}
    for name, idx in (("micromotion", 0), ("constraint", 2)):
        try:
            gp = model.models[idx]
            ls = gp.covar_module.base_kernel.lengthscale.detach().cpu().numpy().ravel()
            out[name] = {v: float(x) for v, x in zip(ph.vars, ls)}
        except Exception as e:                                       # noqa: BLE001
            out[name] = f"n/a ({type(e).__name__})"
    return out


def det_loss_fn(pool: np.ndarray, loss: np.ndarray):
    """确定性目标：单位坐标 → 骨量损失（最近的候选点；采集只在候选池上离散优化，所以是精确值）。
    用 KD 树做最近邻：NEHVI 把基线点和候选批一起送进来（每批 2048 × ~150 行），原来的 torch.cdist 会物化
    (30 万 × 2.5 万) 的距离矩阵——2026-10-03 13:30 把 Linux 的 31 GB 吃光、整台机僵了 6 小时。离散采集不需要梯度。"""
    import torch
    from scipy.spatial import cKDTree
    tree = cKDTree(np.asarray(pool, float))
    Lt = np.asarray(loss, float)

    def fn(Z):
        Zf = Z.detach().cpu().numpy().reshape(-1, Z.shape[-1])
        _, idx = tree.query(Zf, k=1, workers=1)
        return torch.as_tensor(Lt[idx], dtype=Z.dtype, device=Z.device).reshape(Z.shape[:-1])
    return fn


def evaluate(ph: Phase, U, tag: str, state: dict | None = None):
    """同步版提交；state 给定时按 bond_every 计数器决定每个设计带不带粘接模型（计数器写回 state["n_submitted"]）。"""
    ids = [J.submit(ph.spec_of(u, tag, bonded=(next_bonded(state, ph.bond_every) if state is not None else None))) for u in U]
    S.wait_for(ids)
    return ids


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0] if (C[:, 0] <= 0).any() else Y
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def bo(ph: Phase, n_rounds: int, n_init: int, q: int, seed: int, workers: int, legacy_warm: bool, n_pool: int = 8192,
       refresh_k: int = 0, refresh_rad: float = 0.08, stop_tol: float = 0.0, stop_rounds: int = 4) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm) if legacy_warm is not None else _empty(ph)   # None = 不热启动（从零）
    pool, pool_loss = gated_pool(ph, n=n_pool, seed=seed, workers=workers)
    live = J.RESULTS / f"neckopt_p{ph.phase}_pool_live.npz"           # 含邻域补点的池（续跑时用，保证 pool_idx 不变）
    recs, refp, hv_hist, ls_hist, n_submitted_prev = [], None, [], {}, None
    out = out_path(ph.phase)
    if out.exists():                                                     # 续跑：按当前约束形式从作业结果重算
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs = prev["records"]
            hv_hist, ls_hist, n_submitted_prev = prev.get("hv_hist", []), prev.get("lengthscales", {}), prev.get("n_submitted")
            if live.exists():
                z = np.load(live); pool, pool_loss = z["U"], z["loss"]
    used = np.zeros(len(pool), bool)
    if recs:
            for r in recs:
                used[r["pool_idx"]] = True
                r.update(record_of(r["job_id"], ph.sed, ph.metric))
            refp = np.array(prev["ref_point"]) if prev.get("ref_point") else None
            if prev.get("sed") != ph.sed:  # noqa: SIM102
                print(f"[neckopt p{ph.phase}] constraint form changed {prev.get('sed')} -> {ph.sed}; feasibility recomputed", flush=True)
    state = {"phase": ph.phase, "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
             "ref": ph.ref, "n_init": n_init, "q": q, "n_rounds": n_rounds, "warm_start_n": int(len(X0)), "warm_start_ids": ids0,
             "pool_size": int(len(pool)), "records": recs, "ref_point": None if refp is None else refp.tolist(),
             "hv_hist": hv_hist, "lengthscales": ls_hist, "n_pool": n_pool, "refresh_k": refresh_k, "refresh_rad": refresh_rad,
             "stop_tol": stop_tol, "stop_rounds": stop_rounds, "femur_id": ph.femur_id, "margin_check": ph.margin_check,
             "ref_cut_mm": ph.ref_cut_mm, "a_bounds_max": ph.a_bounds_max,
             "bond_every": ph.bond_every, "n_submitted": int(len(recs) if n_submitted_prev is None else n_submitted_prev)}

    def save():
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(state, indent=1, default=float))

    print(f"[neckopt p{ph.phase}] vars {ph.vars}; warm start {len(X0)} ({int((C0[:, 0] <= 0).sum()) if len(C0) else 0} feasible); "
          f"pool {len(pool)}; existing records {len(recs)}; sed={ph.sed}", flush=True)

    def run_batch(idx, tag, rnd):
        ids = evaluate(ph, pool[idx], tag, state)
        for i, j in zip(idx, ids):
            d, h = ph.design_of(pool[i])
            recs.append({"pool_idx": int(i), "x": pool[i].tolist(), "round": rnd, "job_id": j, "h_cut": h, "bonded": _bonded_of(j),
                         "design": {k: d[k] for k in ph.vars if k in d}, **record_of(j, ph.sed, ph.metric)})
        save()
        return np.array([r["ok"] for r in recs[-len(idx):]])

    def stack():
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        return X, Y, C

    if n_init > 0 and not any(r["round"] == 0 for r in recs):
        idx = np.arange(min(n_init, len(pool)))                           # Sobol 顺序的前 n_init 个 = 准随机初始点
        used[idx] = True
        okn = run_batch(idx, "init", 0)
        print(f"[neckopt p{ph.phase}] init: {int(okn.sum())}/{len(idx)} ok", flush=True)
    det = {1: det_loss_fn(pool, pool_loss)} if ph.metric != "v3" else None
    done_rounds = max([r["round"] for r in recs], default=0)

    def front_rows(X, Y, C):
        f = np.nonzero(C[:, 0] <= 0)[0]
        keep = [i for i in f if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in f)]
        return X[keep]

    for rnd in range(done_rounds + 1, n_rounds + 1):
        t0 = time.perf_counter()
        X, Y, C = stack()
        if refp is None:                                                 # 参考点在热启动 / 初始批之后固定一次，超体积才可跨轮、跨阶段比较
            refp = ref_point(Y, C)
            state["ref_point"] = refp.tolist()
        model = mobo.fit_models(X, Y, C, det=det)
        ls_hist[str(rnd)] = lengthscales(model, ph)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, refp, pool[free], q, 2, 1, (50_000 + ph.phase * 100 + seed) * 1000 + rnd)
        idx = free[pick]
        used[idx] = True
        acq_s = time.perf_counter() - t0
        okn = run_batch(idx, f"r{rnd}", rnd)
        X, Y, C = stack()
        feas = Y[C[:, 0] <= 0]
        hv = float(mobo.hypervolume(feas, refp)) if len(feas) else float("nan")
        hv_hist.append({"round": rnd, "hv": hv, "n_eval": int(len(recs)), "n_ok": int(sum(r["ok"] for r in recs))})
        last = recs[-len(idx):]
        print(f"[neckopt p{ph.phase}] round {rnd}: +{int(okn.sum())}/{len(idx)} ok; "
              f"{[{k: round(v, 2) for k, v in r['design'].items()} | {'h': round(r['h_cut'], 1), 'ssi': None if r['ssi_pct'] is None else round(r['ssi_pct'], 1)} for r in last]}; "
              f"HV {hv:.4g}; acq {acq_s:.0f} s", flush=True)
        if refresh_k > 0:                                               # 前沿邻域补点（离散池的局部加密）
            t1 = time.perf_counter()
            Un, Ln = refresh_pool(ph, front_rows(X, Y, C), k=refresh_k, rad=refresh_rad, workers=workers, seed=seed * 1000 + rnd)
            if len(Un):
                pool, pool_loss = np.vstack([pool, Un]), np.r_[pool_loss, Ln]
                used = np.r_[used, np.zeros(len(Un), bool)]
                det = {1: det_loss_fn(pool, pool_loss)} if ph.metric != "v3" else None
                np.savez(live, U=pool, loss=pool_loss)
            state["pool_size"] = int(len(pool))
            print(f"[neckopt p{ph.phase}] pool refresh: +{len(Un)} feasible around {len(front_rows(X, Y, C))} front points "
                  f"({time.perf_counter() - t1:.0f} s), pool {len(pool)}", flush=True)
        save()
        if stop_tol > 0 and len(hv_hist) > stop_rounds:
            hvs = [h["hv"] for h in hv_hist[-(stop_rounds + 1):]]
            gains = [(b - a) / a for a, b in zip(hvs[:-1], hvs[1:]) if a > 0]
            if gains and max(gains) < stop_tol:
                print(f"[neckopt p{ph.phase}] stop: hypervolume gain < {stop_tol:.1%} for {stop_rounds} rounds", flush=True)
                state["stopped_early"] = rnd
                save()
                break
    return state


def _front_rows(X, Y, C):
    f = np.nonzero(C[:, 0] <= 0)[0]
    keep = [i for i in f if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in f)]
    return X[keep]


def bo_async(ph: Phase, budget: int, inflight: int, seed: int, workers: int, legacy_warm: bool, n_pool: int = 8192,
             refresh_k: int = 0, refresh_rad: float = 0.08, stop_tol: float = 0.0, stop_window: int = 18, n_cand: int = 10000,
             poll: float = 30.0) -> dict:
    """异步版（用户 2026-10-03 21:45：同步版每轮采集 6–7 分钟时求解器空转，4 个设计 3 个槽又拖一个尾巴）：
    求解器里始终保持 inflight 个设计在算；每有一个算完，就用全部已完成结果重拟合代理、选 1 个新点提交（在算的点作 X_pending）。
    与同步版共用记录文件、参考点、候选池，可互相续跑；重启时把本阶段不在记录里的作业收编（已解的进记录，在算的进待定）。
    budget = 本阶段新设计的总数（含已完成的）。停止：最近 stop_window 个完成的超体积改进 < stop_tol，之后只排空不再提交。"""
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm) if legacy_warm is not None else _empty(ph)   # None = 不热启动（从零）
    pool, pool_loss = gated_pool(ph, n=n_pool, seed=seed, workers=workers)
    live = J.RESULTS / f"neckopt_p{ph.phase}_pool_live.npz"
    out = out_path(ph.phase)
    recs, refp, hv_hist, ls_hist, pending, n_submitted_prev = [], None, [], {}, {}, None
    if out.exists():
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs, hv_hist, ls_hist, pending = prev["records"], prev.get("hv_hist", []), prev.get("lengthscales", {}), prev.get("pending", {})
            refp = np.array(prev["ref_point"]) if prev.get("ref_point") else None
            n_submitted_prev = prev.get("n_submitted")
            if live.exists():
                z = np.load(live); pool, pool_loss = z["U"], z["loss"]
    used = np.zeros(len(pool), bool)

    def rec_from(job: str, x, pool_idx, round_):
        d_, h_ = ph.design_of(np.asarray(x, float))
        return {"pool_idx": pool_idx, "x": list(map(float, x)), "round": round_, "job_id": job, "h_cut": h_, "bonded": _bonded_of(job),
                "design": {k: d_[k] for k in ph.vars if k in d_}, **record_of(job, ph.sed, ph.metric)}

    known = set()
    for r in recs:
        known.add(r["job_id"]); r.update(record_of(r["job_id"], ph.sed, ph.metric))
        if r.get("pool_idx") is not None and r["pool_idx"] < len(pool):
            used[r["pool_idx"]] = True
    adopted = 0
    for d in sorted(J.QROOT.glob(f"neck{ph.phase}_*")):                 # 收编本阶段不在记录里的作业
        if d.name in known or not (d / "spec.json").exists():
            continue
        st_ = J.state(d)
        spec = json.loads((d / "spec.json").read_text())
        x = ph.to_unit(spec["design"], float(spec.get("h_cut", 25.0)))
        if st_ in ("DONE", "FAILED"):
            recs.append(rec_from(d.name, x, pending.pop(d.name, {}).get("pool_idx"), -1)); known.add(d.name); adopted += 1
        elif st_ in ("NEW", "READY", "CLAIMED", "SOLVED") and d.name not in pending:
            pending[d.name] = {"pool_idx": None, "x": x.tolist(), "submitted": "adopted"}
    for j in list(pending):                                             # 上次待定里已经算完的
        if J.state(J.QROOT / j) in ("DONE", "FAILED"):
            p_ = pending.pop(j); recs.append(rec_from(j, p_["x"], p_.get("pool_idx"), -1)); known.add(j)
    for p_ in pending.values():
        if p_.get("pool_idx") is not None and p_["pool_idx"] < len(pool):
            used[p_["pool_idx"]] = True
    state = {"phase": ph.phase, "mode": "async", "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT,
             "vm_limit": VM_LIMIT, "ref": ph.ref, "inflight": inflight, "budget": budget, "n_cand": n_cand, "warm_start_n": int(len(X0)),
             "warm_start_ids": ids0, "pool_size": int(len(pool)), "records": recs, "pending": pending,
             "ref_point": None if refp is None else refp.tolist(), "hv_hist": hv_hist, "lengthscales": ls_hist, "n_pool": n_pool,
             "refresh_k": refresh_k, "refresh_rad": refresh_rad, "stop_tol": stop_tol, "stop_window": stop_window,
             "femur_id": ph.femur_id, "margin_check": ph.margin_check, "ref_cut_mm": ph.ref_cut_mm, "a_bounds_max": ph.a_bounds_max,
             "bond_every": ph.bond_every}

    def save():
        state["pending"], state["pool_size"], state["updated"] = pending, int(len(pool)), time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(state, indent=1, default=float))

    def stack():
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        return X, Y, C

    det = {1: det_loss_fn(pool, pool_loss)} if ph.metric != "v3" else None
    rng = np.random.default_rng(seed + 7)
    n_sub = len(recs) + len(pending)
    state["n_submitted"] = int(n_sub if n_submitted_prev is None else n_submitted_prev)   # bond_every 计数器：续跑接着数
    since_refresh, stopped = 0, False
    print(f"[neckopt p{ph.phase} async] warm start {len(X0)}; records {len(recs)} (adopted {adopted}); pending {len(pending)}; pool {len(pool)}; "
          f"budget {budget}; inflight {inflight}; sed={ph.sed}; bond_every={ph.bond_every} (n_submitted {state['n_submitted']})", flush=True)
    save()
    while True:
        while not stopped and len(pending) < inflight and n_sub < budget:               # 1. 补满在算的设计
            t0 = time.perf_counter()
            X, Y, C = stack()
            if refp is None:
                refp = ref_point(Y, C); state["ref_point"] = refp.tolist()
            model = mobo.fit_models(X, Y, C, det=det)
            ls_hist[str(n_sub)] = lengthscales(model, ph)
            free = np.nonzero(~used)[0]
            if len(free) > n_cand:                                                      # 随机子集 + 最近补的点（池尾部）
                cand = np.unique(np.r_[rng.choice(free, size=n_cand, replace=False), free[free >= len(pool) - 2000]])
            else:
                cand = free
            Xp = np.array([p_["x"] for p_ in pending.values()]) if pending else None
            pick = mobo.propose(model, X, refp, pool[cand], 1, 2, 1, (60_000 + ph.phase * 100 + seed) * 1000 + n_sub, X_pending=Xp)
            i = int(cand[pick[0]]); used[i] = True
            bonded = next_bonded(state, ph.bond_every)                                      # 每 bond_every 个提交第 bond_every 个带粘接模型
            job = J.submit(ph.spec_of(pool[i], f"a{n_sub}", bonded=bonded))
            pending[job] = {"pool_idx": i, "x": pool[i].tolist(), "submitted": time.strftime("%Y-%m-%d %H:%M:%S"), "bonded": bonded}
            n_sub += 1
            d_, h_ = ph.design_of(pool[i])
            print(f"[neckopt p{ph.phase} async] submit #{n_sub} {job} ({'bond' if bonded else 'fric_only'}; acq {time.perf_counter() - t0:.0f} s, "
                  f"{len(pending)} in flight, cand {len(cand)}): { {k: round(d_[k], 2) for k in ph.vars if k in d_} | {'h': round(h_, 1)} }", flush=True)
            save()
        if not pending:
            break
        time.sleep(poll)                                                                # 2. 等任一完成
        done_now = [j for j in list(pending) if J.state(J.QROOT / j) in ("DONE", "FAILED")]
        if not done_now:
            continue
        for j in done_now:
            p_ = pending.pop(j)
            recs.append(rec_from(j, p_["x"], p_.get("pool_idx"), len(recs) + 1))
        X, Y, C = stack()
        feas = Y[C[:, 0] <= 0]
        hv = float(mobo.hypervolume(feas, refp)) if len(feas) and refp is not None else float("nan")
        hv_hist.append({"n_done": int(len(recs)), "hv": hv, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        print(f"[neckopt p{ph.phase} async] done {len(recs)} (+{len(done_now)}: {[round(10 ** r['y'][0], 1) if r['ok'] else 'fail' for r in recs[-len(done_now):]]} um), "
              f"ok {sum(r['ok'] for r in recs)}, HV {hv:.4g}, {len(pending)} in flight", flush=True)
        since_refresh += len(done_now)
        if refresh_k > 0 and since_refresh >= 6:                                       # 3. 前沿邻域补点
            t1 = time.perf_counter()
            Un, Ln = refresh_pool(ph, _front_rows(X, Y, C), k=refresh_k, rad=refresh_rad, workers=workers, seed=seed * 1000 + len(recs))
            if len(Un):
                pool, pool_loss = np.vstack([pool, Un]), np.r_[pool_loss, Ln]
                used = np.r_[used, np.zeros(len(Un), bool)]
                det = {1: det_loss_fn(pool, pool_loss)} if ph.metric != "v3" else None
                np.savez(live, U=pool, loss=pool_loss)
            since_refresh = 0
            print(f"[neckopt p{ph.phase} async] pool refresh: +{len(Un)} ({time.perf_counter() - t1:.0f} s), pool {len(pool)}", flush=True)
        if stop_tol > 0 and not stopped and len(hv_hist) > stop_window:                 # 4. 停止判据（按完成数）
            a_, b_ = hv_hist[-stop_window - 1]["hv"], hv_hist[-1]["hv"]
            if a_ > 0 and (b_ - a_) / a_ < stop_tol:
                stopped = True; state["stopped_early"] = int(len(recs))
                print(f"[neckopt p{ph.phase} async] stop: HV gain over the last {stop_window} completions < {stop_tol:.1%}; draining {len(pending)} in flight", flush=True)
        save()
    print(f"[neckopt p{ph.phase} async] finished: {len(recs)} records", flush=True)
    return state


def selftest() -> None:
    """不提交作业：合成数据检查 确定性目标 + 两个 GP + qLogNEHVI 在候选池上能选点。"""
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    rng = np.random.default_rng(0)
    pool = rng.random((500, 5))
    loss = 3000 + 9000 * pool[:, 0] + 2000 * pool[:, 4]
    X = pool[:20]
    Y = np.c_[np.log10(5 + 60 * X[:, 0] * (1 - X[:, 2]) + 5 * rng.random(20)), loss[:20]]
    C = (np.abs(30 * (X[:, 2] - 0.5)) - 30) / 30
    model = mobo.fit_models(X, Y, C[:, None], det={1: det_loss_fn(pool, loss)})
    refp = ref_point(Y, C[:, None])
    pick = mobo.propose(model, X, refp, pool[20:], 4, 2, 1, 123)
    print("selftest picks", pick.tolist(), "loss of picks", [round(float(loss[20:][i])) for i in pick])
    pick1 = mobo.propose(model, X, refp, pool[20:], 1, 2, 1, 124, X_pending=pool[20:][pick])
    print("selftest async pick with 4 pending", pick1.tolist())


def status(phase: int) -> None:
    out = out_path(phase)
    if not out.exists():
        print("no results yet"); return
    st = json.loads(out.read_text())
    recs = st["records"]
    print(json.dumps({k: v for k, v in st.items() if k not in ("records", "warm_start_ids")}, indent=1, default=float))
    ok = [r for r in recs if r["ok"]]
    feas = [r for r in ok if r["c"][0] <= 0]
    print(f"evaluated {len(recs)}, ok {len(ok)}, feasible {len(feas)}")
    for r in sorted(feas, key=lambda r: r["y"][0])[:8]:
        key = "sed_chg_pct" if r.get("metric") in ("v2", "v3") else "ssi_pct"
        cal = f"{key[:3]}    n/a " if r.get(key) is None else f"{key[:3]} {r[key]:+6.1f} %"      # fric_only 记录没有 SED
        if r.get("metric") == "v3":
            print(f"  rot {10 ** r['y'][0]:.4f}°  contact {-r['y'][1]:7.0f} mm²  {cal}  bone {r.get('bone_mm3') or 0:7.0f} mm³  {r['design']}  {r['job_id']}")
        else:
            print(f"  {10 ** r['y'][0]:6.1f} µm  loss {r['y'][1]:7.0f} mm³  {cal}  {r['design']}  h_cut {r['h_cut']:.1f}  {r['job_id']}")


def load_ref(job_id: str) -> dict:
    spec = json.loads((J.QROOT / job_id / "spec.json").read_text())
    d = spec["design"]
    return {"L": d["L"], "alpha": d["alpha"], "collar_w": d.get("collar_w", 0.0), "m": d.get("m", G.M_LEGACY), "h_cut": spec.get("h_cut", 25.0),
            "job_id": job_id}


if __name__ == "__main__":
    import argparse
    try:                                                                 # 内存保险：优化进程最多 24 GB 地址空间，撑爆时死自己而不是拖垮整台机
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (24 << 30, 24 << 30))
    except Exception:                                                    # noqa: BLE001  （Windows 没有 resource）
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dataset", "pool", "bo", "async", "status", "selftest"])
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--ref", default=None, help="phase 2: phase-1 job id whose L, alpha, collar_w, h_cut are kept")
    ap.add_argument("--sed", choices=["one-sided", "abs", "none"], default=None, help="默认取阶段定义的 sed（PHASES[p]['sed']，没有则 abs）")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--init", type=int, default=16)
    ap.add_argument("--q", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--warm", choices=["family", "legacy", "none"], default="family", help="none = 从零开始，不用任何已有结果")
    ap.add_argument("--pool", type=int, default=8192, help="候选池 Sobol 点数（阶段 3 建议 32768）")
    ap.add_argument("--refresh", type=int, default=0, help="每轮在前沿各点邻域补的点数（0 = 不补）")
    ap.add_argument("--refresh-rad", type=float, default=0.08)
    ap.add_argument("--stop-tol", type=float, default=0.0, help="连续 --stop-rounds 轮超体积改进都小于此比例则停（0 = 不停）")
    ap.add_argument("--stop-rounds", type=int, default=4)
    ap.add_argument("--inflight", type=int, default=6, help="async：同时在算的设计数（3 槽 → 6 = 两整波）")
    ap.add_argument("--budget", type=int, default=80, help="async：本阶段新设计总数（含已完成）")
    ap.add_argument("--cand", type=int, default=10000, help="async：每次采集随机取的候选数（池尾最近补的点总是包含）")
    ap.add_argument("--stop-window", type=int, default=18, help="async：停止判据的完成数窗口")
    a = ap.parse_args()
    if a.cmd == "selftest":
        selftest()
        sys.exit(0)
    ref = load_ref(a.ref) if a.ref else None
    ph = Phase(a.phase, ref, a.sed)
    if a.cmd == "dataset":
        X, Y, C, ids = dataset(ph, a.warm == "legacy")
        print(json.dumps({"n": int(len(X)), "feasible": int((C[:, 0] <= 0).sum()) if len(C) else 0, "ids": ids}, indent=1))
    elif a.cmd == "pool":
        U, loss = gated_pool(ph, n=a.pool, seed=a.seed, workers=a.workers)
        print(U.shape, float(np.nanmin(loss)), float(np.nanmax(loss)))
    elif a.cmd == "status":
        status(a.phase)
    elif a.cmd == "async":
        bo_async(ph, a.budget, a.inflight, a.seed, a.workers, (None if a.warm == "none" else a.warm == "legacy"), n_pool=a.pool, refresh_k=a.refresh,
                 refresh_rad=a.refresh_rad, stop_tol=a.stop_tol, stop_window=a.stop_window, n_cand=a.cand)
    else:
        bo(ph, a.rounds, a.init, a.q, a.seed, a.workers, (None if a.warm == "none" else a.warm == "legacy"), n_pool=a.pool, refresh_k=a.refresh,
           refresh_rad=a.refresh_rad, stop_tol=a.stop_tol, stop_rounds=a.stop_rounds)
