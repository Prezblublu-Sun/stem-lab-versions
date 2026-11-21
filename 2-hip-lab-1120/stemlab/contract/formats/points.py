"""一批点和候选池。两种都是一个文件夹：清单加一个 points.jsonl，一行一个点。

一批点（points）的一行：
    {"name": "p001", "bone_id": "femur042", "design": {...}, "conditions": {...}, "placement": {...}, "derive": {...},
     "reason": ..., "hash": "..."}
候选池（pool）的一行：
    {"name": "c0001", "bone_id": "femur042", "design": {...}, "feasible": true, "info": {...}}

一批点每个点给的取值分三组（第 2 版，《设定的声明和包的清单》第四节）：
    conditions   有限元设定里写了“每个点给”的项（就是原来的条件）
    placement    放置设定里写了“每个点给”的项，比如截骨面比参考低多少
    derive       推导量设定里写了“每个点给”的项，比如分哪几个区、阈值多少

清单另带：count 有几行；design_keys 设计有哪几项；一批点还带 condition_keys、placement_keys、derive_keys，三组各有哪几项。
三组都必须写全：每个点都带齐那一组的每一项，不能是 null。
每个点的哈希由骨标识、设计、三组取值算出；预测和 FEA 的结果按它对齐，所以一批里同一个点只能出现一次。
放置、推导量两组空着的时候不算进哈希：和第 1 版的哈希一模一样，账里已有的点和数据照样对得上。
第 1 版的一批点没有这两组：核对和写的时候当成空的（with_groups）。read_points 不补，它也用来读数据的行。
"""
from __future__ import annotations

import json
from pathlib import Path

from stemlab.contract.formats.manifest import check_manifest, make_manifest, write_manifest
from stemlab.contract.hashing import canonical, hash_json
from stemlab.contract.layout import is_column, is_label, same_but_case

POINTS_FILE = "points.jsonl"
POINT_KEYS = ("name", "bone_id", "design", "conditions", "placement", "derive", "reason", "hash")
POOL_KEYS = ("name", "bone_id", "design", "feasible", "info")
GROUPS = {"conditions": ("condition_keys", "条件"), "placement": ("placement_keys", "放置"), "derive": ("derive_keys", "推导量")}
LATER = ("placement", "derive")         # 第 2 版加的两组
_MAX_PROBLEMS = 20


def point_hash(point: dict) -> str:
    """一个点的哈希：骨标识、设计、写全的三组取值合起来算。名字和理由不算在内。
    放置、推导量两组空着（或没写）就不算进去，和第 1 版的哈希一样。"""
    payload = {"bone_id": point["bone_id"], "design": point["design"], "conditions": point["conditions"]}
    payload.update({group: point[group] for group in LATER if point.get(group)})
    return hash_json(payload)


def with_groups(row):
    """一批点的一行，补上没写的放置、推导量两组（空的）。第 1 版的行就是这样读成第 2 版的。"""
    return {**{group: {} for group in LATER}, **row} if isinstance(row, dict) else row


def fill_defaults(points, defaults: dict) -> list[dict]:
    """用一份条件默认把每个点的条件补全。已经写了的不改；补两次和补一次结果相同。"""
    filled = []
    for point in points:
        row = with_groups(dict(point, conditions={**defaults, **point.get("conditions", {})}))
        row["hash"] = point_hash(row)
        filled.append(row)
    return filled


def read_points(path) -> list[dict]:
    """读出各行。path 可以是带 points.jsonl 的文件夹，也可以是一个手写的 .jsonl 文件。"""
    path = Path(path)
    source = path / POINTS_FILE if path.is_dir() else path
    rows = []
    # 只按 LF 切行：JSON 的字符串里可以有别的“换行”字符，不能被当成行尾
    for number, line in enumerate(source.read_bytes().decode("utf-8-sig").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{source.name} 第 {number} 行不是合法的 JSON：{error}") from None
        if not isinstance(row, dict):
            raise ValueError(f"{source.name} 第 {number} 行必须是一个 JSON 对象")
        rows.append(row)
    return rows


def write_points(folder, points, kind: str = "points", **more) -> dict:
    """把各行写成一个符合格式的文件夹：points.jsonl 和清单。返回清单。

    一批点的哈希在这里算好写进去。写之前先核一遍，不符就报 ValueError，什么都不写。
    more 是清单里另加的项，比如候选池的 made_by（是哪个内核模板化的）；这种格式自己的项不能用它盖掉。
    """
    rows = [dict(point) if isinstance(point, dict) else point for point in points]
    if not rows:
        raise ValueError("一批点不能是空的")
    taken = sorted(set(more) & {"format", "kind", "files", "count", "design_keys", *(keys for keys, _ in GROUPS.values())})
    if taken:
        raise ValueError(f"这几项是格式自己的，不能另给：{taken}")
    if kind == "points":
        rows = [with_groups(row) for row in rows]

    def keys(name: str) -> list:
        group = rows[0].get(name) if isinstance(rows[0], dict) else None
        return sorted(map(str, group)) if isinstance(group, dict) else []

    extra = {"count": len(rows), "design_keys": keys("design")}
    if kind == "points":
        extra.update({listed: keys(group) for group, (listed, _) in GROUPS.items()})
        for row in rows:
            if (isinstance(row, dict) and isinstance(row.get("design"), dict) and "bone_id" in row
                    and all(isinstance(row.get(group), dict) for group in GROUPS)):
                row["hash"] = _hash_or_none(row)
    manifest = make_manifest(kind, [POINTS_FILE], **extra, **more)
    problems = check_manifest(kind, manifest) or check_points(kind, manifest, rows)
    if problems:
        raise ValueError("这批点不符合格式：" + "；".join(problems))
    try:
        lines = b"".join(canonical(row) + b"\n" for row in rows)
    except (TypeError, ValueError) as error:
        raise ValueError(f"这批点里有写不进 JSON 的东西：{error}") from None
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / POINTS_FILE, "wb") as stream:
        stream.write(lines)
    write_manifest(folder, manifest)
    return manifest


def check_points(kind: str, manifest: dict, rows) -> list[str]:
    """核对一批点或一个候选池。返回哪里不符，点名是哪个点；空列表就是对的。第 1 版的行缺的两组当成空的。"""
    wanted = POINT_KEYS if kind == "points" else POOL_KEYS
    key_lists = ("design_keys", *(keys for keys, _ in GROUPS.values())) if kind == "points" else ("design_keys",)
    if kind == "points":
        rows = [with_groups(row) for row in rows]
    problems = []
    for key in key_lists:
        value = manifest.get(key)
        if not isinstance(value, list) or not all(map(is_column, value)) or value != sorted(set(value)):
            problems.append(f"清单的 {key} 必须是排好序、不重复的名字列表（字母开头，字母、数字、下划线）")
        elif same_but_case(value):
            problems.append(f"清单的 {key} 里有只差大小写的名字：{same_but_case(value)}")
    if manifest.get("count") != len(rows):
        problems.append(f"清单写的是 {manifest.get('count')!r} 行，实际是 {len(rows)} 行")
    if problems:
        return problems

    seen: dict[str, int] = {}
    hashes: dict[str, int] = {}
    for number, row in enumerate(rows, start=1):
        if len(problems) >= _MAX_PROBLEMS:
            problems.append("……还有更多，先改上面这些")
            break
        name = row.get("name") if isinstance(row, dict) else None
        title = f"第 {number} 个点（{name!r}）"
        if not isinstance(row, dict) or set(row) != set(wanted):
            problems.append(f"{title} 要带且只带这几项：{list(wanted)}")
            continue
        if not is_label(name):
            problems.append(f"{title} 的名字要用 ASCII 的字母、数字和 . _ -")
        elif seen.setdefault(name.lower(), number) != number:
            problems.append(f"{title} 的名字和第 {seen[name.lower()]} 个点重复了")
        if not is_label(row["bone_id"]):
            problems.append(f"{title} 的骨标识不对：{row['bone_id']!r}")
        problems += _check_group(title, "设计", row["design"], manifest["design_keys"])
        if kind == "points":
            groups = [_check_group(title, what, row[group], manifest[listed]) for group, (listed, what) in GROUPS.items()]
            problems += [text for found in groups for text in found]
            if row["reason"] in (None, "", {}, []):
                problems.append(f"{title} 没有写理由")
            if not any(groups):                                         # 哪一组不是对象、没写全，哈希先不核
                if row["hash"] != _hash_or_none(row):
                    problems.append(f"{title} 的哈希和它的骨标识、设计、三组取值对不上")
                elif hashes.setdefault(row["hash"], number) != number:  # 结果按点的哈希对齐，所以一批里一个点只能有一次
                    problems.append(f"{title} 和第 {hashes[row['hash']]} 个点是同一个点（骨标识、设计、三组取值都一样）")
        elif not isinstance(row["feasible"], bool) or not isinstance(row["info"], dict):
            problems.append(f"{title} 的 feasible 必须是 true 或 false，info 必须是一个 JSON 对象")
    return problems


def _hash_or_none(row: dict) -> str | None:
    try:
        return point_hash(row)
    except (TypeError, ValueError):     # 里面有写不进 JSON 的东西，比如 NaN
        return None


def _check_group(title: str, what: str, group, keys: list) -> list[str]:
    if not isinstance(group, dict):
        return [f"{title} 的{what}必须是一个 JSON 对象"]
    missing = [key for key in keys if group.get(key) is None]
    extra = [key for key in group if key not in keys]
    problems = []
    if missing:
        problems.append(f"{title} 的{what}没写全，缺 {missing}")
    if extra:
        problems.append(f"{title} 的{what}多了 {extra}")
    return problems


def check(kind: str, manifest: dict, folder) -> list[str]:
    """check_format 叫的入口：清单里的文件对，再读出各行来核。"""
    if manifest["files"] != [POINTS_FILE]:
        return [f"一批点的文件夹里只该有 {POINTS_FILE}"]
    try:
        rows = read_points(folder)
    except ValueError as error:
        return [str(error)]
    return check_points(kind, manifest, rows)
