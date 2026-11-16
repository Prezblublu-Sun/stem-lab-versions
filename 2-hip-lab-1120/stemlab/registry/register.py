"""登记外来的东西和发布的产物；登记这一块唯一的追加函数。

登记后不改不删。同名再登记，版本加一，编号是新的。
复制进来的内容放在 data/registry/store/<编号>/，设成只读。
内容先刷到盘上，再写链上那一行（durable）：断电时，链上不会留下一条指向半截内容的记录。
"""
from __future__ import annotations

import os
import shutil
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from stemlab.contract import Refused, chain, hashing, kinds, layout, origin, versions
from stemlab.contract.formats import manifest
from stemlab.registry import lock


def append(path: Path, name: str, build, check, place=None) -> dict:
    """登记这一块唯一的追加函数，register.jsonl 和 links.jsonl 都经它。

    build(序号, 现有的条目) 在锁里被叫，给出这一条的内容；check 核它长得对不对；
    place(条目) 在写之前把内容放到位。哪一步不过都是被拒，链上不多一条。
    """
    with lock.writing():                                                    # 1 拿这条链的锁
        data = path.read_bytes() if path.exists() else b""
        lines, tail = chain.split(data)                                     # 2 末尾写了一半的一行，下面截掉
        existing = [versions.upcast(name, chain.parse(line)) for line in lines]
        head = chain.head_of(lines)                                         # 3 读链头，给序号和上一条的哈希
        body = dict(build(head.seq + 1, existing), format=versions.FORMATS[name],
                    time=chain.stamp(datetime.now(timezone.utc)))
        entry = chain.link(body, head)
        problems = check(entry)
        if problems:
            raise Refused("；".join(problems))
        if place:
            place(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "r+b" if path.exists() else "wb") as stream:        # 5 按字节追加一行，然后落盘
            stream.seek(len(data) - tail)
            stream.truncate()
            stream.write(chain.dumps(entry))
            stream.flush()
            os.fsync(stream.fileno())
    return entry                                                            # 6 放锁


def register_external(kind: str, name: str, *, note: str, by: str, value=None, source=None,
                      storage: str | None = None, bone_id: str | None = None, new_bone: bool = False) -> dict:
    """登记一样外面拿来的东西，返回登记下的那一条。

    值给 value；文件夹给 source，storage 写 copy（复制一份进 data/，默认）或 ref（只记位置）。
    骨源、人工修改、归档清单、报告这几种没带清单的，复制时替它生成一份。
    登记一个没见过的骨标识要明说是新骨（new_bone），防打错字。
    """
    if kind not in kinds.ITEM_KINDS:
        raise Refused(f"登记的种类里没有 {kind!r}")
    storage = storage or kinds.storages(kind)[0]
    if storage not in kinds.storages(kind):
        raise Refused(f"{kind} 不能存成 {storage!r}，只能是 {kinds.storages(kind)}")
    staged = None
    if storage == kinds.STORE_VALUE:
        content = value
        try:
            digest = hashing.hash_json(value)
        except (TypeError, ValueError) as error:
            raise Refused(f"这个值写不进 JSON：{error}") from None
    else:
        if source is None or not Path(source).is_dir():
            raise Refused(f"找不到要登记的文件夹：{source}")
        folder = Path(source).resolve()
        content = folder.as_posix()
        if storage == kinds.STORE_COPY:
            folder = staged = _stage(kind, folder, bone_id)
        try:
            problems = manifest.check_format(kind, folder)
            if problems and storage == kinds.STORE_REF and not (folder / manifest.MANIFEST).exists():
                problems.append("只记位置的不替你往原处写清单：先在那里放一份清单，或者改成复制")
            if problems:
                raise Refused(f"不符合 {kind} 的格式：" + "；".join(problems))
            listed = manifest.read_manifest(folder).get("bone_id")
            if bone_id and listed and bone_id != listed:
                raise Refused(f"清单里的骨标识是 {listed!r}，登记时给的是 {bone_id!r}")
            bone_id = bone_id or listed
            digest = hashing.hash_tree(folder)
            if staged:
                durable(staged)                 # 复制进来的先刷到盘上，再上链
        except BaseException:
            _discard(staged)
            raise

    def build(seq: int, existing: list[dict]) -> dict:
        item_id = layout.item_id(seq, kinds.ITEM_KINDS[kind].case)
        _check_bone(existing, kind, bone_id, new_bone)
        return {"id": item_id, "kind": kind, "name": name, "version": _version(existing, kind, name),
                "storage": storage, "content": layout.inside(layout.store_dir(item_id)) if staged else content,
                "hash": digest, "origin": origin.external(note, by), "bone_id": bone_id}

    def place(entry: dict) -> None:
        _make_room(entry)
        if staged:
            final = layout.store_dir(entry["id"])
            rename(staged, final)
            _sync_dir(final.parent)             # 改名也落盘，再写链
            read_only(final)

    try:
        return append(layout.register_file(), "register", build, kinds.check_item, place)
    finally:
        _discard(staged)


def register_output(kind: str, name: str, content: str, tree_hash: str, product: dict, bone_id: str | None) -> dict:
    """登记一样发布的产物。内容已经在 data/ 里、哈希已经由发布算好；这里只收，不再算。只许 hooks/publish.py 叫。"""
    def build(seq: int, existing: list[dict]) -> dict:
        if bone_id is not None and bone_id not in {item["bone_id"] for item in existing}:
            raise Refused(f"产物的骨标识 {bone_id!r} 登记里没见过。产物的骨标识要从它的输入继承")
        return {"id": layout.item_id(seq, kinds.ITEM_KINDS[kind].case), "kind": kind, "name": name,
                "version": _version(existing, kind, name), "storage": kinds.STORE_COPY, "content": content,
                "hash": tree_hash, "origin": product, "bone_id": bone_id}

    return append(layout.register_file(), "register", build, kinds.check_item, _make_room)


def _version(existing: list[dict], kind: str, name: str) -> int:
    same = [item for item in existing if item["name"] == name]
    if same and same[0]["kind"] != kind:
        raise Refused(f"{name} 已经登记成 {same[0]['kind']} 了，同名不能换种类")
    near = next((item["name"] for item in existing
                 if isinstance(name, str) and item["name"].lower() == name.lower() and item["name"] != name), None)
    if near:
        raise Refused(f"已经有一个只差大小写的名字 {near!r}，是不是打错了")
    return len(same) + 1


def _check_bone(existing: list[dict], kind: str, bone_id, new_bone: bool) -> None:
    known = [item["bone_id"] for item in existing if item["bone_id"] is not None]
    if bone_id is None:
        if new_bone:
            raise Refused("说了是新骨，却没给骨标识")
        return                          # case 没给骨标识，由 check_item 拒
    if bone_id in known:
        if new_bone:
            raise Refused(f"骨标识 {bone_id!r} 已经有了，不是新骨。新骨要换一个标识")
        return
    near = next((seen for seen in known if isinstance(bone_id, str) and seen.lower() == bone_id.lower()), None)
    if near:
        raise Refused(f"已经有一个只差大小写的骨标识 {near!r}，是不是打错了")
    if not new_bone:
        raise Refused(f"没见过骨标识 {bone_id!r}。如果是新骨，要明说是新骨；不是的话，看看是不是打错了")


# ---------------------------------------------------------------- 文件夹的搬动

def _stage(kind: str, source: Path, bone_id) -> Path:
    """把要登记的文件夹先复制到 store/ 下的一个临时位置。编号要等拿到锁才知道。

    复制不成（有文件正被占着、里面有链接之类）就是被拒，复制到一半的那份删掉。
    """
    staged = layout.store_root() / f".incoming-{uuid.uuid4().hex}"
    staged.parent.mkdir(parents=True, exist_ok=True)
    try:
        hashing.list_tree(source)       # 里面有链接、交接点或读不了的地方，现在就说，不等抄到一半
        shutil.copytree(source, staged)
        generic = kinds.ITEM_KINDS[kind].format == "manifest"
        if generic and not (staged / manifest.MANIFEST).exists():
            extra = {"bone_id": bone_id} if bone_id else {}
            manifest.write_manifest(staged, manifest.make_manifest(kind, hashing.list_tree(staged), **extra))
    except (OSError, ValueError) as error:
        _discard(staged)
        raise Refused(f"复制 {source} 的时候出错了，什么都没登记：{error}") from None
    return staged


def _make_room(entry: dict) -> None:
    """这个编号还没上链。store/ 里要是已经有它名下的东西，挪到一边留着，不删。

    那只能是上次登记到一半留下的，或者链丢了尾巴之后剩下的内容；后一种正是恢复时要用的。
    挪到一边的叫 .orphan-<编号>-…，检查会把它报出来，由人决定去留。
    """
    seq = layout.id_seq(entry["id"])
    for case in (True, False):
        taken = layout.store_dir(layout.item_id(seq, case))
        if taken.exists():
            rename(taken, taken.with_name(f".orphan-{taken.name}-{uuid.uuid4().hex[:8]}"))


def rename(source: Path, target: Path, tries: int = 8) -> None:
    """把文件夹改名到位，带退避重试。

    Windows 上打开着的文件不能改名：杀毒、索引、仪表盘正好读着时会偶发失败，等一下再试。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(tries):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * 2 ** attempt)


def durable(folder: Path) -> None:
    """把文件夹里的文件刷到盘上，连同文件夹自己和它在上一级里的那一项。上链之前做。

    Windows 上的文件要用写的方式打开才刷得了，所以在设成只读之前做；已经是只读的，是上一次设只读之前刷过的。
    Windows 上文件夹刷不了，靠 NTFS 自己的日志。刷不了（文件正被别处占着之类）就被拒，什么都不登记，下次再来。
    """
    try:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                _flush(path)
        for path in [folder.parent, folder, *sorted(p for p in folder.rglob("*") if p.is_dir())]:
            _sync_dir(path)
    except OSError as error:
        raise Refused(f"内容刷不到盘上，先不登记：{error}") from None


def _flush(path: Path) -> None:
    if os.name == "nt":
        if os.access(path, os.W_OK):
            with open(path, "r+b") as stream:
                os.fsync(stream.fileno())
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_dir(path: Path) -> None:
    """把文件夹里的那几项（新建、改名）刷到盘上。只在 Linux 这类系统上做得了。"""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_only(folder: Path) -> None:
    """把文件夹里的文件都设成只读。Linux 上连文件夹也设，Windows 上文件夹设不了。"""
    for path in folder.rglob("*"):
        if path.is_file():
            os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    if os.name != "nt":
        for path in [folder, *(p for p in folder.rglob("*") if p.is_dir())]:
            os.chmod(path, 0o555)


def _discard(folder: Path | None) -> None:
    """删掉一个没登记上的文件夹。已经登记的东西从不删。"""
    if folder is None or not folder.exists():
        return

    def force(function, path, error):   # 只读的先放开再删
        os.chmod(path, stat.S_IRWXU)
        function(path)

    if os.name != "nt":
        for path in [folder, *(p for p in folder.rglob("*") if p.is_dir())]:
            os.chmod(path, 0o755)
    shutil.rmtree(folder, onexc=force)
