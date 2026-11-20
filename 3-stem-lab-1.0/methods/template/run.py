"""空模板的脚本：只演示做法和 stem-lab 之间的全部约定。

1. 启动时，stem-lab 已经在实验目录里放好 task.json：
     task["inputs"][键]    选用的东西的路径（没选的可选项是 None）
     task["settings"][键]  设置的值（已经按 method.toml 的类型和范围核对过）
     task["out"]           产出放这里
     task["progress"]      进度文件
     task["result"]        结果文件
2. 跑的过程中，往进度文件追加一行 JSON：{"done": 完成数, "total": 总数, "note": "一句话"}。
   用文件而不用打印，是因为 Abaqus 之类的程序打印的东西不一定到得了日志。
3. 跑完，写结果文件：
     {"reports": {"answer": 42},                                   报的数，键对上 method.toml 里的 reports
      "outputs": [{"type": "结果", "name": "…", "path": "out/…"}], 产出，会被自动登记，来历指向这个实验
      "table": "out/….csv"}                                        可选：一张结果表，页面上显示
4. 退出码 0 并且写了结果文件，就算跑完；否则算失败。打印的东西都进 log.txt。
5. 页面上点“继续”，会在同一个目录里再跑一次这个脚本：要不要接着上次算，脚本自己看目录里有什么来定。
"""
import json
import os
import sys

run = sys.argv[1]
with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
    task = json.load(f)

with open(task["progress"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"done": 1, "total": 1, "note": "什么也没算"}, ensure_ascii=False) + "\n")

print("设置是：", task["settings"], flush=True)
with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"answer": 42}, "outputs": []}, f, ensure_ascii=False)
