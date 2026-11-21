"""【冻结】surrogate.train、surrogate.predict、surrogate.check 三个类型。换模型不换评价：划分、误差算法、预测器格式不随模型变。

输入表、产物表、结局表写死在这里，三个类型的动作骨架也在这里。几条不靠自由代码自觉的规矩，都在骨架里：
    留出的行不进训练     切分在这里做（split.py）。交给训练代码的只有训练那一部分；留出和往外推的点，
                         训练代码只拿到设计和条件去出预测，真值留在操作台，误差在这里算（report.py）
    适用范围             由训练那一部分数据定（predictor.scope_of），交回来的包里写的不是这一份就不收
    超出范围的点不出数   哪些点在范围里在这里判（predictor.in_range），不在的记成问题
    不同内核的数不混     几份数据一起训练，得是同一个内核算的（清单的 made_by）；预测器、一份预测跟着记；
                         复核时预测和数据都记了、又不是同一个内核的，不比

自由代码要给的这几样，接口不变就可以整个重写：
    data.problems(各份数据的文件夹, 要预测的量) -> [哪里不行]
    data.load(各份数据的文件夹) -> {"columns", "rows", "conflicts", "rule"}
                                                      rule：同一个点结果不同时留的是哪一份（first：填在最前面的那份）。
                                                      它和冲突了几个点一起记进误差报告的 training.merge
    train.check(handle) -> 原因或 None
    train.begin(handle, 作业文件夹)                    把一次训练派出去。作业文件夹里有什么见 train.py 开头
    train.advance(handle) -> {"stage", "machine", "result"}
                                                      干完了 result 不是 None：{"status": ok / diverged / env / error, "reason",
                                                      "package": 预测器的包, "asked": 留出各点的预测（jsonl）, "history", "model"}
    train.halt(handle)
    predict.begin(handle, 在适用范围里的点)            交给预测器的包去算
    predict.advance(handle) -> {"stage", "result"}     result：{"status": ok / env / error, "reason", "rows", "skipped",
                                                      "folder": 包的输出文件夹（预测了场的，场的文件在它下面）}
    predict.halt(handle)

场也走这一套，规矩不变：
    能预测的场是每一行形状都一样的数组（见 predictor.py 开头）。训练的各行里形状不一样的场，这一轮照实做不下去
    交给训练代码的只有训练那一部分的场（作业文件夹的 fields/<点的哈希>/<场的名字>.npy，train.jsonl 的行里写着位置）；
    留出和往外推的点，场的真值留在操作台，误差在这里拿它来算
    训练代码对留出各点预测的场，写成文件放在 asked.jsonl 旁边，行里的 fields 写相对位置

训练设定（surrogate.train 的 setting）：
    targets      要预测哪几个量（数据里的标签、推导量）。只预测场的可以写成空的
    fields       要预测哪几个场（数据里的场）。可以不写
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
    targets, fields = setting.get("targets"), setting.get("fields", [])
    if not isinstance(fields, list) or not all(isinstance(name, str) for name in fields) or len(set(fields)) != len(fields):
        found.append("训练设定的 fields 写的是要预测哪几个场，不重复")
        fields = []
    if not isinstance(targets, list) or not (targets or fields) or not all(isinstance(name, str) for name in targets) \
            or len(set(targets)) != len(targets) or set(targets) & set(fields):
        found.append("训练设定要写 targets：要预测哪几个量，不重复（只预测场的可以写成空的）")
        targets = []
    if isinstance(setting.get("seed"), bool) or not isinstance(setting.get("seed"), int):
        found.append("训练设定要写 seed：一个整数")
    if not _number(setting.get("level", LEVEL)) or not 0 < setting.get("level", LEVEL) < 1:
        found.append("训练设定的 level 是区间的名义覆盖率，在 0 和 1 之间")
    scale = setting.get("scale", {})
    if not isinstance(scale, dict) or any(name not in targets or how not in report.SCALES for name, how in scale.items()):
        found.append(f"训练设定的 scale 写的是要预测的量各用哪个刻度：{list(report.SCALES)} 之一")
    return found + report.line_problems(setting.get("acceptance"), [*targets, *fields])


def _columns(handle) -> list[dict]:
    """数据说明里不是场的各列。由这里自己读清单，不听自由代码说。"""
    return [column for column in _listed(handle.input("data")[0])["columns"] if column["role"] != "field"]


def _fields(setting) -> list:
    """训练设定里要预测的场。没写就是不预测场。"""
    return list(setting.get("fields") or [])


def _field_problems(folders, names) -> list[str]:
    """要预测的场，每份数据的数据说明里都得有，单位相同。"""
    found, first = [], None
    for number, folder in enumerate(folders, start=1):
        listed = {column["name"]: column for column in _listed(folder)["columns"]}
        wrong = [name for name in names if listed.get(name, {}).get("role") != predictor.FIELD]
        if wrong:
            found.append(f"训练设定要预测的这几个场，第 {number} 份数据里没有：{wrong}")
        elif first is None:
            first = listed
        elif any(listed[name]["unit"] != first[name]["unit"] for name in names):
            found.append(f"要预测的场，第 {number} 份数据里的单位和第 1 份不一样")
    return found


def _read(reader, path):
    """读一个场。没有这个文件、读不成，就是 None。"""
    if not path:
        return None
    try:
        return reader(path)
    except ValueError:
        return None


def _field_sources(handle, parts: dict, names) -> tuple:
    """要预测的各个场：每个点的那一份存在哪（点的哈希 -> {场: 文件}）、训练那一部分读进来的（点的哈希 -> {场: 数组}）、各自的形状。

    几份数据里同一个点，用最先见到的那一份（和 data.load 一样）。读不出来的场当这一行没有，这一行就不进训练。
    训练的各行里同一个场形状不一样，这种场学不了：报 ValueError。
    """
    stored, given, shapes = {}, {}, {}
    if not names:
        return stored, given, shapes
    for folder in handle.input("data"):
        for row in hooks.read_points(Path(folder) / "rows.jsonl"):
            if row["point"] not in stored:
                stored[row["point"]] = {name: str(Path(folder) / rel) for name, rel in (row.get("fields") or {}).items() if name in names}
    for row in parts["train"]:
        found = {name: _read(predictor.read_field, stored.get(row["point"], {}).get(name)) for name in names}
        if any(value is None for value in found.values()):
            continue
        for name, value in found.items():
            if shapes.setdefault(name, list(value.shape)) != list(value.shape):
                raise ValueError(f"场 {name} 在训练的各行里形状不一样（{shapes[name]} 和 {list(value.shape)}）：每一行形状都一样的场才学得了")
        given[row["point"]] = found
    return stored, given, shapes


def _field_pairs(kept: dict, predicted, base: Path) -> dict:
    """留出和往外推的各点上，每个场的（真值，预测）：{场: {"holdout": [...], "outside": [...]}}。
    真值是操作台留着的那一份；预测是训练代码交回来的文件，读不出、形状不是训练时那个形状的、同一个点给了不止一次的，当它没给。"""
    guesses = {point: row.get("fields") or {} for point, row in report.once(predicted)[0].items()}
    found = {}
    for column in kept.get("fields") or []:
        name = column["name"]
        shape = kept["field_shapes"][name]
        found[name] = {part: [(_read(predictor.read_field, kept["field_files"].get(row["point"], {}).get(name)),
                               _read(lambda path: predictor.read_predicted(path, shape),
                                     base / guesses[row["point"]][name] if guesses.get(row["point"], {}).get(name) else None))
                              for row in kept[part]] for part in report.ON}
    return found


def _makers(folders) -> list:
    """各份数据是哪个内核算的：[(怎么称呼它, 清单里的 made_by 或 None)]。"""
    return [(f"第 {number} 份数据", _listed(folder).get("made_by")) for number, folder in enumerate(folders, start=1)]


def _common(makers) -> dict | None:
    """训练数据合起来的 made_by，记进预测器。合法在契约里（common_maker）：都一样的照抄，推导量取记了的那一份，
    骨模型的版本合起来。有一份没记，就是不知道（None）。"""
    return hooks.common_maker([made for _, made in makers])


def train_check(handle):
    setting, folders = handle.input("setting"), handle.input("data")
    found = _setting_problems(setting) or (data.problems(folders, setting["targets"]) + _field_problems(folders, _fields(setting))
                                           + hooks.mixed_makers(_makers(folders)))
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
    names, fields = setting["targets"], _fields(setting)
    try:
        stored, given, shapes = _field_sources(handle, parts, fields)
    except ValueError as error:
        handle.fail(str(error))
        return
    labelled = [row for row in parts["train"] if all(_number(row["values"].get(name)) for name in names)
                and (not fields or row["point"] in given)]
    if len(labelled) < 3:
        handle.fail(f"划分之后，训练那一部分里要预测的量都有数的行只有 {len(labelled)} 行，不够训练")
        return
    kept = {"holdout": parts["holdout"], "outside": parts["outside"], "split": split.describe(handle.input("split"), parts),
            "scope": predictor.scope_of(labelled, columns), "targets": predictor.targets_of(columns, names),
            "level": setting.get("level", LEVEL), "made_by": _common(_makers(handle.input("data"))),
            "merge": {"rule": loaded.get("rule"), "conflicts": len(loaded["conflicts"])}}     # 几份数据合起来时冲突了几个点、按什么留的
    if fields:                                          # 场的真值：留出和往外推的各点的场存在哪，只留在操作台
        kept.update(fields=predictor.fields_of(_listed(handle.input("data")[0])["columns"], fields), field_shapes=shapes,
                    field_files={row["point"]: stored.get(row["point"], {}) for part in report.ON for row in parts[part]})
    home = _desk(handle)
    shutil.rmtree(home, ignore_errors=True)
    (home / "job").mkdir(parents=True)
    (home / "truth.json").write_bytes(report.dumps(kept))
    asked = {"seed": setting["seed"], "targets": names, "level": kept["level"], "scale": setting.get("scale") or {},
             "setting": setting, "columns": columns, "target_columns": kept["targets"], "scope": kept["scope"],
             "made_by": kept["made_by"]}
    if fields:
        asked.update(fields=fields, field_columns=kept["fields"], field_shapes=shapes)
    (home / "job" / "job.json").write_bytes(report.dumps(asked))
    for point, found in given.items():                  # 交出去的只有训练那一部分的场
        for name, values in found.items():
            predictor.write_field(home / "job" / predictor.FIELDS / point / f"{name}.npy", values)
    _jsonl(home / "job" / "train.jsonl", [
        dict(row, fields={name: f"{predictor.FIELDS}/{row['point']}/{name}.npy" for name in fields} if row["point"] in given else {})
        for row in parts["train"]])
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
        wrong = predictor.problems(package, columns=kept["targets"] + (kept.get("fields") or []), level=kept["level"],
                                   scope=kept["scope"], packed_here=True, shapes=kept.get("field_shapes") or None)
        if not wrong and _listed(package).get("made_by") != kept.get("made_by"):
            wrong = ["包的清单里写的 made_by 不是训练数据的那一份"]
        if wrong:
            _failed(handle, TRAIN, "error", "训练交回来的包不合规矩：" + "；".join(wrong[:5]))
            return
    try:
        wanted = {row["point"] for part in report.ON for row in kept[part]}
        predicted = [row for row in hooks.read_points(Path(str(result.get("asked")))) if row.get("point") in wanted]
        single, twice = report.once(predicted)
        missing = wanted - set(single) - twice
        if missing or twice:
            said = "，".join(([f"{len(missing)} 个点没有预测"] if missing else []) + ([f"{len(twice)} 个点给了不止一次预测"] if twice else []))
            handle.problem(f"训练对留出、往外推的点交回来的预测不全：{said}。这些点不比，它们那一部分的合格线不可判", task=TRAIN)
        training = {"model": result.get("model"), "history": result.get("history"), "rows_used": result.get("rows_used"),
                    "seed": setting["seed"], "data": [info.id for info in handle.input_info("data")],
                    "merge": kept.get("merge"), "split": handle.input_info("split").id, "setting": handle.input_info("setting").id,
                    "setting_registered": handle.input_info("setting").time, "round_opened": handle.round.opened,
                    "machine": view.get("machine")}
        body = report.error_report(targets=[column["name"] for column in kept["targets"]], scales=setting.get("scale") or {},
                                   level=kept["level"], split=kept["split"], truth=kept, predicted=predicted,
                                   lines=setting.get("acceptance"), training=training,
                                   fields=_field_pairs(kept, predicted, Path(str(result.get("asked"))).parent) or None)
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
    shapes = {column["name"]: (listed.get("shapes") or {}).get(column["name"]) for column in listed["columns"]
              if column["role"] == predictor.FIELD}
    folder = handle.work_dir / "out" / f"r{handle.round.number}" / "prediction"
    try:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        rows, files = [], ["rows.jsonl"]
        for row in result["rows"]:
            if row.get("point") not in bones:
                continue
            one = {"point": row["point"], "bone_id": bones[row["point"]], "values": row["values"], "lower": row["lower"],
                   "upper": row["upper"]}
            if shapes:                                  # 预测出来的场：核过形状和区间，抄进这份预测的 fields/ 下
                one["fields"] = {}
                for name, shape in shapes.items():
                    given = (row.get("fields") or {}).get(name)
                    if given is not None:
                        rel = f"{predictor.FIELDS}/{row['point']}/{name}.npy"
                        predictor.write_field(folder / rel, predictor.read_predicted(Path(str(result.get("folder"))) / given, shape))
                        one["fields"][name] = rel
                        files.append(rel)
            rows.append(one)
        said = {row["point"] for row in rows} | {row.get("point") for row in result.get("skipped") or []}
        for row in result.get("skipped") or []:
            handle.problem(f"预测器自己说点 {str(row.get('point'))[:12]} 不在它的范围里，没有出数：{row.get('why')}")
        silent = sorted(set(bones) - said)
        if silent:
            handle.problem(f"有 {len(silent)} 个在范围里的点预测器没有给数，比如 {silent[0][:12]}")
        _jsonl(folder / "rows.jsonl", rows)
        (folder / "manifest.json").write_bytes(report.dumps({
            "format": 1, "kind": "prediction", "files": sorted(files, key=lambda rel: rel.encode("utf-8")),
            "count": len(rows), "columns": listed["columns"], "level": listed["level"],
            **({"made_by": listed["made_by"]} if listed.get("made_by") else {})}))      # 跟着预测器记：它的训练数据是哪个内核算的
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
    guessed, measured = _listed(handle.input("prediction")), _listed(handle.input("data"))
    known = {column["name"]: column["role"] for column in measured["columns"]}
    missing = [column["name"] for column in guessed["columns"]
               if column["name"] not in known or (column["role"] == predictor.FIELD) != (known[column["name"]] == predictor.FIELD)]
    if missing:
        return f"预测里的这几列数据里没有，没法比：{missing}"
    return hooks.maker_clash(("这份预测（照它的预测器的训练数据）", guessed.get("made_by")), ("这份数据", measured.get("made_by")))


def check_start(handle):
    if _wanted(handle, CHECK):
        handle.task(CHECK, "queued")


def check_poll(handle):
    mine = _mine(handle, CHECK)
    if mine is None or mine.state not in OPEN:
        return
    prediction, measured = Path(handle.input("prediction")), Path(handle.input("data"))
    guesses, rows, columns = hooks.read_points(prediction / "rows.jsonl"), hooks.read_points(measured / "rows.jsonl"), _listed(prediction)["columns"]
    actual = {row["point"]: row.get("fields") or {} for row in rows}
    fields = {column["name"]: {guess["point"]: (
        _read(predictor.read_field, measured / actual[guess["point"]][column["name"]]
              if actual.get(guess["point"], {}).get(column["name"]) else None),
        _read(predictor.read_predicted, prediction / guess["fields"][column["name"]]
              if (guess.get("fields") or {}).get(column["name"]) else None)) for guess in guesses}
        for column in columns if column["role"] == predictor.FIELD}
    body = report.check_report(guesses, rows, columns, fields or None)
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
