"""代理插件的验收：换模型不换评价——划分、误差算法、预测器格式不随模型变。

情形都写在 surrogate_cases.py 里。“在 Linux 上打包、在 Windows 上加载”那一条要连上 Linux，在 tests/cross/ 里。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from stemlab.desk.core import code_state
from tests import helpers
from tests.plugins import surrogate_cases


@pytest.mark.parametrize("case", surrogate_cases.BLUEPRINT + surrogate_cases.OTHERS + surrogate_cases.FIELDS, ids=lambda case: case.__name__)
def test_surrogate(real_lab, data, tmp_path, case):
    case(tmp_path)


# ---- 5 把 models/ 整个换成另一种模型：冻结的四个文件不用改，测试照过；换之前打的包照样出同样的预测 ----

RUN = """\
import json, os, pathlib, sys
from tests.plugins import surrogate_cases as cases
from plugins.surrogate import models
base, what = pathlib.Path(sys.argv[1]), sys.argv[2]


def use(root):
    os.environ.update(STEMLAB_DATA=str(root / "data"), STEMLAB_CACHE=str(root / "cache"), STEMLAB_SLOTS=str(root / "slots"))
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    return root / "tmp"


said = {"default": models.DEFAULT, "rewritten": getattr(models, "REWRITTEN", False), "file": models.__file__, "done": []}
if what == "before":
    kept = cases.before_the_models_are_swapped(use(base / "kept"))
    (base / "before.json").write_text(json.dumps(kept))
else:
    cases.after_the_models_are_swapped(use(base / "kept"), json.loads((base / "before.json").read_text()))
    for case in cases.BLUEPRINT:
        case(use(base / case.__name__))
        said["done"].append(case.__name__)
print(json.dumps(said))
"""


def _run(repo, base, what: str) -> dict:
    env = {key: value for key, value in os.environ.items() if key not in ("STEMLAB_REPO", "STEMLAB_PLUGINS")}
    env.update(PYTHONPATH=str(helpers.REPO), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", RUN, str(base), what], cwd=repo, env=env, capture_output=True, timeout=1200)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-3000:]
    said = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    assert str(repo) in said["file"], "跑的确实是仓库拷贝里的那一份"
    return said


def test_swapping_the_models_changes_nothing_else(real_own_lab, data, tmp_path):
    base = tmp_path / "cases"
    base.mkdir()
    said = _run(real_own_lab, base, "before")
    assert (said["default"], said["rewritten"]) == ("ridge", False), "先用原来的模型训练、打包、出一次预测"
    models = real_own_lab / "plugins" / "surrogate" / "models"
    shutil.rmtree(models)
    shutil.copytree(helpers.REPO / "tests" / "plugins" / "surrogate_rewritten" / "models", models,
                    ignore=shutil.ignore_patterns("__pycache__"))
    said = _run(real_own_lab, base, "after")
    assert (said["default"], said["rewritten"]) == ("knn", True), "换上去的是另一种模型"
    assert said["done"] == [case.__name__ for case in surrogate_cases.BLUEPRINT], "同样的情形在另一种模型上照过；旧的包照样出同样的预测"
    assert code_state.frozen_ok() == [], "冻结的四个文件一个没动"


# ---- 冻结文件里的规则，直接试 ----

def _row(point: str, bone: str = "femur042", **values) -> dict:
    return {"point": point, "bone_id": bone, "values": values}


def test_how_rows_are_split():
    from plugins.surrogate import split

    rows = [_row(f"{number:064x}", length=20.0 + number) for number in range(200)]
    cut = {"by": "row", "fraction": 0.2, "seed": 7}
    parts = split.split(rows, cut)
    assert 20 <= len(parts["holdout"]) <= 60 and len(parts["train"]) + len(parts["holdout"]) == 200 and parts["outside"] == []
    again = split.split(list(reversed(rows)) + [_row("f" * 64, length=1.0)], cut)
    assert {row["point"] for row in parts["holdout"]} <= {row["point"] for row in again["holdout"]}, "数据多了、顺序变了，老的行归属不变"
    assert {row["point"] for row in split.split(rows, dict(cut, seed=8))["holdout"]} != {row["point"] for row in parts["holdout"]}

    boxed = split.split(rows, dict(cut, outside=[{"column": "length", "min": 30.0, "max": 200.0}]))
    assert sorted(row["values"]["length"] for row in boxed["outside"]) == [20.0 + n for n in range(10)] + [201.0 + n for n in range(19)]
    assert all(30 <= row["values"]["length"] <= 200 for part in ("train", "holdout") for row in boxed[part])

    two = [_row(f"{number:064x}", "femur042" if number % 3 else "femur043", length=1.0) for number in range(30)]
    by_bone = split.split(two, {"by": "bone", "bones": ["femur043"]})
    assert {row["bone_id"] for row in by_bone["train"]} == {"femur042"} and len(by_bone["holdout"]) == 10
    assert split.leaks({"train": two, "holdout": two[:1], "outside": []}, {"by": "bone", "bones": ["femur043"]}), "混进去了就查得出"

    columns = [{"name": "length", "role": "design"}, {"name": "rotation", "role": "label"}]
    assert split.problems(cut, columns) == [] and split.problems({"by": "bone", "bones": ["a"]}) == []
    for bad in ({}, {"by": "column"}, {"by": "row", "fraction": 0, "seed": 1}, {"by": "row", "fraction": 0.2}, {"by": "bone", "bones": []},
                dict(cut, outside={"column": "length"}), dict(cut, outside=[{"column": "length"}]),
                dict(cut, outside=[{"column": "rotation", "max": 1}])):
        assert split.problems(bad, columns), bad
    shown = split.unlabeled([dict(rows[0], values={"length": 20.0, "rotation": 0.1})], columns)
    assert shown == [{"point": rows[0]["point"], "bone_id": "femur042", "values": {"length": 20.0}}], "留出的行出去的时候不带 FE 的数"


def test_how_errors_are_computed():
    from plugins.surrogate import report

    truth = [_row("a", y=1.0), _row("b", y=10.0), _row("c", y=100.0), _row("d", y=None), _row("e", y=5.0)]
    guesses = [dict(_row("a", y=2.0), lower={"y": 0.5}, upper={"y": 3.0}), dict(_row("b", y=10.0), lower={"y": 9.0}, upper={"y": 11.0}),
               dict(_row("c", y=50.0), lower={"y": 40.0}, upper={"y": 60.0}), dict(_row("z", y=1.0), lower={"y": 0.0}, upper={"y": 2.0})]
    found = report.errors(truth, guesses, "y")
    assert (found["n"], found["unmatched"], found["skipped"], found["scale"]) == (3, 1, 0, "linear")
    assert found["bias"] == (1 + 0 - 50) / 3 and found["mae"] == 51 / 3 and found["max_abs"] == 50
    assert abs(found["rmse"] - (2501 / 3) ** 0.5) < 1e-12 and found["coverage"] == 2 / 3
    assert abs(found["r2"] - (1 - 2501 / 5994)) < 1e-12
    logged = report.errors(truth, guesses, "y", "log10")
    assert abs(logged["rmse"] - (2 * 0.30102999566398120 ** 2 / 3) ** 0.5) < 1e-12 and logged["coverage"] == 2 / 3
    negative = report.errors([_row("a", y=1.0)], [dict(_row("a", y=-1.0), lower={"y": -2.0}, upper={"y": 0.0})], "y", "log10")
    assert (negative["n"], negative["skipped"], negative["rmse"]) == (0, 1, None), "取不了对数的点单独数出来"
    assert report.errors([], guesses, "y")["r2"] is None

    line = {"id": "a1", "what": "x", "target": "y", "on": "holdout", "metric": "rmse", "op": "<=", "limit": 30.0}
    assert report.line_problems([line], ["y"]) == [] and report.line_problems(None, ["y"]) == []
    for bad in ([dict(line, target="w")], [dict(line, on="train")], [dict(line, metric="p99")], [dict(line, op="=")],
                [dict(line, limit="1")], [line, line], [{"id": "a1"}], {"lines": []}):
        assert report.line_problems(bad, ["y"]), bad
    complete = report.errors(truth[:4], guesses, "y")       # e 没有预测；不算它，这一部分就全了
    assert (complete["n"], complete["unmatched"], complete["repeated"]) == (3, 0, 0) and complete["rmse"] == found["rmse"]
    numbers = {"holdout": {"y": complete}, "outside": {"y": report.errors([], [], "y")}}
    verdicts = report.judge([line, dict(line, id="a2", limit=20.0), dict(line, id="a3", on="outside")], numbers)
    assert [(row["id"], row["passed"]) for row in verdicts] == [("a1", True), ("a2", False), ("a3", None)]

    short = report.judge([line], {"holdout": {"y": found}, "outside": {}})[0]
    assert (short["passed"], short["value"]) == (None, None) and "1 个点没有预测" in short["why"], "缺了预测不判，不当它过了"
    again = report.errors(truth[:4], guesses + [dict(_row("a", y=1.0), lower={"y": 0.5}, upper={"y": 1.5})], "y")
    assert (again["n"], again["repeated"], again["unmatched"]) == (2, 1, 0), "同一个点给了两次：不知道用哪一次，不比，也不悄悄用后一次"
    assert "1 个点预测给了不止一次" in report.judge([line], {"holdout": {"y": again}, "outside": {}})[0]["why"]
    assert report.pairs(truth[:4], guesses + [dict(_row("a", y=1.0), lower={"y": 0.5}, upper={"y": 1.5})], "y") == [
        [10.0, 10.0, 9.0, 11.0], [100.0, 50.0, 40.0, 60.0]], "散点里也不画给了两次的点"
    cut = report.judge([dict(line, metric="n", op=">=", limit=0)], {"holdout": {"y": negative}, "outside": {}})[0]
    assert cut["passed"] is None and "1 个点算不了" in cut["why"], "取不了对数的点也是比不全"


def test_a_training_that_leaves_out_or_repeats_points_is_not_judged(real_lab, data, tmp_path, monkeypatch):
    """训练代码交回来的预测缺了一个留出的点、另一个点给了两次：误差报告照出，留出那一部分的合格线不可判，也记成问题。
    不拿剩下的点悄悄判过，也不悄悄用后一次的预测。"""
    from pathlib import Path

    from plugins.surrogate import report, train
    from stemlab.contract.formats.points import read_points
    from stemlab.experiments import view
    from tests import real

    advance = train.advance

    def tampered(handle):
        found = advance(handle)
        result = found.get("result")
        if result is not None and result.get("status") == "ok":
            kept = json.loads((handle.work_dir / "desk" / f"r{handle.round.number}" / "truth.json").read_bytes())
            known = [row["point"] for row in kept["holdout"] if isinstance(row["values"].get("rotation"), float)]
            asked = Path(str(result["asked"]))
            rows = {row["point"]: row for row in read_points(asked)}
            again = dict(rows[known[1]], values={name: value * 2 if isinstance(value, float) else value
                                                 for name, value in rows[known[1]]["values"].items()})
            asked.write_bytes(b"".join(report.dumps(row) for point, row in rows.items() if point != known[0]) + report.dumps(again))
        return found

    monkeypatch.setattr(train, "advance", tampered)
    made = surrogate_cases.trained([real.data(tmp_path, real.data_rows(real.spread(60, seed=8)))])
    body = surrogate_cases.body_of(made)
    assert (body["holdout"]["rotation"]["unmatched"], body["holdout"]["rotation"]["repeated"]) == (1, 1)
    verdicts = {row["id"]: row for row in body["verdicts"]}
    for name in ("a1", "a2"):
        assert verdicts[name]["passed"] is None, verdicts[name]
        assert "1 个点没有预测" in verdicts[name]["why"] and "1 个点预测给了不止一次" in verdicts[name]["why"]
    told = [problem["error"] for problem in view.view(made).rounds[-1].problems]
    assert any("1 个点没有预测" in text and "1 个点给了不止一次预测" in text for text in told), told


def test_what_is_in_range():
    from plugins.surrogate import predictor

    columns = [{"name": "length", "role": "design"}, {"name": "kind", "role": "design"}, {"name": "load", "role": "condition"},
               {"name": "rotation", "role": "label"}]
    rows = [_row("a", length=20.0, kind="x", load=1.0, rotation=9.0), _row("b", length=40.0, kind="y", load=2.0, rotation=None)]
    scope = predictor.scope_of(rows, columns)
    assert scope == {"bones": ["femur042"], "design": {"length": {"min": 20.0, "max": 40.0}, "kind": {"values": ["x", "y"]}},
                     "conditions": {"load": {"min": 1.0, "max": 2.0}}}
    point = predictor.as_point(rows[0], columns)
    assert point == {"hash": "a", "bone_id": "femur042", "design": {"length": 20.0, "kind": "x"}, "conditions": {"load": 1.0}}
    assert predictor.in_range(scope, point) is None
    for change, word in (({"bone_id": "femur043"}, "femur043"), ({"design": {"length": 41.0, "kind": "x"}}, "length"),
                         ({"design": {"length": 30.0, "kind": "z"}}, "kind"), ({"design": {"length": 30.0}}, "对不上"),
                         ({"conditions": {"load": 1.5, "speed": 1}}, "对不上"), ({"design": {"length": "long", "kind": "x"}}, "length")):
        assert word in predictor.in_range(scope, {**point, **change}), change
    assert "def in_range" in predictor.SCOPE and "in_range(meta[\"scope\"], point)" in predictor.MAIN, "包里带着同一个函数"
    with pytest.raises(ValueError, match="length"):
        predictor.targets_of(columns, ["length"])
    assert predictor.targets_of(columns, ["rotation"]) == [columns[3]]


def test_packing_refuses_what_does_not_belong_in_a_package(tmp_path):
    import numpy as np

    from plugins.surrogate import predictor
    from plugins.surrogate.models import ridge_infer

    columns = [{"name": "rotation", "unit": "deg", "meaning": "x", "role": "label"}]
    scope = {"bones": ["femur042"], "design": {"length": {"min": 20.0, "max": 40.0}}, "conditions": {}}
    sample = {"hash": "a" * 64, "bone_id": "femur042", "design": {"length": 30.0}, "conditions": {}}
    features = {"numeric": [{"group": "design", "name": "length", "mean": 30.0, "std": 5.0}], "categorical": [], "bones": ["femur042"]}
    good = {"infer": ridge_infer.__file__, "weights": {"coef": np.ones((2, 3, 1)), "sigma": np.array([0.1])},
            "meta": {"features": features, "degree": 2, "z": 2.0, "scale": {}}, "columns": columns, "level": 0.95, "scope": scope,
            "samples": [sample]}
    folder = predictor.pack(tmp_path / "good", **good)
    assert predictor.problems(folder, columns=columns, level=0.95, scope=scope, packed_here=True) == []
    expected = json.loads((folder / "data" / "selftest" / "sample" / "expected.json").read_bytes())
    assert expected["rows"][0]["values"]["rotation"] == 1.0 + 0.0 + 0.0 and expected["skipped"] == []
    assert not list(folder.rglob("__pycache__")), "打包时跑自检样本，不往包里留缓存"
    assert predictor.problems(folder, scope=dict(scope, bones=["femur043"])), "清单里的范围不是该有的那一份"

    with pytest.raises(ValueError, match="不是数的数组"):
        predictor.pack(tmp_path / "bad1", **{**good, "weights": {"coef": np.array(["a", "b"])}})
    with pytest.raises(ValueError, match="JSON"):
        predictor.pack(tmp_path / "bad2", **{**good, "meta": dict(good["meta"], where=tmp_path)})
    with pytest.raises(ValueError, match="适用范围"):
        predictor.pack(tmp_path / "bad3", **{**good, "samples": [dict(sample, design={"length": 99.0})]})
    leaning = tmp_path / "leaning_infer.py"
    leaning.write_text("from plugins.surrogate import models\n", encoding="utf-8")
    with pytest.raises(ValueError, match="import"):
        predictor.pack(tmp_path / "bad4", **{**good, "infer": leaning})
    (folder / "code" / "main.py").write_text("print('something else')\n", encoding="utf-8")
    assert any("入口" in text for text in predictor.problems(folder, packed_here=True))


def test_how_field_errors_are_computed():
    import numpy as np

    from plugins.surrogate import report

    truth = np.array([1.0, 2.0, 3.0, 4.0])
    exact = np.stack([truth, truth - 0.5, truth + 0.5])
    off = np.stack([truth + np.array([1.0, 0.0, -1.0, 0.0]), truth - 0.5, truth + 0.5])
    found = report.field_errors([(truth, exact), (truth, off), (None, exact), (truth, None), (truth, exact[:, :3]), (truth * np.nan, exact)])
    assert (found["n"], found["cells"], found["unmatched"], found["skipped"], found["scale"]) == (2, 8, 1, 2, "linear"), \
        "没有真值的点不算；没有预测的数进 unmatched；形状对不上、不是有限数的数进 skipped"
    assert found["bias"] == 0.0 and found["mae"] == 2 / 8 and found["max_abs"] == 1.0 and abs(found["rmse"] - 0.5) < 1e-12
    assert found["coverage"] == 1.0 and abs(found["r2"] - (1 - 2 / 10)) < 1e-12, "逐个格子比，所有点的格子合在一起算"
    missed = np.stack([truth, truth + 0.1, truth + 0.2])
    assert report.field_errors([(truth, missed)])["coverage"] == 0.0, "真值不在区间里的格子不算盖住"
    assert report.field_errors([])["rmse"] is None and report.field_errors([(None, exact)])["n"] == 0
    grid = np.arange(6.0).reshape(2, 3)
    assert report.field_errors([(grid, np.stack([grid + 1, grid, grid + 2]))])["bias"] == 1.0, "几维的场都行"

    complete = report.field_errors([(truth, exact), (truth, off), (None, exact)])
    assert (complete["n"], complete["unmatched"], complete["skipped"]) == (2, 0, 0) and complete["rmse"] == found["rmse"]
    numbers = {"holdout": {"slip": complete}, "outside": {"slip": report.field_errors([])}}
    line = {"id": "f1", "what": "x", "target": "slip", "on": "holdout", "metric": "rmse", "op": "<=", "limit": 0.6}
    assert report.line_problems([line], ["rotation", "slip"]) == []
    assert [row["passed"] for row in report.judge([line, dict(line, id="f2", limit=0.4), dict(line, id="f3", on="outside")], numbers)] == [True, False, None]
    short = report.judge([line], {"holdout": {"slip": found}, "outside": {}})[0]
    assert short["passed"] is None and "1 个点没有预测" in short["why"] and "2 个点算不了" in short["why"], "场比不全也不判"

    rows = [{"point": "a", "bone_id": "femur042", "round": 1, "outcome": "finished", "values": {"y": 1.0}},
            {"point": "b", "bone_id": "femur042", "round": 1, "outcome": "finished", "values": {"y": 2.0}}]
    guesses = [dict(_row(name, y=1.5), lower={"y": 0.0}, upper={"y": 3.0}) for name in ("a", "b", "c")]
    columns = [{"name": "y", "role": "label"}, {"name": "slip", "role": "field"}]
    body = report.check_report(guesses, rows, columns, {"slip": {"a": (truth, off), "b": (truth, None), "c": (None, exact)}})
    assert body["columns"] == ["y"] and body["fields"] == ["slip"] and body["only_predicted"] == ["c"]
    assert body["matched"][0]["fields"]["slip"] == {"rmse": 0.5 ** 0.5, "max_abs": 1.0, "inside": 1.0} and body["matched"][1]["fields"]["slip"] is None
    assert (body["summary"]["slip"]["n"], body["summary"]["slip"]["unmatched"]) == (1, 1) and body["summary"]["y"]["n"] == 2
    assert "fields" not in report.check_report(guesses, rows, columns[:1]), "没有场的预测，复核报告和原来一样"


FIELD_INFER = """\
import numpy as np


def predict(weights, meta, points):
    rows = []
    for point in points:
        value = weights["base"] * point["design"]["length"]
        rows.append({"values": {}, "lower": {}, "upper": {}, "fields": {"slip": np.stack([value, value - 1.0, value + meta["above"]])}})
    return rows
"""


def test_a_package_can_predict_a_field(tmp_path):
    import numpy as np

    from plugins.surrogate import predictor

    field = {"name": "slip", "unit": "um", "meaning": "x", "role": "field"}
    scope = {"bones": ["femur042"], "design": {"length": {"min": 20.0, "max": 40.0}}, "conditions": {}}
    sample = {"hash": "a" * 64, "bone_id": "femur042", "design": {"length": 30.0}, "conditions": {}}
    infer = tmp_path / "field_infer.py"
    infer.write_text(FIELD_INFER, encoding="utf-8")
    good = {"infer": infer, "weights": {"base": np.array([[1.0, 2.0], [3.0, 4.0]])}, "meta": {"above": 1.0}, "columns": [], "level": 0.9,
            "scope": scope, "samples": [sample], "fields": [field], "shapes": {"slip": [2, 2]}}
    folder = predictor.pack(tmp_path / "good", **good)
    assert predictor.problems(folder, columns=[field], level=0.9, scope=scope, packed_here=True, shapes={"slip": [2, 2]}) == []
    listed = json.loads((folder / "manifest.json").read_bytes())
    assert listed["columns"] == [field] and listed["shapes"] == {"slip": [2, 2]}
    expected = json.loads((folder / "data" / "selftest" / "sample" / "expected.json").read_bytes())
    row = expected["rows"][0]
    assert row["fields"] == {"slip": f"fields/{'a' * 64}/slip.npy"} and row["values"] == {}
    assert row["field_summary"] == {"slip": {"mean": 75.0, "min": 30.0, "max": 120.0}}, "自检比的是场的这三个数：包里不留场的文件"
    assert predictor.problems(folder, shapes={"slip": [4]}), "清单里的形状不是该有的那一份"

    out = tmp_path / "out"
    out.mkdir()
    done = subprocess.run([sys.executable, "code/main.py", str(folder / "data" / "selftest" / "sample" / "input"), str(out)], cwd=folder,
                          capture_output=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    stacked = predictor.read_predicted(out / row["fields"]["slip"], [2, 2])
    assert stacked.shape == (3, 2, 2) and (stacked[0] == 30.0 * good["weights"]["base"]).all()
    with pytest.raises(ValueError, match="摞在一起"):
        predictor.read_predicted(out / row["fields"]["slip"], [4])
    (tmp_path / "plain.json").write_text("[[1, 2], [3, 4]]", encoding="utf-8")
    assert predictor.read_field(tmp_path / "plain.json").shape == (2, 2), "数据里的场可以是 .json，也可以是 .npy"
    (tmp_path / "bad.json").write_text('["a"]', encoding="utf-8")
    with pytest.raises(ValueError, match="数的数组"):
        predictor.read_field(tmp_path / "bad.json")

    with pytest.raises(ValueError, match="shapes"):
        predictor.pack(tmp_path / "bad1", **{**good, "shapes": None})
    with pytest.raises(ValueError, match="跑不起来"):
        predictor.pack(tmp_path / "bad2", **{**good, "shapes": {"slip": [3]}})          # 模型给的形状和说好的不一样：入口不收
    with pytest.raises(ValueError, match="跑不起来"):
        predictor.pack(tmp_path / "bad3", **{**good, "meta": {"above": -5.0}})          # 上界比值小：入口不收
    columns = [{"name": "length", "role": "design"}, {"name": "slip", "role": "field"}, {"name": "rotation", "role": "label"}]
    assert predictor.fields_of(columns, ["slip"]) == [columns[1]]
    with pytest.raises(ValueError, match="rotation"):
        predictor.fields_of(columns, ["rotation"])
