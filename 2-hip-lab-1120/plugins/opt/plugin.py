"""【冻结】opt.pool、opt.select 两个类型。选点可重放，可行性不靠策略自觉。

输入表、产物表、结局表写死在这里，两个类型的动作骨架也在这里。不靠自由代码和策略自觉的规矩都在骨架里：
    候选池的每一行是内核自己说的可不可行（这里直接读内核的结果），设计出了设计范围的不收
    策略选出来的点先过 feasible.py：不在池里的、不可行的拦下并记成问题；写出的一批点再独立核一遍
    条件由这里照“选点设定”补全；理由里一定有哪份策略、种子、哪版目标、用的哪个模型
    选完记一笔（replay.py），之后可以重放

自由代码要给的这几样，接口不变就可以整个重写：
    pool.check(handle) -> 原因或 None
    pool.begin(handle)                              在设计范围里取设计，交给内核做模板化（脱离出去跑）
    pool.advance(handle) -> {"stage", "result"}     result：{"status": ok / env / error, "reason",
                                                     "designs": [{"name", "design"}], "template": 内核输出的文件夹}
    pool.halt(handle)
    inputs.problems(handle) -> [哪里对不上]          各样输入对不对得上：同一个骨标识、目标里的列都有
    select.begin(handle) / select.halt(handle)       一次选点：要的话先让预测器对候选出预测，再跑策略
    select.advance(handle) -> {"stage", "result"}   result：{"status": ok / env / error, "reason",
                                                     "chosen": [{"name", "score", "why"}], "model", "job": 交给策略的那份 job.json}
    reasons.reason(pick, context) -> {…}            一个点的理由里自由的那一部分

选点设定（opt.select 的 defaults，种类是设定）：
    {"conditions": {"load": 2000.0}, "count": 8, "seed": 7}
    conditions 是条件默认：选出的每个点都带这一套条件。count 是这一次选几个点，seed 是种子。
"""
import json
from pathlib import Path

from plugins.opt import charts, feasible, inputs, pool, reasons, replay, select
from stemlab import hooks
from stemlab.hooks import Chart, Input, Kind, Outcome, Output

OPEN = ("queued", "running")
POOL, SELECT = "pool", "select"
NOTHING = "这一轮没有要重排的任务：上一轮出的错属于待查，查过之后点名才重排"


def _mine(handle, task: str):
    found = handle.tasks().get(task)
    return found if found is not None and found.round == handle.round.number else None


def _wanted(handle, task: str) -> bool:
    if task in handle.round.rerun or task not in handle.tasks():
        return True
    handle.fail(NOTHING)
    return False


def _report_stage(handle, task: str, view: dict) -> None:
    mine = _mine(handle, task)
    if mine is not None and (mine.state, mine.stage) != ("running", view["stage"]):
        handle.task(task, "running", stage=view["stage"])


def _failed(handle, task: str, outcome: str, reason) -> None:
    said = {"env": "环境问题", "strategy_error": "策略出错"}.get(outcome, "出错")
    handle.problem(f"{said}：{reason or '没有说原因'}", task=task)
    handle.task(task, "failed", outcome=outcome)
    handle.fail(f"{said}：{reason or outcome}")


def _stop(task: str, halt):
    def stop(handle):
        halt(handle)
        mine = _mine(handle, task)
        if mine is not None and mine.state in OPEN:
            handle.task(task, "stopped")
    return stop


def _show(handle, name: str, body: dict) -> None:
    """给图表留一份：产物交上去之后就不在 work/ 里了。"""
    shown = handle.work_dir / "shown" / f"r{handle.round.number}"
    shown.mkdir(parents=True, exist_ok=True)
    (shown / f"{name}.json").write_bytes(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _listed(folder) -> dict:
    return json.loads((Path(folder) / "manifest.json").read_bytes())


def _out(handle, name: str) -> Path:
    return handle.work_dir / "out" / f"r{handle.round.number}" / name


# ---------------------------------------------------------------- opt.pool

def pool_check(handle):
    space = handle.input("range")
    found = feasible.range_problems(space)
    if not found:
        kernel = _listed(handle.input("kernel"))
        wanted = [column.get("name") for column in kernel.get("design") or [] if isinstance(column, dict)]
        if "template" not in (kernel.get("modes") or []):
            found.append("这个内核不会模板化（清单的 modes 里没有 template）")
        if sorted(wanted) != sorted(space["design"]):
            found.append(f"设计范围里的项和内核要的设计项不一样：内核要 {sorted(wanted)}，范围里是 {sorted(space['design'])}")
        bone = handle.input_info("bone").bone_id
        if kernel.get("bones") and bone not in kernel["bones"]:
            found.append(f"这个内核只认这几根骨：{kernel['bones']}，骨模型是 {bone}")
    return "；".join(found) if found else pool.check(handle)


def pool_start(handle):
    if _wanted(handle, POOL):
        pool.begin(handle)
        handle.task(POOL, "queued")


def pool_poll(handle):
    mine = _mine(handle, POOL)
    if mine is None or mine.state not in OPEN:
        return
    view = pool.advance(handle)
    result = view.get("result")
    if result is None:
        _report_stage(handle, POOL, view)
        return
    if result.get("status") != "ok":
        _failed(handle, POOL, "env" if result.get("status") == "env" else "error", result.get("reason"))
        return
    space, bone = handle.input("range"), handle.input_info("bone").bone_id
    try:
        told = {row["name"]: row for row in json.loads((Path(result["template"]) / "result.json").read_bytes())["designs"]}
        rows = []
        for one in result["designs"]:
            why = feasible.inside(one["design"], space)
            said = told.get(one["name"])
            if why:
                handle.problem(f"候选 {one['name']} 不在设计范围里，没有收：{why}")
            elif said is None or not isinstance(said.get("feasible"), bool):
                handle.problem(f"内核没有说候选 {one['name']} 可不可行，没有收")
            else:
                rows.append({"name": one["name"], "bone_id": bone, "design": one["design"], "feasible": said["feasible"],
                             "info": said.get("info") if isinstance(said.get("info"), dict) else {}})
        hooks.write_points(_out(handle, "pool"), rows, kind="pool")
    except (KeyError, TypeError, ValueError, OSError) as error:
        _failed(handle, POOL, "error", f"候选池写不出来：{type(error).__name__}: {error}")
        return
    if handle.output("pool", _out(handle, "pool")) is None:
        _failed(handle, POOL, "error", "候选池没有交上去，原因见记下的问题")
        return
    _show(handle, "pool", {"rows": rows})
    handle.task(POOL, "done", outcome="generated")
    handle.finish()


# ---------------------------------------------------------------- opt.select

def _how(setting) -> list[str]:
    if not isinstance(setting, dict) or not isinstance(setting.get("conditions"), dict) or not setting["conditions"] \
            or any(value is None for value in setting["conditions"].values()):
        return ["选点设定要写 conditions：条件默认，每一项都要有值"]
    found = []
    if isinstance(setting.get("count"), bool) or not isinstance(setting.get("count"), int) or setting["count"] < 1:
        found.append("选点设定要写 count：这一次选几个点")
    if isinstance(setting.get("seed"), bool) or not isinstance(setting.get("seed"), int):
        found.append("选点设定要写 seed：一个整数")
    return found


def select_check(handle):
    found = feasible.problems(handle.input("objective")) + _how(handle.input("defaults"))
    needs = _listed(handle.input("strategy")).get("needs") or []
    if "data" in needs and not handle.input("data"):
        found.append("这份策略要数据（清单的 needs 里有 data），没有填")
    if "predictions" in needs and handle.input("predictor") is None:
        found.append("这份策略要预测器给的预测（清单的 needs 里有 predictions），没有填预测器")
    return "；".join(found or inputs.problems(handle)) or None


def select_start(handle):
    if _wanted(handle, SELECT):
        select.begin(handle)
        handle.task(SELECT, "queued")


def select_poll(handle):
    mine = _mine(handle, SELECT)
    if mine is None or mine.state not in OPEN:
        return
    view = select.advance(handle)
    result = view.get("result")
    if result is None:
        _report_stage(handle, SELECT, view)
        return
    if result.get("status") != "ok":
        _failed(handle, SELECT, "env" if result.get("status") == "env" else "strategy_error", result.get("reason"))
        return
    objective, how, strategy = handle.input("objective"), handle.input("defaults"), handle.input_info("strategy")
    candidates = hooks.read_points(handle.input("pool"))
    made, blocked = feasible.points(result.get("chosen"), candidates, objective, how["conditions"], how["count"])
    for text in blocked:
        handle.problem(text, task=SELECT)
    if not made:
        _show(handle, "select", {"points": [], "blocked": blocked})
        handle.problem("策略没有选出一个可行的点", task=SELECT)
        handle.task(SELECT, "done", outcome="no_feasible")
        handle.finish()
        return
    try:
        picks = {pick["name"]: pick for pick in result["chosen"] if isinstance(pick, dict)}
        context = {"strategy": strategy.id, "seed": how["seed"], "model": result.get("model"),
                   "objective": {"id": handle.input_info("objective").id, "version": objective["version"]},
                   "data": [info.id for info in handle.input_info("data")],
                   "predictor": getattr(handle.input_info("predictor"), "id", None)}
        for row in made:
            free = reasons.reason(picks[row["name"]], context)
            row["reason"] = {**(free if isinstance(free, dict) else {"said": str(free)}),
                             **{key: context[key] for key in ("strategy", "seed", "model", "objective")}}
        folder = _out(handle, "points")
        hashes = replay.hashes(made, folder)
        wrong = feasible.recheck(hooks.read_points(folder), candidates, objective)
        if wrong:
            raise ValueError("写出的点没过约束的复核：" + "；".join(wrong[:5]))
        replay.record(handle, job=Path(result["job"]), strategy=strategy, seed=how["seed"], count=how["count"], points=hashes)
    except (KeyError, TypeError, ValueError, OSError) as error:
        _failed(handle, SELECT, "strategy_error", f"选出来的点写不成一批点：{type(error).__name__}: {error}")
        return
    if handle.output("points", folder) is None:
        _failed(handle, SELECT, "strategy_error", "一批点没有交上去，原因见记下的问题")
        return
    _show(handle, "select", {"points": made, "blocked": blocked, "chosen": result.get("chosen")})
    handle.task(SELECT, "done", outcome="selected")
    handle.finish()


KINDS = [
    Kind(
        name="opt.pool",
        label="优化：出候选池（批量模板化，不做 FE）",
        inputs=(Input("bone", ("bone_model",), label="骨模型"), Input("kernel", ("kernel",), label="内核"),
                Input("range", ("setting",), label="设计范围")),
        outputs=(Output("pool", "pool", "候选池"),),
        outcomes=(Outcome("generated", "ok", "生成完"), Outcome("error", "unclear", "出错"), Outcome("env", "retryable", "环境问题")),
        check=pool_check, start=pool_start, poll=pool_poll, stop=_stop(POOL, pool.halt),
        charts=(Chart("candidates", "table", "各个候选"), Chart("feasible", "bar", "可行的和不可行的")),
        chart=charts.chart,
    ),
    Kind(
        name="opt.select",
        label="优化：一次选点",
        inputs=(Input("objective", ("objective",), label="目标和约束"), Input("strategy", ("strategy",), label="策略"),
                Input("pool", ("pool",), label="候选池"), Input("defaults", ("setting",), label="选点设定（条件默认）"),
                Input("data", ("data",), many=True, required=False, label="数据"),
                Input("predictor", ("predictor",), required=False, label="预测器")),
        outputs=(Output("points", "points", "一批点"),),
        outcomes=(Outcome("selected", "ok", "选完"), Outcome("no_feasible", "conclusion", "没有可行的点"),
                  Outcome("strategy_error", "unclear", "策略出错"), Outcome("env", "retryable", "环境问题")),
        check=select_check, start=select_start, poll=select_poll, stop=_stop(SELECT, select.halt),
        charts=(Chart("chosen", "table", "选中的点和理由"), Chart("where", "scatter", "选中的点在设计范围里的位置"),
                Chart("scores", "bar", "候选的分数")),
        chart=charts.chart,
    ),
]
