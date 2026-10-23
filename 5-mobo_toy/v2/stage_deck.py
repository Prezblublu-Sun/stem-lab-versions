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


def submit(batch: str) -> None:
    f = J.RESULTS / f"deck_{batch}_ids.json"
    old = json.loads(f.read_text())["jobs"] if f.exists() else {}
    sp = specs(batch)
    clash = {k: (old[k], J.job_id({**v, "created": ""})) for k, v in sp.items() if k in old and old[k] != J.job_id({**v, "created": ""})}
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
    ap.add_argument("batch", choices=["A", "B", "C", "E", "BW", "CW", "F", "G", "P9D", "U", "MI", "M", "M14", "SB", "SBb"])
    a = ap.parse_args()
    {"submit": submit, "status": status}[a.cmd](a.batch)
