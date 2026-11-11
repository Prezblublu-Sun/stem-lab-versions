"""每个 FE 作业的结局：一个类，一个名字。只有名字表和分类函数：不读文件，不写文件，只用标准库。

失败的作业带 {"level": L1..L5, "stage": prep|solve|post, "reason": 文字}（jobs._fail 写的 FAILED.json）。级别说的是在哪一步
失败，没有说接下来该怎么办。这里把它对到类和名字：

    classify(level, stage, reason, code=None) -> Result(klass, code, zh)

类（接下来怎么办 / 告诉选点策略什么）：
    OK         完成                                    -> 结果
    DESIGN     设计在这根骨上放不进去                  -> 不重试；告诉策略"不可行"
    NUMERIC    网格或求解在数值上失败                  -> 换设置才值得重试；告诉策略"失败"（可能有物理含义）
    ENV        内存、超时、许可、传输                  -> 不是设计的性质；先不告诉策略
    ERROR      规格的组合不合法，或代码抛异常          -> 先修；不告诉策略
    SKIP       有意跳过                                -> 不告诉
    UNKNOWN    从记录里分不出来                        -> 人看

两条路：
    1 源头知道是哪一种时直接给 code（jobs.py、stage_v2a.py、run_abaqus.py、solve_worker.py 里写死的那些）。code 必须在 CODES 里，
      不在 = 源头写错了，归 UNKNOWN / unclassified，不去猜。
    2 源头只有文字时（冻结文件抛的异常、求解器的报错、2026-11-11 以前的全部记录）按 _RULES 从文字认。

_RULES 按现有的原因文字写：2026-11-11 对 Linux 队列的 126 条 FAILED.json 和 db3406 v0.14 的 1434 行核过，没有一条落到
unclassified。新增一种失败时：在 CODES 里加名字；只有文字的再在 _RULES 里加一条；并在 ops/tests/test_ops.py 的 J 段加一个例子。

不计入 code_hash，也不在 AUX_FILES 里：它不影响任何 FE 结果，只给失败记录多写两个键。
"""
from __future__ import annotations

import re
from typing import NamedTuple


class Result(NamedTuple):
    klass: str      # OK / DESIGN / NUMERIC / ENV / ERROR / SKIP / UNKNOWN
    code: str       # stable name, lower snake case
    zh: str         # one line for people


KLASSES = ("OK", "DESIGN", "NUMERIC", "ENV", "ERROR", "SKIP", "UNKNOWN")
KLASS_ZH = {"OK": "完成", "DESIGN": "设计不可行", "NUMERIC": "没算出来", "ENV": "环境", "ERROR": "出错", "SKIP": "跳过", "UNKNOWN": "待查"}
TELL_STRATEGY = {"OK": "result", "DESIGN": "infeasible", "NUMERIC": "failed"}   # the other classes are not information about the design
# ENV codes the solve worker retries by itself (same spec, later). A time limit or a memory limit is ENV too, but running the same job
# again would most likely end the same way, so those wait for a person (v2/maint.py requeue).
AUTO_RETRY = frozenset({"transport_failed", "license_unavailable"})

CODES: dict[str, tuple[str, str]] = {     # code -> (class, one line for people)
    "ok": ("OK", "完成"),
    "skipped": ("SKIP", "有意跳过"),
    # the design against the bone
    "shoulder_below_neck": ("DESIGN", "肩部面积小于假体颈"),
    "no_entry_offset": ("DESIGN", "找不到合格的入口偏移"),
    "tip_too_thin": ("DESIGN", "柄尖太细"),
    "blocked_by_cortex": ("DESIGN", "最小号在每个偏移都碰皮质"),
    "templating_other": ("DESIGN", "模板化不可行，其他原因"),
    # the mesh and the solve, numerically
    "mesh_failed": ("NUMERIC", "网格重试后仍失败"),
    "mesh_degenerate": ("NUMERIC", "网格有退化单元"),
    "not_converged": ("NUMERIC", "求解不收敛"),
    # the machine, the licence, the network
    "prep_out_of_memory": ("ENV", "建模超内存"),
    "solve_timeout": ("ENV", "求解超时"),
    "license_unavailable": ("ENV", "许可取不到"),
    "transport_failed": ("ENV", "和 Linux 之间的传输失败"),
    # the spec or the code
    "invalid_spec": ("ERROR", "规格的组合不合法"),
    "hook_error": ("ERROR", "钩子出错"),
    "fetch_error": ("ERROR", "作业目录里取不到求解输入"),
    "post_exception": ("ERROR", "后处理抛了异常"),
    # cannot be told from the record
    "solve_aborted": ("UNKNOWN", "求解中止，原因待查"),
    "runner_exception": ("UNKNOWN", "求解器的外壳抛了异常，原因待查"),
    "export_incomplete": ("UNKNOWN", "求解后的导出不全，原因待查"),
    "prep_crashed": ("UNKNOWN", "建模进程异常退出，原因待查"),
    "unclassified": ("UNKNOWN", "规则里没有这种情况"),
}

# (stage, reason pattern, code); first match wins. Stage "" matches every stage.
_RULES: tuple[tuple[str, str, str], ...] = (
    ("", r"^skipped on purpose", "skipped"),
    # prep: the design against the bone
    ("prep", r"shoulder .* < prosthetic neck", "shoulder_below_neck"),
    ("prep", r"templating: .*no offset works", "no_entry_offset"),
    ("prep", r"templating: tip too thin", "tip_too_thin"),
    ("prep", r"templating: blocked", "blocked_by_cortex"),
    ("prep", r"^templating:", "templating_other"),
    # prep: the spec or the code
    ("prep", r"needs model m1|excludes bond_only|implemented only in the M1|is only for design / variant", "invalid_spec"),
    ("prep", r"hook was not called|^foam_refine: \w+", "hook_error"),
    # prep: the machine (a segfault of gmsh under the address space cap is what running out of memory looks like there: stage_v2a.py)
    ("prep", r"memory limit|ran away in memory|RLIMIT_AS|^MemoryError|bad_alloc", "prep_out_of_memory"),
    # prep: the mesh
    ("prep", r"meshing failed after retries", "mesh_failed"),
    ("prep", r"degenerate tetrahedra", "mesh_degenerate"),
    # export of the solver output
    ("", r"missing export|odb export", "export_incomplete"),
    # solve: numerics
    ("", r"TOO MANY ATTEMPTS MADE FOR THIS INCREMENT", "not_converged"),
    # solve: the machine and the transport
    ("", r"timeout > ", "solve_timeout"),
    ("", r"license unavailable", "license_unavailable"),
    ("", r"fetch failed", "transport_failed"),
    # solve: cannot be told
    ("", r"analysis not completed|unknown failure", "solve_aborted"),
    ("", r"runner exception", "runner_exception"),
)
_COMPILED = tuple((st, re.compile(pat), c) for st, pat, c in _RULES)
_UNIT = re.compile(r"^[A-Za-z_0-9]+: ")       # "m_fric: ", "intact: ": the unit name jobs.post puts in front of a solver reason


def of_code(code: str) -> Result:
    """The Result of a code a source wrote. A code that is not in CODES is a mistake in the source: UNKNOWN / unclassified."""
    k, zh = CODES.get(code, CODES["unclassified"])
    return Result(k, code if code in CODES else "unclassified", zh)


def classify(level: str | None, stage: str | None, reason: str | None, code: str | None = None) -> Result:
    """Class and code of one job. No level, no reason and no code = a finished job. A code given by the source wins over the text."""
    level, stage, reason = (level or "").strip(), (stage or "").strip(), (reason or "").strip()
    if code:
        return of_code(str(code).strip())
    if not level and not reason:
        return of_code("ok")
    if level == "SKIP":
        return of_code("skipped")
    body = _UNIT.sub("", reason, count=1) if stage in ("solve", "fetch") else reason
    for st, pat, c in _COMPILED:
        if st and st != stage:
            continue
        if pat.search(body) or pat.search(reason):
            return of_code(c)
    return of_code("post_exception" if stage == "post" else "unclassified")


def for_job(state: str | None, level: str | None, stage: str | None, reason: str | None, code: str | None = None) -> Result | None:
    """The outcome of a job by its queue state. DONE -> ok. FAILED -> classify; a failed job with nothing recorded is
    UNKNOWN / unclassified, never ok. Any other state (NEW, READY, CLAIMED, SOLVED, MISSING) has no outcome yet -> None."""
    state = (state or "").strip()
    if state == "DONE":
        return of_code("ok")
    if state != "FAILED":
        return None
    if not (code or (level or "").strip() or (reason or "").strip()):
        return of_code("unclassified")
    return classify(level, stage, reason, code)
