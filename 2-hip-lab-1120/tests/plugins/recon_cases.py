"""重建插件的验收情形。每个情形是一个函数：造输入、跑、断言。

5c 起重建叫重建方法包干活。这里用假的方法包（tests/packages/recon_fake）：骨源里放着两个假实体，和一根造出来的股骨的标志点
（tests/contract/bone_samples.py，解剖坐标系和前倾角的真值照构造直接写），所以骨架照第 2 版写得对不对可以直接比。
真骨源上自动找的标志点准不准，是方法包自己的事：5c 以前在这里，现在在 plugins/recon/tests/test_rebuild_cad.py，5d 跟着 CAD 方法包走。

test_recon.py 在这个进程里逐个跑。BLUEPRINT 里的三个对应蓝图“怎样算做对”的前三条；
“把 rebuild.py 整个换一份写法”那一条，是在换过写法的仓库拷贝里把这三个原样再跑一遍（格式核对和检查门照过），
再拿一份写得马虎的跑 CARELESS（如实不过）。
REFUSED 里每个情形只违一条启动前核的规矩，BROKEN 里每个情形只违一条方法包交回来以后核的规矩。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import psutil

from stemlab.contract import Refused
from stemlab.contract.formats import bone_model
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.hashing import hash_file
from stemlab.contract.layout import work_dir
from stemlab.desk.core import query, start
from stemlab.experiments import view
from stemlab.registry import lookup, register
from tests import helpers, packages, real

SECONDS = 180.0
SMOKE = {"name": "stem_fits", "value": "stem_smoke", "equals": True, "what": "柄空间包在这根骨上模板化得了这个设计"}
DESIGN = {"length": 30, "behave": "ok"}


def refused(made: str, **how) -> str:
    """启动应该被拒。返回被拒的原因；记录里什么都没多。"""
    before = len(helpers.entries_of(made))
    try:
        start.start(made, **how)
    except Refused as error:
        assert len(helpers.entries_of(made)) == before, "被拒的时候记录里不多一条"
        return str(error)
    raise AssertionError("启动本该被拒")


def finished(made: str):
    """启动、跑完这一轮，返回这个实验现在的样子。"""
    assert start.start(made).ok
    real.run(made, seconds=SECONDS)
    return view.view(made)


def draft_of(tmp: Path, source: dict | None = None, value: dict | None = None, method: dict | None = None) -> str:
    """跑一个 recon.draft，返回它交出来的候选骨模型的编号。"""
    made = real.recon_draft(tmp, source, value, method)
    status = finished(made)
    assert status.rounds[-1].result == "done", (status.rounds[-1].reason, status.rounds[-1].problems)
    return status.rounds[-1].outputs["draft"]["item"]


def report_of(made: str, name: str) -> dict:
    folder = real.output(made, name)
    assert check_format("report", folder) == []
    return json.loads((folder / "report.json").read_bytes())


def stages(made: str, task: str) -> list[str]:
    """这个任务先后报过的阶段，连着重复的只算一次。"""
    seen = []
    for entry in helpers.entries_of(made, "task"):
        if entry["task"] == task and entry["stage"] and (not seen or seen[-1] != entry["stage"]):
            seen.append(entry["stage"])
    return seen


def pinned(item: dict) -> dict:
    return {"id": item["id"], "hash": item["hash"]}


def same_frame(frame: dict, truth: dict) -> bool:
    return all(abs(a - b) < 1e-9 for key in ("origin", "x", "y", "z") for a, b in zip(frame[key], truth[key]))


def smoke_inputs(tmp: Path, **change) -> tuple:
    """冒烟用的假柄空间包（change 盖掉它清单里的同名项），和照它的 placement 声明写的放置设定。"""
    stem = real.package("stem_fake", tmp, **change)
    return stem, real.setting(real.declared(packages.STEM_PLACEMENT, stem["id"]))


def smoke_gate(**smoke) -> dict:
    """定稿的检查门加上冒烟那一条。smoke 不给就是拿 DESIGN 试。"""
    return real.gate_setting(real.FINAL_GATE + [SMOKE], smoke=smoke or {"design": DESIGN})


# ---- 1 一份骨源走完两个类型：骨模型照第 2 版写，过格式核对，该有的都在 ----

def a_source_through_both_kinds(tmp: Path) -> None:
    source, method = real.recon_source(tmp), real.recon_method(tmp)
    marks, truth = real.recon_marks()
    made = real.recon_draft(tmp, source, method=method)
    assert start.start(made).ok
    assert real.tasks(made) == {"rebuild": ("queued", None)}, "一个实验一个任务"
    real.run(made, seconds=SECONDS)
    status = view.view(made)
    assert (status.rounds[-1].result, status.rounds[-1].problems) == ("done", [])
    assert real.tasks(made) == {"rebuild": ("done", "rebuilt")} and status.tasks["rebuild"].machine == "here"
    assert sorted(status.rounds[-1].outputs) == ["draft", "todo"]

    draft = real.output(made, "draft")
    assert check_format("bone_draft", draft) == []
    listed = read_manifest(draft)
    assert (listed["format"], listed["bone_id"]) == (2, real.BONE), "照第 2 版写；骨标识从骨源继承"
    assert listed["source"] == {"how": "cad", "method": pinned(method), "setting": pinned(status.frozen["setting"][0])}, \
        "来源记着存定的方法包和重建设定"
    assert [(row["name"], row["passed"]) for row in listed["checks"]] == [(line["name"], None) for line in real.GATE], "检查还没做"
    assert listed["frame"]["method"] == "shaft_condyles" and same_frame(listed["frame"], truth), "完整的股骨照后髁连线定，坐标系就是真值"
    assert abs(listed["measures"]["anteversion_deg"] - 12.0) < 1e-9, "照后髁连线量出的前倾角记进量出来的数，就是造它时的前倾角"
    assert {name: point["xyz"] for name, point in listed["landmarks"].items()} == marks
    for region in listed["regions"]:
        given = lookup.content(source["id"]) / f"{region['name']}.step"
        assert hash_file(draft / region["geometry"]["file"]) == hash_file(given), "方法包交的几何文件原样复制，一个字节不动"
    todo = report_of(made, "todo")
    assert {row["item"] for row in todo["todo"]} >= set(bone_model.LANDMARKS), "五个标志点都请人看一眼"
    assert all(isinstance(row["doubt"], bool) and row["why"] for row in todo["todo"])
    item = lookup.get(status.rounds[-1].outputs["draft"]["item"])
    assert (item["kind"], item["bone_id"], item["id"][0]) == ("bone_draft", real.BONE, "R"), "候选骨模型不算 case"

    final = real.recon_finalize(item["id"])
    status = finished(final)
    assert (status.rounds[-1].result, status.rounds[-1].problems) == ("done", [])
    assert real.tasks(final) == {"finalize": ("done", "passed")}
    assert sorted(status.rounds[-1].outputs) == ["gate", "model"]
    assert status.frozen["method"][0]["id"] == method["id"], "定稿用的就是出候选的那个方法包"

    folder = real.output(final, "model")
    assert check_format("bone_model", folder) == []
    model = read_manifest(folder)
    assert (model["format"], model["bone_id"], model["side"], model["units"]) == (2, real.BONE, "right", bone_model.UNITS)
    assert model["source"] == {"how": "cad", "method": pinned(method), "setting": pinned(status.frozen["setting"][0])}
    assert [(region["name"], region["role"], region["material"]) for region in model["regions"]] == [
        ("cortical", "cortical", {"model": "elastic", "E": 16800.0, "nu": 0.3}), ("cancellous", "cancellous", {"model": "elastic", "E": 155.0, "nu": 0.3})]
    for region in model["regions"]:
        given = lookup.content(source["id"]) / f"{region['name']}.step"
        assert hash_file(folder / region["geometry"]["file"]) == hash_file(given)
    assert same_frame(model["frame"], truth) and model["surfaces"] == {}
    assert set(model["landmarks"]) == set(marks) and all(point["definition"]["method"] for point in model["landmarks"].values())
    assert len(model["history"]) > len(listed["history"]), "候选时的重建记录还在，定稿接在后面"
    assert [(row["name"], row["passed"]) for row in model["checks"]] == [(line["name"], True) for line in real.FINAL_GATE]
    assert all(row["value"] is not None and row["limit"]["what"] for row in model["checks"]), "每项检查写着量到的数和线"
    assert (model["measures"]["head_fit_rms_mm"], model["measures"]["neck_wall_min_mm"]) == (0.3, 4.0), \
        "定稿重做不了的数（方法包清单 kept 里的），从候选沿用"

    item = lookup.get(status.rounds[-1].outputs["model"]["item"])
    assert (item["kind"], item["bone_id"], item["id"][0]) == ("bone_model", real.BONE, "C"), "骨模型是 case，继承骨标识"
    assert item["origin"] == {"from": "product", "experiment": final, "round": 1, "output": "model"}
    gate = report_of(final, "gate")
    assert gate["passed"] is True and [row["name"] for row in gate["checks"]] == [line["name"] for line in real.FINAL_GATE]

    for one in (made, final):                           # 每张图都拿得到数据
        for chart in query.charts(one):
            assert query.chart(one, chart["name"]) is not None, chart
    assert len(query.chart(final, "checks")["rows"]) == len(real.FINAL_GATE), "检查结果那张图里是这一轮的各项检查"
    assert query.chart(made, "todo")["rows"] and query.chart(made, "measures")["rows"], "图的数据是插件留的，不靠方法包自己的文件"
    assert [chart["name"] for chart in query.charts(made)] == ["steps", "mesh", "measures", "todo", "neck"]
    used = [extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package"]
    assert used == ["recon_method"], "用了哪个方法包，核心记进了这一轮的来历"


# ---- 2 没过检查门：结局是“没过检查门”，不交骨模型，报告里写着哪一项没过 ----

def a_gate_that_is_not_passed(tmp: Path) -> None:
    draft = draft_of(tmp)
    strict = real.FINAL_GATE + [
        {"name": "neck_wall_thick", "value": "neck_wall_min_mm", "min": 6.0, "what": "股骨颈处皮质最薄不小于 6 mm（故意定得过不了）"},
        {"name": "never_measured", "value": "wall_min_mm", "max": 1.0, "what": "方法包答应会量、这根骨上却没有量出来的数"},
    ]
    final = real.recon_finalize(draft, gate=real.gate_setting(strict))
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "gate_failed")}
    assert next(row for row in status.outcomes if row["name"] == "gate_failed")["category"] == "conclusion", "没过检查门是结论"
    assert status.rounds[-1].result == "done"
    assert sorted(status.rounds[-1].outputs) == ["gate"], "不交骨模型"
    assert lookup.find(kind="bone_model") == [], "登记里没有多出骨模型"

    report = report_of(final, "gate")
    assert report["passed"] is False
    failed = {row["name"]: row for row in report["checks"] if not row["passed"]}
    assert sorted(failed) == ["neck_wall_thick", "never_measured"], "报告里写着哪一项没过"
    assert 3.0 < failed["neck_wall_thick"]["value"] < 5.0 and failed["neck_wall_thick"]["limit"]["min"] == 6.0
    assert failed["never_measured"]["value"] is None, "量出来的数里没有这一项：如实不过，不当它不存在"
    assert sorted(row["name"] for row in report["checks"] if row["passed"]) == sorted(line["name"] for line in real.FINAL_GATE)
    assert refused(final), "结论不重排：再启动被拒"


# ---- 3 填了人工修改：骨模型里记着改了哪里 ----

def edits_are_recorded(tmp: Path) -> None:
    source = real.recon_source(tmp)
    draft = draft_of(tmp, source)
    before = read_manifest(lookup.content(draft))
    head = before["landmarks"]["head_center"]["xyz"]
    moved = [head[0] + 0.6, head[1], head[2] + 0.8]                             # 挪 1 mm
    fixed = (lookup.content(source["id"]) / "cancellous.step").read_bytes() + b"hand repaired\n"     # 另一个文件
    change = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": moved, "why": "球拟合带进了一小块颈，往外挪"}},
                              "solids": {"cancellous": {"file": "cancellous_fixed.step", "why": "填了导针孔"}}},
                        files={"cancellous_fixed.step": fixed})
    final = real.recon_finalize(draft, edits=change)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].problems, report_of(final, "gate")["checks"])
    assert status.frozen["edits"][0]["id"] == change["id"], "用的是哪一份修改，存定在实验的输入里"

    folder = real.output(final, "model")
    model = read_manifest(folder)
    assert model["landmarks"]["head_center"]["xyz"] == moved and "wei" in model["landmarks"]["head_center"]["definition"]["text"]
    assert model["landmarks"]["neck_center"] == before["landmarks"]["neck_center"], "没改的点原样"
    told = [step["what"] for step in model["history"]]
    about_point = next(what for what in told if "head_center" in what)
    assert "wei" in about_point and "球拟合带进了一小块颈" in about_point and "1.00 mm" in about_point, "谁改的、为什么、挪了多少"
    about_solid = next(what for what in told if "cancellous_fixed.step" in what)
    assert "wei" in about_solid and "填了导针孔" in about_solid
    assert len(model["history"]) >= len(before["history"]) + 2, "候选时的记录还在，改动接在后面"
    files = {region["name"]: folder / region["geometry"]["file"] for region in model["regions"]}
    assert hash_file(files["cancellous"]) == hash_file(lookup.content(change["id"]) / "cancellous_fixed.step")
    assert hash_file(files["cortical"]) == hash_file(lookup.content(source["id"]) / "cortical.step")
    near = next(row for row in model["checks"] if row["name"] == "landmarks_near")
    assert abs(near["value"] - 1.0) < 0.05, "定稿的标志点离自动找的差多少，检查门量过"

    far = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": [head[0] + 8.0, head[1], head[2]], "why": "试一个离谱的"}}})
    wrong = real.recon_finalize(draft, edits=far)
    finished(wrong)
    assert real.tasks(wrong) == {"finalize": ("done", "gate_failed")}, "人工改得离自动找的太远，检查门照样拦"
    assert [row["name"] for row in report_of(wrong, "gate")["checks"] if not row["passed"]] == ["landmarks_near"]


BLUEPRINT = [a_source_through_both_kinds, a_gate_that_is_not_passed, edits_are_recorded]


# ---- 4 的后一半：一份写得马虎的 rebuild.py，如实不过（只在换过文件的仓库拷贝里跑）----

def a_careless_rebuild_does_not_get_through(tmp: Path) -> None:
    made = real.recon_draft(tmp)
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("failed", "failed")}, "少一个标志点：写不成候选骨模型，记成重建出错"
    assert status.rounds[-1].result == "failed" and "lesser_trochanter" in status.rounds[-1].reason
    assert status.rounds[-1].outputs == {} and lookup.find(kind="bone_draft") == []

    method = real.recon_method(tmp)
    final = real.recon_finalize(real.draft_v2(tmp, method)["id"])
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "gate_failed")}, "什么都没量：检查门的每一条都如实不过"
    assert sorted(status.rounds[-1].outputs) == ["gate"] and lookup.find(kind="bone_model") == []
    report = report_of(final, "gate")
    assert report["passed"] is False and all(row["passed"] is False and row["value"] is None for row in report["checks"])


CARELESS = [a_careless_rebuild_does_not_get_through]


# ---- 另外几样 ----

def the_second_version_takes_its_frame_from_the_landmarks(tmp: Path) -> None:
    """左股骨、只有近端一段的骨、第 1 版的候选：坐标系都由骨架照标志点算，定法照覆盖范围。"""
    method = real.recon_method(tmp)
    for side, whole in (("left", True), ("right", False)):
        marks, truth = real.recon_marks(side, whole)
        value = real.recon_setting(method, side=side, extent="whole" if whole else "proximal", anteversion_deg=None if whole else 12.0)
        made = real.recon_draft(tmp, real.recon_source(tmp, marks=marks), value, method)
        status = finished(made)
        assert status.rounds[-1].result == "done", (side, whole, status.rounds[-1].reason)
        listed = read_manifest(real.output(made, "draft"))
        frame = listed["frame"]
        assert same_frame(frame, truth), (side, whole)
        handed = sum(a * b for a, b in zip([frame["x"][1] * frame["y"][2] - frame["x"][2] * frame["y"][1],
                                            frame["x"][2] * frame["y"][0] - frame["x"][0] * frame["y"][2],
                                            frame["x"][0] * frame["y"][1] - frame["x"][1] * frame["y"][0]], frame["z"]))
        assert (handed > 0) == (side == "right"), "右股骨是右手系，左股骨是左手系"
        if whole:
            assert frame["method"] == "shaft_condyles" and "anteversion_deg" not in frame
            assert abs(listed["measures"]["anteversion_deg"] - 12.0) < 1e-9, "左股骨的前倾角也是朝前为正"
        else:
            assert (frame["method"], frame["anteversion_deg"]) == ("shaft_neck", 12.0), "近端一段照颈轴，前倾角照重建设定"
            assert "anteversion_deg" not in listed["measures"], "前倾角是设定给的，不是量出来的"
            assert listed["coverage"]["extent"] == "proximal"

    given = register.register_external("bone_draft", f"{real.BONE}-draft", note="测试：外面来的候选（盘上是第 1 版）", by="tester",
                                       bone_id=real.BONE, source=real.bone_folder(tmp / "v1-draft", kind="bone_draft", checks=[]))
    lines = [line for line in real.FINAL_GATE if line["name"] in ("cortical_closed", "cancellous_closed", "landmarks_near")]
    final = real.recon_finalize(given["id"], real.recon_setting(method, extent="proximal", anteversion_deg=0.0),
                                real.gate_setting(lines), method=method)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    folder = real.output(final, "model")
    model = read_manifest(folder)
    assert model["format"] == 2 and check_format("bone_model", folder) == [], "第 1 版的候选定稿出第 2 版的骨模型"
    assert (model["frame"]["method"], model["frame"]["anteversion_deg"]) == ("shaft_neck", 0.0)
    assert {name: point["xyz"] for name, point in model["landmarks"].items()} == {
        name: point["xyz"] for name, point in real.BONE_EXTRA["landmarks"].items()}
    for region in model["regions"]:
        assert hash_file(folder / region["geometry"]["file"]) == hash_file(lookup.content(given["id"]) / f"solids/{region['name']}.step")


def a_stem_smoke_in_the_gate(tmp: Path) -> None:
    """检查门里有冒烟：填了柄空间包，就让它在定稿的骨上模板化一个设计。放不进去、或者包不收这根骨，没过检查门。"""
    draft = draft_of(tmp)
    stem, placement = smoke_inputs(tmp)
    final = real.recon_finalize(draft, gate=smoke_gate(), stem=stem, placement=placement)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, status.rounds[-1].problems
    checks = {row["name"]: row for row in read_manifest(real.output(final, "model"))["checks"]}
    assert (checks["stem_fits"]["value"], checks["stem_fits"]["passed"]) == (True, True)
    assert stages(final, "finalize")[-1] == "smoke", "冒烟是定稿的最后一步"
    used = [extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package"]
    assert used == ["recon_method", "stem_space"], "用了哪个方法包、哪个柄空间包，核心记进了这一轮的来历"
    asked = json.loads((work_dir(final) / "gate" / "smoke-ask-r1" / "job.json").read_bytes())
    assert (asked["mode"], asked["designs"], asked["settings"]) == ("template", [{"name": "smoke", "design": DESIGN}], {"cut_drop": 0.0, "entry": "rule"})
    assert asked["bone"]["format"] == 2 and asked["bone"]["bone_id"] == real.BONE, "交给柄空间包的骨模型清单读成第 2 版（5b 的约定）"
    assert all((Path(asked["bone_model"]) / region["geometry"]["file"]).is_file() for region in asked["bone"]["regions"])

    each = real.setting(real.declared(packages.STEM_PLACEMENT, stem["id"], cut_drop={"per_point": True}))
    misfit = real.recon_finalize(draft, gate=smoke_gate(design={"length": 80, "behave": "ok"}, placement={"cut_drop": 2.0}),
                                 stem=stem, placement=each)
    finished(misfit)
    assert real.tasks(misfit) == {"finalize": ("done", "gate_failed")}
    report = report_of(misfit, "gate")
    assert [row["name"] for row in report["checks"] if not row["passed"]] == ["stem_fits"]
    said = report["measures"]["stem_smoke_reason"]
    assert said.startswith("放不进去") and "no entry offset" in said, "为什么放不进去，报告里有"
    asked = json.loads((work_dir(misfit) / "gate" / "smoke-ask-r1" / "job.json").read_bytes())
    assert asked["settings"] == {"cut_drop": 2.0, "entry": "rule"}, "放置设定里每个点给的项，照 smoke 里给的"

    refuses = real.recon_finalize(draft, gate=smoke_gate(design={"length": 30, "behave": "stem_env"}), stem=stem, placement=placement)
    finished(refuses)
    assert real.tasks(refuses) == {"finalize": ("done", "gate_failed")}
    said = report_of(refuses, "gate")["measures"]["stem_smoke_reason"]
    assert said.startswith("柄空间包没能在这根骨上模板化") and "licence server" in said, "包没给出这个设计：和放不进去分开说"


def only_numbers_the_method_cannot_redo_are_kept(tmp: Path) -> None:
    """定稿只沿用重做不了的数：方法包点名，只许清单 kept 里的；点了别的，记成重建出错。"""
    method = real.recon_method(tmp)
    draft = draft_of(tmp, real.recon_source(tmp, measures={"head_fit_rms_mm": 0.71, "neck_wall_min_mm": 4.0}), method=method)
    final = real.recon_finalize(draft)
    finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}
    assert read_manifest(real.output(final, "model"))["measures"]["head_fit_rms_mm"] == 0.71, "假方法包定稿时不量它：值是骨架从候选抄的"
    wrong = real.recon_finalize(draft, real.recon_setting(method, behave="keep_wrong"))
    status = finished(wrong)
    assert real.tasks(wrong) == {"finalize": ("failed", "failed")}
    assert "cortical_volume_mm3" in status.rounds[-1].reason and "kept" in status.rounds[-1].reason, status.rounds[-1].reason
    assert sorted(status.rounds[-1].outputs) == []


def a_source_that_cannot_be_read(tmp: Path) -> None:
    """方法包读不了这份骨源：记成重建出错（待查），这一轮失败，什么都不交。点名才重排。"""
    broken = real.recon_source(tmp, files={"notes.txt": b"nothing to rebuild from"})
    made = real.recon_draft(tmp, broken)
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("failed", "failed")}
    assert next(row for row in status.outcomes if row["name"] == "failed")["category"] == "unclear"
    assert status.rounds[-1].result == "failed" and status.rounds[-1].outputs == {}
    assert any("重建出错" in problem["error"] and "cortical.step" in problem["error"] and problem["task"] == "rebuild"
               for problem in status.rounds[-1].problems), "方法包说的原因记下来"
    start.start(made)                                   # 再启动，不点名：待查的不自动重排，这一轮没有活，照实结束
    status = view.view(made)
    assert (status.rounds[-1].result, status.rounds[-1].rerun) == ("failed", []) and "点名" in status.rounds[-1].reason
    assert status.tasks["rebuild"].round == 1, "任务没有被动过"
    start.start(made, named=["rebuild"])
    real.run(made, seconds=SECONDS)
    assert view.view(made).tasks["rebuild"].round == 3 and real.tasks(made) == {"rebuild": ("failed", "failed")}


def a_method_in_trouble(tmp: Path) -> None:
    """方法包报环境问题：可以重试；半路死掉、没留下结果：记成重建出错，说出它最后说的话。"""
    method = real.recon_method(tmp)
    env = real.recon_draft(tmp, value=real.recon_setting(method, behave="env"), method=method)
    status = finished(env)
    assert real.tasks(env) == {"rebuild": ("failed", "env")} and "licence server" in status.rounds[-1].reason
    assert next(row for row in status.outcomes if row["name"] == "env")["category"] == "retryable"
    crash = real.recon_draft(tmp, value=real.recon_setting(method, behave="crash"), method=method)
    status = finished(crash)
    assert real.tasks(crash) == {"rebuild": ("failed", "failed")}
    assert "crashing on purpose" in status.rounds[-1].reason, status.rounds[-1].reason


def stopping_a_rebuild(tmp: Path) -> None:
    """停止：在跑的方法包被结束；再启动重新来过，照样做完。"""
    method = real.recon_method(tmp)
    made = real.recon_draft(tmp, value=real.recon_setting(method, behave="slow"), method=method)
    start.start(made)
    home = str(work_dir(made))

    def workers() -> list:
        """这个测试进程起出去的进程里，命令行带着这个实验的 work 文件夹的那些：方法包的进程。

        只看自己起的，不把全机的进程扫一遍：进程多的机器上扫一遍要两三秒，扫到的时候它可能已经干完了。
        """
        found = []
        for process in psutil.Process().children(recursive=True):
            try:
                if any(home in part for part in process.cmdline()):
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found

    assert workers(), "方法包在脱离出去的进程里跑"
    assert start.stop(made).ok
    status = view.view(made)
    assert status.rounds[-1].result == "stopped" and real.tasks(made) == {"rebuild": ("stopped", None)}
    helpers.wait_for(lambda: not workers(), seconds=15)
    start.start(made)
    assert view.view(made).rounds[-1].rerun == ["rebuild"]
    real.run(made, seconds=SECONDS)
    assert real.tasks(made) == {"rebuild": ("done", "rebuilt")} and view.view(made).tasks["rebuild"].round == 2


OTHERS = [the_second_version_takes_its_frame_from_the_landmarks, a_stem_smoke_in_the_gate, only_numbers_the_method_cannot_redo_are_kept,
          a_source_that_cannot_be_read, a_method_in_trouble, stopping_a_rebuild]


# ---- 启动前被拒：每个情形只违一条，说出是哪一条 ----

def a_method_that_cannot_draft(tmp: Path) -> None:
    assert "不会 draft" in refused(real.recon_draft(tmp, method=real.recon_method(tmp, modes=["finalize"])))


def a_method_that_cannot_finalize(tmp: Path) -> None:
    method = real.recon_method(tmp, modes=["draft"])
    assert "不会 finalize" in refused(real.recon_finalize(real.draft_v2(tmp, method)["id"]))


def a_method_whose_outputs_are_not_measures(tmp: Path) -> None:
    method = real.recon_method(tmp, outputs=packages.outputs(*(row + ("pre",) for row in packages.RECON_MEASURES)))
    assert "label" in refused(real.recon_draft(tmp, method=method))


def a_method_that_takes_a_name_the_skeleton_keeps(tmp: Path) -> None:
    rows = packages.RECON_MEASURES + (("anteversion_deg", "deg", "anteversion measured by the method"),)
    method = real.recon_method(tmp, outputs=packages.outputs(*(row + ("label",) for row in rows)))
    assert "anteversion_deg" in refused(real.recon_draft(tmp, method=method))


def a_method_that_keeps_what_it_does_not_measure(tmp: Path) -> None:
    method = real.recon_method(tmp, kept=["head_fit_rms_mm", "tet_gamma_min"])
    assert "tet_gamma_min" in refused(real.recon_draft(tmp, method=method))


def a_setting_written_the_old_way(tmp: Path) -> None:
    method = real.recon_method(tmp)
    old = real.setting({"side": "right", "extent": "whole", "behave": "ok"})
    assert "rebuild" in refused(real.recon_draft(tmp, value=old, method=method))


def a_setting_by_another_declaration(tmp: Path) -> None:
    method = real.recon_method(tmp)
    stem, placement = smoke_inputs(tmp)
    made = real.recon_finalize(real.draft_v2(tmp, method)["id"], value=placement, gate=smoke_gate(), stem=stem, placement=placement)
    assert "rebuild" in refused(made)


def a_setting_with_items_each_point_would_give(tmp: Path) -> None:
    declaration = copy.deepcopy(packages.RECON)
    declaration["items"].append(packages.item("tessellation_mm", "骨", "number", 4.0, per_point=True, unit="mm", range={"min": 0.5, "max": 10}))
    method = real.recon_method(tmp, declarations=[declaration])
    value = real.setting(real.declared(declaration, method["id"], tessellation_mm={"per_point": True}))
    assert "每个点给" in refused(real.recon_draft(tmp, value=value, method=method))


def a_setting_against_its_declaration(tmp: Path) -> None:
    method = real.recon_method(tmp)
    assert "side" in refused(real.recon_draft(tmp, value=real.recon_setting(method, side="upper"), method=method)), "核心照声明核"


def a_gate_line_on_a_number_nobody_promised(tmp: Path) -> None:
    gate = real.gate_setting(real.GATE + [{"name": "tets", "value": "tet_gamma_min", "min": 0.1, "what": "四面体最差的 gamma"}])
    said = refused(real.recon_draft(tmp, gate=gate))
    assert "第 5 条" in said and "tet_gamma_min" in said, said


def a_gate_written_wrong(tmp: Path) -> None:
    for lines, said in (([], "gate"), ([{"name": "Head Fit", "value": "head_fit_rms_mm", "max": 1}], "name"),
                        ([{"name": "head_fit", "value": "head_fit_rms_mm"}], "min、max、equals")):
        assert said in refused(real.recon_draft(tmp, gate=real.gate_setting(lines))), lines


def a_smoke_written_the_old_way(tmp: Path) -> None:
    gate = real.gate_setting(real.GATE, smoke={"mode": "template", "design": DESIGN})
    assert "smoke" in refused(real.recon_draft(tmp, gate=gate))


def a_draft_from_another_method(tmp: Path) -> None:
    draft = real.draft_v2(tmp, real.recon_method(tmp))
    other = real.recon_method(tmp, kept=["head_fit_rms_mm"])            # 内容不一样的另一个方法包（同样的内容登记两次是同一个包）
    assert "同一个" in refused(real.recon_finalize(draft["id"], method=other))


def a_smoke_without_a_stem(tmp: Path) -> None:
    assert "柄空间包" in refused(real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate()))


def a_stem_that_cannot_template(tmp: Path) -> None:
    stem, placement = smoke_inputs(tmp, modes=["model"])
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem, placement=placement)
    assert "template" in refused(made)


def a_smoke_without_a_placement(tmp: Path) -> None:
    stem, _ = smoke_inputs(tmp)
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem)
    assert "放置设定要填" in refused(made)


def a_placement_by_another_declaration(tmp: Path) -> None:
    stem, _ = smoke_inputs(tmp)
    design = real.setting(real.declared(packages.STEM_DESIGN, stem["id"]))
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem, placement=design)
    assert "placement" in refused(made)


def a_smoke_design_against_the_stem(tmp: Path) -> None:
    stem, placement = smoke_inputs(tmp)
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(design={"length": 30}),
                               stem=stem, placement=placement)
    assert "behave" in refused(made)


def a_smoke_without_what_each_point_gives(tmp: Path) -> None:
    stem, _ = smoke_inputs(tmp)
    each = real.setting(real.declared(packages.STEM_PLACEMENT, stem["id"], cut_drop={"per_point": True}))
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem, placement=each)
    assert "cut_drop" in refused(made)


def a_draft_the_stem_does_not_take(tmp: Path) -> None:
    stem, placement = smoke_inputs(tmp, inputs={"bone": {"geometry": ["step"]}})       # 外面来的那份候选，髓腔是 STL
    said = refused(real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem, placement=placement))
    assert "不合" in said and "canal" in said, said


def a_stem_whose_wants_are_written_wrong(tmp: Path) -> None:
    stem, placement = smoke_inputs(tmp, inputs={"bone": {"solids": 2}})
    said = refused(real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], gate=smoke_gate(), stem=stem, placement=placement))
    assert "写得不对" in said and "solids" in said, said


def a_stem_without_a_smoke(tmp: Path) -> None:
    stem, placement = smoke_inputs(tmp)
    made = real.recon_finalize(real.draft_v2(tmp, real.recon_method(tmp))["id"], stem=stem, placement=placement)
    assert "不该填" in refused(made)


def edits_written_wrong(tmp: Path) -> None:
    draft = real.draft_v2(tmp, real.recon_method(tmp))["id"]
    unsigned = real.edits(tmp, {"landmarks": {"head_center": {"xyz": [1, 2, 3], "why": "x"}}})
    assert "by" in refused(real.recon_finalize(draft, edits=unsigned))
    no_reason = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": [1, 2, 3]}}})
    assert "why" in refused(real.recon_finalize(draft, edits=no_reason))
    no_file = real.edits(tmp, {"by": "wei", "solids": {"cancellous": {"file": "missing.step", "why": "x"}}})
    assert "file" in refused(real.recon_finalize(draft, edits=no_file))


REFUSED = [a_method_that_cannot_draft, a_method_that_cannot_finalize, a_method_whose_outputs_are_not_measures,
           a_method_that_takes_a_name_the_skeleton_keeps, a_method_that_keeps_what_it_does_not_measure, a_setting_written_the_old_way,
           a_setting_by_another_declaration, a_setting_with_items_each_point_would_give, a_setting_against_its_declaration,
           a_gate_line_on_a_number_nobody_promised, a_gate_written_wrong, a_smoke_written_the_old_way, a_draft_from_another_method,
           a_smoke_without_a_stem, a_stem_that_cannot_template, a_smoke_without_a_placement, a_placement_by_another_declaration,
           a_smoke_design_against_the_stem, a_smoke_without_what_each_point_gives, a_draft_the_stem_does_not_take,
           a_stem_whose_wants_are_written_wrong, a_stem_without_a_smoke, edits_written_wrong]


# ---- 方法包交回来的东西写不成第 2 版：记成重建出错，说出原因。每个情形只违一条 ----

def _broken(tmp: Path, behave: str, source: dict | None = None, **values) -> str:
    """出一个候选，方法包这一回照 behave 交回来；它该是重建出错。返回原因。"""
    method = real.recon_method(tmp)
    made = real.recon_draft(tmp, source, real.recon_setting(method, behave=behave, **values), method)
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("failed", "failed")}, (behave, status.rounds[-1].reason)
    assert status.rounds[-1].outputs == {} and lookup.find(kind="bone_draft") == []
    return status.rounds[-1].reason


def a_result_without_a_landmark(tmp: Path) -> None:
    assert "lesser_trochanter" in _broken(tmp, "garbage")


def a_result_with_a_relative_file(tmp: Path) -> None:
    assert "绝对路径" in _broken(tmp, "relative")


def a_result_with_a_region_name_that_is_not_a_name(tmp: Path) -> None:
    assert "区域的名字" in _broken(tmp, "badname")


def a_whole_femur_without_condyles(tmp: Path) -> None:
    marks, _ = real.recon_marks(whole=False)
    assert "condyle" in _broken(tmp, "ok", real.recon_source(tmp, marks=marks)), "完整的股骨照后髁连线定，没有后髁定不出来"


BROKEN = [a_result_without_a_landmark, a_result_with_a_relative_file, a_result_with_a_region_name_that_is_not_a_name,
          a_whole_femur_without_condyles]
