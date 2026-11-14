"""来路。只有两种形状，别的登记不上。

    {"from": "external", "note": "...", "by": "..."}                           外面拿来的
    {"from": "product", "experiment": "E0007", "round": 2, "output": "data"}    某个实验某一轮发布的产物

东西之间的关系不另存，由这里的来路和实验存定的输入算出。
"""
from __future__ import annotations

from stemlab.contract.layout import is_experiment_id, is_key

EXTERNAL = "external"
PRODUCT = "product"


def external(note: str, by: str) -> dict:
    """外面拿来的。note 写它是什么、从哪来；by 写是谁登记的。"""
    return {"from": EXTERNAL, "note": note, "by": by}


def product(experiment: str, round: int, output: str) -> dict:  # noqa: A002  round 是记录里的键名
    """某个实验某一轮发布的一样产物。"""
    return {"from": PRODUCT, "experiment": experiment, "round": round, "output": output}


def check_origin(origin) -> list[str]:
    """核对一份来路。返回哪里不符；空列表就是对的。"""
    if not isinstance(origin, dict):
        return ["来路必须是一个 JSON 对象"]
    source = origin.get("from")
    if source == EXTERNAL:
        problems = _keys(origin, ("from", "note", "by"))
        for key in ("note", "by"):
            if not isinstance(origin.get(key), str) or not origin.get(key, "").strip():
                problems.append(f"外面拿来的东西，{key} 必须写，不能是空的")
        return problems
    if source == PRODUCT:
        problems = _keys(origin, ("from", "experiment", "round", "output"))
        if not is_experiment_id(origin.get("experiment")):
            problems.append(f"experiment 不是实验的编号：{origin.get('experiment')!r}")
        number = origin.get("round")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            problems.append(f"round 不是一个轮号：{number!r}")
        if not is_key(origin.get("output")):
            problems.append(f"output 不是一个产物名：{origin.get('output')!r}")
        return problems
    return [f"来路只有 external 和 product 两种，没有 {source!r}"]


def _keys(origin: dict, wanted: tuple) -> list[str]:
    missing = [key for key in wanted if key not in origin]
    extra = [key for key in origin if key not in wanted]
    problems = []
    if missing:
        problems.append(f"来路缺这几项：{missing}")
    if extra:
        problems.append(f"来路多了这几项：{extra}")
    return problems
