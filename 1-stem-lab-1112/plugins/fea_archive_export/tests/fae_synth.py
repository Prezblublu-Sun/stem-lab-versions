"""造一个很小的假归档，样子和真归档一样：<作业号>.tar.xz 加 <作业号>.manifest.json。

模型：一个皮质单元、一个松质单元、一个柄单元（都是十节点四面体）。
松质单元的一个面是界面，上面 6 个节点各和柄的一个节点成对。
节点编号故意不连续（1–20 和 31–40），用来查按编号取数对不对。
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import numpy as np

BONE_PAIR = [11, 12, 13, 15, 16, 17]
STEM_PAIR = [31, 32, 33, 35, 36, 37]
NODE_LABELS = list(range(1, 21)) + list(range(31, 41))
STEPS4 = ["RELEASE", "LOAD", "UNLOAD", "LOAD2"]
T0 = 1_800_000_000  # 归档里文件的修改时间从这里起


def f32(x) -> float:
    """真归档里的数是 float32 写成的小数。"""
    return float(np.float32(x))


def tet10(corners: np.ndarray) -> np.ndarray:
    a, b, c, d = corners
    return np.array([a, b, c, d, (a + b) / 2, (b + c) / 2, (a + c) / 2, (a + d) / 2, (b + d) / 2, (c + d) / 2])


def mesh_arrays() -> dict:
    rng = np.random.default_rng(7)
    cortex = tet10(np.array([[0, 0, 0], [4, 0, 0], [0, 4, 0], [0, 0, 4]], float) + 20)
    canc = tet10(np.array([[0, 0, 0], [3, 0, 0], [0, 3, 0], [0, 0, 3]], float))
    stem = tet10(np.array([[0, 0, 0], [3, 0, 0], [0, 3, 0], [0, 0, -3]], float))
    nodes = np.concatenate([cortex, canc, stem]) + rng.normal(0, 1e-3, (30, 3))
    normal = np.tile([0.0, 0.0, 1.0], (6, 1))
    return {
        "cortex_conn": np.array([list(range(1, 11))], np.int64),
        "cancellous_conn": np.array([list(range(11, 21))], np.int64),
        "stem_conn": np.array([list(range(31, 41))], np.int64),
        "stem_conn_bond": np.array([list(range(31, 41))], np.int64),
        "cortex_elab": np.array([1], np.int64),
        "cancellous_elab": np.array([2], np.int64),
        "stem_elab": np.array([3], np.int64),
        "node_labels": np.array(NODE_LABELS, np.int64),
        "nodes": nodes,
        "pair_bone": np.array(BONE_PAIR, np.int64),
        "pair_stem": np.array(STEM_PAIR, np.int64),
        "pair_normal": normal,
        "pair_area": np.array([0.5, 0.5, 0.5, 1.0, 1.0, 1.0]),
        "pair_interf": np.full(6, 0.05),
        "pair_cortex": np.zeros(6, bool),
        "pair_collar": np.array([False, False, False, False, False, True]),
    }


def csv_bytes(header: str, rows: list[list]) -> bytes:
    lines = [header] + [",".join(str(x) if isinstance(x, (int, str)) else repr(float(x)) for x in r) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


def fric_files(steps: list[str], seed: int, odd_value: bool = False, stray_row: bool = False) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    for i, s in enumerate(steps):
        u = [[n] + [f32(v) for v in rng.normal(0, 0.1, 3)] for n in NODE_LABELS]
        if odd_value and i == 0:
            u[0][1] = 0.1 + 1e-12  # 不是 float32 能原样存的数
        out[f"m_fric_csv/{s}_U.csv"] = csv_bytes("node,u1,u2,u3", u)
        out[f"m_fric_csv/{s}_RF.csv"] = csv_bytes("node,rf1,rf2,rf3", [[n] + [f32(v) for v in rng.normal(0, 5, 3)] for n in (1, 2, 3)])
        contact = [["COPEN", n, f32(rng.normal(0, 1e-3))] for n in BONE_PAIR]
        for field in ("CPRESS", "CSTATUS"):
            contact += [[field, n, f32(abs(rng.normal(1, 0.5)))] for n in BONE_PAIR + STEM_PAIR]
        if stray_row and i == 1:
            contact.append(["CPRESS", 1, f32(9.5)])  # 一个不在界面上的节点
        out[f"m_fric_csv/{s}_CONTACT.csv"] = csv_bytes("field,node,value", contact)
        force = []
        for field in ("CNAREA", "CNORMF", "CSHEARF"):
            force += [[field, n] + [f32(v) for v in rng.normal(0, 2, 3)] for n in BONE_PAIR + STEM_PAIR]
        out[f"m_fric_csv/{s}_CFORCE.csv"] = csv_bytes("field,node,f1,f2,f3", force)
    for s in (steps[0], steps[-1]):  # 真归档里应力应变只有两步
        out[f"m_fric_csv/{s}_S.csv"] = csv_bytes("elem,mises,s11,s22,s12", [[e] + [f32(v) for v in rng.normal(10, 3, 4)] for e in (1, 2, 3)])
        out[f"m_fric_csv/{s}_E.csv"] = csv_bytes("elem,e_max,e_mid,e_min", [[e] + [f32(v) for v in rng.normal(0, 1e-3, 3)] for e in (1, 2, 3)])
    return out


def bond_files(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    return {
        "m_bond_csv/LOAD_S.csv": csv_bytes("elem,mises,s11,s22,s12", [[e] + [f32(v) for v in rng.normal(10, 3, 4)] for e in (1, 2, 3)]),
        "m_bond_csv/LOAD_ENER.csv": csv_bytes("elem,else,evol", [[e] + [f32(abs(v)) for v in rng.normal(1, 0.2, 2)] for e in (1, 2, 3)]),
    }


DESIGN = {"L": 30.5, "rho_tip": 0.25, "q": 1.5, "lam": 1.2, "g_ml": 0.5, "g_ap": 0.45, "n_a": 3.0, "n_p": 4.0,
          "tau_a": -0.1, "tau_p": 0.2, "alpha": 33.25, "m": 1.0, "cap_h": 1.5}


def job_files(kind: str = "fric", steps: list[str] | None = None, seed: int = 1, **opts) -> dict:
    """一个作业文件夹里的全部文件：{相对路径: 字节}。kind：fric、bond、failed。"""
    steps = steps or STEPS4
    spec = {"kind": "design", "design": dict(DESIGN), "h_int": 2.0, "min_A0": 150.0, "stage": "syn", "tag": f"t{seed}",
            "model": "m1", "h_cut": 16.0, "delta": 0.1, "femur_id": "sawbone3406", "neck_axis": "isthmus",
            "fric_only": kind == "fric", "created": "2026-11-01 10:00:00"}
    if kind == "bond":
        spec.update(bond_only=True, intact_job="syn_intact_0000")
        spec.pop("fric_only")
    files = {"spec.json": json.dumps(spec).encode()}
    if kind == "failed":
        files["FAILED.json"] = json.dumps({"level": "L3", "stage": "prep", "reason": "meshing failed", "time": "x"}).encode()
        files["prep.log"] = b"FAILED\n"
        return files
    buf = io.BytesIO()
    np.savez(buf, **mesh_arrays())
    files["mesh3d.npz"] = buf.getvalue()
    model = "m_fric" if kind == "fric" else "m_bond"
    solve_steps = ["PRESSFIT"] + steps if kind == "fric" else ["LOAD"]
    prep = {"n_tet": {"cortex": 1, "cancellous": 1, "stem": 1}, "n_nodes": 30, "n_pairs": 6, "n_pairs_cortex": 0,
            "interface_area_mm2": 4.5, "h_int": 2.0, "h_far": 6.0, "delta": 0.1, "mu": 0.3, "torque": True, "E_canc": 155.0,
            "slip_tol": 0.00025, "interference": "clearance", "cycles": 2, "steps": ["PRESSFIT"] + steps,
            "load_N": [-700.5, 600.25, -2100.125], "stem_volume_mm3": 4.5, "code_hash": "abcdef0123",
            "mesh_quality": {"min_vol": {"cortex": 0.5, "cancellous": 0.25, "stem": 0.75}},
            "mesh_attempt": {"algorithm3d": 1, "h_int": 2.0, "section_points": 40, "previous_errors": []},
            "templating": {"alpha": 33.25, "e": 0.0, "A0": 500.5, "contact": 0.01, "s_bind": 12.5, "volume": 9000.0, "margin": 1.0},
            "bone_loss": {"resected_mm3": 0.0, "reamed_mm3": 9000.0, "total_mm3": 9000.0}}
    files["prep.json"] = json.dumps(prep).encode()
    files["prep.log"] = b"READY\n"
    files["solve.json"] = json.dumps({model: {"job": model, "status": "OK", "wall_s": 12.5, "tries": 1, "odb_meta": {
        "odb": f"C:\\q\\{model}.odb", "steps": [{"name": s, "n_frames": 3} for s in solve_steps]}}}).encode()
    if kind == "fric":
        files.update(fric_files(steps, seed, **opts))
        result = {"f1_p95_um": 3.5, "n_pairs": 5, "interface_area": 3.5, "frac_open": 0.05, "some_new_number": 1.25,
                  "model": "m1", "fric_only": True, "intact_job": None, "spec": spec, "templating": prep["templating"]}
    else:
        files.update(bond_files(seed))
        result = {"vm_p99": 120.5, "vm_max": 300.25, "n_stem_elems_in_bone": 1, "sed_gruen7": 0.01, "f2_g7_loss_pct": 12.5,
                  "bond_only": True, "intact_job": "syn_intact_0000", "intact_substituted_h": None, "spec": spec}
    files["result.json"] = json.dumps(result).encode()
    files.update({"CLAIMED": b"2026-11-01 10:01:00", "SOLVED": b"", "DONE": b"2026-11-01 10:30:00"})
    return files


MTIME = {"spec.json": T0, "prep.json": T0 + 60, "CLAIMED": T0 + 60, "SOLVED": T0 + 1700, "DONE": T0 + 1800, "FAILED.json": T0 + 90}


def write_archive(folder: Path, job: str, files: dict, manifest: bool = True) -> Path:
    """把 files 打成 <作业号>.tar.xz，并写清单。返回归档文件的位置。"""
    folder.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        dirs = {job} | {f"{job}/{rel.split('/')[0]}" for rel in files if "/" in rel}
        for d in sorted(dirs):
            info = tarfile.TarInfo(d)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, T0
            tf.addfile(info)
        for rel, data in files.items():
            info = tarfile.TarInfo(f"{job}/{rel}")
            info.size, info.mtime = len(data), MTIME.get(rel, T0 + 1750)
            tf.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()
    path = folder / f"{job}.tar.xz"
    path.write_bytes(blob)
    if manifest:
        sha = hashlib.sha256(blob).hexdigest()
        doc = {"job": job, "state": "FAILED" if "FAILED.json" in files else "DONE", "archive_bytes": len(blob),
               "stream_sha256": {"linux": sha, "windows": sha},
               "files_archive": {f"{job}/{rel}": {"size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for rel, d in files.items()},
               "tool": "假归档"}
        (folder / f"{job}.manifest.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path
