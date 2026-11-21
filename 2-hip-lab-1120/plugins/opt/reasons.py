"""【自由】每个点的理由：哪个策略、分数、用的模型（登记的预测器，或策略内部的）、哪版目标、哪几份数据。

哪份策略、种子、哪版目标、用的哪个模型这四样，冻结的 plugin.py 一定会写进理由（这里写不写都一样）。
这里写自由的那一部分：策略给这个点打的分、它自己说的为什么、用了哪几份数据、用的是不是登记的预测器。
"""
from __future__ import annotations


def reason(pick: dict, context: dict) -> dict:
    """一个点的理由。pick 是策略给的那一条（name、score、why）；context 是这一次选点的来龙去脉。"""
    used = "登记的预测器 " + context["predictor"] if context.get("predictor") else "策略内部的模型" if context.get("data") else "没有用模型"
    return {"score": pick.get("score"), "why": pick.get("why") or "策略没有说为什么", "data": context.get("data") or [],
            "predictor": context.get("predictor"), "model_from": used}
