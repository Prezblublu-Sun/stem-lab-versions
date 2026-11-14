"""【自由】特征。只用不做 FE 就拿得到的量：点里的设计和条件，再加骨标识。

这里只定“怎么算特征”的那份说明（哪几项是数、均值和标准差是多少；哪几项不是数、见过哪几个值；有哪几根骨），
它跟着模型一起存进预测器的包。真正按这份说明把点变成数的代码在各个模型的 *_infer.py 里，因为预测的时候包里只有它。
"""
from __future__ import annotations

import math


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def spec(points) -> dict:
    """照训练的点定下特征的说明。训练里不变的项不进特征（它什么都区分不了）。"""
    numeric, categorical = [], []
    for group in ("design", "conditions"):
        for name in sorted(points[0][group]):
            values = [point[group][name] for point in points]
            if all(_number(value) for value in values):
                mean = sum(values) / len(values)
                std = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
                if std > 1e-12 * max(1.0, abs(mean)):
                    numeric.append({"group": group, "name": name, "mean": mean, "std": std})
            else:
                seen = sorted({repr(value): value for value in values}.values(), key=repr)
                if len(seen) > 1:
                    categorical.append({"group": group, "name": name, "values": seen})
    return {"numeric": numeric, "categorical": categorical, "bones": sorted({point["bone_id"] for point in points})}


def targets(rows, names, scales: dict) -> list[list[float]]:
    """各行要预测的量，换到拟合用的刻度上（log10 的取对数）。"""
    return [[math.log10(row["values"][name]) if scales.get(name) == "log10" else float(row["values"][name]) for name in names]
            for row in rows]


def usable(rows, names, scales: dict) -> list[dict]:
    """能拿来训练的行：要预测的量都有数，取对数的还得是正数。"""
    def fine(row) -> bool:
        return all(_number(row["values"].get(name)) and (scales.get(name) != "log10" or row["values"][name] > 0) for name in names)

    return [row for row in rows if fine(row)]
