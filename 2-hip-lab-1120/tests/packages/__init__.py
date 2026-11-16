"""测试用的带代码的包：假的内核、假的推导量定义、示例策略、假的柄空间、假的有限元等。

每个子文件夹是一个包的内容（code/、data/），清单在登记前由 make() 现写。
它们照 contract/formats/package.py 里写的约定和插件说话，所以真插件可以不用真的求解器走通一遍。
假的柄空间和假的有限元是拆内核以后 fea.run 那条路用的，它们的声明在下面（STEM_DESIGN 等），测试照它们写设定。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from stemlab.contract import hashing
from stemlab.contract.formats.manifest import make_manifest, write_manifest

HERE = Path(__file__).resolve().parent
COLUMN = ("name", "unit", "meaning")
SOURCE = "测试用的假包"


def columns(*rows) -> list[dict]:
    return [dict(zip(COLUMN, row)) for row in rows]


def outputs(*rows) -> list[dict]:
    return [dict(zip(COLUMN + ("role",), row)) for row in rows]


def item(name: str, group: str, kind: str, test, per_point: bool = False, required: bool = True, **more) -> dict:
    """声明里的一项。叫法和含义都写成名字：测试只看规矩。"""
    return {"name": name, "label": name, "meaning": f"{name}（测试）", "group": group, "type": kind,
            "per_point": per_point, "required": required, "test": test, "test_source": SOURCE, **more}


BEHAVES = ("ok", "misfit", "stem_env", "stem_crash", "badmodel", "noname", "mesh", "diverge", "loose", "crash", "env",
           "flaky", "hang")
STEM_DESIGN = {"name": "design", "groups": ["柄的形状"], "items": [
    item("length", "柄的形状", "number", 30.0, per_point=True, unit="mm", range={"min": 10, "max": 100}),
    item("behave", "柄的形状", "choice", "ok", per_point=True, choices=[{"value": v, "label": v} for v in BEHAVES])]}
STEM_PLACEMENT = {"name": "placement", "groups": ["截骨"], "items": [
    item("cut_drop", "截骨", "number", 0.0, per_point=True, unit="mm", range={"min": 0, "max": 20}),
    item("entry", "截骨", "choice", "rule", choices=[{"value": "rule", "label": "照规则"}, {"value": "fixed", "label": "照设计"}])]}
FEM = {"name": "fem", "groups": ["载荷", "作业和求解控制"], "items": [
    item("load", "载荷", "number", 2000.0, per_point=True, unit="N", range={"min": 0, "max": 10000}),
    item("load_point", "载荷", "ref", {"ref": "bone.landmark.head_center"}, refers=["stem.feature", "bone.landmark"]),
    item("seconds", "作业和求解控制", "number", 0.0, unit="s", range={"min": 0, "max": 600}),
    item("build_seconds", "作业和求解控制", "number", None, required=False, unit="s", range={"min": 0, "max": 600})]}
DERIVE = {"name": "derive", "groups": ["分区"], "items": [
    item("zones", "分区", "integer", 7, per_point=True, range={"min": 1, "max": 14}),
    item("where", "分区", "ref", {"ref": "stem.faces.interface"}, refers=["stem.faces"])]}
STEM_NAMES = {"region": ["body"], "faces": ["interface"], "feature": ["taper_center", "tip"], "axis": ["stem_axis"]}


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
    "stem_fake": {
        "kind": "stem_space",
        "programs": [],
        "declarations": [STEM_DESIGN, STEM_PLACEMENT],
        "modes": ["template", "model"],
        "inputs": {"bone": {"landmarks": ["head_center"]}},
        "outputs": outputs(("bone_removed", "mm3", "bone removed, known from templating", "pre")),
        "test_round": {"inputs": {"bone": {"folder": "data/selftest/template/input"}}},
        "names": STEM_NAMES,
    },
    "fem_fake": {
        "kind": "fem",
        "programs": [{"name": "fake-solver", "version": "1.0"}],
        "declarations": [FEM],
        "modes": ["build", "post"],
        "inputs": {"bone": {}},
        "outputs": outputs(("n_nodes", "1", "nodes in the mesh", "pre"), ("rotation", "deg", "rotation under the first load", "label"),
                           ("contact", "1", "closed share of the interface", "label"),
                           ("interface_slip", "um", "slip at each interface node", "field")),
        "test_round": {"inputs": {"bone": {"folder": "data/selftest/post/input"}}},
    },
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
