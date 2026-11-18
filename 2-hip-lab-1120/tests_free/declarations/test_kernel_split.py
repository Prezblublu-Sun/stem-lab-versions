"""拆内核 4b：照现在的设定写的声明。

    external/stem_m1_3406/declarations.py   柄空间 M1 的设计项（design）和放置设定（placement）
    external/fem_abaqus/declarations.py     Abaqus 有限元包的 fem
    plugins/fea/running.py                  fea.run 的运行设定

每份声明过 A 批的规矩，拼出的测试轮设定过核验；原内核清单里的设计项和条件、导出设定里的各项都有着落；
测试轮的取值就是旧数据库里设计 A 用的那一组。external/ 不在检查的范围里，所以测试放在这里。
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

from plugins.fea import export, running
from stemlab.contract.formats import bone_model
from stemlab.contract.formats import declaration as d
from stemlab.contract.formats import package
from tests.science.test_fea import CONDITIONS, A

REPO = Path(__file__).resolve().parents[2]
# 3406 的骨模型（第 1 版）和柄的模型里会有的名字：骨模型的两个实体、必有的五个标志点；柄空间包答应给的面组
# （4d 的有限元声明多引用了小转子，远端截断从它那一层量起，所以标志点从只写头心改成必有的五个）
NAMES = {"bone.region": {"cortical", "cancellous"}, "bone.landmark": set(bone_model.LANDMARKS), "stem.faces": {"interface"}}


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEM = _load("external/stem_m1_3406/declarations.py", "stem_m1_3406_declarations")
FEM = _load("external/fem_abaqus/declarations.py", "fem_abaqus_declarations")
KERNEL = _load("external/kernel_m1_3406/build.py", "kernel_m1_3406_build")


def items(declaration: dict) -> dict:
    return {item["name"]: item for item in declaration["items"]}


def test_every_declaration_keeps_the_rules():
    for one in (*STEM.DECLARATIONS, *FEM.DECLARATIONS, running.DECLARATION):
        assert d.check_declaration(one) == [], one["name"]
    assert package._declarations("stem_space", STEM.DECLARATIONS) == [], "柄空间包要的两份都在，设计项都由一批点逐个给"
    assert package._declarations("fem", FEM.DECLARATIONS) == []


def test_the_test_round_settings_can_be_put_together():
    for one, of in ((STEM.PLACEMENT, "R0001"), (FEM.FEM, "R0002"), (running.DECLARATION, "fea.run")):
        setting = d.test_setting(one, of)
        assert d.check_setting(setting, one, of=of, use="test", names=NAMES) == [], one["name"]
    assert d.check_design({name: item["test"] for name, item in items(STEM.DESIGN).items()}, STEM.DESIGN) == []


def test_what_the_old_kernel_took_is_all_declared():
    design = {column["name"] for column in KERNEL.EXTRA["design"]}
    conditions = {column["name"] for column in KERNEL.EXTRA["conditions"]}
    assert design == set(items(STEM.DESIGN)) | {"h_cut", "e"}, "原内核的 14 个设计项：12 个是柄的形状，截骨高度和入口偏移挪到放置设定"
    assert {"h_cut", "e"} <= set(items(STEM.PLACEMENT)) and items(STEM.PLACEMENT)["h_cut"]["per_point"]
    fem = items(FEM.FEM)
    assert conditions <= set(fem) and all(fem[name]["per_point"] for name in conditions), "原来的 8 个条件都在，每个点都能变"
    assert all(not item["per_point"] for name, item in fem.items() if name not in conditions), "别的是写死的建模、求解设置"
    run = items(running.DECLARATION)
    assert set(export.RUN_KEYS) | {"derive_timeout_s", "archive_root"} == set(run), "导出设定里只管怎么跑的几项，都进了运行设定"
    assert all(not item["per_point"] for item in run.values())


def test_the_test_round_is_design_A_with_its_conditions():
    """测试轮的取值就是旧数据库 v0.14 里设计 A（sb13_a105_91e458e3）用的那一组：拆完以后测试轮算的是同一个点。"""
    shape = {name: value for name, value in A.items() if name not in ("h_cut", "e")}
    assert {name: item["test"] for name, item in items(STEM.DESIGN).items()} == shape
    placement = d.test_setting(STEM.PLACEMENT, "R0001")["values"]
    assert placement["h_cut"] == A["h_cut"] and placement["entry"] == "rule" and A["e"] == "rule" and "e" not in placement, \
        "e 写的是 rule：在几档偏移里选，测试轮的设定里就没有 e"
    assert [placement[name] for name in ("offset_min_mm", "offset_max_mm", "offset_step_mm")] == [-8.0, 8.0, 2.0], "九档"
    assert math.isclose(math.pi * placement["neck_radius_mm"] ** 2, KERNEL_MIN_A0), "原来的最小肩部面积照假体颈的半径算得出"
    fem = d.test_setting(FEM.FEM, "R0002")["values"]
    assert {name: fem[name] for name in CONDITIONS} == CONDITIONS
    assert fem["elastic_slip_um"] / 1000.0 / fem["h_int_mm"] == 0.00025, "原来不写 slip_tol 时，界面网格 2 mm 用的就是 0.00025"


KERNEL_MIN_A0 = math.pi * 7.0 ** 2          # external/kernel_m1_3406/main.py 的 FIXED["min_A0"]


def test_the_old_conditions_given_point_by_point_pass():
    setting = d.test_setting(FEM.FEM, "R0002")
    setting["values"].update({name: dict(d.PER_POINT) for name in CONDITIONS})
    assert d.check_setting(setting, FEM.FEM, names=NAMES) == [], "名字引用指向的是 3406 的骨模型和柄的模型里会有的名字"
    assert d.check_point(CONDITIONS, setting, FEM.FEM) == []
    assert any("规则 5" in text for text in d.check_point(dict(CONDITIONS, h_int_mm=8.0), setting, FEM.FEM)), \
        "界面处的网格不能比远处的还粗"
