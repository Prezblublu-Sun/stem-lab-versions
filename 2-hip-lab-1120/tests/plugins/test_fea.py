"""FEA 插件的验收：给定骨模型、设计、条件，算出力学响应；每一行数据都追得到点、骨、轮。

情形都写在 fea_cases.py 里，用假的内核和假的求解（tests/packages/）。
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
from tests.plugins import fea_cases


@pytest.mark.parametrize("case", fea_cases.BLUEPRINT + fea_cases.OTHERS, ids=lambda case: case.__name__)
def test_fea(real_lab, data, tmp_path, case):
    case(tmp_path)


# ---- 7 把 jobs.py 和 run.py 整个换一份写法：上面几条照过 ----

RUN = """\
import json, os, pathlib, sys
from tests.plugins import fea_cases
import plugins.fea.jobs as jobs, plugins.fea.run as run
base = pathlib.Path(sys.argv[1])
done = []
for case in fea_cases.BLUEPRINT:
    root = base / case.__name__
    os.environ.update(STEMLAB_DATA=str(root / "data"), STEMLAB_CACHE=str(root / "cache"), STEMLAB_SLOTS=str(root / "slots"))
    (root / "tmp").mkdir(parents=True)
    case(root / "tmp")
    done.append(case.__name__)
print(json.dumps({"done": done, "rewritten": [getattr(jobs, "REWRITTEN", False), getattr(run, "REWRITTEN", False)], "run": run.__file__}))
"""


def test_rewriting_jobs_and_run_changes_nothing_the_acceptance_sees(real_own_lab, data, tmp_path):
    for name in ("jobs.py", "run.py"):
        shutil.copy(helpers.REPO / "tests" / "plugins" / "fea_rewritten" / name, real_own_lab / "plugins" / "fea" / name)
    env = {key: value for key, value in os.environ.items() if key not in ("STEMLAB_REPO", "STEMLAB_PLUGINS")}
    env.update(PYTHONPATH=str(helpers.REPO), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", RUN, str(tmp_path / "cases")], cwd=real_own_lab, env=env,
                          capture_output=True, timeout=900)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-3000:]
    said = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    assert said["done"] == [case.__name__ for case in fea_cases.BLUEPRINT], "蓝图的前六条在换过写法的代码上照过"
    assert said["rewritten"] == [True, True] and str(real_own_lab) in said["run"], "跑的确实是换过的那一份"
    assert code_state.frozen_ok() == [], "冻结的文件一个没动"


# ---- 冻结文件里的规则，直接试 ----

def test_which_outcome_a_finished_job_gets():
    from plugins.fea import outcomes

    built = {"status": "built"}
    table = [
        ({"build": built, "post": {"status": "ok"}, "derived": {"slip_p95": 1.0}}, "finished"),
        ({"build": built, "post": {"status": "ok"}, "derived": None}, "error"),
        ({"build": {"status": "misfit", "reason": "too long"}}, "misfit"),
        ({"build": {"status": "mesh_failed"}}, "mesh_failed"),
        ({"build": {"status": "env"}}, "env"),
        ({"build": {"status": "something new"}}, "error"),
        ({"build": None}, "error"),
        ({"build": built, "post": None}, "error"),
        ({"build": built, "post": {"status": "not_converged"}}, "not_converged"),
        ({"build": built, "post": {"status": "unstable"}}, "unstable"),
        ({"build": built, "post": {"status": "env"}}, "env"),
        ({"build": built, "post": {"status": "odd"}}, "error"),
        ({"build": built, "lost": "restart"}, "env"),
        ({"build": built, "lost": "timeout"}, "error"),
        ({"build": built, "lost": "crashed"}, "error"),
        ({"lost": "solve 起不来：FileNotFoundError"}, "error"),
    ]
    for result, expected in table:
        name, reason = outcomes.classify(result)
        assert name == expected and reason, f"{result} 该归 {expected}，归成了 {name}"
    assert outcomes.classify({"build": {"status": "misfit", "reason": "too long"}})[1] == "too long"
    assert {row.name: row.category for row in outcomes.OUTCOMES} == {
        "finished": "ok", "misfit": "conclusion", "unstable": "conclusion", "not_converged": "unclear",
        "mesh_failed": "unclear", "env": "retryable", "error": "unclear"}
    assert [outcomes.task_state(name) for name in ("finished", "misfit", "env", "error")] == ["done", "done", "failed", "failed"]
    assert outcomes.in_data("misfit") and outcomes.in_data("unstable") and not outcomes.in_data("mesh_failed")


def test_when_numerical_failures_are_too_many():
    from plugins.fea import outcomes

    assert outcomes.too_many_numerical(["finished"] * 39 + ["mesh_failed"]) is None, "只有一个，不提醒"
    assert outcomes.too_many_numerical(["finished"] * 38 + ["mesh_failed", "not_converged"]) is None, "两个，占 5%，正好在线上"
    assert "37 个作业里有 2 个" in outcomes.too_many_numerical(["finished"] * 35 + ["mesh_failed", "not_converged"])
    assert outcomes.too_many_numerical(["finished", "misfit", "unstable", "env", "error"]) is None, "放不进去、松动、环境问题都不算在内"


def test_criteria_are_checked_before_the_start_and_judged_by_code():
    from plugins.fea import judge

    listed = [{"name": "rotation", "role": "label"}, {"name": "slip", "role": "field"}]
    good = {"id": "g1", "what": "x", "column": "rotation", "stat": "median", "op": "<", "limit": 1.0}
    assert judge.problems({"criteria": [good]}, listed) == []
    for bad in ({}, {"criteria": []}, {"criteria": [dict(good, column="slip")]}, {"criteria": [dict(good, stat="p99")]},
                {"criteria": [dict(good, op="==")]}, {"criteria": [dict(good, limit="1")]}, {"criteria": [good, good]},
                {"criteria": [dict(good, missing="guess")]}, {"criteria": [{"id": "g1"}]}):
        assert judge.problems(bad, listed), bad

    rows = {name: {"values": {"rotation": value}} for name, value in (("a", 0.2), ("b", 0.4), ("c", 0.9))}
    assert judge.judge({"criteria": [good]}, rows, 3)[0] | {"what": ""} == {
        "id": "g1", "what": "", "column": "rotation", "stat": "median", "op": "<", "limit": 1.0, "used": 3, "missing": 0,
        "value": 0.4, "passed": True}
    unjudged = judge.judge({"criteria": [good]}, rows, 4)[0]
    assert (unjudged["passed"], unjudged["value"], unjudged["missing"]) == (None, None, 1) and "不可判" in unjudged["why"]
    assert judge.judge({"criteria": [dict(good, missing="skip", limit=0.3)]}, rows, 4)[0]["passed"] is False
    assert judge.judge({"criteria": [dict(good, missing="skip")]}, {}, 2)[0]["passed"] is None, "一个有数的点都没有"

    assert not judge.late("2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z")
    assert judge.late("2026-01-03T00:00:00.000Z", "2026-01-02T00:00:00.000Z"), "判据是这一轮开始之后才登记的"
    assert judge.late(None, "2026-01-02T00:00:00.000Z"), "查不到登记的时间，证明不了它写在前面"


def test_package_manifests_must_describe_every_column():
    from plugins.fea import export
    from tests import packages

    kernel, derive = dict(packages.EXTRAS["kernel_fake"]), dict(packages.EXTRAS["derive_fake"])
    assert export.problems(kernel, derive) == []
    assert [column["role"] for column in export.columns(kernel, derive)] == [
        "design", "design", "condition", "pre", "label", "label", "field", "derived"]
    assert any("fields" in text for text in export.problems({**kernel, "fields": None}, derive))
    assert any("columns" in text for text in export.problems(kernel, {**derive, "columns": []}))
    clash = {**derive, "columns": packages.columns(("rotation", "deg", "same name as a label"))}
    assert any("重复" in text and "rotation" in text for text in export.problems(kernel, clash))
