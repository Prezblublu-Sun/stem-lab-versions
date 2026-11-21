"""选点策略的测试。策略的代码在 external/strategies/；测试放在这里，是因为检查只跑 tests/、tests_free/ 和 plugins/ 下的测试。

前一半拿人造的小问题直接试算法：答案手上有数（最低点在哪、两个目标之间的取舍线在哪）。
后一半把策略打成包、登记，经真的优化插件走一遍：点交得出来、理由写全、可以重放。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[2] / "external" / "strategies"
sys.path.insert(0, str(HERE))           # 策略的代码是照“在包的 code/ 文件夹里跑”写的：import common

import bayes  # noqa: E402
import common  # noqa: E402
import predicted  # noqa: E402
import spacefill  # noqa: E402

_spec = importlib.util.spec_from_file_location("strategies_build", HERE / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

LOAD = {"load": 2000.0}


# ---------------------------------------------------------------- 造输入

def f1(a, b):
    return 0.05 + (a - 0.3) ** 2 + (b - 0.7) ** 2


def f2(a, b):
    return 0.05 + (a - 0.8) ** 2 + (b - 0.2) ** 2


def square(count: int, seed: int, fits=lambda a, b: True) -> list:
    """单位正方形里随机撒的候选。"""
    return [{"name": f"c{number:04d}", "bone_id": "b", "design": {"a": float(a), "b": float(b), "kind": "rule"},
             "feasible": bool(fits(a, b)), "info": {}} for number, (a, b) in enumerate(np.random.default_rng(seed).uniform(size=(count, 2)))]


def job_of(candidates, columns=("f1",), count=8, seed=7, data=(), predictions=None, constraints=(), goal="min", weights=None) -> dict:
    goals = [{"column": column, "goal": goal, **({"weight": weights[index]} if weights else {})} for index, column in enumerate(columns)]
    return {"objective": {"version": "v1", "objectives": goals, "constraints": list(constraints)}, "candidates": candidates,
            "conditions": dict(LOAD), "count": count, "seed": seed, "data": [str(folder) for folder in data], "predictions": predictions}


def measured(folder: Path, designs, rows, columns, conditions=LOAD) -> Path:
    """一份数据：designs 的每个设计配上 rows 里它的各个数。"""
    folder.mkdir(parents=True)
    listed = ([{"name": name, "unit": "1", "meaning": name, "role": "design"} for name in designs[0]]
              + [{"name": name, "unit": "N", "meaning": name, "role": "condition"} for name in conditions]
              + [{"name": name, "unit": "1", "meaning": name, "role": "label"} for name in columns])
    (folder / "manifest.json").write_text(json.dumps({"columns": listed}), encoding="utf-8")
    lines = [json.dumps({"point": str(number), "bone_id": "b", "outcome": "finished", "values": {**design, **conditions, **dict(zip(columns, row))}})
             for number, (design, row) in enumerate(zip(designs, rows))]
    (folder / "rows.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return folder


def some_designs(count: int, seed: int) -> list:
    return [{"a": float(a), "b": float(b), "kind": "rule"} for a, b in np.random.default_rng(seed).uniform(size=(count, 2))]


def spot(candidates, chosen) -> np.ndarray:
    by = {one["name"]: one for one in candidates}
    return np.array([[by[pick["name"]]["design"]["a"], by[pick["name"]]["design"]["b"]] for pick in chosen])


# ---------------------------------------------------------------- 共用的那几样

def test_what_may_be_chosen_follows_the_rule_the_system_enforces_afterwards():
    from plugins.opt import feasible

    objective = {"version": "v1", "objectives": [{"column": "y", "goal": "min"}], "constraints": [
        {"id": "c1", "what": "a 不超过 0.5", "on": "design", "column": "a", "op": "<=", "limit": 0.5},
        {"id": "c2", "what": "去骨量不超过 30", "on": "info", "column": "removed", "op": "<=", "limit": 30}]}
    cases = [{"feasible": True, "design": {"a": 0.4}, "info": {"removed": 20}}, {"feasible": False, "design": {"a": 0.4}, "info": {"removed": 20}},
             {"feasible": True, "design": {"a": 0.6}, "info": {"removed": 20}}, {"feasible": True, "design": {"a": 0.4}, "info": {"removed": 31}},
             {"feasible": True, "design": {"a": 0.4}, "info": {}}, {"feasible": True, "design": {"a": "rule"}, "info": {"removed": 20}},
             {"feasible": "yes", "design": {"a": 0.4}, "info": {"removed": 20}}]
    said = [common.allowed(case, objective) for case in cases]
    assert said == [feasible.violations(case, objective) == [] for case in cases] == [True, False, False, False, False, False, False]


def test_designs_become_coordinates_between_zero_and_one():
    designs = [{"a": 2.0, "b": 5.0, "kind": "rule", "fixed": 1.5}, {"a": 4.0, "b": 5.0, "kind": 3.0, "fixed": 1.5}, {"a": 3.0, "b": 5.0, "kind": "rule", "fixed": 1.5}]
    space = common.Space(designs)
    assert [name for name, _, _ in space.numeric] == ["a"] and [name for name, _ in space.listed] == ["kind"], "没变过的项不占坐标"
    placed = space.matrix(designs)
    assert placed.shape == (3, 3) and list(placed[:, 0]) == [0.0, 1.0, 0.5]
    assert np.isclose(np.linalg.norm(placed[0, 1:] - placed[1, 1:]), 1.0), "两个不同的值之间算相距 1"
    assert np.allclose(placed[0, 1:], placed[2, 1:])


def test_the_slope_the_fit_follows_is_the_true_slope():
    rng = np.random.default_rng(3)
    x = rng.uniform(size=(40, 4))
    model = common.Gp(x, np.sin(3 * x[:, 0]) + x[:, 1] ** 2 + 0.05 * rng.standard_normal(40), seed=1)
    theta = np.array([0.3, -0.2, 0.5, 0.1, -3.0])
    _, slope = model._loss(theta)
    by_steps = [(model._loss(theta + step)[0] - model._loss(theta - step)[0]) / 2e-6 for step in np.eye(5) * 1e-6]
    assert np.allclose(slope, by_steps, rtol=1e-4, atol=1e-5), (slope, by_steps)


def test_the_model_learns_a_smooth_function_and_knows_how_sure_it_is():
    rng = np.random.default_rng(3)
    x, test = rng.uniform(size=(40, 4)), rng.uniform(size=(300, 4))
    truth = lambda at: np.sin(3 * at[:, 0]) + at[:, 1] ** 2  # noqa: E731
    model = common.Gp(x, truth(x), seed=1)
    mean, deviation = model.predict(test)
    assert np.sqrt(((mean - truth(test)) ** 2).mean()) < 0.2 * truth(test).std(), "比“一律猜平均值”好五倍以上"
    assert (np.abs(mean - truth(test)) <= 1.96 * deviation + 0.01).mean() > 0.85, "区间盖得住真值"
    assert model.lengths[2] > 5 * model.lengths[0] and model.lengths[3] > 5 * model.lengths[0], "不起作用的两项，长度被放得很长"
    near, far = model.predict(x[:1])[1][0], model.predict(np.full((1, 4), 3.0))[1][0]
    assert near < 0.2 * far, "算过的点上有把握，离得远的地方没把握"
    worst = int(np.argmax(deviation))
    model.add(test[worst], float(mean[worst]))
    assert model.predict(test[worst:worst + 1])[1][0] < 0.2 * deviation[worst], "加进去的点上，把握跟着变大"
    noisy = common.Gp(x, truth(x) + 0.05 * rng.standard_normal(40), seed=1)
    assert noisy.noise > 20 * model.noise, "数据里有噪声，模型看得出来"


def test_expected_improvement_is_what_its_name_says():
    rng = np.random.default_rng(5)
    draws = rng.standard_normal(400_000)
    for mean, deviation, best in ((0.0, 1.0, 0.0), (1.0, 0.5, 0.2), (-0.3, 0.2, 0.0)):
        sampled = np.maximum(best - (mean + deviation * draws), 0.0).mean()
        assert abs(float(common.expected_improvement(mean, deviation, best)) - sampled) < 5e-3


# ---------------------------------------------------------------- 均匀铺点

def line(values) -> list:
    return [{"name": f"c{number}", "bone_id": "b", "design": {"a": a}, "feasible": True, "info": {}} for number, a in enumerate(values, start=1)]


def test_spreading_takes_the_far_end_first_and_then_the_widest_gap(tmp_path):
    done = measured(tmp_path / "done", [{"a": 0.0}], [[1.0]], ["f1"])
    chosen, model = spacefill.choose(job_of(line([0.0, 0.2, 0.5, 0.8, 1.0]), count=3, data=[done]))
    assert [pick["name"] for pick in chosen[:2]] == ["c5", "c3"] and model is None, "先 1.0（离算过的 0 最远），再 0.5（最宽的空当中间）"
    assert chosen[2]["name"] in ("c2", "c4"), "0.2 和 0.8 离已有的点一样远，照种子取一个"
    assert [pick["score"] for pick in chosen] == [1.0, 0.5, pytest.approx(0.2)] and "最远" in chosen[0]["why"]


def test_spreading_never_takes_what_cannot_be_chosen_or_was_already_computed(tmp_path):
    candidates = square(300, 5, fits=lambda a, b: a + b < 1.6)
    limit = {"id": "c1", "what": "a 不小于 0.1", "on": "design", "column": "a", "op": ">=", "limit": 0.1}
    done = measured(tmp_path / "done", [one["design"] for one in candidates[:40]], [[1.0]] * 40, ["f1"])
    other = measured(tmp_path / "other", [one["design"] for one in candidates[40:60]], [[1.0]] * 20, ["f1"], conditions={"load": 999.0})
    chosen, _ = spacefill.choose(job_of(candidates, count=500, data=[done, other], constraints=[limit]))
    by = {one["name"]: one for one in candidates}
    names = [pick["name"] for pick in chosen]
    assert len(set(names)) == len(names) and all(by[name]["feasible"] and by[name]["design"]["a"] >= 0.1 for name in names)
    assert not set(names) & {one["name"] for one in candidates[:40]}, "算过的不再选"
    allowed = [one for one in candidates[40:] if one["feasible"] and one["design"]["a"] >= 0.1]
    assert len(names) == len(allowed), "要的比能选的多，就把能选的都给出来；别的条件下算过的不算算过"


def test_the_seed_picks_the_first_point_and_the_same_seed_gives_the_same_batch():
    candidates = square(200, 5)
    one, again, other = (spacefill.choose(job_of(candidates, seed=seed))[0] for seed in (7, 7, 8))
    assert one == again and [pick["name"] for pick in one] != [pick["name"] for pick in other]
    assert one[0]["score"] is None and "照种子" in one[0]["why"]


def test_a_spread_batch_covers_the_square_better_than_a_random_one():
    candidates = square(400, 5)
    gap = lambda spots: min(np.linalg.norm(spots - one, axis=1)[np.arange(len(spots)) != index].min() for index, one in enumerate(spots))  # noqa: E731
    even = gap(spot(candidates, spacefill.choose(job_of(candidates, count=12))[0]))
    rng = np.random.default_rng(1)
    loose = np.mean([gap(spot(candidates, [candidates[index] for index in rng.choice(400, 12, replace=False)])) for _ in range(20)])
    assert even > 3 * loose, (even, loose)


# ---------------------------------------------------------------- 贝叶斯优化

def test_bayes_goes_for_the_valley(tmp_path):
    candidates, seen = square(600, 5, fits=lambda a, b: a + b < 1.6), some_designs(30, 9)
    data = measured(tmp_path / "data", seen, [[f1(one["a"], one["b"])] for one in seen], ["f1"])
    job = job_of(candidates, data=[data])
    chosen, model = bayes.choose(job)
    by = {one["name"]: one for one in candidates}
    names = [pick["name"] for pick in chosen]
    assert len(names) == len(set(names)) == 8 and all(by[name]["feasible"] for name in names)
    every = sorted(f1(one["design"]["a"], one["design"]["b"]) for one in candidates if one["feasible"])
    first = f1(*spot(candidates, chosen[:1])[0])
    assert first <= every[len(every) // 50], f"第一个点在池里最好的 2% 里：{first}，池里最好的是 {every[0]}"
    assert "期望改进" in chosen[0]["why"] and "f1 预测" in chosen[0]["why"] and "95% 区间" in chosen[0]["why"]
    assert model.startswith("策略内部的高斯过程") and "30 行" in model and "f1 取了对数" in model
    assert bayes.choose(job)[0] == chosen, "同样的输入选出同样的点"
    assert bayes.choose(dict(job, seed=8))[0][0]["name"] == names[0], "一个目标时，第一个点和种子无关：它就是期望改进最大的那个"


def test_bayes_turns_a_goal_to_maximise_into_the_same_search(tmp_path):
    candidates, seen = square(300, 5), some_designs(30, 9)
    low = measured(tmp_path / "low", seen, [[f1(one["a"], one["b"])] for one in seen], ["f1"])
    high = measured(tmp_path / "high", seen, [[-f1(one["a"], one["b"])] for one in seen], ["f1"])
    down, _ = bayes.choose(job_of(candidates, count=1, data=[low]))
    up, model = bayes.choose(job_of(candidates, count=1, data=[high], goal="max"))
    assert f1(*spot(candidates, up)[0]) < 0.08 and f1(*spot(candidates, down)[0]) < 0.08, "两种写法都找到了谷底附近"
    assert "取了对数" not in model, "有负数的列不取对数"


def test_bayes_only_learns_from_rows_computed_under_the_same_conditions(tmp_path):
    candidates, seen, misleading = square(300, 5), some_designs(30, 9), some_designs(60, 4)
    right = measured(tmp_path / "right", seen, [[f1(one["a"], one["b"])] for one in seen], ["f1"])
    wrong = measured(tmp_path / "wrong", misleading, [[f2(one["a"], one["b"])] for one in misleading], ["f1"], conditions={"load": 3000.0})
    alone, _ = bayes.choose(job_of(candidates, count=4, data=[right]))
    mixed, model = bayes.choose(job_of(candidates, count=4, data=[right, wrong]))
    assert alone == mixed and "30 行" in model, "别的载荷下算出来的行，一行都没用"


def test_bayes_spreads_its_batch_along_the_trade_off_between_two_goals(tmp_path):
    candidates, seen = square(600, 5), some_designs(30, 9)
    data = measured(tmp_path / "data", seen, [[f1(one["a"], one["b"]), f2(one["a"], one["b"])] for one in seen], ["f1", "f2"])
    chosen, model = bayes.choose(job_of(candidates, columns=("f1", "f2"), data=[data]))
    assert "ParEGO" in model and len(chosen) == 8
    both = lambda spots: np.column_stack([f1(spots[:, 0], spots[:, 1]), f2(spots[:, 0], spots[:, 1])])  # noqa: E731
    pool, picked = both(spot(candidates, candidates)), both(spot(candidates, chosen))
    front = pool[[not bool(np.any(np.all(pool <= row, axis=1) & np.any(pool < row, axis=1))) for row in pool]]
    close = [float(np.linalg.norm(front - row, axis=1).min()) for row in picked]
    assert sum(gap < 0.03 for gap in close) >= 6, f"八个点里至少六个贴着真正的取舍线：{np.round(close, 3)}"
    assert picked[:, 0].max() - picked[:, 0].min() > 0.15, "不是挤在线上的同一处"

    def volume(rows) -> float:
        """两个目标都往小里优化时，这些点合起来压住了多大一块（参照点 (1, 1)）。"""
        kept, edge, total = sorted(map(tuple, rows)), 1.0, 0.0
        for a, b in kept:
            if b < edge:
                total += (1.0 - a) * (edge - b)
                edge = b
        return total

    start = both(np.array([[one["a"], one["b"]] for one in seen]))
    rng = np.random.default_rng(2)
    by_luck = [volume(np.vstack([start, pool[rng.choice(len(pool), 8, replace=False)]])) - volume(start) for _ in range(30)]
    assert volume(np.vstack([start, picked])) - volume(start) > 2 * float(np.mean(by_luck)), "比随手抓八个点多压住一倍以上"


def test_bayes_leans_towards_the_goal_given_more_weight(tmp_path):
    candidates, seen = square(600, 5), some_designs(30, 9)
    data = measured(tmp_path / "data", seen, [[f1(one["a"], one["b"]), f2(one["a"], one["b"])] for one in seen], ["f1", "f2"])
    first, _ = bayes.choose(job_of(candidates, columns=("f1", "f2"), data=[data], weights=[20.0, 1.0]))
    second, _ = bayes.choose(job_of(candidates, columns=("f1", "f2"), data=[data], weights=[1.0, 20.0]))
    lean = lambda chosen: float(np.mean(f1(*spot(candidates, chosen).T) - f2(*spot(candidates, chosen).T)))  # noqa: E731
    assert lean(first) < lean(second) - 0.05, (lean(first), lean(second))


def test_bayes_does_not_choose_when_the_data_cannot_carry_a_model(tmp_path):
    candidates, seen = square(100, 5), some_designs(4, 9)
    thin = measured(tmp_path / "thin", seen, [[f1(one["a"], one["b"])] for one in seen], ["f1"])
    with pytest.raises(bayes.Unusable, match="只有 4 行，至少要 6 行"):
        bayes.choose(job_of(candidates, data=[thin]))
    other = measured(tmp_path / "other", [{"length": 1.0}] * 9, [[1.0]] * 9, ["f1"])
    with pytest.raises(bayes.Unusable, match="设计项和候选池里的不一样"):
        bayes.choose(job_of(candidates, data=[other]))


# ---------------------------------------------------------------- 用预测器

def guesses(candidates, wide=()) -> list:
    """预测器对可行的候选给的预测：值就是真值，区间是 ±10%；wide 里的候选区间是 ±90%。"""
    rows = []
    for one in candidates:
        if one["feasible"]:
            values = {"f1": f1(one["design"]["a"], one["design"]["b"]), "f2": f2(one["design"]["a"], one["design"]["b"])}
            part = 0.9 if one["name"] in wide else 0.1
            rows.append({"name": one["name"], "values": values, "lower": {key: (1 - part) * value for key, value in values.items()},
                         "upper": {key: (1 + part) * value for key, value in values.items()}})
    return rows


def test_layers_peel_one_front_after_another():
    values = np.array([[1.0, 5.0], [2.0, 2.0], [5.0, 1.0], [3.0, 3.0], [4.0, 4.0], [2.0, 2.0]])
    assert list(predicted.layers(values)) == [1, 1, 1, 2, 3, 1]
    assert list(predicted.layers(values, enough=3)) == [1, 1, 1, 2, 2, 1], "够数了就不往下分"


def test_predicted_takes_the_best_predicted_values_and_skips_what_has_no_prediction():
    candidates = square(300, 5, fits=lambda a, b: a + b < 1.6)
    known = [row for row in guesses(candidates) if row["name"] != "c0000"][:150]
    chosen, model = predicted.choose(job_of(candidates, count=5, predictions=known), gap=0.0)
    values = {row["name"]: row["values"]["f1"] for row in known}
    assert [pick["name"] for pick in chosen] == sorted(values, key=values.get)[:5] and model == "登记的预测器，拿预测值比"
    assert "f1 预测" in chosen[0]["why"] and "区间" in chosen[0]["why"] and chosen[0]["score"] == 0.0
    assert predicted.choose(job_of(candidates, predictions=None))[0] == [], "没有预测就一个都不选"


def test_predicted_keeps_near_twins_out_until_they_are_needed():
    candidates = line([0.50, 0.51, 0.9, 0.1])
    known = [{"name": one["name"], "values": {"f1": value}, "lower": {"f1": value}, "upper": {"f1": value}}
             for one, value in zip(candidates, (1.0, 1.1, 2.0, 3.0))]
    assert [pick["name"] for pick in predicted.choose(job_of(candidates, count=2, predictions=known))[0]] == ["c1", "c3"], "c2 紧挨着 c1，跳过"
    late = predicted.choose(job_of(candidates, count=4, predictions=known))[0]
    assert [pick["name"] for pick in late] == ["c1", "c3", "c4", "c2"] and "不够数才补进来" in late[3]["why"]


def test_optimistic_reaches_for_the_candidates_the_predictor_is_unsure_about():
    candidates = square(300, 5)
    plain, _ = predicted.choose(job_of(candidates, count=5, predictions=guesses(candidates)), pick="optimistic", gap=0.0)
    unsure = sorted(candidates, key=lambda one: f1(one["design"]["a"], one["design"]["b"]))[40]["name"]
    assert unsure not in [pick["name"] for pick in plain]
    chosen, model = predicted.choose(job_of(candidates, count=5, predictions=guesses(candidates, wide=[unsure])), pick="optimistic", gap=0.0)
    assert chosen[0]["name"] == unsure and model == "登记的预测器，拿预测区间里有利的那一端比"
    assert unsure not in [pick["name"] for pick in predicted.choose(job_of(candidates, count=5, predictions=guesses(candidates, wide=[unsure])), gap=0.0)[0]]


def test_with_two_goals_predicted_takes_the_front_and_orders_it_by_the_weights():
    candidates = square(400, 5)
    chosen, _ = predicted.choose(job_of(candidates, columns=("f1", "f2"), predictions=guesses(candidates), weights=[1.0, 1.0]))
    pairs = np.column_stack([f1(*spot(candidates, candidates).T), f2(*spot(candidates, candidates).T)])
    front = {one["name"] for one, row in zip(candidates, pairs) if not np.any(np.all(pairs <= row, axis=1) & np.any(pairs < row, axis=1))}
    assert {pick["name"] for pick in chosen} <= front and all("第 1 层" in pick["why"] for pick in chosen)
    lean = lambda picks: float(np.mean(f1(*spot(candidates, picks).T) - f2(*spot(candidates, picks).T)))  # noqa: E731
    to_first, _ = predicted.choose(job_of(candidates, columns=("f1", "f2"), count=3, predictions=guesses(candidates), weights=[20.0, 1.0]))
    to_second, _ = predicted.choose(job_of(candidates, columns=("f1", "f2"), count=3, predictions=guesses(candidates), weights=[1.0, 20.0]))
    assert lean(to_first) < lean(to_second) - 0.1


# ---------------------------------------------------------------- 打成包

def run_package(folder: Path, source: Path, out: Path) -> subprocess.CompletedProcess:
    listed = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    command = [sys.executable if part == "{python}" else part for part in listed["entry"]] + [str(source), str(out)]
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(command, cwd=folder, capture_output=True, env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))


@pytest.mark.parametrize("which", list(build.KINDS))
def test_each_package_passes_the_format_check_and_its_own_self_test(which, tmp_path):
    from stemlab.contract.formats import package as package_format
    from stemlab.contract.formats.manifest import check_format

    folder = build.build(which, tmp_path / which)
    assert check_format("strategy", folder) == []
    listed = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert listed["needs"] == build.KINDS[which]["needs"] and listed["title"] and listed["about"]
    for sample in listed["selftest"]:
        done = run_package(folder, folder / sample["input"], tmp_path / "out")
        assert done.returncode == 0, (done.stdout + done.stderr).decode("utf-8", "replace")
        got = json.loads((tmp_path / "out" / "result.json").read_text(encoding="utf-8"))
        want = json.loads((folder / sample["expected"]).read_text(encoding="utf-8"))
        assert package_format.differences(got, want, listed["tolerance"]) == []
    assert not list(folder.rglob("__pycache__")), "包里不带跑出来的缓存"


def test_a_package_that_cannot_choose_ends_with_an_error_and_says_why(tmp_path):
    folder = build.build("bayes", tmp_path / "bayes")
    source = tmp_path / "ask"
    source.mkdir()
    (source / "job.json").write_text(json.dumps(job_of(square(50, 5))), encoding="utf-8")
    done = run_package(folder, source, tmp_path / "out")
    assert done.returncode != 0 and not (tmp_path / "out" / "result.json").exists()
    assert "能用的数据只有 0 行" in done.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- 经真的优化插件走一遍

LENGTHS = list(range(20, 81, 4))                # 20、24……80。假内核的规矩：长过 60 的放不进去


def registered(which: str, tmp: Path) -> dict:
    from stemlab.registry import register

    folder = build.build(which, tmp / f"package-{which}")
    return register.register_external("strategy", which, source=folder, note=build.KINDS[which]["title"], by="tester")


def selected(made: str):
    from stemlab.contract.formats.manifest import check_format
    from stemlab.contract.formats.points import read_points
    from stemlab.desk.core import start
    from stemlab.experiments import view
    from tests import real

    assert start.start(made).ok
    real.run(made, seconds=180.0)
    status = view.view(made)
    assert real.tasks(made) == {"select": ("done", "selected")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    assert status.rounds[-1].problems == [] and check_format("points", real.output(made, "points")) == []
    return status, read_points(real.output(made, "points"))


def replays(made: str, points) -> bool:
    from plugins.opt import replay

    said = replay.replay(made)
    return bool(said["same"]) and said["points"] == [point["hash"] for point in points]


def test_a_first_batch_spread_evenly_through_the_real_plugin(real_lab, tmp_path):
    from tests import real

    strategy = registered("spacefill", tmp_path)
    made = real.opt_select(tmp_path, real.pool(tmp_path, real.pool_rows(LENGTHS))["id"], strategy=strategy, defaults=real.how(count=4))
    status, points = selected(made)
    lengths = sorted(point["design"]["length"] for point in points)
    assert len(points) == 4 and lengths[-1] <= 60, "只选了放得进去的"
    assert min(b - a for a, b in zip(lengths, lengths[1:])) >= 8, f"四个点在 20 到 60 之间铺开了：{lengths}"
    for point in points:
        reason = point["reason"]
        assert reason["strategy"] == strategy["id"] and reason["model"] is None and reason["model_from"] == "没有用模型"
        assert "最远" in reason["why"] or "照种子" in reason["why"]
    assert replays(made, points)


def test_bayes_through_the_real_plugin_goes_for_the_longest_stem_that_fits(real_lab, tmp_path):
    from tests import real

    strategy = registered("bayes", tmp_path)
    data = real.data(tmp_path, real.data_rows([(length, 2000.0) for length in (22.0, 27.0, 31.0, 36.0, 44.0, 49.0, 53.0, 57.0)]))
    made = real.opt_select(tmp_path, real.pool(tmp_path, real.pool_rows(LENGTHS))["id"], strategy=strategy, datas=[data])
    status, points = selected(made)
    assert len(points) == 3 and points[0]["design"]["length"] == 60.0, "假内核里转动随柄长变小：最好的是放得进去的最长的那个"
    reason = points[0]["reason"]
    assert reason["model"].startswith("策略内部的高斯过程") and "8 行" in reason["model"] and reason["model_from"] == "策略内部的模型"
    assert reason["data"] == [data["id"]] and "rotation 预测" in reason["why"] and reason["score"] > 0
    assert replays(made, points)


def test_bayes_without_usable_data_ends_as_a_strategy_error_with_the_reason(real_lab, tmp_path):
    from stemlab.desk.core import start
    from stemlab.experiments import view
    from tests import real

    data = real.data(tmp_path, real.data_rows([(length, 1500.0) for length in (22.0, 27.0, 31.0, 36.0, 44.0, 49.0, 53.0, 57.0)]))
    made = real.opt_select(tmp_path, real.pool(tmp_path, real.pool_rows(LENGTHS))["id"], strategy=registered("bayes", tmp_path), datas=[data])
    assert start.start(made).ok
    real.run(made, seconds=180.0)
    status = view.view(made)
    assert real.tasks(made) == {"select": ("failed", "strategy_error")}
    assert any("能用的数据只有 0 行" in problem["error"] for problem in status.rounds[-1].problems), status.rounds[-1].problems


def test_predicted_through_the_real_plugin_takes_what_the_registered_predictor_likes(real_lab, tmp_path):
    from tests import real

    strategy, predictor = registered("predicted-best", tmp_path), real.outside_predictor(tmp_path)
    made = real.opt_select(tmp_path, real.pool(tmp_path, real.pool_rows(LENGTHS))["id"], strategy=strategy, predictor=predictor)
    status, points = selected(made)
    assert [point["design"]["length"] for point in points] == [60.0, 56.0, 52.0]
    reason = points[0]["reason"]
    assert reason["predictor"] == predictor["id"] and reason["model"] == "登记的预测器，拿预测值比" and "rotation 预测" in reason["why"]
    assert replays(made, points)


def test_the_real_plugin_refuses_a_strategy_whose_needs_are_not_filled(real_lab, tmp_path):
    from stemlab.contract import Refused
    from stemlab.desk.core import start
    from tests import real

    candidates = real.pool(tmp_path, real.pool_rows(LENGTHS))["id"]
    with pytest.raises(Refused, match="这份策略要数据"):
        start.start(real.opt_select(tmp_path, candidates, strategy=registered("bayes", tmp_path)))
    with pytest.raises(Refused, match="没有填预测器"):
        start.start(real.opt_select(tmp_path, candidates, strategy=registered("predicted-optimistic", tmp_path)))


def test_a_pool_drawn_with_sobol_and_one_drawn_around_a_design_go_through_the_real_plugin(real_lab, tmp_path):
    from stemlab.contract import Refused
    from stemlab.contract.formats.points import read_points
    from stemlab.desk.core import start
    from stemlab.experiments import view
    from tests import real

    def pooled(space: dict) -> list:
        made = real.opt_pool(tmp_path, space=space)
        assert start.start(made).ok
        real.run(made, seconds=180.0)
        assert real.tasks(made) == {"pool": ("done", "generated")}, view.view(made).rounds[-1].problems
        return read_points(real.output(made, "pool"))

    rows = pooled(dict(real.SPACE, method="sobol"))
    assert len(rows) == 12 and all(20 <= row["design"]["length"] <= 80 for row in rows) and {row["feasible"] for row in rows} == {True, False}
    near = pooled(dict(real.SPACE, method="around", centers=[{"length": 50.0, "behave": "ok"}], spread=0.1))
    assert near[0]["design"]["length"] == 50.0 and all(44 <= row["design"]["length"] <= 56 and row["feasible"] for row in near)
    with pytest.raises(Refused, match="method 只有"):
        start.start(real.opt_pool(tmp_path, space=dict(real.SPACE, method="grid")))
