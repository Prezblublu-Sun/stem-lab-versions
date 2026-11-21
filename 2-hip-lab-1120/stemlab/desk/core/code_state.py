"""代码的状态。

    frozen_ok()       固定的文件和 FROZEN 清单对不对得上
    clean(路径)       只看声明的路径在 git 里有没有没提交的改动
    snapshot(插件)    这一轮必记的来历，和插件没提交的改动
    freeze()          重新生成 FROZEN 清单。只给人用：python -m stemlab.desk.core.code_state freeze

FROZEN 清单的改法只有一种：单独一次提交，只改清单和它锁着的文件，提交说明里写为什么改。AI 不改清单。
"""
from __future__ import annotations

import argparse
import platform
import socket
import subprocess
import sys

from stemlab.contract import hashing, layout, versions
from stemlab.desk import core
from stemlab.hooks import load, local

# 契约、核心，和 FROZEN 清单自己。启动时这些路径不许有没提交的改动：
# 来历里记的是提交号，没提交的东西照着提交号找不回来
CORE = ("FROZEN", "stemlab/__init__.py", "stemlab/contract", "stemlab/registry", "stemlab/experiments",
        "stemlab/hooks", "stemlab/desk/__init__.py", "stemlab/desk/__main__.py", "stemlab/desk/core")

# 第一次生成清单时的覆盖范围。之后以清单里已经写着的为准
DEFAULT_TREES = ("stemlab/contract", "stemlab/registry", "stemlab/experiments", "stemlab/hooks",
                 "stemlab/desk/core", "tests")
DEFAULT_FILES = (".gitattributes", ".importlinter", "stemlab/__init__.py", "stemlab/desk/__init__.py",
                 "stemlab/desk/__main__.py")

_HEADER = """\
# FROZEN：固定文件的清单。一行一个固定的文件：哈希、两个空格、路径。
# “tree 路径”说这个文件夹整个固定：里面多一个、少一个文件都算对不上。
# 改法只有一种：单独一次提交，只改这份清单和它锁着的文件，提交说明里写为什么改。AI 不改这份清单。
# 重新生成：python -m stemlab.desk.core.code_state freeze
"""


def frozen_ok() -> list[str]:
    """固定的文件和清单对不对得上。返回哪里对不上，说出是哪个文件；空列表就是对得上。"""
    root = layout.repo_root()
    try:
        frozen = load.read_frozen()
    except (OSError, ValueError) as error:
        return [f"读不了 {load.FROZEN} 清单：{error}"]
    problems = []
    for rel, recorded in sorted(frozen.files.items()):
        if not (root / rel).is_file():
            problems.append(f"清单里有但文件没了：{rel}")
        elif hashing.hash_file(root / rel) != recorded:
            problems.append(f"和清单对不上（被改过）：{rel}")
    for tree in frozen.trees:
        if not (root / tree).is_dir():
            problems.append(f"清单里整个固定的文件夹没了：{tree}")
            continue
        for rel in hashing.list_tree(root / tree, ignore=load.IGNORE):
            if f"{tree}/{rel}" not in frozen.files:
                problems.append(f"固定的文件夹里多了清单没列的文件：{tree}/{rel}")
    return problems


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=layout.repo_root(),
                          capture_output=True, check=False, **local.QUIET)


def clean(paths) -> list[str]:
    """声明的路径里有没有没提交的改动。返回有改动的文件；空列表就是干净。只看这些路径，别处不管。"""
    done = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    if done.returncode != 0:
        return [f"问不了 git：{done.stderr.decode('utf-8', 'replace').strip()}"]
    return [entry[3:] for entry in done.stdout.decode("utf-8", "replace").split("\0") if len(entry) > 3]


def commit() -> str:
    """现在的提交号。还没有提交过就报 RuntimeError。"""
    done = _git("rev-parse", "HEAD")
    if done.returncode != 0:
        raise RuntimeError("仓库里还没有提交，记不了提交号")
    return done.stdout.decode("ascii").strip()


def snapshot(plugin: str) -> tuple[dict, bytes | None]:
    """这一轮必记的来历（见 entries.ROUND_PROVENANCE），和插件没提交的改动。

    插件带着没提交的改动可以启动：来历里写明不干净，差异由调用方存进这一轮的文件夹。
    """
    root = layout.repo_root()
    folder = (load.plugins_dir() / plugin).relative_to(root).as_posix()
    dirty = clean([folder])
    diff = None
    if dirty:
        tracked = _git("diff", "HEAD", "--binary", "--", folder).stdout
        untracked = _git("ls-files", "--others", "--exclude-standard", "-z", "--", folder).stdout.decode("utf-8")
        added = b"".join(_git("diff", "--binary", "--no-index", "--", "/dev/null", rel).stdout
                         for rel in untracked.split("\0") if rel)
        diff = tracked + added
    lock = layout.lock_file()
    provenance = {
        "commit": commit(),
        "clean": not clean(CORE),
        "frozen": load.read_frozen().hash,
        "plugin": plugin,
        "plugin_hash": load.plugin_hash(plugin),
        "plugin_frozen": load.frozen_hash(plugin),
        "plugin_dirty": bool(dirty),
        "contract": versions.CONTRACT,
        "python": platform.python_version(),
        "lock": hashing.hash_file(lock) if lock.is_file() else hashing.hash_bytes(b""),
        "host": socket.gethostname(),
    }
    return provenance, diff


def freeze(add=(), remove=()) -> list[str]:
    """重新生成 FROZEN 清单，返回和原来比变了什么。只给人用。"""
    root = layout.repo_root()
    try:
        old = load.read_frozen()
        trees = old.trees
        singles = {rel for rel in old.files if not any(rel.startswith(tree + "/") for tree in trees)}
    except FileNotFoundError:
        old, trees, singles = None, DEFAULT_TREES, set(DEFAULT_FILES)
    singles = (singles | set(add)) - set(remove)
    files = {rel: None for rel in singles}
    for tree in trees:
        files.update({f"{tree}/{rel}": None for rel in hashing.list_tree(root / tree, ignore=load.IGNORE)})
    for rel in files:
        files[rel] = hashing.hash_file(root / rel)
    lines = [f"tree {tree}\n" for tree in trees]
    lines += [f"{digest}  {rel}\n" for rel, digest in sorted(files.items(), key=lambda item: item[0].encode("utf-8"))]
    (root / load.FROZEN).write_bytes((_HEADER + "".join(lines)).encode("utf-8"))

    before = old.files if old else {}
    changes = [f"新列入：{rel}" for rel in sorted(set(files) - set(before))]
    changes += [f"不再列：{rel}" for rel in sorted(set(before) - set(files))]
    changes += [f"哈希变了：{rel}" for rel in sorted(set(files) & set(before)) if files[rel] != before[rel]]
    return changes


def main(argv=None) -> int:
    core.utf8_console()
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk.core.code_state",
                                     description="看固定的文件和 FROZEN 清单对不对得上；freeze 重新生成清单（只给人用）")
    parser.add_argument("command", choices=("status", "freeze"), nargs="?", default="status")
    parser.add_argument("--add", nargs="*", default=[], metavar="路径", help="新列入的单个固定文件，比如插件的冻结文件")
    parser.add_argument("--remove", nargs="*", default=[], metavar="路径", help="不再列的单个文件")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        changes = freeze(args.add, args.remove)
        print("\n".join(changes) if changes else "清单没有变化")
        print("清单已重新生成。照规矩：单独一次提交，只改清单和它锁着的文件，提交说明里写为什么改。")
        return 0
    problems = frozen_ok()
    print("\n".join(problems) if problems else "固定的文件和清单对得上")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
