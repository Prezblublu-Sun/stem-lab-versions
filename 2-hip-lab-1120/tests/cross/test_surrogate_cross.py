"""跨机：预测器在 Linux 上训练、打包，在 Windows 上加载——自检过，两边的预测在容差内相同。

用的是真的代理插件和机器清单里真的那台 worker；作业放在它 /tmp 下这次测试自己的文件夹里，测完删掉。
"""
from __future__ import annotations

import json
import math
import shlex
import socket

import pytest

from stemlab.contract import hashing
from stemlab.contract.formats.points import read_points
from stemlab.contract.machines import parse_machines
from stemlab.contract.layout import work_dir
from stemlab.desk.core import start
from stemlab.experiments import view
from stemlab.hooks import remote
from tests import helpers, real

pytestmark = pytest.mark.cross


@pytest.fixture
def linux(real_own_lab):
    workers = [m for m in parse_machines(json.loads((helpers.REPO / "machines.json").read_bytes())) if m.role == "worker"]
    if not workers:
        pytest.skip("机器清单里没有 worker")
    there = workers[0]
    try:
        root = remote.ssh(there, "mktemp -d /tmp/stemlab-cross-XXXXXXXX", timeout=30).decode("utf-8").strip()
    except remote.Unreachable as error:
        pytest.skip(f"连不上 {there.name}：{error}")
    assert root.startswith("/tmp/stemlab-cross-")
    connect = {"ssh": there.ssh, "port": there.port, "options": list(there.options), **({"bin": there.bin} if there.bin else {})}
    listed = {"format": 1, "machines": [
        {"name": "here", "role": "desk", "host": socket.gethostname(), "slots": 2},
        {"name": "linux", "role": "worker", "host": there.host, "connect": connect, "python": there.python,
         "job_root": f"{root}/jobs", "backup_root": f"{root}/backup"}]}
    (real_own_lab / "machines.json").write_bytes(hashing.canonical(listed) + b"\n")
    try:
        yield remote.worker("linux")
    finally:
        remote.ssh(there, f"rm -rf {shlex.quote(root)}", timeout=300)


def test_a_predictor_packed_on_linux_loads_on_windows(linux, data, tmp_path):
    rows = real.data_rows(real.spread(80, seed=21))
    made = real.train([real.data(tmp_path, rows)])
    assert start.start(made).ok
    real.run(made, seconds=600)
    status = view.view(made)
    assert real.tasks(made) == {"train": ("done", "trained")}, (status.rounds[-1].reason, status.rounds[-1].problems)
    assert status.tasks["train"].machine == "linux", "训练是在 worker 上做的"
    report = json.loads((real.output(made, "report") / "report.json").read_bytes())
    assert report["training"]["machine"] == "linux" and report["holdout"]["rotation"]["n"] > 5
    assert linux.host in json.dumps(status.rounds[-1].extra), "远端的环境记进了这一轮的来历"

    there = {row["point"]: row for row in read_points(work_dir(made) / "trained-r1" / "asked.jsonl")}     # Linux 上对留出各点出的预测
    held = [row for row in rows if row["point"] in there][:12]
    batch = real.points(tmp_path, [real.point(f"h{number}", row["values"]["length"], load=row["values"]["load"])
                                   for number, row in enumerate(held)])
    asked = real.predict(status.rounds[-1].outputs["predictor"]["item"], batch)
    assert start.start(asked).ok                            # 第一次在这台机器上用：核心先拿 Linux 上算好的自检样本核一遍，过了才出数
    real.run(asked, seconds=120)
    assert real.tasks(asked) == {"predict": ("done", "predicted")}, view.view(asked).rounds[-1].problems
    here = read_points(real.output(asked, "prediction") / "rows.jsonl")
    assert len(here) >= 5, "留出的点里总有几个在适用范围里"
    for row in here:
        for group in ("values", "lower", "upper"):
            for target, number in row[group].items():
                assert math.isclose(number, there[row["point"]][group][target], rel_tol=1e-9), f"{target} 两边差得比容差大"
