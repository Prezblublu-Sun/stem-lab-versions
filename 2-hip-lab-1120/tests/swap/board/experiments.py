"""全部实验——另一种写法：每个实验一行摘要，直接从实验记录读。只读。"""
from __future__ import annotations

from stemlab.experiments import reader, view


def all_of_them() -> list:
    found = []
    for name in reader.all_ids():
        try:
            found.append(view.summary(name))
        except (LookupError, ValueError) as error:
            found.append({"id": name, "unreadable": str(error)})
    return found
