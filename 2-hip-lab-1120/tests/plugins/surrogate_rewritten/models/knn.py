"""【自由】最近邻（测试用的另一种模型）：预测是最近 k 个训练点按距离倒数加权的平均，不确定度由它们的分散和留一残差合成。"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np

from plugins.surrogate import models
from plugins.surrogate.models import knn_infer as infer


def fit(points, y, features: dict, options: dict, seed: int, level: float):
    x, y = infer.raw(features, points), np.asarray(y, float)
    k = min(int(options.get("k", 4)), len(x) - 1)
    held, _ = infer.nearest(x, x, y, k, skip_self=True)                 # 留一：每个点由别的点来预测
    sigma = np.sqrt(np.mean((held - y) ** 2, axis=0))
    if not np.isfinite(sigma).all():
        raise models.Diverged("最近邻的留一残差不是有限的数")
    meta = {"k": k, "z": NormalDist().inv_cdf(0.5 + level / 2.0)}
    return {"x": x, "y": y, "sigma": sigma}, meta, [{"member": 0, "train_rmse": 0.0, "oob_rmse": float(sigma.mean())}]
