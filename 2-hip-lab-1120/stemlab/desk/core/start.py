"""启动的九步、停止、叫一次轮询。只有这里叫插件的启动、停止、轮询。

每个动作都是“查状态表、记、叫、记结果”，断在哪一步都留下读得懂的记录。
状态只在“结果”上变：停止要等插件真的停成了才生效。
真正跑的插件代码，一定是这一轮的记录里记着的那一份。
"""
from __future__ import annotations

from stemlab.contract import Refused, kinds, layout, plugin_api, states
from stemlab.contract.formats import declaration
from stemlab.contract.formats.manifest import read_manifest
from stemlab.desk.core import code_state, locks
from stemlab.experiments import log, view
from stemlab.hooks import call, load, publish
from stemlab.registry import lookup, verify
from stemlab.registry import reader as register_reader

_STOPPED = "你点了停止"


def _status(experiment: str) -> states.Status:
    try:
        return view.view(experiment)
    except (LookupError, ValueError) as error:
        raise Refused(str(error)) from None


def start(experiment: str, named=()) -> call.Result:
    """启动：开新的一轮。named 是你点名要重排的待查任务。

    前五步只检查，什么都不写；任何一步不过就被拒，记录里不多一条。第 3 步之后另核照声明写的设定（_check_settings）。
    过了第 5 步就一定留下记录：成了是运行中，出错是启动失败，返回里带着报错。
    """
    named = tuple(named)
    with locks.busy(experiment, "start"):
        status = _status(experiment)
        kind, plugin = call.find(status.type)

        rerun = states.rerunnable(status, status.outcomes, named)
        wrong = [task for task in named if task not in rerun]
        if wrong:
            raise Refused(f"点名的任务不能重排（没有这个任务，或者它已经有了结果）：{wrong}")
        why = states.why_not("start", status, plugin_api.actions(kind), named)             # 1 状态表允许启动
        if why:
            raise Refused(why)

        missing = [row["name"] for row in status.inputs                                    # 2 必须的输入都填了
                   if row["required"] and not status.filled.get(row["name"])]
        if missing:
            raise Refused(f"还缺这几样必须的输入：{missing}")

        frozen = _verify_inputs(status)                                                    # 3 每样输入种类对、内容没变
        _check_settings(frozen, status.type, kind)                                         # 3 之后：设定照它的声明核
        provenance, diff = _code_state(status, plugin)                                     # 4 代码的状态

        number = len(status.rounds) + 1
        info = plugin_api.RoundInfo(number, tuple(rerun), provenance)
        why = call.call_check(status.type, experiment, status.inputs, frozen, info)        # 5 叫插件的检查
        if why:
            raise Refused(f"插件的检查没过：{why}")

        if status.frozen is None:                                                          # 6 第一轮：存定输入
            head = register_reader.head()
            log.append(experiment, {"entry": "frozen", "inputs": frozen,
                                    "register_head": {"seq": head.seq, "this": head.this}})
        path = layout.plugin_diff(experiment, number)                                      # 7 开轮。先存差异再记条目
        if diff is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(diff)
        elif path.exists():
            path.unlink()                               # 上次启动断在这一步留下的差异，和这一次无关
        log.append(experiment, {"entry": "round_opened", "round": number, "provenance": provenance, "rerun": rerun})

        result = call.call(status.type, "start", experiment)                               # 8 叫插件的启动
        if result.ok:                                                                      # 9 记结果
            log.append(experiment, {"entry": "called", "round": number, "action": "start", "ok": True, "error": None})
            _reconcile(experiment, number)
            _close_if_said(experiment, number, result)
        else:
            _start_failed(experiment, number, result.error)
        return result


def _verify_inputs(status: states.Status) -> dict:
    """第 3 步。返回每样输入存定用的信息：哈希就是这里核对时算出的那一个，不再算第二次。

    第一轮看填的是什么；之后的轮看存定的那几样，它们现在的内容要和存定时一致。
    """
    frozen = {}
    for row in status.inputs:
        name = row["name"]
        ids = status.filled.get(name, []) if status.frozen is None else [info["id"] for info in status.frozen[name]]
        if len(ids) > 1 and not row["many"]:
            raise Refused(f"输入 {name} 只收一份，现在填了 {len(ids)} 份")
        frozen[name] = []
        for item_id in ids:
            try:
                item = lookup.get(item_id)
            except LookupError as error:
                raise Refused(f"输入 {name}：{error}") from None
            if item["kind"] not in row["kinds"]:
                raise Refused(f"输入 {name} 收的是 {row['kinds']}，{item_id} 是 {item['kind']}")
            try:
                computed = verify.verify_item(item_id)
            except Refused as error:
                raise Refused(f"输入 {name}：{error}") from None
            frozen[name].append({"id": item["id"], "kind": item["kind"], "name": item["name"],
                                 "version": item["version"], "hash": computed, "origin": item["origin"],
                                 "bone_id": item["bone_id"]})
    return frozen


def _check_settings(frozen: dict, type_name: str, kind: plugin_api.Kind) -> None:
    """第 3 步之后：照声明写的设定（新写法），照它照的那份声明核。核的规矩只在契约里（formats/declaration.py）。

    照的声明有两种来处：这个实验填的一个包（of 是包的编号），或者这种实验自己（of 是类型名，比如运行设定）。
    核第 1 到第 5、第 7、第 9 条：照的包这个实验填了（或者就是这种实验）、里面有这份声明、哈希对；值都对；
    现在的轮都是正式的；来路都写了。
    第 6 条（每个点给的项）要对着一批点、第 8 条（名字引用）要对着骨模型和柄的模型，由这种实验的骨架核。
    老写法的设定（随意的 JSON）不核。不合就被拒，说出是哪一样输入、哪一项、哪一条；什么都没写下。
    """
    filled = {info["id"] for infos in frozen.values() for info in infos}
    for name, infos in frozen.items():
        for info in infos:
            if info["kind"] != "setting":
                continue
            value = lookup.get(info["id"])["content"]
            if not declaration.is_declared(value):
                continue
            said = value["declaration"] if isinstance(value["declaration"], dict) else {}
            of, wanted = said.get("of"), said.get("name")
            title = f"输入 {name}（{info['id']}）"
            if of == type_name:
                found = plugin_api.declared(kind, wanted)
                if found is None:
                    raise Refused(f"{title}照的是 {of} 这种实验里叫 {wanted!r} 的声明，它没有声明这一份（规则 1：{declaration.RULES[1]}）")
            elif of not in filled:
                raise Refused(f"{title}是照 {of!r} 的声明写的，这个实验没有填它（规则 1：{declaration.RULES[1]}）")
            else:
                item = lookup.get(of)
                listed = read_manifest(lookup.content(of)) if kinds.ITEM_KINDS[item["kind"]].form == kinds.PACKAGE else {}
                found = declaration.find(listed.get("declarations"), wanted)
                if found is None:
                    raise Refused(f"{title}照的是 {of} 里叫 {wanted!r} 的声明，{of} 里没有它（规则 1：{declaration.RULES[1]}）")
            problems = declaration.check_setting(value, found, of=of, use="formal")
            if problems:
                raise Refused(f"{title}不合它的声明：" + "；".join(problems))


def _code_state(status: states.Status, plugin: str) -> tuple[dict, bytes | None]:
    """第 4 步。返回这一轮的来历和插件没提交的改动。

    契约、核心、插件的冻结文件有改动就不行；插件自由的部分带着没提交的改动可以启动，来历里写明。
    记下的插件哈希必须是这个进程里真正装着的那一份。
    """
    problems = code_state.frozen_ok()
    if problems:
        raise Refused("固定的文件和 FROZEN 清单对不上：" + "；".join(problems))
    dirty = code_state.clean(code_state.CORE)
    if dirty:
        raise Refused("契约和核心有没提交的改动，先提交：" + "、".join(dirty))
    try:
        provenance, diff = code_state.snapshot(plugin)
    except RuntimeError as error:
        raise Refused(str(error)) from None
    if load.imported(plugin) != provenance["plugin_hash"]:
        raise Refused("插件的代码在这个进程装上它之后又变了：记下的哈希会不是真正跑的那一份。再启动一次")
    if status.rounds and status.rounds[-1].provenance["frozen"] != provenance["frozen"]:
        raise Refused("FROZEN 清单和上一轮不一样了：固定的代码变过，这个实验不能再开新的一轮。克隆一个新实验来跑")
    return provenance, diff


def _reconcile(experiment: str, number: int) -> None:
    """对一次账。对不上账不该拦着这一轮收尾：记成问题，接着往下走，检查会再报出来。"""
    try:
        publish.reconcile(experiment)
    except Refused as error:
        log.append(experiment, {"entry": "problem", "round": number, "error": f"对账没做完：{error}",
                                "task": None, "raw": None})


def _close_if_said(experiment: str, number: int, result: call.Result) -> None:
    """插件说了做完或做不下去：动作返回之后，在这里把这一轮记成结束。"""
    if result.said:
        log.append(experiment, {"entry": "round_closed", "round": number, "result": result.said[0],
                                "reason": result.said[1]})


def _start_failed(experiment: str, number: int, reason: str) -> None:
    called = {"entry": "called", "round": number, "action": "start", "ok": False, "error": reason}
    if states.refuse(view.view(experiment), called) is None:        # 启动的结果还没记过才记
        log.append(experiment, called)
    _reconcile(experiment, number)                                  # 启动里交到一半的产物，先接着做完再收尾
    log.append(experiment, {"entry": "round_closed", "round": number, "result": states.START_FAILED, "reason": reason})


def stop(experiment: str) -> call.Result:
    """停止。插件停成了才记；没停成，实验还是运行中，多一条问题，可以再停一次。"""
    with locks.busy(experiment, "stop"):
        status = _status(experiment)
        kind, _ = call.find(status.type)
        why = states.why_not("stop", status, plugin_api.actions(kind))
        if why:
            raise Refused(why)
        number = status.rounds[-1].number
        result = call.call(status.type, "stop", experiment)        # 代码在这一轮中途换了也照样停：见 call._same_code
        if result.ok:
            _reconcile(experiment, number)
            log.append(experiment, {"entry": "called", "round": number, "action": "stop", "ok": True, "error": None})
            log.append(experiment, {"entry": "round_closed", "round": number, "result": states.STOPPED,
                                    "reason": _STOPPED})
        return result


def poll(experiment: str, wait: bool = True) -> call.Result | None:
    """照看这个实验一次：运行中的叫一次插件的轮询，然后对一次账；启动中而没有别处在启动它的，收成启动失败。

    wait=False 是值守的用法：别处正在动这个实验就跳过（被拒）。没什么可做的返回 None。
    """
    with locks.busy(experiment, "poll", timeout=30.0 if wait else 0.0):
        status = _status(experiment)
        if states.can("poll", status):
            number = status.rounds[-1].number
            closing = {"entry": "round_closed", "round": number, "result": states.STOPPED, "reason": _STOPPED}
            if states.refuse(status, closing) is None:
                # 上次停止已经停成了，只差收尾（记下停成之后进程没了）：补上收尾，不再去叫插件
                _reconcile(experiment, number)
                log.append(experiment, closing)
                return None
            result = call.call(status.type, "poll", experiment)       # 代码在这一轮中途换了，在这里被拒：见 call._same_code
            _reconcile(experiment, number)
            if result.ok:
                _close_if_said(experiment, number, result)
            return result
        if states.can("start_error", status):
            # 我们拿到了 busy，所以没有别处在启动它：做启动的那个进程已经不在了
            _start_failed(experiment, status.rounds[-1].number, "启动到一半，做启动的进程不在了")
        return None
