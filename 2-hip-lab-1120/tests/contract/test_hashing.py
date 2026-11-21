"""哈希：同样的内容在 Windows 和 Linux 上算出同一个哈希；文件的先后不影响 hash_tree。

下面写死的哈希是在 Windows 上算的。同一份测试在 Linux 上也跑，两边都过就是两边一致。
"""
from __future__ import annotations

import hashlib

import pytest

from stemlab.contract.hashing import (canonical, fingerprint, hash_bytes, hash_file, hash_json, hash_tree,
                                      is_hash, list_tree)

EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
VALUE = {"b": 1, "a": [1.0, 2.5, "中文"], "c": None, "d": {"z": True, "y": -0.0}}
FILES = {"b.txt": b"second\n", "a.txt": b"first\n", "sub/c.bin": bytes(range(256))}
TREE = "871c9031723aaea1d14eb059e75c760f8afaf6728e9fe719a3a8b2d8de7db68d"


def make_tree(root, order):
    for rel in order:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(FILES[rel])
    return root


def test_hash_bytes_and_file_are_plain_sha256(tmp_path):
    assert hash_bytes(b"") == EMPTY
    data = b"\r\n\xff\x00 text or not \r\n" * 100_000       # 比一次读的块大，带 CRLF 和不是 UTF-8 的字节
    path = tmp_path / "blob"
    path.write_bytes(data)
    assert hash_file(path) == hashlib.sha256(data).hexdigest() == hash_bytes(data)


def test_canonical_bytes_are_fixed():
    assert canonical(VALUE) == b'{"a":[1,2.5,"\xe4\xb8\xad\xe6\x96\x87"],"b":1,"c":null,"d":{"y":0,"z":true}}'
    assert hash_json(VALUE) == "eb7bb15b5d10033c6b727c79d6d2129b7b0524d860a1efceb42b21e8499367d3"


def test_key_order_and_tuples_do_not_matter():
    assert hash_json({"a": 1, "b": [1, 2]}) == hash_json({"b": (1, 2), "a": 1})


def test_whole_floats_are_the_same_value_as_integers():
    assert hash_json({"x": 5}) == hash_json({"x": 5.0}) == hash_json({"x": 5e0})
    assert hash_json(0) == hash_json(-0.0)
    assert hash_json(5) != hash_json(5.5) and hash_json(True) != hash_json(1) and hash_json("5") != hash_json(5)
    assert canonical(1e300) == b"1e+300" and canonical(0.1) == b"0.1"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1: "x"}, {"x": {1, 2}}, b"bytes", object()])
def test_what_json_cannot_hold_is_an_error(bad):
    with pytest.raises((TypeError, ValueError)):
        canonical(bad)


def test_hash_tree_is_defined_by_sorted_lines(tmp_path):
    root = make_tree(tmp_path / "t", ["b.txt", "a.txt", "sub/c.bin"])
    lines = [f"{hashlib.sha256(FILES[rel]).hexdigest()}  {rel}\n" for rel in sorted(FILES)]
    assert hash_tree(root) == hashlib.sha256("".join(lines).encode("utf-8")).hexdigest() == TREE
    assert list_tree(root) == ["a.txt", "b.txt", "sub/c.bin"]


def test_file_order_does_not_change_hash_tree(tmp_path):
    first = make_tree(tmp_path / "one", ["a.txt", "b.txt", "sub/c.bin"])
    second = make_tree(tmp_path / "two", ["sub/c.bin", "b.txt", "a.txt"])
    assert hash_tree(first) == hash_tree(second) == TREE


def test_any_change_changes_hash_tree(tmp_path):
    root = make_tree(tmp_path / "t", list(FILES))
    (root / "a.txt").write_bytes(b"first\r\n")
    assert hash_tree(root) != TREE, "换行被改写也算改"
    (root / "a.txt").write_bytes(FILES["a.txt"])
    assert hash_tree(root) == TREE
    (root / "a.txt").rename(root / "A.txt")
    assert hash_tree(root) != TREE, "改名也算改"
    (root / "A.txt").rename(root / "a.txt")
    (root / "new.txt").write_bytes(b"")
    assert hash_tree(root) != TREE, "多一个空文件也算改"


def test_empty_folders_do_not_count_and_missing_folder_is_an_error(tmp_path):
    root = make_tree(tmp_path / "t", list(FILES))
    (root / "empty" / "deeper").mkdir(parents=True)
    assert hash_tree(root) == TREE
    assert hash_tree(tmp_path / "t" / "empty") == EMPTY
    with pytest.raises(NotADirectoryError):
        hash_tree(tmp_path / "nothing")
    with pytest.raises(NotADirectoryError):
        hash_tree(root / "a.txt")


def test_ignore_skips_names_at_any_depth(tmp_path):
    root = make_tree(tmp_path / "t", list(FILES))
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (root / "sub" / "__pycache__").mkdir()
    (root / "sub" / "__pycache__" / "y.pyc").write_bytes(b"cache")
    assert hash_tree(root) != TREE
    assert hash_tree(root, ignore=("__pycache__",)) == TREE


def test_paths_sort_by_bytes_not_by_locale(tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    for name in ("ab", "a", "_", "Z", "a-b", "a.b", "B"):
        (root / (name + ".x")).write_bytes(b"")
    # 按字节：大写字母在前，下划线在大写和小写之间。系统区域的排序不是这样
    assert list_tree(root) == ["B.x", "Z.x", "_.x", "a-b.x", "a.b.x", "a.x", "ab.x"]


def test_fingerprint_is_by_name():
    parts = dict(point="1" * 64, bone_model="2" * 64, kernel="3" * 64, export="4" * 64, plugin_frozen="5" * 64)
    assert fingerprint(**parts) == "ee9bec42aa05e4d48377df998edd4ffbede9b721bba1915ad5a557e2d50eec5a"
    assert fingerprint(**dict(reversed(list(parts.items())))) == fingerprint(**parts), "先后不影响"
    assert fingerprint(**dict(parts, kernel="9" * 64)) != fingerprint(**parts)
    swapped = dict(parts, point=parts["kernel"], kernel=parts["point"])
    assert fingerprint(**swapped) != fingerprint(**parts), "同样几个哈希换了位置，结果要变"
    fewer = {key: value for key, value in parts.items() if key != "export"}
    assert fingerprint(**fewer) != fingerprint(**parts)


@pytest.mark.parametrize("bad", ["abc", "1" * 63, "G" * 64, "A" * 64, None, 5])
def test_fingerprint_only_takes_full_hashes(bad):
    assert not is_hash(bad)
    with pytest.raises(ValueError):
        fingerprint(point=bad)
    with pytest.raises(ValueError):
        fingerprint()
