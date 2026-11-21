"""出预测插件的测试。每个测试用临时文件夹当 home，不碰真的 experiments。

预测器从哪来：在同一个临时 home 里用训练插件（scalar-train）跑一个实验，走的是操作台，
和真用的时候一样。两个插件之间没有代码上的调用。
"""
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

from stemlab.console import Desk
from stemlab.record import FINISHED, RUNNING, RecordError

PLUGIN_DIR = Path(__file__).resolve().parent.parent
TRAIN_DIR = PLUGIN_DIR.parent / "scalar_train"
REAL = Path(r"H:/projects/Femoral implant generation/db3406/v0.14/scalars.csv")
D13 = ["L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p"]


def load_worker():
    spec = importlib.util.spec_from_file_location("scalar_predict_worker_under_test", PLUGIN_DIR / "worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


W = load_worker()


def make_table(path: Path, n: int = 60, bones=("boneA",)) -> list[dict]:
    """一份小标签表。给两种骨时，第二种骨的 y2 整体高 40。"""
    rng = np.random.default_rng(7)
    rows = []
    for i in range(n):
        a, b, c = rng.uniform(0, 1, 3)
        cond = [0.1, 0.2][i % 2]
        which = (i // 2) % len(bones)
        rows.append({
            "row_id": f"r{i:03d}", "femur_id": bones[which], "status": "DONE",
            "a": repr(float(a)), "b": repr(float(b)), "c": repr(float(c)), "cond": repr(cond), "const": "0.3",
            "design_key": f"d{i:03d}", "split": "test" if i % 5 == 0 else "train",
            "y1": repr(float(10 ** (0.5 + 1.5 * a - b + 2 * cond + 0.02 * rng.normal()))),
            "y2": repr(float(100 + 50 * np.sin(3 * a) + 30 * c + 40 * which + rng.normal())),
        })
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


READ = {"行的名字": "row_id", "骨": "femur_id", "设计": ["a", "b", "c"], "条件": ["cond", "const"]}
GP = {"模型种类": "高斯过程", "重启次数": 0}
RF = {"模型种类": "随机森林", "树的棵数": 30}


@pytest.fixture
def home(tmp_path):
    for src in (PLUGIN_DIR, TRAIN_DIR):
        shutil.copytree(src, tmp_path / "plugins" / src.name, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    return tmp_path


def wait(desk, exp_id, timeout=180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        desk.refresh(exp_id)
        view = desk.store.open(exp_id).view()
        if view["status"] != RUNNING:
            return view
        time.sleep(0.2)
    raise AssertionError("没有在预期的时间内结束")


def train(desk, data: Path, model=GP, read=READ, targets=None, split=None) -> str:
    e = desk.new("scalar-train")
    desk.set(e, "训练数据", ref=str(data), source="测试造的表")
    desk.set(e, "数据怎么读", value=read)
    desk.set(e, "预测目标", value=targets or [{"列": "y1", "变换": "log10"}, "y2"])
    desk.set(e, "模型和训练配置", value=model)
    desk.set(e, "划分", value=split or {"种类": "按列", "列": "split", "留出的值": ["test"]})
    desk.set(e, "随机种子", value=0)
    assert desk.start(e)
    view = wait(desk, e, timeout=600)
    assert view["status"] == FINISHED and view["problems"] == [], view["problems"]
    return e


def point(name, a=0.5, b=0.5, c=0.5, cond=0.1, bone="boneA", **more) -> dict:
    return {"名字": name, "骨": bone, "设计": {"a": a, "b": b, "c": c}, "条件": {"cond": cond}, **more}


def batch(*points) -> dict:
    return {"格式": "一批点 v0", "点": list(points)}


def predict_exp(desk, trained: str | None = None, predictor_file: Path | None = None, points=None, points_file: Path | None = None) -> str:
    e = desk.new("scalar-predict")
    if trained:
        desk.set(e, "预测器", from_exp=trained, output="预测器")
    else:
        desk.set(e, "预测器", ref=str(predictor_file), source="外来的文件")
    if points_file:
        desk.set(e, "一批点", file=str(points_file), source="测试")
    else:
        desk.set(e, "一批点", value=points, source="手填")
    return e


def result(desk, exp_id) -> dict:
    return json.loads(desk.store.open(exp_id).output_path("预测")[0].read_text(encoding="utf-8"))


def flip_byte(path: Path, where: bytes | None = None) -> None:
    data = bytearray(path.read_bytes())
    at = data.index(where) + len(where) + 40 if where else len(data) // 2
    data[at] ^= 0x01
    path.write_bytes(bytes(data))


# ---------------------------------------------------------------- 验收 3 前半：读训练实验的产出，对一批点出预测


@pytest.mark.parametrize("model", [GP, RF], ids=["高斯过程", "随机森林"])
def test_predicts_a_batch_from_a_training_experiment(home, tmp_path, model):
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    assert desk.plugin_errors == []
    t = train(desk, tmp_path / "labels.csv", model=model)
    e = predict_exp(desk, trained=t, points=batch(point("p1"), point("p2", a=0.1, cond=0.2, 理由="选点插件说它好"), point("p3", b=0.9)))
    assert desk.start(e)
    view = wait(desk, e)
    assert view["status"] == FINISHED and view["problems"] == [] and view["tasks"]["预测"]["state"] == "完成"
    assert [o["name"] for o in view["outputs"]] == ["预测", "预测表"]
    assert view["settings"]["预测器"]["source"] == {"kind": "实验产出", "experiment": t, "output": "预测器"}
    doc = result(desk, e)
    assert doc["格式"] == "一份预测 v0" and doc["一批点"] == {**doc["一批点"], "读成": "JSON", "点数": 3, "出了数的": 3, "没出数的": 0}
    assert doc["预测器"]["sha256"] == view["settings"]["预测器"]["content"]["sha256"] == view["provenance"]["预测器_sha256"]
    assert doc["预测器"]["训练"]["误差叫什么"] == "留出误差"
    values = []
    for p in doc["点"]:
        assert p["问题"] is None and set(p["预测"]) == {"y1", "y2"}
        for n in p["预测"].values():
            assert n["标准差"] >= 0 and n["区间90"][0] <= n["预测值"] <= n["区间90"][1]
        assert p["没写、按训练时的值算的输入"] == {"const": 0.3}
        values.append(p["预测"]["y1"]["预测值"])
    assert len(set(values)) == 3  # 三个点三个数，不是同一个数填三遍
    assert doc["点"][1]["理由"] == "选点插件说它好"  # 预测器不用的键原样带着
    table = list(csv.DictReader(io.StringIO(desk.store.open(e).output_path("预测表")[0].read_text(encoding="utf-8-sig"))))
    assert [r["名字"] for r in table] == ["p1", "p2", "p3"]
    assert float(table[0]["y1"]) == doc["点"][0]["预测"]["y1"]["预测值"]
    assert desk.store.open(e).check() == []


def test_csv_batch_reproduces_the_held_out_numbers_of_the_error_report(home, tmp_path):
    """把标签表本身当一批点（CSV）。留出行上的预测要和训练实验的误差报告逐数相同。"""
    data = tmp_path / "labels.csv"
    make_table(data)
    desk = Desk(home)
    t = train(desk, data)
    report = json.loads(desk.store.open(t).output_path("误差报告")[0].read_text(encoding="utf-8"))
    e = predict_exp(desk, trained=t, points_file=data)
    assert desk.start(e)
    assert wait(desk, e)["problems"] == []
    doc = result(desk, e)
    assert doc["一批点"]["读成"] == "CSV" and doc["一批点"]["点数"] == 60
    by_name = {p["名字"]: p for p in doc["点"]}
    held = report["逐行（每一行都是它不在训练里的那个模型给的）"]
    assert len(held) == 12
    for row in held:
        got = by_name[row["行"]]["预测"]
        assert got["y1"]["预测值"] == pytest.approx(10 ** row["y1"]["预测"], rel=1e-12)
        assert got["y1"]["标准差"] == pytest.approx(row["y1"]["标准差"], rel=1e-9)
        assert got["y2"]["预测值"] == pytest.approx(row["y2"]["预测"], rel=1e-12)


# ---------------------------------------------------------------- 验收 3 后半：预测器被改过，记问题，不出数


def test_tampered_predictor_file_gives_a_problem_and_no_numbers(home, tmp_path):
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    original = desk.store.open(t).output_path("预测器")[0]
    good, bad_model, bad_manifest = tmp_path / "good.zip", tmp_path / "bad_model.zip", tmp_path / "bad_manifest.zip"
    for copy in (good, bad_model, bad_manifest):
        shutil.copy2(original, copy)
    flip_byte(bad_model, where=b"model.joblib")  # 模型里改一个字节
    bad_manifest.write_bytes(bad_manifest.read_bytes().replace("留出误差".encode("utf-8"), "留出误羞".encode("utf-8"), 1))  # 说明里改一个字

    points = batch(point("p1"), point("p2", a=0.2))
    exps = {name: predict_exp(desk, predictor_file=f, points=points) for name, f in [("good", good), ("model", bad_model), ("manifest", bad_manifest)]}
    for e in exps.values():
        assert desk.start(e)
    views = {name: wait(desk, e) for name, e in exps.items()}

    # 对照：没改过的同一个文件，照常出数
    assert views["good"]["tasks"]["预测"]["state"] == "完成" and views["good"]["problems"] == []
    assert result(desk, exps["good"])["一批点"]["出了数的"] == 2

    for name in ("model", "manifest"):
        v = views[name]
        assert v["status"] == FINISHED and v["tasks"]["预测"]["state"] == "失败"
        assert v["outputs"] == []  # 没有出数
        assert not (home / "experiments" / exps[name] / "outputs").exists()
        assert len(v["problems"]) == 1 and "被改过" in v["problems"][0]["error"] and v["problems"][0]["task"] == "预测"
        assert desk.store.open(exps[name]).check() == []


def test_training_output_changed_before_start_is_refused_by_the_record(home, tmp_path):
    """用训练实验的产出当设置时，记录里有它的哈希。启动时对不上，地基直接不让启动。"""
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    e = predict_exp(desk, trained=t, points=batch(point("p1")))
    flip_byte(desk.store.open(t).output_path("预测器")[0], where=b"model.joblib")
    with pytest.raises(RecordError, match="哈希对不上"):
        desk.start(e)
    view = desk.store.open(e).view()
    assert view["outputs"] == [] and view["tasks"] == {}


def test_each_check_catches_what_the_other_cannot(home, tmp_path):
    """文件自带的哈希抓不到「改了内容又把哈希重算一遍」；启动时记下的哈希抓得到。"""
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    original = desk.store.open(t).output_path("预测器")[0]
    recorded = hashlib.sha256(original.read_bytes()).hexdigest()
    pts = tmp_path / "pts.json"
    pts.write_text(json.dumps(batch(point("p1")), ensure_ascii=False), encoding="utf-8")

    with zipfile.ZipFile(original) as z:
        files = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(files["manifest.json"])
    manifest["输入"]["数值列"][0]["均值"] += 1.0
    files["manifest.json"] = W.dump_json(manifest)
    files["hashes.json"] = W.dump_json({n: hashlib.sha256(files[n]).hexdigest() for n in ("manifest.json", "model.joblib")})
    repacked = tmp_path / "repacked.zip"
    with zipfile.ZipFile(repacked, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)

    def job(name, expected):
        return {"attempt_dir": str(tmp_path), "out_dir": str(tmp_path / name), "points": {"path": str(pts)},
                "predictor": {"path": str(repacked), "expected_sha256": expected}}

    assert W.run(job("without", None))["n_good"] == 1  # 自带的哈希自己对得上，放过去了
    with pytest.raises(W.Refused, match="启动之后被改过"):
        W.run(job("with", recorded))
    assert not (tmp_path / "with").exists()

    # 反过来：改了说明、没重算哈希（zip 本身是好的）。这时靠的是文件自带的哈希
    with zipfile.ZipFile(original) as z:
        stale = {n: z.read(n) for n in z.namelist()}
    stale["manifest.json"] = files["manifest.json"]
    with zipfile.ZipFile(repacked, "w") as z:
        for n, d in stale.items():
            z.writestr(n, d)
    with pytest.raises(W.Refused, match="manifest.json 的哈希和文件里记的对不上"):
        W.run(job("stale", None))
    assert not (tmp_path / "stale").exists()


@pytest.mark.parametrize("content", [b"", b"not a zip at all", b"PK\x03\x04 broken"], ids=["空文件", "不是 zip", "坏的 zip"])
def test_file_that_is_not_a_predictor_is_refused(tmp_path, content):
    f, pts = tmp_path / "x.zip", tmp_path / "pts.json"
    f.write_bytes(content)
    pts.write_text(json.dumps(batch(point("p1")), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(W.Refused, match="被改过或坏了"):
        W.run({"attempt_dir": str(tmp_path), "out_dir": str(tmp_path / "o"), "predictor": {"path": str(f)}, "points": {"path": str(pts)}})


# ---------------------------------------------------------------- 一个点出问题，不拦别的点


def test_points_with_problems_get_no_numbers_and_others_still_do(home, tmp_path):
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    points = batch(
        point("好的"),
        point("没见过的骨", bone="boneZ"),
        {"名字": "缺输入", "骨": "boneA", "设计": {"a": 0.5, "b": 0.5}, "条件": {"cond": 0.1}},
        {"名字": "也缺输入", "骨": "boneA", "设计": {"a": 0.5, "b": 0.5}, "条件": {"cond": 0.1}},
        {"名字": "条件没学过", "骨": "boneA", "设计": {"a": 0.5, "b": 0.5, "c": 0.5}, "条件": {"cond": 0.1, "const": 0.4}},
        point("超出范围", a=7.0),
        point("没写骨", bone=None),
    )
    e = predict_exp(desk, trained=t, points=points)
    assert desk.start(e)
    view = wait(desk, e)
    assert view["status"] == FINISHED and view["tasks"]["预测"]["state"] == "完成"
    doc = result(desk, e)
    by_name = {p["名字"]: p for p in doc["点"]}
    assert doc["一批点"]["出了数的"] == 3 and doc["一批点"]["没出数的"] == 4
    assert by_name["好的"]["预测"] and by_name["好的"]["问题"] is None
    assert by_name["超出范围"]["预测"] and by_name["超出范围"]["超出训练范围的输入"] == ["a"]
    for name, says in [("没见过的骨", "没见过"), ("缺输入", "缺输入或不是数：c"), ("条件没学过", "没学过")]:
        assert by_name[name]["预测"] is None and says in by_name[name]["问题"]
    # 预测器只见过一种骨：没写骨的点按那一种算，并写明。数和写了骨的同一个点一样
    assert by_name["没写骨"]["问题"] is None and by_name["没写骨"]["没写、按训练时的值算的输入"]["骨"] == "boneA"
    assert by_name["没写骨"]["预测"] == by_name["好的"]["预测"]
    errors = [p["error"] for p in view["problems"]]
    assert len(errors) == 3  # 一种原因一条，两个缺输入的点合在一条里
    assert any("2 个点没出数" in x and "缺输入" in x and "也缺输入" in x for x in errors)
    assert all(p["task"] == "预测" for p in view["problems"])


def test_selection_plugin_shaped_batch_is_read(home, tmp_path):
    """选点插件（Lane）出的一批点：最外层是列表，每个点是名字、设计、条件、理由，没有骨。"""
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    lane_like = [
        {"名字": "c03", "设计": {"a": 0.25, "b": 0.35, "c": 0.5}, "条件": {"cond": 0.1}, "理由": "可行，随机取的", "去骨量": 5.0},
        {"名字": "c07", "设计": {"a": 0.65, "b": 0.45, "c": 0.5}, "条件": {"cond": 0.2}, "理由": "可行，随机取的", "去骨量": 6.0},
    ]
    e = predict_exp(desk, trained=t, points=lane_like)
    assert desk.start(e)
    view = wait(desk, e)
    assert view["problems"] == [] and view["tasks"]["预测"]["state"] == "完成"
    doc = result(desk, e)
    assert doc["一批点"]["出了数的"] == 2
    for p, src in zip(doc["点"], lane_like):
        assert p["预测"] and p["理由"] == src["理由"] and p["去骨量"] == src["去骨量"]  # 别的键原样带着
        assert p["没写、按训练时的值算的输入"] == {"骨": "boneA", "const": 0.3}


def test_two_bones_bone_enters_the_model_and_must_be_written(home, tmp_path):
    make_table(tmp_path / "labels.csv", n=80, bones=("boneA", "boneB"))
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    e = predict_exp(desk, trained=t, points=batch(point("在A上"), point("在B上", bone="boneB"), point("没写骨", bone=None), point("别的骨", bone="boneC")))
    assert desk.start(e)
    view = wait(desk, e)
    by_name = {p["名字"]: p for p in result(desk, e)["点"]}
    ya, yb = by_name["在A上"]["预测"]["y2"]["预测值"], by_name["在B上"]["预测"]["y2"]["预测值"]
    assert 25 < yb - ya < 55  # 表里第二种骨的 y2 高 40：同一个设计换了骨，预测跟着变
    assert by_name["没写骨"]["预测"] is None and "没写骨" in by_name["没写骨"]["问题"] and "2 种骨" in by_name["没写骨"]["问题"]
    assert by_name["别的骨"]["预测"] is None and "没见过" in by_name["别的骨"]["问题"]
    assert len(view["problems"]) == 2


def test_bad_batches_are_refused_with_a_reason(home, tmp_path):
    make_table(tmp_path / "labels.csv")
    desk = Desk(home)
    t = train(desk, tmp_path / "labels.csv")
    cases = {
        "空的": batch(),
        "重名": batch(point("p"), point("p")),
        "没有点": {"格式": "一批点 v0"},
    }
    exps = {name: predict_exp(desk, trained=t, points=pts) for name, pts in cases.items()}
    for e in exps.values():
        assert desk.start(e)
    views = {name: wait(desk, e) for name, e in exps.items()}
    for name, says in [("空的", "空的"), ("重名", "重复的名字"), ("没有点", "「点」")]:
        assert views[name]["tasks"]["预测"]["state"] == "失败" and views[name]["outputs"] == []
        assert says in views[name]["problems"][0]["error"]


# ---------------------------------------------------------------- 真数据（db3406 v0.14，只读）


@pytest.mark.skipif(not REAL.exists(), reason="db3406 v0.14 的 scalars.csv 不在这台机器上")
def test_real_table_train_then_predict(home):
    before = hashlib.sha256(REAL.read_bytes()).hexdigest()
    desk = Desk(home)
    read = {"行的名字": "row_id", "行的筛选": {"status": "DONE", "kind": "design", "has_fric_model": "true"},
            "最多用几行": 60, "骨": "femur_id", "设计": D13, "条件": ["delta_mm"]}
    t = train(desk, REAL, model={"模型种类": "高斯过程", "重启次数": 1}, read=read,
              targets=[{"列": "rot_first_deg", "变换": "log10"}, "contact_area_load2_mm2"],
              split={"种类": "留出", "留出比例": 0.2, "分组列": "design_key"})
    with open(REAL, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "DONE" and r["kind"] == "design" and r["has_fric_model"] == "true"]
    pts = [
        {"名字": r["row_id"], "骨": r["femur_id"], "设计": {c: float(r[c]) for c in D13}, "条件": {"delta_mm": float(r["delta_mm"])}}
        for r in rows[60:70]  # 训练没用到的 10 行
    ]
    pts.append({**pts[0], "名字": "换了骨的", "骨": "别的骨"})
    e = predict_exp(desk, trained=t, points=batch(*pts))
    assert desk.start(e)
    view = wait(desk, e)
    doc = result(desk, e)
    assert doc["一批点"]["出了数的"] == 10 and doc["一批点"]["没出数的"] == 1
    assert len(view["problems"]) == 1 and "别的骨" in view["problems"][0]["error"]
    for p in doc["点"][:10]:
        n = p["预测"]["rot_first_deg"]
        assert 0 < n["区间90"][0] < n["预测值"] < n["区间90"][1]
    assert hashlib.sha256(REAL.read_bytes()).hexdigest() == before
