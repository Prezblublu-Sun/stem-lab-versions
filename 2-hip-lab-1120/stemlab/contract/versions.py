"""格式的版本。

每样落盘的东西都带一个 format，写的是它那种格式的版本号。
读到旧版本，用 upcast 转成现在的形状；读到比自己新的版本，说出来，不当成坏数据。
"""
from __future__ import annotations

from typing import Callable

# 契约版本。记进每一轮的来历
CONTRACT = 1

# 每种格式现在的版本
FORMATS = {
    "register": 1,      # 登记链的一条
    "links": 1,         # 手动挂接的一条
    "issued": 1,        # 发号链的一条
    "record": 1,        # 实验记录的一条
    "manifest": 1,      # 文件夹形态的东西共用的清单
    "points": 1,        # 一批点、候选池
    "bone_model": 1,    # 骨模型、候选骨模型
    "data": 1,          # 数据、一份预测
    "package": 2,       # 带代码的包。第 2 版加了 programs、declarations、modes、inputs、outputs、test_round
    "stem_model": 1,    # 柄的模型：柄空间包交给有限元包、推导量定义包的，不进账（formats/stem_model.py）
    "machines": 1,      # 机器清单
    "backup": 1,        # 备份时记下的链头
}

# (格式, 旧版本) -> 把这个版本转成下一个版本的函数
UPCASTS: dict[tuple[str, int], Callable[[dict], dict]] = {
    # 包的第 2 版只多了几段（原来的几种包可以不写）：第 1 版的清单只改版本号
    ("package", 1): lambda old: {**old, "format": 2},
}


class NewerFormat(ValueError):
    """读到了比自己新的格式版本。数据没坏，是这份代码旧了。"""


class CannotUpcast(ValueError):
    """旧版本的东西转不成现在的形状。"""


def upcast(name: str, obj: dict) -> dict:
    """把一条条目或一份清单转成现在的形状。已经是现在的版本就原样返回。"""
    current = FORMATS[name]
    version = obj.get("format") if isinstance(obj, dict) else None
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CannotUpcast(f"{name}：没有写格式版本，或者写的不是正整数：{version!r}")
    if version > current:
        raise NewerFormat(f"{name} 的格式是第 {version} 版，这份代码只认到第 {current} 版，要先更新代码")
    while version < current:
        step = UPCASTS.get((name, version))
        if step is None:
            raise CannotUpcast(f"{name} 的第 {version} 版转不成第 {current} 版：没有写怎么转")
        obj = step(obj)
        if obj.get("format") != version + 1:
            raise CannotUpcast(f"{name} 的第 {version} 版转完之后不是第 {version + 1} 版")
        version += 1
    return obj
