"""【冻结】recon.draft、recon.finalize 两个类型：一根骨从骨源到过了检查门的骨模型，每处人工改动都留痕。

人工检查放在两个实验之间：recon.draft 出候选；你在系统外看和改，把修改登记进来；recon.finalize 定稿。
5c 起活由重建方法包干（约定见 contract/formats/package.py 的“重建方法”）：这里拼好交给它的 job（_ask），它交回骨模型的几段
和量出来的数，这里照第 2 版写（model.py）、过检查门（gate.py）。输入表、产物表、结局表写死在这里，两个类型的动作骨架也在这里。

启动前核的（_problems）：
    方法包      会这一种（modes 里有 draft 或 finalize）；outputs 是它会量出的数，role 都是 label，不用骨架自己记的三个名字（RESERVED）；
                kept（定稿时重做不了的量）只写 outputs 里的
    重建设定    照声明写，照的是这个方法包的 rebuild；没有每个点给的项（重建没有一批点）。取值由核心照声明核过
    检查门      写法照旧（gate.py）；拿来比的量是方法包答应会量的，或骨架自己记的
    定稿另核    候选记着是哪个方法包出的，就要是那一个。检查门里有冒烟：要填会 template 的柄空间包，和照它的 placement 声明写的放置设定；
                smoke 里的设计照它的 design 声明写全，放置设定里每个点给的项给齐；候选合这个柄空间包清单里对骨模型的要求（inputs 的 bone）。
                没有冒烟，这两样都不该填
方法包交回来以后：量出来的数是它量的，加上定稿沿用候选的（只许它清单 kept 里的，它点名，值从候选里抄），加上骨架自己量的（model.measured）。

自由代码要给的这几样，接口不变就可以整个重写：
    rebuild.check(handle, mode) -> 原因或 None     启动前自由的那部分检查（冻结的这几条过了才叫）。mode 是 draft 或 finalize
    rebuild.begin(handle, mode, job)               一轮开头：把这里拼好的 job 交给方法包（hooks.run_recon，脱离出去的进程）
    rebuild.advance(handle, mode) -> {"stage", "machine", "result"}
                                                    看方法包干到哪了。干完了 result 是它交回来的 result.json；没留下读得出的结果，
                                                    照实写成 {"status": "error" 或 "env", "reason"}
    rebuild.halt(handle, mode)                      把在跑的停掉
"""
from plugins.recon import charts, gate, model, rebuild
from stemlab import hooks
from stemlab.hooks import Chart, Input, Kind, Outcome, Output

OPEN = ("queued", "running")
DRAFT, FINAL = "rebuild", "finalize"                 # 两个类型各自那一个任务的名字
MODES = {"draft": "出候选", "finalize": "定稿"}       # 方法包会做的事
REBUILD = "rebuild"                                  # 方法包声明的重建设定叫这个（契约 package.py 的 DECLARED）
RESERVED = (gate.SMOKE, gate.SMOKE_REASON, model.ANTEVERSION)      # 骨架自己记的量：方法包的 outputs 里不能有


def _mine(handle, task: str):
    """这一轮里这个任务现在的样子；这一轮还没报过它就是 None。"""
    found = handle.tasks().get(task)
    return found if found is not None and found.round == handle.round.number else None


# ---------------------------------------------------------------- 启动前

def _method_problems(handle, mode: str) -> tuple:
    """方法包能不能干这一种、清单写清楚了没有。另返回检查门拿得来比的量：它答应会量的，加上骨架自己记的。"""
    listed = model.read(handle.input("method"))
    found = [] if mode in (listed.get("modes") or []) else [f"这个重建方法包不会 {mode}（{MODES[mode]}）"]
    outputs = listed.get("outputs") if isinstance(listed.get("outputs"), list) else []
    names = {column.get("name") for column in outputs if isinstance(column, dict)}
    if any(not isinstance(column, dict) or column.get("role") != "label" for column in outputs):
        found.append("重建方法包的 outputs 是它会量出的数，role 都写 label")
    taken = sorted(name for name in RESERVED if name in names)
    if taken:
        found.append(f"重建方法包的 outputs 里不能有 {taken}：这几个名字是骨架自己记的")
    kept = listed.get("kept", [])
    if not isinstance(kept, list) or not all(isinstance(name, str) for name in kept) or not set(kept) <= names:
        found.append(f"重建方法包清单的 kept（定稿时重做不了的量）只能写 outputs 里的名字：{kept!r}")
    return found, {name for name in names if isinstance(name, str)} | set(RESERVED)


def _declared_problems(value, label: str, of: str, name: str) -> list[str]:
    """一份设定是不是照 of 的 name 那份声明写的。取值合不合声明，核心启动时已经核过。"""
    if value is None:
        return [f"{label}要填：照 {of} 的 {name} 声明写"]
    if not hooks.is_declared(value):
        return [f"{label}要照声明写（带 format 和 declaration），这里是老写法：照 {of} 的 {name} 声明写"]
    said = value["declaration"] if isinstance(value["declaration"], dict) else {}
    if (said.get("of"), said.get("name")) != (of, name):
        return [f"{label}照的是 {said.get('of')} 的 {said.get('name')} 声明，要照 {of} 的 {name} 声明"]
    return []


def _setting_problems(handle) -> list[str]:
    value = handle.input("setting")
    found = _declared_problems(value, "重建设定", handle.input_info("method").id, REBUILD)
    if not found and hooks.per_point_items(value):
        found.append(f"重建设定里不能有每个点给的项（重建没有一批点）：{hooks.per_point_items(value)}")
    return found


def _draft_problems(handle, draft: dict) -> list[str]:
    """候选记着是哪个方法包出的，定稿就要用那一个。第 1 版读来的候选不知道，不核。"""
    source = draft.get("source")
    said = source.get("method") if isinstance(source, dict) else None
    method = handle.input_info("method")
    if isinstance(said, dict) and said.get("hash") != method.hash:
        return [f"这份候选是方法包 {said.get('id')} 出的，定稿要用同一个方法包（这里填的是 {method.id}）"]
    return []


def _smoke_problems(handle, draft: dict) -> list[str]:
    """冒烟要的几样都在、都对得上；没有冒烟，冒烟用的两样不该填。"""
    lines, stem = handle.input("gate"), handle.input_info("stem")
    if not gate.wants_smoke(lines):
        filled = [label for name, label in (("stem", "柄空间包"), ("placement", "放置设定")) if handle.input_info(name) is not None]
        return [f"检查门里没有冒烟（{gate.SMOKE}），{'、'.join(filled)}不该填"] if filled else []
    if stem is None:
        return [f"检查门里有冒烟（{gate.SMOKE}），要填冒烟用的柄空间包"]
    listed = model.read(handle.input("stem"))
    found = [] if "template" in (listed.get("modes") or []) else ["冒烟用的柄空间包不会 template（模板化）"]
    found += _declared_problems(handle.input("placement"), "冒烟用的放置设定", stem.id, "placement")
    if found:
        return found
    how = lines.get("smoke")
    if how is None:
        return ["检查门里有冒烟，检查门的设定里要写 smoke：让柄空间包拿哪个设计试"]
    design = hooks.find_declaration(listed.get("declarations"), "design")
    found += [f"冒烟的设计：{text}" for text in hooks.check_design(how["design"], design)]
    placement = hooks.find_declaration(listed.get("declarations"), "placement")
    found += [f"冒烟的放置设定：{text}" for text in hooks.check_point(how.get("placement") or {}, handle.input("placement"), placement)]
    inputs = listed.get("inputs")
    want = inputs.get("bone", {}) if isinstance(inputs, dict) else {}
    wrong = hooks.check_bone_wanted(want)
    return found + ([f"冒烟用的柄空间包清单里对骨模型的要求（inputs 的 bone）写得不对：{text}" for text in wrong] if wrong else
                    [f"这份候选骨模型不合冒烟用的柄空间包的要求：{text}" for text in hooks.bone_lacking(want, draft)])


def _problems(handle, mode: str) -> list[str]:
    """启动的第 5 步里冻结的那部分。返回哪里不行；空列表就是行。"""
    found, promised = _method_problems(handle, mode)
    found += _setting_problems(handle)
    found += gate.problems(handle.input("gate"), promised)
    if found or mode == "draft":
        return found
    try:
        draft = hooks.read_bone_model(handle.input("draft"))
    except ValueError as error:
        return [f"读不出候选骨模型的清单：{error}"]
    return _draft_problems(handle, draft) + _smoke_problems(handle, draft)


# ---------------------------------------------------------------- 交给方法包、方法包交回来

def _ask(handle, mode: str) -> dict:
    """交给方法包的 job.json：settings 是重建设定的取值；定稿另带候选的文件夹、读成现在这一版的清单、人工修改的文件夹。"""
    job = {"mode": mode, "settings": dict(handle.input("setting")["values"])}
    if mode == "draft":
        return dict(job, source=str(handle.input("source")), bone_id=handle.input_info("source").bone_id)
    edits = handle.input("edits")
    return dict(job, draft=str(handle.input("draft")), bone=hooks.read_bone_model(handle.input("draft")),
                edits=None if edits is None else str(edits), bone_id=handle.input_info("draft").bone_id)


def _source(handle, how) -> dict:
    """骨模型的来源：怎么来的照方法包交的；哪个方法包、哪份重建设定，是这个实验存定的那两样。"""
    method, setting = handle.input_info("method"), handle.input_info("setting")
    return {"how": how, "method": {"id": method.id, "hash": method.hash}, "setting": {"id": setting.id, "hash": setting.hash}}


def _kept(handle, result: dict) -> dict:
    """定稿沿用候选的数：方法包点名，只许它清单 kept 里的；值从候选的 measures 里抄，候选里没有就是没有。"""
    allowed = model.read(handle.input("method")).get("kept") or []
    named = result.get("kept", [])
    if not isinstance(named, list) or not all(isinstance(name, str) for name in named):
        raise ValueError(f"方法包交回来的 kept 要是量的名字的列表：{named!r}")
    wrong = sorted(set(named) - set(allowed))
    if wrong:
        raise ValueError(f"方法包说要沿用候选的 {wrong}，它的清单 kept 里没写这几个是定稿时重做不了的")
    before = hooks.read_bone_model(handle.input("draft")).get("measures") or {}
    return {name: before[name] for name in named if name in before}


def _numbers(handle, result: dict, final: bool) -> dict:
    """量出来的数：方法包量的，加上定稿沿用候选的，加上骨架自己量的。交回来的东西不对报 ValueError。"""
    measures = result.get("measures", {})
    if not isinstance(measures, dict):
        raise ValueError("方法包交回来的 measures 要是 {名字: 数}")
    return {**measures, **(_kept(handle, result) if final else {}), **model.measured(result)}


def _begin(handle, mode: str, task: str) -> None:
    if task in handle.round.rerun or task not in handle.tasks():
        rebuild.begin(handle, mode, _ask(handle, mode))
        handle.task(task, "queued")
    else:                                               # 上一轮重建出错（待查），这次启动又没点名：没有活可干，照实说
        handle.fail("这一轮没有要重排的任务：上一轮的重建出错属于待查，查过之后点名才重排")


def _report_stage(handle, task: str, view: dict) -> None:
    mine = _mine(handle, task)
    if mine is not None and (mine.state, mine.stage) != ("running", view["stage"]):
        handle.task(task, "running", stage=view["stage"], machine=view.get("machine"))


def _failed(handle, task: str, result) -> None:
    """重建自己没做成：环境的事可重试，别的待查。"""
    result = result if isinstance(result, dict) else {"status": "error", "reason": "方法包交回来的不是一个 JSON 对象"}
    name = "env" if result.get("status") == "env" else "failed"
    handle.problem(f"{'环境问题' if name == 'env' else '重建出错'}：{result.get('reason') or '没有说原因'}", task=task)
    handle.task(task, "failed", outcome=name)
    handle.fail(f"重建没有做成：{result.get('reason') or name}")


def _made(handle, task: str, write):
    """算出来、按格式写出来。方法包交上来的结果写不成格式：如实记成重建出错，这一轮失败；不带病往下走，也不让同一个报错一遍遍重来。"""
    try:
        return write()
    except (KeyError, TypeError, ValueError, OSError, AttributeError) as error:
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


def _result(handle, task: str, mode: str):
    """方法包干完了、交回来的是做成的结果，返回（结果，看到的样子）；还在干、或者没做成（已经照实记下），结果是 None。"""
    mine = _mine(handle, task)
    if mine is None or mine.state not in OPEN:
        return None, None
    view = rebuild.advance(handle, mode)
    result = view.get("result")
    if result is None:
        _report_stage(handle, task, view)
        return None, view
    if not isinstance(result, dict) or result.get("status") != "ok":
        _failed(handle, task, result)
        return None, view
    return result, view


# ---------------------------------------------------------------- recon.draft

def draft_check(handle):
    found = _problems(handle, "draft")
    return "；".join(found) if found else rebuild.check(handle, "draft")


def draft_start(handle):
    _begin(handle, "draft", DRAFT)


def draft_poll(handle):
    result, view = _result(handle, DRAFT, "draft")
    if result is None:
        return
    bone_id = handle.input_info("source").bone_id
    out = handle.work_dir / "out" / f"r{handle.round.number}"
    measured = _made(handle, DRAFT, lambda: _numbers(handle, result, final=False))
    if measured is None:
        return
    pending = [{"name": line["name"], "value": None, "limit": {"what": line.get("what", "")}, "passed": None}
               for line in handle.input("gate")["gate"]]
    draft = _made(handle, DRAFT, lambda: model.write(out / "draft", "bone_draft", bone_id=bone_id, made=result,
                                                     source=_source(handle, result["how"]), checks=pending, measures=measured))
    if draft is None or not _handed(handle, DRAFT, "draft", draft):
        return
    body = {"todo": result.get("todo") or [], "measures": measured, "timings": result.get("timings") or {}}
    _show(handle, "rebuilt", dict(body, neck_loop=result.get("neck_loop") or [], mesh_quality=result.get("mesh_quality") or {}))
    handle.output("todo", model.write_report(out / "todo", "todo", body, bone_id))
    handle.task(DRAFT, "done", outcome="rebuilt", machine=view.get("machine"))
    handle.finish()


# ---------------------------------------------------------------- recon.finalize

def final_check(handle):
    found = _problems(handle, "finalize")
    return "；".join(found) if found else rebuild.check(handle, "finalize")


def final_start(handle):
    _begin(handle, "finalize", FINAL)


def final_poll(handle):
    result, view = _result(handle, FINAL, "finalize")
    if result is None:
        return
    lines, bone_id = handle.input("gate"), handle.input_info("draft").bone_id
    out = handle.work_dir / "out" / f"r{handle.round.number}"
    measured = _made(handle, FINAL, lambda: _numbers(handle, result, final=True))
    if measured is None:
        return
    if gate.wants_smoke(lines):                         # 先照第 2 版写出一份候选，交给柄空间包模板化一个设计
        candidate = out / "candidate"
        if not candidate.exists() and _made(handle, FINAL, lambda: model.write(
                candidate, "bone_draft", bone_id=bone_id, made=result, source=_source(handle, result["how"]), checks=[],
                measures=measured)) is None:
            return
        said = gate.smoke(handle, candidate, lines)
        if said is None:
            _report_stage(handle, FINAL, {"stage": "smoke", "machine": view.get("machine")})
            return
        measured[gate.SMOKE] = said["ok"]
        measured[gate.SMOKE_REASON] = said["reason"]
    results = gate.checks(measured, lines["gate"])
    body = {"passed": gate.passed(results), "checks": results, "measures": measured, "history": result.get("history") or []}
    if gate.passed(results):
        final = _made(handle, FINAL, lambda: model.write(
            out / "model", "bone_model", bone_id=bone_id, made=result, source=_source(handle, result["how"]), checks=results,
            measures=measured))
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
        inputs=(Input("source", ("bone_source",), label="骨源"), Input("method", ("recon_method",), label="重建方法"),
                Input("setting", ("setting",), label="重建设定（照方法包的 rebuild 声明）"),
                Input("gate", ("setting",), label="检查门")),
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
        inputs=(Input("draft", ("bone_draft",), label="候选骨模型"), Input("method", ("recon_method",), label="重建方法（出候选的那一个）"),
                Input("setting", ("setting",), label="重建设定（照方法包的 rebuild 声明）"), Input("gate", ("setting",), label="检查门"),
                Input("edits", ("edits",), required=False, label="人工修改"),
                Input("stem", ("stem_space",), required=False, label="柄空间（检查门里有冒烟才填）"),
                Input("placement", ("setting",), required=False, label="冒烟用的放置设定（填了柄空间才填）")),
        outputs=(Output("model", "bone_model", "骨模型"), Output("gate", "report", "检查结果")),
        outcomes=(Outcome("passed", "ok", "过了检查门"), Outcome("gate_failed", "conclusion", "没过检查门"),
                  Outcome("failed", "unclear", "重建出错"), Outcome("env", "retryable", "环境问题")),
        check=final_check, start=final_start, poll=final_poll, stop=_stop("finalize", FINAL),
        charts=(Chart("steps", "bar", "各步用时"), Chart("mesh", "bar", "网格质量分布"), Chart("measures", "table", "量出来的数"),
                Chart("checks", "table", "检查结果")),
        chart=charts.chart,
    ),
]
