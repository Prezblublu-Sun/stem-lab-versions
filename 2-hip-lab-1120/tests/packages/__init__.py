"""测试用的带代码的包：假的内核、假的推导量定义、示例策略等。

每个子文件夹是一个包的内容（code/、data/），清单在登记前由 make() 现写。
它们照 contract/formats/package.py 里写的约定和插件说话，所以真插件可以不用真的求解器走通一遍。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from stemlab.contract import hashing
from stemlab.contract.formats.manifest import make_manifest, write_manifest

HERE = Path(__file__).resolve().parent
COLUMN = ("name", "unit", "meaning")


def columns(*rows) -> list[dict]:
    return [dict(zip(COLUMN, row)) for row in rows]


EXTRAS = {
    "kernel_fake": {
        "kind": "kernel",
        "modes": ["template", "build", "post"],
        "design": columns(("length", "mm", "stem length"), ("behave", "1", "how the fake kernel behaves for this design")),
        "conditions": columns(("load", "N", "head load")),
        "pre": columns(("bone_removed", "mm3", "bone removed, known from templating")),
        "labels": columns(("rotation", "deg", "rotation under the first load"), ("contact", "1", "closed share of the interface")),
        "fields": columns(("interface_slip", "um", "slip at each interface node")),
    },
    "derive_fake": {
        "kind": "derive_def",
        "needs": ["interface_slip"],
        "columns": columns(("slip_p95", "um", "95th percentile of the interface slip")),
    },
    "strategy_fake": {"kind": "strategy", "needs": [], "behave": "best"},
    "strategy_longest": {"kind": "strategy", "needs": []},
}


def make(name: str, target: Path, **change) -> Path:
    """把 tests/packages/<name> 抄到 target，写上清单，返回 target。change 盖掉清单里的同名项。"""
    shutil.copytree(HERE / name, target, ignore=shutil.ignore_patterns("__pycache__"))
    files = hashing.list_tree(target)
    extra = dict(EXTRAS[name])
    kind = extra.pop("kind")
    samples = sorted({rel.split("/")[2] for rel in files if rel.startswith("data/selftest/")})
    listed = {
        "entry": ["{python}", "code/main.py"], "requires": ["python>=3.12"], "tolerance": {"rel": 1e-9, "abs": 1e-12},
        "selftest": [{"name": sample, "input": f"data/selftest/{sample}/input",
                      "expected": f"data/selftest/{sample}/expected.json"} for sample in samples],
    }
    write_manifest(target, make_manifest(kind, files, **{**listed, **extra, **change}))
    return target
