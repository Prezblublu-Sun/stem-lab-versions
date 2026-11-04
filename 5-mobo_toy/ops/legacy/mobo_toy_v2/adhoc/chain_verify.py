"""A 段自动衔接（Linux，nohup）：等联合优化（neck3）进程退出 → 按 A1 规则选 10 个代表 → 提交 A2–A4 共约 32 个变体作业 →
等待 → 收集 → results/verify/summary.json。全部是 kind=variant、stage=verify，不进任何优化数据集。用户 2026-10-03 22:58 批准。"""
import json
import os
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import numpy as np  # noqa: E402
import jobs as J  # noqa: E402
import stage_v2a as S  # noqa: E402
import stage_neckopt as N  # noqa: E402

LOGS = pathlib.Path.home() / "mobo_toy_v2" / "logs"
RES = J.RESULTS
OUT = RES / "verify"
CONTROLS = {"S1-A": "neck1_r4_0d28fc08", "S1-B": "neck1_r6_102aba81", "S2-A": "neck2_init_1fee0a35", "S2-B": "neck2_init_2965eb88"}


def alive(pidfile):
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        return True
    except Exception:                                                # noqa: BLE001
        return False


def feasible(path):
    st = json.loads(path.read_text())
    return [r for r in st["records"] if r["ok"] and r["c"][0] <= 0]


def front(recs):
    Y = np.array([r["y"] for r in recs])
    keep = [i for i in range(len(Y)) if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in range(len(Y)))]
    return [recs[i] for i in keep]


def pick_reps():
    p1, p2, p3 = (feasible(RES / f"neckopt_p{k}.json") for k in (1, 2, 3))
    allr = p1 + p2 + p3
    fr = front(allr)
    f1 = lambda r: 10 ** r["y"][0]  # noqa: E731
    reps = {}
    reps["min_micromotion"] = min(fr, key=f1)
    cand = [r for r in fr if f1(r) <= 20.0]
    reps["min_bone_loss_le20um"] = min(cand or fr, key=lambda r: r["y"][1])
    kn = [r for r in fr if f1(r) <= 40.0] or fr
    Y = np.array([r["y"] for r in kn]); lo, hi = Y.min(0), Y.max(0)
    Z = (Y - lo) / np.where(hi - lo > 0, hi - lo, 1.0)
    reps["knee"] = kn[int(np.argmin(np.linalg.norm(Z, axis=1)))]
    f3 = sorted(front(p3), key=lambda r: r["y"][1])
    if f3:
        n = len(f3)
        for k, name in enumerate(("joint_low_loss", "joint_mid", "joint_high_stability")):
            reps[name] = f3[min(n - 1, (2 * k + 1) * n // 6)]
    for name, jid in CONTROLS.items():
        r = next((x for x in allr if x["job_id"] == jid), None)
        if r:
            reps[name] = r
    seen, out = set(), {}
    for name, r in reps.items():
        if r["job_id"] in seen:
            continue
        seen.add(r["job_id"]); out[name] = r
    return out


def variants(name, jid):
    spec0 = json.loads((J.QROOT / jid / "spec.json").read_text())
    base = {k: v for k, v in spec0.items() if k not in ("created", "tag", "stage", "kind")}
    base.update(kind="variant", stage="verify")
    short = jid.replace("neck", "")[:16]
    v = {"mesh14": {**base, "tag": f"mesh14_{short}", "h_int": 1.4, "slip_tol": 0.000357143},
         "delta05": {**base, "tag": f"delta05_{short}", "delta": 0.05}}
    if name in ("min_micromotion", "knee"):
        v["rep"] = {**base, "tag": f"rep_{short}", "rep": 1}
    if name in ("min_micromotion", "min_bone_loss_le20um", "knee", "S1-A", "S2-A"):
        v["delta01"] = {**base, "tag": f"delta01_{short}", "delta": 0.01}
        v["Ecanc200"] = {**base, "tag": f"Ecanc200_{short}", "E_canc": 200.0}
    return v


def collect(reps, subs):
    N.record_of  # noqa: B018  （用它的指标口径）
    rows = []
    for name, r in reps.items():
        base = N.record_of(r["job_id"], "abs")
        rows.append({"rep": name, "variant": "base", "job_id": r["job_id"], "design": r["design"], "h_cut": r["h_cut"], **base})
        for vname, jid in subs[name].items():
            rec = N.record_of(jid, "abs") if J.state(J.QROOT / jid) == "DONE" else {"ok": False, "state": J.state(J.QROOT / jid)}
            rows.append({"rep": name, "variant": vname, "job_id": jid, "design": r["design"], "h_cut": r["h_cut"], **rec})
    return rows


def main():
    while alive(LOGS / "neck3.pid"):
        time.sleep(120)
    print(f"{time.strftime('%H:%M:%S')} joint optimisation finished; selecting representatives", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    reps = pick_reps()
    subs = {}
    for name, r in reps.items():
        subs[name] = {vn: J.submit(sp) for vn, sp in variants(name, r["job_id"]).items()}
        print(f"  {name:22} {r['job_id']}  f1 {10 ** r['y'][0]:5.1f} um  loss {r['y'][1]:6.0f}  -> {list(subs[name])}", flush=True)
    plan = {"reps": {k: {"job_id": v["job_id"], "design": v["design"], "h_cut": v["h_cut"], "micromotion_um": 10 ** v["y"][0], "bone_loss_mm3": v["y"][1]}
                     for k, v in reps.items()}, "variants": subs, "submitted": time.strftime("%Y-%m-%d %H:%M:%S")}
    (OUT / "plan.json").write_text(json.dumps(plan, indent=1, default=float))
    ids = [j for d in subs.values() for j in d.values()]
    print(f"submitted {len(ids)} variant jobs", flush=True)
    S.wait_for(ids, timeout_h=24)
    rows = collect(reps, subs)
    (OUT / "summary.json").write_text(json.dumps({"rows": rows, "collected": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1, default=float))
    print(f"{time.strftime('%H:%M:%S')} verification collected: {sum(1 for r in rows if r.get('ok'))}/{len(rows)} ok", flush=True)


if __name__ == "__main__":
    main()
