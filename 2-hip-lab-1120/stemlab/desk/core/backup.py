"""备份：把 data/ 推到 Linux 那台，并把各条链当时的链头记进 backup.json。

备份的是账：各条链、复制进来的内容、发布后只读的产物文件夹、每轮存下的插件差异。
插件自己的 work/ 和系统自己的各把锁不备份。产物只读、链只追加，所以每次只用传新增的部分。

它同时管两件事：
    恢复。核对只能发现问题，恢复靠备份。备份推过去之后，在 Linux 上用同一套核对再核一遍。
    发现末尾被删。哈希链查得出中间被改，查不出最后几条被删；
    since_last 会核对本机的链是不是上次备份那一份的延长，检查的入口里也跑它。

备份只往远端添东西，从不拿本机的去改远端已有的：
    本机的账自己核对不过、或者不是上次备份的延长，就不备份
    链只许变长：远端那一份必须是本机这一份的开头
    别的文件登记后就不变：远端已经有、大小却不一样的，不覆盖，报出来
"""
from __future__ import annotations

import io
import json
import shlex
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

from stemlab.contract import Refused, chain, hashing, layout, versions
from stemlab.experiments import reader as records
from stemlab.hooks import load, remote
from stemlab.registry import verify

CODE = "stemlab-verify"     # 远端 <backup_root> 下放核对用的代码的文件夹。数据在 <backup_root>/data

# 在远端核对用的脚本。只用标准库，所以远端的系统 Python 就能跑。只记位置的东西在远端没有，不核。
# 它的第一个参数是这次备份要记下的各条链的链头：远端的每条链都要到得了那里
_VERIFY = """
import json, sys
from stemlab.contract import chain, layout
from stemlab.experiments import reader
from stemlab.registry import lookup, verify
heads = json.loads(sys.argv[1])
problems = verify.verify_register() + verify.verify_links() + reader.verify_issued()
for experiment in reader.all_ids():
    problems += reader.verify(experiment)
wanted = [("register", layout.register_file(), heads["register"]), ("links", layout.links_file(), heads["links"]),
          ("issued", layout.issued_file(), heads["issued"])]
wanted += [(name, layout.record_file(name), head) for name, head in heads["records"].items()]
for title, path, head in wanted:
    if not chain.extends(reader.lines(path), chain.Head(head["seq"], head["this"])):
        problems.append(title + ": the copy on the backup machine does not reach entry %d recorded for this backup" % head["seq"])
if not problems and "contents" in sys.argv:
    for item in lookup.find():
        if item["storage"] != "ref":
            try:
                verify.verify_item(item["id"])
            except Exception as error:
                problems.append(str(error))
print(json.dumps(problems))
"""


def _experiments() -> list[str]:
    return [name for name in records.all_ids() if layout.record_file(name).exists()]


def heads() -> dict:
    """各条链现在的链头。备份时记下的就是它。"""
    def head(path) -> dict:
        found = chain.head_of(records.lines(path))
        return {"seq": found.seq, "this": found.this}

    return {"register": head(layout.register_file()), "links": head(layout.links_file()),
            "issued": head(layout.issued_file()),
            "records": {name: head(layout.record_file(name)) for name in _experiments()}}


def since_last() -> list[str]:
    """本机的各条链是不是上次备份那一份的延长。哈希链查不出末尾被删，这里查得出。

    返回哪条链不是；还没备份过就没有可比的，返回空列表。
    """
    try:
        saved = json.loads(layout.backup_file().read_bytes())["heads"]
    except FileNotFoundError:
        return []
    except (ValueError, KeyError) as error:
        return [f"backup.json 读不出来：{error}"]
    chains = {"登记链": (layout.register_file(), saved["register"]), "挂接链": (layout.links_file(), saved["links"]),
              "发号链": (layout.issued_file(), saved["issued"])}
    chains.update({f"{name} 的记录": (layout.record_file(name), head) for name, head in saved["records"].items()})
    problems = []
    for title, (path, head) in chains.items():
        lines = records.lines(path)
        if not chain.extends(lines, chain.Head(head["seq"], head["this"])):
            problems.append(f"{title}不是上次备份那一份的延长：备份时有 {head['seq']} 条，现在有 {len(lines)} 条，"
                            "备份过的条目被删过或被换过。用备份恢复")
    return problems


def is_chain(rel: str) -> bool:
    """这个文件是不是一条链（只追加，所以会变长）。别的要备份的文件登记后就不变。"""
    parts = rel.split("/")
    return (rel in ("registry/register.jsonl", "registry/links.jsonl", "experiments/issued.jsonl")
            or (len(parts) == 3 and parts[0] == "experiments" and parts[2] == "record.jsonl"))


def files() -> dict:
    """要备份的文件和它们现在的大小：相对 data/ 的路径 -> 字节数。

    不备份的只有：系统自己的几把锁、插件的 work/、登记到一半留在 store/ 里的东西。
    登记的内容里叫 .lock 的文件（比如包里的 uv.lock）照样备份。
    """
    root = layout.data_root()
    found = {}
    for rel in (hashing.list_tree(root) if root.is_dir() else []):
        parts = rel.split("/")
        if parts[0] == "registry":
            skip = rel == "registry/register.lock" or (parts[1] == "store" and parts[2].startswith((".incoming-", ".orphan-")))
        elif parts[0] == "experiments":
            skip = (rel == "experiments/issued.lock" or (len(parts) > 2 and parts[2] == "work")
                    or (len(parts) == 3 and parts[2] in ("record.lock", "busy.lock")))
        else:
            skip = True                                 # data/ 根下的值守锁、backup.json 之类
        if not skip:
            found[rel] = (root / rel).stat().st_size
    return found


def backup(machine_name: str, contents: bool = False) -> dict:
    """把 data/ 备份到机器清单里的这台机器上，返回这次做了什么。

    只传远端没有的文件和变长了的链。传完在远端核对一遍（contents=True 时连内容的哈希也核），
    都对了才把链头记进 backup.json。哪一步不过都是被拒，远端已有的备份不会被改坏。
    """
    machine = remote.worker(machine_name)
    if not machine.backup_root:
        raise Refused(f"机器清单里 {machine_name} 没有写 backup_root")
    root = machine.backup_root.rstrip("/")
    place = shlex.quote(f"{root}/data")

    broken = verify.verify_register() + verify.verify_links() + records.verify_issued()
    for name in _experiments():
        broken += records.verify(name)
    broken += since_last()
    if broken:
        raise Refused("本机的账核对不过，没有备份，远端的那一份没有动。先查清楚，该恢复就用备份恢复：" + "；".join(broken[:5]))

    at_start = heads()                                  # 先记链头，再看有哪些文件：传过去的至少到这里
    local = files()
    listing = remote.ssh(machine, f"mkdir -p {place} && cd {place} && find . -type f -printf '%s %P\\n'", 600.0)
    there = {rel: int(size) for size, _, rel in (line.partition(" ") for line in listing.decode("utf-8").splitlines())}
    grown = sorted(rel for rel, size in local.items() if is_chain(rel) and rel in there and there[rel] < size)
    changed = sorted(rel for rel, size in local.items() if rel in there and there[rel] != size and rel not in grown)
    if changed:
        raise Refused("这些文件和远端的备份对不上，没有覆盖远端的（不该变的文件变了，或者链比备份的还短）："
                      + "、".join(changed[:10]))
    _check_prefixes(machine, place, grown, there)
    todo = sorted(rel for rel, size in local.items() if there.get(rel) != size)
    if todo:
        _send(machine, f"tar -xf - -C {place}", layout.data_root(), {rel: local[rel] for rel in todo})
    _send_code(machine, root)

    script = (f"cd {shlex.quote(f'{root}/{CODE}')} && STEMLAB_DATA={place} python3 -c {shlex.quote(_VERIFY)} "
              + shlex.quote(json.dumps(at_start)) + (" contents" if contents else ""))
    problems = json.loads(remote.ssh(machine, script, 3600.0).decode("utf-8").strip().splitlines()[-1])
    if problems:
        raise Refused("备份传过去了，但在远端核对没过，backup.json 没有更新：" + "；".join(problems[:5]))

    done = {"format": versions.FORMATS["backup"], "time": chain.stamp(datetime.now(timezone.utc)),
            "machine": machine_name, "heads": at_start, "files": len(local), "sent": len(todo)}
    layout.backup_file().write_bytes(hashing.canonical(done) + b"\n")
    return done


def _check_prefixes(machine, place: str, grown: list[str], there: dict) -> None:
    """链只许变长：远端那一份必须是本机这一份的开头。不是的话，本机的链被换过，不能拿去盖远端的。"""
    grown = [rel for rel in grown if there[rel] > 0]
    if not grown:
        return
    asked = remote.ssh(machine, f"cd {place} && sha256sum -- " + " ".join(map(shlex.quote, grown)), 600.0)
    remote_hash = {rel: digest for digest, _, rel in (line.partition("  ") for line in asked.decode("utf-8").splitlines())}
    for rel in grown:
        with open(layout.data_root() / rel, "rb") as stream:
            if hashing.hash_bytes(stream.read(there[rel])) != remote_hash.get(rel):
                raise Refused(f"{rel} 在远端的那一份不是本机这一份的开头：备份之后链被换过。没有覆盖远端的，用备份恢复")


def _send(machine, script: str, root, sizes: dict) -> None:
    """把 root 下的这些文件打成 tar，边打边经 ssh 送到远端解开。每个文件只送列出来的那么多字节。

    链只追加：列完之后又追加的条目这次不送，这样送过去的各个文件是同一个时刻的样子。
    """
    command = [remote._tool(machine, "ssh"), "-p", str(machine.port), *machine.options, machine.ssh, script]
    with tempfile.TemporaryFile() as complaints:        # 远端的报错写进文件，不占管道：管道满了两边会一起卡死
        receiver = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=complaints,
                                    **remote._QUIET)
        cut = None
        try:
            with tarfile.open(fileobj=receiver.stdin, mode="w|") as tar:
                for rel, size in sizes.items():
                    info = tarfile.TarInfo(rel)
                    info.size, info.mode = size, 0o644
                    with open(root / rel, "rb") as stream:
                        tar.addfile(info, io.BytesIO(stream.read(size)) if size < 1 << 24 else stream)
            receiver.stdin.close()
            code = receiver.wait(timeout=3600)
        except (OSError, subprocess.TimeoutExpired) as error:
            receiver.kill()
            receiver.wait()
            cut = error
        complaints.seek(0)
        said = complaints.read().decode("utf-8", "replace").strip()
    if cut is not None:                                 # 对面先走了（盘满了、连接断了）：把它留下的话带上
        raise remote.Unreachable(f"往 {machine.name} 送备份的时候断了：{cut}" + (f"。对面说：{said[-600:]}" if said else ""))
    if code != 0:
        raise Refused(f"{machine.name} 没有收下备份（退出码 {code}）：{said[-600:]}")


def _send_code(machine, root: str) -> None:
    """把 stemlab/ 现在的样子送到远端的 <backup_root>/stemlab-verify/，在远端核对用的就是它。"""
    repo = layout.repo_root() / "stemlab"
    sizes = {f"stemlab/{rel}": (repo / rel).stat().st_size for rel in hashing.list_tree(repo, ignore=load.IGNORE)}
    place = shlex.quote(f"{root}/{CODE}")
    _send(machine, f"rm -rf {place} && mkdir -p {place} && tar -xf - -C {place}", layout.repo_root(), sizes)
