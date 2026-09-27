"""3D 评估（带缓存、进程并行）：设计 → 3D 摩擦与粘接模型 → QoI → results/runs3d.jsonl。

缓存键 = 分型、设计变量、界面网格尺寸、config 与 3D 建模源码哈希。每型一个完整 3D 股骨作 SED 参照（同样缓存）。
成功的作业删除 .odb 等大文件，只留 gzip 的所需 CSV 与日志。
"""
from __future__ import annotations

import concurrent.futures as cf
import gzip
import hashlib
import json
import pathlib
import shutil
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

LOG = ROOT / "results" / "runs3d.jsonl"
RUN3 = ROOT / "runs" / "3d"
KEEP = {"fric": ["RELEASE_CONTACT.csv", "LOAD_CONTACT.csv"], "bond": ["LOAD_ENER.csv"], "intact": ["LOAD_ENER.csv"]}


def code_hash() -> str:
    import evaluate as EV
    extra = {m: hashlib.sha1((HERE / m).read_bytes()).hexdigest() for m in ("model3d.py", "qoi3d.py", "eval3d.py")}
    return hashlib.sha1((EV._cfg_hash() + json.dumps(extra, sort_keys=True)).encode()).hexdigest()[:10]


def key_of(kind: str, dorr: str, design: dict | None, h: float) -> str:
    import stem2d as S
    x = [round(float(design[v]), 9) for v in S.VARS] if design else []
    return hashlib.sha1(json.dumps({"k": kind, "d": dorr, "x": x, "h": h, "c": code_hash()}).encode()).hexdigest()[:16]


def read_log() -> dict:
    out = {}
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def _tidy(d: pathlib.Path, job: str, kind: str):
    for ext in (".odb", ".prt", ".com", ".sim", ".res", ".mdl", ".stt", ".lck"):
        p = d / f"{job}{ext}"
        if p.exists():
            p.unlink()
    inp = d / f"{job}.inp"
    if inp.exists():
        with open(inp, "rb") as a, gzip.open(str(inp) + ".gz", "wb") as b:
            shutil.copyfileobj(a, b)
        inp.unlink()
    cd = d / f"{job}_csv"
    if cd.exists():
        for p in cd.iterdir():
            if p.name in KEEP[kind]:
                with open(p, "rb") as a, gzip.open(str(p) + ".gz", "wb") as b:
                    shutil.copyfileobj(a, b)
            if p.suffix == ".csv":
                p.unlink()


def _intact_task(dorr: str, key: str, h: float) -> dict:
    import femur2d as F
    import model3d as M
    import qoi3d as Q
    import run_abaqus as ra
    d = RUN3 / f"intact_{dorr}_{key[:8]}"
    if d.exists():
        shutil.rmtree(d)
    f = F.build(dorr)
    M.build_intact(f, d, "intact", h_roi=h, h_far=6.0)
    r = ra.run_and_export(d / "intact.inp", cpus=4, timeout=7200)
    if r["status"] != "OK":
        return {"key": key, "kind": "intact", "dorr": dorr, "status": r["status"], "reason": r.get("reason", "")}
    z = Q.zone_sed(d, "intact", dorr, f.E_cancellous)
    _tidy(d, "intact", "intact")
    return {"key": key, "kind": "intact", "dorr": dorr, "status": "OK", "gruen7": float(z["gruen7"]),
            "gruen1": float(z["gruen1"]), "dir": str(d.relative_to(ROOT)), "wall_s": r["wall_s"]}


def _task(item: dict) -> dict:
    import femur2d as F
    import model3d as M
    import qoi3d as Q
    import run_abaqus as ra
    import stem2d as S
    t0 = time.perf_counter()
    key, dorr, h = item["key"], item["dorr"], item["h"]
    d = RUN3 / f"{dorr}_{key[:10]}"
    out = {"key": key, "kind": "implant", "dorr": dorr, "design": item["design"], "h_int": h, "tag": item.get("tag", ""),
           "design_id_2d": item.get("design_id_2d", ""), "dir": str(d.relative_to(ROOT))}
    try:
        if d.exists():
            shutil.rmtree(d)
        info = M.build(S.make(dorr, item["design"]), d, "m", h_int=h, h_far=6.0)
        out["n_tet"] = info["n_tet"]
    except Exception as e:                                                  # noqa: BLE001
        d.mkdir(parents=True, exist_ok=True)
        (d / "mesh_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        out.update(status="L3", reason=f"{type(e).__name__}: {e}"[:300])
        return out
    for kind in ("fric", "bond"):
        r = ra.run_and_export(d / f"m_{kind}.inp", cpus=4, timeout=14400)
        out[f"wall_{kind}"] = r.get("wall_s")
        if r["status"] != "OK":
            out.update(status=r["status"], reason=f"{kind}: {r.get('reason', '')}"[:300])
            return out
    try:
        mm = Q.micromotion(d, "m_fric")
        zs = Q.zone_sed(d, "m_bond", dorr, F.build(dorr).E_cancellous)
        ref = item["intact"]
        out.update(mm)
        out.update(status="OK", f2_g7_loss_pct=100 * (1 - zs["gruen7"] / ref["gruen7"]),
                   f2_g1_loss_pct=100 * (1 - zs["gruen1"] / ref["gruen1"]), t_total_s=time.perf_counter() - t0)
        _tidy(d, "m_fric", "fric")
        _tidy(d, "m_bond", "bond")
    except Exception as e:                                                  # noqa: BLE001
        (d / "qoi_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        out.update(status="L5", reason=f"{type(e).__name__}: {e}"[:300])
    return out


def _append(r: dict):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(r, ensure_ascii=False, default=float) + "\n")


def intact(dorr: str, h: float = 2.0) -> dict:
    key = key_of("intact", dorr, None, h)
    log = read_log()
    if key in log and log[key]["status"] == "OK":
        return log[key]
    r = _intact_task(dorr, key, h)
    _append(r)
    if r["status"] != "OK":
        raise RuntimeError(f"3D intact {dorr}: {r}")
    return r


def evaluate(items: list[dict], h: float = 2.0, max_parallel: int = 2, verbose: bool = True) -> list[dict]:
    """items: [{"dorr", "design", "tag"?, "design_id_2d"?}]；返回同序结果（含缓存命中）。"""
    log = read_log()
    refs = {t: intact(t, h) for t in sorted({it["dorr"] for it in items})}
    out, todo = [None] * len(items), []
    for i, it in enumerate(items):
        k = key_of("implant", it["dorr"], it["design"], h)
        if k in log and log[k]["status"] == "OK":
            out[i] = log[k]
        else:
            todo.append((i, dict(it, key=k, h=h, intact=refs[it["dorr"]])))
    t0 = time.perf_counter()
    with cf.ProcessPoolExecutor(max_workers=max_parallel) as ex:
        futs = {ex.submit(_task, t): i for i, t in todo}
        for n, fu in enumerate(cf.as_completed(futs), 1):
            i = futs[fu]
            try:
                r = fu.result()
            except Exception as e:                                          # noqa: BLE001
                r = {"key": todo[[j for j, _ in todo].index(i)][1]["key"], "status": "L5", "reason": str(e)[:300]}
            _append(r)
            out[i] = r
            if verbose:
                print(f"[3D {n}/{len(todo)}] {r.get('dorr')} {r['status']} f1={r.get('f1_p95_um')} "
                      f"f2={r.get('f2_g7_loss_pct')} {r.get('reason', '')[:80]} elapsed {(time.perf_counter() - t0) / 60:.1f} min",
                      flush=True)
    return out
