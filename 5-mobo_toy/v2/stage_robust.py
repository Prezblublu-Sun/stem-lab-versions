"""B1 稳健优化（用户 2026-10-04 10:40 批准，今晚运行）。Linux 上跑，本机只求解。

问题：A 段验证显示，基准条件（过盈 0.025 mm）下的最优设计在压配几乎丧失（过盈 0.01 mm）时微动放大 3–4 倍，
五个设计的排序 Spearman 只有 0.20。稳健优化把目标 1 改为两档过盈下的较差值：
    y1 = max(log10 f1(δ 0.025), log10 f1(δ 0.01))     整界面可恢复微动 P95
    y2 = 骨量损失 = 截骨 + 锉骨（确定量，与过盈无关）
约束：两档里较差的那个（柄应力 P99 ≤ 440 MPa、股骨距 |ssi| ≤ 30 %），与之前各阶段同一口径（stage_neckopt.record_of）。
变量：与联合优化相同的 14 个；候选池从联合优化的池复制一份（之后的邻域补点只加在自己这份上）。
代理：δ 0.025 微动 GP（全部已解的同族设计）、δ 0.01 微动 GP（已有的 δ 0.01 结果）、约束 GP、确定性骨量；
采集：qLogNEHVI，多输出目标 [min(−y1a, −y1b), −loss]（= 最小化两档里较差的微动），在算的设计作 X_pending。
流程
  I  初始批：已解设计（δ 0.025）可行前沿第一层 + 第二层（最多 --layer2 个），在 δ 0.01 下补算（每个 1 次 FE；
     A 段已算过 δ 0.01 的直接收编）。
  II 异步：每个新设计 2 次 FE（δ 0.025 与 δ 0.01），在算的 FE 数保持 --inflight；预算 --budget 个新设计。
     超体积参考点在初始批之后固定；停止：最近 --stop-window 个完成的超体积改进 < --stop-tol。
数据以队列为准（每次重扫），记录缓存在 results/neckopt_record_cache.json（已完成的作业结果不会再变）。
作业 stage = neck4；δ 0.025 的那一半与联合优化同族，其他阶段也可用作数据。

    python v2/stage_robust.py run --budget 36 --inflight 6
    python v2/stage_robust.py status
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402

DELTAS = (0.025, 0.01)
STAGE = "neck4"
OUT = J.RESULTS / "neckopt_robust.json"
POOL = J.RESULTS / "neckopt_robust_pool.npz"
CACHE_F = J.RESULTS / "neckopt_record_cache.json"
PH = N.Phase(3, None, "abs")
DKEYS = ("L", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "alpha", "m", "collar_w", "cap_h")
_CACHE: dict | None = None


# ------------------------------------------------------------------------------------------------- 数据
def dkey(dsg: dict, h: float) -> str:
    k = {v: round(float(dsg[v]), 6) for v in DKEYS if v in dsg}
    if k.get("collar_w", 0.0) <= 1e-6:
        k.pop("collar_w", None)
    k.setdefault("m", round(float(G.M_LEGACY), 6))
    k["h_cut"] = round(float(h), 6)
    return json.dumps(k, sort_keys=True)


def rec_cached(job: str) -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(CACHE_F.read_text()) if CACHE_F.exists() else {}
    if job not in _CACHE:
        _CACHE[job] = N.record_of(job, "abs")
        _CACHE["_dirty"] = True
    return _CACHE[job]


def flush_cache() -> None:
    if _CACHE is not None and _CACHE.pop("_dirty", False):
        CACHE_F.write_text(json.dumps(_CACHE, default=float))


def scan() -> dict:
    """队列里同一几何族（平端）、同一 FE 设置（M1、网格 2.0、滑移容差 2.5e-4）、过盈 0.025 或 0.01 的已解作业，按设计归并：
    {key: {"x", "design", "h_cut", "a"/"b": record, "a_job"/"b_job"}}（a = δ 0.025，b = δ 0.01）。"""
    out = {}
    for d in sorted(J.QROOT.iterdir()):
        sp = d / "spec.json"
        if not d.is_dir() or not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("model") != "m1" or spec.get("h_int") != S.H_PROD or spec.get("slip_tol") != N.FRIC["slip_tol"]:
            continue
        if spec.get("E_canc") is not None or spec.get("rep") or spec.get("cfg") or spec.get("mu") is not None:
            continue
        stg = str(spec.get("stage", ""))
        if not (stg.startswith("neck") or stg == "verify"):
            continue
        dsg = spec.get("design") or {}
        if float(dsg.get("cap_h", -1.0)) != G.CAP_FLAT:
            continue
        delta = spec.get("delta")
        if delta not in DELTAS:
            continue
        h = float(spec.get("h_cut", 25.0))
        full = {**dsg, "h_cut": h, "collar_w": float(dsg.get("collar_w", 0.0)), "m": float(dsg.get("m", G.M_LEGACY))}
        if not all(PH.space[k][0] - 1e-9 <= float(full[k]) <= PH.space[k][1] + 1e-9 for k in PH.vars):
            continue
        rec = rec_cached(d.name)
        if not rec["ok"]:
            continue
        k = dkey(dsg, h)
        e = out.setdefault(k, {"x": PH.to_unit(dsg, h).tolist(), "design": {v: float(full[v]) for v in PH.vars}, "h_cut": h,
                               "spec_job": d.name})
        slot = "a" if delta == DELTAS[0] else "b"
        if slot not in e:
            e[slot], e[f"{slot}_job"] = rec, d.name
    flush_cache()
    return out


def robust(e: dict) -> tuple[float, float, float]:
    """(两档里较差的 log 微动, 骨量损失, 两档里较差的约束违反量)。"""
    return max(e["a"]["y"][0], e["b"]["y"][0]), e["a"]["y"][1], max(e["a"]["c"][0], e["b"]["c"][0])


def nondominated(P: np.ndarray) -> np.ndarray:
    return np.array([i for i in range(len(P)) if not any((P[j] <= P[i]).all() and (P[j] < P[i]).any() for j in range(len(P)))], int)


def spec_of(dsg: dict, h: float, delta: float, tag: str) -> dict:
    return {**S.design_spec(dict(dsg), STAGE, tag), "model": "m1", "h_cut": float(h), "slip_tol": N.FRIC["slip_tol"], "delta": float(delta)}


# ------------------------------------------------------------------------------------------------- 代理与采集
def fit(ent: dict, det):
    import torch
    from botorch.models.deterministic import GenericDeterministicModel
    from botorch.models.model import ModelList
    A = [e for e in ent.values() if "a" in e]
    B = [e for e in ent.values() if "b" in e]
    t = lambda v: torch.tensor(v, dtype=torch.double)  # noqa: E731
    gpa = S._fit_gp_unit(t([e["x"] for e in A]), t([-e["a"]["y"][0] for e in A]))
    gpb = S._fit_gp_unit(t([e["x"] for e in B]), t([-e["b"]["y"][0] for e in B]))
    gpc = S._fit_gp_unit(t([e["x"] for e in A]), t([max(e["a"]["c"][0], e["b"]["c"][0]) if "b" in e else e["a"]["c"][0] for e in A]))
    detm = GenericDeterministicModel(lambda Z: -det(Z).unsqueeze(-1))
    return ModelList(gpa, gpb, detm, gpc), len(A), len(B)


def lengthscales(model) -> dict:
    out = {}
    for name, i in (("micromotion_d0.025", 0), ("micromotion_d0.01", 1)):
        try:
            ls = model.models[i].covar_module.base_kernel.lengthscale.detach().cpu().numpy().ravel()
            out[name] = {v: float(x) for v, x in zip(PH.vars, ls)}
        except Exception as e:                                       # noqa: BLE001
            out[name] = f"n/a ({type(e).__name__})"
    return out


def propose(model, Xbase: np.ndarray, refp: np.ndarray, cand: np.ndarray, pending_x: np.ndarray | None, seed: int) -> int:
    import torch
    from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
    from botorch.acquisition.multi_objective.objective import GenericMCMultiOutputObjective
    from botorch.optim import optimize_acqf_discrete
    from botorch.sampling.get_sampler import get_sampler
    Xb = torch.as_tensor(Xbase, dtype=torch.double)
    sampler = get_sampler(model.posterior(Xb[:1]), sample_shape=torch.Size([128]), seed=seed)
    obj = GenericMCMultiOutputObjective(lambda Z, X=None: torch.stack([torch.minimum(Z[..., 0], Z[..., 1]), Z[..., 2]], dim=-1))
    acq = qLogNoisyExpectedHypervolumeImprovement(model=model, ref_point=[-float(refp[0]), -float(refp[1])], X_baseline=Xb,
                                                  prune_baseline=True, sampler=sampler, objective=obj,
                                                  constraints=[lambda Z: Z[..., 3]], cache_root=False)
    if pending_x is not None and len(pending_x):
        acq.set_X_pending(torch.as_tensor(np.asarray(pending_x, float), dtype=torch.double))
    x, _ = optimize_acqf_discrete(acq, q=1, choices=torch.as_tensor(cand, dtype=torch.double), max_batch_size=2048, unique=True)
    return int(np.argmin(np.linalg.norm(cand - x.numpy()[0], axis=1)))


# ------------------------------------------------------------------------------------------------- 主循环
def run(budget: int, inflight: int, n_layer2: int, seed: int, workers: int, n_cand: int, refresh_k: int, refresh_rad: float,
        stop_tol: float, stop_window: int, poll: float = 30.0) -> None:
    import mobo
    st = json.loads(OUT.read_text()) if OUT.exists() else {}
    if POOL.exists():
        z = np.load(POOL)
    else:
        z = np.load(J.RESULTS / "neckopt_p3_pool_live.npz")
        np.savez(POOL, U=z["U"], loss=z["loss"])
        z = np.load(POOL)
    pool, pool_loss = z["U"], z["loss"]
    det = N.det_loss_fn(pool, pool_loss)
    used = np.zeros(len(pool), bool)
    pending = st.get("pending", {})
    hv_hist, ls_hist = st.get("hv_hist", []), st.get("lengthscales", {})
    refp = np.array(st["ref_point"]) if st.get("ref_point") else None
    n_new = int(st.get("n_new", 0))
    state = {**st, "budget": budget, "inflight": inflight, "deltas": DELTAS, "space": PH.space, "sed": "abs", "n_cand": n_cand,
             "refresh_k": refresh_k, "refresh_rad": refresh_rad, "stop_tol": stop_tol, "stop_window": stop_window}

    def save(ent=None):
        if ent is not None:
            both = [(k, e) for k, e in ent.items() if "a" in e and "b" in e]
            state["records"] = [{"key": k, "x": e["x"], "design": e["design"], "h_cut": e["h_cut"], "a_job": e["a_job"], "b_job": e["b_job"],
                                 "f1_d025_um": 10 ** e["a"]["y"][0], "f1_d01_um": 10 ** e["b"]["y"][0], "y_rob": robust(e)[0],
                                 "loss_mm3": robust(e)[1], "c_rob": robust(e)[2], "ssi_pct": e["a"].get("ssi_pct"),
                                 "vm_p99_d025": e["a"].get("vm_p99"), "vm_p99_d01": e["b"].get("vm_p99"),
                                 "new": e["a_job"].startswith(STAGE) and "_a" in e["a_job"]} for k, e in both]
        state.update(pending=pending, hv_hist=hv_hist, lengthscales=ls_hist, n_new=n_new, pool_size=int(len(pool)),
                     ref_point=None if refp is None else refp.tolist(), updated=time.strftime("%Y-%m-%d %H:%M:%S"))
        OUT.write_text(json.dumps(state, indent=1, default=float))

    def robust_set(ent):
        both = [e for e in ent.values() if "a" in e and "b" in e]
        R = np.array([robust(e) for e in both]).reshape(-1, 3)
        return both, R

    # ---------------- I 初始批：已解前沿在 δ 0.01 下补算
    ent = scan()
    if "initial" not in st:
        A = [(k, e) for k, e in ent.items() if "a" in e and e["a"]["c"][0] <= 0]
        P = np.array([e["a"]["y"] for _, e in A])
        l1 = nondominated(P)
        rest = np.setdiff1d(np.arange(len(A)), l1)
        l2 = rest[nondominated(P[rest])] if len(rest) else np.array([], int)
        if len(l2) > n_layer2:
            l2 = l2[np.linspace(0, len(l2) - 1, n_layer2).round().astype(int)]
        chosen = [A[i] for i in np.r_[l1, l2]]
        init, sub = {}, []
        for k, e in chosen:
            if "b" in e:
                init[k] = {"a_job": e["a_job"], "b_job": e["b_job"], "adopted": True}
                continue
            sa = json.loads((J.QROOT / e["a_job"] / "spec.json").read_text())
            jb = J.submit(spec_of(sa["design"], e["h_cut"], DELTAS[1], "init"))
            init[k] = {"a_job": e["a_job"], "b_job": jb}
            sub.append(jb)
        state["initial"] = init
        state["initial_layers"] = {"layer1": int(len(l1)), "layer2": int(len(l2))}
        save(ent)
        print(f"[robust] initial batch: {len(chosen)} designs (front layer 1: {len(l1)}, layer 2: {len(l2)}); "
              f"{len(sub)} new δ 0.01 jobs, {len(chosen) - len(sub)} adopted", flush=True)
    else:
        sub = [v["b_job"] for v in st["initial"].values() if not v.get("adopted")]
    if sub:
        S.wait_for(sub, timeout_h=24)
    ent = scan()
    both, R = robust_set(ent)
    if refp is None:
        F = R[R[:, 2] <= 0][:, :2]
        lo, hi = F.min(0), F.max(0)
        refp = hi + 0.1 * (hi - lo)
        hv0 = float(mobo.hypervolume(F, refp))
        hv_hist.append({"n_both": len(both), "hv": hv0, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        print(f"[robust] initial batch done: {len(both)} designs with both interferences; robust HV {hv0:.4g}; "
              f"ref (log µm, mm³) {refp.round(3).tolist()}", flush=True)
    save(ent)

    # ---------------- II 异步
    for e in ent.values():                                            # 已在池里的设计不再选
        pass
    for p_ in pending.values():
        if p_.get("pool_idx") is not None and p_["pool_idx"] < len(pool):
            used[p_["pool_idx"]] = True
    for i in st.get("used_idx", []):
        if i < len(pool):
            used[i] = True
    used_idx = list(st.get("used_idx", []))
    rng = np.random.default_rng(seed + 11)
    since_refresh, stopped = 0, bool(st.get("stopped_early"))

    def n_running():
        return sum(1 for p_ in pending.values() for j in p_["jobs"] if J.state(J.QROOT / j) not in ("DONE", "FAILED"))

    while True:
        while not stopped and n_new < budget and n_running() + 2 <= inflight:
            t0 = time.perf_counter()
            ent = scan()
            model, na, nb = fit(ent, det)
            ls_hist[str(n_new)] = lengthscales(model)
            Xbase = np.array([e["x"] for e in ent.values() if "a" in e])
            free = np.nonzero(~used)[0]
            cand = np.unique(np.r_[rng.choice(free, size=min(n_cand, len(free)), replace=False), free[free >= len(pool) - 2000]])
            px = np.array([p_["x"] for p_ in pending.values()]) if pending else None
            i = int(cand[propose(model, Xbase, refp, pool[cand], px, (70_000 + seed) * 1000 + n_new)])
            used[i] = True; used_idx.append(i); state["used_idx"] = used_idx
            d_, h_ = PH.design_of(pool[i])
            ja = J.submit(spec_of(d_, h_, DELTAS[0], f"a{n_new}"))
            jb = J.submit(spec_of(d_, h_, DELTAS[1], f"a{n_new}"))
            pending[dkey(d_, h_)] = {"x": pool[i].tolist(), "pool_idx": i, "jobs": [ja, jb], "submitted": time.strftime("%Y-%m-%d %H:%M:%S")}
            n_new += 1
            print(f"[robust] submit #{n_new} {ja} + {jb} (acq {time.perf_counter() - t0:.0f} s; GP data {na} / {nb}; cand {len(cand)}): "
                  f"{ {k: round(d_[k], 2) for k in PH.vars if k in d_} | {'h': round(h_, 1)} }", flush=True)
            save()
        if not pending:
            break
        time.sleep(poll)
        fin = [k for k, p_ in pending.items() if all(J.state(J.QROOT / j) in ("DONE", "FAILED") for j in p_["jobs"])]
        if not fin:
            continue
        for k in fin:
            pending.pop(k)
        ent = scan()
        both, R = robust_set(ent)
        F = R[R[:, 2] <= 0][:, :2]
        hv = float(mobo.hypervolume(F, refp)) if len(F) else float("nan")
        hv_hist.append({"n_both": len(both), "hv": hv, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        last = [ent[k] for k in fin if k in ent and "a" in ent[k] and "b" in ent[k]]
        print(f"[robust] done +{len(fin)} ({[(round(10 ** e['a']['y'][0], 1), round(10 ** e['b']['y'][0], 1)) for e in last]} µm at δ 0.025 / 0.01); "
              f"designs with both {len(both)}; robust HV {hv:.4g}; {len(pending)} designs in flight", flush=True)
        since_refresh += len(fin)
        if refresh_k > 0 and since_refresh >= 6:
            t1 = time.perf_counter()
            fr = nondominated(F)
            cent = np.array([e["x"] for e, r in zip(both, R) if r[2] <= 0])[fr]
            Un, Ln = N.refresh_pool(PH, cent, k=refresh_k, rad=refresh_rad, workers=workers, seed=seed * 1000 + len(both))
            if len(Un):
                pool, pool_loss = np.vstack([pool, Un]), np.r_[pool_loss, Ln]
                used = np.r_[used, np.zeros(len(Un), bool)]
                det = N.det_loss_fn(pool, pool_loss)
                np.savez(POOL, U=pool, loss=pool_loss)
            since_refresh = 0
            print(f"[robust] pool refresh: +{len(Un)} around {len(cent)} robust-front points ({time.perf_counter() - t1:.0f} s), pool {len(pool)}", flush=True)
        if stop_tol > 0 and not stopped and len(hv_hist) > stop_window:
            a_, b_ = hv_hist[-stop_window - 1]["hv"], hv_hist[-1]["hv"]
            if a_ > 0 and (b_ - a_) / a_ < stop_tol:
                stopped = True; state["stopped_early"] = len(both)
                print(f"[robust] stop: robust HV gain over the last {stop_window} completions < {stop_tol:.1%}; draining", flush=True)
        save(ent)
    save(scan())
    print(f"[robust] finished: {n_new} new designs", flush=True)


def status() -> None:
    if not OUT.exists():
        print("no results yet"); return
    st = json.loads(OUT.read_text())
    recs = st.get("records", [])
    print(json.dumps({k: v for k, v in st.items() if k not in ("records", "initial", "pending", "lengthscales", "hv_hist", "used_idx", "space")},
                     indent=1, default=float))
    print("pending", len(st.get("pending", {})), "hv_hist", [round(h["hv"]) for h in st.get("hv_hist", [])][-10:])
    F = [r for r in recs if r["c_rob"] <= 0]
    P = np.array([[r["y_rob"], r["loss_mm3"]] for r in F]).reshape(-1, 2)
    for i in sorted(nondominated(P), key=lambda i: P[i, 0]) if len(P) else []:
        r = F[i]
        print(f"  robust {10 ** r['y_rob']:5.1f} µm (δ0.025 {r['f1_d025_um']:5.1f}, δ0.01 {r['f1_d01_um']:5.1f})  loss {r['loss_mm3'] / 1000:4.1f} cm³  "
              f"{ {k: round(v, 2) for k, v in r['design'].items()} }  {r['a_job']}")


if __name__ == "__main__":
    import argparse
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (24 << 30, 24 << 30))
    except Exception:                                                    # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status", "scan"])
    ap.add_argument("--budget", type=int, default=36)
    ap.add_argument("--inflight", type=int, default=6)
    ap.add_argument("--layer2", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cand", type=int, default=10000)
    ap.add_argument("--refresh", type=int, default=64)
    ap.add_argument("--refresh-rad", type=float, default=0.08)
    ap.add_argument("--stop-tol", type=float, default=0.005)
    ap.add_argument("--stop-window", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "status":
        status()
    elif a.cmd == "scan":
        ent = scan()
        print(len(ent), "designs;", sum("a" in e for e in ent.values()), "with δ 0.025;", sum("b" in e for e in ent.values()), "with δ 0.01;",
              sum("a" in e and "b" in e for e in ent.values()), "with both")
    else:
        run(a.budget, a.inflight, a.layer2, a.seed, a.workers, a.cand, a.refresh, a.refresh_rad, a.stop_tol, a.stop_window)
