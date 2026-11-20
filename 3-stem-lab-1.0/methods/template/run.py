"""空模板的计算：只演示做法和 stem-lab 之间的全部约定。

1. 启动时，stem-lab 已经在实验目录里放好 task.json：
     task["inputs"][键]    选用的东西的路径（没选的可选项是 None）
     task["settings"][键]  设置的值（已经按 method.toml 的类型和范围核对过）
     task["gates"]         这次写的门槛（画图时可以画出来；判定由 stem-lab 照封存的门槛算，不用做法管）
     task["out"]           产出放这里
     task["progress"]      进度文件
     task["result"]        结果文件
2. 跑的过程中，往进度文件追加一行 JSON：{"done": 完成数, "total": 总数, "note": "一句话"}。
   用文件而不用打印，是因为 Abaqus 之类的程序打印的东西不一定到得了日志。
3. 算完，调同一个文件夹里的 show.py 画图，拿回图的清单。
4. 写结果文件：
     {"reports": {"answer": 42},                                   报的数，键对上 method.toml 里的 reports
      "outputs": [{"type": "结果", "name": "…", "path": "out/…"}], 产出，会被自动登记，来历指向这个实验
      "table": "out/….csv",                                        可选：一张结果表，页面上显示
      "figures": [{"title": "…", "path": "out/….svg"}]}            可选：图（SVG、PNG、JPG），页面上摆在判定后面
   产出、表、图都要放在实验目录里，放在外面的不认。
5. 退出码 0 并且写了结果文件，就算跑完；否则算失败。打印的东西都进 log.txt。
6. 页面上点“继续”，会在同一个目录里再跑一次这个脚本；上一次的 result.json 已被改名留着，
   要不要接着上次算，脚本自己看目录里有什么来定。
"""
import json
import os
import sys

run = sys.argv[1]
with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
    task = json.load(f)
S = task["settings"]

with open(task["progress"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"done": 1, "total": 1, "note": "随便算了一点"}, ensure_ascii=False) + "\n")

# 算：这里只是把载荷乘上几个系数，写成一张表
os.makedirs(task["out"], exist_ok=True)
with open(os.path.join(task["out"], "table.csv"), "w", encoding="utf-8", newline="") as f:
    f.write("x,y\n" + "".join(f"{x},{S['load'] * x / 1000}\n" for x in range(6)))
print("设置是：", S, flush=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import show   # noqa: E402  结果展示在同一个文件夹的 show.py 里
figures = show.draw(run)

with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"answer": 42}, "outputs": [], "table": "out/table.csv", "figures": figures},
              f, ensure_ascii=False)
