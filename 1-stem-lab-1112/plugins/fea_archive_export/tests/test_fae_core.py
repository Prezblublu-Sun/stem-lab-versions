"""导出核心的测试：用很小的假归档，不碰真数据。

每个「对得上」的测试后面跟一个「改坏一处就对不上」的对照，证明核对本身是会不过的。
"""
import csv
import io
import json

import numpy as np
import pytest

import fae_checks as CH
import fae_columns as C
import fae_core as K
import fae_synth as SY


@pytest.fixture
def arch(tmp_path):
    folder = tmp_path / "arch"
    SY.write_archive(folder, "syn_fric_0001", SY.job_files("fric", seed=1))
    SY.write_archive(folder, "syn_bond_0002", SY.job_files("bond", seed=2))
    SY.write_archive(folder, "syn_fail_0003", SY.job_files("failed", seed=3))
    return folder


def export(arch, job, out, quantities=K.QUANTITIES):
    return K.export_job(arch, job, out, quantities)


# ---------------------------------------------------------------- 读归档

def test_archive_is_read_and_checked_against_its_manifest(arch):
    a = K.Archive(arch, "syn_fric_0001").load()
    assert a.state() == "DONE" and a.notes == []
    assert a.has("spec.json") and a.has_dir("m_fric_csv") and not a.has_dir("m_bond_csv")
    assert K.step_order(a, "m_fric_csv") == SY.STEPS4


def test_a_changed_archive_is_refused(arch):
    """归档文件被改过一个字节：哈希和清单对不上，读不了。"""
    p = arch / "syn_fric_0001.tar.xz"
    blob = bytearray(p.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    p.write_bytes(bytes(blob))
    with pytest.raises(K.ArchiveError, match="哈希和清单对不上"):
        K.Archive(arch, "syn_fric_0001").load()


def test_a_cut_off_archive_without_manifest_is_refused(arch):
    """没有清单时，截掉一半的归档解不开，也读不了。"""
    p = arch / "syn_fric_0001.tar.xz"
    p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
    (arch / "syn_fric_0001.manifest.json").unlink()
    with pytest.raises(K.ArchiveError, match="解不开"):
        K.Archive(arch, "syn_fric_0001").load()


def test_missing_archive_and_missing_manifest(arch):
    with pytest.raises(K.ArchiveError, match="不存在"):
        K.Archive(arch, "no_such_job").load()
    (arch / "syn_bond_0002.manifest.json").unlink()
    a = K.Archive(arch, "syn_bond_0002").load()  # 没有清单：照读，但记一条
    assert any("没有清单" in n for n in a.notes)


def test_a_file_that_differs_from_the_manifest_is_refused(arch, tmp_path):
    """清单里某个文件的哈希对不上（整个归档的哈希没记）：读不了。"""
    m = arch / "syn_bond_0002.manifest.json"
    doc = json.loads(m.read_text(encoding="utf-8"))
    doc.pop("stream_sha256")
    doc["files_archive"]["syn_bond_0002/prep.json"]["sha256"] = "0" * 64
    m.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(K.ArchiveError, match="prep.json"):
        K.Archive(arch, "syn_bond_0002").load()


# ---------------------------------------------------------------- 标签

def test_label_row_is_what_the_archive_json_says(arch, tmp_path):
    res = export(arch, "syn_fric_0001", tmp_path / "out")
    row = res["row"]
    files = CH.tar_files(arch / "syn_fric_0001.tar.xz")
    spec, prep, result = (json.loads(files[f]) for f in ("spec.json", "prep.json", "result.json"))
    assert res["errors"] == [] and res["notes"] == []
    assert (row["status"], row["kind"], row["stage"]) == ("DONE", "design", "syn")
    for k in C.DESIGN_VARS:
        assert row[k] == (spec["h_cut"] if k == "h_cut" else spec["design"][k])
    assert row["cap_h_mm"] == 1.5 and row["collar_w_mm"] == 0.0
    assert row["delta_spec_mm"] == spec["delta"] and row["delta_mm"] == prep["delta"]
    assert row["load_vec_N"] == prep["load_N"] and row["n_tet_total"] == 3 and row["mesh_min_vol_mm3"] == 0.25
    assert row["steps"] == prep["steps"] and row["solver"] == "abaqus"
    assert (row["solve_wall_s_fric"], row["solve_tries_fric"], row["solve_wall_s_bond"]) == (12.5, 1, None)
    assert row["f1_p95_um"] == result["f1_p95_um"] and row["n_pairs_body"] == 5 and row["interface_area_body_mm2"] == 3.5
    assert row["extra_result_keys"] == {"some_new_number": 1.25}  # 没有对应列的数不丢
    assert (row["has_prep"], row["has_fric_model"], row["has_bond_model"]) == (True, True, False)
    assert row["spec_in_result_match"] is True and row["cons_delta"] is True and row["cons_h_int"] is True
    assert row["t_spec_utc"] == "2027-01-15T08:00:00Z" and row["t_done_utc"] == "2027-01-15T08:30:00Z"
    assert row["t_ready_utc"] == row["t_prep_utc"] == "2027-01-15T08:01:00Z" and row["t_failed_utc"] is None
    assert row["field_n_nodes"] == 6 and row["field_n_tri"] == 4


def test_failed_job_gets_a_row_with_its_reason_and_no_results(arch, tmp_path):
    res = export(arch, "syn_fail_0003", tmp_path / "out")
    row = res["row"]
    assert res["errors"] == []
    assert (row["status"], row["fail_level"], row["fail_stage"], row["fail_reason"]) == ("FAILED", "L3", "prep", "meshing failed")
    assert row["has_prep"] is False and row["f1_p95_um"] is None and row["L"] == 30.5
    assert not (tmp_path / "out" / "整体场").exists() and not (tmp_path / "out" / "界面场").exists()
    assert any("FAILED" in m for m in res["inventory"]["missing"])


def test_missing_keys_stay_empty_and_are_noted(tmp_path):
    """spec.json 里没有 h_cut、设计里没有 m：这两格留空并记一条，不替它填旧管线的默认值。"""
    files = SY.job_files("fric", seed=4)
    spec = json.loads(files["spec.json"])
    del spec["h_cut"], spec["design"]["m"]
    files["spec.json"] = json.dumps(spec).encode()
    SY.write_archive(tmp_path / "arch", "syn_old_0004", files)
    res = export(tmp_path / "arch", "syn_old_0004", tmp_path / "out")
    row = res["row"]
    assert row["h_cut"] is None and row["m"] is None and row["design_key"] is None
    assert sum("留空" in n for n in res["notes"]) == 2


def test_labels_csv_has_one_row_per_job_and_reads_back(arch, tmp_path):
    out = tmp_path / "out"
    rows = [export(arch, j, out)["row"] for j in ("syn_fric_0001", "syn_bond_0002", "syn_fail_0003")]
    K.write_labels(out, rows)
    back = list(csv.DictReader(io.StringIO((out / "标签" / "标签.csv").read_text(encoding="utf-8"))))
    assert [r["job_id"] for r in back] == ["syn_bond_0002", "syn_fail_0003", "syn_fric_0001"]
    assert list(back[0]) == C.NAMES
    fric = back[2]
    assert fric["L"] == "30.5" and fric["fric_only"] == "true" and fric["vm_p99_MPa"] == ""
    assert json.loads(fric["load_vec_N"]) == [-700.5, 600.25, -2100.125] and fric["export_notes"] == "[]"
    assert back[0]["vm_p99_MPa"] == "120.5" and back[0]["intact_job"] == "syn_intact_0000"


# ---------------------------------------------------------------- 整体场

def test_global_field_equals_the_archive_value_by_value(arch, tmp_path):
    out = tmp_path / "out"
    for job in ("syn_fric_0001", "syn_bond_0002"):
        res = export(arch, job, out)
        assert res["errors"] == []
        assert CH.diff_global(out / "整体场" / f"{job}.npz", CH.tar_files(arch / f"{job}.tar.xz")) == []
    g = K.read_global(out / "整体场" / "syn_fric_0001.npz")
    assert len(g["mesh"]["nodes"]) == 30 and sum(len(g["mesh"][k]) for k in g["mesh"] if k.endswith("_elab")) == 3
    lab, val, cols = g[("m_fric", "LOAD", "U")]
    assert cols == ["u1", "u2", "u3"] and val.shape == (30, 3) and lab.tolist() == SY.NODE_LABELS
    assert set(k[1] for k in g if isinstance(k, tuple) and k[2] == "S") == {"RELEASE", "LOAD2"}
    assert ("m_bond", "LOAD", "ENER") in K.read_global(out / "整体场" / "syn_bond_0002.npz")
    assert all(c["ok"] for c in g["index"]["checks"]) and len(g["index"]["checks"]) >= 8


def test_global_check_fails_when_one_value_or_one_count_is_off(arch, tmp_path):
    """对照：导出里改一个位移值、少一个节点，核对都要报出来。"""
    out = tmp_path / "out"
    export(arch, "syn_fric_0001", out)
    files = CH.tar_files(arch / "syn_fric_0001.tar.xz")
    src = out / "整体场" / "syn_fric_0001.npz"
    z = dict(np.load(src, allow_pickle=False))

    one = dict(z)
    one["m_fric__LOAD__U"] = z["m_fric__LOAD__U"].copy()
    one["m_fric__LOAD__U"][17, 2] = np.nextafter(one["m_fric__LOAD__U"][17, 2], np.float32(1))  # 只差最后一位
    np.savez(tmp_path / "one.npz", **one)
    bad = CH.diff_global(tmp_path / "one.npz", files)
    assert len(bad) == 1 and "LOAD_U.csv 第 18 行 u3" in bad[0]

    fewer = dict(z)
    fewer["mesh_nodes"] = z["mesh_nodes"][:-1]
    np.savez(tmp_path / "fewer.npz", **fewer)
    assert any("节点数 29 对 30" in b for b in CH.diff_global(tmp_path / "fewer.npz", files))


def test_field_rows_that_do_not_match_the_mesh_are_reported(tmp_path):
    """位移表比网格少一个节点：照样导出，但这个作业记一条错。"""
    files = SY.job_files("fric", seed=5)
    lines = files["m_fric_csv/LOAD_U.csv"].split(b"\r\n")
    files["m_fric_csv/LOAD_U.csv"] = b"\r\n".join(lines[:3] + lines[4:])  # 去掉节点 3（不在界面上）
    SY.write_archive(tmp_path / "arch", "syn_short_0005", files)
    res = export(tmp_path / "arch", "syn_short_0005", tmp_path / "out")
    assert len(res["errors"]) == 1 and "LOAD_U.csv" in res["errors"][0] and "29 对 30" in res["errors"][0]
    assert (tmp_path / "out" / "整体场" / "syn_short_0005.npz").exists()


def test_float32_is_used_only_when_nothing_is_lost(tmp_path):
    """有一个数存成 float32 会变：那张表整张留 float64；别的表是 float32。两种都逐值等于 csv。"""
    SY.write_archive(tmp_path / "arch", "syn_odd_0006", SY.job_files("fric", seed=6, odd_value=True))
    export(tmp_path / "arch", "syn_odd_0006", tmp_path / "out")
    p = tmp_path / "out" / "整体场" / "syn_odd_0006.npz"
    z = np.load(p, allow_pickle=False)
    assert z["m_fric__RELEASE__U"].dtype == np.float64 and z["m_fric__RELEASE__U"][0, 0] == 0.1 + 1e-12
    assert z["m_fric__LOAD__U"].dtype == np.float32
    assert CH.diff_global(p, CH.tar_files(tmp_path / "arch" / "syn_odd_0006.tar.xz")) == []
    a = np.array([0.5, np.nan, 0.1])
    assert K.compact(a).dtype == np.float64 and K.compact(np.array([0.5, np.nan])).dtype == np.float32


# ---------------------------------------------------------------- 界面场

def test_interface_field_equals_the_archive(arch, tmp_path):
    out = tmp_path / "out"
    export(arch, "syn_fric_0001", out)
    p = out / "界面场" / "syn_fric_0001.npz"
    files = CH.tar_files(arch / "syn_fric_0001.tar.xz")
    assert CH.diff_iface(p, files) == []
    z = np.load(p, allow_pickle=False)
    assert [str(s) for s in z["steps"]] == SY.STEPS4
    assert z["rel"].shape == (6, 4, 3) and z["c_CPRESS"].shape == (6, 4) and z["f_CNORMF_stem"].shape == (6, 4, 3)
    assert "c_COPEN_stem" not in z.files  # 归档里柄侧没有这个量
    assert z["tri"].shape == (4, 3) and sorted(set(z["tri"].ravel().tolist())) == [0, 1, 2, 3, 4, 5]
    assert z["collar"].tolist() == [False] * 5 + [True] and z["load_vec"].tolist() == [-700.5, 600.25, -2100.125]
    gap = -(z["interf"][:, None] + (z["rel"] * z["nrm"][:, None, :]).sum(2)) * 1e3
    assert np.array_equal(z["gap"], gap)
    assert np.array_equal(z["cforce"], z["f_CNORMF"].astype(np.float64) + z["f_CSHEARF"].astype(np.float64))


def test_interface_check_fails_when_one_value_is_off(arch, tmp_path):
    out = tmp_path / "out"
    export(arch, "syn_fric_0001", out)
    files = CH.tar_files(arch / "syn_fric_0001.tar.xz")
    z = dict(np.load(out / "界面场" / "syn_fric_0001.npz", allow_pickle=False))
    z["rel"] = z["rel"].copy()
    z["rel"][2, 1, 0] += 1e-9
    z["c_CSTATUS_stem"] = z["c_CSTATUS_stem"].copy()
    z["c_CSTATUS_stem"][4, 3] = 0.0
    np.savez(tmp_path / "off.npz", **z)
    bad = CH.diff_iface(tmp_path / "off.npz", files)
    assert len(bad) == 2 and "LOAD 第 2 对" in bad[0] and "LOAD2 CONTACT CSTATUS_stem" in bad[1]


def test_rows_off_the_interface_are_kept_not_dropped(tmp_path):
    """接触量的表里有一行不在任何节点对上：原样放进 extra，清单里写明行数。"""
    SY.write_archive(tmp_path / "arch", "syn_stray_0007", SY.job_files("fric", seed=7, stray_row=True))
    res = export(tmp_path / "arch", "syn_stray_0007", tmp_path / "out")
    z = np.load(tmp_path / "out" / "界面场" / "syn_stray_0007.npz", allow_pickle=False)
    assert z["extra__LOAD__CONTACT__CPRESS__label"].tolist() == [1]
    assert z["extra__LOAD__CONTACT__CPRESS__value"].tolist() == [[9.5]]
    assert res["inventory"]["iface"]["unmatched_rows"] == 1
    assert CH.diff_iface(tmp_path / "out" / "界面场" / "syn_stray_0007.npz", CH.tar_files(tmp_path / "arch" / "syn_stray_0007.tar.xz")) == []


def test_more_than_four_steps_are_all_exported(tmp_path):
    steps = ["RELEASE", "LOAD", "UNLOAD", "LOAD2", "UNLOAD2", "LOAD3"]
    SY.write_archive(tmp_path / "arch", "syn_cyc_0008", SY.job_files("fric", steps=steps, seed=8))
    res = export(tmp_path / "arch", "syn_cyc_0008", tmp_path / "out")
    z = np.load(tmp_path / "out" / "界面场" / "syn_cyc_0008.npz", allow_pickle=False)
    assert [str(s) for s in z["steps"]] == steps and z["rel"].shape == (6, 6, 3)
    g = K.read_global(tmp_path / "out" / "整体场" / "syn_cyc_0008.npz")
    assert {k[1] for k in g if isinstance(k, tuple) and k[2] == "U"} == set(steps)
    assert any("S 在这些步没有：LOAD、UNLOAD、LOAD2、UNLOAD2" in m for m in res["inventory"]["missing"])


def test_a_missing_contact_file_is_written_down_not_made_up(tmp_path):
    files = SY.job_files("fric", seed=9)
    del files["m_fric_csv/UNLOAD_CFORCE.csv"]
    SY.write_archive(tmp_path / "arch", "syn_gap_0009", files)
    res = export(tmp_path / "arch", "syn_gap_0009", tmp_path / "out")
    z = np.load(tmp_path / "out" / "界面场" / "syn_gap_0009.npz", allow_pickle=False)
    assert np.isnan(z["cforce"][:, 2]).all() and np.isfinite(z["cforce"][:, 1]).all()
    assert np.isnan(z["f_CNORMF"][:, 2]).all()
    assert "界面场缺：UNLOAD_CFORCE.csv" in res["inventory"]["missing"]
    assert any("CFORCE 在这些步没有：UNLOAD" in m for m in res["inventory"]["missing"])


def test_only_the_chosen_quantities_are_written(arch, tmp_path):
    out = tmp_path / "out"
    res = export(arch, "syn_fric_0001", out, quantities=["标签"])
    assert res["row"]["field_n_nodes"] == 6  # 由界面场算的那几列照样有
    assert (out / "标签" / "原始json" / "syn_fric_0001.json").exists()
    assert not (out / "界面场").exists() and not (out / "整体场").exists()
    raw = json.loads((out / "标签" / "原始json" / "syn_fric_0001.json").read_text(encoding="utf-8"))
    assert set(raw["json"]) == {"spec.json", "prep.json", "result.json", "solve.json"} and raw["text"]["prep.log"] == "READY\n"


def test_export_leaves_the_archive_untouched(arch, tmp_path):
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes()) for p in arch.iterdir()}
    for job in ("syn_fric_0001", "syn_bond_0002", "syn_fail_0003"):
        export(arch, job, tmp_path / "out")
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes()) for p in arch.iterdir()}
    assert before == after
