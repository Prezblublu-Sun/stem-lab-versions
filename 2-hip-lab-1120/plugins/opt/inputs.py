"""【自由】读各样输入，核对它们对得上：同一个骨标识、同一版目标。

核的是“这几样东西能不能放在一起用”：
    候选池里只有一根骨
    填了数据：数据是这根骨的；目标里的列，数据里都有
    填了预测器：它的适用范围里有这根骨；它认的条件项就是选点设定里的那几项；目标里的列它都预测得了
    同一版目标：目标里的每一列，在各份数据和预测器里是同一个量——名字相同，单位也相同。
        目标换了一版（列换了定义、换了单位），旧的数据和预测器就对不上，这里拦下
写得对不对（目标和约束的格式、选点设定的格式）由冻结的代码核，不在这里。
"""
from __future__ import annotations

import json
from pathlib import Path

from stemlab import hooks


def _listed(folder) -> dict:
    return json.loads((Path(folder) / "manifest.json").read_bytes())


def candidates(handle) -> list[dict]:
    return hooks.read_points(handle.input("pool"))


def problems(handle) -> list[str]:
    rows = candidates(handle)
    bones = sorted({row["bone_id"] for row in rows})
    if len(bones) != 1:
        return [f"候选池里要正好一根骨，现在是 {bones}"]
    found, bone, units = [], bones[0], {}
    wanted = [goal["column"] for goal in handle.input("objective")["objectives"]]
    for number, (folder, info) in enumerate(zip(handle.input("data"), handle.input_info("data")), start=1):
        if info.bone_id not in (None, bone):
            found.append(f"第 {number} 份数据是 {info.bone_id} 的，候选池是 {bone} 的")
        known = {column["name"]: column["unit"] for column in _listed(folder)["columns"]}
        missing = [name for name in wanted if name not in known]
        if missing:
            found.append(f"目标里的这几列，第 {number} 份数据里没有：{missing}")
        for name in wanted:
            if name in known and units.setdefault(name, known[name]) != known[name]:
                found.append(f"目标里的 {name}，第 {number} 份数据里的单位是 {known[name]}，前面的是 {units[name]}：不是同一个量")
    if handle.input("predictor") is not None:
        scope = _listed(handle.input("predictor")).get("range") or {}
        if bone not in scope.get("bones", []):
            found.append(f"预测器的适用范围里没有这根骨（{bone}）：它认的是 {scope.get('bones')}")
        given = sorted(handle.input("defaults")["conditions"])
        if sorted(scope.get("conditions", {})) != given:
            found.append(f"预测器认的条件项是 {sorted(scope.get('conditions', {}))}，选点设定里写的是 {given}")
        able = {column["name"]: column["unit"] for column in _listed(handle.input("predictor")).get("columns") or []}
        cannot = [name for name in wanted if name not in able]
        if cannot:
            found.append(f"目标里的这几列，预测器预测不了：{cannot}（它预测的是 {sorted(able)}）")
        for name in wanted:
            if name in able and units.setdefault(name, able[name]) != able[name]:
                found.append(f"目标里的 {name}，预测器里的单位是 {able[name]}，数据里的是 {units[name]}：不是同一个量")
    return found
