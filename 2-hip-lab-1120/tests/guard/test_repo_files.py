"""仓库根目录的几个文件：机器清单合格；源码的换行固定成 LF；data/ 不进 git。"""
from __future__ import annotations

import json

from stemlab.contract import layout
from stemlab.contract.machines import check_machines, parse_machines

REPO = layout.repo_root()


def test_machines_json_is_valid():
    doc = json.loads((REPO / "machines.json").read_bytes())
    assert check_machines(doc) == []
    assert [machine.role for machine in parse_machines(doc)].count("desk") == 1


def test_line_endings_are_pinned_to_lf():
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes


def test_no_source_file_has_crlf():
    """两台机器上文件的字节相同，FROZEN 里的哈希才一致。"""
    bad = []
    for top in ("stemlab", "plugins", "tests", "docs"):
        for path in (REPO / top).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".md", ".json", ".html", ".toml") and b"\r" in path.read_bytes():
                bad.append(path.relative_to(REPO).as_posix())
    for name in (".importlinter", ".gitattributes", ".gitignore", "FROZEN", "CLAUDE.md", "pyproject.toml",
                 "machines.json", ".githooks/pre-commit"):
        if b"\r" in (REPO / name).read_bytes():
            bad.append(name)
    assert bad == [], f"这些文件里有 CR：{bad}"


def test_the_deepest_path_under_data_fits_in_a_windows_path(monkeypatch):
    """Windows 的路径默认最长 260 个字符。照现在仓库放的位置，data/ 里最深的那种路径也要放得下。"""
    from stemlab.contract.formats.manifest import MAX_PATH

    for name in ("STEMLAB_REPO", "STEMLAB_DATA"):
        monkeypatch.delenv(name, raising=False)
    deepest = layout.output_dir("E99999", 999, "x" * 40) / ("y" * MAX_PATH)
    assert len(str(deepest)) < 260, f"仓库放得太深了：{len(str(deepest))} 个字符"
    assert len(str(layout.store_dir("R99999") / ("y" * MAX_PATH))) < 260


def test_data_and_environment_stay_out_of_git():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").split()
    assert "/data/" in ignored and "/.venv/" in ignored and "__pycache__/" in ignored
