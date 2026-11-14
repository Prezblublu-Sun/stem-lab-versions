"""一张图——另一种写法。图的数据经操作台核心取；取不出来只说一声，不进记录。"""
from __future__ import annotations

from stemlab.desk.core import query


def picture(experiment: str, name: str) -> dict:
    try:
        return {"name": name, "data": query.chart(experiment, name)}
    except Exception as error:  # noqa: BLE001  图的代码出什么错都只说出来
        return {"name": name, "trouble": f"{type(error).__name__}: {error}"}
