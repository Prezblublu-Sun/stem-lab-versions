"""V3 敏感性补跑（用户 2026-09-28 18:15 批准，在 Linux 上跑）：微动绝对值偏低的两个嫌疑因素，各改一个再跑同一批设计，
看排序是否保持。

    设计：稳定性–骨量损失前沿上的全部设计 + V3 定向评估里可行且在"V3 内部前沿"上的设计（不足 4 个则按微动补齐）
    变体：E_canc 200 MPa（默认 400；需要同模量的完整股骨参照，先提交）；δ 0.05 mm（默认 0.10）
    输出：results/v3_sens.json —— 每个设计三种条件下的 f1 / |ΔSED| / vM，以及各变体对基线的 Spearman 秩相关

    python v2/stage_v3sens.py run
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402
import stage_v3 as V3  # noqa: E402

VARIANTS = {"Ecanc200": {"E_canc": 200.0}, "delta005": {"delta": 0.05}}
N_V3 = 4


def pick_designs() -> list[dict]:
    import mobo
    import report_v3 as RV
    rows = RV.collect()
    front = [r for r in rows if r["feasible"] and r["front"]]
    v3 = [r for r in rows if r["feasible"] and r["source"] == "v3"]
    Y = np.array([[r["log_f1"], r["bone_loss_mm3"]] for r in v3])
    inner = [r for r, m in zip(v3, mobo.pareto_mask(Y)) if m] if len(v3) else []
    inner = sorted(inner, key=lambda r: r["f1_um"])[:N_V3]
    if len(inner) < N_V3:
        rest = sorted([r for r in v3 if r not in inner], key=lambda r: r["f1_um"])
        inner += rest[:N_V3 - len(inner)]
    out, seen = [], set()
    for r in front + inner:
        if r["job_id"] not in seen:
            seen.add(r["job_id"]); out.append(r)
    return out


def variant_spec(base_job: str, name: str, variant: dict) -> dict:
    """同一设计、同一网格、同一余量与截骨高度，只换变体；stage/tag 换成敏感性阶段。"""
    spec = json.loads((J.QROOT / base_job / "spec.json").read_text())
    core = {k: v for k, v in spec.items() if k not in ("stage", "tag", "created")}
    return {**core, "stage": "v3sens", "tag": f"{name}_{base_job[-8:]}", **variant}


def run() -> dict:
    from scipy.stats import spearmanr
    designs = pick_designs()
    print(f"[v3sens] {len(designs)} designs: " + ", ".join(f"{r['job_id']} ({r['source']}, L {r['L']:.0f}, f1 {r['f1_um']:.1f})"
                                                         for r in designs), flush=True)
    ids = {"intact": J.submit(S.intact_spec(S.H_PROD, E_canc=VARIANTS["Ecanc200"]["E_canc"]))}
    for name, var in VARIANTS.items():
        for r in designs:
            ids[f"{name}:{r['job_id']}"] = J.submit(variant_spec(r["job_id"], name, var))
    print(f"[v3sens] submitted {len(ids)} jobs (incl. E_canc-200 intact reference)", flush=True)
    res = S.wait_for(list(ids.values()), poll=60.0)
    out = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "variants": VARIANTS, "intact_job": ids["intact"],
           "designs": [], "rank_correlation": {}}
    for r in designs:
        row = {"job_id": r["job_id"], "source": r["source"], "L": r["L"], "h_cut": r["h_cut"], "m": r["m"], "alpha": r["alpha"],
               "front": r["front"], "base": {"f1_um": r["f1_um"], "abs_dsed_pct": r["abs_dsed_pct"], "vm_p99": r["vm_p99"]}}
        for name in VARIANTS:
            j = ids[f"{name}:{r['job_id']}"]
            rr = res[j]
            if rr and "f1_p95_um" in rr:
                row[name] = {"job_id": j, "f1_um": rr["f1_p95_um"], "abs_dsed_pct": abs(rr["f2_g7_loss_pct"]), "vm_p99": rr["vm_p99"]}
            else:
                row[name] = {"job_id": j, "failed": (rr or {}).get("failed")}
        out["designs"].append(row)
    for name in VARIANTS:
        pairs = [(d["base"]["f1_um"], d[name]["f1_um"]) for d in out["designs"] if "f1_um" in d[name]]
        if len(pairs) >= 3:
            a = np.array(pairs)
            out["rank_correlation"][name] = {"n": len(pairs), "spearman_f1": float(spearmanr(a[:, 0], a[:, 1])[0]),
                                             "median_ratio_f1": float(np.median(a[:, 1] / a[:, 0]))}
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    (J.RESULTS / "v3_sens.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k != "designs"}, indent=1, default=float), flush=True)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "pick"])
    a = ap.parse_args()
    if a.cmd == "pick":
        for r in pick_designs():
            print(r["job_id"], r["source"], round(r["L"]), round(r["h_cut"]), round(r["m"], 2), round(r["f1_um"], 1), r["front"])
    else:
        run()
