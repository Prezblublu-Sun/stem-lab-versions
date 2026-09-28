"""把 V2A 的远程 FE 流水线包装成 mobo.run 可用的 Problem（在 Linux 上跑）。

目标（最小化）：y1 = log10(P95 微动 µm)；y2 = Gruen 7 区 SED 相对完整股骨的偏离 |ΔSED|（%）= |1 − SED_植入/SED_完整|·100；
约束 c = vm_p99 − 440 MPa ≤ 0。
y2 于 2026-09-28 由用户改定：参考集 64 个设计中多数让 Gruen 7 区 SED 高于完整股骨（下降率中位 −18%），
v1 的"最小化下降率"会把优化推向近端过载；改为偏离最小，遮挡与过载都受罚。FE 结果不变，只改目标的计算。
候选池：按种子打乱的 11 维 Sobol 序列，逐点在真实股骨上模板化，只保留可行者（能放进去、尖端 ≥ 12 mm²、
肩部 ≥ 假体颈截面），保持 Sobol 顺序；带磁盘缓存。FE 失败（L1–L5）记 ok = False，不进 GP，也不再被选。
评估 = 把设计写进队列，等本机 worker 求解、serve 后处理完成（stage_v2a.wait_for）。
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sys
from multiprocessing import Pool

import numpy as np
from scipy.stats import qmc

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402

POOLS = J.RESULTS / "pools"
VM_LIMIT = 440.0
_FM = {}


def _feasible(u) -> tuple[bool, float]:
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    st = G.Stem3D(**G.from_unit(u))
    r = G.template(st, _FM["fm"])
    ok = bool(r["fit"] and r["A0"] >= math.pi * 7.0 ** 2)
    return ok, float(r.get("A0", math.nan))


def gated_pool(n: int, seed: int, workers: int = 10) -> np.ndarray:
    POOLS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((J.code_hash() + f"{n}_{seed}").encode()).hexdigest()[:8]
    f = POOLS / f"pool_n{n}_s{seed}_{key}.npy"
    if f.exists():
        return np.load(f)
    U = qmc.Sobol(len(G.VARS), scramble=True, seed=10_000 + seed).random(n)
    with Pool(workers) as p:
        res = p.map(_feasible, list(U), chunksize=32)
    keep = np.array([r[0] for r in res])
    P = U[keep]
    np.save(f, P)
    (POOLS / f"{f.stem}.json").write_text(json.dumps({"n": n, "seed": seed, "feasible": int(keep.sum()),
                                                      "rate": float(keep.mean())}))
    return P


def objectives(r: dict | None) -> tuple[list[float], float, bool]:
    if r is None or "failed" in r or not all(k in r for k in ("f1_p95_um", "f2_g7_loss_pct", "vm_p99")):
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(r["f1_p95_um"], 1e-3)), abs(r["f2_g7_loss_pct"])]
    return y, r["vm_p99"] - VM_LIMIT, all(np.isfinite(y))


class V2AProblem:
    n_obj, n_con, d = 2, 1, len(G.VARS)

    def __init__(self, ref_point, stage: str, h_int: float, n_pool: int = 8192):
        self.ref_point = np.asarray(ref_point, float)
        self.stage, self.h_int, self.n_pool = stage, h_int, n_pool
        self.name = "V2A real femur"
        self.rows: list[dict] = []

    def pool(self, n, seed):
        return gated_pool(n, seed)

    def evaluate(self, X, seed=0, round=0, method=""):
        import stage_v2a as S
        specs = [S.design_spec(G.from_unit(x), self.stage, f"{method}_s{seed}_r{round}", h_int=self.h_int) for x in X]
        ids = [J.submit(s) for s in specs]
        res = S.wait_for(ids)
        Y, C, ok = [], [], []
        for j in ids:
            y, c, o = objectives(res[j])
            Y.append(y); C.append([c]); ok.append(o)
            self.rows.append({"job_id": j, "seed": seed, "round": round, "method": method, "ok": o})
        return np.array(Y, float), np.array(C, float), np.array(ok, bool)
