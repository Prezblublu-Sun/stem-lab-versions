"""把一个作业的归档读出来，做成标签、界面场、整体场。

只读归档（<作业号>.tar.xz 和 <作业号>.manifest.json）。不调旧管线的任何代码，不重算 FE。
归档里有什么就导出什么；缺的量不补，记在每个作业的清单里。

这个文件只有纯函数，不碰实验记录。后台进程 worker.py 叫它。
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import json
import lzma
import re
import tarfile
import zlib
from pathlib import Path

import numpy as np

import fae_columns as C

VERSION = C.VERSION
QUANTITIES = C.QUANTITIES
LONG_FILES = ("CONTACT", "CFORCE")  # 第一列是 field 的长表，归界面场
MARKERS = ("DONE", "FAILED.json", "SOLVED", "CLAIMED", "READY")


class ArchiveError(Exception):
    """这个作业的归档读不了。消息是给人看的。"""


class Stopped(Exception):
    """被叫停了。"""


# ---------------------------------------------------------------- 小工具

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def jdump(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=float)


def utc(ts) -> str | None:
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def num(v):
    """json 里读出来的数原样留着：整数还是整数，小数还是小数。"""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v)
    return v


def fmt_cell(v, typ: str) -> str:
    """一个值写进 csv 时的样子。和旧表的写法相同，两张表才能逐格比。"""
    if v is None:
        return ""
    if typ == "float":
        f = float(v)
        if f != f:
            return "nan"
        if f in (float("inf"), float("-inf")):
            return "inf" if f > 0 else "-inf"
        return repr(f)
    if typ == "int":
        return str(int(v))
    if typ == "bool":
        return "true" if v else "false"
    if typ == "json":
        if isinstance(v, list) and not v:
            return "[]"
        return jdump(v)
    return str(v)


def compact(a: np.ndarray) -> np.ndarray:
    """float64 的数组，如果每个值存成 float32 再读回来一模一样，就存 float32；否则不动。不丢任何一位。"""
    if a.dtype != np.float64 or a.size == 0:
        return a
    small = a.astype(np.float32)
    back = small.astype(np.float64)
    same = (back == a) | (np.isnan(back) & np.isnan(a))
    return small if bool(same.all()) else a


# ---------------------------------------------------------------- 读归档

class Archive:
    """一个作业的归档，整个读进内存。"""

    def __init__(self, folder: Path, job: str):
        self.folder = Path(folder)
        self.job = job
        self.tar_path = self.folder / f"{job}.tar.xz"
        self.manifest_path = self.folder / f"{job}.manifest.json"
        self.files: dict[str, bytes] = {}
        self.mtimes: dict[str, float] = {}
        self.dirs: set[str] = set()
        self.manifest: dict | None = None
        self.sha256 = ""
        self.size = 0
        self.notes: list[str] = []  # 不拦导出、但要记下来的事

    def load(self) -> "Archive":
        if not self.tar_path.is_file():
            raise ArchiveError(f"归档文件不存在：{self.tar_path}")
        try:
            blob = self.tar_path.read_bytes()
        except OSError as err:
            raise ArchiveError(f"归档文件读不了：{err}") from err
        self.sha256, self.size = sha256_bytes(blob), len(blob)

        if self.manifest_path.is_file():
            try:
                self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                raise ArchiveError(f"清单文件读不出来：{type(err).__name__}: {err}") from err
            want = self.manifest.get("stream_sha256")
            want = set(want.values()) if isinstance(want, dict) else {want} if want else set()
            if want and self.sha256 not in want:
                raise ArchiveError(
                    f"归档文件的哈希和清单对不上：文件是 {self.sha256[:16]}…（{self.size} 字节），"
                    f"清单记的是 {sorted(want)[0][:16]}…（{self.manifest.get('archive_bytes')} 字节）"
                )
            if not want:
                self.notes.append("清单里没有归档文件的哈希，整个文件没法核对")
        else:
            self.notes.append("没有清单文件，归档没法核对")

        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as tf:
                for m in tf:
                    head, _, rel = m.name.partition("/")
                    if head != self.job:
                        raise ArchiveError(f"归档里的文件夹叫 {head}，不是作业号 {self.job}")
                    if m.isdir():
                        self.dirs.add(rel)
                    elif m.isfile():
                        self.files[rel] = tf.extractfile(m).read()
                        self.mtimes[rel] = m.mtime
                    else:
                        self.notes.append(f"归档里有一项既不是文件也不是文件夹，没有读：{rel}")
        except (tarfile.TarError, lzma.LZMAError, EOFError, zlib.error, OSError) as err:
            raise ArchiveError(f"归档解不开：{type(err).__name__}: {err}") from err

        listed = (self.manifest or {}).get("files_archive")
        if isinstance(listed, dict):
            seen = set()
            for name, info in listed.items():
                rel = name.partition("/")[2]
                seen.add(rel)
                if rel not in self.files:
                    self.notes.append(f"清单里有、归档里没有：{rel}")
                elif info.get("sha256") and sha256_bytes(self.files[rel]) != info["sha256"]:
                    raise ArchiveError(f"归档里的 {rel} 和清单记的哈希对不上")
            for rel in sorted(set(self.files) - seen):
                self.notes.append(f"归档里有、清单里没有：{rel}")
        return self

    def has(self, rel: str) -> bool:
        return rel in self.files

    def has_dir(self, name: str) -> bool:
        return name in self.dirs or any(f.startswith(name + "/") for f in self.files)

    def mtime(self, rel: str):
        return self.mtimes.get(rel)

    def json(self, rel: str, notes: list | None = None):
        """读一个 json 文件。没有返回 None；读不出来记一条，也返回 None。"""
        if rel not in self.files:
            return None
        try:
            return json.loads(self.files[rel].decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as err:
            (self.notes if notes is None else notes).append(f"{rel} 读不出来：{type(err).__name__}: {err}")
            return None

    def state(self) -> str:
        for marker in MARKERS:
            if marker in self.files:
                return marker.replace(".json", "")
        return "NEW" if "spec.json" in self.files else "MISSING"

    def model_dirs(self) -> list[str]:
        """放场数据 csv 的文件夹：m_fric_csv、m_bond_csv、intact_csv。"""
        found = {f.split("/")[0] for f in self.files if "/" in f and f.split("/")[0].endswith("_csv")}
        return sorted(found)

    def mesh(self) -> dict | None:
        if "mesh3d.npz" not in self.files:
            return None
        z = np.load(io.BytesIO(self.files["mesh3d.npz"]), allow_pickle=False)
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- 读 csv

def parse_wide(data: bytes) -> tuple[list[str], np.ndarray, np.ndarray]:
    """第一列是 node 或 elem 的表。返回（列名，编号 int64，数值 float64 [N, k]）。"""
    text = data.decode("utf-8")
    head, _, body = text.partition("\n")
    cols = [c.strip() for c in head.split(",")]
    k = len(cols) - 1
    if not body.strip():
        return cols, np.zeros(0, np.int64), np.zeros((0, k), np.float64)
    arr = np.loadtxt(io.StringIO(body), delimiter=",", dtype=np.float64, ndmin=2)
    if arr.shape[1] != k + 1:
        raise ValueError(f"表头有 {k + 1} 列，数据有 {arr.shape[1]} 列")
    labels = arr[:, 0].astype(np.int64)
    if not (labels == arr[:, 0]).all():
        raise ValueError("编号那一列不全是整数")
    return cols, labels, np.ascontiguousarray(arr[:, 1:])


def parse_long(data: bytes) -> tuple[list[str], dict]:
    """第一列是 field 的长表。返回（列名，{field: (编号 int64, 数值 float64 [N, k])}），行的先后不变。"""
    lines = data.decode("utf-8").splitlines()
    cols = [c.strip() for c in lines[0].split(",")] if lines else []
    groups: dict[str, list[str]] = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        field, _, rest = ln.partition(",")
        groups.setdefault(field, []).append(rest)
    out = {}
    for field, rest in groups.items():
        arr = np.loadtxt(io.StringIO("\n".join(rest)), delimiter=",", dtype=np.float64, ndmin=2)
        labels = arr[:, 0].astype(np.int64)
        if not (labels == arr[:, 0]).all():
            raise ValueError(f"{field}：编号那一列不全是整数")
        out[field] = (labels, np.ascontiguousarray(arr[:, 1:]))
    return cols, out


def csv_head(data: bytes) -> list[str]:
    return [c.strip() for c in data[:400].decode("utf-8", "replace").partition("\n")[0].split(",")]


def split_name(fname: str) -> tuple[str, str]:
    """LOAD2_CONTACT.csv → ("LOAD2", "CONTACT")。"""
    stem = fname[:-4] if fname.endswith(".csv") else fname
    step, _, q = stem.rpartition("_")
    return step, q


def step_order(a: Archive, model_dir: str) -> list[str]:
    """这个模型有 csv 的分析步，按求解时的先后排。"""
    present = {split_name(f.split("/", 1)[1])[0] for f in a.files if f.startswith(model_dir + "/") and f.endswith(".csv")}
    known: list[str] = []
    solve = a.json("solve.json", notes=[]) or {}
    ent = solve.get(model_dir[:-4])
    if isinstance(ent, dict):
        known = [s.get("name") for s in (ent.get("odb_meta") or {}).get("steps") or [] if isinstance(s, dict)]
    if not known:
        prep = a.json("prep.json", notes=[]) or {}
        known = list(prep.get("steps") or []) if isinstance(prep.get("steps"), list) else []
    ordered = [s for s in known if s in present]

    def natural(s: str):
        return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]

    return ordered + sorted(present - set(ordered), key=natural)


# ---------------------------------------------------------------- 标签

def label_row(a: Archive) -> dict:
    """一个作业的一行标签。只用归档里的 json、标记文件和它们的修改时间。"""
    row = {c: None for c in C.NAMES}
    notes: list[str] = list(a.notes)
    row.update(row_id=a.job, job_id=a.job, archive_sha256=a.sha256, archive_bytes=a.size, export_notes=notes,
               has_prep=False, has_fric_model=False, has_bond_model=False)
    status = a.state()
    row["status"] = status
    for col, f in (("t_spec_utc", "spec.json"), ("t_prep_utc", "prep.json"), ("t_solved_utc", "SOLVED"),
                   ("t_done_utc", "DONE"), ("t_failed_utc", "FAILED.json")):
        row[col] = utc(a.mtime(f))
    row["t_ready_utc"] = utc(a.mtime("READY") or a.mtime("CLAIMED"))

    spec = a.json("spec.json", notes)
    if spec is None:
        notes.append("没有能读的 spec.json，这一行只有状态和时间")
        return row
    kind = spec.get("kind")
    row.update(
        stage=spec.get("stage"), tag=spec.get("tag"), kind=kind, created_local=spec.get("created"),
        spec_hash=hashlib.sha1(json.dumps(
            {k: spec[k] for k in sorted(spec) if k not in ("stage", "tag", "created")},
            sort_keys=True, default=float).encode()).hexdigest(),
        bond_only=bool(spec.get("bond_only")), fric_only=bool(spec.get("fric_only")), cfg_override=spec.get("cfg"),
        h_int_mm=num(spec.get("h_int")), delta_spec_mm=num(spec.get("delta")),
        entry_offset_forced_mm=num(spec.get("entry_offset")), collar_rule=spec.get("collar_rule"),
        margin_check=spec.get("margin_check"), a_bounds_max=num(spec.get("a_bounds_max")),
        torsion=spec.get("torsion"), pose=spec.get("pose_fixed"), foam_refine=spec.get("foam_refine"),
        ref_cut_mm=num(spec.get("ref_cut_mm")), min_A0_mm2=num(spec.get("min_A0")), source_job=spec.get("source_job"),
        intact_job_spec=spec.get("intact_job"), femur_id=spec.get("femur_id") or "", neck_axis=spec.get("neck_axis"),
    )
    fr = spec.get("foam_refine")
    row["fidelity"] = f"h{float(spec.get('h_int', float('nan'))):g}" + (
        f"+f5h{float(fr['h']):g}" if isinstance(fr, dict) and fr.get("h") is not None else "")

    # ---- 设计
    if kind in ("design", "variant") and isinstance(spec.get("design"), dict):
        design = dict(spec["design"])
        if "m" not in design:
            if "margin" in spec:
                design["m"] = spec["margin"]
            else:
                notes.append("spec.json 的设计里没有 m，也没有 margin：m 留空（旧管线这时用一个常数）")
        if spec.get("h_cut") is not None:
            design["h_cut"] = spec["h_cut"]
        else:
            design.pop("h_cut", None)
            notes.append("spec.json 里没有 h_cut：h_cut 留空（旧管线这时用 25）")
        for k in C.DESIGN_VARS:
            if design.get(k) is not None:
                row[k] = float(design[k])
            elif k not in ("m", "h_cut"):
                notes.append(f"spec.json 的设计里没有 {k}")
        if all(row[k] is not None for k in C.DESIGN_VARS):
            def r6(v):
                x = round(float(v), 6)
                return f"{(0.0 if x == 0 else x):.6f}"
            row["design_key"] = sha1_text(",".join(r6(row[k]) for k in C.DESIGN_VARS))
        row["cap_h_mm"] = num(spec["design"].get("cap_h"))
        row["collar_w_mm"] = float(spec["design"].get("collar_w", 0.0))

    # ---- 失败记录
    failed = a.json("FAILED.json", notes)
    if a.has("FAILED.json"):
        failed = failed or {}
        row.update(fail_level=failed.get("level"), fail_stage=failed.get("stage"),
                   fail_reason=str(failed.get("reason", ""))[:500], fail_code=failed.get("code"))

    # ---- 建模记录
    prep = a.json("prep.json", notes)
    if prep is not None:
        row["has_prep"] = True
        row["code_hash"] = prep.get("code_hash")
        row["h_int_prep_mm"] = num(prep.get("h_int", prep.get("h_roi")))
        row["steps"] = list(prep["steps"]) if isinstance(prep.get("steps"), list) else None
        row.update(delta_mm=num(prep.get("delta")), mu=num(prep.get("mu")), E_canc_MPa=num(prep.get("E_canc")),
                   h_far_mm=num(prep.get("h_far")), slip_tol=num(prep.get("slip_tol")), cycles=num(prep.get("cycles")),
                   interference=prep.get("interference"), torque=prep.get("torque"), load_vec_N=prep.get("load_N"))
        nt = prep.get("n_tet") or {}
        row.update(n_tet_cortex=nt.get("cortex"), n_tet_cancellous=nt.get("cancellous"), n_tet_stem=nt.get("stem"),
                   n_tet_total=(sum(int(v) for v in nt.values()) if nt else None), n_nodes=prep.get("n_nodes"),
                   n_pairs=prep.get("n_pairs"), n_pairs_cortex=prep.get("n_pairs_cortex"),
                   interface_area_mm2=num(prep.get("interface_area_mm2")), stem_volume_mm3=num(prep.get("stem_volume_mm3")))
        ma = prep.get("mesh_attempt") or {}
        row.update(mesh_algo=ma.get("algorithm3d"), mesh_h_used_mm=num(ma.get("h_int")),
                   mesh_section_points=ma.get("section_points"),
                   mesh_retries=(len(ma.get("previous_errors") or []) if ma else None))
        mv = ((prep.get("mesh_quality") or {}).get("min_vol") or {}).values()
        row["mesh_min_vol_mm3"] = float(min(mv)) if mv else None
        tp = prep.get("templating") or {}
        for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin"):
            row["tpl_" + k] = num(tp.get(k))
        bl = prep.get("bone_loss") or {}
        row.update(bone_resected_mm3=num(bl.get("resected_mm3")), bone_reamed_mm3=num(bl.get("reamed_mm3")),
                   bone_total_mm3=num(bl.get("total_mm3")))
        h_prep = prep.get("h_int", prep.get("h_roi"))
        row["cons_h_int"] = (h_prep is not None and spec.get("h_int") is not None
                             and abs(float(h_prep) - float(spec["h_int"])) < 1e-12)
        if spec.get("delta") is not None:
            row["cons_delta"] = prep.get("delta") is not None and abs(float(prep["delta"]) - float(spec["delta"])) < 1e-12
        elif kind in ("design", "variant"):
            row["cons_delta"] = prep.get("delta") is not None
        elif kind == "intact":
            row["cons_delta"] = True
        if row["load_vec_N"] is not None:
            row["load_vec_norm_N"] = float(np.linalg.norm(np.asarray(row["load_vec_N"], float)))

    # ---- 求解记录
    if a.has("solve.json"):
        solve = a.json("solve.json", notes) or {}
        for model, col in (("m_fric", "fric"), ("m_bond", "bond")):
            if isinstance(solve.get(model), dict):
                row[f"solve_wall_s_{col}"] = num(solve[model].get("wall_s"))
                row[f"solve_tries_{col}"] = num(solve[model].get("tries"))
        solvers, steps_by_model = set(), {}
        for model, ent in sorted(solve.items()):
            if not isinstance(ent, dict):
                continue
            meta = ent.get("odb_meta") or {}
            if ent.get("solver"):
                solvers.add(str(ent["solver"]).lower())
            elif str(meta.get("odb", "")).lower().endswith(".odb"):
                solvers.add("abaqus")
            if meta.get("steps"):
                steps_by_model[model] = [s.get("name") for s in meta["steps"]]
        if len(solvers) == 1:
            row["solver"] = solvers.pop()
        elif len(solvers) > 1:
            notes.append(f"solve.json 里有不止一种求解器：{sorted(solvers)}")
        if row["steps"] is None and steps_by_model:
            row["steps"] = steps_by_model[sorted(steps_by_model)[0]]
    if status == "DONE" and row["solver"] is None:
        notes.append("solve.json 里认不出求解器（旧表这一格是另外从别的记录补的）")

    # ---- 结果
    if status == "DONE":
        res = a.json("result.json", notes)
        if res is None:
            notes.append("作业是完成的，但没有能读的 result.json")
            return row
        if "spec" in res:
            row["spec_in_result_match"] = jdump(res.get("spec")) == jdump(spec)
        elif kind != "intact":
            row["spec_in_result_match"] = False
            notes.append("result.json 里没有抄 spec")
        if kind == "intact":
            for k in ("gruen7", "gruen1", "gruen7_vol_mm3", "gruen1_vol_mm3"):
                row[C.RESULT_MAP[k]] = num(res.get(k))
        elif kind in ("design", "variant"):
            has_f, has_b = a.has_dir("m_fric_csv"), a.has_dir("m_bond_csv")
            row["has_fric_model"], row["has_bond_model"] = has_f, has_b
            if has_f == bool(spec.get("bond_only")):
                notes.append(f"有没有 m_fric_csv（{has_f}）和 spec.json 的 bond_only（{bool(spec.get('bond_only'))}）对不上")
            if has_b == bool(spec.get("fric_only")):
                notes.append(f"有没有 m_bond_csv（{has_b}）和 spec.json 的 fric_only（{bool(spec.get('fric_only'))}）对不上")
            extra = {}
            for k, v in res.items():
                if k in C.RESULT_SKIP:
                    continue
                col = C.RESULT_MAP.get(k, k)
                if col in C.RESULT_COLS:
                    row[col] = num(v)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    extra[k] = v
            row["extra_result_keys"] = extra or None
            if has_b:
                row["intact_job"] = res.get("intact_job")
                row["intact_substituted_h"] = num(res.get("intact_substituted_h"))
    return row


def row_from_iface(row: dict, iface: dict) -> None:
    """由界面场算的那几列。"""
    area, tri, X = iface["area"], iface["tri"], iface["X"]
    row["field_n_nodes"], row["field_n_tri"] = int(len(area)), int(len(tri))
    if len(tri):
        p = X[tri]
        tri_sum = float(0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1).sum())
    else:
        tri_sum = 0.0
    row["tri_area_ratio"] = tri_sum / float(area.sum())
    load = row.get("load_vec_N")
    steps = [str(s) for s in iface["steps"]]
    if load is not None:
        lv = np.asarray(load, float)
        for name, col in (("LOAD", "load"), ("LOAD2", "load2")):
            if name not in steps:
                continue
            # 接触力先存成 float32 再求和：和界面场文件里存的是同一份数
            f = iface["cforce"][:, steps.index(name)].astype(np.float32).astype(np.float64)
            if np.isfinite(f).all():
                total = f.sum(0)
                if col == "load":
                    row["iface_force_load_N"] = total.tolist()
                row[f"iface_force_err_{col}"] = float(np.linalg.norm(total - lv) / np.linalg.norm(lv))


# ---------------------------------------------------------------- 界面场

_TET_FACES = ((0, 1, 2, 4, 5, 6), (0, 1, 3, 4, 8, 7), (1, 2, 3, 5, 9, 8), (0, 2, 3, 6, 9, 7))  # 十节点四面体的四个面：三个角点加三个边中点


def interface_triangles(bone_conn: np.ndarray, pair_bone: np.ndarray) -> np.ndarray:
    """骨侧界面的三角形（用节点对的序号）。

    取骨单元的面里六个节点都是界面节点、并且只属于一个骨单元的那些，每个面按边中点分成四个小三角形。
    """
    if len(pair_bone) == 0 or len(bone_conn) == 0:
        return np.zeros((0, 3), np.int32)
    top = int(max(int(bone_conn.max()), int(pair_bone.max())))
    local = np.full(top + 1, -1, np.int64)
    local[pair_bone] = np.arange(len(pair_bone))
    faces = np.concatenate([bone_conn[:, list(f)] for f in _TET_FACES])
    corners = np.sort(faces[:, :3], axis=1)
    _, inverse, counts = np.unique(corners, axis=0, return_inverse=True, return_counts=True)
    outer = counts[inverse.ravel()] == 1
    on_iface = (local[faces] >= 0).all(axis=1)
    f = local[faces[outer & on_iface]]
    a, b, c, ab, bc, ca = (f[:, i] for i in range(6))
    tri = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
    return tri.astype(np.int32)


IFACE_DOC = {
    "文件": "界面场/<作业号>.npz（np.savez_compressed，不含 pickle）",
    "范围": "摩擦模型（m_fric_csv）的骨-柄界面。n = 节点对数，S = 分析步数，步的名字和先后在 steps 里",
    "每个节点对": {
        "node_bone": "[n] 骨侧节点的 Abaqus 编号", "node_stem": "[n] 柄侧对应节点的编号",
        "X": "[n,3] mm 骨侧节点的坐标，模型坐标系", "nrm": "[n,3] 柄表面的外法向",
        "area": "[n] mm2 节点分到的面积", "interf": "[n] mm 施加的过盈量",
        "cortex": "[n] 是不是贴着皮质", "collar": "[n] 是不是在领上",
        "rel": "[n,S,3] mm 柄侧位移减骨侧位移",
        "gap": "[n,S] um = -(interf + rel·nrm) * 1000",
        "c_<量>": "[n,S] 骨侧节点的接触量，量 = CONTACT.csv 里的每个 field（CPRESS、CSTATUS、COPEN、CSHEAR1、CSHEAR2、CSLIP1、CSLIP2）",
        "c_<量>_stem": "[n,S] 柄侧节点的同一个量（归档里柄侧有这个量时才有）",
        "f_<量>": "[n,S,3] 骨侧节点的 CFORCE.csv 里的每个 field（CNAREA、CNORMF、CSHEARF）",
        "f_<量>_stem": "[n,S,3] 柄侧节点的同一个量",
        "cforce": "[n,S,3] N 骨侧节点的 CNORMF + CSHEARF",
    },
    "三角形": "tri [T,3]：节点对的序号。取法见 interface_triangles",
    "其他": {
        "steps": "[S] 分析步的名字", "load_vec": "[3] N prep.json 的 load_N（没有时是 nan）",
        "extra__<步>__<文件>__<量>__label / __value": "csv 里没有落到任何节点对上的行，或同一个节点重复出现的行，原样放在这里",
        "info": "一段 json：每个 csv 文件的哈希、行数，各量落到节点对上的行数",
    },
    "缺的": "某一步没有 CONTACT.csv 或 CFORCE.csv 时，那一步的值是 nan，info 里写明缺哪个文件",
    "没有的": "柄坐标系下的位置、到髓腔壁和外表面的距离（旧库界面场里的 loc、srt、nloc、d_canal、d_outer、frame）。"
            "这些要股骨几何，归档里没有",
    "数值类型": "csv 里读出来的数，存成 float32 再读回来和原数一模一样时存 float32，否则存 float64。rel、gap、cforce 是算出来的，存 float64",
}


def build_iface(a: Archive, mesh: dict | None, model_dir: str = "m_fric_csv") -> tuple[dict, dict] | None:
    """一个作业的界面场。归档里没有摩擦模型的 csv 就返回 None。"""
    if not a.has_dir(model_dir):
        return None
    if mesh is None:
        raise ValueError("有摩擦模型的 csv，但归档里没有 mesh3d.npz")
    need = ("pair_bone", "pair_stem", "pair_normal", "pair_area", "pair_interf", "pair_cortex", "nodes", "node_labels")
    lack = [k for k in need if k not in mesh]
    if lack:
        raise ValueError(f"mesh3d.npz 里没有 {lack}")
    pb, ps = mesh["pair_bone"].astype(np.int64), mesh["pair_stem"].astype(np.int64)
    n_pair = len(pb)
    if len(np.unique(pb)) != n_pair:
        raise ValueError("pair_bone 里有重复的节点编号")
    top = int(mesh["node_labels"].max())
    lut = np.full(top + 1, -1, np.int64)
    lut[mesh["node_labels"]] = np.arange(len(mesh["node_labels"]))
    if (lut[pb] < 0).any() or (lut[ps] < 0).any():
        raise ValueError("有节点对的编号不在 mesh3d.npz 的 node_labels 里")
    steps = [s for s in step_order(a, model_dir) if a.has(f"{model_dir}/{s}_U.csv")]
    if not steps:
        raise ValueError(f"{model_dir} 里没有任何一步的位移（_U.csv）")
    S = len(steps)
    nrm = np.asarray(mesh["pair_normal"], np.float64)
    interf = np.asarray(mesh["pair_interf"], np.float64)
    info: dict = {"files": {}, "missing": [], "unmatched_rows": 0}
    arrays: dict = {
        "node_bone": pb, "node_stem": ps, "X": mesh["nodes"][lut[pb]].astype(np.float64), "nrm": nrm,
        "area": np.asarray(mesh["pair_area"], np.float64), "interf": interf,
        "cortex": np.asarray(mesh["pair_cortex"], bool),
        "collar": np.asarray(mesh["pair_collar"], bool) if "pair_collar" in mesh else np.zeros(n_pair, bool),
    }
    if "pair_collar" not in mesh:
        info["missing"].append("mesh3d.npz 里没有 pair_collar，collar 全记成否")

    rel = np.full((n_pair, S, 3), np.nan)
    for i, s in enumerate(steps):
        data = a.files[f"{model_dir}/{s}_U.csv"]
        _, lab, val = parse_wide(data)
        tab = np.full((top + 1, 3), np.nan)
        ok = lab <= top
        tab[lab[ok]] = val[ok]
        rel[:, i] = tab[ps] - tab[pb]
    if not np.isfinite(rel).all():
        raise ValueError("有节点对在某一步没有位移")
    arrays["rel"] = rel
    arrays["gap"] = np.stack([-(interf + (rel[:, i] * nrm).sum(1)) * 1e3 for i in range(S)], 1)

    in_pair = np.zeros(top + 1, bool)
    in_pair[pb] = True
    in_pair[ps] = True
    cforce = np.full((n_pair, S, 3), np.nan)
    for i, s in enumerate(steps):
        for q, prefix in (("CONTACT", "c_"), ("CFORCE", "f_")):
            rel_name = f"{model_dir}/{s}_{q}.csv"
            if not a.has(rel_name):
                info["missing"].append(f"{s}_{q}.csv")
                continue
            data = a.files[rel_name]
            cols, groups = parse_long(data)
            finfo = {"sha256": sha256_bytes(data), "bytes": len(data), "columns": cols, "fields": {}}
            total = np.zeros((top + 1, 3))
            for field, (lab, val) in groups.items():
                k = val.shape[1]
                _, first = np.unique(lab, return_index=True)
                is_first = np.zeros(len(lab), bool)
                is_first[first] = True
                ok = lab <= top
                tab = np.full((top + 1, k), np.nan)
                use = is_first & ok
                tab[lab[use]] = val[use]
                matched = use & in_pair[np.where(ok, lab, 0)]
                left = ~matched
                for side, idx in (("", pb), ("_stem", ps)):
                    vals = tab[idx]
                    if side and not np.isfinite(vals).any():
                        continue
                    key = f"{prefix}{field}{side}"
                    shape = (n_pair, S) if k == 1 else (n_pair, S, k)
                    if key not in arrays:
                        arrays[key] = np.full(shape, np.nan)
                    arrays[key][:, i] = vals[:, 0] if k == 1 else vals
                if left.any():
                    arrays[f"extra__{s}__{q}__{field}__label"] = lab[left]
                    arrays[f"extra__{s}__{q}__{field}__value"] = compact(val[left])
                    info["unmatched_rows"] += int(left.sum())
                finfo["fields"][field] = {"rows": int(len(lab)), "on_pairs": int(matched.sum()), "left_over": int(left.sum())}
                if q == "CFORCE" and field in ("CNORMF", "CSHEARF") and k == 3:
                    np.add.at(total, lab[ok], val[ok])
            if q == "CFORCE":
                cforce[:, i] = total[pb]
            info["files"][f"{s}_{q}.csv"] = finfo
    arrays["cforce"] = cforce
    for key in list(arrays):
        if key.startswith(("c_", "f_")):
            arrays[key] = compact(arrays[key])

    bone = [mesh[k] for k in ("cortex_conn", "cancellous_conn") if k in mesh]
    arrays["tri"] = interface_triangles(np.concatenate(bone).astype(np.int64), pb) if bone else np.zeros((0, 3), np.int32)
    prep = a.json("prep.json", notes=[]) or {}
    load = prep.get("load_N")
    arrays["load_vec"] = np.asarray(load if load is not None else [np.nan] * 3, np.float64)
    arrays["steps"] = np.array(steps)
    arrays["job_id"] = np.array(a.job)
    info.update(n_pairs=n_pair, n_tri=int(len(arrays["tri"])), steps=steps, model=model_dir)
    arrays["info"] = np.array(json.dumps(info, ensure_ascii=False))
    arrays["doc"] = np.array(json.dumps(IFACE_DOC, ensure_ascii=False))
    arrays["version"] = np.array(f"fea-archive-export {VERSION}")
    return arrays, info


# ---------------------------------------------------------------- 整体场

GLOBAL_DOC = {
    "文件": "整体场/<作业号>.npz（np.savez_compressed，不含 pickle）",
    "网格": "mesh_<名字>：归档里 mesh3d.npz 的每个数组，原样。nodes 是节点坐标，node_labels 是节点编号，"
          "<部件>_conn 是十节点四面体的节点编号，<部件>_elab 是单元编号，pair_* 是界面节点对",
    "场": "index 是一段 json，里面的 tables 列出每一张表：model（m_fric、m_bond、intact）、step、quantity、"
         "columns（各列的名字）、key（数值数组的名字，[行数, 列数]）、label_key（编号数组的名字）、label_kind（node 或 elem）",
    "量": {
        "U": "位移 u1 u2 u3，mm，全部节点",
        "RF": "反力 rf1 rf2 rf3，N，固定端的节点",
        "S": "应力，MPa，每个单元一行：mises（等效应力）、s11、s22、s12。归档里只有这 4 个数，没有完整的 6 个分量",
        "E": "应变，每个单元一行：e_max、e_mid、e_min 三个主值。归档里没有方向，也没有分量",
        "ENER": "每个单元的应变能 else 和体积 evol",
    },
    "读法": "fae_core.read_global(路径) 给出 {(model, step, quantity): (编号, 数值, 列名)}",
    "数值类型": "存成 float32 再读回来和 csv 里的数一模一样时存 float32，否则存 float64。不丢任何一位",
    "归档里本来就没有的": [
        "应力的完整 6 个分量（只有等效应力加 s11、s22、s12）",
        "应变的分量和方向（只有三个主值）",
        "摩擦模型里应力和应变只有部分分析步有（一般是 RELEASE 和最后一次加载），别的步没有",
        "粘接模型和完整股骨没有位移和反力，只有加载一步的应力和应变能",
        "每一步只有最后一帧，没有步内的过程",
        "PRESSFIT 步没有任何场",
    ],
}


def build_global(a: Archive, mesh: dict | None) -> tuple[dict, dict] | None:
    """一个作业的整体场。归档里既没有网格也没有场数据就返回 None。"""
    model_dirs = a.model_dirs()
    if mesh is None and not model_dirs:
        return None
    arrays: dict = {}
    index: dict = {"job_id": a.job, "tables": [], "mesh": {}, "checks": [], "not_exported": [], "missing_mesh": mesh is None}
    if mesh is not None:
        for k, v in mesh.items():
            arrays["mesh_" + k] = v
            index["mesh"][k] = {"shape": list(v.shape), "dtype": str(v.dtype)}
    label_sets: list[np.ndarray] = []

    def label_key(lab: np.ndarray) -> str:
        for i, old in enumerate(label_sets):
            if old.shape == lab.shape and np.array_equal(old, lab):
                return f"label_{i}"
        label_sets.append(lab)
        arrays[f"label_{len(label_sets) - 1}"] = lab
        return f"label_{len(label_sets) - 1}"

    for md in model_dirs:
        model = md[:-4]
        order = {s: i for i, s in enumerate(step_order(a, md))}
        names = sorted((f.split("/", 1)[1] for f in a.files if f.startswith(md + "/")),
                       key=lambda n: (order.get(split_name(n)[0], 10 ** 6), n))
        for fname in names:
            data = a.files[f"{md}/{fname}"]
            if not fname.endswith(".csv"):
                index["not_exported"].append(f"{md}/{fname}（不是 csv）")
                continue
            step, q = split_name(fname)
            head = csv_head(data)
            if head and head[0] == "field":
                continue  # 长表，归界面场
            if not head or head[0] not in ("node", "elem"):
                key = f"rawcsv__{model}__{fname[:-4]}"
                arrays[key] = np.frombuffer(data, np.uint8)
                index["tables"].append({"model": model, "step": step, "quantity": q, "file": f"{md}/{fname}", "key": key,
                                        "raw": True, "csv_sha256": sha256_bytes(data), "csv_bytes": len(data)})
                index["checks"].append({"what": f"{md}/{fname} 的表头不认识，整个文件原样存成字节", "ok": False})
                continue
            cols, lab, val = parse_wide(data)
            val = compact(val)
            key = f"{model}__{step}__{q}"
            arrays[key] = val
            index["tables"].append({
                "model": model, "step": step, "quantity": q, "file": f"{md}/{fname}", "key": key,
                "label_key": label_key(lab), "label_kind": head[0], "columns": cols[1:], "n_rows": int(len(lab)),
                "dtype": str(val.dtype), "csv_sha256": sha256_bytes(data), "csv_bytes": len(data),
            })

    # 和网格对一下行数
    if mesh is not None:
        n_nodes = int(len(mesh["node_labels"])) if "node_labels" in mesh else None
        node_set = mesh.get("node_labels")
        parts = {"m_fric": ("cortex_elab", "cancellous_elab", "stem_elab"),
                 "m_bond": ("cortex_elab", "cancellous_elab", "stem_elab"),
                 "intact": ("cortex_elab", "cancellous_elab")}
        for t in index["tables"]:
            if t.get("raw"):
                continue
            lab = arrays[t["label_key"]]
            if t["label_kind"] == "node" and t["quantity"] == "U" and node_set is not None:
                ok = t["n_rows"] == n_nodes and bool(np.array_equal(np.sort(lab), np.sort(node_set)))
                index["checks"].append({"what": f"{t['file']}：位移的节点和网格的节点是同一批（{t['n_rows']} 对 {n_nodes}）", "ok": ok})
            elif t["label_kind"] == "node" and node_set is not None:
                ok = bool(np.isin(lab, node_set).all())
                index["checks"].append({"what": f"{t['file']}：节点编号都在网格里", "ok": ok})
            elif t["label_kind"] == "elem":
                have = [mesh[k] for k in parts.get(t["model"], ()) if k in mesh]
                if have:
                    elab = np.concatenate(have)
                    ok = t["n_rows"] == len(elab) and bool(np.array_equal(np.sort(lab), np.sort(elab)))
                    index["checks"].append({"what": f"{t['file']}：单元和网格的单元是同一批（{t['n_rows']} 对 {len(elab)}）", "ok": ok})
    for rel in sorted(a.files):
        if "/" not in rel and rel.endswith(".inp"):
            index["not_exported"].append(f"{rel}（求解器的输入文件，不是场）")
    arrays["index"] = np.array(json.dumps(index, ensure_ascii=False))
    arrays["doc"] = np.array(json.dumps(GLOBAL_DOC, ensure_ascii=False))
    arrays["version"] = np.array(f"fea-archive-export {VERSION}")
    return arrays, index


def read_global(path) -> dict:
    """读一个整体场文件。返回 {(model, step, quantity): (编号, 数值, 列名)}，另有 "mesh" 和 "index" 两项。"""
    z = np.load(path, allow_pickle=False)
    index = json.loads(str(z["index"]))
    out: dict = {"index": index, "mesh": {k[5:]: z[k] for k in z.files if k.startswith("mesh_")}}
    for t in index["tables"]:
        if t.get("raw"):
            continue
        out[(t["model"], t["step"], t["quantity"])] = (z[t["label_key"]], z[t["key"]], t["columns"])
    return out


# ---------------------------------------------------------------- 一个作业的清单：有什么，缺什么

def inventory(a: Archive, row: dict, iface_info: dict | None, global_index: dict | None) -> dict:
    """这个作业的归档里有什么、导出了什么、缺什么。"""
    inv: dict = {"job_id": a.job, "status": row.get("status"), "kind": row.get("kind"),
                 "archive_sha256": a.sha256, "archive_bytes": a.size, "n_files": len(a.files),
                 "models": {}, "missing": [], "not_exported": []}
    for md in a.model_dirs():
        steps = step_order(a, md)
        have: dict[str, list[str]] = {}
        for f in a.files:
            if f.startswith(md + "/") and f.endswith(".csv"):
                step, q = split_name(f.split("/", 1)[1])
                have.setdefault(q, []).append(step)
        inv["models"][md[:-4]] = {"steps": steps, "quantities": {q: [s for s in steps if s in ss] for q, ss in sorted(have.items())}}
        if md == "m_fric_csv":
            for q in ("U", "RF", "CONTACT", "CFORCE", "S", "E"):
                lack = [s for s in steps if s not in have.get(q, [])]
                if lack:
                    inv["missing"].append(f"摩擦模型的 {q} 在这些步没有：{'、'.join(lack)}")
        else:
            name = "粘接模型" if md == "m_bond_csv" else "完整股骨" if md == "intact_csv" else md
            inv["missing"].append(f"{name}没有位移、反力、应变，只有 {'、'.join(sorted(have))}")
    if not a.has("mesh3d.npz"):
        inv["missing"].append("没有网格（mesh3d.npz）")
    if row.get("status") != "DONE":
        inv["missing"].append(f"作业的结局是 {row.get('status')}，没有结果")
    if global_index:
        inv["not_exported"] += global_index["not_exported"]
        inv["checks_failed"] = [c["what"] for c in global_index["checks"] if not c["ok"]]
        inv["n_nodes"] = (global_index["mesh"].get("node_labels") or {}).get("shape", [None])[0]
        inv["n_elems"] = sum(v["shape"][0] for k, v in global_index["mesh"].items() if k.endswith("_elab")) or None
    if iface_info:
        inv["iface"] = {"n_pairs": iface_info["n_pairs"], "n_tri": iface_info["n_tri"], "steps": iface_info["steps"],
                        "missing": iface_info["missing"], "unmatched_rows": iface_info["unmatched_rows"]}
        inv["missing"] += [f"界面场缺：{m}" for m in iface_info["missing"]]
    return inv


# ---------------------------------------------------------------- 存

def save_npz(path: Path, arrays: dict) -> None:
    """先写到旁边的临时文件，写完再改名：半截的文件不会留成正式的名字。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as f:
        np.savez_compressed(f, **arrays)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def raw_json_bundle(a: Archive) -> dict:
    """归档里所有小的文字文件，原样收在一起：json 按内容，标记文件和日志按文字。"""
    out: dict = {"job_id": a.job, "json": {}, "text": {}, "mtime_utc": {}, "manifest": a.manifest}
    for rel in sorted(a.files):
        if "/" in rel:
            continue
        out["mtime_utc"][rel] = utc(a.mtimes.get(rel))
        if rel.endswith(".json"):
            try:
                out["json"][rel] = json.loads(a.files[rel].decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                out["text"][rel] = a.files[rel].decode("utf-8", "replace")
        elif rel in ("DONE", "CLAIMED", "SOLVED", "READY") or rel.endswith(".log"):
            out["text"][rel] = a.files[rel].decode("utf-8", "replace")
    return out


def export_job(folder: Path, job: str, out_dir: Path, quantities, stage=lambda name: None) -> dict:
    """导出一个作业。返回 {row, inventory, errors, notes}。归档读不了时抛 ArchiveError。

    stage(名字)：每进一个阶段叫一次；它可以抛 Stopped 来叫停。
    一样量出错不拦别的量：错记在 errors 里。
    """
    stage("读归档")
    a = Archive(folder, job).load()
    errors: list[str] = []
    stage("标签")
    row = label_row(a)
    try:
        mesh = a.mesh()
    except Exception as err:  # 网格读不了：界面场和整体场里的网格都做不了，别的照做
        mesh = None
        errors.append(f"mesh3d.npz 读不出来：{type(err).__name__}: {err}")
    if "标签" in quantities:
        write_text(out_dir / "标签" / "原始json" / f"{job}.json",
                   json.dumps(raw_json_bundle(a), ensure_ascii=False, indent=1))

    stage("界面场")
    iface_info = None
    try:
        built = build_iface(a, mesh)
        if built is not None:
            arrays, iface_info = built
            row_from_iface(row, arrays)
            if "界面场" in quantities:
                save_npz(out_dir / "界面场" / f"{job}.npz", arrays)
    except Stopped:
        raise
    except Exception as err:
        errors.append(f"界面场没做成：{type(err).__name__}: {err}")

    stage("整体场")
    global_index = None
    try:
        built = build_global(a, mesh)
        if built is not None:
            arrays, global_index = built
            if "整体场" in quantities:
                save_npz(out_dir / "整体场" / f"{job}.npz", arrays)
            bad = [c["what"] for c in global_index["checks"] if not c["ok"]]
            if bad:
                errors.append("整体场和网格对不上：" + "；".join(bad))
    except Stopped:
        raise
    except Exception as err:
        errors.append(f"整体场没做成：{type(err).__name__}: {err}")

    inv = inventory(a, row, iface_info, global_index)
    return {"row": row, "inventory": inv, "errors": errors, "notes": list(row["export_notes"])}


# ---------------------------------------------------------------- 汇总

def write_labels(out_dir: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: r["job_id"])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(C.NAMES)
    for r in rows:
        w.writerow([fmt_cell(r.get(c), C.TYPE[c]) for c in C.NAMES])
    write_text(out_dir / "标签" / "标签.csv", buf.getvalue())
