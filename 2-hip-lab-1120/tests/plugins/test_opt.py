"""优化插件的验收：选点可重放，可行性不靠策略自觉。情形都写在 opt_cases.py 里。"""
from __future__ import annotations

import pytest

from stemlab.contract import hashing
from stemlab.contract.formats.points import read_points
from tests import helpers, real
from tests.plugins import opt_cases


@pytest.mark.parametrize("case", opt_cases.BLUEPRINT + opt_cases.OTHERS, ids=lambda case: case.__name__)
def test_opt(real_lab, data, tmp_path, case):
    case(tmp_path)


# ---- 3 换一份策略：不改这个插件的任何文件 ----

def test_another_strategy_changes_no_file_of_the_plugin(real_lab, data, tmp_path):
    plugin = helpers.REPO / "plugins" / "opt"
    before = hashing.hash_tree(plugin, ignore=("__pycache__",))
    candidates = real.pool(tmp_path, real.pool_rows(opt_cases.LENGTHS))
    lengths = {}
    for name in ("strategy_fake", "strategy_longest"):
        made = real.opt_select(tmp_path, candidates["id"], real.package(name, tmp_path))
        opt_cases.finished(made)
        assert real.tasks(made) == {"select": ("done", "selected")}
        lengths[name] = [point["design"]["length"] for point in read_points(real.output(made, "points"))]
    assert lengths["strategy_longest"] == [58.0, 52.0, 46.0] != lengths["strategy_fake"], "两份策略选的不一样，各是各的"
    assert hashing.hash_tree(plugin, ignore=("__pycache__",)) == before, "换策略只是换一样登记的输入，插件的文件一个没动"


# ---- 冻结文件里的规则，直接试 ----

def test_what_counts_as_feasible():
    from plugins.opt import feasible

    goal = {"version": "v1", "objectives": [{"column": "rotation", "goal": "min"}], "constraints": [
        {"id": "c1", "what": "不太长", "on": "design", "column": "length", "op": "<=", "limit": 50},
        {"id": "c2", "what": "去骨不多", "on": "info", "column": "bone_removed", "op": "<", "limit": 4500}]}
    assert feasible.problems(goal) == []
    pool = real.pool_rows([30, 44, 48, 55, 70])
    assert [bool(feasible.violations(row, goal)) for row in pool] == [False, False, True, True, True]
    assert "c2" in feasible.violations(pool[2], goal)[0] and "c1" in feasible.violations(pool[3], goal)[0]
    assert len(feasible.violations(pool[4], goal)) == 3 and "放不进去" in feasible.violations(pool[4], goal)[0]
    assert feasible.violations({"name": "x", "feasible": True, "design": {}, "info": {}}, goal), "要比的那一项没有：按不满足算"

    picks = [{"name": "c0003"}, {"name": "c0002"}, {"name": "c0002"}, {"name": "nobody"}, "junk", {"name": "c0001"}]
    made, blocked = feasible.points(picks, pool, goal, {"load": 2000.0})
    assert [row["name"] for row in made] == ["c0002", "c0001"] and len(blocked) == 4
    assert made[0] == {"name": "c0002", "bone_id": real.BONE, "design": {"length": 44.0, "behave": "ok"},
                       "conditions": {"load": 2000.0}, "reason": None}
    assert [row["name"] for row in feasible.points(picks, pool, goal, {}, count=1)[0]] == ["c0002"], "最多留 count 个，照策略给的先后"
    assert feasible.points(None, pool, goal, {}) == ([], [])
    assert feasible.recheck(made, pool, goal) == []
    assert "不在候选池里" in feasible.recheck([dict(made[0], design={"length": 45.0, "behave": "ok"})], pool, goal)[0]
    assert "c1" in feasible.recheck([dict(made[0], design=pool[3]["design"])], pool, goal)[0]

    for bad in ([], {"version": "v1"}, dict(goal, objectives=[]), dict(goal, objectives=[{"column": "x", "goal": "down"}]),
                dict(goal, objectives=[{"column": "x", "goal": "min", "weight": 0}]), dict(goal, constraints={}),
                dict(goal, constraints=[dict(goal["constraints"][0], op="~")]), dict(goal, constraints=goal["constraints"][:1] * 2)):
        assert feasible.problems(bad), bad


def test_what_a_design_range_looks_like():
    from plugins.opt import feasible, pool

    space = {"design": {"length": [20.0, 60.0], "kind": {"values": ["a", "b"]}}, "count": 40, "seed": 3}
    assert feasible.range_problems(space) == []
    designs = pool.designs(space)
    assert [one["name"] for one in designs[:2]] == ["c0001", "c0002"] and len(designs) == 40
    assert all(feasible.inside(one["design"], space) is None for one in designs)
    lengths = sorted(one["design"]["length"] for one in designs)
    assert all(20 + index <= value <= 21 + index for index, value in enumerate(lengths)), "拉丁超立方：每一段正好一个"
    assert pool.designs(space) == designs and pool.designs(dict(space, seed=4)) != designs, "同一个种子取出同一批设计"
    assert "length" in feasible.inside({"length": 61.0, "kind": "a"}, space) and "kind" in feasible.inside({"length": 30.0, "kind": "c"}, space)
    assert "对不上" in feasible.inside({"length": 30.0}, space)
    for bad in ({}, {"design": {}}, dict(space, count=0), dict(space, seed=None), dict(space, design={"length": [1]}),
                dict(space, design={"length": {"values": []}}), dict(space, design={"length": [3, 1]})):
        assert feasible.range_problems(bad), bad
