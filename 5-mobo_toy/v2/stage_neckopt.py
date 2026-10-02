"""颈部柄的两阶段优化（用户 2026-10-02 13:20 的方案；Linux 上跑，本机只求解）。

阶段 1（主要变量，截面默认椭圆 λ 1.3，平端）：柄长 L、插入角 α、领宽 collar_w、皮质余量 m、截骨深度 h_cut —— 5 个变量。
阶段 2（次要变量，围绕阶段 1 选定的参考设置）：截面形状 λ、γ_ml、γ_ap、n_a、n_p、τ_a、τ_p —— 7 个变量；柄长、插入角、领宽、
    余量、截骨深度取 --ref 作业的值。
全程不变：锥度（ρ_tip 0.5、q 1.0）、领厚 2.5 mm、尖端平端（cap_h 1.5 mm）、M1 界面模型（过盈 0.025、slip_tol 2.5e-4、
    网格 2.0）、上楼载荷含扭转、四项指标。之后的多孔 / 变模量优化在此之外。

目标（最小化）：y1 = log10(柄身可恢复微动 P95, µm)；y2 = 骨量损失 = 截骨 + 锉骨（mm³）。
约束（≤ 0，合成一条归一化违反量）：柄 von Mises P99 ≤ 440 MPa；股骨距 Gruen 7 应变能变化，形式由 --sed 定：
    one-sided（默认）只限屏蔽 Δ ≤ +30 %；abs 为 |Δ| ≤ 30 %（V3 的做法）；none 不限。待用户定。
代理：一个高斯过程（输入 = 本阶段变量，归一化）；候选池 Sobol 8192 过模板化；qLogNEHVI，每轮 q 个。
热启动：只用同一几何族（椭圆 λ 1.3、ρ 0.5、q 1、平端）的已解作业；旧半椭球帽的作业不混入（--warm legacy 可包含）。

    python v2/stage_neckopt.py pool --phase 1
    python v2/stage_neckopt.py bo --phase 1 --init 16 --rounds 12 --q 4     → results/neckopt_p1.json（每轮覆盖，可续跑）
    python v2/stage_neckopt.py bo --phase 2 --ref <job_id> ...               → results/neckopt_p2.json
    python v2/stage_neckopt.py status --phase 1
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
    1: {"vars": {"L": (20.0, 40.0), "alpha": (25.0, 45.0), "collar_w": (0.0, 6.0), "m": (-0.25, 2.0), "h_cut": (25.0, 40.0)},
        "fixed": {"rho_tip": 0.5, "q": 1.0, "lam": 1.3, **G.ELLIPSE}},
    2: {"vars": {"lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0), "n_p": (2.0, 6.0),
                 "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)},
        "fixed": {"rho_tip": 0.5, "q": 1.0}},                 # 其余（L、alpha、collar_w、m、h_cut）来自 --ref
}
CONST = {"collar_t": G.COLLAR_T, "cap_h": G.CAP_FLAT}
FRIC = {"slip_tol": 2.5e-4, "delta": 0.025}
SED_LIMIT, VM_LIMIT = 30.0, 440.0
_FM = {}


def out_path(phase: int) -> pathlib.Path:
    return J.RESULTS / f"neckopt_p{phase}.json"


class Phase:
    def __init__(self, phase: int, ref: dict | None = None, sed: str = "one-sided"):
        self.phase, self.space, self.sed = phase, PHASES[phase]["vars"], sed
        self.vars = list(self.space)
        self.fixed = dict(PHASES[phase]["fixed"])
        if phase == 2:
            if not ref:
                raise ValueError("phase 2 needs --ref <job_id> (the phase-1 design whose L, alpha, collar_w, m, h_cut are kept)")
            self.fixed.update({k: ref[k] for k in ("L", "alpha", "collar_w", "m", "h_cut")})
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
        if not legacy and float(d.get("cap_h", -1.0)) != CONST["cap_h"]:
            return False
        for k, val in self.fixed.items():
            if abs(float(d.get(k, G.M_LEGACY if k == "m" else (0.0 if k == "collar_w" else -999))) - float(val)) > 1e-6:
                if k == "h_cut":
                    if abs(float(spec.get("h_cut", 25.0)) - float(val)) > 1e-6:
                        return False
                    continue
                return False
        return all(self.space[k][0] - 1e-9 <= float({**d, "h_cut": spec.get("h_cut", 25.0), "collar_w": d.get("collar_w", 0.0),
                                                      "m": d.get("m", G.M_LEGACY)}[k]) <= self.space[k][1] + 1e-9 for k in self.vars)

    def spec_of(self, u, tag: str) -> dict:
        d, h = self.design_of(u)
        return {**S.design_spec(d, f"neck{self.phase}", tag), "model": "m1", "h_cut": h, **FRIC}


def objectives(r: dict | None, sed: str) -> tuple[list[float], float, bool]:
    if not r or "failed" in r or "f1_p95_um" not in r:
        return [math.nan, math.nan], math.nan, False
    bl = r.get("bone_loss") or {}
    loss = bl.get("total_mm3")
    if loss is None:
        loss = (r.get("templating") or {}).get("volume")
    g7 = r.get("f2_g7_loss_pct")
    if loss is None or g7 is None or r.get("vm_p99") is None:
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(r["f1_p95_um"], 1e-3)), float(loss)]
    c_vm = (r["vm_p99"] - VM_LIMIT) / VM_LIMIT
    c_sed = {"one-sided": (g7 - SED_LIMIT) / SED_LIMIT, "abs": (abs(g7) - SED_LIMIT) / SED_LIMIT, "none": -1.0}[sed]
    return y, float(max(c_vm, c_sed)), all(np.isfinite(y))


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
        y, c, ok = objectives(J.result(d.name), ph.sed)
        if not ok:
            continue
        seen.add(key)
        X.append(ph.to_unit(dsg, h)); Y.append(y); C.append([c]); ids.append(d.name)
    n = len(ph.vars)
    return (np.array(X).reshape(-1, n), np.array(Y).reshape(-1, 2), np.array(C).reshape(-1, 1), ids)


def _feasible(args) -> bool:
    u, phase, ref = args
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    ph = Phase(phase, ref)
    d, h = ph.design_of(u)
    r = G.template(G.Stem3D(**d), _FM["fm"].with_cut(h))
    return bool(r["fit"] and r["A0"] >= S.MIN_A0)


def gated_pool(ph: Phase, n: int = 8192, seed: int = 0, workers: int = 6) -> np.ndarray:
    from scipy.stats import qmc
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((J.code_hash() + json.dumps(ph.space, sort_keys=True) + json.dumps(ph.fixed, sort_keys=True)
                        + json.dumps(CONST) + f"{n}_{seed}").encode()).hexdigest()[:8]
    f = J.RESULTS / "pools" / f"neckopt_p{ph.phase}_n{n}_s{seed}_{key}.npy"
    if f.exists():
        return np.load(f)
    U = qmc.Sobol(len(ph.vars), scramble=True, seed=50_000 + 100 * ph.phase + seed).random(n)
    with Pool(workers) as p:
        keep = np.array(p.map(_feasible, [(u, ph.phase, ph.ref) for u in U], chunksize=32))
    f.parent.mkdir(exist_ok=True)
    np.save(f, U[keep])
    f.with_suffix(".json").write_text(json.dumps({"phase": ph.phase, "n": n, "seed": seed, "feasible": int(keep.sum()), "rate": float(keep.mean()),
                                                  "space": ph.space, "fixed": ph.fixed}))
    print(f"[neckopt p{ph.phase}] pool: {int(keep.sum())}/{n} feasible", flush=True)
    return U[keep]


def evaluate(ph: Phase, U, tag: str):
    ids = [J.submit(ph.spec_of(u, tag)) for u in U]
    res = S.wait_for(ids)
    out = [objectives(res[j], ph.sed) for j in ids]
    return (np.array([o[0] for o in out], float), np.array([[o[1]] for o in out], float), np.array([o[2] for o in out], bool), ids)


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0] if (C[:, 0] <= 0).any() else Y
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def bo(ph: Phase, n_rounds: int, n_init: int, q: int, seed: int, workers: int, legacy_warm: bool) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset(ph, legacy_warm)
    pool = gated_pool(ph, seed=seed, workers=workers)
    used = np.zeros(len(pool), bool)
    recs = []
    out = out_path(ph.phase)
    if out.exists():                                                     # 续跑
        prev = json.loads(out.read_text())
        if prev.get("space") == {k: list(v) for k, v in ph.space.items()} and prev.get("fixed") == ph.fixed:
            recs = prev["records"]
            for r in recs:
                used[r["pool_idx"]] = True
                # 约束形式（--sed）可能变了：按当前形式从作业结果重算可行性，记录里同时保留原始 G7 与应力
                y, c, ok = objectives(J.result(r["job_id"]), ph.sed)
                r["y"], r["c"], r["ok"] = [float(v) for v in y], [float(c)], bool(ok)
                res = J.result(r["job_id"]) or {}
                r["g7_pct"], r["vm_p99"] = res.get("f2_g7_loss_pct"), res.get("vm_p99")
            if prev.get("sed") != ph.sed:
                print(f"[neckopt p{ph.phase}] constraint form changed {prev.get('sed')} -> {ph.sed}; feasibility recomputed for {len(recs)} records", flush=True)
    state = {"phase": ph.phase, "space": ph.space, "fixed": ph.fixed, "const": CONST, "sed": ph.sed, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
             "ref": ph.ref, "n_init": n_init, "q": q, "n_rounds": n_rounds, "warm_start_n": int(len(X0)), "warm_start_ids": ids0,
             "pool_size": int(len(pool)), "records": recs}

    def save():
        state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out.write_text(json.dumps(state, indent=1, default=float))

    print(f"[neckopt p{ph.phase}] vars {ph.vars}; warm start {len(X0)} ({int((C0[:, 0] <= 0).sum()) if len(C0) else 0} feasible); "
          f"pool {len(pool)}; existing records {len(recs)}; sed={ph.sed}", flush=True)

    def run_batch(idx, tag, rnd):
        Yn, Cn, okn, ids = evaluate(ph, pool[idx], tag)
        for i, y, c, ok, j in zip(idx, Yn, Cn, okn, ids):
            d, h = ph.design_of(pool[i])
            res = J.result(j) or {}
            recs.append({"pool_idx": int(i), "x": pool[i].tolist(), "y": [float(v) for v in y], "c": [float(v) for v in c], "ok": bool(ok),
                         "round": rnd, "job_id": j, "h_cut": h, "design": {k: d[k] for k in ph.vars if k in d},
                         "g7_pct": res.get("f2_g7_loss_pct"), "vm_p99": res.get("vm_p99"), "f1_p95_um": res.get("f1_p95_um")})
        save()
        return okn

    if n_init > 0 and not any(r["round"] == 0 for r in recs):
        idx = np.arange(min(n_init, len(pool)))                           # Sobol 顺序的前 n_init 个 = 准随机初始点
        used[idx] = True
        okn = run_batch(idx, "init", 0)
        print(f"[neckopt p{ph.phase}] init: {int(okn.sum())}/{len(idx)} ok", flush=True)
    done_rounds = max([r["round"] for r in recs], default=0)
    for rnd in range(done_rounds + 1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        refp = ref_point(Y, C)
        model = mobo.fit_models(X, Y, C)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, refp, pool[free], q, 2, 1, (50_000 + ph.phase * 100 + seed) * 1000 + rnd)
        idx = free[pick]
        used[idx] = True
        acq_s = time.perf_counter() - t0
        okn = run_batch(idx, f"r{rnd}", rnd)
        feas = [np.array(r["y"]) for r in recs if r["ok"] and r["c"][0] <= 0]
        ys = np.vstack([Y[C[:, 0] <= 0]] + [f[None] for f in feas]) if (C[:, 0] <= 0).any() or feas else None
        hv = mobo.hypervolume(ys, refp) if ys is not None and len(ys) else float("nan")
        last = recs[-len(idx):]
        print(f"[neckopt p{ph.phase}] round {rnd}: +{int(okn.sum())}/{len(idx)} ok; "
              f"{[{k: round(v, 1) for k, v in r['design'].items()} | {'h': round(r['h_cut'], 1)} for r in last]}; HV {hv:.4g}; acq {acq_s:.0f} s", flush=True)
        state["ref_point"] = refp.tolist()
        save()
    return state


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
    for r in sorted(feas, key=lambda r: r["y"][0])[:6]:
        print(f"  {10 ** r['y'][0]:6.1f} µm  loss {r['y'][1]:7.0f} mm³  {r['design']}  h_cut {r['h_cut']:.1f}  {r['job_id']}")


def load_ref(job_id: str) -> dict:
    spec = json.loads((J.QROOT / job_id / "spec.json").read_text())
    d = spec["design"]
    return {"L": d["L"], "alpha": d["alpha"], "collar_w": d.get("collar_w", 0.0), "m": d.get("m", G.M_LEGACY), "h_cut": spec.get("h_cut", 25.0),
            "job_id": job_id}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dataset", "pool", "bo", "status"])
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--ref", default=None, help="phase 2: phase-1 job id whose L, alpha, collar_w, m, h_cut are kept")
    ap.add_argument("--sed", choices=["one-sided", "abs", "none"], default="one-sided")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--init", type=int, default=16)
    ap.add_argument("--q", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--warm", choices=["family", "legacy"], default="family")
    a = ap.parse_args()
    ref = load_ref(a.ref) if a.ref else None
    ph = Phase(a.phase, ref, a.sed)
    if a.cmd == "dataset":
        X, Y, C, ids = dataset(ph, a.warm == "legacy")
        print(json.dumps({"n": int(len(X)), "feasible": int((C[:, 0] <= 0).sum()) if len(C) else 0, "ids": ids}, indent=1))
    elif a.cmd == "pool":
        print(gated_pool(ph, seed=a.seed, workers=a.workers).shape)
    elif a.cmd == "status":
        status(a.phase)
    else:
        bo(ph, a.rounds, a.init, a.q, a.seed, a.workers, a.warm == "legacy")
