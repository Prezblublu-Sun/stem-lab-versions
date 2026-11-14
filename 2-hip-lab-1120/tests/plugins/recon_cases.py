"""重建插件的验收情形。每个情形是一个函数：造输入、跑、断言。骨源是现造的一根 CAD 假股骨，真值已知（tests/real.py）。

test_recon.py 在这个进程里逐个跑。BLUEPRINT 里的三个对应蓝图“怎样算做对”的前三条；
“把 rebuild.py 整个换一份写法”那一条，是在换过写法的仓库拷贝里把这三个原样再跑一遍（格式核对和检查门照过），
再拿一份写得马虎的跑 CARELESS（如实不过）。
"""
from __future__ import annotations

import json
import math
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
from tests import helpers, real

SECONDS = 180.0


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


def draft_of(tmp: Path, source: dict | None = None, value: dict | None = None) -> str:
    """跑一个 recon.draft，返回它交出来的候选骨模型的编号。"""
    made = real.recon_draft(tmp, source, value)
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


# ---- 1 一份 CAD 骨源走完两个类型：骨模型过格式核对，该有的都在 ----

def a_cad_source_through_both_kinds(tmp: Path) -> None:
    source = real.cad_source(tmp)
    made = real.recon_draft(tmp, source)
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
    assert listed["bone_id"] == real.BONE, "骨标识从骨源继承"
    assert [(row["name"], row["passed"]) for row in listed["checks"]] == [(line["name"], None) for line in real.GATE], "检查还没做"
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

    folder = real.output(final, "model")
    assert check_format("bone_model", folder) == []
    model = read_manifest(folder)
    assert (model["bone_id"], model["side"]) == (real.BONE, "right")
    assert model["units"] == bone_model.UNITS and model["frame"] == real.BONE_EXTRA["frame"]
    assert model["materials"] == real.BONE_EXTRA["materials"]
    for name in bone_model.SOLIDS:
        given = lookup.content(source["id"]) / f"{name}.step"
        assert hash_file(folder / model["solids"][name]["file"]) == hash_file(given), "CAD 的实体原样用，一个字节不动"
    assert set(model["landmarks"]) == set(bone_model.LANDMARKS)
    assert all(point["definition"].strip() for point in model["landmarks"].values()), "每个标志点带着它的定义"
    assert model["history"], "重建记录在"
    assert [(row["name"], row["passed"]) for row in model["checks"]] == [(line["name"], True) for line in real.FINAL_GATE]
    assert all(row["value"] is not None and row["limit"]["what"] for row in model["checks"]), "每项检查写着量到的数和线"

    marks = {name: point["xyz"] for name, point in model["landmarks"].items()}
    assert math.dist(marks["head_center"], real.TRUTH["head_center"]) < 0.5
    assert math.dist(marks["neck_center"], real.TRUTH["neck_center"]) < 1.0
    assert math.dist(marks["lesser_trochanter"], real.TRUTH["lesser_trochanter"]) < 3.0
    assert abs(bone_model.neck_shaft_angle(model["landmarks"]) - real.TRUTH["neck_shaft_angle"]) < 1.0
    neck, shaft = bone_model.axes(model["landmarks"])
    assert sum(a * b for a, b in zip(shaft, real.TRUTH["shaft_axis"])) > math.cos(math.radians(1.0))

    item = lookup.get(status.rounds[-1].outputs["model"]["item"])
    assert (item["kind"], item["bone_id"], item["id"][0]) == ("bone_model", real.BONE, "C"), "骨模型是 case，继承骨标识"
    assert item["origin"] == {"from": "product", "experiment": final, "round": 1, "output": "model"}
    gate = report_of(final, "gate")
    assert gate["passed"] is True and [row["name"] for row in gate["checks"]] == [line["name"] for line in real.FINAL_GATE]

    for one in (made, final):                           # 每张图都拿得到数据
        for chart in query.charts(one):
            assert query.chart(one, chart["name"]) is not None, chart
    assert len(query.chart(final, "checks")["rows"]) == len(real.FINAL_GATE), "检查结果那张图里是这一轮的各项检查"
    assert query.chart(made, "todo")["rows"] and query.chart(made, "measures")["rows"], "图的数据是插件留的，不靠重建代码自己的文件"
    assert [chart["name"] for chart in query.charts(made)] == ["steps", "mesh", "measures", "todo", "neck"]


# ---- 2 没过检查门：结局是“没过检查门”，不交骨模型，报告里写着哪一项没过 ----

def a_gate_that_is_not_passed(tmp: Path) -> None:
    draft = draft_of(tmp)
    strict = real.FINAL_GATE + [
        {"name": "neck_wall_thick", "value": "neck_wall_min_mm", "min": 6.0, "what": "股骨颈处皮质最薄不小于 6 mm（故意定得过不了）"},
        {"name": "never_measured", "value": "no_such_measure", "max": 1.0, "what": "一个谁也没量的数"},
    ]
    final = real.recon_finalize(draft, real.recon_setting(strict))
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
    source = real.cad_source(tmp)
    draft = draft_of(tmp, source)
    before = read_manifest(lookup.content(draft))
    head = before["landmarks"]["head_center"]["xyz"]
    moved = [head[0] + 0.6, head[1], head[2] + 0.8]                             # 挪 1 mm
    core = (lookup.content(source["id"]) / "cancellous.step").read_bytes()
    fixed = core.replace(b"Open CASCADE", b"Hand repaired")                     # 同一个形状，另一个文件
    assert fixed != core
    change = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": moved, "why": "球拟合带进了一小块颈，往外挪"}},
                              "solids": {"cancellous": {"file": "cancellous_fixed.step", "why": "填了导针孔"}}},
                        files={"cancellous_fixed.step": fixed})
    final = real.recon_finalize(draft, edits=change)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, (status.rounds[-1].problems, report_of(final, "gate")["checks"])
    assert status.frozen["edits"][0]["id"] == change["id"], "用的是哪一份修改，存定在实验的输入里"

    folder = real.output(final, "model")
    model = read_manifest(folder)
    assert model["landmarks"]["head_center"]["xyz"] == moved and "wei" in model["landmarks"]["head_center"]["definition"]
    assert model["landmarks"]["neck_center"] == before["landmarks"]["neck_center"], "没改的点原样"
    told = [step["what"] for step in model["history"]]
    about_point = next(what for what in told if "head_center" in what)
    assert "wei" in about_point and "球拟合带进了一小块颈" in about_point and "1.00 mm" in about_point, "谁改的、为什么、挪了多少"
    about_solid = next(what for what in told if "cancellous_fixed.step" in what)
    assert "wei" in about_solid and "填了导针孔" in about_solid
    assert len(model["history"]) >= len(before["history"]) + 2, "候选时的记录还在，改动接在后面"
    assert hash_file(folder / model["solids"]["cancellous"]["file"]) == hash_file(lookup.content(change["id"]) / "cancellous_fixed.step")
    assert hash_file(folder / model["solids"]["cortical"]["file"]) == hash_file(lookup.content(source["id"]) / "cortical.step")
    near = next(row for row in model["checks"] if row["name"] == "landmarks_near")
    assert abs(near["value"] - 1.0) < 0.05, "定稿的标志点离自动找的差多少，检查门量过"

    far = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": [head[0] + 8.0, head[1], head[2]], "why": "试一个离谱的"}}})
    wrong = real.recon_finalize(draft, edits=far)
    finished(wrong)
    assert real.tasks(wrong) == {"finalize": ("done", "gate_failed")}, "人工改得离自动找的太远，检查门照样拦"
    assert [row["name"] for row in report_of(wrong, "gate")["checks"] if not row["passed"]] == ["landmarks_near"]


BLUEPRINT = [a_cad_source_through_both_kinds, a_gate_that_is_not_passed, edits_are_recorded]


# ---- 4 的后一半：一份写得马虎的 rebuild.py，如实不过（只在换过文件的仓库拷贝里跑）----

def a_careless_rebuild_does_not_get_through(tmp: Path) -> None:
    made = real.recon_draft(tmp)
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("failed", "failed")}, "少一个标志点：写不成候选骨模型，记成重建出错"
    assert status.rounds[-1].result == "failed" and "lesser_trochanter" in status.rounds[-1].reason
    assert status.rounds[-1].outputs == {} and lookup.find(kind="bone_draft") == []

    given = register.register_external("bone_draft", f"{real.BONE}-draft", note="测试：外面来的候选", by="tester", bone_id=real.BONE,
                                       source=real.bone_folder(tmp / "given-draft", kind="bone_draft", checks=[]))
    final = real.recon_finalize(given["id"])
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "gate_failed")}, "什么都没量：检查门的每一条都如实不过"
    assert sorted(status.rounds[-1].outputs) == ["gate"] and lookup.find(kind="bone_model") == []
    report = report_of(final, "gate")
    assert report["passed"] is False and all(row["passed"] is False and row["value"] is None for row in report["checks"])


CARELESS = [a_careless_rebuild_does_not_get_through]


# ---- 另外几样 ----

def a_kernel_smoke_in_the_gate(tmp: Path) -> None:
    """检查门里有内核冒烟：填了内核，就让它在定稿的骨上真的建一次模。建不成，没过检查门。"""
    draft = draft_of(tmp)
    kernel = real.package("kernel_fake", tmp)
    line = {"name": "kernel_builds", "value": "kernel_smoke", "equals": True, "what": "内核在这根骨上建得了模"}
    builds = real.recon_setting(real.FINAL_GATE + [line], smoke={"mode": "build", "design": {"length": 30, "behave": "ok"},
                                                                 "conditions": {"load": 2000}})
    final = real.recon_finalize(draft, builds, kernel=kernel)
    status = finished(final)
    assert real.tasks(final) == {"finalize": ("done", "passed")}, status.rounds[-1].problems
    checks = {row["name"]: row for row in read_manifest(real.output(final, "model"))["checks"]}
    assert (checks["kernel_builds"]["value"], checks["kernel_builds"]["passed"]) == (True, True)
    assert stages(final, "finalize")[-1] == "smoke", "建模冒烟是定稿的最后一步"
    used = [extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package"]
    assert used == ["kernel"], "用了哪个内核，核心记进了这一轮的来历"

    misfit = real.recon_setting(real.FINAL_GATE + [line], smoke={"mode": "template", "design": {"length": 80, "behave": "ok"}})
    final = real.recon_finalize(draft, misfit, kernel=kernel)
    finished(final)
    assert real.tasks(final) == {"finalize": ("done", "gate_failed")}
    report = report_of(final, "gate")
    assert [row["name"] for row in report["checks"] if not row["passed"]] == ["kernel_builds"]
    assert "no entry offset" in report["measures"]["kernel_smoke_reason"], "内核为什么建不成，报告里有"

    assert "内核" in refused(real.recon_finalize(draft, builds)), "检查门里有冒烟却没填内核"
    no_design = real.recon_setting(real.FINAL_GATE + [line])
    assert "smoke" in refused(real.recon_finalize(draft, no_design, kernel=kernel)), "没说让内核拿哪个设计试"


def things_refused_before_the_start(tmp: Path) -> None:
    """骨源、重建设定、人工修改不对：启动被拒，说出哪里不对。"""
    ct = real.cad_source(tmp, files={"slices/0001.dcm": b"DICM", "slices/0002.dcm": b"DICM"})
    assert "CT" in refused(real.recon_draft(tmp, ct))
    assert "STEP" in refused(real.recon_draft(tmp, real.cad_source(tmp, files={"notes.txt": b"nothing to rebuild from"})))
    assert "side" in refused(real.recon_draft(tmp, value=real.recon_setting(side="upper")))
    assert "gate" in refused(real.recon_draft(tmp, value=real.recon_setting(gate=[])))
    assert "name" in refused(real.recon_draft(tmp, value=real.recon_setting(gate=[{"name": "Head Fit", "value": "head_fit_rms_mm", "max": 1}])))
    assert "min、max、equals" in refused(real.recon_draft(tmp, value=real.recon_setting(gate=[{"name": "head_fit", "value": "head_fit_rms_mm"}])))
    elsewhere = real.recon_setting(source={"cortical": "shell.step", "cancellous": "cancellous.step"})
    assert "shell.step" in refused(real.recon_draft(tmp, value=elsewhere))

    draft = register.register_external("bone_draft", f"{real.BONE}-draft", note="测试：外面来的候选", by="tester", bone_id=real.BONE,
                                       source=real.bone_folder(tmp / "given-draft", kind="bone_draft", checks=[]))
    unsigned = real.edits(tmp, {"landmarks": {"head_center": {"xyz": [1, 2, 3], "why": "x"}}})
    assert "by" in refused(real.recon_finalize(draft["id"], edits=unsigned))
    no_reason = real.edits(tmp, {"by": "wei", "landmarks": {"head_center": {"xyz": [1, 2, 3]}}})
    assert "why" in refused(real.recon_finalize(draft["id"], edits=no_reason))
    no_file = real.edits(tmp, {"by": "wei", "solids": {"cancellous": {"file": "missing.step", "why": "x"}}})
    assert "file" in refused(real.recon_finalize(draft["id"], edits=no_file))


def a_source_that_cannot_be_read(tmp: Path) -> None:
    """骨源的文件读不出实体：记成重建出错（待查），这一轮失败，什么都不交。点名才重排。"""
    broken = real.cad_source(tmp, files={"cortical.step": b"ISO-10303-21; not a solid\n", "cancellous.step": b"ISO-10303-21; nor this\n"})
    made = real.recon_draft(tmp, broken)
    status = finished(made)
    assert real.tasks(made) == {"rebuild": ("failed", "failed")}
    assert next(row for row in status.outcomes if row["name"] == "failed")["category"] == "unclear"
    assert status.rounds[-1].result == "failed" and status.rounds[-1].outputs == {}
    assert any("重建出错" in problem["error"] and problem["task"] == "rebuild" for problem in status.rounds[-1].problems)
    start.start(made)                                   # 再启动，不点名：待查的不自动重排，这一轮没有活，照实结束
    status = view.view(made)
    assert (status.rounds[-1].result, status.rounds[-1].rerun) == ("failed", []) and "点名" in status.rounds[-1].reason
    assert status.tasks["rebuild"].round == 1, "任务没有被动过"
    start.start(made, named=["rebuild"])
    real.run(made, seconds=SECONDS)
    assert view.view(made).tasks["rebuild"].round == 3 and real.tasks(made) == {"rebuild": ("failed", "failed")}


def stopping_a_rebuild(tmp: Path) -> None:
    """停止：在跑的重建被结束；再启动重新来过，照样做完。"""
    made = real.recon_draft(tmp)
    start.start(made)
    home = str(work_dir(made))

    def workers() -> list:
        """这个测试进程起出去的进程里，命令行带着这个实验的 work 文件夹的那些：重建的进程。

        只看自己起的，不把全机的进程扫一遍：进程多的机器上扫一遍要两三秒，比一次重建还久，扫到的时候它已经干完了。
        """
        found = []
        for process in psutil.Process().children(recursive=True):
            try:
                if any(home in part for part in process.cmdline()):
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found

    assert workers(), "重建在脱离出去的进程里跑"
    assert start.stop(made).ok
    status = view.view(made)
    assert status.rounds[-1].result == "stopped" and real.tasks(made) == {"rebuild": ("stopped", None)}
    helpers.wait_for(lambda: not workers(), seconds=15)
    start.start(made)
    assert view.view(made).rounds[-1].rerun == ["rebuild"]
    real.run(made, seconds=SECONDS)
    assert real.tasks(made) == {"rebuild": ("done", "rebuilt")} and view.view(made).tasks["rebuild"].round == 2


OTHERS = [a_kernel_smoke_in_the_gate, things_refused_before_the_start, a_source_that_cannot_be_read, stopping_a_rebuild]
