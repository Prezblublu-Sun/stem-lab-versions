"""核对用的函数：把导出的东西和归档原文（或旧库）逐值比，返回不一样的地方。

这里读归档用的是另一套写法（标准库的 tarfile 和 csv，逐格 float()），不用插件自己的读法，
这样插件读错了能比出来。返回的列表是空的表示全一样。
"""
from __future__ import annotations

import csv
import io
import json
import tarfile
from pathlib import Path

import numpy as np


def tar_files(tar_path: Path) -> dict:
    """归档里的每个文件：{相对路径: 字节}。"""
    out = {}
    with tarfile.open(tar_path, "r:xz") as tf:
        for m in tf:
            if m.isfile():
                out[m.name.split("/", 1)[1]] = tf.extractfile(m).read()
    return out


def csv_rows(data: bytes) -> tuple[list[str], list[list[str]]]:
    rows = [r for r in csv.reader(io.StringIO(data.decode("utf-8"), newline="")) if r]
    return rows[0], rows[1:]


def same_number(a: float, b: float) -> bool:
    return a == b or (a != a and b != b)


def diff_global(npz_path: Path, files: dict, limit: int = 20) -> list[str]:
    """整体场文件对归档原文：网格的节点数、单元数和每个数组；每张表的行数、编号、每个值。"""
    bad: list[str] = []
    z = np.load(npz_path, allow_pickle=False)
    index = json.loads(str(z["index"]))
    tables = {t["file"]: t for t in index["tables"]}

    if "mesh3d.npz" in files:
        mesh = np.load(io.BytesIO(files["mesh3d.npz"]), allow_pickle=False)
        for k in mesh.files:
            key = "mesh_" + k
            if key not in z.files:
                bad.append(f"网格数组 {k} 没导出")
            elif z[key].dtype != mesh[k].dtype or z[key].shape != mesh[k].shape or not np.array_equal(z[key], mesh[k]):
                bad.append(f"网格数组 {k} 和归档里的不一样")
        n_nodes = len(mesh["node_labels"])
        n_elems = sum(len(mesh[k]) for k in mesh.files if k.endswith("_elab"))
        if len(z["mesh_nodes"]) != n_nodes:
            bad.append(f"节点数 {len(z['mesh_nodes'])} 对 {n_nodes}")
        got_elems = sum(len(z[k]) for k in z.files if k.startswith("mesh_") and k.endswith("_elab"))
        if got_elems != n_elems:
            bad.append(f"单元数 {got_elems} 对 {n_elems}")
    elif any(k.startswith("mesh_") for k in z.files):
        bad.append("归档里没有网格，导出里却有")

    wide = {}
    for rel, data in files.items():
        if "/" in rel and rel.endswith(".csv"):
            head, rows = csv_rows(data)
            if head[0] in ("node", "elem"):
                wide[rel] = (head, rows)
    for rel in sorted(set(tables) - set(wide)):
        bad.append(f"导出里有 {rel}，归档里没有这张表")
    for rel, (head, rows) in sorted(wide.items()):
        t = tables.get(rel)
        if t is None:
            bad.append(f"归档里的 {rel} 没导出")
            continue
        lab, val = z[t["label_key"]], z[t["key"]]
        if t["columns"] != head[1:] or t["label_kind"] != head[0]:
            bad.append(f"{rel}：列名不一样 {t['columns']} 对 {head[1:]}")
        if len(lab) != len(rows) or val.shape != (len(rows), len(head) - 1):
            bad.append(f"{rel}：行数 {val.shape} 对 {len(rows)} 行 {len(head) - 1} 列")
            continue
        for i, r in enumerate(rows):
            if int(lab[i]) != int(r[0]):
                bad.append(f"{rel} 第 {i + 1} 行：编号 {int(lab[i])} 对 {r[0]}")
            for j, cell in enumerate(r[1:]):
                if not same_number(float(val[i, j]), float(cell)):
                    bad.append(f"{rel} 第 {i + 1} 行 {head[j + 1]}：{float(val[i, j])!r} 对 {cell}")
            if len(bad) >= limit:
                return bad
    return bad


def diff_iface(npz_path: Path, files: dict, model_dir: str = "m_fric_csv", limit: int = 20) -> list[str]:
    """界面场文件对归档原文：相对位移、接触量、接触力，按节点编号一个个比。"""
    bad: list[str] = []
    z = np.load(npz_path, allow_pickle=False)
    steps = [str(s) for s in z["steps"]]
    pb, ps = [int(v) for v in z["node_bone"]], [int(v) for v in z["node_stem"]]
    mesh = np.load(io.BytesIO(files["mesh3d.npz"]), allow_pickle=False)
    if pb != [int(v) for v in mesh["pair_bone"]] or ps != [int(v) for v in mesh["pair_stem"]]:
        bad.append("节点对和网格里的不一样")
    for k_out, k_in in (("nrm", "pair_normal"), ("area", "pair_area"), ("interf", "pair_interf")):
        if not np.array_equal(z[k_out], mesh[k_in]):
            bad.append(f"{k_out} 和网格里的 {k_in} 不一样")
    coords = {int(lab): mesh["nodes"][i] for i, lab in enumerate(mesh["node_labels"])}
    if not all(np.array_equal(z["X"][i], coords[n]) for i, n in enumerate(pb)):
        bad.append("X 不是骨侧节点的坐标")
    where_b = {n: i for i, n in enumerate(pb)}
    where_s: dict = {}
    for i, n in enumerate(ps):
        where_s.setdefault(n, i)
    present = {rel.split("/", 1)[1][:-6] for rel in files if rel.startswith(model_dir + "/") and rel.endswith("_U.csv")}
    if set(steps) != present:
        bad.append(f"分析步 {steps} 对归档里有位移的步 {sorted(present)}")
    for si, s in enumerate(steps):
        _, rows = csv_rows(files[f"{model_dir}/{s}_U.csv"])
        u = {int(r[0]): [float(c) for c in r[1:]] for r in rows}
        for i, (nb, ns) in enumerate(zip(pb, ps)):
            want = [u[ns][c] - u[nb][c] for c in range(3)]
            if not all(same_number(float(z["rel"][i, si, c]), want[c]) for c in range(3)):
                bad.append(f"{s} 第 {i} 对：相对位移 {z['rel'][i, si].tolist()} 对 {want}")
        for q, prefix in (("CONTACT", "c_"), ("CFORCE", "f_")):
            rel_name = f"{model_dir}/{s}_{q}.csv"
            if rel_name not in files:
                continue
            _, rows = csv_rows(files[rel_name])
            seen: dict = {}
            placed = 0
            for r in rows:
                field, node, vals = r[0], int(r[1]), [float(c) for c in r[2:]]
                first = (field, node) not in seen
                seen[(field, node)] = True
                hit = False
                for side, where in (("", where_b), ("_stem", where_s)):
                    if first and node in where:
                        i = where[node]
                        got = np.atleast_1d(z[f"{prefix}{field}{side}"][i, si]).astype(np.float64).tolist()
                        if not all(same_number(g, w) for g, w in zip(got, vals)):
                            bad.append(f"{s} {q} {field}{side} 节点 {node}：{got} 对 {vals}")
                        hit = True
                if hit:
                    placed += 1
                else:  # 没落到节点对上的行，应该原样在 extra 里
                    key = f"extra__{s}__{q}__{field}__label"
                    if key not in z.files or node not in [int(v) for v in z[key]]:
                        bad.append(f"{s} {q} {field} 节点 {node} 这一行丢了")
            if len(bad) >= limit:
                return bad
    return bad


def diff_labels(mine: dict, old: dict, columns: list[str], may_be_empty: set[str]) -> list[str]:
    """一行标签对旧表的同一行，逐格比文字。

    may_be_empty：旧表从归档以外补过的列。这些列里本插件留空而旧表有值，不算不同；
    本插件有值而和旧表不一样，照样算不同。
    """
    bad = []
    for c in columns:
        if c not in old:
            continue
        if mine[c] == old[c]:
            continue
        if mine[c] == "" and c in may_be_empty:
            continue
        bad.append(f"{c}：{mine[c]!r} 对旧表的 {old[c]!r}")
    return bad


def diff_iface_old(npz_path: Path, shard: dict, j: int) -> list[str]:
    """界面场文件对旧库界面场分片里的同一个作业。"""
    bad = []
    z = np.load(npz_path, allow_pickle=False)
    a, b = int(shard["off"][j]), int(shard["off"][j + 1])
    ta, tb = int(shard["tri_off"][j]), int(shard["tri_off"][j + 1])
    steps = [str(s) for s in z["steps"]]
    old_steps = [str(s) for s in shard["steps"]]
    idx = [steps.index(s) for s in old_steps]
    for k_new, k_old in (("X", "X"), ("nrm", "nrm"), ("area", "area"), ("interf", "interf"), ("cortex", "cortex"),
                         ("collar", "collar"), ("node_bone", "node_bone"), ("node_stem", "node_stem")):
        if not np.array_equal(z[k_new], shard[k_old][a:b]):
            bad.append(f"{k_new} 不一样")
    if not np.array_equal(z["rel"][:, idx], shard["rel"][a:b]):
        bad.append("rel 不一样")
    if not np.array_equal(z["gap"][:, idx].astype(np.float32), shard["gap"][a:b]):
        bad.append("gap 不一样")
    for k_new, k_old in (("c_CPRESS", "cpress"), ("c_CSTATUS", "cstatus"), ("c_COPEN", "copen")):
        if not np.array_equal(z[k_new][:, idx].astype(np.float32), shard[k_old][a:b], equal_nan=True):
            bad.append(f"{k_new} 和旧库的 {k_old} 不一样")
    two = [steps.index("LOAD"), steps.index("LOAD2")]
    if not np.array_equal(z["cforce"][:, two].astype(np.float32), shard["cforce"][a:b], equal_nan=True):
        bad.append("cforce 不一样")
    if not np.array_equal(z["tri"], shard["tri"][ta:tb]):
        bad.append("三角形不一样")
    return bad
