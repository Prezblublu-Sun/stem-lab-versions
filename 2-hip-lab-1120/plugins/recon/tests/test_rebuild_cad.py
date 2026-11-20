"""CAD 骨源经 rebuild.draft、rebuild.finalize 直接走一遍：自动找的标志点、量出来的数和真值比。

5c 以前这几条断言在固定的验收里（tests/plugins/recon_cases.py），经核心和插件跑。5c 起骨架叫的是重建方法包，验收改走假的方法包，
插件里干活的这一头不再经核心跑，这几条就搬到这里直接试它。5d 把 CAD 这条路搬进 CAD 方法包时，跟着搬过去。
骨源是 tests/real.py 里现造的一根 CAD 假股骨（真值是 real.TRUTH）。要 gmsh。插件的测试只用插件自己的代码，不 import 契约。
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from plugins.recon import landmarks, rebuild
from tests import real

NAMES = ("cortical", "cancellous")
SETTING = {"side": "right", "source": {"cortical": "cortical.step", "cancellous": "cancellous.step"}, "tessellation_mm": 4.0}


def test_the_made_femur_is_rebuilt_where_it_is_and_an_edit_is_measured(tmp_path):
    source = real.cad_femur(tmp_path / "source")
    result = rebuild.draft({"setting": SETTING, "source": str(source), "out": str(tmp_path / "draft-out")}, lambda name: None)
    assert result["status"] == "ok", result
    for name in NAMES:
        assert Path(result["solids"][name]).read_bytes() == (source / f"{name}.step").read_bytes(), "CAD 的实体原样用，一个字节不动"
    marks = {name: point["xyz"] for name, point in result["landmarks"].items()}
    assert set(marks) == set(landmarks.DEFINITIONS) and all(point["definition"].strip() for point in result["landmarks"].values())
    assert math.dist(marks["head_center"], real.TRUTH["head_center"]) < 0.5
    assert math.dist(marks["neck_center"], real.TRUTH["neck_center"]) < 1.0
    assert math.dist(marks["lesser_trochanter"], real.TRUTH["lesser_trochanter"]) < 3.0
    measures = result["measures"]
    assert abs(measures["neck_shaft_angle_deg"] - real.TRUTH["neck_shaft_angle"]) < 1.0
    shaft = [p - d for p, d in zip(marks["shaft_proximal"], marks["shaft_distal"])]
    assert sum(a * b for a, b in zip(shaft, real.TRUTH["shaft_axis"])) / math.hypot(*shaft) > math.cos(math.radians(1.0))
    assert measures["cortical_watertight"] is True and measures["cancellous_watertight"] is True
    assert measures["head_fit_rms_mm"] < 1.0 and 3.0 < measures["neck_wall_min_mm"] < 5.0, "颈最细处皮质壳造的是 4 mm 厚"
    assert {row["item"] for row in result["todo"]} >= set(landmarks.DEFINITIONS)

    draft = tmp_path / "draft"                          # 5c 以前骨架写的那种候选（第 1 版的写法），定稿那一头读的就是它
    (draft / "solids").mkdir(parents=True)
    for name in NAMES:
        shutil.copyfile(result["solids"][name], draft / "solids" / f"{name}.step")
    (draft / "manifest.json").write_text(json.dumps({
        "solids": {name: {"file": f"solids/{name}.step"} for name in NAMES}, "landmarks": result["landmarks"],
        "history": result["history"], "measures": result["measures"]}), encoding="utf-8")
    head = marks["head_center"]
    edits = tmp_path / "edits"
    edits.mkdir()
    (edits / "edits.json").write_text(json.dumps({"by": "wei", "landmarks": {"head_center": {
        "xyz": [head[0] + 0.6, head[1], head[2] + 0.8], "why": "往外挪 1 mm"}}}), encoding="utf-8")
    final = rebuild.finalize({"setting": SETTING, "draft": str(draft), "edits": str(edits), "out": str(tmp_path / "final-out")},
                             lambda name: None)
    assert final["status"] == "ok", final
    assert abs(final["measures"]["landmark_shift_max_mm"] - 1.0) < 0.05, "定稿的标志点离自动找的差多少"
    assert final["measures"]["cortical_volume_change"] < 0.005 and any("wei" in step["what"] for step in final["history"])
