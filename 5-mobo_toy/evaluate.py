"""批量评估：设计 → 几何门 → 网格 → _fric/_bond 两个 Abaqus 作业 → QoI → results/runs.csv（CLAUDE.md §9–10）。

* 每个设计一行，成败都记；design_id = d{序号:06d}_{哈希前 4 位}。
* 失败分级：L1 参数层、L2 几何层（几何门）、L3 网格、L4 求解、L5 导出/QoI。
* 缓存：同一 cache_key（分型、松质骨模量、设计变量、μ、δ、载荷方向、网格倍率、侧板厚度、config 相关段落）
  已有 status = OK 的行时直接复用，不重算（返回行标 cached = 1）。
* 并行：进程池，每个进程串行跑一个设计的两个作业，所以并发作业数 = 进程数（gmsh 非线程安全，故用进程）。
* 磁盘：成功设计删除 .odb 等大文件、只保留 QoI 与作图所需 CSV（gzip）、.inp（gzip）、日志、网格；
  失败设计保留全部文件。
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import shutil
import time
import traceback

import numpy as np

import plotstyle as ps

ROOT = ps.ROOT
RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
RUNS_CSV = RESULTS / "runs.csv"
INTACT_DIR = RESULTS / "intact"

VARS = ["tip_depth", "tip_lat", "w_prox", "taper", "theta_in"]
COLUMNS = (["design_id", "timestamp", "provenance", "campaign", "seed", "round", "dorr", "E_cancellous",
            "mu", "delta", "load_sign", "mesh_scale", "side_plate"] + VARS +
           ["kappa", "L", "status", "fail_stage", "fail_reason",
            "overlap_cortex", "wall", "stem_area_in_bone", "cavity_area", "n_elem_bone", "n_elem_stem", "min_angle",
            "f1_p95_um", "f1_mean_um", "f1_max_um", "frac_gt50", "frac_gt150", "frac_open", "frac_slip",
            "frac_stick", "cpress_release_mean", "cpress_load_mean", "interface_length",
            "f2_g7_loss_pct", "f2_g1_loss_pct", "sed_g7", "sed_g1", "vm_p99", "vm_max",
            "t_mesh_s", "t_fric_s", "t_bond_s", "t_total_s", "cache_key", "cached", "note"])
KEEP_CSV = {"fric": ["RELEASE_CONTACT.csv", "LOAD_CONTACT.csv", "LOAD_S.csv"],
            "bond": ["LOAD_ENER.csv", "LOAD_S.csv"]}


def _cfg_hash() -> str:
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    rel = {k: cfg[k] for k in ("femur", "dorr", "materials", "plane_stress_thickness", "contact_thickness", "load",
                               "interface", "stem", "design_space", "mesh", "qoi", "side_plate")}
    return hashlib.sha1(json.dumps(rel, sort_keys=True).encode()).hexdigest()[:10]


def default_variant(**kw) -> dict:
    import femur2d as F
    c = F.CFG
    v = {"mu": c["interface"]["mu"], "delta": c["interface"]["delta"], "load_sign": 1.0, "mesh_scale": 1.0,
         "side_plate": c["side_plate"]["thickness"]}
    v.update({k: w for k, w in kw.items() if w is not None})
    return v


def cache_key(dorr: str, E_canc: float, design: dict, variant: dict) -> str:
    payload = {"dorr": dorr, "E": round(float(E_canc), 6), "cfg": _cfg_hash(),
               "x": [round(float(design[k]), 9) for k in VARS], **{k: round(float(v), 9) for k, v in variant.items()}}
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------------ runs.csv
def read_runs() -> list[dict]:
    if not RUNS_CSV.exists():
        return []
    with open(RUNS_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append_rows(rows: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    new = not RUNS_CSV.exists()
    with open(RUNS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: _cell(v) for k, v in r.items()})


def _cell(v):
    """numpy 标量先转成 Python 类型（numpy 2 的 repr 会写成 np.float64(...)）；浮点用 repr 保全精度。"""
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return repr(v)
    return "" if v is None else v


def next_seq() -> int:
    rows = read_runs()
    return 1 + max([int(r["design_id"][1:7]) for r in rows] or [0])


# ------------------------------------------------------------------ intact references
def intact_ref(dorr: str, E_canc: float, variant: dict) -> dict:
    import fe_model as FM
    import qoi
    import run_abaqus as ra
    key = hashlib.sha1(json.dumps({"dorr": dorr, "E": E_canc, "sp": variant["side_plate"], "ls": variant["load_sign"],
                                   "ms": variant["mesh_scale"], "cfg": _cfg_hash()}, sort_keys=True).encode()).hexdigest()[:12]
    INTACT_DIR.mkdir(parents=True, exist_ok=True)
    f = INTACT_DIR / f"{dorr}_{E_canc:g}_{key}.json"
    if f.exists():
        return json.loads(f.read_text())
    d = RUNS / "intact" / f"{dorr}_{E_canc:g}_{key}"
    if d.exists():
        shutil.rmtree(d)
    FM.build_intact(dorr, E_canc, d, "intact", load_sign=variant["load_sign"], mesh_scale=variant["mesh_scale"],
                    side_plate=variant["side_plate"])
    r = ra.run_and_export(d / "intact.inp")
    if r["status"] != "OK":
        raise RuntimeError(f"intact reference failed for {dorr}/{E_canc}: {r}")
    z = qoi.zone_sed(d, "intact")
    out = {"gruen7": z["gruen7"]["SED"], "gruen1": z["gruen1"]["SED"], "dir": ps.rel(d), "key": key}
    f.write_text(json.dumps(out, indent=1))
    return out


# ------------------------------------------------------------------ worker
def _tidy(run_dir: pathlib.Path, name: str) -> None:
    """成功设计：删大文件，只留所需 CSV（gzip）、inp（gzip）、日志、网格。"""
    for kind in ("fric", "bond"):
        job = f"{name}_{kind}"
        for ext in (".odb", ".prt", ".com", ".sim", ".res", ".mdl", ".stt", ".abq", ".pac", ".sel", ".lck"):
            p = run_dir / f"{job}{ext}"
            if p.exists():
                p.unlink()
        inp = run_dir / f"{job}.inp"
        if inp.exists():
            with open(inp, "rb") as a, gzip.open(str(inp) + ".gz", "wb") as b:
                shutil.copyfileobj(a, b)
            inp.unlink()
        cdir = run_dir / f"{job}_csv"
        if cdir.exists():
            for p in cdir.iterdir():
                if p.name in KEEP_CSV[kind]:
                    with open(p, "rb") as a, gzip.open(str(p) + ".gz", "wb") as b:
                        shutil.copyfileobj(a, b)
                if p.suffix == ".csv":
                    p.unlink()


def run_one(task: dict) -> dict:
    """在子进程里评估一个设计。task: design_id, dorr, E_canc, design, variant, intact, keep_all。"""
    import fe_model as FM
    import qoi
    import run_abaqus as ra
    import stem2d as S

    t0 = time.perf_counter()
    row = {k: task.get(k, "") for k in ("design_id", "provenance", "campaign", "seed", "round", "dorr", "cache_key")}
    row.update({"timestamp": dt.datetime.now().isoformat(timespec="seconds"), "E_cancellous": task["E_canc"],
                **task["variant"], **{k: task["design"][k] for k in VARS}, "cached": 0, "note": task.get("note", "")})
    run_dir = RUNS / task["design_id"]
    try:
        st = S.make(task["dorr"], task["design"], task["E_canc"])
        g = S.gate(st)
        row.update({"kappa": st.kappa, "L": st.L, "overlap_cortex": g.get("overlap_cortex"), "wall": g.get("wall")})
        if not g["pass"]:
            row.update(status=g["level"], fail_stage="gate", fail_reason=g["reason"],
                       t_total_s=time.perf_counter() - t0)
            return row
    except Exception as e:                                             # noqa: BLE001
        row.update(status="L1", fail_stage="gate", fail_reason=f"{type(e).__name__}: {e}"[:300])
        return row
    try:
        tm = time.perf_counter()
        if run_dir.exists():
            shutil.rmtree(run_dir)
        v = task["variant"]
        info = FM.build_implanted(st, run_dir, task["design_id"], mu=v["mu"], delta=v["delta"],
                                  load_sign=v["load_sign"], mesh_scale=v["mesh_scale"], side_plate=v["side_plate"])
        row.update({k: info[k] for k in ("n_elem_bone", "n_elem_stem", "min_angle", "cavity_area", "stem_area_in_bone")})
        row["t_mesh_s"] = time.perf_counter() - tm
    except Exception as e:                                             # noqa: BLE001
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "mesh_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(status="L3", fail_stage="mesh", fail_reason=f"{type(e).__name__}: {e}"[:300],
                   t_total_s=time.perf_counter() - t0)
        return row
    name = task["design_id"]
    rf = ra.run_and_export(run_dir / f"{name}_fric.inp")
    rb = ra.run_and_export(run_dir / f"{name}_bond.inp") if rf["status"] == "OK" else {"status": "skipped", "wall_s": 0}
    row["t_fric_s"], row["t_bond_s"] = rf.get("wall_s"), rb.get("wall_s")
    for kind, r in (("fric", rf), ("bond", rb)):
        if r["status"] not in ("OK", "skipped"):
            row.update(status=r["status"], fail_stage=f"abaqus_{kind}", fail_reason=r.get("reason", "")[:300],
                       t_total_s=time.perf_counter() - t0)
            return row
    try:
        q = qoi.evaluate_dir(run_dir, name, task["intact"])
        row.update(q)
        row.update(status="OK", fail_stage="", fail_reason="")
    except Exception as e:                                             # noqa: BLE001
        (run_dir / "qoi_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(status="L5", fail_stage="qoi", fail_reason=f"{type(e).__name__}: {e}"[:300])
    row["t_total_s"] = time.perf_counter() - t0
    if row["status"] == "OK" and not task.get("keep_all"):
        _tidy(run_dir, name)
    return row


# ------------------------------------------------------------------ public API
def evaluate(items: list[dict], *, campaign: str, provenance: str = "sampled", max_workers: int | None = None,
             keep_all: bool = False, verbose: bool = True, force: bool = False) -> list[dict]:
    """items: [{"dorr", "design": {...}, "E_canc"?, "variant"?: {...}, "seed"?, "round"?, "note"?}]。
    返回与 items 同序的行（含缓存命中）。"""
    import femur2d as F
    import run_abaqus as ra
    max_workers = max_workers or ra.CFG["abaqus"]["max_concurrent"]
    existing = {}
    for r in read_runs():
        if r["status"] == "OK" and r.get("cache_key"):
            existing.setdefault(r["cache_key"], r)
    seq = next_seq()
    tasks, out = [], [None] * len(items)
    intact_cache: dict = {}
    for i, it in enumerate(items):
        E = float(it.get("E_canc") or F.CFG["dorr"][it["dorr"]]["E_cancellous"])
        var = default_variant(**(it.get("variant") or {}))
        key = cache_key(it["dorr"], E, it["design"], var)
        if key in existing and not force:
            row = dict(existing[key]); row["cached"] = 1
            out[i] = row
            continue
        ik = (it["dorr"], E, var["side_plate"], var["load_sign"], var["mesh_scale"])
        if ik not in intact_cache:
            intact_cache[ik] = intact_ref(it["dorr"], E, var)
        did = f"d{seq:06d}_{key[:4]}"
        seq += 1
        tasks.append((i, {"design_id": did, "dorr": it["dorr"], "E_canc": E, "design": it["design"], "variant": var,
                          "intact": intact_cache[ik], "cache_key": key, "campaign": campaign,
                          "provenance": provenance, "seed": it.get("seed", ""), "round": it.get("round", ""),
                          "note": it.get("note", ""), "keep_all": keep_all}))
    t0 = time.perf_counter()
    done = 0
    if tasks:
        with cf.ProcessPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(run_one, t): i for i, t in tasks}
            for fu in cf.as_completed(futs):
                i = futs[fu]
                try:
                    row = fu.result()
                except Exception as e:                                 # noqa: BLE001
                    t = next(tt for j, tt in tasks if j == i)
                    row = {"design_id": t["design_id"], "dorr": t["dorr"], "status": "L5", "fail_stage": "worker",
                           "fail_reason": f"{type(e).__name__}: {e}"[:300], "cache_key": t["cache_key"],
                           "campaign": campaign, **{k: t["design"][k] for k in VARS}}
                append_rows([row])
                out[i] = row
                done += 1
                if verbose:
                    el = time.perf_counter() - t0
                    print(f"[{done}/{len(tasks)}] {row['design_id']} {row['dorr']} {row['status']} "
                          f"{row.get('fail_reason') or ''} f1={row.get('f1_p95_um', '')} "
                          f"f2={row.get('f2_g7_loss_pct', '')}  elapsed {el / 60:.1f} min", flush=True)
    return out


def as_float(r: dict, k: str) -> float:
    try:
        return float(r[k])
    except (KeyError, TypeError, ValueError):
        return float("nan")
