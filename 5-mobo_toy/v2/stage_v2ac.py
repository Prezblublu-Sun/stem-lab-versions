"""V2A-C：只接触松质骨的尺寸规则（柄面离内膜面 ≥ MARGIN mm，用户 2026-09-28 13:30 要求），在 Linux 上跑。

    ref      同一批 64 个参考设计（取自规则 A 的 ref_r*_h2 作业）在新规则下重算 → results/c_reference.json（成对比较）
    probe    同一批 32 个短柄探针设计在新规则下重算 → results/c_probe.json
    warm     热启动 BO：只用新规则下的已解设计训练，在新规则的可行池上选点 → results/bo_cwarm_s<seed>.json
    run      ref → probe → 并行两个 warm 种子 → results/V2AC_DONE
作业说明里带 margin，与规则 A 的作业在同一队列里并存、互不混淆（作业 id 含 margin）。
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

MARGIN = 1.0                      # mm，柄面到内膜面的最小距离


def _rule_a_design(prefix: str) -> dict | None:
    cands = [d for d in J.QROOT.glob(prefix + "_*") if (d / "spec.json").exists() and float(json.loads((d / "spec.json").read_text()).get("margin", 0)) == 0]
    if not cands:
        return None
    d = min(cands, key=lambda p: p.stat().st_mtime)
    return json.loads((d / "spec.json").read_text())["design"], d.name


def _rows(designs, ids, res, rule_a_ids=None):
    import problem_v2a as PB
    rows = []
    for k, (d, j) in enumerate(zip(designs, ids)):
        r = res[j]
        y, c, ok = PB.objectives(r)
        row = {"i": k, "job_id": j, "x": G.to_unit(d).tolist(), "design": d, "y": y, "c": c, "ok": ok,
               "A0": (r.get("templating") or {}).get("A0") if r else None, "failed": r.get("failed") if r else None}
        if rule_a_ids:
            ra = J.result(rule_a_ids[k]) or {}
            row["rule_a"] = {"job_id": rule_a_ids[k], "A0": (ra.get("templating") or {}).get("A0"),
                             "f1_p95_um": ra.get("f1_p95_um"), "f2_g7_loss_pct": ra.get("f2_g7_loss_pct"), "vm_p99": ra.get("vm_p99")}
        rows.append(row)
    return rows


def ref(n: int = 64) -> dict:
    designs, a_ids = [], []
    for i in range(n):
        got = _rule_a_design(f"ref_r{i}_h{S.H_PROD:g}")
        if got is None:
            raise FileNotFoundError(f"rule-A reference design r{i} not found in queue")
        designs.append(got[0]); a_ids.append(got[1])
    J.submit(S.intact_spec(S.H_PROD))
    ids = [J.submit(S.design_spec(d, "cref", f"r{i}", margin=MARGIN)) for i, d in enumerate(designs)]
    res = S.wait_for(ids)
    rows = _rows(designs, ids, res, a_ids)
    out = {"n": n, "margin_mm": MARGIN, "rows": rows, "n_ok": sum(r["ok"] for r in rows),
           "n_infeasible_L1": sum(1 for r in rows if r["failed"] and r["failed"]["level"] == "L1"),
           "L_range": list(G.DESIGN["L"]), "objective_y2": "|dSED| Gruen 7 (%)"}
    (J.RESULTS / "c_reference.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def probe() -> dict:
    src = json.loads((J.RESULTS / "probe_short.json").read_text())
    designs = [r["design"] for r in src["rows"]]
    a_ids = [r["job_id"] for r in src["rows"]]
    ids = [J.submit(S.design_spec(d, "cprobe", f"L{d['L']:.0f}_{i}", margin=MARGIN)) for i, d in enumerate(designs)]
    res = S.wait_for(ids)
    rows = _rows(designs, ids, res, a_ids)
    out = {"n": len(rows), "margin_mm": MARGIN, "rows": rows, "n_ok": sum(r["ok"] for r in rows),
           "n_infeasible_L1": sum(1 for r in rows if r["failed"] and r["failed"]["level"] == "L1")}
    (J.RESULTS / "c_probe.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def c_ref_point() -> list[float]:
    rows = json.loads((J.RESULTS / "c_reference.json").read_text())["rows"]
    Y = np.array([r["y"] for r in rows if r["ok"] and r["c"] <= 0])
    lo, hi = Y.min(0), Y.max(0)
    return (hi + 0.1 * (hi - lo)).tolist()


def warm(seed: int, n_rounds: int = 8, q: int = 4) -> dict:
    import mobo
    import problem_v2a as PB
    mobo.fit_gp = S._fit_gp_unit
    ref_pt = np.array(c_ref_point())
    prob = PB.V2AProblem(ref_pt.tolist(), "cwarm", S.H_PROD, margin=MARGIN)
    pool = PB.gated_pool(8192, 200 + seed, margin=MARGIN)
    X0, Y0, C0, ids0 = S2.solved_dataset(margin=MARGIN)   # 只用留 1 mm 规则的数据（规则 B 单独的 BO；统一版见 stage_v2au）
    used = np.zeros(len(pool), bool)
    recs, timing = [], []
    print(f"[cwarm s{seed}] start: {len(X0)} solved designs (margin {MARGIN}), pool {len(pool)}, ref {ref_pt.round(3).tolist()}", flush=True)
    for rnd in range(1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        model = mobo.fit_models(X, Y, C)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, ref_pt, pool[free], q, 2, 1, (200 + seed) * 1000 + rnd)
        idx = free[pick]; used[idx] = True
        timing.append(time.perf_counter() - t0)
        Yn, Cn, okn = prob.evaluate(pool[idx], seed=seed, round=rnd, method="cwarm")
        for x, y, c, ok in zip(pool[idx], Yn, Cn, okn):
            recs.append({"x": x.tolist(), "y": [float(v) for v in y], "c": [float(v) for v in c], "ok": bool(ok), "round": rnd})
        ys = np.vstack([Y0] + [np.array(r["y"])[None] for r in recs if r["ok"] and r["c"][0] <= 0])
        print(f"[cwarm s{seed}] round {rnd}: +{int(okn.sum())}/{q} ok, HV(all) = {mobo.hypervolume(ys, ref_pt):.4g}, acq {timing[-1]:.1f} s", flush=True)
    out = {"seed": seed, "margin_mm": MARGIN, "pool_seed": 200 + seed, "pool_size": len(pool), "warm_start_n": len(X0),
           "warm_start_ids": ids0, "ref_point": ref_pt.tolist(), "L_range": list(G.DESIGN["L"]), "n_rounds": n_rounds, "q": q,
           "x": [r["x"] for r in recs], "y": [r["y"] for r in recs], "c": [r["c"] for r in recs], "ok": [r["ok"] for r in recs],
           "round": [r["round"] for r in recs], "acq_s": timing, "rows": prob.rows}
    (J.RESULTS / f"bo_cwarm_s{seed}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def run(seeds=(0, 1)) -> None:
    r = ref()
    print(f"cref: {r['n_ok']}/{r['n']} ok, {r['n_infeasible_L1']} infeasible under margin {MARGIN}", flush=True)
    while not (J.RESULTS / "probe_short.json").exists():          # 规则 A 的探针设计清单
        time.sleep(60)
    p = probe()
    print(f"cprobe: {p['n_ok']}/{p['n']} ok, {p['n_infeasible_L1']} infeasible", flush=True)
    logs = pathlib.Path.home() / "mobo_toy_v2" / "logs"
    procs = [subprocess.Popen([str(pathlib.Path.home() / "mobo_toy_v2" / "run.sh"), "v2/stage_v2ac.py", "warm", "--seed", str(s)],
                              cwd=str(HERE.parent), stdout=open(logs / f"cwarm_s{s}.log", "w"), stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, start_new_session=True) for s in seeds]
    for pr in procs:
        pr.wait()
    (J.RESULTS / "V2AC_DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    print("V2AC done", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ref", "probe", "warm", "run"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "run":
        run()
    else:
        res = {"ref": ref, "probe": probe, "warm": lambda: warm(a.seed)}[a.cmd]()
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "x", "y", "c", "warm_start_ids")}, indent=1, default=float))
