"""【展示】训练过程、留出上预测对真值、各预测量的误差、合格线、各点的预测、复核的散点。只读，可以整个重写。

图表只给数据，画由界面统一画。数据从插件给图表留的那一份里读（work/shown/r<轮号>/）。数据的样子：
    table     {"columns": [列名…], "rows": [[一行的各格]…]}
    line      {"series": [{"name", "x": [...], "y": [...]}], "x_label", "y_label"}
    scatter   同 line
"""
from __future__ import annotations

import json


def _shown(handle, name: str):
    for number in range(handle.round.number, 0, -1):
        path = handle.work_dir / "shown" / f"r{number}" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_bytes())
    return None


def _round(value):
    return round(value, 5) if isinstance(value, float) else value


def chart(handle, name: str):
    if name in ("history", "holdout", "errors", "verdicts"):
        body = _shown(handle, "errors") or {}
        if name == "history":
            history = (body.get("training") or {}).get("history") or []
            keys = [key for key in ("train_rmse", "oob_rmse") if any(row.get(key) is not None for row in history)]
            return {"series": [{"name": key, "x": [row["member"] for row in history], "y": [row.get(key) for row in history]}
                               for key in keys], "x_label": "成员", "y_label": "均方根差（拟合的刻度上）"}
        if name == "holdout":                           # 各量单位不同：每个量按自己真值的范围归一到 0 到 1，落在对角线上就是预测准
            series = []
            for target, pairs in ((body.get("pairs") or {}).get("holdout") or {}).items():
                low, high = min((pair[0] for pair in pairs), default=0.0), max((pair[0] for pair in pairs), default=1.0)
                wide = (high - low) or 1.0
                series.append({"name": target, "x": [(pair[0] - low) / wide for pair in pairs], "y": [(pair[1] - low) / wide for pair in pairs]})
            return {"series": series, "x_label": "FEA（每个量按自己的范围归一）", "y_label": "预测"}
        if name == "errors":
            rows = [[part, target, *(_round(numbers.get(key)) for key in ("n", "rmse", "mae", "bias", "r2", "coverage", "scale"))]
                    for part in ("holdout", "outside") for target, numbers in (body.get(part) or {}).items()]
            return {"columns": ["哪一部分", "预测量", "点数", "rmse", "mae", "bias", "r2", "区间覆盖率", "刻度"], "rows": rows}
        return {"columns": ["线", "看什么", "量到的", "线在哪", "过没过"],
                "rows": [[row["id"], row["what"], _round(row["value"]), f"{row['metric']} {row['op']} {row['limit']}",
                          {True: "过", False: "没过", None: "不可判"}[row["passed"]]] for row in body.get("verdicts") or []]}
    if name == "predictions":                           # 场不放进表里：只说这个点有没有给出这个场
        body = _shown(handle, "prediction") or {"columns": [], "rows": []}
        names = [column["name"] for column in body["columns"] if column.get("role") != "field"]
        fields = [column["name"] for column in body["columns"] if column.get("role") == "field"]
        return {"columns": ["点", *(f"{column} [{group}]" for column in names for group in ("下界", "预测", "上界")),
                            *(f"场 {field}" for field in fields)],
                "rows": [[row["point"][:12], *(_round(row[group][column]) for column in names for group in ("lower", "values", "upper")),
                          *("有" if field in (row.get("fields") or {}) else "没有" for field in fields)]
                         for row in body["rows"]]}
    body = _shown(handle, "check") or {"columns": [], "matched": []}
    if name == "check":
        return {"series": [{"name": column, "x": [row["fe"][column] for row in body["matched"] if row["diff"][column] is not None],
                            "y": [row["predicted"][column] for row in body["matched"] if row["diff"][column] is not None]}
                           for column in body["columns"]], "x_label": "FEA", "y_label": "预测"}
    if name == "diffs":
        fields = body.get("fields") or []
        return {"columns": ["点", "FEA 的结局", *(f"{column} 预测减 FEA" for column in body["columns"]),
                            *(f"场 {field} 的均方根差" for field in fields)],
                "rows": [[row["point"][:12], row["outcome"], *(_round(row["diff"][column]) for column in body["columns"]),
                          *(_round(((row.get("fields") or {}).get(field) or {}).get("rmse")) for field in fields)]
                         for row in body["matched"]]}
    raise ValueError(f"没有叫 {name} 的图")
