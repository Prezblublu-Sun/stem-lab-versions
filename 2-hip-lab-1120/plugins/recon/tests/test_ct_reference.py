"""CT 重建对 2026-11 第二版流程当时留下的产物：同一根股骨（VSD z061 右），现在重建出来的和当时的是不是一回事。

要当时的数据集和产物，都只读；一遍大约两分钟。所以平时不跑，要用的时候单独跑：
    python -m pytest plugins/recon/tests/test_ct_reference.py -m science -s
数据不在、三个库加载不了，就跳过并说明原因。位置可以用环境变量改：
    STEMLAB_CT_CASE        数据集里这一例的文件夹（里面有 Models/Femur_R.ply 和各段 CT）
    STEMLAB_CT_REFERENCE   当时这一例的产物（outer.stl、inner.stl、metrics.json、fe/fe_result.json）

“是不是一回事”的容差，是照同一套库两次运行之间该有多稳定定的，不是物理上的线；要改由人改。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from plugins.recon import ct, solids

pytestmark = pytest.mark.science

CASE = Path(os.environ.get("STEMLAB_CT_CASE", r"H:\hip resource\02_VSDFullBody\z061"))
REFERENCE = Path(os.environ.get("STEMLAB_CT_REFERENCE", r"G:\projects\application\femur_ct_rebuild_2026-11-04\pilot_v2\vsd_z061_R"))


@pytest.fixture
def places():
    missing = [str(path) for path in (CASE / "Models" / "Femur_R.ply", REFERENCE / "metrics.json", REFERENCE / "fe" / "fe_result.json") if not path.is_file()]
    if missing:
        pytest.skip(f"当时的数据不在这台机器上：{missing}")
    try:
        import pymeshlab  # noqa: F401
        import SimpleITK  # noqa: F401

        ct.toolkit()
    except ImportError as error:
        pytest.skip(f"CT 重建要的库加载不了：{error}")
    return CASE, REFERENCE


def test_the_two_surfaces_are_the_ones_made_back_then(places, tmp_path):
    """第 1 到 15 步。"""
    case, reference = places
    scans = [path.relative_to(case).as_posix() for path in sorted(case.glob("*/*.nrrd")) if not path.name.lower().endswith(".seg.nrrd")]
    setting = {"side": "right", "source": {"outer": "Models/Femur_R.ply", "ct": scans}}
    assert ct.problems(case, setting) == []
    made = ct.run(case, setting, tmp_path / "surfaces")
    seen, old = made["measures"], json.loads((reference / "metrics.json").read_text(encoding="utf-8"))
    assert made["notes"] == []
    assert seen["ct_flip"] == old["ref_transform"] and seen["proximal_end"].replace("_", " ") == old["proximal_end"]
    assert seen["reference_groups"] == old["ref_regions"], "模型里混着的多余面片都认出来了"
    for mine, theirs in (("cortex_mask_mm3", "cortex_cm3"), ("interior_mask_mm3", "interior_cm3")):
        assert abs(seen[mine] / 1000 - old[theirs]) < 0.06, f"{mine}：现在 {seen[mine] / 1000:.2f} cm3，当时 {old[theirs]}"
    for mine, theirs in (("wall_fine_min_mm", "thick_min"), ("wall_fine_p05_mm", "thick_p05"), ("wall_fine_median_mm", "thick_med")):
        assert abs(seen[mine] - old[theirs]) < 0.02, f"{mine}：现在 {seen[mine]:.3f}，当时 {old[theirs]}"
    assert abs(seen["isthmus_canal_diameter_mm"] - old["isthmus_canal_d_mm"]) < 0.1
    for name in ("outer", "inner"):
        now, before = solids.read_stl(made[name]), solids.read_stl(reference / f"{name}.stl")
        volume = abs(solids.signed_volume(*before))
        assert abs(abs(solids.signed_volume(*now)) - volume) < 1e-3 * volume, f"{name} 围出的体积"
        apart = max(float(solids.distance(now[0], *before).max()), float(solids.distance(before[0], *now).max()))
        same = Path(made[name]).read_bytes()[84:] == (reference / f"{name}.stl").read_bytes()[84:]
        print(f"{name}：两边互相最远 {apart:.4f} mm；文件内容{'逐字节相同' if same else '不逐字节相同'}")
        assert apart < 0.05, f"{name} 和当时的表面最远差 {apart:.3f} mm"


def test_remeshing_and_tets_match_what_was_recorded(places, tmp_path):
    """第 16、17 步：拿当时的两个细表面重划、试划四面体，和当时记下的数比。"""
    _, reference = places
    old = json.loads((reference / "fe" / "fe_result.json").read_text(encoding="utf-8"))
    setting = {"ct": {"edge_mm": float(old["h"])}}
    solid = solids.from_surfaces(reference / "outer.stl", reference / "inner.stl", tmp_path / "solids", setting)
    seen = solid["measures"]
    assert seen["surfaces_open_edges"] == 0
    for name in ("outer", "inner"):
        print(f"{name}：三角形 {seen[f'{name}_triangles']}（当时 {old[name]['tris']}），重划偏差 95% 分位 "
              f"{seen[f'{name}_remesh_deviation_p95_mm']:.3f} mm（当时 {old[name]['dev_p95']}），体积 {seen[f'{name}_volume_mm3'] / 1000:.1f} cm3（当时 {old[name]['vol_cm3']}）")
        assert abs(seen[f"{name}_triangles"] - old[name]["tris"]) <= 0.02 * old[name]["tris"]
        assert abs(seen[f"{name}_remesh_deviation_p95_mm"] - old[name]["dev_p95"]) < 0.03
        assert abs(seen[f"{name}_volume_mm3"] / 1000 - old[name]["vol_cm3"]) < 0.005 * old[name]["vol_cm3"]
    back = solids.surfaces_of(solid["files"])
    assert back is not None, "写出来的两个实体读得回外表面和内壁"
    thick = solids.wall(back)
    tets = solids.tet_check(back, float(old["h"]))
    print(f"壁厚最小 {thick['wall_min_mm']:.2f} mm（当时 {old['min_gap_mm']}）；四面体 {tets['tet_count_cortical']} + {tets['tet_count_cancellous']}"
          f"（当时 {old['tets']['cortex']} + {old['tets']['cancellous']}），最差 gamma {tets['tet_gamma_min']:.4f}（当时 {old['gamma_min']}）")
    assert abs(thick["wall_min_mm"] - old["min_gap_mm"]) < 0.1
    assert tets["tet_inverted"] == 0 and tets["tet_gamma_min"] >= 0.1
    assert abs(tets["tet_count"] - old["tets_total"]) <= 0.03 * old["tets_total"]
