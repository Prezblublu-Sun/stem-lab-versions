"""V3：聚焦"短柄、少截骨"的提法（用户 2026-09-28 14:00），在 Linux 上跑。

目标（最小化）
    y1 = log10(界面滑移增量 P95, µm)                      稳定性（FE）
    y2 = 骨量损失 = 截掉的颈部骨 + 锉掉的髓腔骨（mm³）       纯几何：resected(h_cut) + 柄体积
约束（≤ 0，合成为一条归一化的最大违反量）
    Gruen 7 |ΔSED| ≤ 30 %；柄 von Mises P99 ≤ 440 MPa
9 个设计变量（其余固定：ρ_tip 0.3、q 1.5；前后两半共用 n 与 τ，前后不对称由 γ_ap 与 τ 表达）
    L 20–70、h_cut 25–45（截骨面距头心，25 = 头颈交界）、α 5–40°、m −0.25…2 mm、λ、γ_ml、γ_ap、n、τ
热启动：全部已解设计映射到 9 维（h_cut = 25，n = (n_a + n_p)/2，τ = (τ_a + τ_p)/2；ρ_tip、q 的差异视为噪声）。

    python v2/stage_v3.py bo --seed 0 [--rounds 10]     → results/v3_bo_s<seed>.json
    python v2/stage_v3.py dataset                         → 打印热启动集概况
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

SPACE = {"L": (20.0, 70.0), "h_cut": (25.0, 45.0), "alpha": (5.0, 40.0), "m": (-0.25, 2.0), "lam": (1.0, 2.2),
         "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n": (2.0, 6.0), "tau": (-0.30, 0.30)}
VARS9 = list(SPACE)
FIXED = {"rho_tip": 0.3, "q": 1.5}
SED_LIMIT, VM_LIMIT = 30.0, 440.0
MIN_A0 = math.pi * 7.0 ** 2
_FM = {}


def from_unit9(u) -> tuple[dict, float]:
    p = {k: SPACE[k][0] + float(x) * (SPACE[k][1] - SPACE[k][0]) for k, x in zip(VARS9, u)}
    d = {"L": p["L"], "rho_tip": FIXED["rho_tip"], "q": FIXED["q"], "lam": p["lam"], "g_ml": p["g_ml"], "g_ap": p["g_ap"],
         "n_a": p["n"], "n_p": p["n"], "tau_a": p["tau"], "tau_p": p["tau"], "alpha": p["alpha"], "m": p["m"]}
    return d, p["h_cut"]


def to_unit9(d: dict, h_cut: float) -> np.ndarray:
    p = {"L": d["L"], "h_cut": h_cut, "alpha": d["alpha"], "m": d.get("m", G.M_LEGACY), "lam": d["lam"], "g_ml": d["g_ml"],
         "g_ap": d["g_ap"], "n": 0.5 * (d["n_a"] + d["n_p"]), "tau": 0.5 * (d["tau_a"] + d["tau_p"])}
    return np.array([(p[k] - SPACE[k][0]) / (SPACE[k][1] - SPACE[k][0]) for k in VARS9])


def objectives(r: dict | None) -> tuple[list[float], float, bool]:
    if not r or "failed" in r or "f1_p95_um" not in r:
        return [math.nan, math.nan], math.nan, False
    bl = r.get("bone_loss") or {}
    loss = bl.get("total_mm3")
    if loss is None:                                             # 旧作业：h_cut = 25 → 截骨 0，只有锉骨
        loss = (r.get("templating") or {}).get("volume")
    if loss is None:
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(r["f1_p95_um"], 1e-3)), float(loss)]
    c = max((abs(r["f2_g7_loss_pct"]) - SED_LIMIT) / SED_LIMIT, (r["vm_p99"] - VM_LIMIT) / VM_LIMIT)
    return y, float(c), all(np.isfinite(y))


def dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """全部已解设计（生产网格、标准变体、去重）映射到 9 维。"""
    seen, X, Y, C, ids = set(), [], [], [], []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design" or spec.get("h_int") != S.H_PROD:
            continue
        if spec.get("delta") is not None or spec.get("mu") is not None or spec.get("torque", True) is False:
            continue
        dsg = G.design_of_spec(spec)
        h = float(spec.get("h_cut", 25.0))
        key = json.dumps({**dsg, "h_cut": h}, sort_keys=True)
        if key in seen:
            continue
        r = J.result(d.name)
        y, c, ok = objectives(r)
        if not ok:
            continue
        seen.add(key)
        X.append(to_unit9(dsg, h)); Y.append(y); C.append([c]); ids.append(d.name)
    return np.array(X), np.array(Y), np.array(C), ids


def _feasible9(u) -> bool:
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    d, h = from_unit9(u)
    fm = _FM["fm"].with_cut(h)
    r = G.template(G.Stem3D(**d), fm)
    return bool(r["fit"] and r["A0"] >= MIN_A0)


def gated_pool(n: int = 8192, seed: int = 0, workers: int = 10) -> np.ndarray:
    from scipy.stats import qmc
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((J.code_hash() + json.dumps(SPACE, sort_keys=True) + f"{n}_{seed}").encode()).hexdigest()[:8]
    f = J.RESULTS / "pools" / f"v3pool_n{n}_s{seed}_{key}.npy"
    if f.exists():
        return np.load(f)
    U = qmc.Sobol(len(VARS9), scramble=True, seed=30_000 + seed).random(n)
    with Pool(workers) as p:
        keep = np.array(p.map(_feasible9, list(U), chunksize=32))
    f.parent.mkdir(exist_ok=True)
    np.save(f, U[keep])
    (f.with_suffix(".json")).write_text(json.dumps({"n": n, "seed": seed, "feasible": int(keep.sum()), "rate": float(keep.mean())}))
    return U[keep]


def evaluate(X9, seed, rnd):
    specs, ids = [], []
    for x in X9:
        d, h = from_unit9(x)
        specs.append(S.design_spec(d, "v3", f"s{seed}_r{rnd}", margin=d["m"], h_cut=h))
    ids = [J.submit(s) for s in specs]
    res = S.wait_for(ids)
    out = [objectives(res[j]) for j in ids]
    return (np.array([o[0] for o in out], float), np.array([[o[1]] for o in out], float), np.array([o[2] for o in out], bool), ids)


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0]
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def bo(seed: int, n_rounds: int = 10, q: int = 4) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset()
    refp = ref_point(Y0, C0)
    pool = gated_pool(8192, seed)
    used = np.zeros(len(pool), bool)
    recs, timing = [], []
    print(f"[v3 s{seed}] warm start {len(X0)} designs ({int((C0[:, 0] <= 0).sum())} feasible), pool {len(pool)}, "
          f"ref (log f1, bone loss) = ({refp[0]:.3f}, {refp[1]:.0f})", flush=True)
    for rnd in range(1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        model = mobo.fit_models(X, Y, C)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, refp, pool[free], q, 2, 1, (30_000 + seed) * 1000 + rnd)
        idx = free[pick]; used[idx] = True
        timing.append(time.perf_counter() - t0)
        Yn, Cn, okn, ids = evaluate(pool[idx], seed, rnd)
        for x, y, c, ok, j in zip(pool[idx], Yn, Cn, okn, ids):
            d, h = from_unit9(x)
            recs.append({"x": x.tolist(), "y": [float(v) for v in y], "c": [float(v) for v in c], "ok": bool(ok), "round": rnd,
                         "job_id": j, "L": d["L"], "h_cut": h, "m": d["m"], "alpha": d["alpha"]})
        ys = np.vstack([Y0[C0[:, 0] <= 0]] + [np.array(r["y"])[None] for r in recs if r["ok"] and r["c"][0] <= 0])
        print(f"[v3 s{seed}] round {rnd}: +{int(okn.sum())}/{q} ok; picked L={[round(r['L']) for r in recs[-q:]]} "
              f"h_cut={[round(r['h_cut']) for r in recs[-q:]]} m={[round(r['m'], 2) for r in recs[-q:]]}; "
              f"HV(all feasible) = {mobo.hypervolume(ys, refp):.4g}; acq {timing[-1]:.1f} s", flush=True)
        out = {"seed": seed, "space": SPACE, "fixed": FIXED, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
               "warm_start_n": int(len(X0)), "warm_start_ids": ids0, "ref_point": refp.tolist(), "pool_size": int(len(pool)),
               "n_rounds": n_rounds, "q": q, "records": recs, "acq_s": timing, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        (J.RESULTS / f"v3_bo_s{seed}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["bo", "dataset", "pool"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "dataset":
        X, Y, C, ids = dataset()
        feas = C[:, 0] <= 0
        print(json.dumps({"n": int(len(X)), "feasible_SED_and_stress": int(feas.sum()),
                          "log_f1_range": [float(Y[:, 0].min()), float(Y[:, 0].max())],
                          "bone_loss_mm3_range": [float(Y[:, 1].min()), float(Y[:, 1].max())],
                          "ref_point": ref_point(Y, C).tolist()}, indent=1))
    elif a.cmd == "pool":
        P = gated_pool(8192, a.seed)
        print("pool", P.shape)
    else:
        r = bo(a.seed, a.rounds)
        print(json.dumps({k: v for k, v in r.items() if k not in ("records", "warm_start_ids")}, indent=1, default=float))
