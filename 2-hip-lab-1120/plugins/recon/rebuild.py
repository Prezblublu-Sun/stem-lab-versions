"""【自由】两半：在操作台进程里把活交给重建方法包；和 5c 以前干活的那一头（自动重建：分骨、外表面、内壁，出皮质和松质两个面）。

在操作台进程里的那一半（接口见 plugin.py 开头：check、begin、advance、halt）：
    begin 把冻结的骨架拼好的 job 写进 <mode>/r<轮号>/ask/job.json，用 hooks.run_recon 起方法包（脱离出去的进程），
    它的输出文件夹是 <mode>/r<轮号>/out/；advance 看它还在不在跑，跑完读它的 result.json；halt 把它停掉。
    启动前自由的那部分检查只剩人工修改写得对不对（review.py）：骨源收不收是方法包的事，跑的时候它说。

干活的那一头（5c 起骨架不再叫它；5d、5e 搬进 CAD、CT 的方法包，搬剩下的 5g 移出隔离）。两种骨源，各走各的路：
    CAD   两个面就是 CAD 里两个实体的表面，不用分骨，实体原样用、不换坐标系
    CT    照 CT 值在参考外形以内分出皮质和内部，出外表面和内壁（ct.py），再变成划得了网格的两个实体（solids.py）。
          分骨不自动做：CT 骨源要带一份股骨的外形，为什么见 ct.py 开头
活在脱离出去的进程里干（读 STEP、划表面三角网要几十秒；CT 一根大约一分钟）：
    python -m plugins.recon.rebuild <活的说明 job.json>
它把走到哪一步写在 stage.txt 里，干完写 result.json。

重建设定里和这里有关的项：
    source            CAD：骨源里哪个文件是哪个实体，{"cortical": "a.STEP", "cancellous": "b.STEP"}
                      CT：{"outer": 外形的文件, "ct": CT 的文件（可不写）}
    tessellation_mm   CAD：表面三角网的最大边长，默认 4
    ct                CT 的各项参数，见 ct.py 和 solids.py 开头，都可以不写
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

from plugins.recon import ct, landmarks, review, solids, sources
from stemlab import hooks

REPO = Path(__file__).resolve().parents[2]
NAMES = ("cortical", "cancellous")


# ---------------------------------------------------------------- 接口（在操作台的进程里）

def _home(handle, mode: str) -> Path:
    return handle.work_dir / mode / f"r{handle.round.number}"


def _desk(handle) -> str:
    return next(machine.name for machine in handle.machines if machine.role == "desk")


def check(handle, mode: str) -> str | None:
    edits = handle.input("edits") if mode == "finalize" else None
    found = review.edit_problems(Path(edits)) if edits is not None else []
    return "人工修改写得不对：" + "；".join(found) if found else None


def begin(handle, mode: str, job: dict) -> None:
    home = _home(handle, mode)
    shutil.rmtree(home, ignore_errors=True)
    (home / "ask").mkdir(parents=True)
    (home / "ask" / "job.json").write_bytes(json.dumps(job, ensure_ascii=False).encode("utf-8"))
    process = hooks.run_recon(handle.input_info("method").id, home / "ask", home / "out", wait=False)
    (home / "process.json").write_bytes(json.dumps(process).encode("utf-8"))


def advance(handle, mode: str) -> dict:
    home = _home(handle, mode)
    view = {"stage": "queued", "machine": _desk(handle), "result": None}
    try:
        process = json.loads((home / "process.json").read_bytes())
    except (OSError, ValueError):
        return dict(view, result={"status": "error", "reason": "方法包的进程没有起来"})
    out = home / "out"
    if hooks.alive(process):
        stage = out / "stage.txt"
        return dict(view, stage=stage.read_text(encoding="utf-8").strip() if stage.exists() else "rebuilding")
    try:
        return dict(view, stage="done", result=json.loads((out / "result.json").read_bytes()))
    except (OSError, ValueError):
        restarted = psutil.boot_time() > process["created"]
        said = (out / "log.txt").read_bytes()[-600:].decode("utf-8", "replace") if (out / "log.txt").exists() else ""
        return dict(view, stage="done", result={"status": "env" if restarted else "error",
                                                "reason": "机器重启过，方法包的进程没了" if restarted else f"方法包没有留下结果：{said}"})


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
    return {name: sources.read_solid(files[name], size) for name in NAMES}


def _mesh_checks(files: dict, setting: dict, stage) -> dict:
    """CT 来的两个实体另外量的几样：皮质有多厚、两个实体在界面上对不对得上；照设定真的划一次四面体，量单元质量。
    不是那种实体就什么都不量。四面体划不成不算重建出错：记下为什么，那几项没有数，检查门里拿它们来比的线自然不过。"""
    surfaces = solids.surfaces_of(files)
    if surfaces is None:
        return {}
    found = solids.wall(surfaces)
    found["surfaces_open_edges"] = solids.open_edges(surfaces["outer"][1]) + solids.open_edges(surfaces["inner"][1])
    how = solids.options(setting)
    if how["tet_check"]:
        stage("tet-check")
        try:
            found.update(solids.tet_check(surfaces, float(how["edge_mm"])))
        except Exception as error:  # noqa: BLE001  gmsh 报什么都记下来
            found["tet_check_problem"] = f"{type(error).__name__}: {error}"[:300]
    return found


def draft_ct(job: dict, stage) -> dict:
    """CT 骨源：ct.py 出两个表面，solids.py 变成两个实体，再照常找标志点、量。"""
    setting, source, home = job["setting"], Path(job["source"]), Path(job["out"])
    made = ct.run(source, setting, home / "surfaces", stage)
    stage("remesh")
    solid = solids.from_surfaces(made["outer"], made["inner"], home / "solids", setting)
    files = solid["files"]
    stage("read")
    meshes = _read(files, setting)
    stage("landmarks")
    found = landmarks.find(meshes["cortical"], setting["side"])
    stage("measure")
    measures = {**made["measures"], **solid["measures"], **measure(meshes, found)}
    for name, mask in (("cortical", "cortex_mask_mm3"), ("cancellous", "interior_mask_mm3")):   # 表面围出的体积和体素数出来的体积差多少
        measures[f"{name}_mesh_volume_error"] = abs(meshes[name]["volume"] - measures[mask]) / measures[mask]
    measures.update(_mesh_checks(files, setting, stage))
    how = solids.options(setting)
    history = made["history"] + [
        {"step": "ct-remesh", "what": f"MeshLab 修复，再等边长重划：外表面 {how['edge_mm']:g} mm，内壁 {how['edge_mm'] * how['inner_factor']:g} mm，"
                                      f"迭代 {how['remesh_iterations']} 次。两个实体：皮质是外表面和内壁之间，松质是内壁以内"},
        {"step": "landmarks", "what": "自动找的五个标志点，定义写在各个点上"}]
    return {"status": "ok", "reason": "", "solids": {name: str(path) for name, path in files.items()},
            "landmarks": found["landmarks"], "measures": measures, "history": history,
            "todo": review.todo(found, measures, made["notes"]), "neck_loop": [[float(v) for v in point] for point in found["neck_loop"]],
            "mesh_quality": {name: sources.quality_histogram(meshes[name]) for name in NAMES}}


def draft(job: dict, stage) -> dict:
    setting, source = job["setting"], Path(job["source"])
    if sources.kind_of(source) == "ct":
        return draft_ct(job, stage)
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
    replaced = {name for name in NAMES if Path(files[name]) != source / listed["solids"][name]["file"]}
    before = listed.get("measures") or {}
    files, said = solids.reconcile(files, replaced, Path(job["out"]) / "solids")       # CT 那种实体只换了一个：另一个跟着重写
    if said:
        history.append({"step": "edit", "what": said})
    elif "ct_file" in before and len(replaced) == 1:   # CT 的骨换了一个实体，却没能照它重写另一个：说出来
        changed = {"cortical": "皮质", "cancellous": "松质"}[next(iter(replaced))]
        history.append({"step": "edit", "what": f"换的是{changed}实体，但它不是 STL 或者块数不对，另一个实体没有照它重写："
                                                f"两个实体在界面上不一定对得上；壁厚、界面间隙、四面体这几项这次量不了，检查门里拿它们比的线不过"})
    stage("read")
    meshes = _read(files, setting)
    stage("landmarks")
    found = landmarks.find(meshes["cortical"], setting["side"])
    stage("measure")
    measures = measure(meshes, found)
    for name in NAMES:                                  # 实体的体积和候选时比变了多少
        old = before.get(f"{name}_volume_mm3")
        measures[f"{name}_volume_change"] = abs(measures[f"{name}_volume_mm3"] - old) / old if old else None
    for name, mask in (("cortical", "cortex_mask_mm3"), ("cancellous", "interior_mask_mm3")):   # CT 的骨：和候选时一样，对的是体素数出来的体积
        if before.get(mask):
            measures[f"{name}_mesh_volume_error"] = abs(meshes[name]["volume"] - before[mask]) / before[mask]
    shifts = {name: math.dist(marks[name]["xyz"], found["landmarks"][name]["xyz"]) for name in found["landmarks"] if name in marks}
    measures["landmark_shift_max_mm"] = max(shifts.values())            # 定稿用的标志点离自动找的最远差多少
    measures.update({f"{name}_shift_mm": value for name, value in shifts.items()})
    measures.update(_mesh_checks(files, setting, stage))
    # 候选的数只照抄定稿不重做、也重做不了的那几样：CT 那一步的；两个实体都没换过时，重划那一步的。
    # 别的（壁厚、界面间隙、四面体……）说的是候选的几何，这次没量成就是没有数，检查门照没有数判，不拿候选的充数
    kept = set(ct.MEASURES) | (set() if replaced else set(solids.REMESH_MEASURES))
    for name in sorted(kept & (set(before) - set(measures))):
        measures[name] = before[name]
    gone = sorted(name for name in set(before) - set(measures) if not name.endswith("_problem"))
    if gone:
        history.append({"step": "measure", "what": "候选时量过、这次没有重量成的几项，不沿用候选的数（那说的是候选的几何）："
                                                   + "、".join(gone[:12]) + (f" 等 {len(gone)} 项" if len(gone) > 12 else "")})
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
