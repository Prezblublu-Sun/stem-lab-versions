"""机器——另一种写法：只列机器清单里有哪几台，不读它们的数，也不连远端。"""
from __future__ import annotations

import json

from stemlab.contract import layout, machines


def names() -> list:
    try:
        listed = machines.parse_machines(json.loads((layout.repo_root() / "machines.json").read_bytes()))
    except (OSError, ValueError):
        return []
    return [f"{one.name} ({one.role})" for one in listed]
