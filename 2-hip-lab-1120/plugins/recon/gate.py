"""【冻结】检查门：照检查门的设定逐条比；检查门里有冒烟，就让柄空间包在定稿的骨上模板化一个设计。线不写在代码里。

检查门是登记的一份设定（5c 起和重建设定分开），写法照旧：一张表，一行一条线：
    {"gate": [{"name": "volume_cortical", "value": "cortical_volume_change", "max": 0.005, "what": "皮质实体的体积和骨源相差不超过 0.5%"}],
     "smoke": {"design": {...}, "placement": {...}}}
    name    这一项检查叫什么（写进骨模型的检查结果）
    value   拿量出来的哪个数来比。只能是重建方法包清单 outputs 里的（它答应会量的），或骨架自己记的：
            冒烟的结果 stem_smoke 和原因 stem_smoke_reason，完整的股骨照后髁连线量出的前倾角 anteversion_deg（model.py）
    min、max、equals   线：不小于、不大于、正好等于。至少写一样
    what    这条线是什么意思、从哪来的，给人看
    smoke   有一条拿 stem_smoke 来比才用得上：design 是让柄空间包试的那个设计（照它的 design 声明写全）；
            placement 是放置设定里写了每个点给的那几项，没有就不写

量出来的数里没有这一项，这一条就是没过：如实不过，不当它不存在。
冒烟：把定稿的骨照第 2 版写成一份候选，交给柄空间包的 template，job 照包的约定带 bone_model（文件夹）和 bone（读成现在这一版的清单）。
给出了这个设计、能放进去，过；放不进去，不过；包没给出这个设计（不收这根骨，或者自己出错了），也不过，两种原因分开说。
旧系统的经验是，导针孔、盲窝、开放的皮质壳这类问题，标志点核对发现不了，要到放柄时才暴露。原来还能让内核真建一次模，5c 起不做了。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from stemlab import hooks

SMOKE, SMOKE_REASON = "stem_smoke", "stem_smoke_reason"
BOUNDS = ("min", "max", "equals")
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")           # 检查的名字要写进骨模型的检查结果，写法和那边要的一样


def problems(setting, promised) -> list[str]:
    """检查门的设定写得对不对。promised 是拿得来比的量：方法包答应会量的，加上骨架自己记的。"""
    lines = setting.get("gate") if isinstance(setting, dict) else None
    if not isinstance(lines, list) or not lines:
        return ["检查门的设定要带 gate：各条线，至少一条"]
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
        if line["value"] not in promised:
            found.append(f"{title}（{line['name']}）拿 {line['value']} 来比：重建方法包的清单里没说会量它（outputs），骨架也不记它")
    if len(set(names)) != len(names):
        found.append("检查门里有重名的检查")
    smoke = setting.get("smoke")
    if smoke is not None and (not isinstance(smoke, dict) or not set(smoke) <= {"design", "placement"} or not isinstance(smoke.get("design"), dict)
                              or not isinstance(smoke.get("placement", {}), dict)):
        found.append('检查门的 smoke 要写成 {"design": {让柄空间包试的设计}, "placement": {放置设定里每个点给的项}}，placement 没有就不写')
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


# ---------------------------------------------------------------- 冒烟

def _state(handle) -> Path:
    return handle.work_dir / "gate" / f"smoke-r{handle.round.number}.json"


def smoke(handle, candidate: Path, setting: dict):
    """让柄空间包在这根骨上模板化 smoke 里的那个设计。还没跑完返回 None；跑完返回 {"ok", "reason"}。可以重复叫。"""
    state_file = _state(handle)
    how = setting["smoke"]
    out = state_file.parent / f"smoke-out-r{handle.round.number}"
    if not state_file.exists():
        ask = state_file.parent / f"smoke-ask-r{handle.round.number}"
        ask.mkdir(parents=True, exist_ok=True)
        bone = hooks.read_bone_model(candidate)
        job = {"mode": "template", "bone_model": str(candidate), "bone": bone, "bone_id": bone["bone_id"],
               "designs": [{"name": "smoke", "design": how["design"]}],
               "settings": hooks.merged(handle.input("placement"), how.get("placement") or {})}
        (ask / "job.json").write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
        process = hooks.run_stem(handle.input_info("stem").id, ask, out, wait=False)
        state_file.write_bytes(json.dumps({"process": process}).encode("utf-8"))
        return None
    process = json.loads(state_file.read_bytes())["process"]
    if hooks.alive(process):
        return None
    try:
        result = json.loads((out / "result.json").read_bytes())
    except (OSError, ValueError):
        return {"ok": False, "reason": "柄空间包没能在这根骨上模板化：它没有留下结果，看 gate/ 下的 log.txt"}
    rows = [row for row in (result.get("designs") or []) if isinstance(row, dict) and row.get("name") == "smoke"] \
        if isinstance(result, dict) else []
    if not rows:
        said = result.get("reason") if isinstance(result, dict) else None
        return {"ok": False, "reason": f"柄空间包没能在这根骨上模板化：{said or '它没有给出这个设计'}"}
    if rows[0].get("feasible") is True:
        return {"ok": True, "reason": ""}
    info = rows[0].get("info")
    return {"ok": False, "reason": f"放不进去：{(info.get('reason') if isinstance(info, dict) else None) or '柄空间包没说为什么'}"}
