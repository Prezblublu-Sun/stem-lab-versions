"""来历：一个动作在执行的那一刻，用的是哪一版代码、哪些输入。只读 git 和输入文件，不写任何文件。

    import provenance
    rec = provenance.record("judge", {"gates": gp, "rows": bd / "rows.json", "db_manifest": db / "manifest.json"})

    rec = {"action": "judge", "utc": "...Z",
           "git": {"commit": 40 位, "branch": ..., "n_dirty": n, "dirty": ["M ops/judge.py", "?? ops/x.py", ...]},   # 或 {"error": ...}
           "inputs": {"gates": {"file": "experiments/b33_r2cand/gates.py", "sha256": ...}, "rows": None, ...}}        # None = 没有这个文件

每个动作的记录带着它的输入的 sha256。上一环的产物就是这一环的输入，所以哈希把各环连起来：
判定的 result.json -> 数据版本的 manifest.json 和 scalars.csv -> （导出的记录）-> 批次的 rows.json -> （喂料的记录）。
括号里的两环在 tools/ 和 v2/，现在还没有调这个函数。

dirty 是 git status --porcelain 的原样行（含未跟踪的文件），在写任何产物之前取。最多留 DIRTY_MAX 行，n_dirty 是总数。
取不到 git（不是仓库、没有 git）时不抛异常，git 里只有 error。只用标准库。
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRTY_MAX = 40


def _git(root: pathlib.Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"{type(e).__name__}: {e}"
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).decode("utf-8", "replace").rstrip("\n")


def git_state(root: str | pathlib.Path = ROOT) -> dict:
    """Commit, branch and uncommitted changes of the repo that holds root."""
    root = pathlib.Path(root)
    rc, head = _git(root, "rev-parse", "HEAD")
    if rc:
        return {"error": head[:200]}
    _, branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    rc, por = _git(root, "-c", "core.quotepath=false", "status", "--porcelain")
    if rc:
        return {"commit": head, "branch": branch, "error": por[:200]}
    dirty = [ln.rstrip() for ln in por.splitlines() if ln.strip()]
    return {"commit": head, "branch": branch, "n_dirty": len(dirty), "dirty": dirty[:DIRTY_MAX]}


def file_ref(path: str | pathlib.Path, root: str | pathlib.Path = ROOT) -> dict | None:
    """Name and sha256 of one input file; None when it does not exist."""
    p = pathlib.Path(path).resolve()
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    try:
        name = p.relative_to(pathlib.Path(root).resolve()).as_posix()
    except ValueError:
        name = p.as_posix()
    return {"file": name, "sha256": h.hexdigest()}


def record(action: str, inputs: dict[str, str | pathlib.Path], root: str | pathlib.Path = ROOT) -> dict:
    """The provenance record of one action. Call it before the action writes anything."""
    return {"action": action, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "git": git_state(root),
            "inputs": {k: file_ref(v, root) for k, v in inputs.items()}}


def one_line(rec: dict) -> str:
    """For people: the commit and how many uncommitted changes."""
    g = rec["git"]
    if "commit" not in g:
        return f"代码版本取不到（{g.get('error', '')[:80]}）"
    n = g.get("n_dirty")
    return f"代码 {g['commit'][:7]}" + ("，工作区干净" if n == 0 else f"，有 {n} 处未提交的改动" if n else "，未提交的改动取不到")
