"""命令行：python -m stemlab.desk <命令> ...

每个命令对应操作台核心里的一个函数，有英文和中文两种写法。这是展示层，可以整个重写。
写只经核心；被拒的时候打印原因，退出码是 1。

重写的时候要留着两样（守边界的测试只认这两样，不认命令叫什么、打印什么）：
    main(argv)        python -m stemlab.desk 进来的入口
    READ_COMMANDS     只看不写的命令
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stemlab.contract import Refused
from stemlab.desk import core
from stemlab.desk.core import actions, backup, check, query, start, watch
from stemlab.desk.ui import progress, views


# 只看不写的命令。守边界的测试照着它逐条去跑，核对前后 data/ 下一个字节都没变。
# 花括号里的词由测试换成手上有的编号：{experiment} 一个实验，{item} 一样登记的东西，{case} 一个 case，
# {bone} 一个骨标识，{chart} 这个实验的一张图的名字
READ_COMMANDS = (
    ("list",), ("items",), ("types",), ("status",),
    ("show", "{experiment}"), ("show", "{item}"), ("progress", "{experiment}"), ("chart", "{experiment}", "{chart}"),
    ("up", "{item}"), ("down", "{item}"), ("case", "{case}"), ("bone", "{bone}"),
    ("compare", "{experiment}", "{experiment}"),
)


def _value(args) -> dict | None:
    if args.value is not None:
        return json.loads(args.value)
    if args.value_file is not None:
        return json.loads(Path(args.value_file).read_text(encoding="utf-8-sig"))
    return None


def _register(args) -> str:
    item = actions.register(args.kind, args.name, note=args.note, by=args.by, value=_value(args), source=args.path,
                            storage="ref" if args.ref else None, bone_id=args.bone_id, new_bone=args.new_bone,
                            defaults=args.defaults)
    return views.item_line(item)


def _outcome(experiment: str, result) -> str:
    said = "" if result is None or result.ok else f"\n插件出错：{result.error}"
    return views.experiment_line(experiment) + said


def _show(args) -> str:
    return views.show(args.id) if args.id.startswith("E") else views.show_item(args.id)


def _chart(args) -> str:
    shown = progress.chart(args.experiment, args.name)
    if "error" in shown:
        return f"取这张图出错了（不进记录）：{shown['error']}"
    return json.dumps(shown, ensure_ascii=False, indent=1)


def _web(args) -> int:
    from stemlab.desk.ui import web

    return web.main(["--port", str(args.port)] + (["--open"] if args.open else []))


def _status(args) -> str:
    holder = watch.status()
    watching = f"值守在跑（进程 {holder['pid']}）" if holder and holder["alive"] else "值守没在跑"
    return f"{watching}\n{check.last_backup()}"


def build() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk", description="stem-lab 操作台")
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")

    def add(name: str, alias: str, text: str, run, *arguments):
        sub = commands.add_parser(name, aliases=[alias], help=f"{alias}：{text}", description=text)
        for flags, options in arguments:
            sub.add_argument(*flags, **options)
        sub.set_defaults(run=run)

    def arg(*flags, **options):
        return flags, options

    experiment = arg("experiment", metavar="实验", help="实验的编号，比如 E0007")
    add("register", "登记", "登记一样外面拿来的东西", _register,
        arg("kind", metavar="种类"), arg("name", metavar="名字"), arg("--note", required=True, help="它是什么、从哪来"),
        arg("--value", help="一个值：JSON 对象"), arg("--value-file", help="一个值：放在文件里的 JSON 对象"),
        arg("--path", help="一个文件夹；手写的一批点可以是一个 .jsonl 文件"),
        arg("--ref", action="store_true", help="只记位置，不复制"), arg("--bone-id", help="骨标识"),
        arg("--new-bone", action="store_true", help="这是一根新骨"), arg("--defaults", help="条件默认的编号（手写的一批点用）"),
        arg("--by", help="谁登记的，默认是当前用户"))
    add("manifest", "写清单", "在一个文件夹里就地写一份清单（给只记位置的东西登记之前用）",
        lambda a: json.dumps(actions.write_manifest(a.path, a.kind, a.bone_id), ensure_ascii=False),
        arg("path", metavar="文件夹"), arg("kind", metavar="种类"), arg("--bone-id"))
    add("attach", "挂", "把一样东西手动挂到一个 case 下面", lambda a: str(actions.attach(a.item, a.case)["op"]),
        arg("item", metavar="编号"), arg("case", metavar="case"))
    add("detach", "摘", "把一样东西从一个 case 下面摘下来", lambda a: str(actions.detach(a.item, a.case)["op"]),
        arg("item", metavar="编号"), arg("case", metavar="case"))
    add("types", "类型", "现在有哪些实验类型", lambda a: views.list_kinds(query.types()))
    add("new", "新建", "新建一个实验", lambda a: actions.new(a.type, a.note, a.tag),
        arg("type", metavar="类型"), arg("--note", default=""), arg("--tag", action="append", default=[]))
    add("clone", "克隆", "克隆一个实验：同类型、输入逐样相同", lambda a: actions.clone(a.experiment, a.note),
        experiment, arg("--note"))
    add("fill", "填", "填一样输入；不给编号就是清掉", lambda a: (actions.fill(a.experiment, a.input, a.items), views.show(a.experiment))[1],
        experiment, arg("input", metavar="输入名"), arg("items", metavar="编号", nargs="*"))
    add("note", "备注", "给一个实验加一条备注", lambda a: (actions.note(a.experiment, a.text), "记下了")[1],
        experiment, arg("text", metavar="备注"))
    add("tag", "标签", "增减一个实验的标签", lambda a: (actions.tag(a.experiment, a.add, a.remove), "改好了")[1],
        experiment, arg("--add", action="append", default=[]), arg("--remove", action="append", default=[]))
    add("start", "启动", "启动：开新的一轮", lambda a: _outcome(a.experiment, start.start(a.experiment, a.rerun)),
        experiment, arg("--rerun", action="append", default=[], metavar="任务", help="点名重排一个待查的任务"))
    add("stop", "停止", "停止这一轮", lambda a: _outcome(a.experiment, start.stop(a.experiment)), experiment)
    add("poll", "看一遍", "照看这个实验一次", lambda a: _outcome(a.experiment, start.poll(a.experiment)), experiment)
    add("watch", "值守", "一直值守，直到 Ctrl+C", lambda a: watch.main(["--interval", str(a.interval)] + (["--once"] if a.once else [])),
        arg("--interval", type=float, default=10.0), arg("--once", action="store_true"))
    add("show", "看", "看一个实验或一样登记的东西", _show, arg("id", metavar="编号"))
    add("list", "列", "列出全部实验", lambda a: views.list_experiments())
    add("items", "东西", "列出登记的东西", lambda a: views.list_registered(a.kind, a.name), arg("--kind"), arg("--name"))
    add("up", "往上追", "一样东西是怎么来的", lambda a: views.show_upstream(a.id), arg("id", metavar="编号"))
    add("down", "往下追", "谁用了一样东西", lambda a: views.show_downstream(a.id), arg("id", metavar="编号"))
    add("case", "骨下面", "一个 case 下面有什么", lambda a: views.show_case(a.id), arg("id", metavar="case"))
    add("bone", "同一根骨", "同一根骨的全部东西", lambda a: views.show_bone(a.bone_id), arg("bone_id", metavar="骨标识"))
    add("progress", "进展", "一个实验现在的进展：任务、产物、问题、有哪些图", lambda a: progress.text(a.experiment), experiment)
    add("chart", "图", "取一张图的数据（JSON）", _chart, experiment, arg("name", metavar="图的名字"))
    add("web", "网页", "开操作台的网页，只有本机打得开", _web, arg("--port", type=int, default=8790),
        arg("--open", action="store_true", help="开起来之后顺手在浏览器里打开"))
    add("compare", "比", "把两个实验的输入和来历并排", lambda a: views.compare(a.first, a.second),
        arg("first", metavar="实验甲"), arg("second", metavar="实验乙"))
    add("status", "状态", "值守在不在跑，上次备份是什么时候", _status)
    add("check", "检查", "一条命令跑全部检查", lambda a: check.main((["--no-tests"] if a.no_tests else []) + (["--contents"] if a.contents else [])),
        arg("--no-tests", action="store_true"), arg("--contents", action="store_true"))
    add("backup", "备份", "把 data/ 备份到一台机器上",
        lambda a: "备份好了：共 {files} 个文件，这次传了 {sent} 个".format(**backup.backup(a.machine, a.contents)),
        arg("machine", metavar="机器"), arg("--contents", action="store_true", help="在远端连内容的哈希也核一遍"))
    return parser


def main(argv=None) -> int:
    core.utf8_console()                 # Windows 的控制台默认不是 UTF-8
    args = build().parse_args(argv)
    try:
        result = args.run(args)
    except Refused as error:
        print(f"被拒：{error}")
        return 1
    except LookupError as error:
        print(f"找不到：{error}")
        return 1
    if isinstance(result, int):
        return result
    if result:
        print(result)
    return 0
