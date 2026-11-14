"""【冻结】按骨模型格式写出候选和定稿；骨标识从骨源继承。

候选骨模型和骨模型是同一种格式的文件夹：清单、solids/ 下的两个实体，另外的文件随意。
这里只管“写成什么样”：实体怎么来、标志点怎么找，是自由代码的事；它们交上来的东西在这里排成格式，写完自己先核一遍。
骨标识不由谁来填：从输入的骨源（或候选骨模型）身上拿，原样写进去。

重建设定里和这里有关的项：
    side        哪一侧：left 或 right
    frame       骨源的坐标系：{"origin", "x", "y", "z"} 四句话。实体不换系，标志点也在这个系里
    materials   两个实体的材料：{"cortical": {"model", "E_MPa", "nu"}, "cancellous": {...}}
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from stemlab import hooks

MANIFEST = "manifest.json"
UNITS = {"length": "mm", "force": "N", "stress": "MPa"}
SOLIDS = ("cortical", "cancellous")
SIDES = ("left", "right")
FRAME = ("origin", "x", "y", "z")


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def read(folder) -> dict:
    return json.loads((Path(folder) / MANIFEST).read_bytes())


def setting_problems(setting) -> list[str]:
    """重建设定里写骨模型要用的那几项对不对。返回哪里不对；空列表就是对的。"""
    if not isinstance(setting, dict):
        return ["重建设定必须是一个 JSON 对象"]
    found = []
    if setting.get("side") not in SIDES:
        found.append(f"重建设定的 side 要写 {list(SIDES)} 之一")
    frame = setting.get("frame")
    if not isinstance(frame, dict) or set(frame) != set(FRAME) or not all(isinstance(text, str) and text.strip() for text in frame.values()):
        found.append(f"重建设定的 frame 要写 {list(FRAME)} 四项：骨源的坐标系是怎么定的")
    materials = setting.get("materials")
    if not isinstance(materials, dict) or set(materials) != set(SOLIDS):
        found.append(f"重建设定的 materials 要写 {list(SOLIDS)} 两种材料")
    return found


def write(folder: Path, kind: str, *, bone_id: str, setting: dict, solids: dict, landmarks: dict, history: list,
          checks: list, measures: dict | None = None) -> Path:
    """写一个候选骨模型（bone_draft）或骨模型（bone_model）的文件夹。solids 是 {"cortical": 文件, "cancellous": 文件}，复制进去。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "solids").mkdir(parents=True)
    placed = {}
    for name in SOLIDS:
        source = Path(solids[name])
        placed[name] = {"file": f"solids/{name}{source.suffix.lower()}"}
        shutil.copyfile(source, folder / placed[name]["file"])
    manifest = {"format": 1, "kind": kind, "files": sorted(row["file"] for row in placed.values()),
                "bone_id": bone_id, "side": setting["side"], "units": UNITS, "frame": setting["frame"], "solids": placed,
                "landmarks": landmarks, "materials": setting["materials"], "history": history, "checks": checks,
                "measures": measures or {}}
    (folder / MANIFEST).write_bytes(dumps(manifest))
    wrong = hooks.check_format(kind, folder)
    if wrong:
        raise ValueError(f"写出来的{'骨模型' if kind == 'bone_model' else '候选骨模型'}不符合格式：" + "；".join(wrong[:5]))
    return folder


def write_report(folder: Path, what: str, body: dict, bone_id: str) -> Path:
    """写一份报告：待检查清单（todo）或检查结果（gate）。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (folder / "report.json").write_bytes(dumps(body))
    (folder / MANIFEST).write_bytes(dumps({"format": 1, "kind": "report", "files": ["report.json"], "bone_id": bone_id, "what": what}))
    return folder
