"""V2A 各阶段的控制器（在 Linux 上跑，nohup 常驻；本机只运行 solve_worker.py 求解）。

    serve        常驻：NEW → prep（进程池）→ READY；SOLVED → post → DONE
    status       队列概况与最近完成的作业
    e2e          完整股骨参照（生产网格）+ 1 个设计，跑通全链路
    signs        符号检查：扭转开/关、δ 0.1/0、μ 0.3/0.8、同设计重跑
下列阶段在后续加入：convergence（S2′）、reference（S4′）、bo（S5′）。
所有提交幂等（作业 id 由规格 + 代码哈希决定），重跑命中已完成作业。
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jobs as J  # noqa: E402

MIN_A0 = math.pi * 7.0 ** 2
H_PROD = 2.0                                  # 生产网格（S2′ 之前的默认，收敛研究后可能改）
BASE = dict(L=60, rho_tip=0.15, q=2.5, lam=1.9, g_ml=0.62, g_ap=0.42, n_a=5.0, n_p=3.0, tau_a=0.25, tau_p=0.05,
            alpha=20.0)                       # cases.EXAMPLES["boxy, calcar-heavy, early taper"]，真实股骨上可行（A0 309 mm²）


def design_spec(design: dict, stage: str, tag: str, h_int: float = H_PROD, **variant) -> dict:
    return {"kind": "design", "design": design, "h_int": h_int, "min_A0": MIN_A0, "stage": stage, "tag": tag, **variant}


def intact_spec(h_int: float, **variant) -> dict:
    tag = f"intact_h{h_int:g}" + "".join(f"_{k}{v:g}" for k, v in sorted(variant.items()))
    return {"kind": "intact", "h_int": h_int, "stage": "ref", "tag": tag, **variant}


PREP_MEM_GB = 12.0          # 每个建模子进程的地址空间上限（RLIMIT_AS，是虚拟地址空间不是常驻内存）。2026-10-02 11:29 与 11:49：一个作业
                            # 的网格生成涨到 13.6 GB 常驻被 OOM killer 杀掉，当时用的进程池整体报废，在建与排队的作业全部停摆；12:03 又因为
                            # “崩两次判失败”的规则误伤了 10 个同批作业；12:10 上限设 10 GB 时五个正常设计在网格阶段一起段错误（gmsh/OCC
                            # 多线程保留的虚拟地址空间远大于常驻），所以上限只能当最后的保险，设得比正常建模的虚拟占用高得多。
                            # 改为下面的独立子进程后，失控的建模只影响它自己的作业。
PREP_CMD = "import sys; sys.path.insert(0, 'v2'); import jobs as J; print(J.prep(sys.argv[1]))"


def _prep_limits() -> None:
    import resource
    lim = int(PREP_MEM_GB * 2 ** 30)
    resource.setrlimit(resource.RLIMIT_AS, (lim, lim))


def serve(n_prep: int = 5, poll: float = 10.0) -> None:
    """常驻服务：每个 NEW 作业用一个独立子进程建模（gmsh 单线程），最多 n_prep 个并行；后处理在主进程串行（很快）。
    子进程被 OOM 杀掉或段错误（gmsh 在内存上限下的典型表现）只影响它自己的作业：退出码非零且作业仍是 NEW → FAILED L3，
    退出码写进原因，子进程的输出在作业目录的 prep.log。"""
    import subprocess
    J.QROOT.mkdir(parents=True, exist_ok=True)
    running: dict[str, subprocess.Popen] = {}
    print(f"serve start {time.strftime('%H:%M:%S')} code={J.code_hash()} prep_mem={PREP_MEM_GB:g} GB n_prep={n_prep}", flush=True)
    while not (J.QROOT / "STOP_SERVE").exists():
        for d in sorted(J.QROOT.glob("*")):
            if not d.is_dir():
                continue
            s = J.state(d)
            if s == "NEW" and d.name not in running and len(running) < n_prep:
                with open(d / "prep.log", "ab") as log:
                    running[d.name] = subprocess.Popen([sys.executable, "-c", PREP_CMD, d.name], cwd=str(HERE.parent),
                                                       stdout=log, stderr=subprocess.STDOUT, preexec_fn=_prep_limits)
            elif s == "SOLVED":
                # 完整股骨参照必须先 DONE，设计作业的后处理才能进行
                spec = json.loads((d / "spec.json").read_text())
                if spec["kind"] in ("design", "variant"):
                    try:
                        J.explicit_ref(spec) or J.intact_ref(spec["h_int"], spec.get("E_canc"))
                    except FileNotFoundError:
                        continue
                print(f"{time.strftime('%H:%M:%S')} post {d.name}: {J.post(d.name)}", flush=True)
        for k in [k for k, p in running.items() if p.poll() is not None]:
            p = running.pop(k)
            d = J.QROOT / k
            st = J.state(d)
            if p.returncode != 0 and st == "NEW":
                sig = f" (signal {-p.returncode})" if p.returncode < 0 else ""
                J._fail(d, "L3", "prep", f"prep process exited with code {p.returncode}{sig} under a {PREP_MEM_GB:g} GB memory limit; "
                                         f"see prep.log in the job directory")
                st = "FAILED"
            print(f"{time.strftime('%H:%M:%S')} prep {k}: {st}" + (f" (exit {p.returncode})" if p.returncode else ""), flush=True)
        time.sleep(poll)
    for p in running.values():
        p.terminate()
    print("serve stop", flush=True)


def wait_for(ids: list[str], timeout_h: float = 48.0, poll: float = 30.0) -> dict:
    t0 = time.time()
    while True:
        st = {j: J.state(J.QROOT / j) for j in ids}
        if all(s in ("DONE", "FAILED") for s in st.values()):
            return {j: J.result(j) for j in ids}
        if time.time() - t0 > timeout_h * 3600:
            raise TimeoutError(f"jobs not finished: { {j: s for j, s in st.items() if s not in ('DONE', 'FAILED')} }")
        time.sleep(poll)


def _brief(r: dict | None) -> dict:
    if r is None:
        return {}
    if "failed" in r:
        return {"FAILED": r["failed"]["level"], "reason": r["failed"]["reason"][:160]}
    keys = ("f1_p95_um", "f2_g7_loss_pct", "f2_g1_loss_pct", "vm_p99", "frac_open", "gruen7", "gruen1")
    out = {k: round(r[k], 3) for k in keys if k in r and isinstance(r[k], (int, float))}
    if "solve" in r:
        out["wall_s"] = {k: round(v.get("wall_s", 0)) for k, v in r["solve"].items()}
    return out


def e2e() -> dict:
    ids = [J.submit(intact_spec(H_PROD)), J.submit(design_spec(BASE, "e2e", "base"))]
    res = wait_for(ids)
    return {j: _brief(r) for j, r in res.items()}


def signs() -> dict:
    specs = {"base": design_spec(BASE, "signs", "base"),
             "torque_off": design_spec(BASE, "signs", "torque_off", torque=False),
             "delta_0": design_spec(BASE, "signs", "delta_0", delta=0.0),
             "mu_0.8": design_spec(BASE, "signs", "mu_0.8", mu=0.8),
             "rerun": design_spec(BASE, "signs", "rerun", rep=1)}
    ids = {k: J.submit(s) for k, s in specs.items()}
    J.submit(intact_spec(H_PROD))
    res = wait_for(list(ids.values()))
    out = {k: _brief(res[j]) for k, j in ids.items()}
    b = out["base"]
    checks = {}
    if all("f1_p95_um" in out[k] for k in out):
        checks["torque raises micromotion"] = out["base"]["f1_p95_um"] > out["torque_off"]["f1_p95_um"]
        checks["no interference raises micromotion"] = out["delta_0"]["f1_p95_um"] > b["f1_p95_um"]
        checks["higher friction lowers micromotion"] = out["mu_0.8"]["f1_p95_um"] < b["f1_p95_um"]
        checks["rerun identical"] = all(abs(out["rerun"][k] - b[k]) < 1e-9 for k in ("f1_p95_um", "f2_g7_loss_pct", "vm_p99"))
    out["checks"] = checks
    return out


REF_SEED = 999                                 # S4′ 参考集的池种子（与 BO 的 0/1/2 分开）


def convergence() -> dict:
    """S2′：2 个设计 × 3 档网格（2.0/1.4/1.0）+ 各档完整股骨；12 个参考设计 × 2 档（2.0/1.4）看排序保持。"""
    import numpy as np
    import problem_v2a as PB
    import geom3d as G
    from scipy.stats import spearmanr
    levels = (2.0, 1.4, 1.0)
    for h in levels:
        J.submit(intact_spec(h))
    pool = PB.gated_pool(8192, REF_SEED)
    d2 = G.from_unit(pool[0])
    ids = {(n, h): J.submit(design_spec(d, "conv", f"{n}_h{h:g}", h_int=h)) for n, d in (("base", BASE), ("ref0", d2))
           for h in levels}
    rank = {(i, h): J.submit(design_spec(G.from_unit(pool[i]), "ref" if h == H_PROD else "conv", f"r{i}_h{h:g}", h_int=h))
            for i in range(12) for h in (2.0, 1.4)}
    res = wait_for(list(ids.values()) + list(rank.values()))
    out = {"grid": {f"{n}_h{h:g}": _brief(res[j]) for (n, h), j in ids.items()}}
    # GCI（Celik 2008）：三档 h1 < h2 < h3，细化比 r21 = h2/h1、r32 = h3/h2（本研究 1.4、1.43）
    gci = {}
    for n in ("base", "ref0"):
        for q in ("f1_p95_um", "f2_g7_loss_pct", "vm_p99"):
            try:
                f1, f2, f3 = (res[ids[(n, h)]][q] for h in (1.0, 1.4, 2.0))
            except (KeyError, TypeError):
                continue
            r21, r32 = 1.4 / 1.0, 2.0 / 1.4
            e32, e21 = f3 - f2, f2 - f1
            p = abs(np.log(abs(e32 / e21))) / np.log(r21) if e21 != 0 and e32 != 0 else float("nan")
            ea = abs((f1 - f2) / f1) if f1 else float("nan")
            gci[f"{n}:{q}"] = {"h1.0": f1, "h1.4": f2, "h2.0": f3, "p": p, "gci_fine": 1.25 * ea / (r21 ** p - 1) if p == p else None,
                               "rel_change_2.0_vs_1.0": abs(f3 - f1) / abs(f1) if f1 else None}
    out["gci"] = gci
    rk = {}
    for q in ("f1_p95_um", "f2_g7_loss_pct"):
        a = [res[rank[(i, 2.0)]].get(q) if res[rank[(i, 2.0)]] else None for i in range(12)]
        b = [res[rank[(i, 1.4)]].get(q) if res[rank[(i, 1.4)]] else None for i in range(12)]
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        rk[q] = {"n": len(pairs), "spearman": float(spearmanr(*zip(*pairs))[0]) if len(pairs) > 3 else None}
    out["ranking_2.0_vs_1.4"] = rk
    return out


def reference(n: int = 64) -> dict:
    """S4′：参考池前 n 个可行设计在生产网格下全跑；兼作同预算 Sobol 基线与 GP 测试集。"""
    import problem_v2a as PB
    import geom3d as G
    pool = PB.gated_pool(8192, REF_SEED)
    J.submit(intact_spec(H_PROD))
    ids = [J.submit(design_spec(G.from_unit(pool[i]), "ref", f"r{i}_h{H_PROD:g}")) for i in range(n)]
    res = wait_for(ids)
    rows = []
    for i, j in enumerate(ids):
        y, c, ok = PB.objectives(res[j])
        rows.append({"i": i, "job_id": j, "x": pool[i].tolist(), "y": y, "c": c, "ok": ok,
                     "failed": res[j].get("failed") if res[j] else None})
    return {"n": n, "pool_seed": REF_SEED, "rows": rows, "n_ok": sum(r["ok"] for r in rows)}


def reference_rebuild(n: int = 64) -> dict:
    """只从队列里已完成的参考作业重算 reference.json（不提交任何作业）。

    目标定义改了（2026-09-28，y2 改为 |ΔSED|）时用它：作业 id 含建模代码哈希，重新 submit 会因夜里的建模修正
    而得到新 id、把 64 个设计重算一遍。这里按 tag 找原作业（最早完成者），设计取自作业自身的 spec。"""
    import problem_v2a as PB
    import geom3d as G
    rows = []
    for i in range(n):
        cands = [d for d in J.QROOT.glob(f"ref_r{i}_h{H_PROD:g}_*") if J.state(d) in ("DONE", "FAILED")]
        if not cands:
            raise FileNotFoundError(f"reference design r{i} has no finished job")
        d = min(cands, key=lambda p: p.stat().st_mtime)
        spec = json.loads((d / "spec.json").read_text())
        r = J.result(d.name)
        y, c, ok = PB.objectives(r)
        rows.append({"i": i, "job_id": d.name, "x": G.to_unit(spec["design"]).tolist(), "y": y, "c": c, "ok": ok,
                     "failed": r.get("failed") if r else None})
    return {"n": n, "pool_seed": REF_SEED, "rows": rows, "n_ok": sum(r["ok"] for r in rows),
            "objective_y2": "|dSED| Gruen 7 (%)", "rebuilt": time.strftime("%Y-%m-%d %H:%M:%S")}


def _fit_gp_unit(X, y, noise_min=1e-6):
    """mobo.fit_gp 的 V2A 版：输入归一化用显式 [0, 1] 边界（11 维只有 24 个初始点时，按数据推断边界不稳），
    拟合失败写日志而不是静默吞掉。"""
    import torch
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.transforms import Normalize, Standardize
    from gpytorch.constraints import GreaterThan
    from gpytorch.kernels import MaternKernel, ScaleKernel
    from gpytorch.likelihoods import GaussianLikelihood
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from gpytorch.priors import GammaPrior
    d = X.shape[-1]
    lik = GaussianLikelihood(noise_constraint=GreaterThan(noise_min))
    kern = ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=d, lengthscale_prior=GammaPrior(3.0, 6.0)),
                       outputscale_prior=GammaPrior(2.0, 0.15))
    bounds = torch.stack([torch.zeros(d, dtype=X.dtype), torch.ones(d, dtype=X.dtype)])
    gp = SingleTaskGP(X, y.reshape(-1, 1), likelihood=lik, covar_module=kern,
                      input_transform=Normalize(d=d, bounds=bounds), outcome_transform=Standardize(m=1))
    try:
        fit_gpytorch_mll(ExactMarginalLogLikelihood(gp.likelihood, gp))
    except Exception as e:                                                   # noqa: BLE001
        print(f"  WARNING GP fit failed ({type(e).__name__}: {e}); using prior hyperparameters", flush=True)
    return gp


def ref_point() -> list[float]:
    f = J.RESULTS / "reference.json"
    if not f.exists():
        raise FileNotFoundError("run `stage_v2a.py reference` first (S4′ defines the HV reference point)")
    rows = json.loads(f.read_text())["rows"]
    import numpy as np
    Y = np.array([r["y"] for r in rows if r["ok"] and r["c"] <= 0])
    lo, hi = Y.min(0), Y.max(0)
    return (hi + 0.1 * (hi - lo)).tolist()


def bo(seed: int, n_init: int = 24, n_rounds: int = 10, q: int = 4) -> dict:
    """S5′：qLogNEHVI，一个种子；可续跑（已完成的评估命中队列缓存）。"""
    import mobo
    import problem_v2a as PB
    mobo.fit_gp = _fit_gp_unit
    ref = ref_point()
    prob = PB.V2AProblem(ref, "bo", H_PROD)
    pool = PB.gated_pool(8192, seed)
    recs, info = mobo.run(prob, method="qnehvi", seed=seed, n_init=n_init, n_rounds=n_rounds, q=q, pool=pool)
    return {"seed": seed, "ref_point": ref, "pool_size": len(pool), "x": [r.x.tolist() for r in recs],
            "y": [r.y.tolist() for r in recs], "c": [r.c.tolist() for r in recs], "ok": [r.ok for r in recs],
            "round": [r.round for r in recs], "acq_s": info.get("timing"), "rows": prob.rows}


def mesh_decision(conv: dict) -> dict:
    """R2′ 的预设判据：生产网格（2.0）对最细（1.0）f1、f2 相对变化均 < 10%，或 12 设计 2.0 对 1.4 的 Spearman 均 ≥ 0.9。"""
    rel = {k: v.get("rel_change_2.0_vs_1.0") for k, v in conv.get("gci", {}).items()
           if k.split(":")[1] in ("f1_p95_um", "f2_g7_loss_pct")}
    rk = conv.get("ranking_2.0_vs_1.4", {})
    ok_change = bool(rel) and all(v is not None and v < 0.10 for v in rel.values())
    ok_rank = all((rk.get(q) or {}).get("spearman") is not None and rk[q]["spearman"] >= 0.9
                  for q in ("f1_p95_um", "f2_g7_loss_pct"))
    return {"rel_change_vs_finest": rel, "spearman_2.0_vs_1.4": {q: (rk.get(q) or {}).get("spearman") for q in rk},
            "pass_change": ok_change, "pass_rank": ok_rank, "production_h": H_PROD if (ok_change or ok_rank) else None}


def auto(poll: float = 60.0) -> dict:
    """等 S2′（convergence.json）与 S4′（reference.json）完成，按预设判据定生产网格；通过则启动 3 个 BO 种子，
    否则写 DECISION_NEEDED 停下等用户。"""
    import subprocess
    need = [J.RESULTS / "convergence.json", J.RESULTS / "reference.json"]
    while not all(f.exists() for f in need):
        time.sleep(poll)
    dec = mesh_decision(json.loads(need[0].read_text()))
    dec["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (J.RESULTS / "mesh_decision.json").write_text(json.dumps(dec, indent=1, default=float))
    if dec["production_h"] is None:
        (J.RESULTS / "DECISION_NEEDED").write_text("2.0 mm mesh failed the R2′ criterion; BO not started.\n")
        return dec
    logs = pathlib.Path.home() / "mobo_toy_v2" / "logs"
    for s in (0, 1, 2):
        subprocess.Popen([str(pathlib.Path.home() / "mobo_toy_v2" / "run.sh"), "v2/stage_v2a.py", "bo", "--seed", str(s)],
                         cwd=str(HERE.parent), stdout=open(logs / f"bo_s{s}.log", "w"), stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    dec["bo_started"] = [0, 1, 2]
    return dec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "status", "e2e", "signs", "convergence", "reference", "reference-rebuild", "bo", "auto"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-prep", type=int, default=5, help="serve：并行建模子进程数（每个最多 PREP_MEM_GB 虚拟内存）")
    a = ap.parse_args()
    if a.cmd == "serve":
        serve(a.n_prep)
    elif a.cmd == "status":
        print(json.dumps(J.summary()))
    else:
        fn = {"e2e": e2e, "signs": signs, "convergence": convergence, "reference": reference,
              "reference-rebuild": reference_rebuild, "bo": lambda: bo(a.seed), "auto": auto}[a.cmd]
        res = fn()
        J.RESULTS.mkdir(parents=True, exist_ok=True)
        name = f"bo_s{a.seed}" if a.cmd == "bo" else ("reference" if a.cmd == "reference-rebuild" else a.cmd)
        (J.RESULTS / f"{name}.json").write_text(json.dumps(res, indent=1, default=float))
        print(json.dumps(res if a.cmd not in ("reference", "reference-rebuild", "bo") else {k: v for k, v in res.items() if k not in ("rows", "x", "y", "c")},
                         indent=1, default=float))
