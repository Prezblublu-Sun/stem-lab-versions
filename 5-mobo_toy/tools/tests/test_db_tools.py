"""Tests for tools/db_export.py, tools/db_qa.py, tools/db_archive.py (no FE, no Linux, nothing outside a temp dir).

Run with the repo venv (pytest or plain python):
    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe -m pytest tools/tests/test_db_tools.py -q
    PYTHONUTF8=1 .venv-mobo/Scripts/python.exe tools/tests/test_db_tools.py
Temp dirs go under $DBTOOLS_TEST_TMP (default: the system temp dir).
The real end-to-end test on Linux job dirs is run by hand (reports of dev_D456 and D456fix, 2026-10-25 / 26).
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import lzma
import math
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import time
import types

import numpy as np

TOOLS = pathlib.Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import db_archive as DA  # noqa: E402
import db_export as DX  # noqa: E402
import db_qa as DQ  # noqa: E402

TMP = pathlib.Path(os.environ.get("DBTOOLS_TEST_TMP") or tempfile.gettempdir())
TMP.mkdir(parents=True, exist_ok=True)
# stdlib-only fake producers run on the BASE interpreter: a Windows venv python.exe is a launcher that spawns the real interpreter as
# a child, so killing the launcher would leave the producer (and its pipe handles) alive -- not what a real ssh.exe does
BASE_PY = getattr(sys, "_base_executable", None) or sys.executable


def _tmpdir(name: str) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"dbtools_{name}_", dir=TMP))
    return d


# ------------------------------------------------------------------------------------------------ numerics vs the pipeline
def test_rigid_fit_and_wquantile_match_pipeline():
    sys.path.insert(0, str(ROOT / "v2"))
    sys.path.insert(0, str(ROOT))
    import qoi
    import stability as ST
    rng = np.random.default_rng(1)
    X = rng.normal(size=(500, 3)) * 20
    R = rng.normal(size=(500, 3)) * 1e-2
    w = rng.uniform(0.1, 2, 500)
    for ww in (w, None):
        a = ST.rigid_fit(X, R, ww)
        b = DX.rigid_fit_np(X, R, ww)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and np.array_equal(a[2], b[2]) and a[3] == b[3]
    x = rng.lognormal(size=400)
    assert DX.wquantile_np(x, w[:400], 0.95) == qoi.wquantile(x, w[:400], 0.95)
    x[3] = np.nan
    ok = np.isfinite(x)
    assert DX.wquantile_np(x, w[:400], 0.95) == qoi.wquantile(x[ok], w[:400][ok], 0.95)


def test_foam_features_definition():
    """foam t = -canal_sdf over body nodes, area-weighted qoi.wquantile (corner check section 2.1 / corner_job.py fe.foam_t)."""
    sys.path.insert(0, str(ROOT))
    import qoi
    rng = np.random.default_rng(7)
    n = 800
    d = -rng.uniform(0.3, 6.0, n)
    w = rng.uniform(0.1, 1.0, n)
    body = rng.random(n) > 0.1
    ff = DX.foam_features(d, w, body)
    t = -d[body]
    assert ff["foam_p05"] == float(qoi.wquantile(t, w[body], 0.05))
    assert ff["foam_p50"] == float(qoi.wquantile(t, w[body], 0.5))
    assert ff["foam_lt1"] == float(w[body][t < 1.0].sum())


def test_design_key_rounding_and_split():
    d = {k: 0.1 * (i + 1) for i, k in enumerate(DX.DESIGN_VARS) if k != "h_cut"}
    k0 = DX.design_key(d, 16.0)
    assert len(k0) == 40
    d2 = {**d, "L": d["L"] + 2e-8}
    assert DX.design_key(d2, 16.0) == k0                     # below the 1e-6 rounding
    d3 = {**d, "L": d["L"] + 2e-6}
    assert DX.design_key(d3, 16.0) != k0
    dz = {**d, "tau_a": -1e-9}
    dz0 = {**d, "tau_a": 0.0}
    assert DX.design_key(dz, 16.0) == DX.design_key(dz0, 16.0)   # no "-0.000000"
    rng = np.random.default_rng(0)
    cnt = {"train": 0, "val": 0, "test": 0}
    for i in range(20000):
        b, s = DX.split_of(DX.sha1(str(rng.random())))
        assert 0 <= b < 100
        cnt[s] += 1
    assert abs(cnt["test"] / 20000 - 0.15) < 0.01 and abs(cnt["val"] / 20000 - 0.10) < 0.01


def test_unit_coords_bounds():
    lo = {k: v[0] for k, v in DX.BOUNDS["v1"].items()}
    hi = {k: v[1] for k, v in DX.BOUNDS["v1"].items()}
    u0 = DX.unit_coords({k: lo[k] for k in lo if k != "h_cut"}, lo["h_cut"])
    u1 = DX.unit_coords({k: hi[k] for k in hi if k != "h_cut"}, hi["h_cut"])
    assert all(abs(v) < 1e-12 for v in u0.values()) and all(abs(v - 1) < 1e-12 for v in u1.values())


def test_float_cells_round_trip():
    for v in (0.1, 1 / 3, 1e-300, -2.5e17, 6.222158271042304, float("nan")):
        s = DX.fmt_cell(v, "float")
        p = DQ.parse(s, "float")
        assert (p != p and v != v) or p == v
    assert DQ.parse(DX.fmt_cell(True, "bool"), "bool") is True
    assert DQ.parse(DX.fmt_cell([], "json"), "json") == []
    assert DX.fmt_cell(None, "float") == "" and DQ.parse("", "float") is None


def test_columns_diag_prefix_solver_steps_foam():
    names = set(DX.COLNAMES)
    for c in ("solver", "steps", "foam_thk_p05_mm", "foam_thk_p50_mm", "area_foam_lt1_mm2", "layer", "manifest_refs",
              "replicate_group_bond", "replicate_of_bond", "femur_geom_verified", "femur_geom_basis", "h_int_prep_mm", "intact_job_spec",
              "fld_err_foam_p05"):
        assert c in names, c
    knife = [c for c in names if "first_prox" in c or "bench_cx" in c]
    assert knife and all(c.startswith("diag_") for c in knife), knife
    assert DX.STAB_KEY_TO_COL["rot_first_prox_deg"] == "diag_rot_first_prox_deg"
    assert DX.STAB_KEY_TO_COL["bench_cx_rot_first_deg"] == "diag_bench_cx_rot_first_deg"
    assert DX.STAB_KEY_TO_COL["rot_first_deg"] == "rot_first_deg"
    assert "db_bd_" in DX.E_JOB_PREFIXES and not any(x.startswith("db_bo") for x in DX.E_JOB_PREFIXES)
    assert DX.DB_STAGE_RULES["db_bd"] == ("offset_variant", "stratum") and DX.DB_STAGE_RULES["db_bo"] == ("bond_partner", "stratum")


def test_csv_present_gz(tmp=None):
    d = _tmpdir("gz")
    f = d / "LOAD_CFORCE.csv"
    assert not DX.csv_present(f)
    (d / "LOAD_CFORCE.csv.gz").write_bytes(b"x")
    assert DX.csv_present(f)
    (d / "LOAD_CFORCE.csv.gz").unlink()
    f.write_text("node\n")
    assert DX.csv_present(f)


def test_femur_geom_key_equals_stage_db():
    """db rows and the D1 manifests must carry the same femur_geom_key (stage_db.femur_geom_key)."""
    sys.path.insert(0, str(ROOT / "v2"))
    sys.path.insert(0, str(ROOT))
    import stage_db as SD
    k = SD.femur_geom_key()
    geo = {r: DX.sha256_file(ROOT / f) for r, f in DX.FEMUR_GEOM_ROLES.items()}
    assert DX.femur_geom_key_of(geo) == k["key"]
    assert {r: v["sha256"] for r, v in k["files"].items()} == geo


# ------------------------------------------------------------------------------------------------ triangles
def _two_tets():
    """One C3D10 bone tet (0,1,2,3); interface = face (0,1,2) with its mid nodes."""
    P = {0: (0, 0, 0), 1: (1, 0, 0), 2: (0, 1, 0), 3: (0, 0, -1)}
    mids = {}
    lab = 10

    def mid(a, b):
        nonlocal lab
        k = tuple(sorted((a, b)))
        if k not in mids:
            mids[k] = lab
            P[lab] = tuple((np.array(P[a]) + np.array(P[b])) / 2)
            lab += 1
        return mids[k]
    c = [0, 1, 2, 3]
    conn = c + [mid(0, 1), mid(1, 2), mid(2, 0), mid(0, 3), mid(1, 3), mid(2, 3)]
    face_nodes = [0, 1, 2, mid(0, 1), mid(1, 2), mid(2, 0)]
    return np.array([conn]), np.array(face_nodes), P


def test_interface_triangles_area():
    conn, face, P = _two_tets()
    T = DX.interface_triangles(conn, face)
    assert T.shape == (4, 3)
    X = np.array([P[int(n)] for n in face], float)
    assert abs(DX.tri_area(X, T) - 0.5) < 1e-12
    assert set(np.unique(T)) == set(range(6))
    conn2 = np.concatenate([conn, conn[:, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]]])   # interior face (two bone tets): not interface
    assert DX.interface_triangles(conn2, face).shape == (0, 3)


# ------------------------------------------------------------------------------------------------ synthetic point cloud
def synthetic_shard(n: int = 300, seed: int = 0, collar: bool = False):
    rng = np.random.default_rng(seed)
    th = rng.uniform(0, 2 * np.pi, n)
    s = rng.uniform(0, 40, n)
    X = np.stack([8 * np.cos(th), 8 * np.sin(th), -s], 1)
    nrm = np.stack([np.cos(th), np.sin(th), np.zeros(n)], 1)
    area = rng.uniform(0.2, 0.6, n)
    interf = np.where(rng.random(n) < 0.8, 0.1, 0.0)
    om = np.radians([0.05, -0.12, 0.02])
    c = X.mean(0)
    rig = np.cross(om, X - c) + np.array([1e-3, -2e-3, 5e-3])
    rel = np.zeros((n, 4, 3))
    rel[:, 0] = -interf[:, None] * nrm * 0.98 + rng.normal(size=(n, 3)) * 1e-5
    rel[:, 1] = rel[:, 0] + rig + rng.normal(size=(n, 3)) * 1e-4
    rel[:, 2] = rel[:, 0] + 0.1 * rig
    rel[:, 3] = rel[:, 1] + rng.normal(size=(n, 3)) * 2e-4
    load = np.array([-782.1, 698.2, -2148.9])
    cf = np.zeros((n, 2, 3), np.float32)
    cf[:, 0] = load / n
    cf[:, 1] = load / n
    gap = np.stack([-(interf + (rel[:, i] * nrm).sum(1)) * 1e3 for i in range(4)], 1)
    col = np.zeros(n, bool)
    if collar:
        col[:10] = True
    d_canal = -rng.uniform(0.4, 5.0, n)
    arr = {"X": X, "nrm": nrm, "area": area, "interf": interf, "cortex": np.zeros(n, bool), "collar": col,
           "node_bone": np.arange(1, n + 1), "node_stem": np.arange(n + 1, 2 * n + 1), "rel": rel,
           "loc": X.astype(np.float32), "srt": X.astype(np.float32), "nloc": nrm.astype(np.float32),
           "d_canal": d_canal, "d_outer": np.ones(n, np.float32), "cpress": np.ones((n, 4), np.float32),
           "cstatus": np.full((n, 4), 2, np.float32), "copen": np.zeros((n, 4), np.float32), "gap": gap.astype(np.float32), "cforce": cf}
    meta = {"frame": np.stack([c, [0, 0, -1.0], [1.0, 0, 0], [0, 1.0, 0]]), "tri": np.array([[0, 1, 2], [2, 3, 4]], np.int32),
            "foam": DX.foam_features(d_canal, area, ~col)}
    return arr, meta, load


def _ref_values(chk: dict) -> dict:
    return {ref: chk[k] for k, ref in DX.REAGG_REF.items()}


def _shard_from(items):
    sb = DX.ShardBuilder("t", 99)

    class Sink:
        def __init__(self):
            self.m = {}

        def add(self, name, data):
            self.m[name] = data
    sk = Sink()
    for row, arr, meta, load in items:
        sb.add(row, arr, meta, load)
    log = {}
    sb.flush(sk, log)
    return sk.m, log


def test_reaggregate_recovers_and_flags():
    arr, meta, load = synthetic_shard()
    sh0 = {"off": np.array([0, len(arr["area"])]), **arr}
    chk = DX.reaggregate(sh0, 0)
    assert abs(chk["rot_first"] - np.degrees(np.linalg.norm(np.radians([0.05, -0.12, 0.02])))) < 0.01
    assert chk["foam_p05"] == meta["foam"]["foam_p05"] and chk["foam_lt1"] == meta["foam"]["foam_lt1"]
    row = {"job_id": "j1", "row_id": "j1", "export_errors": [], **_ref_values(chk)}
    bad = dict(row, job_id="j2", row_id="j2", export_errors=[], rot_first_deg=chk["rot_first"] * (1 + 1e-5))
    mem, log = _shard_from([(row, arr, meta, load), (bad, copy.deepcopy(arr), meta, load)])
    assert list(mem) == ["fields/iface_t_000.npz"] and log["shards"][0]["n_jobs"] == 2
    assert row["fld_err_rot_first"] == 0.0 and row["fld_err_foam_p50"] == 0.0 and not row["export_errors"], row["export_errors"]
    assert bad["fld_err_rot_first"] > 1e-6 and any("re-aggregation rot_first" in e for e in bad["export_errors"])
    sh = dict(np.load(io.BytesIO(mem["fields/iface_t_000.npz"]), allow_pickle=False))
    assert sh["off"].tolist() == [0, 300, 600] and sh["tri_off"].tolist() == [0, 2, 4] and str(sh["job_id"][1]) == "j2"
    assert sh["d_canal"].dtype == np.float64


# ------------------------------------------------------------------------------------------------ sinks / stream round trip
def test_tar_stream_round_trip_and_tamper():
    buf = io.BytesIO()
    sk = DX.TarSink(buf)
    sk.add("export/b0/rows.jsonl", b'{"a": 1}\n')
    sk.add("fields/iface_b0_000.npz", os.urandom(5000))
    sk.close({"batch": "b0"})
    buf.seek(0)
    got, man = {}, None
    with tarfile.open(fileobj=buf, mode="r|") as tf:
        for m in tf:
            assert DX._safe_member(m.name)
            data = tf.extractfile(m).read()
            if m.name == "STREAM_MANIFEST.json":
                man = json.loads(data)
            else:
                got[m.name] = {"sha256": DX.hashlib.sha256(data).hexdigest(), "size": len(data)}
    assert man and man["members"] == got
    assert not DX._safe_member("../evil") and not DX._safe_member("/abs/x") and not DX._safe_member("other/x")
    d = _tmpdir("dirsink")
    ds = DX.DirSink(d)
    ds.add("export/b1/rows.jsonl", b"x\n")
    ds.close({"batch": "b1"})
    assert (d / "export" / "b1" / "EMIT_OK.json").exists()
    (d / "export" / "b1" / "rows.jsonl").write_bytes(b"y\n")
    assert DX.verify_members(d, ds.manifest)                          # tampering detected


# ------------------------------------------------------------------------------------------------ pull: failure mid-stream
_PRODUCER = r"""
import io, sys, tarfile, time
out = sys.stdout.buffer
tf = tarfile.open(fileobj=out, mode="w|")
data = b"\0" * (64 << 20)                       # 64 MB member: far more than a pipe buffer
ti = tarfile.TarInfo("fields/iface_bx_000.npz"); ti.size = len(data)
tf.addfile(ti, io.BytesIO(data))
ti = tarfile.TarInfo("export/bx/rows.jsonl"); ti.size = 3
tf.addfile(ti, io.BytesIO(b"{}\n"))
tf.close()
time.sleep(600)
"""


def test_receive_stream_failure_kills_producer_and_quarantines():
    """A disk-gate SystemExit at the first member must not hang on the producer: stdout closed, producer killed, PULL_BAD.json
    written, export/<batch> moved to <batch>.BAD with the received shard, the exception re-raised (review D456 issue 3)."""
    out = _tmpdir("pullfail")
    (out / "export" / "bx").mkdir(parents=True)
    errlog = out / "export" / "bx" / "remote_stderr.log"
    t0 = time.time()
    raised = None
    try:
        DX.receive_stream([BASE_PY, "-c", _PRODUCER], subprocess.DEVNULL, out, "bx", 1e12, errlog)
    except SystemExit as e:
        raised = e
    dt = time.time() - t0
    assert raised is not None and "DISK GATE" in str(raised)
    assert dt < 60, dt
    assert not (out / "export" / "bx").exists() and (out / "export" / "bx.BAD" / "PULL_BAD.json").exists()
    rep = json.loads((out / "export" / "bx.BAD" / "PULL_BAD.json").read_text())
    assert "DISK GATE" in rep["exception"] and "producer rc" in rep["abort"]
    # the same batch name again: a second failure goes to .BAD.2, and finalize / QA ignore dotted dirs
    (out / "export" / "bx").mkdir()
    try:
        DX.receive_stream([BASE_PY, "-c", _PRODUCER], subprocess.DEVNULL, out, "bx", 1e12, out / "export" / "bx" / "e.log")
    except SystemExit:
        pass
    assert (out / "export" / "bx.BAD.2").exists()
    use, skip = DX.batch_dirs(out)
    assert not use and {p.name for p in skip} == {"bx.BAD", "bx.BAD.2"}


def test_receive_stream_ok_and_quarantine_moves_shards():
    out = _tmpdir("pullok")
    (out / "export" / "by").mkdir(parents=True)
    prod = _PRODUCER.replace("64 << 20", "1 << 10").replace("time.sleep(600)", "").replace("bx", "by")
    res = DX.receive_stream([BASE_PY, "-c", prod], subprocess.DEVNULL, out, "by", 0.0, out / "export" / "by" / "e.log")
    assert res["rc"] == 0 and set(res["got"]) == {"fields/iface_by_000.npz", "export/by/rows.jsonl"} and res["manifest"] is None
    where = DX.quarantine_batch(out, "by", {"problems": ["no manifest"]}, res["got"], [])
    assert where.name == "by.BAD" and (where / "fields" / "iface_by_000.npz").exists() and not (out / "fields" / "iface_by_000.npz").exists()


def test_frozen_list_and_live_select_refused():
    out = _tmpdir("frozen")
    names = ["sb13_init_aaaa1111", "sb11_init_bbbb2222"]
    body = ("\n".join(names) + "\n").encode()
    (out / "jobs.txt").write_bytes(body)
    (out / "jobs_inventory.json").write_text(json.dumps({"jobs": names, "jobs_txt_sha256": hashlib.sha256(body).hexdigest()}))
    got, _ = DX.read_frozen_list(out, str(out / "jobs.txt"))
    assert got == names
    (out / "jobs.txt").write_bytes(body + b"extra\n")
    try:
        DX.read_frozen_list(out, str(out / "jobs.txt"))
        raise AssertionError("a changed jobs.txt must be refused")
    except SystemExit as e:
        assert "not the frozen list" in str(e)
    a = types.SimpleNamespace(out=str(out), list_only=False, batch="b0", jobs_file=None, jobs=None, select_3406=True, offset=0, limit=0)
    try:
        DX.cmd_pull(a)
        raise AssertionError("a live --select-3406 pull must be refused")
    except SystemExit as e:
        assert "refused" in str(e)


# ------------------------------------------------------------------------------------------------ finalize logic
def _row(job, source, selection, dk, **kw):
    r = {c: None for c in DX.COLNAMES}
    r.update(job_id=job, row_id=job, source=source, selection=selection, design_key=dk, realization_key="rk_" + dk, cond_key="c",
             fidelity="h2", has_fric_model=True, has_bond_model=False, status="DONE", alpha=40.0, bounds_version="v1",
             femur_id=DX.FEMUR_ID, load_R_N=2391.0, delta_mm=0.1, export_errors=[], t_done_utc="2026-10-24T00:00:00Z", layer="S0")
    r.update(kw)
    return r


def test_finalize_rows_E_unbiased_replicates_provenance():
    rows = [_row("sb13_init_a", "sobol_init_p13", "iid", "d1"), _row("sb11_init_a", "sobol_init_p11", "iid", "d1", cond_key="c025"),
            _row("sb13_a40_x", "bo_p13", "adaptive", "d2"), _row("v3406_x", "v3406_ref", "stratum", "d2", cond_key="c2"),
            _row("db_sf_s1_aa", "sf", "iid", "d2", cond_key="c3"), _row("db_sf_s2_bb", "sf", "iid", "d3"),
            _row("db_cd_x_cc", None, None, "d4", layer=None), _row("dup1", "sobol_init_p13", "iid", "d5", t_done_utc="2026-10-24T01:00:00Z"),
            _row("dup2", "sobol_init_p13", "iid", "d5", t_done_utc="2026-10-24T00:30:00Z"),
            _row("db_crt_x_dd", "corner_test", "corner_test", "d6"), _row("sb13_a99_y", "bo_p13", "adaptive", "d7", status="FAILED")]
    E_scan = {"d2": ["sb13_a40_x"], "d7": ["sb13_a99_y"]}
    out, errs, info = DX.finalize_rows(copy.deepcopy(rows), E_scan, {})
    R = {r["job_id"]: r for r in out}
    assert any("db_cd_x_cc" in e for e in errs)                      # db_cd row without provenance -> error, loud
    assert R["sb13_init_a"]["unbiased"] and R["sb11_init_a"]["unbiased"]
    assert R["sb13_a40_x"]["in_E"] and not R["sb13_a40_x"]["unbiased"]
    assert R["v3406_x"]["in_E"] and not R["v3406_x"]["unbiased"]      # anchor on an E design
    assert R["db_sf_s1_aa"]["sf_bo_overlap"] and not R["db_sf_s1_aa"]["unbiased"] and R["db_sf_s1_aa"]["a3_test_only"]
    assert R["db_sf_s2_bb"]["unbiased"] and not R["db_sf_s2_bb"]["in_E"]
    assert R["db_crt_x_dd"]["in_E"] and R["db_crt_x_dd"]["test_corner"]
    assert R["sb13_a99_y"]["in_E"]                                    # failed BO designs are still optimisation-selected
    assert R["dup2"]["replicate_group"] == R["dup1"]["replicate_group"] and R["dup1"]["replicate_of"] == "dup2" \
        and R["dup2"]["replicate_of"] is None
    assert R["sb13_init_a"]["replicate_group"] is None                  # different condition from sb11_init_a
    assert R["sb13_a99_y"]["replicate_group"] is None                   # FAILED rows are never replicates
    assert all(r["split"] == DX.split_of(r["design_key"])[1] for r in out)
    prov = {"db_cd_x_cc": {"source": "cond_random", "selection": "iid", "layer": "CD-1", "_file": "p.csv"}}
    out2, errs2, _ = DX.finalize_rows(copy.deepcopy(rows), E_scan, prov)
    R2 = {r["job_id"]: r for r in out2}
    assert not errs2, errs2
    assert R2["db_cd_x_cc"]["unbiased"] and R2["db_cd_x_cc"]["provenance"] == "p.csv" and R2["db_cd_x_cc"]["layer"] == "CD-1"
    prov_al = {"db_al_1_ee": {"source": "al_1", "selection": "adaptive", "layer": "AL-1", "_file": "p.csv"}}
    rows_al = rows[:2] + [_row("db_al_1_ee", None, None, "d1", layer=None)]
    out3, _, _ = DX.finalize_rows(copy.deepcopy(rows_al), {}, prov_al)
    R3 = {r["job_id"]: r for r in out3}
    assert R3["sb13_init_a"]["in_E"] and not R3["sb13_init_a"]["unbiased"]   # an AL optimisation pick on the same design excludes it


def test_replicates_friction_and_bonded_separately():
    """Plan 2.3: a bonded job and a friction-only job with the same geometry / condition / fidelity ARE friction replicates
    (review D456 issue 1: e.g. sb13_init_05165065 + v3406_dx_c742b510_d0.1); bonded replicates are grouped separately."""
    rows = [_row("sb13_init_05165065", "sobol_init_p13", "iid", "dA", has_bond_model=True, intact_job="ref1"),
            _row("v3406_dx_c742b510_d0.1_a539b815", "v3406_ref", "stratum", "dA", t_done_utc="2026-10-24T02:00:00Z"),
            _row("bond1", "d13", "stratum", "dB", has_fric_model=False, has_bond_model=True, intact_job="ref1"),
            _row("bond2", "d13", "stratum", "dB", has_fric_model=False, has_bond_model=True, intact_job="ref1",
                 t_done_utc="2026-10-23T00:00:00Z"),
            _row("bond3", "d13", "stratum", "dB", has_fric_model=False, has_bond_model=True, intact_job="ref_h194")]
    out, errs, info = DX.finalize_rows(copy.deepcopy(rows), {}, {})
    R = {r["job_id"]: r for r in out}
    a, b = R["sb13_init_05165065"], R["v3406_dx_c742b510_d0.1_a539b815"]
    assert a["replicate_group"] and a["replicate_group"] == b["replicate_group"]
    assert a["replicate_of"] is None and b["replicate_of"] == "sb13_init_05165065"
    assert a["replicate_group_bond"] is None and b["replicate_group_bond"] is None
    assert R["bond1"]["replicate_group"] is None and R["bond1"]["replicate_group_bond"] == R["bond2"]["replicate_group_bond"]
    assert R["bond1"]["replicate_of_bond"] == "bond2" and R["bond2"]["replicate_of_bond"] is None
    assert R["bond3"]["replicate_group_bond"] is None                   # other reference -> not a bonded replicate
    assert len(info["replicate_groups"]["fric"]) == 1 and len(info["replicate_groups"]["bond"]) == 1


# ------------------------------------------------------------------------------------------------ provenance (D1 manifest, seed)
def _results_dir():
    d = _tmpdir("results")
    (d / "neckopt_p13.json").write_text(json.dumps({"records": [
        {"job_id": "sb13_a105_91e458e3", "pool_idx": 2292, "round": 55, "rot_first_deg": 0.05, "bonded": False},
        {"job_id": "sb13_init_2943f28a", "pool_idx": 12, "round": 0, "rot_first_deg": 0.24, "bonded": False}], "pending": {}}))
    man = {"batch": "b1", "code_hash": "6d7af243d0", "femur_geom_key": {"key": "k" * 16, "files": {}},
           "femur_model_version": "3406R_v1_hollowcore", "hollow_core": True,
           "rows": {"REF_h1.94": {"layer": "REF", "source": "intact_ref", "selection": "reference", "intact_job": None, "pool_idx": None,
                                  "femur_model_version": "3406R_v1_hollowcore", "hollow_core": True, "source_job": "sb_intact_h2_9c9d7fb5",
                                  "id": "db_ref_intact_h1.94_11111111", "dedup": "new"},
                    "NZ1_h1.94_B": {"layer": "NZ-1", "source": "noise", "selection": "stratum", "intact_job": "db_ref_intact_h1.94_11111111",
                                    "pool_idx": 77, "femur_model_version": "3406R_v1_hollowcore", "hollow_core": True,
                                    "source_job": "sb13_a78_b0f465da", "id": "db_nz_p13_a78_h1.94_22222222", "dedup": "new"},
                    "BD_h2_init29": {"layer": "BD h2.0", "source": "bond_partner", "selection": "stratum", "intact_job": "sb_intact_h2_9c9d7fb5",
                                     "pool_idx": 12, "femur_model_version": "3406R_v1_hollowcore", "hollow_core": True,
                                     "source_job": "sb13_init_2943f28a", "id": "sb13_init_2943f28a", "dedup": "existing"}}}
    (d / "db_manifest_b1.json").write_text(json.dumps(man))
    seed_spec = {"stage": "db_cd", "tag": "A_d0.025", "kind": "variant", "fric_only": True, "db_layer": "CD-0", "delta": 0.025,
                 "femur_model_version": "3406R_v1_hollowcore", "db_cond": "delta0.025", "source_job": "sb13_a105_91e458e3",
                 "femur_id": "sawbone3406"}
    (d / "db_seed_CD0.json").write_text(json.dumps({"batch": "CD-0 seed", "code_hash": "6d7af243d0",
                                                    "jobs": {"CD0_delta0.025_A": "db_cd_A_d0.025_62673584"},
                                                    "specs": {"CD0_delta0.025_A": seed_spec}}))
    return d, seed_spec


def _prow(job, **kw):
    r = {c: None for c in DX.COLNAMES}
    r.update(job_id=job, femur_model_version="3406R_v1_hollowcore", hollow_core=True, **kw)
    return r


def test_db_provenance_manifest_and_seed():
    d, seed_spec = _results_dir()
    files = {}
    recs = DX.load_records(d, files)
    prov, probs = DX.load_db_provenance(d, files, recs)
    assert not probs and set(files) == {"neckopt_p13.json", "db_manifest_b1.json", "db_seed_CD0.json"}
    assert recs["sb13_a105_91e458e3"]["pool_idx"] == 2292
    # seed row: layer CD-0, source cond_anchor, selection stratum, pool_idx of the source job's BO record
    spec = {**seed_spec, "created": "2026-10-25 23:02:52"}
    row = _prow("db_cd_A_d0.025_62673584", **DX.classify("db_cd_A_d0.025_62673584", spec, None))
    errs = []
    DX.apply_db_provenance(row, spec, prov.get(row["job_id"]), "k" * 16, errs)
    assert not errs, errs
    assert (row["layer"], row["source"], row["selection"], row["pool_idx"], row["provenance"]) == \
        ("CD-0", "cond_anchor", "stratum", 2292, "db_seed_CD0.json")
    # a seed row whose spec.json differs from the recorded spec -> error
    errs = []
    DX.apply_db_provenance(_prow("db_cd_A_d0.025_62673584"), {**spec, "delta": 0.05}, prov["db_cd_A_d0.025_62673584"], "k" * 16, errs)
    assert any("differs from the spec recorded" in e for e in errs)
    # manifest REF row: selection reference -> stratum; stage rule (db_ref -> intact_ref) agrees
    rs = {"stage": "db_ref", "kind": "intact", "h_int": 1.94}
    row = _prow("db_ref_intact_h1.94_11111111", **DX.classify("db_ref_intact_h1.94_11111111", rs, None))
    errs = []
    DX.apply_db_provenance(row, rs, prov.get(row["job_id"]), "k" * 16, errs)
    assert not errs and (row["layer"], row["source"], row["selection"]) == ("REF", "intact_ref", "stratum")
    assert "selection reference" in row["source_detail"]
    assert row["source_job"] == "sb_intact_h2_9c9d7fb5"            # stage_db specs carry no source_job: taken from the manifest
    # NZ row: intact_job mismatch and femur key mismatch are errors
    ns = {"stage": "db_nz", "kind": "variant", "intact_job": "sb_intact_h2_9c9d7fb5"}
    row = _prow("db_nz_p13_a78_h1.94_22222222", **DX.classify("db_nz_p13_a78_h1.94_22222222", ns, None))
    errs = []
    DX.apply_db_provenance(row, ns, prov.get(row["job_id"]), "other_key_000000", errs)
    assert any("intact_job" in e for e in errs) and any("femur_geom_key" in e for e in errs)
    # an existing (non-db) job adopted by D1 dedup keeps its own classification; only manifest_refs is set
    s0 = {"stage": "sb13", "kind": "design"}
    row = _prow("sb13_init_2943f28a", **DX.classify("sb13_init_2943f28a", s0, recs["sb13_init_2943f28a"]))
    errs = []
    DX.apply_db_provenance(row, s0, prov.get(row["job_id"]), "k" * 16, errs)
    assert not errs and row["layer"] == "S0" and row["source"] == "sobol_init_p13" and row["manifest_refs"] == ["db_manifest_b1.json:BD_h2_init29"]
    # a db_* job nobody recorded -> error
    errs = []
    row = _prow("db_cd_zz_00000000", **DX.classify("db_cd_zz_00000000", {"stage": "db_cd"}, None))
    DX.apply_db_provenance(row, {"stage": "db_cd"}, None, "k" * 16, errs)
    assert errs and "no entry" in errs[0] and row["layer"] is None


def test_db_provenance_adopted_by_later_batch():
    """A db_* row adopted by a later batch keeps the submitting batch's provenance, whatever order the manifests sort in."""
    base = {"intact_job": "sb_intact_h2_9c9d7fb5", "femur_model_version": "3406R_v1_hollowcore", "condition_id": "c", "source_job": "s"}
    sub = {**base, "file": "db_manifest_b7m.json", "key": "AL3M_01_sts3839", "layer": "AL-3m sts", "source": "al_adaptive",
           "selection_raw": "adaptive", "pool_idx": 5, "dedup": "new", "manifest_femur_geom_key": "k" * 16}
    ado = {**base, "file": "db_manifest_b11.json", "key": "CD2_F3839_al3m_01", "layer": "CD-2", "source": "cond_anchor",
           "selection_raw": "stratum", "pool_idx": None, "dedup": "existing", "manifest_femur_geom_key": "k" * 16}
    spec = {"stage": "db_al", "kind": "variant", "intact_job": "sb_intact_h2_9c9d7fb5"}
    for ents in ([sub, ado], [ado, sub]):
        row, errs = _prow("db_al_al3m_01_F3839_c0c3bcd2", **DX.classify("db_al_al3m_01_F3839_c0c3bcd2", spec, None)), []
        DX.apply_db_provenance(row, spec, ents, "k" * 16, errs)
        assert not errs, errs
        assert (row["layer"], row["source"], row["selection"], row["pool_idx"], row["provenance"]) == ("AL-3m sts", "al_adaptive", "adaptive", 5, "db_manifest_b7m.json")
        assert row["manifest_refs"] == ["db_manifest_b11.json:CD2_F3839_al3m_01", "db_manifest_b7m.json:AL3M_01_sts3839"]
    # an adopter that disagrees on the physics is still an error
    row, errs = _prow("db_al_al3m_01_F3839_c0c3bcd2", **DX.classify("db_al_al3m_01_F3839_c0c3bcd2", spec, None)), []
    DX.apply_db_provenance(row, spec, [sub, {**ado, "intact_job": "other"}], "k" * 16, errs)
    assert any("provenance entries disagree" in e and "intact_job" in e for e in errs), errs
    # two submitters that disagree, and two adopters with no submitter, are still errors
    row, errs = _prow("db_al_al3m_01_F3839_c0c3bcd2", **DX.classify("db_al_al3m_01_F3839_c0c3bcd2", spec, None)), []
    DX.apply_db_provenance(row, spec, [sub, {**sub, "key": "other", "layer": "AL-9"}], "k" * 16, errs)
    assert any("provenance entries disagree" in e and "layer" in e for e in errs), errs
    row, errs = _prow("db_al_al3m_01_F3839_c0c3bcd2", **DX.classify("db_al_al3m_01_F3839_c0c3bcd2", spec, None)), []
    DX.apply_db_provenance(row, spec, [ado, {**ado, "key": "other", "layer": "AL-9"}], "k" * 16, errs)
    assert any("provenance entries disagree" in e and "layer" in e for e in errs), errs


def test_manifest_contract_with_stage_db():
    """Contract: rows written by the CURRENT v2/stage_db._man_row carry every field db_export reads; a seed job adopted by a
    manifest row (stage_db SEEDS) yields two agreeing provenance entries."""
    sys.path.insert(0, str(ROOT / "v2"))
    sys.path.insert(0, str(ROOT))
    import stage_db as SD

    class R(dict):
        def __missing__(self, k):
            return None
    r = R(key="CD0_d0.025_A", layer="CD-0", stage="db_cd", source="cond_anchor", selection="stratum", design_code="A",
          source_job="sb13_a105_91e458e3", condition_id="d0.025|stair|h2|slip0.00025", bonded=False, model_set="fric",
          intact_job=None, femur_model_version=SD.FEMUR_MODEL_VERSION, hollow_core=SD.HOLLOW_CORE, pool_idx=2292,
          expected_id="db_cd_A_d0.025_62673584", id="db_cd_A_d0.025_62673584", dedup="existing")
    row = SD._man_row(r)
    for k in ("layer", "source", "selection", "pool_idx", "intact_job", "femur_model_version", "hollow_core", "source_job", "id", "dedup"):
        assert k in row, k
    d, seed_spec = _results_dir()
    man = json.loads((d / "db_manifest_b1.json").read_text())
    man["rows"] = {r["key"]: row}
    (d / "db_manifest_b1.json").write_text(json.dumps(man, default=str))
    files = {}
    recs = DX.load_records(d, files)
    prov, probs = DX.load_db_provenance(d, files, recs)
    ents = prov["db_cd_A_d0.025_62673584"]
    assert not probs and {e["kind"] for e in ents} == {"manifest", "seed"}
    spec = {**seed_spec, "created": "x"}
    out = _prow("db_cd_A_d0.025_62673584", **DX.classify("db_cd_A_d0.025_62673584", spec, None))
    errs = []
    DX.apply_db_provenance(out, spec, ents, "k" * 16, errs)
    assert not errs, errs
    assert out["layer"] == "CD-0" and out["pool_idx"] == 2292 and len(out["manifest_refs"]) == 2


def test_classify_acq_name_never_guessed():
    c = DX.classify("sb13_a40_x", {"stage": "sb13", "kind": "design"}, None)
    assert c["source"] == "bo_p13" and c["acq_name"] is None and c["pool_idx"] is None
    c = DX.classify("sb13_a40_x", {"stage": "sb13", "kind": "design"}, {"phase": 13, "pool_idx": 5, "round": 3})
    assert c["acq_name"] == "qLogNEHVI" and c["pool_idx"] == 5 and c["acq_round"] == 3 and c["layer"] == "S0"


# ------------------------------------------------------------------------------------------------ femur registry
def _ctx(batch, key, m, T, prep_host=True):
    return {"batch": batch, "prep_host": prep_host, "femur_geom_key": key, "femur_geom_mtime_max_utc": m, "export_time_utc": T,
            "femur_geom_files_sha256": {"femur_3406.py": "a"}}


def test_femur_registry_binds_key_to_job_time():
    rows = [_row("j1", "x", "iid", "d1", has_prep=True, femur_geom_key="K1", femur_geom_verified=True,
                 femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-24T01:00:00Z"),
            _row("j2", "x", "iid", "d2", has_prep=True, femur_geom_key="K1", femur_geom_verified=True,
                 femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-25T01:00:00Z")]
    reg, errs, info = DX.apply_femur_registry(rows, [_ctx("b0", "K1", "2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z")], None, "v0.1")
    ent = reg["femurs"][DX.FEMUR_ID]
    assert not errs and info[DX.FEMUR_ID]["action"] == "register" and ent["femur_geom_key"] == "K1"
    assert ent["windows"] == [["2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z"]]
    assert ent["first_prep_utc"] == "2026-10-24T01:00:00Z" and ent["last_prep_utc"] == "2026-10-25T01:00:00Z"
    # Windows re-export (not the prep host): rows unverified at emit, bound through the registry window
    rw = [dict(r, femur_geom_verified=False, femur_geom_basis="") for r in rows]
    rw.append(_row("j3", "x", "iid", "d3", has_prep=True, femur_geom_key="K1", femur_geom_verified=False, t_prep_utc="2026-10-27T00:00:00Z"))
    reg2, errs2, _ = DX.apply_femur_registry(rw, [_ctx("w0", "K1", "2026-10-26T10:00:00Z", "2026-10-26T11:00:00Z", prep_host=False)],
                                             reg, "v0.1w")
    assert rw[0]["femur_geom_verified"] is True and rw[0]["femur_geom_basis"] == "registry"
    assert rw[2]["femur_geom_verified"] is False and errs2 and "j3" in errs2[0]        # prepped after every verified window
    # a different key under the same femur_id: refused, registry unchanged
    rk = [dict(rows[0], femur_geom_key="K2")]
    reg3, errs3, _ = DX.apply_femur_registry(rk, [_ctx("b1", "K2", "2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z")], reg, "v0.2")
    assert errs3 and "new femur_id" in errs3[0] and reg3["femurs"][DX.FEMUR_ID]["femur_geom_key"] == "K1"
    # not registered and only non-prep-host batches: cannot bind
    _, errs4, _ = DX.apply_femur_registry(rw[:1], [_ctx("w0", "K1", "x", "y", prep_host=False)], None, "v")
    assert errs4 and "cannot bind" in errs4[0]
    # the same files seen later by another Linux batch extend the window
    reg5, errs5, _ = DX.apply_femur_registry(rows, [_ctx("b2", "K1", "2026-10-23T23:40:47Z", "2026-10-30T00:00:00Z")], reg, "v0.2")
    assert not errs5 and reg5["femurs"][DX.FEMUR_ID]["windows"] == [["2026-10-23T23:40:47Z", "2026-10-30T00:00:00Z"]]


def test_solve_evidence_provenance():
    """finalize --provenance may name the solver of a DONE job whose solve.json was overwritten after the solve (with evidence)."""
    err = DX.SOLVER_ERR + " (no 'solver' key and no *.odb in odb_meta)"
    r = _row("sb11_init_x", "sobol_init_p11", "iid", "d1", solver=None, solve_wall_s_fric=None, export_errors=[err, "other"])
    pv = {"solver": "abaqus", "solve_wall_s_fric": "1877", "solver_evidence": "worker.log 04:16:27 m_fric OK 1877 s", "_file": "ev.json"}
    rows, errs, _ = DX.finalize_rows([r], {}, {"sb11_init_x": pv})
    assert not [e for e in errs if "sb11_init_x" in e and "solver" in e], errs
    assert r["solver"] == "abaqus" and r["solve_wall_s_fric"] == 1877.0 and r["export_errors"] == ["other"] and r["export_status"] == "error"
    r1 = _row("sb11_init_w", "sobol_init_p11", "iid", "d1", solver=None, export_errors=[err], export_status="error")
    DX.finalize_rows([r1], {}, {"sb11_init_w": dict(pv)})
    assert r1["export_errors"] == [] and r1["export_status"] == "ok"
    assert r["solver_basis"].startswith("provenance ev.json: worker.log") and r["provenance"] == "rule"   # selection provenance unchanged
    r2 = _row("sb11_init_y", "sobol_init_p11", "iid", "d1", solver=None, export_errors=[err])
    _, errs2, _ = DX.finalize_rows([r2], {}, {"sb11_init_y": {"solver": "abaqus", "_file": "ev.json"}})
    assert any("without solver_evidence" in e for e in errs2) and r2["solver"] is None and r2["export_errors"] == [err]
    r3 = _row("sb11_init_z", "sobol_init_p11", "iid", "d1", solver="abaqus", solve_wall_s_fric=1818.98)
    _, errs3, _ = DX.finalize_rows([r3], {}, {"sb11_init_z": {"solver": "calculix", "solve_wall_s_fric": "1818", "solver_evidence": "x",
                                                             "_file": "ev.json"}})
    assert any("solver 'calculix' != exported 'abaqus'" in e for e in errs3) and not any("solve_wall_s_fric" in e for e in errs3)


def test_finalize_writes_registry_only_when_clean():
    """The db-level femur registry is updated only by a finalize with no errors and no rows with export errors (not even
    under --allow-errors); the version dir always gets its own copy. finalize --db-root has no default."""
    rows = [_row("j1", "x", "iid", "d1", has_prep=True, femur_geom_key="K1", femur_geom_verified=True,
                 femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-24T01:00:00Z")]
    ctxs = [dict(_ctx("b0", "K1", "2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z"), queue_complete=True)]
    einfo = {"E_jobs": {}, "n_E": 0, "replicate_groups": {"fric": [], "bond": []}}
    orig = (DX._load_rows, DX.finalize_rows)
    try:
        for bad, allow, want in ((True, True, False), (False, False, True)):
            rr = [dict(r, export_errors=(["boom"] if bad else [])) for r in rows]
            DX._load_rows = lambda out, rr=rr: ([dict(r) for r in rr], {}, {}, [dict(c) for c in ctxs])
            DX.finalize_rows = lambda rows_, E, prov: (rows_, [], einfo)
            root, out = _tmpdir("finreg_root"), _tmpdir("finreg_out")
            (out / "export").mkdir()
            rc = DX.finalize(out, str(root), None, allow)
            man = json.loads((out / "manifest.json").read_text())
            assert (root / "femur_registry.json").exists() is want and man["femur_registry"]["updated"] is want, (bad, rc, man["femur_registry"])
            assert (out / "femur_registry.json").exists() and rc == (0 if allow or not bad else 3)
            assert bad == any("NOT updated" in w for w in man["finalize_warnings"])
    finally:
        DX._load_rows, DX.finalize_rows = orig
    for argv in (["finalize", "--out", "x"], ["pull", "--jobs", "a", "--out", "x"]):
        try:
            DX.main(argv)
            raise AssertionError(f"{argv}: accepted without --db-root")
        except SystemExit as e:
            assert e.code == 2, argv


# ------------------------------------------------------------------------------------------------ write guard (subprocess: hooks cannot be removed)
def test_write_guard_blocks_and_reports():
    d = _tmpdir("guard")
    ok_dir = d / "ok"
    ok_dir.mkdir()
    code = f"""
import sys, os, json, pathlib
sys.path.insert(0, {str(TOOLS)!r})
import db_export as DX
DX.install_guard([{str(ok_dir)!r}])
res = {{}}
pathlib.Path({str(ok_dir / 'a.txt')!r}).write_text('x'); res['inside'] = 'ok'
for nm, fn in [('outside_write', lambda: open({str(d / 'b.txt')!r}, 'w').write('y')),
               ('outside_mkdir', lambda: os.mkdir({str(d / 'newdir')!r})),
               ('remove', lambda: os.remove({str(ok_dir / 'a.txt')!r}) if False else os.remove({str(d / 'ok' / 'a.txt')!r} + '_no')),
               ('subprocess', lambda: __import__('subprocess').run(['echo', 'hi']))]:
    try:
        fn(); res[nm] = 'allowed'
    except PermissionError:
        res[nm] = 'blocked'
    except FileNotFoundError:
        res[nm] = 'notfound'
open({str(d / 'c.txt')!r}, 'rb') if os.path.exists({str(d / 'c.txt')!r}) else None
res['read_existing_dir_mkdir'] = 'ok'
os.makedirs({str(ok_dir)!r}, exist_ok=True)
res['blocked'] = DX._GUARD['blocked']
print(json.dumps(res))
"""
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert res["inside"] == "ok" and res["outside_write"] == "blocked" and res["outside_mkdir"] == "blocked"
    assert res["subprocess"] == "blocked" and res["remove"] == "notfound"   # inside the allowed dir: not blocked
    assert not (d / "b.txt").exists() and not (d / "newdir").exists()
    assert len(res["blocked"]) == 3


# ------------------------------------------------------------------------------------------------ synthetic DB through db_qa
def _fill_required(r: dict):
    for name, typ, unit, lo, hi, req, src, desc in DX.COLUMNS:
        if r.get(name) is not None or req in ("optional", "reserved", "intact"):
            continue
        if req == "bond" and not r.get("has_bond_model"):
            continue
        if typ == "float":
            r[name] = float(lo) if lo is not None else 0.0
        elif typ == "int":
            r[name] = int(lo) if lo is not None else 0
        elif typ == "bool":
            r[name] = True
        elif typ == "json":
            r[name] = []
        else:
            r[name] = "x"


def build_synthetic_db(root: pathlib.Path):
    arr, meta, load = synthetic_shard()
    sh0 = {"off": np.array([0, len(arr["area"])]), **arr}
    chk = DX.reaggregate(sh0, 0)
    d = {k: 0.5 for k in DX.DESIGN_VARS if k != "h_cut"}
    dk = DX.design_key(d, 20.0)
    base = dict(status="DONE", kind="design", stage="sb13", tag="init", has_prep=True, has_fric_model=True, has_bond_model=False,
                export_status="ok", export_errors=[], femur_id=DX.FEMUR_ID, femur_model_version="3406R_v1_hollowcore",
                femur_geom_key="g" * 16, femur_geom_verified=True, femur_geom_basis="files_older_than_prep",
                femur_pose_match=True, femur_pose_dev_mm=0.0, code_hash=DX.EXPECTED_CODE_HASH,
                code_hash_now=DX.EXPECTED_CODE_HASH, code_hash_source="prep.json", job_id_matches_code=True, aux_code_md5="m" * 32,
                design_key=dk, realization_key="r1", cond_key="c1", fidelity="h2", L=30.0, alpha=40.0, h_cut=20.0, m=0.8,
                bounds_version="v1", n_pairs_cortex=0, h_int_mm=2.0, h_int_prep_mm=2.0, load_R_N=float(np.linalg.norm(load)),
                load_vec_N=load.tolist(), delta_spec_mm=0.1, delta_mm=0.1, cons_delta=True, cons_load=True, cons_h_int=True,
                spec_in_result_match=True, iface_force_err_load=1e-8, iface_force_err_load2=1e-8, tri_area_ratio=1.0,
                field_n_nodes=len(arr["area"]), field_n_tri=len(meta["tri"]), solver="abaqus",
                steps=["PRESSFIT", "RELEASE", "LOAD", "UNLOAD", "LOAD2"], layer="S0", provenance="rule",
                source="sobol_init_p13", selection="iid", in_family_phases=[13, 14], fail_level=None,
                t_prep_utc="2026-10-24T01:00:00Z", **_ref_values(chk))
    r1 = {c: None for c in DX.COLNAMES}
    r1.update(base, job_id="sb13_init_aaaa1111", row_id="sb13_init_aaaa1111")
    r2 = {c: None for c in DX.COLNAMES}
    r2.update({k: base[k] for k in ("femur_id", "femur_model_version", "femur_geom_key", "code_hash_now", "aux_code_md5", "code_hash",
                                    "code_hash_source", "job_id_matches_code", "kind", "stage", "bounds_version", "fidelity",
                                    "femur_geom_verified", "femur_geom_basis", "layer", "provenance", "steps", "t_prep_utc")},
              job_id="sb11_init_bbbb2222", row_id="sb11_init_bbbb2222", status="FAILED", fail_level="L4", fail_stage="solve",
              has_prep=True, has_fric_model=False, has_bond_model=False, export_status="ok", export_errors=[],
              design_key=DX.design_key({**d, "L": 31.0}, 20.0), realization_key="r2", cond_key="c2", femur_pose_match=True,
              femur_pose_dev_mm=0.0, L=31.0, alpha=40.0, h_cut=20.0, m=0.8, n_pairs_cortex=0, h_int_mm=2.0, h_int_prep_mm=2.0,
              load_R_N=float(np.linalg.norm(load)),
              load_vec_N=load.tolist(), delta_spec_mm=0.025, delta_mm=0.025, cons_delta=True, cons_load=True, cons_h_int=True,
              source="sobol_init_p11", selection="iid", in_family_phases=[11, 12])
    for r in (r1, r2):
        _fill_required(r)
        for name, typ, unit, lo, hi, req, *_ in DX.COLUMNS:          # FAILED row: labels must be empty
            if r is r2 and req in ("fric", "bond"):
                r[name] = None

    class Sink:
        def __init__(self):
            self.m = {}

        def add(self, name, data):
            self.m[name] = data
    sb, sk = DX.ShardBuilder("b0", 64), Sink()
    sb.add(r1, arr, meta, load)
    sb.flush(sk, {})
    assert not r1["export_errors"], r1["export_errors"]
    for name, data in sk.m.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    rows, errs, info = DX.finalize_rows([r1, r2], {}, {})
    assert not errs, errs
    ctx = _ctx("b0", "g" * 16, "2026-10-23T00:00:00Z", "2026-10-26T00:00:00Z")
    reg, rerrs, _ = DX.apply_femur_registry(rows, [ctx], None, root.name)
    assert not rerrs, rerrs
    (root / "femur_registry.json").write_text(json.dumps(reg))
    DX.write_scalars(root, rows)
    (root / "schema.json").write_text(json.dumps(DX.schema_dict()))
    b = root / "export" / "b0"
    b.mkdir(parents=True, exist_ok=True)
    (b / "inventory.json").write_text(json.dumps({"jobs": {"sb13_init_aaaa1111": {"state": "DONE"}, "sb11_init_bbbb2222": {"state": "FAILED"}},
                                                  "selected": ["sb13_init_aaaa1111", "sb11_init_bbbb2222"], "selection_args": {"jobs": ["x"]}}))
    (b / "exclusion.json").write_text(json.dumps({"design_keys": {}}))
    (b / "context.json").write_text(json.dumps({"hashed_files_md5": {"a": 1}, "aux_files_md5": {}}))
    return rows


def _qa(root):
    q = DQ.QA(root)
    return {d["id"]: d for d in q.run()}


def _edit_cell(root, job, col, value):
    p = root / "scalars.csv"
    rows = list(csv.reader(open(p, newline="", encoding="utf-8")))
    h = rows[0]
    for r in rows[1:]:
        if r[h.index("job_id")] == job:
            r[h.index(col)] = value
    with open(p, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return rows


def test_qa_synthetic_db_passes_then_fails_on_tampering():
    root = _tmpdir("qa")
    build_synthetic_db(root)
    res = _qa(root)
    bad = {k: v for k, v in res.items() if v["status"] == "FAIL"}
    assert not bad, json.dumps(bad, indent=1, default=str)[:3000]
    assert len(res) == 14 and res[8]["status"] == "WARN"              # explicit --jobs subset, no frozen list
    # tamper 1: scalar rotation no longer matches the stored point cloud
    import shutil
    good = root / "scalars.good.csv"
    shutil.copy(root / "scalars.csv", good)
    rows = list(csv.reader(open(root / "scalars.csv", newline="", encoding="utf-8")))
    h = rows[0]
    v = [r for r in rows[1:] if r[h.index("job_id")] == "sb13_init_aaaa1111"][0][h.index("rot_first_deg")]
    _edit_cell(root, "sb13_init_aaaa1111", "rot_first_deg", repr(float(v) * (1 + 1e-4)))
    assert _qa(root)[2]["status"] == "FAIL"
    # tamper 2: a FAILED row carrying a label, and an unbiased row whose design is in E
    _edit_cell(root, "sb11_init_bbbb2222", "f1_p95_um", "12.5")
    ex = root / "export" / "b0" / "exclusion.json"
    dk = [r for r in rows[1:] if r[h.index("job_id")] == "sb13_init_aaaa1111"][0][h.index("design_key")]
    ex.write_text(json.dumps({"design_keys": {dk: ["sb13_a1_x"]}}))
    res3 = _qa(root)
    assert res3[1]["status"] == "FAIL" and any("labels must be empty" in x for x in res3[1]["failures"])
    assert res3[12]["status"] == "FAIL"
    ex.write_text(json.dumps({"design_keys": {}}))
    # tamper 3 (review D456 issue 7): a row that SHOULD be unbiased but is not flagged
    shutil.copy(good, root / "scalars.csv")
    _edit_cell(root, "sb13_init_aaaa1111", "unbiased", "false")
    r4 = _qa(root)
    assert r4[12]["status"] == "FAIL" and any("plan 1.4 filter gives True" in x for x in r4[12]["failures"]), r4[12]["failures"]
    # tamper 4: femur key differs from the registry; unverified femur binding
    shutil.copy(good, root / "scalars.csv")
    _edit_cell(root, "sb13_init_aaaa1111", "femur_geom_verified", "false")
    r5 = _qa(root)
    assert r5[4]["status"] == "FAIL" and any("not bound to job time" in x for x in r5[4]["failures"])
    shutil.copy(good, root / "scalars.csv")
    reg = json.loads((root / "femur_registry.json").read_text())
    reg["femurs"][DX.FEMUR_ID]["femur_geom_key"] = "h" * 16
    (root / "femur_registry.json").write_text(json.dumps(reg))
    assert _qa(root)[4]["status"] == "FAIL"


def test_qa_check8_frozen_list():
    root = _tmpdir("qa8")
    build_synthetic_db(root)
    names = ["sb11_init_bbbb2222", "sb13_init_aaaa1111"]

    def freeze(nm, inv):
        body = ("\n".join(nm) + "\n").encode()
        (root / "jobs.txt").write_bytes(body)
        sha = hashlib.sha256(body).hexdigest()
        (root / "jobs_inventory.json").write_text(json.dumps({"jobs": nm, "inventory": inv, "jobs_txt_sha256": sha,
                                                             "listed_utc": "2026-10-26T00:00:00Z"}))
        iv = json.loads((root / "export" / "b0" / "inventory.json").read_text())
        iv["selection_args"] = {"jobs": nm, "frozen_list_sha256": sha}
        (root / "export" / "b0" / "inventory.json").write_text(json.dumps(iv))
    inv = {"sb13_init_aaaa1111": {"state": "DONE"}, "sb11_init_bbbb2222": {"state": "FAILED"}, "db_cd_x_1": {"state": "READY"}}
    freeze(names, inv)
    r = _qa(root)[8]
    assert r["status"] == "PASS", r
    assert r["info"]["frozen_list"]["n_finished_not_listed"] == 0
    # a DONE job of the frozen list without a row -> FAIL (review D456 issue 2)
    inv2 = {**inv, "sb13_init_cccc3333": {"state": "DONE"}}
    freeze(names + ["sb13_init_cccc3333"], inv2)
    r = _qa(root)[8]
    assert r["status"] == "FAIL" and any("have no row" in x for x in r["failures"]), r["failures"]


def test_qa_check13_independent_reference_row():
    root = _tmpdir("qa13")
    rows = build_synthetic_db(root)
    import shutil
    # make r1 bonded, add an intact reference row with the same prep-level values, then perturb the reference's E_canc
    p = root / "scalars.csv"
    data = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
    hdr = list(data[0].keys())
    r1 = next(r for r in data if r["job_id"] == "sb13_init_aaaa1111")
    for c, v in (("has_bond_model", "true"), ("intact_job", "ref_x"), ("intact_job_spec", "ref_x"), ("ref_match", "true"),
                 ("sed_chg_pct", "-20.0"), ("ssi_pct", "10.0"), ("vm_p99_MPa", "50.0"), ("vm_max_MPa", "80.0"),
                 ("n_stem_elems_in_bone", "100"), ("f2_g7_loss_pct", "5.0"), ("f2_g1_loss_pct", "1.0"), ("E_canc_MPa", "155.0"),
                 ("h_far_mm", "6.0"), ("neck_axis", '"isthmus"'), ("alpha_front_deg", "20.0"), ("alpha_sagit_deg", "18.0")):
        r1[c] = v
    ref = {k: "" for k in hdr}
    for c in ("femur_id", "femur_geom_key", "femur_model_version", "femur_geom_verified", "femur_geom_basis", "neck_axis", "h_int_mm",
              "h_int_prep_mm", "E_canc_MPa", "h_far_mm", "load_R_N", "alpha_front_deg", "alpha_sagit_deg", "load_vec_N",
              "code_hash", "code_hash_now", "code_hash_source", "aux_code_md5", "layer", "provenance", "t_prep_utc"):
        ref[c] = r1[c]
    ref.update(job_id="ref_x", row_id="ref_x", kind="intact", status="DONE", stage="sb", tag="intact", has_prep="true",
               has_fric_model="false", has_bond_model="false", export_status="ok", export_errors="[]", source="intact_ref",
               selection="stratum", femur_pose_match="true", femur_pose_dev_mm="0.0", spec_in_result_match="",
               in_E="false", sf_bo_overlap="false", unbiased="false", test_iid="false", test_corner="false", a3_test_only="false",
               ood_cond_extreme="false", ood_femur="false", intact_gruen7_vol_mm3="100.0", intact_gruen1_vol_mm3="100.0",
               exporter_version="x", export_batch="b0", export_time_utc="x", export_host="x", job_id_matches_code="true",
               bond_only="false", fric_only="false", in_family_phases="[]", cons_h_int="true", cons_delta="true", cons_load="true",
               load_vec_norm_N=r1["load_vec_norm_N"], head_coupling_radius_mm=r1["head_coupling_radius_mm"], steps='["LOAD"]')

    def write(rs):
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=hdr, lineterminator="\n")
            w.writeheader()
            w.writerows(rs)
    write(data + [ref])
    r = _qa(root)[13]
    assert r["status"] == "PASS" and r["info"]["n_checked_against_ref_row"] == 1, r
    ref2 = dict(ref, E_canc_MPa="400.0")
    write(data + [ref2])
    r = _qa(root)[13]
    assert r["status"] == "FAIL" and any("E_canc_MPa" in x for x in r["failures"]), r["failures"]
    write(data)                                                        # reference not in the version -> FAIL (cannot verify)
    assert _qa(root)[13]["status"] == "FAIL"


# ------------------------------------------------------------------------------------------------ archive helpers (local tar.xz)
def test_archive_members_and_compare():
    d = _tmpdir("arch")
    job = d / "jobx"
    (job / "m_fric_csv").mkdir(parents=True)
    (job / "spec.json").write_text("{}")
    (job / "m_fric_csv" / "LOAD_U.csv").write_bytes(os.urandom(20000))
    arc = d / "jobx.tar.xz"
    with lzma.open(arc, "wb") as xf, tarfile.open(fileobj=xf, mode="w|") as tf:
        tf.add(job, arcname="jobx")
    win, special = DA.members_of(arc)
    lin = {f"jobx/{p.relative_to(job).as_posix()}": {"size": p.stat().st_size, "sha256": DX.sha256_file(p)}
           for p in job.rglob("*") if p.is_file()}
    assert not special and DA.compare(lin, win) == []
    lin2 = dict(lin)
    lin2["jobx/spec.json"] = {"size": 2, "sha256": "0" * 64}
    lin2["jobx/extra.csv"] = {"size": 1, "sha256": "1" * 64}
    errs = DA.compare(lin2, win)
    assert len(errs) == 2


def test_archive_link_rule():
    """Only <job>/m_fric_csv or m_bond_csv -> /mnt/nvme/mobo_raw/<job>/<same name> may be followed (raw_to_nvme.py moves)."""
    j = "db_sf_p1_abc"
    ok = {f"{j}/m_fric_csv": f"/mnt/nvme/mobo_raw/{j}/m_fric_csv", f"{j}/m_bond_csv": f"/mnt/nvme/mobo_raw/{j}/m_bond_csv"}
    assert DA.link_problems(j, ok) == [] and DA.link_problems(j, {}) == []
    for bad in ({f"{j}/m_fric_csv": f"/mnt/nvme/mobo_raw/other_job/m_fric_csv"},     # another job's folder
                {f"{j}/m_fric_csv": "/tmp/x"},                                      # outside the NVMe raw store
                {f"{j}/spec.json": f"/mnt/nvme/mobo_raw/{j}/spec.json"},            # not a raw-CSV folder
                {f"{j}/m_fric_csv/LOAD_U.csv": f"/mnt/nvme/mobo_raw/{j}/m_fric_csv/LOAD_U.csv"},   # a file inside, not the folder
                {f"{j}/m_fric_csv": f"/mnt/nvme/mobo_raw/{j}/m_bond_csv"}):         # swapped names
        assert len(DA.link_problems(j, bad)) == 1, bad


def test_archive_stream_never_hangs():
    """db_archive.stream_archive: the producer closes its stdout but does not exit -> TimeoutExpired after stream_timeout, the
    producer is killed (no 20-minute hang), the exception propagates (review D456 issue 3, second half)."""
    d = _tmpdir("arch_hang")
    prod = "import sys, os, time; sys.stdout.buffer.write(b'x' * 100000); sys.stdout.flush(); os.close(1); time.sleep(600)"
    orig = DA.ssh_base
    DA.ssh_base = lambda a: [BASE_PY, "-c", prod]
    try:
        a = types.SimpleNamespace(level=6, stream_timeout=2.0)
        t0 = time.time()
        try:
            DA.stream_archive(a, "jobx", d / "jobx.tar.xz.part")
            raise AssertionError("expected TimeoutExpired")
        except subprocess.TimeoutExpired:
            pass
        assert time.time() - t0 < 40
    finally:
        DA.ssh_base = orig


# ------------------------------------------------------------------------------------------------ result codes, export provenance
def test_result_code_columns():
    """result_code / result_class sit right after fail_reason; finalize fills them for finished rows only; a code the job itself
    wrote wins over the text; a FAILED row with nothing recorded is UNKNOWN, never ok; a stale code on a DONE row is ignored."""
    i = DX.COLNAMES.index("fail_reason")
    assert DX.COLNAMES[i + 1:i + 3] == ["result_code", "result_class"], DX.COLNAMES[i:i + 4]
    assert {c["name"] for c in DX.schema_dict()["columns"]} >= {"result_code", "result_class"}
    rows = [dict(job_id="a", status="DONE"),
            dict(job_id="b", status="FAILED", fail_level="L4", fail_stage="solve", fail_reason="m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT"),
            dict(job_id="c", status="FAILED", fail_level="L4", fail_stage="solve", fail_reason="m_fric: timeout > 21600 s", result_code="solve_timeout"),
            dict(job_id="d", status="FAILED", fail_level="L3", fail_stage="prep", fail_reason="whatever", result_code="prep_out_of_memory"),
            dict(job_id="e", status="FAILED"),
            dict(job_id="f", status="READY"),
            dict(job_id="g", status="FAILED", fail_level="L4", fail_stage="solve", fail_reason="x", result_code="no_such_code"),
            dict(job_id="h", status="DONE", result_code="not_converged"),
            dict(job_id="i", status="FAILED", fail_level="L3", fail_stage="prep", fail_reason="BuildError: L3: meshing failed after retries: algo 1")]
    DX.apply_result_codes(rows)
    got = {r["job_id"]: (r["result_code"], r["result_class"]) for r in rows}
    assert got == {"a": ("ok", "OK"), "b": ("not_converged", "NUMERIC"), "c": ("solve_timeout", "ENV"), "d": ("prep_out_of_memory", "ENV"),
                   "e": ("unclassified", "UNKNOWN"), "f": (None, None), "g": ("unclassified", "UNKNOWN"), "h": ("ok", "OK"),
                   "i": ("mesh_failed", "NUMERIC")}, got
    assert DQ.ENUMS["result_class"] == {r[1] for r in got.values() if r[1]} | {"DESIGN", "ERROR", "SKIP"}


def test_finalize_records_export_provenance_and_result_classes():
    """manifest.json holds what this finalize ran with: the commit of this repo, its uncommitted changes, the sha256 of the exporter
    and of the result code table; a missing jobs.txt is None, not an error. scalars.csv carries the two result columns."""
    rows = [_row("j1", "x", "iid", "d1", has_prep=True, femur_geom_key="K1", femur_geom_verified=True,
                 femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-24T01:00:00Z"),
            dict(_row("j2", "x", "iid", "d2", has_prep=True, femur_geom_key="K1", femur_geom_verified=True,
                      femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-24T01:00:00Z"),
                 status="FAILED", fail_level="L4", fail_stage="solve", fail_reason="m_fric: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT")]
    ctxs = [dict(_ctx("b0", "K1", "2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z"), queue_complete=True)]
    einfo = {"E_jobs": {}, "n_E": 0, "replicate_groups": {"fric": [], "bond": []}}
    orig = (DX._load_rows, DX.finalize_rows)

    def fin(rows_, E, prov):
        DX.apply_result_codes(rows_)
        return rows_, [], einfo
    try:
        DX._load_rows = lambda out: ([dict(r) for r in rows], {}, {}, [dict(c) for c in ctxs])
        DX.finalize_rows = fin
        root, out = _tmpdir("finprov_root"), _tmpdir("finprov_out")
        (out / "export").mkdir()
        DX.finalize(out, str(root), None, True)
    finally:
        DX._load_rows, DX.finalize_rows = orig
    man = json.loads((out / "manifest.json").read_text())
    ep = man["export_provenance"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(TOOLS), capture_output=True).stdout.decode().strip()
    assert ep["action"] == "export" and len(head) == 40 and ep["git"]["commit"] == head and isinstance(ep["git"]["dirty"], list), ep["git"]
    assert ep["inputs"]["exporter"] == {"file": "tools/db_export.py", "sha256": hashlib.sha256((TOOLS / "db_export.py").read_bytes()).hexdigest()}
    assert ep["inputs"]["result_codes"]["file"] == "v2/result_codes.py" and ep["inputs"]["jobs_list"] is None, ep["inputs"]
    assert man["by_result_class"] == {"NUMERIC": 1, "OK": 1}, man["by_result_class"]
    with open(out / "scalars.csv", encoding="utf-8", newline="") as fh:
        got = {r["job_id"]: (r["status"], r["result_code"], r["result_class"]) for r in csv.DictReader(fh)}
    assert got == {"j1": ("DONE", "ok", "OK"), "j2": ("FAILED", "not_converged", "NUMERIC")}, got


# ------------------------------------------------------------------------------------------------ bed support F
def test_bed_support_by_hand():
    """F = sum A / max(t, 0.25) over stem-body nodes with zeta <= 15 mm and |theta| <= 45 deg. Each node below is in or out for one reason."""
    U = np.array(DX.BED_F["u_neck"]) / np.linalg.norm(DX.BED_F["u_neck"])
    C, N3 = np.array(DX.BED_F["cref"]), np.array(DX.BED_F["n3"])
    ax = -U                                                              # a stem that runs straight down the neck axis: zeta = distance along the stem
    em = N3 - (N3 @ ax) * ax
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
    ep /= np.linalg.norm(ep)

    def node(zeta, th, r=5.0):
        return C + zeta * ax + r * (math.cos(math.radians(th)) * em + math.sin(math.radians(th)) * ep)

    #            position              area   t     collar   in the zone?
    nodes = [(node(5.0, 0.0),          2.0,   1.0,  False),  # yes: 2 / 1
             (node(14.9, 44.0),        3.0,   0.5,  False),  # yes: 3 / 0.5
             (node(10.0, -30.0),       1.0,   0.1,  False),  # yes, the floor decides: 1 / 0.25
             (node(15.1, 0.0),         50.0,  1.0,  False),  # no: too deep
             (node(5.0, 46.0),         50.0,  1.0,  False),  # no: outside the sector
             (node(5.0, 180.0),        50.0,  1.0,  False),  # no: the lateral side
             (node(5.0, 0.0),          50.0,  1.0,  True),   # no: a collar node
             (node(-3.0, 10.0),        4.0,   2.0,  False)]  # yes: above the reference point still counts (zeta <= 15 has no lower bound): 4 / 2
    X = np.array([n[0] for n in nodes])
    area, dc, co = np.array([n[1] for n in nodes]), -np.array([n[2] for n in nodes]), np.array([n[3] for n in nodes])
    r = DX.bed_support(X, area, dc, co, C, ax)
    assert abs(r["F"] - (2 / 1 + 3 / 0.5 + 1 / 0.25 + 4 / 2)) < 1e-9, r
    assert r["F_n_nodes"] == 4 and abs(r["F_area_mm2"] - 10.0) < 1e-12 and abs(r["F_t_min_mm"] - 0.1) < 1e-12 and abs(r["F_frac_floor"] - 0.1) < 1e-12, r
    empty = DX.bed_support(X[3:7], area[3:7], dc[3:7], co[3:7], C, ax)
    assert empty == {"F": 0.0, "F_area_mm2": 0.0, "F_n_nodes": 0, "F_t_min_mm": None, "F_frac_floor": None}, empty


def test_bed_support_constants_are_the_facts_and_the_judging_files():
    """One set of numbers: tools/db_export.BED_F = ops/facts.json = the literals in the judging file of b33 (b28 and later carry the same)."""
    facts = json.loads((TOOLS.parent / "ops" / "facts.json").read_text(encoding="utf-8"))
    assert list(DX.BED_F["u_neck"]) == facts["neck_axis_u"] and list(DX.BED_F["cref"]) == facts["bed_F_cref"] and list(DX.BED_F["n3"]) == facts["bed_F_n3"]
    assert {k: DX.BED_F[k] for k in ("zeta_max_mm", "theta_max_deg", "t_floor_mm")} == facts["bed_F_zone"]
    assert list(DX.BED_F["u_neck"]) != [round(v, 5) for v in facts["neck_axis_u_baked_wrong"]]
    import importlib.util
    spec = importlib.util.spec_from_file_location("gates_b33_for_F", TOOLS.parent / "experiments" / "b33_r2cand" / ("gates" + ".py"))
    gb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gb)
    assert np.array_equal(gb.N3, np.array(DX.BED_F["n3"])) and np.array_equal(gb.CREF, np.array(DX.BED_F["cref"]))
    assert np.array_equal(gb.U_NECK, np.array(DX.BED_F["u_neck"]) / np.linalg.norm(list(DX.BED_F["u_neck"])))
    db = pathlib.Path(r"H:/Projects/Femoral implant generation/db3406/v0.14")       # the version b33 was judged on
    rows = []
    with open(db / "scalars.csv", encoding="utf-8", newline="") as fh:
        for x in csv.DictReader(fh):
            if x["field_shard"] and x["field_shard"] in ("iface_b000_000", "iface_b023_000"):
                rows.append({"job_id": x["job_id"], "femur_id": x["femur_id"], "field_shard": x["field_shard"], "field_index": int(x["field_index"])})
    n, errs = DX.apply_bed_support(db, rows)
    theirs = gb.mesh_F(str(db), {r["job_id"] for r in rows})
    assert n == len(rows) == len(theirs) > 10 and not errs, (n, len(rows), len(theirs), errs[:2])
    assert all(theirs[r["job_id"]] == r["F"] for r in rows), "the exporter's F must equal the judging file's mesh_F to the last bit"


def test_apply_bed_support_and_finalize_columns():
    """Rows get F from their shard and index; a missing shard, a wrong index and another femur leave F empty (the first two are errors);
    finalize writes the five columns and manifest.bed_F."""
    out = _tmpdir("bedF_out")
    (out / "fields").mkdir()
    (out / "export").mkdir()
    U = np.array(DX.BED_F["u_neck"]) / np.linalg.norm(DX.BED_F["u_neck"])
    C, ax = np.array(DX.BED_F["cref"]), -U
    N3 = np.array(DX.BED_F["n3"])
    em = N3 - (N3 @ ax) * ax
    em /= np.linalg.norm(em)
    Xa = np.array([C + 5.0 * ax + 5.0 * em, C + 20.0 * ax + 5.0 * em])                # one node in the zone, one too deep
    Xb = np.array([C + 2.0 * ax + 4.0 * em])
    frame = np.zeros((2, 4, 3))
    frame[:, 0], frame[:, 1] = C, ax
    np.savez(out / "fields" / "iface_t_000.npz", X=np.vstack([Xa, Xb]), area=np.array([2.0, 9.0, 3.0]), d_canal=np.array([-1.0, -1.0, -0.5]),
             collar=np.array([False, False, False]), off=np.array([0, 2, 3]), frame=frame, job_id=np.array(["j1", "j2"]))
    base = dict(femur_id=DX.FEMUR_ID)
    rows = [dict(base, job_id="j1", field_shard="iface_t_000", field_index=0), dict(base, job_id="j2", field_shard="iface_t_000", field_index=1),
            dict(base, job_id="j3", field_shard="iface_t_000", field_index=1),          # the index holds j2
            dict(base, job_id="j4", field_shard="iface_gone_000", field_index=0),       # no such shard
            dict(base, job_id="j5", field_shard=None, field_index=None),                # no point cloud (a bonded-only row, a failed row)
            dict(job_id="j6", femur_id="ct_femur", field_shard="iface_t_000", field_index=0)]
    n, errs = DX.apply_bed_support(out, rows)
    got = {r["job_id"]: r["F"] for r in rows}
    assert n == 2 and got == {"j1": 2.0, "j2": 6.0, "j3": None, "j4": None, "j5": None, "j6": None}, got
    assert len(errs) == 2 and any("j3" in e and "holds j2" in e for e in errs) and any("j4" in e and "missing" in e for e in errs), errs
    assert rows[0]["F_n_nodes"] == 1 and rows[0]["F_area_mm2"] == 2.0 and all(rows[4][k] is None for k in DX.BED_F_COLS)
    i = DX.COLNAMES.index("field_n_tri")
    assert DX.COLNAMES[i + 1:i + 6] == list(DX.BED_F_COLS), DX.COLNAMES[i:i + 7]
    frows = [dict(_row("j1", "x", "iid", "d1", has_prep=True, femur_geom_key="K1", femur_geom_verified=True, femur_geom_basis="files_older_than_prep",
                       t_prep_utc="2026-10-24T01:00:00Z"), field_shard="iface_t_000", field_index=0)]
    ctxs = [dict(_ctx("b0", "K1", "2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z"), queue_complete=True)]
    einfo = {"E_jobs": {}, "n_E": 0, "replicate_groups": {"fric": [], "bond": []}}
    orig = (DX._load_rows, DX.finalize_rows)
    try:
        DX._load_rows = lambda o: ([dict(r) for r in frows], {}, {}, [dict(c) for c in ctxs])
        DX.finalize_rows = lambda rows_, E, prov: (rows_, [], einfo)
        DX.finalize(out, str(_tmpdir("bedF_root")), None, True)
    finally:
        DX._load_rows, DX.finalize_rows = orig
    man = json.loads((out / "manifest.json").read_text())
    assert man["bed_F"]["n_rows"] == 1 and man["bed_F"]["version"] == "mesh" and man["bed_F"]["cref"] == list(DX.BED_F["cref"]) and man["bed_F"]["zeta_max_mm"] == 15.0
    with open(out / "scalars.csv", encoding="utf-8", newline="") as fh:
        (r1,) = list(csv.DictReader(fh))
    assert (r1["F"], r1["F_n_nodes"], r1["F_area_mm2"], r1["F_t_min_mm"], r1["F_frac_floor"]) == ("2.0", "1", "2.0", "1.0", "0.0"), r1["F"]


# ------------------------------------------------------------------------------------------------ publish
def test_publish_freezes_a_version():
    """publish needs every listed file intact, nothing unlisted, and a qa_report.json; it writes PUBLISHED.json; after that finalize refuses,
    and --check tells when a file, the manifest or the QA report changed."""
    out = _tmpdir("publish_out")
    (out / "export").mkdir()
    frows = [_row("j1", "x", "iid", "d1", has_prep=True, femur_geom_key="K1", femur_geom_verified=True, femur_geom_basis="files_older_than_prep", t_prep_utc="2026-10-24T01:00:00Z")]
    ctxs = [dict(_ctx("b0", "K1", "2026-10-23T23:40:47Z", "2026-10-26T00:00:00Z"), queue_complete=True)]
    einfo = {"E_jobs": {}, "n_E": 0, "replicate_groups": {"fric": [], "bond": []}}
    orig = (DX._load_rows, DX.finalize_rows)

    def fin():
        DX._load_rows = lambda o: ([dict(r) for r in frows], {}, {}, [dict(c) for c in ctxs])
        DX.finalize_rows = lambda rows_, E, prov: (rows_, [], einfo)
        try:
            return DX.finalize(out, str(_tmpdir("publish_root")), None, True)
        finally:
            DX._load_rows, DX.finalize_rows = orig

    assert DX.publish(_tmpdir("publish_empty")) == 2                               # no manifest
    assert fin() == 0
    assert DX.publish(out, check=True) == 3                                       # not published yet
    assert DX.publish(out) == 3 and not (out / DX.PUBLISHED_NAME).exists()        # no QA report
    (out / "qa_report.json").write_text("{}", encoding="utf-8")
    (out / "stray.txt").write_text("x", encoding="utf-8")
    assert DX.publish(out) == 3 and not (out / DX.PUBLISHED_NAME).exists()        # a file the manifest does not list
    (out / "stray.txt").unlink()
    sc = (out / "scalars.csv").read_bytes()
    (out / "scalars.csv").write_bytes(sc + b"x")
    assert DX.publish(out) == 3 and not (out / DX.PUBLISHED_NAME).exists()        # a listed file that changed
    (out / "scalars.csv").write_bytes(sc)
    assert DX.publish(out) == 0
    pub = json.loads((out / DX.PUBLISHED_NAME).read_text(encoding="utf-8"))
    assert pub["manifest_sha256"] == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest() and pub["n_rows"] == 1 and pub["published_utc"]
    assert DX.publish(out, check=True) == 0 and DX.publish(out) == 3              # still as published; publishing twice is refused
    try:
        fin()
        raise AssertionError("finalize must refuse a published version")
    except SystemExit as e:
        assert "published" in str(e)
    (out / "qa_report.json").write_text('{"changed": 1}', encoding="utf-8")
    assert DX.publish(out, check=True) == 3
    (out / "qa_report.json").write_text("{}", encoding="utf-8")
    (out / "scalars.csv").write_bytes(sc + b"x")
    assert DX.publish(out, check=True) == 3
    (out / "scalars.csv").write_bytes(sc)
    assert DX.publish(out, check=True) == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        t0 = time.time()
        fn()
        print(f"ok {fn.__name__} ({time.time() - t0:.1f} s)")
    print(f"{len(fns)} tests passed")
