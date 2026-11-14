"""【冻结】不满足约束的点不出现在一批点里，和用哪份策略无关。

约束有两处来源，都不靠策略自觉：
    候选池里记的可不可行（内核模板化的结果）：feasible 不是 true 的设计不能选
    目标和约束（登记的 objective）里写的、不做 FE 就判得了的约束

目标和约束（objective）的写法：
    {"version": "v1",
     "objectives":  [{"column": "rotation", "goal": "min", "weight": 1.0}],
     "constraints": [{"id": "c1", "what": "柄长不超过 50", "on": "design", "column": "length", "op": "<=", "limit": 50}]}
    on 是 design：拿设计里的一项比；on 是 info：拿候选池里模板化给的一项比（比如去骨量）。
    要做了 FE 才知道的约束（比如微动）不写在这里：那是策略打分和 fea.run 判据的事。

设计范围（opt.pool 的输入）的写法：
    {"design": {"length": [20, 60], "behave": {"values": ["ok"]}}, "count": 200, "seed": 5}
    一项写 [最小, 最大] 是连续的数，写 {"values": [...]} 是只取这几个值。
"""
from __future__ import annotations

import json

OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
ON = ("design", "info")
GOALS = ("min", "max")
CONSTRAINT_KEYS = ("id", "what", "on", "column", "op", "limit")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def problems(objective) -> list[str]:
    """一份目标和约束写得对不对。"""
    if not isinstance(objective, dict):
        return ["目标和约束必须是一个 JSON 对象"]
    found = []
    if not isinstance(objective.get("version"), str) or not objective["version"].strip():
        found.append("目标和约束要写 version：这是哪一版")
    goals = objective.get("objectives")
    if not isinstance(goals, list) or not goals or not all(
            isinstance(goal, dict) and isinstance(goal.get("column"), str) and goal.get("goal") in GOALS
            and (goal.get("weight", 1.0) > 0 if _number(goal.get("weight", 1.0)) else False) for goal in goals):
        found.append(f"objectives 至少一条，每条写 column 和 goal（{list(GOALS)} 之一），weight 可以不写")
    limits = objective.get("constraints", [])
    if not isinstance(limits, list):
        return found + ["constraints 要写成一组约束"]
    seen = []
    for number, limit in enumerate(limits, start=1):
        if not isinstance(limit, dict) or set(limit) != set(CONSTRAINT_KEYS):
            found.append(f"第 {number} 条约束要带且只带 {list(CONSTRAINT_KEYS)}")
            continue
        seen.append(limit["id"])
        if limit["on"] not in ON or limit["op"] not in OPS or not isinstance(limit["column"], str):
            found.append(f"第 {number} 条约束（{limit['id']}）：on 只有 {list(ON)}，op 只有 {list(OPS)}")
    if len(set(map(str, seen))) != len(seen):
        found.append("约束的 id 有重复的")
    return found


def range_problems(space) -> list[str]:
    """一份设计范围写得对不对。"""
    if not isinstance(space, dict) or not isinstance(space.get("design"), dict) or not space["design"]:
        return ["设计范围要写 design：每个设计项的范围"]
    found = []
    for name, limits in space["design"].items():
        continuous = isinstance(limits, list) and len(limits) == 2 and all(map(_number, limits)) and limits[0] <= limits[1]
        listed = isinstance(limits, dict) and set(limits) == {"values"} and isinstance(limits["values"], list) and limits["values"]
        if not continuous and not listed:
            found.append(f"设计项 {name} 的范围要写成 [最小, 最大]，或者 {{\"values\": [...]}}")
    if isinstance(space.get("count"), bool) or not isinstance(space.get("count"), int) or space["count"] < 1:
        found.append("设计范围要写 count：取多少个设计")
    if isinstance(space.get("seed"), bool) or not isinstance(space.get("seed"), int):
        found.append("设计范围要写 seed：一个整数")
    return found


def inside(design, space: dict) -> str | None:
    """一个设计在不在设计范围里。在就返回 None；不在返回为什么。"""
    if not isinstance(design, dict) or sorted(design) != sorted(space["design"]):
        return f"设计项对不上：范围里是 {sorted(space['design'])}"
    for name, limits in space["design"].items():
        value = design[name]
        if isinstance(limits, dict):
            if value not in limits["values"]:
                return f"{name}={value!r} 不在 {limits['values']} 里"
        elif not _number(value) or not limits[0] <= value <= limits[1]:
            return f"{name}={value!r} 不在 [{limits[0]}, {limits[1]}] 里"
    return None


def violations(candidate: dict, objective: dict) -> list[str]:
    """候选池里的一个候选不满足哪几条。空列表就是可行。"""
    found = []
    if candidate.get("feasible") is not True:
        why = (candidate.get("info") or {}).get("reason")
        found.append("候选池里记着它放不进去" + (f"（{why}）" if why else ""))
    for limit in objective.get("constraints", []):
        value = (candidate.get(limit["on"]) or {}).get(limit["column"])
        try:
            fine = value is not None and bool(OPS[limit["op"]](value, limit["limit"]))
        except TypeError:
            fine = False
        if not fine:
            found.append(f"不满足约束 {limit['id']}（{limit['what']}）：{limit['column']}={value!r}，要 {limit['op']} {limit['limit']!r}")
    return found


def points(chosen, pool, objective: dict, conditions: dict, count: int | None = None) -> tuple:
    """策略选出的名字，变成一批点的各行（理由先空着）。不在池里的、选重的、不可行的拦下，各说一句。

    count 给了就最多留这么多个，照策略给的先后留前面的。
    """
    by = {row["name"]: row for row in pool}
    made, blocked, seen = [], [], set()
    for pick in chosen if isinstance(chosen, list) else []:
        name = pick.get("name") if isinstance(pick, dict) else None
        row = by.get(name) if isinstance(name, str) else None
        if row is None:
            blocked.append(f"策略选了候选池里没有的 {name!r}，已拦下")
        elif name in seen:
            blocked.append(f"策略把 {name} 选了两次，只留一次")
        else:
            wrong = violations(row, objective)
            if wrong:
                blocked.append(f"策略选了不可行的 {name}，已拦下：" + "；".join(wrong))
            else:
                seen.add(name)
                made.append({"name": name, "bone_id": row["bone_id"], "design": row["design"], "conditions": dict(conditions), "reason": None})
    return (made if count is None else made[:count]), blocked


def _key(bone_id, design) -> str:
    return json.dumps([bone_id, design], sort_keys=True, ensure_ascii=False)


def recheck(batch, pool, objective: dict) -> list[str]:
    """写出的一批点再独立核一遍：每个点的设计都在候选池里、可行、满足约束。空列表就是全部满足。"""
    by = {_key(row["bone_id"], row["design"]): row for row in pool}
    found = []
    for point in batch:
        row = by.get(_key(point["bone_id"], point["design"]))
        wrong = ["它的设计不在候选池里"] if row is None else violations(row, objective)
        if wrong:
            found.append(f"点 {point['name']}：" + "；".join(wrong))
    return found
