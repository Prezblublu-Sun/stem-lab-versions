"""界面和仪表盘是展示，可以整个重写。所以 tests/ 里固定的测试不能靠它们里面的东西。

除了下面写明的几处约定，tests/ 里的代码不许 import 它们、不许出现它们的模块名或文件夹，也不许经
`python -m stemlab.desk` 去跑命令行。要认得命令叫什么、页面上有什么的测试，放在 tests_free/：界面重写的时候跟着改。
真把它们换一份写法、再把固定的测试跑一遍的那条验收在 tests/swap/ 里（要几分钟，平时的检查不跑）。
"""
from __future__ import annotations

import ast
import re

from tests import helpers
from tests.guard import scan

# 哪些文件可以提到界面和仪表盘，各是为什么
ALLOWED = {
    "tests/guard/test_readonly.py": "页面和命令行只读的约定：模块名、READ_PATHS、READ_COMMANDS、python -m 的入口",
    "tests/guard/test_imports.py": "依赖规则的越界样例要往这几个文件里加一行；这几个文件名是蓝图定的",
    "tests/guard/test_frozen.py": "核对展示层不进固定文件的清单",
    "tests/guard/test_ui_is_free.py": "这条测试自己",
    "tests/plugins/test_bad.py": "给测试插件用的依赖规则里，列着不许插件用的模块",
}
SWAP = "tests/swap/"                                    # 换写法的验收，和它用的替身
WORDS = re.compile(r"stemlab[./\\]desk[./\\]ui|stemlab[./\\]board")
ENTRY = "stemlab.desk"                                  # python -m stemlab.desk：进的是界面的命令行


def leans_on_the_ui(tree, docstrings):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if WORDS.search(node.value) or node.value == ENTRY:
                yield node.lineno, f"字符串里出现了 {node.value[:60]!r}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if WORDS.search(alias.name):
                    yield node.lineno, f"import 了 {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            full = [node.module or ""] + [f"{node.module}.{alias.name}" for alias in node.names]
            for name in full:
                if WORDS.search(name):
                    yield node.lineno, f"import 了 {name}"
                    break


def test_fixed_tests_do_not_lean_on_the_ui_or_the_board():
    hits = scan.scan(helpers.REPO / "tests", helpers.REPO, leans_on_the_ui)
    stray = [str(hit) for hit in hits if hit.file not in ALLOWED and not hit.file.startswith(SWAP)]
    assert stray == [], "固定的测试靠着界面或仪表盘里面的东西，界面就不能随便重写了：\n" + "\n".join(stray)
    assert {hit.file for hit in hits if not hit.file.startswith(SWAP)} <= set(ALLOWED)


def test_the_scan_sees_what_it_should(tmp_path):
    bad = tmp_path / "tests" / "blocks"
    bad.mkdir(parents=True)
    (bad / "test_x.py").write_text(
        '"""stemlab.desk.ui in a docstring is fine."""\n'
        "import subprocess, sys\n"
        "from stemlab.desk.ui import views\n"
        "import stemlab.board.web\n"
        'subprocess.run([sys.executable, "-m", "stemlab.desk", "list"])\n'
        'subprocess.run([sys.executable, "-m", "stemlab.desk.core.watch", "--once"])\n'
        'where = "stemlab/board/page.html"\n', encoding="utf-8")
    hits = scan.scan(tmp_path / "tests", tmp_path, leans_on_the_ui)
    assert [hit.line for hit in hits] == [3, 4, 5, 7], [str(hit) for hit in hits]
