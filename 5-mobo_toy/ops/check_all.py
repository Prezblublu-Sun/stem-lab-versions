"""操作员的检查入口：一条命令把只读的检查都跑一遍，给两张表（系统、批次），每项是 过 / 注意 / 不过 / 未查。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/check_all.py [--no-linux] [--json]

什么都不改，不启动任何东西：只读本地文件，对 Linux 只发 ops/state.py 的那一条只读命令。
退出码：0 = 没有"不过"；1 = 有"不过"。"注意"不改退出码：它是要人知道的状态，不是错。
ops/state.py 把同样两张表放在状态页的最前面（STATE.md、STATE.html）。

三种判断的含义
  过    这一项现在是对的。
  注意  不是错，但下一步会被它挡住或要人知道：有没提交的管线文件、Linux 上的版本不是 HEAD、最新版本没发布、批次的行还没导出。
  不过  现在就是错的：冻结被破坏、事实表冲突、worker 暂停、磁盘不够、QA 多出新的失败、发布过的版本被改了、有待查的行。

evaluate(inp) 是纯函数，只看 gather() 收来的字典，测试在 ops/tests/test_ops.py。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
import state as ST  # noqa: E402

PY = ROOT / ".venv-mobo" / "Scripts" / "python.exe"
PY = str(PY) if PY.exists() else sys.executable
OK, NOTE, BAD, SKIP = "过", "注意", "不过", "未查"
QA_BASELINE = {"1", "7", "13"}                 # v0.14 起的已知失败（ops/state.py 的数据库一节同一个基线）
PIPELINE = ("v2/", "tools/", "ops/", "inp_writer.py", "config.yaml")
MIN_LINUX_GB, MIN_H_GB, READY_MAX_MIN = 30, 50, 60        # 喂料门第 6 条；导出器的磁盘门；state.py 的未认领界限


def _rc(script: str, *args: str, timeout: float = 300) -> int:
    return subprocess.run([PY, str(ROOT / script), *args], capture_output=True, cwd=str(ROOT), timeout=timeout).returncode


def _linux(blocks: dict) -> dict | None:
    if not blocks or "QUEUE" not in blocks:
        return None
    ver = " ".join(blocks.get("VERSION", []))
    m = re.search(r"git=([0-9a-f]+(?:-dirty)?)", ver)
    procs = [p for p in blocks.get("PROCS", []) if p.strip()]
    q = {}
    for ln in blocks.get("QUEUE", []):
        p = ln.split()
        if len(p) == 2 and p[1].isdigit():
            q[p[0]] = int(p[1])
    ra = [ln.split() for ln in blocks.get("READY_AGE", []) if ln.strip()]
    disk = [d.split() for d in blocks.get("DISK", []) if d.strip()]
    free = None
    if disk and len(disk[0]) >= 4:
        g = re.match(r"([\d.]+)([GT])", disk[0][3])
        free = float(g.group(1)) * (1024 if g.group(2) == "T" else 1) if g else None
    ch = [x.strip() for x in blocks.get("CODEHASH", []) if x.strip()]
    return {"version_git": m.group(1) if m else None,
            "md5": {p[1]: p[0][:8] for p in (ln.split() for ln in blocks.get("MD5", [])) if len(p) == 2},
            "code_hash": ch[0] if ch else None,
            "serve": any("stage_v2a.py serve" in p for p in procs),
            "feeders": sorted({m2.group(1) for p in procs for m2 in [re.search(r"stage_db\.py feed (\S+)", p)] if m2}),
            "queue": q, "ready_unclaimed": len(ra), "ready_oldest_min": int(ra[0][0]) if ra and ra[0][0].isdigit() else 0,
            "root_free_gb": free, "stop_flags": [f.strip() for f in blocks.get("FLAGS", []) if f.strip().startswith("STOP")]}


def _batches(db_dir: pathlib.Path | None) -> list[dict]:
    import outcomes as OC
    out = []
    for d in sorted((ROOT / "experiments").glob("b*_*")):
        if not d.is_dir():
            continue
        b = {"name": d.name, "approved": (d / "approval.md").exists(), "has_rows": (d / "rows.json").exists(), "judged": (d / "result.json").exists(),
             "rows_in": (d / "rows_in.json").exists(), "n_rows": 0, "by_class": {}, "n_not_in_db": 0, "judged_db": None, "gates": {}}
        if b["has_rows"] and db_dir is not None:
            o = OC.outcomes(d, db_dir)
            b.update(n_rows=o["n_rows"], by_class=o["by_class"], n_not_in_db=len(o["not_in_db"]))
        if b["judged"]:
            try:
                r = json.loads((d / "result.json").read_text(encoding="utf-8"))
                b["judged_db"] = r.get("db")
                b["gates"] = {k: v.get("status") for k, v in (r.get("gates") or {}).items()}
            except (OSError, ValueError):
                b["judged"] = False
        out.append(b)
    return out


def gather(use_linux: bool = True, blocks: dict | None = None) -> dict:
    """Everything evaluate() looks at. Read only. `blocks` = the parsed Linux output state.py already has (saves a second ssh)."""
    fz = json.loads(ST.FREEZE.read_text(encoding="utf-8")) if ST.FREEZE.exists() else {}
    _, g = ST.git_section()
    pushed = subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", "j/master"], capture_output=True, cwd=str(ROOT)).returncode == 0
    if use_linux and blocks is None:
        _, blocks = ST.deploy_section(True)
    lx = _linux(blocks or {}) if use_linux else None
    head_md5 = {f: ST.head_md5(f) for f in ST.DEPLOYED if (ROOT / f).exists()}
    runs = ROOT / "v2" / "runs"
    pid = (runs / "worker.pid").read_text().strip() if (runs / "worker.pid").exists() else ""
    alive = bool(pid) and pid in ST.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])[1]
    paused = []
    for m in sorted(runs.glob("worker.PAUSED_*.json")):
        try:
            paused.append(str(json.loads(m.read_text(encoding="utf-8")).get("kind")))
        except (OSError, ValueError):
            paused.append(m.name)
    vers = sorted([p for p in ST.DB_ROOT.glob("v*") if p.is_dir() and (p / "manifest.json").exists()], key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)]) if ST.DB_ROOT.exists() else []
    db = None
    if vers:
        v = vers[-1]
        man = json.loads((v / "manifest.json").read_text(encoding="utf-8"))
        qa = json.loads((v / "qa_report.json").read_text(encoding="utf-8")) if (v / "qa_report.json").exists() else None
        pub = None
        if (v / "PUBLISHED.json").exists():
            pub = "ok" if _rc("tools/db_export.py", "publish", "--out", str(v), "--check", timeout=900) == 0 else "changed"
        db = {"name": v.name, "n_rows": man.get("n_rows"), "exporter": man.get("exporter_version"), "has_qa": qa is not None,
              "qa_fails": [str(c["id"]) for c in (qa or {}).get("checks", []) if c.get("status") == "FAIL"], "published": pub}
    try:
        h_free = shutil.disk_usage(str(ROOT)).free / 2 ** 30
    except OSError:
        h_free = None
    return {"freeze_rc": _rc("ops/check_freeze.py", "--quiet"), "facts_rc": _rc("ops/check_facts.py", "--quiet"), "frozen_code_hash": fz.get("code_hash"),
            "git": {"head": g["head"], "pushed": pushed, "dirty_pipeline": [f for f in g["dirty"] if f.startswith(PIPELINE)],
                    "dirty_other": [f for f in g["dirty"] if not f.startswith(PIPELINE)]},
            "head_md5": head_md5, "linux": lx, "linux_asked": use_linux,
            "worker": {"alive": alive, "stop": (runs / "worker.STOP").exists(), "paused": paused}, "h_free_gb": h_free, "db": db,
            "batches": _batches(vers[-1] if vers else None)}


def evaluate(inp: dict) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(系统检查, 批次检查)，每项 (名字, 判断, 说明)。纯函数。"""
    c: list[tuple[str, str, str]] = []
    g, lx, w, db = inp["git"], inp["linux"], inp["worker"], inp["db"]
    c.append(("冻结的 8 个文件", OK if inp["freeze_rc"] == 0 else BAD, "一个字节没变" if inp["freeze_rc"] == 0 else "ops/check_freeze.py 不过：立即停止，不要提交"))
    c.append(("文档和事实表", OK if inp["facts_rc"] == 0 else BAD, "没有冲突" if inp["facts_rc"] == 0 else "ops/check_facts.py 不过：有文件和 ops/facts.json 冲突"))
    if g["dirty_pipeline"]:
        c.append(("管线文件已提交", NOTE, f"{len(g['dirty_pipeline'])} 个没提交，喂料门会拦：" + "、".join(g["dirty_pipeline"][:5])))
    else:
        c.append(("管线文件已提交", OK, f"HEAD {g['head']}" + (f"；另有 {len(g['dirty_other'])} 个别的文件没提交" if g["dirty_other"] else "")))
    c.append(("已推到 J:", OK if g["pushed"] else NOTE, "HEAD 在 j/master 上" if g["pushed"] else "HEAD 还没推，部署门和喂料门会拦"))
    if lx is None:
        why = "没有查 Linux（--no-linux）" if not inp["linux_asked"] else "Linux 连不上或命令失败"
        for name in ("Linux 上的代码是 HEAD", "Linux 上的冻结", "serve", "队列", "Linux 磁盘"):
            c.append((name, SKIP if not inp["linux_asked"] else BAD, why))
    else:
        diff = sorted(f for f, h in inp["head_md5"].items() if lx["md5"].get(f) != h)
        if diff:
            c.append(("Linux 上的代码是 HEAD", NOTE, f"{len(diff)} 个文件和 HEAD 不同（没部署，或 Linux 上被改过）：" + "、".join(diff[:5])))
        elif (lx["version_git"] or "") != g["head"]:
            c.append(("Linux 上的代码是 HEAD", NOTE, f"文件都相同，但 VERSION 记的是 {lx['version_git']}，HEAD 是 {g['head']}：喂料门第 5 条会拦，重新部署一次即可"))
        else:
            c.append(("Linux 上的代码是 HEAD", OK, f"{len(inp['head_md5'])} 个文件相同，VERSION {lx['version_git']}"))
        same = lx["code_hash"] == inp["frozen_code_hash"]
        c.append(("Linux 上的冻结", OK if same else BAD, f"code_hash {lx['code_hash']}" + ("" if same else f"，冻结值 {inp['frozen_code_hash']}：Linux 上的哈希文件被改了")))
        q = lx["queue"]
        waiting = q.get("NEW", 0) > 0 or bool(lx["feeders"])
        c.append(("serve", OK if lx["serve"] else (BAD if waiting else NOTE), "在跑" if lx["serve"] else ("没在跑，而队列里有 NEW 作业或有喂料器：作业不会被 prep" if waiting else "没在跑；现在没有 NEW 作业")))
        qd = "，".join(f"{k} {q.get(k, 0)}" for k in ("NEW", "READY", "CLAIMED", "SOLVED", "DONE", "FAILED")) + f"；喂料器：{'、'.join(lx['feeders']) or '无'}"
        if lx["stop_flags"]:
            qd += f"；停止标记 {'、'.join(lx['stop_flags'])}"
        stuck = lx["ready_unclaimed"] > 0 and lx["ready_oldest_min"] > READY_MAX_MIN and not w["stop"]
        if stuck:
            c.append(("队列", BAD, f"有 {lx['ready_unclaimed']} 个 READY 没人领，最老 {lx['ready_oldest_min']} 分钟，而 worker 没被停：查 worker。" + qd))
        elif lx["ready_unclaimed"] > 0 and not w["alive"]:
            c.append(("队列", NOTE, f"有 {lx['ready_unclaimed']} 个 READY 在等，worker 不在。" + qd))
        else:
            c.append(("队列", OK, qd))
        f = lx["root_free_gb"]
        c.append(("Linux 磁盘", SKIP if f is None else (OK if f >= MIN_LINUX_GB else BAD), "读不到" if f is None else f"根分区剩 {f:.0f} GB（喂料要 ≥ {MIN_LINUX_GB}）"))
    if w["paused"]:
        c.append(("worker", BAD, f"暂停着（{'、'.join(w['paused'])}）：连续失败，还在每 300 s 试一次。看 v2/runs/worker.PAUSED_*.json"))
    else:
        c.append(("worker", OK if w["alive"] else NOTE, "在跑" if w["alive"] else ("没在跑" + ("，worker.STOP 存在" if w["stop"] else "") + "：READY 的作业不会被求解；启动要用户说")))
    hf = inp["h_free_gb"]
    c.append(("本机磁盘", SKIP if hf is None else (OK if hf >= MIN_H_GB else BAD), "读不到" if hf is None else f"H: 剩 {hf:.0f} GB（导出要 ≥ {MIN_H_GB}）"))
    if db is None:
        c.append(("数据库最新版本", BAD, "没有带 manifest 的版本目录"))
    else:
        new_fail = sorted(set(db["qa_fails"]) - QA_BASELINE, key=int)
        if not db["has_qa"]:
            c.append(("数据库最新版本", NOTE, f"{db['name']}，{db['n_rows']} 行；没有 QA 报告"))
        elif new_fail:
            c.append(("数据库最新版本", BAD, f"{db['name']}，{db['n_rows']} 行；QA 多出新的失败：第 {'、'.join(new_fail)} 条"))
        else:
            c.append(("数据库最新版本", OK, f"{db['name']}，{db['n_rows']} 行；QA 失败的只有已知的 {'、'.join(sorted(db['qa_fails'], key=int)) or '无'}"))
        c.append(("最新版本已发布", {"ok": OK, "changed": BAD, None: NOTE}[db["published"]],
                  {"ok": "发布后没有变", "changed": "发布之后被改了：tools/db_export.py publish --check 列出哪里变了", None: "还没发布，可以被再次 finalize"}[db["published"]]))
    b_out: list[tuple[str, str, str]] = []
    for b in inp["batches"]:
        if not b["approved"]:
            b_out.append((b["name"], NOTE, "没有批准记录（approval.md）：还不能喂" + ("；行文件批次" if b["rows_in"] else "")))
            continue
        if not b["has_rows"]:
            b_out.append((b["name"], OK if b["judged"] else NOTE, "没有 rows.json（b25 之前的批次），不报各行的结局" + ("" if b["judged"] else "；没有判定结果")))
            continue
        cls = "，".join(f"{k} {n}" for k, n in b["by_class"].items()) or "无"
        d = f"{b['n_rows']} 行：{cls}"
        if b["n_not_in_db"]:
            d += f"；{b['n_not_in_db']} 行不在最新版本里（没喂完、没算完或还没导出）"
        gates = "，".join(f"{k} {v}" for k, v in b["gates"].items())
        d += f"；判定：{gates}（{b['judged_db']}）" if b["judged"] else "；还没判定"
        st = BAD if b["by_class"].get("UNKNOWN") else (NOTE if b["n_not_in_db"] or not b["judged"] else OK)
        if b["by_class"].get("UNKNOWN"):
            d += "；有待查的行，用这个批次的判定前要人看过"
        b_out.append((b["name"], st, d))
    return c, b_out


def tables(checks: list, batches: list) -> list[str]:
    """The two tables as markdown lines (state.py puts them at the top of the state page)."""
    n = {s: sum(1 for _, st, _ in checks + batches if st == s) for s in (OK, NOTE, BAD, SKIP)}
    out = [f"**{'有不过的项' if n[BAD] else '没有不过的项'}**：过 {n[OK]}，注意 {n[NOTE]}，不过 {n[BAD]}" + (f"，未查 {n[SKIP]}" if n[SKIP] else "") + "。",
           "", "| 系统 | 判断 | 说明 |", "|---|---|---|"]
    out += [f"| {a} | {'**不过**' if s == BAD else s} | {d} |" for a, s, d in checks]
    out += ["", "| 批次 | 判断 | 说明 |", "|---|---|---|"]
    out += [f"| `{a}` | {'**不过**' if s == BAD else s} | {d} |" for a, s, d in batches]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="操作员的检查入口：只读，一条命令跑完所有检查。")
    ap.add_argument("--no-linux", action="store_true", help="不连 Linux，只查本机")
    ap.add_argument("--json", action="store_true", help="打印收来的原始数据和判断（给别的脚本读）")
    a = ap.parse_args()
    inp = gather(not a.no_linux)
    checks, batches = evaluate(inp)
    if a.json:
        print(json.dumps({"input": inp, "checks": checks, "batches": batches}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(tables(checks, batches)))
    return 1 if any(s == BAD for _, s, _ in checks + batches) else 0


if __name__ == "__main__":
    sys.exit(main())
