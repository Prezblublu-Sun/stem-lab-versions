"""【自由】标量的和场的预测器，各有训练和预测。给均值和不确定度。

一种模型是这里的两个文件：
    <名字>.py          训练：fit(points, y, features, options, seed, level) -> (weights, meta, history)
                       points 是训练的点（骨标识、设计、条件）；y 是要预测的量，已经在拟合的刻度上；
                       weights 是 名字 -> 数的数组；meta 是预测时要的别的东西（纯 JSON）；history 是训练过程，给图表看
    <名字>_infer.py    预测：predict(weights, meta, points) -> 每个点 {"values", "lower", "upper"}（各是 预测量 -> 数）
                       它会被原样抄进预测器的包，所以只能用 numpy 和标准库

会预测场的模型另写一句 FIELDS = True，它的 fit 多收一个 fields：{场的名字: 数组（第一维是训练的各行）}，
它的 predict 给每个点多一项 "fields"：{场的名字: 值、下界、上界摞在一起的数组}。meta["fields"] 是场的名字，
meta["field_shapes"] 是各自的形状（打包时冻结代码写进去的）。训练设定要了场、选的模型不会，启动前就被拒。

    ridge   二次岭回归的自助重抽样集成。只预测标量。默认
    pod     标量同 ridge；场用 POD 加岭回归。最简单的一种，用来把场这条路走通

能学的场是每一行形状都一样的数组。各个设计网格不同的点云（现在内核给的界面场就是这种）要先换成共同的写法
（比如重采样到柄自己的坐标网格上）才学得了：这一步放在哪、怎么换，还没有定。

训练设定里写 {"model": {"name": "ridge", …选项}}；不写就是 DEFAULT。训练不出像样的数就抛 Diverged。

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
