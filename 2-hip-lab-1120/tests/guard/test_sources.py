"""源码扫描：插件不直接碰 data/；只许一处叫的函数；核心不认识插件；状态名的判断只在契约里。"""
from __future__ import annotations

import textwrap

import pytest

from stemlab.contract import layout
from stemlab.hooks import load
from tests.guard import scan

REPO = layout.repo_root()
STEMLAB = REPO / "stemlab"
PLUGINS = REPO / "plugins"
TYPE_NAMES = ("recon.draft", "recon.finalize", "opt.pool", "opt.select", "fea.run", "fea.reference",
              "surrogate.train", "surrogate.predict", "surrogate.check")


def show(hits) -> str:
    return "\n" + "\n".join(map(str, hits))


def test_plugins_do_not_touch_data():
    hits = scan.scan(PLUGINS, REPO, scan.strings_matching(scan.DATA_WORDS))
    assert not hits, "插件的源码里不该出现 data/ 的路径和两条链的文件名：" + show(hits)


def test_register_output_is_called_from_one_place_only():
    hits = scan.scan(STEMLAB, REPO, scan.mentions("register_output")) + scan.scan(PLUGINS, REPO, scan.mentions("register_output"))
    allowed = {"stemlab/registry/register.py", "stemlab/hooks/publish.py"}
    outside = [hit for hit in hits if hit.file not in allowed]
    assert not outside, "register_output 只许 hooks/publish.py 叫：" + show(outside)


def test_os_kill_is_never_used():
    hits = scan.scan(STEMLAB, REPO, scan.calls_os_kill) + scan.scan(PLUGINS, REPO, scan.calls_os_kill)
    assert not hits, "查进程在不在要用 psutil，不能用 os.kill：" + show(hits)


def test_core_does_not_know_any_plugin_or_type():
    names = sorted(path.name for path in PLUGINS.iterdir() if (path / "plugin.py").is_file())
    assert names == ["fea", "opt", "recon", "surrogate"]
    hits = scan.scan(STEMLAB, REPO, scan.words(names + list(TYPE_NAMES)))
    assert not hits, "stemlab/ 里不该出现任何插件或类型的名字：" + show(hits)


def test_only_the_contract_judges_state_names():
    hits = [hit for hit in scan.scan(STEMLAB, REPO, scan.judges_states) if not hit.file.startswith("stemlab/contract/")]
    assert not hits, "状态的算法只在契约里，别的块问 states.can：" + show(hits)


def test_readers_do_not_import_writers():
    """读的模块绝不能 import 写的模块，间接的也不行；依赖规则第 6 条靠这个才成立。"""
    writers = ("stemlab.registry.register", "stemlab.registry.links", "stemlab.registry.lock",
               "stemlab.experiments.log", "stemlab.experiments.lock")
    for rel in ("stemlab/registry/reader.py", "stemlab/registry/lookup.py", "stemlab/registry/verify.py",
                "stemlab/experiments/reader.py", "stemlab/experiments/view.py"):
        hits = scan.scan(REPO / rel, REPO, scan.imports(writers))
        assert not hits, show(hits)


def test_plugins_package_is_where_the_loader_looks(monkeypatch):
    monkeypatch.delenv("STEMLAB_PLUGINS", raising=False)
    monkeypatch.delenv("STEMLAB_REPO", raising=False)
    assert load.plugins_dir() == PLUGINS
    assert load.plugin_names() == ["fea", "opt", "recon", "surrogate"]


# ---- 扫描本身管不管用：给它一段越界的代码，看它报不报、报的是哪一行 ----

BAD = textwrap.dedent('''\
    """文档字符串里提到 data/registry/register.jsonl、os.kill、register_output 都不算。"""
    import os
    from os import kill
    from stemlab.registry.register import register_output      # 第 4 行

    # 注释里提到 record.jsonl 也不算
    def peek(folder, status):
        """这里提到 "running" 也不算。"""
        open(folder / "record.jsonl")                           # 第 9 行
        open("H:/projects/Hip-lab/data/experiments/E0001/work/x")
        os.kill(123, 0)                                         # 第 11 行
        register_output()                                       # 第 12 行
        if status.state == "running":                           # 第 13 行
            return status.state in ("ended", "new")             # 第 14 行
        return fea_run                                          # 不是整词，不算
    kind = "fea.run"                                            # 第 16 行
''')


@pytest.fixture
def bad(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bad.py").write_text(BAD, encoding="utf-8")
    return tmp_path


def lines(hits) -> list[int]:
    return sorted({hit.line for hit in hits})


def test_scans_report_file_and_line(bad):
    hits = scan.scan(bad, bad, scan.strings_matching(scan.DATA_WORDS))
    assert lines(hits) == [9, 10] and hits[0].file == "pkg/bad.py"
    assert "pkg/bad.py:9" in str(hits[0])
    assert lines(scan.scan(bad, bad, scan.calls_os_kill)) == [3, 11]
    assert lines(scan.scan(bad, bad, scan.mentions("register_output"))) == [4, 12]
    assert lines(scan.scan(bad, bad, scan.judges_states)) == [13, 14]
    assert lines(scan.scan(bad, bad, scan.words(["fea", "fea.run"]))) == [16]
    assert lines(scan.scan(bad, bad, scan.imports(["stemlab.registry.register", "os.path"]))) == [4]
    assert lines(scan.scan(bad, bad, scan.imports(["stemlab.registry.register.register_output", "os"]))) == [2, 3, 4]
