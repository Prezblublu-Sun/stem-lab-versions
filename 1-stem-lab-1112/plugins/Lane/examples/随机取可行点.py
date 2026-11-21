"""示例策略：在候选池里随机取可行点。

只用来演示 Lane 的约定，不是一份真的选点策略。

约定见 ../说明.md。这里用到的三样：
  inputs["候选池"]      一个列表，或一个内容是列表的 JSON 文件。每个候选有「名字」「设计」和若干个量
  inputs["目标和约束"]  一个对象，或一个 JSON 文件。只用里面的「约束」：[{"量": 名字, "不超过": 数}]
  inputs["已有数据"]    可以不填。一个候选名字的列表（或 JSON 文件），这些点不再选
"""
import json
import random
from pathlib import Path


def load(x):
    """设置是文件就读出来，是值就直接用。"""
    if isinstance(x, Path):
        return json.loads(x.read_text(encoding="utf-8"))
    return x


def select(inputs):
    pool = load(inputs["候选池"])
    limits = load(inputs["目标和约束"]).get("约束", [])
    done = set(load(inputs["已有数据"]) or [])
    n, seed = inputs["选几个点"], inputs["随机种子"]

    feasible = [
        c for c in pool
        if c["名字"] not in done and all(c[lim["量"]] <= lim["不超过"] for lim in limits)
    ]
    rng = random.Random(seed)
    picked = rng.sample(feasible, min(n, len(feasible)))

    points = []
    for c in picked:
        met = "，".join(f"{lim['量']} {c[lim['量']]} 不超过 {lim['不超过']}" for lim in limits) or "没有约束"
        points.append({
            "名字": c["名字"],
            "设计": c["设计"],
            "理由": f"在 {len(feasible)} 个可行候选里随机抽中（种子 {seed}）；{met}",
        })
    return points
