"""S4 参考扫描：每型按打乱 Sobol 序列逐个尝试，直到 n 个设计通过几何门；通过者全部跑 FE，得参考前沿。

python reference_sweep.py --dorr B --n 256 [--E 300] [--campaign S4_ref]

* 几何门失败的尝试也记入 runs.csv（L1/L2 行，不跑 FE），所以 runs.csv 行数 = 尝试数（R4-A2）。
* 对照组（松质骨同为 300 MPa）用与该型完全相同的尝试序列，便于成对比较。
* 目标：f1 = log10(P95 微动 µm)，f2 = Gruen 7 SED 下降率（%），均最小化；约束 vm_p99 ≤ 440 MPa。
"""
from __future__ import annotations

import argparse

import numpy as np
from scipy.stats import qmc

import evaluate as EV
import femur2d as F
import stem2d as S

SWEEP_SEED = 4242


def attempts(dorr: str, n_pass: int, seed: int = SWEEP_SEED, batch: int = 1024) -> list[dict]:
    """按 Sobol 顺序返回尝试过的设计（含门失败者），直到 n_pass 个通过为止。"""
    sob = qmc.Sobol(5, scramble=True, seed=seed)
    out, n_ok = [], 0
    while n_ok < n_pass:
        for u in sob.random(batch):
            d = S.to_physical(u)
            ok = S.gate(S.make(dorr, d))["pass"]
            out.append({"design": d, "u": u, "gate_pass": ok})
            n_ok += ok
            if n_ok >= n_pass:
                break
    return out


def objectives(row: dict) -> tuple[np.ndarray, float, bool]:
    """(y = [log10 f1, f2], 约束值 vm_p99 − 440, 是否 FE 成功)。"""
    ok = row.get("status") == "OK"
    if not ok:
        return np.array([np.nan, np.nan]), np.nan, False
    f1 = EV.as_float(row, "f1_p95_um")
    y = np.array([np.log10(max(f1, 1e-6)), EV.as_float(row, "f2_g7_loss_pct")])
    return y, EV.as_float(row, "vm_p99") - F.CFG["qoi"]["stem_vm_limit"], True


def run(dorr: str, n: int, E: float | None = None, campaign: str = "S4_ref", seed: int = SWEEP_SEED) -> list[dict]:
    att = attempts(dorr, n, seed)
    items = [{"dorr": dorr, "design": a["design"], "E_canc": E, "note": f"S4 sweep #{i}"} for i, a in enumerate(att)]
    return EV.evaluate(items, campaign=campaign, provenance="sampled")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dorr", required=True)
    ap.add_argument("--n", type=int, default=F.CFG["bo"]["reference_n"])
    ap.add_argument("--E", type=float, default=None)
    ap.add_argument("--campaign", default="S4_ref")
    a = ap.parse_args()
    rows = run(a.dorr, a.n, a.E, a.campaign)
    ok = sum(r["status"] == "OK" for r in rows)
    print(f"{a.dorr}: {len(rows)} attempts, {ok} FE OK")
