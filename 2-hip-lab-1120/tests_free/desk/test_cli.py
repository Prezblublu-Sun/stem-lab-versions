"""命令行：每个命令对应核心里的一个函数；看的命令不往 data/ 里写任何东西。

这里认得命令叫什么、打印什么，所以它是界面自己的测试，放在 tests_free/：命令行重写的时候，这里跟着改。
不认措辞的那一条（照 READ_COMMANDS 逐条跑，前后 data/ 不变）在 tests/guard/test_readonly.py 里。
"""
from __future__ import annotations

import os
import subprocess
import sys

from stemlab.experiments import view
from stemlab.registry import lookup
from tests import helpers


def desk(*arguments: str, expect: int = 0) -> str:
    """跑一条命令：python -m stemlab.desk ...，返回它打印的东西。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "stemlab.desk", *arguments], cwd=helpers.REPO, env=env,
                          capture_output=True, timeout=300)
    out = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert done.returncode == expect, f"{arguments} 的退出码是 {done.returncode}：\n{out}"
    return out


def test_walk_through_on_the_command_line(lab, data, tmp_path):
    assert "demo.echo" in desk("types") and "装不上" in desk("类型")

    setting = tmp_path / "setting.json"
    setting.write_text('{"scale": 2, "tasks": ["a", "b"]}', encoding="utf-8")
    assert "R0001" in desk("register", "setting", "cli-setting", "--value-file", str(setting), "--note", "命令行登记的")
    assert "R0002" in desk("登记", "setting", "inline", "--value", '{"x": 1}', "--note", "直接写在命令里的值")
    assert desk("new", "demo.echo", "--note", "命令行建的", "--tag", "示范").strip() == "E0001"
    assert "还没填" in desk("show", "E0001")
    assert "cli-setting" in desk("fill", "E0001", "setting", "R0001")

    assert "运行中" in desk("start", "E0001")
    out = desk("poll", "E0001")
    assert "已结束" in out and "做完" in out
    shown = desk("看", "E0001")
    assert "任务 a  done  finished" in shown and "产物 report → R0003" in shown and "输入已经存定" in shown
    assert "插件 demo" in shown and "来历（plugin）" in shown

    assert "被拒" in desk("start", "E0001", expect=1) and "已经做完" in desk("启动", "E0001", expect=1)
    assert "找不到" in desk("show", "E0099", expect=1)
    assert "被拒" in desk("fill", "E0001", "setting", "R0002", expect=1)
    assert "被拒" in desk("stop", "E0001", expect=1)

    assert desk("clone", "E0001", "--note", "克隆的").strip() == "E0002"
    desk("note", "E0002", "先放着"), desk("tag", "E0002", "--add", "重要")
    assert view.view("E0002").tags == ["示范", "重要"] and view.view("E0002").notes[0]["text"] == "先放着"
    assert desk("watch", "--once") == "" and view.view("E0002").state == "new"


def test_looking_never_writes(lab, data):
    made = helpers.experiment(value={"tasks": ["a"]})
    desk("start", made), desk("poll", made)
    report = lookup.by_origin(made, 1)[0]["id"]
    setting = view.view(made).filled["setting"][0]
    before = helpers.snapshot(data)
    for arguments, word in [(("list",), made), (("列",), "demo.echo"), (("items",), report), (("items", "--kind", "setting"), setting),
                            (("show", made), "任务 a"), (("show", report), "哈希"), (("up", report), "外面拿来的"),
                            (("往上追", report), made), (("down", setting), made), (("bone", "femur042"), "femur042"),
                            (("compare", made, made), "commit"), (("status",), "值守没在跑"), (("types",), "demo.sleep")]:
        assert word in desk(*arguments), arguments
    assert helpers.snapshot(data) == before, "看的命令前后，data/ 下每个文件的哈希不变"
