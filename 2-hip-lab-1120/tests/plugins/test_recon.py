"""重建插件的验收：一根骨从骨源到过了检查门的骨模型，每处人工改动都留痕。

情形都写在 recon_cases.py 里，骨源是现造的一根 CAD 假股骨（tests/real.py，真值已知）。
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
from tests.plugins import recon_cases


@pytest.mark.parametrize("case", recon_cases.BLUEPRINT + recon_cases.OTHERS, ids=lambda case: case.__name__)
def test_recon(real_lab, data, tmp_path, case):
    case(tmp_path)


# ---- 4 把 rebuild.py 整个换一份写法：格式核对和检查门照过，或者如实不过 ----

RUN = """\
import json, os, pathlib, sys
from tests.plugins import recon_cases
import plugins.recon.rebuild as rebuild
base = pathlib.Path(sys.argv[1])
done = []
for case in getattr(recon_cases, sys.argv[2]):
    root = base / case.__name__
    os.environ.update(STEMLAB_DATA=str(root / "data"), STEMLAB_CACHE=str(root / "cache"), STEMLAB_SLOTS=str(root / "slots"))
    (root / "tmp").mkdir(parents=True)
    case(root / "tmp")
    done.append(case.__name__)
print(json.dumps({"done": done, "rewritten": getattr(rebuild, "REWRITTEN", False), "file": rebuild.__file__}))
"""


def _with_another_rebuild(repo, tmp_path, written: str, cases: str) -> dict:
    """把仓库拷贝里的 rebuild.py 换成 tests/plugins/recon_rewritten/<written>，在那里把 recon_cases.<cases> 跑一遍。"""
    shutil.copy(helpers.REPO / "tests" / "plugins" / "recon_rewritten" / written, repo / "plugins" / "recon" / "rebuild.py")
    env = {key: value for key, value in os.environ.items() if key not in ("STEMLAB_REPO", "STEMLAB_PLUGINS")}
    env.update(PYTHONPATH=str(helpers.REPO), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", RUN, str(tmp_path / "cases"), cases], cwd=repo, env=env, capture_output=True, timeout=900)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-3000:]
    said = json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])
    assert str(repo) in said["file"], "跑的确实是换过的那一份"
    assert code_state.frozen_ok() == [], "冻结的文件一个没动"
    return said


def test_rewriting_rebuild_changes_nothing_the_acceptance_sees(real_own_lab, data, tmp_path):
    said = _with_another_rebuild(real_own_lab, tmp_path, "rebuild.py", "BLUEPRINT")
    assert said["rewritten"] is True
    assert said["done"] == [case.__name__ for case in recon_cases.BLUEPRINT], "蓝图的前三条在换过写法的代码上照过"


def test_a_careless_rebuild_fails_honestly(real_own_lab, data, tmp_path):
    said = _with_another_rebuild(real_own_lab, tmp_path, "careless.py", "CARELESS")
    assert said["rewritten"] == "careless"
    assert said["done"] == [case.__name__ for case in recon_cases.CARELESS], "格式和检查门没让它混过去"


# ---- 冻结文件里的规则，直接试 ----

def test_the_gate_compares_each_line_and_missing_numbers_do_not_pass():
    from plugins.recon import gate

    lines = [{"name": "closed", "value": "watertight", "equals": True}, {"name": "thick", "value": "wall", "min": 0.3, "max": 5.0},
             {"name": "small", "value": "change", "max": 0.005, "what": "体积变化"}, {"name": "absent", "value": "nobody_measured", "min": 0}]
    results = gate.checks({"watertight": True, "wall": 0.3, "change": 0.0051}, lines)
    assert [(row["name"], row["value"], row["passed"]) for row in results] == [
        ("closed", True, True), ("thick", 0.3, True), ("small", 0.0051, False), ("absent", None, False)]
    assert results[2]["limit"] == {"max": 0.005, "what": "体积变化"} and not gate.passed(results)
    assert gate.passed(results[:2]) and not gate.passed([]), "一条检查都没有不算过"
    assert not gate.checks({"wall": True}, lines[1:2])[0]["passed"], "要比大小的线，量出来的不是数就不过"
    assert not gate.checks({"watertight": 1.0}, [{"name": "closed", "value": "watertight", "equals": "yes"}])[0]["passed"]

    good = {"gate": lines}
    assert gate.problems(good) == [] and not gate.wants_smoke(good)
    assert gate.wants_smoke({"gate": [{"name": "builds", "value": "kernel_smoke", "equals": True}]})
    for bad in ({}, {"gate": []}, {"gate": [{"name": "closed"}]}, {"gate": [{"name": "closed", "value": "watertight"}]},
                {"gate": [lines[0], lines[0]]}, {"gate": [{"name": "Closed Surface", "value": "watertight", "equals": True}]},
                {"gate": [{"name": "thick", "value": "wall", "min": "0.3"}]}, {"gate": lines, "smoke": {"mode": "solve", "design": {}}},
                {"gate": lines, "smoke": {"mode": "build"}}):
        assert gate.problems(bad), bad


def test_the_reconstruction_setting_must_say_side_frame_and_materials():
    from plugins.recon import model
    from tests import real

    good = {"side": "left", "frame": real.BONE_EXTRA["frame"], "materials": real.BONE_EXTRA["materials"]}
    assert model.setting_problems(good) == []
    assert model.setting_problems([]) and model.setting_problems({**good, "side": "both"})
    assert model.setting_problems({**good, "frame": {"origin": "somewhere"}}) and model.setting_problems({**good, "materials": {}})


def test_what_is_written_is_checked_against_the_format(tmp_path):
    from plugins.recon import model
    from stemlab.contract.formats.manifest import check_format, read_manifest
    from tests import real

    solids = {name: tmp_path / f"{name}.STEP" for name in model.SOLIDS}
    for path in solids.values():
        path.write_bytes(b"ISO-10303-21; " + path.name.encode())
    setting = {"side": "right", "frame": real.BONE_EXTRA["frame"], "materials": real.BONE_EXTRA["materials"]}
    how = {"bone_id": "femur042", "setting": setting, "solids": solids, "landmarks": real.BONE_EXTRA["landmarks"],
           "history": [{"step": "import", "what": "x"}]}
    passed = [{"name": "closed", "value": True, "limit": {"equals": True}, "passed": True}]
    folder = model.write(tmp_path / "model", "bone_model", checks=passed, measures={"wall": 1.0}, **how)
    assert check_format("bone_model", folder) == []
    listed = read_manifest(folder)
    assert listed["solids"] == {"cortical": {"file": "solids/cortical.step"}, "cancellous": {"file": "solids/cancellous.step"}}
    assert (listed["bone_id"], listed["units"], listed["measures"]) == ("femur042", model.UNITS, {"wall": 1.0})

    not_passed = [dict(passed[0], passed=False)]
    with pytest.raises(ValueError, match="不符合格式"):
        model.write(tmp_path / "bad", "bone_model", checks=not_passed, **how)
    assert check_format("bone_draft", model.write(tmp_path / "draft", "bone_draft", checks=not_passed, **how)) == [], "候选可以有没过的检查"
    fewer = {name: point for name, point in real.BONE_EXTRA["landmarks"].items() if name != "neck_center"}
    with pytest.raises(ValueError, match="neck_center"):
        model.write(tmp_path / "fewer", "bone_draft", checks=[], **{**how, "landmarks": fewer})
