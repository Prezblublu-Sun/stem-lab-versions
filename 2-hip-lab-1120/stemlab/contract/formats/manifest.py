"""所有文件夹形态的东西共用的清单，和落盘名字的规矩。

除了值，登记的东西都是一个文件夹，里面带一份 manifest.json：

    {"format": 1, "kind": "report", "files": ["summary.json", "plots/a.png"], ...这种格式自己的项}

    format   这种格式的版本号。用哪种格式由种类定，见 kinds.ITEM_KINDS
    kind     种类
    files    文件夹里除清单之外的全部文件：相对路径、正斜杠
    bone_id  骨标识。骨模型和候选骨模型必带，别的可以不带

契约只核清单，和清单列的文件是不是都在。内容和清单对不对得上，由写它的那个冻结文件负责。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from stemlab.contract.hashing import canonical, list_tree
from stemlab.contract.kinds import ITEM_KINDS, VALUE
from stemlab.contract.layout import is_key, is_label
from stemlab.contract.versions import FORMATS, CannotUpcast, upcast

MANIFEST = "manifest.json"
MAX_PATH = 150      # 相对路径最长多少个字符。Windows 的路径默认有长度上限

_ALLOWED = re.compile(r"[A-Za-z0-9 !#$%&'()+,\-.;=@\[\]^_`{}~]+")       # ASCII 里 Windows 允许的那些
_DEVICES = {"con", "prn", "aux", "nul"} | {f"{name}{n}" for name in ("com", "lpt") for n in range(1, 10)}


def check_name(rel) -> str | None:
    """核对一个落盘的名字：ASCII、相对路径、正斜杠、不太长。对就返回 None，不对返回原因。"""
    if not isinstance(rel, str) or not rel:
        return f"名字必须是非空的字符串：{rel!r}"
    if len(rel) > MAX_PATH:
        return f"路径太长（{len(rel)} 个字符，最多 {MAX_PATH}）：{rel}"
    for part in rel.split("/"):
        if not _ALLOWED.fullmatch(part):
            return f"名字只能用 ASCII，不能用 \\ : * ? \" < > | 这些字符，也不能有空的一段：{rel!r}"
        if part in (".", "..") or part != part.strip() or part.endswith("."):
            return f"名字的每一段不能是 . 或 ..，不能以空格开头或结尾，不能以点结尾：{rel!r}"
        if part.split(".")[0].lower() in _DEVICES:
            return f"{part} 是 Windows 的保留名：{rel!r}"
    return None


def check_names(paths) -> list[str]:
    """核对一组落盘的名字：逐个核，再不分大小写查重。"""
    problems = [why for why in map(check_name, paths) if why]
    seen: dict[str, str] = {}
    for rel in paths:
        if not isinstance(rel, str):
            continue
        if rel.lower() in seen:
            problems.append(f"名字重复（不分大小写）：{seen[rel.lower()]!r} 和 {rel!r}")
        else:
            seen[rel.lower()] = rel
    return problems


def make_manifest(kind: str, files, **extra) -> dict:
    """写一份清单。extra 是这种格式自己的项。"""
    form = ITEM_KINDS[kind].format
    return {"format": FORMATS[form], "kind": kind, "files": sorted(files, key=lambda rel: rel.encode("utf-8")), **extra}


def write_manifest(folder, manifest: dict) -> None:
    """把清单按固定的字节写进文件夹。"""
    with open(Path(folder) / MANIFEST, "wb") as stream:
        stream.write(canonical(manifest) + b"\n")


def read_manifest(folder) -> dict:
    """读文件夹里的清单。没有清单、或清单不是一个 JSON 对象，报 ValueError。"""
    path = Path(folder) / MANIFEST
    try:
        manifest = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        raise ValueError(f"文件夹里没有 {MANIFEST}：{folder}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{MANIFEST} 读不出来：{error}") from None
    if not isinstance(manifest, dict):
        raise ValueError(f"{MANIFEST} 必须是一个 JSON 对象")
    return manifest


def check_manifest(kind: str, manifest: dict) -> list[str]:
    """核对清单里各种格式共用的那几项。"""
    problems = [f"清单缺 {key}" for key in ("format", "kind", "files") if key not in manifest]
    problems += [f"清单里的键要用小写字母、数字和下划线：{key!r}" for key in manifest if not is_key(key)]
    if problems:
        return problems
    form = ITEM_KINDS[kind].format
    if manifest["format"] != FORMATS[form]:
        problems.append(f"清单的格式版本是 {manifest['format']!r}，{form} 现在是第 {FORMATS[form]} 版")
    if manifest["kind"] != kind:
        problems.append(f"清单写的种类是 {manifest['kind']!r}，这里要的是 {kind}")
    files = manifest["files"]
    if not isinstance(files, list):
        return problems + ["清单的 files 必须是一个列表"]
    problems += check_names(files)
    if MANIFEST in files:
        problems.append(f"files 里不用列 {MANIFEST} 自己")
    bone_id = manifest.get("bone_id")
    if bone_id is not None and not is_label(bone_id):
        problems.append(f"骨标识要用 ASCII 的字母、数字和 . _ -：{bone_id!r}")
    return problems


def check_format(kind: str, folder) -> list[str]:
    """核对一个文件夹是不是这个种类该有的样子。返回哪里不符；空列表就是对的。

    读到比自己新的格式版本时报 versions.NewerFormat，不当成坏数据。
    """
    from stemlab.contract.formats import bone_model, data, package, points     # 它们都用到这个文件，所以在这里才 import

    item_kind = ITEM_KINDS.get(kind)
    if item_kind is None:
        return [f"十六种种类里没有 {kind!r}"]
    if item_kind.form == VALUE:
        return [f"{kind} 是一个值，不是文件夹"]
    if not Path(folder).is_dir():
        return [f"不是文件夹：{folder}"]
    try:
        manifest = read_manifest(folder)
    except ValueError as error:
        return [str(error)]
    try:
        manifest = upcast(item_kind.format, manifest)
    except CannotUpcast as error:
        return [str(error)]
    problems = check_manifest(kind, manifest)
    if problems:
        return problems

    try:
        listed, present = set(manifest["files"]), set(list_tree(folder)) - {MANIFEST}
    except (ValueError, OSError) as error:          # 里面有链接或交接点，或者有读不了的地方
        return [str(error)]
    problems += [f"清单列了但文件夹里没有：{rel}" for rel in sorted(listed - present)]
    problems += [f"文件夹里有但清单没列：{rel}" for rel in sorted(present - listed)]
    if problems:
        return problems
    specific = {"points": points.check, "bone_model": bone_model.check, "data": data.check, "package": package.check}
    check = specific.get(item_kind.format)
    return check(kind, manifest, folder) if check else []
