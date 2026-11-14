"""内核包的入口：冻结的 FE 模型 M1-3406-v1。

    python code/main.py <输入文件夹> <输出文件夹>

输入文件夹里的 job.json 说要做什么（约定见 stemlab/contract/formats/package.py）：
    template   一批设计各自放进这根骨里：放不放得下、去多少骨。不做 FE
    build      一个点：模板化、划网格、写 Abaqus 的输入。产出放在 job 文件夹里
    post       求解结束之后：读结果，算标签，导出界面的场
    bench      验证用：Lamé 压配对照（圆柱压进套筒），走和设计模型相同的界面代码。只建模，求解和后处理同 build、post

旧代码在 code/legacy/ 下，是从旧系统原字节搬来的，一个字节不改：8 个计入 code_hash 的文件就是冻结的模型。
这个文件只做三件事：把 stem-lab 的一个点翻成旧代码的 spec；把旧代码要的文件和缓存安排到可写的地方；
把旧代码的结果翻回约定的 result.json。怎么算，一行都不在这里。

旧代码每个作业要一个自己的进程（它会改进程里的全局状态），所以这个入口一次只做一件事。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEGACY = HERE / "legacy"
BONE_ID = "sawbone3406"
STEP_NAMES = {"cortical": "3406R_cortical.STEP", "cancellous": "3406R_cancellous_v2.STEP"}

# 一个点要带的设计项。e 是入口偏移：一个数就固定在这个值；写 "rule" 就由生产规则在九档里选
DESIGN = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p", "e")
STEM_KEYS = ("L", "alpha", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
CONDITIONS = ("delta_mm", "mu", "E_canc_MPa", "load_N", "load_front_deg", "load_sagit_deg", "cycles", "h_int_mm")
# 生产设置里固定不变的那几项（旧系统 3406 批次的写法）
FIXED = {"kind": "design", "model": "m1", "collar_rule": "neck_in_shoulder", "femur_id": BONE_ID, "neck_axis": "isthmus",
         "margin_check": "dense", "ref_cut_mm": 16.0, "a_bounds_max": 2000.0, "min_A0": math.pi * 7.0 ** 2,
         "fric_only": True, "stage": "sl"}
CAP_H = 1.5                     # 平端。必须写进 design：缺了就是半椭球帽，几何不同
BASE_LOAD = {"resultant_N": 2391.0, "alpha_front_deg": 20.0, "alpha_sagit_deg": 18.0}
BASE_E_CANC = 155.0
SLIP_TOL_AT_H2 = 0.00025        # 罚摩擦的弹性滑移上限，按 2.0 / h 放大，保持约 0.5 微米
UNSTABLE_UM = 150.0             # 界面相对位移超过它就长不上骨（Pilliar 1986；Jasty 1997）。不收敛时拿它判是不是已经松动
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")

# 旧系统的失败类 -> 约定里的 status
BUILD_STATUS = {"DESIGN": "misfit", "NUMERIC": "mesh_failed", "ENV": "env"}


class Unsupported(Exception):
    """这个包做不了这件事。"""


# ---------------------------------------------------------------- 安排旧代码要的文件和缓存

def _cache_root() -> Path:
    """这台机器上放股骨距离场缓存的地方。可写、可删：没有了会重建（约半分钟）。"""
    given = os.environ.get("STEMLAB_KERNEL_CACHE")
    if given:
        return Path(given)
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "stemlab" / "kernel-m1-3406"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def setup(bone_model) -> None:
    """让旧代码能在这个进程里跑：两个 STEP 从骨模型里取，缓存放到这台机器可写的地方。"""
    os.environ.setdefault("MPLBACKEND", "Agg")
    for folder in (LEGACY, LEGACY / "v2"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import femur_3406 as F3
    import femur_real as FR

    listed = json.loads((Path(bone_model) / "manifest.json").read_text(encoding="utf-8"))
    if listed.get("bone_id") != BONE_ID:
        raise Unsupported(f"这个内核只认 {BONE_ID}，骨模型是 {listed.get('bone_id')!r}")
    sources = {name: Path(bone_model) / listed["solids"][name]["file"] for name in STEP_NAMES}
    hashes = {name: _sha256(path) for name, path in sources.items()}
    if hashes != F3.SHA256:
        raise Unsupported("骨模型里的两个实体不是冻结模型认的那两个 STEP 文件（哈希不同）：这个内核只能算 3406R_v1_hollowcore")
    home = _cache_root() / hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]
    place = home / "femur_3406"
    place.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        target = place / STEP_NAMES[name]
        if not target.exists():
            spare = target.with_name(f"{target.name}.{os.getpid()}.part")
            shutil.copyfile(source, spare)
            os.replace(spare, target)
    (home / "cache").mkdir(exist_ok=True)
    F3.DATA = place
    FR.CACHE = F3.CACHE = home / "cache"
    _warm(F3, home)


def _warm(F3, home: Path) -> None:
    """缓存不在就先建好。同一时刻只让一个进程建：两个进程同时写同一个缓存文件会写坏。"""
    wanted = F3.CACHE / f"femur_3406_{F3._cache_key(F3.load_cfg(None))}.npz"
    guard = home / "building"
    deadline = time.time() + 1800
    while not wanted.exists():
        try:
            os.close(os.open(guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            if time.time() - guard.stat().st_mtime > 900:       # 建它的那个进程多半已经不在了
                guard.unlink(missing_ok=True)
            elif time.time() > deadline:
                raise Unsupported("股骨的缓存一直没有建好") from None
            else:
                time.sleep(2.0)
            continue
        try:
            if not wanted.exists():
                F3.build()
        finally:
            guard.unlink(missing_ok=True)


# ---------------------------------------------------------------- 一个点 -> 旧代码的 spec

def spec_of(point: dict, settings: dict) -> dict:
    """把一个点翻成旧代码的 spec。和旧系统 3406 生产批次的写法逐项相同；和基线相同的项不写，走旧代码的默认路径。"""
    design, conditions = point["design"], point["conditions"]
    missing = [key for key in DESIGN if key not in design] + [key for key in CONDITIONS if key not in conditions]
    if missing:
        raise Unsupported(f"这个点少了内核要的项：{missing}")
    h = float(conditions["h_int_mm"])
    spec = dict(FIXED, tag=str(point.get("name", "p")),
                design={**{key: float(design[key]) for key in STEM_KEYS}, "cap_h": CAP_H},
                h_cut=float(design["h_cut"]), h_int=h, delta=float(conditions["delta_mm"]),
                slip_tol=float(settings.get("slip_tol") or SLIP_TOL_AT_H2 * 2.0 / h))
    if design["e"] != "rule":
        spec["entry_offset"] = float(design["e"])
    if float(conditions["mu"]) != 0.3:
        spec["mu"] = float(conditions["mu"])
    if float(conditions["E_canc_MPa"]) != BASE_E_CANC:
        spec["E_canc"] = float(conditions["E_canc_MPa"])
    if int(conditions["cycles"]) != 2:
        spec["cycles"] = int(conditions["cycles"])
    load = {"resultant_N": float(conditions["load_N"]), "alpha_front_deg": float(conditions["load_front_deg"]),
            "alpha_sagit_deg": float(conditions["load_sagit_deg"])}
    if load != BASE_LOAD:
        spec["cfg"] = {"load": load}
    return spec


def _templating(spec: dict):
    """只做模板化：和旧代码建模前半段相同的顺序。返回（股骨，柄，放置结果）。"""
    import collar_rule as CR
    import geom3d as G
    import jobs as J
    import numpy as np

    fm = J.femur_for(spec)
    CR.install_neck(min_A0=float(spec["min_A0"]), margin_check=spec["margin_check"])
    installed = G.template
    try:
        if spec.get("entry_offset") is not None:
            fixed = np.array([float(spec["entry_offset"])])
            G.template = lambda stem, fem, alphas=None, offsets=None, iters=14, margin=None: \
                installed(stem, fem, alphas=alphas, offsets=fixed, iters=iters, margin=margin)
        stem = G.Stem3D(**spec["design"])
        with J.a_bounds_cap(spec.get("a_bounds_max")):
            placed = G.template(stem, fm, margin=spec.get("margin"))
    finally:
        G.template = installed
    return fm, stem, placed


def _pre(fm, spec: dict, placed: dict) -> dict:
    """建模之前就知道的量：选出的号和位置、去骨量。"""
    resected = fm.resected_volume(ref_cut_mm=float(spec["ref_cut_mm"]))
    return {"e_mm": float(placed["e"]), "A0_mm2": float(placed["A0"]), "alpha_placed_deg": float(placed["alpha"]),
            "contact_templated": float(placed["contact"]), "bone_resected_mm3": float(resected),
            "bone_reamed_mm3": float(placed["volume"]), "bone_total_mm3": float(resected + placed["volume"])}


# ---------------------------------------------------------------- 四种做法

def template(job: dict, out: Path) -> dict:
    setup(job["bone_model"])
    rows = []
    for one in job["designs"]:
        point = {"name": one["name"], "design": one["design"], "conditions": job.get("conditions") or _baseline_conditions()}
        try:
            spec = spec_of(point, job.get("settings") or {})
            fm, _, placed = _templating(spec)
            fits = bool(placed["fit"]) and placed["A0"] >= spec["min_A0"]
            info = _pre(fm, spec, placed) if fits else {"reason": str(placed.get("reason") or "shoulder smaller than the prosthetic neck")}
        except Unsupported as error:
            fits, info = False, {"reason": str(error)}
        rows.append({"name": one["name"], "feasible": fits, "info": info})
    return {"designs": rows}


def _baseline_conditions() -> dict:
    return {"delta_mm": 0.10, "mu": 0.3, "E_canc_MPa": BASE_E_CANC, "load_N": 2391.0, "load_front_deg": 20.0,
            "load_sagit_deg": 18.0, "cycles": 2, "h_int_mm": 2.0}


def _prep(job: dict, spec: dict) -> tuple[Path, str]:
    """叫旧代码建模。返回（作业文件夹，READY 或 FAILED）。"""
    import jobs as J

    where = Path(job["job"])
    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True)
    (where / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    J.QROOT, J.RESULTS = where.parent, where / "legacy-results"
    return where, J.prep(where.name)


def _solve_command(job: dict, unit: str) -> dict:
    how = (job.get("settings") or {}).get("abaqus") or {}
    cpus, limit = int(how.get("cpus", 5)), float(how.get("timeout_s", 21600))
    command = ["{python}", str(HERE / "solve.py"), unit, str(cpus), str(limit)] + ([str(how["launcher"])] if how.get("launcher") else [])
    return {"command": command, "timeout_s": limit + 1800, "cpus": cpus}


def build(job: dict, out: Path) -> dict:
    setup(job["bone_model"])
    spec = spec_of(job["point"], job.get("settings") or {})
    where, state = _prep(job, spec)
    if state != "READY":
        failed = json.loads((where / "FAILED.json").read_text(encoding="utf-8"))
        status = BUILD_STATUS.get(failed.get("klass"), "error")
        return {"status": status, "reason": f"{failed.get('code')}: {failed.get('reason', '')[:600]}", "pre": {}}
    prep = json.loads((where / "prep.json").read_text(encoding="utf-8"))
    placed, loss = prep["templating"], prep["bone_loss"]
    tets, attempt = prep.get("n_tet"), prep.get("mesh_attempt") or {}
    pre = {"e_mm": placed["e"], "A0_mm2": placed["A0"], "alpha_placed_deg": placed["alpha"], "contact_templated": placed["contact"],
           "bone_resected_mm3": loss["resected_mm3"], "bone_reamed_mm3": loss["reamed_mm3"], "bone_total_mm3": loss["total_mm3"],
           "n_tet": sum(tets.values()) if isinstance(tets, dict) else tets, "n_pairs": prep.get("n_pairs"),
           "mesh_attempt": 1 + len(attempt.get("previous_errors") or []), "h_mesh_mm": attempt.get("h_int")}
    return {"status": "built", "reason": "", "pre": pre, "solve": _solve_command(job, "m_fric"), "code_hash": prep.get("code_hash")}


def bench(job: dict, out: Path) -> dict:
    """Lamé 压配对照。设计项：h（网格）、delta、mu；别的用旧代码的默认值。"""
    setup(job["bone_model"])
    spec = {"kind": "bench", "femur_id": BONE_ID, "neck_axis": "isthmus", "stage": "sl", "tag": "lame",
            **{key: job["point"]["design"][key] for key in ("h", "delta", "mu", "slip_tol") if key in job["point"]["design"]}}
    where, state = _prep(job, spec)
    if state != "READY":
        failed = json.loads((where / "FAILED.json").read_text(encoding="utf-8"))
        return {"status": "error", "reason": f"{failed.get('code')}: {failed.get('reason', '')[:600]}", "pre": {}}
    return {"status": "built", "reason": "", "pre": {}, "solve": _solve_command(job, "lame_fric")}


def post(job: dict, out: Path) -> dict:
    where = Path(job["job"])
    spec = json.loads((where / "spec.json").read_text(encoding="utf-8"))
    unit = "lame_fric" if spec["kind"] == "bench" else "m_fric"
    keep = _keep(where, unit)
    solved = json.loads((where / "solve.json").read_text(encoding="utf-8")).get(unit) if (where / "solve.json").exists() else None
    if solved is None:
        return {"status": "env", "reason": "求解的进程没有留下 solve.json：多半是被外面结束了", "keep": keep,
                "steps": {"done": 0, "total": len(STEPS) + 1}}
    if solved.get("status") != "OK":
        return dict(_not_solved(job, where, unit, solved), keep=keep)

    setup(job["bone_model"])
    import jobs as J
    import post_m1 as PM1

    J.QROOT, J.RESULTS = where.parent, where / "legacy-results"
    if spec["kind"] == "bench":
        return {"status": "ok", "reason": "", "labels": {key: value for key, value in PM1.lame(where).items()
                                                         if isinstance(value, (int, float))},
                "fields": {}, "keep": keep, "steps": {"done": 1, "total": 1}, "solver": _solver(solved)}
    import stability as ST

    labels = {**J.fric_only_result(where, unit), **ST.stability(where, unit)}
    loaded = ST._load(where, unit)
    labels.update(_force_balance(where, unit, loaded))
    labels = {key: (float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None)
              for key, value in labels.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    _interface_field(out / "interface.npz", loaded)
    return {"status": "ok", "reason": "", "labels": labels, "fields": {"interface": "interface.npz"}, "keep": keep,
            "steps": {"done": len(STEPS) + 1, "total": len(STEPS) + 1}, "solver": _solver(solved)}


def _solver(solved: dict) -> dict:
    return {"name": "Abaqus/Standard", "wall_s": solved.get("wall_s"), "tries": solved.get("tries"), "odb": solved.get("odb_meta")}


def _keep(where: Path, unit: str) -> dict:
    """这个作业该留下什么。odb 不留：场已经导出成 CSV 了。"""
    def there(*names):
        return [name for name in names if (where / name).is_file()]

    csv = sorted(path.relative_to(where).as_posix() for folder in where.glob(f"{unit}_csv*") for path in folder.glob("*"))
    return {"mesh": there("mesh3d.npz", "model3d.json"), "fields": csv,
            "process": there(f"{unit}.sta", f"{unit}.msg", f"{unit}.dat", f"{unit}.runner.log", "solve.json", "prep.json", "prep.log"),
            "settings": there(f"{unit}.inp", "spec.json", "keep.json")}


def _not_solved(job: dict, where: Path, unit: str, solved: dict) -> dict:
    """求解没有算完：是环境的事、是不收敛，还是别的。不收敛的再看停下之前柄是不是已经松动。"""
    reason, code = str(solved.get("reason") or ""), solved.get("code")
    done = _steps_done(where, unit)
    said = {"reason": f"{code or 'solver'}: {reason}"[:600], "steps": {"done": done, "total": len(STEPS) + 1}}
    if code == "license_unavailable":
        return dict(said, status="env")
    if "TOO MANY ATTEMPTS" not in reason.upper():
        return dict(said, status="error")
    evidence = _loosened(job, where, unit, done)
    if evidence is None:
        return dict(said, status="not_converged")
    return dict(said, status="unstable", evidence=evidence,
                reason=said["reason"] + f"；停在 {evidence['step']} 步，那时界面相对位移的 95 分位已经是 {evidence['slip_p95_um']:.0f} 微米")


def _steps_done(where: Path, unit: str) -> int:
    """.sta 里走完了几个分析步。"""
    try:
        text = (where / f"{unit}.sta").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    steps = [int(parts[0]) for parts in (line.split() for line in text.splitlines()) if len(parts) > 7 and parts[0].isdigit()]
    return max(steps) - 1 if steps else 0


def _loosened(job: dict, where: Path, unit: str, done: int):
    """不收敛的作业停下之前是不是已经松动。有证据就返回它，没有返回 None。

    证据要三样都成立：压配和释放两步已经算完；停在加载步里；停下前最后一个收敛的增量上，
    柄身界面相对释放后的切向相对位移，面积加权 95 分位已经超过长不上骨的阈值。
    载荷没加满就松到这个程度，加满只会更松，所以这个设计的结论不依赖数值收敛。
    """
    partial = where / f"{unit}_csv_partial"
    if done < 2 or not (partial / "RELEASE_U.csv").exists():
        return None
    last = next((step for step in reversed(STEPS[1:]) if (partial / f"{step}_U.csv").exists()), None)
    if last is None:
        return None
    try:
        setup(job["bone_model"])
        import numpy as np
        import post_m1 as PM1

        pairs = PM1.pairs(where)
        body = ~pairs["pair_collar"]
        moved = [PM1._utab(partial / f"{step}_U.csv", pairs["n"]) for step in ("RELEASE", last)]
        rel = [table[pairs["pair_stem"]] - table[pairs["pair_bone"]] for table in moved]
        change = (rel[1] - rel[0])[body]
        normal = pairs["pair_normal"][body]
        slip = np.linalg.norm(change - (change * normal).sum(1)[:, None] * normal, axis=1) * 1e3
        if not np.isfinite(slip).all():
            return None
        p95 = float(PM1._wq(slip, pairs["pair_area"][body], 0.95))
    except Exception:  # noqa: BLE001  证据算不出来就是没有证据
        return None
    return {"step": last, "slip_p95_um": p95, "line_um": UNSTABLE_UM} if p95 > UNSTABLE_UM else None


def _force_balance(where: Path, unit: str, loaded: dict) -> dict:
    """界面上骨侧接触力之和对外载：相对差。两者平衡，说明载荷加对了、加满了、读的是对的那一帧。"""
    import numpy as np
    import post_m1 as PM1

    load = np.asarray(json.loads((where / "model3d.json").read_text(encoding="utf-8"))["load_N"], float)
    pairs = loaded["p"]
    found = {"load_x_N": float(load[0]), "load_y_N": float(load[1]), "load_z_N": float(load[2])}
    for step in ("LOAD", "LOAD2"):
        table = where / f"{unit}_csv" / f"{step}_CFORCE.csv"
        if table.exists():
            total = PM1._ftab(table, pairs["n"])[pairs["pair_bone"]].sum(0)
            found[f"iface_force_err_{step.lower()}"] = float(np.linalg.norm(total - load) / np.linalg.norm(load))
    return found


def _interface_field(path: Path, loaded: dict) -> None:
    """界面的点云：每个界面节点对的位置、法向、面积、过盈、四个分析步的相对位移，和它到髓腔壁的距离。"""
    import numpy as np

    pairs, fm = loaded["p"], loaded["fm"]
    np.savez_compressed(
        path, X=loaded["X"], normal=pairs["pair_normal"], area=pairs["pair_area"], interference=pairs["pair_interf"],
        cortex=pairs["pair_cortex"], collar=pairs["pair_collar"], steps=np.array(STEPS),
        rel=np.stack([loaded["rel"][step] for step in STEPS], axis=1), d_canal=fm.canal_sdf(loaded["X"]),
        P0=np.asarray(loaded["P0"], float), stem_axis=np.asarray(loaded["ax"], float),
        e_ml=loaded["e_ml"], e_ap=loaded["e_ap"], head=np.asarray(fm.H, float) if hasattr(fm, "H") else np.zeros(3),
        neck_axis=np.asarray(fm.u3, float), cut_centre=np.asarray(fm.C03, float))


HASHED = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml", "model3d_m1.py", "post_m1.py")


def selfcheck(job: dict, out: Path) -> dict:
    """自检：这个包在这台机器的这个环境里还是不是冻结的那个模型。不用骨模型，几秒钟。

    8 个冻结文件的 code_hash 没变；旧代码导得进来；一根给定的柄，几何算出来还是老数。
    """
    digest = hashlib.sha256()
    for name in HASHED:
        digest.update((LEGACY / "v2" / name).read_bytes())
    os.environ.setdefault("MPLBACKEND", "Agg")
    for folder in (LEGACY, LEGACY / "v2"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    import geom3d as G

    stem = G.Stem3D(**job["design"])
    area = float(job["A0"])
    return {"code_hash": digest.hexdigest()[:10], "volume_mm3": float(stem.volume(area)), "cap_length_mm": float(stem.cap_length(area)),
            "area_ratio_mid": float(stem.area_ratio(0.5 * stem.L)), "area_ratio_tip": float(stem.area_ratio(stem.L))}


MODES = {"template": template, "build": build, "post": post, "bench": bench, "selfcheck": selfcheck}


def main() -> int:
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    try:
        result = MODES[job["mode"]](job, out)
    except Unsupported as error:
        result = {"status": "error", "reason": str(error)}
    except Exception as error:  # noqa: BLE001  旧代码抛的任何错都说出来，不让这个进程带着一串看不懂的东西死掉
        result = {"status": "error", "reason": f"{type(error).__name__}: {error}\n{traceback.format_exc()[-1500:]}"}
    (out / "result.json").write_text(json.dumps(result, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
