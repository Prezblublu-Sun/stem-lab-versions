"""八条依赖规则：在仓库上都过；每条各造一次越界，各自报错，并说出是哪个文件哪一行。"""
from __future__ import annotations

import shutil

import pytest

from stemlab.contract import layout
from stemlab.desk.core import check

REPO = layout.repo_root()
RULES = {
    1: "1 上层用下层，同层互不相用",
    2: "2 插件只经挂点",
    3: "3 插件只用挂点的门面",
    4: "4 插件互不相用",
    5: "5 核心不认识插件",
    6: "6 仪表盘碰不到任何写的模块",
    7: "7 界面的写只经操作台核心",
    8: "8 操作台核心不用界面",
}

# （破的是第几条，往哪个文件里加一行，加什么，输出里该点名的模块）
# 第五项可以不写：先往另一个文件里加一行，把要验的那条间接的路接上，不靠别的代码正好这样 import 了
VIOLATIONS = [
    (1, "stemlab/contract/kinds.py", "from stemlab.registry import lookup", "stemlab.contract.kinds"),
    (1, "stemlab/registry/lookup.py", "from stemlab.experiments import view", "stemlab.registry.lookup"),
    (1, "stemlab/experiments/view.py", "from stemlab.hooks import load", "stemlab.experiments.view"),
    (1, "stemlab/hooks/load.py", "from stemlab.desk.core import code_state", "stemlab.hooks.load"),
    (1, "stemlab/board/alerts.py", "from stemlab.desk.core import query", "stemlab.board.alerts"),
    (2, "plugins/fea/jobs.py", "from stemlab.contract import hashing", "plugins.fea.jobs"),
    (2, "plugins/opt/select.py", "from stemlab.registry import lookup", "plugins.opt.select"),
    (2, "plugins/recon/review.py", "from stemlab.experiments import log", "plugins.recon.review"),
    (3, "plugins/fea/jobs.py", "from stemlab.hooks import handle", "plugins.fea.jobs"),
    (3, "plugins/surrogate/train.py", "from stemlab.hooks import remote", "plugins.surrogate.train"),
    (3, "plugins/opt/select.py", "from stemlab.hooks.publish import publish", "plugins.opt.select"),
    (4, "plugins/recon/gate.py", "from plugins.fea import outcomes", "plugins.recon.gate"),
    (4, "plugins/surrogate/data.py", "import plugins.opt.feasible", "plugins.surrogate.data"),
    (5, "stemlab/hooks/load.py", "import plugins.fea.plugin", "stemlab.hooks.load"),
    (5, "stemlab/desk/ui/views.py", "from plugins.recon import charts", "stemlab.desk.ui.views"),
    (6, "stemlab/board/experiments.py", "from stemlab.hooks import load", "stemlab.board.experiments"),
    (6, "stemlab/board/experiments.py", "from stemlab.experiments import log", "stemlab.board.experiments"),
    (6, "stemlab/registry/lookup.py", "from stemlab.registry import register", "stemlab.registry.lookup",
     ("stemlab/board/experiments.py", "from stemlab.registry import lookup")),      # 间接的也算：仪表盘 → 登记的读模块 → 写模块
    (7, "stemlab/desk/ui/views.py", "from stemlab.hooks import publish", "stemlab.desk.ui.views"),
    (7, "stemlab/desk/ui/web.py", "from stemlab.registry import register", "stemlab.desk.ui.web"),
    (8, "stemlab/desk/core/query.py", "from stemlab.desk.ui import views", "stemlab.desk.core.query"),
]


def broken(output: str) -> set[int]:
    return {number for number, name in RULES.items() if f"{name} BROKEN" in output}


def test_the_repo_keeps_all_eight_rules():
    ok, output = check.lint_imports()
    assert ok, output
    assert all(f"{name} KEPT" in output for name in RULES.values()), output
    assert "Contracts: 8 kept, 0 broken." in output


@pytest.fixture(scope="module")
def copy(tmp_path_factory):
    """仓库里参加依赖检查的那部分的一份拷贝，在它上面造越界。"""
    root = tmp_path_factory.mktemp("lint") / "repo"
    ignore = shutil.ignore_patterns("__pycache__")
    for name in ("stemlab", "plugins"):
        shutil.copytree(REPO / name, root / name, ignore=ignore)
    shutil.copy(REPO / ".importlinter", root / ".importlinter")
    return root


@pytest.mark.parametrize("violation", VIOLATIONS, ids=[f"{v[0]}-{v[1]}-{v[2].split()[-1]}" for v in VIOLATIONS])
def test_each_rule_reports_its_own_violation(copy, monkeypatch, violation):
    rule, rel, line, module = violation[:4]
    planted = [(copy / rel, line)] + [(copy / first, text) for first, text in violation[4:5]]
    kept = [(path, path.read_bytes()) for path, _ in planted]
    before = kept[0][1]
    for (path, text), (_, content) in zip(planted, kept):
        path.write_bytes(content + f"\n{text}\n".encode("utf-8"))
    monkeypatch.setenv("STEMLAB_REPO", str(copy))
    try:
        ok, output = check.lint_imports()
    finally:
        for path, content in kept:
            path.write_bytes(content)
    assert not ok, f"往 {rel} 里加了“{line}”，依赖规则应该不过"
    assert rule in broken(output), output
    line_number = before.count(b"\n") + 2
    assert f"{module} -> " in output and f"(l.{line_number})" in output, "要说出是哪个文件哪一行：\n" + output
