"""往实验记录里写。

    create(类型, 三张表, 说明, 标签)   发号，并写下第一条
    append(实验, 条目)                 实验记录唯一的追加函数

这一块里不出现对状态名的判断：一条现在能不能记，问契约里的状态表。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from stemlab.contract import Refused, chain, entries, layout, states, versions
from stemlab.experiments import lock


def _now() -> str:
    return chain.stamp(datetime.now(timezone.utc))


def _write(path, data: bytes, tail: int, entry: dict) -> None:
    """按字节追加一行，然后落盘。末尾写了一半的那一行先截掉。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "r+b" if path.exists() else "wb") as stream:
        stream.seek(len(data) - tail)
        stream.truncate()
        stream.write(chain.dumps(entry))
        stream.flush()
        os.fsync(stream.fileno())


def append(experiment: str, body: dict) -> dict:
    """实验记录唯一的追加函数。body 是条目的内容，不带 format、time 和链填的三项。

    条目长得不对，或者现在不能记，都是被拒，记录里不多一条。
    """
    path = layout.record_file(experiment)
    with lock.writing(experiment):                                          # 1 拿这条链的锁
        data = path.read_bytes() if path.exists() else b""
        lines, tail = chain.split(data)                                     # 2 末尾写了一半的一行，下面截掉
        head = chain.head_of(lines)                                         # 3 读链头，给序号和上一条的哈希
        entry = chain.link(dict(body, format=versions.FORMATS["record"], time=_now()), head)
        problems = entries.check_entry(entry)
        if problems:
            raise Refused("；".join(problems))
        existing = [versions.upcast("record", chain.parse(line)) for line in lines]
        why = states.refuse(states.fold(existing), entry)                   # 4 由全部条目算出现状，问状态表
        if why:
            raise Refused(why)
        _write(path, data, tail, entry)                                     # 5 按字节追加一行，然后落盘
    return entry                                                            # 6 放锁


def create(type_name: str, tables: dict, note: str = "", tags=(), clone_of: str | None = None) -> str:
    """新建一个实验：发号，并写下第一条。返回实验的编号。

    tables 是这个类型的输入表、产物表、结局表，抄进 created，插件拔掉之后旧实验照样读得懂。
    """
    first = {"entry": "created", "type": type_name, "inputs": tables["inputs"], "outputs": tables["outputs"],
             "outcomes": tables["outcomes"], "note": note, "tags": list(tags)}
    if clone_of is not None:
        first["clone_of"] = clone_of
    problems = entries.check_entry(dict(first, format=versions.FORMATS["record"], time=_now()))
    if problems:
        raise Refused("；".join(problems))                                   # 先核过再发号，免得白占一个编号

    path = layout.issued_file()
    with lock.issuing():
        data = path.read_bytes() if path.exists() else b""
        lines, tail = chain.split(data)
        head = chain.head_of(lines)
        experiment = layout.experiment_id(head.seq + 1)
        issue = chain.link({"format": versions.FORMATS["issued"], "time": _now(), "id": experiment,
                            "type": type_name}, head)
        _write(path, data, tail, issue)
    append(experiment, first)
    return experiment
