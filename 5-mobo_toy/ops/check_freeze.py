"""核对冻结模型 M1-3406-v1：工作区里 8 个哈希文件的字节是否等于 docs/freeze/M1-3406-v1.json 记录的 sha256。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/check_freeze.py            # 核对，不一致退出码 1
    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/check_freeze.py --restore  # 从 docs/freeze/M1-3406-v1_files.tar 写回 8 个文件的原字节（先备份到 .bak）
    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/check_freeze.py --staged   # 另外比 git 暂存区（LF）与 JSON 的 sha256_lf：提交前用

为什么要比字节而不是比 git：code_hash 按文件字节算，8 个文件里 5 个在工作区是 CRLF、3 个是 LF，git 对象一律 LF。
从 git 重新检出得到的文件算不出 6d7af243d0（全 LF 是 ebefa65488）。所以冻结的"真身"是 JSON 里的 sha256 和同目录的 tar，不是 git 对象。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FREEZE = ROOT / "docs" / "freeze" / "M1-3406-v1.json"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    fz = json.loads(FREEZE.read_text(encoding="utf-8"))
    say = (lambda *x: None) if a.quiet else print

    if a.restore:
        tar = (ROOT / fz["files_tar"]["path"]).read_bytes()
        if sha(tar) != fz["files_tar"]["sha256"]:
            print("tar 的 sha256 与 JSON 不符，拒绝恢复"); return 2
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            for m in tf.getmembers():
                p = ROOT / m.name
                b = tf.extractfile(m).read()
                if p.exists() and p.read_bytes() != b:
                    p.with_suffix(p.suffix + ".bak").write_bytes(p.read_bytes())
                p.write_bytes(b)
                say("restored", m.name)

    bad = []
    h = hashlib.sha256()
    for rel, info in fz["hashed_files"].items():
        p = ROOT / rel
        b = p.read_bytes() if p.exists() else b""
        h.update(b)
        ok = sha(b) == info["sha256"]
        if not ok:
            bad.append(rel)
        say(f"{'OK ' if ok else 'BAD'} {rel}  {'CRLF' if info.get('crlf') else 'LF'}")
    ch = h.hexdigest()[:10]
    say(f"code_hash {ch}  frozen {fz['code_hash']}")
    rc = 0
    if bad or ch != fz["code_hash"]:
        print(f"冻结被破坏：{', '.join(bad) or 'code_hash 不符'}。不要提交、不要部署；用 --restore 写回原字节，或先写 ADR 换版本。")
        rc = 1

    if a.staged:
        for rel, info in fz["hashed_files"].items():
            r = subprocess.run(["git", "show", f":{rel}"], capture_output=True, cwd=str(ROOT))
            if r.returncode != 0:
                print(f"暂存区没有 {rel}"); rc = 1; continue
            if sha(r.stdout) != info["sha256_lf"]:
                print(f"暂存区的 {rel} 内容变了（LF 比较）"); rc = 1
            else:
                say(f"OK  staged {rel}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
