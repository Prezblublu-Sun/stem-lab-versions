"""登记：往账本加一条“有这么一样东西”——类型、名字、从哪来、指纹、说明（来源）。

类型就是一个词（骨、点、CT、结果、模型、做法……），这里不写死清单。
外来的东西（做法也是）登记时一律抄一份到 data/store/ 里，按指纹留底；实验用的是留底那份，
原处的文件以后怎么变都不影响已经登记的这一版。要用变了的，再登记一次就是新的一版。
做法和别的东西只有一点不同：做法是带 method.toml 的文件夹，登记时要读它。
实验的产出不抄（它们在实验目录里，由跑完时的目录指纹看着），也不排版本：同名的产出各属各的实验。
"""
import math
import os
import shutil
import tomllib
import uuid

from . import fingerprint, ledger

METHOD = "做法"
KINDS = ("数", "整数", "选项", "开关", "文字")   # 设置项只有这五种


class Problem(Exception):
    """用户看得懂、能照着改的问题。页面上原样显示这句话。"""


def label(t):
    """一样东西给人看的叫法：外来的东西和做法带“第几版”；实验的产出不排版本，写它是哪个实验的。"""
    made_by = (t.get("source") or {}).get("experiment")
    return f'「{t["name"]}」' + (f"（e{made_by:04d} 的产出）" if made_by else f'第{t["version"]}版')


def where(data, entry):
    """一样登记过的东西，实验要用时在哪：外来的是留底，实验的产出是它在实验目录里的位置。
    两种都按相对 data 的位置记，整个数据文件夹挪到别处也找得到。"""
    return os.path.normpath(os.path.join(data, entry["kept"]))


def check(data, entry):
    """和登记时一不一样。一样返回 None，不一样返回一句话。"""
    return fingerprint.check(where(data, entry), entry["fingerprint"], entry["files"])


def read_method(folder):
    """读一个做法的 method.toml。只查跑起来必需的几项，别的随做法写。"""
    path = os.path.join(folder, "method.toml")
    if not os.path.isfile(path):
        raise Problem(f"{folder} 里没有 method.toml，它不是一个做法")
    try:
        with open(path, "rb") as f:
            spec = tomllib.load(f)
    except tomllib.TOMLDecodeError as err:
        raise Problem(f"method.toml 写得不对：{err}")
    for key, what in (("name", "名字"), ("category", "哪一类"), ("command", "命令行")):
        if not spec.get(key):
            raise Problem(f"method.toml 里缺 {key}（{what}）")
    # 每一项里跑起来必需的键；缺了就在登记时说清楚，免得到新建页才出错
    for part, keys in (("inputs", ("key", "type")), ("settings", ("key", "kind")), ("reports", ("key",))):
        items = spec.get(part, [])
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise Problem(f"method.toml 里的 {part} 要写成 [[{part}]] 一项一项的样子")
        for i, item in enumerate(items, 1):
            for key in keys:
                if not item.get(key):
                    raise Problem(f"method.toml 里 [[{part}]] 的第 {i} 项缺 {key}")
    for i, s in enumerate(spec.get("settings", []), 1):
        if s["kind"] not in KINDS:
            raise Problem(f"[[settings]] 的第 {i} 项（{s['key']}）kind 是 {s['kind']!r}，只能是 {'、'.join(KINDS)} 之一")
        if s["kind"] == "选项" and not s.get("choices"):
            raise Problem(f"[[settings]] 的第 {i} 项（{s['key']}）是选项，要写 choices")
    return spec


def _keep(data, path):
    """把原处的文件或文件夹抄一份到 data/store/<指纹>/ 留底。只用指纹做文件夹名。
    同样内容的留底已经在，就不再抄；在、但被人动过，就用刚抄的换掉。
    返回 (留底在 data 里的位置, 指纹, 各文件的指纹, 一句提示)。"""
    tmp = os.path.join(data, "store", "tmp-" + uuid.uuid4().hex[:8])   # 先抄到临时处，按抄下来的算指纹
    name = "" if os.path.isdir(path) else os.path.basename(path)
    if name:
        os.makedirs(tmp)
        shutil.copy2(path, os.path.join(tmp, name))
    else:
        shutil.copytree(path, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    fp, files = fingerprint.of(os.path.join(tmp, name) if name else tmp)
    kept = "/".join(["store", fp[:16]] + ([name] if name else []))
    target, told = os.path.normpath(os.path.join(data, kept)), ""
    if os.path.exists(target) and fingerprint.of(target)[0] != fp:
        (os.remove if name else shutil.rmtree)(target)
        told ="它的留底被人动过，已经照原处的文件恢复。"
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(os.path.join(tmp, name) if name else tmp, target)
    shutil.rmtree(tmp, ignore_errors=True)
    return kept, fp, files, told


def register(data, type_, name, path, note="", source=None):
    """登记一样东西。返回 (账本里的那一条, 给用户看的一句话)。source 为空就是外来的。"""
    type_, name, note = type_.strip(), name.strip(), note.strip()
    path = os.path.abspath(path.strip().strip('"'))
    if not type_:
        raise Problem("要写类型，比如 骨、点、CT、结果、模型、做法")
    if not os.path.exists(path):
        raise Problem(f"找不到这个路径：{path}")
    spec = read_method(path) if type_ == METHOD else {}
    name = name or spec.get("name", "")
    if not name:
        raise Problem("要写名字")
    if source is None:
        kept, fp, files, told = _keep(data, path)
    else:   # 实验的产出：不抄，记它在 data 里的位置
        (fp, files), told = fingerprint.of(path), ""
        kept, path = os.path.relpath(path, data).replace(os.sep, "/"), None
    same = {}

    def make(entries):
        older = [x for x in entries if x.get("kind") == "register" and x["type"] == type_ and x["name"] == name
                 and not x.get("source")]   # 只有外来的东西和做法排版本
        if source is None and older and older[-1]["fingerprint"] == fp:   # 内容和最新一版一样：不多出一版
            same["entry"] = older[-1]
            return None
        version = None if source else max((x["version"] for x in older), default=0) + 1
        return {"kind": "register", "type": type_, "name": name, "version": version, "path": path, "kept": kept,
                "fingerprint": fp, "files": files, "note": note, "source": source,
                **({"category": spec["category"]} if spec else {})}
    entry = ledger.append(data, make)
    if entry is None:
        return same["entry"], f"没有新登记：{type_}{label(same['entry'])}的内容和现在一样。{told}"
    return entry, f"登记好了：{type_}{label(entry)}。{told}"


def range_text(s):
    lo, hi, unit = s.get("min"), s.get("max"), s.get("unit", "")
    if s.get("kind") == "选项":
        return "、".join(str(c) for c in s.get("choices", []))
    if lo is not None and hi is not None:
        return f"{lo} ~ {hi} {unit}".strip()
    if lo is not None:
        return f"≥ {lo} {unit}".strip()
    if hi is not None:
        return f"≤ {hi} {unit}".strip()
    return "不限" if s.get("kind") in ("数", "整数") else ""


def parse_value(s, raw):
    """把填进来的值（页面上的字，或外来 JSON 里的值）变成这一项该有的值；不行就说清楚为什么。"""
    kind, label = s.get("kind"), s.get("name") or s["key"]
    if kind == "开关":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("1", "true", "on", "yes", "是", "开"):
            return True
        if text in ("", "0", "false", "off", "no", "否", "关"):
            return False
        raise Problem(f"「{label}」是开关，只能开或关，现在是 {raw!r}")
    if kind == "文字":
        return "" if raw is None else str(raw)
    if kind == "选项":
        for c in s.get("choices", []):
            if str(c) == str(raw):
                return c
        raise Problem(f"「{label}」只能从这几个里选：{range_text(s)}；现在是 {raw!r}")
    try:   # 数 或 整数
        if kind == "数":
            value = float(raw)
        else:
            value = int(raw) if isinstance(raw, int) or (isinstance(raw, float) and raw.is_integer()) \
                else int(str(raw).strip())
    except (TypeError, ValueError):
        raise Problem(f"「{label}」要填一个{kind}，现在是 {raw!r}")
    if not math.isfinite(value):
        raise Problem(f"「{label}」要填一个实实在在的数，{raw!r} 不算")
    lo, hi = s.get("min"), s.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        shown = int(value) if isinstance(value, float) and value.is_integer() else value
        raise Problem(f"「{label}」= {shown} {s.get('unit', '')}".rstrip() + f"，超出了范围（{range_text(s)}）")
    return value
