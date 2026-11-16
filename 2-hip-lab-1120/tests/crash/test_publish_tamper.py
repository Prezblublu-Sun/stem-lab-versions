"""发布断在半路，断开的时候产物的文件被动过，再对账（《修改目标》04）。

断在 test_crash.py 的四个断点之后（移过去了、设成只读了、登记了、记了 output），改动 outputs/ 里的那一份：
改 summary.json 的一个字节、删掉它、多放一个 extra.txt。设成只读的先放开：动它的是人或者别的程序，它们放得开。
然后对账两遍，看：

    对账新记的 output，记下的哈希就是内容现在的哈希
    这样产物最多登记一次、最多一条 output
    没收下的，有一条说到它的问题
    第二遍对账一个字节都不改

断在“登记了”之后的三种现在不成：已经登记、还没记 output 的那一份，补记之前不再核内容的哈希，
记下的是登记时的哈希，内容已经不是那样了。标成 xfail(strict=True, raises=AssertionError)，改好之后把标记去掉。
断在“记了 output”之后再动，是发布做完以后的事，对账不管：由核对内容（检查里的 contents）报出来。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from stemlab.contract import hashing, layout
from stemlab.experiments import reader, view
from stemlab.hooks import publish
from stemlab.registry import lookup
from tests import helpers
from tests.crash.test_crash import STEPS, cut_while_publishing

GAP = pytest.mark.xfail(strict=True, raises=AssertionError,
                        reason="修改目标 04：已经登记、还没记 output 的那一份，补记之前不再核内容的哈希")
CASES = [pytest.param(where, how, marks=GAP if where == "registered" else (), id=f"{where}-{how}")
         for where in STEPS for how in ("byte", "delete", "add")]


def writable(folder: Path) -> None:
    """把设成只读的放开：文件，Linux 上还有文件夹。"""
    for path in (folder, *folder.rglob("*")):
        os.chmod(path, stat.S_IRWXU if path.is_dir() else stat.S_IREAD | stat.S_IWRITE)


def tamper(folder: Path, how: str) -> None:
    """byte：改 summary.json 的头一个字节；delete：删掉它；add：多放一个清单没列的 extra.txt。"""
    writable(folder)
    summary = folder / "summary.json"
    if how == "byte":
        body = bytearray(summary.read_bytes())
        body[0] ^= 0x01
        summary.write_bytes(bytes(body))
    elif how == "delete":
        summary.unlink()
    else:
        (folder / "extra.txt").write_bytes(b"put here while publishing was cut\n")


@pytest.mark.parametrize("where,how", CASES)
def test_a_product_changed_while_publishing_was_cut(lab, data, where, how):
    made = cut_while_publishing(where)
    before = len(reader.read(made))
    tamper(layout.output_dir(made, 1, "report"), how)

    publish.reconcile(made)
    once = helpers.snapshot(data)
    publish.reconcile(made)
    assert helpers.snapshot(data) == once, "对账做两遍和做一遍结果相同"

    entries = reader.read(made)
    for entry in entries[before:]:
        if entry["entry"] == "output":
            assert hashing.hash_tree(lookup.content(entry["item"])) == entry["hash"], "对账记下的哈希就是内容现在的哈希"
    outputs = [entry for entry in entries if entry["entry"] == "output" and entry["output"] == "report"]
    registered = [item for item in lookup.by_origin(made, 1) if item["origin"]["output"] == "report"]
    assert len(outputs) <= 1 and len(registered) <= 1, "最多登记一次、最多一条 output"
    if not outputs:
        problems = view.view(made).rounds[0].problems
        assert any("report" in problem["error"] for problem in problems), f"没收下，要有一条说到它的问题：{problems}"
