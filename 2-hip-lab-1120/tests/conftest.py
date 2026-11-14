"""各组测试共用的夹具。

    data        一份空的 data/
    lab         一份空的 data/，加一个干净的、提交过的仓库拷贝；核心到 tests/plugins 里找插件
    own_lab     同上，但仓库拷贝是这次测试自己的，可以随便改

启动的第 4 步要看代码的状态（FROZEN 清单、git 干不干净）。开发的时候真仓库总是不干净的，
所以测试让核心去看一份提交过的拷贝（STEMLAB_REPO）。跑的代码还是真仓库里的这一份，两边内容相同。
"""
from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from stemlab.contract import hashing
from stemlab.desk.core import code_state
from stemlab.hooks import call, load

REPO = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=lab", "-c", "user.email=lab@localhost", "-c", "core.autocrlf=false",
                           *args], cwd=root, capture_output=True, check=True)
    return done.stdout.decode("utf-8", "replace")


@pytest.fixture(autouse=True)
def _fresh_process_state():
    """核心留在进程里的两样东西，每个测试开头清掉：连着出现的报错的计数，和插件 import 时的哈希。"""
    call._STREAK.clear()
    load._AT_IMPORT.clear()
    yield


@pytest.fixture
def data(tmp_path, monkeypatch):
    """一份空的 data/，这次测试自己用。这台机器的缓存也换成这次测试自己的。"""
    root = tmp_path / "data"
    monkeypatch.setenv("STEMLAB_DATA", str(root))
    monkeypatch.setenv("STEMLAB_CACHE", str(tmp_path / "cache"))
    return root


@pytest.fixture(scope="session")
def lab_repo(tmp_path_factory) -> Path:
    """一个干净的、提交过的仓库拷贝。整场测试共用，谁也不要改它；要改的用 own_lab。"""
    root = tmp_path_factory.mktemp("lab") / "repo"
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO / "stemlab", root / "stemlab", ignore=ignore)
    shutil.copytree(REPO / "tests" / "plugins", root / "tests" / "plugins", ignore=ignore)
    shutil.copy(REPO / "tests" / "__init__.py", root / "tests" / "__init__.py")
    for name in (".importlinter", ".gitattributes", "uv.lock"):
        shutil.copy(REPO / name, root / name)
    machines = {"format": 1, "machines": [{"name": "here", "role": "desk", "host": socket.gethostname(), "slots": 2}]}
    (root / "machines.json").write_bytes(hashing.canonical(machines) + b"\n")
    with pytest.MonkeyPatch.context() as patch:
        # 这份拷贝里，测试用的插件和真插件一样：只有 plugin.py 是冻结的，别的文件自由
        patch.setenv("STEMLAB_REPO", str(root))
        patch.setattr(code_state, "DEFAULT_TREES", tuple(t for t in code_state.DEFAULT_TREES if t != "tests"))
        code_state.freeze(add=["tests/__init__.py", "tests/plugins/__init__.py",
                               *(f"tests/plugins/{name}/plugin.py" for name in ("demo", "bad", "broken"))])
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "lab")
    return root


def _use(repo: Path, monkeypatch) -> Path:
    monkeypatch.setenv("STEMLAB_REPO", str(repo))
    monkeypatch.setenv("STEMLAB_PLUGINS", "tests.plugins")
    return repo


@pytest.fixture
def lab(lab_repo, data, monkeypatch) -> Path:
    """一份空的 data/ 加共用的仓库拷贝。返回仓库拷贝的位置。"""
    return _use(lab_repo, monkeypatch)


@pytest.fixture
def own_lab(lab_repo, data, tmp_path, monkeypatch) -> Path:
    """一份空的 data/ 加这次测试自己的仓库拷贝，可以改文件、可以提交。"""
    root = tmp_path / "repo"
    shutil.copytree(lab_repo, root)
    return _use(root, monkeypatch)


# ---- 真的四个插件 ----

@pytest.fixture(scope="session")
def real_repo(tmp_path_factory) -> Path:
    """一个干净的、提交过的仓库拷贝，带的是真的四个插件（plugins/）。整场测试共用，谁也不要改它。"""
    root = tmp_path_factory.mktemp("real") / "repo"
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO / "stemlab", root / "stemlab", ignore=ignore)
    shutil.copytree(REPO / "plugins", root / "plugins", ignore=ignore)
    for name in (".importlinter", ".gitattributes", "uv.lock"):
        shutil.copy(REPO / name, root / name)
    machines = {"format": 1, "machines": [{"name": "here", "role": "desk", "host": socket.gethostname(), "slots": 2}]}
    (root / "machines.json").write_bytes(hashing.canonical(machines) + b"\n")
    frozen_in_plugins = [rel for rel in load.parse_frozen((REPO / load.FROZEN).read_bytes()).files if rel.startswith("plugins/")]
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("STEMLAB_REPO", str(root))
        patch.setattr(code_state, "DEFAULT_TREES", tuple(t for t in code_state.DEFAULT_TREES if t != "tests"))
        code_state.freeze(add=frozen_in_plugins)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "real")
    return root


def _use_real(repo: Path, tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("STEMLAB_REPO", str(repo))
    monkeypatch.delenv("STEMLAB_PLUGINS", raising=False)
    monkeypatch.setenv("STEMLAB_SLOTS", str(tmp_path / "slots"))        # 求解槽是整台机器共用的；测试各用各的
    return repo


@pytest.fixture
def real_lab(real_repo, data, tmp_path, monkeypatch) -> Path:
    """一份空的 data/ 加带真插件的仓库拷贝。返回仓库拷贝的位置。"""
    return _use_real(real_repo, tmp_path, monkeypatch)


@pytest.fixture
def real_own_lab(real_repo, data, tmp_path, monkeypatch) -> Path:
    """同上，但仓库拷贝是这次测试自己的，可以改插件里的文件、可以提交。"""
    root = tmp_path / "repo"
    shutil.copytree(real_repo, root)
    return _use_real(root, tmp_path, monkeypatch)
