"""把 Linux 上的喂料清单取回仓库。Linux 这边只读；默认本地也不写，只列对照表。

    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe ops/fetch_feed_manifests.py            # 列：Linux 有哪些，仓库里有没有、一样不一样
    ... ops/fetch_feed_manifests.py --write                                            # 取回：新的写进去，变了的更新，一样的不动

喂料器（v2/stage_db.py feed）把每个批次的清单写在 Linux 的 ~/mobo_toy_v2/results/db_manifest_<批次>.json：代码哈希、股骨几何键、
辅助文件 md5、每行的作业号和状态和时间、事件。它原来只在 Linux，不在 git，也不在批次目录里（设计稿 v0.2 第 1.3 节第 3 条）。

放在哪里：
    experiments/<批次>_<名字>/feed_manifest.json          批次有自己的目录时
    experiments/_feed_manifests/db_manifest_<批次>.json    没有目录的旧批次（b1 到 b24 的大多数），和两个批次合用一个目录时的第二个
    experiments/_feed_manifests/index.json                每个清单的 sha256、字节数、放在哪、取回时间
内容是 Linux 上那个文件的逐字节拷贝。判定（ops/judge.py）会把批次目录里的 feed_manifest.json 的 sha256 记进 result.json 的来历。
在跑的批次清单会变：再跑一次 --write 就更新，index.json 里是最后一次取回时的值。
退出码：0；Linux 连不上 2。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import re
import sys
import tarfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v2"))
sys.path.insert(0, str(ROOT / "ops"))
EXP = ROOT / "experiments"
POOL = "_feed_manifests"
NAME_RE = re.compile(r"db_manifest_([A-Za-z0-9]+)\.json")


def dest_of(batch: str, exp: pathlib.Path = EXP) -> pathlib.Path:
    """Where the manifest of a batch lives in the repo: its own batch directory when there is exactly one, else the pool."""
    hits = sorted(p for p in exp.glob(f"{batch}_*") if p.is_dir())
    return hits[0] / "feed_manifest.json" if len(hits) == 1 else exp / POOL / f"db_manifest_{batch}.json"


def plan(remote: dict, exp: pathlib.Path = EXP) -> list[dict]:
    """remote: {batch: bytes}. One entry per batch: where it goes and whether the repo already holds the same bytes."""
    out = []
    for batch in sorted(remote, key=lambda b: (len(re.sub(r"\D", "", b) or "0"), int(re.sub(r"\D", "", b) or 0), b)):
        raw = remote[batch]
        d = dest_of(batch, exp)
        state = "new" if not d.is_file() else "same" if d.read_bytes() == raw else "changed"
        out.append({"batch": batch, "file": d.relative_to(exp.parent).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "state": state})
    return out


def write(remote: dict, exp: pathlib.Path = EXP) -> list[dict]:
    """Write what is new or changed, byte for byte, and the index. Returns the plan as it was before writing."""
    pl = plan(remote, exp)
    for e in pl:
        if e["state"] != "same":
            d = exp.parent / e["file"]
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(remote[e["batch"]])
    idx_p = exp / POOL / "index.json"
    old = json.loads(idx_p.read_text(encoding="utf-8")) if idx_p.is_file() else {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    idx = {e["batch"]: {"file": e["file"], "sha256": e["sha256"], "bytes": e["bytes"],
                        "fetched_utc": old[e["batch"]]["fetched_utc"] if e["state"] == "same" and e["batch"] in old else now} for e in pl}
    idx_p.parent.mkdir(parents=True, exist_ok=True)
    idx_p.write_text(json.dumps(idx, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return pl


def fetch() -> dict:
    """{batch: bytes} of every results/db_manifest_<batch>.json on Linux. One read-only ssh call (a tar stream)."""
    import remote as R
    r = R._ssh(f"cd ~/{R.RBASE}/results && tar -cf - db_manifest_*.json", timeout=600)
    if r.returncode != 0:
        raise R.RemoteError(f"could not read the manifests ({r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
    out = {}
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        for m in tf.getmembers():
            k = NAME_RE.fullmatch(pathlib.PurePosixPath(m.name).name)
            if k and m.isfile():
                out[k.group(1)] = tf.extractfile(m).read()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="取回 Linux 上的喂料清单。Linux 只读；不加 --write 本地也不写。")
    ap.add_argument("--write", action="store_true", help="把新的和变了的写进仓库，并更新 index.json")
    a = ap.parse_args()
    try:
        remote = fetch()
    except Exception as e:  # noqa: BLE001
        print(f"Linux 读不到：{type(e).__name__}: {str(e)[:300]}")
        return 2
    pl = write(remote) if a.write else plan(remote)
    print("| 批次 | 字节 | sha256 | 仓库里 | 放在 |\n|---|---|---|---|---|")
    zh = {"new": "没有" if not a.write else "新写入", "same": "一样", "changed": "不一样" if not a.write else "已更新"}
    for e in pl:
        print(f"| {e['batch']} | {e['bytes']} | {e['sha256'][:12]} | {zh[e['state']]} | {e['file']} |")
    n = {s: sum(x["state"] == s for x in pl) for s in ("new", "same", "changed")}
    print(f"\nLinux 上 {len(pl)} 个清单，共 {sum(e['bytes'] for e in pl) / 1e6:.1f} MB；仓库里没有的 {n['new']}，一样的 {n['same']}，不一样的 {n['changed']}"
          + ("；已写入" if a.write else "；没有写任何文件（加 --write 才写）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
