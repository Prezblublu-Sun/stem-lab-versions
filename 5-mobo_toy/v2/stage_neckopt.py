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
}
CONST = {"collar_t": G.COLLAR_T, "cap_h": G.CAP_FLAT}
FRIC = {"slip_tol": 2.5e-4, "delta": 0.025}
SED_LIMIT, VM_LIMIT = 30.0, 440.0
_FM = {}
_SSI = {}


def out_path(phase: int) -> pathlib.Path:
    return J.RESULTS / f"neckopt_p{phase}.json"


class Phase:
    def __init__(self, phase: int, ref: dict | None = None, sed: str = "abs"):
        self.phase, self.space, self.sed = phase, PHASES[phase]["vars"], sed
        self.vars = list(self.space)
        self.fixed = dict(PHASES[phase]["fixed"])
        if phase == 2:
            if not ref:
                raise ValueError("phase 2 needs --ref <job_id> (the phase-1 design whose L, alpha, collar_w, h_cut are kept)")
            self.fixed.update({k: ref[k] for k in ("L", "alpha", "collar_w", "h_cut")})
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
        if not legacy and (float(d.get("cap_h", -1.0)) != CONST["cap_h"] or not str(spec.get("stage", "")).startswith("neck")):
            return False
        full = {**d, "h_cut": float(spec.get("h_cut", 25.0)), "collar_w": float(d.get("collar_w", 0.0)), "m": float(d.get("m", G.M_LEGACY))}
        for k, val in self.fixed.items():
            if abs(float(full.get(k, -999.0)) - float(val)) > 1e-6:
                return False
        return all(self.space[k][0] - 1e-9 <= float(full[k]) <= self.space[k][1] + 1e-9 for k in self.vars)

    def spec_of(self, u, tag: str) -> dict:
        d, h = self.design_of(u)
        return {**S.design_spec(d, f"neck{self.phase}", tag), "model": "m1", "h_cut": h, **FRIC}


# ------------------------------------------------------------------------------------------------- 指标
def calcar_ssi(job_id: str) -> float | None:
    """固定解剖区 G7、只算皮质的屏蔽指数（%）：1 − 植入 / 完整 的应变能密度均值，设计截骨面以下同一组采样点。"""
    if job_id in _SSI:
        return _SSI[job_id]
    try:
        import resorption as RS
        rows, _ = RS.design_rows(job_id)
        v = next((r.get("ssi_pct") for r in rows if r["scheme"] == "fixed" and r["zone"] == "G7" and r["tissue"] == "cortex"), None)
        v = None if v is None or not np.isfinite(v) else float(v)
    except Exception as e:                                           # noqa: BLE001
        print(f"[neckopt] calcar_ssi {job_id}: {type(e).__name__}: {str(e)[:120]}", flush=True)
        v = None
    _SSI[job_id] = v
    return v


def objectives(r: dict | None, sed: str, ssi: float | None) -> tuple[list[float], float, bool]:
    if not r or "failed" in r or "f1_p95_um" not in r:
        return [math.nan, math.nan], math.nan, False
    f1 = r.get("f1_all_p95_um", r.get("f1_p95_um"))
    bl = r.get("bone_loss") or {}
    loss = bl.get("total_mm3")
    if loss is None:
        loss = (r.get("templating") or {}).get("volume")
    if f1 is None or loss is None or r.get("vm_p99") is None or (sed != "none" and ssi is None):
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(float(f1), 1e-3)), float(loss)]
    c_vm = (r["vm_p99"] - VM_LIMIT) / VM_LIMIT
    c_sed = {"one-sided": (ssi - SED_LIMIT) / SED_LIMIT, "abs": (abs(ssi) - SED_LIMIT) / SED_LIMIT, "none": -1.0}[sed] if ssi is not None else -1.0
    return y, float(max(c_vm, c_sed)), all(np.isfinite(y))


def record_of(job_id: str, sed: str) -> dict:
    res = J.result(job_id) or {}
    ssi = calcar_ssi(job_id) if res and "f1_p95_um" in res else None
    y, c, ok = objectives(res, sed, ssi)
    return {"y": [float(v) for v in y], "c": [float(c)], "ok": bool(ok), "ssi_pct": ssi, "g7_mixed_pct": res.get("f2_g7_loss_pct"),
            "vm_p99": res.get("vm_p99"), "f1_all_p95_um": res.get("f1_all_p95_um"), "f1_body_p95_um": res.get("f1_p95_um"),
            "collar_open_frac_load2": res.get("collar_open_frac_load2"), "collar_force_share_load2": res.get("collar_force_share_load2")}


def dataset(ph: Phase, legacy: bool = False):
    seen, X, Y, C, ids = set(), [], [], [], []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") not in ("design", "variant") or not ph.in_family(spec, legacy):
            continue
        dsg = dict(spec["design"])
        h = float(spec.get("h_cut", 25.0))
        key = json.dumps({**dsg, "h_cut": h}, sort_keys=True)
        if key in seen:
            continue
        rec = record_of(d.name, ph.sed)
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
    r = G.template(G.Stem3D(**d), fm)
    ok = bool(r["fit"] and r["A0"] >= S.MIN_A0)
    loss = float(fm.resected_volume() + r["volume"]) if ok else math.nan
    return ok, loss


def gated_pool(ph: Phase, n: int = 8192, seed: int = 0, workers: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """返回 (可行候选的单位坐标, 各自的骨量损失 mm³)。"""
    from scipy.stats import qmc
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((J.code_hash() + json.dumps(ph.space, sort_keys=True) + json.dumps(ph.fixed, sort_keys=True)
                        + json.dumps(CONST) + f"{n}_{seed}_v2").encode()).hexdigest()[:8]
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
                                                  "space": ph.space, "fixed": ph.fixed, "loss_range_mm3": [float(np.nanmin(loss[keep])), float(np.nanmax(loss[keep]))]}))
    print(f"[neckopt p{ph.phase}] pool: {int(keep.sum())}/{n} feasible; bone loss {np.nanmin(loss[keep]):.0f}–{np.nanmax(loss[keep]):.0f} mm³", flush=True)
    return U[keep], loss[keep]


def det_loss_fn(pool: np.ndarray, loss: np.ndarray):
    """确定性目标：单位坐标 → 骨量损失（最近的候选点；采集只在候选池上离散优化，所以是精确值）。"""
    import torch
    P, Lt = torch.as_tensor(pool, dtype=torch.double), torch.as_tensor(loss, dtype=torch.double)

    def fn(Z):
        Zf = Z.reshape(-1, Z.shape[-1]).to(torch.double)
        idx = torch.cdist(Zf, P).argmin(dim=1)
        return Lt[idx].reshape(Z.shape[:-1]).to(Z.dtype)
    return fn


def evaluate(ph: Phase, U, tag: str):
    ids = [J.submit(ph.spec_of(u, tag)) for u in U]
    S.wait_for(ids)
    return ids


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0] if (C[:, 0] <= 0).any() else Y
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def bo(ph: Phase, n_rounds: int, n_init: int, q: int, seed: int, workers: int, legacy_warm: bool) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm)
    pool, pool_loss = gated_pool(ph, seed=seed, workers=workers)
    used = np.zeros(len(pool), bool)
    recs, refp = [], None
    out = out_path(ph.phase)
    if out.exists():                                                     # 续跑：按当前约束形式从作业结果重算
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs = prev["records"]
            for r in recs:
                used[r["pool_idx"]] = True
                r.update(record_of(r["job_id"], ph.sed))
            refp = np.array(prev["ref_point"]) if prev.get("ref_point") else None
            if prev.get("sed") != ph.sed:
                print(f"[neckopt p{ph.phase}] constraint form changed {prev.get('sed')} -> {ph.sed}; feasibility recomputed", flush=True)
    state = {"phase": ph.phase, "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
             "ref": ph.ref, "n_init": n_init, "q": q, "n_rounds": n_rounds, "warm_start_n": int(len(X0)), "warm_start_ids": ids0,
             "pool_size": int(len(pool)), "records": recs, "ref_point": None if refp is None else refp.tolist()}

    def save():
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(state, indent=1, default=float))

    print(f"[neckopt p{ph.phase}] vars {ph.vars}; warm start {len(X0)} ({int((C0[:, 0] <= 0).sum()) if len(C0) else 0} feasible); "
          f"pool {len(pool)}; existing records {len(recs)}; sed={ph.sed}", flush=True)

    def run_batch(idx, tag, rnd):
        ids = evaluate(ph, pool[idx], tag)
        for i, j in zip(idx, ids):
            d, h = ph.design_of(pool[i])
            recs.append({"pool_idx": int(i), "x": pool[i].tolist(), "round": rnd, "job_id": j, "h_cut": h,
                         "design": {k: d[k] for k in ph.vars if k in d}, **record_of(j, ph.sed)})
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
    det = {1: det_loss_fn(pool, pool_loss)}
    done_rounds = max([r["round"] for r in recs], default=0)
    for rnd in range(done_rounds + 1, n_rounds + 1):
        t0 = time.perf_counter()
        X, Y, C = stack()
        if refp is None:                                                 # 参考点在初始批之后固定一次，超体积才可跨轮比较
            refp = ref_point(Y, C)
            state["ref_point"] = refp.tolist()
        model = mobo.fit_models(X, Y, C, det=det)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, refp, pool[free], q, 2, 1, (50_000 + ph.phase * 100 + seed) * 1000 + rnd)
        idx = free[pick]
        used[idx] = True
        acq_s = time.perf_counter() - t0
        okn = run_batch(idx, f"r{rnd}", rnd)
        X, Y, C = stack()
        feas = Y[C[:, 0] <= 0]
        hv = mobo.hypervolume(feas, refp) if len(feas) else float("nan")
        last = recs[-len(idx):]
        print(f"[neckopt p{ph.phase}] round {rnd}: +{int(okn.sum())}/{len(idx)} ok; "
              f"{[{k: round(v, 1) for k, v in r['design'].items()} | {'h': round(r['h_cut'], 1), 'ssi': None if r['ssi_pct'] is None else round(r['ssi_pct'], 1)} for r in last]}; "
              f"HV {hv:.4g}; acq {acq_s:.0f} s", flush=True)
        save()
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
        print(f"  {10 ** r['y'][0]:6.1f} µm  loss {r['y'][1]:7.0f} mm³  ssi {r['ssi_pct']:+6.1f} %  {r['design']}  h_cut {r['h_cut']:.1f}  {r['job_id']}")


def load_ref(job_id: str) -> dict:
    spec = json.loads((J.QROOT / job_id / "spec.json").read_text())
    d = spec["design"]
    return {"L": d["L"], "alpha": d["alpha"], "collar_w": d.get("collar_w", 0.0), "m": d.get("m", G.M_LEGACY), "h_cut": spec.get("h_cut", 25.0),
            "job_id": job_id}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dataset", "pool", "bo", "status", "selftest"])
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--ref", default=None, help="phase 2: phase-1 job id whose L, alpha, collar_w, h_cut are kept")
    ap.add_argument("--sed", choices=["one-sided", "abs", "none"], default="abs")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--init", type=int, default=16)
    ap.add_argument("--q", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--warm", choices=["family", "legacy"], default="family")
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
        U, loss = gated_pool(ph, seed=a.seed, workers=a.workers)
        print(U.shape, float(np.nanmin(loss)), float(np.nanmax(loss)))
    elif a.cmd == "status":
        status(a.phase)
    else:
        bo(ph, a.rounds, a.init, a.q, a.seed, a.workers, a.warm == "legacy")
