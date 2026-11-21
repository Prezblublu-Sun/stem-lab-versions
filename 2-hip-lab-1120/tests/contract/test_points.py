"""一批点：写出再读回不变；条件没写全的被点名；补默认两次结果相同；同一个点哈希相同。"""
from __future__ import annotations

import copy

import pytest

from stemlab.contract.formats.manifest import check_format, read_manifest, write_manifest
from stemlab.contract.formats.points import (POINTS_FILE, check_points, fill_defaults, point_hash, read_points,
                                             with_groups, write_points)
from stemlab.contract.hashing import canonical, hash_tree

POINT = {"name": "p1", "bone_id": "femur042", "design": {"length": 120, "offset": 37.5},
         "conditions": {"load": "walk", "bw": 700.0}, "reason": "手写"}
GOLDEN = "965e2d8c935c77512ee6d4acccf511aaf0a7da0b69562cf73152de82cc255ad6"


def batch(count=3):
    return [dict(copy.deepcopy(POINT), name=f"p{n}", design={"length": 100 + n, "offset": 37.5})
            for n in range(1, count + 1)]


def test_point_hash_is_fixed_across_machines():
    assert point_hash(POINT) == GOLDEN


def test_the_same_point_has_the_same_hash():
    same = {"reason": "策略选的", "name": "another-name", "bone_id": "femur042",
            "conditions": {"bw": 700, "load": "walk"}, "design": {"offset": 37.5, "length": 120.0}}
    assert point_hash(same) == GOLDEN, "名字、理由、键的先后、120 和 120.0 都不影响"


@pytest.mark.parametrize("change", [
    lambda p: p.update(bone_id="femur043"),
    lambda p: p["design"].update(length=121),
    lambda p: p["design"].update(extra=0),
    lambda p: p["design"].pop("offset"),
    lambda p: p["conditions"].update(load="stair"),
    lambda p: p["conditions"].update(bw=700.5),
    lambda p: p["conditions"].pop("bw"),
])
def test_changing_any_part_changes_the_hash(change):
    changed = copy.deepcopy(POINT)
    change(changed)
    assert point_hash(changed) != GOLDEN


def test_placement_and_derive_values_given_per_point_are_written_in_full_and_hashed(tmp_path):
    """第 2 版：放置、推导量两组也能每个点给，和条件一样写全；有值才算进哈希，没值的点哈希和第 1 版一样。"""
    plain = batch(1)[0]
    cut = dict(plain, placement={"cut_drop_mm": 1.0}, derive={"threshold_um": 150})
    manifest = write_points(tmp_path / "pts", [cut, dict(cut, name="p2", placement={"cut_drop_mm": 0.0})])
    assert (manifest["placement_keys"], manifest["derive_keys"]) == (["cut_drop_mm"], ["threshold_um"])
    assert check_format("points", tmp_path / "pts") == []
    assert point_hash(with_groups(plain)) == point_hash(plain), "两组空着，哈希和第 1 版一样"
    assert point_hash(cut) != point_hash(plain) != point_hash(dict(cut, derive={})), "有值就算进哈希"
    assert point_hash(dict(cut, placement={"cut_drop_mm": 1.0})) == point_hash(cut)


@pytest.mark.parametrize("change,said", [
    (lambda rows: rows[1].update(placement={}), "放置没写全"),
    (lambda rows: rows[1].update(placement={"cut_drop_mm": None}), "放置没写全"),
    (lambda rows: rows[1].update(placement={"cut_drop_mm": 1.0, "tilt_deg": 2.0}), "放置多了"),
    (lambda rows: rows[0].update(derive=[150]), "推导量必须是一个 JSON 对象"),
])
def test_placement_and_derive_groups_written_wrong_are_named(change, said):
    rows = [dict(row, placement={"cut_drop_mm": 1.0}, derive={"threshold_um": 150}) for row in batch(2)]
    manifest = {"count": 2, "design_keys": ["length", "offset"], "condition_keys": ["bw", "load"],
                "placement_keys": ["cut_drop_mm"], "derive_keys": ["threshold_um"]}
    for row in rows:
        row["hash"] = point_hash(row)
    change(rows)
    problems = check_points("points", manifest, rows)
    assert problems and any(said in text for text in problems), problems


def test_a_first_version_batch_of_points_is_still_read(tmp_path):
    """第 1 版的一批点：清单没有两组的单子，行里没有两组。读成第 2 版，两组当成空的，哈希不变。"""
    write_points(tmp_path / "pts", batch())
    folder = tmp_path / "pts"
    manifest = read_manifest(folder)
    old = {k: v for k, v in manifest.items() if k not in ("placement_keys", "derive_keys")}
    write_manifest(folder, dict(old, format=1))
    rows = read_points(folder)
    (folder / POINTS_FILE).write_bytes(b"".join(canonical({k: v for k, v in row.items() if k not in ("placement", "derive")}) + b"\n"
                                                for row in rows))
    assert check_format("points", folder) == []


def test_write_then_read_is_unchanged(tmp_path):
    """写进去的行读出来不变；第 2 版写的时候给没写的放置、推导量两组补上空的。"""
    manifest = write_points(tmp_path / "pts", batch())
    rows = read_points(tmp_path / "pts")
    assert [{k: v for k, v in row.items() if k != "hash"} for row in rows] == [with_groups(row) for row in batch()]
    assert [row["hash"] for row in rows] == [point_hash(row) for row in batch()]
    assert manifest == read_manifest(tmp_path / "pts")
    assert (manifest["count"], manifest["design_keys"], manifest["condition_keys"]) == (3, ["length", "offset"], ["bw", "load"])
    assert (manifest["placement_keys"], manifest["derive_keys"]) == ([], [])
    assert check_format("points", tmp_path / "pts") == []

    write_points(tmp_path / "again", rows)
    assert read_points(tmp_path / "again") == rows
    assert hash_tree(tmp_path / "again") == hash_tree(tmp_path / "pts"), "再写一遍，字节也相同"
    assert b"\r" not in (tmp_path / "pts" / POINTS_FILE).read_bytes()


def test_incomplete_conditions_are_named(tmp_path):
    rows = batch()
    del rows[1]["conditions"]["bw"]
    rows[2]["conditions"]["load"] = None
    with pytest.raises(ValueError) as caught:
        write_points(tmp_path / "pts", rows)
    text = str(caught.value)
    assert "第 2 个点（'p2'）" in text and "['bw']" in text
    assert "第 3 个点（'p3'）" in text and "['load']" in text
    assert "p1" not in text
    assert not (tmp_path / "pts").exists(), "不符就什么都不写"


def test_fill_defaults_completes_without_overwriting_and_is_idempotent():
    rows = [{"name": "p1", "bone_id": "femur042", "design": {"length": 120}, "conditions": {"load": "stair"}, "reason": "手写"},
            {"name": "p2", "bone_id": "femur042", "design": {"length": 121}, "reason": "手写"}]
    before = copy.deepcopy(rows)
    defaults = {"load": "walk", "bw": 700}
    once = fill_defaults(rows, defaults)
    assert once[0]["conditions"] == {"load": "stair", "bw": 700}, "已经写了的不被改"
    assert once[1]["conditions"] == {"load": "walk", "bw": 700}
    assert fill_defaults(once, defaults) == once, "补两次和补一次结果相同"
    assert rows == before, "不改传进来的"
    assert all(row["hash"] == point_hash(row) for row in once)


def test_hand_written_file_can_be_read_completed_and_written(tmp_path):
    source = tmp_path / "hand.jsonl"
    source.write_bytes(b'\xef\xbb\xbf{"name": "p1", "bone_id": "femur042", "design": {"length": 120}, "reason": "\xe6\x89\x8b\xe5\x86\x99"}\r\n'
                       b'\r\n{"name": "p2", "bone_id": "femur042", "design": {"length": 121}, "conditions": {"load": "stair"}, "reason": "x"}\n')
    rows = read_points(source)
    assert [row["name"] for row in rows] == ["p1", "p2"], "带 BOM、CRLF、空行的手写文件读得进来"
    write_points(tmp_path / "pts", fill_defaults(rows, {"load": "walk"}))
    assert check_format("points", tmp_path / "pts") == []
    assert [row["conditions"]["load"] for row in read_points(tmp_path / "pts")] == ["walk", "stair"]


def test_unusual_line_separators_inside_strings_survive(tmp_path):
    rows = batch(1)
    rows[0]["reason"] = "第一行 第二行\x85第三行"
    write_points(tmp_path / "pts", rows)
    assert read_points(tmp_path / "pts")[0]["reason"] == rows[0]["reason"]


def test_bad_lines_are_named(tmp_path):
    source = tmp_path / "bad.jsonl"
    source.write_bytes(b'{"name": "p1"}\n{not json}\n')
    with pytest.raises(ValueError, match="第 2 行"):
        read_points(source)
    source.write_bytes(b'[1, 2]\n')
    with pytest.raises(ValueError, match="第 1 行"):
        read_points(source)


BAD_ROWS = [
    ("名字重复", lambda rows: rows[1].update(name="P1"), "重复"),
    ("名字不是 ASCII", lambda rows: rows[0].update(name="点一"), "名字"),
    ("骨标识不对", lambda rows: rows[0].update(bone_id=""), "骨标识"),
    ("设计多了一项", lambda rows: rows[2]["design"].update(extra=1), "多了"),
    ("设计少了一项", lambda rows: rows[2]["design"].pop("offset"), "缺"),
    ("没写理由", lambda rows: rows[0].update(reason=""), "理由"),
    ("多了一项", lambda rows: rows[0].update(surprise=1), "要带且只带"),
    ("哈希对不上", lambda rows: rows[0].update(hash="0" * 64), "哈希"),
    ("设计不是对象", lambda rows: rows[0].update(design=[1, 2]), "设计"),
    ("同一个点换个名字又来一次", lambda rows: rows[2].update(design=dict(rows[0]["design"]), hash=rows[0]["hash"]), "同一个点"),
]


@pytest.mark.parametrize("why,damage,word", BAD_ROWS, ids=[row[0] for row in BAD_ROWS])
def test_bad_points_are_named(tmp_path, why, damage, word):
    manifest = write_points(tmp_path / "pts", batch())
    rows = read_points(tmp_path / "pts")
    damage(rows)
    problems = check_points("points", manifest, rows)
    assert problems and any(word in text for text in problems), why


def test_count_and_key_lists_are_checked(tmp_path):
    manifest = write_points(tmp_path / "pts", batch())
    rows = read_points(tmp_path / "pts")
    assert check_points("points", manifest, rows) == []
    assert check_points("points", manifest, rows[:2])
    assert check_points("points", dict(manifest, condition_keys=["load", "bw"]), rows), "键的列表要排好序"
    assert check_points("points", {k: v for k, v in manifest.items() if k != "design_keys"}, rows)


def test_many_bad_points_do_not_flood(tmp_path):
    manifest = write_points(tmp_path / "pts", batch(60))
    rows = read_points(tmp_path / "pts")
    for row in rows:
        row["reason"] = ""
    assert len(check_points("points", manifest, rows)) <= 25


def test_empty_batch_is_refused(tmp_path):
    with pytest.raises(ValueError):
        write_points(tmp_path / "pts", [])


# ---- 候选池 ----

def pool(count=3):
    return [{"name": f"c{n:04d}", "bone_id": "femur042", "design": {"length": 100 + n},
             "feasible": n % 2 == 0, "info": {"clearance": 0.5 * n}} for n in range(1, count + 1)]


def test_pool_round_trip(tmp_path):
    manifest = write_points(tmp_path / "pool", pool(), kind="pool")
    assert "condition_keys" not in manifest and manifest["kind"] == "pool"
    assert read_points(tmp_path / "pool") == pool()
    assert check_format("pool", tmp_path / "pool") == []
    assert check_format("points", tmp_path / "pool"), "候选池不能当一批点用"


def test_bad_pool_rows_are_named(tmp_path):
    manifest = write_points(tmp_path / "pool", pool(), kind="pool")
    rows = read_points(tmp_path / "pool")
    rows[0]["feasible"] = "yes"
    assert any("feasible" in text for text in check_points("pool", manifest, rows))
    rows = read_points(tmp_path / "pool")
    rows[1]["conditions"] = {}
    assert check_points("pool", manifest, rows)
