"""FEA 示例：读 task.json，每个点用一个公式顶替有限元，报进度，写结果。示例，不是科学。"""
import csv
import json
import math
import os
import sys
import time

run = sys.argv[1]
with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
    task = json.load(f)
S = task["settings"]


def progress(done, total, note):
    with open(task["progress"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"done": done, "total": total, "note": note}, ensure_ascii=False) + "\n")


with open(task["inputs"]["bone"], encoding="utf-8") as f:
    bone = json.load(f)
with open(task["inputs"]["points"], encoding="utf-8-sig", newline="") as f:
    points = list(csv.DictReader(f))

rows = []
for i, p in enumerate(points, 1):
    progress(i - 1, len(points), f"算第 {i} 个点：{p['name']}")
    print(f"点 {p['name']}：柄长 {p['length']} mm，偏距 {p['offset']} mm", flush=True)
    length, offset = float(p["length"]), float(p["offset"])
    # 顶替有限元的公式（随手写的）：力越大、偏距越大、柄越短、皮质越薄，应力越大
    moment = S["load"] * math.cos(math.radians(S["angle"])) * (offset + 20) / 1000
    stress = moment / (length / 100) / bone["cortex_mm"] * 4 * (1 + 0.01 * S["mesh"])
    motion = 0.0 if S["bonded"] else S["load"] / 100 * (1 - S["friction"]) / bone["density"] * (150 / length)
    rows.append({"name": p["name"], "length": length, "offset": offset,
                 "max_stress": round(stress, 3), "micromotion": round(motion, 3)})
    time.sleep(S["pause"])
progress(len(points), len(points), "写结果")

os.makedirs(task["out"], exist_ok=True)
with open(os.path.join(task["out"], "results.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({
        "reports": {"max_stress": max(r["max_stress"] for r in rows),
                    "mean_micromotion": round(sum(r["micromotion"] for r in rows) / len(rows), 3)},
        "outputs": [{"type": "结果", "name": f"{bone.get('name', '骨')}的 FEA 示例结果", "path": "out/results.csv"}],
        "table": "out/results.csv",
    }, f, ensure_ascii=False, indent=2)
print("算完了", flush=True)
