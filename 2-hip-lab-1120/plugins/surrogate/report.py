"""【冻结】误差报告：留出误差、往外推的误差、区间覆盖率，写明用的是哪种划分。复核报告：预测和 FEA 按点的哈希对齐后的差。算法固定。

误差怎么算只写在这里，不随模型变：

    n          对得上、算得了的点数
    unmatched  有真值、没有预测的点数
    repeated   有真值、预测给了不止一次的点数：不知道该用哪一次，这些点不比
    rmse       差的平方的均值再开方。差是预测减真值
    mae        差的绝对值的均值
    bias       差的均值
    r2         1 减去 残差平方和 除以 真值的离差平方和。不到两个点、或者真值都一样时是 null
    max_abs    差的绝对值里最大的
    coverage   真值落在预测区间里的比例。区间的名义覆盖率是预测器的 level

在哪个刻度上算由训练设定说：{"scale": {"rotation": "log10"}}，没写的列是 linear。
在 log10 上算的时候，真值或预测不是正数的点算不了，单独数出来（skipped）。覆盖率总是拿原来的数比。

合格线写在训练设定里，训练设定是存定的输入，所以一定登记在看到结果之前：
    {"acceptance": [{"id": "a1", "what": "…", "target": "rotation", "on": "holdout", "metric": "rmse", "op": "<=", "limit": 0.05}]}
on 是 holdout（留出）或 outside（往外推）。这一部分一个算得了的点都没有，这条线就是不可判，不当它过了；
数点数的线（metric 是 n）也一样。
判之前先核这一部分全不全：有真值的点，每一个都要有一份、只有一份算得了的预测。有点没有预测、给了不止一次、
或者算不了（skipped），这条线也不可判：比不了的点可能正是难预测的点，去掉它们会把误差算小。

场的误差用同样的几个名字（field_errors），逐个格子比，所有点的所有格子合在一起算：
    n 是比得了的点数，cells 是这些点一共多少个格子；rmse、mae、bias、max_abs 是对格子说的；
    r2 的离差是各格子的真值对它们总的均值；coverage 是真值落在区间里的格子的比例
    预测的形状和真值对不上的点比不了，单独数出来（skipped）。场只在原来的刻度上比
合格线的 target 可以是一个场的名字。
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

MANIFEST = "manifest.json"
METRICS = ("n", "rmse", "mae", "bias", "r2", "max_abs", "coverage")
SCALES = ("linear", "log10")
ON = ("holdout", "outside")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
LINE_KEYS = ("id", "what", "target", "on", "metric", "op", "limit")


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _scaled(value, scale: str):
    if scale == "linear":
        return value
    return math.log10(value) if value > 0 else None


def once(predicted) -> tuple[dict, set]:
    """预测按点的哈希排好：（只给了一次的点 -> 那一行，给了不止一次的点）。给了不止一次的不知道该用哪一次，不拿来比。"""
    guesses, twice = {}, set()
    for row in predicted:
        if row["point"] in guesses:
            twice.add(row["point"])
        guesses[row["point"]] = row
    return {point: row for point, row in guesses.items() if point not in twice}, twice


def errors(truth, predicted, target: str, scale: str = "linear") -> dict:
    """一个预测量的误差。truth 是数据的各行，predicted 是预测的各行；按点的哈希对齐。"""
    guesses, twice = once(predicted)
    diffs, actuals, inside, skipped, unmatched, repeated = [], [], 0, 0, 0, 0
    for row in truth:
        actual = row["values"].get(target)
        if not _number(actual):
            continue                                    # 这个点没有这个量的真值（放不进去的点之类）：不在比的范围里
        if row["point"] in twice:
            repeated += 1
            continue
        guess = guesses.get(row["point"])
        if guess is None or not _number(guess["values"].get(target)):
            unmatched += 1
            continue
        a, g = _scaled(actual, scale), _scaled(guess["values"][target], scale)
        if a is None or g is None:
            skipped += 1
            continue
        diffs.append(g - a)
        actuals.append(a)
        inside += guess["lower"][target] <= actual <= guess["upper"][target]
    found = {"n": len(diffs), "scale": scale, "skipped": skipped, "unmatched": unmatched, "repeated": repeated}
    if not diffs:
        return dict(found, **{name: None for name in METRICS[1:]})
    n, mean = len(diffs), sum(actuals) / len(actuals)
    squares, spread = sum(d * d for d in diffs), sum((a - mean) ** 2 for a in actuals)
    return dict(found, rmse=math.sqrt(squares / n), mae=sum(abs(d) for d in diffs) / n, bias=sum(diffs) / n,
                r2=1.0 - squares / spread if n >= 2 and spread > 0 else None, max_abs=max(abs(d) for d in diffs),
                coverage=inside / n)


def field_errors(pairs) -> dict:
    """一个场的误差。pairs 的每一项是一个点：（真值，预测）。真值是一个数组；预测是值、下界、上界摞在一起的数组（第一维是 3）。
    哪一边没有就给 None：没有真值的点不在比的范围里，有真值没有预测的数进 unmatched。"""
    import numpy as np

    points = cells = skipped = unmatched = 0
    squares = absolute = total = inside = worst = actual = actual_squares = 0.0
    for truth, guess in pairs:
        if truth is None:
            continue
        if guess is None:
            unmatched += 1
            continue
        truth, guess = np.asarray(truth, dtype=float), np.asarray(guess, dtype=float)
        if guess.shape != (3, *truth.shape) or not truth.size or not np.isfinite(truth).all() or not np.isfinite(guess).all():
            skipped += 1
            continue
        diff = guess[0] - truth
        points, cells = points + 1, cells + diff.size
        squares, absolute, total = squares + float((diff ** 2).sum()), absolute + float(np.abs(diff).sum()), total + float(diff.sum())
        worst = max(worst, float(np.abs(diff).max()))
        inside += float(((guess[1] <= truth) & (truth <= guess[2])).sum())
        actual, actual_squares = actual + float(truth.sum()), actual_squares + float((truth ** 2).sum())
    found = {"n": points, "scale": "linear", "skipped": skipped, "unmatched": unmatched, "cells": cells}
    if not cells:
        return dict(found, **{name: None for name in METRICS[1:]})
    spread = actual_squares - actual * actual / cells
    return dict(found, rmse=math.sqrt(squares / cells), mae=absolute / cells, bias=total / cells,
                r2=1.0 - squares / spread if cells >= 2 and spread > 1e-12 * max(1.0, actual_squares) else None,
                max_abs=worst, coverage=inside / cells)


def line_problems(lines, targets) -> list[str]:
    """训练设定里的合格线写得对不对。没写（None）是可以的：那就只报误差，不判。"""
    if lines is None:
        return []
    if not isinstance(lines, list):
        return ["acceptance 要写成一组合格线"]
    found, seen = [], []
    for number, line in enumerate(lines, start=1):
        title = f"第 {number} 条合格线"
        if not isinstance(line, dict) or set(line) != set(LINE_KEYS):
            found.append(f"{title}要带且只带 {list(LINE_KEYS)}")
            continue
        seen.append(line["id"])
        if line["target"] not in targets:
            found.append(f"{title}（{line['id']}）的 target 不是这次要预测的量：{line['target']!r}")
        if line["on"] not in ON or line["metric"] not in METRICS or line["op"] not in OPS or not _number(line["limit"]):
            found.append(f"{title}（{line['id']}）：on 只有 {list(ON)}，metric 只有 {list(METRICS)}，op 只有 {list(OPS)}，limit 是数")
    if len(set(map(str, seen))) != len(seen):
        found.append("合格线的 id 有重复的")
    return found


_GAPS = (("unmatched", "没有预测"), ("repeated", "预测给了不止一次"), ("skipped", "算不了（取不了对数、形状不对、不是有限的数）"))


def gaps(found: dict) -> str:
    """这一部分的这个量比不全的地方，一句话；全了是空的。"""
    return "，".join(f"{found[key]} 个点{said}" for key, said in _GAPS if found.get(key))


def judge(lines, numbers: dict) -> list[dict]:
    """逐条判。numbers 是 {"holdout": {预测量: 误差}, "outside": {...}}。这一部分比不全的，不判。"""
    verdicts = []
    for line in lines or []:
        found = numbers[line["on"]].get(line["target"], {})
        value, short = found.get(line["metric"]), gaps(found)
        if short:
            verdicts.append(dict(line, value=None, passed=None,
                                 why=f"{line['on']} 这一部分有 {short}，不可判：比不了的点可能正是难预测的点，去掉它们会把误差算小"))
        elif value is None or not found["n"]:           # 一个算得了的点都没有：数点数的线（n）也不判，不然“n ≤ 10”就判过了
            verdicts.append(dict(line, value=None, passed=None, why=f"{line['on']} 这一部分没有算得了的点，不可判"))
        else:
            verdicts.append(dict(line, value=value, passed=bool(OPS[line["op"]](value, line["limit"])), why=""))
    return verdicts


def pairs(truth, predicted, target: str) -> list[list]:
    """对得上的点：[真值, 预测, 下界, 上界]。给人看散点用，误差不从这里算。给了不止一次预测的点不画。"""
    guesses = once(predicted)[0]
    found = []
    for row in truth:
        actual, guess = row["values"].get(target), guesses.get(row["point"])
        if _number(actual) and guess is not None and _number(guess["values"].get(target)):
            found.append([actual, guess["values"][target], guess["lower"][target], guess["upper"][target]])
    return found


def error_report(*, targets, scales: dict, level: float, split: dict, truth: dict, predicted, lines, training: dict,
                 fields: dict | None = None) -> dict:
    """误差报告的内容。truth 是 {"holdout": 各行, "outside": 各行}；predicted 是训练代码对这些点出的预测。

    fields 是要预测的各个场：{场的名字: {"holdout": 各点的（真值，预测）, "outside": 同样}}，见 field_errors。
    场的误差和标量的排在一起，所以合格线可以拿场的名字当 target。
    """
    numbers = {part: {target: errors(truth[part], predicted, target, scales.get(target, "linear")) for target in targets}
               for part in ON}
    for name, given in (fields or {}).items():
        for part in ON:
            numbers[part][name] = field_errors(given[part])
    body = {"what": "errors", "split": split, "level": level, "targets": list(targets), "holdout": numbers["holdout"],
            "outside": numbers["outside"], "verdicts": judge(lines, numbers), "training": training,
            "pairs": {part: {target: pairs(truth[part], predicted, target) for target in targets} for part in ON}}
    return dict(body, fields=list(fields)) if fields else body


def check_report(predicted, data, columns, fields: dict | None = None) -> dict:
    """复核报告的内容：预测和数据按点的哈希对齐。对得上的点逐个有差值；对不上的点两边各列出来。

    fields 是预测里的各个场：{场的名字: {点的哈希: （FEA 的场，预测的场）}}，哪一边没有就是 None。
    对得上的点另记每个场在这个点上的均方根差、最大的差、真值落在区间里的格子的比例。
    """
    names = [column["name"] for column in columns if column.get("role") != "field"]
    rows = {row["point"]: row for row in data}
    matched, only_predicted = [], []
    for guess in predicted:
        row = rows.get(guess["point"])
        if row is None:
            only_predicted.append(guess["point"])
            continue
        one = {"point": guess["point"], "bone_id": row["bone_id"], "round": row["round"], "outcome": row["outcome"],
               "predicted": {}, "fe": {}, "diff": {}, "inside": {}}
        for name in names:
            guessed, actual = guess["values"].get(name), row["values"].get(name)
            one["predicted"][name], one["fe"][name] = guessed, actual
            both = _number(guessed) and _number(actual)
            one["diff"][name] = guessed - actual if both else None
            one["inside"][name] = bool(guess["lower"][name] <= actual <= guess["upper"][name]) if both else None
        if fields:
            one["fields"] = {}
            for name, given in fields.items():
                found = field_errors([given.get(guess["point"], (None, None))])
                one["fields"][name] = {"rmse": found["rmse"], "max_abs": found["max_abs"], "inside": found["coverage"]} if found["n"] else None
        matched.append(one)
    seen = {guess["point"] for guess in predicted}
    summary = {name: errors(data, predicted, name) for name in names}
    for name, given in (fields or {}).items():
        summary[name] = field_errors([given.get(row["point"], (None, None)) for row in matched])
    body = {"what": "check", "columns": names, "matched": matched, "only_predicted": only_predicted,
            "only_data": [row["point"] for row in data if row["point"] not in seen], "summary": summary}
    return dict(body, fields=list(fields)) if fields else body


def write(folder: Path, what: str, body: dict, bone_id: str | None = None) -> Path:
    """写一份报告的文件夹：report.json 和清单。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / "report.json").write_bytes(dumps(body))
    listed = {"format": 1, "kind": "report", "files": ["report.json"], "what": what}
    (folder / MANIFEST).write_bytes(dumps(dict(listed, bone_id=bone_id) if bone_id else listed))
    return folder
