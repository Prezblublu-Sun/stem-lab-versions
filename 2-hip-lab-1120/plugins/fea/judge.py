"""【冻结】按判据判定。判据的登记时间晚于这一轮开始的被拒。

判据是登记的一份设定，要在看到结果之前写定：

    {"criteria": [{"id": "g1", "what": "转动的最大值不超过 1 度", "column": "rotation",
                   "stat": "max", "op": "<=", "limit": 1.0, "missing": "na"}, ...]}

    column    数据里的一列（标量，不是场）
    stat      对这一列在各个点上取什么：min、max、mean、median、count（有数的点有几个）
    op、limit  和线怎么比：<=、<、>=、>
    missing   有的点没有这个数（放不进去、没算出来）时这一条怎么判：
              "na"   不可判（不写就是它）：没算出来的点不是设计的性质，不能悄悄当成没有这个点
              "skip" 只看有数的点

判定结果一条判据一行：passed 是 true、false，或者不可判的 null；另写着算出来的数、用了几个点、几个点没有数。
判定由这里的代码做，不由人看着结果填。
"""
from __future__ import annotations

import operator
import shutil
import statistics
from pathlib import Path

from plugins.fea import export

VERDICT, MANIFEST = "verdict.json", "manifest.json"
STATS = {"min": min, "max": max, "mean": statistics.fmean, "median": statistics.median, "count": len}
OPS = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt}
MISSING = ("na", "skip")
KEYS = ("id", "what", "column", "stat", "op", "limit")


def problems(value, listed: list[dict]) -> list[str]:
    """一份判据写得对不对。listed 是数据说明。返回哪里不对；空列表就是对的。"""
    rows = value.get("criteria") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not rows:
        return ['判据要写成 {"criteria": [...]}，至少一条']
    scalars = {column["name"] for column in listed if column["role"] != "field"}
    found, seen = [], set()
    for number, row in enumerate(rows, start=1):
        title = f"第 {number} 条判据"
        if not isinstance(row, dict) or any(key not in row for key in KEYS):
            found.append(f"{title}要带 {list(KEYS)}")
            continue
        if not isinstance(row["id"], str) or not row["id"] or row["id"] in seen:
            found.append(f"{title}的 id 要写，而且不能重复：{row['id']!r}")
        seen.add(row["id"]) if isinstance(row["id"], str) else None
        if row["column"] not in scalars:
            found.append(f"{title}的 column 不是数据里的一列标量：{row['column']!r}")
        if row["stat"] not in STATS or row["op"] not in OPS or row.get("missing", "na") not in MISSING:
            found.append(f"{title}的 stat 只有 {list(STATS)}，op 只有 {list(OPS)}，missing 只有 {list(MISSING)}")
        if isinstance(row["limit"], bool) or not isinstance(row["limit"], (int, float)):
            found.append(f"{title}的 limit 必须是一个数")
    return found


def late(registered: str | None, opened: str | None) -> bool:
    """这份判据是不是在这一轮开始之后才登记的。时间的写法定长，字符串的先后就是时间的先后。

    登记的时间查不到，也按“晚了”算：证明不了它是看到结果之前写定的。
    """
    return registered is None or opened is None or registered > opened


def judge(value: dict, rows: dict, points: int) -> list[dict]:
    """按判据判定。rows 是进了数据的各行（任务名 -> 行），points 是这批点一共有几个。"""
    verdicts = []
    for row in value["criteria"]:
        numbers = [made["values"].get(row["column"]) for made in rows.values()]
        numbers = [number for number in numbers if isinstance(number, (int, float)) and not isinstance(number, bool)]
        missing = points - len(numbers)
        verdict = {"id": row["id"], "what": row["what"], "column": row["column"], "stat": row["stat"], "op": row["op"],
                   "limit": row["limit"], "used": len(numbers), "missing": missing, "value": None, "passed": None}
        if missing and row.get("missing", "na") == "na":
            verdict["why"] = f"有 {missing} 个点没有这个数，这一条不可判"
        elif not numbers and row["stat"] != "count":
            verdict["why"] = "没有一个点有这个数，这一条不可判"
        else:
            verdict["value"] = STATS[row["stat"]](numbers)
            verdict["passed"] = bool(OPS[row["op"]](verdict["value"], row["limit"]))
        verdicts.append(verdict)
    return verdicts


def write(folder: Path, verdicts: list[dict], criteria: dict, bone_id: str) -> Path:
    """把判定结果写成一份报告。criteria 说用的是哪一份判据：编号、哈希、登记的时间。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / VERDICT).write_bytes(export.dumps({"criteria": criteria, "verdicts": verdicts}))
    (folder / MANIFEST).write_bytes(export.dumps({"format": 1, "kind": "report", "files": [VERDICT], "bone_id": bone_id,
                                                  "what": "verdict"}))
    return folder
