"""这个插件自己的测试的公共部分。

测试用临时文件夹当 home，把插件文件夹复制一份进去，不碰正式的 experiments，也不装别的插件。
"""
import shutil
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PLUGIN = TESTS.parent
REPO = PLUGIN.parent.parent
for p in (str(REPO), str(PLUGIN), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def home(tmp_path):
    """一个临时的 home，里面只装这个插件。测试结束时把还活着的后台进程结束掉。"""
    from fae_helpers import kill_workers

    h = tmp_path / "home"
    shutil.copytree(PLUGIN, h / "plugins" / "fea_archive_export",
                    ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    yield h
    kill_workers(h)
