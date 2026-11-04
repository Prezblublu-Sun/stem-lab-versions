"""模板化记录包装：入口偏移 e 的逐档 A0 与可用性（3406 数据库规划 2026-10-25 第 1.1 节"入口偏移 e 的跳变"、第 2.2 节 D3）。
不计入作业哈希；不改 collar_rule.py / jobs.py / stage_neckopt.py / femur_3406.py，只在调用期间替换本进程里的几个名字、调完还原。

对一个无领设计（阶段 13 的 13 个设计量 L、α、h_cut、m、ρ_tip、q、λ、γ_ml、γ_ap、n_a、n_p、τ_a、τ_p；股骨 Sawbones 3406）
调用生产选号 collar_rule.template_neck_in_shoulder（neck_in_shoulder + margin_check dense + jobs.a_bounds_cap(2000)，与 jobs.prep、
stage_neckopt._feasible 同一调用、同一股骨路径 jobs.femur_for），同时记下 9 个入口偏移 e = −8…8 mm（步长 2）各自的结果：
    A0_by_e       该偏移下按皮质余量的最大号（mm²，即 template_base 的 A0；template_base 判该偏移不可行时 NaN）
    usable_by_e   该偏移是否通过 neck_in_shoulder 的全部检查（皮质余量可行、号 ≥ max(min_A0, A_BOUNDS[0])、颈底伸出 ≤ tol_mm2）
    code_by_e     0 可用 / 1 blocked / 2 canal larger than largest size / 3 tip too thin / 4 号低于假体颈下限 / 5 颈底伸出 > tol / 9 其他
    overhang_by_e 假体颈底面伸出柄截口的面积（mm²；只在 collar_rule 算过的偏移上有值，其余 NaN）
派生量：
    e_star, A0_star  collar_rule 的选择（直接取它的返回值，不是自己重算的）；不可行 NaN
    e_margin         (A0* − 其余可用偏移里最大的 A0) / A0*。只有一个可用偏移时记 1.0（n_usable 区分）；不可行 NaN。
                     选号的平手规则是"0.5 % 以内取 |e| 小"，所以 e_margin 可以略小于 0（最低约 −0.005），表示另一偏移的号略大
    feasible, reason 与 stage_neckopt._feasible 同口径（fit 且 A0 ≥ min_A0）；reason = "ok" | "no_offset" | "below_min_A0" | "error: …"
    bone_mm3         去骨量 = resected_volume(ref_cut_mm) + 锉骨体积（= jobs.prep 的 bone_loss.total_mm3 = _feasible 的 loss）；不可行 NaN

怎么记：调用期间把 collar_rule 模块里的 template_base、neck_overhang 两个名字换成"原函数 + 记录"（template_neck_in_shoulder 按名字
取它们），调完（含异常）还原。另外用记下的逐偏移结果按同一平手规则重选一次：与 collar_rule 的返回值不一致（选号规则或调用方式改了）
就抛 TplRecordError，不静默。逐偏移的"可用"判定只在一处与 collar_rule 重复：颈底伸出 ≤ tol_mm2（tol 取函数签名的默认值）。

股骨缓存只读：股骨按 jobs.femur_for({"femur_id", "neck_axis"})（= 候选池 stage_neckopt.base_femur 的路径）取，但先确认
cache/femur_3406_<key>.npz 已在（不在就抛 FileNotFoundError，绝不重建）；建对象期间 femur_3406 / femur_real 两个模块里的
np.save / savez / savez_compressed / savetxt 换成抛 CacheWriteRefused 的版本，事后核对 cache 目录（文件名、大小、mtime）前后不变。

批量：单位立方体点表（.npy 或 .csv，N × 13，列序 = stage_neckopt.Phase(phase).vars）→ 一个 npz（只用 numpy；allow_pickle=False 可读）。
多进程用 spawn（各 worker 自己只读加载股骨缓存；--workers 1 = 本进程、不起子进程）；每 --checkpoint 个点原子地写一次部分结果
（done 列标出已算的点），--resume 按 done 续跑（规则、点表必须与已有文件一致）。某个点在流水线里抛异常（例如截口为空）：该行
error = True、reason = "error: …"，结束时汇总打印，命令以退出码 3 结束；TplRecordError / CacheWriteRefused 直接中止整批（先写已完成部分）。
不写进流水线代码目录或作业队列（out 落在那里就拒绝）。

用法
    python v2/tpl_record.py batch --in U.npy --out pool.npz [--workers 4] [--phase 13] [--checkpoint 500] [--resume]
    python v2/tpl_record.py job <作业目录或 id> ... [--queue ~/mobo_toy_v2/queue]   # 与 prep.json 的 templating 逐项对照（只读）
从流水线以外的目录跑（Linux 的临时目录）时设 MOBO_V2_DIR=~/mobo_toy_v2/code/v2（只读导入流水线模块），并设 PYTHONDONTWRITEBYTECODE=1。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import hashlib
import inspect
import json
import math
import multiprocessing as mp
import os
import pathlib
import platform
import socket
import sys
import time
from dataclasses import asdict, dataclass

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
CODE = pathlib.Path(os.environ.get("MOBO_V2_DIR") or HERE).expanduser().resolve()   # 流水线 v2 目录（只读导入）
sys.path.insert(0, str(CODE.parent))
sys.path.insert(0, str(CODE))
import collar_rule as CR  # noqa: E402
import femur_3406 as F6  # noqa: E402
import femur_real as FR  # noqa: E402
import geom3d as G  # noqa: E402
import jobs as J  # noqa: E402
import stage_neckopt as N  # noqa: E402
import stage_v2a as S  # noqa: E402


class TplRecordError(RuntimeError):
    """记录与 collar_rule 的行为对不上（选号规则或调用方式变了）：整批中止，不静默。"""


class CacheWriteRefused(RuntimeError):
    """加载股骨时有代码试图写股骨缓存。"""


_SIG = inspect.signature(CR.template_neck_in_shoulder).parameters
OFFSETS = np.asarray(_SIG["offsets"].default, float).copy()          # 生产选号搜索的入口偏移（mm）
TOL_MM2 = float(_SIG["tol_mm2"].default)                             # 颈底伸出容差（候选池用函数默认值）
if OFFSETS.tolist() != [-8.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]:
    raise TplRecordError(f"collar_rule.template_neck_in_shoulder default offsets changed to {OFFSETS.tolist()}; the 9-column record assumes -8..8 step 2")
if float(inspect.signature(CR.install_neck).parameters["tol_mm2"].default) != TOL_MM2:
    raise TplRecordError("collar_rule.install_neck (jobs.prep) and template_neck_in_shoulder (candidate pool) default tol_mm2 differ")
NE = len(OFFSETS)
CODES = {0: "usable", 1: "blocked", 2: "canal_larger_than_largest_size", 3: "tip_too_thin", 4: "shoulder_below_neck_min",
         5: "neck_base_overhang", 9: "other"}
_TB_REASON = (("blocked", 1), ("canal larger than largest size", 2), ("tip too thin", 3))   # geom3d.template 的失败原因前缀
_ROW = ("feasible", "error", "n_usable", "e_star", "A0_star", "e_margin", "alpha_star", "s_bind_star", "contact_star", "volume_star",
        "resected_mm3", "bone_mm3", "t_s", "done")
_ROW_E = ("A0_by_e", "usable_by_e", "code_by_e", "overhang_by_e")


@dataclass
class Rule:
    """选号设置（= jobs.prep 对 spec、stage_neckopt._feasible 对阶段做的模板化所用的全部参数）。"""
    femur_id: str
    neck_axis: object
    margin_check: str
    a_bounds_max: float | None
    ref_cut_mm: float
    min_A0: float
    margin: float | None = None
    tol_mm2: float = TOL_MM2


_PH: dict = {}


def _phase(phase: int):
    if phase not in _PH:
        _PH[phase] = N.Phase(phase)
    return _PH[phase]


def _check_femur(femur_id) -> None:
    if J.FEMURS.get(femur_id) != "femur_3406":
        raise ValueError(f"tpl_record covers the Sawbones 3406 hook femur only (femur_id 'sawbone3406'), got {femur_id!r}")


def phase_rule(phase: int = 13) -> Rule:
    """阶段 phase 的候选池选号设置（stage_neckopt.Phase.template + _feasible）。只支持无领的 neck_in_shoulder、3406 股骨。"""
    ph = _phase(phase)
    if ph.rule != "neck_in_shoulder" or abs(float(ph.fixed.get("collar_w", 0.0))) > 0.0:
        raise ValueError(f"phase {phase}: tpl_record wraps collar_rule neck_in_shoulder (collarless) only; phase rule {ph.rule!r}")
    _check_femur(ph.femur_id)
    return Rule(ph.femur_id, ph.neck_axis, ph.margin_check, ph.a_bounds_max, float(ph.ref_cut_mm), float(S.MIN_A0))


def spec_rule(spec: dict) -> Rule:
    """作业 spec 在 jobs.prep 里的选号设置。不支持的情形（别的领规则、外部柄、带领）直接报错。"""
    if spec.get("kind") not in ("design", "variant"):
        raise ValueError(f"spec kind {spec.get('kind')!r} has no templating")
    if spec.get("collar_rule") != "neck_in_shoulder":
        raise NotImplementedError(f"tpl_record wraps collar_rule neck_in_shoulder only; spec collar_rule {spec.get('collar_rule')!r}")
    if spec.get("import_stem"):
        raise NotImplementedError("import_stem specs are templated by import_stem.py, not wrapped here")
    _check_femur(spec.get("femur_id"))
    tol = float(inspect.signature(CR.install_neck).parameters["tol_mm2"].default)
    return Rule(spec["femur_id"], spec.get("neck_axis"), spec.get("margin_check") or "sparse",
                None if spec.get("a_bounds_max") is None else float(spec["a_bounds_max"]),
                float(spec.get("ref_cut_mm", N.REF_CUT_DEFAULT)), float(spec.get("min_A0", 0.0)),
                None if spec.get("margin") is None else float(spec["margin"]), tol)


# ------------------------------------------------------------------------------------------- 股骨（只读缓存）
_WRITERS = ("save", "savez", "savez_compressed", "savetxt")


class _ReadOnlyNumpy:
    """建股骨期间放进 femur_3406 / femur_real 的 np 名字：读照常转给 numpy，np.save* 抛 CacheWriteRefused。"""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def __getattr__(self, name):
        if name in _WRITERS:
            def _refuse(*a, **k):
                raise CacheWriteRefused(f"tpl_record: np.{name} called while loading the femur; the femur cache is never written here")
            return _refuse
        return getattr(object.__getattribute__(self, "_real"), name)


def _cache_listing():
    c = pathlib.Path(F6.CACHE)
    if not c.exists():
        return None
    return sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in c.iterdir())


@contextlib.contextmanager
def no_cache_writes():
    """块内 femur_3406.np / femur_real.np 的写函数抛错；正常退出时 cache 目录必须与进入时相同。"""
    saved = [(m, m.np) for m in (F6, FR)]
    before = _cache_listing()
    for m, _ in saved:
        m.np = _ReadOnlyNumpy(np)
    try:
        yield
    finally:
        for m, v in saved:
            m.np = v
    if _cache_listing() != before:
        raise CacheWriteRefused(f"tpl_record: the femur cache directory {F6.CACHE} changed while loading the femur")


def femur_cache_file(neck_axis=None) -> pathlib.Path:
    """femur_3406.build 会读的缓存文件（键不含颈轴）。"""
    return pathlib.Path(F6.CACHE) / f"femur_3406_{F6._cache_key(F6.load_cfg(neck_axis))}.npz"


_FM: dict = {}


def base_femur(femur_id: str = "sawbone3406", neck_axis=None):
    """未截骨的股骨（进程内按 (femur_id, 颈轴) 缓存）：缓存文件必须已在，加载期间禁止写缓存。
    与候选池一样经 jobs.femur_for → femur_3406.install()：本进程的 geom3d.A_BOUNDS 之后保持 (20, 2000)（同一进程里再做 CT 模板化的调用方要知道）。
    加载期间若别的进程恰好往 cache 目录写文件，目录核对会误报 CacheWriteRefused（报错，不会静默）。"""
    key = (femur_id, N._axis_key(neck_axis))
    if key in _FM:
        return _FM[key]
    _check_femur(femur_id)
    f = femur_cache_file(neck_axis)
    if not f.exists():
        raise FileNotFoundError(f"femur cache {f} is missing; tpl_record never builds or writes the femur cache "
                                "(build it with the pipeline first)")
    with no_cache_writes():
        fm = J.femur_for({"femur_id": femur_id, "neck_axis": neck_axis})     # = stage_neckopt.base_femur（含 femur_3406.install）
    _FM[key] = fm
    return fm


# ------------------------------------------------------------------------------------------- 单个设计
def _call_recorded(st, fm, rule: Rule):
    """调一次 collar_rule.template_neck_in_shoulder，记下每个偏移的 template_base 结果与颈底伸出。返回 (结果, {e: 记录})。"""
    per: dict = {}
    cur = {"e": None}
    tb0, ov0 = CR.template_base, CR.neck_overhang

    def tb(stem, fem, alphas=None, offsets=None, iters=14, margin=None, margin_check=None):
        offs = np.atleast_1d(np.asarray(offsets, float))
        if offs.size != 1:
            raise TplRecordError(f"template_neck_in_shoulder called template_base with {offs.size} offsets at once; the per-offset record needs one")
        e = float(offs[0])
        if e in per:
            raise TplRecordError(f"template_base called twice for offset {e:+g}")
        r = tb0(stem, fem, alphas=alphas, offsets=offsets, iters=iters, margin=margin, margin_check=margin_check)
        per[e] = {"tb": r, "ov": None}
        cur["e"] = e
        return r

    def ov(st_, fm_, A0, pose):
        e = cur["e"]
        if e is None or per[e]["ov"] is not None or not per[e]["tb"].get("fit") or float(A0) != float(per[e]["tb"]["A0"]):
            raise TplRecordError("neck_overhang called out of the expected order (after a fitting template_base, once per offset, at its A0)")
        v = ov0(st_, fm_, A0, pose)
        per[e]["ov"] = float(v)
        return v

    CR.template_base, CR.neck_overhang = tb, ov
    try:
        res = CR.template_neck_in_shoulder(st, fm, offsets=OFFSETS.copy(), margin=rule.margin, min_A0=rule.min_A0,
                                           tol_mm2=rule.tol_mm2, margin_check=rule.margin_check)
    finally:
        CR.template_base, CR.neck_overhang = tb0, ov0
    return res, per


def _tb_code(reason) -> int:
    s = str(reason or "")
    for prefix, c in _TB_REASON:
        if s.startswith(prefix):
            return c
    return 9


def _derive(res: dict, per: dict, rule: Rule, lo_min: float) -> dict:
    nan = math.nan
    A0, ovh = np.full(NE, nan), np.full(NE, nan)
    sb, ct, vol, al = np.full(NE, nan), np.full(NE, nan), np.full(NE, nan), np.full(NE, nan)
    code = np.full(NE, -1, np.int8)
    why = [None] * NE
    for k, e in enumerate(OFFSETS):
        p = per.get(float(e))
        if p is None:
            raise TplRecordError(f"offset {e:+g} was not evaluated by template_neck_in_shoulder")
        r = p["tb"]
        if not r.get("fit"):
            code[k], why[k] = _tb_code(r.get("reason")), str(r.get("reason"))
            continue
        A0[k], sb[k], ct[k], vol[k], al[k] = r["A0"], r["s_bind"], r["contact"], r["volume"], r["alpha"]
        if p["ov"] is None:                                   # collar_rule 只在号够大时才算颈底伸出
            if not r["A0"] < lo_min:
                raise TplRecordError(f"offset {e:+g}: collar_rule skipped the neck check although A0 {r['A0']:.2f} >= {lo_min:.2f}")
            code[k], why[k] = 4, f"shoulder {r['A0']:.0f} mm2 < {lo_min:.0f} mm2"
        else:
            if r["A0"] < lo_min:
                raise TplRecordError(f"offset {e:+g}: neck checked although A0 {r['A0']:.2f} < {lo_min:.2f}")
            ovh[k] = p["ov"]
            code[k] = 0 if p["ov"] <= rule.tol_mm2 else 5
            why[k] = None if code[k] == 0 else f"neck base overhangs the shoulder by {p['ov']:.1f} mm2"
    usable = code == 0
    best = None                                               # 同一平手规则重选（只作核对）
    for k in np.flatnonzero(usable):
        if best is None or A0[k] > A0[best] * 1.005 or (abs(A0[k] - A0[best]) <= A0[best] * 0.005 and abs(OFFSETS[k]) < abs(OFFSETS[best])):
            best = int(k)
    rec = {"fit": bool(res.get("fit")), "A0_by_e": A0, "usable_by_e": usable, "code_by_e": code, "overhang_by_e": ovh,
           "s_bind_by_e": sb, "contact_by_e": ct, "volume_by_e": vol, "alpha_by_e": al, "reason_by_e": why, "n_usable": int(usable.sum()),
           "e_star": nan, "A0_star": nan, "e_margin": nan, "alpha_star": nan, "s_bind_star": nan, "contact_star": nan,
           "volume_star": nan, "resected_mm3": nan, "bone_mm3": nan, "reason_full": res.get("reason")}
    if res.get("fit"):
        ks = np.flatnonzero(OFFSETS == float(res["e"]))
        if len(ks) != 1 or not usable[ks[0]] or A0[ks[0]] != float(res["A0"]):
            raise TplRecordError(f"collar_rule chose e {res['e']:+g}, A0 {res['A0']:.3f}, which is not a usable recorded offset")
        if best != int(ks[0]):
            raise TplRecordError(f"selection drift: collar_rule chose e {res['e']:+g} but the recorded offsets give e {OFFSETS[best]:+g}")
        k = int(ks[0])
        others = A0[usable & (np.arange(NE) != k)]
        rec.update(e_star=float(res["e"]), A0_star=float(res["A0"]), alpha_star=float(res["alpha"]), s_bind_star=float(res["s_bind"]),
                   contact_star=float(res["contact"]), volume_star=float(res["volume"]),
                   e_margin=float((res["A0"] - others.max()) / res["A0"]) if len(others) else 1.0)
    elif best is not None:
        raise TplRecordError("collar_rule found no usable offset but the record has usable offsets")
    rec["feasible"] = bool(res.get("fit") and res["A0"] >= rule.min_A0)       # = stage_neckopt._feasible
    rec["reason"] = "ok" if rec["feasible"] else ("no_offset" if not res.get("fit") else "below_min_A0")
    return rec


def record_with(st, fm, rule: Rule) -> dict:
    """已建好的柄（geom3d.Stem3D）与已截骨的股骨：记录 + 去骨量。"""
    t0 = time.perf_counter()
    with J.a_bounds_cap(rule.a_bounds_max) as ab:              # 与 jobs.prep、_feasible 同一个上限补丁
        res, per = _call_recorded(st, fm, rule)
        lo_min = max(rule.min_A0, float(G.A_BOUNDS[0]))
    rec = _derive(res, per, rule, lo_min)
    if rec["feasible"]:
        rec["resected_mm3"] = float(fm.resected_volume(ref_cut_mm=rule.ref_cut_mm))
        rec["bone_mm3"] = rec["resected_mm3"] + rec["volume_star"]
    rec["A_BOUNDS_templating"] = [float(x) for x in ab]
    rec["t_s"] = time.perf_counter() - t0
    return rec


def record_design(design: dict, h_cut: float | None, rule: Rule | None = None, cfg: dict | None = None) -> dict:
    """设计（geom3d.Stem3D 的参数，与 spec["design"] 同格式）+ 截骨深度 → 记录。股骨的截骨与配置覆盖同 jobs.femur_for。"""
    rule = phase_rule(13) if rule is None else rule
    fm = base_femur(rule.femur_id, rule.neck_axis)
    if h_cut is not None:
        fm = fm.with_cut(float(h_cut))
    if cfg:
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        J._merge(fm.cfg, cfg)
    st = G.Stem3D(**design)
    if getattr(st, "has_collar", False):
        raise ValueError("tpl_record: neck_in_shoulder is for collarless designs only")
    return record_with(st, fm, rule)


def check_points(U, phase: int = 13) -> np.ndarray:
    U = np.atleast_2d(np.asarray(U, float))
    nv = len(_phase(phase).vars)
    if U.ndim != 2 or U.shape[1] != nv:
        raise ValueError(f"unit-cube points must be N x {nv} (phase {phase} vars {_phase(phase).vars}), got shape {U.shape}")
    if not np.isfinite(U).all() or (U < 0.0).any() or (U > 1.0).any():
        raise ValueError("unit-cube points must be finite and inside [0, 1] (not clipped here)")
    return U


def physical(u, phase: int = 13) -> np.ndarray:
    ph = _phase(phase)
    d, h = ph.design_of(u)
    return np.array([h if k == "h_cut" else d[k] for k in ph.vars], float)


def record_u(u, phase: int = 13) -> dict:
    """单位立方体点（列序 = Phase(phase).vars）→ 记录（设计换算用 stage_neckopt.Phase.design_of，与候选池、spec_of 相同）。"""
    u = check_points(u, phase)[0]
    d, h = _phase(phase).design_of(u)
    rec = record_design(d, h, phase_rule(phase))
    rec["x13"] = physical(u, phase)
    return rec


def record_spec(spec: dict) -> dict:
    """作业 spec → 记录 + prep_view（jobs.prep 对这个 spec 会写进 prep.json 的 templating 与 bone_loss.total_mm3）。"""
    rec = record_design(spec["design"], spec.get("h_cut"), spec_rule(spec), spec.get("cfg"))
    fe = spec.get("entry_offset")
    if fe is None:
        v = {"fit": rec["feasible"], "e": rec["e_star"], "alpha": rec["alpha_star"], "A0": rec["A0_star"], "s_bind": rec["s_bind_star"],
             "contact": rec["contact_star"], "volume": rec["volume_star"], "bone_total_mm3": rec["bone_mm3"]}
    else:                                                    # jobs.prep 把偏移固定为 entry_offset：= 记录里该偏移那一档
        ks = np.flatnonzero(OFFSETS == float(fe))
        if len(ks) != 1:
            raise NotImplementedError(f"entry_offset {fe} is not one of the recorded offsets {OFFSETS.tolist()}")
        k = int(ks[0])
        ok = bool(rec["usable_by_e"][k] and rec["A0_by_e"][k] >= spec_rule(spec).min_A0)
        nan = math.nan
        v = {"fit": ok, "e": float(fe) if ok else nan, "alpha": float(rec["alpha_by_e"][k]) if ok else nan,
             "A0": float(rec["A0_by_e"][k]) if ok else nan, "s_bind": float(rec["s_bind_by_e"][k]) if ok else nan,
             "contact": float(rec["contact_by_e"][k]) if ok else nan, "volume": float(rec["volume_by_e"][k]) if ok else nan,
             "bone_total_mm3": rec["resected_mm3"] + float(rec["volume_by_e"][k]) if ok else nan}
    rec["prep_view"] = v
    return rec


def _sdiff(a, b) -> float:
    """|a − b| / max(|b|, 1)：大量按相对、接近 0 的量（接触比例、s_bind = 0）按绝对。"""
    if a is None or b is None:
        return math.inf
    a, b = float(a), float(b)
    if math.isnan(a) and math.isnan(b):
        return 0.0
    return abs(a - b) / max(abs(b), 1.0)


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return _jsonable(x.tolist())
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(float(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def compare_job(job, queue=None, tol: float = 1e-9) -> dict:
    """作业目录（或队列里的作业 id）：按 spec 重做记录，与 prep.json 的 templating、bone_loss 逐项对照（只读）。
    match True / False；None = 没有可对照的 prep.json（如建模在模板化之后失败，此时 expect_feasible = True）。"""
    d = pathlib.Path(str(job))
    if not (d / "spec.json").exists():
        d = pathlib.Path(queue or J.QROOT).expanduser() / str(job)
    spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
    rec = record_spec(spec)
    out = {"job": d.name, "feasible": rec["feasible"], "reason": rec["reason"], "e_star": rec["e_star"], "A0_star": rec["A0_star"],
           "e_margin": rec["e_margin"], "n_usable": rec["n_usable"], "A0_by_e": rec["A0_by_e"], "code_by_e": rec["code_by_e"],
           "t_s": rec["t_s"], "prep_view": rec["prep_view"], "prep": None, "sdiff": None, "match": None, "expect_feasible": None}
    pj, fj = d / "prep.json", d / "FAILED.json"
    if not pj.exists():
        if fj.exists():
            fr = json.loads(fj.read_text(encoding="utf-8"))
            out["failed"] = str(fr.get("reason", ""))[:160]
            if fr.get("stage") == "prep":
                out["expect_feasible"] = not str(fr.get("reason", "")).startswith(("templating:", "shoulder "))
        return _jsonable(out)
    prep = json.loads(pj.read_text(encoding="utf-8"))
    t = prep.get("templating")
    if not t:
        return _jsonable(out)
    ref = {"e": t["e"], "alpha": t["alpha"], "A0": t["A0"], "s_bind": t["s_bind"], "contact": t["contact"], "volume": t["volume"],
           "bone_total_mm3": (prep.get("bone_loss") or {}).get("total_mm3"), "A_BOUNDS_templating": prep.get("A_BOUNDS_templating")}
    pv = rec["prep_view"]
    sd = {k: _sdiff(pv[k], ref[k]) for k in ("alpha", "A0", "s_bind", "contact", "volume", "bone_total_mm3")}
    out.update(prep=ref, sdiff=sd, match=bool(pv["fit"] and pv["e"] == ref["e"] and max(sd.values()) <= tol
                                              and (ref["A_BOUNDS_templating"] in (None, rec["A_BOUNDS_templating"]))))
    return _jsonable(out)


# ------------------------------------------------------------------------------------------- 批量
def _md5(p: pathlib.Path) -> str:
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


def provenance(rule: Rule) -> dict:
    cfg = F6.load_cfg(rule.neck_axis)["femur"]
    aux = {f: _md5(CODE / f) for f in ("collar_rule.py", "femur_3406.py", "jobs.py", "stage_neckopt.py", "stage_v2a.py")}
    aux["tpl_record.py"] = _md5(pathlib.Path(__file__))
    return {"code_hash": J.code_hash(), "aux_md5": aux, "code_dir": str(CODE), "femur_cache": femur_cache_file(rule.neck_axis).name,
            "step_sha256": {"cortical": cfg.get("sha256_cortical"), "cancellous": cfg.get("sha256_cancellous")},
            "host": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version(), "numpy": np.__version__}


def _empty(n: int) -> dict:
    A = {"A0_by_e": np.full((n, NE), np.nan), "usable_by_e": np.zeros((n, NE), bool), "code_by_e": np.full((n, NE), -1, np.int8),
         "overhang_by_e": np.full((n, NE), np.nan), "feasible": np.zeros(n, bool), "error": np.zeros(n, bool),
         "n_usable": np.zeros(n, np.int8), "done": np.zeros(n, bool)}
    for k in _ROW:
        if k not in A:
            A[k] = np.full(n, np.nan)
    return A


def _compact(rec: dict) -> dict:
    return {**{k: rec[k] for k in _ROW_E}, **{k: rec[k] for k in _ROW if k not in ("error", "done")}, "reason": rec["reason"],
            "other": [w for c, w in zip(rec["code_by_e"], rec["reason_by_e"]) if c == 9]}


_W: dict = {}


def _init_worker(phase: int) -> None:
    _W["phase"] = phase
    r = phase_rule(phase)
    base_femur(r.femur_id, r.neck_axis)


def _task(item):
    i, u = item
    try:
        rec = record_u(u, _W["phase"])
    except (TplRecordError, CacheWriteRefused):
        raise
    except Exception as e:                                   # noqa: BLE001 —— 记成 error 行、汇总打印、退出码 3（不静默）
        return i, {"error": f"error: {type(e).__name__}: {e}"[:300]}
    return i, _compact(rec)


def _inside(p: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(pathlib.Path(root).expanduser().resolve())
        return True
    except ValueError:
        return False


def _save(out: pathlib.Path, U, X, A, reason, meta) -> None:
    meta = {**meta, "n_done": int(A["done"].sum()), "complete": bool(A["done"].all()), "errors": int(A["error"].sum()),
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    arrays = {"u13": U, "x13": X, "var_names": np.array(meta["var_names"]), "offsets": OFFSETS, "reason": np.array(reason, dtype=str),
              **A, "meta_json": np.array(json.dumps(_jsonable(meta)))}
    tmp = out.with_name(out.name + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, **arrays)
    os.replace(tmp, out)


def load(path) -> dict:
    """读 batch 写的 npz（allow_pickle=False）；meta 解析成 dict。"""
    with np.load(path, allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["meta"] = json.loads(str(d.pop("meta_json")))
    return d


def batch(U, out, phase: int = 13, workers: int = 4, checkpoint: int = 500, resume: bool = False, chunksize: int = 4,
          input_info: dict | None = None, quiet: bool = False) -> dict:
    """单位立方体点表 → npz（字段见模块说明）。返回汇总 dict。"""
    U = check_points(U, phase)
    out = pathlib.Path(out).expanduser()
    for root in (CODE, J.QROOT):
        if _inside(out, root):
            raise ValueError(f"refusing to write {out} inside {root}")
    n, rule = len(U), phase_rule(phase)
    X = np.array([physical(u, phase) for u in U])
    meta = {"tool": "tpl_record", "format": 1, "phase": phase, "rule": asdict(rule), "var_names": list(_phase(phase).vars),
            "offsets": OFFSETS.tolist(), "codes": CODES, "n": n, "workers": int(workers), "input": input_info,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "provenance": provenance(rule), "other_reasons": []}
    A, reason = _empty(n), [""] * n
    if resume and out.exists():
        old = load(out)
        if old["meta"].get("rule") != _jsonable(asdict(rule)) or old["meta"].get("phase") != phase or not np.array_equal(old["u13"], U):
            raise ValueError(f"--resume: {out} was written for another rule / phase / point list")
        for k in A:
            A[k] = old[k].astype(A[k].dtype)
        reason = [str(s) for s in old["reason"]]
        meta["started_utc"], meta["other_reasons"] = old["meta"].get("started_utc"), old["meta"].get("other_reasons", [])
    todo = [i for i in range(n) if not A["done"][i]]
    out.parent.mkdir(parents=True, exist_ok=True)
    t0, n_new, last = time.time(), 0, 0

    def put(i, r):
        if "error" in r:
            A["error"][i], A["feasible"][i], reason[i] = True, False, r["error"]
            print(f"[tpl_record] point {i}: {r['error']}", file=sys.stderr, flush=True)
        else:
            for k, v in r.items():
                if k == "reason":
                    reason[i] = v
                elif k == "other":
                    for w in v:
                        if w not in meta["other_reasons"] and len(meta["other_reasons"]) < 50:
                            meta["other_reasons"].append(w)
                else:
                    A[k][i] = v
        A["done"][i] = True

    try:
        if workers <= 1:
            _init_worker(phase)
            results = (_task((i, U[i])) for i in todo)
            pool = None
        else:
            pool = mp.get_context("spawn").Pool(int(workers), initializer=_init_worker, initargs=(phase,))
            results = pool.imap_unordered(_task, [(i, U[i]) for i in todo], chunksize=max(1, int(chunksize)))
        clean = False
        try:
            for i, r in results:
                put(i, r)
                n_new += 1
                if checkpoint and n_new - last >= checkpoint:
                    last = n_new
                    _save(out, U, X, A, reason, {**meta, "wall_s_this_run": time.time() - t0, "n_computed_this_run": n_new})
                    if not quiet:
                        print(f"[tpl_record] {int(A['done'].sum())}/{n} done, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)
            clean = True
        finally:
            if pool is not None:
                (pool.close if clean else pool.terminate)()      # 出错 / 中断时立即停掉 worker
                pool.join()
    except BaseException:
        _save(out, U, X, A, reason, {**meta, "wall_s_this_run": time.time() - t0, "n_computed_this_run": n_new, "aborted": True})
        raise
    wall = time.time() - t0
    _save(out, U, X, A, reason, {**meta, "wall_s_this_run": wall, "n_computed_this_run": n_new})
    ok = A["done"] & ~A["error"]
    summ = {"out": str(out), "n": n, "computed_this_run": n_new, "wall_s": round(wall, 2), "workers": int(workers),
            "feasible": int(A["feasible"].sum()), "errors": int(A["error"].sum()), "other_code_points": int((A["code_by_e"] == 9).any(1).sum()),
            "t_s_mean": float(np.nanmean(A["t_s"][ok])) if ok.any() else None,
            "t_s_median": float(np.nanmedian(A["t_s"][ok])) if ok.any() else None,
            "e_star_counts": {f"{e:+g}": int((A["e_star"] == e).sum()) for e in OFFSETS}}
    if not quiet:
        print(f"[tpl_record] {json.dumps(summ)}", file=sys.stderr, flush=True)
    return summ


def read_points(path, phase: int = 13) -> tuple[np.ndarray, dict]:
    """.npy（N × 13）或 .csv（13 列；可带表头 = 变量名或 u_变量名）。返回 (点表, 输入描述)。"""
    p = pathlib.Path(path).expanduser()
    names = list(_phase(phase).vars)
    if p.suffix == ".npy":
        U = np.load(p, allow_pickle=False)
    elif p.suffix == ".csv":
        with open(p, newline="", encoding="utf-8") as fh:
            rows = [r for r in csv.reader(fh) if r]
        try:
            float(rows[0][0])
        except ValueError:
            head = [c.strip() for c in rows[0]]
            if head not in (names, [f"u_{v}" for v in names]):
                raise ValueError(f"{p}: header {head} does not match phase {phase} vars {names}")
            rows = rows[1:]
        U = np.array([[float(c) for c in r] for r in rows], float)
    else:
        raise ValueError(f"{p}: use .npy or .csv")
    return check_points(U, phase), {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A0(e) templating record (3406, collar_rule neck_in_shoulder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("batch", help="unit-cube point list -> npz")
    b.add_argument("--in", dest="inp", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--phase", type=int, default=13)
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--checkpoint", type=int, default=500)
    b.add_argument("--chunksize", type=int, default=4)
    b.add_argument("--resume", action="store_true")
    j = sub.add_parser("job", help="compare with prep.json (read-only)")
    j.add_argument("jobs", nargs="+")
    j.add_argument("--queue", default=None)
    a = ap.parse_args(argv)
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(k, "1")                        # spawn 的 worker 单线程
    if a.cmd == "batch":
        U, info = read_points(a.inp, a.phase)
        s = batch(U, a.out, a.phase, a.workers, a.checkpoint, a.resume, a.chunksize, input_info=info)
        print(json.dumps(s))
        return 3 if s["errors"] else 0
    bad = 0
    for jb in a.jobs:
        r = compare_job(jb, a.queue)
        print(json.dumps(r), flush=True)
        bad += r["match"] is False
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
