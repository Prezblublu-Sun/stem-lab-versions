"""【自由】待检查清单，把不可靠的地方标出来；用上人工修改并记下改了哪里。

人工修改是登记的一个文件夹（种类 edits），里面一个 edits.json，另加你换掉的文件：

    {"by": "谁改的",
     "landmarks": {"head_center": {"xyz": [x, y, z], "why": "为什么改"}},
     "solids": {"cancellous": {"file": "cancellous_fixed.step", "why": "填了导针孔"}}}

两项都可以不写。改了哪个标志点、从哪挪到哪，换了哪个实体、为什么，都记进骨模型的重建记录。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

EDITS = "edits.json"
NAMES = ("cortical", "cancellous")
SANE_NECK_SHAFT = (110.0, 145.0)        # 颈干角出了这个范围多半是颈轴的定义不对或者找错了（成人大致 114 到 140 度）


def _read(folder: Path) -> dict:
    return json.loads((Path(folder) / EDITS).read_bytes())


def edit_problems(folder: Path) -> list[str]:
    """一份人工修改写得对不对。"""
    try:
        edits = _read(folder)
    except (OSError, ValueError) as error:
        return [f"读不出 {EDITS}：{error}"]
    if not isinstance(edits, dict) or not isinstance(edits.get("by"), str) or not edits["by"].strip():
        return [f"{EDITS} 要写 by：谁改的"]
    found = []
    for name, change in (edits.get("landmarks") or {}).items():
        xyz = change.get("xyz") if isinstance(change, dict) else None
        if (not isinstance(xyz, list) or len(xyz) != 3 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in xyz)
                or not isinstance(change.get("why"), str) or not change["why"].strip()):
            found.append(f"标志点 {name} 的修改要写 xyz（三个数）和 why（为什么改）")
    for name, change in (edits.get("solids") or {}).items():
        if name not in NAMES or not isinstance(change, dict) or not (Path(folder) / str(change.get("file"))).is_file() \
                or not isinstance(change.get("why"), str) or not change["why"].strip():
            found.append(f"实体 {name} 的修改要写 file（这个文件夹里的文件）和 why（为什么换）；实体只有 {list(NAMES)}")
    return found


def apply(listed: dict, draft: Path, edits: Path | None) -> tuple:
    """把人工修改用到候选骨模型上。返回（两个实体的文件，标志点，重建记录）。没有修改就是候选原样。"""
    files = {name: Path(draft) / listed["solids"][name]["file"] for name in NAMES}
    marks = {name: dict(point) for name, point in listed["landmarks"].items()}
    history = list(listed["history"])
    if edits is None:
        return files, marks, history + [{"step": "review", "what": "没有人工修改，候选原样定稿"}]
    changes = _read(edits)
    for name, change in (changes.get("landmarks") or {}).items():
        old = marks.get(name, {}).get("xyz")
        moved = f"挪了 {math.dist(old, change['xyz']):.2f} mm，" if old else "新加的，"
        marks[name] = {"xyz": [float(v) for v in change["xyz"]],
                       "definition": f"人工标的（{changes['by']}）：{change['why']}"}
        history.append({"step": "edit", "what": f"标志点 {name}：{moved}{changes['by']} 改，原因：{change['why']}"})
    for name, change in (changes.get("solids") or {}).items():
        files[name] = Path(edits) / change["file"]
        history.append({"step": "edit", "what": f"实体 {name} 换成 {change['file']}：{changes['by']} 改，原因：{change['why']}"})
    if not changes.get("landmarks") and not changes.get("solids"):
        history.append({"step": "review", "what": f"{changes['by']} 看过，没有改动"})
    return files, marks, history


def todo(found: dict, measures: dict) -> list[dict]:
    """待检查清单：请人看的各项，自动找得不踏实的排在前面并写明为什么。"""
    doubts = []
    if not found["neck_converged"]:
        doubts.append(("neck_center", "颈轴的迭代没有收敛，颈最细的截面可能找偏了"))
    if measures["head_fit_rms_mm"] > 1.0:
        doubts.append(("head_center", f"球拟合的残差是 {measures['head_fit_rms_mm']:.2f} mm，头可能不圆，或者拟合进了别的面"))
    if not SANE_NECK_SHAFT[0] <= measures["neck_shaft_angle_deg"] <= SANE_NECK_SHAFT[1]:
        doubts.append(("neck_center", f"颈干角是 {measures['neck_shaft_angle_deg']:.1f} 度，出了常见范围 {SANE_NECK_SHAFT}。"
                                      "先确认颈轴用的是不是你要的那种定义"))
    if measures["lesser_trochanter_prominence_mm"] < 2.0:
        doubts.append(("lesser_trochanter", f"小转子只凸出 {measures['lesser_trochanter_prominence_mm']:.1f} mm，可能找到的不是它"))
    if measures.get("neck_wall_min_mm") is not None and measures["neck_wall_min_mm"] < 0.3:
        doubts.append(("solids", f"股骨颈处皮质最薄只有 {measures['neck_wall_min_mm']:.2f} mm，多半是几何有破口"))
    for name in NAMES:
        if not measures[f"{name}_watertight"]:
            doubts.append(("solids", f"{name} 的表面不封闭"))
        if measures[f"{name}_solids"] != 1:
            doubts.append(("solids", f"{name} 的文件里有 {measures[f'{name}_solids']} 个实体，该是一个"))
    listed = [{"item": item, "doubt": True, "why": why} for item, why in doubts]
    doubted = {row["item"] for row in listed}
    listed += [{"item": name, "doubt": False, "why": "自动找的没有发现问题，请照定义看一眼位置"}
               for name in found["landmarks"] if name not in doubted]
    return listed
