"""多目标贝叶斯优化引擎（BoTorch）：GP 代理 + qLogNEHVI（qNEHVI 的数值稳定版）+ 离散候选池。

* 每个目标与约束各一个 SingleTaskGP：ARD Matérn 5/2，输入归一化、输出标准化；
  观测噪声下界来自 R2 噪声底（基准函数用 1e-6）。
* 采集：qLogNoisyExpectedHypervolumeImprovement，参考点固定（跨种子相同）；约束 c ≤ 0 为可行，
  以 outcome constraint 进入；在候选池（几何门已过滤）上序贯贪心选 q 个（optimize_acqf_discrete）。
* 目标一律按最小化给出；内部取负号交给 BoTorch（最大化）。
* 方法 "sobol" 为同预算基线：按打乱 Sobol 序列取候选池中的点。

Problem 接口：name, d, n_obj, n_con, ref_point（最小化空间，"更差"的角点）,
              evaluate(X) -> (Y[n, n_obj], C[n, n_con], ok[n])，pool(n, seed) -> 候选点（单位立方体）。
"""
from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field

import numpy as np
import torch
from scipy.stats import qmc

warnings.filterwarnings("ignore")
torch.set_default_dtype(torch.double)

from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement  # noqa: E402
from botorch.fit import fit_gpytorch_mll  # noqa: E402
from botorch.models import ModelListGP, SingleTaskGP  # noqa: E402
from botorch.models.transforms import Normalize, Standardize  # noqa: E402
from botorch.optim import optimize_acqf_discrete  # noqa: E402
from botorch.sampling import SobolQMCNormalSampler  # noqa: E402
from botorch.utils.multi_objective.hypervolume import Hypervolume  # noqa: E402
from botorch.utils.multi_objective.pareto import is_non_dominated  # noqa: E402
from gpytorch.constraints import GreaterThan  # noqa: E402
from gpytorch.kernels import MaternKernel, ScaleKernel  # noqa: E402
from gpytorch.likelihoods import GaussianLikelihood  # noqa: E402
from gpytorch.mlls import ExactMarginalLogLikelihood  # noqa: E402
from gpytorch.priors import GammaPrior  # noqa: E402


# ------------------------------------------------------------------ 指标
def pareto_mask(Y: np.ndarray) -> np.ndarray:
    """最小化意义下的非支配点。"""
    if len(Y) == 0:
        return np.zeros(0, bool)
    return is_non_dominated(-torch.as_tensor(Y)).numpy()


def hypervolume(Y: np.ndarray, ref: np.ndarray) -> float:
    """最小化空间的超体积（只计严格优于参考点的点）。"""
    Y = np.asarray(Y, dtype=float)
    if len(Y) == 0:
        return 0.0
    Y = Y[np.all(Y < ref, axis=1)]
    if len(Y) == 0:
        return 0.0
    return float(Hypervolume(-torch.as_tensor(ref)).compute(-torch.as_tensor(Y[pareto_mask(Y)])))


def igd(front: np.ndarray, ref_front: np.ndarray, scale: np.ndarray | None = None) -> float:
    """参考前沿每个点到所得前沿最近点的平均距离（按 scale 归一化）。"""
    if len(front) == 0:
        return float("inf")
    s = np.ones(front.shape[1]) if scale is None else scale
    d = np.linalg.norm((ref_front[:, None, :] - front[None, :, :]) / s, axis=2)
    return float(d.min(axis=1).mean())


def attainment_surface(fronts: list[np.ndarray], grid: np.ndarray, level: float = 0.5) -> np.ndarray:
    """二目标经验达成面（EAF）：对 f1 网格上每个值，各次运行在 f1' ≤ f1 处达到的最小 f2，取 level 分位。"""
    vals = []
    for F in fronts:
        v = np.full(len(grid), np.inf)
        for i, g in enumerate(grid):
            m = F[:, 0] <= g
            if m.any():
                v[i] = F[m, 1].min()
        vals.append(v)
    V = np.vstack(vals)
    k = int(math.ceil(level * len(fronts))) - 1
    return np.sort(V, axis=0)[k]


# ------------------------------------------------------------------ 模型
def fit_gp(X: torch.Tensor, y: torch.Tensor, noise_min: float = 1e-6) -> SingleTaskGP:
    d = X.shape[-1]
    lik = GaussianLikelihood(noise_constraint=GreaterThan(noise_min))
    kern = ScaleKernel(MaternKernel(nu=2.5, ard_num_dims=d, lengthscale_prior=GammaPrior(3.0, 6.0)),
                       outputscale_prior=GammaPrior(2.0, 0.15))
    gp = SingleTaskGP(X, y.reshape(-1, 1), likelihood=lik, covar_module=kern,
                      input_transform=Normalize(d=d), outcome_transform=Standardize(m=1))
    mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
    try:
        fit_gpytorch_mll(mll)
    except Exception:                                                  # noqa: BLE001
        pass
    return gp


def fit_models(X: np.ndarray, Y: np.ndarray, C: np.ndarray | None, noise_sd: list[float] | None = None,
               det: dict | None = None):
    """按 BoTorch 最大化约定：目标取负；约束保持原号（≤ 0 可行）。
    noise_sd：各输出的观测噪声标准差（原单位，来自 R2 噪声底）；换算成标准化后的方差下界 (σ / sd_y)²。
    det：{目标下标: f(X) → 目标值（最小化意义，张量 (..., q)）}——已知的确定性目标（如由几何直接算出的截骨量），
         用 GenericDeterministicModel 代替 GP；没有 det 时行为与原来完全相同。"""
    Xt = torch.as_tensor(X)
    cols = [-Y[:, j] for j in range(Y.shape[1])] + ([C[:, j] for j in range(C.shape[1])] if C is not None else [])
    mins = []
    for j, c in enumerate(cols):
        sd = float(np.std(c)) or 1.0
        mins.append(max(1e-6, (noise_sd[j] / sd) ** 2) if noise_sd else 1e-6)
    if not det:
        return ModelListGP(*[fit_gp(Xt, torch.as_tensor(c), n) for c, n in zip(cols, mins)])
    from botorch.models.deterministic import GenericDeterministicModel
    from botorch.models.model import ModelList
    models = []
    for j, (c, n) in enumerate(zip(cols, mins)):
        if j in det:
            models.append(GenericDeterministicModel(lambda Z, f=det[j]: -f(Z).unsqueeze(-1)))
        else:
            models.append(fit_gp(Xt, torch.as_tensor(c), n))
    return ModelList(*models)


def propose(model: ModelListGP, X_obs: np.ndarray, ref_min: np.ndarray, pool: np.ndarray, q: int, n_obj: int,
            n_con: int, seed: int, X_pending: np.ndarray | None = None) -> np.ndarray:
    """返回候选池中选中点的下标（长度 q）。X_pending：已提交、还没算完的点（异步模式），采集函数把它们当作待定点避开。"""
    constraints = [(lambda Z, j=j: Z[..., n_obj + j]) for j in range(n_con)] or None
    if isinstance(model, ModelListGP):
        sampler = SobolQMCNormalSampler(sample_shape=torch.Size([128]), seed=seed)
    else:                                           # 含确定性目标的 ModelList：按后验类型取 ListSampler
        from botorch.sampling.get_sampler import get_sampler
        sampler = get_sampler(model.posterior(torch.as_tensor(X_obs[:1])), sample_shape=torch.Size([128]), seed=seed)
    acq = qLogNoisyExpectedHypervolumeImprovement(
        model=model, ref_point=(-torch.as_tensor(ref_min)).tolist(), X_baseline=torch.as_tensor(X_obs),
        prune_baseline=True, sampler=sampler,
        constraints=constraints, objective=None if n_con == 0 else _obj_only(n_obj), cache_root=False)
    if X_pending is not None and len(X_pending):
        acq.set_X_pending(torch.as_tensor(np.asarray(X_pending, float)))
    choices = torch.as_tensor(pool)
    cand, _ = optimize_acqf_discrete(acq, q=q, choices=choices, max_batch_size=2048, unique=True)
    cand = cand.numpy()
    idx = [int(np.argmin(np.linalg.norm(pool - c, axis=1))) for c in cand]
    return np.array(idx)


def _obj_only(n_obj):
    from botorch.acquisition.multi_objective.objective import IdentityMCMultiOutputObjective
    return IdentityMCMultiOutputObjective(outcomes=list(range(n_obj)))


# ------------------------------------------------------------------ 主循环
@dataclass
class Record:
    method: str
    seed: int
    round: int
    x: np.ndarray
    y: np.ndarray
    c: np.ndarray
    ok: bool
    meta: dict = field(default_factory=dict)


def run(problem, *, method: str = "qnehvi", seed: int = 0, n_init: int = 12, n_rounds: int = 12, q: int = 4,
        n_pool: int = 20000, noise_sd: list[float] | None = None, verbose: bool = True,
        pool: np.ndarray | None = None, det: dict | None = None, proposer=None) -> tuple[list[Record], dict]:
    """返回 (记录列表, 附加信息)。候选池是按种子打乱的 Sobol 序列（已过几何门），保持序列顺序：
    初始点 = 池的前 n_init 个；Sobol 基线 = 池的前 n_init + n_rounds·q 个（同种子下两种方法初始点相同）。"""
    pool = problem.pool(n_pool, seed) if pool is None else pool
    order = np.arange(len(pool))
    used = np.zeros(len(pool), bool)
    recs: list[Record] = []
    info = {"timing": [], "pool_size": len(pool)}

    def do_eval(idx, rnd):
        X = pool[idx]
        used[idx] = True
        Y, C, ok = problem.evaluate(X, seed=seed, round=rnd, method=method)
        for x, y, c, o in zip(X, Y, C, ok):
            recs.append(Record(method, seed, rnd, x, np.asarray(y, float), np.asarray(c, float), bool(o)))

    if method == "sobol":
        budget = n_init + n_rounds * q
        do_eval(order[:budget], 0)
        return recs, info
    do_eval(order[:n_init], 0)
    for rnd in range(1, n_rounds + 1):
        t0 = time.perf_counter()
        good = [r for r in recs if r.ok]
        X = np.array([r.x for r in good]); Y = np.array([r.y for r in good])
        C = np.array([r.c for r in good]) if problem.n_con else None
        free = np.nonzero(~used)[0]
        if proposer is not None:                         # 例如交给 Linux 上的 worker（straight3d/remote.py）
            pick_local = np.asarray(proposer(X, Y, C, pool[free], q, seed * 1000 + rnd))
        else:
            model = fit_models(X, Y, C, noise_sd, det)
            pick_local = propose(model, X, problem.ref_point, pool[free], q, problem.n_obj, problem.n_con, seed * 1000 + rnd)
            info["last_model"] = model
        info["timing"].append(time.perf_counter() - t0)
        do_eval(free[pick_local], rnd)
        if verbose:
            ys = np.array([r.y for r in recs if r.ok])
            print(f"  [{problem.name} {method} s{seed}] round {rnd}: n = {len(recs)}, "
                  f"HV = {hypervolume(ys, problem.ref_point):.4g}, acq {info['timing'][-1]:.1f} s", flush=True)
    return recs, info


def hv_trace(recs: list[Record], ref: np.ndarray, feasible_fn=None) -> list[tuple[int, float]]:
    """按评估次数累计的超体积（只计可行点）。"""
    out, pts = [], []
    for i, r in enumerate(recs, start=1):
        if r.ok and (feasible_fn is None or feasible_fn(r)):
            pts.append(r.y)
        out.append((i, hypervolume(np.array(pts), ref) if pts else 0.0))
    return out
