"""照登记的预测器的预测选点。要填预测器：系统先让它对候选池里可行的候选出预测，再交到这里。

    能选的候选     候选池里可行、满足约束、还没算过，并且预测器给了预测的（不在它适用范围里的候选没有预测，不选）
    拿哪个数比     清单里的 pick 定：
                     best         预测值
                     optimistic   预测区间里有利的那一端（往小里优化取下限，往大里优化取上限）：
                                  把“可能很好、但预测器没把握”的候选也放进来
    几个目标       先分层：没有被别的候选在每个目标上都压过的是第一层（预测的帕累托前沿），去掉它们再分出第二层……
                   一层一层往下取；同一层里照各目标缩放到 0 到 1 之后的加权和，从好到坏
    别挤在一起     和已选的点离得太近的（各设计项缩放之后的距离小于 gap，默认 0.05）跳过；跳完不够数再把跳过的补回来

分数是负的加权和（大的好）。只有一个目标时，分层就是照那一个数排队。
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

import common

HERE = pathlib.Path(__file__).resolve().parent


def layers(values: np.ndarray, enough: int | None = None) -> np.ndarray:
    """每一行在第几层（从 1 起）。values 的每一列都是越小越好。

    enough 给了，就分到“已经分出来的行不少于 enough”为止，剩下的都算再下一层：只要前面几层时不用把整池分完。
    """
    layer, left, number = np.zeros(len(values), dtype=int), np.arange(len(values)), 0
    while len(left):
        number += 1
        if enough is not None and len(values) - len(left) >= enough:
            layer[left] = number
            break
        here = values[left]
        beaten = np.array([bool(np.any(np.all(here <= row, axis=1) & np.any(here < row, axis=1))) for row in here])
        layer[left[~beaten]] = number
        left = left[beaten]
    return layer


def choose(job: dict, pick: str = "best", gap: float = 0.05, source=None) -> tuple:
    goals = job["objective"]["objectives"]
    guesses = {row["name"]: row for row in job.get("predictions") or []}
    fine = sorted((one for one in job["candidates"] if common.allowed(one, job["objective"]) and one["name"] in guesses),
                  key=lambda one: one["name"])
    bone = fine[0].get("bone_id") if fine else None
    known = {common.key(design) for design in common.tried(job, bone, source)}
    fine = [one for one in fine if common.key(one["design"]) not in known]
    usable = []
    for one in fine:
        guess = guesses[one["name"]]
        numbers = [(guess["lower" if goal["goal"] == "min" else "upper"] if pick == "optimistic" else guess["values"]).get(goal["column"])
                   for goal in goals]
        if all(common.is_number(number) for number in numbers):
            usable.append((one, [number if goal["goal"] == "min" else -number for number, goal in zip(numbers, goals)]))
    if not usable:
        return [], "登记的预测器"
    values = np.array([row for _, row in usable], dtype=float)
    low, high = values.min(axis=0), values.max(axis=0)
    scaled = (values - low) / np.where(high > low, high - low, 1.0)
    weights = np.array([float(goal.get("weight", 1.0)) for goal in goals])
    total = scaled @ (weights / weights.sum())
    layer = layers(values, enough=20 * job["count"] + 50)
    order = sorted(range(len(usable)), key=lambda index: (layer[index], round(float(total[index]), 12), usable[index][0]["name"]))
    points = common.Space([one["design"] for one, _ in usable]).matrix([one["design"] for one, _ in usable])
    picked, skipped = [], []
    for index in order:
        if len(picked) == job["count"]:
            break
        if picked and float(np.linalg.norm(points[picked] - points[index], axis=1).min()) < gap:
            skipped.append(index)
        else:
            picked.append(index)
    picked += skipped[:job["count"] - len(picked)]
    chosen = []
    for index in picked:
        one, guess = usable[index][0], guesses[usable[index][0]["name"]]
        said = "；".join(f"{goal['column']} 预测 {common.shown(guess['values'][goal['column']])}"
                        f"（区间 {common.shown(guess['lower'][goal['column']])} 到 {common.shown(guess['upper'][goal['column']])}）"
                        for goal in goals)
        where = f"在预测的帕累托前沿的第 {int(layer[index])} 层" if len(goals) > 1 else "照这一个目标排"
        late = "；它和已选的点离得近，是不够数才补进来的" if index in skipped else ""
        chosen.append({"name": one["name"], "score": 0.0 - float(total[index]), "why": f"{said}；{where}{late}"})
    model = "登记的预测器，拿预测值比" if pick == "best" else "登记的预测器，拿预测区间里有利的那一端比"
    return chosen, model


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    listed = json.loads((HERE.parent / "manifest.json").read_text(encoding="utf-8"))
    chosen, model = choose(common.read_job(source), listed.get("pick", "best"), float(listed.get("gap", 0.05)), source)
    common.write_result(out, chosen, model)


if __name__ == "__main__":
    main()
