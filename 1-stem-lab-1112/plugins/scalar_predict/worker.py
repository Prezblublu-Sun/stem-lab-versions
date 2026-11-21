"""用标量预测器对一批点出预测。在后台进程里跑：python worker.py <job.json>

预测器是一个 zip 文件（格式「标量预测器 v0」）：manifest.json、model.joblib、hashes.json。
先核对哈希，对不上就不出数。一批点两种都读：JSON（每个点有名字、骨、设计、条件），
或平的 CSV 表（列名和标签表一样）。

这个文件不 import stemlab，也不 import 训练插件。它只认预测器文件的格式。
注意：model.joblib 是 pickle，读它等于运行里面的代码。只给它你信得过的预测器文件。
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"

import csv
import hashlib
import io
import json
import math
import sys
import time
import traceback
import zipfile
from pathlib import Path

PREDICTOR_FORMAT = "标量预测器 v0"
POINTS_FORMAT = "一批点 v0"
OUTPUT_FORMAT = "一份预测 v0"
JSON_NAME = "预测.json"
CSV_NAME = "预测表.csv"
Z90 = 1.645
MEMBERS = ("manifest.json", "model.joblib", "hashes.json")


class Refused(Exception):
    """这一次不出数。消息是给人看的。"""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(x):
    x = float(x)
    return x if math.isfinite(x) else None


def dump_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    for _ in range(200):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def number(x):
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- 预测器


def open_predictor(data: bytes) -> tuple[dict, dict]:
    """核对预测器文件，读出说明和模型。被改过、坏了、不是这种格式，都抛 Refused。"""
    changed = "预测器文件被改过或坏了，不出预测"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sorted(z.namelist()) != sorted(MEMBERS):
                raise Refused(f"{changed}：里面应该正好是 {'、'.join(MEMBERS)}，实际是 {'、'.join(z.namelist())}")
            files = {name: z.read(name) for name in MEMBERS}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as err:
        raise Refused(f"{changed}：读不出来（{type(err).__name__}: {err}）。它应该是「{PREDICTOR_FORMAT}」的 zip 文件")
    try:
        hashes = json.loads(files["hashes.json"])
    except ValueError:
        raise Refused(f"{changed}：hashes.json 读不出来")
    for name in ("manifest.json", "model.joblib"):
        if not isinstance(hashes, dict) or hashes.get(name) != sha256_bytes(files[name]):
            raise Refused(f"{changed}：{name} 的哈希和文件里记的对不上")
    manifest = json.loads(files["manifest.json"])
    if manifest.get("格式") != PREDICTOR_FORMAT:
        raise Refused(f"预测器的格式是「{manifest.get('格式')}」，这个插件只认「{PREDICTOR_FORMAT}」")
    import joblib

    models = joblib.load(io.BytesIO(files["model.joblib"]))
    missing = [t["列"] for t in manifest["目标"] if t["列"] not in models]
    if missing:
        raise Refused(f"预测器的说明里有这些目标，模型里没有：{'、'.join(missing)}")
    return manifest, models


def predict(est, kind: str, Z):
    """预测值和标准差，都在模型的尺度上。和训练插件算误差时用的是同样的算法。"""
    import numpy as np

    if kind == "高斯过程":
        mu, sd = est.predict(Z, return_std=True)
    elif kind == "随机森林":
        each = np.stack([tree.predict(Z) for tree in est.estimators_])
        mu, sd = each.mean(0), each.std(0)
    else:
        raise Refused(f"预测器的模型种类是「{kind}」，这个插件不会用")
    return np.asarray(mu, float), np.asarray(sd, float)


# ---------------------------------------------------------------- 一批点


def read_points(data: bytes, manifest: dict) -> tuple[str, list[dict]]:
    """读一批点，两种都收。返回读成了哪种，以及每个点：名字、骨、设计、条件、理由。"""
    text = data.decode("utf-8-sig")
    inp = manifest["输入"]
    if text.lstrip()[:1] in ("{", "["):
        try:
            doc = json.loads(text)
        except ValueError as err:
            raise Refused(f"一批点看起来是 JSON，但读不出来：{err}")
        items = doc.get("点") if isinstance(doc, dict) else doc
        if not isinstance(items, list):
            raise Refused("JSON 的一批点里要有「点」：一个列表，一个点一项。")
        points = []
        for i, p in enumerate(items, start=1):
            if not isinstance(p, dict):
                raise Refused(f"第 {i} 个点不是一个对象。")
            points.append({
                **p,
                "名字": str(p.get("名字") or f"第{i}个点"),
                "骨": p.get("骨"),
                "设计": p.get("设计") if isinstance(p.get("设计"), dict) else {},
                "条件": p.get("条件") if isinstance(p.get("条件"), dict) else {},
            })
        kind = "JSON"
    else:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        cols = list(reader.fieldnames or [])
        name_col = next((c for c in ("name", "名字", inp.get("标签表里行的名字")) if c in cols), None)
        reason_col = next((c for c in ("reason", "理由") if c in cols), None)
        points = []
        for i, row in enumerate(reader, start=1):
            p = {
                "名字": (row[name_col] if name_col else "") or f"第{i}行",
                "骨": row.get(inp["骨"]) or None,
                "设计": {c: row[c] for c in inp["设计"] if c in cols and row[c] != ""},
                "条件": {c: row[c] for c in inp["条件"] if c in cols and row[c] != ""},
            }
            if reason_col and row[reason_col]:
                p["理由"] = row[reason_col]
            points.append(p)
        kind = "CSV"
    if not points:
        raise Refused("这一批点是空的。")
    names = [p["名字"] for p in points]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise Refused(f"这一批点里有重复的名字：{'、'.join(twice[:10])}")
    return kind, points


def check_point(p: dict, manifest: dict) -> tuple[list | None, dict, list, str | None]:
    """一个点能不能出数。返回（数值输入，没写而按训练时的值算的输入，超出训练范围的输入，问题）。"""
    inp = manifest["输入"]
    values, assumed, outside, missing, unlearned = [], {}, [], [], []
    if p["骨"] is None or p["骨"] == "":
        # 骨和别的输入一样对待：训练时只有一种骨，没写就按那一种算并写明；有几种骨时必须写
        if len(inp["见过的骨"]) != 1:
            return None, {}, [], f"没写骨。预测器见过 {len(inp['见过的骨'])} 种骨，要写明是哪一种：{'、'.join(inp['见过的骨'])}"
        assumed["骨"] = inp["见过的骨"][0]
    elif str(p["骨"]) not in inp["见过的骨"]:
        return None, {}, [], f"骨「{p['骨']}」预测器没见过。它见过的是：{'、'.join(inp['见过的骨'])}"
    constant = inp["训练时不变的输入"]
    ranges = {c["列"]: c["训练范围"] for c in inp["数值列"]}
    for col in inp["数值列的顺序"]:
        where = "设计" if col in inp["设计"] else "条件"
        raw = p[where].get(col)
        v = number(raw)
        if col in constant:
            if raw is None or raw == "":
                assumed[col] = constant[col]
                v = constant[col]
            elif v is None:
                missing.append(col)
            elif abs(v - constant[col]) > 1e-9 * max(1.0, abs(constant[col])):
                unlearned.append(f"{col}（训练时一直是 {constant[col]:g}，这个点是 {v:g}）")
        elif v is None:
            missing.append(col)
        elif not ranges[col][0] <= v <= ranges[col][1]:
            outside.append(col)
        values.append(v)
    if missing:
        return None, {}, [], f"缺输入或不是数：{'、'.join(missing)}"
    if unlearned:
        return None, {}, [], f"预测器没学过这个输入的变化：{'；'.join(unlearned)}"
    return values, assumed, outside, None


# ---------------------------------------------------------------- 一次预测


def run(job: dict, stage=lambda text: None) -> dict:
    import numpy as np

    out_dir = Path(job["out_dir"])
    if out_dir.exists():
        raise Refused(f"产出文件夹已经在了，不往里写：{out_dir}")

    stage("核对预测器")
    pred_path = Path(job["predictor"]["path"])
    pred_bytes = pred_path.read_bytes()
    pred_sha = sha256_bytes(pred_bytes)
    expected = job["predictor"].get("expected_sha256")
    if expected and expected != pred_sha:
        raise Refused(f"预测器文件在启动之后被改过，哈希对不上，不出预测：{pred_path}")
    manifest, models = open_predictor(pred_bytes)
    notes = []
    import sklearn

    trained_with = manifest.get("环境", {}).get("scikit-learn")
    if trained_with and trained_with != sklearn.__version__:
        notes.append(f"预测器是用 scikit-learn {trained_with} 训练的，现在装的是 {sklearn.__version__}。数照出，可能有差别")

    stage("读一批点")
    pts_path = Path(job["points"]["path"])
    pts_bytes = pts_path.read_bytes()
    pts_sha = sha256_bytes(pts_bytes)
    expected = job["points"].get("expected_sha256")
    if expected and expected != pts_sha:
        raise Refused(f"一批点在启动之后被改过，哈希对不上：{pts_path}")
    read_as, points = read_points(pts_bytes, manifest)

    stage("出预测")
    inp, kind, targets = manifest["输入"], manifest["模型种类"], manifest["目标"]
    checked = [check_point(p, manifest) for p in points]
    good = [i for i, c in enumerate(checked) if c[3] is None]
    numbers: dict[int, dict] = {}
    if good:
        order = inp["数值列的顺序"]
        varying = [order.index(c["列"]) for c in inp["数值列"]]
        mean = np.array([c["均值"] for c in inp["数值列"]], float)
        sd = np.array([c["标准差"] for c in inp["数值列"]], float)
        X = np.array([checked[i][0] for i in good], float).reshape(len(good), len(order))
        Z = (X[:, varying] - mean) / sd
        if inp["骨进不进模型"]:
            onehot = np.array([[1.0 if str(points[i]["骨"]) == level else 0.0 for level in inp["见过的骨"]] for i in good])
            Z = np.hstack([Z, onehot])
        for t in targets:
            mu, s = predict(models[t["列"]], kind, Z)
            lo, hi = mu - Z90 * s, mu + Z90 * s
            if t["变换"] == "log10":
                value, lo, hi = 10.0 ** mu, 10.0 ** lo, 10.0 ** hi
            else:
                value = mu
            for pos, i in enumerate(good):
                numbers.setdefault(i, {})[t["列"]] = {
                    "预测值": clean(value[pos]), "标准差": clean(s[pos]), "区间90": [clean(lo[pos]), clean(hi[pos])],
                }

    out_points, reasons = [], {}
    for i, p in enumerate(points):
        _, assumed, outside, problem = checked[i]
        out_points.append({
            **p,
            "预测": numbers.get(i),
            "超出训练范围的输入": outside,
            "没写、按训练时的值算的输入": assumed,
            "问题": problem,
        })
        if problem:
            reasons.setdefault(problem, []).append(p["名字"])

    doc = {
        "格式": OUTPUT_FORMAT,
        "预测器": {
            "位置": str(pred_path), "sha256": pred_sha, "格式": manifest["格式"], "出自": manifest.get("出自", {}),
            "模型种类": kind, "不确定度": manifest.get("不确定度"), "训练": manifest.get("训练", {}),
        },
        "一批点": {
            "位置": str(pts_path), "sha256": pts_sha, "读成": read_as,
            "点数": len(points), "出了数的": len(good), "没出数的": len(points) - len(good),
        },
        "目标": [{"列": t["列"], "变换": t["变换"]} for t in targets],
        "数怎么读": (
            f"预测值和区间90 在原始尺度上。标准差在模型尺度上（目标的变换是 log10 时，就是 log10 之后的标准差）。"
            f"区间90 = 模型尺度上的 预测 ± {Z90} × 标准差，再变回原始尺度。"
            "「预测」是 null 的点没出数，原因在「问题」里。"
        ),
        "提醒": notes,
        "点": out_points,
    }

    stage("写产出")
    out_dir.mkdir(parents=True)
    (out_dir / JSON_NAME).write_bytes(dump_json(doc))
    table = io.StringIO(newline="")
    w = csv.writer(table, lineterminator="\n")
    head = ["名字", "骨", *inp["数值列的顺序"]]
    for t in targets:
        head += [t["列"], f"{t['列']}__sd", f"{t['列']}__lo90", f"{t['列']}__hi90"]
    w.writerow(head + ["超出训练范围的输入", "问题"])
    for i, p in enumerate(points):
        row = [p["名字"], p["骨"] if p["骨"] not in (None, "") else checked[i][1].get("骨", "")]
        for col in inp["数值列的顺序"]:
            v = p["设计" if col in inp["设计"] else "条件"].get(col, checked[i][1].get(col, ""))
            row.append("" if v is None else v)
        for t in targets:
            n = (numbers.get(i) or {}).get(t["列"])
            row += [n["预测值"], n["标准差"], *n["区间90"]] if n else ["", "", "", ""]
        w.writerow(row + [";".join(checked[i][2]), checked[i][3] or ""])
    (out_dir / CSV_NAME).write_bytes(("﻿" + table.getvalue()).encode("utf-8"))

    problems = []
    for reason, names in reasons.items():
        shown = "、".join(names[:20]) + (f" 等 {len(names)} 个" if len(names) > 20 else "")
        problems.append({"error": f"{len(names)} 个点没出数：{reason}。点：{shown}", "raw": "\n".join(names)})
    problems += [{"error": note, "raw": ""} for note in notes]
    return {
        "json": str(out_dir / JSON_NAME),
        "csv": str(out_dir / CSV_NAME),
        "n_points": len(points),
        "n_good": len(good),
        "model_kind": kind,
        "targets": [t["列"] for t in targets],
        "uncertainty": manifest.get("不确定度"),
        "problems": problems,
        "provenance": {
            "预测器_sha256": pred_sha,
            "预测器的训练数据_sha256": manifest.get("训练", {}).get("数据 sha256"),
            "预测器的误差叫什么": manifest.get("训练", {}).get("误差叫什么"),
            "一批点_sha256": pts_sha, "一批点读成": read_as, "点数": len(points), "出了数的点": len(good),
            "scikit-learn": sklearn.__version__, "worker_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
    }


def main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    status_path = Path(job["attempt_dir"]) / "status.json"

    def put(**items):
        write_atomic(status_path, dump_json({"pid": os.getpid(), **items}))

    try:
        result = run(job, stage=lambda text: put(state="运行", stage=text))
        put(state="完成", stage="", result=result)
        return 0
    except Refused as err:
        put(state="失败", stage="", error=str(err), raw=traceback.format_exc())
    except Exception as err:  # 出问题是正常的：写下来，由插件记成问题
        put(state="失败", stage="", error=f"{type(err).__name__}: {err}", raw=traceback.format_exc())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
