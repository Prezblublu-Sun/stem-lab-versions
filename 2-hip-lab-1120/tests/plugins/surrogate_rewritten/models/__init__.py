"""【自由】标量的预测器——换成另一种模型（测试用）：最近邻。

和 plugins/surrogate/models/ 的接口一样。用来验蓝图的那一条：把 models/ 整个换成另一种模型，
冻结的四个文件不用改，测试照过；换之前打的包照样出同样的预测。
"""
from __future__ import annotations

import importlib
from pathlib import Path

DEFAULT = "knn"
HERE = Path(__file__).resolve().parent
REWRITTEN = True


class Diverged(Exception):
    """训练发散了。"""


def names() -> list[str]:
    return sorted(path.name[:-len("_infer.py")] for path in HERE.glob("*_infer.py"))


def get(name: str):
    return (importlib.import_module(f"{__name__}.{name}"), importlib.import_module(f"{__name__}.{name}_infer"),
            HERE / f"{name}_infer.py")
