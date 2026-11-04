"""模板化记录包装：入口偏移 e 的逐档 A0 与可用性（3406 数据库规划 2026-10-25 第 1.1 节"入口偏移 e 的跳变"、第 2.2 节 D3）。
不计入作业哈希；不改 collar_rule.py / jobs.py / stage_neckopt.py / femur_3406.py，只在调用期间替换本进程里的几个名字、调完还原。

对一个无领设计（阶段 13 的 13 个设计量 L、α、h_cut、m、ρ_tip、q、λ、γ_ml、γ_ap、n_a、n_p、τ_a、τ_p；股骨 Sawbones 3406）
调用生产选号 collar_rule.template_neck_in_shoulder（neck_in_shoulder + margin_check dense + jobs.a_bounds_cap(2000)，与 jobs.prep、
stage_neckopt._feasible 同一调用、同一股骨路径 jobs.femur_for），同时记下 9 个入口偏移 e = −8…8 mm（步长 2）各自的结果：
    A0_by_e       该偏移下按皮质余量的最大号（mm²，即 template_base 的 A0；template_base 判该偏移不可行时 NaN，含 tip too thin）
    usable_by_e   该偏移是否通过 neck_in_shoulder 的全部检查（皮质余量可行、号 ≥ max(min_A0, A_BOUNDS[0])、颈底伸出 ≤ tol_mm2）
    code_by_e     0 可用 / 1 blocked / 2 canal larger than largest size / 3 tip too thin / 4 号低于假体颈下限 / 5 颈底伸出 > tol / 9 其他
    overhang_by_e 假体颈底面伸出柄截口的面积（mm²；只在 collar_rule 算过的偏移上有值，其余 NaN）
派生量（tol = tol_mm2 = 2 mm²；OV_NEAR_MM2 = 3 mm²；"code-5 偏移" = 只因颈底伸出 > tol 被挡掉的偏移，它们都有 A0_by_e 和伸出值）：
    e_star, A0_star  collar_rule 的选择（直接取它的返回值，不是自己重算的）；不可行 NaN
    e_margin         (A0* − 其余可用偏移里最大的 A0) / A0*。只有一个可用偏移时记 1.0（n_usable 区分）；不可行 NaN。
                     选号的平手规则是"0.5 % 以内取 |e| 小"，所以 e_margin 可以略小于 0（最低约 −0.005），表示另一偏移的号略大
    ov_slack_star    tol − 颈底伸出(e*)（mm²，≥ 0）：所选偏移离被颈底规则挡掉还差多少（小 = e* 本身快要被挡掉）；不可行 NaN
    ov_gap_up        在 A0_by_e > A0* 的 code-5 偏移上取 min(伸出 − tol)（mm²，> 0）：颈底规则只要放宽这么多，选择就会跳到一个
                     更大的号；没有这样的偏移（或不可行）NaN
    A0_up_rel        同一组偏移（code 5 且 A0_by_e > A0*）上 (max A0_by_e − A0*) / A0*（> 0）：被颈底规则挡掉的最大号比 A0* 大多少；没有 NaN
    e_margin_eff     min(e_margin, (A0* − A0_near) / A0*)，A0_near = 伸出 − tol ≤ OV_NEAR_MM2 的 code-5 偏移里最大的 A0_by_e
                     （不论比 A0* 大还是小）。即把"差不到 3 mm² 就可用"的偏移也当成对手；没有这样的偏移时 = e_margin（含 1.0 的约定）。
                     可以是负数。现有作业的例子：sb14_a60_46532259 只有 e 0 可用，e_margin = 1.0；但 e* 本身只余 0.017 mm²
                     （ov_slack_star），另一个偏移只多伸出 0.16 mm²（ov_gap_up）、号大 5.6 %（A0_up_rel），e_margin_eff = −0.056。
                     e_margin 只看完全可用的偏移，会把这种跳变记成 1.0（"没有对手"），所以 BD（边界 / 跳变）层按 e_margin_eff 小来选，
                     e_margin 照旧保留。不可行 NaN
    feasible, reason 与 stage_neckopt._feasible 同口径（fit 且 A0 ≥ min_A0）；reason = "ok" | "no_offset" | "below_min_A0" | "error: …"。
                     min_A0 已传进 template_neck_in_shoulder（它先按 min_A0 过滤），所以 "below_min_A0" 现在不会出现，只作防线
    bone_mm3         去骨量 = resected_volume(ref_cut_mm) + 锉骨体积（= jobs.prep 的 bone_loss.total_mm3 = _feasible 的 loss）；不可行 NaN

怎么记：调用期间把 collar_rule 模块里的 template_base、neck_overhang 两个名字换成"原函数 + 记录"（template_neck_in_shoulder 按名字
取它们），调完（含异常）还原。另外用记下的逐偏移结果按同一平手规则重选一次：与 collar_rule 的返回值不一致（选号规则或调用方式改了）
就抛 TplRecordError，不静默。逐偏移的"可用"判定只在一处与 collar_rule 重复：颈底伸出 ≤ tol_mm2（tol 取函数签名的默认值）。

股骨缓存只读：股骨按 jobs.femur_for({"femur_id", "neck_axis"})（= 候选池 stage_neckopt.base_femur 的路径）取，但先确认
cache/femur_3406_<key>.npz 已在（不在就抛 FileNotFoundError，绝不重建）；建对象期间 femur_3406 / femur_real 两个模块里的
np.save / savez / savez_compressed / savetxt 换成抛 CacheWriteRefused 的版本，事后核对 cache 目录（文件名、大小、mtime）前后不变。

来源（npz 的 meta.provenance）：code_hash（8 个哈希文件）、aux_md5（实际导入的 collar_rule.py、femur_3406.py、jobs.py、stage_neckopt.py、
stage_v2a.py 与 tpl_record.py 自己）、femur_geom_key、step_sha256（femur_3406 声明的两个 STEP 的 SHA256）、step_file_sha256（本机
STEP 文件的实际 SHA256；文件不在时 None 并在 stderr 说明，在而不符就报错）、femur_cache / femur_cache_sha256（本机读的缓存文件名
与内容哈希）。femur_geom_key 与主机无关 = sha256(femur_3406.py 字节 + 两个 STEP 的声明 SHA256 + json(cfg["femur"] 去掉 step_* 路径
与 neck_axis，sort_keys))的前 16 位十六进制；剩下的 cfg 里若还有像路径的字符串就报错（否则键又会随主机变）。femur_cache 的名字是
femur_3406._cache_key，它哈希了 STEP 的绝对路径，所以两台机器不同（305416778b / 521f28cddd），只作本机信息。host、platform、
python、numpy、code_dir、线程设置、缓存文件大小与 mtime 也只作本机信息。

批量：单位立方体点表（.npy 或 .csv，N × 13，列序 = stage_neckopt.Phase(phase).vars）→ 一个 npz（只用 numpy；allow_pickle=False 可读）。
开算前先在本进程里加载一次股骨（= worker 的初始化）：缓存缺失、CacheWriteRefused 在起任何子进程之前就报错。--workers 1 = 本进程算、
不起子进程；--workers ≥ 2 = concurrent.futures.ProcessPoolExecutor（spawn，各 worker 自己只读加载股骨缓存，点按 --chunksize 分块提交，
在途块数 ≤ 4 × workers）。worker 的初始化失败或进程死掉（如内存不足被杀）→ BrokenProcessPool：先把已完成的行写进 out（aborted = True），
再抛 BrokenProcessPool 并说明原因（不会挂住）。每 --checkpoint 个点原子地写一次部分结果（done 列标出已算的点）。
--resume 按 done 续跑，但下面任何一项与已有文件不同就拒绝（ValueError，列出不同的键，不算任何点、不改文件）：格式版本、阶段、规则、
OV_NEAR_MM2、点表，以及来源里的 code_hash、每个 aux_md5、femur_geom_key、femur_cache、femur_cache_sha256、step_sha256、
step_file_sha256（所以别的机器写的部分文件不能续，换个 --out 重算）。某个点在流水线里抛异常（例如截口为空）：该行 error = True、
reason = "error: …"，结束时汇总打印，命令以退出码 3 结束；TplRecordError / CacheWriteRefused 直接中止整批（先写已完成部分；
多进程时其余在算的块算完也写进去）。不写进流水线代码目录或作业队列（out 落在那里就拒绝）。
线程：命令行运行时在 import numpy 之前把 OMP / OPENBLAS / MKL_NUM_THREADS 默认设为 1（--workers 1 的本进程路径因此单线程）；
batch() 起 worker 之前也 setdefault 这三个变量（spawn 的 worker 继承）。作为库调用、workers = 1 时线程数由调用方的环境决定，
meta.provenance 记下 threads_env 与（装了 threadpoolctl 时）实际的 BLAS 线程数。

用法
    python v2/tpl_record.py batch --in U.npy --out pool.npz [--workers 4] [--phase 13] [--checkpoint 500] [--chunksize 4] [--resume]
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
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass

_THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
if __name__ == "__main__":                                   # 命令行：numpy 导入之前定单线程（本进程路径；spawn 的 worker 继承）
    for _k in _THREAD_ENV:
        os.environ.setdefault(_k, "1")

import numpy as np  # noqa: E402

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


FORMAT = 2                                                   # npz 格式：2 = 加了 ov_* / e_margin_eff 列、femur_geom_key、续跑来源核对
OV_NEAR_MM2 = 3.0                                            # e_margin_eff：伸出比 tol 多不到这么多（mm²）的 code-5 偏移算对手
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
_ROW = ("feasible", "error", "n_usable", "e_star", "A0_star", "e_margin", "ov_slack_star", "ov_gap_up", "A0_up_rel", "e_margin_eff",
        "alpha_star", "s_bind_star", "contact_star", "volume_star", "resected_mm3", "bone_mm3", "t_s", "done")
_ROW_E = ("A0_by_e", "usable_by_e", "code_by_e", "overhang_by_e")
_AUX_MODULES = (("collar_rule.py", CR), ("femur_3406.py", F6), ("jobs.py", J), ("stage_neckopt.py", N), ("stage_v2a.py", S))
_STEP_KEYS = ("cortical", "cancellous")
# 续跑时必须相同的来源键（其余 provenance 键只是本机信息：code_dir、host、platform、python、numpy、缓存文件大小 / mtime、线程设置）
PROVENANCE_COMPARED = ("code_hash", "aux_md5", "femur_geom_key", "femur_cache", "femur_cache_sha256", "step_sha256", "step_file_sha256")


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


def _femur_key(femur_id, neck_axis) -> tuple:
    return femur_id, N._axis_key(neck_axis)


def base_femur(femur_id: str = "sawbone3406", neck_axis=None):
    """未截骨的股骨（进程内按 (femur_id, 颈轴) 缓存）：缓存文件必须已在，加载期间禁止写缓存。
    与候选池一样经 jobs.femur_for → femur_3406.install()：本进程的 geom3d.A_BOUNDS 之后保持 (20, 2000)（同一进程里再做 CT 模板化的调用方要知道）。
    加载期间若别的进程恰好往 cache 目录写文件，目录核对会误报 CacheWriteRefused（报错，不会静默）。"""
    key = _femur_key(femur_id, neck_axis)
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


def overhang_aware(A0, code, ovh, k: int, e_margin: float, tol: float, near: float = OV_NEAR_MM2) -> dict:
    """e* = 第 k 档时的 ov_slack_star、ov_gap_up、A0_up_rel、e_margin_eff（定义见模块说明）。A0 / code / ovh 是 9 档数组。"""
    nan = math.nan
    A0, code, ovh = np.asarray(A0, float), np.asarray(code), np.asarray(ovh, float)
    A0s = float(A0[k])
    blocked = code == 5                                       # 只被颈底规则挡掉（都有 A0 与伸出值）
    if np.isnan(A0[blocked]).any() or np.isnan(ovh[blocked]).any() or not np.isfinite(ovh[k]):
        raise TplRecordError("overhang-aware columns: a code-5 offset without A0 / overhang, or e* without an overhang value")
    up = blocked & (A0 > A0s)
    nr = blocked & (ovh - tol <= near)
    gap_near = float((A0s - A0[nr].max()) / A0s) if nr.any() else nan
    return {"ov_slack_star": float(tol - ovh[k]),
            "ov_gap_up": float((ovh[up] - tol).min()) if up.any() else nan,
            "A0_up_rel": float((A0[up].max() - A0s) / A0s) if up.any() else nan,
            "e_margin_eff": float(min(e_margin, gap_near)) if nr.any() else float(e_margin)}


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
           "e_star": nan, "A0_star": nan, "e_margin": nan, "ov_slack_star": nan, "ov_gap_up": nan, "A0_up_rel": nan, "e_margin_eff": nan,
           "alpha_star": nan, "s_bind_star": nan, "contact_star": nan, "volume_star": nan, "resected_mm3": nan, "bone_mm3": nan,
           "reason_full": res.get("reason")}
    if res.get("fit"):
        ks = np.flatnonzero(OFFSETS == float(res["e"]))
        if len(ks) != 1 or not usable[ks[0]] or A0[ks[0]] != float(res["A0"]):
            raise TplRecordError(f"collar_rule chose e {res['e']:+g}, A0 {res['A0']:.3f}, which is not a usable recorded offset")
        if best != int(ks[0]):
            raise TplRecordError(f"selection drift: collar_rule chose e {res['e']:+g} but the recorded offsets give e {OFFSETS[best]:+g}")
        k = int(ks[0])
        others = A0[usable & (np.arange(NE) != k)]
        em = float((res["A0"] - others.max()) / res["A0"]) if len(others) else 1.0
        rec.update(e_star=float(res["e"]), A0_star=float(res["A0"]), alpha_star=float(res["alpha"]), s_bind_star=float(res["s_bind"]),
                   contact_star=float(res["contact"]), volume_star=float(res["volume"]), e_margin=em,
                   **overhang_aware(A0, code, ovh, k, em, rule.tol_mm2))
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


def offgrid_view(spec: dict) -> dict:
    """entry_offset 不在 2 mm 一档：生产选号只在这一个偏移上调一次（jobs.prep 对这个 spec 就是这样调的），返回同 record_spec 的 prep_view，另加 reason。
    记录的 9 列不变，这一档不进记录。"""
    fe = float(spec["entry_offset"])
    rule = spec_rule(spec)
    fm = base_femur(rule.femur_id, rule.neck_axis)
    if spec.get("h_cut") is not None:
        fm = fm.with_cut(float(spec["h_cut"]))
    if spec.get("cfg"):
        fm = copy.copy(fm)
        fm.cfg = copy.deepcopy(fm.cfg)
        J._merge(fm.cfg, spec["cfg"])
    st = G.Stem3D(**spec["design"])
    with J.a_bounds_cap(rule.a_bounds_max):
        r = CR.template_neck_in_shoulder(st, fm, offsets=np.array([fe]), margin=rule.margin, min_A0=rule.min_A0, tol_mm2=rule.tol_mm2, margin_check=rule.margin_check)
    if not r.get("fit"):
        nan = math.nan
        return {"fit": False, "reason": str(r.get("reason")), "e": nan, "alpha": nan, "A0": nan, "s_bind": nan, "contact": nan, "volume": nan, "bone_total_mm3": nan}
    return {"fit": True, "reason": "ok", "e": float(r["e"]), "alpha": float(r["alpha"]), "A0": float(r["A0"]), "s_bind": float(r["s_bind"]), "contact": float(r["contact"]),
            "volume": float(r["volume"]), "bone_total_mm3": float(fm.resected_volume(ref_cut_mm=rule.ref_cut_mm)) + float(r["volume"])}


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


def read_json(p, tries: int = 3, wait_s: float = 0.5):
    """读作业目录里的 json。jobs.prep 用 write_text 直接写 prep.json（不是原子写），正在写的作业可能读到半个文件：
    解析失败时隔 wait_s 秒再读，tries 次都失败就抛（不静默）。"""
    p = pathlib.Path(p)
    for k in range(tries):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if k == tries - 1:
                raise
            time.sleep(wait_s)


def compare_job(job, queue=None, tol: float = 1e-9) -> dict:
    """作业目录（或队列里的作业 id）：按 spec 重做记录，与 prep.json 的 templating、bone_loss 逐项对照（只读）。
    match True / False；None = 没有可对照的 prep.json（如建模在模板化之后失败，此时 expect_feasible = True）。"""
    d = pathlib.Path(str(job))
    if not (d / "spec.json").exists():
        d = pathlib.Path(queue or J.QROOT).expanduser() / str(job)
    spec = read_json(d / "spec.json")
    rec = record_spec(spec)
    out = {"job": d.name, "feasible": rec["feasible"], "reason": rec["reason"], "e_star": rec["e_star"], "A0_star": rec["A0_star"],
           "e_margin": rec["e_margin"], "ov_slack_star": rec["ov_slack_star"], "ov_gap_up": rec["ov_gap_up"], "A0_up_rel": rec["A0_up_rel"],
           "e_margin_eff": rec["e_margin_eff"], "n_usable": rec["n_usable"], "A0_by_e": rec["A0_by_e"], "usable_by_e": rec["usable_by_e"],
           "code_by_e": rec["code_by_e"], "overhang_by_e": rec["overhang_by_e"], "entry_offset": spec.get("entry_offset"),
           "t_s": rec["t_s"], "prep_view": rec["prep_view"], "prep": None, "sdiff": None, "match": None, "expect_feasible": None}
    pj, fj = d / "prep.json", d / "FAILED.json"
    if not pj.exists():
        if fj.exists():
            fr = read_json(fj)
            out["failed"] = str(fr.get("reason", ""))[:160]
            if fr.get("stage") == "prep":
                out["expect_feasible"] = not str(fr.get("reason", "")).startswith(("templating:", "shoulder "))
        return _jsonable(out)
    prep = read_json(pj)
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


# ------------------------------------------------------------------------------------------- 来源
_HASHED: dict = {}


def _sha256_file(p) -> str:
    """文件内容的 SHA256（同一进程里按 (路径, 大小, mtime) 记住，同一个大文件不重复读）。"""
    p = pathlib.Path(p)
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if key not in _HASHED:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        _HASHED[key] = h.hexdigest()
    return _HASHED[key]


def _md5(p: pathlib.Path) -> str:
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


def _path_like(x, pre: str = "") -> list:
    """cfg 里像路径的字符串值（含 / 或 \\）的键名。"""
    if isinstance(x, dict):
        return [p for k, v in x.items() for p in _path_like(v, f"{pre}{k}.")]
    if isinstance(x, (list, tuple)):
        return [p for k, v in enumerate(x) for p in _path_like(v, f"{pre}{k}.")]
    if isinstance(x, str) and ("/" in x or "\\" in x):
        return [pre.rstrip(".")]
    return []


def femur_geom_key(cfg: dict | None = None, src: bytes | None = None) -> str:
    """与主机无关的 3406 股骨几何键：sha256(femur_3406.py 字节 + 声明的 STEP SHA256（cortical、cancellous）
    + json(cfg["femur"] 去掉 step_* 与 neck_axis，sort_keys))的前 16 位十六进制。cfg 默认 femur_3406.load_cfg()，src 默认实际导入的
    femur_3406.py。去掉路径后若还有像路径的字符串值就报错（否则键会随主机变）。"""
    cfg = F6.load_cfg() if cfg is None else cfg
    fc = cfg["femur"]
    sha = [fc.get(f"sha256_{k}") for k in _STEP_KEYS]
    if not all(isinstance(s, str) and len(s) == 64 for s in sha):
        raise ValueError(f"femur cfg must declare sha256_cortical / sha256_cancellous (64 hex), got {sha}")
    rest = {k: v for k, v in fc.items() if not str(k).startswith("step_") and k != "neck_axis"}
    bad = _path_like(rest)
    if bad:
        raise ValueError(f"femur cfg value(s) {bad} look like host paths; femur_geom_key would depend on the host")
    h = hashlib.sha256(pathlib.Path(F6.__file__).read_bytes() if src is None else src)
    for s in sha:
        h.update(s.encode())
    h.update(json.dumps(rest, sort_keys=True, default=float).encode())
    return h.hexdigest()[:16]


def _blas_threads():
    try:
        import threadpoolctl
    except ImportError:
        return None                                          # 没装 threadpoolctl：只记环境变量
    return [{"api": i.get("internal_api"), "num_threads": i.get("num_threads")} for i in threadpoolctl.threadpool_info()]


def provenance(rule: Rule) -> dict:
    """本进程所用代码与股骨的来源（键的含义见模块说明；PROVENANCE_COMPARED 是续跑时必须相同的那些）。"""
    cfg = F6.load_cfg(rule.neck_axis)
    fc = cfg["femur"]
    aux = {f: _md5(pathlib.Path(m.__file__)) for f, m in _AUX_MODULES}
    aux["tpl_record.py"] = _md5(pathlib.Path(__file__))
    step_file = {}
    for k in _STEP_KEYS:
        p = pathlib.Path(fc[f"step_{k}"])
        if not p.exists():
            step_file[k] = None
            print(f"[tpl_record] note: STEP file {p} is not on this host; step_file_sha256.{k} = None "
                  "(femur_geom_key uses the declared sha256)", file=sys.stderr, flush=True)
            continue
        step_file[k] = _sha256_file(p)
        if step_file[k] != fc[f"sha256_{k}"]:
            raise RuntimeError(f"STEP file {p} has sha256 {step_file[k]}, but femur_3406 declares {fc[f'sha256_{k}']} "
                               "(the femur cache was built from the declared file)")
    cf = femur_cache_file(rule.neck_axis)
    st = cf.stat()
    return {"code_hash": J.code_hash(), "aux_md5": aux, "femur_geom_key": femur_geom_key(cfg),
            "step_sha256": {k: fc[f"sha256_{k}"] for k in _STEP_KEYS}, "step_file_sha256": step_file,
            "femur_cache": cf.name, "femur_cache_sha256": _sha256_file(cf), "femur_cache_bytes": int(st.st_size),
            "femur_cache_mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            "code_dir": str(CODE), "host": socket.gethostname(), "platform": platform.platform(), "python": platform.python_version(),
            "numpy": np.__version__, "threads_env": {k: os.environ.get(k) for k in _THREAD_ENV}, "blas_threads": _blas_threads()}


def provenance_diff(old: dict, new: dict) -> list:
    """PROVENANCE_COMPARED 里不同的键（字典键逐项比，如 aux_md5.collar_rule.py），每项 "键: 旧 -> 新"。"""
    old, new, miss = _jsonable(old or {}), _jsonable(new), "<missing>"
    out = []
    for k in PROVENANCE_COMPARED:
        a, b = old.get(k, miss), new.get(k, miss)
        if isinstance(a, dict) and isinstance(b, dict):
            out += [f"{k}.{kk}: {a.get(kk, miss)} -> {b.get(kk, miss)}" for kk in sorted(set(a) | set(b)) if a.get(kk, miss) != b.get(kk, miss)]
        elif a != b:
            out.append(f"{k}: {a} -> {b}")
    return out


# ------------------------------------------------------------------------------------------- 批量
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


def _task_chunk(items):
    return [_task(it) for it in items]


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


def _resume_refusals(old: dict, U, phase: int, rule: Rule, prov: dict, fields) -> list:
    om = old.get("meta") or {}
    why = []
    if om.get("tool") != "tpl_record" or om.get("format") != FORMAT:
        why.append(f"format: {om.get('tool')}/{om.get('format')} -> tpl_record/{FORMAT}")
    if om.get("phase") != phase:
        why.append(f"phase: {om.get('phase')} -> {phase}")
    if om.get("rule") != _jsonable(asdict(rule)):
        why.append(f"rule: {om.get('rule')} -> {_jsonable(asdict(rule))}")
    if om.get("ov_near_mm2") != OV_NEAR_MM2:
        why.append(f"ov_near_mm2: {om.get('ov_near_mm2')} -> {OV_NEAR_MM2}")
    u_old = old.get("u13")
    if u_old is None or u_old.shape != U.shape or not np.array_equal(u_old, U):
        why.append("u13: another point list")
    missing = [k for k in (*fields, "reason") if k not in old]
    if missing:
        why.append(f"fields missing in the old file: {missing}")
    return why + provenance_diff(om.get("provenance"), prov)


def _run_pool(todo, U, phase: int, workers: int, chunksize: int, consume) -> None:
    """ProcessPoolExecutor（spawn）跑 todo；worker 初始化失败或死掉 → BrokenProcessPool（由 f.result() 抛出）。出错时取消未开始的块、
    等在算的块算完，凡是已经算完的块都交给 consume（由调用方存盘），然后把异常抛给调用方。"""
    if not todo:
        return
    for k in _THREAD_ENV:
        os.environ.setdefault(k, "1")                        # spawn 的 worker 继承：单线程
    chunks = [todo[j:j + chunksize] for j in range(0, len(todo), chunksize)]
    window, nxt, pending = 4 * workers, 0, set()
    ex = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"), initializer=_init_worker, initargs=(phase,))
    try:
        while nxt < len(chunks) or pending:
            while nxt < len(chunks) and len(pending) < window:
                pending.add(ex.submit(_task_chunk, [(i, U[i]) for i in chunks[nxt]]))
                nxt += 1
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                rows = f.result()                            # worker 的 TplRecordError / CacheWriteRefused，或 BrokenProcessPool
                pending.discard(f)
                for i, r in rows:
                    consume(i, r)
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        for f in list(pending):                              # 出错时：其它已经算完的块照样记下
            if f.done() and not f.cancelled() and f.exception() is None:
                pending.discard(f)
                for i, r in f.result():
                    consume(i, r)


def batch(U, out, phase: int = 13, workers: int = 4, checkpoint: int = 500, resume: bool = False, chunksize: int = 4,
          input_info: dict | None = None, quiet: bool = False) -> dict:
    """单位立方体点表 → npz（字段见模块说明）。返回汇总 dict。"""
    U = check_points(U, phase)
    out = pathlib.Path(out).expanduser()
    for root in (CODE, J.QROOT):
        if _inside(out, root):
            raise ValueError(f"refusing to write {out} inside {root}")
    workers, chunksize = max(1, int(workers)), max(1, int(chunksize))
    n, rule = len(U), phase_rule(phase)
    key = _femur_key(rule.femur_id, rule.neck_axis)
    had = key in _FM
    _init_worker(phase)                                      # 先在本进程加载一次股骨：缓存缺失 / 写缓存在起 worker 之前就报错
    if workers > 1 and not had:
        _FM.pop(key, None)                                   # 多进程时本进程不算点，放掉这份股骨（约 0.6 GB）
    prov = provenance(rule)
    X = np.array([physical(u, phase) for u in U])
    meta = {"tool": "tpl_record", "format": FORMAT, "phase": phase, "rule": asdict(rule), "ov_near_mm2": OV_NEAR_MM2,
            "var_names": list(_phase(phase).vars), "offsets": OFFSETS.tolist(), "codes": CODES, "n": n, "workers": workers,
            "chunksize": chunksize, "input": input_info, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "provenance": prov, "other_reasons": []}
    A, reason = _empty(n), [""] * n
    if resume and out.exists():
        old = load(out)
        why = _resume_refusals(old, U, phase, rule, prov, A)
        if why:
            raise ValueError(f"--resume refused: {out} was written by another run setup; differing: " + "; ".join(why)
                             + ". Nothing was computed and the file is unchanged; write to a new --out instead.")
        for k in A:
            A[k] = old[k].astype(A[k].dtype)
        reason = [str(s) for s in old["reason"]]
        meta["started_utc"], meta["other_reasons"] = old["meta"].get("started_utc"), old["meta"].get("other_reasons", [])
    todo = [i for i in range(n) if not A["done"][i]]
    out.parent.mkdir(parents=True, exist_ok=True)
    t0, cnt = time.time(), {"new": 0, "last": 0}

    def consume(i, r):
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
        cnt["new"] += 1
        if checkpoint and cnt["new"] - cnt["last"] >= checkpoint:
            cnt["last"] = cnt["new"]
            _save(out, U, X, A, reason, {**meta, "wall_s_this_run": time.time() - t0, "n_computed_this_run": cnt["new"]})
            if not quiet:
                print(f"[tpl_record] {int(A['done'].sum())}/{n} done, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)

    try:
        if workers == 1:
            for i in todo:
                consume(*_task((i, U[i])))
        else:
            _run_pool(todo, U, phase, workers, chunksize, consume)
    except BaseException as e:
        _save(out, U, X, A, reason, {**meta, "wall_s_this_run": time.time() - t0, "n_computed_this_run": cnt["new"], "aborted": True,
                                     "abort_reason": f"{type(e).__name__}: {e}"[:300]})
        if isinstance(e, BrokenProcessPool):
            raise BrokenProcessPool(f"tpl_record batch aborted: a worker process died or its initializer failed ({e}). "
                                    f"{int(A['done'].sum())}/{n} rows are saved in {out} (aborted = True); the worker traceback is "
                                    "printed above (e.g. femur cache missing or unreadable for a worker, CacheWriteRefused, a worker "
                                    "killed for memory). Fix the cause and rerun with --resume.") from e
        raise
    wall = time.time() - t0
    _save(out, U, X, A, reason, {**meta, "wall_s_this_run": wall, "n_computed_this_run": cnt["new"]})
    ok = A["done"] & ~A["error"]
    summ = {"out": str(out), "n": n, "computed_this_run": cnt["new"], "wall_s": round(wall, 2), "workers": workers,
            "feasible": int(A["feasible"].sum()), "errors": int(A["error"].sum()), "other_code_points": int((A["code_by_e"] == 9).any(1).sum()),
            "overhang_jump_points": int(np.isfinite(A["A0_up_rel"]).sum()),
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
