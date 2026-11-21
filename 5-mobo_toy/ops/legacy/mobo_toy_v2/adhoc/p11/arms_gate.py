"""并行两臂的启动前预检（阶段 11 / 12：计算计划_50h_2026-10-24.md §7 修订 1；阶段 13 / 14：用户 2026-10-24 12:20；README_p11_ops.md）。
只用标准库，可手动运行看数字。阶段对用 --src / --dst 给（默认 11 / 12，与从前逐字相同；阶段 13 / 14 用 --src 13 --dst 14）。

读（只读）：~/mobo_toy_v2/results/neckopt_p<src>.json、neckopt_p<dst>.json（有就读）、~/mobo_toy_v2/queue/sb<src>_* 与各作业的
    spec.json / FAILED.json。写：只在给了 --flag FILE 时，闸门不过就写 FILE（内容 = 数字），过了就删掉 FILE。别的什么都不写。

    python3 arms_gate.py init [--src 11 --dst 12] [--max-fail 0.15] [--new 95] [--flag ~/mobo_toy_v2/logs/arms_gate.FAIL]
                              [--allow-infeasible] [--expect-delta 0.1] [--expect-mm-limit none|<um>]
        来源阶段的段 A（init 批）闸门：round-0 记录的不 ok 比例 > max-fail，或 0 个可行（c ≤ 0）→ FAIL（--allow-infeasible 只越过后一条，
        看过数字后有意为之；没有 round-0 记录永远 FAIL）。
        微动上限：状态文件有 "mm_limit" 键时用它（stage_neckopt.state_extras：阶段 13 / 14 存 null = 微动不作约束），没有 = 150 µm。
        mm_limit 为 null 时"0 个可行"一条不适用（c 只剩粘接行的 vM 项），只报数字（可行数、微动范围、超过 150 µm 的个数，记录不约束）。
        --expect-delta：每个 init 作业的 spec.json 的过盈 delta 必须等于它（缺 spec 也算不符）→ 否则 FAIL；不给就只报 delta 的分布。
        --expect-mm-limit none | <µm>（审查 wxa60xosx 中 1：显式核对设置，不只比一致性）：状态文件的微动上限（"mm_limit" 键；没有这个键 = 150）
        必须等于它 → 否则 FAIL（阶段 13 / 14 给 none：一个由旧代码写的 neckopt_p13.json 没有这个键，按 150 判，在这里拦住）。不给就不查。
        另给来源阶段臂的预算：
        BUDGET<src> = init 记录数（round 0，含 FAILED）+ 收编数（不是来源阶段驱动提交的 sb<src>_*：记录 / 待定里 pool_idx 为 None 的，
        加上队列里还没收编的）+ NEW。bo_async 的预算 = len(records) + len(pending)，init 记录与冒烟作业都在来源阶段的记录里，所以要加上；
        目标阶段的预算只数它自己的 sb<dst>_*（冻结的热启动行不计），BUDGET<dst> = NEW。两臂各 NEW 个自有提交。
    python3 arms_gate.py ready [--src 11 --dst 12]        （= 旧名 p12，两个名字等价）
        目标阶段的冻结热启动现在能不能建（与 stage_neckopt.warm_from_select 同一规则；g12_run.sh 轮询它）：
        READY = neckopt_p<dst>.json 里已有冻结集（续跑），或 neckopt_p<src>.json 有 round-0 记录、队列里没有来源阶段还没收编的 sb<src>_*、
        来源阶段没有收编后仍在算的作业。
    共同：--root ~/mobo_toy_v2（测试用假树）

退出码：0 PASS / READY；3 闸门不过；5 neckopt_p<src>.json 不存在或读不了；8 目标阶段还不能冻结；2 参数错。
输出最后是机器可读的 KEY=VALUE 行：VERDICT、BUDGET<src>、BUDGET<dst>、N_PICKS<src>、READY<dst> …（阶段号进键名，11 / 12 时与从前相同），
另有与阶段号无关的 BUDGET_SRC、BUDGET_DST、N_PICKS_SRC、READY_DST、MM_LIMIT（数字或 none）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

MM_LIMIT = 150.0                    # = stage_neckopt.MM_LIMIT（状态文件没有 "mm_limit" 键时的微动上限）
STAGE_PREFIX = "sb"                 # 3406（femur_id）阶段的作业 stage 前缀：sb<phase>_*


def read_json(path: pathlib.Path, tries: int = 5, wait_s: float = 2.0):
    """(dict | None, 错误)：不存在 → (None, "missing")；写到一半读不到 → 重试。"""
    err = "missing"
    for k in range(tries):
        if not path.exists():
            return None, "missing"
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except (ValueError, OSError) as e:
            err = f"{type(e).__name__}: {e}"
            if k < tries - 1:
                time.sleep(wait_s)
    return None, err


def job_state(d: pathlib.Path) -> str:
    for s in ("DONE", "FAILED.json", "SOLVED", "CLAIMED", "READY"):
        if (d / s).exists():
            return s.replace(".json", "")
    return "NEW" if (d / "spec.json").exists() else "MISSING"


def failed_level(d: pathlib.Path) -> str:
    try:
        f = json.loads((d / "FAILED.json").read_text(encoding="utf-8"))
        return f"{f.get('level')}/{f.get('stage')}"
    except Exception:                                                     # noqa: BLE001
        return "?"


def num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def split_src(st: dict, queue: pathlib.Path, src: int) -> dict:
    """来源阶段状态文件的账：init / 收编 / 自己的选点（记录与待定），以及队列里还没收编的 sb<src>_*。"""
    recs = [r for r in st.get("records", []) if isinstance(r, dict) and r.get("job_id")]
    pend = {j: p for j, p in (st.get("pending") or {}).items() if isinstance(p, dict)}
    known = {r["job_id"] for r in recs} | set(pend)
    unadopted = sorted(d.name for d in queue.glob(f"{STAGE_PREFIX}{src}_*")
                       if d.is_dir() and (d / "spec.json").exists() and d.name not in known)
    return {
        "recs": recs, "pend": pend,
        "r0": [r for r in recs if r.get("round") == 0],
        "adopted_recs": [r for r in recs if r.get("round") != 0 and r.get("pool_idx") is None],
        "picks_recs": [r for r in recs if r.get("round") != 0 and r.get("pool_idx") is not None],
        "adopted_pend": sorted(j for j, p in pend.items() if p.get("pool_idx") is None),
        "picks_pend": sorted(j for j, p in pend.items() if p.get("pool_idx") is not None),
        "unadopted": unadopted,
    }


def split_p11(st: dict, queue: pathlib.Path) -> dict:
    """旧名（阶段 11）。"""
    return split_src(st, queue, 11)


def warm_candidates(st: dict, rounds=(0, -1)) -> list:
    """= stage_neckopt.warm_from_select 的选法：round 0 → init；-1 → 收编（pool_idx None，任何 round）；来源阶段驱动自己的选点不取。"""
    out = []
    for r in st.get("records", []):
        if not isinstance(r, dict) or not r.get("job_id"):
            continue
        rd = r.get("round")
        if rd == 0:
            take = 0 in rounds
        elif r.get("pool_idx") is None:
            take = -1 in rounds
        else:
            take = rd in rounds and rd not in (0, -1)
        if take and r["job_id"] not in out:
            out.append(r["job_id"])
    return out


def state_mm_limit(st: dict):
    """(微动上限 µm 或 None, 来源说明)：状态文件的 "mm_limit" 键（null = 不作约束）；没有这个键 = MM_LIMIT（阶段 10–12 的文件）。"""
    if "mm_limit" in st:
        v = st["mm_limit"]
        return (None if v is None else float(v)), "state file 'mm_limit'"
    return MM_LIMIT, "default (no 'mm_limit' key in the state file)"


def spec_delta(d: pathlib.Path):
    try:
        return json.loads((d / "spec.json").read_text(encoding="utf-8")).get("delta", "absent")
    except Exception:                                                     # noqa: BLE001
        return "no spec"


def write_flag(flag: str | None, text: str, fail: bool) -> None:
    if not flag:
        return
    f = pathlib.Path(os.path.expanduser(flag))
    if fail:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        tmp.replace(f)
    elif f.exists():
        f.unlink()


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


def mm_matches(stored, expected) -> bool:
    """stored：state_mm_limit 的值（None = 不作约束）；expected：mm_arg 的值（"none" 或 µm）。"""
    if expected == "none":
        return stored is None
    return stored is not None and abs(float(stored) - float(expected)) <= 1e-9 * max(1.0, abs(float(expected)))


def launcher_of(src: int) -> str:
    return "g11b_run.sh" if src == 11 else f"g{src}b_run.sh"


def cmd_init(a, root: pathlib.Path) -> int:
    src, dst = a.src, a.dst
    name = f"neckopt_p{src}.json"
    queue, path = root / "queue", root / "results" / name
    st, err = read_json(path)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if st is None:
        msg = f"FAIL {now} {path} {err}: no phase-{src} state file (the init batch has not finished, or the file is unreadable)"
        print(msg)
        write_flag(a.flag, msg, True)
        print("VERDICT=FAIL")
        return 5
    s = split_src(st, queue, src)
    r0 = s["r0"]
    ok = [r for r in r0 if r.get("ok")]
    feas = [r for r in ok if isinstance(r.get("c"), list) and r["c"] and num(r["c"][0]) is not None and r["c"][0] <= 0]
    frac = (1.0 - len(ok) / len(r0)) if r0 else 1.0
    mm_limit, mm_src = state_mm_limit(st)
    levels = {}
    for r in r0:
        if r.get("ok"):
            continue
        d = queue / r["job_id"]
        k = f"FAILED {failed_level(d)}" if job_state(d) == "FAILED" else f"{job_state(d)} but not ok (metrics missing)"
        levels[k] = levels.get(k, 0) + 1
    print(f"phase-{src} state file {path} (updated {st.get('updated')}, mode {st.get('mode', 'bo')}, n_submitted {st.get('n_submitted')})")
    print(f"micromotion limit: {'none (micromotion recorded, not a constraint)' if mm_limit is None else f'{mm_limit:g} um'} [{mm_src}]")
    mm_bad = a.expect_mm_limit is not None and not mm_matches(mm_limit, a.expect_mm_limit)
    if a.expect_mm_limit is not None:
        exp_txt = "none" if a.expect_mm_limit == "none" else f"{a.expect_mm_limit:g} um"
        print(f"    expected micromotion limit {exp_txt}: {'MISMATCH' if mm_bad else 'match'}"
              + (f" -- the stored c were computed under another feasibility rule (code that wrote {name} is not the expected one); "
                 f"re-score with the synced code: v2/stage_neckopt.py async --phase {src} --budget 0 --pool 16384 --seed 0 --warm none "
                 f"--workers 4, then re-run g1_regress.py (README_p11_ops.md section 8)" if mm_bad else ""))
    print(f"init batch (round 0): {len(r0)} records (asked {st.get('n_init')}), ok {len(ok)}, feasible {len(feas)}, "
          f"not ok {len(r0) - len(ok)} = {frac:.1%} (limit {a.max_fail:.0%})")
    for k, v in sorted(levels.items()):
        print(f"    not ok: {v} x {k}")
    deltas = {}
    for r in r0:
        dl = spec_delta(queue / r["job_id"])
        deltas[repr(dl)] = deltas.get(repr(dl), 0) + 1
    print("    init specs, interference delta: " + (", ".join(f"{k} x {v}" for k, v in sorted(deltas.items())) or "none"))
    bad_delta = []
    if a.expect_delta is not None:
        bad_delta = [r["job_id"] for r in r0 if not (isinstance(spec_delta(queue / r["job_id"]), (int, float))
                                                     and abs(float(spec_delta(queue / r["job_id"])) - a.expect_delta) <= 1e-12)]
        print(f"    expected delta {a.expect_delta:g}: {len(r0) - len(bad_delta)} of {len(r0)} init specs match"
              + (f"; mismatched {', '.join(bad_delta[:6])}{' …' if len(bad_delta) > 6 else ''}" if bad_delta else ""))
    over = None
    if ok:
        rot = sorted(10 ** r["y"][0] for r in ok if num(r["y"][0]) is not None)
        area = sorted(-r["y"][1] for r in ok if num(r["y"][1]) is not None)
        f1 = sorted(num(r.get("f1_body_p95_um")) for r in ok if num(r.get("f1_body_p95_um")) is not None)
        med = (lambda v: v[len(v) // 2] if v else float("nan"))
        over = sum(1 for v in f1 if v > MM_LIMIT)
        tail = "" if mm_limit is None or mm_limit == MM_LIMIT else f"; {sum(1 for v in f1 if v > mm_limit)} over the phase limit {mm_limit:g}"
        note = " -- reported only: no micromotion constraint on this phase" if mm_limit is None else ""
        print(f"    ok init designs: rotation {rot[0]:.4g}–{rot[-1]:.4g} deg (median {med(rot):.4g}); contact area {area[0]:.0f}–{area[-1]:.0f} mm² "
              f"(median {med(area):.0f}); stem micromotion P95 {f1[0]:.0f}–{f1[-1]:.0f} µm (median {med(f1):.0f}; "
              f"{over} of {len(f1)} over {MM_LIMIT:g}{tail}){note}" if rot and area and f1 else "    ok init designs: metrics incomplete")
    if mm_limit is None:
        n_b = sum(1 for r in ok if not r.get("fric_only", False))       # 记录的 fric_only（record_of）；没有该键的按粘接算
        print(f"    feasibility without a micromotion limit: c = max(-1, vM term on bonded rows); {len(feas)} of {len(ok)} ok init designs "
              f"feasible ({n_b} bonded); the zero-feasible rule does not apply")
    n_adopt = len(s["adopted_recs"]) + len(s["adopted_pend"]) + len(s["unadopted"])
    n_picks = len(s["picks_recs"]) + len(s["picks_pend"])
    budget_src = len(r0) + n_adopt + a.new
    print(f"adopted / to adopt ({STAGE_PREFIX}{src}_* not submitted by the phase-{src} driver): {n_adopt} = {len(s['adopted_recs'])} records "
          f"+ {len(s['adopted_pend'])} adopted in flight + {len(s['unadopted'])} not yet adopted")
    for r in s["adopted_recs"]:
        print(f"    adopted record {r['job_id']} round {r.get('round')} ok {r.get('ok')}")
    for j in s["adopted_pend"]:
        print(f"    adopted, in flight {j} {job_state(queue / j)}")
    for j in s["unadopted"]:
        print(f"    not yet adopted {j} {job_state(queue / j)}")
    print(f"phase-{src} arm picks so far: {n_picks} ({len(s['picks_recs'])} done + {len(s['picks_pend'])} in flight) of NEW {a.new}")
    print(f"budget arithmetic: BUDGET{src} = {len(r0)} init records + {n_adopt} adopted + {a.new} new = {budget_src} "
          f"(bo_async counts len(records) + len(pending)); BUDGET{dst} = {a.new} (phase {dst} counts only its own {STAGE_PREFIX}{dst}_* jobs; "
          f"the frozen warm-start rows are not records)")
    zero_rule = mm_limit is not None                                      # mm_limit None：c 只剩 vM 项，"0 个可行"不作闸门
    fail = (not r0) or frac > a.max_fail or (zero_rule and not feas and not a.allow_infeasible) or bool(bad_delta) or mm_bad
    why = []
    if not r0:
        why.append("no round-0 records")
    elif frac > a.max_fail:
        why.append(f"not-ok fraction {frac:.1%} > {a.max_fail:.0%}")
    if r0 and not feas and zero_rule:
        why.append("zero feasible init designs (micromotion / stress constraint)"
                   + (" -- overridden by --allow-infeasible" if a.allow_infeasible else ""))
    if bad_delta:
        why.append(f"{len(bad_delta)} init spec(s) without delta {a.expect_delta:g}")
    if mm_bad:
        why.append(f"micromotion limit in {name} {'none' if mm_limit is None else f'{mm_limit:g}'} ({mm_src}) != expected "
                   f"{'none' if a.expect_mm_limit == 'none' else f'{a.expect_mm_limit:g}'}")
    verdict = "FAIL" if fail else "PASS"
    line = (f"{verdict} {now}: phase {src} init {len(r0)}, ok {len(ok)}, feasible {len(feas)}, not ok {frac:.1%} (limit {a.max_fail:.0%})"
            + ("; no micromotion limit" if mm_limit is None else "")
            + (f" -- {'; '.join(why)}" if why else ""))
    if src == 11 and dst == 12:                                           # 旧格式逐字保留（阶段 11 / 12 的标记文件与日志不变）
        line = (f"{verdict} {now}: init {len(r0)}, ok {len(ok)}, feasible {len(feas)}, not ok {frac:.1%} (limit {a.max_fail:.0%})"
                + (f" -- {'; '.join(why)}" if why else ""))
    print(line)
    write_flag(a.flag, line, fail)
    print(f"VERDICT={verdict}")
    print(f"INIT_RECORDS={len(r0)}")
    print(f"INIT_OK={len(ok)}")
    print(f"INIT_FEASIBLE={len(feas)}")
    print(f"NOT_OK_FRAC={frac:.4f}")
    print(f"N_ADOPT={n_adopt}")
    print(f"N_PICKS{src}={n_picks}")
    print(f"BUDGET{src}={budget_src}")
    print(f"BUDGET{dst}={a.new}")
    print(f"SRC={src}")
    print(f"DST={dst}")
    print(f"N_PICKS_SRC={n_picks}")
    print(f"BUDGET_SRC={budget_src}")
    print(f"BUDGET_DST={a.new}")
    print(f"MM_LIMIT={'none' if mm_limit is None else f'{mm_limit:g}'}")
    if over is not None:
        print(f"INIT_OVER_150={over}")
    if a.expect_mm_limit is not None:
        print(f"MM_LIMIT_EXPECTED={a.expect_mm_limit if a.expect_mm_limit == 'none' else f'{a.expect_mm_limit:g}'}")
        print(f"MM_LIMIT_OK={0 if mm_bad else 1}")
    return 3 if fail else 0


def cmd_ready(a, root: pathlib.Path) -> int:
    src, dst = a.src, a.dst
    queue = root / "queue"
    nd, ns = f"neckopt_p{dst}.json", f"neckopt_p{src}.json"
    pd, errd = read_json(root / "results" / nd)
    if pd is None and errd != "missing":
        print(f"{nd} unreadable: {errd}")
        print(f"READY{dst}=0")
        print("READY_DST=0")
        return 8
    if pd is not None and pd.get("warm_from"):
        wf = pd["warm_from"]
        print(f"phase {dst} already has a frozen warm start: {len(pd.get('warm_start_ids') or [])} ids (frozen {wf.get('frozen')} from "
              f"{wf.get('source')}); a restart reuses them and does not read {ns}")
        if int(wf.get("phase", -1)) != src:
            print(f"    warning: it was frozen from phase {wf.get('phase')}, not from phase {src} (the driver refuses this mismatch)")
        print(f"READY{dst}=1")
        print("READY_DST=1")
        print(f"WARM_IDS={len(pd.get('warm_start_ids') or [])}")
        return 0
    if pd is not None and (pd.get("records") or pd.get("pending")):
        print(f"{nd} has {len(pd.get('records') or [])} records but no frozen warm start (written before warm_from): "
              f"move it away before starting phase {dst}")
        print(f"READY{dst}=0")
        print("READY_DST=0")
        return 8
    st, err = read_json(root / "results" / ns)
    if st is None:
        print(f"{ns} {err}: the phase-{src} init batch has not saved its records yet")
        print(f"READY{dst}=0")
        print("READY_DST=0")
        return 8 if err == "missing" else 5
    s = split_src(st, queue, src)
    cand = warm_candidates(st)
    by = {r["job_id"]: r for r in s["recs"]}
    c_ok = [j for j in cand if by[j].get("ok")]
    c_feas = [j for j in c_ok if isinstance(by[j].get("c"), list) and by[j]["c"] and num(by[j]["c"][0]) is not None and by[j]["c"][0] <= 0]
    problems = []
    if not s["r0"]:
        problems.append(f"no round-0 (init) records in {ns}")
    if s["unadopted"]:
        problems.append(f"{len(s['unadopted'])} {STAGE_PREFIX}{src}_* job(s) not yet adopted by phase {src} ({', '.join(s['unadopted'][:6])}): "
                        f"start {launcher_of(src)} first and wait for its first save")
    if s["adopted_pend"]:
        problems.append(f"phase-{src} adopted job(s) still in flight ({', '.join(s['adopted_pend'][:6])}): wait until DONE / FAILED")
    mm_limit, _ = state_mm_limit(st)
    print(f"phase-{src} state: {len(s['recs'])} records ({len(s['r0'])} init, {len(s['adopted_recs'])} adopted, {len(s['picks_recs'])} arm picks), "
          f"{len(s['pend'])} pending; mode {st.get('mode', 'bo')} (updated {st.get('updated')})")
    if src == 11 and dst == 12:
        print(f"frozen warm start would be: {len(cand)} candidates (round 0 + adopted), {len(c_ok)} ok under v3 as stored "
              f"({len(c_feas)} feasible); phase 12 re-scores them under v4 at its first start")
    else:
        print(f"frozen warm start would be: {len(cand)} candidates (round 0 + adopted), {len(c_ok)} ok as stored in {ns} "
              f"({len(c_feas)} feasible; micromotion limit {'none' if mm_limit is None else f'{mm_limit:g} um'}); "
              f"phase {dst} re-scores them with its own settings at its first start")
    for p_ in problems:
        print(f"    not ready: {p_}")
    print(f"READY{dst}={0 if problems else 1}")
    print(f"READY_DST={0 if problems else 1}")
    print(f"WARM_CANDIDATES={len(cand)}")
    return 8 if problems else 0


def cmd_p12(a, root: pathlib.Path) -> int:
    """旧名。"""
    return cmd_ready(a, root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["init", "p12", "ready"])
    ap.add_argument("--root", default="~/mobo_toy_v2")
    ap.add_argument("--src", type=int, default=11, help="source phase (segment A, the 2-objective arm; default 11)")
    ap.add_argument("--dst", type=int, default=12, help="target phase (frozen warm start from --src; default 12)")
    ap.add_argument("--max-fail", type=float, default=0.15)
    ap.add_argument("--new", type=int, default=95, help="new submissions per arm")
    ap.add_argument("--flag", default=None, help="init: write this file on FAIL (numbers inside), remove it on PASS")
    ap.add_argument("--allow-infeasible", action="store_true",
                    help="init: do not fail on zero feasible init designs (a deliberate override after looking at the numbers)")
    ap.add_argument("--expect-delta", type=float, default=None,
                    help="init: every round-0 job's spec.json must carry this interference delta (else FAIL)")
    ap.add_argument("--expect-mm-limit", type=mm_arg, default=None, metavar="none|UM",
                    help="init: the state file's micromotion limit ('mm_limit' key; no key = 150) must equal this (else FAIL); "
                         "phases 13 / 14: none")
    a = ap.parse_args(argv)
    if a.src <= 0 or a.dst <= 0 or a.src == a.dst:
        print(f"--src {a.src} / --dst {a.dst}: two different positive phase numbers needed")
        return 2
    root = pathlib.Path(os.path.expanduser(a.root))
    return cmd_init(a, root) if a.cmd == "init" else cmd_ready(a, root)


if __name__ == "__main__":
    sys.exit(main())
