"""修复 deck_F_ids.json（2026-10-06 18:00）：重新提交批次 F 时领宽舍入方式改了（round → floor），被收窄的设计领宽差 ≤ 0.0005 mm，
生成了新作业号并覆盖了作业表里已解的作业。处理：同一键下若已有 DONE 的旧作业，作业表指回旧作业；新生成、还没开始建模求解的重复作业删掉。
只动本批次今天生成的作业目录（stage front_wrap / load_wrap），不碰任何其他作业。"""
import json
import pathlib
import shutil
import sys

HOME = pathlib.Path.home() / "mobo_toy_v2"
sys.path.insert(0, str(HOME / "code")); sys.path.insert(0, str(HOME / "code" / "v2"))
import jobs as J  # noqa: E402

f = J.RESULTS / "deck_F_ids.json"
meta = json.loads(f.read_text())
ids = meta["jobs"]
by_key = {}
for d in J.QROOT.iterdir():
    if not d.name.startswith(("front_wrap_", "load_wrap_")) or not (d / "spec.json").exists():
        continue
    sp = json.loads((d / "spec.json").read_text())
    if sp.get("stage") == "front_wrap":
        key = f"F1_{sp['source_job']}" + ("_contact" if sp.get("bond_only") else "")
    else:
        key = f"F2_{sp.get('tag')}" if sp.get("tag", "").endswith(("_iso", "_high", "_stair")) else None
        if key and key.endswith("_stair"):
            key = "F2_S1B_stair"
    if key in ids:
        by_key.setdefault(key, []).append(d)
changed, removed = [], []
for key, dirs in by_key.items():
    if len(dirs) < 2:
        continue
    done = [d for d in dirs if J.state(d) == "DONE"]
    cur = J.QROOT / ids[key]
    if done and J.state(cur) != "DONE":
        ids[key] = done[0].name
        changed.append((key, cur.name, done[0].name))
        if J.state(cur) in ("NEW", "READY"):                       # 还没被求解端领走
            shutil.rmtree(cur)
            removed.append(cur.name)
meta["jobs"] = ids
meta["fixed"] = "2026-10-06 18:00 restored DONE jobs after the rounding change; removed unclaimed duplicates"
f.write_text(json.dumps(meta, indent=1))
print("restored", len(changed)); [print("  ", c) for c in changed]
print("removed", removed)
