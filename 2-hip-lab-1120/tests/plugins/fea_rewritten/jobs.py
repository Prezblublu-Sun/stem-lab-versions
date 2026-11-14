"""plugins/fea/jobs.py 的另一种写法：接口不变，写法不同。

给“把自由的部分整个换一份写法”那条验收用：把它抄过去盖掉原来的 jobs.py，蓝图的前六条照过。
"""
import json
import pathlib

from stemlab import hooks

REWRITTEN = True


def _listed(folder) -> dict:
    return json.loads((pathlib.Path(folder) / "manifest.json").read_text(encoding="utf-8"))


def check(handle):
    bone_id = handle.input_info("bone").bone_id
    kernel = _listed(handle.input("kernel"))
    reasons = []
    modes = kernel.get("modes") or []
    for mode in ("build", "post"):
        if mode not in modes:
            reasons.append("内核不会 %s" % mode)
    allowed = kernel.get("bones")
    if allowed and bone_id not in allowed:
        reasons.append("内核只认 %s，骨模型是 %s" % (allowed, bone_id))
    design = {column["name"] for column in kernel["design"]}
    conditions = {column["name"] for column in kernel["conditions"]}
    for point in hooks.read_points(handle.input("points")):
        if point["bone_id"] != bone_id:
            reasons.append("点 %s 的骨标识是 %s，骨模型是 %s" % (point["name"], point["bone_id"], bone_id))
        if set(point["design"]) != design:
            reasons.append("点 %s 的设计项和内核要的不一样" % point["name"])
        if set(point["conditions"]) != conditions:
            reasons.append("点 %s 的条件项和内核要的不一样" % point["name"])
    offered = {column["name"] for column in kernel["fields"]}
    for name in _listed(handle.input("derive")).get("needs") or []:
        if name not in offered:
            reasons.append("推导量定义要的场 %s 内核不给" % name)
    return "；".join(reasons) or None


def plan(handle):
    common = {"bone": handle.input_info("bone").hash, "kernel": handle.input_info("kernel").hash,
              "export": handle.input_info("export").hash, "plugin": handle.round.provenance["plugin_frozen"]}
    made = []
    for point in hooks.read_points(handle.input("points")):
        made.append({"task": point["name"], "point": point, "fingerprint": hooks.fingerprint(point=point["hash"], **common)})
    return made
