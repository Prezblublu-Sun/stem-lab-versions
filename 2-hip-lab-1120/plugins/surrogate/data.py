"""【自由】读数据，照数据说明认出骨、设计、条件、预测量各是哪几列；几份数据里同一个点结果不同的说出来。

一个实验可以填好几份数据。合成一张表时：
    设计和条件的列（名字、单位）每份都要一样，要预测的量每份都要有、单位相同；别的列可以各有各的
    （旧库转来的数据和新算的数据，建模时的量、标签不全一样，但只要这几样对得上就能放在一起训练）
    同一个点（哈希相同）出现几次：结果相同的只留一行；结果不同的留最先见到的那一行，并记一条，由插件报成问题。
    “最先”是填输入的顺序：第 1 份数据里的先于第 2 份。这条规则叫 first，load 返回它，记进误差报告
场不在这里读。要预测的场由冻结代码核对、把训练那一部分的抄进作业文件夹（见 plugin.py），训练代码从那里读。
"""
from __future__ import annotations

import json
from pathlib import Path

from stemlab import hooks

ROWS = "rows.jsonl"
SCALAR = ("design", "condition", "pre", "label", "derived")
RULE = "first"          # 同一个点结果不同时，留填在最前面那份数据里的那一行


def columns_of(folder) -> list[dict]:
    """一份数据的数据说明里不是场的那些列。"""
    listed = json.loads((Path(folder) / "manifest.json").read_bytes())
    return [column for column in listed["columns"] if column["role"] in SCALAR]


def _given(columns) -> list:
    """设计和条件的列：点是由它们定的，几份数据必须一样。"""
    return sorted((column["name"], column["unit"], column["role"]) for column in columns if column["role"] in ("design", "condition"))


def problems(folders, targets) -> list[str]:
    """这几份数据能不能合成一张表来训练。"""
    if not folders:
        return ["至少要填一份数据"]
    first = columns_of(folders[0])
    known = {column["name"]: column for column in first}
    wrong = [name for name in targets if known.get(name, {}).get("role") not in ("label", "derived")]
    found = [f"训练设定要预测的这几个量，数据里没有，或者不是标签、推导量：{wrong}"] if wrong else []
    for number, folder in enumerate(folders[1:], start=2):
        other = {column["name"]: column for column in columns_of(folder)}
        if _given(other.values()) != _given(first):
            found.append(f"第 {number} 份数据的设计、条件各列和第 1 份不一样（名字、单位要都相同），不能合在一起训练")
        differ = [name for name in targets if name in known and (other.get(name, {}).get("unit"), other.get(name, {}).get("role"))
                  != (known[name]["unit"], known[name]["role"])]
        if differ:
            found.append(f"要预测的这几个量，第 {number} 份数据里没有，或者单位不一样：{differ}")
    return found


def load(folders) -> dict:
    """把几份数据合成一张表。返回 columns（不含场）、rows、conflicts（同一个点结果不同的，各说一句）、rule（留哪一行的规则）。"""
    columns, rows, seen, conflicts = columns_of(folders[0]), [], {}, []
    names = [column["name"] for column in columns if column["role"] in ("label", "derived")]      # 结果同不同，看 FE 算出来的那几列
    for number, folder in enumerate(folders, start=1):
        for row in hooks.read_points(Path(folder) / ROWS):
            first = seen.get(row["point"])
            if first is None:
                seen[row["point"]] = (number, row)
                rows.append(row)
            elif any(first[1]["values"].get(name) != row["values"].get(name) for name in names):
                conflicts.append(f"点 {row['point'][:12]} 在第 {first[0]} 份和第 {number} 份数据里结果不同，用了第 {first[0]} 份的")
    return {"columns": columns, "rows": rows, "conflicts": conflicts, "rule": RULE}
