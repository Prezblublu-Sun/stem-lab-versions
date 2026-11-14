"""检查的固定入口：python -m stemlab.desk.core.check

    guard()           代码这一边：FROZEN 清单、八条依赖规则、全部测试
    verify_chains()   数据这一边：各条链有没有被改，每条长得对不对
    reconcile_all()   把发布到一半的产物接着做完
    verify_books()    两本账对不对得上，账上的内容还在不在、（要的话）变没变
    check_backup()    本机的链是不是上次备份那一份的延长

入口在核心里，不在界面里。界面重写时漏不掉任何一项检查。
每次改完代码都跑一遍，不过就不算做完；提交之前也自动跑一次。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from stemlab.contract import Refused, kinds, layout, states
from stemlab.desk import core
from stemlab.desk.core import backup, code_state, locks
from stemlab.experiments import reader as records
from stemlab.experiments import view
from stemlab.hooks import local, publish
from stemlab.registry import reader as register_reader
from stemlab.registry import verify

_LINT = "import sys; from importlinter.cli import lint_imports; sys.exit(lint_imports(config_filename=sys.argv[1], no_cache=True))"


# ---------------------------------------------------------------- 代码这一边

def _run(command: list[str]) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(command, cwd=layout.repo_root(), env=env, capture_output=True, check=False, **local.QUIET)
    return done.returncode == 0, (done.stdout + done.stderr).decode("utf-8", "replace").strip()


def lint_imports(config: str = ".importlinter") -> tuple[bool, str]:
    """跑八条依赖规则。返回（过没过，import-linter 的输出）。"""
    return _run([sys.executable, "-c", _LINT, config])


def run_tests(selection=("-m", "not cross and not science and not swap")) -> tuple[bool, str]:
    """跑测试：tests/ 下固定的，加上自由代码的（tests_free/，和插件里各自的 tests/）。

    默认不跑要连 Linux 的跨机测试、由人定的科学测试，和要几分钟的“界面换一份写法”那一条（tests/swap/）。
    """
    return _run([sys.executable, "-m", "pytest", "tests", "tests_free", "plugins", "-q", "-p", "no:cacheprovider", *selection])


def guard(tests: bool = True) -> list[tuple[str, bool, str]]:
    """代码这一边的检查。返回每一项：（名字，过没过，细节）。"""
    problems = code_state.frozen_ok()
    results = [("固定的文件和 FROZEN 清单对得上", not problems, "\n".join(problems))]
    results.append(("八条依赖规则", *lint_imports()))
    if tests:
        results.append(("全部测试", *run_tests()))
    return results


# ---------------------------------------------------------------- 数据这一边

def _experiments() -> list[str]:
    """有记录的实验。发了号却没有记录的空号不算。"""
    return [experiment for experiment in records.all_ids() if layout.record_file(experiment).exists()]


def _status(experiment: str) -> states.Status | None:
    """一个实验的现状。记录是空的（新建到一半断掉留下的）就是 None。"""
    try:
        return view.view(experiment)
    except LookupError:
        return None


def verify_chains() -> list[str]:
    """各条链有没有被改、每条长得对不对。返回哪里不对，指出是哪一条；空列表就是没问题。"""
    try:
        problems = verify.verify_register() + verify.verify_links() + records.verify_issued()
        for experiment in _experiments():
            problems += records.verify(experiment)
    except ValueError as error:                     # 读到了比这份代码新的格式：说出来，不当成坏数据
        return [str(error)]
    return problems


def verify_books(contents: bool = False) -> list[str]:
    """两本账对不对得上，账上的内容还在不在。要在各条链核对过之后跑。

    登记里的每样产物，都记在它那个实验那一轮的记录里，反过来也是；outputs/ 下没有没登记的文件夹；
    复制进来的内容和产物的文件夹都还在；store/ 里没有不在登记里的东西；只记位置的内容没变。
    contents=True 时把所有登记的内容都重算一遍哈希（慢）。
    """
    items = register_reader.items()
    problems = [f"{item['id']}（{item['name']} 第 {item['version']} 版）的内容不见了：{item['content']}"
                for item in items
                if item["storage"] == kinds.STORE_COPY and not layout.locate(item["content"]).is_dir()]

    registered: dict[tuple, dict] = {}              # （实验, 轮）-> 产物名 -> 登记的编号
    for item in items:
        origin = item["origin"]
        if origin["from"] == "product":
            registered.setdefault((origin["experiment"], origin["round"]), {})[origin["output"]] = item["id"]
    for experiment in _experiments():
        status = _status(experiment)
        if status is None:
            continue
        live = states.can("report", status)
        for one in status.rounds:
            listed = registered.pop((experiment, one.number), {})
            if live and one is status.rounds[-1]:
                continue                            # 正在跑的那一轮可能正发布到一半，那是对账的事
            recorded = {name: made["item"] for name, made in one.outputs.items()}
            if recorded != listed:
                problems.append(f"{experiment} 第 {one.number} 轮：记录里的产物是 {recorded}，登记里的是 {listed}")
            folder = layout.outputs_dir(experiment, one.number)
            present = sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
            extra = [name for name in present if name not in recorded and name not in listed]
            if extra:
                problems.append(f"{experiment} 第 {one.number} 轮的 outputs/ 里有没登记的东西：{extra}")
    problems += [f"登记里有 {experiment} 第 {number} 轮的产物 {listed}，但那个实验没有这一轮"
                 for (experiment, number), listed in registered.items()]

    store = layout.store_root()
    known = {item["content"] for item in items if item["storage"] == kinds.STORE_COPY}
    for path in (sorted(store.iterdir()) if store.is_dir() else []):
        if layout.inside(path) not in known:
            problems.append(f"registry/store/{path.name} 不在登记里：是登记到一半留下的，"
                            "或者是链丢了尾巴之后剩下的内容。确认不要了再删")
    if not problems:
        problems += verify.verify_items() if contents else verify.verify_refs()
    return problems


def verify_all(contents: bool = False) -> list[str]:
    """核对 data/：先核各条链；链没问题，再核两本账对不对得上、内容还在不在。"""
    problems = verify_chains()
    return problems or verify_books(contents)


def reconcile_all() -> list[str]:
    """对一遍账：把每个实验发布到一半的产物接着做完。返回这次补做了什么。

    正被别处动着的、记录读不出来的实验跳过：前一种等它自己做完，后一种由核对去报。
    """
    done = []
    for experiment in _experiments():
        try:
            status = _status(experiment)
            if status is None or not states.can("report", status):
                continue
            with locks.busy(experiment, "reconcile", timeout=0):
                done += [f"{experiment} 的 {name}" for name in publish.reconcile(experiment)]
        except (Refused, LookupError, ValueError):
            continue
    return done


def check_backup() -> list[str]:
    """本机的各条链是不是上次备份那一份的延长。哈希链查不出末尾被删，这里查得出。"""
    return backup.since_last()


def last_backup() -> str:
    """上次备份是什么时候、推到了哪台机器。给人看的一句话。"""
    try:
        saved = json.loads(layout.backup_file().read_bytes())
        return f"上次备份：{saved['time']}，推到 {saved['machine']}"
    except FileNotFoundError:
        return "还没备份过，没有可比的"
    except (ValueError, KeyError):
        return "backup.json 读不出来"


# ---------------------------------------------------------------- 入口

def main(argv=None) -> int:
    core.utf8_console()
    parser = argparse.ArgumentParser(prog="python -m stemlab.desk.core.check", description="一条命令跑全部检查")
    parser.add_argument("--no-tests", action="store_true", help="不跑测试")
    parser.add_argument("--contents", action="store_true", help="把所有登记的内容都重算一遍哈希（慢）")
    args = parser.parse_args(argv)

    results = guard(tests=not args.no_tests)
    problems = verify_chains()
    results.append(("data/ 的各条链", not problems, "\n".join(problems)))
    if not problems:                                # 链有问题就不往账上写：先不对账，也不往下核
        done = reconcile_all()
        results.append(("对账" + (f"（接着做完了：{'、'.join(done)}）" if done else ""), True, ""))
        problems = verify_books(contents=args.contents)
        results.append(("两本账对得上，登记的内容都在", not problems, "\n".join(problems)))
    problems = check_backup()
    results.append((f"本机的链是上次备份的延长（{last_backup()}）", not problems, "\n".join(problems)))

    failed = 0
    for name, ok, detail in results:
        print(f"[{'过' if ok else '不过'}] {name}")
        if not ok:
            failed += 1
            print("    " + detail.replace("\n", "\n    "))
    print("检查全过" if not failed else f"有 {failed} 项不过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
