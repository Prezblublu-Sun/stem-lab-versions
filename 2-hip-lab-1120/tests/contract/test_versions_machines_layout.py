"""格式版本、机器清单、data/ 的布局。"""
from __future__ import annotations

from pathlib import Path

import pytest

from stemlab.contract import layout, versions
from stemlab.contract.machines import check_machines, parse_machines
from stemlab.contract.versions import CannotUpcast, NewerFormat, upcast

# ---------------------------------------------------------------- 版本

def test_every_format_has_a_version():
    assert versions.CONTRACT == 1
    assert set(versions.FORMATS) == {"register", "links", "issued", "record", "manifest", "points", "bone_model",
                                     "data", "package", "stem_model", "setting", "machines", "backup"}
    assert all(isinstance(v, int) and v >= 1 for v in versions.FORMATS.values())


def test_current_version_is_returned_as_is():
    entry = {"format": 1, "entry": "noted"}
    assert upcast("record", entry) is entry


def test_a_newer_version_is_said_out_loud():
    with pytest.raises(NewerFormat, match="第 2 版"):
        upcast("record", {"format": 2})


@pytest.mark.parametrize("bad", [{}, {"format": "1"}, {"format": 0}, {"format": True}, {"format": 1.0}, None])
def test_missing_or_odd_version_cannot_be_upcast(bad):
    with pytest.raises(CannotUpcast):
        upcast("record", bad)


def test_old_versions_are_converted_step_by_step(monkeypatch):
    monkeypatch.setitem(versions.FORMATS, "record", 3)
    monkeypatch.setitem(versions.UPCASTS, ("record", 1), lambda old: {**old, "format": 2, "a": 1})
    with pytest.raises(CannotUpcast, match="没有写怎么转"):
        upcast("record", {"format": 1})
    monkeypatch.setitem(versions.UPCASTS, ("record", 2), lambda old: {**old, "format": 3, "b": 2})
    assert upcast("record", {"format": 1}) == {"format": 3, "a": 1, "b": 2}
    assert upcast("record", {"format": 2}) == {"format": 3, "b": 2}
    monkeypatch.setitem(versions.UPCASTS, ("record", 2), lambda old: dict(old))
    with pytest.raises(CannotUpcast):
        upcast("record", {"format": 2})


# ---------------------------------------------------------------- 机器清单

MACHINES = {
    "format": 1,
    "machines": [
        {"name": "win", "role": "desk", "host": "WIN-BOX", "slots": 4},
        {"name": "linux", "role": "worker", "host": "linuxbox",
         "connect": {"ssh": "user@10.0.0.2", "port": 2222, "options": ["-o", "BatchMode=yes"]},
         "job_root": "/home/user/stemlab-jobs", "backup_root": "/home/user/stemlab-backup"},
    ],
}


def without(doc, index, key):
    rows = [dict(row) for row in doc["machines"]]
    del rows[index][key]
    return dict(doc, machines=rows)


def with_row(doc, index, **change):
    rows = [dict(row) for row in doc["machines"]]
    rows[index].update(change)
    return dict(doc, machines=rows)


def test_a_good_list_passes_and_parses():
    assert check_machines(MACHINES) == []
    desk, worker = parse_machines(MACHINES)
    assert (desk.name, desk.role, desk.slots, desk.ssh, desk.job_root) == ("win", "desk", 4, None, None)
    assert (worker.ssh, worker.port, worker.options) == ("user@10.0.0.2", 2222, ("-o", "BatchMode=yes"))
    assert (worker.job_root, worker.backup_root, worker.slots) == ("/home/user/stemlab-jobs", "/home/user/stemlab-backup", 0)
    assert worker.bin is None and desk.bin is None and worker.python == "python3"
    with_python = with_row(MACHINES, 1, python="/home/user/env/bin/python")
    assert check_machines(with_python) == [] and parse_machines(with_python)[1].python == "/home/user/env/bin/python"
    with_bin = with_row(MACHINES, 1, connect={"ssh": "user@10.0.0.2", "bin": "C:/Windows/System32/OpenSSH"})
    assert check_machines(with_bin) == []
    assert parse_machines(with_bin)[1].bin == "C:/Windows/System32/OpenSSH"


def test_desk_alone_is_enough():
    assert check_machines({"format": 1, "machines": [MACHINES["machines"][0]]}) == []


ABAQUS = {"name": "abaqus", "version": "2025", "path": "D:/SIMULIA/Commands/abq2025.bat"}


def test_a_machine_says_where_its_programs_are():
    """装在哪是机器的事：包只写要哪个程序哪一版，位置照名字和版本在这台机器的清单里找。同一个程序可以装几个版本。"""
    older = {"name": "abaqus", "version": "2024", "path": "D:\\SIMULIA\\Commands\\abq2024.bat"}
    solver = {"name": "calculix", "version": "2.21", "path": "/usr/local/bin/ccx_2.21"}
    doc = with_row(with_row(MACHINES, 0, programs=[ABAQUS, older]), 1, programs=[solver])
    assert check_machines(doc) == []
    desk, worker = parse_machines(doc)
    assert desk.program("abaqus", "2025") == ABAQUS["path"] and desk.program("abaqus", "2024") == older["path"]
    assert desk.program("abaqus", "2023") is None and desk.program("calculix", "2.21") is None
    assert worker.program("calculix", "2.21") == "/usr/local/bin/ccx_2.21"
    assert parse_machines(MACHINES)[0].programs == () and parse_machines(MACHINES)[0].program("abaqus", "2025") is None, \
        "不写 programs 的清单照样合格：这台机器没有登记的外部程序"
    assert check_machines(with_row(MACHINES, 0, programs=[])) == []


BAD_MACHINES = [
    ("不是对象", []),
    ("没有 machines", {"format": 1}),
    ("版本不对", dict(MACHINES, format=2)),
    ("多了一项", dict(MACHINES, note="x")),
    ("没有 desk", dict(MACHINES, machines=[MACHINES["machines"][1]])),
    ("两台 desk", dict(MACHINES, machines=[MACHINES["machines"][0], dict(MACHINES["machines"][0], name="win2")])),
    ("重名", with_row(MACHINES, 1, name="win")),
    ("名字不合规矩", with_row(MACHINES, 0, name="Win Box")),
    ("角色", with_row(MACHINES, 1, role="gpu")),
    ("没写 host", without(MACHINES, 0, "host")),
    ("槽数是负的", with_row(MACHINES, 0, slots=-1)),
    ("worker 没写怎么连", without(MACHINES, 1, "connect")),
    ("worker 没写作业根目录", without(MACHINES, 1, "job_root")),
    ("端口不对", with_row(MACHINES, 1, connect={"ssh": "user@host", "port": 0})),
    ("选项不是列表", with_row(MACHINES, 1, connect={"ssh": "user@host", "options": "-v"})),
    ("bin 不是位置", with_row(MACHINES, 1, connect={"ssh": "user@host", "bin": ""})),
    ("解释器的位置里用了 ~", with_row(MACHINES, 1, python="~/env/bin/python")),
    ("作业根目录里用了 ~", with_row(MACHINES, 1, job_root="~/stemlab-jobs")),
    ("作业根目录不是完整的位置", with_row(MACHINES, 1, job_root="stemlab-jobs")),
    ("备份的位置里有空格", with_row(MACHINES, 1, backup_root="/home/user/stem lab")),
    ("位置里有分号", with_row(MACHINES, 1, job_root="/home/user/jobs;rm")),
    ("connect 多了一项", with_row(MACHINES, 1, connect={"ssh": "user@host", "password": "x"})),
    ("desk 写了 connect", with_row(MACHINES, 0, connect={"ssh": "user@host"})),
    ("机器多了一项", with_row(MACHINES, 0, gpu="RTX")),
    ("programs 不是列表", with_row(MACHINES, 0, programs={"abaqus": "D:/SIMULIA/Commands/abq2025.bat"})),
    ("程序少写了位置", with_row(MACHINES, 0, programs=[{"name": "abaqus", "version": "2025"}])),
    ("程序多写了一项", with_row(MACHINES, 0, programs=[dict(ABAQUS, licence="27000@server")])),
    ("程序的名字不合规矩", with_row(MACHINES, 0, programs=[dict(ABAQUS, name="Abaqus Standard")])),
    ("程序的版本是空的", with_row(MACHINES, 0, programs=[dict(ABAQUS, version=" ")])),
    ("程序的位置不是完整的路径", with_row(MACHINES, 0, programs=[dict(ABAQUS, path="abq2025.bat")])),
    ("程序的位置里有 &", with_row(MACHINES, 0, programs=[dict(ABAQUS, path="D:/SIMULIA/abq2025.bat & del x")])),
    ("同一个程序同一版写了两遍", with_row(MACHINES, 0, programs=[ABAQUS, dict(ABAQUS, path="E:/abq2025.bat")])),
]


@pytest.mark.parametrize("why,doc", BAD_MACHINES, ids=[row[0] for row in BAD_MACHINES])
def test_bad_lists_are_named(why, doc):
    assert check_machines(doc), why
    with pytest.raises(ValueError):
        parse_machines(doc)


# ---------------------------------------------------------------- 布局

@pytest.fixture
def roots(monkeypatch, tmp_path):
    monkeypatch.setenv("STEMLAB_REPO", str(tmp_path / "repo"))
    monkeypatch.setenv("STEMLAB_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("STEMLAB_PLUGINS", raising=False)
    return tmp_path


def test_defaults_follow_the_repo(monkeypatch, tmp_path):
    for name in ("STEMLAB_REPO", "STEMLAB_DATA", "STEMLAB_PLUGINS"):
        monkeypatch.delenv(name, raising=False)
    assert layout.repo_root() == Path(versions.__file__).resolve().parents[2]
    assert layout.data_root() == layout.repo_root() / "data"
    assert layout.plugins_package() == "plugins"
    monkeypatch.setenv("STEMLAB_REPO", str(tmp_path))
    assert layout.data_root() == tmp_path / "data"
    monkeypatch.setenv("STEMLAB_PLUGINS", "tests.plugins")
    assert layout.plugins_package() == "tests.plugins"


def test_the_layout_is_the_blueprint_tree(roots):
    data = roots / "data"
    assert layout.register_file() == data / "registry" / "register.jsonl"
    assert layout.register_lock() == data / "registry" / "register.lock"
    assert layout.links_file() == data / "registry" / "links.jsonl"
    assert layout.store_dir("C0001") == data / "registry" / "store" / "C0001"
    assert layout.issued_file() == data / "experiments" / "issued.jsonl"
    assert layout.issued_lock() == data / "experiments" / "issued.lock"
    exp = data / "experiments" / "E0001"
    assert layout.record_file("E0001") == exp / "record.jsonl"
    assert layout.record_lock("E0001") == exp / "record.lock"
    assert layout.busy_lock("E0001") == exp / "busy.lock"
    assert layout.work_dir("E0001") == exp / "work"
    assert layout.output_dir("E0001", 1, "data") == exp / "rounds" / "1" / "outputs" / "data"
    assert layout.plugin_diff("E0001", 2) == exp / "rounds" / "2" / "plugin.diff"
    assert layout.plugin_diff("E0001", 2, changed_to="ab" * 32) == exp / "rounds" / "2" / "plugin-abababababab.diff"
    assert layout.watch_lock() == data / "watch.lock"
    assert layout.backup_file() == data / "backup.json"
    assert layout.store_root() == data / "registry" / "store"
    assert layout.lock_file() == roots / "repo" / "uv.lock"


def test_the_cache_is_per_machine_and_outside_data(roots, monkeypatch):
    monkeypatch.delenv("STEMLAB_CACHE", raising=False)
    assert layout.cache_root() == roots / "repo" / ".cache"
    assert layout.data_root() not in layout.cache_root().parents, "缓存不是账的一部分，不能跟着 data/ 备份到别的机器上"
    monkeypatch.setenv("STEMLAB_CACHE", str(roots / "elsewhere"))
    assert layout.cache_root() == roots / "elsewhere"


def test_ids():
    assert layout.item_id(1, case=True) == "C0001" and layout.item_id(27, case=False) == "R0027"
    assert layout.item_id(12345, case=False) == "R12345", "超过四位照样往上走"
    assert layout.experiment_id(7) == "E0007"
    assert layout.id_seq("C0001") == 1 and layout.id_seq("E0123") == 123
    assert layout.is_item_id("R0001") and not layout.is_item_id("E0001") and not layout.is_item_id("R1")
    assert layout.is_experiment_id("E0001") and not layout.is_experiment_id("e0001") and not layout.is_experiment_id(1)
    with pytest.raises(ValueError):
        layout.id_seq("X0001")


@pytest.mark.parametrize("bad", ["../E0001", "E0001/..", "E1", "", "E0001\\x", None])
def test_paths_cannot_be_steered_out_of_data(roots, bad):
    with pytest.raises(ValueError):
        layout.experiment_dir(bad)
    with pytest.raises(ValueError):
        layout.store_dir(bad)
    with pytest.raises(ValueError):
        layout.output_dir("E0001", 1, bad)
    with pytest.raises(ValueError):
        layout.round_dir("E0001", bad)


def test_round_numbers_start_at_one(roots):
    for bad in (0, -1, True, "1", 1.0):
        with pytest.raises(ValueError):
            layout.round_dir("E0001", bad)


def test_positions_inside_data_are_relative_with_forward_slashes(roots):
    place = layout.output_dir("E0001", 2, "data")
    assert layout.inside(place) == "experiments/E0001/rounds/2/outputs/data"
    assert layout.locate(layout.inside(place)) == place
    with pytest.raises(ValueError):
        layout.inside(roots / "elsewhere")
    for bad in ("/abs", "C:/abs", "a/../../b", "..", 5):
        with pytest.raises(ValueError):
            layout.locate(bad)


def test_name_rules():
    assert layout.is_key("data") and layout.is_key("bone_model") and layout.is_key("a1")
    assert not any(map(layout.is_key, ["Data", "1a", "a-b", "", "数据", None, "a" * 41]))
    assert layout.is_label("femur042") and layout.is_label("E0007.data") and layout.is_label("p-001_a")
    assert not any(map(layout.is_label, ["", ".hidden", "a b", "骨", "-x", None, "a" * 81]))
    assert layout.is_type_name("fea.run") and layout.is_type_name("surrogate.train")
    assert not any(map(layout.is_type_name, ["fea", "fea.", ".run", "Fea.Run", "a.b.c", None]))
