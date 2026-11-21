"""已解作业的盘点（只读）：按 kind 与 stage 计数，设计类作业中不同设计向量的个数。"""
import json
import pathlib
from collections import Counter

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
kinds, stages, designs = Counter(), Counter(), set()
for d in Q.iterdir():
    if not (d / "DONE").exists() or not (d / "spec.json").exists():
        continue
    s = json.loads((d / "spec.json").read_text())
    kinds[s.get("kind")] += 1
    stages[s.get("stage")] += 1
    if s.get("kind") == "design":
        designs.add(json.dumps(s["design"], sort_keys=True))
print("kinds", dict(kinds))
print("stages", dict(stages))
print("distinct designs (kind=design, DONE)", len(designs))
