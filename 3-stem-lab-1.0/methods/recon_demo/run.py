"""重建示例：把选来的文件当作 CT，按内容和设置算出一根“骨”。示例，不是科学。"""
import hashlib
import json
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


ct = task["inputs"]["ct"]
h = hashlib.sha256()
if os.path.isdir(ct):   # CT 也可以是一个文件夹（一摞切片）
    for root, _, names in sorted(os.walk(ct)):
        for name in sorted(names):
            with open(os.path.join(root, name), "rb") as f:
                h.update(f.read())
else:
    with open(ct, "rb") as f:
        h.update(f.read())
seed = int(h.hexdigest()[:8], 16)

layers = 10
for k in range(layers):
    progress(k, layers, f"分割第 {k + 1} 层")
    print(f"第 {k + 1}/{layers} 层，阈值 {S['threshold']} HU", flush=True)
    time.sleep(S["pause"])
progress(layers, layers, "写出骨")

# 随手写的公式：只为了让设置的变化在结果里看得出来
cortex = round(2.5 + (S["threshold"] - 100) / 1400 * 3 + (seed % 50) / 100, 3)
error = S["voxel"] * (0.6 + (seed % 40) / 100) / (1 + 0.1 * S["smooth"]) * (0.9 if S["fill_holes"] else 1.2)
bone = {"name": S["bone_name"], "note": "示例，不是真的骨", "made_from": ct,
        "length_mm": 400 + seed % 60, "cortex_mm": cortex, "density": round(0.9 + (seed % 70) / 100, 3)}

os.makedirs(task["out"], exist_ok=True)
with open(os.path.join(task["out"], "bone.json"), "w", encoding="utf-8") as f:
    json.dump(bone, f, ensure_ascii=False, indent=2)
with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"surface_error": round(error, 4), "cortex": cortex},
               "outputs": [{"type": "骨", "name": S["bone_name"], "path": "out/bone.json"}]},
              f, ensure_ascii=False, indent=2)
print("重建完了", flush=True)
