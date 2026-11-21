"""【冻结】FEA 的两种实验，一套流程：给定骨模型、一批点，每个点一个作业，算出力学响应。

    fea.run        柄空间包（不填就是无植入物）出柄的模型，有限元包建模、求解、后处理。几份设定都照包的声明写，
                   运行设定照这种实验自己声明的（running.py）。made_by 记柄空间包、有限元包和设定
    fea.reference  参照包：原来的内核（M1-3406-v1）从模板化到后处理整个算，只用来和旧库对照。
                   输入表和拆内核以前的 fea.run 一样。made_by 记内核

每个点走同样几步：出柄的模型（无植入物和参照包没有这一步）、建模、求解、后处理、推导量、交数据、判判据、归档。
输入表、产物表、结局表写死在这里，四个动作的骨架也在这里。自由代码（jobs.py、run.py）只管“怎么算”；
一个作业结束后归到哪个结局、留下什么、数据怎么写、怎么判定，都走冻结的那几个文件，自由代码绕不过去。
fea.run 启动前另核的几样（几份设定照对了声明、每个点给的项、名字引用）在 given.py。

自由代码要给的这几样，接口不变就可以整个重写：
    jobs.check(handle) -> 原因或 None      参照包那条启动前的检查：点里的骨标识和骨模型一致，点的各项和内核要的一致
    jobs.plan(handle) -> [作业]            参照包那条：一个点一个作业 {"task": 任务名, "point": 这个点, "fingerprint": 输入指纹}
    jobs.check_run(handle) -> 原因或 None  fea.run 启动前自由的那部分检查（冻结的 given.problems 过了才叫）
    jobs.plan_run(handle) -> [作业]        fea.run：一个点一个作业，同上
    run.begin(handle, 作业们)              一轮开头：给这一轮要跑的作业腾出地方
    run.advance(handle, 作业们) -> {任务名: {"stage", "machine", "result"}}
                                          把还没结束的作业各往前推。stage 是 queued、stem、modeled、build、ready、solve、post 之一
                                          （stem 是出柄的模型，modeled 是柄的模型出好了、等建模）；
                                          结束了的 result 不是 None：{"stem", "build", "post", "lost", "dirs"}，
                                          见 outcomes.classify 和 archive.wanted。推导量不由它算：见 export.derive
    run.halt(handle, 作业们)               把在跑的停掉
    run.release(handle, 作业)              这个作业该留的都留好了，它占的地方可以清掉
两种实验的作业都交给同一个 run.py；作业是哪一种，由 jobs.py 自己在作业里写明。
"""
from plugins.fea import archive, charts, export, given, jobs, judge, outcomes, run, running
from stemlab.hooks import Chart, Input, Kind, Output

RUN, REFERENCE = "fea.run", "fea.reference"
OPEN = ("queued", "running")


def _inputs(handle, kind: str) -> dict:
    """这一次调用里要反复用的几样：怎么跑的设定、数据说明、骨标识、这一轮的轮号、made_by。"""
    if kind == REFERENCE:
        kernel, derive = export.read_manifest(handle.input("kernel")), export.read_manifest(handle.input("derive"))
        return {"kind": kind, "setting": handle.input("export"), "columns": export.columns(kernel, derive),
                "bone_id": handle.input_info("bone").bone_id, "number": handle.round.number, "made_by": export.maker(handle)}
    read = given.read(handle)
    return {"kind": kind, "setting": handle.input("run")["values"], "columns": given.columns(read),
            "bone_id": handle.input_info("bone").bone_id, "number": handle.round.number, "made_by": given.maker(handle, read)}


def _plan(handle, kind: str) -> list[dict]:
    return jobs.plan(handle) if kind == REFERENCE else jobs.plan_run(handle)


def _open(handle, planned: list[dict]) -> list[dict]:
    """这一轮里还没结束的作业。"""
    known = handle.tasks()
    return [job for job in planned
            if job["task"] in known and known[job["task"]].round == handle.round.number and known[job["task"]].state in OPEN]


def check(handle, kind: str):
    """启动的第 5 步。只读。"""
    if kind == REFERENCE:
        kernel, derive = export.read_manifest(handle.input("kernel")), export.read_manifest(handle.input("derive"))
        found = export.problems(kernel, derive)
        if not found and handle.input("criteria") is not None:
            found = judge.problems(handle.input("criteria"), export.columns(kernel, derive))
        if not isinstance(handle.input("export"), dict):
            found.append("导出设定必须是一个 JSON 对象")
        return "；".join(found) if found else jobs.check(handle)
    found = given.problems(handle)
    if not found and handle.input("criteria") is not None:
        found = judge.problems(handle.input("criteria"), given.columns(given.read(handle)))
    return "；".join(found) if found else jobs.check_run(handle)


def start(handle, kind: str):
    """每一轮开头：把这一轮要跑的作业排上队。要重排的，加上还从没报过的。"""
    known = handle.tasks()
    todo = [job for job in _plan(handle, kind) if job["task"] in handle.round.rerun or job["task"] not in known]
    run.begin(handle, todo)
    for job in todo:
        handle.task(job["task"], "queued", fingerprint=job["fingerprint"])


def poll(handle, kind: str):
    """值守每看一遍：把作业往前推；结束了的归结局、留档、记下它那一行；都结束了就交产物、收尾。"""
    planned, inputs = _plan(handle, kind), _inputs(handle, kind)
    known = handle.tasks()
    still = _open(handle, planned)
    views = run.advance(handle, still) or {}
    for job in still:
        view = views.get(job["task"])
        if view is None:
            continue
        task = known[job["task"]]
        if view.get("result") is None:
            if view["stage"] != "queued" and (task.state, task.stage) != ("running", view["stage"]):   # 还在排队的不用再报
                handle.task(job["task"], "running", stage=view["stage"], machine=view.get("machine"), fingerprint=job["fingerprint"])
            continue
        _end(handle, job, view, inputs)
    if not _open(handle, planned):
        made = _publish(handle, planned, inputs)
        if made is None:
            handle.fail("数据没有交上去，原因见记下的问题")
        elif made:
            handle.finish()
        else:
            handle.fail("这一轮结束了，但没有一个作业算出能进数据的结果")


def _end(handle, job: dict, view: dict, inputs: dict) -> None:
    """一个作业结束了：算推导量、归结局、留档、记下它那一行，然后把它占的地方清掉。"""
    result, more, sources = view["result"], None, None
    if inputs["kind"] == RUN:
        result = given.checked(handle, job, result)
        more = given.derive_ask(handle, job, result)
    else:                                       # 参照包那条没有出柄的模型这一步：自由代码交上来的这两项不作数
        result = {key: value for key, value in result.items() if key not in ("stem", "stem_wrong")}
    result = export.derive(handle, job, result, inputs["setting"], more)
    if inputs["kind"] == RUN:
        sources = given.row_sources(job, result)
    name, reason = outcomes.classify(result)
    archive.keep(handle, job, inputs["number"], result, inputs["setting"])
    export.keep(handle, job, export.row(job, inputs["bone_id"], inputs["number"], name, result, inputs["columns"], sources))
    export.remember(handle, job, inputs["number"], name, reason)
    if name != "finished":
        handle.problem(f"{outcomes.LABEL[name]}：{reason}", task=job["task"])
    handle.task(job["task"], outcomes.task_state(name), outcome=name, machine=view.get("machine"), fingerprint=job["fingerprint"])
    run.release(handle, job)
    export.release(handle, job)


def _publish(handle, planned: list[dict], inputs: dict) -> bool | None:
    """交这一轮的产物：数据（有行才交）、归档清单、填了判据时的判定结果。返回有没有交出数据；有行却没被收下是 None。"""
    rows = export.collect(handle)
    number = inputs["number"]
    warning = outcomes.too_many_numerical(task.outcome for task in handle.tasks().values() if task.round == number and task.outcome)
    if warning:
        handle.problem(warning)
    out = handle.work_dir / "out" / f"r{number}"
    kept = handle.output("data", export.write(out / "data", rows, inputs["columns"], inputs["bone_id"], inputs["made_by"])) if rows else None
    handle.output("archive", archive.write(out / "archive", handle, inputs["setting"], inputs["bone_id"]))
    criteria = handle.input("criteria")
    if criteria is not None and rows:
        info = handle.input_info("criteria")
        if judge.late(info.time, handle.round.opened):
            handle.problem(f"判据 {info.id} 是这一轮开始之后才登记的（{info.time}），不能拿它判这一轮：判据要在看到结果之前写定")
        else:
            used = {"id": info.id, "hash": info.hash, "registered": info.time, "round_opened": handle.round.opened}
            handle.output("verdict", judge.write(out / "verdict", judge.judge(criteria, rows, len(planned)), used, inputs["bone_id"]))
    return (kept is not None or None) if rows else False


def stop(handle, kind: str):
    """你点停止：把在跑的停掉；已经算好的照常交。可以重复叫。"""
    planned, inputs = _plan(handle, kind), _inputs(handle, kind)
    still = _open(handle, planned)
    run.halt(handle, still)
    for job in still:
        handle.task(job["task"], "stopped", fingerprint=job["fingerprint"])
    _publish(handle, planned, inputs)


OUTPUTS = (Output("data", "data", "数据"), Output("archive", "archive", "归档清单"), Output("verdict", "report", "判定结果"))
CHARTS = (Chart("progress", "table", "作业走到哪"), Chart("solving", "table", "一个作业的求解过程"),
          Chart("results", "table", "已算完的点"), Chart("failures", "table", "没算出来的和原因"),
          Chart("kept", "bar", "每个作业留下了多少"))


def _kind(name: str, label: str, inputs: tuple, settings: tuple = ()) -> Kind:
    return Kind(name=name, label=label, inputs=inputs, outputs=OUTPUTS, outcomes=outcomes.OUTCOMES,
                check=lambda handle: check(handle, name), start=lambda handle: start(handle, name),
                poll=lambda handle: poll(handle, name), stop=lambda handle: stop(handle, name),
                charts=CHARTS, chart=charts.chart, settings=settings)


KINDS = [
    _kind(RUN, "FEA：一批点，每个点一个作业（柄空间包加有限元包）", (
        Input("bone", ("bone_model",), label="骨模型"),
        Input("points", ("points",), label="一批点"),
        Input("stem", ("stem_space",), required=False, label="柄空间（不填就是无植入物）"),
        Input("placement", ("setting",), required=False, label="放置设定（填了柄空间才填）"),
        Input("fem", ("fem",), label="有限元"),
        Input("fem_setting", ("setting",), label="有限元设定"),
        Input("derive", ("derive_def",), label="推导量定义"),
        Input("derive_setting", ("setting",), required=False, label="推导量设定（推导量定义声明了才填）"),
        Input("run", ("setting",), label="运行设定"),
        Input("criteria", ("setting",), required=False, label="判据"),
    ), settings=(running.DECLARATION,)),
    _kind(REFERENCE, "FEA（参照包）：原来的内核整个算，只用来对照", (
        Input("bone", ("bone_model",), label="骨模型"),
        Input("points", ("points",), label="一批点"),
        Input("kernel", ("kernel",), label="内核"),
        Input("derive", ("derive_def",), label="推导量定义"),
        Input("export", ("setting",), label="导出设定"),
        Input("criteria", ("setting",), required=False, label="判据"),
    )),
]
