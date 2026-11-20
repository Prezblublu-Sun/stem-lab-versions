"""代理示例：读结果表，最小二乘拟合多项式，报留出点上的误差，产出一个“模型”。示例，不是科学。"""
import csv
import json
import math
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


def terms(x, degree):
    """多项式的各项：1、各列、（二次时）各列两两相乘。x 已经缩放到 0~1。"""
    out = [1.0] + list(x)
    if degree == 2:
        out += [x[i] * x[j] for i in range(len(x)) for j in range(i, len(x))]
    return out


def solve(a, b):
    """高斯消元解 a·β = b。"""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c and m[c][c]:
                f = m[r][c] / m[c][c]
                m[r] = [v - f * w for v, w in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


steps = 4
progress(0, steps, "读结果表")
features = [c.strip() for c in S["features"].split(",") if c.strip()]
with open(task["inputs"]["result"], encoding="utf-8-sig", newline="") as f:
    rows = [r for r in csv.DictReader(f)]
missing = [c for c in features + [S["target"]] if rows and c not in rows[0]]
if not rows or missing:
    sys.exit(f"结果表里没有这些列：{missing}（有的是 {list(rows[0]) if rows else '空表'}）")
X = [[float(r[c]) for c in features] for r in rows]
y = [float(r[S["target"]]) for r in rows]
ranges = {c: [min(x[i] for x in X), max(x[i] for x in X)] for i, c in enumerate(features)}
scale = lambda x: [(v - ranges[c][0]) / ((ranges[c][1] - ranges[c][0]) or 1) for v, c in zip(x, features)]
time.sleep(S["pause"])

progress(1, steps, "分出留出的点")
idx = list(range(len(rows)))
random.Random(S["seed"]).shuffle(idx)
k = int(len(idx) * S["holdout"])
test, train = (idx[:k], idx[k:]) if k else (idx, idx)
degree = 2 if S["degree"] == "二次" else 1
time.sleep(S["pause"])

progress(2, steps, f"在 {len(train)} 个点上拟合{S['degree']}多项式")
T = [terms(scale(X[i]), degree) for i in train]
n = len(T[0])
ata = [[sum(t[a] * t[b] for t in T) + (1e-9 if a == b else 0) for b in range(n)] for a in range(n)]
aty = [sum(t[a] * y[i] for t, i in zip(T, train)) for a in range(n)]
coef = solve(ata, aty)
time.sleep(S["pause"])

progress(3, steps, f"在 {len(test)} 个点上算误差")
pred = {i: sum(c * t for c, t in zip(coef, terms(scale(X[i]), degree))) for i in test}
rmse = math.sqrt(sum((pred[i] - y[i]) ** 2 for i in test) / len(test))
rel = 100 * rmse / (sum(abs(y[i]) for i in test) / len(test) or 1)
time.sleep(S["pause"])
progress(steps, steps, "写出模型")

os.makedirs(task["out"], exist_ok=True)
with open(os.path.join(task["out"], "model.json"), "w", encoding="utf-8") as f:
    json.dump({"kind": "polynomial", "note": "代理示例拟合的多项式，示例，不是科学",
               "features": features, "target": S["target"], "degree": degree, "ranges": ranges,
               "coef": coef, "trained_on": task["inputs"]["result"]}, f, ensure_ascii=False, indent=2)
with open(os.path.join(task["out"], "check.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(features + [S["target"], "预测", "差"])
    for i in test:
        w.writerow(X[i] + [y[i], round(pred[i], 3), round(pred[i] - y[i], 3)])
with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"rel_error": round(rel, 3), "rmse": round(rmse, 4)},
               "outputs": [{"type": "模型", "name": S["model_name"], "path": "out/model.json"}],
               "table": "out/check.csv"}, f, ensure_ascii=False, indent=2)
print(f"拟合完了：留出 {len(test)} 个点，相对误差 {rel:.2f}%", flush=True)
