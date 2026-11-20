"""登记：往账本加一条“有这么一样东西”——类型、名字、位置、指纹、说明（来源）。

类型就是一个词（骨、点、CT、结果、模型……），这里不写死清单。
同类型同名字再登记一次，就是新的一版；旧的一版留着。

只有“做法”这一种类型特别：做法是一个带 method.toml 的文件夹，登记时按指纹抄一份到
data/methods/ 里留底，实验跑的是留底的那一份。别的东西（可能很大）留在原处不抄，用的时候核对指纹。
"""
import os
import shutil
import tomllib
import uuid

from . import fingerprint, ledger

METHOD = "做法"
KINDS = ("数", "整数", "选项", "开关", "文字")   # 设置项只有这五种


class Problem(Exception):
    """用户看得懂、能照着改的问题。页面上原样显示这句话。"""


def method_dir(data, entry):
    """做法留底的位置。只用指纹做文件夹名，所以 data/ 里的路径全是 ASCII。"""
    return os.path.join(data, "methods", entry["fingerprint"][:16])


def where(data, entry):
    """一样登记过的东西现在该在哪：做法看留底，别的看原处。"""
    return method_dir(data, entry) if entry["type"] == METHOD else entry["path"]


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
    for s in spec.get("settings", []):
        if s.get("kind") not in KINDS:
            raise Problem(f"设置项 {s.get('key')} 的 kind 是 {s.get('kind')!r}，只能是 {'、'.join(KINDS)} 之一")
    return spec


def register(data, type_, name, path, note="", source=None):
    """登记一样东西，返回账本里登记的那一条。source 为空就是“外来的”。"""
    type_, name, note = type_.strip(), name.strip(), note.strip()
    path = os.path.abspath(path.strip().strip('"'))
    if not type_:
        raise Problem("要写类型，比如 骨、点、CT、结果、模型、做法")
    if not os.path.exists(path):
        raise Problem(f"找不到这个路径：{path}")
    extra = {}
    if type_ == METHOD:
        spec = read_method(path)
        name = name or spec["name"]
        extra["category"] = spec["category"]
        # 先抄到一个临时文件夹，按抄下来的内容算指纹，再改名成指纹；同样内容已经有留底就不再抄
        tmp = os.path.join(data, "methods", "tmp-" + uuid.uuid4().hex[:8])
        shutil.copytree(path, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        fp, files = fingerprint.of(tmp)
        final = os.path.join(data, "methods", fp[:16])
        if os.path.exists(final):
            shutil.rmtree(tmp)
        else:
            os.replace(tmp, final)
    else:
        fp, files = fingerprint.of(path)
    if not name:
        raise Problem("要写名字")

    def make(entries):
        versions = [x["version"] for x in entries
                    if x.get("kind") == "register" and x["type"] == type_ and x["name"] == name]
        return {"kind": "register", "type": type_, "name": name, "version": max(versions, default=0) + 1,
                "path": path, "fingerprint": fp, "files": files, "note": note, "source": source, **extra}
    return ledger.append(data, make)


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
    lo, hi = s.get("min"), s.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise Problem(f"「{label}」= {value}{s.get('unit', '')}，超出了范围（{range_text(s)}）")
    return value
