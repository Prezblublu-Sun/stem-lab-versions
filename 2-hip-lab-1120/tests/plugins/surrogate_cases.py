"""代理插件的验收情形。每个情形是一个函数：造输入、跑、断言。数据是现造的（tests/real.py），数照假内核的算法来。

test_surrogate.py 在这个进程里逐个跑。BLUEPRINT 里的几个对应蓝图“怎样算做对”里不靠 Linux 的那几条；
“把 models/ 整个换成另一种模型”那一条，是在换过模型的仓库拷贝里把它们原样再跑一遍。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import psutil

from stemlab.contract import Refused
from stemlab.contract.formats.manifest import as_v2, check_format, read_manifest
from stemlab.contract.formats.points import read_points
from stemlab.contract.layout import work_dir
from stemlab.desk.core import query, start
from stemlab.experiments import view
from stemlab.registry import lookup
from tests import helpers, real

SECONDS = 180.0
GIVEN = {"length", "behave", "load"}                    # 设计和条件的列：不做 FE 就知道的


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


def trained(datas, value: dict | None = None, split: dict | None = None) -> str:
    """跑完一次训练，返回实验的编号。"""
    made = real.train(datas, value, split)
    status = finished(made)
    assert status.rounds[-1].result == "done", (status.rounds[-1].reason, status.rounds[-1].problems)
    assert real.tasks(made) == {"train": ("done", "trained")} and sorted(status.rounds[-1].outputs) == ["predictor", "report"]
    return made


def body_of(made: str, name: str = "report") -> dict:
    folder = real.output(made, name)
    assert check_format("report", folder) == []
    return json.loads((folder / "report.json").read_bytes())


def item_of(made: str, name: str) -> str:
    return view.view(made).rounds[-1].outputs[name]["item"]


def handed(made: str, number: int = 1) -> Path:
    """冻结代码交给训练代码的那个作业文件夹。"""
    return work_dir(made) / "desk" / f"r{number}" / "job"


def predictions(made: str) -> dict:
    """一份预测的各行：点的名字 -> 行。"""
    status = view.view(made)
    names = {point["hash"]: point["name"] for point in read_points(lookup.content(status.frozen["points"][0]["id"]))}
    return {names[row["point"]]: row for row in read_points(real.output(made, "prediction") / "rows.jsonl")}


# ---- 1 留出的行一行都没进训练；按骨划分时，留出的骨一根都没进 ----

def held_out_rows_never_reach_training(tmp: Path) -> None:
    rows = real.data_rows(real.spread(80, seed=1))
    made = trained([real.data(tmp, rows)], split=real.split_setting(outside=[{"column": "length", "max": 50.0}]))
    report = body_of(made)
    counts = report["split"]["rows"]
    assert sum(counts.values()) == 80 and all(counts[part] > 5 for part in ("train", "holdout", "outside")), counts

    job = handed(made)
    given = read_points(job / "train.jsonl")
    kept = json.loads((job.parent / "truth.json").read_bytes())
    held = {row["point"] for part in ("holdout", "outside") for row in kept[part]}
    assert {row["point"] for row in given}.isdisjoint(held), "留出的行一行都没进训练"
    assert {row["point"] for row in given} | held == {row["point"] for row in rows}, "每一行都有去处"
    asked = read_points(job / "ask.jsonl")
    assert {row["point"] for row in asked} == held
    assert all(set(row["values"]) == GIVEN and set(row) == {"point", "bone_id", "values"} for row in asked), \
        "留出的点交给训练代码去出预测时，只带设计和条件"
    assert all(row["values"]["length"] > 50 for row in kept["outside"]) and all(row["values"]["length"] <= 50 for row in given)
    assert sorted(path.name for path in job.iterdir()) == ["ask.jsonl", "job.json", "train.jsonl"], "真值不在交出去的文件夹里"
    assert report["training"]["rows_used"] == counts["train"]
    assert report["holdout"]["rotation"]["n"] == counts["holdout"] and report["outside"]["rotation"]["n"] == counts["outside"]
    assert report["split"]["by"] == "row" and report["split"]["setting"]["fraction"] == 0.25, "报告写明用的是哪种划分"

    mixed = real.data_rows(real.spread(40, seed=2)) + real.data_rows(real.spread(20, seed=3), bone_id="femur043")
    by_bone = trained([real.data(tmp, mixed, bone_id=None)], split=real.setting({"by": "bone", "bones": ["femur043"]}))
    assert {row["bone_id"] for row in read_points(handed(by_bone) / "train.jsonl")} == {real.BONE}, "留出的骨一根都没进训练"
    report = body_of(by_bone)
    assert report["split"]["bones"] == {"train": [real.BONE], "holdout": ["femur043"], "outside": []}
    assert report["holdout"]["rotation"]["n"] == 20
    assert read_manifest(real.output(by_bone, "predictor"))["range"]["bones"] == [real.BONE], "适用范围只有训练过的骨"


# ---- 2 特征里没有 FE 算出来的列；包合规矩 ----

def features_use_only_what_is_known_before_fe(tmp: Path) -> None:
    import numpy as np

    designs = real.spread(60, seed=4)
    made = trained([real.data(tmp, real.data_rows(designs))])
    folder = real.output(made, "predictor")
    assert check_format("predictor", folder) == []
    listed = read_manifest(folder)
    assert [(column["name"], column["role"], column["unit"]) for column in listed["columns"]] == [
        ("rotation", "label", "deg"), ("slip_p95", "derived", "um")]
    assert listed["level"] == 0.95
    scope = listed["range"]
    assert scope["bones"] == [real.BONE] and scope["design"]["behave"] == {"values": ["ok"]}
    assert set(scope["design"]) == {"length", "behave"} and set(scope["conditions"]) == {"load"}
    assert 25 <= scope["design"]["length"]["min"] < scope["design"]["length"]["max"] <= 55, "范围是训练那一部分数据的范围"

    meta = json.loads((folder / "data" / "meta.json").read_bytes())
    used = {item["name"] for group in ("numeric", "categorical") for item in meta["features"][group]}
    assert used and used <= GIVEN, f"特征只用设计和条件：{used}"
    with np.load(folder / "data" / "weights.npz", allow_pickle=False) as stored:
        assert all(stored[name].dtype.kind in "fiu" for name in stored.files), "权重只有数"
    code = (folder / "code" / "infer.py").read_text(encoding="utf-8")
    assert "plugins" not in code and "stemlab" not in code, "推理代码离开插件也能跑"
    item = lookup.get(item_of(made, "predictor"))
    assert (item["kind"], item["origin"]["experiment"], item["origin"]["output"]) == ("predictor", made, "predictor")
    for chart in query.charts(made):
        assert query.chart(made, chart["name"]) is not None, chart


# ---- 3 同样的输入和种子再训练一次：误差报告在容差内相同 ----

def the_same_inputs_and_seed_give_the_same_report(tmp: Path) -> None:
    item, value, cut = real.data(tmp, real.data_rows(real.spread(60, seed=5))), real.train_setting(), real.split_setting()
    first, second = body_of(trained([item], value, cut)), body_of(trained([item], value, cut))
    for part in ("holdout", "outside"):
        for target, numbers in first[part].items():
            for metric, number in numbers.items():
                other = second[part][target][metric]
                same = number == other if not isinstance(number, float) else math.isclose(number, other, rel_tol=1e-9, abs_tol=1e-12)
                assert same, f"{part} {target} {metric}：{number} 对 {other}"
    assert first["verdicts"] == second["verdicts"] and first["split"] == second["split"]
    assert first["training"]["seed"] == 11, "种子是训练设定里的那个"


# ---- 6 登记一个外面训练好的预测器，不训练直接出预测；超出适用范围的点不出数 ----

def a_predictor_from_outside_predicts_without_training(tmp: Path) -> None:
    outside = real.outside_predictor(tmp)
    batch = real.points(tmp, [real.point("p1", 30.0), real.point("p2", 45.0, load=1800.0), real.point("far", 75.0)])
    made = real.predict(outside["id"], batch)
    status = finished(made)
    assert real.tasks(made) == {"predict": ("done", "predicted")} and status.rounds[-1].result == "done"
    folder = real.output(made, "prediction")
    assert check_format("prediction", folder) == []
    assert (read_manifest(folder)["level"], read_manifest(folder)["count"]) == (0.9, 2)
    rows = predictions(made)
    assert sorted(rows) == ["p1", "p2"], "超出适用范围的点不出数，别的点照常"
    assert math.isclose(rows["p1"]["values"]["rotation"], 2000 / 30000) and math.isclose(rows["p2"]["upper"]["rotation"], 1.1 * 1800 / 45000)
    assert rows["p1"]["bone_id"] == real.BONE
    told = [problem["error"] for problem in status.rounds[-1].problems]
    assert len(told) == 1 and "far" in told[0] and "适用范围" in told[0] and "length" in told[0], told
    used = [extra["info"]["kind"] for extra in status.rounds[-1].extra if extra["source"] == "package"]
    assert used == ["predictor"], "用了哪个预测器，核心记进了这一轮的来历"
    assert "适用范围" in refused(real.predict(outside["id"], real.points(tmp, [real.point("far", 75.0)]))), "一个在范围里的点都没有"


# ---- 7 复核：预测和数据对得上的点逐个有差值；对不上的点列出来 ----

def checking_predictions_against_fea(tmp: Path) -> None:
    from stemlab.contract.formats.points import point_hash

    designs = [(30.0, 2000.0), (40.0, 2000.0), (50.0, 2000.0), (35.0, 1800.0), (45.0, 2200.0)]
    batch = real.points(tmp, [real.point(f"p{number}", length, load=load) for number, (length, load) in enumerate(designs)])
    asked = real.predict(real.outside_predictor(tmp)["id"], batch)
    finished(asked)
    measured = real.data(tmp, real.data_rows(designs[:3] + [(33.0, 2000.0), (58.0, 2100.0)], misfit=[designs[2]]))
    made = real.check(item_of(asked, "prediction"), measured)
    status = finished(made)
    assert real.tasks(made) == {"check": ("done", "checked")} and status.rounds[-1].problems == []
    report = body_of(made)
    assert (len(report["matched"]), len(report["only_predicted"]), len(report["only_data"])) == (3, 2, 2)
    hashes = [point_hash({"bone_id": real.BONE, "design": {"length": length, "behave": "ok"}, "conditions": {"load": load}})
              for length, load in designs]
    by = {row["point"]: row for row in report["matched"]}
    assert sorted(by) == sorted(hashes[:3]) and sorted(report["only_predicted"]) == sorted(hashes[3:])
    assert abs(by[hashes[0]]["diff"]["rotation"]) < 1e-12 and by[hashes[0]]["inside"]["rotation"] is True, "对得上的点逐个有差值"
    assert (by[hashes[2]]["outcome"], by[hashes[2]]["diff"]["rotation"]) == ("misfit", None), "FEA 说放不进去的点：对上了，没有数可比"
    assert report["summary"]["rotation"]["n"] == 2 and report["prediction"] == item_of(asked, "prediction")

    elsewhere = real.check(item_of(asked, "prediction"), real.data(tmp, real.data_rows([(31.0, 2000.0)])))
    status = finished(elsewhere)
    assert real.tasks(elsewhere) == {"check": ("done", "nothing_matched")}
    assert next(row for row in status.outcomes if row["name"] == "nothing_matched")["category"] == "conclusion"
    assert body_of(elsewhere)["matched"] == [] and len(body_of(elsewhere)["only_predicted"]) == 5


# ---- 训练出来的预测器拿去用：范围里的点出数，范围外的记成问题 ----

def a_trained_predictor_is_used_on_new_points(tmp: Path) -> None:
    made = trained([real.data(tmp, real.data_rows(real.spread(80, seed=6)))])
    batch = real.points(tmp, [real.point("in1", 31.0, load=1900.0), real.point("in2", 47.5, load=2300.0), real.point("long", 70.0),
                              real.point("odd", 40.0, behave="mesh"), real.point("other", 40.0, bone_id="femur043")])
    asked = real.predict(item_of(made, "predictor"), batch)
    status = finished(asked)
    assert real.tasks(asked) == {"predict": ("done", "predicted")}
    rows = predictions(asked)
    assert sorted(rows) == ["in1", "in2"]
    for name, (length, load) in (("in1", (31.0, 1900.0)), ("in2", (47.5, 2300.0))):
        truth = real.fe_truth(length, load)
        for target in ("rotation", "slip_p95"):
            assert abs(rows[name]["values"][target] / truth[target] - 1) < 0.15, f"{name} {target}：{rows[name]['values'][target]} 对 {truth[target]}"
            assert rows[name]["lower"][target] <= rows[name]["values"][target] <= rows[name]["upper"][target]
    told = sorted(problem["error"] for problem in status.rounds[-1].problems)
    assert len(told) == 3 and all("适用范围" in text for text in told)
    assert any("long" in text and "length" in text for text in told) and any("odd" in text and "behave" in text for text in told)
    assert any("other" in text and "femur043" in text for text in told)

    measured = real.data(tmp, real.data_rows([(31.0, 1900.0), (47.5, 2300.0)]))
    report = body_of(finished_check(real.check(item_of(asked, "prediction"), measured)))
    assert len(report["matched"]) == 2 and report["summary"]["rotation"]["n"] == 2 and report["summary"]["rotation"]["rmse"] < 0.01


def finished_check(made: str) -> str:
    finished(made)
    return made


BLUEPRINT = [held_out_rows_never_reach_training, features_use_only_what_is_known_before_fe,
             the_same_inputs_and_seed_give_the_same_report, a_predictor_from_outside_predicts_without_training,
             checking_predictions_against_fea, a_trained_predictor_is_used_on_new_points]


# ---- 5 的后一半：换模型之前打的包，换了之后照样出同样的预测（在仓库拷贝里分两步跑）----

BATCH = [("q1", 28.0, 1700.0), ("q2", 36.5, 2100.0), ("q3", 44.0, 2450.0), ("q4", 52.0, 1600.0)]


def before_the_models_are_swapped(tmp: Path) -> dict:
    """换模型之前：训练一个预测器，拿它出一次预测。返回之后要用的编号和预测。"""
    made = trained([real.data(tmp, real.data_rows(real.spread(80, seed=7)))])
    batch = real.points(tmp, [real.point(name, length, load=load) for name, length, load in BATCH])
    asked = real.predict(item_of(made, "predictor"), batch)
    finished(asked)
    return {"predictor": item_of(made, "predictor"), "batch": batch["id"], "rows": predictions(asked)}


def after_the_models_are_swapped(tmp: Path, before: dict) -> None:
    """换模型之后：同一个预测器、同一批点，再出一次预测，和之前的一样。"""
    asked = real.predict(before["predictor"], {"id": before["batch"]})
    finished(asked)
    rows = predictions(asked)
    assert sorted(rows) == sorted(before["rows"]) == sorted(name for name, _, _ in BATCH)
    for name, row in rows.items():
        for group in ("values", "lower", "upper"):
            for target, number in row[group].items():
                assert math.isclose(number, before["rows"][name][group][target], rel_tol=1e-12), f"{name} {group} {target}"


# ---- 另外几样 ----

def acceptance_lines_are_judged_by_code(tmp: Path) -> None:
    """合格线写在训练设定里：逐条判；那一部分没有点的不可判，不当它过了。"""
    lines = real.LINES + [
        {"id": "a3", "what": "故意定得过不了", "target": "rotation", "on": "holdout", "metric": "rmse", "op": "<=", "limit": 1e-12},
        {"id": "a4", "what": "往外推的那一组（这次没有）", "target": "rotation", "on": "outside", "metric": "rmse", "op": "<=", "limit": 0.1},
    ]
    made = trained([real.data(tmp, real.data_rows(real.spread(60, seed=8)))], real.train_setting(acceptance=lines))
    report = body_of(made)
    verdicts = {row["id"]: row for row in report["verdicts"]}
    assert (verdicts["a1"]["passed"], verdicts["a2"]["passed"], verdicts["a3"]["passed"], verdicts["a4"]["passed"]) == (True, True, False, None)
    assert verdicts["a1"]["value"] == report["holdout"]["rotation"]["rmse"] and report["holdout"]["rotation"]["scale"] == "log10"
    assert "不可判" in verdicts["a4"]["why"]
    assert report["training"]["setting_registered"] <= report["training"]["round_opened"], "线登记在这一轮开始之前"


def rows_that_disagree_are_reported(tmp: Path) -> None:
    """几份数据里同一个点结果不同：说出来，训练照常。"""
    designs = real.spread(40, seed=9)
    again = real.data_rows(designs[:5])
    again[0]["values"]["rotation"] *= 1.5
    made = real.train([real.data(tmp, real.data_rows(designs)), real.data(tmp, again)])
    status = finished(made)
    assert real.tasks(made) == {"train": ("done", "trained")}
    told = [problem["error"] for problem in status.rounds[-1].problems]
    assert len(told) == 1 and "结果不同" in told[0] and again[0]["point"][:12] in told[0]
    assert sum(body_of(made)["split"]["rows"].values()) == 40, "同一个点只算一行"
    assert body_of(made)["training"]["merge"] == {"rule": "first", "conflicts": 1}, "按什么规则留的、冲突了几个点，记进报告"


def a_training_that_diverges(tmp: Path) -> None:
    """训练出来的权重不是有限的数：记成训练发散（待查），什么都不交。"""
    rows = real.data_rows(real.spread(40, seed=10))
    for row in rows[::3]:
        row["values"]["slip_p95"] = 1e308
    made = real.train([real.data(tmp, rows)], real.train_setting(targets=["slip_p95"], scale={}, acceptance=[]))
    status = finished(made)
    assert real.tasks(made) == {"train": ("failed", "diverged")}, status.rounds[-1].problems
    assert next(row for row in status.outcomes if row["name"] == "diverged")["category"] == "unclear"
    assert status.rounds[-1].result == "failed" and status.rounds[-1].outputs == {}
    start.start(made)
    assert "点名" in view.view(made).rounds[-1].reason, "待查的不自动重排"


def things_refused_before_the_start(tmp: Path) -> None:
    item = real.data(tmp, real.data_rows(real.spread(20, seed=11)))
    assert "by" in refused(real.train([item], split=real.setting({"fraction": 0.2})))
    assert "fraction" in refused(real.train([item], split=real.split_setting(fraction=1.5)))
    assert "设计和条件" in refused(real.train([item], split=real.split_setting(outside=[{"column": "rotation", "max": 0.1}])))
    assert "targets" in refused(real.train([item], real.train_setting(targets=[])))
    assert "bone_removed" in refused(real.train([item], real.train_setting(targets=["bone_removed"], scale={}, acceptance=[])))
    assert "seed" in refused(real.train([item], real.train_setting(seed="eleven")))
    assert "scale" in refused(real.train([item], real.train_setting(scale={"rotation": "ln"})))
    assert "model" in refused(real.train([item], real.train_setting(model={"name": "no_such_model"})))
    assert "metric" in refused(real.train([item], real.train_setting(acceptance=[dict(real.LINES[0], metric="p99")])))
    assert "target" in refused(real.train([item], real.train_setting(acceptance=[dict(real.LINES[0], target="contact")])))


def stopping_a_training(tmp: Path) -> None:
    """停止：在跑的训练被结束；再启动重新来过，照样做完。"""
    made = real.train([real.data(tmp, real.data_rows(real.spread(60, seed=12)))])
    start.start(made)
    home = str(work_dir(made))

    def workers() -> list:
        return [process for process in psutil.process_iter(["cmdline"]) if any(home in part for part in process.info["cmdline"] or [])]

    assert start.stop(made).ok
    assert view.view(made).rounds[-1].result == "stopped" and real.tasks(made) == {"train": ("stopped", None)}
    helpers.wait_for(lambda: not workers(), seconds=15)
    start.start(made)
    assert view.view(made).rounds[-1].rerun == ["train"]
    real.run(made, seconds=SECONDS)
    assert real.tasks(made) == {"train": ("done", "trained")}


def data_from_different_kernels_are_not_mixed(tmp: Path) -> None:
    """几份数据合起来训练，得是同一个内核算的：不同内核的、没记是哪个内核算的，启动前被拒。
    预测器记着它的训练数据是哪个内核算的，一份预测跟着它记；复核时预测和 FEA 不是同一个内核算的，也被拒。"""
    first = real.data(tmp, real.data_rows(real.spread(30, seed=31)))
    other = dict(real.MADE_BY, kernel={"name": "another-kernel"})
    said = refused(real.train([first, real.data(tmp, real.data_rows(real.spread(30, seed=32)), made_by=other)]))
    assert "another-kernel" in said and "fake-kernel-1" in said, said
    assert "没有记" in refused(real.train([first, real.data(tmp, real.data_rows(real.spread(30, seed=33)), made_by=None)]))
    redone = dict(real.MADE_BY, derive={"package": "e" * 64})
    assert "推导量" in refused(real.train([first, real.data(tmp, real.data_rows(real.spread(30, seed=34)), made_by=redone)]))

    older = dict(real.MADE_BY, derive=None)             # 同一个内核、没有推导量（比如旧库转来的）：可以放在一起
    made = trained([first, real.data(tmp, real.data_rows(real.spread(30, seed=35)), made_by=older)])
    assert read_manifest(real.output(made, "predictor"))["made_by"] == as_v2(real.MADE_BY), \
        "预测器记着它的训练数据是怎么算的（合起来的写成第 2 版）"
    asked = real.predict(item_of(made, "predictor"), real.points(tmp, [real.point("p", 40.0)]))
    finished(asked)
    assert read_manifest(real.output(asked, "prediction"))["made_by"] == as_v2(real.MADE_BY), "一份预测跟着预测器记"
    elsewhere = real.data(tmp, real.data_rows([(40.0, 2000.0)]), made_by=other)
    assert "another-kernel" in refused(real.check(item_of(asked, "prediction"), elsewhere)), "预测和 FEA 不是同一个内核算的：不比"
    unknown = real.data(tmp, real.data_rows([(40.0, 2000.0)]), made_by=None)
    assert real.tasks(finished_check(real.check(item_of(asked, "prediction"), unknown))) == {"check": ("done", "checked")}, \
        "数据没记是哪个内核算的：没法比，不拦"


OTHERS = [acceptance_lines_are_judged_by_code, rows_that_disagree_are_reported, a_training_that_diverges,
          things_refused_before_the_start, stopping_a_training, data_from_different_kernels_are_not_mixed]


# ---- 场：训练、出预测、复核都走得通；留出的场不出操作台；误差和合格线照样由冻结的代码算 ----
# 用的是最简单的场模型（pod）。蓝图里“标量的和场的预测器”的场这一半，位置在冻结的四个文件里，模型怎么换都不动它们。

FIELD = "interface_slip"
FIELD_LINE = {"id": "f1", "what": "滑移场的留出误差", "target": FIELD, "on": "holdout", "metric": "rmse", "op": "<=", "limit": 0.05}


def a_field_is_trained_predicted_and_checked(tmp: Path) -> None:
    import numpy as np

    rows = real.data_rows(real.spread(80, seed=21), fields=True)
    made = trained([real.data(tmp, rows)], real.train_setting(fields=[FIELD], model={"name": "pod"}, acceptance=real.LINES + [FIELD_LINE]))
    report = body_of(made)
    counts = report["split"]["rows"]
    assert report["fields"] == [FIELD] and report["targets"] == ["rotation", "slip_p95"], "报告里标量和场分开列名字，误差排在一起"
    numbers = report["holdout"][FIELD]
    assert (numbers["n"], numbers["cells"], numbers["unmatched"], numbers["skipped"]) == (counts["holdout"], 5 * counts["holdout"], 0, 0)
    assert numbers["rmse"] < 0.05 and numbers["r2"] > 0.999 and 0.0 <= numbers["coverage"] <= 1.0, numbers
    assert report["outside"][FIELD]["n"] == 0 and report["holdout"]["rotation"]["n"] == counts["holdout"]
    verdicts = {row["id"]: row for row in report["verdicts"]}
    assert verdicts["f1"]["passed"] is True and verdicts["f1"]["value"] == numbers["rmse"], "合格线可以拿场的名字当 target"

    job = handed(made)
    kept = json.loads((job.parent / "truth.json").read_bytes())
    held = {row["point"] for part in ("holdout", "outside") for row in kept[part]}
    given = read_points(job / "train.jsonl")
    assert sorted(path.name for path in job.iterdir()) == ["ask.jsonl", "fields", "job.json", "train.jsonl"]
    sent = {path.name for path in (job / "fields").iterdir()}
    assert sent == {row["point"] for row in given} and sent.isdisjoint(held), "交出去的场只有训练那一部分的；留出的场不出操作台"
    assert all(set(row) == {"point", "bone_id", "values"} for row in read_points(job / "ask.jsonl")), "留出的点出去时不带场"
    assert np.allclose(np.load(job / given[0]["fields"][FIELD]), real.field_of(given[0]["values"]["length"]))
    assert set(kept["field_files"]) == held and kept["field_shapes"] == {FIELD: [5]}

    folder = real.output(made, "predictor")
    assert check_format("predictor", folder) == []
    listed = read_manifest(folder)
    assert [(column["name"], column["role"]) for column in listed["columns"]] == [("rotation", "label"), ("slip_p95", "derived"), (FIELD, "field")]
    assert listed["shapes"] == {FIELD: [5]}
    for chart in query.charts(made):
        assert query.chart(made, chart["name"]) is not None, chart

    batch = real.points(tmp, [real.point("in1", 31.0, load=1900.0), real.point("in2", 47.5, load=2300.0), real.point("long", 70.0)])
    asked = real.predict(item_of(made, "predictor"), batch)
    status = finished(asked)
    assert real.tasks(asked) == {"predict": ("done", "predicted")}, status.rounds[-1].problems
    out = real.output(asked, "prediction")
    assert check_format("prediction", out) == []
    guessed = predictions(asked)
    assert sorted(guessed) == ["in1", "in2"], "超出适用范围的点，场也不出"
    for name, length in (("in1", 31.0), ("in2", 47.5)):
        stacked = np.load(out / guessed[name]["fields"][FIELD], allow_pickle=False)
        assert stacked.shape == (3, 5) and (stacked[1] <= stacked[0]).all() and (stacked[0] <= stacked[2]).all(), "值、下界、上界摞在一起"
        assert np.allclose(stacked[0], real.field_of(length), rtol=0.01, atol=0.01), f"{name}：{stacked[0]} 对 {real.field_of(length)}"
        assert abs(guessed[name]["values"]["slip_p95"] / (0.95 * length / 2.0) - 1) < 0.15
    for chart in query.charts(asked):
        assert query.chart(asked, chart["name"]) is not None, chart

    measured = real.data(tmp, real.data_rows([(31.0, 1900.0), (47.5, 2300.0), (40.0, 2000.0)], fields=True))
    checked = finished_check(real.check(item_of(asked, "prediction"), measured))
    report = body_of(checked)
    assert report["fields"] == [FIELD] and len(report["matched"]) == 2 and len(report["only_data"]) == 1
    assert (report["summary"][FIELD]["n"], report["summary"][FIELD]["cells"]) == (2, 10) and report["summary"][FIELD]["rmse"] < 0.05
    assert all(row["fields"][FIELD]["rmse"] < 0.05 and row["fields"][FIELD]["max_abs"] < 0.1 for row in report["matched"]), "对得上的点，场逐个有差"
    for chart in query.charts(checked):
        assert query.chart(checked, chart["name"]) is not None, chart

    wrong = real.data(tmp, real.data_rows([(31.0, 1900.0), (47.5, 2300.0)], fields=True), field=lambda length: [length] * 7)
    report = body_of(finished_check(real.check(item_of(asked, "prediction"), wrong)))
    assert (report["summary"][FIELD]["n"], report["summary"][FIELD]["skipped"]) == (0, 2), "形状对不上的场比不了，数出来，不硬比"
    assert all(row["fields"][FIELD] is None for row in report["matched"])


def only_a_field_can_be_predicted(tmp: Path) -> None:
    """一个标量都不预测，只预测场：照样训练、打包、出预测。"""
    import numpy as np

    rows = real.data_rows(real.spread(60, seed=22), fields=True)
    made = trained([real.data(tmp, rows)], real.train_setting(targets=[], fields=[FIELD], scale={}, acceptance=[FIELD_LINE], model={"name": "pod"}))
    report = body_of(made)
    assert report["targets"] == [] and report["fields"] == [FIELD] and report["verdicts"][0]["passed"] is True
    listed = read_manifest(real.output(made, "predictor"))
    assert [(column["name"], column["role"]) for column in listed["columns"]] == [(FIELD, "field")]
    asked = real.predict(item_of(made, "predictor"), real.points(tmp, [real.point("p", 42.0, load=2000.0)]))
    finished(asked)
    row = predictions(asked)["p"]
    assert row["values"] == {} and np.allclose(np.load(real.output(asked, "prediction") / row["fields"][FIELD])[0], real.field_of(42.0), atol=0.01)


def fields_that_cannot_be_learned_are_refused(tmp: Path) -> None:
    """要预测的不是数据里的场、选的模型不会预测场：启动前被拒。各行形状不一样的场：这一轮照实做不下去。"""
    item = real.data(tmp, real.data_rows(real.spread(30, seed=23), fields=True))
    plain = real.data(tmp, real.data_rows(real.spread(30, seed=24)))
    field = dict(fields=[FIELD], model={"name": "pod"})
    assert "场" in refused(real.train([plain], real.train_setting(**field))), "数据里没有这个场"
    assert "场" in refused(real.train([item], real.train_setting(fields=["rotation"], model={"name": "pod"}))), "标量不是场"
    assert "fields" in refused(real.train([item], real.train_setting(fields=FIELD)))
    assert "targets" in refused(real.train([item], real.train_setting(targets=[FIELD], fields=[FIELD], scale={}, acceptance=[])))
    assert "只会预测标量" in refused(real.train([item], real.train_setting(fields=[FIELD], model={"name": "ridge"})))
    assert "target" in refused(real.train([item], real.train_setting(acceptance=[dict(FIELD_LINE, target="contact")], **field)))

    ragged = real.data(tmp, real.data_rows(real.spread(30, seed=25), fields=True), field=lambda length: [length] * (5 if length < 40 else 6))
    made = real.train([ragged], real.train_setting(acceptance=[], **field))
    status = finished(made)
    assert status.rounds[-1].result == "failed" and "形状不一样" in status.rounds[-1].reason, status.rounds[-1].reason
    assert status.rounds[-1].outputs == {} and real.tasks(made) == {}, "还没派出去就做不下去了，什么都不交"


FIELDS = [a_field_is_trained_predicted_and_checked, only_a_field_can_be_predicted, fields_that_cannot_be_learned_are_refused]
