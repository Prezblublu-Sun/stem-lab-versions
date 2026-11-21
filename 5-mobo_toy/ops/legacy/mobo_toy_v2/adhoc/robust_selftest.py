"""stage_robust 的离线自检（不提交作业）：用现有数据拟合三个 GP + 确定性骨量，选 1 个点（含 2 个待定点）；量时间和内存。"""
import pathlib
import resource
import sys
import time

import numpy as np

CODE = pathlib.Path.home() / "mobo_toy_v2" / "code"
sys.path.insert(0, str(CODE)); sys.path.insert(0, str(CODE / "v2"))
import stage_neckopt as N  # noqa: E402
import stage_robust as R  # noqa: E402
from stage_v2a import _fit_gp_unit  # noqa: E402,F401

ent = R.scan()
z = np.load(R.J.RESULTS / "neckopt_p3_pool_live.npz")
pool, loss = z["U"], z["loss"]
det = N.det_loss_fn(pool, loss)
t0 = time.time()
model, na, nb = R.fit(ent, det)
print("fit", round(time.time() - t0, 1), "s; GP data", na, nb)
both = [e for e in ent.values() if "a" in e and "b" in e]
Rr = np.array([R.robust(e) for e in both])
F = Rr[Rr[:, 2] <= 0][:, :2]
lo, hi = F.min(0), F.max(0)
refp = hi + 0.1 * (hi - lo)
Xbase = np.array([e["x"] for e in ent.values() if "a" in e])
rng = np.random.default_rng(0)
cand = rng.choice(len(pool), size=10000, replace=False)
t0 = time.time()
i = R.propose(model, Xbase, refp, pool[cand], pool[cand[:2]], 123)
d_, h_ = R.PH.design_of(pool[cand[i]])
print("propose", round(time.time() - t0, 1), "s ->", {k: round(d_[k], 2) for k in R.PH.vars if k in d_}, "h", round(h_, 1),
      "maxrss GB", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2))
print("lengthscales d0.01 (5 points):", {k: round(v, 2) for k, v in list(R.lengthscales(model)["micromotion_d0.01"].items())[:5]})
