"""Abaqus 批量提交、判定与 odb 导出（CLAUDE.md §5.4–5.5）。

* 并发上限可配（config.yaml abaqus.max_concurrent）；许可获取失败排队重试，不直接判失败。
* 判定：.sta 最后有 "COMPLETED SUCCESSFULLY" 为 OK；否则 L4（求解不收敛/出错）；超时判 L4。
* odb 导出失败判 L5。任何失败都返回原因，由调用方写进 runs.csv，不静默吞掉。
* 本模块自己知道是哪一种失败时，返回里带 code（名字见 v2/result_codes.py：solve_timeout、license_unavailable、
  export_incomplete）；求解器自己的报错不带 code，由 Linux 端从 reason 的文字认。
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import pathlib
import re
import subprocess
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
LAUNCHER = CFG["abaqus"]["launcher"]
EXPORT = ROOT / "abaqus" / "odb_export.py"
LICENSE_PAT = re.compile(r"licen[cs]e.*(not available|unable|error|denied|exceed|queued)|"
                         r"(unable to (obtain|check out)).*licen", re.I)
TRANSIENT_PAT = re.compile(r"DLL load failed|being used by another process|另一个程序正在使用此文件|"
                           r"PermissionError|WinError 32", re.I)


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def _cleanup(workdir: pathlib.Path, job: str) -> None:
    for ext in (".lck",):
        f = workdir / f"{job}{ext}"
        if f.exists():
            f.unlink()


def run_job(inp: pathlib.Path, *, cpus: int | None = None, timeout: float | None = None) -> dict:
    """同步运行一个作业。返回 {job, status, wall_s, reason, tries}。"""
    inp = pathlib.Path(inp).resolve()
    workdir, job = inp.parent, inp.stem
    cpus = cpus or CFG["abaqus"]["cpus_per_job"]
    timeout = timeout or CFG["abaqus"]["timeout_s"]
    tries_max = CFG["abaqus"]["license_retry"]["max_tries"]
    wait = CFG["abaqus"]["license_retry"]["wait_s"]
    t0 = time.perf_counter()
    for attempt in range(1, tries_max + 1):
        for ext in (".sta", ".msg", ".dat", ".odb", ".log"):
            f = workdir / f"{job}{ext}"
            if f.exists():
                f.unlink()
        _cleanup(workdir, job)
        cmd = ["cmd", "/c", LAUNCHER, f"job={job}", f"input={inp.name}", f"cpus={cpus}",
               "interactive", "ask_delete=OFF"]
        try:
            proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                                  timeout=timeout, errors="ignore")
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            subprocess.run(["cmd", "/c", LAUNCHER, "terminate", f"job={job}"], cwd=workdir,
                           capture_output=True, text=True)
            return {"job": job, "status": "L4", "wall_s": time.perf_counter() - t0,
                    "reason": f"timeout > {timeout} s", "tries": attempt, "code": "solve_timeout"}
        (workdir / f"{job}.runner.log").write_text(out, encoding="utf-8")
        sta, log, msg = _read(workdir / f"{job}.sta"), _read(workdir / f"{job}.log"), _read(workdir / f"{job}.msg")
        if "COMPLETED SUCCESSFULLY" in sta:
            return {"job": job, "status": "OK", "wall_s": time.perf_counter() - t0, "reason": "",
                    "tries": attempt}
        if LICENSE_PAT.search(out + log) and "COMPLETED" not in sta:
            time.sleep(wait)
            continue
        if not sta and TRANSIENT_PAT.search(out):
            # 启动器瞬时故障（Windows 文件锁导致 DLL 加载失败等），求解器根本没启动：重试，不判 L4
            time.sleep(5)
            continue
        reason = _first_error(msg, _read(workdir / f"{job}.dat"), log, out)
        return {"job": job, "status": "L4", "wall_s": time.perf_counter() - t0, "reason": reason,
                "tries": attempt}
    return {"job": job, "status": "L4", "wall_s": time.perf_counter() - t0,
            "reason": f"license unavailable after {tries_max} tries", "tries": tries_max, "code": "license_unavailable"}


def _first_error(*texts: str) -> str:
    for t in texts:
        m = re.search(r"\*\*\*ERROR:?\s*(.{0,300})", t, re.S)
        if m:
            return " ".join(m.group(1).split())[:300]
    for t in texts:
        if "NOT BEEN COMPLETED" in t or "exited with error" in t.lower():
            return "analysis not completed (see .msg)"
    return "unknown failure (see .log/.msg)"


def export_odb(odb: pathlib.Path, out_dir: pathlib.Path, timeout: float = 600, script: pathlib.Path | None = None) -> dict:
    """在 Abaqus 内置 Python 下跑导出脚本（默认 odb_export.py；3D 用 odb_export3d.py；只用标准库）。失败返回 L5。"""
    odb = pathlib.Path(odb).resolve()
    out_dir = pathlib.Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["cmd", "/c", LAUNCHER, "python", str(script or EXPORT), str(odb), str(out_dir)]
    try:
        proc = subprocess.run(cmd, cwd=odb.parent, capture_output=True, text=True, timeout=timeout,
                              errors="ignore")
    except subprocess.TimeoutExpired:
        return {"status": "L5", "reason": "odb export timeout"}
    meta = out_dir / "odb_meta.json"
    if proc.returncode != 0 or not meta.exists():
        return {"status": "L5", "reason": " ".join(((proc.stdout or "") + (proc.stderr or "")).split())[-300:]}
    return {"status": "OK", "meta": json.loads(meta.read_text())}


def run_and_export(inp: pathlib.Path, export_script: pathlib.Path | None = None, **kw) -> dict:
    r = run_job(inp, **kw)
    if r["status"] != "OK":
        return r
    inp = pathlib.Path(inp).resolve()
    e = export_odb(inp.with_suffix(".odb"), inp.parent / f"{inp.stem}_csv", script=export_script)
    r["export"] = e["status"]
    if e["status"] != "OK":
        r["status"], r["reason"], r["code"] = "L5", e["reason"], "export_incomplete"
    else:
        r["odb_meta"] = e["meta"]
    return r


def run_many(inps: list[pathlib.Path], max_concurrent: int | None = None, export: bool = True) -> list[dict]:
    n = max_concurrent or CFG["abaqus"]["max_concurrent"]
    fn = run_and_export if export else run_job
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(fn, inps))
