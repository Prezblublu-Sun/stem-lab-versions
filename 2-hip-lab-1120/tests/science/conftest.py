"""科学验收共用的夹具：旧系统的文件（只读）、现打的内核包、3406 的骨模型、跑内核的办法。

哪样没有，用到它的测试就跳过并说明缺什么。这里不往旧系统的文件夹里写任何东西。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import helpers
from tests.science import tools


@pytest.fixture(scope="session")
def legacy() -> Path:
    """旧系统的文件夹。只读。"""
    if not (tools.LEGACY / "v2" / "data" / "femur_3406" / tools.STEPS["cortical"]).is_file():
        pytest.skip(f"找不到旧系统的文件（{tools.LEGACY}）。换地方了就设 STEMLAB_LEGACY")
    return tools.LEGACY


@pytest.fixture(scope="session")
def source(legacy) -> Path:
    """3406 的 CAD 骨源：旧系统里那两个 STEP 所在的文件夹。只读。"""
    return legacy / "v2" / "data" / "femur_3406"


@pytest.fixture(scope="session")
def bone(source, tmp_path_factory) -> Path:
    """一个骨模型文件夹，两个实体就是旧系统用的那两个 STEP。内核只认实体，所以清单只写它用得到的几项。"""
    folder = tmp_path_factory.mktemp("bone3406")
    (folder / "solids").mkdir()
    for name, file in tools.STEPS.items():
        shutil.copyfile(source / file, folder / "solids" / f"{name}.step")
    listed = {"format": 1, "kind": "bone_model", "files": ["solids/cancellous.step", "solids/cortical.step"], "bone_id": tools.BONE_ID,
              "solids": {name: {"file": f"solids/{name}.step"} for name in tools.STEPS}}
    (folder / "manifest.json").write_text(json.dumps(listed), encoding="utf-8")
    return folder


@pytest.fixture(scope="session")
def package(legacy, tmp_path_factory) -> Path:
    """照 external/kernel_m1_3406 的做法现打一个内核包。"""
    folder = tmp_path_factory.mktemp("kernel") / "package"
    done = subprocess.run([sys.executable, str(helpers.REPO / "external" / "kernel_m1_3406" / "build.py"), str(legacy), str(folder)],
                          capture_output=True, timeout=600, env=dict(os.environ, **tools.ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return folder


@pytest.fixture(scope="session")
def abaqus() -> Path:
    if not tools.ABAQUS.is_file():
        pytest.skip(f"这台机器上找不到 Abaqus 的启动器（{tools.ABAQUS}）。换地方了就设 STEMLAB_ABAQUS")
    return tools.ABAQUS


@pytest.fixture
def kernel(package, tmp_path):
    """跑一次内核：kernel(job, 名字) -> result.json 的内容。"""
    def run(job: dict, name: str, timeout: float = 3600.0) -> dict:
        ask, out = tmp_path / f"ask-{name}", tmp_path / f"out-{name}"
        ask.mkdir(), out.mkdir()
        (ask / "job.json").write_text(json.dumps(job), encoding="utf-8")
        done = subprocess.run([sys.executable, str(package / "code" / "main.py"), str(ask), str(out)], cwd=package,
                              env=dict(os.environ, **tools.ENV), capture_output=True, timeout=timeout)
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
        return json.loads((out / "result.json").read_bytes())

    return run
