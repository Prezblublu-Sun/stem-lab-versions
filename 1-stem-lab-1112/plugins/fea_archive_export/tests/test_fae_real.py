"""验收：拿真实的归档（db3406/raw，只读）导出少量作业，和归档原文、和旧库 v0.14 逐值比。

旧库不在这台机器上时，这些测试跳过。位置可以用环境变量换：
  FAE_REAL_RAW      归档文件夹
  FAE_REAL_OLD      旧库的一个版本文件夹（里面有 scalars.csv 和 fields/）
每条「对得上」后面跟一条「改坏一处就对不上」的对照。
"""
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

import fae_checks as CH
import fae_columns as C
import fae_core as K
from fae_helpers import new_experiment, run_to_end
from stemlab.console import Desk
from stemlab.record import FINISHED

RAW = Path(os.environ.get("FAE_REAL_RAW", r"H:\projects\Femoral implant generation\db3406\raw"))
OLD = Path(os.environ.get("FAE_REAL_OLD", r"H:\projects\Femoral implant generation\db3406\v0.14"))

pytestmark = pytest.mark.skipif(not (RAW.is_dir() and (OLD / "scalars.csv").is_file()), reason="这台机器上没有旧库")

JOBS = {
    "sb13_a105_91e458e3": "只有摩擦模型",
    "d13bond_p13_a100_b1cce588_102676fb": "只有粘接模型",
    "db_fd_p13_init_4bb091df_h2.4_55670d41": "摩擦和粘接模型都有",
    "db_ref_intact_h1.4_b7b166b8": "完整股骨",
    "db_al_al3m_16_0e1927ad": "失败，没建成模型",
    "sb11_init_af3dc582": "失败，建了模型",
    "db_cd_db_al_al1_07_c4_6a7b6c57": "多循环，9 个分析步",
    "sb11_init_5dab466f": "旧表的求解器是从别处补的",
    "db_cd_p13_a105_91e458e3_m1_TA10_e31bfa78": "带扭转",
    "db_crt_c723_2790d7db": "旧导出时报过错",
}
# 旧表从归档以外补过的列：这里留空不算不同（有值而不一样照样算）
FILLED_FROM_OUTSIDE = {"source_job", "code_hash", "solver", "solve_wall_s_fric", "solve_wall_s_bond",
                       "solve_tries_fric", "solve_tries_bond"}
JSON_COLS = [c for c in C.NAMES if C.CLASS[c] == "json"]
IFACE_COLS = [c for c in C.NAMES if C.CLASS[c] == "界面场"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def old_rows():
    with open(OLD / "scalars.csv", newline="", encoding="utf-8") as f:
        return {r["job_id"]: r for r in csv.DictReader(f)}


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    """把这几个作业导出一次，后面的测试都用它。顺手记下归档文件导出前后的哈希。"""
    out = tmp_path_factory.mktemp("real_out")
    before = {j: (sha(RAW / f"{j}.tar.xz"), (RAW / f"{j}.tar.xz").stat().st_mtime_ns) for j in JOBS}
    results = {j: K.export_job(RAW, j, out, K.QUANTITIES) for j in JOBS}
    after = {j: (sha(RAW / f"{j}.tar.xz"), (RAW / f"{j}.tar.xz").stat().st_mtime_ns) for j in JOBS}
    K.write_labels(out, [r["row"] for r in results.values()])
    with open(out / "标签" / "标签.csv", newline="", encoding="utf-8") as f:
        mine = {r["job_id"]: r for r in csv.DictReader(f)}
    return {"out": out, "results": results, "mine": mine, "before": before, "after": after}


@pytest.fixture(scope="module")
def archive_files():
    cache: dict = {}

    def get(job):
        if job not in cache:
            cache.clear()  # 一次只留一个作业，省内存
            cache[job] = CH.tar_files(RAW / f"{job}.tar.xz")
        return cache[job]

    return get


# ---------------------------------------------------------------- 验收 1：标签

def test_a1_labels_equal_the_old_table_cell_by_cell(exported, old_rows):
    compared = 0
    left_empty = []
    for job in JOBS:
        mine, old = exported["mine"][job], old_rows[job]
        assert CH.diff_labels(mine, old, JSON_COLS, FILLED_FROM_OUTSIDE) == [], job
        assert CH.diff_labels(mine, old, IFACE_COLS, set()) == [], job  # 由界面场算的列也逐格相同
        compared += len(JSON_COLS) + len(IFACE_COLS)
        left_empty += [(job, c) for c in FILLED_FROM_OUTSIDE if mine[c] == "" and old[c] != ""]
    assert len(JSON_COLS) == 139 and len(IFACE_COLS) == 6 and compared == 1450
    # 留空而旧表有值的格子，一个个都说得清来历
    assert sorted(left_empty) == sorted([
        ("db_al_al3m_16_0e1927ad", "code_hash"),          # 没有 prep.json，旧表是由作业号反推的
        ("db_ref_intact_h1.4_b7b166b8", "source_job"),    # 旧表从批次清单里补的
        ("db_cd_db_al_al1_07_c4_6a7b6c57", "source_job"),
        ("sb11_init_5dab466f", "solver"),                 # solve.json 在求解后被覆盖过，旧表另有依据
    ])


def test_a1_the_label_check_can_fail(exported, old_rows):
    """对照：把导出的一格改掉一位，核对要报；留空的豁免不盖住「有值但不一样」。"""
    job = "sb13_a105_91e458e3"
    mine, old = dict(exported["mine"][job]), old_rows[job]
    mine["f1_p95_um"] = repr(np.nextafter(float(mine["f1_p95_um"]), 1e9))
    mine["solver"] = "calculix"
    bad = CH.diff_labels(mine, old, JSON_COLS, FILLED_FROM_OUTSIDE)
    assert len(bad) == 2 and bad[0].startswith("solver") and bad[1].startswith("f1_p95_um")


# ---------------------------------------------------------------- 验收 2：整体场

FIELD_JOBS = [j for j in JOBS if "失败" not in JOBS[j]]


@pytest.mark.parametrize("job", FIELD_JOBS)
def test_a2_global_field_equals_the_archive(exported, archive_files, job):
    """节点数、单元数、网格的每个数组、每张表的每个值，都和归档原文相同。"""
    files = archive_files(job)
    npz = exported["out"] / "整体场" / f"{job}.npz"
    assert exported["results"][job]["errors"] == []
    assert CH.diff_global(npz, files) == []
    g = K.read_global(npz)
    prep = json.loads(files["prep.json"])
    n_elems = sum(len(g["mesh"][k]) for k in g["mesh"] if k.endswith("_elab"))
    assert n_elems == sum(prep["n_tet"].values())  # 和建模记录里写的单元数也一致
    if "n_nodes" in prep:
        assert len(g["mesh"]["nodes"]) == prep["n_nodes"]
    for key, (lab, val, _cols) in ((k, v) for k, v in g.items() if isinstance(k, tuple)):
        if key[2] == "U":
            assert len(lab) == len(g["mesh"]["nodes"]) and np.array_equal(np.sort(lab), np.sort(g["mesh"]["node_labels"]))
        if key[2] in ("S", "E", "ENER"):
            assert len(lab) == n_elems
    assert all(c["ok"] for c in g["index"]["checks"])


def test_a2_step_coverage_is_what_the_archive_has(exported):
    """位移每步都有；应力应变只有归档里有的那几步，没有的不补。"""
    g = K.read_global(exported["out"] / "整体场" / "sb13_a105_91e458e3.npz")
    steps = lambda q: [k[1] for k in g if isinstance(k, tuple) and k[0] == "m_fric" and k[2] == q]  # noqa: E731
    assert steps("U") == ["RELEASE", "LOAD", "UNLOAD", "LOAD2"] == steps("RF")
    assert steps("S") == ["RELEASE", "LOAD2"] == steps("E")
    assert g[("m_fric", "LOAD2", "S")][2] == ["mises", "s11", "s22", "s12"]  # 只有 4 个数，不是 6 个分量
    assert g[("m_fric", "LOAD2", "E")][2] == ["e_max", "e_mid", "e_min"]     # 只有主值
    cyc = K.read_global(exported["out"] / "整体场" / "db_cd_db_al_al1_07_c4_6a7b6c57.npz")
    assert len([k for k in cyc if isinstance(k, tuple) and k[2] == "U"]) == 8
    both = K.read_global(exported["out"] / "整体场" / "db_fd_p13_init_4bb091df_h2.4_55670d41.npz")
    assert {k[2] for k in both if isinstance(k, tuple) and k[0] == "m_bond"} == {"S", "ENER"}
    assert not (exported["out"] / "整体场" / "db_al_al3m_16_0e1927ad.npz").exists()  # 失败、没网格：没有整体场


def test_a2_the_global_check_can_fail(exported, archive_files, tmp_path):
    """对照：真实作业的导出里，位移改最后一位、网格少一个单元，核对都要报。"""
    job = "sb13_a105_91e458e3"
    files = archive_files(job)
    z = dict(np.load(exported["out"] / "整体场" / f"{job}.npz", allow_pickle=False))
    one = dict(z)
    one["m_fric__UNLOAD__U"] = z["m_fric__UNLOAD__U"].copy()
    v = one["m_fric__UNLOAD__U"][40000, 1]
    one["m_fric__UNLOAD__U"][40000, 1] = np.nextafter(v, np.float32(np.inf))
    one["mesh_stem_elab"] = z["mesh_stem_elab"][:-1]
    np.savez(tmp_path / "off.npz", **one)
    bad = CH.diff_global(tmp_path / "off.npz", files)
    assert len(bad) == 3
    assert "stem_elab" in bad[0] and "单元数 30614 对 30615" in bad[1] and "UNLOAD_U.csv 第 40001 行 u2" in bad[2]


# ---------------------------------------------------------------- 界面场

IFACE_JOBS = [j for j in FIELD_JOBS if (RAW / f"{j}.manifest.json").is_file()
              and any("m_fric_csv/" in k for k in json.loads((RAW / f"{j}.manifest.json").read_text(encoding="utf-8"))["files_archive"])]


@pytest.mark.parametrize("job", IFACE_JOBS)
def test_interface_field_equals_the_archive_and_the_old_database(exported, archive_files, old_rows, job):
    npz = exported["out"] / "界面场" / f"{job}.npz"
    assert CH.diff_iface(npz, archive_files(job)) == []
    info = exported["results"][job]["inventory"]["iface"]
    assert info["unmatched_rows"] == 0  # 归档里的接触量每一行都落在节点对上，没有丢的
    old = old_rows[job]
    if old["field_shard"]:
        shard = np.load(OLD / "fields" / f"{old['field_shard']}.npz", allow_pickle=False)
        j = int(old["field_index"])
        assert str(shard["job_id"][j]) == job
        assert CH.diff_iface_old(npz, shard, j) == []


def test_interface_field_has_more_steps_and_quantities_than_the_old_one(exported):
    z = np.load(exported["out"] / "界面场" / "db_cd_db_al_al1_07_c4_6a7b6c57.npz", allow_pickle=False)
    assert len(z["steps"]) == 8 and z["cforce"].shape[1] == 8 and np.isfinite(z["cforce"]).all()
    assert {"c_CSLIP1", "c_CSLIP2", "c_CSHEAR1", "c_CSHEAR2", "c_CPRESS_stem", "f_CNAREA", "f_CNORMF_stem"} <= set(z.files)
    assert not {"loc", "srt", "nloc", "d_canal", "d_outer", "frame"} & set(z.files)  # 要股骨几何的量没有，也没有造


def test_the_interface_check_against_the_old_database_can_fail(exported, old_rows, tmp_path):
    job = "sb13_a105_91e458e3"
    old = old_rows[job]
    shard = np.load(OLD / "fields" / f"{old['field_shard']}.npz", allow_pickle=False)
    z = dict(np.load(exported["out"] / "界面场" / f"{job}.npz", allow_pickle=False))
    z["rel"] = z["rel"].copy()
    z["rel"][100, 3, 2] = np.nextafter(z["rel"][100, 3, 2], np.inf)
    np.savez(tmp_path / "off.npz", **z)
    assert CH.diff_iface_old(tmp_path / "off.npz", shard, int(old["field_index"])) == ["rel 不一样"]


# ---------------------------------------------------------------- 验收 3：坏归档

def test_a3_one_broken_real_archive_does_not_stop_the_others(home, tmp_path):
    """真实归档的副本里弄坏一个：它记成问题，别的照常导出。副本在临时文件夹，db3406 不动。"""
    jobs = ["sb13_a105_91e458e3", "d13bond_p13_a100_b1cce588_102676fb", "sb11_init_af3dc582", "db_al_al3m_16_0e1927ad"]
    arch = tmp_path / "arch"
    arch.mkdir()
    for j in jobs:
        for ext in (".tar.xz", ".manifest.json"):
            shutil.copy2(RAW / (j + ext), arch / (j + ext))
    broken = arch / "sb13_a105_91e458e3.tar.xz"
    broken.write_bytes(broken.read_bytes()[:3_000_000])  # 截掉后面一大半
    desk = Desk(home)
    exp = new_experiment(desk, arch, jobs, note="坏一个归档")
    desk.start(exp)
    view = run_to_end(desk, exp)
    assert view["status"] == FINISHED
    assert {k: t["state"] for k, t in view["tasks"].items()} == {
        "sb13_a105_91e458e3": "失败", "d13bond_p13_a100_b1cce588_102676fb": "完成",
        "sb11_init_af3dc582": "完成", "db_al_al3m_16_0e1927ad": "完成"}
    assert [(p["task"], "哈希和清单对不上" in p["error"]) for p in view["problems"]] == [("sb13_a105_91e458e3", True)]
    out = home / "experiments" / exp / "outputs"
    with open(out / "标签" / "标签.csv", newline="", encoding="utf-8") as f:
        assert sorted(r["job_id"] for r in csv.DictReader(f)) == sorted(jobs[1:])
    assert (out / "整体场" / "d13bond_p13_a100_b1cce588_102676fb.npz").exists()
    assert not (out / "整体场" / "sb13_a105_91e458e3.npz").exists()
    assert desk.store.open(exp).check() == []


# ---------------------------------------------------------------- 只读

def test_the_real_archive_was_not_changed(exported):
    assert exported["before"] == exported["after"]
    for job in JOBS:  # 归档文件现在的哈希还是它自己的清单里记的那个
        manifest = json.loads((RAW / f"{job}.manifest.json").read_text(encoding="utf-8"))
        assert exported["after"][job][0] in manifest["stream_sha256"].values()
