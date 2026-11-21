"""告警——另一种写法：只有一条线，出过问题的实验有几个。只显示，不动作。"""
from __future__ import annotations


def warnings(listed: list) -> list:
    troubled = [one["id"] for one in listed if one.get("problems")]
    return [f"{len(troubled)} experiments have problems: {' '.join(troubled)}"] if troubled else []
