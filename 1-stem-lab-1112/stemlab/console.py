"""操作台（命令行）。

帮你操作实验，并把每次操作记进实验记录。
它不认识任何具体的插件：新建、启动、停止都是通过挂点去叫插件。
看实验（show、list）只读记录，插件没装上也能看。
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

from . import plugins as hooks
from .record import (
    FINISHED,
    NOT_STARTED,
    PAUSED,
    RECORD_FILE,
    RUNNING,
    STOPPED,
    TASK_STATES,
    Busy,
    Experiment,
    RecordError,
    Store,
)

CODE_DIR = Path(__file__).resolve().parent.parent

# 每种操作在实验是什么状态时能做，以及叫插件的哪个挂点
OP_FROM = {
    "启动": (NOT_STARTED,),
    "暂停": (RUNNING,),
    "继续": (PAUSED,),
    "停止": (RUNNING, PAUSED),
    "重试": (STOPPED, FINISHED),
}
OP_HOOK = {"启动": "start", "暂停": "pause", "继续": "resume", "停止": "stop", "重试": "retry"}


def parse_value(text: str):
    """手填的一个值：能当 JSON 读就当 JSON，否则当文字。"""
    try:
        return json.loads(text)
    except ValueError:
        return text


def code_version() -> dict:
    """地基代码现在是哪个提交。"""
    def git(*args):
        try:
            out = subprocess.run(
                ["git", "-C", str(CODE_DIR), *args], capture_output=True, text=True, timeout=20
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    commit = git("rev-parse", "HEAD")
    if not commit:
        return {"code_commit": "没有提交", "code_dirty": None}
    return {"code_commit": commit, "code_dirty": bool(git("status", "--porcelain"))}


class Desk:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.store = Store(self.home)
        self.plugins, self.plugin_errors = hooks.load_plugins(hooks.plugin_dirs(self.home))
        self.refresh_errors: dict[str, str] = {}  # 上一次刷新时，哪个实验的记录读不了
        self._rows: dict[str, tuple] = {}

    # ---- 找插件 -------------------------------------------------------

    def _plugin(self, name: str):
        if name not in self.plugins:
            raise RecordError(f"插件「{name}」没装上。装着的有：{'、'.join(self.plugins) or '（无）'}")
        return self.plugins[name]

    def _plugin_of(self, exp: Experiment):
        name = exp.view()["plugin"]["name"]
        if name not in self.plugins:
            raise RecordError(f"{exp.id} 用的插件「{name}」现在没装上，这个实验只能看，不能操作。")
        return self.plugins[name][0]

    # ---- 新建、填设置 --------------------------------------------------

    def new(self, plugin_name: str, note: str = "", tags: list[str] | None = None) -> str:
        plugin, folder = self._plugin(plugin_name)
        exp = self.store.create(hooks.describe(plugin, folder), note=note, tags=tags)
        return exp.id

    def set(
        self,
        exp_id: str,
        name: str,
        value=None,
        file: str | None = None,
        ref: str | None = None,
        from_exp: str | None = None,
        output: str | None = None,
        source: str = "",
        when: str = "",
    ) -> None:
        exp = self.store.open(exp_id)
        plugin = self._plugin_of(exp)
        wanted = [s.name for s in plugin.settings]
        if name not in wanted:
            raise RecordError(f"插件「{plugin.name}」没有叫「{name}」的设置。它要的是：{'、'.join(wanted)}")
        given = [x is not None for x in (value, file, ref, from_exp)]
        if sum(given) != 1:
            raise RecordError("内容要给且只给一种：一个值、一个要复制进来的文件、一个只记位置的文件，或另一个实验的产出。")
        if from_exp is not None:
            if not output:
                raise RecordError("用另一个实验的产出时，要说是它的哪一项产出。")
            path, sha = self.store.open(from_exp).output_path(output)
            content = {"kind": "位置", "path": str(path), "expected_sha256": sha}
            src = {"kind": "实验产出", "experiment": from_exp, "output": output}
        else:
            if value is not None:
                content = {"kind": "值", "value": value}
            elif file is not None:
                content = {"kind": "复制", "path": str(Path(file).resolve())}
            else:
                content = {"kind": "位置", "path": str(Path(ref).resolve())}
            src = {"kind": "其他来源", "from": source, "when": when}
        with exp.busy():
            exp.set_setting(name, content, src)

    def note(self, exp_id: str, text: str) -> None:
        self.store.open(exp_id).append("备注", {"text": text})

    def tag(self, exp_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        self.store.open(exp_id).append("标签", {"add": list(add or []), "remove": list(remove or [])})

    # ---- 操作 ---------------------------------------------------------

    # 每个操作都把「查状态、记操作、叫插件」整个放在 exp.busy() 里：
    # 网页、命令行、定时值守同时动同一个实验时，一次只有一处进得去，不会重复叫插件。

    def _operate(self, exp_id: str, op: str) -> bool:
        exp = self.store.open(exp_id)
        plugin = self._plugin_of(exp)
        with exp.busy():
            status = exp.view()["status"]
            if status not in OP_FROM[op]:
                raise RecordError(f"{exp_id} 现在是「{status}」，不能{op}。")
            exp.append("操作", {"op": op})
            return hooks.call(plugin, OP_HOOK[op], exp)

    def start(self, exp_id: str) -> bool:
        exp = self.store.open(exp_id)
        plugin = self._plugin_of(exp)
        with exp.busy():
            view = exp.view()
            if view["status"] not in OP_FROM["启动"]:
                raise RecordError(f"{exp_id} 现在是「{view['status']}」，不能启动。")
            missing = [s.name for s in plugin.settings if s.required and s.name not in view["settings"]]
            if missing:
                raise RecordError(f"{exp_id} 还有设置没填：{'、'.join(missing)}")
            exp.freeze_settings()
            _, folder = self.plugins[plugin.name]
            exp.provenance(
                machine=socket.gethostname(),
                python=platform.python_version(),
                plugin_at_start=hooks.describe(plugin, folder),
                **code_version(),
            )
            exp.append("操作", {"op": "启动"})
            return hooks.call(plugin, OP_HOOK["启动"], exp)

    def pause(self, exp_id: str) -> bool:
        return self._operate(exp_id, "暂停")

    def resume(self, exp_id: str) -> bool:
        return self._operate(exp_id, "继续")

    def stop(self, exp_id: str) -> bool:
        return self._operate(exp_id, "停止")

    def retry(self, exp_id: str) -> bool:
        return self._operate(exp_id, "重试")

    def refresh(self, exp_id: str | None = None) -> list[str]:
        """叫插件看一眼任务走到哪了。不给编号就看所有运行中的实验。

        一个实验出问题，不拦别的。别处正在动的实验这次跳过。返回这次看过的实验。
        """
        done = []
        self.refresh_errors = {}
        for one in [exp_id] if exp_id else self.store.ids():
            if exp_id:
                exp = self.store.open(one)
            else:
                exp = Experiment(self.store, one)
            try:
                view = exp.view()
                if view["status"] != RUNNING:
                    continue
                name = view["plugin"]["name"]
                if name not in self.plugins:
                    continue
                with exp.busy(wait=0):
                    if exp.view()["status"] != RUNNING:  # 等锁的工夫被别处暂停或停止了
                        continue
                    hooks.call(self.plugins[name][0], "poll", exp)
                done.append(one)
            except Busy:
                continue
            except (OSError, ValueError, KeyError) as err:  # 这个实验的记录读不了：记下，接着看别的
                self.refresh_errors[one] = f"{type(err).__name__}: {err}"
        return done

    # ---- 给网页用的读法：和 show、list、plugins 是同样的内容，只是不排成文字 ----

    def rows(self) -> list[dict]:
        """所有实验，一个一行。记录文件没变就用上次算好的。"""
        rows = []
        for exp_id in self.store.ids():
            path = self.store.root / exp_id / RECORD_FILE
            try:
                stat = path.stat()
                key = (stat.st_mtime_ns, stat.st_size)
                cached = self._rows.get(exp_id)
                if cached and cached[0] == key:
                    rows.append(cached[1])
                    continue
                v = Experiment(self.store, exp_id).view()
            except (OSError, ValueError, KeyError) as err:
                rows.append({"id": exp_id, "status": "读不出来", "error": f"{type(err).__name__}: {err}"})
                continue
            states = [t["state"] for t in v["tasks"].values()]
            row = {
                "id": exp_id,
                "status": v["status"],
                "plugin": v["plugin"],
                "note": v["note"],
                "tags": v["tags"],
                "created": v["created"],
                "updated": v["updated"],
                "counts": {s: states.count(s) for s in TASK_STATES if s in states},
                "problems": len(v["problems"]),
                "outputs": list(dict.fromkeys(o["name"] for o in v["outputs"])),
            }
            self._rows[exp_id] = (key, row)
            rows.append(row)
        return rows

    def detail(self, exp_id: str) -> dict:
        """一个实验的九项，加上现在能对它做什么。"""
        v = self.store.open(exp_id).view()
        name = v["plugin"].get("name")
        installed = name in self.plugins
        v["plugin_installed"] = installed
        v["can"] = [op for op, allowed in OP_FROM.items() if installed and v["status"] in allowed]
        v["can_refresh"] = installed and v["status"] == RUNNING
        v["wanted"] = (
            [{"name": s.name, "required": s.required, "what": s.what} for s in self.plugins[name][0].settings]
            if installed
            else []
        )
        return v

    def plugin_info(self) -> list[dict]:
        """装着的插件各报的四样。"""
        return [
            {
                "name": p.name,
                "version": p.version,
                "category": p.category,
                "what": p.what,
                "folder": str(folder),
                "settings": [{"name": s.name, "required": s.required, "what": s.what} for s in p.settings],
                "hooks": hooks.hooks_filled(p),
                "outputs": [{"name": o.name, "what": o.what} for o in p.outputs],
            }
            for p, folder in self.plugins.values()
        ]

    def check_all(self, exp_id: str | None = None) -> list[dict]:
        """核对记录有没有被改过。每个实验一条，found 为空表示完好。"""
        out = []
        for one in [exp_id] if exp_id else self.store.ids():
            try:
                out.append({"id": one, "found": self.store.open(one).check()})
            except OSError as err:
                out.append({"id": one, "found": [f"读不了：{err}"]})
        return out

    # ---- 看 -----------------------------------------------------------

    def show(self, exp_id: str) -> str:
        return format_view(self.store.open(exp_id).view())

    def list(self) -> str:
        rows = []
        for exp_id in self.store.ids():
            v = self.store.open(exp_id).view()
            states = [t["state"] for t in v["tasks"].values()]
            counts = "　".join(f"{s} {states.count(s)}" for s in dict.fromkeys(states)) or "没有任务"
            p = v["plugin"]
            rows.append(
                f"{exp_id}　{v['status']}　{p['name']} {p['version']}（{p['category']}）　"
                f"{counts}　问题 {len(v['problems'])}　{v['note']}"
            )
        return "\n".join(rows) if rows else "还没有实验。"

    def list_plugins(self) -> str:
        lines = []
        for name, (p, folder) in self.plugins.items():
            lines.append(f"{name} {p.version}（类别：{p.category}）　{p.what}")
            lines.append(f"  位置　{folder}")
            for s in p.settings:
                lines.append(f"  设置　{s.name}（{'必填' if s.required else '可以不填'}）　{s.what}")
            for o in p.outputs:
                lines.append(f"  产出　{o.name}　{o.what}")
        for err in self.plugin_errors:
            lines.append(f"装不上：{err}")
        return "\n".join(lines) if lines else "没有装任何插件。"

    def check(self, exp_id: str | None = None) -> str:
        lines = [
            f"{c['id']}　" + ("记录完好" if not c["found"] else "；".join(c["found"]))
            for c in self.check_all(exp_id)
        ]
        return "\n".join(lines) if lines else "还没有实验。"


def _short(sha: str | None) -> str:
    return (sha or "")[:10]


def _clock(iso: str) -> str:
    return iso[:19].replace("T", " ")


def format_view(v: dict) -> str:
    """把一个实验的九项排成给人看的文字。"""
    p = v["plugin"]
    out = [f"实验 {v['id']}　状态：{v['status']}", ""]
    out.append(f"1 编号　{v['id']}")
    out.append(
        f"2 插件　{p.get('name')} {p.get('version')}（类别：{p.get('category')}）　文件哈希 {_short(p.get('files_sha256'))}"
    )
    out.append(f"3 说明　{v['note'] or '（没写）'}")
    for n in v["notes"]:
        out.append(f"  　备注　{_clock(n['time'])}　{n['text']}")
    out.append(f"4 标签　{'、'.join(v['tags']) or '（没有）'}")

    out.append(f"5 实际设置　{'已存定，不能再改' if v['frozen'] else '还没存定，启动时存定'}")
    if not v["settings"]:
        out.append("  　（一项都没填）")
    for name, s in v["settings"].items():
        c, src = s["content"], s["source"]
        if c["kind"] == "值":
            body = "值　" + json.dumps(c["value"], ensure_ascii=False)
        elif c["kind"] == "复制":
            body = f"文件（原文存了一份）　{c.get('stored') or c['path']}"
        else:
            body = f"文件（只记位置）　{c['path']}"
        if src["kind"] == "实验产出":
            origin = f"来路：实验 {src['experiment']} 的产出「{src['output']}」"
        else:
            origin = f"来路：其他来源，{src.get('from') or '没写从哪来'}"
            if src.get("when"):
                origin += f"，{src['when']}"
        sha = f"　哈希 {_short(c.get('sha256'))}" if c.get("sha256") else ""
        out.append(f"  　{name}　{body}　{origin}{sha}")

    out.append("6 操作")
    for o in v["operations"]:
        out.append(f"  　{_clock(o['time'])}　{o['op']}")

    out.append("7 任务")
    if not v["tasks"]:
        out.append("  　（还没有任务）")
    for name, t in v["tasks"].items():
        trail = " → ".join(
            f"{h['state']}{'/' + h['stage'] if h['stage'] else ''} {_clock(h['time'])[11:]}" for h in t["history"]
        )
        out.append(f"  　{name}　{t['state']}　机器 {t['machine']}　{trail}")

    out.append("8 产出")
    if not v["outputs"]:
        out.append("  　（还没有产出）")
    for o in v["outputs"]:
        out.append(f"  　{o['name']}　{o['path']}　哈希 {_short(o['sha256'])}　{o['what']}")

    out.append("9 问题")
    if not v["problems"]:
        out.append("  　（没有）")
    for pr in v["problems"]:
        who = f"任务 {pr['task']}：" if pr["task"] else ""
        out.append(f"  　{_clock(pr['time'])}　{who}{pr['error']}")

    prov = v["provenance"]
    if prov:
        at = prov.get("plugin_at_start", {})
        commit = prov.get("code_commit") or ""
        if prov.get("code_dirty") is not None:
            commit = _short(commit) + ("，有没提交的改动" if prov["code_dirty"] else "")
        out.append(
            f"来历　代码提交 {commit}"
            f"　机器 {prov.get('machine')}　Python {prov.get('python')}　启动时插件文件哈希 {_short(at.get('files_sha256'))}"
        )
        extra = {k: val for k, val in prov.items() if k not in ("code_commit", "code_dirty", "machine", "python", "plugin_at_start")}
        for k, val in extra.items():
            out.append(f"  　{k}　{val}")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stemlab", description="操作台：操作实验，并把操作记下来。")
    ap.add_argument("--home", help="放 experiments 和 plugins 的文件夹。默认是环境变量 STEMLAB_HOME，再默认是代码所在的文件夹。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("plugins", aliases=["插件"], help="装着哪些插件，各要什么设置、产出什么")

    p = sub.add_parser("new", aliases=["新建"], help="新建一个实验")
    p.add_argument("plugin")
    p.add_argument("--note", default="", help="说明")
    p.add_argument("--tag", action="append", default=[], help="标签，可以给多个")

    p = sub.add_parser("set", aliases=["设置"], help="填一项设置（启动前）")
    p.add_argument("exp")
    p.add_argument("name")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--value", help="一个值。能当 JSON 读就当 JSON，否则当文字")
    g.add_argument("--file", help="一个文件或文件夹，启动时把原文复制进实验")
    g.add_argument("--ref", help="一个大文件或文件夹，只记位置和哈希，不复制")
    g.add_argument("--from-exp", help="另一个实验的编号，用它的产出")
    p.add_argument("--output", help="和 --from-exp 一起用：那个实验的哪一项产出")
    p.add_argument("--source", default="", help="其他来源：从哪拿的")
    p.add_argument("--when", default="", help="其他来源：什么时候拿的")

    for cmd, alias, text in (
        ("start", "启动", "启动（设置在这时存定）"),
        ("pause", "暂停", "暂停"),
        ("resume", "继续", "继续"),
        ("stop", "停止", "停止"),
        ("retry", "重试", "重试失败的和停掉的任务"),
        ("show", "看", "看一个实验的全部记录"),
    ):
        p = sub.add_parser(cmd, aliases=[alias], help=text)
        p.add_argument("exp")

    p = sub.add_parser("refresh", aliases=["刷新"], help="叫插件看一眼任务走到哪了")
    p.add_argument("exp", nargs="?")

    sub.add_parser("list", aliases=["列表"], help="所有实验，一行一个")

    p = sub.add_parser("note", aliases=["备注"], help="加一条备注")
    p.add_argument("exp")
    p.add_argument("text")

    p = sub.add_parser("tag", aliases=["标签"], help="加或去掉标签")
    p.add_argument("exp")
    p.add_argument("--add", action="append", default=[])
    p.add_argument("--remove", action="append", default=[])

    p = sub.add_parser("check", aliases=["核对"], help="核对记录有没有被改过")
    p.add_argument("exp", nargs="?")

    p = sub.add_parser("watch", aliases=["值守"], help="定时值守：隔一会儿叫一次运行中实验的插件报任务状态")
    p.add_argument("--every", type=float, default=15, help="隔几秒看一次，默认 15")
    p.add_argument("--rounds", type=int, help="看几次后自己停。不给就一直值守，按 Ctrl+C 停")
    return ap


ALIASES = {
    "插件": "plugins", "新建": "new", "设置": "set", "启动": "start", "暂停": "pause", "继续": "resume",
    "停止": "stop", "重试": "retry", "看": "show", "刷新": "refresh", "列表": "list", "备注": "note",
    "标签": "tag", "核对": "check", "值守": "watch",
}


def _watch(desk: Desk, every: float, rounds: int | None) -> None:
    from .watch import Watch

    said = {"elsewhere": None}

    def say(st: dict) -> None:
        if not st["holding"]:
            if st["elsewhere"] and st["elsewhere"] != said["elsewhere"]:
                print(f"别处已经在值守（进程 {st['elsewhere']}），这里等着。", flush=True)
            said["elsewhere"] = st["elsewhere"]
            return
        said["elsewhere"] = None
        if st["last_seen"]:
            print(f"{_clock(st['last_time'])}　看过：{'、'.join(st['last_seen'])}", flush=True)
        if st["last_error"]:
            print(f"{_clock(st['last_time'])}　这一次出了问题：{st['last_error']}", flush=True)
        for exp_id, err in st["unreadable"].items():
            print(f"{_clock(st['last_time'])}　{exp_id} 的记录读不了：{err}", flush=True)

    print(f"值守开始：每 {every:g} 秒叫一次运行中实验的插件报任务状态。按 Ctrl+C 停。", flush=True)
    try:
        Watch(lambda: desk, every=every).run(on_round=say, rounds=rounds)
    except KeyboardInterrupt:
        pass
    print("值守停了。", flush=True)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    home = Path(args.home or os.environ.get("STEMLAB_HOME") or CODE_DIR)
    cmd = ALIASES.get(args.cmd, args.cmd)
    try:
        desk = Desk(home)
        if cmd == "plugins":
            print(desk.list_plugins())
        elif cmd == "new":
            print(desk.new(args.plugin, note=args.note, tags=args.tag))
        elif cmd == "set":
            value = parse_value(args.value) if args.value is not None else None
            desk.set(
                args.exp, args.name, value=value, file=args.file, ref=args.ref,
                from_exp=args.from_exp, output=args.output, source=args.source, when=args.when,
            )
            print(f"{args.exp} 的设置「{args.name}」已填。")
        elif cmd in ("start", "pause", "resume", "stop", "retry"):
            ok = getattr(desk, cmd)(args.exp)
            word = {v: k for k, v in ALIASES.items()}[cmd]
            print(f"{args.exp} 已{word}。" if ok else f"{args.exp} 已{word}，但插件出了问题，已记进记录。")
        elif cmd == "refresh":
            seen = desk.refresh(args.exp)
            print("看过：" + ("、".join(seen) if seen else "没有运行中的实验"))
        elif cmd == "show":
            print(desk.show(args.exp))
        elif cmd == "list":
            print(desk.list())
        elif cmd == "note":
            desk.note(args.exp, args.text)
            print(f"{args.exp} 的备注已记。")
        elif cmd == "tag":
            desk.tag(args.exp, add=args.add, remove=args.remove)
            print(f"{args.exp} 的标签已改。")
        elif cmd == "check":
            print(desk.check(args.exp))
        elif cmd == "watch":
            _watch(desk, args.every, args.rounds)
    except RecordError as err:
        print(f"没有做：{err}", file=sys.stderr)
        return 2
    return 0
