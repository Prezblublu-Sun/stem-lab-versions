"""导师汇报的补算作业（用户 2026-10-05；清单 research-log/neck_implant_2026-10-02/deck_plan/补算实验清单_2026-10-05.md）。
全部 kind = variant，不进任何优化数据集；现行生产设置（M1、δ 0.025、μ 0.3、爬楼 2391 N + 扭矩、2.0 mm、平端、统一截骨面）。

    python v2/stage_deck.py submit A|B|C       → results/deck_<批次>_ids.json（可重复提交，已有的作业复用）
    python v2/stage_deck.py status A|B|C
批次
    A  领只受压：7 个设计 × 粘接模型两种领（tied 共节点 / contact 只受压），只解粘接模型（bond_only）
    B  演示重算：完整股骨参照 + FI、FI-0、J1、R1、R2、LA、B2，摩擦模型 + 粘接模型（tied），另各一个 contact 粘接模型；保留 odb
    C  单因素扫描：B1 = FI、B2 = neck5_r10，按清单水平表，每个水平摩擦 + tied 粘接，另一个 contact 粘接（bond_only）
"""
from __future__ import annotations

import json
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
           "R2": "neck3_a45_639d489d"}
A_CODES = ("FI", "J1", "B2", "S1B", "LA", "R1", "R2")
B_CODES = ("FI", "FI0", "J1", "R1", "R2", "LA", "B2")
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
    ap.add_argument("batch", choices=["A", "B", "C"])
    a = ap.parse_args()
    {"submit": submit, "status": status}[a.cmd](a.batch)
