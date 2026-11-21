"""【冻结】照骨模型第 2 版写出候选和定稿；骨标识从骨源继承，来源照存定的输入写，解剖坐标系照标志点算。

候选骨模型和骨模型是同一种格式的文件夹：清单、regions/ 下各个区域的几何文件，别的文件随意（格式见契约的 formats/bone_model.py）。
这里只管“写成什么样”：几何怎么来、标志点怎么找，是重建方法包的事。它交回来的骨模型的几段（约定见 contract/formats/package.py
的“重建方法”）在这里排成格式，写完自己先核一遍：
    骨标识      不由谁来填：从输入的骨源（或候选骨模型）身上拿，原样写进去
    来源        怎么来的（how）照方法包交的；哪个方法包、哪份重建设定，是这个实验存定的那两样（编号和哈希），由骨架给
    解剖坐标系  file 照方法包交的。定法照覆盖范围（METHOD_OF，和契约的 bone_model.METHOD_OF 一样：完整的股骨照后髁连线，
                只有近端一段的照颈轴）。原点和三个轴照标志点算（hooks.bone_frame，算法只在契约里），近端一段的照方法包交的前倾角转回去
    几何文件    方法包给的绝对路径，原样复制成 regions/<区域名><后缀>。区域名不合规矩的不复制：名字要拿来拼文件名
    表面        写空的：现在没有方法包交表面
骨架自己另量一个数（measured）：完整的股骨照后髁连线量出的前倾角（ANTEVERSION），记进量出来的数。

setting_problems 核的是第 1 版那种没有声明的重建设定：5c 起重建设定照方法包的声明写，骨架不再叫它，留到 5g 移出隔离。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from stemlab import hooks

MANIFEST = "manifest.json"
UNITS = {"length": "mm", "force": "N", "stress": "MPa"}
SOLIDS = ("cortical", "cancellous")
SIDES = ("left", "right")
FRAME = ("origin", "x", "y", "z")
METHOD_OF = {"whole": "shaft_condyles", "proximal": "shaft_neck"}    # 和契约的 bone_model.METHOD_OF 一样；对不上 check_format 会拒
ANTEVERSION = "anteversion_deg"                                     # 骨架自己记的量：完整的股骨照后髁连线量出的前倾角
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")                          # 区域名拿来拼文件名之前先看一眼。名字的规矩在契约里


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def read(folder) -> dict:
    return json.loads((Path(folder) / MANIFEST).read_bytes())


def setting_problems(setting) -> list[str]:
    """第 1 版那种没有声明的重建设定里，写骨模型要用的那几项对不对。5c 起骨架不叫它（见文件开头）。"""
    if not isinstance(setting, dict):
        return ["重建设定必须是一个 JSON 对象"]
    found = []
    if setting.get("side") not in SIDES:
        found.append(f"重建设定的 side 要写 {list(SIDES)} 之一")
    frame_said = setting.get("frame")
    if not isinstance(frame_said, dict) or set(frame_said) != set(FRAME) or not all(isinstance(text, str) and text.strip() for text in frame_said.values()):
        found.append(f"重建设定的 frame 要写 {list(FRAME)} 四项：骨源的坐标系是怎么定的")
    materials = setting.get("materials")
    if not isinstance(materials, dict) or set(materials) != set(SOLIDS):
        found.append(f"重建设定的 materials 要写 {list(SOLIDS)} 两种材料")
    return found


def _method(made: dict) -> str:
    """这根骨的解剖坐标系照哪种定法：看方法包交的覆盖范围。"""
    extent = made["coverage"].get("extent") if isinstance(made.get("coverage"), dict) else None
    if extent not in METHOD_OF:
        raise ValueError(f"覆盖范围（coverage）的 extent 要是 {list(METHOD_OF)} 之一：{extent!r}")
    return METHOD_OF[extent]


def frame(made: dict) -> dict:
    """解剖坐标系：file 照方法包交的，定法照覆盖范围，原点和三个轴照标志点算。定不出来报 ValueError，说出为什么。"""
    method, said = _method(made), made["frame"]
    turn = said.get("anteversion_deg") if method == "shaft_neck" else None
    if method == "shaft_neck" and turn is None:
        raise ValueError("只有近端一段的骨照颈轴定坐标系：方法包要交 frame 的 anteversion_deg（照重建设定写的前倾角）")
    found = hooks.bone_frame(made["landmarks"], made["side"], method, turn)
    return {"file": said["file"], "method": method, **({"anteversion_deg": turn} if method == "shaft_neck" else {}), **found}


def measured(made: dict) -> dict:
    """骨架自己量的数：完整的股骨照后髁连线量出的前倾角。只有近端一段的，前倾角是设定给的，不量。定不出来报 ValueError。"""
    if _method(made) != "shaft_condyles":
        return {}
    return {ANTEVERSION: hooks.bone_anteversion(made["landmarks"], made["side"])}


def write(folder: Path, kind: str, *, bone_id: str, made: dict, source: dict, checks: list, measures: dict) -> Path:
    """写一个候选骨模型（bone_draft）或骨模型（bone_model）的文件夹。made 是方法包交回来的那几段（约定见文件开头），
    source 是来源：{"how", "method": {"id", "hash"}, "setting": {"id", "hash"}}。写不成格式报 ValueError。"""
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "regions").mkdir(parents=True)
    regions = []
    for region in made["regions"]:
        name, given = region.get("name"), Path(region["geometry"]["file"])
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError(f"区域的名字要用小写字母、数字和下划线：{name!r}")
        if not given.is_absolute():
            raise ValueError(f"区域 {name} 的几何文件要写绝对路径：{region['geometry']['file']!r}")
        rel = f"regions/{name}{given.suffix.lower()}"
        shutil.copyfile(given, folder / rel)
        regions.append({**region, "geometry": {**region["geometry"], "file": rel}})
    manifest = {"format": 2, "kind": kind, "files": sorted(region["geometry"]["file"] for region in regions),
                "bone_id": bone_id, "side": made["side"], "bone_type": made["bone_type"], "coverage": made["coverage"],
                "source": source, "units": UNITS, "frame": frame(made), "regions": regions, "surfaces": {},
                "landmarks": made["landmarks"], "history": made["history"], "checks": checks, "measures": measures}
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
