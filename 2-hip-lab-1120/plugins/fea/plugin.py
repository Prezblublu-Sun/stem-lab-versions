"""【冻结】fea.run 一个类型：给定骨模型、设计、条件，算出力学响应。

输入表、产物表、结局表写死在这里，四个动作的骨架也在这里。自由代码（jobs.py、run.py）只管“怎么算”；
一个作业结束后归到哪个结局、留下什么、数据怎么写、怎么判定，都走冻结的那几个文件，自由代码绕不过去。

自由代码要给的这几样，接口不变就可以整个重写：
    jobs.check(handle) -> 原因或 None      启动前的检查：点里的骨标识和骨模型一致，点的各项和内核要的一致
    jobs.plan(handle) -> [作业]            一个点一个作业：{"task": 任务名, "point": 这个点, "fingerprint": 输入指纹}
    run.begin(handle, 作业们)              一轮开头：给这一轮要跑的作业腾出地方
    run.advance(handle, 作业们) -> {任务名: {"stage", "machine", "result"}}
                                          把还没结束的作业各往前推。stage 是 queued、build、ready、solve、post 之一；
                                          结束了的 result 不是 None：{"build", "post", "lost", "dirs"}，
                                          见 outcomes.classify 和 archive.wanted。推导量不由它算：见 export.derive
    run.halt(handle, 作业们)               把在跑的停掉
    run.release(handle, 作业)              这个作业该留的都留好了，它占的地方可以清掉
"""
from plugins.fea import archive, charts, export, jobs, judge, outcomes, run
from stemlab.hooks import Chart, Input, Kind, Output

OPEN = ("queued", "running")


def _inputs(handle) -> dict:
    """这一次调用里要反复用的几样：导出设定、数据说明、骨标识、这一轮的轮号。"""
    kernel, derive = export.read_manifest(handle.input("kernel")), export.read_manifest(handle.input("derive"))
    return {"setting": handle.input("export"), "columns": export.columns(kernel, derive),
            "bone_id": handle.input_info("bone").bone_id, "number": handle.round.number, "made_by": export.maker(handle)}


def _open(handle, planned: list[dict]) -> list[dict]:
    """这一轮里还没结束的作业。"""
    known = handle.tasks()
    return [job for job in planned
            if job["task"] in known and known[job["task"]].round == handle.round.number and known[job["task"]].state in OPEN]


def check(handle):
    """启动的第 5 步。只读。"""
    kernel, derive = export.read_manifest(handle.input("kernel")), export.read_manifest(handle.input("derive"))
    found = export.problems(kernel, derive)
    if not found and handle.input("criteria") is not None:
        found = judge.problems(handle.input("criteria"), export.columns(kernel, derive))
    if not isinstance(handle.input("export"), dict):
        found.append("导出设定必须是一个 JSON 对象")
    return "；".join(found) if found else jobs.check(handle)


def start(handle):
    """每一轮开头：把这一轮要跑的作业排上队。要重排的，加上还从没报过的。"""
    known = handle.tasks()
    todo = [job for job in jobs.plan(handle) if job["task"] in handle.round.rerun or job["task"] not in known]
    run.begin(handle, todo)
    for job in todo:
        handle.task(job["task"], "queued", fingerprint=job["fingerprint"])


def poll(handle):
    """值守每看一遍：把作业往前推；结束了的归结局、留档、记下它那一行；都结束了就交产物、收尾。"""
    planned, given = jobs.plan(handle), _inputs(handle)
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
        _end(handle, job, view, given)
    if not _open(handle, planned):
        made = _publish(handle, planned, given)
        if made is None:
            handle.fail("数据没有交上去，原因见记下的问题")
        elif made:
            handle.finish()
        else:
            handle.fail("这一轮结束了，但没有一个作业算出能进数据的结果")


def _end(handle, job: dict, view: dict, given: dict) -> None:
    """一个作业结束了：算推导量、归结局、留档、记下它那一行，然后把它占的地方清掉。"""
    result = export.derive(handle, job, view["result"], given["setting"])
    name, reason = outcomes.classify(result)
    archive.keep(handle, job, given["number"], result, given["setting"])
    export.keep(handle, job, export.row(job, given["bone_id"], given["number"], name, result, given["columns"]))
    export.remember(handle, job, given["number"], name, reason)
    if name != "finished":
        handle.problem(f"{outcomes.LABEL[name]}：{reason}", task=job["task"])
    handle.task(job["task"], outcomes.task_state(name), outcome=name, machine=view.get("machine"), fingerprint=job["fingerprint"])
    run.release(handle, job)
    export.release(handle, job)


def _publish(handle, planned: list[dict], given: dict) -> bool | None:
    """交这一轮的产物：数据（有行才交）、归档清单、填了判据时的判定结果。返回有没有交出数据；有行却没被收下是 None。"""
    rows = export.collect(handle)
    number = given["number"]
    warning = outcomes.too_many_numerical(task.outcome for task in handle.tasks().values() if task.round == number and task.outcome)
    if warning:
        handle.problem(warning)
    out = handle.work_dir / "out" / f"r{number}"
    kept = handle.output("data", export.write(out / "data", rows, given["columns"], given["bone_id"], given["made_by"])) if rows else None
    handle.output("archive", archive.write(out / "archive", handle, given["setting"], given["bone_id"]))
    criteria = handle.input("criteria")
    if criteria is not None and rows:
        info = handle.input_info("criteria")
        if judge.late(info.time, handle.round.opened):
            handle.problem(f"判据 {info.id} 是这一轮开始之后才登记的（{info.time}），不能拿它判这一轮：判据要在看到结果之前写定")
        else:
            used = {"id": info.id, "hash": info.hash, "registered": info.time, "round_opened": handle.round.opened}
            handle.output("verdict", judge.write(out / "verdict", judge.judge(criteria, rows, len(planned)), used, given["bone_id"]))
    return (kept is not None or None) if rows else False


def stop(handle):
    """你点停止：把在跑的停掉；已经算好的照常交。可以重复叫。"""
    planned, given = jobs.plan(handle), _inputs(handle)
    still = _open(handle, planned)
    run.halt(handle, still)
    for job in still:
        handle.task(job["task"], "stopped", fingerprint=job["fingerprint"])
    _publish(handle, planned, given)


KINDS = [
    Kind(
        name="fea.run",
        label="FEA：一批点，每个点一个作业",
        inputs=(
            Input("bone", ("bone_model",), label="骨模型"),
            Input("points", ("points",), label="一批点"),
            Input("kernel", ("kernel",), label="内核"),
            Input("derive", ("derive_def",), label="推导量定义"),
            Input("export", ("setting",), label="导出设定"),
            Input("criteria", ("setting",), required=False, label="判据"),
        ),
        outputs=(Output("data", "data", "数据"), Output("archive", "archive", "归档清单"), Output("verdict", "report", "判定结果")),
        outcomes=outcomes.OUTCOMES,
        check=check, start=start, poll=poll, stop=stop,
        charts=(Chart("progress", "table", "作业走到哪"), Chart("solving", "table", "一个作业的求解过程"),
                Chart("results", "table", "已算完的点"), Chart("failures", "table", "没算出来的和原因"),
                Chart("kept", "bar", "每个作业留下了多少")),
        chart=charts.chart,
    ),
]
