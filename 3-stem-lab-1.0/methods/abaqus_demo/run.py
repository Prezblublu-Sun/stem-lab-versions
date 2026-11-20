"""Abaqus 检查的计算：照设置里的几个应变，各跑一次真的 Abaqus，读出应力，和理论值比。不是研究用的。

一个包三样：method.toml（说明）、run.py（计算，就是这个）、show.py（结果展示）；one_elem.inp 是算例模板。
先问一次版本（不占许可证）；再每个应变跑一个单元的拉伸算例（每次占几秒钟许可证），从 .dat 里读出 S33。
"""
import csv
import json
import os
import re
import subprocess
import sys

run = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(run, "task.json"), encoding="utf-8") as f:
    task = json.load(f)
S, out = task["settings"], task["out"]
os.makedirs(out, exist_ok=True)
E = 210000.0   # one_elem.inp 里写的弹性模量，MPa


def progress(done, total, note):
    with open(task["progress"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"done": done, "total": total, "note": note}, ensure_ascii=False) + "\n")


def abaqus(args, timeout):
    """起 Abaqus，等它结束，返回 (退出码, 它打印的全部内容)。.bat 要经 cmd /c 起。"""
    p = subprocess.run(["cmd", "/c", S["launcher"]] + args, cwd=out, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    text = p.stdout.decode("utf-8", errors="replace")
    print(f"---- abaqus {' '.join(args)} （退出码 {p.returncode}）\n{text}", flush=True)
    return p.returncode, text


try:
    strains = [float(x) for x in S["strains"].replace("，", ",").split(",") if x.strip()]
except ValueError:
    sys.exit(f"“拉伸应变”要写成用逗号隔开的几个数，现在是 {S['strains']!r}")
if not strains:
    sys.exit("“拉伸应变”至少写一个数")
if not os.path.isfile(S["launcher"]):
    sys.exit(f"找不到 Abaqus 启动器 {S['launcher']}：这台机器没装 Abaqus，或者设置里的路径不对。")

total = len(strains) + 1
progress(0, total, "问 Abaqus 的版本")
code, text = abaqus(["information=release"], 120)
if code != 0 or "Abaqus" not in text:
    sys.exit("Abaqus 的版本没问出来：启动器起不来，或者它没有回话。看上面的输出。")

with open(os.path.join(here, "one_elem.inp"), encoding="utf-8") as f:
    template = f.read()
rows = []
for i, strain in enumerate(strains, 1):
    job = f"strain{i}"
    progress(i, total, f"跑第 {i}/{len(strains)} 个应变 {strain:g}（会占几秒钟许可证）")
    with open(os.path.join(out, job + ".inp"), "w", encoding="utf-8", newline="\n") as f:
        f.write(template.replace("__DISPLACEMENT__", repr(strain)))
    abaqus([f"job={job}", f"input={job}.inp", "interactive", "ask_delete=OFF"], 900)
    sta = os.path.join(out, job + ".sta")
    if not (os.path.exists(sta) and "COMPLETED SUCCESSFULLY" in open(sta, encoding="utf-8", errors="replace").read()):
        sys.exit(f"应变 {strain:g} 那一次没有算完：{job}.sta 里没有 COMPLETED SUCCESSFULLY。看上面的输出和 out/{job}.msg。")
    with open(os.path.join(out, job + ".dat"), encoding="utf-8", errors="replace") as f:
        dat = f.read()
    # .dat 里 S33 的表：单元号、积分点、应力。取 8 个积分点的平均
    values = [float(m.group(1)) for m in re.finditer(r"^\s+1\s+[1-8]\s+([-+0-9.Ee]+)\s*$", dat, re.M)]
    if not values:
        sys.exit(f"应变 {strain:g} 那一次算完了，但没能从 {job}.dat 里读出 S33。")
    s33, theory = sum(values) / len(values), E * strain
    rows.append({"strain": strain, "s33_mpa": round(s33, 4), "theory_mpa": round(theory, 4),
                 "error_pct": round(abs(s33 - theory) / theory * 100, 5)})
    print(f"应变 {strain:g}：S33 = {s33:.4f} MPa，理论值 {theory:.4f} MPa", flush=True)

progress(total, total, "写结果，画图")
with open(os.path.join(out, "stress_strain.csv"), "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
sys.path.insert(0, here)
import show   # noqa: E402  结果展示在同一个文件夹的 show.py 里
figures = show.draw(run)
with open(task["result"], "w", encoding="utf-8") as f:
    json.dump({"reports": {"max_error": max(r["error_pct"] for r in rows),
                           "modulus": round(sum(r["s33_mpa"] / r["strain"] for r in rows) / len(rows), 2)},
               "outputs": [{"type": "结果", "name": "Abaqus 检查的应力应变", "path": "out/stress_strain.csv"}],
               "table": "out/stress_strain.csv", "figures": figures}, f, ensure_ascii=False, indent=2)
print("检查做完了", flush=True)
