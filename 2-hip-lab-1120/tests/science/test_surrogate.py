"""代理的科学验收：留出误差多大算可用。线写在 lines.py，训练之前就写进训练设定（存定的输入），报告里由代码逐条判。

拿旧数据库 v0.14 的结果（照 external/legacy_data_v014 转成本系统的数据）训练一次，看留出误差落在哪一档。
这条测试守的是“线在结果出来之前登记、报告里逐条有判定”；误差本身过不过线是给你看的结论，打印出来，不在这里替你签。
"""
from __future__ import annotations

import importlib.util
import json

import pytest

from stemlab.desk.core import start
from stemlab.experiments import view
from stemlab.registry import register
from tests import helpers, real
from tests.science import lines, tools

pytestmark = pytest.mark.science
TARGETS = ["rot_first_deg", "f1_p95_um"]


def _converter():
    spec = importlib.util.spec_from_file_location("legacy_data_v014", helpers.REPO / "external" / "legacy_data_v014" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tier(rmse: float) -> str:
    line = lines.SURROGATE
    return "好" if rmse <= line["rmse_good"] else "能用，下结论要拿 FE 复核" if rmse <= line["rmse_usable"] else \
        "介于能用和不能用之间" if rmse <= line["rmse_unusable"] else "不能用"


def test_hold_out_error_on_the_legacy_database(package, real_lab, data, tmp_path):
    if not tools.LEGACY_DB.is_file():
        pytest.skip(f"找不到旧数据库（{tools.LEGACY_DB}）。换地方了就设 STEMLAB_LEGACY_DB")
    counts = _converter().convert(tools.LEGACY_DB, package, tmp_path / "legacy-data")
    print(json.dumps(counts, ensure_ascii=False))
    item = register.register_external("data", "legacy-v014", source=tmp_path / "legacy-data", note="旧数据库 v0.14 转来的", by="tester",
                                      bone_id=tools.BONE_ID, new_bone=True)
    line = lines.SURROGATE
    accepted = [{"id": f"usable_{name}", "what": f"{name} 的留出误差不超过 {line['rmse_usable']} dex", "target": name, "on": "holdout",
                 "metric": "rmse", "op": "<=", "limit": line["rmse_usable"]} for name in TARGETS]
    accepted += [{"id": f"covered_{name}", "what": "名义 95% 的区间，实际覆盖率不低于下限", "target": name, "on": "holdout",
                  "metric": "coverage", "op": ">=", "limit": line["coverage"][0]} for name in TARGETS]
    made = real.train([item], real.setting({"targets": TARGETS, "seed": 20261113, "level": 0.95, "scale": dict.fromkeys(TARGETS, "log10"),
                                            "acceptance": accepted}),
                      real.setting({"by": "row", "fraction": 0.2, "seed": 20261113}))
    assert start.start(made).ok
    real.run(made, seconds=1800)
    status = view.view(made)
    assert real.tasks(made) == {"train": ("done", "trained")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    report = json.loads((real.output(made, "report") / "report.json").read_bytes())

    assert report["training"]["setting_registered"] <= report["training"]["round_opened"], "线登记在这一轮开始之前"
    assert [row["id"] for row in report["verdicts"]] == [row["id"] for row in accepted]
    assert all(row["passed"] in (True, False) for row in report["verdicts"]), "每条线都判得出来"
    print(f"训练 {report['split']['rows']['train']} 行，留出 {report['split']['rows']['holdout']} 行，模型 {report['training']['model']['model']}")
    for name in TARGETS:
        found = report["holdout"][name]
        print(f"{name:16} 留出 rmse {found['rmse']:.4f} dex  R2 {found['r2']:.3f}  覆盖率 {found['coverage']:.3f}  → {_tier(found['rmse'])}")
        assert found["n"] > 100 and found["scale"] == "log10"
    for row in report["verdicts"]:
        print(f"线 {row['id']}：{row['value']:.4f} {row['op']} {row['limit']} → {'过' if row['passed'] else '没过'}")
