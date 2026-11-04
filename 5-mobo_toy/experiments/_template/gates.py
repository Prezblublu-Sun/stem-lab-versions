"""判据：纯函数，只读冻结的数据版本目录。批准后不能改（ops/guard_pretooluse.py 挡）。

接口：GATES = {编号: 说明}；judge(db_dir) -> {编号: {"status": "PASS"|"FAIL"|"NA", "value": 数, "threshold": 数或字符串, "rows": [job_id], "note": 文字}}
NA = 这条判据需要的数据不在 scalars.csv 里（写明要什么），不是"没判"。
"""
from __future__ import annotations

import csv
import math
import pathlib

GATES = {
    "G99": "示例：行 X 相对行 Y 的转动 Δ（dex）≤ 0.10",
}


def load_rows(db_dir: str) -> list[dict]:
    with open(pathlib.Path(db_dir) / "scalars.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("status") == "DONE"]


def f(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def dex(a: float, b: float) -> float:
    return math.log10(a / b)


def judge(db_dir: str) -> dict:
    rows = load_rows(db_dir)
    out = {}
    # 示例
    out["G99"] = {"status": "NA", "value": None, "threshold": 0.10, "rows": [], "note": "模板，未实现"}
    return out
