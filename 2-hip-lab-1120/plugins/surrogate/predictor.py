"""【冻结】把模型打成包：权重和设备无关、不存路径对象、推理代码放进包里、带自检样本和适用范围；in_range(点)。

包里有什么（包的格式见 stemlab/contract/formats/package.py）：

    code/main.py       入口，这里写死的一份（MAIN）：读点、核适用范围、叫 infer.predict、核它给的数、写结果
    code/scope.py      核适用范围的那个函数，从这个文件原样抄进去
    code/infer.py      模型自己的推理代码，从 models/ 里原样抄进来。只用 numpy 和标准库，不 import plugins、stemlab：
                       这样插件以后重写了，旧的包照样出同样的预测
    data/weights.npz   权重：只有数的数组（numpy 自己的格式，不用 pickle），哪台机器、有没有 GPU 都读得出
    data/meta.json     特征怎么算、预测哪几列、区间的名义覆盖率、适用范围。纯 JSON，路径对象写不进去
    data/selftest/     自检样本：几个训练过的点，和打包时拿这个包自己跑出来的结果

入口只把点的骨标识、设计、条件交给推理代码，所以特征里不可能有 FE 算出来的量。

适用范围（清单的 range），由训练那一部分数据定，不由训练代码说：
    {"bones": ["femur042"], "design": {"length": {"min": 20, "max": 60}, "behave": {"values": ["ok"]}},
     "conditions": {"load": {"min": 1500, "max": 2500}}}
骨标识要在 bones 里；是数的项要落在最小和最大之间；不是数的项要是见过的那几个值之一。项多了、少了，都算不在范围里。
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST = "manifest.json"
TOLERANCE = {"rel": 1e-6, "abs": 1e-9}
GROUPS = {"design": "design", "condition": "conditions"}        # 列的 role -> 点里的哪一组
PREDICTABLE = ("label", "derived")
STORE = "data"                                                  # 包里放权重、说明和自检样本的文件夹，名字是包的格式定的
SAMPLE = "/".join((STORE, "selftest", "sample"))


def in_range(scope: dict, point: dict):
    """这个点在不在适用范围里。在就返回 None；不在返回为什么。"""
    if point.get("bone_id") not in scope.get("bones", []):
        return f"骨 {point.get('bone_id')!r} 不在适用范围里（{scope.get('bones', [])}）"
    for group in ("design", "conditions"):
        allowed, given = scope.get(group, {}), point.get(group) or {}
        if sorted(allowed) != sorted(given):
            return f"{group} 的项对不上：预测器认的是 {sorted(allowed)}，点里是 {sorted(given)}"
        for name in sorted(allowed):
            limits, value = allowed[name], given[name]
            if "values" in limits:
                if value not in limits["values"]:
                    return f"{name}={value!r} 不在 {limits['values']} 里"
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not limits["min"] <= value <= limits["max"]:
                return f"{name}={value!r} 不在 [{limits['min']}, {limits['max']}] 里"
    return None


MAIN = '''\
"""Entry of a stem-lab predictor package. Written at pack time by plugins/surrogate/predictor.py; do not edit.

usage:  python code/main.py <input folder> <output folder>
input:  job.json     {"points": [{"hash", "bone_id", "design", "conditions"}]}
output: result.json  {"rows": [{"point", "values", "lower", "upper"}], "skipped": [{"point", "why"}]}
"""
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import infer  # noqa: E402
from scope import in_range  # noqa: E402


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    points = json.loads((source / "job.json").read_text(encoding="utf-8"))["points"]
    meta = json.loads((HERE.parent / "data" / "meta.json").read_text(encoding="utf-8"))
    with np.load(HERE.parent / "data" / "weights.npz", allow_pickle=False) as stored:
        weights = {name: stored[name] for name in stored.files}
    asked, skipped = [], []
    for point in points:
        why = in_range(meta["scope"], point)
        if why:
            skipped.append({"point": point["hash"], "why": why})
        else:
            asked.append(point)
    rows = []
    if asked:
        given = [{"bone_id": one["bone_id"], "design": one["design"], "conditions": one["conditions"]} for one in asked]
        for point, said in zip(asked, infer.predict(weights, meta, given), strict=True):
            row = {"point": point["hash"], "values": {}, "lower": {}, "upper": {}}
            for target in meta["targets"]:
                value, low, high = (float(said[key][target]) for key in ("values", "lower", "upper"))
                if not all(map(math.isfinite, (value, low, high))) or not low <= value <= high:
                    raise ValueError(f"{target}: the model gave {low} <= {value} <= {high} for point {point['hash'][:12]}")
                row["values"][target], row["lower"][target], row["upper"][target] = value, low, high
            rows.append(row)
    (out / "result.json").write_text(json.dumps({"rows": rows, "skipped": skipped}), encoding="utf-8")


if __name__ == "__main__":
    main()
'''
SCOPE = '"""The range check of a stem-lab predictor package. Copied at pack time from plugins/surrogate/predictor.py."""\n\n\n' \
        + inspect.getsource(in_range)


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def scope_of(rows, columns) -> dict:
    """适用范围：这些行（训练那一部分）的骨、设计和条件各项的范围。"""
    scope = {"bones": sorted({row["bone_id"] for row in rows}), "design": {}, "conditions": {}}
    for column in columns:
        group = GROUPS.get(column["role"])
        if group is None:
            continue
        values = [row["values"][column["name"]] for row in rows]
        if values and all(_number(value) for value in values):
            scope[group][column["name"]] = {"min": min(values), "max": max(values)}
        else:
            scope[group][column["name"]] = {"values": sorted({json.dumps(value): value for value in values}.values(), key=json.dumps)}
    return scope


def as_point(row: dict, columns) -> dict:
    """数据（或留出时不带结果）的一行，写成交给预测器的一个点：哈希、骨标识、设计、条件。"""
    point = {"hash": row["point"], "bone_id": row["bone_id"], "design": {}, "conditions": {}}
    for column in columns:
        if column["role"] in GROUPS:
            point[GROUPS[column["role"]]][column["name"]] = row["values"][column["name"]]
    return point


def targets_of(columns, names) -> list[dict]:
    """要预测的各列的说明：名字、单位、含义、role。只有 FE 算出来的标量列（标签、推导量）能预测。"""
    listed = {column["name"]: column for column in columns}
    wrong = [name for name in names if name not in listed or listed[name]["role"] not in PREDICTABLE]
    if wrong:
        raise ValueError(f"这几个量预测不了（数据里没有，或者不是标签、推导量）：{wrong}")
    return [dict(listed[name]) for name in names]


def pack(folder, *, infer, weights: dict, meta: dict, columns: list, level: float, scope: dict, samples: list,
         requires=()) -> Path:
    """把一个训练好的模型打成预测器的包。哪里不合规矩就报 ValueError，不出包。

    infer 是模型的推理代码文件；weights 是 名字 -> 数组；meta 是推理要用的别的东西（纯 JSON）；
    columns 是预测的各列的说明；samples 是几个在适用范围里的点，拿来做自检样本。
    """
    import numpy as np

    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    for part in ("code", STORE, f"{SAMPLE}/input"):
        (folder / part).mkdir(parents=True, exist_ok=True)
    arrays = {}
    for name, value in weights.items():
        array = np.asarray(value)
        if array.dtype.kind not in "fiub":
            raise ValueError(f"权重 {name!r} 不是数的数组（{array.dtype}）：包里只放数，才和设备无关")
        arrays[name] = np.ascontiguousarray(array)
    np.savez(folder / STORE / "weights.npz", **arrays)
    body = dict(meta, targets=[column["name"] for column in columns], level=level, scope=scope)
    try:
        (folder / STORE / "meta.json").write_bytes(dumps(body))
    except (TypeError, ValueError) as error:
        raise ValueError(f"meta 里有写不进 JSON 的东西（路径对象、NaN 之类）：{error}") from None
    code = Path(infer).read_text(encoding="utf-8")
    banned = [word for word in ("plugins", "stemlab") if f"import {word}" in code or f"from {word}" in code]
    if banned:
        raise ValueError(f"推理代码不能 import {banned}：包要离开插件也能跑")
    (folder / "code" / "infer.py").write_bytes(code.replace("\r\n", "\n").encode("utf-8"))
    (folder / "code" / "main.py").write_bytes(MAIN.encode("utf-8"))
    (folder / "code" / "scope.py").write_bytes(SCOPE.encode("utf-8"))

    outside = [why for why in (in_range(scope, point) for point in samples) if why]
    if not samples or outside:
        raise ValueError("自检样本要是几个在适用范围里的点" + (f"：{outside[0]}" if outside else ""))
    (folder / SAMPLE / "input" / "job.json").write_bytes(dumps({"points": samples}))
    scratch = folder.parent / f"{folder.name}-selftest"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:                                                # 自检的标准答案：拿这个包自己跑一遍，证明它离开插件也能跑
        done = subprocess.run([sys.executable, "code/main.py", str(folder / SAMPLE / "input"), str(scratch)], cwd=folder,
                              capture_output=True, timeout=600, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
        if done.returncode != 0:
            raise ValueError("打好的包自己跑不起来：" + done.stderr.decode("utf-8", "replace")[-800:])
        result = json.loads((scratch / "result.json").read_bytes())
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if result["skipped"] or len(result["rows"]) != len(samples):
        raise ValueError("自检样本没有全部出数")
    (folder / SAMPLE / "expected.json").write_bytes(dumps(result))

    files = sorted((path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()),
                   key=lambda rel: rel.encode("utf-8"))
    listed = {"format": 1, "kind": "predictor", "files": files, "entry": ["{python}", "code/main.py"],
              "requires": ["python>=3.12", "numpy>=2", *requires], "tolerance": TOLERANCE,
              "selftest": [{"name": "sample", "input": f"{SAMPLE}/input", "expected": f"{SAMPLE}/expected.json"}],
              "range": scope, "columns": columns, "level": level}
    (folder / MANIFEST).write_bytes(dumps(listed))
    return folder


def problems(folder, *, columns=None, level=None, scope=None, packed_here: bool = False) -> list[str]:
    """一个预测器的包合不合规矩。空列表就是合。

    给了 columns、level、scope，就连清单里写的是不是这几样一起核。packed_here 说这个包是这个插件刚打出来的：
    那就连入口是不是写死的那一份、权重是不是只有数一起核。外面训练好拿来登记的包不核这两样，它有它自己的入口。
    """
    import numpy as np

    from stemlab import hooks

    folder = Path(folder)
    found = list(hooks.check_format("predictor", folder))
    if found:
        return found
    listed = json.loads((folder / MANIFEST).read_bytes())
    described = listed.get("columns")
    if not isinstance(described, list) or not described or not all(
            isinstance(column, dict) and column.get("role") in PREDICTABLE
            and all(isinstance(column.get(key), str) and column[key].strip() for key in ("name", "unit", "meaning")) for column in described):
        found.append("清单的 columns 要写它预测的各列：name、unit、meaning、role（label 或 derived）")
    if not _number(listed.get("level")) or not 0 < listed["level"] < 1:
        found.append("清单的 level 要写区间的名义覆盖率，在 0 和 1 之间")
    for name, wanted in (("columns", columns), ("level", level), ("range", scope)):
        if wanted is not None and listed.get(name) != wanted:
            found.append(f"包的清单里写的 {name} 不是这次训练该有的那一份")
    if packed_here:
        if not (folder / "code" / "main.py").is_file() or (folder / "code" / "main.py").read_bytes() != MAIN.encode("utf-8"):
            found.append("包的入口不是打包时写死的那一份")
        try:
            with np.load(folder / STORE / "weights.npz", allow_pickle=False) as stored:
                odd = [name for name in stored.files if stored[name].dtype.kind not in "fiub"]
        except (OSError, ValueError) as error:
            found.append(f"权重读不出来（里面只该有数的数组）：{error}")
        else:
            if odd:
                found.append(f"权重里有不是数的数组：{odd}")
    return found
