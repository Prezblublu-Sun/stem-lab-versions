"""【展示】候选的分数分布、选中的点在设计范围里的位置、每个点的理由；候选池里各个候选可不可行。只读，可以整个重写。

图表只给数据，画由界面统一画。数据从插件给图表留的那一份里读（work/shown/r<轮号>/）。
"""
from __future__ import annotations

import json


def _shown(handle, name: str) -> dict:
    for number in range(handle.round.number, 0, -1):
        path = handle.work_dir / "shown" / f"r{number}" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_bytes())
    return {}


def _numbers(rows) -> list[str]:
    """各行的设计里是数的那几项的名字。"""
    first = rows[0]["design"] if rows else {}
    return [name for name in sorted(first) if isinstance(first[name], (int, float)) and not isinstance(first[name], bool)]


def chart(handle, name: str):
    if name in ("candidates", "feasible"):
        rows = _shown(handle, "pool").get("rows") or []
        if name == "feasible":
            fine = sum(1 for row in rows if row["feasible"])
            return {"labels": ["可行", "不可行"], "values": [fine, len(rows) - fine], "unit": "个"}
        items = sorted(rows[0]["design"]) if rows else []
        return {"columns": ["候选", "可行", *items, "模板化说的"],
                "rows": [[row["name"], "是" if row["feasible"] else "否", *(row["design"][item] for item in items),
                          json.dumps(row["info"], ensure_ascii=False)] for row in rows]}
    body = _shown(handle, "select")
    points = body.get("points") or []
    if name == "chosen":
        return {"columns": ["点", "分数", "为什么", "用的模型", "拦下的"],
                "rows": [[row["name"], row["reason"].get("score"), row["reason"].get("why"), str(row["reason"].get("model")), ""]
                         for row in points] + [["", "", "", "", text] for text in body.get("blocked") or []]}
    if name == "where":
        items = _numbers(points)[:2]
        if len(items) < 2:
            return {"series": [{"name": "选中的点", "x": list(range(len(points))), "y": [row["design"][items[0]] for row in points] if items else []}],
                    "x_label": "第几个", "y_label": items[0] if items else ""}
        return {"series": [{"name": "选中的点", "x": [row["design"][items[0]] for row in points], "y": [row["design"][items[1]] for row in points]}],
                "x_label": items[0], "y_label": items[1]}
    if name == "scores":
        picks = [pick for pick in body.get("chosen") or [] if isinstance(pick, dict) and isinstance(pick.get("score"), (int, float))]
        return {"labels": [str(pick.get("name")) for pick in picks], "values": [pick["score"] for pick in picks], "unit": "分"}
    raise ValueError(f"没有叫 {name} 的图")
