"""把 FE 流水线包装成 mobo.run 可用的 Problem（S5）。

目标（最小化）：y1 = log10(P95 微动 µm)，y2 = Gruen 7 SED 下降率（%）；约束 c = vm_p99 − 440 MPa ≤ 0。
候选池：按种子打乱的 Sobol 20,000 点，只保留过几何门者（保持 Sobol 顺序）。
FE 失败（L3–L5）记为 ok = False，不进 GP，也不再被选。
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
from scipy.stats import qmc

import evaluate as EV
import femur2d as F
import stem2d as S
from reference_sweep import objectives

ROOT = EV.ROOT
POOL_DIR = ROOT / "results" / "pools"


def gated_pool(dorr: str, n: int, seed: int) -> np.ndarray:
    """打乱 Sobol n 点中过几何门者（单位立方体坐标），带磁盘缓存。"""
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    f = POOL_DIR / f"pool_{dorr}_n{n}_s{seed}_{EV._cfg_hash()}.npy"
    if f.exists():
        return np.load(f)
    U = qmc.Sobol(5, scramble=True, seed=10_000 + seed).random(n)
    keep = np.array([S.gate(S.make(dorr, S.to_physical(u)))["pass"] for u in U])
    P = U[keep]
    np.save(f, P)
    return P


class FEProblem:
    n_obj, n_con, d = 2, 1, 5

    def __init__(self, dorr: str, ref_point: np.ndarray, E_canc: float | None = None, campaign: str = "S5",
                 n_pool: int = 20000):
        self.dorr, self.E, self.campaign, self.n_pool = dorr, E_canc, campaign, n_pool
        self.ref_point = np.asarray(ref_point, float)
        self.name = f"FE Dorr {dorr}"
        self.rows: list[dict] = []

    def pool(self, n, seed):
        return gated_pool(self.dorr, n, seed)

    def evaluate(self, X, seed=0, round=0, method=""):
        items = [{"dorr": self.dorr, "design": S.to_physical(x), "E_canc": self.E, "seed": seed, "round": round,
                  "note": f"{method}"} for x in X]
        rows = EV.evaluate(items, campaign=f"{self.campaign}_{method}", provenance="fitted" if method == "qnehvi" else "sampled",
                           verbose=False)
        Y, C, ok = [], [], []
        for r in rows:
            y, c, o = objectives(r)
            Y.append(y); C.append([c]); ok.append(o)
            self.rows.append({"design_id": r["design_id"], "cache_key": r.get("cache_key"), "seed": seed, "round": round,
                              "method": method, "status": r["status"]})
        return np.array(Y), np.array(C), np.array(ok)


def noise_sd() -> list[float]:
    """由 R2 噪声底换算的观测噪声标准差：[log10 f1, f2 (百分点), vm (MPa)]。"""
    f = ROOT / "results" / "noise_floor.json"
    if not f.exists():
        return [1e-3, 1e-2, 1e-1]
    nf = json.loads(f.read_text())
    return [max(float(nf["noise_rel_f1"]) / np.log(10), 1e-4), max(float(nf["noise_abs_f2"]), 1e-3), 0.1]
