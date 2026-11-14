"""机器清单的格式。清单放在仓库根目录的 machines.json。

    {
      "format": 1,
      "machines": [
        {"name": "win", "role": "desk", "host": "...", "slots": 4},
        {"name": "linux", "role": "worker", "host": "...",
         "connect": {"ssh": "user@10.0.0.1", "port": 22, "options": ["-o", "BatchMode=yes"],
                     "bin": "C:/Windows/System32/OpenSSH"},
         "job_root": "/home/user/stemlab-jobs", "backup_root": "/home/user/stemlab-backup"}
      ]
    }

系统只用“操作台连 worker”这一个方向：desk 只有一台，data/ 的全部只由它写。
connect.bin 是 ssh 和 scp 所在的文件夹；不写就用 PATH 上的。Windows 上要用系统自带的 OpenSSH
才读得到 ssh-agent 里的密钥，所以最好写明。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from stemlab.contract.layout import is_key
from stemlab.contract.versions import FORMATS

DESK, WORKER = "desk", "worker"
ROLES = (DESK, WORKER)
_SAFE_PATH = re.compile(r"[A-Za-z0-9_./-]+")       # 这些位置要拼进远端的命令里，所以只许这些字符；~ 不会被展开，也不许


@dataclass(frozen=True)
class Machine:
    name: str                       # 清单里的名字，记录里的 machine 写的是它
    role: str                       # desk：操作台那台；worker：远端
    host: str                       # 主机名，用来认出“我是哪一台”
    slots: int = 0                  # 求解槽数：同一时刻最多起几个求解进程
    ssh: str | None = None          # 怎么连：user@地址。desk 不用写
    port: int = 22
    options: tuple[str, ...] = ()   # 另加给 ssh 和 scp 的选项
    bin: str | None = None          # ssh 和 scp 所在的文件夹；不写就用 PATH 上的
    python: str = "python3"         # 这台机器上跑 worker 用的解释器（它那个环境里的 python）
    job_root: str | None = None     # 作业根目录，worker 必写
    backup_root: str | None = None  # 备份推到哪，收备份的那台必写


def check_machines(doc) -> list[str]:
    """核对一份机器清单。返回哪里不符；空列表就是对的。"""
    if not isinstance(doc, dict) or not isinstance(doc.get("machines"), list):
        return ["机器清单必须是一个 JSON 对象，里面有 machines 列表"]
    problems = [] if doc.get("format") == FORMATS["machines"] else [f"format 该是 {FORMATS['machines']}"]
    problems += [f"清单多了 {key}" for key in doc if key not in ("format", "machines")]
    names = []
    for row in doc["machines"]:
        if not isinstance(row, dict):
            problems.append("machines 里有一项不是 JSON 对象")
            continue
        title = f"机器 {row.get('name')!r}"
        known = ("name", "role", "host", "slots", "connect", "python", "job_root", "backup_root")
        problems += [f"{title} 多了 {key}" for key in row if key not in known]
        if not is_key(row.get("name")):
            problems.append(f"{title}：name 要用小写字母、数字和下划线")
        names.append(row.get("name"))
        if row.get("role") not in ROLES:
            problems.append(f"{title}：role 只有 {list(ROLES)}")
        if not isinstance(row.get("host"), str) or not row.get("host"):
            problems.append(f"{title}：host 必须写")
        slots = row.get("slots", 0)
        if isinstance(slots, bool) or not isinstance(slots, int) or slots < 0:
            problems.append(f"{title}：slots 必须是不小于 0 的整数")
        for key in ("python", "job_root", "backup_root"):
            if row.get(key) is not None and (not isinstance(row[key], str) or not _SAFE_PATH.fullmatch(row[key])):
                problems.append(f"{title}：{key} 要写一个位置，只用字母、数字和 / . _ -（不能用 ~，写完整的位置）")
        for key in ("job_root", "backup_root"):
            if isinstance(row.get(key), str) and not row[key].startswith("/"):
                problems.append(f"{title}：{key} 要写从 / 开始的完整位置")
        problems += [f"{title}：{text}" for text in _check_connect(row)]
    if len(set(names)) != len(names):
        problems.append("机器的名字有重复的")
    if [row.get("role") for row in doc["machines"] if isinstance(row, dict)].count(DESK) != 1:
        problems.append("desk 必须有而且只有一台")
    return problems


def _check_connect(row: dict) -> list[str]:
    connect = row.get("connect")
    if row.get("role") != WORKER:
        return [] if connect is None else ["desk 不用写 connect"]
    if not isinstance(connect, dict) or not isinstance(connect.get("ssh"), str) or not connect.get("ssh"):
        return ["worker 必须写 connect.ssh"]
    problems = [f"connect 多了 {key}" for key in connect if key not in ("ssh", "port", "options", "bin")]
    port = connect.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        problems.append("connect.port 不是一个端口号")
    if connect.get("bin") is not None and (not isinstance(connect["bin"], str) or not connect["bin"]):
        problems.append("connect.bin 要写 ssh 和 scp 所在的文件夹")
    options = connect.get("options", [])
    if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
        problems.append("connect.options 必须是字符串的列表")
    if not row.get("job_root"):
        problems.append("worker 必须写 job_root")
    return problems


def parse_machines(doc) -> tuple[Machine, ...]:
    """把核对过的清单读成 Machine。清单不符就报 ValueError。"""
    problems = check_machines(doc)
    if problems:
        raise ValueError("机器清单不符：" + "；".join(problems))
    machines = []
    for row in doc["machines"]:
        connect = row.get("connect") or {}
        machines.append(Machine(
            name=row["name"], role=row["role"], host=row["host"], slots=row.get("slots", 0),
            ssh=connect.get("ssh"), port=connect.get("port", 22), options=tuple(connect.get("options", ())),
            bin=connect.get("bin"), python=row.get("python") or "python3",
            job_root=row.get("job_root"), backup_root=row.get("backup_root"),
        ))
    return tuple(machines)
