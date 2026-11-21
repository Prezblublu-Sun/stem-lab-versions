"""贝叶斯优化：拿已有的 FE 结果在策略内部拟合模型，挑“最可能比现在最好的还好”的候选。要填数据。

    用哪些数据     给的数据里同一根骨、条件和这次的条件默认逐项相同、目标的各列都有数的行。
                   不够 max(6, 设计的坐标数 + 2) 行就不选，照实说差多少：硬凑出来的模型不可信
    模型           每个目标一个高斯过程（Matern 5/2，每个设计项各一个长度），输入是缩放到 0 到 1 的设计。
                   全是正数的目标（微动、转动这类）取了对数再拟合
    一个目标       期望改进：这个候选比现在算过的最好的还好多少，按预测的分布取平均
    几个目标       ParEGO 的做法：每选一个点换一组随机权重，把几个目标合成一个数（切比雪夫加一小点加权和），
                   对这个数算期望改进。权重换来换去，选出的点就沿着几个目标之间的取舍铺开。
                   目标里写的 weight 乘在随机权重上：权重大的目标更常被照顾到
    一批点         逐个选。选中一个，就先当它算出来的正好是预测的均值，再选下一个，
                   这样同一批里的点不会挤在同一处
    能选的候选     候选池里可行、满足约束、还没算过的

分数是期望改进（在拟合用的刻度上）。理由里写着每个目标的预测值和 95% 的区间，换回了原来的单位。
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np

import common

CAP = 1500          # 拟合最多用这么多行：再多就取最好的四分之一，加上照种子随机取的
RHO = 0.05          # 切比雪夫合成里加权和那一项的分量
DRAWS = 256         # 几个目标时，每个候选按预测的分布取这么多个样


class Unusable(ValueError):
    """给的数据撑不起一个模型。"""


def scales(rows: np.ndarray) -> list:
    return ["log10" if bool(np.all(rows[:, index] > 0)) else "linear" for index in range(rows.shape[1])]


def forward(rows: np.ndarray, goals: list, how: list) -> np.ndarray:
    """换到拟合用的刻度上，并且都变成越小越好。"""
    made = np.array(rows, dtype=float)
    for index, goal in enumerate(goals):
        if how[index] == "log10":
            made[:, index] = np.log10(made[:, index])
        if goal["goal"] == "max":
            made[:, index] = -made[:, index]
    return made


def backward(number: float, goal: dict, how: str) -> float:
    number = -number if goal["goal"] == "max" else number
    return float(10.0 ** number) if how == "log10" else float(number)


def _kept(targets: np.ndarray, seed: int) -> np.ndarray:
    """行太多时留哪些：各目标缩放之后的和最小的四分之一，加上照种子随机取的。"""
    if len(targets) <= CAP:
        return np.arange(len(targets))
    low, high = targets.min(axis=0), targets.max(axis=0)
    total = ((targets - low) / np.where(high > low, high - low, 1.0)).sum(axis=1)
    order = np.argsort(total, kind="stable")
    best, rest = order[:CAP // 4], order[CAP // 4:]
    more = np.random.default_rng(seed).choice(rest, size=CAP - len(best), replace=False)
    return np.sort(np.concatenate([best, more]))


def choose(job: dict, source=None) -> tuple:
    goals = job["objective"]["objectives"]
    columns = [goal["column"] for goal in goals]
    fine = sorted((one for one in job["candidates"] if common.allowed(one, job["objective"])), key=lambda one: one["name"])
    bone = fine[0].get("bone_id") if fine else None
    seen = common.observed(job, columns, bone, source)
    known = {common.key(design) for design in common.tried(job, bone, source)}
    fresh = [one for one in fine if common.key(one["design"]) not in known]
    if fresh and any(sorted(design) != sorted(fresh[0]["design"]) for design, _ in seen):
        raise Unusable("数据里的设计项和候选池里的不一样：它们不是同一种参数化算出来的，不能放在一起用")
    space = common.Space([one["design"] for one in fresh] + [design for design, _ in seen])
    need = max(6, space.width + 2)
    if len(seen) < need:
        raise Unusable(f"能用的数据只有 {len(seen)} 行，至少要 {need} 行：要同一根骨、条件和这次选点的条件默认逐项相同、"
                       f"目标的各列（{columns}）都有数")
    rows = np.array([numbers for _, numbers in seen], dtype=float)
    how = scales(rows)
    targets = forward(rows, goals, how)
    kept = _kept(targets, job["seed"])
    targets = targets[kept]
    placed = space.matrix([design for design, _ in seen])[kept]
    models = [common.Gp(placed, targets[:, index], seed=job["seed"] + index, starts=3 if len(kept) <= 600 else 2)
              for index in range(len(goals))]
    logged = [column for column, scale in zip(columns, how) if scale == "log10"]
    model = (f"策略内部的高斯过程（Matern 5/2，每个设计项各一个长度），用给的数据里 {len(kept)} 行拟合"
             f"（同一根骨、条件和这次选点相同、目标都有数的共 {len(seen)} 行）"
             + (f"；{'、'.join(logged)} 取了对数" if logged else "")
             + ("；几个目标用随机权重的切比雪夫合成（ParEGO）" if len(goals) > 1 else "；期望改进"))
    if not fresh:
        return [], model

    points = space.matrix([one["design"] for one in fresh])
    low, high = targets.min(axis=0), targets.max(axis=0)
    span = np.where(high > low, high - low, 1.0)
    rng = np.random.default_rng(job["seed"])
    draws = rng.standard_normal((DRAWS, len(goals)))
    wanted = np.array([float(goal.get("weight", 1.0)) for goal in goals])
    have, left, chosen = targets.copy(), np.ones(len(fresh), dtype=bool), []
    while left.any() and len(chosen) < job["count"]:
        guess = [one.predict(points) for one in models]
        mean, deviation = np.column_stack([m for m, _ in guess]), np.column_stack([d for _, d in guess])
        if len(goals) == 1:
            gain = common.expected_improvement(mean[:, 0], deviation[:, 0], float(have[:, 0].min()))
        else:
            weights = rng.dirichlet(np.ones(len(goals))) * wanted
            weights = weights / weights.sum()

            def merged(values):
                part = weights * (values - low) / span
                return part.max(axis=-1) + RHO * part.sum(axis=-1)

            best, gain = float(merged(have).min()), np.empty(len(fresh))
            for start in range(0, len(fresh), 2000):
                block = slice(start, start + 2000)
                sampled = mean[block, None, :] + deviation[block, None, :] * draws[None, :, :]
                gain[block] = np.maximum(best - merged(sampled), 0.0).mean(axis=1)
        gain = np.where(left, gain, -np.inf)
        index = int(np.argmax(gain))
        unsure = float(gain[index]) <= 1e-15
        if unsure:                                          # 哪个候选都不指望比现在的好：取预测最没把握的
            index = int(np.argmax(np.where(left, (deviation / span).sum(axis=1), -np.inf)))
        said = []
        for number, goal in enumerate(goals):
            ends = sorted(backward(mean[index, number] + sign * 1.96 * deviation[index, number], goal, how[number]) for sign in (-1.0, 1.0))
            said.append(f"{goal['column']} 预测 {common.shown(backward(mean[index, number], goal, how[number]))}"
                        f"（95% 区间 {common.shown(ends[0])} 到 {common.shown(ends[1])}）")
        lead = "期望改进都接近 0，取的是预测最没把握的候选" if unsure else f"期望改进 {common.shown(float(gain[index]))}"
        chosen.append({"name": fresh[index]["name"], "score": float(gain[index]), "why": f"{lead}；" + "；".join(said)})
        for number, one in enumerate(models):
            one.add(points[index], float(mean[index, number]))
        have = np.vstack([have, mean[index]])
        left[index] = False
    return chosen, model


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    try:
        chosen, model = choose(common.read_job(source), source)
    except Unusable as error:
        print(f"贝叶斯优化选不了点：{error}", flush=True)
        sys.exit(3)
    common.write_result(out, chosen, model)


if __name__ == "__main__":
    main()
