"""在子进程里跑一个带代码的包。包的格式见 contract/formats/package.py。

    run(包的编号, 输入文件夹, 输出文件夹)
    predict、derive、run_strategy、run_kernel、run_stem、run_fem    六个薄封装，各认一种包
    look(实验, 轮)、rerun(...)                    重放用的两个只读的口子：不在一次调用里，也不往记录里写

只能在插件的启动、轮询、停止里用，而且包必须是这个实验存定的一样输入：
这样一个结果用了哪个包，一定追得到。用了哪个包由这里记进这一轮的来历，不靠插件自己报。

跑之前核哈希，对不上不跑。第一次在这台机器上用，先过自检样本，不过不交出结果。
包在自己的子进程里跑：它崩了只是这一次调用出错，不带倒值守。
"""
from __future__ import annotations

import contextvars
import copy
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from stemlab.contract import Refused, chain, hashing, kinds, layout
from stemlab.contract.formats import manifest, package
from stemlab.experiments import log, view
from stemlab.hooks import local
from stemlab.registry import verify

# 现在正在进行的那一次调用的 handle。由 call.py 在叫插件之前放进来、叫完拿走
CURRENT: contextvars.ContextVar = contextvars.ContextVar("stemlab_current_handle", default=None)


def run(package_id: str, input_folder, output_folder, wait: bool = True, timeout: float = 3600.0,
        kind: str | None = None):
    """跑一个带代码的包。包读 input_folder，把结果写进 output_folder（里面必有一个 result.json）。

    wait=True：等它跑完，返回 result.json 的内容；跑出错、超时都是被拒，带着它输出的末尾。
    wait=False：起一个脱离出去的进程就返回（{"pid", "created"}）；插件下一次 poll 用 alive 问它，
    跑完了自己去读 output_folder 里的 result.json。它的输出在 output_folder 的 log.txt 里。
    """
    given = CURRENT.get()
    if given is None:
        raise Refused("带代码的包只能在插件的启动、轮询、停止里跑")
    given._allow_write()                                    # 检查和图表是只读的，不能跑包
    info = given.find_input(package_id)
    if info is None:
        raise Refused(f"{package_id} 不是这个实验存定的输入，不能跑")
    if kinds.ITEM_KINDS[info.kind].form != kinds.PACKAGE or (kind and info.kind != kind):
        raise Refused(f"{package_id} 是 {info.kind}，这里要的是{kind or '一个带代码的包'}")
    folder = given.verified(info)                           # 跑之前核哈希
    listed = manifest.read_manifest(folder)
    _selftest(folder, listed, info, timeout)                # 第一次在这台机器上用，先过自检样本
    _note(given, info)                                      # 用了哪个包记进来历
    return _launch(info.id, folder, listed, Path(input_folder), Path(output_folder), wait, timeout)


def predict(package_id: str, input_folder, output_folder, **how):
    """跑一个预测器。"""
    return run(package_id, input_folder, output_folder, kind="predictor", **how)


def derive(package_id: str, input_folder, output_folder, **how):
    """跑一份推导量定义。"""
    return run(package_id, input_folder, output_folder, kind="derive_def", **how)


def run_strategy(package_id: str, input_folder, output_folder, **how):
    """跑一份策略。"""
    return run(package_id, input_folder, output_folder, kind="strategy", **how)


def run_kernel(package_id: str, input_folder, output_folder, **how):
    """跑内核。"""
    return run(package_id, input_folder, output_folder, kind="kernel", **how)


def run_stem(package_id: str, input_folder, output_folder, **how):
    """跑柄空间包：模板化，或者出柄的模型。"""
    return run(package_id, input_folder, output_folder, kind="stem_space", **how)


def run_fem(package_id: str, input_folder, output_folder, **how):
    """跑有限元包：建模，或者后处理。"""
    return run(package_id, input_folder, output_folder, kind="fem", **how)


def look(experiment: str, number: int | None = None):
    """这个实验某一轮（默认最后一轮）的一份只读 handle。重放和事后核对用：读得到存定的输入，一个字都写不了。

    另带 recorded：这一轮补记的来历（[{"source", "info"}]）。用完叫它的 close()。
    """
    from stemlab.contract import plugin_api
    from stemlab.hooks import handle

    try:
        status = view.view(experiment)
    except (LookupError, ValueError) as error:
        raise Refused(str(error)) from None
    if not status.rounds or status.frozen is None:
        raise Refused(f"{experiment} 还没有启动过")
    chosen = status.rounds[-1] if number is None else next((one for one in status.rounds if one.number == number), None)
    if chosen is None:
        raise Refused(f"{experiment} 没有第 {number} 轮")
    info = plugin_api.RoundInfo(chosen.number, tuple(chosen.rerun), copy.deepcopy(chosen.provenance), chosen.opened)
    given = handle.ReadOnly(experiment, info, status.inputs, status.frozen)
    given.recorded = copy.deepcopy(chosen.extra)
    return given


def rerun(given, package_id: str, input_folder, output_folder, timeout: float = 3600.0) -> dict:
    """重放：把这个实验存定的一个包再跑一遍，等它跑完，返回 result.json 的内容。不往记录里写，也不记来历。

    given 是 look() 给的那一份。包必须是这个实验存定的输入，而且那一轮的来历里记着用过它。
    跑之前照样核哈希、过自检。输出文件夹不能在 data/ 里。
    """
    info = given.find_input(package_id)
    if info is None or kinds.ITEM_KINDS[info.kind].form != kinds.PACKAGE:
        raise Refused(f"{package_id} 不是这个实验存定的一个带代码的包，不能重放")
    if not any(extra["source"] == "package" and extra["info"]["id"] == package_id for extra in given.recorded):
        raise Refused(f"第 {given.round.number} 轮的来历里没有记着用过 {package_id}，没有可重放的")
    target = Path(output_folder).resolve()
    if layout.data_root().resolve() in (target, *target.parents):
        raise Refused("重放的输出不能放在 data/ 里")
    folder = given.verified(info)
    listed = manifest.read_manifest(folder)
    _selftest(folder, listed, info, timeout)
    return _launch(info.id, folder, listed, Path(input_folder), target, True, timeout)


def _launch(package_id: str, folder: Path, listed: dict, source: Path, target: Path, wait: bool, timeout: float):
    command = [sys.executable if part == "{python}" else part for part in listed["entry"]] + [str(source), str(target)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")     # 包在只读的地方跑，不许它往里写缓存
    target.mkdir(parents=True, exist_ok=True)
    (target / package.RESULT).unlink(missing_ok=True)       # 上一次留下的结果不能冒充这一次的
    if not wait:
        return local.spawn(command, cwd=folder, env=env, log=target / "log.txt")
    with open(target / "log.txt", "ab") as output:
        try:
            child = subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=output,
                                     stderr=subprocess.STDOUT, **local.QUIET)
        except OSError as error:
            raise Refused(f"包 {package_id} 起不来：{error}") from None
        try:
            code = child.wait(timeout)
        except subprocess.TimeoutExpired:
            local.end(child.pid)                            # 连同它起的进程一起结束：求解器不能留在后面接着跑
            child.wait()
            raise Refused(f"包 {package_id} 跑了 {timeout} 秒还没完，已经把它和它起的进程都结束了") from None
    if code != 0:
        tail = (target / "log.txt").read_bytes()[-800:].decode("utf-8", "replace").strip()
        raise Refused(f"包 {package_id} 跑出错了（退出码 {code}）：{tail}")
    try:
        return json.loads((target / package.RESULT).read_bytes())
    except (OSError, ValueError) as error:
        raise Refused(f"包 {package_id} 跑完了，但没有留下读得出的 {package.RESULT}：{error}") from None


def _selftest(folder: Path, listed: dict, info, timeout: float) -> None:
    """这个包在这台机器上过没过自检。过了就在这台机器的缓存里留个记号，下次不用再跑。

    记号认的是“这个包、在这台机器、这个环境里”：换了 Python 或者锁文件变了，就重新自检。
    """
    lock = layout.lock_file()
    environment = hashing.hash_json({"host": socket.gethostname(), "python": platform.python_version(),
                                     "lock": hashing.hash_file(lock) if lock.is_file() else None})
    marker = layout.cache_root() / "selftest" / f"{info.hash[:32]}-{environment[:16]}.json"
    if marker.exists():
        return
    for sample in listed["selftest"]:
        with tempfile.TemporaryDirectory() as scratch:
            got = _launch(info.id, folder, listed, folder / sample["input"], Path(scratch) / "out", True, timeout)
        expected = json.loads((folder / sample["expected"]).read_bytes())
        found = package.differences(expected, got, listed["tolerance"])
        if found:
            raise Refused(f"包 {info.id} 在这台机器上的自检没过（样本 {sample['name']}）：" + "；".join(found[:5]))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(hashing.canonical({"package": info.id, "host": socket.gethostname(),
                                          "time": chain.stamp(datetime.now(timezone.utc))}) + b"\n")


def _note(given, info) -> None:
    """用了哪个包记进这一轮的来历。一轮里同一个包只记一次。"""
    current = view.view(given.experiment).rounds[-1]
    if any(extra["source"] == "package" and extra["info"]["id"] == info.id for extra in current.extra):
        return
    log.append(given.experiment, {"entry": "provenance", "round": given.round.number, "source": "package",
                                  "info": {"id": info.id, "hash": info.hash, "kind": info.kind,
                                           "name": info.name, "version": info.version}})


def call_with(given, function):
    """在 given 这次调用里叫 function(given)。call.py 用它，包才知道自己是在哪一次调用里跑的。"""
    token = CURRENT.set(given)
    try:
        return function(given)
    finally:
        CURRENT.reset(token)
