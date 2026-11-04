"""Claude Code PreToolUse 钩子：挡住对冻结文件的写入。退出码 2 = 拒绝并把原因交给 agent；0 = 放行。

注册（项目级 .claude/settings.json 已写；用户级要自己加）：
  {"hooks": {"PreToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
             "hooks": [{"type": "command", "command": "python", "args": ["<repo>/ops/guard_pretooluse.py"]}]}]}}
输入：stdin 一个 JSON，含 tool_name、tool_input（Write/Edit 有 file_path；Bash 有 command）。
只看路径，不看内容；路径在仓库之外一律放行。只用标准库。

挡什么：
  1. 8 个哈希文件（docs/freeze/M1-3406-v1.json 列的）；
  2. docs/freeze/ 下的冻结清单和 tar；
  3. experiments/<批次>/gates.py 在同目录出现 approval.md 之后（判据冻结）；
  4. Bash 命令里出现对上述路径的 rm / mv / 重定向写（粗匹配）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def frozen_paths() -> list[pathlib.Path]:
    out = [ROOT / "docs" / "freeze"]
    fz = ROOT / "docs" / "freeze" / "M1-3406-v1.json"
    if fz.exists():
        try:
            for rel in json.loads(fz.read_text(encoding="utf-8"))["hashed_files"]:
                out.append(ROOT / rel)
        except Exception:  # noqa: BLE001
            pass
    exp = ROOT / "experiments"
    if exp.exists():
        for d in exp.iterdir():
            if (d / "approval.md").exists() and (d / "gates.py").exists():
                out.append(d / "gates.py")
    return out


def is_under(p: pathlib.Path, base: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def deny(msg: str) -> None:
    print(f"[guard] 拒绝：{msg}。冻结文件不能改；要换版本先写 ADR（docs/adr/），见 AGENTS.md 红线 1、3。", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    frozen = frozen_paths()
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if not fp:
            return
        p = pathlib.Path(fp)
        for f in frozen:
            if (f.is_dir() and is_under(p, f)) or (not f.is_dir() and p.resolve() == f.resolve()):
                deny(f"{tool} 想写 {fp}")
        return
    if tool == "Bash":
        cmd = inp.get("command", "") or ""
        names = [f.name for f in frozen if not f.is_dir()] + ["docs/freeze", "docs\\freeze"]
        writes = re.compile(r"(^|[\s;&|(`])(rm|mv|cp|tee|truncate|sed\s+-i|perl\s+-i|unix2dos|dos2unix|git\s+checkout|git\s+restore)\s|>")
        for n in names:
            if n in cmd and writes.search(cmd):
                deny(f"Bash 命令涉及冻结文件 {n}（命令里有写、删、改名或重定向）")
    return


if __name__ == "__main__":
    main()
