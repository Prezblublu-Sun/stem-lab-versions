"""FEA 插件的验收情形。每个情形是一个函数：造输入、跑、断言。用假的内核和假的求解。

test_fea.py 在这个进程里逐个跑。BLUEPRINT 里的六个对应蓝图“怎样算做对”的前六条；
“把 jobs.py 和 run.py 整个换一份写法”那一条，是在换过写法的仓库拷贝里把这六个原样再跑一遍。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from stemlab.contract import Refused
from stemlab.contract.formats import data as data_format
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.contract.hashing import hash_file, is_hash
from stemlab.desk.core import query, start
from stemlab.experiments import view
from stemlab.registry import lookup
from tests import helpers, real


def refused(made: str, **how) -> str:
    """启动应该被拒。返回被拒的原因；记录里什么都没多。"""
    before = len(helpers.entries_of(made))
    try:
        start.start(made, **how)
    except Refused as error:
        assert len(helpers.entries_of(made)) == before, "被拒的时候记录里不多一条"
        return str(error)
    raise AssertionError("启动本该被拒")


def rows_of(made: str, number: int | None = None) -> dict:
    """这一轮发布的数据里的各行：点的名字 -> 行。"""
    status = view.view(made)
    names = {point["hash"]: point["name"] for point in read_points(lookup.content(status.frozen["points"][0]["id"]))}
    return {names[row["point"]]: row for row in read_points(real.output(made, "data", number) / data_format.ROWS_FILE)}


def index_of(made: str, number: int | None = None) -> list[dict]:
    """这一轮发布的归档清单里的各行。"""
    return read_points(real.output(made, "archive", number) / "index.jsonl")


def kept(made: str, task: str, number: int | None = None) -> dict:
    """归档清单里这个任务留下的文件：哪一类 -> 文件名的集合。"""
    found: dict[str, set] = {}
    for row in index_of(made, number):
        if row["task"] == task:
            found.setdefault(row["what"], set()).add(row["file"].rsplit("/", 1)[-1])
    return found


def stages(made: str, task: str) -> list[str]:
    """这个任务先后报过的阶段，连着重复的只算一次。建好了等求解槽的那一段（ready）不是每个作业都有，不算。"""
    seen = []
    for entry in helpers.entries_of(made, "task"):
        stage = entry["stage"]
        if entry["task"] == task and stage and stage != "ready" and (not seen or seen[-1] != stage):
            seen.append(stage)
    return seen


# ---- 1 三个点的一批点：三个任务，各走完阶段 ----

def three_points(tmp: Path) -> None:
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 40), real.point("p3", 50)])
    assert start.start(made).ok
    assert real.tasks(made) == {"p1": ("queued", None), "p2": ("queued", None), "p3": ("queued", None)}, "一个点一个任务"
    real.run(made)
    status = view.view(made)
    assert (status.rounds[-1].result, status.rounds[-1].problems) == ("done", [])
    assert real.tasks(made) == {"p1": ("done", "finished"), "p2": ("done", "finished"), "p3": ("done", "finished")}
    for name in ("p1", "p2", "p3"):
        assert stages(made, name) == ["build", "solve", "post"], f"{name} 各走完阶段：{stages(made, name)}"
        assert status.tasks[name].machine == "here" and is_hash(status.tasks[name].fingerprint)
    assert len({status.tasks[name].fingerprint for name in ("p1", "p2", "p3")}) == 3, "输入指纹是一个作业的身份，三个点三个样"

    rows = rows_of(made)
    assert check_format("data", real.output(made, "data")) == []
    assert rows["p1"]["values"] == {"length": 30, "behave": "ok", "load": 2000, "bone_removed": 3000.0,
                                    "rotation": 2000 / 30000, "contact": 0.5, "slip_p95": 0.95 * 15}
    assert rows["p3"]["values"]["rotation"] == 2000 / 50000
    slip = real.output(made, "data") / rows["p1"]["fields"]["interface_slip"]
    assert json.loads(slip.read_bytes()) == [3.0, 6.0, 9.0, 12.0, 15.0], "场跟着数据一起发布"

    assert check_format("archive", real.output(made, "archive")) == []
    assert kept(made, "p2") == {"mesh": {"mesh.json"}, "settings": {"deck.json"}, "fields": {"step1.json", "step2.json"},
                                "process": {"solver.log", "build-result.json", "build-log.txt", "post-result.json",
                                            "post-log.txt", "derive-result.json", "derive-log.txt"}}
    root = Path(read_manifest(real.output(made, "archive"))["root"])
    for row in index_of(made):
        assert hash_file(root / row["file"]) == row["sha256"] and (root / row["file"]).stat().st_size == row["size"]
        assert row["round"] == 1 and row["fingerprint"] == status.tasks[row["task"]].fingerprint
    used = sorted(extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package")
    assert used == ["derive_def", "kernel"], "用了哪两个包，核心记进了这一轮的来历"
    solving = query.chart(made, "solving")["rows"]
    assert {row[0] for row in solving} == {"p1", "p2", "p3"} and {row[2] for row in solving} == {"solver.log"}, \
        "求解过程那张图：作业结束之后，读的是归档里留下的求解日志"
    assert any(row[3].strip() for row in solving)


# ---- 2 一个作业不收敛：记成待查，别的作业照常；失败前算出来的步也在归档里 ----

def one_job_does_not_converge(tmp: Path) -> None:
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 40, "diverge"), real.point("p3", 50)])
    start.start(made)
    real.run(made)
    status = view.view(made)
    assert real.tasks(made) == {"p1": ("done", "finished"), "p2": ("failed", "not_converged"), "p3": ("done", "finished")}
    assert status.rounds[-1].result == "done", "做完不等于每个任务都成功"
    assert next(row for row in status.outcomes if row["name"] == "not_converged")["category"] == "unclear", "不收敛归待查"
    assert sorted(rows_of(made)) == ["p1", "p3"], "待查的不进数据"
    assert kept(made, "p2")["fields"] == {"step1.json"}, "失败前算出来的那一步也留在归档里"
    assert {"solver.log", "post-result.json"} <= kept(made, "p2")["process"] and kept(made, "p2")["settings"] == {"deck.json"}
    found = [problem for problem in status.rounds[-1].problems if problem["task"] == "p2"]
    assert len(found) == 1 and "不收敛" in found[0]["error"] and "TOO MANY ATTEMPTS" in found[0]["error"]


# ---- 3 放不进去的点：任务是完成，结局是放不进去，数据里有这一行 ----

def a_point_that_does_not_fit(tmp: Path) -> None:
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 80), real.point("p3", 40, "loose")])
    start.start(made)
    real.run(made)
    assert real.tasks(made) == {"p1": ("done", "finished"), "p2": ("done", "misfit"), "p3": ("done", "unstable")}
    rows = rows_of(made)
    assert check_format("data", real.output(made, "data")) == []
    assert rows["p2"]["outcome"] == "misfit" and rows["p2"]["fields"] == {}
    assert rows["p2"]["values"] == {"length": 80, "behave": "ok", "load": 2000, "bone_removed": None,
                                    "rotation": None, "contact": None, "slip_p95": None}, "这一行在，FE 的结果是空的"
    assert rows["p3"]["outcome"] == "unstable" and rows["p3"]["values"]["rotation"] is None
    assert rows["p3"]["values"]["bone_removed"] == 4000.0, "建模时就有的量照样记"
    categories = {row["name"]: row["category"] for row in view.view(made).outcomes}
    assert categories["misfit"] == categories["unstable"] == "conclusion"
    assert "step1.json" in kept(made, "p3")["fields"], "松动的那个作业，停下之前算出来的步也留着"


# ---- 4 点里的骨标识和骨模型不一致，或条件项和内核要的不一致：检查不过 ----

def inputs_that_do_not_agree(tmp: Path) -> None:
    other_bone = real.fea(tmp, [real.point("p1"), real.point("p2", bone_id="femur043")])
    why = refused(other_bone)
    assert "骨标识" in why and "femur043" in why and "p2" in why

    extra = dict(real.point("p1"), conditions={"load": 2000.0, "friction": 0.3})
    assert "条件项" in refused(real.fea(tmp, [extra]))
    short = dict(real.point("p1"), design={"length": 30.0})
    assert "设计项" in refused(real.fea(tmp, [short]))

    assert "场" in refused(real.fea(tmp, [real.point("p1")], derive=real.package("derive_fake", tmp, needs=["strain"])))
    assert "build" in refused(real.fea(tmp, [real.point("p1")], kernel=real.package("kernel_fake", tmp, modes=["template"])))
    only_this = real.package("kernel_fake", tmp, bones=["femur777"])
    assert "femur777" in refused(real.fea(tmp, [real.point("p1")], kernel=only_this))
    no_units = real.package("kernel_fake", tmp, labels=[{"name": "rotation", "meaning": "no unit given"}])
    assert "labels" in refused(real.fea(tmp, [real.point("p1")], kernel=no_units))
    assert "column" in refused(real.fea(tmp, [real.point("p1")], criteria={"criteria": [
        {"id": "g1", "what": "x", "column": "no_such_column", "stat": "max", "op": "<=", "limit": 1}]}))


# ---- 5 数据的每一行带齐五样键；数据说明里每列有单位 ----

def every_row_has_its_five_keys(tmp: Path) -> None:
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 80)])
    start.start(made)
    real.run(made)
    status = view.view(made)
    manifest = read_manifest(real.output(made, "data"))
    assert manifest["bone_id"] == real.BONE and manifest["count"] == 2
    assert [(column["name"], column["role"], column["unit"]) for column in manifest["columns"]] == [
        ("length", "design", "mm"), ("behave", "design", "1"), ("load", "condition", "N"),
        ("bone_removed", "pre", "mm3"), ("rotation", "label", "deg"), ("contact", "label", "1"),
        ("interface_slip", "field", "um"), ("slip_p95", "derived", "um")]
    assert all(column["unit"] and column["meaning"] for column in manifest["columns"]), "每列有单位和含义"
    points = {point["name"]: point for point in read_points(lookup.content(status.frozen["points"][0]["id"]))}
    for name, row in rows_of(made).items():
        assert all(key in row for key in data_format.ROW_KEYS)
        assert row["point"] == points[name]["hash"] and row["bone_id"] == real.BONE and row["round"] == 1
        assert row["fingerprint"] == status.tasks[name].fingerprint and row["outcome"] == status.tasks[name].outcome
    item = lookup.get(status.rounds[-1].outputs["data"]["item"])
    assert (item["kind"], item["name"], item["version"], item["bone_id"]) == ("data", f"{made}.data", 1, real.BONE)
    assert item["origin"] == {"from": "product", "experiment": made, "round": 1, "output": "data"}


# ---- 6 再启动：只重排该重排的；新一轮的数据里，每行写着是哪一轮算的 ----

def restarting(tmp: Path) -> None:
    before = os.environ.get("FAKE_KERNEL_STATE")
    os.environ["FAKE_KERNEL_STATE"] = str(tmp / "kernel-state")
    try:
        made = real.fea(tmp, [real.point("a", 30), real.point("b", 40, "diverge"), real.point("c", 50, "flaky")])
        start.start(made)
        real.run(made)
        assert real.tasks(made) == {"a": ("done", "finished"), "b": ("failed", "not_converged"), "c": ("failed", "env")}
        assert sorted(rows_of(made)) == ["a"]

        start.start(made)                                   # 再启动，不点名：只重排可重试的那一个
        assert view.view(made).rounds[-1].rerun == ["c"]
        real.run(made)
        assert real.tasks(made) == {"a": ("done", "finished"), "b": ("failed", "not_converged"), "c": ("done", "finished")}
        second = [entry["task"] for entry in helpers.entries_of(made, "task") if entry["round"] == 2]
        assert set(second) == {"c"}, "新的一轮只动了重排的那个任务"
        rows = rows_of(made)
        assert {name: row["round"] for name, row in rows.items()} == {"a": 1, "c": 2}, "每行写着是哪一轮算的"
        assert sorted(rows_of(made, 1)) == ["a"], "上一轮发布的数据一个字节不动"
        versions = [lookup.get(one.outputs["data"]["item"])["version"] for one in view.view(made).rounds]
        assert versions == [1, 2], "同名再登记，版本加一"
        assert {row["round"] for row in index_of(made) if row["task"] == "c"} == {1, 2}, "两轮留下的都在归档清单里"

        assert "重排" in refused(made) or "做完" in refused(made), "没有可以重排的了，再启动被拒"
        start.start(made, named=["b"])                      # 待查的要点名才重排
        assert view.view(made).rounds[-1].rerun == ["b"]
        real.run(made)
        assert real.tasks(made)["b"] == ("failed", "not_converged") and view.view(made).tasks["b"].round == 3
        assert {name: row["round"] for name, row in rows_of(made).items()} == {"a": 1, "c": 2}
    finally:
        os.environ.pop("FAKE_KERNEL_STATE") if before is None else os.environ.update(FAKE_KERNEL_STATE=before)


BLUEPRINT = [three_points, one_job_does_not_converge, a_point_that_does_not_fit, inputs_that_do_not_agree,
             every_row_has_its_five_keys, restarting]


# ---- 另外几样 ----

def other_ways_to_fail(tmp: Path) -> None:
    """网格失败是待查；环境问题是可重试；内核自己崩了是待查。都不进数据，别的作业照常。"""
    made = real.fea(tmp, [real.point("ok", 30), real.point("mesh", 31, "mesh"), real.point("env", 32, "env"),
                          real.point("crash", 33, "crash")])
    start.start(made)
    real.run(made)
    assert real.tasks(made) == {"ok": ("done", "finished"), "mesh": ("failed", "mesh_failed"), "env": ("failed", "env"),
                                "crash": ("failed", "error")}
    categories = {row["name"]: row["category"] for row in view.view(made).outcomes}
    assert (categories["mesh_failed"], categories["env"], categories["error"]) == ("unclear", "retryable", "unclear")
    assert sorted(rows_of(made)) == ["ok"]
    assert "build-log.txt" in kept(made, "crash")["process"], "内核崩之前说的话留着"
    errors = {problem["task"]: problem["error"] for problem in view.view(made).rounds[-1].problems}
    assert "overlapping facets" in errors["mesh"] and "licence" in errors["env"] and "没有留下结果" in errors["crash"]
    start.start(made)
    assert view.view(made).rounds[-1].rerun == ["env"], "再启动时只有环境问题的那个自动重排"
    start.stop(made)


def nothing_computed(tmp: Path) -> None:
    """一个作业都没算出能进数据的结果：这一轮是失败，不交数据，归档清单照交。"""
    made = real.fea(tmp, [real.point("p1", 30, "env"), real.point("p2", 31, "mesh")])
    start.start(made)
    real.run(made)
    status = view.view(made)
    assert status.rounds[-1].result == "failed" and "没有一个作业" in status.rounds[-1].reason
    assert sorted(status.rounds[-1].outputs) == ["archive"]


def too_many_numerical_failures(tmp: Path) -> None:
    """数值上没算出来的作业占比高了，记一条提醒：先查模型，别让选点绕着走。"""
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 31, "mesh"), real.point("p3", 32, "diverge")])
    start.start(made)
    real.run(made)
    errors = [problem["error"] for problem in view.view(made).rounds[-1].problems if problem["task"] is None]
    assert len(errors) == 1 and "3 个作业里有 2 个" in errors[0] and "先查模型" in errors[0]


def traced(tmp: Path, body) -> list[int]:
    """跑 body()，其间让假求解器记下每次开始求解时同一时刻有几个在跑。返回记下的各个数。"""
    before = os.environ.get("FAKE_SOLVER_TRACE")
    os.environ["FAKE_SOLVER_TRACE"] = str(tmp / "solver-trace")
    try:
        body()
    finally:
        os.environ.pop("FAKE_SOLVER_TRACE") if before is None else os.environ.update(FAKE_SOLVER_TRACE=before)
    seen = tmp / "solver-trace" / "seen.txt"
    assert not list((tmp / "solver-trace").glob("*.running")), "求解的进程都结束了"
    return [int(line) for line in seen.read_text().split()]


def solving_is_queued_by_slots(tmp: Path) -> None:
    """按求解槽数排队：这台机器 2 个槽，三个作业同一时刻在求解的最多两个。"""
    made = real.fea(tmp, [real.point(f"p{n}", 30 + n) for n in range(3)], export={"seconds": 1.2})
    start.start(made)
    counts = traced(tmp, lambda: real.run(made, seconds=90))
    assert view.view(made).rounds[-1].result == "done"
    assert len(counts) == 3 and max(counts) == 2, f"三次求解开始时同一时刻在跑的个数：{counts}"
    slots = Path(os.environ["STEMLAB_SLOTS"])
    assert not list(slots.glob("solve-*.json")) and not list(slots.glob("build-*.json")), "做完之后槽都放掉了"


def two_experiments_share_the_slots(tmp: Path) -> None:
    """槽是整台机器共用的：两个实验同时跑，合起来也不超过求解槽数。"""
    first = real.fea(tmp, [real.point(f"a{n}", 30 + n) for n in range(3)], export={"seconds": 0.8})
    second = real.fea(tmp, [real.point(f"b{n}", 40 + n) for n in range(3)], export={"seconds": 0.8})
    start.start(first), start.start(second)

    def both():
        deadline = time.monotonic() + 120
        while any(view.view(made).rounds[-1].result is None for made in (first, second)) and time.monotonic() < deadline:
            for made in (first, second):
                if view.view(made).rounds[-1].result is None:
                    start.poll(made)
            time.sleep(0.05)

    counts = traced(tmp, both)
    assert [view.view(made).rounds[-1].result for made in (first, second)] == ["done", "done"]
    assert len(counts) == 6 and max(counts) <= 2, f"六次求解开始时同一时刻在跑的个数：{counts}，槽只有 2 个"


def stopping(tmp: Path) -> None:
    """停止：在跑的求解被结束，已经算好的照常交；再启动只重排没做完的。"""
    import psutil

    made = real.fea(tmp, [real.point("quick", 30), real.point("stuck", 40, "hang")])
    start.start(made)
    real.run(made, until=lambda: real.tasks(made)["quick"][0] == "done" and view.view(made).tasks["stuck"].stage == "solve")
    held = json.loads(next(Path(os.environ["STEMLAB_SLOTS"]).glob("solve-*.json")).read_bytes())["process"]
    assert psutil.pid_exists(held["pid"])
    assert start.stop(made).ok
    status = view.view(made)
    assert status.rounds[-1].result == "stopped" and real.tasks(made) == {"quick": ("done", "finished"), "stuck": ("stopped", None)}
    helpers.wait_for(lambda: not psutil.pid_exists(held["pid"]), seconds=15)
    assert not list(Path(os.environ["STEMLAB_SLOTS"]).glob("solve-*.json")), "槽放掉了"
    assert sorted(rows_of(made)) == ["quick"], "已经算好的照常交"
    start.start(made)
    assert view.view(made).rounds[-1].rerun == ["stuck"]
    start.stop(made)
    assert {name: row["round"] for name, row in rows_of(made).items()} == {"quick": 1}


def judging(tmp: Path) -> None:
    """填了判据：加一份判定结果。有点没有数的那一条，默认不可判。"""
    criteria = {"criteria": [
        {"id": "g1", "what": "转动的最大值不超过 0.07 度", "column": "rotation", "stat": "max", "op": "<=", "limit": 0.07},
        {"id": "g2", "what": "同上，只看有数的点", "column": "rotation", "stat": "max", "op": "<=", "limit": 0.07, "missing": "skip"},
        {"id": "g3", "what": "滑移的 95 分位不超过 10", "column": "slip_p95", "stat": "max", "op": "<=", "limit": 10.0, "missing": "skip"},
        {"id": "g4", "what": "至少三个点有结果", "column": "rotation", "stat": "count", "op": ">=", "limit": 3, "missing": "skip"},
    ]}
    made = real.fea(tmp, [real.point("p1", 30), real.point("p2", 40), real.point("p3", 80)], criteria=criteria)
    start.start(made)
    real.run(made)
    status = view.view(made)
    assert sorted(status.rounds[-1].outputs) == ["archive", "data", "verdict"]
    folder = real.output(made, "verdict")
    assert check_format("report", folder) == []
    said = json.loads((folder / "verdict.json").read_bytes())
    verdicts = {row["id"]: row for row in said["verdicts"]}
    assert (verdicts["g1"]["passed"], verdicts["g1"]["missing"], verdicts["g1"]["used"]) == (None, 1, 2), "有一个点没有数：不可判"
    assert verdicts["g2"]["passed"] is True and verdicts["g2"]["value"] == 2000 / 30000
    assert verdicts["g3"]["passed"] is False and verdicts["g3"]["value"] == 0.95 * 20
    assert verdicts["g4"]["passed"] is False and verdicts["g4"]["value"] == 2
    used = status.frozen["criteria"][0]
    assert said["criteria"]["id"] == used["id"] and said["criteria"]["hash"] == used["hash"]
    assert said["criteria"]["registered"] <= said["criteria"]["round_opened"] == status.rounds[-1].opened


def criteria_written_after_the_round_began(tmp: Path) -> None:
    """判据的登记时间晚于这一轮开始：不拿它判，记一条问题，数据照交。"""
    from plugins.fea import judge

    criteria = {"criteria": [{"id": "g1", "what": "x", "column": "rotation", "stat": "max", "op": "<=", "limit": 1}]}
    made = real.fea(tmp, [real.point("p1", 30)], criteria=criteria)
    genuine, judge.late = judge.late, lambda registered, opened: True
    try:
        start.start(made)
        real.run(made)
    finally:
        judge.late = genuine
    status = view.view(made)
    assert sorted(status.rounds[-1].outputs) == ["archive", "data"]
    assert any("之后才登记" in problem["error"] for problem in status.rounds[-1].problems)


OTHERS = [other_ways_to_fail, nothing_computed, too_many_numerical_failures, solving_is_queued_by_slots,
          two_experiments_share_the_slots, stopping, judging, criteria_written_after_the_round_began]
