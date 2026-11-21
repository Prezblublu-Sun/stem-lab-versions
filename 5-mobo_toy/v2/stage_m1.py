"""M1 界面模型的验证阶段（在 Linux 上跑；本机只求解）。每个命令提交作业、等待、把结果写进 results/m1_<cmd>.json。

    lame      Lamé 压配对照：{offset, clearance} × {μ 0, 0.3} × h {2.0, 1.4}
    smoke     基准设计，生产设置
    friction  摩擦容差收敛：2 设计 × {0.005, 0.001, 0.00025, Lagrange}
    noise     噪声底：3 设计 × h_int {1.94, 1.97, 2.00, 2.03, 2.06}
    compare   新旧界面对比：12 个当前版本设计（按旧 f1 分位取）
    signs     方向性：基准设计 δ 0 / 0.05、μ 0.6、去扭转
    delta     过盈量扫描：3 设计 × δ {0.01, 0.025, 0.05, 0.10}
    mesh      网格：3 设计 × {2.0, 1.4} mm（--fine 再加基准 1.0 mm）
公共选项 --slip-tol / --lagrange：生产用的摩擦设置（默认 slip tolerance 2.5e-4；friction 之后可改）。
同一（设计、网格、摩擦设置、变体）在各命令里用同一个作业说明，所以互相命中缓存。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402

PRE_FIX = {"af2719da27", "3edd9887e5"}
KEYS = ("f1_p95_um", "f1_rev_p50_um", "f1_first_p95_um", "f1_closed_p95_um", "f1_cslip_p95_um", "normal_rev_p95_um",
        "area_frac_gt40", "area_frac_gt150", "open_frac_release", "open_frac_load2", "gap_p95_release_um",
        "cpress_release_p50", "cpress_release_p95", "cpress_release_max", "status_frac_stick", "status_frac_slip",
        "status_frac_open", "stick_cslip_p95_um", "stick_cslip_max_um", "f2_g7_loss_pct", "vm_p99", "cortex_area_frac", "n_pairs")
NAMED = {"base": None, "short": "probe_L25_12_e265f0bf", "readout": "bo_qnehvi_s1_r0_62bbf792"}
FRICTION_SETS = {"tol0.005": {"slip_tol": 0.005}, "tol0.001": {"slip_tol": 0.001}, "tol0.00025": {"slip_tol": 0.00025},
                 "tol0.0001": {"slip_tol": 0.0001}, "lagrange": {"lagrange": True}}


def brief(r: dict | None) -> dict:
    if r is None:
        return {}
    if "failed" in r:
        return {"FAILED": r["failed"]["level"], "reason": r["failed"]["reason"][:300]}
    out = {k: (round(float(r[k]), 4) if isinstance(r[k], (int, float)) else r[k]) for k in KEYS if k in r}
    if "solve" in r:
        out["wall_s"] = {k: round(v.get("wall_s", 0)) for k, v in r["solve"].items()}
    return out


def core_of(job: str | None) -> dict:
    """已有作业的设计说明（设计向量、余量、截骨高度、网格）；None → 基准设计。"""
    if job is None:
        return {"kind": "design", "design": dict(S.BASE), "h_int": S.H_PROD, "min_A0": S.MIN_A0}
    spec = json.loads((J.QROOT / job / "spec.json").read_text())
    return {k: v for k, v in spec.items() if k in ("kind", "design", "h_int", "min_A0", "margin", "h_cut")}


def frtag(fr: dict) -> str:
    return "lagrange" if fr.get("lagrange") else f"tol{fr['slip_tol']:g}"


def spec_of(core: dict, label: str, h: float, fr: dict, **variant) -> dict:
    vt = "".join(f"_{k}{(v if isinstance(v, bool) else format(v, 'g'))}" for k, v in sorted(variant.items()))
    return {**core, "h_int": h, "model": "m1", "stage": "m1", "tag": f"{label}_h{h:g}_{frtag(fr)}{vt}", **fr, **variant}


def named(d: str, h: float, fr: dict, **variant) -> dict:
    return spec_of(core_of(NAMED[d]), d, h, fr, **variant)


def save(name: str, out: dict) -> None:
    J.RESULTS.mkdir(parents=True, exist_ok=True)
    out["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (J.RESULTS / f"m1_{name}.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float), flush=True)


def lame() -> dict:
    ids = {}
    for method in ("offset", "clearance"):
        for mu in (0.0, 0.3):
            for h in (2.0, 1.4):
                ids[f"{method}_mu{mu:g}_h{h:g}"] = J.submit({"kind": "bench", "stage": "m1lame", "tag": f"{method}_mu{mu:g}_h{h:g}",
                                                             "h": h, "delta": 0.10, "mu": mu, "interference": method})
    res = S.wait_for(list(ids.values()), timeout_h=2.0, poll=15.0)
    out = {"runs": {}}
    for k, j in ids.items():
        r = res[j]
        out["runs"][k] = ({"job_id": j, "FAILED": r["failed"]["level"], "reason": r["failed"]["reason"][:400]} if "failed" in r else
                          {kk: r[kk] for kk in ("p_lame_MPa", "p_inferred_MPa", "err_pct", "p_fe_mean_mid_MPa", "err_cpress_pct",
                                                "p_fe_min_mid", "p_fe_max_mid", "bone_normal_disp_mean_um",
                                                "bone_normal_disp_sd_um", "open_frac", "rel_normal_mean_um", "n_pairs")} |
                          {"wall_s": {kk: round(v.get("wall_s", 0)) for kk, v in r["solve"].items()}, "job_id": j})
    save("lame", out)
    return out


def smoke(fr: dict) -> dict:
    j = J.submit(named("base", 2.0, fr))
    res = S.wait_for([j], timeout_h=3.0, poll=20.0)
    old = J.result("e2e_base_92712f81") or {}
    out = {"job_id": j, "m1": brief(res[j]),
           "old_interface": {k: old.get(k) for k in ("f1_p95_um", "f2_g7_loss_pct", "vm_p99", "frac_open")}}
    save("smoke", out)
    return out


def friction() -> dict:
    ids = {(d, k): J.submit(named(d, 2.0, fr)) for d in ("base", "readout") for k, fr in FRICTION_SETS.items()}
    res = S.wait_for(list(ids.values()), timeout_h=6.0, poll=30.0)
    out = {"runs": {f"{d}:{k}": {"job_id": j, **brief(res[j])} for (d, k), j in ids.items()}}
    save("friction", out)
    return out


def _var(delta):
    return {} if delta is None else {"delta": float(delta)}


def _sfx(delta):
    return "" if delta is None else f"_d{delta:g}"


def noise(fr: dict, delta=None, designs=None) -> dict:
    hs = (1.94, 1.97, 2.00, 2.03, 2.06)
    names = [d for d in NAMED if designs is None or d in designs]
    ids = {(d, h): J.submit(named(d, h, fr, **_var(delta))) for d in names for h in hs}
    res = S.wait_for(list(ids.values()), timeout_h=8.0, poll=30.0)
    out = {"delta": delta, "runs": {f"{d}:h{h:g}": {"job_id": j, **brief(res[j])} for (d, h), j in ids.items()}, "summary": {}}
    for d in names:
        for q in ("f1_p95_um", "f1_first_p95_um", "f1_cslip_p95_um", "f2_g7_loss_pct", "vm_p99", "open_frac_release"):
            v = np.array([res[ids[(d, h)]].get(q, np.nan) for h in hs if "failed" not in res[ids[(d, h)]]], float)
            v = v[np.isfinite(v)]
            if len(v) >= 3:
                out["summary"][f"{d}:{q}"] = {"n": int(len(v)), "mean": float(v.mean()), "sd": float(v.std(ddof=1)),
                                              "cv_pct": float(100 * v.std(ddof=1) / abs(v.mean())) if v.mean() else None,
                                              "min": float(v.min()), "max": float(v.max())}
    save("noise" + _sfx(delta), out)
    return out


def pick_compare(n: int = 12) -> list[str]:
    rows = []
    for d in sorted(J.QROOT.glob("*")):
        sp = d / "spec.json"
        if not sp.exists() or not (d / "DONE").exists():
            continue
        spec = json.loads(sp.read_text())
        if spec.get("kind") != "design" or spec.get("h_int") != S.H_PROD or spec.get("model") is not None:
            continue
        if any(spec.get(k) is not None for k in ("delta", "mu", "E_canc", "rep")) or spec.get("torque", True) is False:
            continue
        prep = json.loads((d / "prep.json").read_text()) if (d / "prep.json").exists() else {}
        if prep.get("code_hash") in PRE_FIX:
            continue
        r = J.result(d.name)
        if r and "f1_p95_um" in r:
            rows.append((r["f1_p95_um"], d.name))
    rows.sort()
    idx = np.unique(np.round(np.linspace(0, len(rows) - 1, n)).astype(int))
    return [rows[i][1] for i in idx]


def compare(fr: dict, n: int = 12, delta=None) -> dict:
    jobs_ = pick_compare(n)
    ids = {j: J.submit(spec_of(core_of(j), "cmp" + j[-8:], 2.0, fr, **_var(delta))) for j in jobs_}
    res = S.wait_for(list(ids.values()), timeout_h=8.0, poll=30.0)
    from scipy.stats import spearmanr
    rows = []
    for j, k in ids.items():
        o = J.result(j)
        sp = json.loads((J.QROOT / j / "spec.json").read_text())
        dsg = G.design_of_spec(sp)
        rows.append({"old_job": j, "m1_job": k, "L": dsg["L"], "alpha": dsg["alpha"], "m": dsg["m"], "h_cut": sp.get("h_cut", 25.0),
                     "old": {q: o.get(q) for q in ("f1_p95_um", "f2_g7_loss_pct", "vm_p99", "frac_open")}, "m1": brief(res[k])})
    ok = [r for r in rows if "f1_p95_um" in r["m1"]]
    out = {"delta": delta, "rows": rows, "n_ok": len(ok)}
    if len(ok) >= 4:
        a = np.array([r["old"]["f1_p95_um"] for r in ok])
        for q in ("f1_p95_um", "f1_first_p95_um", "f1_cslip_p95_um"):
            b = np.array([r["m1"][q] for r in ok])
            out[f"spearman_old_vs_{q}"] = float(spearmanr(a, b)[0])
            out[f"median_ratio_{q}"] = float(np.median(b / a))
    save("compare" + _sfx(delta), out)
    return out


def signs(fr: dict) -> dict:
    specs = {"base": named("base", 2.0, fr), "delta_0": named("base", 2.0, fr, delta=0.0),
             "delta_0.05": named("base", 2.0, fr, delta=0.05), "mu_0.6": named("base", 2.0, fr, mu=0.6),
             "torque_off": named("base", 2.0, fr, torque=False)}
    ids = {k: J.submit(s) for k, s in specs.items()}
    res = S.wait_for(list(ids.values()), timeout_h=6.0, poll=30.0)
    out = {"runs": {k: {"job_id": j, **brief(res[j])} for k, j in ids.items()}, "checks": {}}
    r = out["runs"]
    if all("f1_p95_um" in v for v in r.values()):
        b = r["base"]["f1_p95_um"]
        out["checks"] = {"no interference raises micromotion": r["delta_0"]["f1_p95_um"] > b,
                         "half interference raises micromotion": r["delta_0.05"]["f1_p95_um"] > b,
                         "higher friction lowers micromotion": r["mu_0.6"]["f1_p95_um"] < b,
                         "torque raises micromotion": b > r["torque_off"]["f1_p95_um"]}
    save("signs", out)
    return out


def delta_sweep(fr: dict) -> dict:
    """过盈量扫描：3 个设计 × δ {0, 0.025, 0.05, 0.10} mm。δ 是压配模型里最不确定的输入（线弹性松质骨、无压溃上限）。"""
    # δ = 0 不在扫描里：没有压配时，卸载到零载荷后柄完全松开，第二次加载不收敛（2026-09-29 01:25 基准设计 L4，
    # 前四步都完成，LOAD2 第一增量反复减步长）。最低一档取 0.01 mm。
    ds = (0.01, 0.025, 0.05, 0.10)
    ids = {(d, x): J.submit(named(d, 2.0, fr) if x == 0.10 else named(d, 2.0, fr, delta=x)) for d in NAMED for x in ds}
    res = S.wait_for(list(ids.values()), timeout_h=8.0, poll=30.0)
    out = {"runs": {f"{d}:delta{x:g}": {"job_id": j, **brief(res[j])} for (d, x), j in ids.items()}}
    save("delta", out)
    return out


def review3(fr: dict) -> dict:
    """第三份评估后的 23 个验证作业（用户 2026-09-29 批准）。全部带新导出（反力、接触力与接触面积、应变）。"""
    tol14 = {"slip_tol": fr["slip_tol"] * 2.0 / 1.4}           # 1.4 mm 网格上保持绝对弹性滑移上限不变（0.5 µm）
    ids = {}
    for d in NAMED:                                              # 第三循环
        ids[f"cycle3:{d}:d0.1"] = J.submit(named(d, 2.0, fr, cycles=3))
        ids[f"cycle3:{d}:d0.025"] = J.submit(named(d, 2.0, fr, cycles=3, delta=0.025))
    for d in NAMED:                                              # 等绝对滑移的网格加密
        ids[f"mesh14:{d}:d0.1"] = J.submit(named(d, 1.4, tol14))
    for dl in (0.05, 0.025):                                     # 短柄阈值工况：噪声底与网格
        for h in (1.94, 1.97, 2.03, 2.06):
            ids[f"noise:short:d{dl:g}:h{h:g}"] = J.submit(named("short", h, fr, delta=dl))
        ids[f"mesh14:short:d{dl:g}"] = J.submit(named("short", 1.4, tol14, delta=dl))
    ids["export:base:d0.1"] = J.submit(named("base", 2.0, fr))   # 四个代表工况按原规格重解（新导出；兼作跨版本一致性检查）
    ids["export:readout:d0.1"] = J.submit(named("readout", 2.0, fr))
    ids["export:short:d0.05"] = J.submit(named("short", 2.0, fr, delta=0.05))
    ids["export:short:d0.025"] = J.submit(named("short", 2.0, fr, delta=0.025))
    (J.RESULTS / "m1_review3_ids.json").write_text(json.dumps(ids, indent=1))
    print(f"[review3] submitted {len(ids)} jobs", flush=True)
    res = S.wait_for(list(ids.values()), timeout_h=12.0, poll=30.0)
    out = {"runs": {k: {"job_id": j, **brief(res[j])} for k, j in ids.items()}}
    save("review3", out)
    return out


def mesh(fr: dict, fine: bool = False, delta=None) -> dict:
    ids = {(d, h): J.submit(named(d, h, fr, **_var(delta))) for d in NAMED for h in (2.0, 1.4)}
    if fine:
        ids[("base", 1.0)] = J.submit(named("base", 1.0, fr, **_var(delta)))
    res = S.wait_for(list(ids.values()), timeout_h=10.0, poll=30.0)
    out = {"delta": delta, "runs": {f"{d}:h{h:g}": {"job_id": j, **brief(res[j])} for (d, h), j in ids.items()}}
    save("mesh" + _sfx(delta), out)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["lame", "smoke", "friction", "noise", "compare", "signs", "mesh", "delta", "review3", "pick"])
    ap.add_argument("--slip-tol", type=float, default=2.5e-4)
    ap.add_argument("--lagrange", action="store_true")
    ap.add_argument("--fine", action="store_true")
    ap.add_argument("--delta", type=float, default=None, help="过盈量变体（mm）；不给则用配置里的 0.10")
    ap.add_argument("--designs", default=None, help="逗号分隔：base,short,readout")
    a = ap.parse_args()
    fr = {"lagrange": True} if a.lagrange else {"slip_tol": a.slip_tol}
    if a.cmd == "lame":
        lame()
    elif a.cmd == "smoke":
        smoke(fr)
    elif a.cmd == "friction":
        friction()
    elif a.cmd == "noise":
        noise(fr, a.delta, a.designs.split(",") if a.designs else None)
    elif a.cmd == "compare":
        compare(fr, delta=a.delta)
    elif a.cmd == "signs":
        signs(fr)
    elif a.cmd == "mesh":
        mesh(fr, a.fine, a.delta)
    elif a.cmd == "delta":
        delta_sweep(fr)
    elif a.cmd == "review3":
        review3(fr)
    else:
        print("\n".join(pick_compare()))
