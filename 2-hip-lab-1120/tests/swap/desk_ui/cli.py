"""命令行——另一种写法。命令是另一套名字，打印的是 JSON。写只经操作台核心。

留着的两样：main(argv) 和 READ_COMMANDS。
"""
from __future__ import annotations

import json
import sys

from stemlab.contract import Refused
from stemlab.desk import core
from stemlab.desk.core import actions, start
from stemlab.desk.ui import progress, views

READ_COMMANDS = (
    ("experiments",), ("kinds",), ("registered",), ("one", "{experiment}"), ("thing", "{item}"), ("under", "{case}"),
    ("picture", "{experiment}", "{chart}"),
)
LOOK = {"experiments": views.experiments, "kinds": views.kinds, "registered": views.registered, "one": views.one,
        "thing": views.thing, "under": views.under, "picture": progress.picture}


def _ran(result) -> dict:
    return {"ran": result.ok, "trouble": result.error}


DO = {
    "make": lambda kind, note="": actions.new(kind, note, []),
    "put": lambda experiment, name, *items: actions.fill(experiment, name, list(items)) and None,
    "remark": lambda experiment, text: actions.note(experiment, text) and None,
    "begin": lambda experiment, *named: _ran(start.start(experiment, named)),
    "end": lambda experiment: _ran(start.stop(experiment)),
    "glance": lambda experiment: _ran(start.poll(experiment)),
}


def main(argv=None) -> int:
    core.utf8_console()
    words = list(sys.argv[1:] if argv is None else argv)
    try:
        if not words or words[0] not in {**LOOK, **DO}:
            raise Refused(f"commands: {sorted({**LOOK, **DO})}")
        said = {**LOOK, **DO}[words[0]](*words[1:])
    except Refused as error:
        print(json.dumps({"refused": str(error)}, ensure_ascii=False))
        return 1
    except (LookupError, TypeError) as error:
        print(json.dumps({"missing": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(said, ensure_ascii=False, default=str))
    return 0
