"""【自由】一个点一个作业；算输入指纹；核对点里的骨标识和骨模型一致、点的各项和内核要的一致。

接口见 plugin.py 开头：check(handle) 和 plan(handle)。
"""
from __future__ import annotations

import json
from pathlib import Path

from stemlab import hooks

MANIFEST = "manifest.json"
NEEDED_MODES = ("build", "post")


def manifest(folder) -> dict:
    return json.loads((Path(folder) / MANIFEST).read_bytes())


def names(listed) -> list[str]:
    return sorted(column["name"] for column in listed)


def check(handle) -> str | None:
    """启动前的检查。过了返回 None，不过返回原因。"""
    bone = handle.input_info("bone")
    kernel, derive = manifest(handle.input("kernel")), manifest(handle.input("derive"))
    points = hooks.read_points(handle.input("points"))
    found = []

    missing = [mode for mode in NEEDED_MODES if mode not in (kernel.get("modes") or [])]
    if missing:
        found.append(f"这个内核不会 {missing}，FEA 要它会建模（build）和后处理（post）")
    if kernel.get("bones") and bone.bone_id not in kernel["bones"]:
        found.append(f"这个内核只认 {kernel['bones']} 这几根骨，骨模型是 {bone.bone_id}")

    other = sorted({point["bone_id"] for point in points} - {bone.bone_id})
    if other:
        who = [point["name"] for point in points if point["bone_id"] != bone.bone_id]
        found.append(f"点里的骨标识和骨模型不一致：骨模型是 {bone.bone_id}，这几个点写的是 {other}：{who[:5]}")

    for group, what in (("design", "设计"), ("conditions", "条件")):
        wanted = names(kernel[group])
        wrong = [point["name"] for point in points if sorted(point[group]) != wanted]
        if wrong:
            given = sorted(next(point for point in points if point["name"] == wrong[0])[group])
            found.append(f"点的{what}项和内核要的不一致：内核要 {wanted}，点 {wrong[0]} 带的是 {given}"
                         + (f"（还有 {len(wrong) - 1} 个点也是）" if len(wrong) > 1 else ""))

    lacking = sorted(set(derive.get("needs") or []) - set(names(kernel["fields"])))
    if lacking:
        found.append(f"推导量定义要的场 {lacking}，这个内核不给")
    return "；".join(found) if found else None


def plan(handle) -> list[dict]:
    """一个点一个作业。任务名就是点的名字。

    输入指纹是一个 FEA 作业的身份：点、骨模型、内核、导出设定、插件冻结文件，五个哈希合起来。
    """
    hashes = {name: handle.input_info(name).hash for name in ("bone", "kernel", "export")}
    frozen = handle.round.provenance["plugin_frozen"]
    return [{"task": point["name"], "point": point,
             "fingerprint": hooks.fingerprint(point=point["hash"], bone=hashes["bone"], kernel=hashes["kernel"],
                                              export=hashes["export"], plugin=frozen)}
            for point in hooks.read_points(handle.input("points"))]
