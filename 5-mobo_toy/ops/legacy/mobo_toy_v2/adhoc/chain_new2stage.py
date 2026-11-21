"""新分法的两阶段测试（用户 2026-10-04 12:00）：从零开始，协议与原两阶段完全相同，只换分法。Linux，nohup。
第一阶段（stage_neckopt 阶段 5）：柄长、插入角、皮质余量、截骨深度 25–32；截面椭圆 λ 1.3、领 3 mm、锥度 0.5 / 1.0。
    16 个 Sobol 初始点 + 12 轮 × 4，同步批量 qLogNEHVI，池 8192、不补点，不用任何已有结果（--warm none）。
参考设计：与原两阶段相同的拐点规则（可行前沿两目标归一化后离理想点最近）。
第二阶段（阶段 6）：截面 7 个 + 领宽 + 锥度 2 个；柄长、插入角、余量、截骨深度取参考设计；24 初始 + 12 轮 × 4；热启动只有参考设计本身
    （与原阶段 2 相同）。总预算 64 + 72 = 136 次，与原两阶段相同。"""
import json
import pathlib
import sys
import time

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import numpy as np  # noqa: E402
import stage_neckopt as N  # noqa: E402

ph5 = N.Phase(5, None, "abs")
if not (N.out_path(5).exists() and max((r["round"] for r in json.loads(N.out_path(5).read_text())["records"]), default=-1) >= 12):
    N.bo(ph5, n_rounds=12, n_init=16, q=4, seed=0, workers=6, legacy_warm=None, n_pool=8192)
st = json.loads(N.out_path(5).read_text())
recs = [r for r in st["records"] if r["ok"] and r["c"][0] <= 0]
Y = np.array([r["y"] for r in recs])
front = [i for i in range(len(Y)) if not any((Y[j] <= Y[i]).all() and (Y[j] < Y[i]).any() for j in range(len(Y)))]
F = Y[front]
lo, hi = F.min(0), F.max(0)
Z = (F - lo) / np.where(hi - lo > 0, hi - lo, 1.0)
ref = recs[front[int(np.argmin(np.linalg.norm(Z, axis=1)))]]
out = {"rule": "knee over the feasible Pareto front (same rule as the original two-stage run)", "job_id": ref["job_id"], "design": ref["design"],
       "micromotion_um": 10 ** ref["y"][0], "bone_loss_mm3": ref["y"][1], "ssi_pct": ref["ssi_pct"],
       "front": [{"job_id": recs[i]["job_id"], "micromotion_um": 10 ** recs[i]["y"][0], "bone_loss_mm3": recs[i]["y"][1], **recs[i]["design"]} for i in front],
       "chosen": time.strftime("%Y-%m-%d %H:%M:%S")}
(N.J.RESULTS / "neckopt_p5_ref.json").write_text(json.dumps(out, indent=1, default=float))
print("reference:", json.dumps({k: v for k, v in out.items() if k != "front"}, default=float), flush=True)
ph6 = N.Phase(6, N.load_ref(ref["job_id"]), "abs")
N.bo(ph6, n_rounds=12, n_init=24, q=4, seed=0, workers=6, legacy_warm=False, n_pool=8192)
print("new two-stage test finished", time.strftime("%Y-%m-%d %H:%M:%S"), flush=True)
