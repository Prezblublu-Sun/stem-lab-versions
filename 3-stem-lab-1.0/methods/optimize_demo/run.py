"""优化示例：在模型的范围里随机撒点，用模型预测，留下最好的几个点。示例，不是科学。"""
import csv
import json
import os
import random
import sys
import time

run = sys.argv[1]
with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
    task = json.load(f)
S = task["settings"]


def progress(done, total, note):
    with open(task["progress"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"done": done, "total": total, "note": note}, ensure_ascii=False) + "\n")


with open(task["inputs"]["model"], encoding="utf-8") as f:
    model = json.load(f)
features, ranges = model["features"], model["ranges"]


def predict(x):
    """和代理示例同一种多项式：各列先缩放到 0~1。"""
    s = [(x[c] - ranges[c][0]) / ((ranges[c][1] - ranges[c][0]) or 1) for c in features]
    t = [1.0] + s
    if model["degree"] == 2:
        t += [s[i] * s[j] for i in range(len(s)) for j in range(i, len(s))]
    return sum(c * v for c, v in zip(model["coef"], t))


rng = random.Random(S["seed"])
found, batches = [], 10
for b in range(batches):
    progress(b, batches, f"第 {b + 1} 批，已经撒了 {len(found)} 个点")
    for _ in range(S["samples"] // batches + (1 if b < S["samples"] % batches else 0)):
        x = {c: round(rng.uniform(*ranges[c]), 2) for c in features}
        found.append((predict(x), x))
    time.sleep(S["pause"])
progress(batches, batches, "挑出最好的几个")

found.sort(key=lambda p: p[0], reverse=(S["goal"] == "越大越好"))
best = found[:S["keep"]]
os.makedirs(task["out"], exist_ok=True)
with open(os.path.join(task["out"], "points.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name"] + features + ["predicted_" + model["target"]])
    for i, (y, x) in enumerate(best, 1):
        w.writerow([f"opt{i:02d}"] + [x[c] for c in features] + [round(y, 3)])
with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"best": round(best[0][0], 4)},
               "outputs": [{"type": "点", "name": S["points_name"], "path": "out/points.csv"}],
               "table": "out/points.csv"}, f, ensure_ascii=False, indent=2)
print(f"撒了 {len(found)} 个点，最好的预测值 {best[0][0]:.3f}", flush=True)
