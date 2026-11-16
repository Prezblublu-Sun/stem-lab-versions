"""【自由】待检查清单，把不可靠的地方标出来；用上人工修改并记下改了哪里。

人工修改是登记的一个文件夹（种类 edits），里面一个 edits.json，另加你换掉的文件：

    {"by": "谁改的",
     "landmarks": {"head_center": {"xyz": [x, y, z], "why": "为什么改"}},
     "solids": {"cancellous": {"file": "cancellous_fixed.step", "why": "填了导针孔"}}}

两项都可以不写。改了哪个标志点、从哪挪到哪，换了哪个实体、为什么，都记进骨模型的重建记录。

CT 重建出来的两个实体是成对的（皮质 = 外表面加内壁，松质 = 内壁，见 solids.py）。只换其中一个、而且交的是 STL 时，
另一个在定稿时照它重写（solids.reconcile），所以改内壁只用交一个内壁的 STL，写成换 cancellous。
交的不是 STL（比如上面的 .step）或者块数不对，就不重写：重建记录里写明，壁厚、界面间隙、四面体这几项量不了，
检查门里拿它们比的线不过（不拿候选的数充数）。
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


def ct_doubts(measures: dict, notes) -> list[tuple]:
    """CT 重建出来的骨，请人看的地方。两端的内壁每一根都要看：它是规则补出来的，不是量出来的。"""
    doubts = [("source", note) for note in notes]
    if measures.get("surface_on_bone_share", 1.0) < 0.4:
        doubts.append(("source", f"外形两侧各一个体素的那一层里，只有 {measures['surface_on_bone_share']:.0%} 的体素够得上骨的 CT 值："
                                 "外形可能没有压在骨面上，请核对外形和 CT 是不是对齐的"))
    if measures.get("hu_inside_p95", 0.0) > 2500:
        doubts.append(("source", f"骨内 CT 值的 95% 分位是 {measures['hu_inside_p95']:.0f}，多半有金属：有金属的 CT 分不准皮质"))
    if measures.get("outer_vs_reference_p95_mm", 0.0) > 0.5:
        doubts.append(("solids", f"重建的外表面和参考外形的距离，95% 分位是 {measures['outer_vs_reference_p95_mm']:.2f} mm，比平常的 0.1 到 0.2 mm 大"))
    if measures.get("tet_check_problem"):
        doubts.append(("solids", f"照这两个表面试划四面体没有划成：{measures['tet_check_problem']}。多半是内壁和外表面相交，或者表面自己相交"))
    if measures.get("interface_gap_max_mm", 0.0) > 0.01:
        doubts.append(("solids", f"皮质实体带的内壁和松质实体的表面最远差 {measures['interface_gap_max_mm']:.2f} mm：两个实体在界面上对不上"))
    if "cortex_added_by_rules_share" in measures:
        doubts.append(("solids", f"股骨头、颈和髁部的内壁不是量出来的：那里的皮质太薄，CT 上够不到阈值，是照“两端限深”和“最小壁厚”补的"
                                 f"（这根骨最终的皮质里有 {measures['cortex_added_by_rules_share']:.0%} 是这样来的）。做近端的分析之前请看截面，该改的用人工修改换掉"))
    return doubts


def todo(found: dict, measures: dict, notes=()) -> list[dict]:
    """待检查清单：请人看的各项，自动找得不踏实的排在前面并写明为什么。notes 是重建那一步自己想说的话。"""
    doubts = ct_doubts(measures, notes)
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
