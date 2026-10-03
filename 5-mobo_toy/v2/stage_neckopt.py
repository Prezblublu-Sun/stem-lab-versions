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
    # 阶段 3（用户 2026-10-03 11:30）：14 个变量一轮联合优化，热启动 = 阶段 1 + 阶段 2 的全部设计（同一几何族），用于和两阶段对比
    3: {"vars": {"L": (20.0, 60.0), "alpha": (15.0, 45.0), "collar_w": (0.0, 6.0), "h_cut": (25.0, 32.0), "m": (-0.25, 2.0),
                 "rho_tip": (0.10, 0.50), "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65),
                 "n_a": (2.0, 6.0), "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
        "fixed": {}},
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
        if spec.get("stage") == f"neck{ph.phase}":                        # 本阶段自己的作业由 records 续跑接管，不作热启动（否则重复计入）
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


def refresh_pool(ph: Phase, centres: np.ndarray, k: int = 64, rad: float = 0.08, workers: int = 6, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """前沿邻域补点：每个中心周围 [x−rad, x+rad]^d 内均匀取 k 个点，过模板化，返回 (可行点, 骨量损失)。离散池的局部加密。"""
    rng = np.random.default_rng(seed)
    U = np.clip(np.vstack([c + rng.uniform(-rad, rad, size=(k, len(ph.vars))) for c in np.atleast_2d(centres)]), 0.0, 1.0)
    with Pool(workers) as p:
        res = p.map(_feasible, [(u, ph.phase, ph.ref) for u in U], chunksize=16)
    keep = np.array([r[0] for r in res]); loss = np.array([r[1] for r in res], float)
    return U[keep], loss[keep]


def lengthscales(model, ph: Phase) -> dict:
    """微动 GP 与约束 GP 的 ARD 长度尺度（归一化输入空间；越短越重要）。"""
    out = {}
    for name, idx in (("micromotion", 0), ("constraint", 2)):
        try:
            gp = model.models[idx]
            ls = gp.covar_module.base_kernel.lengthscale.detach().cpu().numpy().ravel()
            out[name] = {v: float(x) for v, x in zip(ph.vars, ls)}
        except Exception as e:                                       # noqa: BLE001
            out[name] = f"n/a ({type(e).__name__})"
    return out


def det_loss_fn(pool: np.ndarray, loss: np.ndarray):
    """确定性目标：单位坐标 → 骨量损失（最近的候选点；采集只在候选池上离散优化，所以是精确值）。
    用 KD 树做最近邻：NEHVI 把基线点和候选批一起送进来（每批 2048 × ~150 行），原来的 torch.cdist 会物化
    (30 万 × 2.5 万) 的距离矩阵——2026-10-03 13:30 把 Linux 的 31 GB 吃光、整台机僵了 6 小时。离散采集不需要梯度。"""
    import torch
    from scipy.spatial import cKDTree
    tree = cKDTree(np.asarray(pool, float))
    Lt = np.asarray(loss, float)

    def fn(Z):
        Zf = Z.detach().cpu().numpy().reshape(-1, Z.shape[-1])
        _, idx = tree.query(Zf, k=1, workers=1)
        return torch.as_tensor(Lt[idx], dtype=Z.dtype, device=Z.device).reshape(Z.shape[:-1])
    return fn


def evaluate(ph: Phase, U, tag: str):
    ids = [J.submit(ph.spec_of(u, tag)) for u in U]
    S.wait_for(ids)
    return ids


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0] if (C[:, 0] <= 0).any() else Y
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def bo(ph: Phase, n_rounds: int, n_init: int, q: int, seed: int, workers: int, legacy_warm: bool, n_pool: int = 8192,
       refresh_k: int = 0, refresh_rad: float = 0.08, stop_tol: float = 0.0, stop_rounds: int = 4) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm)
    pool, pool_loss = gated_pool(ph, n=n_pool, seed=seed, workers=workers)
    live = J.RESULTS / f"neckopt_p{ph.phase}_pool_live.npz"           # 含邻域补点的池（续跑时用，保证 pool_idx 不变）
    recs, refp, hv_hist, ls_hist = [], None, [], {}
    out = out_path(ph.phase)
    if out.exists():                                                     # 续跑：按当前约束形式从作业结果重算
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs = prev["records"]
            hv_hist, ls_hist = prev.get("hv_hist", []), prev.get("lengthscales", {})
            if live.exists():
                z = np.load(live); pool, pool_loss = z["U"], z["loss"]
    used = np.zeros(len(pool), bool)
    if recs:
            for r in recs:
                used[r["pool_idx"]] = True
                r.update(record_of(r["job_id"], ph.sed))
            refp = np.array(prev["ref_point"]) if prev.get("ref_point") else None
            if prev.get("sed") != ph.sed:  # noqa: SIM102
                print(f"[neckopt p{ph.phase}] constraint form changed {prev.get('sed')} -> {ph.sed}; feasibility recomputed", flush=True)
    state = {"phase": ph.phase, "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
             "ref": ph.ref, "n_init": n_init, "q": q, "n_rounds": n_rounds, "warm_start_n": int(len(X0)), "warm_start_ids": ids0,
             "pool_size": int(len(pool)), "records": recs, "ref_point": None if refp is None else refp.tolist(),
             "hv_hist": hv_hist, "lengthscales": ls_hist, "n_pool": n_pool, "refresh_k": refresh_k, "refresh_rad": refresh_rad,
             "stop_tol": stop_tol, "stop_rounds": stop_rounds}

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

    def front_rows(X, Y, C):
        f = np.nonzero(C[:, 0] <= 0)[0]
        keep = [i for i in f if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in f)]
        return X[keep]

    for rnd in range(done_rounds + 1, n_rounds + 1):
        t0 = time.perf_counter()
        X, Y, C = stack()
        if refp is None:                                                 # 参考点在热启动 / 初始批之后固定一次，超体积才可跨轮、跨阶段比较
            refp = ref_point(Y, C)
            state["ref_point"] = refp.tolist()
        model = mobo.fit_models(X, Y, C, det=det)
        ls_hist[str(rnd)] = lengthscales(model, ph)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, refp, pool[free], q, 2, 1, (50_000 + ph.phase * 100 + seed) * 1000 + rnd)
        idx = free[pick]
        used[idx] = True
        acq_s = time.perf_counter() - t0
        okn = run_batch(idx, f"r{rnd}", rnd)
        X, Y, C = stack()
        feas = Y[C[:, 0] <= 0]
        hv = float(mobo.hypervolume(feas, refp)) if len(feas) else float("nan")
        hv_hist.append({"round": rnd, "hv": hv, "n_eval": int(len(recs)), "n_ok": int(sum(r["ok"] for r in recs))})
        last = recs[-len(idx):]
        print(f"[neckopt p{ph.phase}] round {rnd}: +{int(okn.sum())}/{len(idx)} ok; "
              f"{[{k: round(v, 2) for k, v in r['design'].items()} | {'h': round(r['h_cut'], 1), 'ssi': None if r['ssi_pct'] is None else round(r['ssi_pct'], 1)} for r in last]}; "
              f"HV {hv:.4g}; acq {acq_s:.0f} s", flush=True)
        if refresh_k > 0:                                               # 前沿邻域补点（离散池的局部加密）
            t1 = time.perf_counter()
            Un, Ln = refresh_pool(ph, front_rows(X, Y, C), k=refresh_k, rad=refresh_rad, workers=workers, seed=seed * 1000 + rnd)
            if len(Un):
                pool, pool_loss = np.vstack([pool, Un]), np.r_[pool_loss, Ln]
                used = np.r_[used, np.zeros(len(Un), bool)]
                det = {1: det_loss_fn(pool, pool_loss)}
                np.savez(live, U=pool, loss=pool_loss)
            state["pool_size"] = int(len(pool))
            print(f"[neckopt p{ph.phase}] pool refresh: +{len(Un)} feasible around {len(front_rows(X, Y, C))} front points "
                  f"({time.perf_counter() - t1:.0f} s), pool {len(pool)}", flush=True)
        save()
        if stop_tol > 0 and len(hv_hist) > stop_rounds:
            hvs = [h["hv"] for h in hv_hist[-(stop_rounds + 1):]]
            gains = [(b - a) / a for a, b in zip(hvs[:-1], hvs[1:]) if a > 0]
            if gains and max(gains) < stop_tol:
                print(f"[neckopt p{ph.phase}] stop: hypervolume gain < {stop_tol:.1%} for {stop_rounds} rounds", flush=True)
                state["stopped_early"] = rnd
                save()
                break
    return state


def _front_rows(X, Y, C):
    f = np.nonzero(C[:, 0] <= 0)[0]
    keep = [i for i in f if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in f)]
    return X[keep]


def bo_async(ph: Phase, budget: int, inflight: int, seed: int, workers: int, legacy_warm: bool, n_pool: int = 8192,
             refresh_k: int = 0, refresh_rad: float = 0.08, stop_tol: float = 0.0, stop_window: int = 18, n_cand: int = 10000,
             poll: float = 30.0) -> dict:
    """异步版（用户 2026-10-03 21:45：同步版每轮采集 6–7 分钟时求解器空转，4 个设计 3 个槽又拖一个尾巴）：
    求解器里始终保持 inflight 个设计在算；每有一个算完，就用全部已完成结果重拟合代理、选 1 个新点提交（在算的点作 X_pending）。
    与同步版共用记录文件、参考点、候选池，可互相续跑；重启时把本阶段不在记录里的作业收编（已解的进记录，在算的进待定）。
    budget = 本阶段新设计的总数（含已完成的）。停止：最近 stop_window 个完成的超体积改进 < stop_tol，之后只排空不再提交。"""
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm)
    pool, pool_loss = gated_pool(ph, n=n_pool, seed=seed, workers=workers)
    live = J.RESULTS / f"neckopt_p{ph.phase}_pool_live.npz"
    out = out_path(ph.phase)
    recs, refp, hv_hist, ls_hist, pending = [], None, [], {}, {}
    if out.exists():
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs, hv_hist, ls_hist, pending = prev["records"], prev.get("hv_hist", []), prev.get("lengthscales", {}), prev.get("pending", {})
            refp = np.array(prev["ref_point"]) if prev.get("ref_point") else None
            if live.exists():
                z = np.load(live); pool, pool_loss = z["U"], z["loss"]
    used = np.zeros(len(pool), bool)

    def rec_from(job: str, x, pool_idx, round_):
        d_, h_ = ph.design_of(np.asarray(x, float))
        return {"pool_idx": pool_idx, "x": list(map(float, x)), "round": round_, "job_id": job, "h_cut": h_,
                "design": {k: d_[k] for k in ph.vars if k in d_}, **record_of(job, ph.sed)}

    known = set()
    for r in recs:
        known.add(r["job_id"]); r.update(record_of(r["job_id"], ph.sed))
        if r.get("pool_idx") is not None and r["pool_idx"] < len(pool):
            used[r["pool_idx"]] = True
    adopted = 0
    for d in sorted(J.QROOT.glob(f"neck{ph.phase}_*")):                 # 收编本阶段不在记录里的作业
        if d.name in known or not (d / "spec.json").exists():
            continue
        st_ = J.state(d)
        spec = json.loads((d / "spec.json").read_text())
        x = ph.to_unit(spec["design"], float(spec.get("h_cut", 25.0)))
        if st_ in ("DONE", "FAILED"):
            recs.append(rec_from(d.name, x, pending.pop(d.name, {}).get("pool_idx"), -1)); known.add(d.name); adopted += 1
        elif st_ in ("NEW", "READY", "CLAIMED", "SOLVED") and d.name not in pending:
            pending[d.name] = {"pool_idx": None, "x": x.tolist(), "submitted": "adopted"}
    for j in list(pending):                                             # 上次待定里已经算完的
        if J.state(J.QROOT / j) in ("DONE", "FAILED"):
            p_ = pending.pop(j); recs.append(rec_from(j, p_["x"], p_.get("pool_idx"), -1)); known.add(j)
    for p_ in pending.values():
        if p_.get("pool_idx") is not None and p_["pool_idx"] < len(pool):
            used[p_["pool_idx"]] = True
    state = {"phase": ph.phase, "mode": "async", "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT,
             "vm_limit": VM_LIMIT, "ref": ph.ref, "inflight": inflight, "budget": budget, "n_cand": n_cand, "warm_start_n": int(len(X0)),
             "warm_start_ids": ids0, "pool_size": int(len(pool)), "records": recs, "pending": pending,
             "ref_point": None if refp is None else refp.tolist(), "hv_hist": hv_hist, "lengthscales": ls_hist, "n_pool": n_pool,
             "refresh_k": refresh_k, "refresh_rad": refresh_rad, "stop_tol": stop_tol, "stop_window": stop_window}

    def save():
        state["pending"], state["pool_size"], state["updated"] = pending, int(len(pool)), time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(state, indent=1, default=float))

    def stack():
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        return X, Y, C

    det = {1: det_loss_fn(pool, pool_loss)}
    rng = np.random.default_rng(seed + 7)
    n_sub = len(recs) + len(pending)
    since_refresh, stopped = 0, False
    print(f"[neckopt p{ph.phase} async] warm start {len(X0)}; records {len(recs)} (adopted {adopted}); pending {len(pending)}; pool {len(pool)}; "
          f"budget {budget}; inflight {inflight}; sed={ph.sed}", flush=True)
    save()
    while True:
        while not stopped and len(pending) < inflight and n_sub < budget:               # 1. 补满在算的设计
            t0 = time.perf_counter()
            X, Y, C = stack()
            if refp is None:
                refp = ref_point(Y, C); state["ref_point"] = refp.tolist()
            model = mobo.fit_models(X, Y, C, det=det)
            ls_hist[str(n_sub)] = lengthscales(model, ph)
            free = np.nonzero(~used)[0]
            if len(free) > n_cand:                                                      # 随机子集 + 最近补的点（池尾部）
                cand = np.unique(np.r_[rng.choice(free, size=n_cand, replace=False), free[free >= len(pool) - 2000]])
            else:
                cand = free
            Xp = np.array([p_["x"] for p_ in pending.values()]) if pending else None
            pick = mobo.propose(model, X, refp, pool[cand], 1, 2, 1, (60_000 + ph.phase * 100 + seed) * 1000 + n_sub, X_pending=Xp)
            i = int(cand[pick[0]]); used[i] = True
            job = J.submit(ph.spec_of(pool[i], f"a{n_sub}"))
            pending[job] = {"pool_idx": i, "x": pool[i].tolist(), "submitted": time.strftime("%Y-%m-%d %H:%M:%S")}
            n_sub += 1
            d_, h_ = ph.design_of(pool[i])
            print(f"[neckopt p{ph.phase} async] submit #{n_sub} {job} (acq {time.perf_counter() - t0:.0f} s, {len(pending)} in flight, cand {len(cand)}): "
                  f"{ {k: round(d_[k], 2) for k in ph.vars if k in d_} | {'h': round(h_, 1)} }", flush=True)
            save()
        if not pending:
            break
        time.sleep(poll)                                                                # 2. 等任一完成
        done_now = [j for j in list(pending) if J.state(J.QROOT / j) in ("DONE", "FAILED")]
        if not done_now:
            continue
        for j in done_now:
            p_ = pending.pop(j)
            recs.append(rec_from(j, p_["x"], p_.get("pool_idx"), len(recs) + 1))
        X, Y, C = stack()
        feas = Y[C[:, 0] <= 0]
        hv = float(mobo.hypervolume(feas, refp)) if len(feas) and refp is not None else float("nan")
        hv_hist.append({"n_done": int(len(recs)), "hv": hv, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        print(f"[neckopt p{ph.phase} async] done {len(recs)} (+{len(done_now)}: {[round(10 ** r['y'][0], 1) if r['ok'] else 'fail' for r in recs[-len(done_now):]]} um), "
              f"ok {sum(r['ok'] for r in recs)}, HV {hv:.4g}, {len(pending)} in flight", flush=True)
        since_refresh += len(done_now)
        if refresh_k > 0 and since_refresh >= 6:                                       # 3. 前沿邻域补点
            t1 = time.perf_counter()
            Un, Ln = refresh_pool(ph, _front_rows(X, Y, C), k=refresh_k, rad=refresh_rad, workers=workers, seed=seed * 1000 + len(recs))
            if len(Un):
                pool, pool_loss = np.vstack([pool, Un]), np.r_[pool_loss, Ln]
                used = np.r_[used, np.zeros(len(Un), bool)]
                det = {1: det_loss_fn(pool, pool_loss)}
                np.savez(live, U=pool, loss=pool_loss)
            since_refresh = 0
            print(f"[neckopt p{ph.phase} async] pool refresh: +{len(Un)} ({time.perf_counter() - t1:.0f} s), pool {len(pool)}", flush=True)
        if stop_tol > 0 and not stopped and len(hv_hist) > stop_window:                 # 4. 停止判据（按完成数）
            a_, b_ = hv_hist[-stop_window - 1]["hv"], hv_hist[-1]["hv"]
            if a_ > 0 and (b_ - a_) / a_ < stop_tol:
                stopped = True; state["stopped_early"] = int(len(recs))
                print(f"[neckopt p{ph.phase} async] stop: HV gain over the last {stop_window} completions < {stop_tol:.1%}; draining {len(pending)} in flight", flush=True)
        save()
    print(f"[neckopt p{ph.phase} async] finished: {len(recs)} records", flush=True)
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
    pick1 = mobo.propose(model, X, refp, pool[20:], 1, 2, 1, 124, X_pending=pool[20:][pick])
    print("selftest async pick with 4 pending", pick1.tolist())


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
    try:                                                                 # 内存保险：优化进程最多 24 GB 地址空间，撑爆时死自己而不是拖垮整台机
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (24 << 30, 24 << 30))
    except Exception:                                                    # noqa: BLE001  （Windows 没有 resource）
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dataset", "pool", "bo", "async", "status", "selftest"])
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--ref", default=None, help="phase 2: phase-1 job id whose L, alpha, collar_w, h_cut are kept")
    ap.add_argument("--sed", choices=["one-sided", "abs", "none"], default="abs")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--init", type=int, default=16)
    ap.add_argument("--q", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--warm", choices=["family", "legacy"], default="family")
    ap.add_argument("--pool", type=int, default=8192, help="候选池 Sobol 点数（阶段 3 建议 32768）")
    ap.add_argument("--refresh", type=int, default=0, help="每轮在前沿各点邻域补的点数（0 = 不补）")
    ap.add_argument("--refresh-rad", type=float, default=0.08)
    ap.add_argument("--stop-tol", type=float, default=0.0, help="连续 --stop-rounds 轮超体积改进都小于此比例则停（0 = 不停）")
    ap.add_argument("--stop-rounds", type=int, default=4)
    ap.add_argument("--inflight", type=int, default=6, help="async：同时在算的设计数（3 槽 → 6 = 两整波）")
    ap.add_argument("--budget", type=int, default=80, help="async：本阶段新设计总数（含已完成）")
    ap.add_argument("--cand", type=int, default=10000, help="async：每次采集随机取的候选数（池尾最近补的点总是包含）")
    ap.add_argument("--stop-window", type=int, default=18, help="async：停止判据的完成数窗口")
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
        U, loss = gated_pool(ph, n=a.pool, seed=a.seed, workers=a.workers)
        print(U.shape, float(np.nanmin(loss)), float(np.nanmax(loss)))
    elif a.cmd == "status":
        status(a.phase)
    elif a.cmd == "async":
        bo_async(ph, a.budget, a.inflight, a.seed, a.workers, a.warm == "legacy", n_pool=a.pool, refresh_k=a.refresh,
                 refresh_rad=a.refresh_rad, stop_tol=a.stop_tol, stop_window=a.stop_window, n_cand=a.cand)
    else:
        bo(ph, a.rounds, a.init, a.q, a.seed, a.workers, a.warm == "legacy", n_pool=a.pool, refresh_k=a.refresh,
           refresh_rad=a.refresh_rad, stop_tol=a.stop_tol, stop_rounds=a.stop_rounds)
