"""优化插件的验收情形。每个情形是一个函数：造输入、跑、断言。内核和策略都是假的（tests/packages/）。

选点可重放，可行性不靠策略自觉。BLUEPRINT 里的几个对应蓝图“怎样算做对”的前五条。
"""
from __future__ import annotations

from pathlib import Path

from stemlab.contract import Refused, layout
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.desk.core import query, start
from stemlab.experiments import view
from stemlab.registry import lookup
from tests import helpers, real

SECONDS = 120.0
LENGTHS = [22, 28, 34, 40, 46, 52, 58, 64, 70]         # 后两个放不进去（c0008、c0009）


def refused(made: str, **how) -> str:
    before = len(helpers.entries_of(made))
    try:
        start.start(made, **how)
    except Refused as error:
        assert len(helpers.entries_of(made)) == before, "被拒的时候记录里不多一条"
        return str(error)
    raise AssertionError("启动本该被拒")


def finished(made: str):
    assert start.start(made).ok
    real.run(made, seconds=SECONDS)
    return view.view(made)


def chosen(made: str) -> list[dict]:
    """这个选点实验交出来的一批点的各行。"""
    folder = real.output(made, "points")
    assert check_format("points", folder) == []
    return read_points(folder)


def told(status) -> list[str]:
    return [problem["error"] for problem in status.rounds[-1].problems]


# ---- 1 一份示例策略加一个小候选池：产出一批点，过格式核对，条件写全，每个点带理由 ----

def an_example_strategy_and_a_small_pool(tmp: Path) -> None:
    made = real.opt_pool(tmp)
    status = finished(made)
    assert real.tasks(made) == {"pool": ("done", "generated")} and status.rounds[-1].problems == []
    folder = real.output(made, "pool")
    assert check_format("pool", folder) == []
    rows = read_points(folder)
    assert len(rows) == 12 and all(20 <= row["design"]["length"] <= 80 and row["design"]["behave"] == "ok" for row in rows)
    assert {row["feasible"] for row in rows} == {True, False}
    assert all(row["feasible"] == (row["design"]["length"] <= 60) and row["bone_id"] == real.BONE for row in rows), "可不可行是内核说的"
    assert all(row["info"]["bone_removed"] == row["design"]["length"] * 100.0 for row in rows), "模板化给的量跟着候选走"
    used = [extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package"]
    assert used == ["kernel"]

    picked = real.opt_select(tmp, status.rounds[-1].outputs["pool"]["item"])
    status = finished(picked)
    assert real.tasks(picked) == {"select": ("done", "selected")} and status.rounds[-1].problems == []
    points, by = chosen(picked), {row["name"]: row for row in rows}
    assert len(points) == 3 and read_manifest(real.output(picked, "points"))["condition_keys"] == ["load"]
    for point in points:
        assert point["conditions"] == {"load": 2000.0}, "条件写全"
        assert by[point["name"]]["feasible"] and point["design"] == by[point["name"]]["design"] and point["bone_id"] == real.BONE
        reason = point["reason"]
        assert reason["strategy"] == status.frozen["strategy"][0]["id"] and reason["seed"] == 7, "每个点带理由：哪份策略、种子"
        assert reason["objective"] == {"id": status.frozen["objective"][0]["id"], "version": "v1"} and "model" in reason
        assert reason["why"] and isinstance(reason["score"], (int, float))
    for one in (made, picked):
        for chart in query.charts(one):
            assert query.chart(one, chart["name"]) is not None, chart


# ---- 2 同样的输入和种子重放出同一批点 ----

def the_same_inputs_and_seed_replay_the_same_points(tmp: Path) -> None:
    from plugins.opt import replay

    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    strategy, goal, how = real.package("strategy_fake", tmp), real.objective(), real.how()
    first = real.opt_select(tmp, candidates["id"], strategy, goal, how)
    status = finished(first)
    hashes = [point["hash"] for point in chosen(first)]
    before = helpers.snapshot(layout.data_root())
    said = replay.replay(first)
    assert said["same"] and said["points"] == hashes == said["recorded"], said
    assert helpers.snapshot(layout.data_root()) == before, "重放不往账上写一个字"

    recorded = [extra["info"]["replay"] for extra in status.rounds[-1].extra if extra["source"] == "plugin"]
    assert len(recorded) == 1 and recorded[0]["seed"] == 7 and recorded[0]["count"] == 3
    assert recorded[0]["strategy"] == {"id": strategy["id"], "hash": status.frozen["strategy"][0]["hash"]}
    assert recorded[0]["inputs"] == {"objective": [goal["id"]], "strategy": [strategy["id"]], "pool": [candidates["id"]],
                                     "defaults": [how["id"]], "data": [], "predictor": []}, "每样输入的编号都记着"

    second = real.opt_select(tmp, candidates["id"], strategy, goal, how)
    finished(second)
    assert [point["hash"] for point in chosen(second)] == hashes, "另开一个实验，同样的输入和种子：同一批点"
    other = real.opt_select(tmp, candidates["id"], strategy, goal, real.how(seed=8))
    finished(other)
    assert [point["hash"] for point in chosen(other)] != hashes, "换一个种子，选的就不一样"


# ---- 4 写出的一批点再独立用约束核一遍；故意选不可行点的策略，这些点被拦下并记成问题 ----

def infeasible_picks_are_blocked(tmp: Path) -> None:
    from plugins.opt import feasible

    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    limit = real.objective(constraints=[{"id": "c1", "what": "柄长不超过 45", "on": "design", "column": "length", "op": "<=", "limit": 45}])
    made = real.opt_select(tmp, candidates["id"], real.package("strategy_fake", tmp, behave="infeasible"), limit, real.how(count=5))
    status = finished(made)
    assert real.tasks(made) == {"select": ("done", "selected")}
    points = chosen(made)
    assert 1 <= len(points) <= 4 and all(point["design"]["length"] <= 45 for point in points)
    said = told(status)
    assert any("c0008" in text and "已拦下" in text and "放不进去" in text for text in said), said
    assert any("c0009" in text and "no entry offset" in text for text in said), "内核说的为什么放不进去，问题里有"
    assert any("c1" in text and "柄长不超过 45" in text for text in said), "不满足登记的约束的也拦下"
    assert feasible.recheck(points, read_points(lookup.content(candidates["id"])), lookup.content(limit["id"])) == [], \
        "写出的一批点再独立核一遍，全部满足"

    nobody = real.objective(constraints=[{"id": "c9", "what": "谁也过不了", "on": "info", "column": "bone_removed", "op": "<", "limit": 0}])
    none = real.opt_select(tmp, candidates["id"], goal=nobody)
    status = finished(none)
    assert real.tasks(none) == {"select": ("done", "no_feasible")} and status.rounds[-1].outputs == {}
    assert next(row for row in status.outcomes if row["name"] == "no_feasible")["category"] == "conclusion"

    stray = real.opt_select(tmp, candidates["id"], real.package("strategy_fake", tmp, behave="unknown"))
    status = finished(stray)
    assert real.tasks(stray) == {"select": ("done", "selected")} and len(chosen(stray)) == 3
    assert any("c9999" in text and "候选池里没有" in text for text in told(status))


# ---- 5 没填预测器和数据也能启动；策略需要它们却没填，检查不过 ----

def data_and_predictor_are_optional_unless_the_strategy_needs_them(tmp: Path) -> None:
    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    wants_data = real.package("strategy_fake", tmp, needs=["data"])
    assert "数据" in refused(real.opt_select(tmp, candidates["id"], wants_data))
    measured = real.data(tmp, real.data_rows([(25.0, 2000.0), (45.0, 2000.0), (57.0, 2000.0)]))
    made = real.opt_select(tmp, candidates["id"], wants_data, defaults=real.how(count=2), datas=[measured])
    finished(made)
    points = chosen(made)
    assert sorted(point["design"]["length"] for point in points) == [52.0, 58.0], "离算过的、转动最小的那个点最近的两个候选"
    assert points[0]["reason"]["model"] == "nearest neighbour on the given data" and points[0]["reason"]["data"] == [measured["id"]]
    assert points[0]["reason"]["model_from"] == "策略内部的模型"

    wants_predictions = real.package("strategy_fake", tmp, needs=["predictions"])
    assert "预测器" in refused(real.opt_select(tmp, candidates["id"], wants_predictions))
    outside = real.outside_predictor(tmp)
    made = real.opt_select(tmp, candidates["id"], wants_predictions, defaults=real.how(count=2), predictor=outside)
    status = finished(made)
    points = chosen(made)
    assert [point["design"]["length"] for point in points] == [58.0, 52.0], "预测的转动最小的两个可行候选"
    assert points[0]["reason"]["predictor"] == outside["id"] and points[0]["reason"]["model"] == "the registered predictor"
    used = sorted(extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package")
    assert used == ["predictor", "strategy"], "用了哪个预测器、哪份策略，核心都记进了来历"


BLUEPRINT = [an_example_strategy_and_a_small_pool, the_same_inputs_and_seed_replay_the_same_points, infeasible_picks_are_blocked,
             data_and_predictor_are_optional_unless_the_strategy_needs_them]


# ---- 另外几样 ----

def a_strategy_that_crashes(tmp: Path) -> None:
    """策略自己崩了：记成策略出错（待查），什么都不交。"""
    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    made = real.opt_select(tmp, candidates["id"], real.package("strategy_fake", tmp, behave="crash"))
    status = finished(made)
    assert real.tasks(made) == {"select": ("failed", "strategy_error")} and status.rounds[-1].outputs == {}
    assert next(row for row in status.outcomes if row["name"] == "strategy_error")["category"] == "unclear"
    assert any("crashing on purpose" in text for text in told(status)), "它崩之前说的话留着"


def a_strategy_that_ignores_the_seed_cannot_be_replayed(tmp: Path) -> None:
    """不用种子的策略：选得出点，但重放对不上，重放如实说。"""
    from plugins.opt import replay

    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    made = real.opt_select(tmp, candidates["id"], real.package("strategy_fake", tmp, behave="dice"))
    finished(made)
    again = [replay.replay(made) for _ in range(4)]         # 七个里随机排出三个，四次都碰巧一样的可能可以不计
    assert not all(said["same"] for said in again)
    assert "不可重放" in next(said["why"] for said in again if not said["same"])
    assert replay.replay(made, 1)["recorded"] == [point["hash"] for point in chosen(made)]


def things_refused_before_the_start(tmp: Path) -> None:
    candidates = real.pool(tmp, real.pool_rows(LENGTHS))
    assert "version" in refused(real.opt_select(tmp, candidates["id"], goal=real.objective(version="")))
    assert "goal" in refused(real.opt_select(tmp, candidates["id"], goal=real.objective(objectives=[{"column": "rotation", "goal": "smallest"}])))
    assert "约束" in refused(real.opt_select(tmp, candidates["id"], goal=real.objective(constraints=[{"id": "c1", "on": "design"}])))
    assert "count" in refused(real.opt_select(tmp, candidates["id"], defaults=real.setting({"conditions": {"load": 2000.0}, "seed": 1})))
    assert "conditions" in refused(real.opt_select(tmp, candidates["id"], defaults=real.setting({"count": 2, "seed": 1})))
    both = real.pool(tmp, real.pool_rows([30, 40]) + [dict(row, name="d" + row["name"]) for row in real.pool_rows([35], "femur043")])
    assert "一根骨" in refused(real.opt_select(tmp, both["id"]))
    elsewhere = real.data(tmp, real.data_rows([(30.0, 2000.0)], bone_id="femur043"), bone_id="femur043")
    assert "femur043" in refused(real.opt_select(tmp, candidates["id"], datas=[elsewhere]))

    # 同一版目标：目标里的列，在各份数据和预测器里得是同一个量（名字相同、单位相同），预测器还得预测得了它
    radians = [dict(column, unit="rad") if column["name"] == "rotation" else column for column in real.DATA_COLUMNS]
    degrees = real.data(tmp, real.data_rows([(31.0, 2000.0)]))
    other = real.data(tmp, real.data_rows([(32.0, 2000.0)]), columns=radians)
    assert "不是同一个量" in refused(real.opt_select(tmp, candidates["id"], datas=[degrees, other]))
    assert "不是同一个量" in refused(real.opt_select(tmp, candidates["id"], datas=[other], predictor=real.outside_predictor(tmp)))
    slip = real.objective(objectives=[{"column": "slip_p95", "goal": "min"}])
    assert "预测不了" in refused(real.opt_select(tmp, candidates["id"], goal=slip, predictor=real.outside_predictor(tmp)))

    # 不同内核算出来的数不放在一起：候选池、数据、预测器都记着是哪个内核算的，记了而对不上的被拒
    theirs = dict(real.MADE_BY, kernel={"name": "another-kernel"}, derive=None)
    their_pool = real.pool(tmp, real.pool_rows(LENGTHS), made_by=theirs)
    assert "another-kernel" in refused(real.opt_select(tmp, their_pool["id"], datas=[degrees])), "候选池和数据不是同一个内核"
    mixed = [degrees, real.data(tmp, real.data_rows([(33.0, 2000.0)]), made_by=dict(real.MADE_BY, kernel={"name": "another-kernel"}))]
    assert "another-kernel" in refused(real.opt_select(tmp, candidates["id"], datas=mixed)), "两份数据不是同一个内核"
    ours = real.outside_predictor(tmp, made_by=real.MADE_BY)
    assert "another-kernel" in refused(real.opt_select(tmp, their_pool["id"], predictor=ours)), "预测器和候选池不是同一个内核"

    assert "count" in refused(real.opt_pool(tmp, {"design": real.SPACE["design"], "seed": 1}))
    assert "内核要" in refused(real.opt_pool(tmp, {"design": {"length": [20, 60]}, "count": 3, "seed": 1}))
    assert "length" in refused(real.opt_pool(tmp, {"design": {"length": [60, 20], "behave": {"values": ["ok"]}}, "count": 3, "seed": 1}))
    assert "template" in refused(real.opt_pool(tmp, kernel=real.package("kernel_fake", tmp, modes=["build", "post"])))


def stopping_a_pool(tmp: Path) -> None:
    """停止：在跑的模板化被结束；再启动重新来过。"""
    made = real.opt_pool(tmp)
    start.start(made)
    assert start.stop(made).ok
    assert view.view(made).rounds[-1].result == "stopped" and real.tasks(made) == {"pool": ("stopped", None)}
    start.start(made)
    real.run(made, seconds=SECONDS)
    assert real.tasks(made) == {"pool": ("done", "generated")} and len(read_points(real.output(made, "pool"))) == 12
    kernel = view.view(made).frozen["kernel"][0]["hash"]
    assert read_manifest(real.output(made, "pool"))["made_by"] == {"kernel": {"package": kernel}, "derive": None}, \
        "候选池记着是哪个内核模板化的"


OTHERS = [a_strategy_that_crashes, a_strategy_that_ignores_the_seed_cannot_be_replayed, things_refused_before_the_start, stopping_a_pool]
