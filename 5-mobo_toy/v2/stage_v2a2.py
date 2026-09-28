"""V2A-2（长度下限扩到 20 mm 之后，在 Linux 上跑）：

    remap    把种子 0 的 bo_s0.json（旧单位坐标，L 40–90）重映射到新坐标；重建 reference.json（x 由物理设计反算）
    probe    短柄探针：L 20–40 mm 每 5 mm 取 per_bin 个可行设计（其余变量 Sobol），全部 FE → results/probe_short.json
    warm     热启动 BO：GP 用全部已解设计（2.0 mm，标准变体）训练，在新池上 qLogNEHVI 选点 n_rounds × q
             → results/bo_warm_s<seed>.json
    run      顺序驱动：等 bo_s0.json → remap → probe → 并行两个 warm 种子 → results/V2A2_DONE
所有评估经队列（jobs.submit + stage_v2a.wait_for），幂等。
"""
from __future__ import annotations

import json
import math
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

OLD_L = (40.0, 90.0)
MIN_A0 = math.pi * 7.0 ** 2


def _remap_x(x, old=OLD_L, new=None):
    new = new or G.DESIGN["L"]
    x = list(x)
    L = old[0] + (old[1] - old[0]) * x[0]
    x[0] = (L - new[0]) / (new[1] - new[0])
    return x


def remap() -> dict:
    out = {}
    f = J.RESULTS / "bo_s0.json"
    if f.exists():
        b = json.loads(f.read_text())
        if b.get("L_range") != list(G.DESIGN["L"]):
            b["x"] = [_remap_x(x) for x in b["x"]]
            b["L_range"] = list(G.DESIGN["L"])
            b["remapped_from_L_range"] = list(OLD_L)
            f.write_text(json.dumps(b, indent=1, default=float))
            out["bo_s0"] = "remapped"
        else:
            out["bo_s0"] = "already in new coordinates"
    ref = S.reference_rebuild()
    ref["L_range"] = list(G.DESIGN["L"])
    (J.RESULTS / "reference.json").write_text(json.dumps(ref, indent=1, default=float))
    out["reference"] = f"rebuilt, n_ok {ref['n_ok']}"
    return out


def solved_dataset(margin: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """全部已解设计（生产网格、标准变体、去重）：X（12 维单位坐标，含皮质余量 m）、Y、C、job_id。
    margin=None 取全部尺寸规则；给定 margin 只取该余量的作业。"""
    import problem_v2a as PB
    seen, X, Y, C, ids = {}, [], [], [], []
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
        if margin is not None and abs(dsg["m"] - float(margin)) > 1e-9:
            continue
        key = json.dumps(dsg, sort_keys=True)
        if key in seen:
            continue
        r = J.result(d.name)
        y, c, ok = PB.objectives(r)
        if not ok:
            continue
        seen[key] = 1
        X.append(G.to_unit(dsg)); Y.append(y); C.append([c]); ids.append(d.name)
    return np.array(X), np.array(Y), np.array(C), ids


def probe(per_bin: int = 8, seed: int = 55) -> dict:
    import femur_real as FR
    import problem_v2a as PB
    from scipy.stats import qmc
    fm = FR.build()
    U = iter(qmc.Sobol(len(G.VARS), scramble=True, seed=seed).random(8192))
    chosen = []
    for lo in (20.0, 25.0, 30.0, 35.0):
        n = 0
        while n < per_bin:
            u = next(U)
            d = G.from_unit(u)
            d["L"] = lo + 5.0 * u[0]
            st = G.Stem3D(**d)
            r = G.template(st, fm)
            if r["fit"] and r["A0"] >= MIN_A0:
                chosen.append(d); n += 1
    J.submit(S.intact_spec(S.H_PROD))
    ids = [J.submit(S.design_spec(d, "probe", f"L{d['L']:.0f}_{i}")) for i, d in enumerate(chosen)]
    res = S.wait_for(ids)
    rows = []
    for d, j in zip(chosen, ids):
        y, c, ok = PB.objectives(res[j])
        rows.append({"job_id": j, "design": d, "y": y, "c": c, "ok": ok,
                     "f1_um": res[j].get("f1_p95_um") if res[j] and "f1_p95_um" in res[j] else None,
                     "dsed_pct": abs(res[j]["f2_g7_loss_pct"]) if res[j] and "f2_g7_loss_pct" in res[j] else None,
                     "A0": (res[j].get("templating") or {}).get("A0") if res[j] else None,
                     "failed": res[j].get("failed") if res[j] else None})
    out = {"per_bin": per_bin, "seed": seed, "n": len(rows), "n_ok": sum(r["ok"] for r in rows), "rows": rows}
    (J.RESULTS / "probe_short.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def warm(seed: int, n_rounds: int = 8, q: int = 4) -> dict:
    import mobo
    import problem_v2a as PB
    mobo.fit_gp = S._fit_gp_unit
    ref = np.array(S.ref_point())
    prob = PB.V2AProblem(ref.tolist(), "warm", S.H_PROD)
    pool = PB.gated_pool(8192, 100 + seed)
    X0, Y0, C0, ids0 = solved_dataset()
    used = np.zeros(len(pool), bool)
    recs, timing = [], []
    print(f"[warm s{seed}] start: {len(X0)} solved designs, pool {len(pool)}, ref {ref.round(3).tolist()}", flush=True)
    for rnd in range(1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r["ok"]]
        X = np.vstack([X0] + [np.array(r["x"])[None] for r in good]) if good else X0
        Y = np.vstack([Y0] + [np.array(r["y"])[None] for r in good]) if good else Y0
        C = np.vstack([C0] + [np.array(r["c"])[None] for r in good]) if good else C0
        model = mobo.fit_models(X, Y, C)
        free = np.nonzero(~used)[0]
        pick = mobo.propose(model, X, ref, pool[free], q, 2, 1, (100 + seed) * 1000 + rnd)
        idx = free[pick]
        used[idx] = True
        timing.append(time.perf_counter() - t0)
        Yn, Cn, okn = prob.evaluate(pool[idx], seed=seed, round=rnd, method="warm")
        for x, y, c, ok in zip(pool[idx], Yn, Cn, okn):
            recs.append({"x": x.tolist(), "y": [float(v) for v in y], "c": [float(v) for v in c], "ok": bool(ok), "round": rnd})
        ys = np.vstack([Y0] + [np.array(r["y"])[None] for r in recs if r["ok"] and r["c"][0] <= 0])
        print(f"[warm s{seed}] round {rnd}: +{int(okn.sum())}/{q} ok, HV(all) = {mobo.hypervolume(ys, ref):.4g}, acq {timing[-1]:.1f} s",
              flush=True)
    out = {"seed": seed, "pool_seed": 100 + seed, "pool_size": len(pool), "warm_start_n": len(X0), "warm_start_ids": ids0,
           "ref_point": ref.tolist(), "L_range": list(G.DESIGN["L"]), "n_rounds": n_rounds, "q": q,
           "x": [r["x"] for r in recs], "y": [r["y"] for r in recs], "c": [r["c"] for r in recs], "ok": [r["ok"] for r in recs],
           "round": [r["round"] for r in recs], "acq_s": timing, "rows": prob.rows}
    (J.RESULTS / f"bo_warm_s{seed}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def run(seeds=(0, 1)) -> None:
    while not (J.RESULTS / "bo_s0.json").exists():
        time.sleep(60)
    print("bo_s0 finished; remap:", remap(), flush=True)
    p = probe()
    print(f"probe: {p['n_ok']}/{p['n']} ok", flush=True)
    logs = pathlib.Path.home() / "mobo_toy_v2" / "logs"
    procs = []
    for s in seeds:
        procs.append(subprocess.Popen([str(pathlib.Path.home() / "mobo_toy_v2" / "run.sh"), "v2/stage_v2a2.py", "warm", "--seed", str(s)],
                                      cwd=str(HERE.parent), stdout=open(logs / f"warm_s{s}.log", "w"), stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True))
    for pr in procs:
        pr.wait()
    (J.RESULTS / "V2A2_DONE").write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    print("V2A2 done", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["remap", "probe", "warm", "run"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "run":
        run()
    else:
        res = {"remap": remap, "probe": probe, "warm": lambda: warm(a.seed)}[a.cmd]()
        print(json.dumps({k: v for k, v in res.items() if k not in ("rows", "x", "y", "c", "warm_start_ids")}, indent=1, default=float))
