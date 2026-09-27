"""本机 ↔ Linux（linuxworkstation）的薄封装：代码同步、远程执行、取回文件。只用标准库。

约定
* 本机只做 Abaqus 求解；前后处理、模板化、网格、GP/BO 都经本模块在 Linux 上执行。
* Linux 侧目录：~/mobo_toy_v2/{code, data, queue, results}；Python 入口 ~/mobo_toy_v2/run.sh（带用户级 libGLU）。
* 连接用 Git 自带的 ssh + 指定私钥，BatchMode；失败直接抛异常并带上 stderr，不静默重试。
"""
from __future__ import annotations

import hashlib
import io
import pathlib
import subprocess
import tarfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]           # sandbox/mobo_toy
SSH = r"C:\Program Files\Git\usr\bin\ssh.exe"
KEY = str(pathlib.Path.home() / ".ssh" / "id_ed25519_lrlbackup")
HOST = "linux-user@<linux-ip>"
RBASE = "mobo_toy_v2"                                        # 相对 Linux 家目录
SYNC = [                                                     # 需要在 Linux 上的代码（相对 ROOT）
    "config.yaml", "plotstyle.py", "femur2d.py", "stem2d.py", "inp_writer.py", "qoi.py", "mobo.py",
    "spot3d/__init__.py", "spot3d/model3d.py", "spot3d/qoi3d.py",
    "v2/__init__.py", "v2/*.py", "v2/config_v2a.yaml",
]


class RemoteError(RuntimeError):
    pass


def _ssh(cmd: str, stdin: bytes | None = None, timeout: float = 3600) -> subprocess.CompletedProcess:
    args = [SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30", "-i", KEY, HOST, cmd]
    return subprocess.run(args, input=stdin, capture_output=True, timeout=timeout)


def sh(cmd: str, timeout: float = 3600, stdin: bytes | None = None) -> str:
    """在 Linux 上执行 shell 命令，返回 stdout；非零退出码抛 RemoteError。"""
    r = _ssh(cmd, stdin=stdin, timeout=timeout)
    if r.returncode != 0:
        raise RemoteError(f"remote command failed ({r.returncode}): {cmd}\n--- stderr ---\n"
                          f"{r.stderr.decode(errors='replace')[-4000:]}\n--- stdout ---\n{r.stdout.decode(errors='replace')[-2000:]}")
    return r.stdout.decode(errors="replace")


def py(args: str, timeout: float = 3600) -> str:
    """在 Linux 的 code 目录下用 venv 的 python 执行（args 如 'v2/femur_real.py --build'）。"""
    return sh(f"cd ~/{RBASE}/code && ~/{RBASE}/run.sh {args}", timeout=timeout)


def launch(name: str, args: str) -> str:
    """在 Linux 上以 nohup 常驻方式启动 `run.sh <args>`，日志 ~/mobo_toy_v2/logs/<name>.log，pid 写 <name>.pid；
    已在运行则不重复启动。`&` 只作用于 nohup 本身，ssh 立即返回。"""
    L = f"~/{RBASE}/logs"
    cmd = (f"mkdir -p {L}; cd ~/{RBASE}/code; P={L}/{name}.pid; "
           f"if [ -f $P ] && kill -0 $(cat $P) 2>/dev/null; then echo \"{name} already running pid $(cat $P)\"; "
           f"else nohup ~/{RBASE}/run.sh {args} > {L}/{name}.log 2>&1 < /dev/null & echo $! > $P; "
           f"echo \"{name} started pid $(cat $P)\"; fi")
    return sh(cmd, timeout=60).strip()


def _files() -> list[pathlib.Path]:
    out = []
    for pat in SYNC:
        out += sorted(p for p in ROOT.glob(pat) if p.is_file())
    return out


def code_hash(files: list[pathlib.Path] | None = None) -> str:
    h = hashlib.sha256()
    for p in files or _files():
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def git_head() -> str:
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "v2"], capture_output=True, text=True)
    return r.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def sync_code() -> dict:
    """把 SYNC 列表中的文件打包推到 ~/mobo_toy_v2/code，并写 VERSION（git 提交 + 代码哈希）。"""
    files = _files()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for p in files:
            tf.add(p, arcname=p.relative_to(ROOT).as_posix())
        ver = f"git={git_head()}\ncode_hash={code_hash(files)}\nsynced={time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode()
        ti = tarfile.TarInfo("VERSION"); ti.size = len(ver)
        tf.addfile(ti, io.BytesIO(ver))
    sh(f"mkdir -p ~/{RBASE}/code && tar -xf - -C ~/{RBASE}/code", stdin=buf.getvalue(), timeout=300)
    return {"n_files": len(files), "code_hash": code_hash(files), "git": git_head()}


def put(local: pathlib.Path, remote_dir: str, timeout: float = 600) -> None:
    """推一个本地文件到 Linux 的 ~/mobo_toy_v2/<remote_dir>/（同名覆盖）。"""
    data = pathlib.Path(local).read_bytes()
    sh(f"mkdir -p ~/{RBASE}/{remote_dir} && cat > ~/{RBASE}/{remote_dir}/'{pathlib.Path(local).name}'", stdin=data, timeout=timeout)


def fetch(remote_rel: str, local_dir: pathlib.Path, timeout: float = 1800) -> list[str]:
    """把 ~/mobo_toy_v2/<remote_rel>（文件或目录）取回到 local_dir 下，返回解出的成员名。"""
    parent, name = remote_rel.rsplit("/", 1) if "/" in remote_rel else ("", remote_rel)
    r = _ssh(f"tar -cf - -C ~/{RBASE}/{parent} '{name}'", timeout=timeout)
    if r.returncode != 0:
        raise RemoteError(f"fetch failed: {remote_rel}\n{r.stderr.decode(errors='replace')[-2000:]}")
    local_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout), mode="r") as tf:
        names = tf.getnames()
        tf.extractall(local_dir, filter="data")
    return names


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["sync"]:
        print(sync_code())
    elif sys.argv[1:2] == ["py"]:
        print(py(" ".join(sys.argv[2:])), end="")
    elif sys.argv[1:2] == ["sh"]:
        print(sh(" ".join(sys.argv[2:])), end="")
    else:
        print("usage: remote.py sync | py <args> | sh <cmd>")
