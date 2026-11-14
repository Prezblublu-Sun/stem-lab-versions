"""【冻结】recon.draft、recon.finalize 两个类型：一根骨从骨源到过了检查门的骨模型，每处人工改动都留痕。

人工检查放在两个实验之间：recon.draft 出候选；你在系统外看和改，把修改登记进来；recon.finalize 定稿。
输入表、产物表、结局表写死在这里，两个类型的动作骨架也在这里。自由代码只管怎么重建、怎么找标志点；
写成什么格式（model.py）、过不过检查门（gate.py）都走冻结的文件，自由代码绕不过去。

自由代码要给的这几样，接口不变就可以整个重写：
    rebuild.check(handle, mode) -> 原因或 None     启动前的检查。mode 是 draft 或 finalize
    rebuild.begin(handle, mode)                     一轮开头：把重建的活派出去（脱离出去的进程）
    rebuild.advance(handle, mode) -> {"stage", "result"}
                                                    看活干到哪了。干完了 result 不是 None：
                                                    {"status": ok / error / env, "reason", "solids": {cortical, cancellous: 文件},
                                                     "landmarks", "measures", "history", "todo", "timings"}
    rebuild.halt(handle, mode)                      把在跑的停掉
"""
from plugins.recon import charts, gate, model, rebuild
from stemlab.hooks import Chart, Input, Kind, Outcome, Output

OPEN = ("queued", "running")
DRAFT, FINAL = "rebuild", "finalize"                 # 两个类型各自那一个任务的名字


def _mine(handle, task: str):
    """这一轮里这个任务现在的样子；这一轮还没报过它就是 None。"""
    found = handle.tasks().get(task)
    return found if found is not None and found.round == handle.round.number else None


def _begin(handle, mode: str, task: str) -> None:
    if task in handle.round.rerun or task not in handle.tasks():
        rebuild.begin(handle, mode)
        handle.task(task, "queued")
    else:                                               # 上一轮重建出错（待查），这次启动又没点名：没有活可干，照实说
        handle.fail("这一轮没有要重排的任务：上一轮的重建出错属于待查，查过之后点名才重排")


def _report_stage(handle, task: str, view: dict) -> None:
    mine = _mine(handle, task)
    if mine is not None and (mine.state, mine.stage) != ("running", view["stage"]):
        handle.task(task, "running", stage=view["stage"], machine=view.get("machine"))


def _failed(handle, task: str, result: dict) -> None:
    """重建自己没做成：环境的事可重试，别的待查。"""
    name = "env" if result.get("status") == "env" else "failed"
    handle.problem(f"{'环境问题' if name == 'env' else '重建出错'}：{result.get('reason') or '没有说原因'}", task=task)
    handle.task(task, "failed", outcome=name)
    handle.fail(f"重建没有做成：{result.get('reason') or name}")


def _made(handle, task: str, write):
    """按格式写出来。自由代码交上来的结果写不成格式：如实记成重建出错，这一轮失败；不带病往下走，也不让同一个报错一遍遍重来。"""
    try:
        return write()
    except (KeyError, TypeError, ValueError, OSError) as error:
        _failed(handle, task, {"status": "error", "reason": f"重建交上来的结果写不成骨模型的格式：{type(error).__name__}: {error}"})
        return None


def _handed(handle, task: str, name: str, folder) -> bool:
    """交一样产物。核心没收（原因它已经记成问题了）：这一轮如实记成失败，不能结局写着做成了、东西却不在。"""
    if handle.output(name, folder) is not None:
        return True
    _failed(handle, task, {"status": "error", "reason": f"{name} 没有交上去，原因见记下的问题"})
    return False


def _show(handle, name: str, body: dict) -> None:
    """给图表留一份：产物交上去之后就不在 work/ 里了。"""
    shown = handle.work_dir / "shown" / f"r{handle.round.number}"
    shown.mkdir(parents=True, exist_ok=True)
    (shown / f"{name}.json").write_bytes(model.dumps(body))


def _stop(mode: str, task: str):
    def stop(handle):
        rebuild.halt(handle, mode)
        mine = _mine(handle, task)
        if mine is not None and mine.state in OPEN:
            handle.task(task, "stopped")
    return stop


# ---------------------------------------------------------------- recon.draft

def draft_check(handle):
    setting = handle.input("setting")
    found = model.setting_problems(setting) + gate.problems(setting)
    return "；".join(found) if found else rebuild.check(handle, "draft")


def draft_start(handle):
    _begin(handle, "draft", DRAFT)


def draft_poll(handle):
    mine = _mine(handle, DRAFT)
    if mine is None or mine.state not in OPEN:
        return
    view = rebuild.advance(handle, "draft")
    result = view.get("result")
    if result is None:
        _report_stage(handle, DRAFT, view)
        return
    if result.get("status") != "ok":
        _failed(handle, DRAFT, result)
        return
    setting, bone_id = handle.input("setting"), handle.input_info("source").bone_id
    out = handle.work_dir / "out" / f"r{handle.round.number}"
    pending = [{"name": line["name"], "value": None, "limit": {"what": line.get("what", "")}, "passed": None} for line in setting["gate"]]
    draft = _made(handle, DRAFT, lambda: model.write(
        out / "draft", "bone_draft", bone_id=bone_id, setting=setting, solids=result["solids"], landmarks=result["landmarks"],
        history=result["history"], checks=pending, measures=result["measures"]))
    if draft is None or not _handed(handle, DRAFT, "draft", draft):
        return
    body = {"todo": result.get("todo") or [], "measures": result["measures"], "timings": result.get("timings") or {}}
    _show(handle, "rebuilt", dict(body, neck_loop=result.get("neck_loop") or [], mesh_quality=result.get("mesh_quality") or {}))
    handle.output("todo", model.write_report(out / "todo", "todo", body, bone_id))
    handle.task(DRAFT, "done", outcome="rebuilt", machine=view.get("machine"))
    handle.finish()


# ---------------------------------------------------------------- recon.finalize

def final_check(handle):
    setting = handle.input("setting")
    found = model.setting_problems(setting) + gate.problems(setting)
    if not found and gate.wants_smoke(setting):
        if handle.input("kernel") is None:
            found.append("检查门里有内核冒烟（kernel_smoke），但没有填内核")
        elif not isinstance(setting.get("smoke"), dict):
            found.append("检查门里有内核冒烟，重建设定里要写 smoke：让内核拿哪个设计试")
    return "；".join(found) if found else rebuild.check(handle, "finalize")


def final_start(handle):
    _begin(handle, "finalize", FINAL)


def final_poll(handle):
    mine = _mine(handle, FINAL)
    if mine is None or mine.state not in OPEN:
        return
    view = rebuild.advance(handle, "finalize")
    result = view.get("result")
    if result is None:
        _report_stage(handle, FINAL, view)
        return
    if result.get("status") != "ok":
        _failed(handle, FINAL, result)
        return
    setting, bone_id = handle.input("setting"), handle.input_info("draft").bone_id
    out = handle.work_dir / "out" / f"r{handle.round.number}"
    measured = dict(result.get("measures") or {})
    if gate.wants_smoke(setting):                       # 先按格式写出一份候选，交给内核真的建一次模
        candidate = out / "candidate"
        if not candidate.exists() and _made(handle, FINAL, lambda: model.write(
                candidate, "bone_draft", bone_id=bone_id, setting=setting, solids=result["solids"], landmarks=result["landmarks"],
                history=result["history"], checks=[], measures=measured)) is None:
            return
        said = gate.smoke(handle, candidate, setting)
        if said is None:
            _report_stage(handle, FINAL, {"stage": "smoke", "machine": view.get("machine")})
            return
        measured[gate.SMOKE] = said["ok"]
        measured["kernel_smoke_reason"] = said["reason"]
    results = gate.checks(measured, setting["gate"])
    body = {"passed": gate.passed(results), "checks": results, "measures": measured, "history": result.get("history") or []}
    if gate.passed(results):
        final = _made(handle, FINAL, lambda: model.write(
            out / "model", "bone_model", bone_id=bone_id, setting=setting, solids=result["solids"], landmarks=result["landmarks"],
            history=result["history"], checks=results, measures=measured))
        if final is None or not _handed(handle, FINAL, "model", final):
            return
    _show(handle, "gate", body)
    _show(handle, "rebuilt", {"todo": [], "measures": measured, "timings": result.get("timings") or {}, "neck_loop": [],
                              "mesh_quality": result.get("mesh_quality") or {}})
    handle.output("gate", model.write_report(out / "gate", "gate", body, bone_id))
    handle.task(FINAL, "done", outcome="passed" if gate.passed(results) else "gate_failed", machine=view.get("machine"))
    handle.finish()


KINDS = [
    Kind(
        name="recon.draft",
        label="重建：从骨源出候选骨模型",
        inputs=(Input("source", ("bone_source",), label="骨源"), Input("setting", ("setting",), label="重建设定")),
        outputs=(Output("draft", "bone_draft", "候选骨模型"), Output("todo", "report", "待检查清单")),
        outcomes=(Outcome("rebuilt", "ok", "重建完"), Outcome("failed", "unclear", "重建出错"), Outcome("env", "retryable", "环境问题")),
        check=draft_check, start=draft_start, poll=draft_poll, stop=_stop("draft", DRAFT),
        charts=(Chart("steps", "bar", "各步用时"), Chart("mesh", "bar", "网格质量分布"), Chart("measures", "table", "量出来的数"),
                Chart("todo", "table", "待检查清单"), Chart("neck", "scatter", "股骨颈最细的截面")),
        chart=charts.chart,
    ),
    Kind(
        name="recon.finalize",
        label="重建：候选骨模型过检查门，定稿成骨模型",
        inputs=(Input("draft", ("bone_draft",), label="候选骨模型"), Input("setting", ("setting",), label="重建设定"),
                Input("edits", ("edits",), required=False, label="人工修改"),
                Input("kernel", ("kernel",), required=False, label="内核（做建模冒烟）")),
        outputs=(Output("model", "bone_model", "骨模型"), Output("gate", "report", "检查结果")),
        outcomes=(Outcome("passed", "ok", "过了检查门"), Outcome("gate_failed", "conclusion", "没过检查门"),
                  Outcome("failed", "unclear", "重建出错"), Outcome("env", "retryable", "环境问题")),
        check=final_check, start=final_start, poll=final_poll, stop=_stop("finalize", FINAL),
        charts=(Chart("steps", "bar", "各步用时"), Chart("mesh", "bar", "网格质量分布"), Chart("measures", "table", "量出来的数"),
                Chart("checks", "table", "检查结果")),
        chart=charts.chart,
    ),
]
