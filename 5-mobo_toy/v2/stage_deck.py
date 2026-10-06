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
    ap.add_argument("batch", choices=["A", "B", "C", "E", "BW", "CW", "F"])
    a = ap.parse_args()
    {"submit": submit, "status": status}[a.cmd](a.batch)
