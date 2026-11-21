"""【自由】二次多项式的岭回归，自助重抽样成一组。只用 numpy。

    均值        这一组各个成员预测的平均
    不确定度    这一组的分散，和袋外残差的标准差，两样平方相加再开方；区间是均值加减 z 倍，z 由名义覆盖率定
    岭参数      在给的几个里用留一法挑（留一残差有闭式解，不用真的一个个留）

选项（训练设定的 model 里）：degree（1 或 2，默认 2）、members（成员数，默认 20）、alphas（候选的岭参数）。
同样的输入和种子，结果相同：随机只用 numpy 的 default_rng(种子)。
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np

from plugins.surrogate import models
from plugins.surrogate.models import ridge_infer as infer

ALPHAS = (1e-8, 1e-6, 1e-4, 1e-2, 1.0)


def _penalty(width: int, alpha: float, rows: int) -> np.ndarray:
    penalty = np.eye(width) * alpha * rows
    penalty[0, 0] = 0.0                                 # 常数项不罚
    return penalty


def _solve(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    gram = x.T @ x + _penalty(x.shape[1], alpha, len(x))
    try:
        return np.linalg.solve(gram, x.T @ y)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(gram, x.T @ y, rcond=None)[0]


def _leave_one_out(x: np.ndarray, y: np.ndarray, alpha: float) -> float:
    """留一法的均方残差：e_i / (1 - h_ii)。"""
    gram = x.T @ x + _penalty(x.shape[1], alpha, len(x))
    try:
        solved = np.linalg.solve(gram, x.T)
    except np.linalg.LinAlgError:
        return float("inf")
    leverage = np.einsum("ij,ji->i", x, solved)
    residual = y - x @ (solved @ y)
    return float(np.mean((residual / np.maximum(1.0 - leverage, 1e-9)[:, None]) ** 2))


def fit(points, y, features: dict, options: dict, seed: int, level: float):
    degree, members = int(options.get("degree", 2)), int(options.get("members", 20))
    y = np.asarray(y, float)
    x = infer.expand(infer.raw(features, points), degree)
    rows = len(x)
    scores = {float(alpha): _leave_one_out(x, y, float(alpha)) for alpha in options.get("alphas", ALPHAS)}
    alpha = min(scores, key=scores.get)
    rng = np.random.default_rng(seed)
    coef, history = [], []
    total, count = np.zeros_like(y), np.zeros(rows)
    for member in range(members):
        picked = rng.integers(0, rows, rows)
        beta = _solve(x[picked], y[picked], alpha)
        left = np.setdiff1d(np.arange(rows), picked)
        total[left] += x[left] @ beta
        count[left] += 1
        coef.append(beta)
        history.append({"member": member, "train_rmse": float(np.sqrt(np.mean((x[picked] @ beta - y[picked]) ** 2))),
                        "oob_rmse": float(np.sqrt(np.mean((x[left] @ beta - y[left]) ** 2))) if len(left) else None})
    coef = np.stack(coef)
    seen = count > 0
    if seen.sum() >= 3:                                 # 残差用袋外的算：每一行只让没抽到它的成员来预测，不乐观
        sigma = np.sqrt(np.mean((total[seen] / count[seen, None] - y[seen]) ** 2, axis=0))
    else:
        sigma = np.sqrt(np.mean((x @ coef.mean(axis=0) - y) ** 2, axis=0))
    if not np.isfinite(coef).all() or not np.isfinite(sigma).all():
        raise models.Diverged("岭回归出来的权重不是有限的数：多半是特征共线得厉害，或者要预测的量里有离谱的值")
    meta = {"degree": degree, "z": NormalDist().inv_cdf(0.5 + level / 2.0), "alpha": alpha, "members": members,
            "terms": int(x.shape[1]),
            "leave_one_out": {str(key): (value if np.isfinite(value) else None) for key, value in scores.items()}}
    return {"coef": coef, "sigma": sigma}, meta, history
