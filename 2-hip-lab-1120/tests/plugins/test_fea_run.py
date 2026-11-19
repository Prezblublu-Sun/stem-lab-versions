"""fea.run 的验收（拆内核 4a）：柄空间包加有限元包，有植入物、无植入物都走得通。

核心核过的设定（第 1 到 5、7、9 条），骨架再核每个点给的项（第 6 条）、名字引用（第 8 条），
和几份设定照的是不是该照的那份声明。用假的柄空间包、假的有限元包（tests/packages/stem_fake、fem_fake）。
参照包那条（fea.reference）的验收在 test_fea.py，情形本身没改。

骨模型（第 5 步的 5b）：三个包各自在清单的 inputs.bone 里写对骨模型的要求，骨架启动前照它核，自己不挑骨；
交给包的骨模型清单一律是读成第 2 版的那一份（job 的 bone），盘上是第 1 版的也一样。见最后一组。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.fea import running
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.contract.hashing import hash_json, is_hash
from stemlab.desk.core import start
from stemlab.experiments import view
from stemlab.hooks import load
from stemlab.registry import lookup
from tests import packages, real
from tests.conftest import FAKE_SOLVER
from tests.plugins.fea_cases import kept, refused, rows_of, stages

P = real.point_run


def finished(made: str):
    assert start.start(made).ok
    real.run(made)
    return view.view(made)


def deck(made: str, task: str) -> dict:
    """归档里这个作业交给假求解器的输入：假有限元包照柄的模型、骨模型解开名字引用，写在里面。"""
    root = Path(read_manifest(real.output(made, "archive"))["root"])
    row = next(row for row in read_points(real.output(made, "archive") / "index.jsonl")
               if row["task"] == task and row["file"].endswith("/deck.json"))
    return json.loads((root / row["file"]).read_bytes())


# ---- 两种实验，输入表不同 ----

def test_two_kinds_one_flow(real_lab):
    loaded = load.load()
    run, reference = loaded.kinds["fea.run"], loaded.kinds["fea.reference"]
    assert [row.name for row in reference.inputs] == ["bone", "points", "kernel", "derive", "export", "criteria"], \
        "参照包那条的输入表和拆内核以前的 fea.run 一样"
    assert [(row.name, row.kinds, row.required) for row in run.inputs] == [
        ("bone", ("bone_model",), True), ("points", ("points",), True), ("stem", ("stem_space",), False),
        ("placement", ("setting",), False), ("fem", ("fem",), True), ("fem_setting", ("setting",), True),
        ("derive", ("derive_def",), True), ("derive_setting", ("setting",), False), ("run", ("setting",), True),
        ("criteria", ("setting",), False)]
    assert run.settings == (running.DECLARATION,) and reference.settings == (), "运行设定由 fea.run 自己声明"
    assert run.outcomes == reference.outcomes and run.outputs == reference.outputs, "结局和产物两种一样"


# ---- 1 有植入物：三个点各走完出柄的模型、建模、求解、后处理 ----

def test_three_points_through_a_stem_space_and_an_fe_package(real_lab, data, tmp_path):
    rows = [P("p1", 30, placement={"cut_drop": 0.0}), P("p2", 40, placement={"cut_drop": 1.0}), P("p3", 50, placement={"cut_drop": 2.0})]
    made = real.fea_run(tmp_path, rows, placement={"cut_drop": real.PER_POINT})
    assert start.start(made).ok
    assert real.tasks(made) == {name: ("queued", None) for name in ("p1", "p2", "p3")}
    real.run(made)
    status = view.view(made)
    assert (status.rounds[-1].result, status.rounds[-1].problems) == ("done", [])
    assert real.tasks(made) == {name: ("done", "finished") for name in ("p1", "p2", "p3")}
    for name in ("p1", "p2", "p3"):
        assert [stage for stage in stages(made, name) if stage != "modeled"] == ["stem", "build", "solve", "post"], stages(made, name)
        assert is_hash(status.tasks[name].fingerprint)
    assert len({status.tasks[name].fingerprint for name in ("p1", "p2", "p3")}) == 3

    assert check_format("data", real.output(made, "data")) == [] and check_format("archive", real.output(made, "archive")) == []
    manifest = read_manifest(real.output(made, "data"))
    assert [(column["name"], column["role"], column["unit"]) for column in manifest["columns"]] == [
        ("length", "design", "mm"), ("behave", "design", "1"), ("load", "condition", "N"), ("cut_drop", "condition", "mm"),
        ("bone_removed", "pre", "mm3"), ("n_nodes", "pre", "1"), ("rotation", "label", "deg"), ("contact", "label", "1"),
        ("interface_slip", "field", "um"), ("slip_p95", "derived", "um")], "数据说明从两个包的声明和产出拼出来"
    values = rows_of(made)["p2"]["values"]
    assert values == {"length": 40, "behave": "ok", "load": 2000.0, "cut_drop": 1.0, "bone_removed": 4010.0, "n_nodes": 140,
                      "rotation": 2000 / 40000, "contact": 0.5, "slip_p95": 0.95 * 20}, "放置每个点给的值交到了柄空间包"

    frozen = status.frozen
    assert manifest["made_by"] == {
        "kernel": None, "stem": {"package": frozen["stem"][0]["hash"]}, "fem": {"package": frozen["fem"][0]["hash"]},
        "derive": {"package": frozen["derive"][0]["hash"]},
        "settings": {"placement": hash_json({"entry": "rule"}),
                     "fem": hash_json({"load_point": {"ref": "stem.feature.taper_center"}, "seconds": 0.0}), "derive": None},
        "bones": {real.BONE: {"id": frozen["bone"][0]["id"], "hash": frozen["bone"][0]["hash"]}}, "predictions": []}, \
        "记柄空间包、有限元包和三份设定里所有点都一样的那部分；运行设定不进来"
    assert deck(made, "p3")["load_point"] == [0.0, 0.0, 50.0] and deck(made, "p3")["implant"], \
        "有限元包拿到了柄的模型，照名字引用找到了锥头中心"
    files = kept(made, "p1")
    assert {"stem_model.json", "body.step", "interface.stl", "deck.json"} <= files["settings"], "交出的柄的模型也归档"
    assert {"stem-result.json", "stem-log.txt", "build-result.json", "post-result.json", "derive-result.json"} <= files["process"]
    used = sorted(extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package")
    assert used == ["derive_def", "fem", "stem_space"], "用了哪三个包，核心记进了这一轮的来历"


# ---- 2 无植入物：不填柄空间包，设计和放置两组是空的 ----

def test_no_implant(real_lab, data, tmp_path):
    rows = [P("b1", load=1000.0, implant=False), P("b2", load=2000.0, implant=False)]
    made = real.fea_run(tmp_path, rows, implant=False)
    status = finished(made)
    assert real.tasks(made) == {"b1": ("done", "finished"), "b2": ("done", "finished")}, status.rounds[-1].problems
    assert stages(made, "b1") == ["build", "solve", "post"], "没有出柄的模型这一步"
    manifest = read_manifest(real.output(made, "data"))
    assert [column["name"] for column in manifest["columns"]] == ["load", "n_nodes", "rotation", "contact", "interface_slip", "slip_p95"]
    assert rows_of(made)["b2"]["values"] == {"load": 2000.0, "n_nodes": 120, "rotation": 2000 / 20000, "contact": 0.5,
                                             "slip_p95": 0.95 * 10}
    made_by = manifest["made_by"]
    assert made_by["stem"] == "none" and made_by["kernel"] is None and made_by["settings"]["placement"] is None, "无植入物写明“无”"
    assert deck(made, "b1")["load_point"] == real.BONE_EXTRA["landmarks"]["head_center"]["xyz"] and not deck(made, "b1")["implant"], \
        "名字引用指向骨模型的标志点"


# ---- 3 柄空间包说的，决定结局 ----

def test_what_the_stem_space_says_decides_the_outcome(real_lab, data, tmp_path):
    rows = [P("ok", 30), P("long", 80), P("env", 31, "stem_env"), P("bad", 32, "badmodel"), P("noname", 33, "noname"),
            P("crash", 34, "stem_crash")]
    made = real.fea_run(tmp_path, rows)
    status = finished(made)
    assert real.tasks(made) == {"ok": ("done", "finished"), "long": ("done", "misfit"), "env": ("failed", "env"),
                                "bad": ("failed", "error"), "noname": ("failed", "error"), "crash": ("failed", "error")}
    said = {problem["task"]: problem["error"] for problem in status.rounds[-1].problems if problem["task"]}
    assert "不合格式" in said["bad"] and "taper_center" in said["noname"] and "没有留下结果" in said["crash"]
    assert stages(made, "bad") == ["stem"] and stages(made, "long") == ["stem"], "柄的模型不对、放不进去的，不再去建模"
    rows_ = rows_of(made)
    assert sorted(rows_) == ["long", "ok"], "放不进去是结论，进数据；别的不进"
    assert rows_["long"]["values"] == {"length": 80, "behave": "ok", "load": 2000.0, "bone_removed": None, "n_nodes": None,
                                       "rotation": None, "contact": None, "slip_p95": None}


# ---- 4 第 6 条：每个点给的项，启动前核 ----

@pytest.mark.parametrize("why,rows,change,said", [
    ("设定说每个点给，点没给", [dict(P("p1"), conditions={})], {}, ["规则 6", "'load'"]),
    ("设定没说每个点给，点给了", [dict(P("p1"), conditions={"load": 2000.0, "seconds": 1.0})], {}, ["规则 6", "'seconds'"]),
    ("每个点给的值超出范围", [P("p1", load=-5.0)], {}, ["规则 4", "'load'"]),
    ("设计项没写全", [dict(P("p1"), design={"length": 30.0})], {}, ["规则 6", "'behave'"]),
    ("设计项的值不在可选的里", [P("p1", behave="dance")], {}, ["规则 4", "'behave'"]),
    ("放置每个点给，点没给", [P("p1")], {"placement": {"cut_drop": real.PER_POINT}}, ["规则 6", "'cut_drop'"]),
    ("骨标识和骨模型不一致", [P("p1", bone_id="femur043")], {}, ["femur043"]),
])
def test_rule_6_what_each_point_gives_is_checked_before_the_start(real_lab, data, tmp_path, why, rows, change, said):
    text = refused(real.fea_run(tmp_path, rows, **change))
    assert all(part in text for part in said), f"{why}：{text}"


def test_without_an_implant_the_design_and_placement_are_empty(real_lab, data, tmp_path):
    text = refused(real.fea_run(tmp_path, [P("p1")], implant=False))
    assert "无植入物" in text and "设计项" in text


# ---- 5 第 8 条：名字引用照骨模型和柄空间包说的名字核 ----

@pytest.mark.parametrize("why,implant,where", [
    ("骨模型里没有这个标志点", True, "bone.landmark.nowhere"),
    ("柄空间包没说它交出的柄的模型里有这个点", True, "stem.feature.nowhere"),
    ("无植入物，却引用柄的模型", False, "stem.feature.taper_center"),
])
def test_rule_8_names_must_be_there(real_lab, data, tmp_path, why, implant, where):
    text = refused(real.fea_run(tmp_path, [P("p1", implant=implant)], implant=implant, fem={"load_point": {"ref": where}}))
    assert "规则 8" in text and where in text, f"{why}：{text}"


def test_a_derive_setting_follows_the_derive_package_and_its_names(real_lab, data, tmp_path):
    derive = real.package("derive_fake", tmp_path, declarations=[packages.DERIVE])
    rows = [P("p1", derive={"zones": 7}), P("p2", 40, derive={"zones": 4})]
    made = real.fea_run(tmp_path, rows, packages_={"derive": derive}, derive_setting={"zones": real.PER_POINT})
    finished(made)
    assert real.tasks(made) == {"p1": ("done", "finished"), "p2": ("done", "finished")}
    manifest = read_manifest(real.output(made, "data"))
    assert ("zones", "condition") in [(column["name"], column["role"]) for column in manifest["columns"]]
    assert rows_of(made)["p2"]["values"]["zones"] == 4
    assert manifest["made_by"]["settings"]["derive"] == hash_json({"where": {"ref": "stem.faces.interface"}})

    lost = real.fea_run(tmp_path, rows, packages_={"derive": real.package("derive_fake", tmp_path, declarations=[packages.DERIVE])},
                        derive_setting={"zones": real.PER_POINT, "where": {"ref": "stem.faces.nowhere"}})
    assert "规则 8" in refused(lost)
    missing = real.fea_run(tmp_path, [P("p1")], packages_={"derive": real.package("derive_fake", tmp_path, declarations=[packages.DERIVE])})
    assert "推导量设定要填" in refused(missing)


# ---- 6 几份设定照的是该照的那一份 ----

def test_each_setting_follows_its_own_declaration(real_lab, data, tmp_path):
    stem = real.package("stem_fake", tmp_path)
    assert "放置设定要填" in refused(real.fea_run(tmp_path, [P("p1")], skip=("placement",)))
    no_stem = real.fea_run(tmp_path, [P("p1", implant=False)], implant=False, settings={"placement": {"cut_drop": 0.0}})
    assert "放置设定不该填" in refused(no_stem), "无植入物不填放置设定"
    elsewhere = real.fea_run(tmp_path, [P("p1", implant=False)], implant=False,
                             settings={"placement": real.declared(packages.STEM_PLACEMENT, stem["id"])})
    assert "这个实验没有填它" in refused(elsewhere), "照没填的柄空间包写的放置设定，核心先拒（规则 1）"
    old = real.fea_run(tmp_path, [P("p1")], settings={"fem_setting": {"load": 2000.0}})
    assert "老写法" in refused(old)
    swapped = real.fea_run(tmp_path, [P("p1")], packages_={"stem": stem},
                           settings={"fem_setting": real.declared(packages.STEM_PLACEMENT, stem["id"])})
    assert "fem 声明" in refused(swapped), "有限元设定照的是柄空间包的放置声明"
    undeclared = real.fea_run(tmp_path, [P("p1")], settings={"derive_setting": {"zones": 7}})
    assert "推导量设定不该填" in refused(undeclared), "推导量定义没声明 derive，就不填推导量设定"


def test_the_run_setting_follows_what_fea_run_declares(real_lab, data, tmp_path):
    other = dict(real.declared(running.DECLARATION, "fea.run"))
    assert "规则 1" in refused(real.fea_run(tmp_path, [P("p1")], settings={"run": dict(other, declaration=dict(
        other["declaration"], of="fea.reference"))})), "照别的类型写的运行设定：这个实验没有填它"
    assert "规则 1" in refused(real.fea_run(tmp_path, [P("p1")], settings={"run": dict(other, declaration=dict(
        other["declaration"], hash="0" * 64))})), "声明改过了，旧的运行设定对不上"
    assert "规则 4" in refused(real.fea_run(tmp_path, [P("p1")], run={"build_slots": 0}))
    assert "规则 3" in refused(real.fea_run(tmp_path, [P("p1")], run={"solve_timeout_s": None})), "运行设定也要写全"


# ---- 7 外部程序装在哪：写在机器清单里，照名字和版本交到包手里 ----

def test_the_programs_a_package_needs_come_from_the_machine_list(real_lab, data, tmp_path):
    """包的清单只写要哪个程序哪一版；装在哪写在操作台这台的机器清单里，骨架照名字和版本找到，放进交给包的 job。
    包要的程序这台机器的清单里没有（版本对不上也算没有），启动前就拒，说出是哪个包要的哪个程序哪一版。"""
    made = real.fea_run(tmp_path, [P("p1")])
    finished(made)
    assert real.tasks(made) == {"p1": ("done", "finished")}
    assert deck(made, "p1")["programs"] == {FAKE_SOLVER["name"]: FAKE_SOLVER["path"]}, "有限元包拿到了假求解器在这台机器上的位置"
    newer = real.package("fem_fake", tmp_path, programs=[{"name": "fake-solver", "version": "2.0"}])
    said = refused(real.fea_run(tmp_path, [P("p1")], packages_={"fem": newer}))
    assert "有限元包" in said and "fake-solver 2.0" in said and "机器清单" in said, said
    other = real.package("stem_fake", tmp_path, programs=[{"name": "cad-kernel", "version": "7"}])
    said = refused(real.fea_run(tmp_path, [P("p1")], packages_={"stem": other}))
    assert "柄空间包" in said and "cad-kernel 7" in said, said


# ---- 8 骨模型：包在清单里写要什么，骨架启动前照它核；交给包的清单一律是第 2 版 ----

# 一份写全了的要求，real.bone_v2 的那根骨样样都合：皮质、松质各一块，髓腔有没有都行；STEP、STL 都收；线弹性；
# 两个标志点；完整的股骨，往远端至少到 400 mm；坐标系照后髁连线定
WANT = {"regions": {"cortical": [1, 1], "cancellous": [1, 1], "canal": [0, 1]}, "geometry": ["step", "stl"], "materials": ["elastic"],
        "landmarks": ["head_center", "lesser_trochanter"], "coverage": {"extent": ["whole"], "distal_mm": 400.0},
        "frame": {"methods": ["shaft_condyles"]}, "what": "测试：写全了的一份要求"}
LABELS = {"stem": "柄空间包", "fem": "有限元包", "derive": "推导量定义"}


def wanting(tmp: Path, bone: dict, **wants) -> str:
    """一个 fea.run：三个假包各自在清单里写对骨模型的要求（没给的那个写 WANT），配上这根骨。返回实验的编号。"""
    given = {name: real.package(f"{name}_fake", tmp, inputs={"bone": wants.get(name, WANT)}) for name in LABELS}
    return real.fea_run(tmp, [P("p1")], packages_=given, bone=bone)


def test_a_bone_model_that_has_what_every_package_asks_for_goes_through(real_lab, data, tmp_path):
    """盘上就是第 2 版的骨模型，三个包要的它都有：走得通；清单原样交到包手里，几何文件在 bone_model 那个文件夹里。"""
    made = wanting(tmp_path, real.bone_v2(tmp_path))
    status = finished(made)
    assert real.tasks(made) == {"p1": ("done", "finished")}, status.rounds[-1].problems
    assert deck(made, "p1")["bone"] == {"format": 2, "frame": "shaft_condyles", "regions": {
        "cortical": {"file": "regions/cortical.step", "there": True, "material": "elastic"},
        "cancellous": {"file": "regions/cancellous.stp", "there": True, "material": "elastic"},
        "canal": {"file": "regions/canal.stl", "there": True, "material": None}}}


@pytest.mark.parametrize("why,package,change,said", [
    ("区域的角色：不收髓腔", "fem", {"regions": {"cortical": [1, 1], "cancellous": [1, 1]}}, ["区域", "不收髓腔"]),
    ("区域的个数：要两块皮质", "stem", {"regions": {"cortical": [2, None], "cancellous": [1, 1], "canal": [0, 1]}}, ["至少 2 个皮质"]),
    ("几何文件：只收 STEP，髓腔那一块是 STL", "fem", {"geometry": ["step"]}, ["几何", "'canal' 是 stl"]),
    ("材料模型：只会 neo-Hookean", "derive", {"materials": ["neo_hooke"]}, ["材料", "elastic"]),
    ("标志点：要大转子", "derive", {"landmarks": ["head_center", "greater_trochanter"]}, ["标志点", "greater_trochanter"]),
    ("覆盖范围：要往远端到 500 mm", "stem", {"coverage": {"extent": ["whole"], "distal_mm": 500.0}}, ["覆盖范围", "远端"]),
    ("坐标系的定法：只收照颈轴定的", "fem", {"frame": {"methods": ["shaft_neck"]}}, ["解剖坐标系", "shaft_condyles"]),
    ("要求自己写错：旧写法的 solids", "fem", {"solids": ["cortical", "cancellous"]}, ["写得不对", "solids"]),
])
def test_what_a_package_asks_of_the_bone_model_is_checked_before_the_start(real_lab, data, tmp_path, why, package, change, said):
    """这根骨缺包要的哪一样，启动前被拒，说出是哪个包、缺哪一样；要求自己写错的，说出是哪个包、错在哪。
    每个情形只动一个包的一项，另外两个包要的这根骨都有：它们不被点名。同一根骨配三份没动过的要求走得通（上一条）。"""
    text = refused(wanting(tmp_path, real.bone_v2(tmp_path), **{package: {**WANT, **change}}))
    assert LABELS[package] in text and all(part in text for part in said), f"{why}：{text}"
    assert not [label for name, label in LABELS.items() if name != package and label in text], f"{why}：只该点 {LABELS[package]} 的名：{text}"


def test_the_skeleton_does_not_pick_bones_the_packages_do(real_lab, data, tmp_path):
    """收哪种几何文件由包在自己的清单里写，骨架只照它核：只收 STEP 的有限元包配上三个区域都是 STL 的骨，启动前被拒，
    说出是有限元包不收；同一个包把清单改成也收 STL，同一根骨就走得通。骨架自己没有“只认 STEP”这一条。"""
    bone = real.bone_v2(tmp_path, stl=True)
    step_only = real.package("fem_fake", tmp_path, inputs={"bone": {"geometry": ["step"]}})
    said = refused(real.fea_run(tmp_path, [P("p1")], packages_={"fem": step_only}, bone=bone))
    assert "有限元包" in said and "是 stl" in said and "柄空间包" not in said and "推导量定义" not in said, said
    both = real.package("fem_fake", tmp_path, inputs={"bone": {"geometry": ["step", "stl"]}})
    made = real.fea_run(tmp_path, [P("p1")], packages_={"fem": both}, bone=bone)
    status = finished(made)
    assert real.tasks(made) == {"p1": ("done", "finished")}, status.rounds[-1].problems
    assert {region["file"] for region in deck(made, "p1")["bone"]["regions"].values()} == {
        "regions/cortical.stl", "regions/cancellous.stl", "regions/canal.stl"}


def test_a_version_1_bone_model_reaches_the_packages_read_as_version_2(real_lab, data, tmp_path):
    """盘上是第 1 版的骨模型：盘上的不动；交给包的 job 里，bone 是读成第 2 版的清单（区域带着角色，材料换成了 elastic，
    坐标系照颈轴定），bone_model 还是那个文件夹。假柄空间包、假推导量定义拿到的不是第 2 版就不干，所以走完就是三个包都拿到了。"""
    made = real.fea_run(tmp_path, [P("p1")])
    status = finished(made)
    assert real.tasks(made) == {"p1": ("done", "finished")}, status.rounds[-1].problems
    stored = read_manifest(lookup.content(status.frozen["bone"][0]["id"]))
    assert stored["format"] == 1 and set(stored["solids"]) == {"cortical", "cancellous"}, "盘上的还是第 1 版"
    assert deck(made, "p1")["bone"] == {"format": 2, "frame": "shaft_neck", "regions": {
        "cortical": {"file": "solids/cortical.step", "there": True, "material": "elastic"},
        "cancellous": {"file": "solids/cancellous.step", "there": True, "material": "elastic"}}}


def test_what_a_version_1_bone_model_does_not_know_counts_as_missing(real_lab, data, tmp_path):
    """第 1 版读成第 2 版，有几样是不知道的。包要它，就算缺；照颈轴定、前倾角不知道的坐标系，包说了收才收。"""
    bone = real.bone_model(tmp_path)
    text = refused(wanting(tmp_path, bone, stem={}, derive={}, fem={"coverage": {"extent": ["whole"]}}))
    assert "有限元包" in text and "不知道覆盖范围" in text, text
    text = refused(wanting(tmp_path, bone, stem={}, derive={}, fem={"frame": {"methods": ["shaft_neck"]}}))
    assert "有限元包" in text and "前倾角不知道" in text, text
    taken = wanting(tmp_path, bone, stem={}, derive={}, fem={"frame": {"methods": ["shaft_neck"], "unknown_anteversion": True}})
    assert start.start(taken).ok
