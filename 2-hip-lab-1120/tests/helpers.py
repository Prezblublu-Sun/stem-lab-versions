"""各组测试共用的小工具：造文件夹、登记样本、起并发的工人、看 data/ 有没有变。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from stemlab.contract import hashing, layout
from stemlab.contract.formats.manifest import make_manifest, write_manifest
from stemlab.registry import register

REPO = Path(__file__).resolve().parents[1]


def write_files(root: Path, files: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def make_folder(root: Path, kind: str = "report", files: dict | None = None, **extra) -> Path:
    """一个带清单的、符合格式的文件夹。"""
    files = {"summary.json": b"{}\n", "plots/a.png": b"\x89PNG"} if files is None else files
    write_files(root, files)
    write_manifest(root, make_manifest(kind, list(files), **extra))
    return root


def setting(name: str = "demo-setting", value: dict | None = None) -> dict:
    """登记一个值。"""
    return register.register_external("setting", name, value={"scale": 2} if value is None else value,
                                      note="测试用的设定", by="tester")


PACKAGE_CODE = b"""\
import json, pathlib, subprocess, sys, time
import scaling      # a sibling module: importing it is what makes Python want to write a cache into the package
source, target = map(pathlib.Path, sys.argv[1:3])
given = json.loads((source / "x.json").read_text())
if given.get("crash"):
    print("package: crashing on purpose", flush=True)
    sys.exit(7)
if given.get("silent"):
    sys.exit(0)     # exits cleanly without leaving a result
if given.get("child"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])    # stands in for a solver
    (target / "child.pid").write_text(str(child.pid))
time.sleep(given.get("sleep", 0))
(target / "result.json").write_text(json.dumps({"y": scaling.scale(given["x"]), "name": "demo"}))
"""
PACKAGE_MODULE = b"""\
import json, pathlib


def scale(x):
    return x * json.loads((pathlib.Path(__file__).parent.parent / "data" / "scale.json").read_text())["scale"]
"""


def make_package(root: Path, kind: str = "strategy", scale: float = 2.5, expected: dict | None = None, **extra) -> Path:
    """一个符合格式的带代码的包：把输入里的 x 乘上 scale。自检样本是 x=2。"""
    files = {
        "code/main.py": PACKAGE_CODE,
        "code/scaling.py": PACKAGE_MODULE,
        "data/scale.json": hashing.canonical({"scale": scale}),
        "data/selftest/small/input/x.json": hashing.canonical({"x": 2}),
        "data/selftest/small/expected.json": hashing.canonical({"y": 2 * scale, "name": "demo"} if expected is None else expected),
    }
    write_files(root, files)
    listed = {"entry": ["{python}", "code/main.py"], "requires": ["python>=3.12"], "tolerance": {"rel": 1e-9, "abs": 0},
              "selftest": [{"name": "small", "input": "data/selftest/small/input", "expected": "data/selftest/small/expected.json"}]}
    if kind == "predictor":
        listed["range"] = {"bones": ["femur042"]}
    write_manifest(root, make_manifest(kind, list(files), **{**listed, **extra}))
    return root


_COUNTER = iter(range(1, 1_000_000))


def experiment(type_name: str = "demo.echo", value: dict | None = None, extra=()) -> str:
    """登记一份设定，新建一个实验，把输入填好。返回实验的编号。要用 lab 或 own_lab 夹具。"""
    from stemlab.desk.core import actions

    item = setting(f"setting-{next(_COUNTER)}", {} if value is None else value)
    made = actions.new(type_name, note="测试用的实验")
    actions.fill(made, "setting", [item["id"]])
    if extra:
        actions.fill(made, "extra", list(extra))
    return made


def entries_of(made: str, name: str | None = None) -> list[dict]:
    """一个实验记录里的条目；给了条目名就只要那一种。"""
    from stemlab.experiments import reader

    return [entry for entry in reader.read(made) if name is None or entry["entry"] == name]


def snapshot(root: Path) -> dict:
    """root 下每个文件的哈希。用来比“前后一个字节都没变”。锁文件不算：拿锁放锁不是往账上写。"""
    if not root.exists():
        return {}
    return {rel: hashing.hash_file(root / rel) for rel in hashing.list_tree(root) if not rel.endswith(".lock")}


def family(process: subprocess.Popen) -> set[int]:
    """一个子进程和它起的所有进程的进程号。

    Windows 的虚拟环境里 python.exe 是个转发器，真正的解释器是它的子进程，所以“是不是这个进程”要连子进程一起看。
    """
    import psutil

    try:
        return {process.pid} | {child.pid for child in psutil.Process(process.pid).children(recursive=True)}
    except psutil.NoSuchProcess:
        return {process.pid}


def kill_tree(process: subprocess.Popen) -> None:
    """结束一个子进程和它起的所有进程，等它们都真的不在了才返回（它们拿着的锁这时才算放了）。"""
    import psutil

    try:
        family = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        family = []
    for member in [*family, process]:
        try:
            member.kill()
        except (psutil.NoSuchProcess, OSError):
            pass
    process.wait(timeout=10)
    psutil.wait_procs(family, timeout=10)


def wait_for(condition, seconds: float = 20.0, step: float = 0.05):
    """等到 condition() 为真，返回它的值。等不到就让测试失败。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(step)
    raise AssertionError(f"等了 {seconds} 秒也没等到")


def spawn_worker(*args: str, **env: str) -> subprocess.Popen:
    """起一个测试用的子进程：python -m tests.blocks.parallel <参数...>。它继承现在的环境变量。"""
    full = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", **env)
    return subprocess.Popen([sys.executable, "-m", "tests.blocks.parallel", *args], cwd=REPO, env=full,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def release(workers: list[subprocess.Popen], timeout: float = 120.0) -> None:
    """等工人都起来了，放一声发令枪让它们同时开工，再等它们都做完。哪个出错就把它的输出报出来。"""
    go = layout.data_root() / "go"
    go.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(0.5)
    go.write_bytes(b"")
    for worker in workers:
        out, err = worker.communicate(timeout=timeout)
        assert worker.returncode == 0, (out + err).decode("utf-8", "replace")
    go.unlink()
