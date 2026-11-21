"""均匀铺点：不用任何模型，在能选的候选里挑一批彼此离得最远的。

用在第一批点、或者要把设计范围里还空着的地方补上的时候。

    能选的候选     候选池里可行、满足“不做 FE 就判得了的约束”、而且还没算过的
    怎么挑         把设计各项缩放到 0 到 1，逐个挑离“已选的点和已经算过的点”最远的那个
    第一个点       一个算过的点都没有时，照种子从能选的候选里取一个；换一个种子就是另一批
    给的数据       可以不给。给了就避开已经算过的设计（同一根骨、条件和这次的条件默认相同）

分数是这个点离已有的点的距离（各项缩放之后的直线距离）；分数大说明它周围原来是空的。
"""
from __future__ import annotations

import pathlib
import random
import sys

import common


def choose(job: dict, source=None) -> tuple:
    """返回（选的，用的模型）。source 是 job.json 所在的文件夹：数据的位置不是完整路径时照它找。"""
    fine = sorted((one for one in job["candidates"] if common.allowed(one, job["objective"])), key=lambda one: one["name"])
    bone = fine[0].get("bone_id") if fine else None
    done = common.tried(job, bone, source)
    known = {common.key(design) for design in done}
    fresh = [one for one in fine if common.key(one["design"]) not in known]
    if not fresh:
        return [], None
    space = common.Space([one["design"] for one in fresh] + done)
    order = list(range(len(fresh)))
    random.Random(job["seed"]).shuffle(order)
    chosen = []
    for index, far in common.spread(space.matrix([one["design"] for one in fresh]), space.matrix(done), job["count"], order):
        if far is None:
            why = "第一个点：一个算过的点都没有，照种子从能选的候选里取的"
        else:
            why = f"离已选的点和已经算过的点最远：最近的一个在 {common.shown(far)} 处（各设计项缩放到 0 到 1 之后的距离）"
        chosen.append({"name": fresh[index]["name"], "score": far, "why": why})
    return chosen, None


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    chosen, model = choose(common.read_job(source), source)
    common.write_result(out, chosen, model)


if __name__ == "__main__":
    main()
