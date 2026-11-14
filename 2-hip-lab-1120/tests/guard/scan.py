"""源码扫描。用 ast 看代码本身，所以注释和文档字符串里提到不算。

扫描是为了发现写得粗糙的代码，不是防恶意代码。每一处都报出是哪个文件哪一行。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# 两条链和 data/ 下别的文件的名字；data/ 里的路径；改 data/ 位置的环境变量
DATA_WORDS = re.compile(
    r"register\.jsonl|record\.jsonl|links\.jsonl|issued\.jsonl|backup\.json|\.lock$"
    r"|(^|[\\/])data[\\/]|(^|[\\/])(registry|experiments)[\\/]|STEMLAB_DATA")

# 实验的状态、轮的结局、任务的状态。别的块不许拿它们做判断
STATE_NAMES = {"none", "new", "starting", "running", "ended", "done", "failed", "stopped", "start_failed", "queued"}
STATE_CONSTANTS = {"NONE", "NEW", "STARTING", "RUNNING", "ENDED", "DONE", "FAILED", "STOPPED", "START_FAILED",
                   "T_QUEUED", "T_RUNNING", "T_DONE", "T_FAILED", "T_STOPPED"}


@dataclass(frozen=True)
class Hit:
    file: str       # 相对路径，正斜杠
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} {self.what}"


def python_files(root: Path) -> list[Path]:
    """root 下全部的 .py 文件；root 自己是一个文件时就是它。root 不存在是写错了路径，直接报错。"""
    root = Path(root)
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise FileNotFoundError(f"要扫描的地方不存在：{root}")
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join(reversed(parts + [node.id]))
    return None


def scan(root: Path, base: Path, check) -> list[Hit]:
    """对 root 下每个 .py 文件叫 check(tree, docstrings)，它给出（行号，说明）。路径相对 base 写。"""
    hits = []
    for path in python_files(root):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        rel = path.relative_to(base).as_posix()
        hits += sorted((Hit(rel, line, what) for line, what in check(tree, _docstrings(tree))),
                       key=lambda hit: (hit.line, hit.what))
    return hits


def strings_matching(pattern: re.Pattern):
    """代码里的字符串常量（不含文档字符串）里出现了 pattern。"""
    def check(tree, docstrings):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if pattern.search(node.value):
                    yield node.lineno, f"字符串里出现了 {pattern.search(node.value).group(0)!r}"
    return check


def mentions(identifier: str):
    """代码里用到了这个名字：变量、属性，或 import 进来的名字。"""
    def check(tree, docstrings):
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == identifier:
                yield node.lineno, f"用到了 {identifier}"
            elif isinstance(node, ast.Attribute) and node.attr == identifier:
                yield node.lineno, f"用到了 {_dotted(node) or identifier}"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if identifier in (alias.name.split(".")[-1], alias.asname):
                        yield node.lineno, f"import 了 {alias.name}"
    return check


def imports(modules):
    """import 了这些模块里的某一个（写全名，比如 stemlab.registry.register）。"""
    wanted = set(modules)

    def check(tree, docstrings):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            for name in names:
                if name in wanted:
                    yield node.lineno, f"import 了 {name}"
    return check


def calls_os_kill(tree, docstrings):
    """用到了 os.kill。在 Windows 上它不是探测，会把进程杀掉。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _dotted(node) in ("os.kill", "os.killpg"):
            yield node.lineno, f"用到了 {_dotted(node)}"
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name in ("kill", "killpg"):
                    yield node.lineno, f"从 os import 了 {alias.name}"


def words(names):
    """代码里的名字或字符串常量里出现了这些词（整词）。"""
    pattern = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z0-9_])")

    def check(tree, docstrings):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                found = pattern.search(node.value)
            elif isinstance(node, ast.Name):
                found = pattern.fullmatch(node.id)
            elif isinstance(node, ast.Attribute):
                found = pattern.fullmatch(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                found = next((m for alias in node.names for m in [pattern.search(alias.name)] if m), None)
                found = found or (pattern.search(node.module or "") if isinstance(node, ast.ImportFrom) else None)
            else:
                continue
            if found:
                yield node.lineno, f"出现了 {found.group(1)!r}"
    return check


def _state_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in STATE_NAMES:
        return repr(node.value)
    if isinstance(node, ast.Attribute) and node.attr in STATE_CONSTANTS:
        return _dotted(node) or node.attr
    if isinstance(node, ast.Name) and node.id in STATE_CONSTANTS:
        return node.id
    return None


def judges_states(tree, docstrings):
    """拿状态名做判断：和状态名（字符串，或契约里的状态常量）比较，或者按它分支。

    拿状态常量去写一条条目不算判断；问 states.can 也不算。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                for value in (side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]):
                    if _state_name(value):
                        yield node.lineno, f"和状态名 {_state_name(value)} 做了比较"
        elif isinstance(node, ast.match_case) and isinstance(node.pattern, ast.MatchValue):
            if _state_name(node.pattern.value):
                yield node.pattern.value.lineno, f"按状态名 {_state_name(node.pattern.value)} 分了支"
