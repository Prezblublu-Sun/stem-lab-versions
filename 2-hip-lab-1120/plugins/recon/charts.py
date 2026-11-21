"""【展示】各步用时、网格质量分布、量出来的数、待检查清单、检查结果、股骨颈最细的截面。只读，可以整个重写。

图表只给数据，画由界面统一画。数据从插件给图表留的那一份里读（work/shown/r<轮号>/），不去翻重建代码自己的文件：
这样重建换一种写法，图照样有。数据的样子：
    table     {"columns": [列名…], "rows": [[一行的各格]…]}
    bar       {"labels": [每根柱的名字…], "values": [数…], "unit": 单位}
    scatter   {"series": [{"name", "x": [...], "y": [...]}], "x_label", "y_label"}
"""
from __future__ import annotations

import json


def _shown(handle, name: str) -> dict:
    """插件给图表留的那一份；这一轮没有就往前找。"""
    for number in range(handle.round.number, 0, -1):
        path = handle.work_dir / "shown" / f"r{number}" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_bytes())
    return {}


def chart(handle, name: str):
    rebuilt = _shown(handle, "rebuilt")
    if name == "steps":
        timings = rebuilt.get("timings") or {}
        return {"labels": list(timings), "values": list(timings.values()), "unit": "s"}
    if name == "mesh":                                  # 两个实体的表面三角网：三角形质量（正三角形是 1）落在各段里的个数
        short = {"cortical": "皮质", "cancellous": "松质"}
        labels, values = [], []
        for solid, found in (rebuilt.get("mesh_quality") or {}).items():
            labels += [f"{short.get(solid, solid)} {low:.1f}" for low in found["edges"][:-1]]
            values += found["counts"]
        return {"labels": labels, "values": values, "unit": "个三角形"}
    if name == "measures":
        return {"columns": ["量", "数"], "rows": [[key, value] for key, value in sorted((rebuilt.get("measures") or {}).items())]}
    if name == "todo":
        return {"columns": ["看什么", "要留意", "为什么"],
                "rows": [[row["item"], "是" if row["doubt"] else "", row["why"]] for row in rebuilt.get("todo") or []]}
    if name == "checks":
        return {"columns": ["检查", "数", "线", "过没过"],
                "rows": [[row["name"], row["value"], json.dumps(row["limit"], ensure_ascii=False), "过" if row["passed"] else "没过"]
                         for row in _shown(handle, "gate").get("checks") or []]}
    if name == "neck":
        loop = rebuilt.get("neck_loop") or []
        return {"series": [{"name": "颈最细截面的最外圈", "x": [point[0] for point in loop], "y": [point[2] for point in loop]}],
                "x_label": "x (mm)", "y_label": "z (mm)"}
    raise ValueError(f"没有叫 {name} 的图")
