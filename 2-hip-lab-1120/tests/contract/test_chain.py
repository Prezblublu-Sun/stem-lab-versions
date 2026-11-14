"""哈希链：一条一行固定的字节；被改、被删都指得出是哪一条。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stemlab.contract.chain import (GENESIS, Head, check_chain, dumps, extends, head_of, is_time, link, parse,
                                    split, stamp)
from tests.contract import samples as s

NOTE = {"format": 1, "time": s.T0, "entry": "noted", "text": "一条备注"}
THIS = "7ba6dc554d69e3322d68ec9625ca8a0180785e0454c554c7a12659bb785fcda2"


def lines_of(count: int) -> list[bytes]:
    bodies = [dict(NOTE, text=f"第 {n} 条") for n in range(1, count + 1)]
    return [dumps(entry)[:-1] for entry in s.chained(bodies)]


def test_link_and_dumps_are_fixed_bytes():
    linked = link(NOTE, GENESIS)
    assert (linked["seq"], linked["prev"], linked["this"]) == (1, "0" * 64, THIS)
    assert dumps(linked) == (
        b'{"entry":"noted","format":1,"prev":"' + b"0" * 64 + b'","seq":1,'
        b'"text":"\xe4\xb8\x80\xe6\x9d\xa1\xe5\xa4\x87\xe6\xb3\xa8","this":"' + THIS.encode() + b'",'
        b'"time":"2026-01-01T00:00:00.000Z"}\n')
    assert NOTE == {"format": 1, "time": s.T0, "entry": "noted", "text": "一条备注"}, "link 不改原来的那一条"


def test_dumps_then_parse_gives_the_same_entry_and_the_same_bytes():
    linked = link(dict(NOTE, numbers=[1, 2.5, -3], nested={"值": None, "ok": True}), GENESIS)
    assert parse(dumps(linked)[:-1]) == linked
    assert dumps(parse(dumps(linked)[:-1])) == dumps(linked)


def test_link_refuses_reserved_keys():
    for key in ("seq", "prev", "this"):
        with pytest.raises(ValueError):
            link(dict(NOTE, **{key: 1}), GENESIS)


def test_a_good_chain_passes():
    lines = lines_of(5)
    assert check_chain(lines) is None
    assert check_chain([]) is None
    assert head_of(lines) == Head(5, parse(lines[-1])["this"])
    assert head_of([]) == GENESIS


@pytest.mark.parametrize("position", [1, 3, 5])
def test_a_changed_entry_is_pointed_out_even_the_last_one(position):
    lines = lines_of(5)
    lines[position - 1] = lines[position - 1].replace("第".encode(), "笫".encode())
    found = check_chain(lines)
    assert found.line == position and "被改过" in found.reason


@pytest.mark.parametrize("position", [1, 3])
def test_a_deleted_entry_is_pointed_out(position):
    lines = lines_of(5)
    del lines[position - 1]
    found = check_chain(lines)
    assert found.line == position and "接不上" in found.reason


def test_swapped_and_repeated_entries_are_pointed_out():
    lines = lines_of(4)
    assert check_chain([lines[0], lines[2], lines[1], lines[3]]).line == 2
    assert check_chain([lines[0], lines[1], lines[1], lines[2]]).line == 3


def test_an_entry_replaced_by_one_from_another_chain_is_pointed_out():
    """换进来的那一条自己的哈希是对的、序号也对，只有“上一条的哈希”对不上。"""
    ours = lines_of(4)
    theirs = [dumps(entry)[:-1] for entry in s.chained([dict(NOTE, text=f"别处的第 {n} 条") for n in range(1, 5)])]
    found = check_chain([ours[0], theirs[1], ours[2], ours[3]])
    assert found.line == 2 and "接不上" in found.reason
    found = check_chain(ours[:3] + [theirs[3]])
    assert found.line == 4 and "接不上" in found.reason, "换的是最后一条也查得出"


@pytest.mark.parametrize("damage,word", [
    (lambda line: line + b"\r", "规范"),                                  # 换行被改写成 CRLF
    (lambda line: line.replace(b'":', b'": ', 1), "规范"),                # 多了空白
    (lambda line: b"\xef\xbb\xbf" + line, "JSON"),                        # 被加了 BOM
    (lambda line: line[:-1], "JSON"),                                     # 少了半截
    (lambda line: b'["not","an","object"]', "JSON"),
    (lambda line: b"", "JSON"),
    (lambda line: line.replace(b'"seq":2', b'"seq":2.0'), "规范"),
    (lambda line: line.replace("第 2 条".encode(), b"\\u7b2c 2 \\u6761"), "规范"),     # 同样的内容换了写法
])
def test_any_other_bytes_are_pointed_out(damage, word):
    lines = lines_of(3)
    lines[1] = damage(lines[1])
    found = check_chain(lines)
    assert found.line == 2 and word in found.reason


def test_split_finds_the_half_written_tail():
    lines = lines_of(3)
    whole = b"".join(line + b"\n" for line in lines)
    assert split(whole) == (lines, 0)
    assert split(b"") == ([], 0)
    assert split(whole + b'{"entry":"no') == (lines, 12)
    assert split(whole + lines[0]) == (lines, len(lines[0])), "没有以 LF 结尾的整行也算写了一半"
    assert split(lines[0]) == ([], len(lines[0]))


def test_extends_notices_a_deleted_or_replaced_tail():
    lines = lines_of(5)
    at_backup = Head(3, parse(lines[2])["this"])
    assert extends(lines, at_backup) and extends(lines[:3], at_backup)
    assert not extends(lines[:2], at_backup), "末尾被删"
    other = lines_of(2) + [dumps(e)[:-1] for e in s.chained([dict(NOTE, text="别的")] * 3)[2:]]
    assert not extends(other, at_backup), "备份之后那一条被换过"
    assert extends([], GENESIS) and extends(lines, GENESIS)


def test_time_stamps_are_utc_fixed_width_and_sortable():
    moment = datetime(2026, 11, 13, 16, 5, 9, 123999, tzinfo=timezone(timedelta(hours=8)))
    assert stamp(moment) == "2026-11-13T08:05:09.123Z"
    later = stamp(moment + timedelta(milliseconds=1))
    assert is_time(later) and later > stamp(moment)
    assert not is_time("2026-11-13 08:05:09") and not is_time("2026-11-13T08:05:09Z") and not is_time(None)
