"""参照内核包（external/kernel_m1_3406，M1-3406-v1）还登记得上，参照包那条（fea.reference）还启动得了。

包的清单升到第 2 版以后，契约核清单里的 modes：内核只认 template、build、post。这个包的清单里原来多写了 bench
（Lamé 对照算例），所以真的参照内核包登记不上，科学验收的整条链在登记内核那一步就失败。科学验收不在平时的检查里，
一直没露出来。2026-11-19 清单里去掉了 bench（用户定的）：bench 和 selfcheck 一样，包的入口照样认，只是不写进清单。

这里守的是平时的检查里看得见的那几步：
    清单      现打的包过契约的核对；modes 只写系统会叫的三样
    入口      清单里没写的两样，直接叫包还做得了：自检样本过得去；Lamé 对照建得出模型（只建模，不求解）
    登记      登记得进一本空账；配 3406 的骨模型和旧常数的床支撑 F，fea.reference 启动前的核对过得去，作业排上了队
真的求解在科学验收里（tests/science，要 Abaqus）。
要旧系统的文件（只读；换了地方设 STEMLAB_LEGACY）；Lamé 那条另要 gmsh。哪样没有，用到它的测试跳过并说明原因：
看到跳过，不等于那部分验过了。external/ 不在检查的范围里，所以测试放在这里。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from stemlab.contract.formats import package as package_format
from stemlab.contract.formats.manifest import check_format, read_manifest
from stemlab.desk.core import start as starting
from stemlab.registry import register
from tests import real
from tests.science import lines, tools
from tests.science.test_fea import CONDITIONS, A
from tests_free import sawbone3406

REPO = Path(__file__).resolve().parents[2]
HERE = REPO / "external" / "kernel_m1_3406"


@pytest.fixture(scope="module")
def legacy() -> Path:
    """旧系统的文件夹。只读。"""
    wanted = [tools.LEGACY / "docs" / "freeze" / "M1-3406-v1_files.tar", tools.LEGACY / sawbone3406.SUMMARY,
              *(tools.LEGACY / "v2" / "data" / "femur_3406" / file for file in tools.STEPS.values())]
    missing = [str(path) for path in wanted if not path.is_file()]
    if missing:
        pytest.skip(f"找不到旧系统的文件（{missing[0]}）。换地方了就设 STEMLAB_LEGACY")
    return tools.LEGACY


@pytest.fixture(scope="module")
def summary(legacy) -> dict:
    return json.loads((legacy / sawbone3406.SUMMARY).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def works():
    """gmsh 加载得了。加载不了（比如安全软件还占着它的 DLL）就跳过：Lamé 对照要划网格。"""
    try:
        import gmsh  # noqa: F401
    except (ImportError, OSError) as error:
        pytest.skip(f"gmsh 加载不了：{error}")


def _build(script: Path, folder: Path, *before: str) -> Path:
    done = subprocess.run([sys.executable, str(script), *before, str(folder)], capture_output=True, timeout=600,
                          env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


@pytest.fixture(scope="module")
def built(legacy, tmp_path_factory) -> Path:
    """照 external/kernel_m1_3406 的做法现打一个内核包：参照包。"""
    return _build(HERE / "build.py", tmp_path_factory.mktemp("kernel") / "package", str(legacy))


@pytest.fixture(scope="module")
def bone(legacy, summary, tmp_path_factory) -> Path:
    return sawbone3406.bone_folder(tmp_path_factory.mktemp("bone3406") / "bone", legacy, summary)


def run(package: Path, source: Path, out: Path) -> dict:
    """照核心的办法跑一次包：入口后面跟输入文件夹和输出文件夹，在包的文件夹里跑。返回 result.json 的内容。"""
    out.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, str(package / "code" / "main.py"), str(source), str(out)], cwd=package,
                          env=dict(os.environ, **tools.ENV), capture_output=True, timeout=900)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads((out / package_format.RESULT).read_bytes())


def test_the_package_is_a_well_formed_kernel(built):
    """现打的包过契约的核对：这一步不过，登记不上，fea.reference 就没有内核可用。"""
    assert check_format("kernel", built) == []
    listed = read_manifest(built)
    assert listed["modes"] == ["template", "build", "post"] == list(package_format.MODES["kernel"]), \
        "清单的 modes 只写系统会叫的三样；bench、selfcheck 入口里认，不写进清单"
    assert listed["bones"] == [tools.BONE_ID] and listed["model"]["name"] == "M1-3406-v1"


def test_what_the_manifest_does_not_list_still_runs(built, bone, works, tmp_path):
    """清单里没写的两样，直接叫包还做得了：自检样本过得去；Lamé 对照（bench）建得出模型，交出求解的命令。不求解。"""
    listed = read_manifest(built)
    for sample in listed["selftest"]:
        got = run(built, built / sample["input"], tmp_path / f"selftest-{sample['name']}")
        expected = json.loads((built / sample["expected"]).read_bytes())
        assert package_format.differences(expected, got, listed["tolerance"]) == [], sample["name"]
    job = {"mode": "bench", "bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": {}, "job": str(tmp_path / "job-lame"),
           "point": {"name": "lame", "design": lines.LAME, "conditions": {}}}
    (tmp_path / "ask").mkdir()
    (tmp_path / "ask" / "job.json").write_text(json.dumps(job), encoding="utf-8")
    said = run(built, tmp_path / "ask", tmp_path / "out")
    assert said["status"] == "built", said
    assert (tmp_path / "job-lame" / "lame_fric.inp").is_file() and said["solve"]["command"], "Lamé 对照的输入写出来了，求解的命令也交了"


def test_it_registers_and_the_reference_run_can_start(real_lab, data, legacy, summary, built, tmp_path):
    """登记进一本空账（科学验收的整条链原来就卡在这一步）；配 3406 的骨模型和旧常数的床支撑 F，
    fea.reference 启动前的核对过得去，设计 A 的作业排上了队。不往下跑：建模、求解在科学验收里。"""
    kernel = register.register_external("kernel", "kernel-m1-3406", source=built, note="测试用：现打的 M1-3406-v1 内核包", by="tester")
    bone = register.register_external("bone_model", "sawbone3406-model", source=sawbone3406.bone_folder(tmp_path / "bone", legacy, summary),
                                      note="测试用：3406 的两个实体，标志点照旧系统找出的", by="tester", bone_id=tools.BONE_ID, new_bone=True)
    derive = register.register_external("derive_def", "bed-f-3406", note="测试用：旧常数的床支撑 F，参照包那条用的", by="tester",
                                        source=_build(REPO / "external" / "derive_bed_f" / "build.py", tmp_path / "derive"))
    point = {"name": "A", "bone_id": tools.BONE_ID, "design": A, "conditions": CONDITIONS, "reason": "和旧数据库 v0.14 同一个设计"}
    made = real.fea(tmp_path, [point], export={"solve_timeout_s": 7200}, kernel=kernel, derive=derive, bone=bone)
    began = starting.start(made)
    assert began.ok, began
    assert real.tasks(made) == {"A": ("queued", None)}
