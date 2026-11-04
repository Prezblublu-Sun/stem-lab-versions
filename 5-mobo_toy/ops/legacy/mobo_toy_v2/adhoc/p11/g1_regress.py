"""闸门 G1 回归：并行两臂（来源阶段 = metric v3，目标阶段 = metric v4 + 冻结热启动）启动前，在 Linux 上同步新代码之后只读运行。
阶段对用 --src / --dst 给：默认 11 / 12（与从前相同）；阶段 13 / 14（δ 0.10、微动不作约束）用 --src 13 --dst 14 --expect-delta 0.1。

读（只读）：~/mobo_toy_v2/code（同步后的代码）、results/neckopt_p<src>.json、results/pools/、queue/sb<src>_*（spec / result / prep / CSV）。
写：只写 ~/mobo_toy_v2/deck/p11_3406/g1/（阶段 11 / 12；别的阶段对写 deck/p<src>_3406/g1/）：g1_<时刻>.json / .txt 与 g1_latest.json / .txt，
    先写 .tmp 再改名。sys.dont_write_bytecode；3406（及 CT）股骨距离场缓存不在就不重算（femur_*.build 会写缓存），退出 2。

    cd ~/mobo_toy_v2/code && PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 taskset -c 4-11 nice -n 19 \\
        ~/mobo_toy_v2/run.sh ~/mobo_toy_v2/adhoc/p11/g1_regress.py [--src 11 --dst 12] [--rtol 1e-12] [--pool 16384 --seed 0] [--expect-delta D]
        [--expect-mm-limit none|<um>]

下面写的是默认的阶段 11 / 12；别的阶段对把 11 / 12 换成 src / dst（G1a 用来源阶段的 sed / metric / mm_limit，G1b 用目标阶段的）。

检查（每行一个 PASS / FAIL；INFO / WARN 不影响退出码）
  G1a  每个 DONE 的 sb11_* 作业与 neckopt_p11.json 的每条记录：当前代码的 record_of(job, "none", "v3") 的 ok / y / c
       与状态文件里存的相同（存了的时候；|差| ≤ rtol·max(1, |值|)，默认 rtol 1e-12，另报逐位相同的个数；--rtol 0 = 逐位）。
       没存的（冒烟作业在阶段 11 的 async 收编之前）只算、不比（INFO）。
  G1b  record_of(job, "none", "v4") 不抛错；ok 与 v3 相同；ok 时 y[:2] == v3 的 y、c == v3 的 c、y[2] == result.json 的 bone_loss.total_mm3（逐位）。
  G1c  阶段 12 冻结热启动的空跑（stage_neckopt.warm_from_select(strict=False) + warm_from_rows；不写状态文件）：
       选中 = round 0 + 收编的；还没收编的 DONE sb11_* 作业（阶段 11 的 async 还没跑时的冒烟作业）作"预计"一并建行。
       X0 (n, 13)、Y0 (n, 3)、C0 (n, 1)，n > 0；Y0[:, 2] == 每个作业的 bone_loss.total_mm3；
       查表 = 阶段 12 会用的候选池文件（pool_phase 11：neckopt_p11_n<pool>_s<seed>_<key>.npz，必须存在）+ det_extra(X0) →
       det(X0) == Y0[:, 2] 逐行逐位。另报（INFO）：与池点重合的热启动行数、这些点上池里的去骨量与记录的差。
       阶段 12 现在启动会不会拒绝（未收编 / 收编后仍在算）只作 INFO：两臂按 README 的顺序启动时它们会消失。
  G1d  形状与阶段定义：_empty(Phase(11)) 的 Y (0, 2)、v3 记录 y 长 2；PHASES[11] 没有 warm_from / pool_phase、metric v3；
       PHASES[12] 的 warm_from = {phase 11, rounds [0, -1]}；neckopt_p11.json 的 space / fixed == 同步后的 Phase(11)
       （不同时 bo_async 会悄悄丢掉全部存的记录——FAIL，拦住启动）。别的阶段对：PHASES[src] metric v3、没有 warm_from（可以有 pool_phase）；
       PHASES[dst] metric v4、warm_from {phase src, rounds [0, -1]}。候选池（G1c）：目标阶段与来源阶段用同一个池文件（pool_source 相同）且文件存在。
  G1e  摩擦模型与微动上限（2026-10-24，阶段 13 / 14）：Phase(src).fric == Phase(dst).fric、mm_limit 相同（--expect-delta 给了时 Phase(src) 的
       delta 必须等于它）；每个要比的作业（存的记录、待定、DONE 的 sb<src>_*）的 spec.json 的 delta / slip_tol == Phase(src).fric（阶段 13：
       全是 0.1；delta 与 FRIC 默认（0.025）不同的阶段另有一行"没有一个 0.025 的作业"）；冻结热启动的候选同样 == Phase(dst).fric；
       状态文件存的微动上限（"mm_limit" 键，没有 = 150）== Phase(src).mm_limit（不同 = 存的 c 是按另一种可行性算的）。
       INFO：in_family 不接受的作业数；mm_limit None 时微动 > 150 µm 的 ok 记录数（照样可行）。
       --expect-mm-limit none | <µm>（审查 wxa60xosx 中 1）：Phase(src).mm_limit 与 Phase(dst).mm_limit 都必须等于它，否则 FAIL——上面几行只比
       一致性，同步了一份没有 mm_limit 的旧代码时它们全部 PASS（全是 150）；这一行核对的是设置本身（阶段 13 / 14：none）。不给就没有这一行。
退出码：0 全部 PASS；1 有 FAIL；2 只读守卫不过或读不到状态文件。
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

ROWS = []


def row(check: str, item: str, verdict: str, detail: str = "") -> None:
    ROWS.append({"check": check, "item": item, "verdict": verdict, "detail": detail})
    print(f"{verdict:5s} {check:4s} {item:42s} {detail}", flush=True)


def same(a, b, rtol: float) -> tuple[bool, bool, float]:
    """(在容差内, 逐位相同, 最大相对差)；nan 与 nan 相同；长度不同 → 不同。"""
    a = list(a) if isinstance(a, (list, tuple)) else [a]
    b = list(b) if isinstance(b, (list, tuple)) else [b]
    if len(a) != len(b):
        return False, False, math.inf
    worst, exact, ok = 0.0, True, True
    for x, y in zip(a, b):
        if x is None or y is None:
            if not (x is None and y is None):
                return False, False, math.inf
            continue
        x, y = float(x), float(y)
        if math.isnan(x) or math.isnan(y):
            if not (math.isnan(x) and math.isnan(y)):
                return False, False, math.inf
            continue
        if x != y:
            exact = False
            d = abs(x - y) / max(1.0, abs(x), abs(y))
            worst = max(worst, d)
            if d > rtol:
                ok = False
    return ok, exact, worst


def femur_cache_ok(SN, femur_ids) -> tuple[bool, str]:
    """要重算的作业所用股骨的距离场缓存都在（否则 build 会重建并写缓存，违反只读）。"""
    msgs, good = [], True
    for fid in sorted(set(femur_ids), key=str):
        try:
            if fid == "sawbone3406":
                import femur_3406 as F
                f = F.CACHE / f"femur_3406_{F._cache_key(F.load_cfg(None))}.npz"
            elif fid is None:
                import femur_real as FR
                f = FR.CACHE / f"femur_real_{FR._cache_key(FR.load_cfg())}.npz"
            else:
                good = False
                msgs.append(f"{fid}: unknown femur")
                continue
            good &= f.exists()
            msgs.append(f"{fid or 'CT'}: {f.name} {'ok' if f.exists() else 'MISSING'}")
        except Exception as e:                                            # noqa: BLE001
            good = False
            msgs.append(f"{fid}: cache check failed {type(e).__name__}: {str(e)[:100]}")
    return good, "; ".join(msgs)


class Out:
    """只写 out_dir 之内；先写 .tmp 再改名。"""

    def __init__(self, d: pathlib.Path):
        self.d = d.resolve()

    def write(self, name: str, text: str) -> pathlib.Path:
        p = (self.d / name).resolve()
        if self.d not in p.parents:
            raise RuntimeError(f"refusing to write outside {self.d}: {p}")
        self.d.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        return p


def rec_of(SN, job: str, ph, metric: str) -> dict:
    """record_of(job, ph.sed, metric, ph.mm_limit)；没有 Phase.mm_limit 的旧代码（阶段 11 / 12 时）调旧签名。"""
    if hasattr(ph, "mm_limit"):
        return SN.record_of(job, ph.sed, metric, ph.mm_limit)
    return SN.record_of(job, ph.sed, metric)


def mm_arg(s: str):
    """--expect-mm-limit 的值：none / null → "none"（微动不作约束），否则正的 µm 数。"""
    if str(s).strip().lower() in ("none", "null"):
        return "none"
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r}: expected 'none' or a positive number of um") from None
    if not (v > 0 and v != float("inf")):
        raise argparse.ArgumentTypeError(f"{s!r}: expected 'none' or a positive number of um")
    return v


def mm_is(v, expected) -> bool:
    """v：Phase.mm_limit（None = 不作约束；没有这个属性的旧代码 = MM_LIMIT）；expected：mm_arg 的值。"""
    if expected == "none":
        return v is None
    return v is not None and abs(float(v) - float(expected)) <= 1e-9 * max(1.0, abs(float(expected)))


def fric_of(SN, ph) -> dict:
    return dict(getattr(ph, "fric", None) or SN.FRIC)


def run(a) -> int:
    src, dst = int(a.src), int(a.dst)
    legacy_pair = (src, dst) == (11, 12)                                   # 阶段 11 / 12：行名与输出目录与从前逐字相同
    root = pathlib.Path(os.path.expanduser(a.root)).resolve()
    code = pathlib.Path(os.path.expanduser(a.code)).resolve() if a.code else root / "code"
    out = Out(pathlib.Path(os.path.expanduser(a.out)).resolve() if a.out else
              root / "deck" / ("p11_3406" if legacy_pair else f"p{src}_3406") / "g1")
    queue, results = root / "queue", root / "results"
    t0 = time.time()
    sys.path.insert(0, str(code))
    sys.path.insert(0, str(code / "v2"))
    import jobs as J                                                       # noqa: E402
    J.QROOT, J.RESULTS = queue, results
    import numpy as np                                                     # noqa: E402
    import stage_neckopt as SN                                             # noqa: E402
    ver = (code / "VERSION").read_text(errors="replace").strip().replace("\n", " ") if (code / "VERSION").exists() else "(no VERSION)"
    print(f"g1_regress: phases {src} -> {dst}; code {code} [{ver}]; queue {queue}; code_hash {J.code_hash()}", flush=True)

    # ---- G1d：阶段定义与形状（不碰作业）
    if src not in SN.PHASES or dst not in SN.PHASES:
        row("G1d", f"PHASES[{src}] / PHASES[{dst}] defined", "FAIL", f"known phases {sorted(SN.PHASES)}: sync the code that defines them")
        return finish(out, a, t0, ver, code=2)
    p_s, p_d = SN.PHASES[src], SN.PHASES[dst]
    if legacy_pair:
        row("G1d", "PHASES[11] metric v3, no warm_from / pool_phase",
            "PASS" if p_s.get("metric") == "v3" and "warm_from" not in p_s and "pool_phase" not in p_s else "FAIL",
            f"metric {p_s.get('metric')}, keys {sorted(k for k in p_s if k in ('warm_from', 'pool_phase'))}")
        row("G1d", "PHASES[12] warm_from {phase 11, rounds [0, -1]}",
            "PASS" if p_d.get("warm_from") == {"phase": 11, "rounds": [0, -1]} and p_d.get("metric") == "v4" else "FAIL",
            f"metric {p_d.get('metric')}, warm_from {p_d.get('warm_from')}")
    else:
        row("G1d", f"PHASES[{src}] metric v3, no warm_from",
            "PASS" if p_s.get("metric") == "v3" and "warm_from" not in p_s else "FAIL",
            f"metric {p_s.get('metric')}, warm_from {p_s.get('warm_from')}, pool_phase {p_s.get('pool_phase')}")
        row("G1d", f"PHASES[{dst}] warm_from {{phase {src}, rounds [0, -1]}}",
            "PASS" if p_d.get("warm_from") == {"phase": src, "rounds": [0, -1]} and p_d.get("metric") == "v4" else "FAIL",
            f"metric {p_d.get('metric')}, warm_from {p_d.get('warm_from')}, pool_phase {p_d.get('pool_phase')}")
    ph_s, ph_d = SN.Phase(src), SN.Phase(dst)
    e_s = SN._empty(ph_s)
    row("G1d", f"_empty(Phase({src})) shapes", "PASS" if e_s[1].shape == (0, 2) and e_s[0].shape == (0, len(ph_s.vars)) else "FAIL",
        f"X {e_s[0].shape}, Y {e_s[1].shape}")

    # ---- G1e：摩擦模型与微动上限（定义）
    fr_s, fr_d = fric_of(SN, ph_s), fric_of(SN, ph_d)
    mm_s, mm_d = getattr(ph_s, "mm_limit", SN.MM_LIMIT), getattr(ph_d, "mm_limit", SN.MM_LIMIT)
    row("G1e", f"fric Phase({src}) == Phase({dst})", "PASS" if fr_s == fr_d else "FAIL", f"{fr_s} vs {fr_d}")
    row("G1e", f"mm_limit Phase({src}) == Phase({dst})", "PASS" if mm_s == mm_d else "FAIL",
        f"{mm_s} vs {mm_d} ({'micromotion recorded, not a constraint' if mm_s is None else 'micromotion constraint'})")
    if a.expect_mm_limit is not None:
        exp = a.expect_mm_limit
        exp_txt = "none" if exp == "none" else f"{exp:g}"
        good_mm = mm_is(mm_s, exp) and mm_is(mm_d, exp)
        row("G1e", f"mm_limit Phase({src}) / Phase({dst}) == expected {exp_txt}", "PASS" if good_mm else "FAIL",
            f"Phase({src}) {mm_s}, Phase({dst}) {mm_d}"
            + ("" if hasattr(ph_s, "mm_limit") else " (this stage_neckopt has no Phase.mm_limit: old code, 150 everywhere)")
            + ("" if good_mm else " -- the synced stage_neckopt.py does not define the expected micromotion limit: sync the right commit"))
    if a.expect_delta is not None:
        row("G1e", f"Phase({src}) delta == expected {a.expect_delta:g}",
            "PASS" if abs(float(fr_s.get("delta")) - a.expect_delta) <= 1e-12 else "FAIL", f"Phase({src}).fric {fr_s}")

    # ---- 状态文件
    st, err = None, None
    sp = SN.out_path(src)
    try:
        st = SN._read_state_retry(sp)
    except ValueError as e:
        err = str(e)
    if st is None:
        row("G1a", sp.name, "FAIL", err or f"{sp} does not exist (the init batch has not finished)")
        return finish(out, a, t0, ver, code=2)
    # G1d：状态文件的 space / fixed 必须与同步后的 Phase(src) 相同——bo / bo_async 只在两者都相同时续用记录；不同就悄悄丢掉全部记录
    # （init 作业被重新收编成 round -1 / pool_idx None，参考点与粘接计数器重置，目标阶段的冻结规则与预算公式都会错）。
    spc = {k: list(v) for k, v in ph_s.space.items()}
    st_space, st_fixed = st.get("space"), st.get("fixed")
    diffs = []
    if st_space != spc:
        ks = sorted(set(st_space or {}) | set(spc), key=str)
        diffs.append("space " + ", ".join(f"{k}: stored {(st_space or {}).get(k)} vs Phase({src}) {spc.get(k)}"
                                          for k in ks if (st_space or {}).get(k) != spc.get(k)))
    if st_fixed != ph_s.fixed:
        ks = sorted(set(st_fixed or {}) | set(ph_s.fixed), key=str)
        diffs.append("fixed " + ", ".join(f"{k}: stored {(st_fixed or {}).get(k)} vs Phase({src}) {ph_s.fixed.get(k)}"
                                          for k in ks if (st_fixed or {}).get(k) != ph_s.fixed.get(k)))
    n_st = len(st.get("records") or [])
    row("G1d", f"{sp.name} space / fixed == Phase({src})", "FAIL" if diffs else "PASS",
        (f"{'; '.join(diffs)} -- bo_async would silently drop all {n_st} stored records (re-adopt the init jobs as round -1 / "
         f"pool_idx None, reset ref_point and the bond counter): sync the code that wrote the file") if diffs else
        f"{len(spc)} variables and {len(ph_s.fixed)} fixed values identical; the {n_st} stored records will be reused")
    st_mm = (st["mm_limit"] if st["mm_limit"] is None else float(st["mm_limit"])) if "mm_limit" in st else SN.MM_LIMIT
    row("G1e", f"{sp.name} micromotion limit == Phase({src}).mm_limit", "PASS" if st_mm == mm_s else "FAIL",
        f"stored {st_mm} ({'key' if 'mm_limit' in st else 'no key = default'}) vs Phase({src}) {mm_s}"
        + ("" if st_mm == mm_s else " -- the stored c were computed under another feasibility rule"))
    stored = {r["job_id"]: r for r in st.get("records", []) if isinstance(r, dict) and r.get("job_id")}
    pending = sorted((st.get("pending") or {}).keys())
    jobs = sorted({d.name for d in queue.glob(f"{ph_s.stage}_*") if (d / "DONE").exists()} | set(stored))
    specs = {}
    for j in jobs + [p_ for p_ in pending if p_ not in stored]:
        f = queue / j / "spec.json"
        specs[j] = json.loads(f.read_text()) if f.exists() else {}
    good, msg = femur_cache_ok(SN, [specs[j].get("femur_id") for j in jobs] + [ph_s.femur_id])
    if not good:
        row("G1a", "read-only guard: femur caches", "FAIL", msg + " -- not rescoring (femur build would write the cache)")
        return finish(out, a, t0, ver, code=2)
    row("G1a", "read-only guard: femur caches", "INFO", msg)
    print(f"... {len(jobs)} jobs ({len(stored)} stored records in {sp.name}, updated {st.get('updated')})", flush=True)

    # ---- G1e：每个作业的摩擦模型（阶段 13：全是 δ 0.1，没有一个 δ 0.025）
    def fric_bad(spec_, fr):
        return [k for k in ("delta", "slip_tol") if spec_.get(k) != fr.get(k)]
    every = sorted(specs)
    mism = {j: {k: specs[j].get(k) for k in ("delta", "slip_tol")} for j in every if fric_bad(specs[j], fr_s)}
    row("G1e", f"phase-{src} job specs carry delta {fr_s['delta']:g} / slip_tol {fr_s['slip_tol']:g}", "FAIL" if mism or not every else "PASS",
        f"{len(every) - len(mism)} of {len(every)} (stored records, pending, DONE {ph_s.stage}_*) match"
        + (f"; mismatched {dict(list(mism.items())[:6])}" if mism else ""))
    if fr_s.get("delta") != SN.FRIC["delta"]:
        old = [j for j in every if specs[j].get("delta") == SN.FRIC["delta"]]
        row("G1e", f"no delta-{SN.FRIC['delta']:g} job in phase {src}'s records / pending / queue", "FAIL" if old else "PASS",
            f"{len(old)} of {len(every)}" + (f": {old[:6]}" if old else ""))
    nf = [j for j in every if specs[j] and not ph_s.in_family(specs[j])]
    row("G1e", f"in_family(Phase({src})) of those jobs", "INFO", f"{len(every) - len(nf)} of {len(every)} in the family" + (f"; not: {nf[:6]}" if nf else ""))

    # ---- G1a / G1b
    n_exact, n_cmp, worst_all, n_over_ok = 0, 0, 0.0, 0
    for j in jobs:
        try:
            r3 = rec_of(SN, j, ph_s, ph_s.metric)
        except Exception as e:                                            # noqa: BLE001
            row("G1a", j, "FAIL", f"record_of {ph_s.metric} raised {type(e).__name__}: {e}")
            continue
        if len(r3["y"]) != 2:
            row("G1d", j, "FAIL", f"{ph_s.metric} y has {len(r3['y'])} entries")
        if r3["ok"] and r3.get("f1_body_p95_um") is not None and float(r3["f1_body_p95_um"]) > SN.MM_LIMIT and r3["c"][0] <= 0:
            n_over_ok += 1
        if j in stored:
            s_ = stored[j]
            oky, exy, wy = same(r3["y"], s_.get("y"), a.rtol)
            okc, exc, wc = same(r3["c"], s_.get("c"), a.rtol)
            okk = bool(r3["ok"]) == bool(s_.get("ok"))
            n_cmp += 1
            n_exact += int(exy and exc and okk)
            worst_all = max(worst_all, wy if math.isfinite(wy) else 0.0, wc if math.isfinite(wc) else 0.0)
            v = "PASS" if (oky and okc and okk) else "FAIL"
            row("G1a", j, v, f"ok {r3['ok']}/{s_.get('ok')}; y {'=' if exy else ('~' if oky else '!=')} (max rel {wy:.1e}); "
                             f"c {'=' if exc else ('~' if okc else '!=')} (max rel {wc:.1e})"
                             + ("" if v == "PASS" else f"; now y {r3['y']} c {r3['c']}, stored y {s_.get('y')} c {s_.get('c')}"))
        else:
            row("G1a", j, "INFO", f"no stored record yet (adopted by phase {src}'s async at its first start); {ph_s.metric} ok {r3['ok']}")
        try:
            r4 = rec_of(SN, j, ph_d, ph_d.metric)
        except Exception as e:                                            # noqa: BLE001
            row("G1b", j, "FAIL", f"record_of {ph_d.metric} raised {type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}")
            continue
        res = J.result(j) or {}
        bone = (res.get("bone_loss") or {}).get("total_mm3")
        probs = []
        if len(r4["y"]) != 3:
            probs.append(f"v4 y has {len(r4['y'])} entries")
        if bool(r4["ok"]) != bool(r3["ok"]):
            probs.append(f"ok v4 {r4['ok']} != v3 {r3['ok']}" + (" (no bone_loss.total_mm3 in result.json)" if bone is None else ""))
        if r4["ok"] and r3["ok"] and len(r4["y"]) == 3:
            if not (r4["y"][:2] == r3["y"] and r4["c"] == r3["c"]):
                probs.append(f"y[:2] / c differ from v3: {r4['y'][:2]} {r4['c']} vs {r3['y']} {r3['c']}")
            if bone is None or r4["y"][2] != float(bone):
                probs.append(f"y[2] {r4['y'][2]} != bone_loss.total_mm3 {bone}")
        row("G1b", j, "FAIL" if probs else "PASS", "; ".join(probs) if probs else
            (f"bone {r4['y'][2]:.1f} mm3 == bone_loss.total_mm3; y[:2], c == v3" if r4["ok"] else "not ok under v3 and v4 (consistent)"))
    if n_cmp:
        row("G1a", "summary", "INFO", f"{n_exact}/{n_cmp} stored records bitwise identical; max relative deviation {worst_all:.1e} (rtol {a.rtol:g})")
    if mm_s is None:
        row("G1e", f"micromotion > {SN.MM_LIMIT:g} um, feasible (mm_limit None)", "INFO",
            f"{n_over_ok} of {len(jobs)} rescored jobs are ok and feasible with stem micromotion P95 > {SN.MM_LIMIT:g} um (recorded, not a constraint)")

    # ---- G1c：目标阶段冻结热启动空跑
    try:
        cand, info = SN.warm_from_select(ph_d, st, strict=False)
        projected = [j for j in info.get("unadopted", []) if (queue / j / "DONE").exists()]
        X0, Y0, C0, used, skipped = SN.warm_from_rows(ph_d, cand + projected)
        row("G1c", "warm-start selection", "INFO",
            f"{len(cand)} selected (round 0 {info['source_round0']}, adopted {info['source_adopted']}) + {len(projected)} not yet adopted "
            f"DONE {ph_s.stage} jobs (projected) -> {len(used)} rows; skipped {skipped}")
        for p_ in info.get("problems", []):
            row("G1c", f"phase {dst} would refuse now", "INFO", p_)
        wsp = {}
        for j in cand + projected:
            f = queue / j / "spec.json"
            wsp[j] = json.loads(f.read_text()) if f.exists() else {}
        wm = {j: {k: wsp[j].get(k) for k in ("delta", "slip_tol")} for j in wsp if fric_bad(wsp[j], fr_d)}
        row("G1e", f"warm-start candidates carry Phase({dst}).fric (delta {fr_d['delta']:g})", "FAIL" if wm else "PASS",
            f"{len(wsp) - len(wm)} of {len(wsp)} match" + (f"; mismatched {dict(list(wm.items())[:6])}" if wm else ""))
        nv = len(ph_d.vars)
        shp_ok = X0.shape == (len(used), nv) and Y0.shape == (len(used), 3) and C0.shape == (len(used), 1) and len(used) > 0
        row("G1c", "X0 / Y0 / C0 shapes", "PASS" if shp_ok else "FAIL", f"X0 {X0.shape}, Y0 {Y0.shape}, C0 {C0.shape}")
        bones = []
        for j in used:
            bones.append((( J.result(j) or {}).get("bone_loss") or {}).get("total_mm3"))
        b_ok = len(used) > 0 and all(b is not None and Y0[i, 2] == float(b) for i, b in enumerate(bones))
        row("G1c", "Y0[:, 2] == bone_loss.total_mm3", "PASS" if b_ok else "FAIL",
            f"{sum(1 for i, b in enumerate(bones) if b is not None and Y0[i, 2] == float(b))}/{len(used)} rows")
        ps_s, ps_d = SN.pool_source(ph_s, a.pool, a.seed), SN.pool_source(ph_d, a.pool, a.seed)
        pf = SN.pool_file(ph_d, a.pool, a.seed, ps_d)
        pool_item = "phase-12 candidate pool (reuse of phase 11's)" if legacy_pair else \
            f"phase-{dst} candidate pool (= phase {src}'s pool file)"
        if ps_d != ps_s or not pf.exists():
            row("G1c", pool_item, "FAIL",
                f"pool_source {ps_d} (phase {src}: {ps_s}), {pf.name} {'exists' if pf.exists() else 'MISSING'}: phase {dst} would build its own "
                f"pool (check --pool / --seed = the phase-{src} values, and that the hashed code is unchanged)")
        else:
            z = np.load(pf)
            pool, pool_loss = z["U"], z["loss"]
            row("G1c", pool_item, "PASS", f"{pf.name}: {len(pool)} feasible points (pool phase {ps_d})")
            import torch                                                   # noqa: E402
            det = SN.det_of(ph_d, pool, pool_loss, SN.det_extra(ph_d, pool, X0, Y0, [], {}))
            got = det[2](torch.as_tensor(X0)).numpy() if len(X0) else np.zeros(0)
            exact = len(X0) > 0 and np.array_equal(got, Y0[:, 2])
            row("G1c", "det(X0) == Y0[:, 2] (every warm row)", "PASS" if exact else "FAIL",
                f"{int((got == Y0[:, 2]).sum()) if len(X0) else 0}/{len(X0)} exact; max |diff| "
                f"{float(np.max(np.abs(got - Y0[:, 2]))) if len(X0) else 0.0:.3g} mm3")
            mask = SN._coincident(pool, X0)
            from scipy.spatial import cKDTree                              # noqa: E402
            if len(X0):
                dist, idx = cKDTree(pool).query(X0, k=1, p=np.inf)
                on = dist < 1e-9
                diffs = np.abs(pool_loss[idx[on]] - Y0[on, 2]) if on.any() else np.zeros(0)
                row("G1c", "warm rows on pool points (marked used)", "INFO",
                    f"{int(on.sum())} of {len(X0)} rows coincide with pool points ({int(mask.sum())} pool points marked used); "
                    f"pool bone vs record bone on them: max |diff| {float(diffs.max()) if len(diffs) else 0.0:.3g} mm3")
    except Exception as e:                                                # noqa: BLE001
        row("G1c", "warm-start dry run", "FAIL", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
    return finish(out, a, t0, ver)


def finish(out: Out, a, t0: float, ver: str, code: int | None = None) -> int:
    n_fail = sum(1 for r in ROWS if r["verdict"] == "FAIL")
    rc = code if code is not None else (1 if n_fail else 0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    summ = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": ver, "src": a.src, "dst": a.dst, "rtol": a.rtol, "pool": a.pool, "seed": a.seed,
            "n_pass": sum(1 for r in ROWS if r["verdict"] == "PASS"), "n_fail": n_fail, "exit_code": rc, "seconds": round(time.time() - t0, 1),
            "rows": ROWS}
    lines = [f"G1 regression phases {a.src} -> {a.dst} {summ['time']} [{ver}]: {summ['n_pass']} PASS, {n_fail} FAIL, exit {rc} ({summ['seconds']} s)", ""]
    lines += [f"{r['verdict']:5s} {r['check']:4s} {r['item']:42s} {r['detail']}" for r in ROWS]
    txt = "\n".join(lines) + "\n"
    try:
        for name in (f"g1_{stamp}.json", "g1_latest.json"):
            out.write(name, json.dumps(summ, indent=1, default=str))
        for name in (f"g1_{stamp}.txt", "g1_latest.txt"):
            out.write(name, txt)
        print(f"written {out.d}/g1_{stamp}.{{json,txt}} (+ g1_latest)", flush=True)
    except Exception as e:                                                # noqa: BLE001
        print(f"could not write the report: {type(e).__name__}: {e}", flush=True)
    print(lines[0], flush=True)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="G1 regression before the parallel arms (default phase 11 / 12; read-only)")
    ap.add_argument("--root", default="~/mobo_toy_v2")
    ap.add_argument("--src", type=int, default=11, help="source phase (v3 arm, warm-start source; default 11)")
    ap.add_argument("--dst", type=int, default=12, help="target phase (v4 arm with the frozen warm start; default 12)")
    ap.add_argument("--expect-delta", type=float, default=None, help="G1e: Phase(src) interference delta must equal this (phase 13: 0.1)")
    ap.add_argument("--expect-mm-limit", type=mm_arg, default=None, metavar="none|UM",
                    help="G1e: Phase(src).mm_limit and Phase(dst).mm_limit must equal this ('none' = no micromotion constraint; phase 13: none)")
    ap.add_argument("--code", default=None, help="code directory (default <root>/code)")
    ap.add_argument("--out", default=None, help="output directory (default <root>/deck/p11_3406/g1; other pairs <root>/deck/p<src>_3406/g1)")
    ap.add_argument("--rtol", type=float, default=1e-12, help="G1a tolerance (relative, floor 1); 0 = bitwise")
    ap.add_argument("--pool", type=int, default=16384)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    ROWS.clear()
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
