"""标量预测器的训练。在后台进程里跑：python worker.py <job.json>

读一份标签表（平的 CSV，一行一个 FE 作业），按设置挑行、挑列、划分，训练，
写出两样：预测器（一个文件）和误差报告。走到哪一步写在 status.json 里，插件的 poll 来读。

这个文件不 import stemlab，也不认识别的插件。
同设置同种子重跑，误差报告的每个字节相同：报告里没有时间、没有实验编号。
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"  # 只用一个线程，重跑才逐数相同

import csv
import hashlib
import io
import json
import math
import platform
import sys
import time
import traceback
import zipfile
from pathlib import Path

REPORT_FORMAT = "标量预测器误差报告 v0"
PREDICTOR_FORMAT = "标量预测器 v0"
REPORT_NAME = "误差报告.json"
PREDICTOR_NAME = "预测器.zip"

METRICS = ("R2", "RMSE", "MAE", "相对误差", "秩相关")
MODEL_DEFAULTS = {
    "高斯过程": {"核": "Matern52", "重启次数": 3, "长度尺度范围": [0.2, 200.0], "噪声范围": [2.5e-4, 0.1]},
    "随机森林": {"树的棵数": 300, "叶子最少行数": 1, "每次分裂看的输入比例": 1.0},
}
UNCERTAINTY = {"高斯过程": "模型自带的方差", "随机森林": "集成：各棵树的预测之间的离散"}
KERNELS = {"Matern52": 2.5, "Matern32": 1.5, "RBF": None}
Z90 = 1.645  # 90% 区间 = 预测 ± 1.645 × 标准差（模型尺度上）


class SettingError(Exception):
    """设置写得不对。消息是给人看的。"""


# ---------------------------------------------------------------- 小工具


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean(x):
    """写进 JSON 的数：nan 和无穷写成 null。"""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def dump_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    for _ in range(200):  # Windows 上别处正在读的时候换不掉，等它读完
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.01)
    os.replace(tmp, path)


def as_list(x) -> list:
    return list(x) if isinstance(x, (list, tuple)) else [x]


def number(text):
    """标签表里的一格读成数。空的、nan、读不出来的都算缺。"""
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- 设置


def resolve(job: dict) -> dict:
    """把四项设置检查一遍，补上默认值。返回实际用的那一份（原样写进误差报告）。"""
    read = job.get("read")
    if not isinstance(read, dict):
        raise SettingError("「数据怎么读」要是一个对象，写明行的名字、骨、设计、条件各是哪几列。")
    unknown = set(read) - {"行的名字", "行的筛选", "最多用几行", "骨", "设计", "条件"}
    if unknown:
        raise SettingError(f"「数据怎么读」里有不认识的键：{'、'.join(sorted(unknown))}")
    for key in ("行的名字", "骨", "设计"):
        if not read.get(key):
            raise SettingError(f"「数据怎么读」里缺「{key}」。")
    limit = read.get("最多用几行")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise SettingError("「数据怎么读」里的「最多用几行」要是正整数，或不写。")
    row_filter = read.get("行的筛选") or {}
    if not isinstance(row_filter, dict):
        raise SettingError("「数据怎么读」里的「行的筛选」要是 {列名: 值 或 值的列表}。")
    r = {
        "行的名字": str(read["行的名字"]),
        "行的筛选": {str(k): [str(v) for v in as_list(vs)] for k, vs in row_filter.items()},
        "最多用几行": limit,
        "骨": str(read["骨"]),
        "设计": [str(c) for c in as_list(read["设计"])],
        "条件": [str(c) for c in as_list(read.get("条件") or [])],
    }
    inputs = [r["骨"]] + r["设计"] + r["条件"]
    if len(set(inputs)) != len(inputs):
        raise SettingError("骨、设计、条件里有重复的列。")

    targets = []
    for t in as_list(job.get("targets") or []):
        if isinstance(t, str):
            t = {"列": t}
        if not isinstance(t, dict) or not t.get("列"):
            raise SettingError("「预测目标」的每一项要是列名，或 {\"列\": 列名, \"变换\": \"log10\"}。")
        tf = t.get("变换") or "不变换"
        if tf not in ("不变换", "log10"):
            raise SettingError(f"目标「{t['列']}」的变换只能是 log10 或不写，收到的是：{tf}")
        targets.append({"列": str(t["列"]), "变换": tf})
    if not targets:
        raise SettingError("「预测目标」是空的。")
    names = [t["列"] for t in targets]
    if len(set(names)) != len(names):
        raise SettingError("「预测目标」里有重复的列。")
    both = set(names) & set(inputs)
    if both:
        raise SettingError(f"这些列既是输入又是目标：{'、'.join(sorted(both))}")

    model = job.get("model")
    if not isinstance(model, dict) or model.get("模型种类") not in MODEL_DEFAULTS:
        raise SettingError(f"「模型和训练配置」里的「模型种类」要是：{'、'.join(MODEL_DEFAULTS)}")
    kind = model["模型种类"]
    unknown = set(model) - set(MODEL_DEFAULTS[kind]) - {"模型种类", "误差指标"}
    if unknown:
        raise SettingError(f"「{kind}」没有这些配置：{'、'.join(sorted(unknown))}。它有的是：{'、'.join(MODEL_DEFAULTS[kind])}")
    m = {"模型种类": kind, **MODEL_DEFAULTS[kind], **{k: v for k, v in model.items() if k in MODEL_DEFAULTS[kind]}}
    if kind == "高斯过程" and m["核"] not in KERNELS:
        raise SettingError(f"核只能是：{'、'.join(KERNELS)}")
    wanted = as_list(model.get("误差指标") or list(METRICS))
    bad = [w for w in wanted if w not in METRICS]
    if bad:
        raise SettingError(f"不认识的误差指标：{'、'.join(map(str, bad))}。有的是：{'、'.join(METRICS)}")
    m["误差指标"] = [w for w in METRICS if w in wanted]
    m["输入的归一化"] = "每一列减训练行的均值、除以训练行的标准差"
    m["不确定度"] = UNCERTAINTY[kind]

    split = job.get("split")
    if not isinstance(split, dict) or not split.get("种类"):
        raise SettingError("「划分」要是一个对象，里面有「种类」：留出、k 折、按列。")
    kind_s = str(split["种类"]).replace(" ", "").lower()
    if kind_s == "留出":
        frac = split.get("留出比例", 0.2)
        if not isinstance(frac, (int, float)) or not 0 < frac < 1:
            raise SettingError("「留出比例」要在 0 和 1 之间。")
        s = {"种类": "留出", "留出比例": float(frac), "分组列": split.get("分组列") or None}
        allowed = {"种类", "留出比例", "分组列"}
    elif kind_s == "k折":
        k = split.get("折数", 5)
        if not isinstance(k, int) or isinstance(k, bool) or k < 2:
            raise SettingError("「折数」要是不小于 2 的整数。")
        s = {"种类": "k 折", "折数": k, "分组列": split.get("分组列") or None}
        allowed = {"种类", "折数", "分组列"}
    elif kind_s == "按列":
        if not split.get("列") or not split.get("留出的值"):
            raise SettingError("按列划分要写「列」和「留出的值」。")
        s = {"种类": "按列", "列": str(split["列"]), "留出的值": [str(v) for v in as_list(split["留出的值"])]}
        allowed = {"种类", "列", "留出的值"}
    else:
        raise SettingError(f"划分的种类只能是留出、k 折、按列，收到的是：{split['种类']}")
    unknown = set(split) - allowed
    if unknown:
        raise SettingError(f"「{s['种类']}」划分没有这些键：{'、'.join(sorted(unknown))}")

    seed = job.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise SettingError("「随机种子」要是不小于 0 的整数。")
    return {"read": r, "targets": targets, "model": m, "split": s, "seed": seed}


# ---------------------------------------------------------------- 读数据


def read_table(data: bytes) -> tuple[list[str], list[dict]]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    rows = list(reader)
    return list(reader.fieldnames or []), rows


def pick_rows(cols: list[str], rows: list[dict], cfg: dict) -> dict:
    """按设置挑行，读成数。缺输入或缺目标的行去掉，并记下是哪些行、缺什么。"""
    r, targets, split = cfg["read"], cfg["targets"], cfg["split"]
    need = [r["行的名字"], r["骨"], *r["设计"], *r["条件"], *[t["列"] for t in targets], *r["行的筛选"]]
    need += [c for c in (split.get("分组列"), split.get("列")) if c]
    missing = [c for c in dict.fromkeys(need) if c not in cols]
    if missing:
        raise SettingError(f"标签表里没有这些列：{'、'.join(missing)}")

    kept = [row for row in rows if all(row[c] in vs for c, vs in r["行的筛选"].items())]
    n_filtered = len(kept)
    if r["最多用几行"] is not None:
        kept = kept[: r["最多用几行"]]

    numeric = r["设计"] + r["条件"]
    ids, bones, X, Y, groups, by_col, dropped = [], [], [], [], [], [], []
    for row in kept:
        rid = row[r["行的名字"]]
        why = []
        if not row[r["骨"]]:
            why.append(r["骨"])
        xs = [number(row[c]) for c in numeric]
        why += [c for c, v in zip(numeric, xs) if v is None]
        ys = []
        for t in targets:
            v = number(row[t["列"]])
            if v is not None and t["变换"] == "log10":
                v = math.log10(v) if v > 0 else None
            if v is None:
                why.append(t["列"])
            ys.append(v)
        if why:
            dropped.append({"行": rid, "缺": why})
            continue
        ids.append(rid)
        bones.append(row[r["骨"]])
        X.append(xs)
        Y.append(ys)
        g = row[split["分组列"]] if split.get("分组列") else ""
        groups.append(g or f"（单独一行）{rid}")
        by_col.append(row[split["列"]] if split.get("列") else "")
    if len(set(ids)) != len(ids):
        raise SettingError(f"「{r['行的名字']}」这一列在用到的行里有重复，不能当行的名字。")
    return {
        "ids": ids, "bones": bones, "X": X, "Y": Y, "groups": groups, "by_col": by_col,
        "dropped": dropped, "n_total": len(rows), "n_filtered": n_filtered, "n_limited": len(kept),
    }


# ---------------------------------------------------------------- 划分


def make_split(d: dict, split: dict, seed: int) -> list[tuple[list[int], list[int]]]:
    """返回每一折的（训练行，留出行），都是行的下标。留出和按列只有一折。

    有分组列时整组一起走：同一组的行不会一边在训练、一边在留出。
    """
    import numpy as np

    n = len(d["ids"])
    everyone = list(range(n))
    if split["种类"] == "按列":
        test = [i for i in everyone if d["by_col"][i] in split["留出的值"]]
        folds = [([i for i in everyone if d["by_col"][i] not in split["留出的值"]], test)]
    else:
        units = sorted(set(d["groups"])) if split.get("分组列") else [str(i) for i in everyone]
        unit_of = d["groups"] if split.get("分组列") else [str(i) for i in everyone]
        order = [units[i] for i in np.random.default_rng([seed, 20261112]).permutation(len(units))]
        if split["种类"] == "留出":
            n_out = max(1, int(round(split["留出比例"] * len(order))))
            parts = [set(order[:n_out])]
        else:
            if split["折数"] > len(order):
                raise SettingError(f"折数（{split['折数']}）比能分的份数（{len(order)}）还多。")
            parts = [set(order[k :: split["折数"]]) for k in range(split["折数"])]
        folds = [
            ([i for i in everyone if unit_of[i] not in part], [i for i in everyone if unit_of[i] in part])
            for part in parts
        ]
    for train, test in folds:
        if len(train) < 5 or not test:
            raise SettingError(f"划分之后训练行 {len(train)} 行、留出行 {len(test)} 行。训练至少要 5 行，留出至少 1 行。")
        assert not set(train) & set(test)
    return folds


# ---------------------------------------------------------------- 模型


class Encoder:
    """把（骨，数值输入）变成模型吃的矩阵。均值、标准差、见过的骨都只从训练行来。"""

    def __init__(self, columns: list[str], X, bones: list[str]):
        import numpy as np

        X = np.asarray(X, float)
        self.columns = columns
        self.lo, self.hi = X.min(0), X.max(0)
        self.varying = [j for j in range(len(columns)) if self.hi[j] > self.lo[j]]
        self.constant = {columns[j]: float(self.lo[j]) for j in range(len(columns)) if j not in self.varying}
        self.mean = X[:, self.varying].mean(0)
        self.sd = X[:, self.varying].std(0)
        self.bones = sorted(set(bones))

    def matrix(self, X, bones: list[str]):
        import numpy as np

        X = np.asarray(X, float)
        Z = (X[:, self.varying] - self.mean) / self.sd
        if len(self.bones) > 1:  # 只有一种骨时，骨这一列不变，不进模型
            onehot = np.array([[1.0 if b == level else 0.0 for level in self.bones] for b in bones])
            Z = np.hstack([Z, onehot])
        return Z

    def describe(self) -> dict:
        return {
            "数值列": [
                {"列": self.columns[j], "均值": float(self.mean[k]), "标准差": float(self.sd[k]),
                 "训练范围": [float(self.lo[j]), float(self.hi[j])]}
                for k, j in enumerate(self.varying)
            ],
            "训练时不变的输入": self.constant,
            "见过的骨": self.bones,
            "骨进不进模型": len(self.bones) > 1,
        }


def fit(Z, y, model: dict, seed: int):
    import numpy as np

    if Z.shape[1] == 0:
        raise SettingError("训练行里所有输入都不变，没有可以学的东西。")
    if model["模型种类"] == "高斯过程":
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel

        ls, nz = tuple(model["长度尺度范围"]), tuple(model["噪声范围"])
        ls0, nz0 = float(np.clip(2.0, *ls)), float(np.clip(1e-3, *nz))
        ones = np.ones(Z.shape[1]) * ls0
        nu = KERNELS[model["核"]]
        shape = RBF(ones, ls) if nu is None else Matern(ones, ls, nu=nu)
        kernel = ConstantKernel(1.0, (1e-2, 1e2)) * shape + WhiteKernel(nz0, nz)
        est = GaussianProcessRegressor(kernel, normalize_y=True, n_restarts_optimizer=int(model["重启次数"]), random_state=seed)
    else:
        from sklearn.ensemble import RandomForestRegressor

        est = RandomForestRegressor(
            n_estimators=int(model["树的棵数"]), min_samples_leaf=int(model["叶子最少行数"]),
            max_features=float(model["每次分裂看的输入比例"]), random_state=seed, n_jobs=1,
        )
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return est.fit(Z, np.asarray(y, float))


def predict(est, kind: str, Z):
    """预测值和标准差，都在模型的尺度上。出预测插件里有一份同样的算法。"""
    import numpy as np

    if kind == "高斯过程":
        mu, sd = est.predict(Z, return_std=True)
    else:
        each = np.stack([tree.predict(Z) for tree in est.estimators_])
        mu, sd = each.mean(0), each.std(0)
    return np.asarray(mu, float), np.asarray(sd, float)


# ---------------------------------------------------------------- 误差

METRIC_DEFS = {
    "n": "算这组数用了多少行",
    "R2": "1 − Σ(预测−真值)² / Σ(真值−真值的均值)²，在模型尺度上算",
    "RMSE": "√(均值((预测−真值)²))。模型尺度和原始尺度各算一个",
    "MAE": "均值(|预测−真值|)。模型尺度和原始尺度各算一个",
    "相对误差": "|预测−真值| / |真值|，在原始尺度上算，给均值和中位数。真值为 0 的行不算",
    "秩相关": "Spearman 秩相关",
    "90% 区间覆盖率": f"真值落在 预测 ± {Z90} × 标准差（模型尺度）里的行占多少。总是给，不用点",
    "模型尺度": "目标做了变换（log10）时，模型学的是变换后的数；没变换时模型尺度就是原始尺度",
}


def measure(y, mu, sd, transform: str, which: list[str]) -> dict:
    import numpy as np
    from scipy.stats import spearmanr

    y, mu, sd = np.asarray(y, float), np.asarray(mu, float), np.asarray(sd, float)
    e = mu - y
    yo, po = (10.0 ** y, 10.0 ** mu) if transform == "log10" else (y, mu)
    eo = po - yo
    out: dict = {"n": int(len(y))}
    on_model, on_orig = {}, {}
    if "R2" in which:
        tot = float(((y - y.mean()) ** 2).sum())
        on_model["R2"] = clean(1 - float((e ** 2).sum()) / tot) if len(y) > 1 and tot > 0 else None
    if "RMSE" in which:
        on_model["RMSE"], on_orig["RMSE"] = clean(np.sqrt((e ** 2).mean())), clean(np.sqrt((eo ** 2).mean()))
    if "MAE" in which:
        on_model["MAE"], on_orig["MAE"] = clean(np.abs(e).mean()), clean(np.abs(eo).mean())
    if "相对误差" in which:
        ok = yo != 0
        rel = np.abs(eo[ok]) / np.abs(yo[ok])
        on_orig["相对误差的均值"] = clean(rel.mean()) if ok.any() else None
        on_orig["相对误差的中位数"] = clean(np.median(rel)) if ok.any() else None
    if on_model:
        out[f"模型尺度（{transform}）"] = on_model
    if on_orig:
        out["原始尺度"] = on_orig
    if "秩相关" in which:
        same = len(y) < 3 or np.ptp(y) == 0 or np.ptp(mu) == 0
        out["秩相关"] = None if same else clean(spearmanr(y, mu)[0])
    out["90% 区间覆盖率"] = clean((np.abs(e) <= Z90 * sd).mean())
    return out


# ---------------------------------------------------------------- 预测器文件


def pack_predictor(manifest: dict, models: dict) -> bytes:
    """预测器是一个 zip：说明、模型、三者的哈希。哈希对不上就是被改过。"""
    import joblib

    buf = io.BytesIO()
    joblib.dump(models, buf)
    files = {"manifest.json": dump_json(manifest), "model.joblib": buf.getvalue()}
    files["hashes.json"] = dump_json({name: sha256_bytes(data) for name, data in files.items()})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data)
    return out.getvalue()


def environment() -> dict:
    import joblib
    import numpy
    import scipy
    import sklearn

    return {
        "python": platform.python_version(), "numpy": numpy.__version__, "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__, "joblib": joblib.__version__, "线程数": 1,
    }


# ---------------------------------------------------------------- 一次训练


def run(job: dict, stage=lambda text: None) -> dict:
    """做一次训练。返回写出的两个文件和几个要进实验记录的数。"""
    import numpy as np

    cfg = resolve(job)
    out_dir = Path(job["out_dir"])
    if out_dir.exists():
        raise SettingError(f"产出文件夹已经在了，不往里写：{out_dir}")

    stage("读数据")
    data_path = Path(job["data"]["path"])
    data = data_path.read_bytes()
    data_sha = sha256_bytes(data)
    expected = job["data"].get("expected_sha256")
    if expected and expected != data_sha:
        raise SettingError(f"训练数据在启动之后被改过，哈希对不上：{data_path}")
    cols, rows = read_table(data)
    d = pick_rows(cols, rows, cfg)
    numeric = cfg["read"]["设计"] + cfg["read"]["条件"]
    kind = cfg["model"]["模型种类"]
    X, Y = np.asarray(d["X"], float).reshape(len(d["ids"]), len(numeric)), np.asarray(d["Y"], float)

    stage("划分")
    folds = make_split(d, cfg["split"], cfg["seed"])
    cross = cfg["split"]["种类"] == "k 折"
    error_name = "交叉验证误差" if cross else "留出误差"

    def train_on(rows_idx):
        enc = Encoder(numeric, X[rows_idx], [d["bones"][i] for i in rows_idx])
        Z = enc.matrix(X[rows_idx], [d["bones"][i] for i in rows_idx])
        return enc, {t["列"]: fit(Z, Y[rows_idx, j], cfg["model"], cfg["seed"]) for j, t in enumerate(cfg["targets"])}

    def predict_on(enc, models, rows_idx):
        Z = enc.matrix(X[rows_idx], [d["bones"][i] for i in rows_idx])
        return {name: predict(est, kind, Z) for name, est in models.items()}

    # 每一折：只用这一折的训练行训练，在这一折的留出行上预测
    held = {}  # 行下标 -> (第几折, {目标: (预测, 标准差)})
    per_fold = []
    fold_models = []
    for k, (train, test) in enumerate(folds):
        stage(f"训练并算误差（第 {k + 1}/{len(folds)} 折）" if cross else "训练并算误差")
        enc, models = train_on(train)
        fold_models.append((enc, models))
        pred = predict_on(enc, models, test)
        for pos, i in enumerate(test):
            held[i] = (k, {name: (float(pred[name][0][pos]), float(pred[name][1][pos])) for name in pred})
        per_fold.append({
            "折": k + 1, "训练行数": len(train), "留出行数": len(test),
            **{t["列"]: measure(Y[test, j], *pred[t["列"]], t["变换"], cfg["model"]["误差指标"]) for j, t in enumerate(cfg["targets"])},
        })

    # 存下来的预测器：留出和按列时就是上面那一个（没见过留出行）；k 折时用全部行另训一个
    if cross:
        stage("用全部行训练要存的预测器")
        final_rows = list(range(len(d["ids"])))
        enc, models = train_on(final_rows)
        trained_on = f"全部 {len(final_rows)} 行。交叉验证时每一折的模型不见自己那一折；存下的预测器是之后用全部行另训的，下面的{error_name}不是它的留出误差。"
    else:
        final_rows = folds[0][0]
        enc, models = fold_models[0]
        trained_on = f"训练行（{len(final_rows)} 行）。留出的 {len(folds[0][1])} 行没有进训练，下面的数是{error_name}。"

    stage("算误差")
    order = sorted(held)
    errors = {}
    for j, t in enumerate(cfg["targets"]):
        name = t["列"]
        mu = [held[i][1][name][0] for i in order]
        sd = [held[i][1][name][1] for i in order]
        entry = {error_name: measure(Y[order, j], mu, sd, t["变换"], cfg["model"]["误差指标"])}
        if cross:
            entry["各折"] = [{"折": f["折"], **f[name]} for f in per_fold]
        fit_mu, fit_sd = predict_on(enc, models, final_rows)[name]
        entry["训练行上的误差（不是留出误差，只用来看拟合）"] = measure(Y[final_rows, j], fit_mu, fit_sd, t["变换"], cfg["model"]["误差指标"])
        errors[name] = entry

    train_ids = [d["ids"][i] for i in final_rows]
    held_ids = [d["ids"][i] for i in order]
    train_hash = sha256_bytes("\n".join(train_ids).encode("utf-8"))
    inputs = {"骨": cfg["read"]["骨"], "设计": cfg["read"]["设计"], "条件": cfg["read"]["条件"], **enc.describe()}
    env = environment()

    report = {
        "格式": REPORT_FORMAT,
        "插件": job.get("plugin", {}),
        "误差叫什么": error_name,
        "预测器是用哪些行训练的": trained_on,
        "数据": {
            "位置": str(data_path), "sha256": data_sha, "总行数": d["n_total"], "筛选后行数": d["n_filtered"],
            "限了行数之后": d["n_limited"], "因为缺值去掉的行": d["dropped"], "用的行数": len(d["ids"]),
        },
        "数据怎么读": cfg["read"],
        "输入（存下的预测器）": inputs,
        "预测目标": cfg["targets"],
        "模型和训练配置": cfg["model"],
        "随机种子": cfg["seed"],
        "划分": {
            **cfg["split"],
            "折": [{"折": k + 1, "训练行": [d["ids"][i] for i in tr], "留出行": [d["ids"][i] for i in te]} for k, (tr, te) in enumerate(folds)],
        },
        "存下的预测器的训练行": {"行数": len(train_ids), "哈希": train_hash, "行": train_ids},
        "指标的定义": METRIC_DEFS,
        "误差": errors,
        "逐行（每一行都是它不在训练里的那个模型给的）": [
            {
                "行": d["ids"][i], "折": held[i][0] + 1,
                **{t["列"]: {"真值": float(Y[i, j]), "预测": held[i][1][t["列"]][0], "标准差": held[i][1][t["列"]][1]} for j, t in enumerate(cfg["targets"])},
            }
            for i in order
        ],
        "逐行的数在什么尺度上": {t["列"]: t["变换"] for t in cfg["targets"]},
        "环境": env,
    }
    manifest = {
        "格式": PREDICTOR_FORMAT,
        "出自": job.get("plugin", {}),
        "模型种类": kind,
        "不确定度": UNCERTAINTY[kind],
        "输入": {**inputs, "数值列的顺序": numeric, "标签表里行的名字": cfg["read"]["行的名字"]},
        "目标": cfg["targets"],
        "训练": {
            "数据位置": str(data_path), "数据 sha256": data_sha, "训练行数": len(train_ids), "训练行的哈希": train_hash,
            "划分": cfg["split"], "误差叫什么": error_name, "预测器是用哪些行训练的": trained_on,
            "随机种子": cfg["seed"], "配置": cfg["model"],
        },
        "环境": env,
        "模型文件": "model.joblib",
    }

    stage("写产出")
    out_dir.mkdir(parents=True)  # 已经在了就报错，不覆盖
    (out_dir / PREDICTOR_NAME).write_bytes(pack_predictor(manifest, models))
    (out_dir / REPORT_NAME).write_bytes(dump_json(report))
    headline = {t["列"]: errors[t["列"]][error_name] for t in cfg["targets"]}
    return {
        "predictor": str(out_dir / PREDICTOR_NAME),
        "report": str(out_dir / REPORT_NAME),
        "error_name": error_name,
        "split_kind": cfg["split"]["种类"],
        "model_kind": kind,
        "targets": [t["列"] for t in cfg["targets"]],
        "n_train": len(train_ids),
        "n_held": len(held_ids),
        "n_dropped": len(d["dropped"]),
        "provenance": {
            "训练数据_sha256": data_sha, "训练行数": len(train_ids), "训练行的哈希": train_hash,
            "留出行数": len(held_ids), "环境": env, "worker_sha256": sha256_bytes(Path(__file__).read_bytes()),
        },
        "headline": headline,
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
    except SettingError as err:
        put(state="失败", stage="", error=str(err), raw=traceback.format_exc())
    except Exception as err:  # 出问题是正常的：写下来，由插件记成问题
        put(state="失败", stage="", error=f"{type(err).__name__}: {err}", raw=traceback.format_exc())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
