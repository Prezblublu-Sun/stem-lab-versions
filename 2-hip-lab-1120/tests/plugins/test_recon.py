"""重建插件的验收：一根骨从骨源到过了检查门的骨模型，每处人工改动都留痕。

情形都写在 recon_cases.py 里。5c 起重建叫重建方法包干活，验收用假的方法包（tests/packages/recon_fake），
骨源里放着一根造出来的股骨的标志点（tests/contract/bone_samples.py，坐标系和前倾角的真值已知）。
"""
from __future__ import annotations

import copy
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


@pytest.mark.parametrize("case", recon_cases.REFUSED, ids=lambda case: case.__name__)
def test_refused_before_the_start(real_lab, data, tmp_path, case):
    case(tmp_path)


@pytest.mark.parametrize("case", recon_cases.BROKEN, ids=lambda case: case.__name__)
def test_what_the_method_hands_back_is_checked(real_lab, data, tmp_path, case):
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
    promised = {"watertight", "wall", "change", "nobody_measured"}
    assert gate.problems(good, promised) == [] and not gate.wants_smoke(good)
    assert gate.wants_smoke({"gate": [{"name": "fits", "value": "stem_smoke", "equals": True}]})
    for bad in ({}, {"gate": []}, {"gate": [{"name": "closed"}]}, {"gate": [{"name": "closed", "value": "watertight"}]},
                {"gate": [lines[0], lines[0]]}, {"gate": [{"name": "Closed Surface", "value": "watertight", "equals": True}]},
                {"gate": [{"name": "thick", "value": "wall", "min": "0.3"}]}, {"gate": lines, "smoke": {"mode": "template", "design": {}}},
                {"gate": lines, "smoke": {"design": {}, "conditions": {}}}, {"gate": lines, "smoke": {"placement": {}}},
                {"gate": lines, "smoke": {"design": {}, "placement": []}}):
        assert gate.problems(bad, promised), bad
    assert gate.problems({"gate": lines, "smoke": {"design": {"length": 30}, "placement": {"cut_drop": 1.0}}}, promised) == []
    found = gate.problems(good, promised - {"nobody_measured"})
    assert len(found) == 1 and "第 4 条" in found[0] and "nobody_measured" in found[0], "拿方法包没答应给的量来比：说出是哪一条、哪个量"
    from plugins.recon import plugin

    assert set(plugin.RESERVED) == {"stem_smoke", "stem_smoke_reason", "anteversion_deg"}, "骨架自己记的三个量，方法包不能用这几个名字"
    assert gate.problems({"gate": [{"name": "fits", "value": "stem_smoke", "equals": True}]}, set(plugin.RESERVED)) == []


def test_the_reconstruction_setting_must_say_side_frame_and_materials():
    """第 1 版那种没有声明的重建设定的核法。5c 起重建设定照方法包的声明写，骨架不再叫它（留到 5g 移出隔离）。"""
    from plugins.recon import model
    from tests import real

    good = {"side": "left", "frame": real.BONE_EXTRA["frame"], "materials": real.BONE_EXTRA["materials"]}
    assert model.setting_problems(good) == []
    assert model.setting_problems([]) and model.setting_problems({**good, "side": "both"})
    assert model.setting_problems({**good, "frame": {"origin": "somewhere"}}) and model.setting_problems({**good, "materials": {}})


def test_what_is_written_is_checked_against_the_format(tmp_path):
    """照第 2 版写：方法包交回来的几段，加上骨架记的来源、照标志点算的坐标系；写完自己先核一遍格式。"""
    from plugins.recon import model
    from stemlab.contract.formats.manifest import check_format, read_manifest
    from tests import real

    marks, truth = real.recon_marks()
    files = {name: tmp_path / f"{name}.STEP" for name in ("cortical", "cancellous")}
    for path in files.values():
        path.write_bytes(b"ISO-10303-21; " + path.name.encode())
    made = {"how": "cad", "side": "right", "bone_type": "synthetic", "frame": {"file": "the files' own coordinates"},
            "coverage": {"extent": "whole", "proximal_mm": 80.0, "distal_mm": 400.0},
            "regions": [{"name": name, "role": name, "geometry": {"kind": "solid", "format": "step", "file": str(path)}, "volume_mm3": 1.0,
                         "material": {"model": "elastic", "E": 100.0, "nu": 0.3}} for name, path in files.items()],
            "landmarks": {name: {"xyz": xyz, "definition": {"method": "m", "version": "1", "params": {}}, "fit": {}} for name, xyz in marks.items()},
            "history": [{"step": "import", "what": "x"}]}
    source = {"how": "cad", "method": {"id": "R0001", "hash": "a" * 64}, "setting": {"id": "R0002", "hash": "b" * 64}}
    passed = [{"name": "closed", "value": True, "limit": {"equals": True}, "passed": True}]
    how = {"bone_id": "femur042", "source": source}
    folder = model.write(tmp_path / "model", "bone_model", made=made, checks=passed, measures={"wall": 1.0}, **how)
    assert check_format("bone_model", folder) == []
    listed = read_manifest(folder)
    assert [region["geometry"]["file"] for region in listed["regions"]] == ["regions/cortical.step", "regions/cancellous.step"]
    assert all((folder / f"regions/{name}.step").read_bytes() == path.read_bytes() for name, path in files.items()), "原样复制"
    assert (listed["format"], listed["bone_id"], listed["units"], listed["measures"], listed["source"], listed["surfaces"]) == (
        2, "femur042", model.UNITS, {"wall": 1.0}, source, {})
    near = {key: listed["frame"][key] for key in ("origin", "x", "y", "z")}
    assert listed["frame"]["method"] == "shaft_condyles" and recon_cases.same_frame(near, truth), "坐标系照标志点算，完整的股骨照后髁连线"
    assert abs(model.measured(made)[model.ANTEVERSION] - 12.0) < 1e-9, "完整的股骨量出前倾角"
    proximal = dict(made, coverage=dict(made["coverage"], extent="proximal"), frame={"file": "x", "anteversion_deg": 12.0})
    again = read_manifest(model.write(tmp_path / "proximal", "bone_draft", made=proximal, checks=[], measures={}, **how))
    assert (again["frame"]["method"], again["frame"]["anteversion_deg"]) == ("shaft_neck", 12.0) and recon_cases.same_frame(again["frame"], truth)
    assert model.measured(proximal) == {}, "近端一段的前倾角是设定给的，不量"

    not_passed = [dict(passed[0], passed=False)]
    with pytest.raises(ValueError, match="不符合格式"):
        model.write(tmp_path / "bad", "bone_model", made=made, checks=not_passed, measures={}, **how)
    assert check_format("bone_draft", model.write(tmp_path / "draft", "bone_draft", made=made, checks=not_passed, measures={}, **how)) == [], \
        "候选可以有没过的检查"
    fewer = dict(made, landmarks={name: point for name, point in made["landmarks"].items() if name != "neck_center"})
    with pytest.raises(ValueError, match="neck_center"):
        model.write(tmp_path / "fewer", "bone_draft", made=fewer, checks=[], measures={}, **how)
    relative = copy.deepcopy(made)
    relative["regions"][0]["geometry"]["file"] = "cortical.STEP"
    with pytest.raises(ValueError, match="绝对路径"):
        model.write(tmp_path / "relative", "bone_draft", made=relative, checks=[], measures={}, **how)
    outside = copy.deepcopy(made)
    outside["regions"][0]["name"] = "../cortical"
    with pytest.raises(ValueError, match="区域的名字"):
        model.write(tmp_path / "outside", "bone_draft", made=outside, checks=[], measures={}, **how)
    assert not (tmp_path / "outside" / "cortical.step").exists(), "名字不合规矩的区域，文件不往 regions/ 外面拼"
