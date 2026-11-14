"""【自由】自动重建：分骨、外表面、内壁，出皮质和松质两个面。

1.0 只做 CAD 骨源：两个面就是 CAD 里两个实体的表面，不用分骨，实体原样用、不换坐标系。
CT 骨源认得出来（sources.kind_of），检查时就说明白 1.0 不重建它。

接口见 plugin.py 开头：check、begin、advance、halt。活在脱离出去的进程里干（读 STEP、划表面三角网要几十秒）：
    python -m plugins.recon.rebuild <活的说明 job.json>
它把走到哪一步写在 stage.txt 里，干完写 result.json。

重建设定里和这里有关的项：
    source            骨源里哪个文件是哪个实体：{"cortical": "a.STEP", "cancellous": "b.STEP"}
    tessellation_mm   表面三角网的最大边长，默认 4
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import psutil

from plugins.recon import landmarks, review, solids, sources
from stemlab import hooks

REPO = Path(__file__).resolve().parents[2]
NAMES = ("cortical", "cancellous")


# ---------------------------------------------------------------- 接口（在操作台的进程里）

def _home(handle, mode: str) -> Path:
    return handle.work_dir / mode / f"r{handle.round.number}"


def _desk(handle) -> str:
    return next(machine.name for machine in handle.machines if machine.role == "desk")


def check(handle, mode: str) -> str | None:
    setting = handle.input("setting")
    if mode == "draft":
        folder = Path(handle.input("source"))
        kind = sources.kind_of(folder)
        if kind == "ct":
            return "这份骨源是 CT。1.0 只重建 CAD 骨源（两个 STEP 实体）；CT 的自动重建不在 1.0 里"
        if kind != "cad":
            return "认不出这份骨源：里面没有 STEP 文件"
        files = setting.get("source")
        if not isinstance(files, dict) or set(files) != set(NAMES):
            return f"重建设定的 source 要说骨源里哪个文件是哪个实体：{list(NAMES)}"
        missing = [files[name] for name in NAMES if not (folder / str(files[name])).is_file()]
        return f"骨源里没有重建设定说的文件：{missing}" if missing else None
    edits = handle.input("edits")
    found = review.edit_problems(Path(edits)) if edits is not None else []
    return "人工修改写得不对：" + "；".join(found) if found else None


def begin(handle, mode: str) -> None:
    home = _home(handle, mode)
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    job = {"mode": mode, "setting": handle.input("setting"), "out": str(home)}
    if mode == "draft":
        job["source"] = str(handle.input("source"))
    else:
        edits = handle.input("edits")
        job.update(draft=str(handle.input("draft")), edits=None if edits is None else str(edits))
    (home / "job.json").write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
    process = hooks.spawn([sys.executable, "-m", "plugins.recon.rebuild", str(home / "job.json")], cwd=REPO,
                          env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"), log=home / "log.txt")
    (home / "process.json").write_bytes(json.dumps(process).encode("utf-8"))


def advance(handle, mode: str) -> dict:
    home = _home(handle, mode)
    view = {"stage": "queued", "machine": _desk(handle), "result": None}
    try:
        process = json.loads((home / "process.json").read_bytes())
    except (OSError, ValueError):
        return dict(view, result={"status": "error", "reason": "重建的进程没有起来"})
    if hooks.alive(process):
        stage = home / "stage.txt"
        return dict(view, stage=stage.read_text(encoding="utf-8").strip() if stage.exists() else "starting")
    try:
        return dict(view, stage="done", result=json.loads((home / "result.json").read_bytes()))
    except (OSError, ValueError):
        restarted = psutil.boot_time() > process["created"]
        said = (home / "log.txt").read_bytes()[-600:].decode("utf-8", "replace") if (home / "log.txt").exists() else ""
        return dict(view, stage="done", result={"status": "env" if restarted else "error",
                                                "reason": "机器重启过，重建的进程没了" if restarted else f"重建的进程没有留下结果：{said}"})


def halt(handle, mode: str) -> None:
    try:
        hooks.kill(json.loads((_home(handle, mode) / "process.json").read_bytes()))
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- 干活的那一头（脱离出去的进程）

def measure(meshes: dict, found: dict) -> dict:
    """量出来的数：体积、三角网封不封闭、标志点那几项、股骨颈最细处的皮质厚度。"""
    measures = dict(found["measures"])
    for name in NAMES:
        mesh = meshes[name]
        measures[f"{name}_volume_mm3"] = mesh["volume"]
        measures[f"{name}_solids"] = mesh["solids"]
        measures[f"{name}_watertight"] = sources.watertight(mesh)
        measures[f"{name}_mesh_volume_error"] = abs(sources.enclosed_volume(mesh) - mesh["volume"]) / mesh["volume"]
        measures[f"{name}_mesh_quality_min"] = float(sources.quality(mesh).min())
    neck = [point["xyz"] for point in (found["landmarks"]["neck_center"],)][0]
    wall = landmarks.wall_thickness(meshes["cortical"], neck, found["neck_axis"], neck)
    if wall is not None:
        measures.update(neck_wall_min_mm=wall["min_mm"], neck_wall_median_mm=wall["median_mm"])
    measures["neck_axis_converged"] = found["neck_converged"]
    return measures


def _read(files: dict, setting: dict) -> dict:
    size = float(setting.get("tessellation_mm", 4.0))
    return {name: sources.read_step(files[name], size) for name in NAMES}


def draft(job: dict, stage) -> dict:
    setting, source = job["setting"], Path(job["source"])
    files = solids.from_cad(source, setting["source"])
    stage("read")
    meshes = _read(files, setting)
    stage("landmarks")
    found = landmarks.find(meshes["cortical"], setting["side"])
    stage("measure")
    measures = measure(meshes, found)
    history = [{"step": "import", "what": f"CAD 骨源：皮质 {setting['source']['cortical']}，松质 {setting['source']['cancellous']}。"
                                          "两个实体原样用，不换坐标系"},
               {"step": "landmarks", "what": "自动找的五个标志点，定义写在各个点上"}]
    return {"status": "ok", "reason": "", "solids": {name: str(path) for name, path in files.items()},
            "landmarks": found["landmarks"], "measures": measures, "history": history,
            "todo": review.todo(found, measures), "neck_loop": [[float(v) for v in point] for point in found["neck_loop"]],
            "mesh_quality": {name: sources.quality_histogram(meshes[name]) for name in NAMES}}


def finalize(job: dict, stage) -> dict:
    setting, source = job["setting"], Path(job["draft"])
    listed = json.loads((source / "manifest.json").read_bytes())
    stage("edits")
    files, marks, history = review.apply(listed, source, None if job["edits"] is None else Path(job["edits"]))
    stage("read")
    meshes = _read(files, setting)
    stage("landmarks")
    found = landmarks.find(meshes["cortical"], setting["side"])
    stage("measure")
    measures = measure(meshes, found)
    before = listed.get("measures") or {}
    for name in NAMES:                                  # 实体的体积和候选时比变了多少
        old = before.get(f"{name}_volume_mm3")
        measures[f"{name}_volume_change"] = abs(measures[f"{name}_volume_mm3"] - old) / old if old else None
    shifts = {name: math.dist(marks[name]["xyz"], found["landmarks"][name]["xyz"]) for name in found["landmarks"] if name in marks}
    measures["landmark_shift_max_mm"] = max(shifts.values())            # 定稿用的标志点离自动找的最远差多少
    measures.update({f"{name}_shift_mm": value for name, value in shifts.items()})
    return {"status": "ok", "reason": "", "solids": {name: str(path) for name, path in files.items()},
            "landmarks": marks, "measures": measures, "history": history, "todo": [],
            "mesh_quality": {name: sources.quality_histogram(meshes[name]) for name in NAMES}}


def main(argv=None) -> int:
    job = json.loads(Path((argv or sys.argv[1:])[0]).read_bytes())
    home = Path(job["out"])
    timings, began = {}, [time.time(), "start"]

    def stage(name: str) -> None:
        timings[began[1]] = round(time.time() - began[0], 3)
        began[:] = [time.time(), name]
        (home / "stage.txt").write_text(name, encoding="utf-8")

    try:
        result = (draft if job["mode"] == "draft" else finalize)(job, stage)
    except MemoryError as error:
        result = {"status": "env", "reason": f"内存不够：{error}"}
    except Exception as error:  # noqa: BLE001  重建出什么错都说出来
        result = {"status": "error", "reason": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1500:]}
    stage("done")
    timings.pop("start", None)
    result["timings"] = timings
    spare = home / "result.json.new"
    spare.write_bytes(json.dumps(result, ensure_ascii=False, default=float).encode("utf-8"))
    os.replace(spare, home / "result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
