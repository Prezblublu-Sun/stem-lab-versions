"""【冻结】误差报告：留出误差、往外推的误差、区间覆盖率，写明用的是哪种划分。复核报告：预测和 FEA 按点的哈希对齐后的差。算法固定。

误差怎么算只写在这里，不随模型变：

    n          对得上、算得了的点数
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
on 是 holdout（留出）或 outside（往外推）。这一部分一个点都没有，这条线就是不可判，不当它过了。
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


def errors(truth, predicted, target: str, scale: str = "linear") -> dict:
    """一个预测量的误差。truth 是数据的各行，predicted 是预测的各行；按点的哈希对齐。"""
    guesses = {row["point"]: row for row in predicted}
    diffs, actuals, inside, skipped, unmatched = [], [], 0, 0, 0
    for row in truth:
        actual = row["values"].get(target)
        if not _number(actual):
            continue                                    # 这个点没有这个量的真值（放不进去的点之类）：不在比的范围里
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
    found = {"n": len(diffs), "scale": scale, "skipped": skipped, "unmatched": unmatched}
    if not diffs:
        return dict(found, **{name: None for name in METRICS[1:]})
    n, mean = len(diffs), sum(actuals) / len(actuals)
    squares, spread = sum(d * d for d in diffs), sum((a - mean) ** 2 for a in actuals)
    return dict(found, rmse=math.sqrt(squares / n), mae=sum(abs(d) for d in diffs) / n, bias=sum(diffs) / n,
                r2=1.0 - squares / spread if n >= 2 and spread > 0 else None, max_abs=max(abs(d) for d in diffs),
                coverage=inside / n)


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


def judge(lines, numbers: dict) -> list[dict]:
    """逐条判。numbers 是 {"holdout": {预测量: 误差}, "outside": {...}}。"""
    verdicts = []
    for line in lines or []:
        value = numbers[line["on"]].get(line["target"], {}).get(line["metric"])
        if value is None or (line["metric"] != "n" and not numbers[line["on"]][line["target"]]["n"]):
            verdicts.append(dict(line, value=None, passed=None, why=f"{line['on']} 这一部分没有算得了的点，不可判"))
        else:
            verdicts.append(dict(line, value=value, passed=bool(OPS[line["op"]](value, line["limit"])), why=""))
    return verdicts


def pairs(truth, predicted, target: str) -> list[list]:
    """对得上的点：[真值, 预测, 下界, 上界]。给人看散点用，误差不从这里算。"""
    guesses = {row["point"]: row for row in predicted}
    found = []
    for row in truth:
        actual, guess = row["values"].get(target), guesses.get(row["point"])
        if _number(actual) and guess is not None and _number(guess["values"].get(target)):
            found.append([actual, guess["values"][target], guess["lower"][target], guess["upper"][target]])
    return found


def error_report(*, targets, scales: dict, level: float, split: dict, truth: dict, predicted, lines, training: dict) -> dict:
    """误差报告的内容。truth 是 {"holdout": 各行, "outside": 各行}；predicted 是训练代码对这些点出的预测。"""
    numbers = {part: {target: errors(truth[part], predicted, target, scales.get(target, "linear")) for target in targets}
               for part in ON}
    return {"what": "errors", "split": split, "level": level, "targets": list(targets), "holdout": numbers["holdout"],
            "outside": numbers["outside"], "verdicts": judge(lines, numbers), "training": training,
            "pairs": {part: {target: pairs(truth[part], predicted, target) for target in targets} for part in ON}}


def check_report(predicted, data, columns) -> dict:
    """复核报告的内容：预测和数据按点的哈希对齐。对得上的点逐个有差值；对不上的点两边各列出来。"""
    names = [column["name"] for column in columns]
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
        matched.append(one)
    seen = {guess["point"] for guess in predicted}
    return {"what": "check", "columns": names, "matched": matched, "only_predicted": only_predicted,
            "only_data": [row["point"] for row in data if row["point"] not in seen],
            "summary": {name: errors(data, predicted, name) for name in names}}


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
