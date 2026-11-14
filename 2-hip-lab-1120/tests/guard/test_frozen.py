"""固定的文件不被顺手改：清单里记着每个固定文件的哈希，文件和清单对不上就不过。"""
from __future__ import annotations

import pytest

from stemlab.contract import hashing, layout
from stemlab.desk.core import code_state
from stemlab.hooks import load

PLUGIN_FROZEN = [
    "plugins/recon/plugin.py", "plugins/recon/gate.py", "plugins/recon/model.py",
    "plugins/fea/plugin.py", "plugins/fea/outcomes.py", "plugins/fea/export.py", "plugins/fea/archive.py",
    "plugins/fea/judge.py",
    "plugins/surrogate/plugin.py", "plugins/surrogate/split.py", "plugins/surrogate/report.py",
    "plugins/surrogate/predictor.py",
    "plugins/opt/plugin.py", "plugins/opt/feasible.py", "plugins/opt/replay.py",
]


# ---- 仓库自己 ----

def test_the_repo_matches_its_manifest():
    problems = code_state.frozen_ok()
    assert problems == [], "固定的文件和 FROZEN 清单对不上：\n" + "\n".join(problems)


def test_the_manifest_covers_what_the_blueprint_says():
    frozen = load.read_frozen()
    assert set(frozen.trees) == {"stemlab/contract", "stemlab/registry", "stemlab/experiments", "stemlab/hooks",
                                 "stemlab/desk/core", "tests"}
    for rel in (".importlinter", ".gitattributes", ".githooks/pre-commit", "stemlab/__init__.py",
                "stemlab/desk/__init__.py", "stemlab/desk/__main__.py", "plugins/__init__.py", *PLUGIN_FROZEN):
        assert rel in frozen.files, f"清单里该有 {rel}"
    assert len(PLUGIN_FROZEN) == 15, "冻结文件一共 15 个：重建 3、FEA 5、代理 4、优化 3"
    # plugins/__init__.py 每次装插件都会跑到，所以也锁着；除它之外，插件里自由的文件不进清单
    free = [rel for rel in frozen.files if rel.startswith("plugins/") and rel not in [*PLUGIN_FROZEN, "plugins/__init__.py"]]
    assert free == [], "插件里自由的文件不进清单"
    assert not any("/ui/" in rel or rel.startswith("stemlab/board/") for rel in frozen.files), "展示层不进清单"


def test_manifest_lines_are_sorted_and_lf_only():
    raw = (layout.repo_root() / load.FROZEN).read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    paths = [line[66:] for line in raw.decode("utf-8").split("\n") if hashing.is_hash(line[:64])]
    assert paths == sorted(paths, key=lambda rel: rel.encode("utf-8"))


# ---- 核对本身管不管用：在一棵小树上试 ----

@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    files = {
        "stemlab/contract/a.py": b"A = 1\n",
        "stemlab/contract/formats/b.py": b"B = 2\n",
        "stemlab/hooks/c.py": b"C = 3\n",
        "tests/test_x.py": b"def test_x(): pass\n",
        ".importlinter": b"[importlinter]\n",
        "plugins/__init__.py": b"",
        "plugins/demo/plugin.py": b"KINDS = []\n",
        "plugins/demo/rules.py": b"RULE = 1\n",
        "plugins/demo/free.py": b"FREE = 1\n",
    }
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    monkeypatch.setenv("STEMLAB_REPO", str(root))
    monkeypatch.delenv("STEMLAB_PLUGINS", raising=False)
    monkeypatch.setattr(code_state, "DEFAULT_TREES", ("stemlab/contract", "stemlab/hooks", "tests"))
    monkeypatch.setattr(code_state, "DEFAULT_FILES", (".importlinter",))
    code_state.freeze(add=["plugins/demo/plugin.py", "plugins/demo/rules.py"])
    return root


def test_a_fresh_manifest_matches(tree):
    assert code_state.frozen_ok() == []
    frozen = load.read_frozen()
    assert frozen.trees == ("stemlab/contract", "stemlab/hooks", "tests")
    assert sorted(frozen.files) == [".importlinter", "plugins/demo/plugin.py", "plugins/demo/rules.py",
                                    "stemlab/contract/a.py", "stemlab/contract/formats/b.py",
                                    "stemlab/hooks/c.py", "tests/test_x.py"]
    assert frozen.files["stemlab/contract/a.py"] == hashing.hash_bytes(b"A = 1\n")
    assert frozen.hash == hashing.hash_file(tree / "FROZEN")


@pytest.mark.parametrize("rel", ["stemlab/contract/a.py", "stemlab/contract/formats/b.py", "tests/test_x.py",
                                 ".importlinter", "plugins/demo/rules.py"])
def test_a_changed_fixed_file_is_named(tree, rel):
    (tree / rel).write_bytes((tree / rel).read_bytes() + b"# touched\n")
    assert code_state.frozen_ok() == [f"和清单对不上（被改过）：{rel}"]


def test_a_line_ending_rewrite_counts_as_a_change(tree):
    (tree / "stemlab/contract/a.py").write_bytes(b"A = 1\r\n")
    assert code_state.frozen_ok() == ["和清单对不上（被改过）：stemlab/contract/a.py"]


def test_a_deleted_fixed_file_is_named(tree):
    (tree / "stemlab/hooks/c.py").unlink()
    assert code_state.frozen_ok() == ["清单里有但文件没了：stemlab/hooks/c.py"]


def test_a_new_file_in_a_fixed_folder_is_named(tree):
    (tree / "stemlab/contract/formats/new.py").write_bytes(b"")
    assert code_state.frozen_ok() == ["固定的文件夹里多了清单没列的文件：stemlab/contract/formats/new.py"]


def test_free_files_and_caches_do_not_matter(tree):
    (tree / "plugins/demo/free.py").write_bytes(b"FREE = 2\n")
    (tree / "plugins/demo/new_free.py").write_bytes(b"")
    (tree / "stemlab/contract/__pycache__").mkdir()
    (tree / "stemlab/contract/__pycache__/a.cpython-312.pyc").write_bytes(b"cache")
    assert code_state.frozen_ok() == []


def test_a_missing_or_garbled_manifest_fails(tree):
    manifest = tree / "FROZEN"
    good = manifest.read_bytes()
    manifest.write_bytes(good + b"not a line\n")
    assert "写法不对" in code_state.frozen_ok()[0]
    first = next(line for line in good.split(b"\n") if hashing.is_hash(line[:64].decode("ascii", "replace")))
    manifest.write_bytes(good + first + b"\n")
    assert "重复" in code_state.frozen_ok()[0]
    manifest.unlink()
    assert "读不了" in code_state.frozen_ok()[0]


def test_freeze_reports_what_changed_and_keeps_the_coverage(tree):
    assert code_state.freeze() == []
    (tree / "stemlab/contract/a.py").write_bytes(b"A = 2\n")
    (tree / "stemlab/hooks/d.py").write_bytes(b"D = 4\n")
    (tree / "tests/test_x.py").unlink()
    changes = code_state.freeze(add=["plugins/demo/free.py"], remove=["plugins/demo/rules.py"])
    assert changes == ["新列入：plugins/demo/free.py", "新列入：stemlab/hooks/d.py",
                       "不再列：plugins/demo/rules.py", "不再列：tests/test_x.py",
                       "哈希变了：stemlab/contract/a.py"]
    assert code_state.frozen_ok() == []
    assert load.read_frozen().trees == ("stemlab/contract", "stemlab/hooks", "tests")


def test_plugin_hashes(tree):
    whole, frozen = load.plugin_hash("demo"), load.frozen_hash("demo")
    (tree / "plugins/demo/free.py").write_bytes(b"FREE = 2\n")
    assert load.plugin_hash("demo") != whole, "自由的文件一改，插件文件夹的哈希就变"
    assert load.frozen_hash("demo") == frozen, "但冻结文件的哈希不变"
    (tree / "plugins/demo/rules.py").write_bytes(b"RULE = 2\n")
    assert load.frozen_hash("demo") != frozen, "冻结文件一改，哈希就变，不用等清单重新生成"
    (tree / "plugins/demo/__pycache__").mkdir()
    (tree / "plugins/demo/__pycache__/x.pyc").write_bytes(b"cache")
    before = load.plugin_hash("demo")
    (tree / "plugins/demo/__pycache__/y.pyc").write_bytes(b"cache")
    assert load.plugin_hash("demo") == before
