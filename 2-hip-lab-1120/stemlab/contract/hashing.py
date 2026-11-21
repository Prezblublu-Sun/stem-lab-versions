"""哈希。完整的 SHA-256，一律按字节算。

同样的内容在两台机器上必须算出同一个哈希，所以这里不用文本模式、不看系统区域、
不看文件在盘上的先后。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path

_HASH = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1 << 20
_EXACT = 2 ** 53        # 浮点数在这个范围内能精确表示整数


def is_hash(text) -> bool:
    """是不是一个完整的 SHA-256（64 位小写十六进制）。"""
    return isinstance(text, str) and _HASH.fullmatch(text) is not None


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path) -> str:
    """一个文件的哈希。按字节读，不管它是不是文本。"""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(obj) -> bytes:
    """一个 JSON 值的固定字节：键排序、UTF-8、无空白。

    值是整数的浮点数写成整数，所以 5 和 5.0 是同一个值、同一个哈希。
    NaN、无穷大和 JSON 里没有的类型直接报错，不悄悄换成别的。
    """
    text = json.dumps(_plain(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8")


def _plain(obj):
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("NaN 和无穷大不能写进 JSON")
        return int(obj) if obj.is_integer() and abs(obj) < _EXACT else obj
    if isinstance(obj, dict):
        for key in obj:
            if not isinstance(key, str):
                raise TypeError(f"JSON 的键必须是字符串：{key!r}")
        return {key: _plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(value) for value in obj]
    raise TypeError(f"不能写进 JSON 的类型：{type(obj).__name__}")


def hash_json(obj) -> str:
    """一个 JSON 值的哈希，按它的固定字节算。"""
    return hash_bytes(canonical(obj))


def list_tree(folder, ignore=()) -> list[str]:
    """文件夹里全部文件的相对路径：用正斜杠，按 UTF-8 字节排序。

    ignore 里的名字在任何一层都跳过（算代码文件夹的哈希时用来跳过 __pycache__）。
    里面有链接或交接点就报 ValueError：那样内容就不全在这个文件夹自己里面了。读不了的子文件夹也报错，不悄悄跳过。
    """
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(f"不是文件夹：{root}")

    def fail(error: OSError):
        raise error

    found = []
    for base, dirs, files in os.walk(root, onerror=fail):
        dirs[:] = [name for name in dirs if name not in ignore]
        for name in dirs + files:
            path = os.path.join(base, name)
            if name not in ignore and (os.path.islink(path) or os.path.isjunction(path)):
                raise ValueError(f"文件夹里不能有链接或交接点：{Path(path).relative_to(root).as_posix()}")
        for name in files:
            if name not in ignore:
                found.append((Path(base) / name).relative_to(root).as_posix())
    return sorted(found, key=lambda rel: rel.encode("utf-8"))


def hash_tree(folder, ignore=()) -> str:
    """一个文件夹的哈希。

    每个文件一行“文件的哈希、两个空格、相对路径”，各行按路径的字节排序后接起来再算一次。
    文件在盘上的先后、文件夹在哪台机器上都不影响结果。空文件夹不计。
    """
    root = Path(folder)
    lines = [f"{hash_file(root / rel)}  {rel}\n".encode("utf-8") for rel in list_tree(root, ignore)]
    return hash_bytes(b"".join(lines))


def fingerprint(**parts: str) -> str:
    """几个哈希合成一个。

    按名字给，所以先后不影响结果；少给一个、多给一个或换了名字，结果就变。
    输入指纹就是这样算的：点、骨模型、内核、导出设定、插件冻结文件，五个哈希合起来。
    """
    if not parts:
        raise ValueError("至少要给一个哈希")
    for name, value in parts.items():
        if not is_hash(value):
            raise ValueError(f"{name} 不是一个完整的哈希：{value!r}")
    return hash_json(parts)
