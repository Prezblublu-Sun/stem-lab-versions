"""队列普查（只读）：按 stage × kind × 模型 × 代码哈希 × 状态计数，DONE 的才算已解。"""
import collections
import json
import pathlib

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
c = collections.Counter()
hashes = collections.defaultdict(lambda: [None, None, 0])
for d in Q.iterdir():
    if not d.is_dir() or not (d / "spec.json").exists():
        continue
    sp = json.loads((d / "spec.json").read_text())
    st = "DONE" if (d / "DONE").exists() else ("FAILED" if (d / "FAILED.json").exists() else "other")
    h = None
    if (d / "prep.json").exists():
        try:
            h = json.loads((d / "prep.json").read_text()).get("code_hash")
        except Exception:
            h = "?"
    cap = (sp.get("design") or {}).get("cap_h")
    c[(sp.get("stage"), sp.get("kind"), sp.get("model", "v2"), st)] += 1
    if st == "DONE":
        t = (d / "DONE").stat().st_mtime
        e = hashes[h]
        e[0] = t if e[0] is None else min(e[0], t)
        e[1] = t if e[1] is None else max(e[1], t)
        e[2] += 1
for k, v in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][3]))):
    print(v, k)
import time
print("\ncode hashes of DONE jobs (first, last, n):")
for h, (a, b, n) in sorted(hashes.items(), key=lambda x: x[1][0] or 0):
    print(h, time.strftime("%m-%d %H:%M", time.localtime(a)), time.strftime("%m-%d %H:%M", time.localtime(b)), n)
