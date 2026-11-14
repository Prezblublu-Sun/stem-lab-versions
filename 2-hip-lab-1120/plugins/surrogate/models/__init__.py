"""【自由】标量的预测器，各有训练和预测。给均值和不确定度。

一种模型是这里的两个文件：
    <名字>.py          训练：fit(points, y, features, options, seed, level) -> (weights, meta, history)
                       points 是训练的点（骨标识、设计、条件）；y 是要预测的量，已经在拟合的刻度上；
                       weights 是 名字 -> 数的数组；meta 是预测时要的别的东西（纯 JSON）；history 是训练过程，给图表看
    <名字>_infer.py    预测：predict(weights, meta, points) -> 每个点 {"values", "lower", "upper"}（各是 预测量 -> 数）
                       它会被原样抄进预测器的包，所以只能用 numpy 和标准库

训练设定里写 {"model": {"name": "ridge", …选项}}；不写就是 DEFAULT。训练不出像样的数就抛 Diverged。
场的预测器 1.0 没有：各个设计的界面网格不一样，场没有一个共同的写法可以拿来学。

整个文件夹可以换成另一种模型：冻结的四个文件不用动。
"""
from __future__ import annotations

import importlib
from pathlib import Path

DEFAULT = "ridge"
HERE = Path(__file__).resolve().parent


class Diverged(Exception):
    """训练发散了：出来的权重不是有限的数。"""


def names() -> list[str]:
    return sorted(path.name[:-len("_infer.py")] for path in HERE.glob("*_infer.py"))


def get(name: str):
    """（训练的模块，推理的模块，推理代码的文件）。"""
    return (importlib.import_module(f"{__name__}.{name}"), importlib.import_module(f"{__name__}.{name}_infer"),
            HERE / f"{name}_infer.py")
