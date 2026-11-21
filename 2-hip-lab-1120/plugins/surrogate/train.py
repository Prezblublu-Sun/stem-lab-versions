"""【自由】一次训练。种子从训练设定里读。

两头都在这个文件里：
    操作台这一头   check、begin、advance、halt：把活派出去、看它干到哪了。机器清单里有 worker 就派到那台（Linux），
                   没有就在本机起一个脱离出去的进程。两种走的是同一个 worker.py
    干活的那一头   run(job, out, report)：读训练的行、拟合、打包、给留出的点出预测

插件交过来的作业文件夹（job）里：
    job.json      seed、targets（要预测的量）、level、scale、setting（训练设定原样）、columns（数据说明，不含场）、
                  target_columns（要预测的各列的说明）、scope（适用范围，冻结代码照训练那一部分定好的）、
                  made_by（训练数据是哪个内核算的，原样交给打包，写进预测器的清单；不知道就是 null）；
                  要预测场的另有 fields（场的名字）、field_columns（它们的说明）、field_shapes（各自的形状）
    train.jsonl   训练的各行。要预测场的，行里的 fields 写着这一行的场在 job 里的哪个文件（.npy）
    fields/       训练各行的场。留出的点的场不在这里
    ask.jsonl     留出和往外推的点：只有哈希、骨标识、设计和条件
交回去的（outputs/）：package/（预测器的包）、asked.jsonl（对 ask 里各点的预测）、result.json；
    预测了场的，每个点的场写在 asked_fields/<点的哈希>/<场的名字>.npy（值、下界、上界摞在一起），asked.jsonl 的行里写着位置
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

from plugins.surrogate import features, models, predictor
from stemlab import hooks

REPO = Path(__file__).resolve().parents[2]
WORKER = "plugins.surrogate.worker"
STALE = 300.0                   # worker 这么多秒没有心跳，就当它没了


# ---------------------------------------------------------------- 操作台这一头

def _home(handle) -> Path:
    return handle.work_dir / "train" / f"r{handle.round.number}"


def _remote(handle) -> str | None:
    return next((machine.name for machine in handle.machines if machine.role == "worker"), None)


def _here(handle) -> str:
    return next(machine.name for machine in handle.machines if machine.role == "desk")


def check(handle) -> str | None:
    setting = handle.input("setting")
    options = setting.get("model", {})
    name = options.get("name", models.DEFAULT) if isinstance(options, dict) else None
    if name not in models.names():
        return f"训练设定的 model.name 只有 {models.names()}：{name!r}"
    if setting.get("fields") and not getattr(models.get(name)[0], "FIELDS", False):
        able = [one for one in models.names() if getattr(models.get(one)[0], "FIELDS", False)]
        return f"训练设定要预测场，可是模型 {name} 只会预测标量。会预测场的模型：{able}"
    return None


def begin(handle, job: Path) -> None:
    home, machine = _home(handle), _remote(handle)
    home.mkdir(parents=True, exist_ok=True)
    if machine is not None:
        hooks.remote.push(handle, machine, {"job": job})
        hooks.remote.start(handle, machine, WORKER)
        state = {"machine": machine}
    else:
        base = home / "local"
        shutil.rmtree(base, ignore_errors=True)
        (base / "inputs").mkdir(parents=True)
        shutil.copytree(job, base / "inputs" / "job")
        process = hooks.spawn([sys.executable, "-m", WORKER, str(base)], cwd=REPO, log=base / "log.txt",
                              env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
        state = {"machine": None, "process": process, "base": str(base)}
    (home / "state.json").write_bytes(json.dumps(state).encode("utf-8"))


def _result(outputs: Path) -> dict:
    try:
        said = json.loads((outputs / "result.json").read_bytes())
    except (OSError, ValueError):
        return {"status": "error", "reason": "worker 结束了，但没有留下读得出的结果"}
    if said.get("status") == "ok":
        said.update(package=str(outputs / "package"), asked=str(outputs / "asked.jsonl"))
    return said


def advance(handle) -> dict:
    home = _home(handle)
    try:
        state = json.loads((home / "state.json").read_bytes())
    except (OSError, ValueError):
        return {"stage": "done", "machine": _here(handle), "result": {"status": "error", "reason": "训练没有派出去"}}
    if state["machine"] is not None:
        view = {"stage": "starting", "machine": state["machine"], "result": None}
        try:
            status = hooks.remote.status(handle, state["machine"])
            if status is None:
                return view
            if status.get("result") is None:
                if status["age"] > STALE:
                    return dict(view, stage="done", result={"status": "env", "reason": f"worker 已经 {status['age']:.0f} 秒没有心跳了"})
                return dict(view, stage=status["stage"])
            return dict(view, stage="done", result=_result(hooks.remote.pull(handle, state["machine"], "trained")))
        except hooks.remote.Unreachable:
            return dict(view, stage="unreachable")      # 连不上不是任务失败：这一遍先不动，下一遍再试
    view, base = {"stage": "starting", "machine": _here(handle), "result": None}, Path(state["base"])
    if hooks.alive(state["process"]):
        try:
            return dict(view, stage=json.loads((base / "status.json").read_bytes())["stage"])
        except (OSError, ValueError, KeyError):
            return view
    found = _result(base / "outputs")
    if found["status"] == "error" and "没有留下" in found["reason"] and (base / "log.txt").exists():
        found["reason"] += "：" + (base / "log.txt").read_bytes()[-600:].decode("utf-8", "replace")
    return dict(view, stage="done", result=found)


def halt(handle) -> None:
    try:
        state = json.loads((_home(handle) / "state.json").read_bytes())
    except (OSError, ValueError):
        return
    if state["machine"] is not None:
        hooks.remote.stop(handle, state["machine"])
    else:
        hooks.kill(state["process"])


# ---------------------------------------------------------------- 干活的那一头

def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def run(job: Path, out: Path, report) -> dict:
    """做一次训练。report(阶段) 用来报走到哪了。返回写进 result.json 的内容。"""
    asked = json.loads((job / "job.json").read_bytes())
    targets, scales, level, seed = asked["targets"], asked["scale"], asked["level"], asked["seed"]
    options = dict(asked["setting"].get("model") or {})
    name = options.pop("name", models.DEFAULT)
    wanted, shapes = asked.get("fields") or [], asked.get("field_shapes") or {}
    rows = _lines(job / "train.jsonl")
    kept = features.usable(rows, targets, scales, wanted)
    if len(kept) < 3:
        raise ValueError(f"训练那一部分里，要预测的量都有数的行只有 {len(kept)} 行，不够训练")
    points = [predictor.as_point(row, asked["columns"]) for row in kept]
    described = features.spec(points)
    model, infer, infer_file = models.get(name)
    report("training")
    extra = {"fields": {field: np.stack([np.load(job / row["fields"][field], allow_pickle=False) for row in kept])
                        for field in wanted}} if wanted else {}
    weights, meta, history = model.fit(points, features.targets(kept, targets, scales), described, options, seed, level, **extra)
    meta = dict(meta, model=name, features=described, scale={target: scales.get(target, "linear") for target in targets}, seed=seed)
    report("packing")
    predictor.pack(out / "package", infer=infer_file, weights=weights, meta=meta, columns=asked["target_columns"], level=level,
                   scope=asked["scope"], samples=points[:5], fields=asked.get("field_columns") or (), shapes=shapes or None,
                   made_by=asked.get("made_by"))
    report("predicting")                                # 留出和往外推的点。往外推的本来就在适用范围外面，所以不经包的入口，直接叫推理代码
    unknown = [predictor.as_point(row, asked["columns"]) for row in _lines(job / "ask.jsonl")]
    told = dict(meta, targets=targets, **({"fields": wanted, "field_shapes": shapes} if wanted else {}))
    guesses = infer.predict(weights, told, unknown) if unknown else []
    with open(out / "asked.jsonl", "w", encoding="utf-8", newline="\n") as stream:
        for point, guess in zip(unknown, guesses, strict=True):
            placed = {}
            for field, stacked in (guess.pop("fields", None) or {}).items():       # 预测的场写成文件，行里只记位置
                placed[field] = f"asked_fields/{point['hash']}/{field}.npy"
                predictor.write_field(out / placed[field], stacked)
            stream.write(json.dumps(dict(guess, point=point["hash"], bone_id=point["bone_id"], **({"fields": placed} if wanted else {}))) + "\n")
    return {"status": "ok", "reason": "", "history": history, "rows_used": len(kept), "rows_without_numbers": len(rows) - len(kept),
            "model": dict({key: value for key, value in meta.items() if key not in ("features",)}, options=options)}
