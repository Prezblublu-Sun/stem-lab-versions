"""把 stemlab/desk/ui/ 和 stemlab/board/ 整个换成替身，在仓库的拷贝里把固定的测试跑一遍。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import helpers

pytestmark = pytest.mark.swap
HERE = Path(__file__).resolve().parent
TREES = ("stemlab", "plugins", "tests", ".githooks")
FILES = (".importlinter", ".gitattributes", ".gitignore", "FROZEN", "CLAUDE.md", "pyproject.toml", "machines.json", "uv.lock", "conftest.py")
SWAPPED = (("stemlab/desk/ui", "desk_ui"), ("stemlab/board", "board"))
# 这一条量的是“仓库放在哪”：拷贝放在临时文件夹里，路径本来就比真仓库长得多，和换界面无关，所以在拷贝里不跑它
ELSEWHERE = "tests/guard/test_repo_files.py::test_the_deepest_path_under_data_fits_in_a_windows_path"


def test_the_other_blocks_pass_with_another_ui_and_board(tmp_path):
    copy = tmp_path / "repo"
    ignore = shutil.ignore_patterns("__pycache__")
    for name in TREES:
        shutil.copytree(helpers.REPO / name, copy / name, ignore=ignore)
    for name in FILES:
        shutil.copy(helpers.REPO / name, copy / name)
    for target, stand_in in SWAPPED:
        shutil.rmtree(copy / target)
        shutil.copytree(HERE / stand_in, copy / target, ignore=ignore)
    assert not (copy / "stemlab" / "desk" / "ui" / "page.html").exists(), "原来的界面一个文件都不在了"

    env = {key: value for key, value in os.environ.items() if not key.startswith("STEMLAB_")}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider",
                           "-m", "not cross and not science and not swap", "--deselect", ELSEWHERE],
                          cwd=copy, env=env, capture_output=True, timeout=3600)
    said = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert done.returncode == 0, "换了界面和仪表盘之后，固定的测试有不过的：\n" + said[-4000:]
    assert "[100%]" in said and said.count(".") > 300, "固定的测试确实整个跑了一遍：\n" + said[-600:]
