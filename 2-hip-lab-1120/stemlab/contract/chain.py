"""只追加的哈希链。登记链和实验记录链共用这一份。

一条就是一行固定的字节（UTF-8、LF）。每条带三样：
    seq    序号，从 1 起
    prev   上一条的 this；第一条是 64 个 0
    this   这一条去掉 this 之后的固定字节的 SHA-256
所以任何一条被改、中间任何一条被删，都指得出是哪一条。
末尾几条被整条删掉，链自己查不出，要靠备份时记下的链头，见 extends。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from stemlab.contract.hashing import canonical, hash_bytes

RESERVED = ("seq", "prev", "this")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")


@dataclass(frozen=True)
class Head:
    """链头：最后一条的序号和哈希。"""
    seq: int
    this: str


GENESIS = Head(0, "0" * 64)


@dataclass(frozen=True)
class Break:
    """链上第一处不对的地方。"""
    line: int       # 第几行，从 1 数
    reason: str


def stamp(moment: datetime) -> str:
    """时间的写法：UTC，到毫秒，定长，所以字符串的先后就是时间的先后。"""
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def is_time(text) -> bool:
    """是不是 stamp 写出来的那种时间。"""
    return isinstance(text, str) and _TIME.fullmatch(text) is not None


def dumps(entry: dict) -> bytes:
    """把一条写成一行固定的字节。"""
    return canonical(entry) + b"\n"


def parse(line: bytes) -> dict:
    """把一行读成一条。不是一个 JSON 对象就报 ValueError。"""
    entry = json.loads(line.decode("utf-8"), parse_constant=_no_constant)
    if not isinstance(entry, dict):
        raise ValueError("一条必须是一个 JSON 对象")
    return entry


def _no_constant(name):
    raise ValueError(f"JSON 里不能有 {name}")


def link(body: dict, head: Head) -> dict:
    """给一条加上序号、上一条的哈希和它自己的哈希。"""
    clash = [key for key in RESERVED if key in body]
    if clash:
        raise ValueError(f"这几项由链来填，不能自己带：{clash}")
    entry = dict(body, seq=head.seq + 1, prev=head.this)
    entry["this"] = hash_bytes(canonical(entry))
    return entry


def split(data: bytes) -> tuple[list[bytes], int]:
    """把链文件的全部字节切成完整的行。

    返回（各行，末尾写了一半的那一行有几个字节）。没有以 LF 结尾的最后一行就是写了一半的，
    追加之前要把它截掉。
    """
    lines = data.split(b"\n")
    tail = lines.pop()
    return lines, len(tail)


def head_of(lines: list[bytes]) -> Head:
    """链头。空链的链头是 GENESIS。"""
    if not lines:
        return GENESIS
    last = parse(lines[-1])
    return Head(last["seq"], last["this"])


def check_chain(lines: list[bytes]) -> Break | None:
    """核对一条链，指出第一处被改或被删的地方。没问题返回 None。"""
    head = GENESIS
    for number, line in enumerate(lines, start=1):
        try:
            entry = parse(line)
        except ValueError:
            return Break(number, "不是一条合法的 JSON")
        try:
            same_bytes = dumps(entry) == line + b"\n"
        except (TypeError, ValueError):
            same_bytes = False
        if not same_bytes:
            return Break(number, "不是规范的字节：被手改过，或者换行、编码被改写了")
        body = {key: value for key, value in entry.items() if key != "this"}
        if entry.get("this") != hash_bytes(canonical(body)):
            return Break(number, "内容和它自己的哈希对不上：这一条被改过")
        if entry.get("seq") != head.seq + 1 or entry.get("prev") != head.this:
            return Break(number, "和上一条接不上：它前面有条目被删、被换，或者顺序被动过")
        head = Head(entry["seq"], entry["this"])
    return None


def extends(lines: list[bytes], head: Head) -> bool:
    """这条链是不是 head 那一份的延长。

    备份时记下链头；之后本机的链应该还包含那一条，而且那一条没变。
    末尾几条被删掉的话，这里查得出来。
    """
    if head == GENESIS:
        return True
    if len(lines) < head.seq:
        return False
    try:
        return parse(lines[head.seq - 1]).get("this") == head.this
    except ValueError:
        return False
