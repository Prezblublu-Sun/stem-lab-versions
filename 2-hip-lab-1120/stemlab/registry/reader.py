"""读两个 jsonl 的唯一一处，容忍末尾半行；head() 链头。

读的一方读完就关。读出来的条目在内存里留一份，文件没变就不重读；这一份不要改动。
"""
from __future__ import annotations

from pathlib import Path

from stemlab.contract import chain, layout, versions

_CACHE: dict[str, tuple[tuple, list[bytes], list[dict]]] = {}


def read(path: Path, name: str) -> tuple[list[bytes], list[dict]]:
    """读一条链：完整的各行，和转成现在形状的各条。末尾写了一半的那一行不算。文件还没有就是空的。"""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return [], []
    signature = (stat.st_size, stat.st_mtime_ns)
    cached = _CACHE.get(str(path))
    if cached and cached[0] == signature:
        return cached[1], cached[2]
    lines, _ = chain.split(path.read_bytes())
    entries = [versions.upcast(name, chain.parse(line)) for line in lines]
    _CACHE[str(path)] = (signature, lines, entries)
    return lines, entries


def lines(path: Path) -> list[bytes]:
    """一条链现在盘上的各行，不经内存里留的那一份，也不解析。核对时用它。"""
    try:
        return chain.split(path.read_bytes())[0]
    except FileNotFoundError:
        return []


def items() -> list[dict]:
    """登记链上的全部条目，先登记的在前。"""
    return read(layout.register_file(), "register")[1]


def links() -> list[dict]:
    """手动挂接的全部条目。"""
    return read(layout.links_file(), "links")[1]


def head() -> chain.Head:
    """登记链的链头。"""
    return chain.head_of(read(layout.register_file(), "register")[0])
