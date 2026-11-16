"""登记：一样东西登记之后，编号、哈希、来路永远答得出，谁也改不了。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from stemlab.contract import Refused, chain, hashing, layout
from stemlab.contract.formats import points
from stemlab.contract.formats.manifest import read_manifest
from stemlab.registry import links, lock, lookup, reader, register, verify
from tests import helpers

CT = {"Series 1/IM 0001.dcm": b"slice one", "Series 1/IM 0002.dcm": b"slice two", "notes.txt": b"left femur\n"}


def bone_source(tmp_path, name="femur042-ct", bone_id="femur042", new_bone=True, **more):
    source = helpers.write_files(tmp_path / f"src-{name}", CT)
    item = register.register_external("bone_source", name, source=source, note="CT 原始数据", by="tester",
                                      bone_id=bone_id, new_bone=new_bone, **more)
    return source, item


def chain_bytes() -> bytes:
    path = layout.register_file()
    return path.read_bytes() if path.exists() else b""


def leftovers() -> list[str]:
    store = layout.store_root()
    return sorted(path.name for path in store.iterdir()) if store.exists() else []


# ---- 1 登记一个外来的文件夹（复制） ----

def test_copied_content_is_flushed_to_disk_before_its_line_goes_on_the_chain(data, tmp_path, monkeypatch):
    """复制进来的每个文件先刷到盘上，再写链上那一行：断电时，链上不会留下一条指向半截内容的记录（注释审查 高 2）。"""
    flushed = []
    real = register._flush

    def watching(path):
        flushed.append((path.name, chain_bytes()))
        real(path)

    monkeypatch.setattr(register, "_flush", watching)
    before = chain_bytes()
    _, item = bone_source(tmp_path)
    assert sorted(name for name, _ in flushed) == sorted([Path(rel).name for rel in CT] + ["manifest.json"]), "每个文件都刷过"
    assert all(chain == before for _, chain in flushed), "刷盘的时候链上还没有这一条"
    assert chain_bytes() != before and lookup.get(item["id"])["hash"] == item["hash"]


def test_register_a_folder_by_copy_records_every_field(data, tmp_path):
    source, item = bone_source(tmp_path)
    stored = data / "registry" / "store" / "C0001"
    assert item["id"] == "C0001" and item["kind"] == "bone_source" and item["name"] == "femur042-ct"
    assert item["version"] == 1 and item["storage"] == "copy" and item["content"] == "registry/store/C0001"
    assert item["origin"] == {"from": "external", "note": "CT 原始数据", "by": "tester"}
    assert item["bone_id"] == "femur042" and item["format"] == 1 and chain.is_time(item["time"])
    assert item["hash"] == hashing.hash_tree(stored)
    assert lookup.get("C0001") == item and lookup.content("C0001") == stored
    assert (stored / "Series 1" / "IM 0001.dcm").read_bytes() == b"slice one"
    manifest = read_manifest(stored)
    assert manifest["kind"] == "bone_source" and manifest["bone_id"] == "femur042", "没带清单的，复制时替它生成一份"
    assert sorted(manifest["files"]) == sorted(CT)
    assert not (source / "manifest.json").exists(), "不往原件里写东西"


def test_the_stored_copy_does_not_follow_the_original(data, tmp_path):
    source, item = bone_source(tmp_path)
    (source / "notes.txt").write_bytes(b"changed afterwards\n")
    (source / "Series 1" / "IM 0001.dcm").unlink()
    assert verify.verify_item("C0001") == item["hash"], "原件之后改了，存下的那一份不变"
    assert (lookup.content("C0001") / "notes.txt").read_bytes() == b"left femur\n"


def test_the_stored_copy_is_read_only(data, tmp_path):
    bone_source(tmp_path)
    target = lookup.content("C0001") / "notes.txt"
    assert not os.access(target, os.W_OK)
    with pytest.raises(PermissionError):
        target.write_bytes(b"overwrite")


def test_a_folder_that_already_has_a_manifest_is_copied_as_is(data, tmp_path):
    source = helpers.make_folder(tmp_path / "rep", summary={"max": 1.5})
    item = register.register_external("report", "hand-report", source=source, note="手写的报告", by="tester")
    assert item["id"] == "R0001" and item["hash"] == hashing.hash_tree(source) and item["bone_id"] is None


# ---- 2 只记位置的 ----

def test_a_ref_item_that_changed_is_caught_and_named(data, tmp_path):
    source = helpers.make_folder(tmp_path / "big", kind="bone_source", bone_id="femur042")
    item = register.register_external("bone_source", "femur042-ct", source=source, storage="ref",
                                      note="太大，只记位置", by="tester", bone_id="femur042", new_bone=True)
    assert item["storage"] == "ref" and Path(item["content"]) == source.resolve()
    assert verify.verify_item("C0001") == item["hash"] and verify.verify_refs() == []
    assert leftovers() == [], "只记位置的不往 data/ 里复制"

    (source / "summary.json").write_bytes(b'{"touched": true}\n')
    with pytest.raises(Refused) as caught:
        verify.verify_item("C0001")
    assert "C0001" in str(caught.value) and "femur042-ct" in str(caught.value) and "不一致" in str(caught.value)
    assert len(verify.verify_refs()) == 1 and "C0001" in verify.verify_refs()[0]


def test_a_ref_item_that_disappeared_is_caught(data, tmp_path):
    source = helpers.make_folder(tmp_path / "gone")
    register.register_external("report", "r", source=source, storage="ref", note="n", by="b")
    for path in sorted(source.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    source.rmdir()
    with pytest.raises(Refused, match="找不到"):
        verify.verify_item("R0001")


def test_a_ref_folder_without_a_manifest_is_refused_and_left_alone(data, tmp_path):
    source = helpers.write_files(tmp_path / "raw", CT)
    with pytest.raises(Refused, match="不替你往原处写清单"):
        register.register_external("bone_source", "x", source=source, storage="ref", note="n", by="b",
                                   bone_id="femur042", new_bone=True)
    assert sorted(p.name for p in source.iterdir()) == ["Series 1", "notes.txt"]


# ---- 3 同名再登记 ----

def test_registering_the_same_name_again_adds_a_version(data):
    first = helpers.setting("load-default", {"bw": 700})
    other = helpers.setting("something-else")
    second = helpers.setting("load-default", {"bw": 750})
    assert (first["id"], first["version"]) == ("R0001", 1)
    assert (second["id"], second["version"]) == ("R0003", 2), "版本加一，编号是新的"
    assert lookup.get("R0001") == first and lookup.content("R0001") == {"bw": 700}, "旧版本还在"
    assert lookup.find("setting", "load-default") == [first, second]
    assert lookup.latest("load-default") == second and lookup.latest("nothing") is None
    assert lookup.find(name="something-else") == [other]


def test_the_same_name_cannot_change_kind(data):
    helpers.setting("load-default")
    before = chain_bytes()
    with pytest.raises(Refused, match="同名不能换种类"):
        register.register_external("objective", "load-default", value={"minimize": "stress"}, note="n", by="b")
    with pytest.raises(Refused, match="只差大小写"):
        helpers.setting("Load-Default")
    assert chain_bytes() == before


# ---- 4 登记不上的 ----

def incomplete_points(tmp_path) -> Path:
    rows = [{"name": f"p{n}", "bone_id": "femur042", "design": {"length": 100 + n},
             "conditions": {"load": "walk", "bw": 700}, "reason": "手写"} for n in (1, 2)]
    folder = tmp_path / "pts"
    points.write_points(folder, rows)
    written = points.read_points(folder)
    del written[1]["conditions"]["bw"]
    (folder / points.POINTS_FILE).write_bytes(b"".join(hashing.canonical(row) + b"\n" for row in written))
    return folder


REFUSALS = [
    ("清单外的种类", lambda tmp: dict(kind="notes", name="x", value={}), "十六种"),
    ("来路的形状不对：没写是什么", lambda tmp: dict(kind="setting", name="x", value={}, note=""), "note"),
    ("来路的形状不对：没写是谁", lambda tmp: dict(kind="setting", name="x", value={}, by=" "), "by"),
    ("没给骨标识的 case", lambda tmp: dict(kind="bone_source", name="x", source=helpers.write_files(tmp / "s", CT)), "骨标识"),
    ("条件没写全的一批点", lambda tmp: dict(kind="points", name="x", source=incomplete_points(tmp)), "没写全"),
    ("值给了文件夹的种类", lambda tmp: dict(kind="report", name="x", value={"a": 1}), "找不到要登记的文件夹"),
    ("文件夹的种类存成值", lambda tmp: dict(kind="report", name="x", value={}, storage="value"), "不能存成"),
    ("值不是对象", lambda tmp: dict(kind="setting", name="x", value=[1, 2]), "JSON 对象"),
    ("值里有 NaN", lambda tmp: dict(kind="setting", name="x", value={"a": float("nan")}), "写不进 JSON"),
    ("名字带空格", lambda tmp: dict(kind="setting", name="load default", value={}), "名字"),
    ("名字是中文", lambda tmp: dict(kind="setting", name="载荷默认", value={}), "名字"),
    ("文件夹不存在", lambda tmp: dict(kind="report", name="x", source=tmp / "nothing"), "找不到"),
    ("文件名不是 ASCII", lambda tmp: dict(kind="report", name="x", source=helpers.write_files(tmp / "s", {"结果.txt": b"x"})), "ASCII"),
    ("没见过的骨标识没说是新骨", lambda tmp: dict(kind="setting", name="x", value={}, bone_id="femur999"), "新骨"),
    ("说是新骨却没给标识", lambda tmp: dict(kind="setting", name="x", value={}, new_bone=True), "新骨"),
    ("数据的文件夹里没有各行", lambda tmp: dict(kind="data", name="x", source=helpers.make_folder(tmp / "s", kind="data")), "rows.jsonl"),
]


@pytest.mark.parametrize("why,make,word", REFUSALS, ids=[row[0] for row in REFUSALS])
def test_what_cannot_be_registered_leaves_nothing_behind(data, tmp_path, why, make, word):
    helpers.setting("already-there")
    before = chain_bytes()
    arguments = {"note": "说明", "by": "tester", **make(tmp_path)}
    with pytest.raises(Refused) as caught:
        register.register_external(arguments.pop("kind"), arguments.pop("name"), **arguments)
    assert word in str(caught.value), f"{why}：{caught.value}"
    assert chain_bytes() == before, "被拒的时候链上不多一条"
    assert leftovers() == [], "也不留下复制到一半的文件夹"


def test_bone_ids_guard_against_typos(data, tmp_path):
    bone_source(tmp_path)
    with pytest.raises(Refused, match="不是新骨"):
        bone_source(tmp_path, name="another-ct", new_bone=True)
    with pytest.raises(Refused, match="只差大小写"):
        bone_source(tmp_path, name="another-ct", bone_id="Femur042", new_bone=True)
    with pytest.raises(Refused, match="没见过"):
        bone_source(tmp_path, name="another-ct", bone_id="femur043", new_bone=False)
    _, second = bone_source(tmp_path, name="femur042-ct", new_bone=False)
    assert (second["id"], second["version"], second["bone_id"]) == ("C0002", 2, "femur042"), "同一根骨的版本共用骨标识"
    assert leftovers() == ["C0001", "C0002"]
    assert lookup.bones() == ["femur042"] and [item["id"] for item in lookup.bone("femur042")] == ["C0001", "C0002"]
    assert [item["id"] for item in lookup.cases()] == ["C0001", "C0002"]


def test_the_manifest_bone_id_must_agree_with_the_one_given(data, tmp_path):
    source = helpers.make_folder(tmp_path / "s", kind="bone_source", bone_id="femur042")
    with pytest.raises(Refused, match="清单里的骨标识"):
        register.register_external("bone_source", "x", source=source, note="n", by="b", bone_id="femur043", new_bone=True)
    item = register.register_external("bone_source", "x", source=source, note="n", by="b", new_bone=True)
    assert item["bone_id"] == "femur042", "没另给的话，用清单里的"


# ---- 5 手改或手删一条 ----

def tamper(position: int, change) -> None:
    path = layout.register_file()
    lines = path.read_bytes().split(b"\n")[:-1]
    changed = change(lines, position - 1)
    path.write_bytes(b"".join(line + b"\n" for line in changed))


@pytest.mark.parametrize("position", [1, 3, 5])
def test_a_hand_edited_entry_is_pointed_out(data, position):
    for n in range(5):
        helpers.setting(f"s{n}", {"n": n})
    assert verify.verify_register() == []
    tamper(position, lambda lines, i: lines[:i] + [lines[i].replace(b'"by":"tester"', b'"by":"nobody"')] + lines[i + 1:])
    problems = verify.verify_register()
    assert len(problems) == 1 and f"第 {position} 条" in problems[0] and "被改过" in problems[0]


@pytest.mark.parametrize("position", [1, 3])
def test_a_hand_deleted_entry_is_pointed_out(data, position):
    for n in range(5):
        helpers.setting(f"s{n}", {"n": n})
    tamper(position, lambda lines, i: lines[:i] + lines[i + 1:])
    problems = verify.verify_register()
    assert len(problems) == 1 and f"第 {position} 条" in problems[0] and "接不上" in problems[0]


def test_an_entry_that_was_rehashed_by_hand_still_has_to_be_a_valid_item(data):
    helpers.setting("s0")
    entry = json.loads(layout.register_file().read_bytes())
    forged = chain.link({k: v for k, v in entry.items() if k not in chain.RESERVED} | {"kind": "notes"}, chain.GENESIS)
    layout.register_file().write_bytes(chain.dumps(forged))
    problems = verify.verify_register()
    assert problems and "第 1 条" in problems[0] and "十六种" in problems[0]


# ---- 6 四个进程同时登记 ----

def test_four_processes_registering_at_once(data):
    helpers.release([helpers.spawn_worker("register", f"w{n}", "25") for n in range(4)])
    items = reader.items()
    assert len(items) == 100
    assert [item["id"] for item in items] == [f"R{n:04d}" for n in range(1, 101)], "编号不重复，一个不少"
    assert sorted(item["name"] for item in items) == sorted(f"w{w}-{n}" for w in range(4) for n in range(25))
    assert verify.verify_register() == [], "链接得上"
    assert len({item["origin"]["by"] for item in items[:40]}) > 1, "四个进程确实是交错着写的"


# ---- 7 末尾留着半行 ----

def test_a_half_written_tail_is_ignored_then_cut_off(data):
    first = helpers.setting("s0")
    whole = chain_bytes()
    with open(layout.register_file(), "ab") as stream:
        stream.write(b'{"bone_id":null,"content":{"sca')
    assert reader.items() == [first], "读不崩"
    assert reader.head() == chain.Head(1, first["this"])
    assert verify.verify_register() == []
    assert lookup.get("R0001") == first

    second = helpers.setting("s1")
    assert second["id"] == "R0002" and second["prev"] == first["this"]
    assert chain_bytes() == whole + chain.dumps(second), "下一次追加前半行被截掉"
    assert verify.verify_register() == []


# ---- 查 ----

def test_lookups(data, tmp_path):
    _, source_item = bone_source(tmp_path)
    value = helpers.setting("s0", {"a": [1, 2]})
    assert lookup.content("R0002") == {"a": [1, 2]}
    lookup.content("R0002")["a"].append(3)
    assert lookup.content("R0002") == {"a": [1, 2]}, "拿到的值改了也不影响登记的那一份"
    for missing in ("R0001", "C0002", "R0009", "E0001", "nothing", None):
        with pytest.raises(LookupError):
            lookup.get(missing)
    assert lookup.find("bone_source") == [source_item] and lookup.find("setting") == [value]
    assert lookup.by_origin("E0001") == []


# ---- 手动挂接 ----

def test_attach_and_detach(data, tmp_path):
    bone_source(tmp_path)
    helpers.setting("s0")
    helpers.setting("s1")
    links.attach("R0002", "C0001")
    links.attach("R0003", "C0001")
    assert lookup.attached("C0001") == ["R0002", "R0003"]
    links.detach("R0002", "C0001")
    assert lookup.attached("C0001") == ["R0003"]
    links.attach("R0002", "C0001")
    assert lookup.attached("C0001") == ["R0003", "R0002"]
    assert len(reader.links()) == 4 and verify.verify_links() == [], "挂和摘都只是往后追加"
    assert lookup.get("R0002")["origin"]["from"] == "external", "挂接不是来路"

    before = layout.links_file().read_bytes()
    for op, item, case, word in [(links.attach, "R0002", "C0001", "已经挂"), (links.detach, "R0009", "C0001", "没有"),
                                 (links.attach, "R0002", "R0003", "不是一个 case"), (links.detach, "C0001", "C0001", "没有挂")]:
        with pytest.raises(Refused, match=word):
            op(item, case)
    assert layout.links_file().read_bytes() == before


# ---- 产物的登记（只许发布叫，这里直接试它收什么、拒什么） ----

def test_register_output_takes_the_hash_it_is_given(data, tmp_path):
    bone_source(tmp_path)
    place = helpers.make_folder(layout.output_dir("E0001", 1, "report"))
    origin = {"from": "product", "experiment": "E0001", "round": 1, "output": "report"}
    item = register.register_output("report", "E0001.report", layout.inside(place), "a" * 64, origin, "femur042")
    assert item["hash"] == "a" * 64, "只收发布算好的哈希，这里不再算"
    assert (item["id"], item["storage"], item["content"]) == ("R0002", "copy", "experiments/E0001/rounds/1/outputs/report")
    assert lookup.by_origin("E0001", 1) == [item] and lookup.by_origin("E0001", 2) == [] and lookup.by_origin("E0001") == [item]
    assert lookup.content("R0002") == place
    with pytest.raises(Refused, match="没见过"):
        register.register_output("report", "E0001.report", layout.inside(place), "a" * 64, origin, "femur999")
    with pytest.raises(Refused):
        register.register_output("report", "E0001.report", layout.inside(place), "a" * 64, {"from": "product"}, None)


# ---- 登记到一半断掉留下的东西 ----

def set_aside() -> dict:
    """store/ 里被挪到一边的东西：名字 -> 里面的文件。"""
    return {path.name: sorted(p.name for p in path.iterdir()) for path in layout.store_root().iterdir()
            if path.name.startswith(".orphan-")}


def test_content_left_under_an_unused_id_is_set_aside_never_deleted(data, tmp_path):
    """这个编号名下已经有内容：是上次登记到一半留下的，也可能是链丢了尾巴之后剩下的。挪到一边，不删。"""
    helpers.setting("s0")
    helpers.write_files(layout.store_dir("R0002"), {"stale.txt": b"left by a crash, or the only copy left"})
    source = helpers.make_folder(tmp_path / "rep")
    item = register.register_external("report", "r", source=source, note="n", by="b")
    assert item["id"] == "R0002" and verify.verify_item("R0002") == item["hash"], "这个编号照常发出去"
    aside = set_aside()
    assert len(aside) == 1 and list(aside.values()) == [["stale.txt"]], "原来在那里的内容还在"
    assert next(iter(aside)).startswith(".orphan-R0002-")

    helpers.write_files(layout.store_dir("C0003"), {"ct.dcm": b"content of a lost case"})
    helpers.write_files(layout.store_dir("R0004"), {"x.txt": b"x"})
    helpers.setting("a-value")                                              # 第 3 条是一个值，不往 store/ 里放东西
    place = helpers.make_folder(layout.output_dir("E0001", 1, "report"))
    register.register_output("report", "E0001.report", layout.inside(place), "a" * 64,
                             {"from": "product", "experiment": "E0001", "round": 1, "output": "report"}, None)
    assert sorted(name[:14] for name in set_aside()) == [".orphan-C0003-", ".orphan-R0002-", ".orphan-R0004-"], \
        "不管新登记的是什么、编号是 C 还是 R 开头，那个序号名下的内容都先挪开"


def test_a_copy_that_fails_halfway_is_refused_and_cleaned_up(data, tmp_path, monkeypatch):
    import shutil

    source = helpers.make_folder(tmp_path / "rep")

    def half(src, dst, **how):
        helpers.write_files(dst, {"half.txt": b"copied before the failure"})
        raise shutil.Error([(str(src), str(dst), "another process has this file open")])

    monkeypatch.setattr(shutil, "copytree", half)
    with pytest.raises(Refused, match="复制.*出错"):
        register.register_external("report", "r", source=source, note="n", by="b")
    assert leftovers() == [] and chain_bytes() == b"", "复制到一半的那份删掉了，链上什么都没有"


def make_junction(link, target) -> None:
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_folder_with_a_link_or_junction_cannot_be_registered(data, tmp_path):
    """内容必须全在文件夹自己里面。带链接或交接点的，登记不上，外面那个文件夹一个字节不动。"""
    shared = helpers.write_files(tmp_path / "shared", {"big.bin": b"lives somewhere else"})
    source = helpers.make_folder(tmp_path / "rep")
    make_junction(source / "linked", shared)
    with pytest.raises(ValueError, match="链接或交接点"):
        hashing.hash_tree(source)
    for storage in ("copy", "ref"):
        with pytest.raises(Refused, match="链接或交接点"):
            register.register_external("report", "r", source=source, storage=storage, note="n", by="b")
    assert leftovers() == [] and chain_bytes() == b""
    assert os.access(shared / "big.bin", os.W_OK) and (shared / "big.bin").read_bytes() == b"lives somewhere else"


# ---- 锁 ----

def wait_until_held(worker) -> None:
    assert worker.stdout.readline().strip() == b"held"


def test_the_lock_is_exclusive_and_dies_with_its_process(data):
    worker = helpers.spawn_worker("hold", "register")
    try:
        wait_until_held(worker)
        started = time.monotonic()
        with pytest.raises(Refused, match="拿不到锁"):
            with lock.writing(timeout=0.3):
                pass
        assert 0.25 < time.monotonic() - started < 3
        with pytest.raises(Refused):
            with lock.writing(timeout=0):   # 只试一次
                pass
    finally:
        helpers.kill_tree(worker)
    with lock.writing(timeout=5):
        pass                                # 持锁的进程死了，锁自动释放
    assert helpers.setting("after")["id"] == "R0001"


def test_a_held_lock_does_not_block_readers(data):
    """锁的是单独的 .lock 文件，链文件别的进程照样能读；锁文件自己的开头也读得了。"""
    first = helpers.setting("s0")
    worker = helpers.spawn_worker("hold", "register")
    try:
        wait_until_held(worker)
        assert reader.items() == [first]
        assert layout.register_file().read_bytes().endswith(b"\n")
        assert layout.register_lock().read_bytes() == b""
        assert verify.verify_register() == []
    finally:
        helpers.kill_tree(worker)
