"""每种格式有好样本和坏样本，坏的被点名哪里不符。"""
from __future__ import annotations

import json

import pytest

from stemlab.contract.formats.manifest import (MANIFEST, MAX_PATH, check_format, check_manifest, check_name,
                                               check_names, make_manifest, read_manifest, write_manifest)
from stemlab.contract.formats.package import DECLARED, MODES, NEW_KINDS
from stemlab.contract.kinds import ITEM_KINDS
from stemlab.contract.versions import NewerFormat


def make_folder(root, kind="report", files=None, **extra):
    files = {"summary.json": b"{}\n", "plots/a.png": b"\x89PNG"} if files is None else files
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_manifest(root, make_manifest(kind, list(files), **extra))
    return root


# ---- 落盘的名字 ----

@pytest.mark.parametrize("name", [
    "a.txt", "sub/b.bin", "code/__init__.py", "Series 1/IM 0001.dcm", "a-b_c.d", "x" * MAX_PATH, "plots/A (2).png"])
def test_good_names(name):
    assert check_name(name) is None


@pytest.mark.parametrize("name", [
    "", None, 5, "中文.txt", "a\\b.txt", "/abs.txt", "C:/abs.txt", "a//b", "../up", "a/./b", "a/..", "tail./x",
    "trailing /x", " leading/x", "a/b.", "what?.txt", "star*.txt", 'quote".txt', "pipe|x", "a<b", "tab\tx",
    "con", "NUL.txt", "sub/Com1.log", "lpt9", "x" * (MAX_PATH + 1)])
def test_bad_names(name):
    assert isinstance(check_name(name), str)


def test_duplicates_ignore_case():
    assert check_names(["a.txt", "b/A.txt"]) == []
    assert any("重复" in text for text in check_names(["a.txt", "A.TXT"]))
    assert any("重复" in text for text in check_names(["a.txt", "a.txt"]))


# ---- 共用的清单 ----

GENERIC = [name for name, kind in ITEM_KINDS.items() if kind.format == "manifest"]


def test_which_kinds_use_which_format():
    assert sorted(GENERIC) == ["archive", "bone_source", "edits", "report"]
    assert {kind.format for kind in ITEM_KINDS.values()} == {"manifest", "points", "bone_model", "data", "package", "value"}


@pytest.mark.parametrize("kind", GENERIC)
def test_good_folders_pass(tmp_path, kind):
    assert check_format(kind, make_folder(tmp_path / "f", kind=kind)) == []


def test_manifest_is_written_as_fixed_bytes(tmp_path):
    root = make_folder(tmp_path / "f", bone_id="femur042", summary={"值": 1.0})
    raw = (root / MANIFEST).read_bytes()
    assert raw == ('{"bone_id":"femur042","files":["plots/a.png","summary.json"],"format":1,"kind":"report",'
                   '"summary":{"值":1}}\n').encode("utf-8")
    assert read_manifest(root) == json.loads(raw)


def test_empty_folder_with_a_manifest_is_fine(tmp_path):
    assert check_format("report", make_folder(tmp_path / "f", files={})) == []


BAD_FOLDERS = [
    ("没有清单", lambda root: (root / MANIFEST).unlink(), "没有"),
    ("清单不是 JSON", lambda root: (root / MANIFEST).write_bytes(b"{half"), "读不出来"),
    ("清单不是对象", lambda root: (root / MANIFEST).write_bytes(b"[1]"), "JSON 对象"),
    ("清单缺 files", lambda root: write_manifest(root, {"format": 1, "kind": "report"}), "缺 files"),
    ("清单没写版本", lambda root: write_manifest(root, {"kind": "report", "files": []}), "格式版本"),
    ("种类不符", lambda root: write_manifest(root, dict(read_manifest(root), kind="edits")), "种类"),
    ("键不是 ASCII", lambda root: write_manifest(root, dict(read_manifest(root), 说明="x")), "键"),
    ("列了自己", lambda root: write_manifest(root, dict(read_manifest(root), files=["manifest.json", "plots/a.png", "summary.json"])), "自己"),
    ("files 不是列表", lambda root: write_manifest(root, dict(read_manifest(root), files="summary.json")), "列表"),
    ("骨标识不对", lambda root: write_manifest(root, dict(read_manifest(root), bone_id="骨 1")), "骨标识"),
    ("列了但没有", lambda root: (root / "summary.json").unlink(), "清单列了但文件夹里没有：summary.json"),
    ("有但没列", lambda root: (root / "extra.txt").write_bytes(b"x"), "文件夹里有但清单没列：extra.txt"),
    ("名字不合规矩", lambda root: write_manifest(root, dict(read_manifest(root), files=["plots/a.png", "summary.json", "a?.txt"])), "ASCII"),
]


@pytest.mark.parametrize("why,damage,word", BAD_FOLDERS, ids=[row[0] for row in BAD_FOLDERS])
def test_bad_folders_are_named(tmp_path, why, damage, word):
    root = make_folder(tmp_path / "f")
    damage(root)
    problems = check_format("report", root)
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_not_a_folder_and_not_a_folder_kind(tmp_path):
    assert any("不是文件夹" in text for text in check_format("report", tmp_path / "nothing"))
    assert any("是一个值" in text for text in check_format("setting", tmp_path))
    assert any("没有" in text for text in check_format("nothing", tmp_path))


def test_a_newer_format_is_said_out_loud_not_treated_as_bad_data(tmp_path):
    root = make_folder(tmp_path / "f")
    write_manifest(root, dict(read_manifest(root), format=2))
    with pytest.raises(NewerFormat, match="第 2 版"):
        check_format("report", root)


def test_check_manifest_alone():
    good = make_manifest("report", ["b.txt", "a.txt"])
    assert good == {"format": 1, "kind": "report", "files": ["a.txt", "b.txt"]}
    assert check_manifest("report", good) == []
    assert check_manifest("report", dict(good, format=3))


# ---- 各有各的格式的种类：只带共用的那几项是不够的（它们自己的测试在 test_data.py、test_bone_model.py）----

@pytest.mark.parametrize("kind", [name for name, kind in ITEM_KINDS.items() if kind.format in ("bone_model", "data")])
def test_kinds_with_their_own_format_need_more_than_the_shared_manifest(tmp_path, kind):
    assert check_format(kind, make_folder(tmp_path / "f", kind=kind))


# ---- 带代码的包 ----

PACKAGE_FILES = {"code/main.py": b"print('hi')\n", "data/weights.bin": b"\x00\x01",
                 "data/selftest/small/input/x.json": b"{}", "data/selftest/small/expected.json": b"{}"}
PACKAGE = {"entry": ["{python}", "code/main.py"], "requires": ["numpy>=2"], "tolerance": {"rel": 1e-6, "abs": 1e-9},
           "selftest": [{"name": "small", "input": "data/selftest/small/input", "expected": "data/selftest/small/expected.json"}]}
PACKAGE_KINDS = [name for name, kind in ITEM_KINDS.items() if kind.format == "package"]


def declared(name: str) -> dict:
    """一份最小的、合规矩的声明。"""
    return {"name": name, "groups": ["一"], "items": [{"name": "x", "label": "叫法", "meaning": "含义", "group": "一", "type": "bool",
                                                     "per_point": False, "required": True, "test": True, "test_source": "文献"}]}


# 第 2 版新的四种包必写的六段
SECOND = {kind: {"programs": [{"name": "abaqus", "version": "2025"}], "declarations": [declared(name) for name in DECLARED[kind]],
                 "modes": list(MODES[kind]), "inputs": {"bone": {"landmarks": ["head_center"]}},
                 "outputs": [{"name": "rotation", "unit": "deg", "meaning": "柄的转角", "role": "label"}],
                 "test_round": {"inputs": {"bone": {"folder": "data/selftest/small/input"}, "points": {"item": "R0012"}}}}
          for kind in NEW_KINDS}


def make_package(root, kind, files=None, **change):
    listed = {**PACKAGE, **({"range": {"bones": ["femur042"]}} if kind == "predictor" else {}), **SECOND.get(kind, {}), **change}
    return make_folder(root, kind=kind, files=PACKAGE_FILES if files is None else files,
                       **{key: value for key, value in listed.items() if value is not None})


@pytest.mark.parametrize("kind", PACKAGE_KINDS)
def test_good_packages_pass(tmp_path, kind):
    assert sorted(PACKAGE_KINDS) == ["derive_def", "fem", "kernel", "predictor", "recon_method", "stem_space", "strategy",
                                     "surrogate_model"]
    assert check_format(kind, make_package(tmp_path / "p", kind)) == []


BAD_SECOND = [
    ("新的一种缺一段", "fem", dict(test_round=None), "缺 test_round"),
    ("外部程序没写版本", "fem", dict(programs=[{"name": "abaqus"}]), "programs 要写成"),
    ("外部程序重名", "fem", dict(programs=[{"name": "abaqus", "version": "2025"}] * 2), "重名的程序"),
    ("外部程序写成一串字", "fem", dict(programs=["abaqus 2025"]), "programs 要写成"),
    ("对输入的要求是一串字", "fem", dict(inputs={"bone": "landmarks"}), "inputs 要写成"),
    ("声明的列表里是字", "fem", dict(declarations=["fem"]), "declarations 要是"),
    ("声明不合规矩", "fem", dict(declarations=[dict(declared("fem"), groups=[])]), "groups"),
    ("声明重名", "fem", dict(declarations=[declared("fem"), declared("fem")]), "重名的声明"),
    ("少了要有的声明", "stem_space", dict(declarations=[declared("design")]), "要声明 placement"),
    ("声明不是列表", "fem", dict(declarations={"fem": declared("fem")}), "declarations 要是"),
    ("能做的事不认得", "fem", dict(modes=["build", "mesh"]), "modes 要从"),
    ("能做的事是空的", "fem", dict(modes=[]), "modes 要从"),
    ("能做的事重复", "fem", dict(modes=["build", "build"]), "modes 要从"),
    ("对输入的要求不是对象", "fem", dict(inputs=["bone"]), "inputs 要写成"),
    ("产出的列缺单位", "fem", dict(outputs=[{"name": "rot", "meaning": "转角", "role": "label"}]), "outputs："),
    ("测试轮的文件夹不在包里", "fem", dict(test_round={"inputs": {"bone": {"folder": "data/nowhere"}}}), "不是包里的一个文件夹"),
    ("测试轮的编号不对", "fem", dict(test_round={"inputs": {"bone": {"item": "femur042"}}}), "要写成"),
    ("测试轮多了一段", "fem", dict(test_round={"inputs": {}, "note": "x"}), "test_round 要写成"),
    ("原来的一种写了它不会的事", "kernel", dict(modes=["train"]), "modes 要从"),
]


@pytest.mark.parametrize("why,kind,change,word", BAD_SECOND, ids=[row[0] for row in BAD_SECOND])
def test_bad_second_version_sections_are_named(tmp_path, why, kind, change, word):
    problems = check_format(kind, make_package(tmp_path / "p", kind, **change))
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_old_kinds_may_leave_the_new_sections_out_and_new_kinds_may_hand_over_no_columns(tmp_path):
    assert check_format("strategy", make_package(tmp_path / "a", "strategy")) == []
    assert check_format("surrogate_model", make_package(tmp_path / "b", "surrogate_model", outputs=[])) == [], "代理模型交出的是预测器"


def test_a_first_version_package_manifest_is_read_as_the_second(tmp_path):
    folder = make_package(tmp_path / "p", "kernel")
    manifest = read_manifest(folder)
    assert manifest["format"] == 2
    (folder / MANIFEST).write_bytes(json.dumps(dict(manifest, format=1)).encode("utf-8"))
    assert check_format("kernel", folder) == [], "第 1 版只差版本号"


BAD_PACKAGES = [
    ("没写入口", dict(entry=None), "缺 entry"),
    ("入口是空的", dict(entry=[]), "entry"),
    ("入口不是参数的列表", dict(entry="python code/main.py"), "entry"),
    ("入口里没有包里的文件", dict(entry=["{python}", "-m", "somewhere.else"]), "包里的一个文件"),
    ("依赖不是列表", dict(requires="numpy"), "requires"),
    ("没写依赖", dict(requires=None), "缺 requires"),
    ("没有自检样本", dict(selftest=[]), "至少"),
    ("自检样本多了一项", dict(selftest=[dict(PACKAGE["selftest"][0], note="x")]), "要带且只带"),
    ("样本的输入不是包里的文件夹", dict(selftest=[dict(PACKAGE["selftest"][0], input="data/nowhere")]), "input"),
    ("样本的期望不是包里的文件", dict(selftest=[dict(PACKAGE["selftest"][0], expected="data/nothing.json")]), "expected"),
    ("样本重名", dict(selftest=PACKAGE["selftest"] * 2), "重复"),
    ("容差缺一项", dict(tolerance={"rel": 1e-6}), "tolerance"),
    ("容差是负的", dict(tolerance={"rel": -1, "abs": 0}), "tolerance"),
    ("不是预测器却带了适用范围", dict(range={"bones": []}), "只有预测器"),
]


@pytest.mark.parametrize("why,change,word", BAD_PACKAGES, ids=[row[0] for row in BAD_PACKAGES])
def test_bad_packages_are_named(tmp_path, why, change, word):
    problems = check_format("kernel", make_package(tmp_path / "p", "kernel", **change))
    assert problems and any(word in text for text in problems), f"{why}：{problems}"


def test_a_package_needs_code_and_a_predictor_needs_a_range(tmp_path):
    files = {rel: data for rel, data in PACKAGE_FILES.items() if not rel.startswith("code/")}
    files["main.py"] = b""
    problems = check_format("kernel", make_package(tmp_path / "p", "kernel", files=files, entry=["{python}", "main.py"]))
    assert any("code/" in text for text in problems)
    problems = check_format("predictor", make_package(tmp_path / "q", "predictor", range=None))
    assert any("range" in text for text in problems)


def test_selftest_differences_use_the_tolerance():
    from stemlab.contract.formats.package import differences

    tight = {"rel": 1e-9, "abs": 0}
    assert differences({"y": 5.0, "tags": ["a", 1], "ok": True, "none": None}, {"y": 5, "tags": ["a", 1.0], "ok": True, "none": None}, tight) == []
    assert differences({"y": 5.0}, {"y": 5.0000000001}, {"rel": 1e-6, "abs": 0}) == []
    assert "result.y" in differences({"y": 5.0}, {"y": 5.1}, {"rel": 1e-6, "abs": 0})[0]
    assert differences({"y": 0.0}, {"y": 1e-12}, {"rel": 0, "abs": 1e-9}) == []
    assert "少了 'z'" in differences({"y": 1, "z": 2}, {"y": 1}, tight)[0]
    assert "多了 'w'" in differences({"y": 1}, {"y": 1, "w": 2}, tight)[0]
    assert "result.rows[1].v" in differences({"rows": [{"v": 1}, {"v": 2}]}, {"rows": [{"v": 1}, {"v": 3}]}, tight)[0]
    assert differences([1, 2], [1, 2, 3], tight) and differences("a", "b", tight) and differences(1, "1", tight)
    assert differences(True, 1, tight) and differences(None, 0, tight), "true 不是 1，null 不是 0"
