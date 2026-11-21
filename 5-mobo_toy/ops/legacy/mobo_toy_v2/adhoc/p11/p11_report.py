"""阶段 11 / 12（Sawbones 3406）检查点报告 —— Linux 上只读运行，只写 ~/mobo_toy_v2/deck/p11_3406/。

计划：research-log/neck_implant_2026-10-02/计算计划_50h_2026-10-24.md §4（检查点：一页中文摘要 + 前沿、超体积、设计图册）。

阶段对（2026-10-24，阶段 13 / 14 = δ 0.10、微动不作约束）：--src / --dst（默认 11 / 12：输出与从前逐字相同，下文写的就是默认）。
    --src 13 --dst 14：读 neckopt_p13.json / neckopt_p14.json、作业组 sb13_ / sb14_ / sb_（参照），写 ~/mobo_toy_v2/deck/p13_3406/。
    指标 = record_of(job, Phase(p).sed, Phase(p).metric, **Phase(p).mm_kw)（阶段 13 v3、阶段 14 v4，mm_limit None）。可行的微动上限取
    阶段的 mm_limit（13 / 14：None → 不看微动，带粘接行只剩 vM ≤ 440；fric_only 行没有 vM，有指标即可行），微动照样作为一列报告
    （--mm-limit none | <µm> 可覆盖）。2 目标前沿 = 来源阶段（转动 ↓ × 接触 ↑）；3 目标非支配集与去骨上限 6 / 8 / 10 / 12 cm³ 下的
    2 目标前沿 = 目标阶段臂（冻结热启动 + 自有 sb<dst>_；目标阶段还没有时事后在来源阶段上算）；超体积图另画两个驱动的 hv_hist。
    另有（非默认阶段对自动开；--compare on 也可给 11 / 12）：
      fig8 + §7：两臂相同自有评估数下的 2 维 HV(转动, 接触)，事后共同参考点（= 两臂可行行并集的最差 + 10 % 极差；共同起点 = 冻结热启动），
          横轴 = 各臂自有评估数；另在去骨 ≤ 8 / 10 cm³（--cmp-caps）下各算一次（参考点按上限内的并集）。
          来源阶段臂自有 = 不在冻结热启动里的 DONE / FAILED 作业中驱动自己的选点，按 neckopt_p<src>.json 分账（= stage_neckopt.bo_async /
          warm_from_select、arms_gate.split_src）：记录里 round ≠ 0 且 pool_idx 有值（round -1 = 停机期间算完、重启时 bo_async 收编的选点，
          designs.csv 标 "bo (re-adopted after restart)"），或待定里 pool_idx 有值。收编的作业 = 记录里 round ≠ 0 且 pool_idx None（任何
          round，含在算时收编、之后记成 round ≥ 1 的）或待定里 pool_idx None：不算，designs.csv 标 "adopted"，个数另报。状态文件读得到
          却没列出的 DONE / FAILED 行（手工提交的作业等）不是驱动提交的（bo_async 提交后立即写进待定并保存）= arms_gate.split_src 的
          unadopted，bo_async 下次启动时以 round -1、pool_idx None 收编：不论标签（含 init）都算收编、不算（designs.csv 标 "adopted"，
          并告警）；NEW 的不进计数、标签照旧（可能是驱动还没保存的选点）。状态文件没有 / 读不到时才全部按标签：init → round 0、
          smoke* → 收编、其他算自有。目标阶段臂自有 = DONE / FAILED 的 sb<dst>_ 作业，按 neckopt_p<dst>.json 同样分账、去掉收编的
          （含读得到却没列出的；个数另报）。
      fig9 + §8（--cmp-init 11，src 13 时默认）：初始批 δ 0.025（neckopt_p11.json 的 round-0 记录，sb11 init）与 δ 0.10（sb13 init）
          按 pool_idx 配对（没有 pool_idx 时按设计），转动 / 接触 / 微动的 Spearman ρ 与逐对表。

读（全部只读）
    ~/mobo_toy_v2/results/neckopt_p11.json（驱动 bo / async 的状态文件；写到一半读不到时重试 5 次，仍不行只用作业目录）
    ~/mobo_toy_v2/results/neckopt_p12.json（有就读；阶段 12 = 3 目标，v4 代码，本脚本不依赖 v4）
    ~/mobo_toy_v2/results/neckopt_p10.json（CT 阶段 10，只作参照，用记录里存的值，不重算）
    ~/mobo_toy_v2/queue/sb11_* / sb12_* / sb_*：spec.json、prep.json、solve.json、result.json、FAILED.json、状态标记
写（只写这一个目录，所有写入经 Out 守卫、先写 .tmp 再改名）
    ~/mobo_toy_v2/deck/p11_3406/{summary.json, summary.md, designs.csv, fig1…fig7 *.png, history/, _cache/, _mpl/}

指标
    每个 DONE 设计调 v2/stage_neckopt.record_of(job, "none", "v3")（= 阶段 11 的口径：内部用 v2/stability.py 算转动 / 接触，
    带粘接模型的作业再调 _calcar 取 SED），再从 stage_neckopt.stability_of 的进程内缓存取记录没带的键（rot_perm_deg 等）。
    阶段 12 的目标向量本脚本按字段自己算（转动、接触、去骨量），不调 v4 的 objectives。
    可行 = 柄身微动 P95（f1_body_p95_um）≤ 150 µm，且带粘接模型时 vm_p99 ≤ 440 MPa —— 与驱动 v3 在 sed "none" 下的约束 c ≤ 0 相同。
    超体积在驱动的坐标里算：2 目标 [log10 max(rot, 1e-3), −area]，参考点用 neckopt_p11.json 的 ref_point（没有时按驱动的
    ref_point 公式从现有可行点算，标 "computed"）；3 目标再加去骨量（单位按 neckopt_p12.json 记录的 y[2] / bone_mm3 推断，默认 mm³）。
    3 目标非支配集与去骨上限 6 / 8 / 10 / 12 cm³ 下的 2 目标前沿：阶段 12 存在时在 阶段 11 ∪ 12 的全部 3406 结果上算；
    不存在时同样在阶段 11 结果上事后算（标 post-hoc），供比较。
    重算的结果按 result.json 的 mtime / 大小与指标代码哈希缓存在 _cache/，下一次检查点只算新完成的作业。

时间（2026-10-25 utcorder：检查点 3 附 / §2 的改时问题）
    jobs.py 写的时间（spec.json 的 created、DONE 的内容、FAILED.json 的 time）是 Linux 本地时间、不带时区；designs.csv / summary 照原样
    显示。完成先后（超体积曲线、§7 两臂的自有评估顺序、designs.csv 的行序）、速度（含近 6 h）与周转一律按 epoch 秒算，不再把显示的
    字符串重新解析：夏令时结束时重复的那一小时（英国 2026-10-25 01:00–01:59，先 BST 后 GMT）里的时间按同一秒写下的标记文件的 mtime
    定（created ← spec.json，完成 ← DONE / FAILED.json；mtime 与一种解释相差 ≤ 60 s、与另一种相差 > 3000 s 才用；只满足前一条时
    也不用、另外告警），定不了再按"提交不晚于完成"，仍定不了取较早的夏令时解释并告警。其余时间与从前一样用 time.mktime。作业时间（不含报告
    时刻）跨夏令时切换或有落在重复那一小时的时间时，summary.json 加 clock（报告时刻的 UTC 偏移 / 时区也记在里面）、summary.md
    标题时刻带时区、§2 多一行说明；不跨时输出与从前逐字相同（报告时钟在切换之后也是）。

只读的保证
    sys.dont_write_bytecode（不写 __pycache__）；MPLCONFIGDIR 指到输出目录下；3406 股骨距离场缓存不存在时不重算指标
    （femur_3406.build 会写缓存），改用状态文件里存的值并给出警告；femur_*.build 在本进程记忆化（只为快，不写盘）。

用法（Linux；见同目录 README_p11_ops.md）
    cd ~/mobo_toy_v2/code && PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 taskset -c 4-11 nice -n 19 \\
        ~/mobo_toy_v2/run.sh ~/mobo_toy_v2/adhoc/p11/p11_report.py --label cp1
    阶段 13 / 14：同上加 --src 13 --dst 14（→ ~/mobo_toy_v2/deck/p13_3406/）
本机测试（假树）
    python p11_report.py --root <假树>/mobo_toy_v2 --code "<仓库>/sandbox/mobo_toy"
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import calendar  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

import numpy as np  # noqa: E402

REPORT_VERSION = "p11_report 2026-10-24 v1"                       # 默认阶段对 11 / 12（缓存键与 summary 的 report 字段不变）
REPORT_VERSION_PAIR = "p11_report 2026-10-24 v2 (--src/--dst)"     # 其他阶段对
MM_REF = 150.0                                                     # CT 模型的微动合格线（只用于"超过 150 µm"的计数，不是约束）
READOPTED = "bo (re-adopted after restart)"                        # 来源阶段驱动的选点：停机期间算完，重启时以 round -1 收编（pool_idx 保留）
OWN_RULE = ("source-phase rows not in the shared start, DONE or FAILED, that the source driver picked itself, by the split of "
            "neckopt_p<src>.json (= stage_neckopt.bo_async / warm_from_select, arms_gate.split_src): recorded with round != 0 and a pool_idx "
            "(round -1 = a pick that finished while the arm was stopped, re-adopted on restart) or pending with a pool_idx; adopted jobs "
            "(recorded with round != 0 and pool_idx None, any round, or pending with pool_idx None) are not counted; DONE / FAILED rows a "
            "readable state file does not list are not driver submissions (= arms_gate.split_src 'unadopted'; bo_async adopts them as "
            "round -1, pool_idx None at its next start, whatever the tag): adopted, not counted (a warning names them); "
            "only when the state file is missing / unreadable do rows fall back to the job tag (init -> round 0, smoke* -> adopted, "
            "other -> own). Target-phase rows: every DONE / FAILED sb<dst>_ job except the adopted ones, same split of "
            "neckopt_p<dst>.json (rows it does not list while readable are adopted likewise)")
VARS13 = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
SECTION = ("rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
REC_KEYS = ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_rev_deg", "subsid_first_um", "subsid_perm_um",
            "lateral_first_um", "slip_axial_p95_um", "slip_circ_p95_um", "contact_area_load2_mm2", "contact_frac_load2",
            "sed_chg_pct", "ssi_pct", "bone_mm3", "vm_p99", "f1_body_p95_um", "f1_all_p95_um", "A0", "entry_offset_e", "fric_only")
STAB_EXTRA = ("rot_perm_deg", "rot_axial_perm_deg", "rot_tilt_perm_deg", "rigid_fit_rms_first_um", "contact_area_load_mm2",
              "body_interface_mm2", "rot_first_prox_deg", "bench_cx_rot_perm_deg", "bench_cx_subsid_perm_um")
METRIC_FILES = ("stage_neckopt.py", "stability.py", "post_m1.py", "resorption.py", "shielding.py", "jobs.py")
NAME_RE = re.compile(r"^sb(\d*)_")
TFMT = "%Y-%m-%d %H:%M:%S"
CLOCK_TOL_S = 60.0                                                        # 重复的那一小时：标记文件 mtime 与某一解释相差 ≤ 60 s 才用它定（同一秒写；cp3 实测 < 1 s）
CLOCK_FAR_S = 3000.0                                                      # …且与另一解释相差 > 3000 s（两种解释差 1 h 时自然成立；防切换不到 1 h 的时区），否则当作没定并告警
CLOCK_RULE = ("times are the job machine's local time without a zone (as jobs.py writes them); completion order (HV traces, own evaluations "
              "of both arms, designs.csv row order), rates and turnarounds use epoch seconds: a string in a repeated local hour (DST end) is "
              "placed by the mtime of the marker written in the same second (created <- spec.json, done <- DONE / FAILED.json) when that "
              "mtime is within 60 s of one reading and more than 3000 s from the other (a mtime within 60 s of one reading but not more "
              "than 3000 s from the other does not decide it and is warned), else by created <= done, else the earlier (summer-time) reading is used and a warning names the "
              "job; this block is written when the job times (not the report clock) cross a DST change or fall in a repeated hour")

# 颜色（dataviz 参考调色板：分类前 3 个槽位全对通过 CVD 检查；顺序型 = 单一蓝色由浅到深）
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#9a9893"
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
FIG_DPI = 170                                                             # PNG 的 dpi（Out.fig；图例避让在同一 dpi 下试画）
BLUE_RAMP = ("#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b")
CAP_COLORS = ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b")        # 去骨上限 6 / 8 / 10 / 12（有序：浅 = 更严）

WARN: list[str] = []


def warn(msg: str) -> None:
    WARN.append(msg)
    print(f"[p11_report] warning: {msg}", file=sys.stderr, flush=True)


def log(msg: str) -> None:
    print(f"[p11_report] {msg}", flush=True)


# ------------------------------------------------------------------------------------------------- 输出守卫
class Out:
    """所有写入都经这里：路径必须在输出目录内；先写 .tmp 再 os.replace（取回时不会拿到写了一半的文件）。"""

    def __init__(self, d: pathlib.Path):
        self.d = d.resolve()

    def path(self, name: str) -> pathlib.Path:
        p = (self.d / name).resolve()
        if p != self.d and self.d not in p.parents:
            raise RuntimeError(f"refusing to write outside {self.d}: {p}")
        return p

    def _atomic(self, name: str, data: bytes) -> pathlib.Path:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return p

    def text(self, name: str, s: str) -> pathlib.Path:
        return self._atomic(name, s.encode("utf-8"))

    def json(self, name: str, obj) -> pathlib.Path:
        return self.text(name, json.dumps(obj, indent=1, ensure_ascii=False, default=_jdefault))

    def fig(self, name: str, fig) -> pathlib.Path:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=FIG_DPI)
        return self._atomic(name, buf.getvalue())


def _jdefault(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, pathlib.Path):
        return str(o)
    return str(o)


def _clean(o):
    """JSON 里不写 NaN / inf（换成 None）。"""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    return o


# ------------------------------------------------------------------------------------------------- 读
def read_json(p: pathlib.Path, tries: int = 1, wait: float = 2.0):
    """返回 (对象, 错误)。tries > 1 时对解析失败重试（驱动的 write_text 不是原子写）。"""
    err = None
    for k in range(max(1, tries)):
        if not p.exists():
            return None, "missing"
        try:
            return json.loads(p.read_text(encoding="utf-8", errors="replace")), None
        except (ValueError, OSError) as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            if k + 1 < tries:
                time.sleep(wait)
    return None, err


def parse_t(s) -> float | None:
    if not s:
        return None
    try:
        return time.mktime(time.strptime(str(s).strip()[:19], TFMT))
    except (ValueError, OverflowError):
        return None


def fmt_t(t: float | None) -> str | None:
    return None if t is None else time.strftime(TFMT, time.localtime(t))


def local_epochs(s) -> list:
    """不带时区的本地时间字符串（TFMT）对应的全部 epoch 秒：平常 1 个；夏令时结束时重复的那一小时（英国 2026-10-25 01:00–01:59：
    先 BST、后 GMT）2 个，升序；跳过的那一小时（3 月）0 个。"""
    try:
        tm = time.strptime(str(s).strip()[:19], TFMT)
    except (ValueError, OverflowError):
        return []
    key = time.strftime(TFMT, tm)
    out = set()
    for dst in (0, 1):
        try:
            t = time.mktime(tuple(tm)[:8] + (dst,))
        except (ValueError, OverflowError):
            continue
        if time.strftime(TFMT, time.localtime(t)) == key:
            out.add(t)
    return sorted(out)


def epoch_of(s, hint=None) -> tuple:
    """本地时间字符串 → (epoch 秒, 候选, 定法)。不在重复的那一小时：= parse_t(s)（与从前相同），定法 'unique'（含读不出的：None）。
    在重复的那一小时：hint（同一秒写下的标记文件的 mtime）与一种解释相差 ≤ CLOCK_TOL_S、与另一种相差 > CLOCK_FAR_S 时取前者，定法
    'mtime'；hint 没有或对不上（例如拷贝时没保留 mtime）时先取较早的（夏令时）解释，定法 'open'；hint 与一种解释差 ≤ CLOCK_TOL_S
    但与另一种也不够远（≤ CLOCK_FAR_S，两种解释差 1 h 时不会出现）时同样不按 mtime 定，定法 'near'（settle_clock 告警）。'open' /
    'near' 的两个候选留给 settle_clock 按"提交不晚于完成"再定。"""
    t0 = parse_t(s)
    if t0 is None:
        return None, [], "unique"
    c = local_epochs(s)
    if len(c) < 2:
        return t0, [t0], "unique"
    if hint is not None:
        d = sorted((abs(t - hint), t) for t in c)
        if d[0][0] <= CLOCK_TOL_S:
            if all(x > CLOCK_FAR_S for x, _ in d[1:]):
                return d[0][1], [d[0][1]], "mtime"
            return c[0], c, "near"
    return c[0], c, "open"


def _mtime(p: pathlib.Path):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def utc_offset(t: float) -> str:
    """t 时刻本机本地时间的 UTC 偏移，如 '+01:00'。"""
    off = calendar.timegm(time.localtime(t)) - math.floor(t)
    hh, mm = divmod(abs(int(off)) // 60, 60)
    return f"{'+' if off >= 0 else '-'}{hh:02d}:{mm:02d}"


def zone_tag(t: float) -> str:
    """显示用的时区：本机给得出简短的 ASCII 简称时用它（Linux：GMT / BST），否则（Windows 的本地化长名）写 'UTC+00:00'。"""
    nm = time.strftime("%Z", time.localtime(t))
    return nm if (nm.isascii() and nm.isalpha() and 2 <= len(nm) <= 5) else f"UTC{utc_offset(t)}"


def done_key(r: dict):
    """完成先后的排序键：epoch 秒（build 的行带 _t_done = 完成时刻取整到秒；从前把显示的 done 字符串重新解析，夏令时结束那一小时会排错），
    同秒按 job_id。没有 _t_done 的行（直接调用 arms_compare 的测试行）照旧解析 done。"""
    t = r["_t_done"] if "_t_done" in r else parse_t(r.get("done"))
    return (t if t is not None else 9e18, r["job_id"])


def num(v):
    """None / 非数 → None，否则 float。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def stats(vals) -> dict:
    v = np.array([x for x in (num(a) for a in vals) if x is not None], float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "min": float(v.min()), "p10": float(np.percentile(v, 10)), "median": float(np.median(v)),
            "p90": float(np.percentile(v, 90)), "max": float(v.max()), "mean": float(v.mean())}


def group_of(name: str):
    m = NAME_RE.match(name)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else "ref"


def job_info(d: pathlib.Path, J) -> dict:
    st = J.state(d)
    spec, _ = read_json(d / "spec.json")
    spec = spec or {}
    kind = spec.get("kind")
    t_cre, c_cre, h_cre = epoch_of(spec.get("created"), _mtime(d / "spec.json"))   # 重复的那一小时：spec.json 与 created 同一秒写（jobs.submit）
    info = {"job_id": d.name, "group": group_of(d.name), "state": st, "kind": kind, "stage": spec.get("stage"), "tag": spec.get("tag"),
            "femur_id": spec.get("femur_id"), "created": spec.get("created"), "t_created": t_cre,
            "bonded": (not spec.get("fric_only")) if kind in ("design", "variant") else None,
            "design": spec.get("design") or {}, "h_cut": num(spec.get("h_cut")), "source_job": spec.get("source_job")}
    c_end, h_end = [], "unique"
    if st == "FAILED":
        fj, err = read_json(d / "FAILED.json")
        fj = fj or {}
        info["failed"] = {"level": fj.get("level", "?"), "stage": fj.get("stage", "?"), "reason": str(fj.get("reason", err or ""))[:240]}
        t, c_end, h_end = epoch_of(fj.get("time"), _mtime(d / "FAILED.json"))      # 标记文件与其中的时间同一秒写
        info["t_end"] = t or (d / "FAILED.json").stat().st_mtime
    elif st == "DONE":
        try:
            t, c_end, h_end = epoch_of((d / "DONE").read_text(errors="replace"), _mtime(d / "DONE"))
            info["t_end"] = t or (d / "DONE").stat().st_mtime
        except OSError:
            info["t_end"] = None
    if h_cre != "unique" or h_end != "unique":                            # 有时间落在重复的那一小时：settle_clock 计数 / 再定
        info["_clock"] = {"created": (h_cre, c_cre), "end": (h_end, c_end)}
    sj, _ = read_json(d / "solve.json")
    if isinstance(sj, dict):
        info["solve"] = {k: {"status": (v or {}).get("status"), "wall_s": num((v or {}).get("wall_s")), "tries": (v or {}).get("tries")}
                         for k, v in sj.items() if isinstance(v, dict)}
    pj, _ = read_json(d / "prep.json")
    if isinstance(pj, dict):
        t = pj.get("templating") or {}
        bl = pj.get("bone_loss") or {}
        info["prep"] = {"n_tet": pj.get("n_tet"), "A0": num(t.get("A0")), "bone_mm3": num(bl.get("total_mm3")),
                        "resected_mm3": num(bl.get("resected_mm3")), "reamed_mm3": num(bl.get("reamed_mm3"))}
    return info


def settle_clock(infos: dict, groups, t_now: float) -> dict:
    """job_info 里落在重复那一小时、标记文件 mtime 也定不了的时间（定法 'open'；mtime 不够分明的 'near' 同样处理并另外告警）：同一
    作业的 (提交, 完成) 各种解释里只留完成 ≥ 提交的，剩一种的那边就定了；还剩两种的保留较早（夏令时）的解释并告警。返回时间口径
    （作业时间跨夏令时切换、或有时间落在重复那一小时时 crossed = True，build 才把它写进 summary.json 的 clock 与 summary.md；报告
    时刻 t_now 不算进是否跨时，只记在 generated_utc_offset / generated_zone）。只看报告的组（groups）。"""
    n_amb = n_mtime = n_order = 0
    undecided, near, hours, ts_ = [], [], set(), []                       # ts_ 只收作业时间：报告时钟在切换之后也不算跨
    for i in infos.values():
        if i.get("group") not in groups:
            continue
        ck = i.get("_clock") or {}
        sides = {s: ck.get(s, ("unique", [])) for s in ("created", "end")}
        for s, (how, _c) in sides.items():
            if how != "unique":
                n_amb += 1
                n_mtime += how == "mtime"
                hours.add((fmt_t(i.get("t_created") if s == "created" else i.get("t_end")) or "")[:13])
            if how == "near":
                near.append(f"{i['job_id']} {s} {i.get('created') if s == 'created' else fmt_t(i.get('t_end'))}")
        op = {s: sides[s][0] in ("open", "near") for s in sides}
        if any(op.values()) and i.get("t_created") is not None and i.get("t_end") is not None:
            cc = sides["created"][1] if op["created"] else [i["t_created"]]
            ce = sides["end"][1] if op["end"] else [i["t_end"]]
            pairs = [(a, b) for a in cc for b in ce if b >= a]
            cs, es = sorted({a for a, _ in pairs}), sorted({b for _, b in pairs})
            if op["created"] and len(cs) == 1:
                i["t_created"], op["created"] = cs[0], False
                n_order += 1
            if op["end"] and len(es) == 1:
                i["t_end"], op["end"] = es[0], False
                n_order += 1
        for s in ("created", "end"):
            if op[s]:
                undecided.append(f"{i['job_id']} {s} {i.get('created') if s == 'created' else fmt_t(i.get('t_end'))}")
        ts_ += [t for t in (i.get("t_created"), i.get("t_end")) if t is not None]
    offs = []
    for t in sorted(ts_):
        o = utc_offset(t)
        if not offs or offs[-1] != o:
            offs.append(o)
    hours.discard("")
    if n_amb:
        log(f"clock: {n_amb} job time(s) in a repeated local hour {sorted(hours)}: {n_mtime} placed by the marker mtime, "
            f"{n_order} by created <= done, {len(undecided)} undecided")
    if near:
        warn(f"{len(near)} job time(s) in the repeated local hour {sorted(hours)} (DST end): the marker file's mtime is within "
             f"{CLOCK_TOL_S:.0f} s of one reading but not more than {CLOCK_FAR_S:.0f} s from the other, so the mtime does not decide them "
             f"(treated as undecided by mtime; created <= done is tried next) ({', '.join(near[:8])}{', …' if len(near) > 8 else ''})")
    if undecided:
        warn(f"{len(undecided)} job time(s) in the repeated local hour {sorted(hours)} (DST end) could not be placed by the marker file's "
             f"mtime nor by created <= done: the earlier (summer-time) reading is used, so their completion order / rate / turnaround may "
             f"be off by 1 h ({', '.join(undecided[:8])}{', …' if len(undecided) > 8 else ''})")
    return {"crossed": len(set(offs)) > 1 or n_amb > 0, "utc_offsets": offs, "generated_utc_offset": utc_offset(t_now),
            "generated_zone": zone_tag(t_now), "repeated_hours": sorted(hours), "repeated_hour_strings": n_amb,
            "placed_by_mtime": n_mtime, "placed_by_order": n_order, "n_undecided": len(undecided), "undecided": undecided[:40],
            "mtime_inconclusive": len(near), "rule": CLOCK_RULE}


# ------------------------------------------------------------------------------------------------- 指标
def _code_key(code: pathlib.Path, extra: str = "") -> str:
    h = hashlib.sha1(REPORT_VERSION.encode())
    for f in METRIC_FILES:
        p = code / "v2" / f
        h.update(f.encode())
        h.update(p.read_bytes() if p.exists() else b"-")
    if extra:                                                             # 非默认阶段对：打分设置（sed / metric / mm_limit）进键
        h.update(extra.encode())
    return h.hexdigest()[:12]


def _result_key(d: pathlib.Path) -> str | None:
    p = d / "result.json"
    if not p.exists():
        return None
    s = p.stat()
    return f"{s.st_mtime_ns}:{s.st_size}"


def memoize_builds() -> None:
    """femur_real.build / femur_3406.build 每次都 np.load 距离场（3406 约 100 MB 压缩）；stability._load 每个作业调一次 J.femur_for。
    在本进程按参数记忆化（with_cut 是浅拷贝、共享距离场，所以安全）。只为快，不写盘。"""
    import femur_real as FR
    for mod in (FR,):
        _wrap_build(mod)
    try:
        import femur_3406 as F3
        _wrap_build(F3)
    except Exception as e:                                                # noqa: BLE001
        warn(f"femur_3406 import failed: {type(e).__name__}: {str(e)[:120]}")


def _wrap_build(mod) -> None:
    if getattr(mod.build, "_p11_memo", False):
        return
    orig, memo = mod.build, {}

    def build(*a, **k):
        key = json.dumps([a, k], sort_keys=True, default=str)
        if key not in memo:
            memo[key] = orig(*a, **k)
        return memo[key]
    build._p11_memo = True
    mod.build = build


def femur_cache_ok(femur_ids) -> tuple[bool, str]:
    """要重算的作业所用股骨的距离场缓存都在（否则 build 会重建并写缓存，违反只读）。"""
    msgs, ok = [], True
    for fid in sorted({f for f in femur_ids}, key=str):
        try:
            if fid == "sawbone3406":
                import femur_3406 as F
                f = F.CACHE / f"femur_3406_{F._cache_key(F.load_cfg(None))}.npz"
            elif fid is None:
                import femur_real as FR
                f = FR.CACHE / f"femur_real_{FR._cache_key(FR.load_cfg())}.npz"
            else:
                ok = False; msgs.append(f"{fid}: unknown femur"); continue
            if not f.exists():
                ok = False
            msgs.append(f"{fid or 'CT'}: {f} {'ok' if f.exists() else 'MISSING'}")
        except Exception as e:                                            # noqa: BLE001
            ok = False
            msgs.append(f"{fid}: cache check failed {type(e).__name__}: {str(e)[:100]}")
    return ok, "; ".join(msgs)


def row_from_record(rec: dict) -> dict:
    row = {k: rec.get(k) for k in REC_KEYS}
    row["has_metrics_driver"] = bool(rec.get("ok"))
    c = rec.get("c")
    row["c_driver"] = num(c[0]) if isinstance(c, (list, tuple)) and c else None
    return row


def metrics_rescore(job: str, SN, sargs=("none", "v3"), skw=None) -> dict:
    """默认 = record_of(job, "none", "v3")（阶段 11 / 12 的口径，与从前相同）；阶段对 13 / 14 传 (Phase.sed, Phase.metric) 与 Phase.mm_kw。"""
    rec = SN.record_of(job, *sargs, **(skw or {}))
    row = row_from_record(rec)
    stab = SN.stability_of(job) or {}
    row.update({k: stab.get(k) for k in STAB_EXTRA})
    row["metrics_source"] = "rescored"
    return row


def metrics_stored(rec: dict | None) -> dict:
    if not rec:
        return {"metrics_source": "none"}
    row = row_from_record(rec)
    row.update({k: rec.get(k) for k in STAB_EXTRA})
    row["metrics_source"] = "stored"
    return row


def has_metrics(row: dict) -> bool:
    return (num(row.get("rot_first_deg")) is not None and num(row.get("contact_area_load2_mm2")) is not None
            and num(row.get("f1_body_p95_um")) is not None and (num(row.get("vm_p99")) is not None or bool(row.get("fric_only"))))


def is_feasible(row: dict, mm_limit: float | None, vm_limit: float) -> bool:
    """mm_limit None（阶段 13 / 14）= 微动不作约束：只剩 vm_p99 ≤ vm_limit（fric_only 行没有 vM → 有指标即可行）。"""
    if not has_metrics(row):
        return False
    vm = num(row.get("vm_p99"))
    return (mm_limit is None or num(row["f1_body_p95_um"]) <= mm_limit) and (vm is None or vm <= vm_limit)


# ------------------------------------------------------------------------------------------------- 前沿与超体积（最小化）
def nondom_mask(P: np.ndarray) -> np.ndarray:
    P = np.asarray(P, float)
    n = len(P)
    keep = np.ones(n, bool)
    for i in range(n):
        dom = np.all(P <= P[i], axis=1) & np.any(P < P[i], axis=1)
        keep[i] = not dom.any()
    return keep


def hv2(P: np.ndarray, ref) -> float:
    P = np.asarray(P, float).reshape(-1, 2)
    ref = np.asarray(ref, float)
    P = P[np.all(P < ref, axis=1)]
    if not len(P):
        return 0.0
    P = P[nondom_mask(P)]
    P = P[np.lexsort((P[:, 1], P[:, 0]))]
    hv = 0.0
    for i in range(len(P)):
        x_next = P[i + 1, 0] if i + 1 < len(P) else ref[0]
        hv += (x_next - P[i, 0]) * (ref[1] - P[i, 1])
    return float(hv)


def hv3(P: np.ndarray, ref) -> float:
    P = np.asarray(P, float).reshape(-1, 3)
    ref = np.asarray(ref, float)
    P = P[np.all(P < ref, axis=1)]
    if not len(P):
        return 0.0
    P = P[nondom_mask(P)]
    P = P[np.argsort(P[:, 2], kind="stable")]
    hv = 0.0
    for i in range(len(P)):
        z_next = P[i + 1, 2] if i + 1 < len(P) else ref[2]
        if z_next > P[i, 2]:
            hv += (z_next - P[i, 2]) * hv2(P[: i + 1, :2], ref[:2])
    return float(hv)


def hv_any(P, ref) -> float:
    ref = np.asarray(ref, float)
    return hv2(P, ref) if len(ref) == 2 else hv3(P, ref)


def ref_point_of(Y: np.ndarray) -> np.ndarray | None:
    """= stage_neckopt.ref_point 对可行点：最差 + 10 % 极差。"""
    Y = np.asarray(Y, float)
    if not len(Y):
        return None
    lo, hi = Y.min(0), Y.max(0)
    return hi + 0.1 * (hi - lo)


def common_ref(Y) -> np.ndarray | None:
    """两臂比较的事后共同参考点：并集的最差 + 10 % 极差；某一维极差为 0（只有 1 个点等）时余量取 10 % |最差| + 1e-9（不让参考点贴在点上）。"""
    Y = np.asarray(Y, float).reshape(-1, 2)
    if not len(Y):
        return None
    lo, hi = Y.min(0), Y.max(0)
    span = np.where(hi - lo > 0, hi - lo, 0.1 * np.abs(hi) + 1e-9)
    return hi + 0.1 * span


def rankdata(v) -> np.ndarray:
    """平均秩（并列取平均），= scipy.stats.rankdata(method="average")。"""
    v = np.asarray(v, float)
    order = np.argsort(v, kind="mergesort")
    sv = v[order]
    ranks = np.empty(len(v), float)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a, b) -> float | None:
    """Spearman ρ（秩的 Pearson 相关）；n < 3 或某一边全部并列 → None。"""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or len(a) != len(b):
        return None
    ra, rb = rankdata(a), rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def warm_ids_of(st_dst: dict | None, st_src: dict | None, r_src: list) -> tuple[list, str]:
    """目标阶段臂的共同起点（冻结热启动）：neckopt_p<dst>.json 的 warm_start_ids；还没有时按 stage_neckopt.warm_from_select 的规则
    （round 0 → init，pool_idx None → 收编）从来源阶段的状态文件预计；状态文件也没有时按作业标签（init / smoke）预计。"""
    ids = (st_dst or {}).get("warm_start_ids")
    if isinstance(ids, list) and ids:
        return [str(j) for j in ids], "neckopt_p<dst>.json warm_start_ids (frozen)"
    out = []
    for r in ((st_src or {}).get("records") or []):
        if isinstance(r, dict) and r.get("job_id") and (r.get("round") == 0 or r.get("pool_idx") is None) and r["job_id"] not in out:
            out.append(r["job_id"])
    if out:
        return out, "projected from neckopt_p<src>.json (round 0 + adopted; not frozen yet)"
    return [r["job_id"] for r in r_src if r.get("source") in ("init", "adopted")], "projected from job tags (no state file)"


def state_split(st: dict | None) -> dict | None:
    """neckopt_p<p>.json 的分账，与 arms_gate.split_src、stage_neckopt.warm_from_select / bo_async 相同：listed = 记录 ∪ 待定的作业 id；
    adopted = 记录里 round ≠ 0 且 pool_idx None（任何 round：bo_async 收编在算的作业时待定 pool_idx None，算完记成 round len(recs)+1）
    ∪ 待定里 pool_idx None；picks = 记录里 round ≠ 0 且 pool_idx 有值 ∪ 待定里 pool_idx 有值；记录里 round 0 = init。
    状态文件读不到 / 不是对象 → None（全部行按标签，见 arm_kind）；读得到时没列出的行按收编算（arm_kind）。只读。"""
    if not isinstance(st, dict):
        return None
    recs = [r for r in (st.get("records") or []) if isinstance(r, dict) and r.get("job_id")]
    pend = st.get("pending")
    pend = {str(j): p for j, p in pend.items() if isinstance(p, dict)} if isinstance(pend, dict) else {}
    return {"listed": {r["job_id"] for r in recs} | set(pend),
            "adopted": ({r["job_id"] for r in recs if r.get("round") != 0 and r.get("pool_idx") is None}
                        | {j for j, p in pend.items() if p.get("pool_idx") is None}),
            "picks": ({r["job_id"] for r in recs if r.get("round") != 0 and r.get("pool_idx") is not None}
                      | {j for j, p in pend.items() if p.get("pool_idx") is not None})}


def arm_kind(r: dict, split: dict | None = None) -> str:
    """一行在它那一臂里的身份：'pick'（驱动自己的选点）/ 'adopted'（收编的作业）/ 'init'（round 0）/ 'other'（round 不是数）。
    状态文件列出的作业按 state_split（收编优先：同一 id 既是选点又是收编时算收编）。状态文件读得到（split 不是 None）却没列出的行：
    任何 round（含 0、None）、任何标签都 = 'adopted'——不是驱动提交的（bo_async 提交后立即写进待定并保存）= arms_gate.split_src
    的 'unadopted'，bo_async 下次启动时以 round -1、pool_idx None 收编（build() 只对 DONE / FAILED 的行这样标：NEW 的可能是驱动
    还没保存的选点，不进计数）。状态文件读不到（split None）时按行自己的 round / pool_idx：round 0 = init；round 有值且 ≠ 0：
    pool_idx 有值 = 选点、None = 收编；round None = 自有。build() 给的没列出的行 round 来自标签（init → 0、smoke* → -1、其他 None）、
    pool_idx 为空，即标签规则：init 不算、smoke* 收编、其他算自有。"""
    j = r.get("job_id")
    if split is not None:
        if j in split["listed"]:
            if j in split["adopted"]:
                return "adopted"
            return "pick" if j in split["picks"] else "init"
        return "adopted"                                                   # 读得到却没列出：不是驱动提交的（= split_src 'unadopted'），任何 round、任何标签
    rd = r.get("round")
    if rd is None:
        return "pick"
    if isinstance(rd, bool) or not isinstance(rd, (int, float)):
        return "other"
    if rd == 0:
        return "init"
    return "pick" if r.get("pool_idx") is not None else "adopted"


def own_pick(r: dict, split: dict | None = None) -> bool:
    """来源阶段一行是不是该臂驱动自己的选点（调用方另查：不在冻结热启动里、DONE / FAILED）= arm_kind(r, split) == 'pick'：
    neckopt_p<src>.json 记录里 round ≠ 0 且 pool_idx 有值（round -1 = 停机期间算完、重启时以 round -1 收编、保留 pool_idx 的选点），
    或待定里 pool_idx 有值；收编的作业（pool_idx None，任何 round）与 init 不算。状态文件读得到却没列出的行不算（收编，arm_kind）；
    状态文件读不到时按标签。"""
    return arm_kind(r, split) == "pick"


def arms_compare(r_src, r_dst, warm, warm_src, vec2, caps, src, dst, have_dst, split_src=None, split_dst=None) -> dict:
    """两臂相同自有评估数下的 2 维 HV(转动, 接触)。共同起点 B = 冻结热启动（两臂都从它出发：来源阶段臂的 init + 收编 = 目标阶段臂的热启动行）。
    来源阶段臂自有 = 来源阶段不在 B 里、own_pick(r, split_src) 的作业（驱动的选点，按 neckopt_p<src>.json 的分账 state_split：记录里
    round ≠ 0 且 pool_idx 有值、含 round -1 = 重启后收编的选点，或待定里 pool_idx 有值；收编的作业 = pool_idx None、任何 round，不算）；
    目标阶段臂自有 = sb<dst>_ 作业中按 split_dst 不是收编的（arm_kind ≠ 'adopted'）。状态文件读得到却没列出的行两臂都算收编、不算
    （= arms_gate.split_src 'unadopted'；个数在 own_*_unlisted_excluded）；split 为 None（状态文件读不到）时按标签。
    都只数 DONE + FAILED，按完成先后；FAILED 计一次评估、不加点。每个面板（不设上限 / 去骨 ≤ cap）的参考点 = common_ref(该面板内两臂
    全部可行行的并集，含 B)，两臂共用。"""
    W = set(warm)
    key = done_key                                                         # epoch 秒（夏令时结束那一小时也对）
    base = [r for r in r_src if r["job_id"] in W]
    done_s = [r for r in r_src if r["job_id"] not in W and r["state"] in ("DONE", "FAILED")]
    own_s = sorted([r for r in done_s if own_pick(r, split_src)], key=key)
    done_d = [r for r in r_dst if r["state"] in ("DONE", "FAILED")]
    own_d = sorted([r for r in done_d if arm_kind(r, split_dst) != "adopted"], key=key)

    def by_tag(rr, sp):
        return sum(1 for r in rr if sp is None or r["job_id"] not in sp["listed"])

    def unlisted(rr, sp):                                                  # 读得到的状态文件没列出、按收编去掉的
        return 0 if sp is None else sum(1 for r in rr if r["job_id"] not in sp["listed"] and arm_kind(r, sp) == "adopted")
    panels = []
    for cap in [None] + [float(c) for c in caps]:
        def ok(r, cap=cap):
            return bool(r["feasible"]) and (cap is None or (r.get("bone_cm3") is not None and r["bone_cm3"] <= cap))
        U = [vec2(r) for r in base + own_s + own_d if ok(r)]
        ref = common_ref(U)
        cur = {}
        for arm, own in (("src", own_s), ("dst", own_d)):
            pts = [vec2(r) for r in base if ok(r)]
            hv0 = hv2(np.array(pts).reshape(-1, 2), ref) if ref is not None else 0.0
            tr = [{"n": 0, "hv": hv0}]
            for k, r in enumerate(own, 1):
                if ok(r):
                    pts.append(vec2(r))
                tr.append({"n": k, "job_id": r["job_id"], "feasible": ok(r),
                           "hv": hv2(np.array(pts).reshape(-1, 2), ref) if ref is not None else 0.0})
            cur[arm] = tr
        n_c = min(len(own_s), len(own_d))
        marks = sorted(set(list(range(0, n_c + 1, 10)) + [n_c]))
        panels.append({"cap_cm3": cap, "ref_point": None if ref is None else ref.tolist(), "n_feasible_union": len(U),
                       "n_feasible_base": sum(1 for r in base if ok(r)), "n_common": n_c,
                       "at_n": [{"n": n, "hv_src": cur["src"][n]["hv"], "hv_dst": cur["dst"][n]["hv"]} for n in marks],
                       "final": {"src": {"n": len(own_s), "hv": cur["src"][-1]["hv"]}, "dst": {"n": len(own_d), "hv": cur["dst"][-1]["hv"]}},
                       "trace_src": cur["src"], "trace_dst": cur["dst"]})
    return {"src": src, "dst": dst, "have_dst": have_dst, "baseline_n": len(base), "baseline_source": warm_src,
            "baseline_feasible": sum(1 for r in base if r["feasible"]), "own_src": len(own_s), "own_dst": len(own_d),
            "own_src_readopted": sum(1 for r in own_s if r.get("round") == -1),
            "own_src_unrecorded": sum(1 for r in own_s if split_src is not None and r["job_id"] in split_src["listed"]
                                      and r.get("round") is None),                   # 状态文件列出（待定）、还没记进记录的选点
            "own_src_adopted_excluded": sum(1 for r in done_s if arm_kind(r, split_src) == "adopted"),
            "own_src_unlisted_excluded": unlisted(done_s, split_src),
            "own_src_by_tag": by_tag(own_s, split_src),
            "own_dst_adopted_excluded": len(done_d) - len(own_d), "own_dst_unlisted_excluded": unlisted(done_d, split_dst),
            "own_dst_by_tag": by_tag(own_d, split_dst),
            "split_src": f"neckopt_p{src}.json" if split_src is not None else "job tags (state file not available)",
            "split_dst": f"neckopt_p{dst}.json" if split_dst is not None else "job tags (state file not available)",
            "own_rule": OWN_RULE,
            "frame": "[log10(max(rot_first_deg, 1e-3)), -contact_area_load2_mm2] (minimised)",
            "ref_rule": "per panel: worst + 10 % range of the union of both arms' feasible rows in that panel (shared start included); "
                        "a zero range takes 10 % of |worst| + 1e-9",
            "panels": panels}


def _delta_label(vals: dict) -> str:
    ks = [k for k in vals if k not in ("None", "'absent'", "'no spec'")]
    if len(vals) == 1 and ks:
        try:
            return f"{float(ks[0]):g}"
        except ValueError:
            return ks[0]
    return "mixed" if vals else "?"


def init_delta_compare(cmp_ph: int, src: int, results: pathlib.Path, queue: pathlib.Path, r_src: list, rec_by_job: dict) -> dict:
    """来源阶段的初始批（round 0）与 cmp_ph 阶段的初始批逐个配对（阶段 13 vs 11：同一批池点，δ 0.10 vs 0.025）。
    cmp_ph 一边用其状态文件里存的记录（不重算）；来源阶段一边用本报告的行（重算或存的指标）。配对：两边都有 pool_idx 时按 pool_idx，
    否则按 13 个设计变量（四舍五入到 1e-9）。另报两边 spec.json 的 delta 分布、配对设计的单位向量 x 的最大差。"""
    st, err = read_json(results / f"neckopt_p{cmp_ph}.json", tries=5)
    out = {"ref_phase": cmp_ph, "src_phase": src, "ref_state": "ok" if isinstance(st, dict) else (err or "unreadable")}
    A = [r for r in ((st or {}).get("records") or []) if isinstance(r, dict) and r.get("round") == 0 and r.get("job_id")]
    B = [r for r in r_src if r["round"] == 0]

    def spec_delta(jid):
        sp, _ = read_json(queue / jid / "spec.json")
        return repr(sp.get("delta", "absent")) if isinstance(sp, dict) else repr("no spec")

    def dkey_rec(r):
        d = dict(r.get("design") or {})
        d["h_cut"] = r.get("h_cut")
        v = [num(d.get(k)) for k in VARS13]
        return None if any(x is None for x in v) else tuple(round(x, 9) for x in v)

    def dkey_row(r):
        v = [num(r.get(k)) for k in VARS13]
        return None if any(x is None for x in v) else tuple(round(x, 9) for x in v)

    by_pool = {r["pool_idx"]: r for r in A if r.get("pool_idx") is not None}
    by_key = {}
    for r in A:
        k = dkey_rec(r)
        if k is not None:
            by_key.setdefault(k, r)
    da, db = {}, {}
    for r in A:
        k = spec_delta(r["job_id"])
        da[k] = da.get(k, 0) + 1
    for r in B:
        k = spec_delta(r["job_id"])
        db[k] = db.get(k, 0) + 1
    MK = ("rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um", "bone_mm3")
    pairs, used, xdiff = [], set(), 0.0
    for r in sorted(B, key=lambda r: ((rec_by_job.get(r["job_id"]) or {}).get("pool_idx") if (rec_by_job.get(r["job_id"]) or {}).get("pool_idx") is not None else 10 ** 9, r["job_id"])):
        rec_b = rec_by_job.get(r["job_id"]) or {}
        pi = rec_b.get("pool_idx")
        a, how = (by_pool.get(pi), "pool_idx") if pi is not None else (None, None)
        if a is None:
            k = dkey_row(r)
            a, how = (by_key.get(k), "design") if k is not None else (None, None)
        if a is None or a["job_id"] in used:
            pairs.append({"pool_idx": pi, "how": None, "src": {"job_id": r["job_id"], "state": r["state"], "bonded": r.get("bonded"),
                                                                  **{k: num(r.get(k)) for k in MK}}, "ref": None, "both_metrics": False})
            continue
        used.add(a["job_id"])
        if isinstance(a.get("x"), list) and isinstance(rec_b.get("x"), list) and len(a["x"]) == len(rec_b["x"]):
            xdiff = max(xdiff, max((abs(float(p) - float(q)) for p, q in zip(a["x"], rec_b["x"])), default=0.0))
        ra = {"job_id": a["job_id"], "ok": bool(a.get("ok")), "bonded": a.get("bonded") if a.get("bonded") is not None else
              (None if a.get("fric_only") is None else not a.get("fric_only")), **{k: num(a.get(k)) for k in MK}}
        rb = {"job_id": r["job_id"], "state": r["state"], "has_metrics": r["has_metrics"], "bonded": r.get("bonded"), **{k: num(r.get(k)) for k in MK}}
        both = r["has_metrics"] and ra["ok"] and all(ra[k] is not None and rb[k] is not None for k in MK[:3])
        pairs.append({"pool_idx": pi if pi is not None else a.get("pool_idx"), "how": how, "src": rb, "ref": ra, "both_metrics": bool(both)})
    pb = [p for p in pairs if p["both_metrics"]]
    rho = {}
    for k in MK:
        v = [(p["ref"][k], p["src"][k]) for p in pb if p["ref"][k] is not None and p["src"][k] is not None]
        rho[k] = {"rho": spearman([x for x, _ in v], [y for _, y in v]) if v else None, "n": len(v)}
    ratio = {}
    for k in MK[:3]:
        v = [p["src"][k] / p["ref"][k] for p in pb if p["ref"][k] not in (None, 0.0) and p["src"][k] is not None]
        ratio[k] = {"median": float(np.median(v)) if v else None, "min": min(v) if v else None, "max": max(v) if v else None, "n": len(v)}
    out.update({"pairing": "pool_idx" if any(p["how"] == "pool_idx" for p in pairs) else ("design" if pairs else "none"),
                "n_ref_init": len(A), "n_src_init": len(B), "n_pairs": sum(1 for p in pairs if p["how"]),
                "n_pairs_pool_idx": sum(1 for p in pairs if p["how"] == "pool_idx"), "n_pairs_design": sum(1 for p in pairs if p["how"] == "design"),
                "n_src_unpaired": sum(1 for p in pairs if not p["how"]), "n_ref_unpaired": len(A) - len(used), "n_both_metrics": len(pb),
                "x_max_abs_diff": xdiff, "ref_deltas": da, "src_deltas": db, "ref_delta_label": _delta_label(da), "src_delta_label": _delta_label(db),
                "spearman": rho, "ratio_src_over_ref": ratio, "pairs": pairs})
    return out


# ------------------------------------------------------------------------------------------------- 主体
def build(args) -> dict:
    src, dst = int(args.src), int(args.dst)
    legacy = (src, dst) == (11, 12)                                        # 默认阶段对：输出与从前逐字相同
    PH = (src, dst)
    root = pathlib.Path(os.path.expanduser(args.root)).resolve()
    code = pathlib.Path(os.path.expanduser(args.code)).resolve() if args.code else root / "code"
    out = Out(pathlib.Path(os.path.expanduser(args.out)).resolve() if args.out else root / "deck" / f"p{src}_3406")
    queue, results = root / "queue", root / "results"
    os.environ.setdefault("MPLCONFIGDIR", str(out.path("_mpl")))
    t_now = time.time()

    sys.path.insert(0, str(code))
    sys.path.insert(0, str(code / "v2"))
    import jobs as J                                                       # noqa: E402
    J.QROOT, J.RESULTS = queue, results
    import stage_neckopt as SN                                             # noqa: E402
    if not legacy:
        missing = [p for p in PH if p not in SN.PHASES]
        if missing:
            raise SystemExit(f"[p11_report] PHASES{missing} not defined in {code / 'v2' / 'stage_neckopt.py'}: sync the code that defines "
                             f"phases {src} / {dst}")
    phs = {} if legacy else {p: SN.Phase(p) for p in PH}

    def _mm_of(p):                                                         # 可行用的微动上限：--mm-limit 覆盖；默认对 = MM_LIMIT；其他 = Phase.mm_limit
        if args.mm_limit is not None:
            return None if args.mm_limit == "none" else float(args.mm_limit)
        if legacy:
            return float(SN.MM_LIMIT)
        return getattr(phs[p], "mm_limit", SN.MM_LIMIT)
    mm_by = {p: _mm_of(p) for p in PH}
    mm_phase = {p: (float(SN.MM_LIMIT) if legacy else getattr(phs[p], "mm_limit", SN.MM_LIMIT)) for p in PH}   # 阶段自身的设置（驱动用的）
    mm_cli = args.mm_limit                                                 # None = 没给 --mm-limit；"none" / µm = 命令行的事后口径
    mm_same = mm_cli is not None and all(mm_by[p] == mm_phase[p] for p in PH)   # 命令行的值 = 阶段自身的设置（规则与驱动相同，不是事后口径）
    mm_limit = mm_by[src]
    if mm_by[src] != mm_by[dst]:
        warn(f"micromotion limits differ: phase {src} {mm_by[src]}, phase {dst} {mm_by[dst]} (each phase's rows use their own)")

    def _score_of(p):                                                      # record_of 的参数：默认对 = ("none", "v3")（与从前相同）
        if legacy:
            return ("none", "v3"), {}
        ph_ = phs[p]
        return (ph_.sed, ph_.metric), dict(getattr(ph_, "mm_kw", None) or {})
    scoring = {p: _score_of(p) for p in PH}
    vm_limit = float(args.vm_limit if args.vm_limit is not None else SN.VM_LIMIT)
    rot_floor = float(getattr(SN, "ROT_FLOOR", 1e-3))
    ver_txt = (code / "VERSION").read_text(errors="replace").strip() if (code / "VERSION").exists() else None

    # ---- 状态文件
    states = {}
    for p in PH:
        st, err = read_json(results / f"neckopt_p{p}.json", tries=5)
        if st is None and err != "missing":
            warn(f"neckopt_p{p}.json unreadable after retries ({err}); using job directories only")
        states[p] = st if isinstance(st, dict) else None
    p10, err10 = read_json(pathlib.Path(os.path.expanduser(args.p10)) if args.p10 else results / "neckopt_p10.json", tries=3)
    if p10 is None:
        warn(f"phase-10 reference not available ({err10}); comparison figure skipped")

    # ---- 作业目录
    infos = {}
    if queue.exists():
        for d in sorted(queue.glob("sb*")):
            if d.is_dir() and group_of(d.name) is not None:
                try:
                    infos[d.name] = job_info(d, J)
                except Exception as e:                                    # noqa: BLE001
                    warn(f"{d.name}: unreadable job dir ({type(e).__name__}: {str(e)[:100]})")
    else:
        warn(f"queue directory {queue} does not exist")
    rec_by_job = {}
    for p in PH:
        for r in ((states[p] or {}).get("records") or []):
            if isinstance(r, dict) and r.get("job_id"):
                rec_by_job[r["job_id"]] = {**r, "_phase": p}
    splits = {p: state_split(states[p]) for p in PH}                       # 驱动的分账（选点 / 收编 / init），两臂对比与 designs.csv 标签用
    pend_by_job = {}                                                       # 待定（已提交、还没记进记录）：pool_idx 的后备来源
    for p in PH:
        pend = (states[p] or {}).get("pending")
        if isinstance(pend, dict):
            for k, v in pend.items():
                if isinstance(v, dict):
                    pend_by_job.setdefault(str(k), v)
    for p in PH:                                                           # 状态文件里有、目录里没有的作业也列出来
        st = states[p] or {}
        for j in list(((st.get("records") or []))) + [{"job_id": k} for k in (st.get("pending") or {})]:
            jid = j.get("job_id") if isinstance(j, dict) else None
            if jid and jid not in infos:
                infos[jid] = {"job_id": jid, "group": p, "state": "MISSING", "kind": "design", "design": (j.get("design") or {}),
                              "h_cut": num(j.get("h_cut")), "bonded": j.get("bonded")}
                warn(f"{jid}: listed in neckopt_p{p}.json but no job directory")
    clock = settle_clock(infos, set(PH) | {"ref"}, t_now)                  # 重复那一小时里 mtime 定不了的时间再按提交 ≤ 完成定

    # ---- 指标（DONE 设计）
    design_jobs = [i for i in infos.values() if i["group"] in PH and i.get("kind") in ("design", "variant", None)]
    done_jobs = [i for i in design_jobs if i["state"] == "DONE"]
    mode = args.metrics
    if mode == "rescore":
        ok_cache, msg = femur_cache_ok({i.get("femur_id") for i in done_jobs}) if done_jobs else (True, "no DONE jobs")
        log(f"femur cache check: {msg}")
        if not ok_cache:
            warn(f"femur distance-field cache missing or unverifiable ({msg}); NOT rescoring (build would write the cache) — "
                 "using metrics stored in the state files")
            mode = "stored"
    cache_name = "_cache/metrics.json"
    cache = {}
    ckey = _code_key(code) if legacy else _code_key(code, REPORT_VERSION_PAIR + json.dumps(
        {str(p): [list(scoring[p][0]), scoring[p][1]] for p in PH}, sort_keys=True))
    if mode == "rescore" and not args.no_cache:
        c, _ = read_json(out.path(cache_name))
        if isinstance(c, dict) and c.get("code_key") == ckey:
            cache = c.get("rows") or {}
    if mode == "rescore" and done_jobs:
        memoize_builds()
    n_new, n_hit, t0 = 0, 0, time.perf_counter()
    mismatch = []
    for i in design_jobs:
        jid = i["job_id"]
        stored = rec_by_job.get(jid)
        if i["state"] != "DONE":
            i["m"] = metrics_stored(stored) if i["state"] == "MISSING" else {"metrics_source": "none"}
            continue
        if mode == "stored":
            i["m"] = metrics_stored(stored)
            continue
        rk = _result_key(queue / jid)
        hit = cache.get(jid)
        if hit and hit.get("key") == rk:
            i["m"] = {**hit["row"], "metrics_source": "rescored(cache)"}
            n_hit += 1
        else:
            try:
                i["m"] = metrics_rescore(jid, SN) if legacy else metrics_rescore(jid, SN, *scoring[i["group"]])
            except Exception as e:                                        # noqa: BLE001
                warn(f"{jid}: rescoring failed ({type(e).__name__}: {str(e)[:120]}); using stored record")
                traceback.print_exc()
                i["m"] = metrics_stored(stored)
                continue
            cache[jid] = {"key": rk, "row": _clean(i["m"])}
            n_new += 1
        if stored:                                                        # 与驱动记下的值核对（代码漂移 / 结果被改写）
            for k in ("rot_first_deg", "contact_area_load2_mm2", "f1_body_p95_um", "bone_mm3"):
                a, b = num(stored.get(k)), num(i["m"].get(k))
                if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-6 * max(1.0, abs(a))):
                    mismatch.append({"job_id": jid, "key": k, "stored": a, "rescored": b})
    if mode == "rescore" and n_new:
        out.json(cache_name, {"code_key": ckey, "rows": cache, "updated": fmt_t(t_now)})
    t_metrics = time.perf_counter() - t0
    log(f"metrics: mode {mode}; {len(done_jobs)} DONE designs, {n_new} newly computed, {n_hit} from cache, {t_metrics:.0f} s")
    if mismatch:
        warn(f"{len(mismatch)} stored-vs-rescored differences (first: {mismatch[0]})")

    # ---- 每个设计一行
    ext_rows = not legacy or args.compare == "on"                          # 默认对（不加 --compare on）：designs.csv 与从前逐字相同
    rows = []
    for i in design_jobs:
        m = i.get("m") or {}
        d = i.get("design") or {}
        stored = rec_by_job.get(i["job_id"]) or {}
        rnd = stored.get("round")
        if rnd is None:
            tag = str(i.get("tag") or "")
            rnd = 0 if tag == "init" else (-1 if tag.startswith("smoke") else None)
        pidx = stored.get("pool_idx") if stored else (pend_by_job.get(i["job_id"]) or {}).get("pool_idx")
        source = {0: "init", -1: "adopted"}.get(rnd, "bo" if rnd is not None else "unrecorded")
        sp = splits.get(i["group"])
        if ext_rows and sp is not None and i["job_id"] in sp["listed"]:  # 状态文件列出的作业：标签按驱动的分账（没列出的照旧按标签）
            kind = arm_kind(i, sp)
            if kind == "adopted":                                         # 收编的作业：pool_idx None，任何 round（含待定里的）
                source = "adopted"
            elif kind == "pick":
                source = READOPTED if stored.get("round") == -1 else ("bo" if stored else "unrecorded")   # round -1 = 停机期间算完、重启时收编
        elif ext_rows and sp is not None and i["state"] in ("DONE", "FAILED"):
            source = "adopted"                                            # 读得到却没列出、已算完：不是驱动提交的（= split_src 'unadopted'）；NEW 的照旧
        sol = i.get("solve") or {}
        bone = num(m.get("bone_mm3"))
        if bone is None:
            bone = num((i.get("prep") or {}).get("bone_mm3"))
        r = {"job_id": i["job_id"], "phase": i["group"], "state": i["state"], "round": rnd,
             **({"pool_idx": pidx} if ext_rows else {}), "source": source,
             "bonded": i.get("bonded"), "failed_level": (i.get("failed") or {}).get("level"),
             "failed_stage": (i.get("failed") or {}).get("stage"), "failed_reason": (i.get("failed") or {}).get("reason"),
             **{k: num(d.get(k)) for k in VARS13 if k != "h_cut"}, "h_cut": i.get("h_cut"),
             **{k: m.get(k) for k in REC_KEYS if k not in ("bone_mm3", "fric_only")},
             **{k: m.get(k) for k in STAB_EXTRA},
             "bone_mm3": bone, "bone_cm3": None if bone is None else bone / 1e3,
             "A0": num(m.get("A0")) if num(m.get("A0")) is not None else num((i.get("prep") or {}).get("A0")),
             "n_tet": (i.get("prep") or {}).get("n_tet"), "fric_only": bool(m.get("fric_only")) if m else (i.get("bonded") is False),
             "solve_fric_s": num((sol.get("m_fric") or {}).get("wall_s")), "solve_bond_s": num((sol.get("m_bond") or {}).get("wall_s")),
             "created": i.get("created"), "done": fmt_t(i.get("t_end")),
             "_t_done": None if i.get("t_end") is None else float(math.floor(i["t_end"])),   # 排序用的 epoch 秒（= 从前解析 done 的值；不进 designs.csv）
             "turnaround_min": None if i.get("t_end") is None or i.get("t_created") is None else (i["t_end"] - i["t_created"]) / 60,
             "metrics_source": m.get("metrics_source"), "c_driver": m.get("c_driver")}
        r["has_metrics"] = has_metrics({**m, "fric_only": r["fric_only"]}) if i["state"] == "DONE" else False
        r["feasible"] = is_feasible({**m, "fric_only": r["fric_only"]}, mm_by.get(i["group"], mm_limit), vm_limit) if r["has_metrics"] else False
        rows.append(r)
    rows.sort(key=lambda r: (r["phase"], *done_key(r)))
    if ext_rows:                                                           # 读得到的状态文件没列出的 DONE / FAILED 行：按收编算（不论标签），告警
        for p in PH:
            sp = splits.get(p)
            ul = [r for r in rows if sp is not None and r["phase"] == p and r["state"] in ("DONE", "FAILED") and r["job_id"] not in sp["listed"]]
            if ul:
                how = ", ".join(f"{r['job_id']} -> {arm_kind(r, sp)}" for r in ul[:12]) + (f", … ({len(ul) - 12} more)" if len(ul) > 12 else "")
                warn(f"phase {p}: {len(ul)} DONE / FAILED job(s) not listed in neckopt_p{p}.json although it was read ({how}): not driver "
                     f"submissions (= arms_gate.split_src 'unadopted'; bo_async adopts them as round -1, pool_idx None at its next start), "
                     f"so adopted and not counted as own evaluations, whatever the tag")

    # ---- 计数
    def counts(group):
        js = [i for i in infos.values() if i["group"] == group]
        st = {}
        for i in js:
            st[i["state"]] = st.get(i["state"], 0) + 1
        fl = {}
        for i in js:
            if i.get("failed"):
                k = f"{i['failed']['level']}/{i['failed']['stage']}"
                fl[k] = fl.get(k, 0) + 1
        rr = [r for r in rows if r["phase"] == group]
        return {"n_dirs": len(js), "by_state": st, "failed_by_level": fl,
                "pending": sum(st.get(k, 0) for k in ("NEW", "READY", "CLAIMED", "SOLVED")),
                "done": st.get("DONE", 0), "failed": st.get("FAILED", 0),
                "done_with_metrics": sum(r["has_metrics"] for r in rr), "done_without_metrics": sum(r["state"] == "DONE" and not r["has_metrics"] for r in rr),
                "feasible": sum(r["feasible"] for r in rr), "bonded": sum(1 for r in rr if r["bonded"]),
                "fric_only": sum(1 for r in rr if r["bonded"] is False),
                "kinds": sorted({str(i.get("kind")) for i in js}),
                "failed_jobs": [{"job_id": i["job_id"], **i["failed"]} for i in js if i.get("failed")][:40]}

    cnt = {f"phase{src}": counts(src), f"phase{dst}": counts(dst), "ref_sb": counts("ref")}
    other = sorted({i["group"] for i in infos.values()} - {src, dst, "ref"}, key=str)
    for g in other:
        cnt[f"phase{g}"] = counts(g)

    def state_summary(p):
        st = states[p]
        if not st:
            return None
        recs = st.get("records") or []
        dirs = {i["job_id"] for i in infos.values() if i["group"] == p}
        known = {r.get("job_id") for r in recs if isinstance(r, dict)} | set((st.get("pending") or {}).keys())
        return {"mode": st.get("mode", "sync (bo)"), "updated": st.get("updated"), "budget": st.get("budget"), "inflight": st.get("inflight"),
                "n_init": st.get("n_init"), "n_submitted": st.get("n_submitted"), "records": len(recs), "pending": len(st.get("pending") or {}),
                "records_ok": sum(1 for r in recs if isinstance(r, dict) and r.get("ok")),
                "pool_size": st.get("pool_size"), "ref_point": st.get("ref_point"), "hv_hist_n": len(st.get("hv_hist") or []),
                "hv_last": (st.get("hv_hist") or [{}])[-1].get("hv") if st.get("hv_hist") else None,
                "stopped_early": st.get("stopped_early"), "warm_start_n": st.get("warm_start_n"), "bond_every": st.get("bond_every"),
                "intact_job": st.get("intact_job"), "metric": (recs[0].get("metric") if recs and isinstance(recs[0], dict) else None),
                "dirs_not_in_state": sorted(dirs - known)[:40], "n_dirs_not_in_state": len(dirs - known),
                **({} if legacy else {"mm_limit": st.get("mm_limit", "absent (= 150)"), "fric": st.get("fric"),
                                      "warm_start_ids_n": len(st.get("warm_start_ids") or []) if "warm_start_ids" in st else None})}

    state_sum = {f"p{p}": state_summary(p) for p in PH}

    # 初始批（round 0）—— 计划 §5 的闸门：不 ok 比例 > 15 % 暂停
    init_rows = [r for r in rows if r["phase"] == src and r["round"] == 0]
    init_done = [r for r in init_rows if r["state"] in ("DONE", "FAILED")]
    init = {"n": len(init_rows), "completed": len(init_done), "with_metrics": sum(r["has_metrics"] for r in init_done),
            "feasible": sum(r["feasible"] for r in init_done)}
    init["not_ok_frac"] = None if not init_done else 1.0 - init["with_metrics"] / len(init_done)
    init["gate_15pct"] = None if init["not_ok_frac"] is None else ("pause" if init["not_ok_frac"] > 0.15 else "pass")

    # ---- 求解时间与产出
    def walls(group):
        js = [i for i in infos.values() if i["group"] == group]
        per = {}
        for i in js:
            for stem, v in (i.get("solve") or {}).items():
                e = per.setdefault(stem, {"ok": [], "fail": 0})
                if v.get("status") == "OK" and v.get("wall_s") is not None:
                    e["ok"].append(v["wall_s"])
                else:
                    e["fail"] += 1
        outw = {stem: {**stats(e["ok"]), "n_not_ok": e["fail"]} for stem, e in per.items()}
        tend = sorted(i["t_end"] for i in js if i["state"] == "DONE" and i.get("t_end"))
        tcre = [i["t_created"] for i in js if i.get("t_created")]
        thr = {"n_done": len(tend), "first_done": fmt_t(tend[0]) if tend else None, "last_done": fmt_t(tend[-1]) if tend else None,
               "first_created": fmt_t(min(tcre)) if tcre else None}
        if len(tend) >= 2 and tend[-1] > tend[0]:
            thr["per_h_first_to_last_done"] = (len(tend) - 1) / ((tend[-1] - tend[0]) / 3600)
        if tcre and tend:
            thr["per_h_since_first_created"] = len(tend) / max((t_now - min(tcre)) / 3600, 1e-9)
        w6 = [t for t in tend if t >= t_now - 6 * 3600]
        if tcre and t_now - min(tcre) >= 6 * 3600:
            thr["per_h_last_6h"] = len(w6) / 6.0
        thr["turnaround_min"] = stats([(i["t_end"] - i["t_created"]) / 60 for i in js
                                       if i["state"] == "DONE" and i.get("t_end") and i.get("t_created")])
        return {"solve_wall_s": outw, "throughput": thr}

    wall = {f"phase{src}": walls(src), f"phase{dst}": walls(dst), "ref_sb": walls("ref")}

    # ---- 指标分布
    MKEYS = ("rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_perm_deg", "contact_area_load2_mm2", "contact_frac_load2",
             "f1_body_p95_um", "subsid_first_um", "subsid_perm_um", "bone_cm3", "A0", "n_tet", "sed_chg_pct", "vm_p99", "L", "alpha", "h_cut", "m")
    dist = {}
    for p in PH:
        rr = [r for r in rows if r["phase"] == p and r["has_metrics"]]
        if rr:
            dist[f"phase{p}"] = {k: stats([r.get(k) for r in rr]) for k in MKEYS}
            dist[f"phase{p}_feasible"] = {k: stats([r.get(k) for r in rr if r["feasible"]]) for k in MKEYS}

    # ---- 前沿
    def vec2(r):
        return [math.log10(max(float(r["rot_first_deg"]), rot_floor)), -float(r["contact_area_load2_mm2"])]

    def front_of(rr, k3=False, scale=1.0):
        rr = [r for r in rr if r["feasible"] and (not k3 or r.get("bone_mm3") is not None)]
        if not rr:
            return []
        P = np.array([vec2(r) + ([r["bone_mm3"] * scale] if k3 else []) for r in rr])
        return sorted([rr[i] for i in np.nonzero(nondom_mask(P))[0]], key=lambda r: r["contact_area_load2_mm2"])

    FR_KEYS = ("job_id", "phase", "round", "bonded", "rot_first_deg", "rot_axial_first_deg", "rot_tilt_first_deg", "rot_perm_deg",
               "contact_area_load2_mm2", "f1_body_p95_um", "subsid_first_um", "bone_cm3", "A0", "sed_chg_pct", "vm_p99", *VARS13)

    def slim(rr):
        return [{k: r.get(k) for k in FR_KEYS} for r in rr]

    r11 = [r for r in rows if r["phase"] == src]                         # 名字沿用 11 / 12 = 来源 / 目标阶段
    r12 = [r for r in rows if r["phase"] == dst]
    have_p12 = bool(states[dst]) or bool(r12)
    pooled = r11 + r12
    front11 = front_of(r11)
    front_pooled = front_of(pooled) if have_p12 else front11

    # HV（驱动坐标）
    st11 = states[src] or {}
    ref2 = st11.get("ref_point")
    ref2_src = f"driver (neckopt_p{src}.json)"
    if not (isinstance(ref2, list) and len(ref2) == 2 and all(num(v) is not None for v in ref2)):
        fe = [vec2(r) for r in r11 if r["feasible"]]
        ref2 = None if not fe else ref_point_of(np.array(fe)).tolist()
        ref2_src = f"computed from current feasible phase-{src} points (provisional; driver ref not set yet)"

    def trace(rr, ref, k3=False, scale=1.0, base=None):
        ev = sorted([r for r in rr if r["state"] in ("DONE", "FAILED")], key=done_key)
        pts = [list(b) for b in (base or [])]
        outt = [{"n": 0, "hv": hv_any(pts, ref) if pts else 0.0}] if base is not None else []
        for k, r in enumerate(ev, 1):
            if r["feasible"] and (not k3 or r.get("bone_mm3") is not None):
                pts.append(vec2(r) + ([r["bone_mm3"] * scale] if k3 else []))
                P = np.array(pts)
                pts = P[nondom_mask(P)].tolist()
            outt.append({"n": k, "job_id": r["job_id"], "done": r["done"], "hv": hv_any(pts, ref) if (pts and ref is not None) else 0.0})
        return outt

    hv11 = trace(r11, ref2) if ref2 is not None else []
    drv_hist = [{"n": h.get("n_done", h.get("n_eval")), "hv": num(h.get("hv"))} for h in (st11.get("hv_hist") or []) if isinstance(h, dict)]

    # 3 目标（阶段 12 / 事后）
    st12 = states[dst] or {}
    scale, ref3, ref3_src = 1.0, None, None
    ratios = []
    for r in (st12.get("records") or []):
        y = r.get("y") if isinstance(r, dict) else None
        b = num(r.get("bone_mm3")) if isinstance(r, dict) else None
        if isinstance(y, list) and len(y) == 3 and b and num(y[2]) is not None:
            ratios.append(num(y[2]) / b)
    frame_known = False                                                    # y[2] = 固定倍数 × bone_mm3 → 驱动的 3-D 参考点可直接用
    if ratios:
        med = float(np.median(ratios))
        if np.std(ratios) <= 1e-3 * abs(med) and med > 0:
            scale, frame_known = med, True
        else:
            warn(f"phase-{dst} y[2] is not a fixed multiple of bone_mm3 (ratios {min(ratios):.4g}–{max(ratios):.4g}); 3-objective HV uses mm³ and a computed reference point")
    rp12 = st12.get("ref_point")
    if frame_known and isinstance(rp12, list) and len(rp12) == 3 and all(num(v) is not None for v in rp12):
        ref3, ref3_src = rp12, f"driver (neckopt_p{dst}.json)"
    # 3 目标非支配集 / 去骨上限前沿的数据：默认对 = 阶段 11 ∪ 12（与从前相同）；其他阶段对 = 目标阶段臂看到的（冻结热启动 + 自有 sb<dst>_），
    # 目标阶段还没有时事后在来源阶段上算
    warm, warm_src = warm_ids_of(st12, st11, r11)
    warm_set = set(warm)
    if legacy:
        nd3_rows = pooled
        nd3_basis = "phase 11 + phase 12" if have_p12 else "post-hoc on phase 11"
    elif have_p12:
        nd3_rows = [r for r in r11 if r["job_id"] in warm_set] + r12
        nd3_basis = (f"phase {dst} arm: frozen warm start ({sum(1 for r in r11 if r['job_id'] in warm_set)} phase-{src} rows, "
                     f"{warm_src.replace('<dst>', str(dst)).replace('<src>', str(src))}) + own sb{dst}_ ({len(r12)})")
    else:
        nd3_rows = r11
        nd3_basis = f"post-hoc on phase {src}"
    if ref3 is None:
        fe3 = [vec2(r) + [r["bone_mm3"] * scale] for r in nd3_rows if r["feasible"] and r.get("bone_mm3") is not None]
        if fe3:
            ref3 = ref_point_of(np.array(fe3)).tolist()
            ref3_src = "computed from current feasible 3406 points"
    nd3 = front_of(nd3_rows, k3=True, scale=scale)
    nd3.sort(key=lambda r: r["bone_mm3"])
    hv12 = []
    if have_p12 and ref3 is not None:
        base = [vec2(r) + [r["bone_mm3"] * scale] for r in (r11 if legacy else [r for r in r11 if r["job_id"] in warm_set])
                if r["feasible"] and r.get("bone_mm3") is not None]
        hv12 = trace(r12, ref3, k3=True, scale=scale, base=base)
    drv_hist12 = [{"n": h.get("n_done", h.get("n_eval")), "hv": num(h.get("hv"))} for h in (st12.get("hv_hist") or []) if isinstance(h, dict)]
    caps = []
    for cap in args.caps:
        rr = [r for r in nd3_rows if r["feasible"] and r.get("bone_cm3") is not None and r["bone_cm3"] <= cap]
        fr = front_of(rr)
        caps.append({"cap_cm3": cap, "n_feasible_under_cap": len(rr), "front_n": len(fr),
                     "min_rot_deg": min((r["rot_first_deg"] for r in fr), default=None),
                     "max_area_mm2": max((r["contact_area_load2_mm2"] for r in fr), default=None),
                     "hv2": hv2(np.array([vec2(r) for r in fr]), ref2) if (fr and ref2 is not None) else None,
                     "front": slim(fr)})

    # ---- 两臂相同自有评估数下的比较、初始批的 δ 对比（非默认阶段对自动做；--compare on 也给 11 / 12）
    compare = args.compare == "on" or (args.compare == "auto" and not legacy)
    arms = arms_compare(r11, r12, warm, warm_src.replace("<dst>", str(dst)).replace("<src>", str(src)), vec2, args.cmp_caps,
                        src, dst, have_p12, splits[src], splits[dst]) if compare else None
    cmp_ph = args.cmp_init if args.cmp_init is not None else (11 if src == 13 else 0)
    dcmp = init_delta_compare(cmp_ph, src, results, queue, r11, rec_by_job) if (compare and cmp_ph and cmp_ph != src) else None
    if dcmp is not None and dcmp["ref_state"] != "ok":
        warn(f"init comparison: neckopt_p{cmp_ph}.json not available ({dcmp['ref_state']}); no pairs")
    mm_rep = {}
    for p in PH:                                                           # 微动：只报告（阶段 13 / 14 不作约束）
        v = [num(r.get("f1_body_p95_um")) for r in rows if r["phase"] == p and r["has_metrics"]]
        v = [x for x in v if x is not None]
        mm_rep[f"phase{p}"] = {**stats(v), "n_over_150": sum(1 for x in v if x > MM_REF),
                               "n_feasible_over_150": sum(1 for r in rows if r["phase"] == p and r["feasible"]
                                                          and (num(r.get("f1_body_p95_um")) or 0.0) > MM_REF)}

    # ---- CT 阶段 10（参照）
    p10_sum, p10_pts, p10_front = None, [], []
    if isinstance(p10, dict):
        recs = [r for r in (p10.get("records") or []) if isinstance(r, dict)]
        okr = [r for r in recs if r.get("ok") and num(r.get("rot_first_deg")) is not None and num(r.get("contact_area_load2_mm2")) is not None]
        fz = [r for r in okr if isinstance(r.get("c"), list) and r["c"] and num(r["c"][0]) is not None and r["c"][0] <= 0]
        if fz:
            P = np.array([[math.log10(max(r["rot_first_deg"], rot_floor)), -r["contact_area_load2_mm2"]] for r in fz])
            p10_front = sorted([fz[i] for i in np.nonzero(nondom_mask(P))[0]], key=lambda r: r["contact_area_load2_mm2"])
        p10_pts = fz

        def rng(rr, k, s=1.0):
            v = [num(r.get(k) if k != "L" and k != "alpha" and k != "m" else (r.get("design") or {}).get(k)) for r in rr]
            v = [x * s for x in v if x is not None]
            return [min(v), max(v)] if v else None
        f11 = front_pooled if have_p12 else front11
        p10_sum = {"note": "reference only: CT femur, h_cut 25–32, L 20–60, |ΔSED| ≤ 30 % constraint; phase 11 = Sawbones 3406, h_cut 16–32, L 20–45, no SED constraint"
                   if legacy else f"reference only: CT femur, h_cut 25–32, L 20–60, |ΔSED| ≤ 30 % constraint, micromotion ≤ 150 um; phase {src} = "
                   f"Sawbones 3406, h_cut 16–32, L 20–45, no SED constraint, interference delta "
                   f"{(getattr(phs[src], 'fric', None) or {}).get('delta')} mm, micromotion limit {mm_by[src]}",
                   "p10": {"records": len(recs), "ok": len(okr), "feasible": len(fz), "front_n": len(p10_front),
                           "front_rot_deg": rng(p10_front, "rot_first_deg"), "front_area_mm2": rng(p10_front, "contact_area_load2_mm2"),
                           "front_bone_cm3": rng(p10_front, "bone_mm3", 1e-3), "front_L": rng(p10_front, "L"),
                           "front_alpha": rng(p10_front, "alpha"), "front_h_cut": [min(r.get("h_cut") for r in p10_front), max(r.get("h_cut") for r in p10_front)] if p10_front else None,
                           "feasible_rot_median": stats([r.get("rot_first_deg") for r in fz]).get("median"),
                           "feasible_area_median": stats([r.get("contact_area_load2_mm2") for r in fz]).get("median")},
                   f"p{src}": {"feasible": sum(r["feasible"] for r in (pooled if have_p12 else r11)), "front_n": len(f11),
                           "front_rot_deg": [min(r["rot_first_deg"] for r in f11), max(r["rot_first_deg"] for r in f11)] if f11 else None,
                           "front_area_mm2": [min(r["contact_area_load2_mm2"] for r in f11), max(r["contact_area_load2_mm2"] for r in f11)] if f11 else None,
                           "front_bone_cm3": rng(f11, "bone_cm3"), "front_L": [min(r["L"] for r in f11), max(r["L"] for r in f11)] if f11 else None,
                           "front_alpha": [min(r["alpha"] for r in f11), max(r["alpha"] for r in f11)] if f11 else None,
                           "front_h_cut": [min(r["h_cut"] for r in f11), max(r["h_cut"] for r in f11)] if f11 else None,
                           "feasible_rot_median": stats([r.get("rot_first_deg") for r in r11 if r["feasible"]]).get("median"),
                           "feasible_area_median": stats([r.get("contact_area_load2_mm2") for r in r11 if r["feasible"]]).get("median")}}

    # 变量范围（图册的坐标轴）
    bounds = {}
    for p in PH:                                                           # 来源阶段的范围优先（目标阶段 = 同一设计空间）
        if p in SN.PHASES:
            bounds = {k: list(v) for k, v in SN.PHASES[p]["vars"].items()}
            break

    feas_default = (f"f1_body_p95_um <= {mm_limit:g} and (vm_p99 is None or vm_p99 <= {vm_limit:g}) [= driver v3 c<=0 with sed none]"
                    if mm_limit is not None else
                    f"vm_p99 is None or vm_p99 <= {vm_limit:g}; micromotion is not a constraint (mm_limit None: recorded and reported) "
                    f"[= driver v3 / v4 c<=0 with sed none, mm_limit None]")   # 没给 --mm-limit：与从前相同
    feas_rule = feas_default
    if mm_cli is not None and mm_same:                                     # 命令行的值 = 阶段自身的设置：规则与驱动相同，只注明来源
        feas_rule = feas_default + f" [--mm-limit {'none' if mm_limit is None else format(mm_limit, 'g')} on the command line = the phase setting]"
    elif mm_cli is not None:                                               # 与阶段的设置不同：事后口径
        ph_txt = ", ".join(f"phase {p} {'None' if v is None else format(float(v), 'g')}" for p, v in mm_phase.items())
        feas_rule = (f"f1_body_p95_um <= {mm_limit:g} and (vm_p99 is None or vm_p99 <= {vm_limit:g}) "
                     f"[--mm-limit {mm_limit:g} on the command line (post hoc); the drivers use the phase setting: mm_limit {ph_txt}]"
                     if mm_limit is not None else
                     f"vm_p99 is None or vm_p99 <= {vm_limit:g}; micromotion is not a constraint (--mm-limit none on the command line, "
                     f"post hoc: recorded and reported) [the drivers use the phase setting: mm_limit {ph_txt}]")
    summary = {"report": REPORT_VERSION if legacy else REPORT_VERSION_PAIR, "generated": fmt_t(t_now), "label": args.label, "root": str(root), "code": str(code),
               "code_version": ver_txt, "metrics_mode": mode, "metrics_newly_computed": n_new, "metrics_from_cache": n_hit,
               "metrics_seconds": round(t_metrics, 1), "mm_limit_um": mm_limit, "vm_limit_mpa": vm_limit,
               "feasible_rule": feas_rule,
               f"have_p{dst}": have_p12, "states": state_sum, "counts": cnt, "init_batch": init, "walls": wall, "distributions": dist,
               f"front2_p{src}": {"n": len(front11), "designs": slim(front11)},
               "front2_pooled": {"n": len(front_pooled), "designs": slim(front_pooled),
                                 "sets": f"phase {src} + phase {dst}" if have_p12 else f"phase {src}"},
               "hv2": {"frame": "[log10(max(rot_first_deg, 1e-3)), -contact_area_load2_mm2] (minimised)", "ref_point": ref2, "ref_source": ref2_src,
                       "trace": hv11, "driver_hv_hist": drv_hist,
                       "last": hv11[-1]["hv"] if hv11 else None, "first_nonzero": next((h["hv"] for h in hv11 if h["hv"] > 0), None)},
               "nd3": {"basis": nd3_basis, "bone_scale_to_frame": scale,
                       "ref_point": ref3, "ref_source": ref3_src, "n": len(nd3), "designs": slim(nd3), f"trace_p{dst}": hv12},
               "bone_caps": {"basis": nd3_basis, "caps": caps},
               "p10_comparison": p10_sum, "stored_vs_rescored_mismatch": mismatch[:50], "n_mismatch": len(mismatch),
               "bounds": bounds, "warnings": WARN}
    if not legacy:                                                         # 阶段对的附加键（默认对没有，summary.json 与从前相同）
        summary.update({"src": src, "dst": dst, "mm_limit_by_phase": {f"phase{p}": mm_by[p] for p in PH},
                        "fric_by_phase": {f"phase{p}": dict(getattr(phs[p], "fric", None) or {}) for p in PH},
                        "scoring": {f"phase{p}": {"sed": scoring[p][0][0], "metric": scoring[p][0][1], **scoring[p][1]} for p in PH},
                        "warm_start": {"n": len(warm), "source": warm_src.replace("<dst>", str(dst)).replace("<src>", str(src)),
                                       "n_rows_in_report": sum(1 for r in r11 if r["job_id"] in warm_set)},
                        "driver_hv_hist_dst": drv_hist12, "micromotion": mm_rep})
    elif mm_limit is None:                                                 # 默认对 + --mm-limit none：微动计数也进 summary.json（默认输出不变）
        summary["micromotion"] = mm_rep
    if mm_cli is not None or not legacy:
        summary["mm_limit_from"] = ("phase setting" if mm_cli is None else
                                    "--mm-limit (command line, = the phase setting)" if mm_same else "--mm-limit (command line, post hoc)")
        summary["mm_limit_phase_setting"] = {f"phase{p}": mm_phase[p] for p in PH}
    if compare:
        summary["arms_compare"] = arms
        summary["init_delta_compare"] = dcmp
    if clock["crossed"]:                                                   # 跨夏令时切换才写（不跨时 summary.json 与从前相同）
        summary["clock"] = {k: v for k, v in clock.items() if k != "crossed"}

    # ---- 输出
    delta_src = (getattr(phs.get(src), "fric", None) or {}).get("delta") if not legacy else None
    ctx = {"src": src, "dst": dst, "legacy": legacy, "mm_none": mm_limit is None, "mm_cli": mm_cli, "mm_same": mm_same, "mm_phase": mm_phase,
           "delta": delta_src, "nd3_basis": nd3_basis,
           "drv_hist12": [] if legacy else drv_hist12, "arms": arms, "dcmp": dcmp}
    out.json("summary.json", _clean(summary))
    cols = []
    for r in rows:
        cols += [c for c in r if c not in cols and not c.startswith("_")]  # _t_done 只用于排序
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    out.text("designs.csv", buf.getvalue())
    figs = []
    if not args.no_figs:
        out.path("_mpl").mkdir(parents=True, exist_ok=True)
        figs = make_figs(out, rows, front11, front_pooled, have_p12, hv11, drv_hist, hv12, nd3, caps, p10_pts, p10_front, bounds,
                         ref2_src, args.label, ctx)
    summary["figures"] = figs
    out.text("summary.md", summary_md(summary, rows, front11, front_pooled, nd3, caps, figs, ctx))
    out.json("summary.json", _clean(summary))
    stamp = time.strftime("%Y%m%d_%H%M", time.localtime(t_now))
    out.json(f"history/summary_{stamp}{'_' + args.label if args.label else ''}.json", _clean(summary))
    log(f"wrote {out.d} (summary.json, summary.md, designs.csv, {len(figs)} figures); warnings {len(WARN)}")
    return summary


# ------------------------------------------------------------------------------------------------- 图
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    plt.rcParams.update({"font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                         "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.6, "axes.spines.top": False,
                         "axes.spines.right": False, "legend.frameon": False, "figure.constrained_layout.use": True, "axes.axisbelow": True, "figure.facecolor": "white", "axes.facecolor": "white"})
    return plt, LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)


def _empty(ax, text):
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes, color=INK2)
    ax.set_xticks([]); ax.set_yticks([])


_NO_MARKER = (None, "None", "none", "", " ")
_LEG_LOCS = ("upper left", "upper right", "lower left", "lower right", "center left", "center right", "upper center", "lower center")


def _legend_obstacles(ax, renderer):
    """一个已画好的坐标轴里图例不该盖住的东西（显示坐标）：散点 / 标记点（中心 + 半径 px）、数据坐标里的曲线（折线顶点，
    阶梯线按 drawstyle 展开）、坐标轴里的文字框。axvline 之类（混合变换，不是数据）不算。"""
    from matplotlib.cbook import STEP_LOOKUP_MAP
    k = ax.figure.dpi / 72.0
    pts, polys, boxes = [], [], []
    for c in ax.collections:
        if not c.get_visible() or not hasattr(c, "get_offsets"):
            continue
        off = np.asarray(c.get_offsets(), float)
        if off.ndim != 2 or not len(off):
            continue
        xy = c.get_offset_transform().transform(off)
        sz = np.asarray(c.get_sizes(), float) if hasattr(c, "get_sizes") and len(c.get_sizes()) else np.array([36.0])
        lw = np.asarray(c.get_linewidths(), float) if len(c.get_linewidths()) else np.array([0.0])
        for i, (x, y) in enumerate(xy):
            if np.isfinite(x) and np.isfinite(y):
                pts.append((x, y, (math.sqrt(max(sz[i % len(sz)], 0.0)) / 2 + lw[i % len(lw)] / 2) * k))
    for ln in ax.lines:
        if not ln.get_visible() or ln.get_transform() is not ax.transData:
            continue
        x, y = (np.asarray(v, float) for v in ln.get_data())
        if not len(x):
            continue
        if ln.get_marker() not in _NO_MARKER:
            rad = (ln.get_markersize() / 2 + ln.get_markeredgewidth() / 2) * k
            for X, Y in ax.transData.transform(np.column_stack([x, y])):
                if np.isfinite(X) and np.isfinite(Y):
                    pts.append((X, Y, rad))
        if ln.get_linestyle() not in _NO_MARKER and len(x) > 1:
            ds = ln.get_drawstyle()
            if ds in STEP_LOOKUP_MAP and ds != "default":
                x, y = STEP_LOOKUP_MAP[ds](x, y)
            v = ax.transData.transform(np.column_stack([x, y]))
            v = v[np.isfinite(v).all(1)]
            if len(v) > 1:
                polys.append(v)
    for t in ax.texts:
        if t.get_visible() and t.get_text():
            boxes.append(t.get_window_extent(renderer))
    return pts, polys, boxes


def _legend_hits(bb, obs, pad) -> bool:
    from matplotlib.path import Path
    from matplotlib.transforms import Bbox
    pts, polys, boxes = obs
    x0, y0, x1, y1 = bb.x0 - pad, bb.y0 - pad, bb.x1 + pad, bb.y1 + pad
    for x, y, rad in pts:
        dx, dy = max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1)
        if dx * dx + dy * dy <= rad * rad:
            return True
    eb = Bbox.from_extents(x0, y0, x1, y1)
    return any(Path(v).intersects_bbox(eb, filled=False) for v in polys) or any(b.overlaps(eb) for b in boxes)


def _place_legends(plt, fig, specs) -> None:
    """图例不盖数据点：specs = [(ax, legend kwargs, 首选位置, 放到下方时的最多列数)]。在图的副本上按输出 dpi 试画（原图不多画一遍，
    首选位置空着时输出与从前逐字节相同）。位置按"首选，再 _LEG_LOCS"的顺序找不碰任何点、曲线、文字的：多个坐标轴先找大家都空着的
    同一个位置，没有就各取各的第一个；只要有一个坐标轴一个空位都没有，这张图的所有图例都放到各自坐标轴下方
    （x 轴标签之下，constrained layout 让出位置）。"""
    if not specs:
        return
    import pickle
    from matplotlib import transforms as mtr
    cp = None
    try:
        cp = pickle.loads(pickle.dumps(fig))
        cp.set_dpi(FIG_DPI)
        pf = cp
    except Exception:                                                     # noqa: BLE001  副本做不出来：在原图上试画（输出可能有亚像素差）
        pf = fig
    free, below = [], []
    try:
        pf.canvas.draw()
        r = pf.canvas.get_renderer()
        pad = 2.0 * pf.dpi / 72.0
        for ax, kw, prefer, _ in specs:
            pa = pf.axes[fig.axes.index(ax)]
            obs = _legend_obstacles(pa, r)
            ok = []
            for cand in dict.fromkeys((*prefer, *_LEG_LOCS)):
                lg = pa.legend(loc=cand, **kw)
                if not _legend_hits(lg.get_window_extent(r), obs, pad):
                    ok.append(cand)
                lg.remove()
            free.append(ok)
            xb = pa.xaxis.get_tightbbox(r)
            below.append(max(pa.bbox.y0 - xb.y0, 0.0) * 72.0 / pf.dpi + 3.0 if xb is not None else 24.0)
    except Exception as e:                                                # noqa: BLE001  试放失败不丢图：图例放回原来的位置
        log(f"legend placement probe failed ({type(e).__name__}: {str(e)[:120]}); legends at their usual places")
        for ax, kw, prefer, _ in specs:
            ax.legend(loc=prefer[0], **kw)
        return
    finally:
        if cp is not None:
            plt.close(cp)
    common = [c for c in free[0] if all(c in f for f in free[1:])]
    choice = [common[0]] * len(free) if common else [f[0] if f else None for f in free]
    outside = any(c is None for c in choice)
    for (ax, kw, prefer, ncol), loc, dy in zip(specs, choice, below):
        if not outside:
            ax.legend(loc=loc, **kw)
            continue
        n = len(ax.get_legend_handles_labels()[1])
        tr = ax.transAxes + mtr.ScaledTranslation(0.0, -dy / 72.0, fig.dpi_scale_trans)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 0.0), bbox_transform=tr, ncol=max(1, min(n, ncol)), **kw)


def _hv_trace(ax, hist, one, **kw) -> None:
    """超体积随评估数的阶梯线；只有一个点时阶梯线画不出来，改画标记 one（线型和图例不变）。"""
    xs, ys = [h["n"] for h in hist], [h["hv"] for h in hist]
    if len(xs) == 1:
        ax.plot(xs, ys, **one, **kw)
    else:
        ax.step(xs, ys, where="post", **kw)


def _count_xaxis(ax, xs, integer=True) -> None:
    """评估数横轴：所有点同一个 n 时（例如只有起点 0）横轴取 0 … max(n, 1)（两端留 5 %），刻度取整数；integer 时总取整数刻度。"""
    from matplotlib.ticker import MaxNLocator
    xs = [x for x in xs if x is not None]
    if xs and max(xs) == min(xs):
        lo, hi = min(min(xs), 0), max(max(xs), 1)
        ax.set_xlim(lo - 0.05 * (hi - lo), hi + 0.05 * (hi - lo))
        integer = True
    if integer:
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))


def make_figs(out, rows, front11, front_pooled, have_p12, hv11, drv_hist, hv12, nd3, caps, p10_pts, p10_front, bounds, ref_src, label, ctx=None):
    ctx = ctx or {"src": 11, "dst": 12, "legacy": True, "mm_none": False, "delta": None, "nd3_basis": None, "drv_hist12": [], "arms": None, "dcmp": None}
    src, dst, legacy = ctx["src"], ctx["dst"], ctx["legacy"]
    try:
        plt, cmap = _plt()
    except Exception as e:                                                # noqa: BLE001
        warn(f"matplotlib unavailable ({type(e).__name__}: {e}); figures skipped")
        return []
    made = []
    tag = f" — {label}" if label else ""
    ok = [r for r in rows if r["has_metrics"]]
    feas = [r for r in ok if r["feasible"]]
    inf = [r for r in ok if not r["feasible"]]

    def save(name, fig):
        try:
            out.fig(name, fig)
            made.append(name)
        finally:
            plt.close(fig)

    def guard(name, fn):
        try:
            fn(name)
        except Exception as e:                                            # noqa: BLE001
            warn(f"figure {name} failed: {type(e).__name__}: {str(e)[:160]}")
            traceback.print_exc()

    bones = [r["bone_cm3"] for r in feas if r.get("bone_cm3") is not None]
    vmin, vmax = (min(bones), max(bones)) if bones else (0, 1)
    if vmax <= vmin:
        vmax = vmin + 1

    def front_line(ax, fr, **kw):
        if fr:
            ax.plot([r["contact_area_load2_mm2"] for r in fr], [r["rot_first_deg"] for r in fr], **kw)

    # (1) 转动 × 接触面积，按去骨量着色，带前沿
    def f1(name):
        fig, ax = plt.subplots(figsize=(7.4, 4.8), layout="constrained")
        if not ok:
            _empty(ax, "no design with metrics yet")
        else:
            for ph, mk in ((src, "o"), (dst, "^")):
                rr = [r for r in feas if r["phase"] == ph]
                if not rr:
                    continue
                sc = ax.scatter([r["contact_area_load2_mm2"] for r in rr], [r["rot_first_deg"] for r in rr], s=26, marker=mk,
                                c=[r["bone_cm3"] if r.get("bone_cm3") is not None else np.nan for r in rr], cmap=cmap, vmin=vmin, vmax=vmax,
                                edgecolors=[INK if r["bonded"] else "white" for r in rr], linewidths=0.7, zorder=3,
                                label=f"phase {ph} feasible ({len(rr)})")
            if inf:
                ax.scatter([r["contact_area_load2_mm2"] for r in inf], [r["rot_first_deg"] for r in inf], s=22, marker="x", color=MUTED,
                           linewidths=0.9, zorder=2, label=(f"infeasible: vM > limit ({len(inf)})" if ctx["mm_none"] else f"infeasible: f1 > limit ({len(inf)})"))
            front_line(ax, front11, color=INK, lw=1.4, zorder=4, marker="s", ms=7.5, mfc="none", mec=INK, mew=1.1,
                       label=f"2-objective front, phase {src} ({len(front11)})")
            if have_p12:
                front_line(ax, front_pooled, color=C2, lw=1.4, ls="--", zorder=4, marker="D", ms=6.5, mfc="none", mec=C2, mew=1.1,
                           label=f"front, phase {src} + {dst} ({len(front_pooled)})")
            ax.scatter([], [], s=26, facecolors="white", edgecolors=INK, linewidths=0.7,       # 说明放进图例（右下角正是前沿所在）
                       label="black ring = bonded model (every 5th)")
            if feas:
                cb = fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize(vmin, vmax), cmap=cmap), ax=ax, pad=0.01)
                cb.set_label("bone removed (cm³)")
            ax.set_yscale("log")
            ax.set_xlabel("closed contact area, LOAD2 (mm²)  →  better")
            ax.set_ylabel("stem rotation rel. bone, first load (°)  ↓ better")
        ax.set_title(f"Sawbones 3406: rotation vs closed contact{tag}" if legacy else
                     f"Sawbones 3406, δ {ctx['delta']} mm{', micromotion not a constraint' if ctx['mm_none'] else ''}: rotation vs closed contact{tag}",
                     loc="left", fontsize=9)
        if ok:
            _place_legends(plt, fig, [(ax, dict(fontsize=7), ("upper left",), 3)])
        save(name, fig)

    # (2) 超体积 vs 完成数
    def f2(name):
        drv12 = ctx["drv_hist12"]
        n = 2 if (hv12 or drv12) else 1
        fig, axs = plt.subplots(1, n, figsize=(6.2 * n, 3.6), squeeze=False, layout="constrained")
        ax = axs[0, 0]
        legs = []
        if hv11:
            _hv_trace(ax, hv11, dict(marker="o", ms=5), color=C1, lw=1.6, label="recomputed (report)")
        if drv_hist:
            ax.plot([h["n"] for h in drv_hist], [h["hv"] for h in drv_hist], "o", ms=3, color=C2, label="driver hv_hist")
        if not hv11 and not drv_hist:
            _empty(ax, "no completed design yet")
        ax.set_xlabel(f"completed phase-{src} designs (DONE + FAILED, in completion order)")
        ax.set_ylabel("hypervolume, 2 objectives")
        ax.set_title(f"Phase {src} hypervolume (ref: " + ("driver" if ref_src.startswith("driver") else "provisional") + ")", loc="left", fontsize=9)
        if hv11 or drv_hist:
            _count_xaxis(ax, [h["n"] for h in hv11] + [h["n"] for h in drv_hist], integer=not legacy)
            legs.append((ax, dict(fontsize=7), ("center right",), 1))
        if hv12 or drv12:
            ax = axs[0, 1]
            if hv12:
                _hv_trace(ax, hv12, dict(marker="o", ms=5), color=C1, lw=1.6, **({} if legacy else {"label": "recomputed (report)"}))
            if drv12:
                ax.plot([h["n"] for h in drv12], [h["hv"] for h in drv12], "o", ms=3, color=C2, label="driver hv_hist")
            ax.set_xlabel(f"completed phase-{dst} designs (0 = phase-{src} warm start only)")
            ax.set_ylabel("hypervolume, 3 objectives")
            ax.set_title(f"Phase {dst} hypervolume (rot × contact × bone)", loc="left", fontsize=9)
            _count_xaxis(ax, [h["n"] for h in hv12] + [h["n"] for h in drv12], integer=not legacy)
            if not legacy:
                legs.append((ax, dict(fontsize=7), ("center right",), 1))
        _place_legends(plt, fig, legs)
        save(name, fig)

    # (3) 前沿设计图册
    def atlas(name, fr, title, order_note):
        n = len(fr)
        fig = plt.figure(figsize=(11.0, 3.2 + 0.26 * max(n, 4)), layout="constrained")
        gs = fig.add_gridspec(2, 4, height_ratios=[1.0, 0.35 + 0.09 * max(n, 4)])
        if not n:
            ax = fig.add_subplot(gs[:, :])
            _empty(ax, "no feasible front yet")
        else:
            x = np.arange(n)
            for k, (key, lab) in enumerate((("L", "stem length L (mm)"), ("alpha", "insertion angle α (°)"),
                                            ("h_cut", "cut depth h_cut (mm)"), ("m", "cortical margin m (mm)"))):
                ax = fig.add_subplot(gs[0, k])
                v = [r.get(key) if r.get(key) is not None else np.nan for r in fr]
                ax.bar(x, v, width=0.72, color=C1)
                if key in bounds:
                    ax.set_ylim(bounds[key][0], bounds[key][1])
                    ax.axhline(bounds[key][0], color=MUTED, lw=0.6); ax.axhline(bounds[key][1], color=MUTED, lw=0.6)
                ax.set_xticks(x); ax.set_xticklabels([str(i + 1) for i in x], fontsize=6)
                ax.set_title(lab, loc="left", fontsize=8)
                ax.grid(axis="x", visible=False)
            ax = fig.add_subplot(gs[1, :])
            keys = [k for k in VARS13 if k in bounds] or list(VARS13)
            M = np.array([[((r.get(k) - bounds[k][0]) / (bounds[k][1] - bounds[k][0])) if (r.get(k) is not None and k in bounds) else np.nan
                           for k in keys] for r in fr])
            im = ax.imshow(M, aspect="auto", cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
            ax.set_xticks(range(len(keys))); ax.set_xticklabels(keys, fontsize=7)
            ax.set_yticks(range(n))
            ax.set_yticklabels([f"{i + 1}  {r['job_id'][:22]}  rot {r['rot_first_deg']:.4f}°  area {r['contact_area_load2_mm2']:.0f}  "
                                f"bone {'—' if r.get('bone_cm3') is None else format(r['bone_cm3'], '.1f')}" for i, r in enumerate(fr)], fontsize=6)
            ax.grid(False)
            cb = fig.colorbar(im, ax=ax, pad=0.01, fraction=0.03)
            cb.set_label("position in bounds (0 = lower, 1 = upper)", fontsize=6.5)
        fig.suptitle(f"{title}{tag}  ({order_note})", x=0.01, ha="left", fontsize=9)
        save(name, fig)

    # (4) 去骨量 × 截骨深度
    def f4(name):
        fig, ax = plt.subplots(figsize=(6.4, 4.2), layout="constrained")
        rr = [r for r in ok if r.get("bone_cm3") is not None and r.get("h_cut") is not None]
        if not rr:
            _empty(ax, "no design with bone volume yet")
        else:
            a = [r for r in rr if r["feasible"]]
            b = [r for r in rr if not r["feasible"]]
            if a:
                ax.scatter([r["h_cut"] for r in a], [r["bone_cm3"] for r in a], s=22, color=C1, edgecolors="white", linewidths=0.6,
                           zorder=3, label=f"feasible ({len(a)})")
            if b:
                ax.scatter([r["h_cut"] for r in b], [r["bone_cm3"] for r in b], s=20, marker="x", color=MUTED, zorder=2, label=f"infeasible ({len(b)})")
            fr = front_pooled if have_p12 else front11
            ff = [r for r in fr if r.get("bone_cm3") is not None]
            if ff:
                ax.scatter([r["h_cut"] for r in ff], [r["bone_cm3"] for r in ff], s=70, facecolors="none", edgecolors=INK, linewidths=1.1,
                           zorder=4, label=f"2-objective front ({len(ff)})")
            ax.legend(fontsize=7, loc="upper left")
        ax.set_xlabel("cut depth below head centre, h_cut (mm)")
        ax.set_ylabel("bone removed: resection (ref 16 mm) + reaming (cm³)")
        ax.set_title(f"Bone removed vs cut depth{tag}", loc="left", fontsize=9)
        save(name, fig)

    # (5) 与 CT 阶段 10 的对比（只作参照）
    def f5(name):
        fig, ax = plt.subplots(figsize=(7.0, 4.6), layout="constrained")
        if p10_pts:
            ax.scatter([r["contact_area_load2_mm2"] for r in p10_pts], [r["rot_first_deg"] for r in p10_pts], s=14, color=MUTED, alpha=0.6,
                       linewidths=0, label=f"CT phase 10 feasible ({len(p10_pts)})")
            front_line(ax, p10_front, color=MUTED, lw=1.2, ls="--", marker="^", ms=6, mfc="none", mec=INK2, mew=0.9,
                       label=f"CT phase 10 front ({len(p10_front)})")
        if feas:
            ax.scatter([r["contact_area_load2_mm2"] for r in feas], [r["rot_first_deg"] for r in feas], s=20, color=C1, edgecolors="white",
                       linewidths=0.6, label=f"3406 phase {src}{(' + ' + str(dst)) if have_p12 else ''} feasible ({len(feas)})")
        fr = front_pooled if have_p12 else front11
        front_line(ax, fr, color=INK, lw=1.5, marker="s", ms=7, mfc="none", mec=INK, mew=1.1, label=f"3406 front ({len(fr)})")
        legs = []
        if not p10_pts and not feas:
            _empty(ax, "no data")
        else:
            ax.set_yscale("log")
            legs.append((ax, dict(fontsize=7), ("upper left",), 2))
        ax.set_xlabel("closed contact area, LOAD2 (mm²)")
        ax.set_ylabel("stem rotation rel. bone, first load (°)")
        ax.set_title("Reference only: CT phase 10 vs Sawbones 3406 (different femur, cut and length ranges)", loc="left", fontsize=8.5)
        _place_legends(plt, fig, legs)
        save(name, fig)

    # (6) 去骨上限下的 2 目标前沿
    def f6(name):
        fr = front_pooled if have_p12 else front11
        basis = ("phase 11 + 12" if have_p12 else "post-hoc on phase 11") if legacy else ctx["nd3_basis"]
        n = max(len(caps), 1)
        fig, axs = plt.subplots(1, n, figsize=(3.1 * n, 3.6), sharex=True, sharey=True, squeeze=False, layout="constrained")
        legs = []
        for k in range(n):
            ax = axs[0, k]
            c = caps[k] if k < len(caps) else None
            if not fr:
                _empty(ax, "no feasible front yet")
                continue
            front_line(ax, fr, color=MUTED, lw=1.2, ls="--", marker="o", ms=2.5, label=f"no cap ({len(fr)})")
            if c and c["front"]:
                front_line(ax, c["front"], color=C1, lw=1.6, marker="o", ms=3.5, label=f"bone ≤ {c['cap_cm3']:g} cm³ ({c['front_n']})")
            ax.set_yscale("log")
            ax.set_title(("—" if not c else f"bone ≤ {c['cap_cm3']:g} cm³: {c['n_feasible_under_cap']} feasible, {c['front_n']} on front"
                          if c["front"] else f"bone ≤ {c['cap_cm3']:g} cm³: no feasible design"), loc="left", fontsize=7.5)
            legs.append((ax, dict(fontsize=6.5), ("upper left",), 2))
            ax.set_xlabel("closed contact area (mm²)")
            if k == 0:
                ax.set_ylabel("stem rotation, first load (°)")
        fig.suptitle(f"2-objective fronts under bone caps ({basis}){tag}", x=0.01, ha="left", fontsize=9)
        _place_legends(plt, fig, legs)
        save(name, fig)

    guard("fig1_rot_vs_area.png", f1)
    guard("fig2_hypervolume.png", f2)
    guard("fig3_atlas_front2.png", lambda nm: atlas(nm, (front_pooled if have_p12 else front11) if legacy else front11,
                                                     "Front designs, 2 objectives (rotation ↓, contact ↑)" if legacy else
                                                     f"Front designs of the phase-{src} arm, 2 objectives (rotation ↓, contact ↑)",
                                                     "ordered by contact area"))
    guard("fig4_bone_vs_hcut.png", f4)
    guard("fig5_vs_ct_phase10.png", f5)
    guard("fig6_bone_caps.png", f6)
    guard("fig7_atlas_nd3.png", lambda nm: atlas(nm, nd3, "Non-dominated designs, 3 objectives (rotation ↓, contact ↑, bone ↓; "
                                                  + (("phase 11 + 12" if have_p12 else "post-hoc") if legacy else
                                                     (f"phase {dst} arm" if have_p12 else "post-hoc")) + ")", "ordered by bone removed"))

    # (8) 两臂相同自有评估数下的 2 维超体积（事后共同参考点）
    arms = ctx.get("arms")

    def f8(name):
        P = arms["panels"]
        fig, axs = plt.subplots(1, len(P), figsize=(3.7 * len(P), 3.6), squeeze=False, layout="constrained")
        legs = []
        for k, pnl in enumerate(P):
            ax = axs[0, k]
            ttl = "no bone cap" if pnl["cap_cm3"] is None else f"bone ≤ {pnl['cap_cm3']:g} cm³"
            if pnl["ref_point"] is None:
                _empty(ax, f"{ttl}: no feasible design yet")
                continue
            ts, td = pnl["trace_src"], pnl["trace_dst"]
            _hv_trace(ax, ts, dict(marker="o", ms=6), color=C1, lw=1.6,
                      label=f"phase {src} arm, 2 objectives ({arms['own_src']} own"
                            f"{', ' + str(arms.get('own_src_readopted')) + ' re-adopted after restart' if arms.get('own_src_readopted') else ''})")
            _hv_trace(ax, td, dict(marker="s", ms=9, mfc="none", mec=C2, mew=1.3), color=C2, lw=1.6, ls="--",
                      label=f"phase {dst} arm, 3 objectives ({arms['own_dst']} own)")
            _count_xaxis(ax, [h["n"] for h in ts] + [h["n"] for h in td])
            if pnl["n_common"] > 0:
                ax.axvline(pnl["n_common"], color=MUTED, lw=0.8, ls=":")
            ax.set_xlabel("own evaluations (0 = shared start)")
            if k == 0:
                ax.set_ylabel("2-D HV (log10 rotation, −contact), common ref")
            ax.set_title(f"{ttl}: {pnl['n_feasible_union']} feasible in the union", loc="left", fontsize=8)
            legs.append((ax, dict(fontsize=6.5), ("upper left",), 1))
        fig.suptitle(f"Arms at equal own evaluation count: 2-D hypervolume, post-hoc common reference point per panel "
                     f"(shared start = {arms['baseline_n']} warm-start rows){tag}", x=0.01, ha="left", fontsize=8.5)
        _place_legends(plt, fig, legs)
        save(name, fig)

    # (9) 初始批：两种过盈量下同一批设计的逐对比较
    dcmp = ctx.get("dcmp")

    def f9(name):
        pr = [p for p in dcmp["pairs"] if p["both_metrics"]]
        keys = (("rot_first_deg", "rotation, first load (°)", True), ("contact_area_load2_mm2", "closed contact LOAD2 (mm²)", False),
                ("f1_body_p95_um", "stem micromotion P95 (µm)", True))
        fig, axs = plt.subplots(1, 3, figsize=(11.4, 3.7), squeeze=False, layout="constrained")
        for k, (key, lab, lg) in enumerate(keys):
            ax = axs[0, k]
            if not pr:
                _empty(ax, "no pair with metrics on both sides")
                continue
            a = [p["ref"][key] for p in pr]
            b = [p["src"][key] for p in pr]
            ax.scatter(a, b, s=24, color=C1, edgecolors=[INK if p["src"].get("bonded") else "white" for p in pr], linewidths=0.7, zorder=3)
            lo, hi = min(a + b), max(a + b)
            ax.plot([lo, hi], [lo, hi], color=MUTED, lw=0.8, ls="--", zorder=1, label="y = x")
            if lg and lo > 0:
                ax.set_xscale("log")
                ax.set_yscale("log")
            rho = (dcmp["spearman"].get(key) or {}).get("rho")
            ax.set_title(f"{lab}: Spearman ρ {'—' if rho is None else format(rho, '.2f')} (n {len(pr)})", loc="left", fontsize=8)
            ax.set_xlabel(f"δ {dcmp['ref_delta_label']} mm (phase {dcmp['ref_phase']} init)")
            ax.set_ylabel(f"δ {dcmp['src_delta_label']} mm (phase {dcmp['src_phase']} init)")
            if k == 0:
                ax.legend(fontsize=6.5, loc="upper left")
        fig.suptitle(f"Init batch, same designs at two interferences (paired by {dcmp['pairing']}; black ring = bonded){tag}",
                     x=0.01, ha="left", fontsize=9)
        save(name, fig)

    if arms:
        guard("fig8_arms_equal_n.png", f8)
    if dcmp and dcmp.get("n_pairs"):
        guard("fig9_init_delta.png", f9)
    return made


# ------------------------------------------------------------------------------------------------- 中文摘要
def _f(v, nd=1, unit=""):
    v = num(v)
    return "—" if v is None else f"{v:.{nd}f}{unit}"


def _mm_set_txt(ctx) -> str:
    """阶段自身的微动设置（驱动用的），例如 '阶段 11 150 µm、阶段 12 150 µm'。"""
    mp = (ctx or {}).get("mm_phase") or {}
    return "、".join(f"阶段 {p} " + ("None（不作约束）" if v is None else f"{float(v):g} µm") for p, v in mp.items()) or "—"


def _mm_cli_note(s, ctx) -> str:
    """给了 --mm-limit <µm> 时补一句：上限来自命令行；与阶段自身的设置相同时写"= 阶段自身的设置"，不同时写事后口径。没给时为空（默认输出不变）。"""
    if (ctx or {}).get("mm_cli") is None or s.get("mm_limit_um") is None:
        return ""
    if ctx.get("mm_same"):
        return f"微动上限 {s['mm_limit_um']:g} µm 来自命令行 `--mm-limit {s['mm_limit_um']:g}`（= 阶段自身的设置：{_mm_set_txt(ctx)}）。"
    return (f"微动上限 {s['mm_limit_um']:g} µm 来自命令行 `--mm-limit {s['mm_limit_um']:g}`（事后口径，不是阶段的设置；"
            f"阶段自身的设置：{_mm_set_txt(ctx)}，驱动按它算可行）。")


def _mm_none_note(src, dst, ctx) -> str:
    """微动不作约束的来源：阶段的设置（mm_limit None），还是命令行 --mm-limit none（= 阶段的设置，或事后口径）。"""
    if (ctx or {}).get("mm_cli") is None:
        return f"（阶段 {src} / {dst} 的 mm_limit None）"
    if ctx.get("mm_same"):
        return f"（命令行 `--mm-limit none`，= 阶段自身的设置：{_mm_set_txt(ctx)}）"
    return f"（命令行 `--mm-limit none`，事后口径，不是阶段的设置；阶段自身的设置：{_mm_set_txt(ctx)}，驱动按它算可行）"


def _same_as_driver(ctx, differs: str) -> str:
    """summary.md 第一段的括号：没给 --mm-limit 或命令行的值 = 阶段的设置 → "与驱动约束相同"；不同 → differs。"""
    return "与驱动约束相同" if (ctx.get("mm_cli") is None or ctx.get("mm_same")) else differs


def _own_note(ar) -> str:
    """§7：来源阶段臂自有评估的口径（驱动的分账；重启后收编的选点、去掉的收编作业、按标签算的个数）。"""
    src = ar.get("src")
    if str(ar.get("split_src", "")).startswith("neckopt_p"):
        how = (f"按 {ar['split_src']} 分账（与 bo_async / arms_gate.split_src 相同）：记录里 round ≠ 0 且 pool_idx 有值，或待定里 pool_idx 有值。"
               f"其中还没记进状态文件的，本次 {ar.get('own_src_unrecorded', 0)} 个；round -1 的，本次 {ar.get('own_src_readopted', 0)} 个 = "
               f"停机期间算完、重启后收编，designs.csv 标 `{READOPTED}`。收编的作业（pool_idx 为空，任何 round）不算")
    else:
        how = f"neckopt_p{src}.json 没有或读不到，全部按作业标签：init 不算，smoke* = 收编的作业、不算，其他算自有"
    return (f"（= 不在共同起点里、阶段 {src} 驱动自己的选点，{how}，本次去掉 {ar.get('own_src_adopted_excluded', 0)} 个收编的"
            f"{_unlisted_note(ar.get('own_src_unlisted_excluded'), src)}；状态文件没列出、按标签算的 {ar.get('own_src_by_tag', 0)} 个）")


def _unlisted_note(k, p) -> str:
    """§7：读得到的状态文件没列出、按收编去掉的个数（0 时为空，文字与从前相同）。"""
    return (f"（含 neckopt_p{p}.json 没列出的 {k} 个：不是驱动提交的，= arms_gate.split_src 的 unadopted，"
            f"bo_async 下次启动时收编；见告警）") if k else ""


def _own_note_dst(ar) -> str:
    """§7：目标阶段臂自有评估的口径（同样分账，去掉收编的）。"""
    dst = ar.get("dst")
    how = (f"按 {ar['split_dst']} 同样分账去掉收编的" if str(ar.get("split_dst", "")).startswith("neckopt_p")
           else f"neckopt_p{dst}.json 没有或读不到，按作业标签去掉 smoke*")
    return (f"（= DONE / FAILED 的 sb{dst}_ 作业，{how}，本次去掉 {ar.get('own_dst_adopted_excluded', 0)} 个"
            f"{_unlisted_note(ar.get('own_dst_unlisted_excluded'), dst)}；按标签算的 {ar.get('own_dst_by_tag', 0)} 个）")


def summary_md(s, rows, front11, front_pooled, nd3, caps, figs, ctx=None) -> str:
    ctx = ctx or {"src": 11, "dst": 12, "legacy": True, "mm_none": False, "delta": None}
    src, dst, legacy = ctx["src"], ctx["dst"], ctx["legacy"]
    L = []
    c11, c12, cref = s["counts"][f"phase{src}"], s["counts"][f"phase{dst}"], s["counts"]["ref_sb"]
    st = s["states"][f"p{src}"] or {}
    ck = s.get("clock")                                                    # 只在作业时间跨夏令时切换（或落在重复那一小时）时有
    gz = f" {ck['generated_zone']}" if ck else ""
    if legacy:
        L.append(f"# 阶段 11（Sawbones 3406）检查点{(' ' + s['label']) if s['label'] else ''}（{s['generated']}{gz}）")
    else:
        L.append(f"# 阶段 {src} / {dst}（Sawbones 3406，δ {ctx['delta']} mm{'，微动不作约束' if ctx['mm_none'] else ''}）检查点"
                 f"{(' ' + s['label']) if s['label'] else ''}（{s['generated']}{gz}）")
    L.append("")
    ver = (s.get("code_version") or "").replace("\n", "，")
    if s["mm_limit_um"] is not None:
        L.append(f"数据 `{s['root']}`；代码 {ver or '（无 VERSION）'}；指标 {s['metrics_mode']}。可行 = 柄身微动 P95 ≤ {s['mm_limit_um']:g} µm"
                 f"（带粘接模型时另加柄 vM P99 ≤ {s['vm_limit_mpa']:g} MPa，{_same_as_driver(ctx, '与驱动的 vM 约束相同')}）。" + _mm_cli_note(s, ctx))
    else:
        mr = (s.get("micromotion") or {}).get(f"phase{src}") or {}
        L.append(f"数据 `{s['root']}`；代码 {ver or '（无 VERSION）'}；指标 {s['metrics_mode']}。可行 = 带粘接模型时柄 vM P99 ≤ {s['vm_limit_mpa']:g} MPa"
                 f"（{_same_as_driver(ctx, 'vM 一条与驱动相同')}；只摩擦的行没有 vM，有指标即可行）。"
                 f"柄身微动 P95 **不作约束**{_mm_none_note(src, dst, ctx)}，"
                 f"照样记录、报告：阶段 {src} 有指标的 {mr.get('n', 0)} 个设计里 {mr.get('n_over_150', 0)} 个超过 150 µm（CT 模型的合格线）。")
    if not legacy:
        sp, sd = s["states"].get(f"p{src}") or {}, s["states"].get(f"p{dst}") or {}
        mmv = sp.get("mm_limit", "—") if sp else "（没有文件）"
        L.append(f"状态文件：neckopt_p{src}.json mm_limit = {'null（不作约束）' if (sp and mmv is None) else mmv}，fric = {sp.get('fric') if sp else '—'}；"
                 f"neckopt_p{dst}.json " + (f"冻结热启动 {sd.get('warm_start_ids_n')} 个 id。" if sd else "还没有（目标阶段臂未启动）。"))
    if st:
        L.append(f"驱动状态：{st.get('mode')}，更新于 {st.get('updated')}；预算 {st.get('budget')}，在算上限 {st.get('inflight')}，"
                 f"已提交计数 {st.get('n_submitted')}，记录 {st.get('records')}，待定 {st.get('pending')}，候选池 {st.get('pool_size')}。")
    else:
        L.append(f"驱动状态：neckopt_p{src}.json 还没有（段 A 未开始或未写出）。")
    L.append("")
    L.append("## 1 作业")
    L.append("")
    L.append("| 组 | 目录 | DONE | 有指标 | 可行 | FAILED（级别/阶段） | 在途 | 带粘接 / 只摩擦 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, c in ((f"阶段 {src}（sb{src}_）", c11), (f"阶段 {dst}（sb{dst}_）", c12), ("参照（sb_）", cref)):
        if c["n_dirs"] == 0 and name.startswith(f"阶段 {dst}"):
            continue
        fl = "、".join(f"{k} ×{v}" for k, v in sorted(c["failed_by_level"].items())) or "0"
        L.append(f"| {name} | {c['n_dirs']} | {c['done']} | {c['done_with_metrics']} | {c['feasible']} | {fl} | {c['pending']} | "
                 f"{c['bonded']} / {c['fric_only']} |")
    ib = s["init_batch"]
    if ib["n"]:
        L.append("")
        gate = {"pass": "通过", "pause": "**超过 15 %，按计划 §5 暂停并查原因**", None: "未完成"}[ib["gate_15pct"]]
        L.append(f"初始批（round 0）：{ib['n']} 个，已完成 {ib['completed']}，有指标 {ib['with_metrics']}，可行 {ib['feasible']}；"
                 f"不 ok 比例 {_f(None if ib['not_ok_frac'] is None else 100 * ib['not_ok_frac'], 1, ' %')}（闸门：{gate}）。")
    if c11["done_without_metrics"]:
        L.append(f"DONE 但缺转动 / 接触指标的有 {c11['done_without_metrics']} 个（见 designs.csv 的 has_metrics 列）。")
    L.append("")
    L.append("## 2 求解时间与产出")
    L.append("")
    for name, key in ((f"阶段 {src}", f"phase{src}"), (f"阶段 {dst}", f"phase{dst}"), ("参照", "ref_sb")):
        w = s["walls"][key]
        sw = w["solve_wall_s"]
        if not sw and not w["throughput"]["n_done"]:
            continue
        parts = []
        for stem in ("m_fric", "m_bond", "intact"):
            if stem in sw and sw[stem].get("n"):
                e = sw[stem]
                parts.append(f"{stem} n {e['n']}，中位 {e['median'] / 60:.1f} min（p10–p90 {e['p10'] / 60:.1f}–{e['p90'] / 60:.1f}，"
                             f"最长 {e['max'] / 60:.1f}）" + (f"，非 OK {e['n_not_ok']}" if e["n_not_ok"] else ""))
        th = w["throughput"]
        rate = th.get("per_h_first_to_last_done")
        r6 = th.get("per_h_last_6h")
        tm = (th.get("turnaround_min") or {}).get("median")
        L.append(f"- {name}：" + ("；".join(parts) if parts else "无 solve.json")
                 + f"。DONE {th['n_done']} 个" + (f"，{rate:.1f} 个/h（首个到最后一个 DONE）" if rate else "")
                 + (f"，近 6 h {r6:.1f} 个/h" if r6 is not None else "") + (f"，提交到 DONE 中位 {tm:.0f} min" if tm else "") + "。")
    if ck:
        rh = "、".join(f"{h}:00–{h[-2:]}:59" for h in ck["repeated_hours"])
        L.append("- 时间：summary 与 designs.csv 里的时间是本地时间、不带时区；"
                 + (f"作业时间跨夏令时切换（UTC {' → '.join(ck['utc_offsets'])}）" if len(ck["utc_offsets"]) > 1 else
                    f"有时间落在夏令时切换时重复的那一小时（UTC {ck['utc_offsets'][0] if ck['utc_offsets'] else '?'}）")
                 + ((f"，本地时间 {rh} 出现两次，{ck['repeated_hour_strings']} 个时间落在这一小时：按同一秒写下的标记文件 mtime 定了 "
                     f"{ck['placed_by_mtime']} 个，按提交不晚于完成定了 {ck['placed_by_order']} 个"
                     + (f"，标记文件 mtime 不够分明、没按它定的 {ck['mtime_inconclusive']} 个（见告警）" if ck.get("mtime_inconclusive") else "")
                     + (f"，**{ck['n_undecided']} 个定不了**（取较早的夏令时解释，见告警）" if ck["n_undecided"] else ""))
                    if ck["repeated_hour_strings"] else "")
                 + "。完成先后（超体积曲线、两臂的自有评估顺序、designs.csv 的行序）、速度与周转都按 epoch 秒算。")
    L.append("")
    d11 = (s["distributions"].get(f"phase{src}") or {})
    if d11:
        L.append(f"## 3 指标分布（阶段 {src}，有指标的 DONE 设计）")
        L.append("")
        L.append("| 指标 | n | 最小 | 中位 | 最大 |")
        L.append("|---|---|---|---|---|")
        for k, lab, nd in (("rot_first_deg", "转动，首次加载（°）", 4), ("rot_perm_deg", "转动，卸载后残留（°）", 4),
                           ("contact_area_load2_mm2", "完全接触面积 LOAD2（mm²）", 0), ("contact_frac_load2", "接触占柄身界面比例", 2),
                           ("f1_body_p95_um", "柄身微动 P95（µm）", 1), ("subsid_first_um", "下沉，首次加载（µm）", 1),
                           ("bone_cm3", "去骨量（cm³）", 2), ("A0", "肩部面积 A0（mm²）", 0), ("sed_chg_pct", "股骨距 SED 变化（%，只带粘接）", 1),
                           ("vm_p99", "柄 vM P99（MPa，只带粘接）", 0)):
            e = d11.get(k) or {}
            if e.get("n"):
                L.append(f"| {lab} | {e['n']} | {_f(e['min'], nd)} | {_f(e['median'], nd)} | {_f(e['max'], nd)} |")
        L.append("")
    if (not legacy or ctx.get("mm_none")) and s.get("micromotion"):
        for p in (src, dst):
            mr = s["micromotion"].get(f"phase{p}") or {}
            if mr.get("n"):
                L.append(f"柄身微动 P95（{'只报告，不作约束' if ctx['mm_none'] else '约束'}）阶段 {p}：有指标 {mr['n']} 个，"
                         f"{_f(mr['min'], 0)}–{_f(mr['max'], 0)} µm（中位 {_f(mr['median'], 0)}），超过 150 µm 的 {mr['n_over_150']} 个"
                         f"（其中可行 {mr['n_feasible_over_150']}）。")
        L.append("")
    fr = front_pooled if s[f"have_p{dst}"] else front11
    sets4 = s['front2_pooled']['sets']
    if not legacy:                                                         # 阶段对：2 目标前沿 = 来源阶段臂自己的；合起来的另报个数
        fr = front11
        sets4 = f"阶段 {src} 臂；阶段 {src} + {dst} 合起来的前沿 {s['front2_pooled']['n']} 个见 summary.json 的 front2_pooled"
    L.append(f"## 4 2 目标前沿（转动 ↓ × 完全接触面积 ↑；{sets4}）")
    L.append("")
    if fr:
        L.append(f"前沿 {len(fr)} 个设计（按接触面积排序；最多列 12 个，全部见 summary.json）：")
        L.append("")
        L.append("| # | 作业 | 转动 ° | 接触 mm² | 微动 µm | 去骨 cm³ | L | α | h_cut | m | 粘接 |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(fr[:12], 1):
            L.append(f"| {i} | {r['job_id']} | {_f(r['rot_first_deg'], 4)} | {_f(r['contact_area_load2_mm2'], 0)} | {_f(r['f1_body_p95_um'], 1)} | "
                     f"{_f(r.get('bone_cm3'), 2)} | {_f(r.get('L'), 1)} | {_f(r.get('alpha'), 1)} | {_f(r.get('h_cut'), 1)} | {_f(r.get('m'), 2)} | "
                     f"{'是' if r.get('bonded') else '否'} |")
    else:
        L.append("还没有可行设计，前沿为空。")
    hv = s["hv2"]
    L.append("")
    tr = hv["trace"]
    if tr:
        tail = [h["hv"] for h in tr[-21:]]
        gain = None if len(tail) < 2 or tail[0] <= 0 else (tail[-1] - tail[0]) / tail[0]
        L.append(f"超体积（2 目标，参考点 {['%.4g' % v for v in hv['ref_point']] if hv['ref_point'] else '—'}，来源 {hv['ref_source']}）："
                 f"首个非零 {_f(hv['first_nonzero'], 1)} → 现在 {_f(hv['last'], 1)}（{tr[-1]['n']} 次完成）"
                 + (f"；最近 {len(tail) - 1} 次完成的相对增量 {100 * gain:.1f} %" if gain is not None else "") + "。")
    L.append("")
    L.append(f"## 5 3 目标与去骨上限（{s['nd3']['basis']}）")
    L.append("")
    L.append(f"3 目标（转动 ↓、接触 ↑、去骨 ↓）非支配集 {s['nd3']['n']} 个"
             + (f"；去骨 {_f(min(r['bone_cm3'] for r in nd3), 1)}–{_f(max(r['bone_cm3'] for r in nd3), 1)} cm³" if nd3 else "") + "。")
    L.append("")
    L.append("| 去骨上限 | 可行数 | 前沿数 | 最小转动 ° | 最大接触 mm² |")
    L.append("|---|---|---|---|---|")
    for c in caps:
        L.append(f"| ≤ {c['cap_cm3']:g} cm³ | {c['n_feasible_under_cap']} | {c['front_n']} | {_f(c['min_rot_deg'], 4)} | {_f(c['max_area_mm2'], 0)} |")
    L.append("")
    pc = s.get("p10_comparison")
    if pc:
        a, b = pc["p10"], pc[f"p{src}"]

        def rr_(v, nd):
            return "—" if not v else f"{_f(v[0], nd)}–{_f(v[1], nd)}"
        L.append("## 6 与 CT 阶段 10 的对比（只作参照：股骨、截骨范围、柄长范围、约束都不同）")
        L.append("")
        L.append(f"| | CT 阶段 10 | 3406 阶段 {src}" + (f" + {dst}" if s[f"have_p{dst}"] else "") + " |")
        L.append("|---|---|---|")
        L.append(f"| 可行设计 | {a['feasible']} | {b['feasible']} |")
        L.append(f"| 前沿设计 | {a['front_n']} | {b['front_n']} |")
        L.append(f"| 前沿转动 ° | {rr_(a['front_rot_deg'], 4)} | {rr_(b['front_rot_deg'], 4)} |")
        L.append(f"| 前沿接触 mm² | {rr_(a['front_area_mm2'], 0)} | {rr_(b['front_area_mm2'], 0)} |")
        L.append(f"| 前沿去骨 cm³ | {rr_(a['front_bone_cm3'], 1)} | {rr_(b['front_bone_cm3'], 1)} |")
        L.append(f"| 前沿柄长 mm | {rr_(a['front_L'], 1)} | {rr_(b['front_L'], 1)} |")
        L.append(f"| 前沿截骨深度 mm | {rr_(a['front_h_cut'], 1)} | {rr_(b['front_h_cut'], 1)} |")
        L.append(f"| 可行设计转动中位 ° | {_f(a['feasible_rot_median'], 4)} | {_f(b['feasible_rot_median'], 4)} |")
        L.append("")
    ar = s.get("arms_compare")
    if ar:
        L.append(f"## 7 两臂对比：相同自有评估数下的 2 维超体积（转动 ↓ × 接触 ↑，事后共同参考点）")
        L.append("")
        L.append(f"共同起点 = 冻结热启动 {ar['baseline_n']} 行（{ar['baseline_source']}；可行 {ar['baseline_feasible']}）。"
                 f"自有评估（DONE + FAILED，按完成先后；FAILED 计数、不加点）：阶段 {src} 臂 {ar['own_src']} 个{_own_note(ar)}、"
                 f"阶段 {dst} 臂 {ar['own_dst']} 个{_own_note_dst(ar)}。"
                 f"参考点 = 该面板内两臂全部可行行（含共同起点）并集的最差 + 10 % 极差，两臂共用；去骨上限面板只用上限内的行。")
        L.append("")
        L.append(f"| 面板 | 并集可行 | 起点 HV（n = 0） | 相同 n | 阶段 {src} 臂 HV | 阶段 {dst} 臂 HV | 各自全部（n：HV） |")
        L.append("|---|---|---|---|---|---|---|")
        for pnl in ar["panels"]:
            at = {x["n"]: x for x in pnl["at_n"]}
            nc = pnl["n_common"]
            ttl = "不设上限" if pnl["cap_cm3"] is None else f"去骨 ≤ {pnl['cap_cm3']:g} cm³"
            fs, fd = pnl["final"]["src"], pnl["final"]["dst"]
            L.append(f"| {ttl} | {pnl['n_feasible_union']} | {_f(at[0]['hv_src'], 2)} | {nc} | {_f(at[nc]['hv_src'], 2)} | {_f(at[nc]['hv_dst'], 2)} | "
                     f"{src}：{fs['n']}：{_f(fs['hv'], 2)}；{dst}：{fd['n']}：{_f(fd['hv'], 2)} |")
        L.append("")
        if not ar["have_dst"]:
            L.append(f"阶段 {dst} 还没有结果：它的曲线只有起点。")
            L.append("")
    dc = s.get("init_delta_compare")
    if dc:
        L.append(f"## 8 初始批：δ {dc.get('ref_delta_label', '?')}（阶段 {dc['ref_phase']}）vs δ {dc.get('src_delta_label', '?')}（阶段 {dc['src_phase']}），"
                 f"同一批设计逐对比较")
        L.append("")
        if dc["ref_state"] != "ok":
            L.append(f"neckopt_p{dc['ref_phase']}.json 读不到（{dc['ref_state']}），没有配对。")
        else:
            sr, ra = dc["spearman"], dc["ratio_src_over_ref"]

            def rho_(k):
                v = (sr.get(k) or {}).get("rho")
                return "—" if v is None else f"{v:.2f}"

            def rat_(k):
                v = (ra.get(k) or {}).get("median")
                return "—" if v is None else f"{v:.3g}"
            L.append(f"阶段 {dc['ref_phase']} 的 init 记录 {dc['n_ref_init']} 个、阶段 {dc['src_phase']} 的 init 设计 {dc['n_src_init']} 个；"
                     f"配对 {dc['n_pairs']}（按 pool_idx {dc['n_pairs_pool_idx']}、按设计 {dc['n_pairs_design']}；未配对：阶段 {dc['src_phase']} "
                     f"{dc['n_src_unpaired']}、阶段 {dc['ref_phase']} {dc['n_ref_unpaired']}），两边都有指标 {dc['n_both_metrics']} 对；"
                     f"配对设计的单位向量 x 最大差 {dc['x_max_abs_diff']:.3g}。spec 的 delta：阶段 {dc['ref_phase']} {dc['ref_deltas']}，"
                     f"阶段 {dc['src_phase']} {dc['src_deltas']}。")
            L.append("")
            L.append(f"Spearman ρ（两种过盈量下的排序一致性）：转动 {rho_('rot_first_deg')}、接触 {rho_('contact_area_load2_mm2')}、"
                     f"微动 {rho_('f1_body_p95_um')}；去骨 {rho_('bone_mm3')}（几何相同，应为 1）。"
                     f"中位比 δ {dc['src_delta_label']} / δ {dc['ref_delta_label']}：转动 {rat_('rot_first_deg')}、接触 {rat_('contact_area_load2_mm2')}、"
                     f"微动 {rat_('f1_body_p95_um')}。")
            L.append("")
            a_, b_ = dc["ref_delta_label"], dc["src_delta_label"]
            L.append(f"| pool_idx | 粘接 | 转动 ° δ {a_} | 转动 ° δ {b_} | 接触 mm² δ {a_} | 接触 mm² δ {b_} | 微动 µm δ {a_} | 微动 µm δ {b_} | 备注 |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            for p in dc["pairs"]:
                A_, B_ = p["ref"] or {}, p["src"] or {}
                probs = []
                if not p["how"]:
                    probs.append("未配对")
                else:
                    if not A_.get("ok"):
                        probs.append(f"δ {a_} 不 ok")
                    if not B_.get("has_metrics"):
                        probs.append(f"δ {b_} {B_.get('state')}" + ("，缺指标" if B_.get("state") == "DONE" else ""))
                note = "" if p["both_metrics"] else "；".join(probs)
                bd = "是" if B_.get("bonded") else ("否" if B_.get("bonded") is False else "—")
                L.append(f"| {'—' if p['pool_idx'] is None else p['pool_idx']} | {bd} | {_f(A_.get('rot_first_deg'), 4)} | {_f(B_.get('rot_first_deg'), 4)} | "
                         f"{_f(A_.get('contact_area_load2_mm2'), 0)} | {_f(B_.get('contact_area_load2_mm2'), 0)} | {_f(A_.get('f1_body_p95_um'), 0)} | "
                         f"{_f(B_.get('f1_body_p95_um'), 0)} | {note} |")
        L.append("")
    if s["n_mismatch"]:
        L.append(f"重算值与驱动记录不一致 {s['n_mismatch']} 处（summary.json 的 stored_vs_rescored_mismatch）。")
        L.append("")
    if s["warnings"]:
        L.append("## 提醒")
        L.append("")
        for w in s["warnings"][:12]:
            L.append(f"- {w}")
        if len(s["warnings"]) > 12:
            L.append(f"- ……另 {len(s['warnings']) - 12} 条见 summary.json")
        L.append("")
    if figs:
        L.append("图：" + "、".join(f"`{f}`" for f in figs) + "。")
    return "\n".join(L) + "\n"


def _mm_arg(s: str):
    """--mm-limit：none / null → "none"（微动不作约束），否则正的 µm 数。"""
    if str(s).strip().lower() in ("none", "null"):
        return "none"
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{s!r}: expected 'none' or a positive number of um") from None
    if not (v > 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError(f"{s!r}: expected 'none' or a positive number of um")
    return v


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="phase 11 / 12 (Sawbones 3406) checkpoint report; read-only except --out")
    ap.add_argument("--root", default="~/mobo_toy_v2", help="Linux tree with queue/ and results/ (default ~/mobo_toy_v2)")
    ap.add_argument("--code", default=None, help="code root with v2/ (default <root>/code)")
    ap.add_argument("--out", default=None, help="output dir (default <root>/deck/p11_3406)")
    ap.add_argument("--p10", default=None, help="phase-10 state file (default <root>/results/neckopt_p10.json)")
    ap.add_argument("--label", default="", help="checkpoint label, e.g. cp1_0800")
    ap.add_argument("--metrics", choices=["rescore", "stored"], default="rescore",
                    help="rescore = stage_neckopt.record_of + stability (default); stored = values in the state files")
    ap.add_argument("--no-cache", action="store_true", help="recompute every DONE design (ignore _cache/metrics.json)")
    ap.add_argument("--no-figs", action="store_true")
    ap.add_argument("--src", type=int, default=11, help="source phase (2-objective arm; default 11)")
    ap.add_argument("--dst", type=int, default=12, help="target phase (3-objective arm, frozen warm start from --src; default 12)")
    ap.add_argument("--mm-limit", type=_mm_arg, default=None, metavar="none|UM",
                    help="micromotion limit µm for feasibility, or 'none' (default: 11 / 12 stage_neckopt.MM_LIMIT = 150; other pairs the "
                         "phase's mm_limit, 13 / 14: none)")
    ap.add_argument("--vm-limit", type=float, default=None, help="stem vM P99 limit MPa (default stage_neckopt.VM_LIMIT = 440)")
    ap.add_argument("--caps", type=float, nargs="+", default=[6.0, 8.0, 10.0, 12.0], help="bone caps in cm³")
    ap.add_argument("--compare", choices=["auto", "on", "off"], default="auto",
                    help="arms comparison (fig8) and init-delta comparison (fig9); auto = on except for the default pair 11 / 12")
    ap.add_argument("--cmp-caps", type=float, nargs="+", default=[8.0, 10.0], help="bone caps (cm³) for the arms comparison")
    ap.add_argument("--cmp-init", type=int, default=None,
                    help="phase whose init batch is paired with the source phase's (default 11 when --src 13, else none; 0 = off)")
    ap.add_argument("--mem-gb", type=float, default=8.0, help="address-space cap for this process on Linux (RLIMIT_AS)")
    a = ap.parse_args(argv)
    if a.src <= 0 or a.dst <= 0 or a.src == a.dst:
        ap.error(f"--src {a.src} / --dst {a.dst}: two different positive phase numbers needed")
    try:
        import resource
        lim = int(a.mem_gb * (1 << 30))
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except Exception:                                                     # noqa: BLE001  （Windows 没有 resource）
        pass
    WARN.clear()
    return build(a)


if __name__ == "__main__":
    main()
