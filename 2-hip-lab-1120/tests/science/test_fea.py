"""FEA 的科学验收：一个有解析解的小算例在容差内；界面力和外载平衡；载荷的大小对；同一个设计和旧系统对得上。

算例和线在 lines.py。跑的是照 external/kernel_m1_3406 现打的内核包，和登记进系统的那个包是同一份做法。
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

import pytest

from tests.science import lines, tools

pytestmark = pytest.mark.science

# 设计 A：旧数据库 v0.14 的 sb13_a105_91e458e3
A = {"L": 43.06123448163271, "rho_tip": 0.21170926745980978, "q": 2.9987468989565968, "lam": 1.118611091375351,
     "g_ml": 0.5421065539121628, "g_ap": 0.4619918614625931, "n_a": 4.55768808722496, "n_p": 2.8643375262618065,
     "tau_a": -0.3, "tau_p": -0.24825596250593662, "alpha": 44.35368996113539, "m": 0.5, "h_cut": 16.0, "e": "rule"}
CONDITIONS = {"delta_mm": 0.10, "mu": 0.3, "E_canc_MPa": 155.0, "load_N": lines.LOAD_N, "load_front_deg": 20.0,
              "load_sagit_deg": 18.0, "cycles": 2, "h_int_mm": 2.0}


def test_the_lame_press_fit_matches_the_closed_form(kernel, bone, abaqus, tmp_path):
    job = {"bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": {}, "job": str(tmp_path / "job-lame"),
           "point": {"name": "lame", "design": lines.LAME, "conditions": {}}}
    built = kernel(dict(job, mode="bench"), "bench")
    assert built["status"] == "built", built
    tools.solve(built, tmp_path / "job-lame")
    said = kernel(dict(job, mode="post"), "post")
    assert said["status"] == "ok", said
    labels = said["labels"]
    print(f"Lamé：解析解 {labels['p_lame_MPa']:.4f} MPa，反推 {labels['p_inferred_MPa']:.4f} MPa，差 {labels['err_pct']:+.2f}%")
    assert abs(labels["p_lame_MPa"] - lines.LAME_ANALYTIC_MPA) < 1e-3, "对照算例本身被改了"
    assert abs(labels["err_pct"]) <= 100 * lines.LAME_REL
    assert labels["open_frac"] == 0.0, "压配的界面应该处处贴着"


def test_design_a_matches_the_legacy_system(kernel, bone, tmp_path):
    old = tools.legacy_rows(lines.LEGACY_JOB)[0]
    where = tmp_path / "job-A"
    job = {"bone_model": str(bone), "bone_id": tools.BONE_ID, "settings": {}, "job": str(where),
           "point": {"name": "A", "design": A, "conditions": CONDITIONS}}
    solved = os.environ.get("STEMLAB_SCIENCE_JOB")
    if solved:                                          # 一个已经求解完的设计 A 的作业文件夹：抄过来，只做后处理
        shutil.copytree(Path(solved), where)
        pre = None
    elif os.environ.get("STEMLAB_SCIENCE_SLOW") == "1":
        if not tools.ABAQUS.is_file():
            pytest.skip(f"这台机器上找不到 Abaqus 的启动器（{tools.ABAQUS}）")
        built = kernel(dict(job, mode="build"), "build")
        assert built["status"] == "built", built
        pre = built["pre"]
        tools.solve(built, where)
    else:
        pytest.skip("设计 A 的整算要十几分钟：设 STEMLAB_SCIENCE_SLOW=1 才算，或者设 STEMLAB_SCIENCE_JOB 指向一个算完的作业文件夹")
    said = kernel(dict(job, mode="post"), "post")
    assert said["status"] == "ok", said
    labels = said["labels"]

    load = math.sqrt(sum(labels[f"load_{axis}_N"] ** 2 for axis in "xyz"))
    assert abs(load - lines.LOAD_N) <= lines.LOAD_REL * lines.LOAD_N, f"合力是 {load} N"
    assert labels["load_z_N"] < 0 and abs(labels["load_z_N"]) > 0.8 * load, "载荷主要沿骨的长轴往远端压"
    for step in ("load", "load2"):
        assert labels[f"iface_force_err_{step}"] <= lines.FORCE_BALANCE, f"{step}：界面力和外载差 {labels[f'iface_force_err_{step}']:.2e}"

    for name, limit in lines.VS_LEGACY_DEX.items():
        apart = abs(math.log10(labels[name] / float(old[name])))
        print(f"{name:18} 新 {labels[name]:.6g}  旧 {float(old[name]):.6g}  差 {apart:.4f} dex（线 {limit}）")
        assert apart <= limit, f"{name} 和旧系统差 {apart:.4f} dex"
    if pre is not None:
        for name, limit in lines.VS_LEGACY_REL.items():
            apart = abs(pre[name] - float(old[name])) / float(old[name])
            assert apart <= limit, f"{name} 和旧系统差 {apart:.2%}"
