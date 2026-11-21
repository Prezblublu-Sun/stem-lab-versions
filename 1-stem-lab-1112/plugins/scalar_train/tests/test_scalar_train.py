"""训练插件的测试。每个测试用临时文件夹当 home，不碰真的 experiments。

多数测试用一份现造的小标签表，不依赖任何外面的文件。
最后两个用 db3406 v0.14 的 scalars.csv（只读），文件不在就跳过。

每条要守的事都配一个「能不过」的对照：同一个检查，在该不一样的时候确实不一样。
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
from stemlab.record import FINISHED, RUNNING, STOPPED, pid_alive

PLUGIN_DIR = Path(__file__).resolve().parent.parent
REAL = Path(r"H:/projects/Femoral implant generation/db3406/v0.14/scalars.csv")
D13 = ["L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p"]


def load_worker():
    spec = importlib.util.spec_from_file_location("scalar_train_worker_under_test", PLUGIN_DIR / "worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


W = load_worker()


def make_table(path: Path, n: int = 80, poison: set | None = None) -> list[dict]:
    """一份小标签表。poison 里的行，标签乘 1000（用来看这些行有没有进训练）。"""
    rng = np.random.default_rng(7)
    rows = []
    for i in range(n):
        a, b, c = rng.uniform(0, 1, 3)
        cond = [0.1, 0.2][i % 2]
        y1 = 10 ** (0.5 + 1.5 * a - b + 2 * cond + 0.02 * rng.normal())
        y2 = 100 + 50 * np.sin(3 * a) + 30 * c + rng.normal()
        row = {
            "row_id": f"r{i:03d}", "femur_id": "boneA", "status": "DONE",
            "a": repr(float(a)), "b": repr(float(b)), "c": repr(float(c)), "cond": repr(cond), "const": "0.3",
            "design_key": f"d{i // 2:03d}",  # 两行一个设计
            "split": "test" if i % 5 == 0 else "train",
            "y1": repr(float(y1)), "y2": repr(float(y2)),
        }
        if poison and row["row_id"] in poison:
            row["y1"], row["y2"] = repr(float(y1) * 1000), repr(float(y2) * 1000)
        rows.append(row)
    rows.append({**rows[0], "row_id": "bad1", "status": "FAILED", "y1": "", "y2": ""})  # 会被筛掉
    rows.append({**rows[1], "row_id": "nolabel", "design_key": "dx", "y2": "nan"})  # 缺标签，去掉并记下
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


READ = {"行的名字": "row_id", "行的筛选": {"status": "DONE"}, "骨": "femur_id", "设计": ["a", "b", "c"], "条件": ["cond", "const"]}
TARGETS = [{"列": "y1", "变换": "log10"}, "y2"]
GP = {"模型种类": "高斯过程", "重启次数": 0}
RF = {"模型种类": "随机森林", "树的棵数": 30}
HOLDOUT = {"种类": "留出", "留出比例": 0.25, "分组列": "design_key"}
KFOLD = {"种类": "k 折", "折数": 4, "分组列": "design_key"}
BY_COL = {"种类": "按列", "列": "split", "留出的值": ["test"]}


def job_for(tmp: Path, data: Path, name: str, model=GP, split=HOLDOUT, seed=0, read=READ, targets=TARGETS) -> dict:
    return {
        "attempt_dir": str(tmp), "out_dir": str(tmp / name), "data": {"path": str(data)},
        "read": read, "targets": targets, "model": model, "split": split, "seed": seed,
        "plugin": {"name": "scalar-train", "version": "测试"},
    }


def report_of(result: dict) -> dict:
    return json.loads(Path(result["report"]).read_text(encoding="utf-8"))


def predictor_of(path) -> tuple[dict, dict]:
    import joblib

    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json")), joblib.load(io.BytesIO(z.read("model.joblib")))


def probe(path) -> np.ndarray:
    """存下的预测器在一组固定的点上给的数。"""
    manifest, models = predictor_of(path)
    Z = np.random.default_rng(1).normal(size=(12, len(manifest["输入"]["数值列"])))
    return np.concatenate([np.concatenate(W.predict(models[t["列"]], manifest["模型种类"], Z)) for t in manifest["目标"]])


@pytest.fixture
def home(tmp_path):
    shutil.copytree(PLUGIN_DIR, tmp_path / "plugins" / "scalar_train", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    return tmp_path


def fill(desk, data: Path, model=GP, split=HOLDOUT, seed=0, read=READ, targets=TARGETS) -> str:
    e = desk.new("scalar-train")
    desk.set(e, "训练数据", ref=str(data), source="测试造的表")
    desk.set(e, "数据怎么读", value=read)
    desk.set(e, "预测目标", value=targets)
    desk.set(e, "模型和训练配置", value=model)
    desk.set(e, "划分", value=split)
    desk.set(e, "随机种子", value=seed)
    return e


def wait(desk, exp_id, timeout=180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        desk.refresh(exp_id)
        view = desk.store.open(exp_id).view()
        if view["status"] != RUNNING:
            return view
        time.sleep(0.2)
    raise AssertionError("训练没有在预期的时间内结束")


def output_file(desk, exp_id, name) -> Path:
    return desk.store.open(exp_id).output_path(name)[0]


# ---------------------------------------------------------------- 验收 1：同设置同种子，误差报告逐数相同


def test_same_settings_same_seed_gives_identical_report(home, tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    desk = Desk(home)
    a, b, c = fill(desk, data, seed=3), fill(desk, data, seed=3), fill(desk, data, seed=4)
    for e in (a, b, c):
        assert desk.start(e)
    views = [wait(desk, e) for e in (a, b, c)]
    assert [v["status"] for v in views] == [FINISHED] * 3
    assert [v["problems"] for v in views] == [[], [], []]
    ra, rb, rc = (output_file(desk, e, "误差报告").read_bytes() for e in (a, b, c))
    assert ra == rb  # 两个实验、两个进程，报告的每个字节相同
    assert ra != rc  # 对照：换一个种子，报告就不一样。所以上面那条不是恒真的
    assert json.loads(ra)["随机种子"] == 3


def test_random_forest_is_reproducible_too(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    r1 = W.run(job_for(tmp_path, data, "o1", model=RF))
    r2 = W.run(job_for(tmp_path, data, "o2", model=RF))
    r3 = W.run(job_for(tmp_path, data, "o3", model=RF, seed=1))
    assert Path(r1["report"]).read_bytes() == Path(r2["report"]).read_bytes()
    assert Path(r1["report"]).read_bytes() != Path(r3["report"]).read_bytes()
    assert report_of(r1)["模型和训练配置"]["不确定度"].startswith("集成")


# ---------------------------------------------------------------- 验收 2：留出的行没有进训练


@pytest.mark.parametrize("model", [GP, RF], ids=["高斯过程", "随机森林"])
def test_held_out_rows_never_reach_the_stored_predictor(tmp_path, model):
    """把留出行的标签乘 1000。留出时，存下的预测器一个数都不变；k 折时会变（对照）。"""
    clean, dirty = tmp_path / "clean.csv", tmp_path / "dirty.csv"
    make_table(clean)
    base = W.run(job_for(tmp_path, clean, "base", model=model, split=BY_COL))
    held = {r["行"] for r in report_of(base)["逐行（每一行都是它不在训练里的那个模型给的）"]}
    assert len(held) == 16
    make_table(dirty, poison=held)

    poisoned = W.run(job_for(tmp_path, dirty, "poisoned", model=model, split=BY_COL))
    assert np.array_equal(probe(base["predictor"]), probe(poisoned["predictor"]))  # 留出行改成什么都不影响预测器
    assert report_of(base)["存下的预测器的训练行"] == report_of(poisoned)["存下的预测器的训练行"]
    # 留出行的真值变了，所以留出误差变了：说明这些行确实只用来算误差
    assert report_of(base)["误差"]["y2"]["留出误差"] != report_of(poisoned)["误差"]["y2"]["留出误差"]

    # 对照：k 折存下的预测器用了全部行，同样的改动它就变了。这个检查抓得到漏进去的行
    k1 = W.run(job_for(tmp_path, clean, "k1", model=model, split=KFOLD))
    k2 = W.run(job_for(tmp_path, dirty, "k2", model=model, split=KFOLD))
    assert not np.array_equal(probe(k1["predictor"]), probe(k2["predictor"]))


def test_changing_the_split_changes_the_error_numbers(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    reports = {
        name: report_of(W.run(job_for(tmp_path, data, name, split=split, seed=seed)))
        for name, split, seed in [
            ("a", HOLDOUT, 0), ("same", HOLDOUT, 0), ("seed", HOLDOUT, 1),
            ("ratio", {**HOLDOUT, "留出比例": 0.4}, 0), ("col", BY_COL, 0),
        ]
    }
    err = {name: r["误差"]["y1"]["留出误差"] for name, r in reports.items()}
    assert err["a"] == err["same"]
    assert err["a"] != err["seed"] and err["a"] != err["ratio"] and err["a"] != err["col"]
    for r in reports.values():
        fold = r["划分"]["折"][0]
        assert not set(fold["训练行"]) & set(fold["留出行"])
        assert r["存下的预测器的训练行"]["行"] == fold["训练行"]


def test_input_scaling_uses_training_rows_only(tmp_path):
    data = tmp_path / "labels.csv"
    rows = {r["row_id"]: r for r in make_table(data)}
    result = W.run(job_for(tmp_path, data, "o", split=BY_COL))
    report = report_of(result)
    train = report["存下的预测器的训练行"]["行"]
    col_a = next(c for c in report["输入（存下的预测器）"]["数值列"] if c["列"] == "a")
    assert col_a["均值"] == pytest.approx(np.mean([float(rows[i]["a"]) for i in train]), rel=1e-12)
    everyone = [float(r["a"]) for r in rows.values() if r["status"] == "DONE" and r["row_id"] != "nolabel"]
    assert col_a["均值"] != pytest.approx(np.mean(everyone), rel=1e-6)  # 对照：不是全部行的均值


def test_groups_stay_on_one_side(tmp_path):
    data = tmp_path / "labels.csv"
    rows = {r["row_id"]: r for r in make_table(data)}
    for split in (HOLDOUT, KFOLD):
        report = report_of(W.run(job_for(tmp_path, data, split["种类"], split=split)))
        for fold in report["划分"]["折"]:
            tr = {rows[i]["design_key"] for i in fold["训练行"]}
            te = {rows[i]["design_key"] for i in fold["留出行"]}
            assert not tr & te
    # 对照：不分组时，同一个设计的两行会分到两边
    report = report_of(W.run(job_for(tmp_path, data, "nogroup", split={"种类": "留出", "留出比例": 0.25})))
    fold = report["划分"]["折"][0]
    assert {rows[i]["design_key"] for i in fold["训练行"]} & {rows[i]["design_key"] for i in fold["留出行"]}


# ---------------------------------------------------------------- 误差叫什么


def test_cross_validation_error_is_never_called_held_out_error(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    kfold = report_of(W.run(job_for(tmp_path, data, "k", split=KFOLD)))
    hold = report_of(W.run(job_for(tmp_path, data, "h", split=HOLDOUT)))
    assert kfold["误差叫什么"] == "交叉验证误差" and hold["误差叫什么"] == "留出误差"
    for target in ("y1", "y2"):
        assert "交叉验证误差" in kfold["误差"][target] and "留出误差" not in kfold["误差"][target]
        assert "留出误差" in hold["误差"][target] and "交叉验证误差" not in hold["误差"][target]
        assert len(kfold["误差"][target]["各折"]) == 4
    assert "全部" in kfold["预测器是用哪些行训练的"] and "不是它的留出误差" in kfold["预测器是用哪些行训练的"]
    assert kfold["存下的预测器的训练行"]["行数"] == kfold["数据"]["用的行数"]
    assert hold["存下的预测器的训练行"]["行数"] < hold["数据"]["用的行数"]
    # 每一行正好被留出一次
    rows = [r["行"] for r in kfold["逐行（每一行都是它不在训练里的那个模型给的）"]]
    assert len(rows) == len(set(rows)) == kfold["数据"]["用的行数"]


def test_only_chosen_metrics_are_reported(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    report = report_of(W.run(job_for(tmp_path, data, "o", model={**GP, "误差指标": ["RMSE", "秩相关"]})))
    e = report["误差"]["y1"]["留出误差"]
    assert set(e) == {"n", "模型尺度（log10）", "原始尺度", "秩相关", "90% 区间覆盖率"}
    assert set(e["模型尺度（log10）"]) == {"RMSE"} and set(e["原始尺度"]) == {"RMSE"}
    assert report["模型和训练配置"]["误差指标"] == ["RMSE", "秩相关"]


# ---------------------------------------------------------------- 记录里有什么


def test_report_records_data_hash_rows_and_dropped_rows(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    result = W.run(job_for(tmp_path, data, "o"))
    report = report_of(result)
    assert report["数据"]["sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
    assert report["数据"]["总行数"] == 82 and report["数据"]["筛选后行数"] == 81 and report["数据"]["用的行数"] == 80
    assert report["数据"]["因为缺值去掉的行"] == [{"行": "nolabel", "缺": ["y2"]}]
    train = report["存下的预测器的训练行"]
    assert train["哈希"] == hashlib.sha256("\n".join(train["行"]).encode("utf-8")).hexdigest()
    assert report["输入（存下的预测器）"]["训练时不变的输入"] == {"const": 0.3}
    assert report["输入（存下的预测器）"]["见过的骨"] == ["boneA"]
    manifest, models = predictor_of(result["predictor"])
    assert manifest["训练"]["数据 sha256"] == report["数据"]["sha256"]
    assert manifest["训练"]["训练行的哈希"] == train["哈希"]
    assert set(models) == {"y1", "y2"}
    with zipfile.ZipFile(result["predictor"]) as z:  # 预测器文件带着自己内容的哈希
        hashes = json.loads(z.read("hashes.json"))
        assert hashes == {n: hashlib.sha256(z.read(n)).hexdigest() for n in ("manifest.json", "model.joblib")}


def test_existing_output_folder_is_refused(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    first = W.run(job_for(tmp_path, data, "o"))
    before = Path(first["report"]).read_bytes()
    with pytest.raises(W.SettingError, match="已经在了"):
        W.run(job_for(tmp_path, data, "o", seed=9))
    assert Path(first["report"]).read_bytes() == before  # 没有被盖掉


def test_data_changed_after_start_is_refused(tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    job = job_for(tmp_path, data, "o")
    job["data"]["expected_sha256"] = hashlib.sha256(data.read_bytes()).hexdigest()
    data.write_bytes(data.read_bytes().replace(b"boneA", b"boneB", 1))
    with pytest.raises(W.SettingError, match="被改过"):
        W.run(job)
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize(
    "change, says",
    [
        ({"read": {**READ, "设计": ["a", "b", "没有这一列"]}}, "没有这些列"),
        ({"read": {**READ, "多余的键": 1}}, "不认识的键"),
        ({"targets": [{"列": "y1", "变换": "ln"}]}, "变换"),
        ({"targets": ["a"]}, "既是输入又是目标"),
        ({"model": {"模型种类": "神经网络"}}, "模型种类"),
        ({"model": {**GP, "树的棵数": 5}}, "没有这些配置"),
        ({"split": {"种类": "留一"}}, "种类"),
        ({"split": {"种类": "k 折", "折数": 500}}, "折数"),
        ({"seed": "abc"}, "随机种子"),
    ],
)
def test_wrong_settings_are_named(tmp_path, change, says):
    data = tmp_path / "labels.csv"
    make_table(data)
    with pytest.raises(W.SettingError, match=says):
        W.run({**job_for(tmp_path, data, "o"), **change})
    assert not (tmp_path / "o").exists()


# ---------------------------------------------------------------- 在操作台里走


def test_console_run_records_outputs_tasks_and_provenance(home, tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    desk = Desk(home)
    assert desk.plugin_errors == []
    e = fill(desk, data, split=KFOLD)
    assert desk.start(e)
    view = wait(desk, e)
    assert view["status"] == FINISHED and view["problems"] == []
    assert [h["state"] for h in view["tasks"]["训练"]["history"]][0] == "排队"
    assert view["tasks"]["训练"]["state"] == "完成"
    assert [o["name"] for o in view["outputs"]] == ["预测器", "误差报告"]
    assert "交叉验证误差" in view["outputs"][1]["what"]
    frozen = view["settings"]["训练数据"]["content"]
    assert frozen["kind"] == "位置" and frozen["sha256"] == view["provenance"]["训练数据_sha256"]  # 数据只记位置和哈希
    assert not (home / "experiments" / e / "settings" / "训练数据").exists()
    assert view["provenance"]["训练行数"] == 80 and view["provenance"]["环境"]["线程数"] == 1
    assert desk.store.open(e).check() == []


def test_wrong_setting_becomes_a_problem_not_a_crash(home, tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    desk = Desk(home)
    bad = fill(desk, data, targets=["没有这一列"])
    good = fill(desk, data)
    assert desk.start(bad) and desk.start(good)
    vb, vg = wait(desk, bad), wait(desk, good)
    assert vb["status"] == FINISHED and vb["tasks"]["训练"]["state"] == "失败" and vb["outputs"] == []
    assert "没有这些列" in vb["problems"][0]["error"] and vb["problems"][0]["task"] == "训练"
    assert vg["tasks"]["训练"]["state"] == "完成"  # 一个实验出问题，不拦别的


def test_stop_kills_the_process_and_retry_writes_a_new_folder(home, tmp_path):
    data = tmp_path / "labels.csv"
    make_table(data)
    desk = Desk(home)
    e = fill(desk, data)
    assert desk.start(e)
    folder = home / "experiments" / e
    pid = int((folder / "plugin_state" / "1" / "pid.txt").read_text())
    assert desk.stop(e)  # 后台进程这时还在装载
    view = desk.store.open(e).view()
    assert view["status"] == STOPPED and view["tasks"]["训练"]["state"] == "停止"
    for _ in range(100):
        if not pid_alive(pid):
            break
        time.sleep(0.1)
    assert not pid_alive(pid)
    assert not (folder / "outputs" / "1").exists()

    assert desk.retry(e)
    view = wait(desk, e)
    assert view["status"] == FINISHED and view["tasks"]["训练"]["state"] == "完成"
    assert view["provenance"]["第几次"] == 2
    assert output_file(desk, e, "预测器") == folder / "outputs" / "2" / "预测器.zip"


# ---------------------------------------------------------------- 真数据（db3406 v0.14，只读）

REAL_READ = {
    "行的名字": "row_id", "行的筛选": {"status": "DONE", "kind": "design", "has_fric_model": "true"},
    "最多用几行": 60, "骨": "femur_id", "设计": D13, "条件": ["delta_mm"],
}
REAL_TARGETS = [{"列": "rot_first_deg", "变换": "log10"}, "contact_area_load2_mm2"]
needs_real = pytest.mark.skipif(not REAL.exists(), reason="db3406 v0.14 的 scalars.csv 不在这台机器上")


@needs_real
def test_real_table_same_seed_identical_report(home):
    before = hashlib.sha256(REAL.read_bytes()).hexdigest()
    desk = Desk(home)
    ids = [fill(desk, REAL, read=REAL_READ, targets=REAL_TARGETS, model={"模型种类": "高斯过程", "重启次数": 1}, seed=s) for s in (0, 0, 1)]
    for e in ids:
        assert desk.start(e)
    views = [wait(desk, e, timeout=600) for e in ids]
    assert [v["problems"] for v in views] == [[], [], []]
    a, b, c = (output_file(desk, e, "误差报告").read_bytes() for e in ids)
    assert a == b and a != c
    report = json.loads(a)
    assert report["数据"]["sha256"] == before and report["数据"]["用的行数"] == 60
    assert report["误差叫什么"] == "留出误差"
    assert hashlib.sha256(REAL.read_bytes()).hexdigest() == before  # 旧数据没被动过


@needs_real
def test_real_table_split_changes_error(tmp_path):
    numbers = {}
    for name, split in [("a", HOLDOUT), ("b", {**HOLDOUT, "留出比例": 0.4}), ("k", {"种类": "k 折", "折数": 3, "分组列": "design_key"})]:
        report = report_of(W.run(job_for(tmp_path, REAL, name, model=RF, split=split, read=REAL_READ, targets=REAL_TARGETS)))
        numbers[name] = report["误差"]["rot_first_deg"][report["误差叫什么"]]
    assert numbers["a"] != numbers["b"] and numbers["a"] != numbers["k"]
