"""【冻结】surrogate.train、surrogate.predict、surrogate.check 三个类型。换模型不换评价：划分、误差算法、预测器格式不随模型变。

输入表、产物表、结局表写死在这里，三个类型的动作骨架也在这里。几条不靠自由代码自觉的规矩，都在骨架里：
    留出的行不进训练     切分在这里做（split.py）。交给训练代码的只有训练那一部分；留出和往外推的点，
                         训练代码只拿到设计和条件去出预测，真值留在操作台，误差在这里算（report.py）
    适用范围             由训练那一部分数据定（predictor.scope_of），交回来的包里写的不是这一份就不收
    超出范围的点不出数   哪些点在范围里在这里判（predictor.in_range），不在的记成问题

自由代码要给的这几样，接口不变就可以整个重写：
    data.problems(各份数据的文件夹, 要预测的量) -> [哪里不行]
    data.load(各份数据的文件夹) -> {"columns", "rows", "conflicts"}
    train.check(handle) -> 原因或 None
    train.begin(handle, 作业文件夹)                    把一次训练派出去。作业文件夹里有什么见 train.py 开头
    train.advance(handle) -> {"stage", "machine", "result"}
                                                      干完了 result 不是 None：{"status": ok / diverged / env / error, "reason",
                                                      "package": 预测器的包, "asked": 留出各点的预测（jsonl）, "history", "model"}
    train.halt(handle)
    predict.begin(handle, 在适用范围里的点)            交给预测器的包去算
    predict.advance(handle) -> {"stage", "result"}     result：{"status": ok / env / error, "reason", "rows", "skipped"}
    predict.halt(handle)

训练设定（surrogate.train 的 setting）：
    targets      要预测哪几个量（数据里的标签、推导量）
    seed         种子
    level        区间的名义覆盖率，默认 0.95
    scale        哪些量在 log10 上拟合、算误差：{"rotation": "log10"}。没写的是 linear
    acceptance   合格线，见 report.py。可以不写
    model        用哪种模型和它的选项，自由代码自己认
"""
import json
import shutil
from pathlib import Path

from plugins.surrogate import charts, data, predict, predictor, report, split, train
from stemlab import hooks
from stemlab.hooks import Chart, Input, Kind, Outcome, Output

OPEN = ("queued", "running")
TRAIN, PREDICT, CHECK = "train", "predict", "check"
LEVEL = 0.95
NOTHING = "这一轮没有要重排的任务：上一轮出的错属于待查，查过之后点名才重排"


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mine(handle, task: str):
    """这一轮里这个任务现在的样子；这一轮还没报过它就是 None。"""
    found = handle.tasks().get(task)
    return found if found is not None and found.round == handle.round.number else None


def _wanted(handle, task: str) -> bool:
    """这一轮要不要派这个任务。不要的时候把话说明白，这一轮照实结束。"""
    if task in handle.round.rerun or task not in handle.tasks():
        return True
    handle.fail(NOTHING)
    return False


def _report_stage(handle, task: str, view: dict) -> None:
    mine = _mine(handle, task)
    if mine is not None and (mine.state, mine.stage) != ("running", view["stage"]):
        handle.task(task, "running", stage=view["stage"], machine=view.get("machine"))


def _failed(handle, task: str, outcome: str, reason) -> None:
    said = {"diverged": "训练发散", "env": "环境问题"}.get(outcome, "出错")
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


def _desk(handle) -> Path:
    """冻结代码自己放东西的地方：切出来的各部分、真值。自由代码拿到的只有其中的作业文件夹。"""
    return handle.work_dir / "desk" / f"r{handle.round.number}"


def _show(handle, name: str, body: dict) -> None:
    """给图表留一份：产物交上去之后就不在 work/ 里了。"""
    shown = handle.work_dir / "shown" / f"r{handle.round.number}"
    shown.mkdir(parents=True, exist_ok=True)
    (shown / f"{name}.json").write_bytes(report.dumps(body))


def _listed(folder) -> dict:
    return json.loads((Path(folder) / "manifest.json").read_bytes())


def _jsonl(path: Path, rows) -> None:
    with open(path, "wb") as stream:
        for row in rows:
            stream.write(report.dumps(row))


def _one_bone(infos) -> str | None:
    bones = {info.bone_id for info in infos}
    return bones.pop() if len(bones) == 1 else None


# ---------------------------------------------------------------- surrogate.train

def _setting_problems(setting) -> list[str]:
    if not isinstance(setting, dict):
        return ["训练设定必须是一个 JSON 对象"]
    found = []
    targets = setting.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(name, str) for name in targets) or len(set(targets)) != len(targets):
        found.append("训练设定要写 targets：要预测哪几个量，不重复")
        targets = []
    if isinstance(setting.get("seed"), bool) or not isinstance(setting.get("seed"), int):
        found.append("训练设定要写 seed：一个整数")
    if not _number(setting.get("level", LEVEL)) or not 0 < setting.get("level", LEVEL) < 1:
        found.append("训练设定的 level 是区间的名义覆盖率，在 0 和 1 之间")
    scale = setting.get("scale", {})
    if not isinstance(scale, dict) or any(name not in targets or how not in report.SCALES for name, how in scale.items()):
        found.append(f"训练设定的 scale 写的是要预测的量各用哪个刻度：{list(report.SCALES)} 之一")
    return found + report.line_problems(setting.get("acceptance"), targets)


def _columns(handle) -> list[dict]:
    """数据说明里不是场的各列。由这里自己读清单，不听自由代码说。"""
    return [column for column in _listed(handle.input("data")[0])["columns"] if column["role"] != "field"]


def train_check(handle):
    setting, folders = handle.input("setting"), handle.input("data")
    found = _setting_problems(setting) or data.problems(folders, setting["targets"])
    if not found:
        columns = _columns(handle)
        found = split.problems(handle.input("split"), columns)
        try:
            predictor.targets_of(columns, setting["targets"])
        except ValueError as error:
            found.append(str(error))
    return "；".join(found) if found else train.check(handle)


def train_start(handle):
    if not _wanted(handle, TRAIN):
        return
    setting, columns = handle.input("setting"), _columns(handle)
    loaded = data.load(handle.input("data"))
    for text in loaded["conflicts"][:20]:
        handle.problem(text)
    parts = split.split(loaded["rows"], handle.input("split"))
    names = setting["targets"]
    labelled = [row for row in parts["train"] if all(_number(row["values"].get(name)) for name in names)]
    if len(labelled) < 3:
        handle.fail(f"划分之后，训练那一部分里要预测的量都有数的行只有 {len(labelled)} 行，不够训练")
        return
    kept = {"holdout": parts["holdout"], "outside": parts["outside"], "split": split.describe(handle.input("split"), parts),
            "scope": predictor.scope_of(labelled, columns), "targets": predictor.targets_of(columns, names),
            "level": setting.get("level", LEVEL)}
    home = _desk(handle)
    shutil.rmtree(home, ignore_errors=True)
    (home / "job").mkdir(parents=True)
    (home / "truth.json").write_bytes(report.dumps(kept))
    asked = {"seed": setting["seed"], "targets": names, "level": kept["level"], "scale": setting.get("scale") or {},
             "setting": setting, "columns": columns, "target_columns": kept["targets"], "scope": kept["scope"]}
    (home / "job" / "job.json").write_bytes(report.dumps(asked))
    _jsonl(home / "job" / "train.jsonl", parts["train"])
    _jsonl(home / "job" / "ask.jsonl", split.unlabeled(parts["holdout"] + parts["outside"], columns))
    train.begin(handle, home / "job")
    handle.task(TRAIN, "queued")


def train_poll(handle):
    mine = _mine(handle, TRAIN)
    if mine is None or mine.state not in OPEN:
        return
    view = train.advance(handle)
    result = view.get("result")
    if result is None:
        _report_stage(handle, TRAIN, view)
        return
    if result.get("status") != "ok":
        _failed(handle, TRAIN, result.get("status") if result.get("status") in ("diverged", "env") else "error", result.get("reason"))
        return
    kept, setting = json.loads((_desk(handle) / "truth.json").read_bytes()), handle.input("setting")
    package = Path(str(result.get("package")))
    if package.exists():                                # 不在了：上一遍已经交上去过，下面的 output 会认出来
        wrong = predictor.problems(package, columns=kept["targets"], level=kept["level"], scope=kept["scope"], packed_here=True)
        if wrong:
            _failed(handle, TRAIN, "error", "训练交回来的包不合规矩：" + "；".join(wrong[:5]))
            return
    try:
        wanted = {row["point"] for part in report.ON for row in kept[part]}
        predicted = [row for row in hooks.read_points(Path(str(result.get("asked")))) if row.get("point") in wanted]
        training = {"model": result.get("model"), "history": result.get("history"), "rows_used": result.get("rows_used"),
                    "seed": setting["seed"], "data": [info.id for info in handle.input_info("data")],
                    "split": handle.input_info("split").id, "setting": handle.input_info("setting").id,
                    "setting_registered": handle.input_info("setting").time, "round_opened": handle.round.opened,
                    "machine": view.get("machine")}
        body = report.error_report(targets=[column["name"] for column in kept["targets"]], scales=setting.get("scale") or {},
                                   level=kept["level"], split=kept["split"], truth=kept, predicted=predicted,
                                   lines=setting.get("acceptance"), training=training)
        written = report.write(handle.work_dir / "out" / f"r{handle.round.number}" / "report", "errors", body,
                               _one_bone(handle.input_info("data")))
    except (KeyError, TypeError, ValueError, OSError) as error:
        _failed(handle, TRAIN, "error", f"训练交回来的预测算不出误差：{type(error).__name__}: {error}")
        return
    if handle.output("predictor", package) is None:
        _failed(handle, TRAIN, "error", "预测器没有交上去，原因见记下的问题")
        return
    _show(handle, "errors", body)
    handle.output("report", written)
    handle.task(TRAIN, "done", outcome="trained", machine=view.get("machine"))
    handle.finish()


# ---------------------------------------------------------------- surrogate.predict

def _asked(handle) -> tuple:
    """这批点里在适用范围里的（写成交给预测器的样子），和不在的（点的名字、为什么）。"""
    scope = _listed(handle.input("predictor"))["range"]
    inside, outside = [], []
    for point in hooks.read_points(handle.input("points")):
        why = predictor.in_range(scope, point)
        if why:
            outside.append((point["name"], why))
        else:
            inside.append({"hash": point["hash"], "bone_id": point["bone_id"], "design": point["design"], "conditions": point["conditions"]})
    return inside, outside


def predict_check(handle):
    found = predictor.problems(handle.input("predictor"))
    if found:
        return "预测器的包不合规矩：" + "；".join(found[:5])
    inside, outside = _asked(handle)
    return None if inside else f"这批点没有一个在预测器的适用范围里。比如 {outside[0][0]}：{outside[0][1]}"


def predict_start(handle):
    if not _wanted(handle, PREDICT):
        return
    inside, outside = _asked(handle)
    for name, why in outside:
        handle.problem(f"点 {name} 超出预测器的适用范围，没有出数：{why}")
    predict.begin(handle, inside)
    handle.task(PREDICT, "queued")


def predict_poll(handle):
    mine = _mine(handle, PREDICT)
    if mine is None or mine.state not in OPEN:
        return
    view = predict.advance(handle)
    result = view.get("result")
    if result is None:
        _report_stage(handle, PREDICT, view)
        return
    if result.get("status") != "ok":
        _failed(handle, PREDICT, "env" if result.get("status") == "env" else "error", result.get("reason"))
        return
    listed = _listed(handle.input("predictor"))
    bones = {point["hash"]: point["bone_id"] for point in _asked(handle)[0]}
    try:
        rows = [{"point": row["point"], "bone_id": bones[row["point"]], "values": row["values"], "lower": row["lower"],
                 "upper": row["upper"]} for row in result["rows"] if row.get("point") in bones]
        said = {row["point"] for row in rows} | {row.get("point") for row in result.get("skipped") or []}
        for row in result.get("skipped") or []:
            handle.problem(f"预测器自己说点 {str(row.get('point'))[:12]} 不在它的范围里，没有出数：{row.get('why')}")
        silent = sorted(set(bones) - said)
        if silent:
            handle.problem(f"有 {len(silent)} 个在范围里的点预测器没有给数，比如 {silent[0][:12]}")
        folder = handle.work_dir / "out" / f"r{handle.round.number}" / "prediction"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        _jsonl(folder / "rows.jsonl", rows)
        (folder / "manifest.json").write_bytes(report.dumps({"format": 1, "kind": "prediction", "files": ["rows.jsonl"],
                                                             "count": len(rows), "columns": listed["columns"], "level": listed["level"]}))
        wrong = hooks.check_format("prediction", folder)
    except (KeyError, TypeError, ValueError, OSError) as error:
        wrong = [f"{type(error).__name__}: {error}"]
    if wrong:
        _failed(handle, PREDICT, "error", "预测器给的结果写不成一份预测：" + "；".join(wrong[:5]))
        return
    if handle.output("prediction", folder) is None:
        _failed(handle, PREDICT, "error", "预测没有交上去，原因见记下的问题")
        return
    _show(handle, "prediction", {"columns": listed["columns"], "level": listed["level"], "rows": rows})
    handle.task(PREDICT, "done", outcome="predicted")
    handle.finish()


# ---------------------------------------------------------------- surrogate.check

def check_check(handle):
    predicted = [column["name"] for column in _listed(handle.input("prediction"))["columns"]]
    known = [column["name"] for column in _listed(handle.input("data"))["columns"]]
    missing = [name for name in predicted if name not in known]
    return f"预测里的这几列数据里没有，没法比：{missing}" if missing else None


def check_start(handle):
    if _wanted(handle, CHECK):
        handle.task(CHECK, "queued")


def check_poll(handle):
    mine = _mine(handle, CHECK)
    if mine is None or mine.state not in OPEN:
        return
    prediction, measured = Path(handle.input("prediction")), Path(handle.input("data"))
    body = report.check_report(hooks.read_points(prediction / "rows.jsonl"), hooks.read_points(measured / "rows.jsonl"),
                               _listed(prediction)["columns"])
    body["prediction"], body["data"] = handle.input_info("prediction").id, handle.input_info("data").id
    _show(handle, "check", body)
    handle.output("report", report.write(handle.work_dir / "out" / f"r{handle.round.number}" / "report", "check", body,
                                         handle.input_info("data").bone_id))
    if not body["matched"]:
        handle.problem("预测和数据一个点都对不上：它们不是同一批点（点的哈希由骨标识、设计、条件算出）", task=CHECK)
    handle.task(CHECK, "done", outcome="checked" if body["matched"] else "nothing_matched")
    handle.finish()


KINDS = [
    Kind(
        name="surrogate.train",
        label="代理：训练一个预测器",
        inputs=(Input("data", ("data",), many=True, label="数据"), Input("setting", ("setting",), label="训练设定"),
                Input("split", ("setting",), label="划分")),
        outputs=(Output("predictor", "predictor", "预测器"), Output("report", "report", "误差报告")),
        outcomes=(Outcome("trained", "ok", "训练完"), Outcome("diverged", "unclear", "训练发散"), Outcome("error", "unclear", "出错"),
                  Outcome("env", "retryable", "环境问题")),
        check=train_check, start=train_start, poll=train_poll, stop=_stop(TRAIN, train.halt), where="worker",
        charts=(Chart("history", "line", "训练过程"), Chart("holdout", "scatter", "留出上预测对真值"),
                Chart("errors", "table", "各预测量的误差"), Chart("verdicts", "table", "合格线")),
        chart=charts.chart,
    ),
    Kind(
        name="surrogate.predict",
        label="代理：对一批点出预测",
        inputs=(Input("predictor", ("predictor",), label="预测器"), Input("points", ("points",), label="一批点")),
        outputs=(Output("prediction", "prediction", "一份预测"),),
        outcomes=(Outcome("predicted", "ok", "出完"), Outcome("error", "unclear", "出错"), Outcome("env", "retryable", "环境问题")),
        check=predict_check, start=predict_start, poll=predict_poll, stop=_stop(PREDICT, predict.halt),
        charts=(Chart("predictions", "table", "各点的预测"),),
        chart=charts.chart,
    ),
    Kind(
        name="surrogate.check",
        label="代理：复核，预测对 FEA",
        inputs=(Input("prediction", ("prediction",), label="一份预测"), Input("data", ("data",), label="数据")),
        outputs=(Output("report", "report", "复核报告"),),
        outcomes=(Outcome("checked", "ok", "复核完"), Outcome("nothing_matched", "conclusion", "一个点都对不上")),
        check=check_check, start=check_start, poll=check_poll,
        charts=(Chart("check", "scatter", "复核：预测对 FEA"), Chart("diffs", "table", "各点的差")),
        chart=charts.chart,
    ),
]
