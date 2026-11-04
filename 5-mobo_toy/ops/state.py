"""生成 STATE.md：仓库、冻结哈希、部署版本、Linux 队列与喂料器、Windows worker、数据库版本。只读；失败的部分写进文件，不抛异常。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/state.py [--no-linux] [--out STATE.md]

规则：STATE.md 不手改；每个数字都来自本脚本当次读取。Linux 只跑只读命令（ls、md5sum、cat、stage_db.py status）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SSH = r"C:\Program Files\Git\usr\bin\ssh.exe"
KEY = str(pathlib.Path.home() / ".ssh" / "id_ed25519_lrlbackup")
HOST = "linux-user@<linux-ip>"
FREEZE = ROOT / "docs" / "freeze" / "M1-3406-v1.json"
DB_ROOT = ROOT.parents[1] / "db3406"
PLAN = pathlib.Path(r"H:\projects\application\research-log\neck_implant_2026-10-02\3406计划_第三版_到Gate1_2026-11-02.md")

# 部署到 Linux 并影响作业的文件（8 个哈希文件之外）；tools/db_export.py 在 Windows 上跑，只比 HEAD
DEPLOYED = ["v2/jobs.py", "v2/stage_db.py", "v2/stage_al.py", "v2/al_local.py", "v2/tpl_record.py", "v2/stage_deck.py",
            "v2/stage_neckopt.py", "v2/stage_v2a.py", "v2/stability.py", "v2/collar_rule.py", "v2/femur_3406.py",
            "v2/torsion_load.py", "v2/pose_fixed.py", "v2/bond_collar.py", "v2/resorption.py", "v2/shielding.py", "inp_writer.py"]
LOCAL_ONLY = ["tools/db_export.py", "tools/db_qa.py", "tools/db_archive.py", "v2/solve_worker.py", "v2/remote.py"]


def run(cmd: list[str], timeout: float = 60, cwd: pathlib.Path | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=str(cwd or ROOT))
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def lf_md5(data: bytes) -> str:
    return hashlib.md5(data.replace(b"\r\n", b"\n")).hexdigest()[:8]


def git_section() -> tuple[list[str], dict]:
    rc, head = run(["git", "rev-parse", "--short", "HEAD"])
    head = head.strip() if rc == 0 else "?"
    rc, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    rc, por = run(["git", "status", "--porcelain"])
    lines = [ln for ln in por.splitlines() if ln.strip()]
    mod = [ln[3:] for ln in lines if not ln.startswith("??")]
    new = [ln[3:] for ln in lines if ln.startswith("??")]
    rc, remote = run(["git", "rev-parse", "--short", "j/master"])
    out = [f"| HEAD | `{head}` 在 `{branch.strip()}` |", f"| 远程 j/master | `{remote.strip() if rc == 0 else '?'}` |",
           f"| 已跟踪但未提交 | {len(mod)} 个：{', '.join('`%s`' % m for m in mod) or '无'} |",
           f"| 未跟踪 | {len(new)} 个：{', '.join('`%s`' % n for n in new) or '无'} |"]
    return out, {"head": head, "dirty": mod, "untracked": new}


def freeze_section() -> list[str]:
    if not FREEZE.exists():
        return ["冻结清单不存在：`docs/freeze/M1-3406-v1.json`"]
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    bad = []
    h = hashlib.sha256()
    for rel, info in fz["hashed_files"].items():
        p = ROOT / rel
        b = p.read_bytes() if p.exists() else b""
        h.update(b)
        if hashlib.sha256(b).hexdigest() != info["sha256"]:
            bad.append(rel)
    ch = h.hexdigest()[:10]
    ok = not bad and ch == fz["code_hash"]
    line = f"| code_hash（本地工作区） | `{ch}`，冻结值 `{fz['code_hash']}` | {'完好' if ok else '**已破坏**'} |"
    rows = [line, f"| 8 个哈希文件 | {', '.join('`%s`' % r.split('/')[-1] for r in fz['hashed_files'])} | 一个字节都不改；`ops/check_freeze.py` |"]
    if bad:
        rows.append(f"| 变动的哈希文件 | {', '.join('`%s`' % b for b in bad)} | **立即停止，不要提交** |")
    rows.append(f"| 股骨 | `{fz['femur']['femur_id']}` / `{fz['femur']['femur_model_version']}` / 键 `{fz['femur']['femur_geom_key']}` | 登记表 `db3406/femur_registry.json` |")
    return rows


def head_md5(rel: str) -> str:
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, cwd=str(ROOT))
    return lf_md5(r.stdout) if r.returncode == 0 else "—"


def linux(cmd: str, timeout: float = 120) -> tuple[int, str]:
    return run([SSH, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-i", KEY, HOST, cmd], timeout=timeout)


LINUX_SCRIPT = r"""
cd ~/mobo_toy_v2 || exit 9
echo "@@VERSION"; cat code/VERSION 2>/dev/null; echo "mtime $(stat -c %y code/VERSION 2>/dev/null | cut -c1-16)"
echo "@@MD5"; cd code && for f in %FILES%; do [ -f "$f" ] && printf "%s  %s\n" "$(tr -d '\r' < "$f" | md5sum | cut -c1-32)" "$f"; done; cd ..
echo "@@CODEHASH"; cd code/v2 && cat femur_real.py geom3d.py fe3d_geom.py model3d_v2.py post.py config_v2a.yaml model3d_m1.py post_m1.py | sha256sum | cut -c1-10; cd ../..
echo "@@PROCS"; pgrep -af 'stage_v2a.py serve|stage_db.py feed|stage_al.py|train_' | grep -v pgrep
echo "@@MON"; for p in $(pgrep -f 'sleep [0-9]+$' | head -8); do pp=$(ps -o ppid= -p $p 2>/dev/null | tr -d ' '); printf "%s <- %s\n" "$(ps -o args= -p $p)" "$(ps -o args= -p $pp 2>/dev/null | cut -c1-80)"; done | sort | uniq -c
echo "@@SERVE"; for p in $(pgrep -f 'stage_v2a.py serve' | head -1); do ps -o lstart= -p $p; done; stat -c '%y %n' code/v2/jobs.py code/v2/stage_db.py 2>/dev/null | cut -c1-16,36-
echo "@@FLAGS"; ls -1 2>/dev/null | grep -E '^(STOP|DB_)'; ls -1 queue 2>/dev/null | grep -E '^STOP'
echo "@@QUEUE"; for m in NEW READY CLAIMED SOLVED DONE; do printf "%s %s\n" $m "$(ls -d queue/*/$m 2>/dev/null | wc -l)"; done; printf "FAILED %s\n" "$(ls queue/*/FAILED.json 2>/dev/null | wc -l)"
echo "@@READY_AGE"; for f in $(ls -d queue/*/READY 2>/dev/null); do d=$(dirname $f); [ -e $d/CLAIMED ] || printf "%s %s\n" "$(( ($(date +%s) - $(stat -c %Y $f)) / 60 ))" "$(basename $d)"; done | sort -rn | head -5
echo "@@DISK"; df -h / | tail -1; df -h /mnt/nvme 2>/dev/null | tail -1
echo "@@MANIFESTS"; ls -t results/db_manifest_*.json 2>/dev/null | head -4
echo "@@STATUS"
for b in $(ls -t results/db_manifest_*.json 2>/dev/null | head -3 | sed 's/.*db_manifest_//; s/\.json//'); do
  echo "== $b"; timeout 90 nice -n 19 ./run.sh code/v2/stage_db.py status $b --root ~/mobo_toy_v2 2>&1 | head -40
done
"""


def parse_blocks(text: str) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    cur = None
    for ln in text.splitlines():
        if ln.startswith("@@"):
            cur = ln[2:].strip()
            blocks[cur] = []
        elif cur is not None:
            blocks[cur].append(ln)
    return blocks


def deploy_section(use_linux: bool) -> tuple[list[str], list[str]]:
    files = [f for f in DEPLOYED if (ROOT / f).exists()]
    remote_md5: dict[str, str] = {}
    blocks: dict[str, list[str]] = {}
    note = []
    if use_linux:
        rc, out = linux(LINUX_SCRIPT.replace("%FILES%", " ".join(files)), timeout=300)
        if rc != 0 and "@@VERSION" not in out:
            note.append(f"Linux 不可达或命令失败（rc {rc}）：`{out.strip()[:200]}`")
        blocks = parse_blocks(out)
        for ln in blocks.get("MD5", []):
            parts = ln.split()
            if len(parts) == 2:
                remote_md5[parts[1]] = parts[0][:8]
    rows = ["| 文件 | HEAD | 本地 | Linux | 判断 |", "|---|---|---|---|---|"]
    n_bad = 0
    for f in files + [x for x in LOCAL_ONLY if (ROOT / x).exists()]:
        loc = lf_md5((ROOT / f).read_bytes())
        hd = head_md5(f)
        rm = remote_md5.get(f, "只在 Windows 跑" if f in LOCAL_ONLY else ("?" if use_linux else "未查"))
        if f in LOCAL_ONLY:
            verdict = "同" if hd == loc else "**本地未提交**"
        else:
            verdict = "同" if hd == loc == rm else ("**三处不一致**" if len({hd, loc, rm}) == 3 else ("**本地未提交**" if hd != loc else "**Linux 与本地不同**"))
        if verdict != "同":
            n_bad += 1
        rows.append(f"| `{f}` | {hd} | {loc} | {rm} | {verdict} |")
    rows.insert(0, f"不一致 {n_bad} 个（md5 去 CR 后前 8 位）。" + (" " + "；".join(note) if note else ""))
    ver = blocks.get("VERSION", [])
    rows.append("")
    rows.append("Linux `code/VERSION`：`" + " | ".join(v.strip() for v in ver if v.strip()) + "`（整包同步时写；单文件 put 不更新，所以常过时；它的 12 位 code_hash 是 remote.py 对同步列表算的，不是作业的 10 位 code_hash）" if ver else "Linux `code/VERSION`：未读到")
    lch = [x.strip() for x in blocks.get("CODEHASH", []) if x.strip()]
    if lch:
        rows.append(f"Linux 上 8 个哈希文件的 code_hash：`{lch[0]}`" + ("，与冻结值一致" if lch[0] == "6d7af243d0" else "，**与冻结值不一致**"))
    return rows, blocks


def linux_section(blocks: dict[str, list[str]]) -> list[str]:
    if not blocks:
        return ["未查 Linux。"]
    out = []
    procs = [p for p in blocks.get("PROCS", []) if p.strip()]
    out.append("**进程**：" + ("；".join("`" + re.sub(r"^\d+\s+\S+/python\s+", "", p.strip()) + "`" for p in procs) if procs else "没有 serve、喂料器或训练在跑"))
    mon = [p for p in blocks.get("MON", []) if p.strip()]
    out.append("**Linux 端的 sleep 循环（个数 × 命令 <- 父进程）**：" + ("；".join("`" + p.strip()[:110] + "`" for p in mon) if mon else "没有") + "。红线 4 要求一个项目只有一个监视器：父进程是 `bash -c` 带 ssh 的那条就是 Windows 发来的监视器。")
    sv = [s.strip() for s in blocks.get("SERVE", []) if s.strip()]
    if sv:
        out.append(f"**serve 启动时间**：`{sv[0]}`；Linux 上 jobs.py / stage_db.py 的 mtime：" + "；".join("`%s`" % s for s in sv[1:]) + "。serve 对每个作业重新 import，所以钩子文件比 serve 新也会生效。")
    flags = [f for f in blocks.get("FLAGS", []) if f.strip()]
    out.append("**标记文件**：" + (", ".join("`%s`" % f for f in flags) if flags else "无"))
    q = dict(ln.split() for ln in blocks.get("QUEUE", []) if len(ln.split()) == 2)
    out.append("**队列**（标记文件累计计数，一个作业可同时有多个；FAILED 含 prep 失败，所以 DONE + FAILED ≠ SOLVED 正常）：" + ", ".join(f"{k} {v}" for k, v in q.items()))
    ra = [ln for ln in blocks.get("READY_AGE", []) if ln.strip()]
    stop_present = (ROOT / "v2" / "runs" / "worker.STOP").exists()
    if ra:
        oldest = ra[0].split()
        why = ""
        if int(oldest[0]) > 60:
            why = "。worker 被用户停着（`worker.STOP` 存在），没人领是预期的；恢复要用户说" if stop_present else "。**超过 60 分钟没人领而 worker 没被停，查 worker**"
        out.append(f"**未认领的 READY**：{len(ra)} 个以上，最老 {oldest[0]} 分钟（`{oldest[1]}`）" + why)
    else:
        out.append("**未认领的 READY**：0")
    disk = [d.split() for d in blocks.get("DISK", []) if d.strip()]
    for d in disk:
        if len(d) >= 6:
            out.append(f"**磁盘** `{d[5]}`：剩 {d[3]}（已用 {d[4]}）")
    st = blocks.get("STATUS", [])
    if st:
        out.append("")
        out.append("**最近 3 个批次（`stage_db.py status`）**")
        out.append("```")
        out.extend(ln.rstrip()[:160] for ln in st if ln.strip())
        out.append("```")
    return out


def windows_section() -> list[str]:
    runs = ROOT / "v2" / "runs"
    out = []
    pid = (runs / "worker.pid").read_text().strip() if (runs / "worker.pid").exists() else ""
    alive = False
    if pid:
        rc, t = run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])
        alive = pid in t
    out.append(f"**worker**：pid `{pid or '无'}` {'活着' if alive else '不在'}；`worker.STOP` {'存在（不会自动重启）' if (runs / 'worker.STOP').exists() else '不存在'}")
    rc, t = run(["tasklist", "/FI", "IMAGENAME eq standard.exe", "/NH"])
    n_abq = sum(1 for ln in t.splitlines() if ln.lower().startswith("standard.exe"))
    out.append(f"**Abaqus 求解进程**：{n_abq}")
    log = runs / "worker.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3:]
        out.append("**worker.log 末 3 行**：")
        out.append("```")
        out.extend(ln[:150] for ln in tail)
        out.append("```")
    return out


def db_section() -> list[str]:
    if not DB_ROOT.exists():
        return [f"数据库目录不存在：`{DB_ROOT}`"]
    vers = sorted([p for p in DB_ROOT.glob("v*") if p.is_dir() and (p / "manifest.json").exists()],
                  key=lambda p: [int(x) for x in re.findall(r"\d+", p.name)])
    if not vers:
        return ["没有带 manifest 的版本目录"]
    v = vers[-1]
    m = json.loads((v / "manifest.json").read_text(encoding="utf-8"))
    qa = v / "qa_report.json"
    fails = []
    if qa.exists():
        q = json.loads(qa.read_text(encoding="utf-8"))
        fails = [str(c["id"]) for c in q.get("checks", []) if c.get("status") == "FAIL"]
    return [f"| 最新版本 | `{v.name}`，{m.get('n_rows')} 行，无偏 {m.get('n_unbiased')}，E {m.get('n_E_design_keys')}，finalize {m.get('finalized_utc')} |",
            f"| 导出器 | {m.get('exporter_version')} |",
            f"| QA FAIL 的检查 | {', '.join(fails) or '无'}（基线：1、7、13 为已知行；新增才算失败） |"]


def decisions_section() -> list[str]:
    if not PLAN.exists():
        return ["第三版计划文件不存在"]
    txt = PLAN.read_text(encoding="utf-8")
    m = re.search(r"## 9 要定的事(.*?)\n## ", txt, re.S)
    rows = [ln for ln in (m.group(1).splitlines() if m else []) if ln.startswith("| ") and not ln.startswith("| #") and not ln.startswith("|---")]
    heads = list(re.finditer(r"^\*\*(\d{2}-\d{2} \d{2}:\d{2} UTC[^*]*)\*\*", txt, re.M))
    out = [f"第三版第 9 节列了 {len(rows)} 项要人定的事（`docs/goal.md` 第 5 节列其中卡交付物的 8 项）。"]
    if heads:
        h = heads[-1]
        body = txt[h.end():].strip().splitlines()
        excerpt = [ln.rstrip()[:200] for ln in body[:8]]
        out.append(f"第 12 节最后一条记录：**{h.group(1).strip()}**（原文前 {len(excerpt)} 行）")
        out.append("")
        out.extend("> " + ln for ln in excerpt)
    return out


REORG = pathlib.Path(r"H:\projects\application\research-log\neck_implant_2026-10-02\项目重组提议_2026-11-04.md")


def reorg_section() -> list[str]:
    if not REORG.exists():
        return ["重组提议文件不存在"]
    txt = REORG.read_text(encoding="utf-8")
    m = re.search(r"## 7 迁移步骤(.*?)\n## 8 ", txt, re.S)
    rows = [ln for ln in (m.group(1).splitlines() if m else []) if re.match(r"^\| \d ", ln)]
    out = ["| 步 | 内容 | 状态 |", "|---|---|---|"]
    for ln in rows:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 4:
            continue
        done = re.search(r"\*\*(\d{2}-\d{2} \d{2}:\d{2} UTC 做完)", cells[3])
        st = done.group(1) if done else ("Gate 1 之后" if "Gate 1 后" in cells[1] else "未做")
        out.append(f"| {cells[0]} | {cells[1][:60]} | {st} |")
    out.append("执行者：第 1–4 步重组会话，第 0 步实验会话（b24 撤销后）；第 5 步未批准。详情在提议文件第 7–9 节。")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-linux", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "STATE.md"))
    a = ap.parse_args()
    t0 = time.time()
    git_rows, g = git_section()
    dep_rows, blocks = deploy_section(not a.no_linux)
    parts = [
        "# STATE.md",
        f"由 `ops/state.py` 生成于 {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}（本机时间 {time.strftime('%H:%M')}），不要手改。",
        "", "## 1 仓库", "| 项 | 值 |", "|---|---|", *git_rows,
        "", "## 2 冻结模型 M1-3406-v1", "| 项 | 值 | 判断 |", "|---|---|---|", *freeze_section(),
        "", "## 3 部署版本（HEAD / 本地工作区 / Linux）", *dep_rows,
        "", "## 4 Linux 流水线", *linux_section(blocks),
        "", "## 5 Windows 求解", *windows_section(),
        "", "## 6 数据库 db3406", "| 项 | 值 |", "|---|---|", *db_section(),
        "", "## 7 待定与记录", *decisions_section(),
        "", "## 8 重组进度", *reorg_section(),
        "", f"生成用时 {time.time() - t0:.0f} s。", "",
    ]
    pathlib.Path(a.out).write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
