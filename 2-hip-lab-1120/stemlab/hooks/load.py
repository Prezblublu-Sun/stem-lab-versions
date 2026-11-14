"""找到所有插件；FROZEN 清单怎么读；插件文件夹和冻结文件的哈希。

核心不认识任何插件：靠扫描插件所在的包（默认是仓库根目录下的 plugins/）找到它们，
源码里没有对插件的 import。

FROZEN 清单的写法（UTF-8、LF）：
    # 开头的是说明
    tree stemlab/contract           这个文件夹整个固定：里面多一个、少一个文件都算对不上
    <SHA-256>  stemlab/desk/__main__.py     一个固定的文件，和它的哈希（中间两个空格）
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from stemlab.contract import Refused, hashing, layout, plugin_api

FROZEN = "FROZEN"
IGNORE = ("__pycache__",)       # 算代码文件夹的哈希时跳过


@dataclass(frozen=True)
class Frozen:
    trees: tuple[str, ...]      # 整个固定的文件夹
    files: dict                 # 路径 -> 清单里记的哈希
    hash: str                   # 清单自己的哈希


@dataclass(frozen=True)
class Loaded:
    kinds: dict                 # 类型名 -> Kind
    owners: dict                # 类型名 -> 插件名
    errors: dict                # 装不上的插件 -> 原因


def parse_frozen(data: bytes) -> Frozen:
    """读 FROZEN 清单的字节。写法不对就报 ValueError。"""
    trees, files = [], {}
    for number, line in enumerate(data.decode("utf-8").split("\n"), start=1):
        if not line or line.startswith("#"):
            continue
        if line.startswith("tree "):
            trees.append(line[5:])
        elif len(line) > 66 and hashing.is_hash(line[:64]) and line[64:66] == "  " and line[66:] not in files:
            files[line[66:]] = line[:64]
        else:
            raise ValueError(f"{FROZEN} 第 {number} 行写法不对，或者路径重复：{line!r}")
    return Frozen(tuple(trees), files, hashing.hash_bytes(data))


def read_frozen() -> Frozen:
    """读仓库根目录的 FROZEN 清单。"""
    return parse_frozen((layout.repo_root() / FROZEN).read_bytes())


def plugins_dir() -> Path:
    """插件所在的包对应的文件夹。"""
    return layout.repo_root().joinpath(*layout.plugins_package().split("."))


def plugin_names() -> list[str]:
    """扫描出来的插件名：带 plugin.py 的子文件夹。"""
    root = plugins_dir()
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if (path / "plugin.py").is_file())


def plugin_hash(plugin: str) -> str:
    """插件文件夹现在的哈希。"""
    return hashing.hash_tree(plugins_dir() / plugin, ignore=IGNORE)


def frozen_hash(plugin: str) -> str:
    """这个插件冻结文件现在的哈希：FROZEN 清单里列在它名下的那些文件，按盘上现在的内容算。

    输入指纹用它，所以冻结文件一改，同一个点就是另一个作业。
    """
    root = layout.repo_root()
    prefix = (plugins_dir() / plugin).relative_to(root).as_posix() + "/"
    listed = sorted(rel for rel in read_frozen().files if rel.startswith(prefix))
    return hashing.hash_json({rel: hashing.hash_file(root / rel) if (root / rel).is_file() else None for rel in listed})


_AT_IMPORT: dict[str, str] = {}     # 插件 -> 这个进程 import 它时文件夹的哈希


class Stale(Refused):
    """这个进程里装着的插件代码，不是这一轮该跑的那一份。重新起这个进程再来；什么都没写下。"""


def imported(plugin: str) -> str | None:
    """这个进程 import 这个插件时它文件夹的哈希：这个进程里真正在跑的就是这一份。还没 import 过就是 None。

    记进来历的哈希必须是它，不能是盘上现在的：盘上的代码可以在 import 之后又被改。
    """
    return _AT_IMPORT.get(plugin)


def stale() -> list[str]:
    """这个进程里装着的插件，哪几个的代码在 import 之后又变了。值守发现有就该重启，不拿旧代码接着跑。"""
    return [name for name, before in _AT_IMPORT.items() if plugin_hash(name) != before]


def load() -> Loaded:
    """找到所有插件，返回类型名到 Kind 的表。装不上的给出原因，别的照常。"""
    root = str(layout.repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    package = layout.plugins_package()
    kinds, owners, errors = {}, {}, {}
    for name in plugin_names():
        try:
            before = plugin_hash(name)
            module = importlib.import_module(f"{package}.{name}.plugin")
            _AT_IMPORT.setdefault(name, before)
            declared = list(module.KINDS)
            problems = [text for kind in declared for text in plugin_api.check_kind(kind)]
        except Exception as error:  # noqa: BLE001  插件写得再糟也不能带倒别的
            errors[name] = f"装不上：{type(error).__name__}: {error}"
            continue
        if not problems:
            problems = [f"类型 {kind.name} 要以插件名 {name} 开头" for kind in declared
                        if kind.name.split(".")[0] != name]
            problems += [f"类型 {kind.name} 报了两次" for kind in declared
                         if [k.name for k in declared].count(kind.name) > 1]
        if problems:
            errors[name] = "；".join(dict.fromkeys(problems))
            continue
        for kind in declared:
            kinds[kind.name], owners[kind.name] = kind, name
    return Loaded(kinds, owners, errors)
