"""阶段 1 → 阶段 2 自动衔接（Linux，nohup）：等阶段 1 的优化进程退出，按"拐点"规则选参考设计，直接启动阶段 2。
拐点规则：可行的 Pareto 前沿点，把两个目标各自归一化到前沿的 [0,1]，取离理想点 (0,0) 最近的那个；写 results/neckopt_p1_ref.json。
早上若想换参考设计：停掉 neck2（remote.stop），删 results/neckopt_p2.json，用 --ref 重启。"""
import json
import os
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import numpy as np  # noqa: E402

LOGS = pathlib.Path.home() / "mobo_toy_v2" / "logs"
RES = pathlib.Path.home() / "mobo_toy_v2" / "results"


def alive(pidfile: pathlib.Path) -> bool:
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:                                                # noqa: BLE001
        return False


while alive(LOGS / "neck1.pid"):
    time.sleep(120)
st = json.loads((RES / "neckopt_p1.json").read_text())
recs = [r for r in st["records"] if r["ok"] and r["c"][0] <= 0]
print(f"{time.strftime('%H:%M:%S')} phase 1 finished: {len(st['records'])} records, {len(recs)} feasible, rounds {max(r['round'] for r in st['records'])}", flush=True)
Y = np.array([r["y"] for r in recs])
front = [i for i in range(len(Y)) if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in range(len(Y)))]
F = Y[front]
lo, hi = F.min(0), F.max(0)
Z = (F - lo) / np.where(hi - lo > 0, hi - lo, 1.0)
k = front[int(np.argmin(np.linalg.norm(Z, axis=1)))]
ref = recs[k]
out = {"rule": "knee: feasible Pareto point nearest to the ideal point after normalising both objectives over the front",
       "job_id": ref["job_id"], "design": ref["design"], "h_cut": ref["h_cut"], "micromotion_um": 10 ** ref["y"][0], "bone_loss_mm3": ref["y"][1],
       "ssi_pct": ref["ssi_pct"], "front": [{"job_id": recs[i]["job_id"], "micromotion_um": 10 ** recs[i]["y"][0], "bone_loss_mm3": recs[i]["y"][1],
                                             **recs[i]["design"], "h_cut": recs[i]["h_cut"]} for i in front],
       "chosen": time.strftime("%Y-%m-%d %H:%M:%S")}
(RES / "neckopt_p1_ref.json").write_text(json.dumps(out, indent=1, default=float))
print("reference:", json.dumps({k: v for k, v in out.items() if k != "front"}, default=float), flush=True)
print(f"front ({len(front)} points):", flush=True)
for p in sorted(out["front"], key=lambda p: p["micromotion_um"]):
    print("  ", {k: (round(v, 1) if isinstance(v, float) else v) for k, v in p.items()}, flush=True)

import stage_neckopt as N  # noqa: E402
ph = N.Phase(2, N.load_ref(ref["job_id"]), "abs")
N.bo(ph, n_rounds=12, n_init=24, q=4, seed=0, workers=6, legacy_warm=False)
print("phase 2 finished", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)
