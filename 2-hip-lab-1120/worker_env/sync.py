"""把 worker 的 Python 环境照仓库这份锁装出来：两台机器各一个环境，由同一份锁文件装出来。

在仓库根目录运行（Windows，用仓库的 .venv）：

    .venv\\Scripts\\python.exe worker_env\\sync.py            装。已经装好、锁也没变，就什么都不动
    .venv\\Scripts\\python.exe worker_env\\sync.py --check    只看不装：那边的环境还是不是照现在这份锁装的

改了 uv.lock 之后两边都要重装：本机 `.venv\\Scripts\\uv.exe sync --inexact`，worker 跑上面第一条。

环境放在哪，看机器清单里那台 worker 的 python：它写的是 <根>/venv/bin/python，这里就装到 <根>/ 下面
（lock/ 放送过去的锁和两个脚本，tools/ 只放 uv，venv/ 是环境）。不用 sudo，只动 <根>/ 这一个文件夹。
uv 用和本机同一个版本；包从 PyPI 下，下载的缓存在那边的 ~/.cache/uv。
装完那边报回来：Python 版本、每个包的版本、锁的哈希、直接要的包能不能导入。这里拿它和本机的环境逐个比。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import re
import shlex
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from stemlab.contract.machines import parse_machines  # noqa: E402

SUFFIX = "/venv/bin/python"
SENT = (("pyproject.toml", REPO / "pyproject.toml", 0o644), ("uv.lock", REPO / "uv.lock", 0o644),
        ("install_env.sh", HERE / "install_env.sh", 0o755), ("report_env.py", HERE / "report_env.py", 0o644))


def plain(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def workers(only: str | None) -> list:
    listed = parse_machines(json.loads((REPO / "machines.json").read_bytes()))
    found = [machine for machine in listed if machine.role == "worker" and only in (None, machine.name)]
    if not found:
        raise SystemExit(f"机器清单里没有叫 {only} 的 worker" if only else "机器清单里没有 worker")
    return found


def bundle() -> bytes:
    """要送过去的四个文件，打成一个 tar。字节原样送：锁在两边的哈希要相同。"""
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w") as tar:
        for name, path, mode in SENT:
            body = path.read_bytes()
            if name.endswith(".sh") and b"\r" in body:
                raise SystemExit(f"{path} 里有 CR，那边的 bash 跑不了。它该是 LF 换行")
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(body), mode, int(path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(body))
    return held.getvalue()


def ssh(machine, script: str, data: bytes | None = None) -> tuple[int, list[str]]:
    """在那台机器上跑一段 shell，把它说的话一行行打出来（JSON 那一行不打）。返回退出码和说的每一行。"""
    tool = str(Path(machine.bin) / "ssh") if machine.bin else "ssh"
    command = [tool, "-p", str(machine.port), *machine.options, machine.ssh, script]
    if data is not None:
        done = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        said = done.stdout.decode("utf-8", "replace").splitlines()
        print("".join(f"    {line}\n" for line in said), end="", flush=True)
        return done.returncode, said
    said = []
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as running:
        for raw in running.stdout:
            said.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
            if not said[-1].startswith("{"):
                print("    " + said[-1], flush=True)
    return running.returncode, said


def differences(machine, found: dict) -> list[str]:
    """那边报回来的环境，和这份锁、和本机的环境，哪里对不上。空列表就是都对上了。"""
    problems = []
    lock = hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()
    if found.get("lock") != lock:
        problems.append(f"那边的环境不是照现在这份锁装的：那边记的是 {str(found.get('lock'))[:12]}，这份锁是 {lock[:12]}")
    if found.get("executable") != machine.python:
        problems.append(f"报回来的解释器是 {found.get('executable')}，机器清单里写的是 {machine.python}")
    theirs = {plain(name): version for name, version in found.get("packages", {}).items()}
    for name, version in sorted(theirs.items()):
        try:
            mine = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            mine = None
        if mine != version:
            problems.append(f"{name}：那边是 {version}，本机" + (f"是 {mine}" if mine else "没有"))
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    for line in project["project"]["dependencies"]:
        name = plain(re.match(r"[A-Za-z0-9._-]+", line).group(0))
        if name not in theirs:
            problems.append(f"{name}：那边没装上")
    problems += [f"{module} 装上了但导入不了：{said}" for module, said in sorted(found.get("imports", {}).items())
                 if said != "ok"]
    return problems


def one(machine, check_only: bool) -> bool:
    if not machine.python.startswith("/") or not machine.python.endswith(SUFFIX):
        print(f"{machine.name}：机器清单里它的 python 要写成 <环境的根>{SUFFIX}，现在是 {machine.python}")
        return False
    root = shlex.quote(machine.python[: -len(SUFFIX)])
    print(f"{machine.name}（{machine.host}）：环境在 {root}/venv", flush=True)
    if check_only:
        code, said = ssh(machine, f"{root}/venv/bin/python {root}/lock/report_env.py {root}/lock")
    else:
        try:
            uv = importlib.metadata.version("uv")
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit("本机的环境里没有 uv，不知道那边该装哪一版。请用仓库的 .venv 运行") from None
        code, said = ssh(machine, f"mkdir -p {root}/lock && tar -xf - -C {root}/lock", bundle())
        if code == 0:
            code, said = ssh(machine, f"bash {root}/lock/install_env.sh {root} {shlex.quote(uv)}")
    report = next((line for line in reversed(said) if line.startswith("{")), None)
    if code != 0 or report is None:
        print(f"  没做成（退出码 {code}）。" + ("那边还没装过环境，去掉 --check 再跑一遍就是装" if check_only else ""))
        return False
    found = json.loads(report)
    print(f"  Python {found['python']}，{len(found['packages'])} 个包，照锁 {str(found['lock'])[:12]} 装的")
    problems = differences(machine, found)
    if problems:
        print("  对不上的：" + "".join(f"\n    - {text}" for text in problems))
        return False
    print("  和这份锁、和本机的环境都对得上；直接要的包都能导入")
    return True


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="把 worker 的环境照 uv.lock 装出来，或者只核对")
    parser.add_argument("--check", action="store_true", help="只看不装")
    parser.add_argument("--machine", help="机器清单里 worker 的名字；不写就是每一台 worker")
    asked = parser.parse_args()
    results = [one(machine, asked.check) for machine in workers(asked.machine)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
