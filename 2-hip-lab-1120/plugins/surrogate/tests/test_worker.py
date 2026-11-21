"""训练的入口：心跳停下之后才写终态，终态不会被最后一下心跳盖掉。"""
from __future__ import annotations

import threading
import time

from plugins.surrogate import train, worker
from stemlab import hooks


def test_the_last_status_written_is_the_end_not_a_heartbeat(tmp_path, monkeypatch):
    written, lock = [], threading.Lock()

    def report(job, stage, libs=None, result=None, **more):
        time.sleep(0.01 if result is None else 0)       # 心跳写得慢一点：不等它停下，它就会落在终态后面
        with lock:
            written.append((stage, result))

    def run(job, out, said):
        said("training")
        time.sleep(0.15)                                # 训练期间心跳跳了很多下
        return {"status": "ok", "reason": ""}

    monkeypatch.setattr(worker, "BEAT", 0.001)
    monkeypatch.setattr(hooks.remote, "report", report)
    monkeypatch.setattr(train, "run", run)
    for _ in range(8):
        written.clear()
        assert worker.main([str(tmp_path)]) == 0
        time.sleep(0.05)                                # 没等心跳停下的话，落在后面的那一下要过一会儿才写完
        assert written[-1] == ("done", "ok"), written[-3:]
        assert len([one for one in written if one[1] is None]) > 10, "训练期间有心跳"
        assert (tmp_path / "outputs" / "result.json").exists()
