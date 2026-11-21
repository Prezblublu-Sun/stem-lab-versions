"""读实验记录。只读。

    read(实验)      这个实验的全部条目
    head(实验)      它的链头
    verify(实验)    记录有没有被改；每条长得对不对；每条在当时是不是能记的
    all_ids()       发过的全部实验编号

读的一方读完就关。读出来的条目在内存里留一份，文件没变就不重读；这一份不要改动。
"""
from __future__ import annotations

from pathlib import Path

from stemlab.contract import chain, entries, layout, states, versions

_CACHE: dict[str, tuple[tuple, list[bytes], list[dict]]] = {}


def _read(path: Path, name: str) -> tuple[list[bytes], list[dict]]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return [], []
    signature = (stat.st_size, stat.st_mtime_ns)
    cached = _CACHE.get(str(path))
    if cached and cached[0] == signature:
        return cached[1], cached[2]
    lines, _ = chain.split(path.read_bytes())
    parsed = [versions.upcast(name, chain.parse(line)) for line in lines]
    _CACHE[str(path)] = (signature, lines, parsed)
    return lines, parsed


def lines(path: Path) -> list[bytes]:
    """一条链现在盘上的各行，不经内存里留的那一份，也不解析。核对时用它。"""
    try:
        return chain.split(path.read_bytes())[0]
    except FileNotFoundError:
        return []


def read(experiment: str) -> list[dict]:
    """这个实验的全部条目，先记的在前。末尾写了一半的那一行不算。"""
    return _read(layout.record_file(experiment), "record")[1]


def head(experiment: str) -> chain.Head:
    """这个实验记录的链头。"""
    return chain.head_of(_read(layout.record_file(experiment), "record")[0])


def issued() -> list[dict]:
    """发号链上的全部条目。"""
    return _read(layout.issued_file(), "issued")[1]


def issued_head() -> chain.Head:
    return chain.head_of(_read(layout.issued_file(), "issued")[0])


def all_ids() -> list[str]:
    """发过的全部实验编号，先发的在前。编号用过不再用，文件夹被删了也一样。"""
    return [entry["id"] for entry in issued()]


def verify(experiment: str) -> list[str]:
    """核对一个实验的记录。返回哪里不对，指出是哪一条；空列表就是没问题。"""
    raw = lines(layout.record_file(experiment))
    found = chain.check_chain(raw)
    if found:
        return [f"{experiment} 的记录第 {found.line} 条：{found.reason}"]
    status = states.Status()
    for number, line in enumerate(raw, start=1):
        try:
            entry = versions.upcast("record", chain.parse(line))
        except versions.CannotUpcast as error:
            return [f"{experiment} 的记录第 {number} 条：{error}"]
        problems = entries.check_entry(entry)
        why = None if problems else states.refuse(status, entry)
        if problems or why:
            return [f"{experiment} 的记录第 {number} 条：{text}" for text in (problems or [f"当时不该记下：{why}"])]
        states.advance(status, entry)
    return []


def verify_issued() -> list[str]:
    """核对发号链。"""
    raw = lines(layout.issued_file())
    found = chain.check_chain(raw)
    if found:
        return [f"发号链第 {found.line} 条：{found.reason}"]
    return [f"发号链第 {number} 条：{text}" for number, line in enumerate(raw, start=1)
            for text in entries.check_issued(versions.upcast("issued", chain.parse(line)))]
