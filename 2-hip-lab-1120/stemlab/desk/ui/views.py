"""把登记的东西、实验、追溯的结果排成给人看的文字。只读。

这是展示层，可以整个重写。读直接用 registry.lookup 和 experiments.view；追溯和图表经操作台核心。
"""
from __future__ import annotations

import json

from stemlab.contract import kinds, layout, states
from stemlab.desk.core import locks, query
from stemlab.experiments import reader, view
from stemlab.registry import lookup


def _origin(item: dict) -> str:
    origin = item["origin"]
    if origin["from"] == "external":
        return f"外面拿来的（{origin['note']}，{origin['by']} 登记）"
    return f"{origin['experiment']} 第 {origin['round']} 轮的产物 {origin['output']}"


def item_line(item: dict) -> str:
    label = kinds.ITEM_KINDS[item["kind"]].label
    bone = f"  骨 {item['bone_id']}" if item["bone_id"] else ""
    return f"{item['id']}  {label}  {item['name']} 第 {item['version']} 版{bone}  {_origin(item)}"


def show_item(item_id: str) -> str:
    item = lookup.get(item_id)
    content = (json.dumps(item["content"], ensure_ascii=False) if item["storage"] == kinds.STORE_VALUE
               else str(lookup.content(item_id)))
    lines = [item_line(item), f"  存法 {item['storage']}  登记于 {item['time']}", f"  哈希 {item['hash']}", f"  内容 {content}"]
    return "\n".join(lines)


def list_registered(kind: str | None = None, name: str | None = None) -> str:
    found = lookup.find(kind, name)
    return "\n".join(map(item_line, found)) if found else "（没有）"


def experiment_line(experiment: str) -> str:
    try:
        summary = view.summary(experiment)
    except LookupError:
        return f"{experiment}  （发了号，但没有记录）"
    tasks = "  ".join(f"{state} {count}" for state, count in summary["tasks"].items())
    result = f"，{states.LABELS[summary['result']]}" if summary["result"] else ""
    extra = f"  问题 {summary['problems']}" if summary["problems"] else ""
    tags = f"  [{' '.join(summary['tags'])}]" if summary["tags"] else ""
    return (f"{experiment}  {summary['type']}  {summary['label']}（第 {summary['round']} 轮{result}）"
            f"  {tasks}{extra}{tags}  {summary['note']}").rstrip()


def list_experiments() -> str:
    found = reader.all_ids()
    return "\n".join(map(experiment_line, found)) if found else "（还没有实验）"


def show_round(experiment: str, number: int) -> str:
    one = view.rounds(experiment)[number - 1]
    result = states.LABELS[one.result] if one.result else "还没结束"
    lines = [f"第 {one.number} 轮  {one.opened} 开始  {result}" + (f"：{one.reason}" if one.reason else "")]
    code = one.provenance
    lines.append(f"  代码 提交 {code['commit'][:12]}  插件 {code['plugin']} {code['plugin_hash'][:12]}"
                 + ("（有没提交的改动，差异存在这一轮的 plugin.diff）" if code["plugin_dirty"] else "")
                 + f"  Python {code['python']}  主机 {code['host']}")
    if one.rerun:
        lines.append(f"  重排的任务 {' '.join(one.rerun)}")
    for task in one.tasks.values():
        detail = "  ".join(text for text in (task.outcome, task.stage, task.machine) if text)
        lines.append(f"  任务 {task.name}  {task.state}  {detail}".rstrip())
    for name, made in one.outputs.items():
        lines.append(f"  产物 {name} → {made['item']}")
    for extra in one.extra:
        lines.append(f"  来历（{extra['source']}） {json.dumps(extra['info'], ensure_ascii=False)}")
    for problem in one.problems:
        times = f"（连着 {problem['count']} 次）" if problem["count"] > 1 else ""
        lines.append(f"  问题{times} {problem['error']}")
    return "\n".join(lines)


def show(experiment: str) -> str:
    status = view.view(experiment)
    lines = [experiment_line(experiment)]
    holder = locks.holder(layout.busy_lock(experiment))
    if holder and holder["alive"]:
        lines.append(f"  进程 {holder['pid']} 正在动它（{holder['doing']}）。卡死了的话，结束这个进程")
    elif holder:
        lines.append(f"  上次动它的进程 {holder['pid']}（{holder['doing']}）没有正常收尾，已经不在了")
    if status.clone_of:
        lines.append(f"  克隆自 {status.clone_of}")
    frozen = status.frozen or {}
    for row in status.inputs:
        ids = [info["id"] for info in frozen.get(row["name"], [])] or status.filled.get(row["name"], [])
        need = "" if row["required"] else "（可选）"
        filled = "  ".join(item_line(lookup.get(item_id)) for item_id in ids) if ids else "还没填"
        lines.append(f"  输入 {row['name']}{need}：{filled}")
    lines.append("  输入已经存定" if status.frozen is not None else "  输入还没存定（第一次启动时存定）")
    lines += [show_round(experiment, one.number) for one in status.rounds]
    lines += [f"  备注 {note['time']} {note['text']}" for note in status.notes]
    return "\n".join(lines)


def list_kinds(loaded) -> str:
    """现在装着的实验类型，和装不上的插件。loaded 是 hooks.load.load() 的结果，由调用方经核心拿来。"""
    lines = []
    for name, kind in sorted(loaded.kinds.items()):
        inputs = "  ".join(row.name + ("" if row.required else "?") for row in kind.inputs)
        outputs = "  ".join(row.name for row in kind.outputs)
        lines.append(f"{name}  {kind.label}\n    输入 {inputs}\n    产物 {outputs}")
    lines += [f"插件 {name} 装不上：{why}" for name, why in loaded.errors.items()]
    return "\n".join(lines) if lines else "（现在没有任何实验类型：插件还没有报）"


def show_upstream(item_id: str) -> str:
    def walk(node: dict, depth: int) -> list[str]:
        pad = "  " * depth
        lines = [pad + item_line(node["item"])]
        for name, listed in node.get("inputs", {}).items():
            for child in listed:
                lines.append(f"{pad}  输入 {name}：")
                lines += walk(child, depth + 2)
        return lines

    return "\n".join(walk(query.upstream(item_id), 0))


def show_downstream(item_id: str) -> str:
    def walk(users: list, depth: int) -> list[str]:
        lines = []
        for user in users:
            lines.append("  " * depth + f"{user['experiment']}（{user['type']}）把它用作 {'、'.join(user['as'])}")
            for product in user["products"]:
                lines.append("  " * (depth + 1) + "产出 " + item_line(product["item"]))
                lines += walk(product["users"], depth + 2)
        return lines

    return "\n".join(walk(query.downstream(item_id), 0)) or "（还没有实验用它）"


def show_case(case_id: str) -> str:
    lines = [item_line(lookup.get(case_id))]
    for row in query.under_case(case_id):
        what = experiment_line(row["experiment"]) if "experiment" in row else item_line(row["item"])
        lines.append(f"  [{row['why']}] {what}")
    return "\n".join(lines)


def show_bone(bone_id: str) -> str:
    found = query.same_bone(bone_id)
    lines = [f"骨 {bone_id}"] + ["  " + item_line(item) for item in found["items"]]
    lines += ["  " + experiment_line(experiment) for experiment in found["experiments"]]
    return "\n".join(lines)


def compare(first: str, second: str) -> str:
    """把两个实验的输入逐样并排，再并排各自最后一轮的来历。"""
    one, two = view.view(first), view.view(second)

    def ids(status, name):
        listed = (status.frozen or {}).get(name) or [{"id": item_id} for item_id in status.filled.get(name, [])]
        return " ".join(info["id"] for info in listed) or "—"

    lines = [f"{'':14}{first:24}{second}"]
    for name in dict.fromkeys(row["name"] for row in one.inputs + two.inputs):
        mark = "  " if ids(one, name) == ids(two, name) else "≠ "
        lines.append(f"{mark}{name:12}{ids(one, name):24}{ids(two, name)}")
    if one.rounds and two.rounds:
        left, right = one.rounds[-1].provenance, two.rounds[-1].provenance
        for key in left:
            mark = "  " if left[key] == right.get(key) else "≠ "
            lines.append(f"{mark}{key:12}{str(left[key])[:22]:24}{str(right.get(key))[:22]}")
    return "\n".join(lines)


def where(experiment: str) -> str:
    """这个实验的文件夹在哪。"""
    return str(layout.experiment_dir(experiment))
