"""V2A-U：统一尺寸规则（皮质余量 m 为第 12 个设计变量，用户 2026-09-28 13:50 决定）的热启动 BO，在 Linux 上跑。

    uwarm    热启动 BO：训练集 = 全部已解设计（两种规则：m = −0.25 与 +1 的点，以及此后任意 m 的点），
             12 维候选池（每个点自带 m），qLogNEHVI 选点 n_rounds × q → results/bo_uwarm_s<seed>.json
    run      等规则 B 的成对重算（stage_v2ac.ref / probe，幂等）→ 并行两个 uwarm 种子 → results/V2AU_DONE
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402
import stage_v2a2 as S2  # noqa: E402
import stage_v2ac as SC  # noqa: E402


def u_ref_point(Y, C) -> np.ndarray:
    Yf = Y[C[:, 0] <= 0]
    lo, hi = Yf.min(0), Yf.max(0)
    return hi + 0.1 * (hi - lo)


def uwarm(seed: int, n_rounds: int = 8, q: int = 4) -> dict:
    import mobo
    import problem_v2a as PB
    mobo.fit_gp = S._fit_gp_unit
    X0, Y0, C0, ids0 = S2.solved_dataset(margin=None)
    ref_pt = u_ref_point(Y0, C0)
    prob = PB.V2AProblem(ref_pt.tolist(), "uwarm", S.H_PROD, margin=None)
    pool = PB.gated_pool(8192, 300 + seed, margin=None)
    used = np.zeros(len(pool), bool)
    recs, timing = [], []
    ms = 20 + 0 * X0[:, -1]
    print(f"[uwarm s{seed}] start: {len(X0)} solved designs (m levels: "
          f"{sorted(set(np.round(G.DESIGN['m'][0] + X0[:, -1] * (G.DESIGN['m'][1] - G.DESIGN['m'][0]), 2)))}), "
          f"pool {len(pool)}, ref {ref_pt.round(3).tolist()}", flush=True)
    for rnd in range(1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        model = mobo.fit_models(X, Y, C)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, ref_pt, pool[free], q, 2, 1, (300 + seed) * 1000 + rnd)
        idx = free[pick]; used[idx] = True
        timing.append(time.perf_counter() - t0)
        Yn, Cn, okn = prob.evaluate(pool[idx], seed=seed, round=rnd, method="uwarm")
        for x, y, c, ok in zip(pool[idx], Yn, Cn, okn):
            recs.append({"x": x.tolist(), "y": [float(v) for v in y], "c": [float(v) for v in c], "ok": bool(ok), "round": rnd,
                         "m_mm": float(G.from_unit(x)["m"])})
        ys = np.vstack([Y0] + [np.array(r["y"])[None] for r in recs if r["ok"] and r["c"][0] <= 0])
        print(f"[uwarm s{seed}] round {rnd}: +{int(okn.sum())}/{q} ok, m chosen = {[round(G.from_unit(x)['m'], 2) for x in pool[idx]]}, "
              f"HV(all) = {mobo.hypervolume(ys, ref_pt):.4g}, acq {timing[-1]:.1f} s", flush=True)
    out = {"seed": seed, "pool_seed": 300 + seed, "pool_size": len(pool), "warm_start_n": len(X0), "warm_start_ids": ids0,
           "ref_point": ref_pt.tolist(), "design_ranges": {k: list(v) for k, v in G.DESIGN.items()}, "n_rounds": n_rounds, "q": q,
           "x": [r["x"] for r in recs], "y": [r["y"] for r in recs], "c": [r["c"] for r in recs], "ok": [r["ok"] for r in recs],
           "round": [r["round"] for r in recs], "m_mm": [r["m_mm"] for r in recs], "acq_s": timing, "rows": prob.rows}
    (J.RESULTS / f"bo_uwarm_s{seed}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def run(seeds=(0, 1)) -> None:
    r = SC.ref()
    print(f"cref: {r['n_ok']}/{r['n']} ok, {r['n_infeasible_L1']} infeasible under margin {SC.MARGIN}", flush=True)
    while not (J.RESULTS / "probe_short.json").exists():
        time.sleep(60)
    p = SC.probe()
    print(f"cprobe: {p['n_ok']}/{p['n']} ok, {p['n_infeasible_L1']} infeasible", flush=True)
    logs = pathlib.Path.home() / "mobo_toy_v2" / "logs"
    procs = [subprocess.Popen([str(pathlib.Path.home() / "mobo_toy_v2" / "run.sh"), "v2/stage_v2au.py", "uwarm", "--seed", str(s)],
                              cwd=str(HERE.parent), stdout=open(logs / f"uwarm_s{s}.log", "w"), stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, start_new_session=True) for s in seeds]
    for pr in procs:
        pr.wait()
    (J.RESULTS / "V2AU_DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    print("V2AU done", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["uwarm", "run"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "run":
        run()
    else:
        res = uwarm(a.seed)
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "x", "y", "c", "warm_start_ids")}, indent=1, default=float))
