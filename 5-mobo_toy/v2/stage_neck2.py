"""颈部柄第二阶段（用户 2026-10-02 下午）：在第一阶段九类里选出的两类（综合最优、柄最短）内，优化截面形状与截骨深度。Linux 上跑。

类 = 柄长 × 领宽，第一阶段的记法：S/M/L = 25/30/35 mm，后面的数字 = 领宽 mm（S4 = 短柄、宽领）。
固定（全部）：插入角 40°、ρ_tip 0.5、q 1.0、皮质余量 m −0.25、领厚 2.5 mm；固定（按类）：L、collar_w。
变量 8 个：h_cut 25–40（截骨面距头心）、λ、γ_ml、γ_ap、n_a、n_p、τ_a、τ_p（圆、椭圆都是这组参数的特例）。
目标（最小化）：y1 = log10(柄身可恢复微动 P95, µm)；y2 = 骨量损失 = 截骨 + 锉骨（mm³）。
约束（≤ 0）：Gruen 7 |ΔSED| ≤ 30 %；柄 von Mises P99 ≤ 440 MPa。
模型：M1 界面模型（领与截骨面接触），过盈 0.025 mm，slip_tol 2.5e-4，生产网格 2.0 mm —— 与第一阶段相同。
一个 GP 两类共用：输入 = 8 个变量 + L + 领宽（归一化），热启动 = 第一阶段全部颈部柄作业（同模型，h_cut 25）。
每轮每类提 q 个（默认 2），初始每类 n_init 个 Sobol 点。

    python v2/stage_neck2.py dataset
    python v2/stage_neck2.py pool --classes M2,S4
    python v2/stage_neck2.py bo --classes M2,S4 --rounds 8 --init 8      → results/neck2_bo.json（每轮覆盖）
    python v2/stage_neck2.py status
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

SPACE = {"h_cut": (25.0, 40.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0), "n_p": (2.0, 6.0),
         "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)}
VARS8 = list(SPACE)
CLASS_SPACE = {"L": (25.0, 35.0), "collar_w": (0.0, 4.0)}          # GP 的两个“类”输入；只取第一阶段的离散水平
FIXED = {"alpha": 40.0, "rho_tip": 0.5, "q": 1.0, "m": G.M_LEGACY}
LEN = {"S": 25.0, "M": 30.0, "L": 35.0}
FRIC = {"slip_tol": 2.5e-4, "delta": 0.025}
SED_LIMIT, VM_LIMIT = 30.0, 440.0
OUT = J.RESULTS / "neck2_bo.json"
_FM = {}


def parse_class(name: str) -> tuple[float, float]:
    return LEN[name[0].upper()], float(name[1:])


def design_of(u8, L: float, w: float) -> tuple[dict, float]:
    p = {k: SPACE[k][0] + float(x) * (SPACE[k][1] - SPACE[k][0]) for k, x in zip(VARS8, u8)}
    d = {"L": float(L), "rho_tip": FIXED["rho_tip"], "q": FIXED["q"], "lam": p["lam"], "g_ml": p["g_ml"], "g_ap": p["g_ap"],
         "n_a": p["n_a"], "n_p": p["n_p"], "tau_a": p["tau_a"], "tau_p": p["tau_p"], "alpha": FIXED["alpha"], "m": FIXED["m"]}
    if w > 0:
        d.update(collar_w=float(w), collar_t=G.COLLAR_T)
    return d, p["h_cut"]


def to_unit10(d: dict, h_cut: float) -> np.ndarray:
    p = {"h_cut": h_cut, **{k: d[k] for k in VARS8 if k != "h_cut"}}
    u = [(p[k] - SPACE[k][0]) / (SPACE[k][1] - SPACE[k][0]) for k in VARS8]
    u += [(d["L"] - CLASS_SPACE["L"][0]) / (CLASS_SPACE["L"][1] - CLASS_SPACE["L"][0]),
          (d.get("collar_w", 0.0) - CLASS_SPACE["collar_w"][0]) / (CLASS_SPACE["collar_w"][1] - CLASS_SPACE["collar_w"][0])]
    return np.clip(np.array(u, float), 0.0, 1.0)


def unit10(u8, L: float, w: float) -> np.ndarray:
    d, h = design_of(u8, L, w)
    return to_unit10(d, h)


def is_neck_family(spec: dict) -> bool:
    d = spec.get("design") or {}
    return (spec.get("model") == "m1" and spec.get("stage") in ("collar", "neck2") and float(d.get("alpha", 0)) == FIXED["alpha"]
            and float(d.get("rho_tip", 0)) == FIXED["rho_tip"] and float(d.get("q", 0)) == FIXED["q"]
            and spec.get("h_int") == S.H_PROD and spec.get("slip_tol") == FRIC["slip_tol"] and spec.get("delta") == FRIC["delta"])


def objectives(r: dict | None) -> tuple[list[float], float, bool]:
    if not r or "failed" in r or "f1_p95_um" not in r:
        return [math.nan, math.nan], math.nan, False
    bl = r.get("bone_loss") or {}
    loss = bl.get("total_mm3")
    if loss is None:
        loss = (r.get("templating") or {}).get("volume")
    if loss is None or r.get("f2_g7_loss_pct") is None or r.get("vm_p99") is None:
        return [math.nan, math.nan], math.nan, False
    y = [math.log10(max(r["f1_p95_um"], 1e-3)), float(loss)]
    c = max((abs(r["f2_g7_loss_pct"]) - SED_LIMIT) / SED_LIMIT, (r["vm_p99"] - VM_LIMIT) / VM_LIMIT)
    return y, float(c), all(np.isfinite(y))


def dataset() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """全部已解的颈部柄作业（第一阶段 + 本阶段），映射到 10 维。"""
    seen, X, Y, C, ids = set(), [], [], [], []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") not in ("design", "variant") or not is_neck_family(spec):
            continue
        dsg = dict(spec["design"])
        h = float(spec.get("h_cut", 25.0))
        key = json.dumps({**dsg, "h_cut": h}, sort_keys=True)
        if key in seen:
            continue
        y, c, ok = objectives(J.result(d.name))
        if not ok:
            continue
        seen.add(key)
        X.append(to_unit10(dsg, h)); Y.append(y); C.append([c]); ids.append(d.name)
    return np.array(X), np.array(Y), np.array(C), ids


def _feasible(args) -> bool:
    u8, L, w = args
    if "fm" not in _FM:
        _FM["fm"] = FR.build()
    d, h = design_of(u8, L, w)
    fm = _FM["fm"].with_cut(h)
    r = G.template(G.Stem3D(**d), fm)
    return bool(r["fit"] and r["A0"] >= S.MIN_A0)


def gated_pool(cls: str, n: int = 8192, seed: int = 0, workers: int = 10) -> np.ndarray:
    from scipy.stats import qmc
    L, w = parse_class(cls)
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((J.code_hash() + json.dumps(SPACE, sort_keys=True) + f"{cls}_{n}_{seed}").encode()).hexdigest()[:8]
    f = J.RESULTS / "pools" / f"neck2pool_{cls}_n{n}_s{seed}_{key}.npy"
    if f.exists():
        return np.load(f)
    U = qmc.Sobol(len(VARS8), scramble=True, seed=40_000 + seed).random(n)
    with Pool(workers) as p:
        keep = np.array(p.map(_feasible, [(u, L, w) for u in U], chunksize=32))
    f.parent.mkdir(exist_ok=True)
    np.save(f, U[keep])
    f.with_suffix(".json").write_text(json.dumps({"class": cls, "n": n, "seed": seed, "feasible": int(keep.sum()), "rate": float(keep.mean())}))
    print(f"[neck2] pool {cls}: {int(keep.sum())}/{n} feasible", flush=True)
    return U[keep]


def spec_of(u8, cls: str, tag: str) -> dict:
    L, w = parse_class(cls)
    d, h = design_of(u8, L, w)
    return {**S.design_spec(d, "neck2", f"{cls}_{tag}"), "model": "m1", "h_cut": h, **FRIC}


def evaluate(items: list[tuple[np.ndarray, str]], tag: str):
    ids = [J.submit(spec_of(u, cls, tag)) for u, cls in items]
    res = S.wait_for(ids)
    out = [objectives(res[j]) for j in ids]
    return (np.array([o[0] for o in out], float), np.array([[o[1]] for o in out], float), np.array([o[2] for o in out], bool), ids)


def ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0] if (C[:, 0] <= 0).any() else Y
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def _save(state: dict) -> None:
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT.write_text(json.dumps(state, indent=1, default=float))


def bo(classes: list[str], n_rounds: int = 8, n_init: int = 8, q: int = 2, seed: int = 0) -> dict:
    import mobo
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = dataset()
    pools = {c: gated_pool(c, seed=seed) for c in classes}
    used = {c: np.zeros(len(pools[c]), bool) for c in classes}
    recs = []
    if OUT.exists():                                                   # 续跑：读回已有记录（同一组类）
        prev = json.loads(OUT.read_text())
        if prev.get("classes") == classes:
            recs = prev["records"]
            for r in recs:
                if r.get("pool_idx") is not None:
                    used[r["class"]][r["pool_idx"]] = True
    state = {"classes": classes, "space": SPACE, "fixed": FIXED, "class_space": CLASS_SPACE, "sed_limit": SED_LIMIT, "vm_limit": VM_LIMIT,
             "n_init": n_init, "q_per_class": q, "n_rounds": n_rounds, "warm_start_n": int(len(X0)), "warm_start_ids": ids0,
             "pool_size": {c: int(len(pools[c])) for c in classes}, "records": recs}
    print(f"[neck2] classes {classes}; warm start {len(X0)} ({int((C0[:, 0] <= 0).sum())} feasible); pools "
          f"{ {c: len(pools[c]) for c in classes} }; existing records {len(recs)}", flush=True)

    def run_batch(items, tag, rnd):
        Yn, Cn, okn, ids = evaluate([(pools[c][i], c) for c, i in items], tag)
        for (c, i), y, cc, ok, j in zip(items, Yn, Cn, okn, ids):
            d, h = design_of(pools[c][i], *parse_class(c))
            recs.append({"class": c, "pool_idx": int(i), "x": unit10(pools[c][i], *parse_class(c)).tolist(), "y": [float(v) for v in y],
                         "c": [float(v) for v in cc], "ok": bool(ok), "round": rnd, "job_id": j, "h_cut": h,
                         "design": {k: d[k] for k in ("lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")}})
        _save(state)
        return okn

    if n_init > 0 and not any(r["round"] == 0 for r in recs):
        items = [(c, i) for c in classes for i in range(min(n_init, len(pools[c])))]   # Sobol 顺序的前 n_init 个即准随机初始点
        for c, i in items:
            used[c][i] = True
        okn = run_batch(items, "init", 0)
        print(f"[neck2] init: {int(okn.sum())}/{len(items)} ok", flush=True)
    done_rounds = max([r["round"] for r in recs], default=0)
    for rnd in range(done_rounds + 1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        refp = ref_point(Y, C)
        model = mobo.fit_models(X, Y, C)
        items = []
        for k, c in enumerate(classes):
            free = np.nonzero(~used[c])[0]
            P10 = np.array([unit10(pools[c][i], *parse_class(c)) for i in free])
            pick = mobo.propose(model, X, refp, P10, q, 2, 1, (40_000 + seed) * 1000 + rnd * 10 + k)
            for i in free[pick]:
                used[c][i] = True
                items.append((c, int(i)))
        acq_s = time.perf_counter() - t0
        okn = run_batch(items, f"r{rnd}", rnd)
        ys = np.vstack([Y[C[:, 0] <= 0]] + [np.array(r["y"])[None] for r in recs[-len(items):] if r["ok"] and r["c"][0] <= 0])
        print(f"[neck2] round {rnd}: +{int(okn.sum())}/{len(items)} ok; h_cut {[round(r['h_cut'], 1) for r in recs[-len(items):]]}; "
              f"HV(all feasible) {mobo.hypervolume(ys, refp):.4g}; acq {acq_s:.0f} s", flush=True)
        state["ref_point"] = refp.tolist()
        _save(state)
    return state


def status() -> None:
    if not OUT.exists():
        print("no results yet"); return
    st = json.loads(OUT.read_text())
    recs = st["records"]
    print(json.dumps({k: v for k, v in st.items() if k not in ("records", "warm_start_ids", "space", "fixed", "class_space")}, indent=1, default=float))
    for c in st["classes"]:
        rc = [r for r in recs if r["class"] == c and r["ok"]]
        feas = [r for r in rc if r["c"][0] <= 0]
        best = min(feas, key=lambda r: r["y"][0]) if feas else None
        print(c, f"evaluated {len([r for r in recs if r['class'] == c])}, ok {len(rc)}, feasible {len(feas)}",
              f"best micromotion {10 ** best['y'][0]:.1f} µm at h_cut {best['h_cut']:.1f}, loss {best['y'][1]:.0f} mm³ ({best['job_id']})" if best else "")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dataset", "pool", "bo", "status"])
    ap.add_argument("--classes", default="M2,S4")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--init", type=int, default=8)
    ap.add_argument("--q", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    classes = [c.strip() for c in a.classes.split(",") if c.strip()]
    if a.cmd == "dataset":
        X, Y, C, ids = dataset()
        print(json.dumps({"n": int(len(X)), "feasible": int((C[:, 0] <= 0).sum()) if len(C) else 0, "ids": ids,
                          "log_f1_range": [float(Y[:, 0].min()), float(Y[:, 0].max())] if len(Y) else None,
                          "loss_range": [float(Y[:, 1].min()), float(Y[:, 1].max())] if len(Y) else None}, indent=1))
    elif a.cmd == "pool":
        for c in classes:
            print(c, gated_pool(c, seed=a.seed).shape)
    elif a.cmd == "status":
        status()
    else:
        bo(classes, a.rounds, a.init, a.q, a.seed)
