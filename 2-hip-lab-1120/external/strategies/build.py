"""把选点的算法打成 stem-lab 的带代码的包（种类 strategy）。一种算法一个包，登记之后在“一次选点”里选用。

    python external/strategies/build.py <哪一种> <包放到哪个文件夹>

哪一种：
    spacefill             均匀铺点：不用模型。第一批点、补空白用
    bayes                 贝叶斯优化：拿已有的 FE 结果在策略内部拟合高斯过程。要填数据
    predicted-best        照登记的预测器的预测值选。要填预测器
    predicted-optimistic  照预测区间里有利的那一端选。要填预测器

打好之后登记：python -m stemlab.desk register strategy <名字> --path <包的文件夹> --note "..."
算法本身在 spacefill.py、bayes.py、predicted.py 里，开头写着它是怎么选的；它们的测试在 tests/ 下。

自检样本：前三种的样本小到手算得出来（见 SAMPLES 里各自的说明）；bayes 的是现跑出来的，
另外核一条手上有数的事：选出来的第一个点就是离真正的最低点最近的那个候选。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAR ="离已选的点和已经算过的点最远：最近的一个在 {} 处（各设计项缩放到 0 到 1 之后的距离）"
KINDS = {
    "spacefill": {"code": "spacefill.py", "needs": [], "title": "均匀铺点", "about": "不用模型，在能选的候选里挑一批彼此离得最远的"},
    "bayes": {"code": "bayes.py", "needs": ["data"], "title": "贝叶斯优化",
              "about": "拿已有的 FE 结果在策略内部拟合高斯过程，挑最可能比现在最好的还好的候选"},
    "predicted-best": {"code": "predicted.py", "needs": ["predictions"], "pick": "best", "title": "照预测值选",
                       "about": "用登记的预测器的预测值，先取预测的帕累托前沿"},
    "predicted-optimistic": {"code": "predicted.py", "needs": ["predictions"], "pick": "optimistic", "title": "照预测区间有利的一端选",
                             "about": "用登记的预测器，把可能很好但没把握的候选也放进来"},
}


def _columns(design, conditions, labels) -> list:
    return ([{"name": name, "unit": "1", "meaning": name, "role": "design"} for name in design]
            + [{"name": name, "unit": "N", "meaning": name, "role": "condition"} for name in conditions]
            + [{"name": name, "unit": "1", "meaning": name, "role": "label"} for name in labels])


def _data(folder: Path, rows: list, labels: list) -> None:
    """一份小数据：rows 是 [(a, [各标签的数])]，条件都是 load = 2000。"""
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"format": 1, "kind": "data", "files": ["rows.jsonl"], "count": len(rows),
                                                      "columns": _columns(["a"], ["load"], labels), "bone_id": "b"}), encoding="utf-8")
    lines = [json.dumps({"point": f"p{number}", "bone_id": "b", "round": 1, "fingerprint": f"f{number}", "outcome": "finished", "fields": {},
                         "values": {"a": a, "load": 2000.0, **dict(zip(labels, numbers))}}) for number, (a, numbers) in enumerate(rows)]
    (folder / "rows.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _job(values, objective: dict, count: int, **more) -> dict:
    candidates = [{"name": f"c{number}", "bone_id": "b", "design": {"a": a}, "feasible": fits, "info": {}}
                  for number, (a, fits) in enumerate(values, start=1)]
    return {"objective": objective, "candidates": candidates, "conditions": {"load": 2000.0}, "count": count, "seed": 7,
            "data": [], "predictions": None, **more}


def sample_spacefill(folder: Path) -> dict:
    """六个候选排在一条线上：a = 0、0.2、0.5、0.8、1.0 可行，2.0 不可行。约束是 a 不超过 0.9，a = 0 已经算过。

    能选的只剩 0.2、0.5、0.8，连同算过的 0 一起缩放：0.25、0.625、1、0。
    第一个挑离 0 最远的 0.8（距离 1）；第二个，0.2 离最近的已有点 0.25，0.5 离 0.375，挑 0.5。
    """
    _data(folder / "done", [(0.0, [1.0])], ["y"])
    objective = {"version": "v1", "objectives": [{"column": "y", "goal": "min"}],
                 "constraints": [{"id": "c1", "what": "a 不超过 0.9", "on": "design", "column": "a", "op": "<=", "limit": 0.9}]}
    job = _job([(0.0, True), (0.2, True), (0.5, True), (0.8, True), (1.0, True), (2.0, False)], objective, 2, data=["done"])
    (folder / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return {"chosen": [{"name": "c4", "score": 1.0, "why": FAR.format("1")}, {"name": "c3", "score": 0.375, "why": FAR.format("0.375")}],
            "model": None}


def _guesses() -> list:
    """四个候选，预测器给了前三个的预测：值是 3、1、2，区间下限是 0.5、0.8、1.9。第四个不在它的适用范围里，没有预测。"""
    return [{"name": "c1", "values": {"y": 3.0}, "lower": {"y": 0.5}, "upper": {"y": 5.5}},
            {"name": "c2", "values": {"y": 1.0}, "lower": {"y": 0.8}, "upper": {"y": 1.2}},
            {"name": "c3", "values": {"y": 2.0}, "lower": {"y": 1.9}, "upper": {"y": 2.1}}]


def _predicted_job(folder: Path) -> None:
    objective = {"version": "v1", "objectives": [{"column": "y", "goal": "min"}], "constraints": []}
    job = _job([(0.0, True), (0.3, True), (0.6, True), (0.9, True)], objective, 2, predictions=_guesses())
    (folder / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def sample_predicted_best(folder: Path) -> dict:
    """照预测值从小到大：c2（1）、c3（2）。分数是负的“缩放到 0 到 1 的值”：0 和 −0.5。"""
    _predicted_job(folder)
    return {"chosen": [{"name": "c2", "score": 0.0, "why": "y 预测 1（区间 0.8 到 1.2）；照这一个目标排"},
                       {"name": "c3", "score": -0.5, "why": "y 预测 2（区间 1.9 到 2.1）；照这一个目标排"}],
            "model": "登记的预测器，拿预测值比"}


def sample_predicted_optimistic(folder: Path) -> dict:
    """照区间下限从小到大：c1（0.5）、c2（0.8）。c1 的预测值最差，但预测器对它最没把握，下限最低。
    分数：下限缩放到 0 到 1 是 0 和 0.3 / 1.4。"""
    _predicted_job(folder)
    return {"chosen": [{"name": "c1", "score": 0.0, "why": "y 预测 3（区间 0.5 到 5.5）；照这一个目标排"},
                       {"name": "c2", "score": -0.3 / 1.4, "why": "y 预测 1（区间 0.8 到 1.2）；照这一个目标排"}],
            "model": "登记的预测器，拿预测区间里有利的那一端比"}


def sample_bayes(folder: Path) -> dict:
    """y = (a − 0.6)² + 0.1。算过八个点；候选是 0 到 1 每隔 0.05 一个。真正的最低点在 a = 0.6，它是候选之一、没算过。

    expected 是打包时现跑出来的（见 main）；这里只备好输入。
    """
    seen = [0.0, 0.12, 0.27, 0.41, 0.52, 0.7, 0.85, 1.0]
    _data(folder / "seen", [(a, [(a - 0.6) ** 2 + 0.1]) for a in seen], ["y"])
    objective = {"version": "v1", "objectives": [{"column": "y", "goal": "min"}], "constraints": []}
    job = _job([(round(0.05 * step, 2), True) for step in range(21)], objective, 2, data=["seen"])
    (folder / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return {}


SAMPLES = {"spacefill": ("line", sample_spacefill), "bayes": ("valley", sample_bayes),
           "predicted-best": ("three_guesses", sample_predicted_best), "predicted-optimistic": ("three_guesses", sample_predicted_optimistic)}


def build(which: str, package: Path) -> Path:
    how = dict(KINDS[which])
    if package.exists():
        shutil.rmtree(package)
    (package / "code").mkdir(parents=True)
    shutil.copyfile(HERE / how.pop("code"), package / "code" / "main.py")
    shutil.copyfile(HERE / "common.py", package / "code" / "common.py")
    name, make = SAMPLES[which]
    test = package / "data" / "selftest" / name
    (test / "input").mkdir(parents=True)
    expected = make(test / "input")
    entry = ["{python}", "code/main.py"]
    listed = {"format": 1, "kind": "strategy", "entry": entry, "requires": ["python>=3.12", "numpy>=2", "scipy>=1.11"],
              "tolerance": {"rel": 1e-6, "abs": 1e-9},
              "selftest": [{"name": name, "input": f"data/selftest/{name}/input", "expected": f"data/selftest/{name}/expected.json"}], **how}

    def write_manifest() -> None:
        files = sorted((path.relative_to(package).as_posix() for path in package.rglob("*")
                        if path.is_file() and path != package / "manifest.json"), key=lambda rel: rel.encode("utf-8"))
        text = json.dumps(dict(listed, files=files), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        (package / "manifest.json").write_bytes(text.encode("utf-8") + b"\n")

    (test / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
    write_manifest()                                    # 策略跑的时候要读自己的清单（predicted 的 pick）
    if which == "bayes":
        out = package.parent / f"{package.name}-selftest-out"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        done = subprocess.run([sys.executable, "code/main.py", str(test / "input"), str(out)], cwd=package, capture_output=True,
                              env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
        if done.returncode != 0:
            raise SystemExit("bayes 的自检样本跑不出来：" + (done.stdout + done.stderr).decode("utf-8", "replace")[-800:])
        expected = json.loads((out / "result.json").read_text(encoding="utf-8"))
        shutil.rmtree(out)
        if expected["chosen"][0]["name"] != "c13":      # 第 13 个候选是 a = 0.6
            raise SystemExit(f"bayes 的自检样本选出来的第一个点不是最低点上的那个候选：{expected['chosen']}")
        for junk in list(package.rglob("__pycache__")):
            shutil.rmtree(junk)
        (test / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        write_manifest()
    return package


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in KINDS:
        print(__doc__)
        return 2
    package = build(sys.argv[1], Path(sys.argv[2]))
    count = sum(1 for path in package.rglob("*") if path.is_file())
    print(f"打好了：{package}（{KINDS[sys.argv[1]]['title']}，{count} 个文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
