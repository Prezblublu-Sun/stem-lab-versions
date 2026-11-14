"""【冻结】检查门：网格检查；填了内核就经 run_kernel 做一次建模冒烟。过不过的线从重建设定里读，不写在代码里。

重建设定的 gate 是一张表，一行一条线：
    {"name": "volume_cortical", "value": "cortical_volume_change", "max": 0.005, "what": "皮质实体的体积和骨源相差不超过 0.5%"}
    name    这一项检查叫什么（写进骨模型的检查结果）
    value   拿量出来的哪个数来比（自由代码量出来交上来的那些数里的一个；内核冒烟的结果叫 kernel_smoke）
    min、max、equals   线：不小于、不大于、正好等于。至少写一样
    what    这条线是什么意思、从哪来的，给人看

量出来的数里没有这一项，这一条就是没过：如实不过，不当它不存在。
内核冒烟：把刚定稿的骨模型交给内核，让它在这根骨上真的建一次模（或者只模板化，由重建设定的 smoke 说）。
旧系统的经验是，导针孔、盲窝、开放的皮质壳这类问题，标志点核对发现不了，要到建模时才暴露。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from stemlab import hooks

SMOKE = "kernel_smoke"
BOUNDS = ("min", "max", "equals")
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")           # 检查的名字要写进骨模型的检查结果，写法和那边要的一样


def problems(setting) -> list[str]:
    """重建设定里的检查门写得对不对。"""
    lines = setting.get("gate") if isinstance(setting, dict) else None
    if not isinstance(lines, list) or not lines:
        return ["重建设定要带 gate：检查门的各条线，至少一条"]
    found, names = [], []
    for number, line in enumerate(lines, start=1):
        title = f"检查门的第 {number} 条"
        if not isinstance(line, dict) or not isinstance(line.get("name"), str) or not isinstance(line.get("value"), str):
            found.append(f"{title}要写 name 和 value")
            continue
        if not NAME.fullmatch(line["name"]):
            found.append(f"{title}的 name 要用小写字母、数字和下划线：{line['name']!r}")
        names.append(line["name"])
        if not any(bound in line for bound in BOUNDS):
            found.append(f"{title}（{line['name']}）没有线：min、max、equals 至少写一样")
        if any(isinstance(line.get(bound), bool) or not isinstance(line.get(bound, 0), (int, float)) for bound in ("min", "max")):
            found.append(f"{title}（{line['name']}）的 min、max 必须是数")
    if len(set(names)) != len(names):
        found.append("检查门里有重名的检查")
    smoke = setting.get("smoke")
    if smoke is not None and (not isinstance(smoke, dict) or smoke.get("mode") not in ("template", "build")
                              or not isinstance(smoke.get("design"), dict)):
        found.append('重建设定的 smoke 要写成 {"mode": "template" 或 "build", "design": {...}, "conditions": {...}}')
    return found


def wants_smoke(setting: dict) -> bool:
    return any(line.get("value") == SMOKE for line in setting["gate"])


def checks(measured: dict, lines: list) -> list[dict]:
    """逐条比。返回骨模型格式里的检查结果：name、value、limit、passed。"""
    results = []
    for line in lines:
        value = measured.get(line["value"])
        limit = {bound: line[bound] for bound in BOUNDS if bound in line}
        if value is None:
            passed = False
        elif "equals" in line:
            passed = value == line["equals"]
        else:
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            passed = number and ("min" not in line or value >= line["min"]) and ("max" not in line or value <= line["max"])
        results.append({"name": line["name"], "value": value, "limit": dict(limit, what=line.get("what", "")), "passed": bool(passed)})
    return results


def passed(results: list) -> bool:
    return bool(results) and all(row["passed"] is True for row in results)


# ---------------------------------------------------------------- 内核冒烟

def _state(handle) -> Path:
    return handle.work_dir / "gate" / f"smoke-r{handle.round.number}.json"


def smoke(handle, candidate: Path, setting: dict):
    """让内核在这根骨上建一次模。还没跑完返回 None；跑完返回 {"ok", "reason"}。可以重复叫。"""
    state_file = _state(handle)
    how = setting["smoke"]
    kernel = handle.input_info("kernel")
    out = state_file.parent / f"smoke-out-r{handle.round.number}"
    if not state_file.exists():
        ask = state_file.parent / f"smoke-ask-r{handle.round.number}"
        ask.mkdir(parents=True, exist_ok=True)
        point = {"name": "smoke", "design": how["design"], "conditions": how.get("conditions") or {}}
        job = {"mode": how["mode"], "bone_model": str(candidate), "bone_id": json.loads((candidate / "manifest.json").read_bytes())["bone_id"],
               "settings": how.get("settings") or {}, "point": point, "designs": [{"name": "smoke", "design": how["design"]}],
               "conditions": how.get("conditions") or {}, "job": str(state_file.parent / f"smoke-job-r{handle.round.number}")}
        (ask / "job.json").write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
        process = hooks.run_kernel(kernel.id, ask, out, wait=False)
        state_file.write_bytes(json.dumps({"process": process}).encode("utf-8"))
        return None
    process = json.loads(state_file.read_bytes())["process"]
    if hooks.alive(process):
        return None
    try:
        result = json.loads((out / "result.json").read_bytes())
    except (OSError, ValueError):
        return {"ok": False, "reason": "内核没有留下结果：它自己出错了，看 gate/ 下的 log.txt"}
    if how["mode"] == "build":
        return {"ok": result.get("status") == "built", "reason": str(result.get("reason") or result.get("status"))}
    rows = result.get("designs") or []
    fits = bool(rows) and rows[0].get("feasible") is True
    return {"ok": fits, "reason": "" if fits else str((rows[0].get("info") or {}).get("reason") if rows else result.get("reason"))}
