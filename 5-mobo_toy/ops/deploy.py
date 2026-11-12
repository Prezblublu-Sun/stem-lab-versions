"""部署门：把代码推到 Linux 之前核对，推完写 VERSION 和 deployed_md5.txt。向 Linux 写文件要用户在对话里明确授权。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/deploy.py --check                 # 只比对，不写（随时可跑）
    ... ops/deploy.py --files v2/stage_db.py v2/tests/x.py        # 推这些文件（必须已提交、已推到 j）
    ... ops/deploy.py --files experiments/b34_x/rows_in.json      # 行文件批次的行文件：Linux 上没有这个目录时先建（只对 experiments/ 下的路径建）
    ... ops/deploy.py --files ... --allow-dirty                   # 例外：用户明确要求推未提交的文件时才用，VERSION 记 dirty
    ... ops/deploy.py --files ... --allow-aux-with-feeders        # 例外：用户明确要求在喂料器跑着时推辅助代码时才用

门（不过就退出，什么都不推）：
  1 冻结完好（ops/check_freeze.py）；
  2 要推的每个文件在工作区与 HEAD 相同（去 CR 比），除非 --allow-dirty；
  3 HEAD 已在远程 j/master 上（git merge-base --is-ancestor HEAD j/master），除非 --allow-dirty；
  4 推完逐文件比 Linux 的 LF md5 与本地一致，不一致报错；
  5 要推的文件里有辅助代码（不进 code_hash、但影响结果：v2/stage_db.py 和 tools/db_export.py 两份 AUX_FILES 的并集，按源码读），
    而 Linux 上有喂料器活着（logs/db_feed_<批次>.pid 的进程在）→ 拒绝，除非 --allow-aux-with-feeders。喂料器每轮核对辅助代码的 md5，
    变了就停，重启也拒绝（2026-11-08 13:09 UTC 部署 F5 版 jobs.py 时 b29–b31 就这样停了，见 experiments/b32_f5smoke/note.md）。
VERSION 内容：git=<HEAD>[-dirty]  deployed=<UTC>  by=ops/deploy.py  files=<n>；deployed_md5.txt 每行 "<lf md5> <路径>"（SYNC 列表里存在的文件）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2"))
import remote as R  # noqa: E402


SAFE_REL = __import__("re").compile(r"[A-Za-z0-9_.+-]+(/[A-Za-z0-9_.+-]+)*")


def lf_md5(b: bytes) -> str:
    return hashlib.md5(b.replace(b"\r\n", b"\n")).hexdigest()


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], capture_output=True, cwd=str(ROOT))
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").strip()


def head_bytes(rel: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, cwd=str(ROOT))
    return r.stdout if r.returncode == 0 else None


def remote_md5(rels: list[str]) -> dict[str, str]:
    cmd = "cd ~/%s/code && for f in %s; do [ -f \"$f\" ] && printf '%%s %%s\\n' \"$(tr -d '\\r' < \"$f\" | md5sum | cut -c1-32)\" \"$f\"; done" % (R.RBASE, " ".join(rels))
    out = R.sh(cmd, timeout=120)
    res = {}
    for ln in out.splitlines():
        p = ln.split()
        if len(p) == 2:
            res[p[1]] = p[0]
    return res


def result_files() -> set[str]:
    """不进 code_hash、但影响结果的文件：v2/stage_db.py 和 tools/db_export.py 里 AUX_FILES 的并集（路径相对代码根，按源码读，不 import）。"""
    out = set()
    for rel in ("v2/stage_db.py", "tools/db_export.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        vals = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "AUX_FILES" for t in n.targets)]
        if len(vals) != 1:
            raise SystemExit(f"门 5：{rel} 里找到 {len(vals)} 个 AUX_FILES，应为 1 个")
        out |= set(vals[0])
    return out


def live_feeders() -> list[str]:
    """Linux 上活着的喂料器：['b29 2432401', ...]。"""
    out = R.sh(f"cd ~/{R.RBASE}/logs && for f in db_feed_*.pid; do [ -f \"$f\" ] || continue; p=$(cat \"$f\"); "
               f"kill -0 \"$p\" 2>/dev/null && echo \"${{f#db_feed_}} $p\"; done; true", timeout=60)
    return [ln.replace(".pid", "").strip() for ln in out.splitlines() if ln.strip()]


def aux_gate(rels: list[str], aux: set[str], live: list[str]) -> str | None:
    """门 5：要推辅助代码而有喂料器活着 → 拒绝的原因；否则 None。"""
    hit = sorted(set(rels) & aux)
    if hit and live:
        return (f"门 5：{', '.join(hit)} 是喂料器核对的辅助代码（不进 code_hash、但影响结果），Linux 上有喂料器在跑：{'; '.join(live)}。"
                "现在推，它们下一轮就停，重启也会被拒。等它们跑完再推；用户明确要这样做时才加 --allow-aux-with-feeders")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--allow-aux-with-feeders", action="store_true")
    a = ap.parse_args()

    r = subprocess.run([sys.executable, str(ROOT / "ops" / "check_freeze.py"), "--quiet"], cwd=str(ROOT))
    if r.returncode != 0:
        print("门 1：冻结被破坏，停止"); return 1
    rc, head = git("rev-parse", "--short", "HEAD")
    rc, por = git("status", "--porcelain", "--", "v2", "tools", "inp_writer.py", "config.yaml")
    dirty = [ln[3:] for ln in por.splitlines() if ln.strip()]
    rc_anc, _ = git("merge-base", "--is-ancestor", "HEAD", "j/master")
    sync_files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in R._files()]

    if a.check:
        rm = remote_md5(sync_files)
        n_bad = 0
        for rel in sync_files:
            loc = lf_md5((ROOT / rel).read_bytes())
            hb = head_bytes(rel)
            hd = lf_md5(hb) if hb is not None else "—"
            lin = rm.get(rel, "缺")
            flag = "" if (loc == lin and (hd == loc or hd == "—")) else ("本地未提交" if hd != loc and hd != "—" else "Linux 不同")
            if flag:
                n_bad += 1
                print(f"{flag:8s} {rel}  HEAD {hd[:8]}  本地 {loc[:8]}  Linux {lin[:8]}")
        print(f"HEAD {head}，{'已' if rc_anc == 0 else '未'}推到 j/master；流水线文件未提交 {len(dirty)} 个；与 Linux 或 HEAD 不一致 {n_bad} 个。")
        ver = R.sh(f"cat ~/{R.RBASE}/code/VERSION 2>/dev/null", timeout=30).strip().replace("\n", " | ")
        print(f"Linux VERSION：{ver or '无'}")
        return 0

    if not a.files:
        print("要推什么？--files ...；只看就 --check"); return 2
    rels = [f.replace("\\", "/") for f in a.files]
    for rel in rels:
        if not (ROOT / rel).exists():
            print(f"没有 {rel}"); return 1
        if not SAFE_REL.fullmatch(rel):
            print(f"路径 {rel!r} 里有不能放进远端命令的字符（只许字母、数字、/ . _ + -）"); return 1
    if not a.allow_dirty:
        bad = []
        for rel in rels:
            hb = head_bytes(rel)
            if hb is None or lf_md5(hb) != lf_md5((ROOT / rel).read_bytes()):
                bad.append(rel)
        if bad:
            print("门 2：这些文件未提交或与 HEAD 不同，先提交：" + ", ".join(bad)); return 1
        if rc_anc != 0:
            print("门 3：HEAD 还没推到 j/master，先 git push j master"); return 1
    hashed = set(json.loads((ROOT / "docs" / "freeze" / "M1-3406-v1.json").read_text(encoding="utf-8"))["hashed_files"])
    if hashed & set(rels):
        print("门 1：哈希文件不部署（code_hash 按字节算）：" + ", ".join(sorted(hashed & set(rels)))); return 1
    aux = result_files()
    if set(rels) & aux:
        why = aux_gate(rels, aux, live_feeders())
        if why and not a.allow_aux_with_feeders:
            print(why); return 1
        if why:
            print("注意：" + why.replace("门 5：", "") + "（--allow-aux-with-feeders，照推）")
    print(f"推 {len(rels)} 个文件到 Linux（HEAD {head}{'-dirty' if a.allow_dirty else ''}）…")
    for rel in rels:
        p = pathlib.PurePosixPath(rel)          # 按 LF 字节推，先写临时文件再改名，import 不会读到半个文件
        mk = f"mkdir -p ~/{R.RBASE}/code/{p.parent} && " if rel.startswith("experiments/") else ""   # 行文件批次的 rows_in.json：批次目录在 Linux 上还没有
        R.sh(f"{mk}cd ~/{R.RBASE}/code/{p.parent} && cat > .{p.name}.new && mv .{p.name}.new {p.name}", stdin=(ROOT / rel).read_bytes().replace(b"\r\n", b"\n"), timeout=600)
    rm = remote_md5(rels)
    bad = [rel for rel in rels if rm.get(rel) != lf_md5((ROOT / rel).read_bytes())]
    if bad:
        print("门 4：推完 md5 不一致：" + ", ".join(bad)); return 1
    rm_all = remote_md5(sync_files)
    lines = [f"{rm_all.get(rel, '-')} {rel}" for rel in sync_files]
    ver = f"git={head}{'-dirty' if a.allow_dirty else ''}\ndeployed={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\nby=ops/deploy.py\nfiles={len(rels)}\n"
    R.sh(f"cat > ~/{R.RBASE}/code/VERSION", stdin=ver.encode(), timeout=30)
    R.sh(f"cat > ~/{R.RBASE}/code/deployed_md5.txt", stdin=("\n".join(lines) + "\n").encode(), timeout=30)
    print("完成：" + ", ".join(rels) + f"；VERSION 已写（{head}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
