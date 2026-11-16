"""【自由】最简单的场模型：POD 加岭回归。只用 numpy。它是用来把“场”这条路走通的，不是定下来的做法。

    标量      和 ridge 一模一样（就是叫它算的）
    场        每个格子减去训练时的均值，做奇异值分解，留前几个模态（POD）；
              每个设计在这几个模态上的系数，用和 ridge 同一套二次岭回归的自助重抽样集成去学
    区间      三样平方相加再开方：集成各成员的分散、系数的袋外残差、留下的模态重建不出来的那一部分

能学的场要每一行形状都一样（比如重采样到同一张网格上的场）。各个设计网格不同的点云，这种模型学不了。

选项（训练设定的 model 里）：degree、members、alphas 同 ridge；modes（最多留几个模态，默认 8）、
energy（留到解释了这么多方差为止，默认 0.9999）。同样的输入和种子，结果相同。
"""
from __future__ import annotations

import numpy as np

from plugins.surrogate import models
from plugins.surrogate.models import ridge

FIELDS = True                       # 这种模型会预测场。训练设定里要了场、模型没有这一句的，启动前就被拒


def _modes(centred: np.ndarray, most: int, energy: float) -> np.ndarray:
    """留下的模态（每行一个）。一个都不留是全零的一行：这个场在训练里处处一样。"""
    _, strength, rows = np.linalg.svd(centred, full_matrices=False)
    power = strength ** 2
    if power.sum() <= 1e-24 * max(1.0, float(centred.size)):
        return np.zeros((1, centred.shape[1]))
    share = np.cumsum(power) / power.sum()
    keep = int(min(most, len(strength), np.searchsorted(share, energy) + 1))
    return rows[:max(keep, 1)]


def fit(points, y, features: dict, options: dict, seed: int, level: float, fields: dict | None = None):
    scalars = np.asarray(y, float).reshape(len(points), -1)
    weights, meta, history = {}, {}, []
    if scalars.shape[1]:
        weights, meta, history = ridge.fit(points, scalars, features, options, seed, level)
    else:                                               # 只预测场：推理时要的那几样还是得有
        _, meta, _ = ridge.fit(points, np.zeros((len(points), 1)), features, options, seed, level)
    kept = {}
    for number, (name, values) in enumerate((fields or {}).items()):
        flat = np.asarray(values, float).reshape(len(points), -1)
        centre = flat.mean(axis=0)
        modes = _modes(flat - centre, int(options.get("modes", 8)), float(options.get("energy", 0.9999)))
        coefficients = (flat - centre) @ modes.T
        learned, _, steps = ridge.fit(points, coefficients, features, options, seed + 1 + number, level)
        floor = np.sqrt(np.mean((flat - centre - coefficients @ modes) ** 2, axis=0))
        if not np.isfinite(modes).all() or not np.isfinite(floor).all():
            raise models.Diverged(f"场 {name} 分解出来的模态不是有限的数")
        weights.update({f"field{number}_coef": learned["coef"], f"field{number}_sigma": learned["sigma"],
                        f"field{number}_modes": modes, f"field{number}_mean": centre, f"field{number}_floor": floor})
        kept[name] = int(len(modes))
        history += [dict(step, field=name) for step in steps] if not history else []
    meta = dict(meta, modes=kept)
    return weights, meta, history
