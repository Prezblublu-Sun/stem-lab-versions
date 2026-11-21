"""【冻结】照登记的划分切成训练和留出。留出的行一行都不进训练；按骨分时，留出的骨标识不出现在训练里。

划分是登记的一份设定：

    {"by": "row", "fraction": 0.2, "seed": 7}      按行：一行归哪边由它的点的哈希和种子定。以后数据多了，老的行归属不变
    {"by": "bone", "bones": ["femur043"]}          按骨：这几根骨的行全部留出

    另可加 "outside": [{"column": "length", "min": 20, "max": 50}]
        往外推的那一组：这些列里任何一列落在范围之外的行。它们既不进训练也不算留出，误差单独报。
        只能用设计和条件的列来划：拿 FE 算出来的量划，等于先看了结果

切分只在这里做。交给训练代码的只有 train 那一部分；留出和往外推的行，训练代码只拿到它们的设计和条件，用来出预测，
拿不到 FE 算出来的数。误差由 report.py 在操作台这一边拿真值来算。
"""
from __future__ import annotations

import hashlib

BY = ("row", "bone")
PARTS = ("train", "holdout", "outside")
GIVEN = ("design", "condition")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def problems(setting, columns=None) -> list[str]:
    """一份划分写得对不对。columns 给了数据说明里的各列，就连 outside 用的列一起核。"""
    if not isinstance(setting, dict) or setting.get("by") not in BY:
        return [f"划分要写 by：{list(BY)} 之一"]
    found = []
    if setting["by"] == "row":
        fraction, seed = setting.get("fraction"), setting.get("seed")
        if not _number(fraction) or not 0 < fraction < 1:
            found.append("按行划分要写 fraction：留出的比例，在 0 和 1 之间")
        if isinstance(seed, bool) or not isinstance(seed, int):
            found.append("按行划分要写 seed：一个整数")
    else:
        bones = setting.get("bones")
        if not isinstance(bones, list) or not bones or not all(isinstance(bone, str) and bone for bone in bones):
            found.append("按骨划分要写 bones：留出哪几根骨")
    roles = {column["name"]: column["role"] for column in columns} if columns is not None else None
    outside = setting.get("outside", [])
    if not isinstance(outside, list):
        return found + ["outside 要写成一组 {column, min, max}"]
    for box in outside:
        if not isinstance(box, dict) or not isinstance(box.get("column"), str) or not ("min" in box or "max" in box) \
                or not all(_number(box[bound]) for bound in ("min", "max") if bound in box):
            found.append("outside 的每一项要写 column，和 min、max 里至少一样（都是数）")
        elif roles is not None and roles.get(box["column"]) not in GIVEN:
            found.append(f"outside 只能拿设计和条件的列来划：{box['column']!r} 不是")
    return found


def _share(seed: int, point: str) -> float:
    """这个点在 0 到 1 之间的一个固定位置：只由种子和点的哈希定。"""
    return int(hashlib.sha256(f"{seed}:{point}".encode("utf-8")).hexdigest()[:13], 16) / 16 ** 13


def side(row: dict, setting: dict) -> str:
    """一行归哪一部分：train、holdout 或 outside。"""
    for box in setting.get("outside", []):
        value = row["values"].get(box["column"])
        if _number(value) and (("min" in box and value < box["min"]) or ("max" in box and value > box["max"])):
            return "outside"
    if setting["by"] == "bone":
        return "holdout" if row["bone_id"] in setting["bones"] else "train"
    return "holdout" if _share(setting["seed"], row["point"]) < setting["fraction"] else "train"


def split(rows, setting: dict) -> dict:
    """把各行切成三部分。同一个点在几份数据里出现，归属相同。"""
    parts: dict[str, list] = {name: [] for name in PARTS}
    for row in rows:
        parts[side(row, setting)].append(row)
    wrong = leaks(parts, setting)
    if wrong:
        raise ValueError("划分出了岔子：" + "；".join(wrong))
    return parts


def leaks(parts: dict, setting: dict) -> list[str]:
    """切完再核一遍：训练那一部分里有没有混进留出的点、留出的骨。空列表就是没有。"""
    found = []
    kept = {row["point"] for name in ("holdout", "outside") for row in parts[name]}
    mixed = sorted({row["point"] for row in parts["train"]} & kept)
    if mixed:
        found.append(f"有 {len(mixed)} 个留出的点也在训练里，比如 {mixed[0][:12]}")
    if setting["by"] == "bone":
        bones = sorted({row["bone_id"] for row in parts["train"]} & set(setting["bones"]))
        if bones:
            found.append(f"留出的骨出现在训练里：{bones}")
    return found


def unlabeled(rows, columns) -> list[dict]:
    """留出的行交给训练代码去出预测时的样子：只有点的哈希、骨标识、设计和条件；FE 算出来的数一个都不带。"""
    given = [column["name"] for column in columns if column["role"] in GIVEN]
    return [{"point": row["point"], "bone_id": row["bone_id"], "values": {name: row["values"].get(name) for name in given}}
            for row in rows]


def describe(setting: dict, parts: dict) -> dict:
    """写进误差报告：用的是哪种划分，各部分多少行、多少根骨。"""
    return {"setting": setting, "by": setting["by"],
            "rows": {name: len(parts[name]) for name in PARTS},
            "bones": {name: sorted({row["bone_id"] for row in parts[name]}) for name in PARTS}}
