"""Run with the repo venv: PYTHONUTF8=1 .venv-mobo/Scripts/python.exe v2/tests/test_stage_db_rows_in.py
Local only: a fake queue and a fake experiments folder in the system temp dir (mobo_toy_db_rows_in_tests); J.QROOT and DB.ROWS_IN_ROOT point
there. No gmsh, no FE, no Linux, nothing under ~/mobo_toy_v2 or the repo's experiments/ is read for rows_in or written. Source specs come
read-only from db3406/raw.

v2/stage_db.py v1.26, batches from a rows file (build_file): one row = one DONE baseline row x one condition.
A. same job ids as the old builders: for b33, b28c, b26, b32, b32b and b24 the rows are written out as a rows file (base = the row's baseline,
   cond = what the old builder changed) and built again under a new batch name. Every row must come back with the same spec, the same
   expected id, layer, stage, source, model set, reference and heavy flag. The ids also equal the frozen experiments/<batch>/rows.json
   (what was fed and judged) where there is one.
B. the file is strict: format, batch name, form, unknown keys, empty rows, two conditions in a row, an unknown condition, a bad key,
   repeated keys, two files for one batch, a batch name that is in BATCHES.
C. the baseline row: absent, not a baseline row (an intact reference, a row that already carries a condition) -> refused; not DONE -> a problem.
D. conditions: values outside what the hooks and references allow are refused; an integer and a float give the same id.
E. layers: a new layer must be declared with a known source and becomes slow start; an existing layer with another source is refused.
F. the feeder: the rows file's sha256 goes into the manifest; a changed file is refused at restart and stops a running feeder; dry run writes nothing.
G. form new_designs (hard-written u13 and entry offset, as build_urows and build_b25): b31, b30 and b25 written as files build the same rows and
   the same ids as the frozen rows.json; the checks of the old builders still fire (m below 1, the 0-FE record, a required row not DONE);
   malformed files are refused; a new layer may be adaptive but not iid.
"""
import contextlib
import io
import json
import pathlib
import shutil
import sys
import tarfile
import tempfile
import time

ROOT = pathlib.Path(r"H:/projects/Femoral implant generation/sandbox/mobo_toy")
RAW = pathlib.Path(r"H:/projects/Femoral implant generation/db3406/raw")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2"))
BASE = pathlib.Path(tempfile.gettempdir()) / "mobo_toy_db_rows_in_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

import jobs as J  # noqa: E402
import stage_db as DB  # noqa: E402

T_START = time.perf_counter()
REAL_Q, REAL_R, REAL_ROWS = J.QROOT, J.RESULTS, DB.ROWS_IN_ROOT
checks = []
A, REF = DB.CODES["A"], DB.REF_H2
R194, R206, R14 = "db_ref_intact_h1.94_0df7c4b7", "db_ref_intact_h2.06_f1de5f78", "db_ref_intact_h1.4_b7b166b8"
CTRL = "db_ws_p13_a105_91e458e3_m1_2a79b613"
JOBS = {A, REF, R194, R206, R14, CTRL, DB.F5_SMOKE_BASE, *DB.UROW_CURVE} | {j for _, j in DB.FAM1_CTRL} | {j for _, j in DB.STS1_ROWS}
snap = sorted(p for p in (RAW / "results").iterdir() if p.is_dir() and "." not in p.name)[-1]
EXP = ROOT / "experiments"


def ok(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + f"(t={time.perf_counter() - T_START:.0f}s) " + name + (f"  [{extra}]" if extra and not cond else ""), flush=True)


def extract(job, dest):
    d = dest / job
    d.mkdir(parents=True)
    with tarfile.open(RAW / f"{job}.tar.xz", "r:xz") as tf:
        for member in ("spec.json", "prep.json", "DONE"):
            try:
                f = tf.extractfile(f"{job}/{member}")
            except KeyError:
                continue
            (d / member).write_bytes(f.read())


CACHE = BASE / "_cache"
for j_ in sorted(JOBS):
    extract(j_, CACHE)


def queue(name):
    """A fake queue with every baseline row the old builders need: the raw jobs, plus the main rows of b31 and b28 written as DONE."""
    root = BASE / name
    J.QROOT, J.RESULTS = root / "queue", root / "results"
    assert not str(J.QROOT).startswith(str(pathlib.Path.home() / "mobo_toy_v2"))
    J.QROOT.mkdir(parents=True)
    J.RESULTS.mkdir(parents=True)
    (root / "logs").mkdir()
    for j in JOBS:
        shutil.copytree(CACHE / j, J.QROOT / j)
    shutil.copy2(snap / "db_manifest_b1.json", J.RESULTS / "db_manifest_b1.json")
    for old, layer in (("b31", None), ("b28", "FAM-1")):
        for r in DB.build(old)["rows"]:
            if layer is None or r["layer"] == layer:
                d = J.QROOT / r["expected_id"]
                if not d.exists():
                    d.mkdir()
                    (d / "spec.json").write_text(json.dumps(r["spec"], indent=1, default=float))
                    (d / "DONE").write_text("")
    return root


def rows_dir(name):
    DB.ROWS_IN_ROOT = BASE / name
    DB.ROWS_IN_ROOT.mkdir(parents=True, exist_ok=True)
    return DB.ROWS_IN_ROOT


def write(name, rows, layers=None, folder=None, **over):
    d = DB.ROWS_IN_ROOT / (folder or f"{name}_t")
    d.mkdir(parents=True, exist_ok=True)
    doc = {"format": DB.ROWS_IN_FORMAT, "batch": name, "form": "variants", "layers": layers or {}, "rows": rows, **over}
    (d / "rows_in.json").write_text(json.dumps(doc, indent=1, default=float), encoding="utf-8")
    return d / "rows_in.json"


def cond_of(spec):
    """What an old builder changed, read back from the spec it wrote."""
    if spec.get("torsion"):
        return {"torsion": dict(spec["torsion"])}
    if spec.get("pose_fixed"):
        return {"pose": dict(spec["pose_fixed"])}
    if spec.get("foam_refine"):
        return {"foam_refine": {"h": spec["foam_refine"]["h"]}}
    if spec.get("h_int") != DB.H_PROD:
        return {"mesh": spec["h_int"]}
    load = (spec.get("cfg") or {}).get("load")
    return {"load": next(k for k, v in DB.STS_LOADS.items() if v == load)}


def refused(fn, *a):
    try:
        with contextlib.redirect_stderr(io.StringIO()):          # argparse writes its usage text there
            fn(*a)
    except SystemExit as e:
        return str(e) or "exit"
    return ""


def one(cond, base=None, key="X1", layer="STS-1"):
    return [{"key": key, "layer": layer, "base": base or CTRL, "cond": cond}]


FIELDS = ("key", "layer", "stage", "source", "selection", "model_set", "bonded", "intact_job", "ref_key", "heavy", "exclusive", "expected_id", "id", "dedup")
try:
    # ---------------------------------------------------------------- A
    queue("same")
    rows_dir("rows_same")
    ok("A: v1.26 keeps the code hash; the file batch names are not in BATCHES", J.code_hash() == DB.DB_CODE_HASH and not {"f33", "f28c", "f26", "f32", "f32b", "f24"} & set(DB.BATCHES))
    frozen = {}
    for old, folder in (("b33", "b33_r2cand"), ("b28c", "b28c_cond"), ("b32", "b32_f5smoke"), ("b32b", "b32b_f5smoke07")):
        frozen[old] = {r["label"]: r["job_id"] for r in json.load(open(EXP / folder / "rows.json", encoding="utf-8"))["rows"]}
    frozen["b26"] = {r["label"]: r["job_id"] for r in json.load(open(EXP / "b26_sts1714" / "rows.json", encoding="utf-8"))["b26"]}
    n_rows = 0
    for old in ("b33", "b28c", "b26", "b32", "b32b", "b24"):
        b_old = DB.build(old)
        base_of = {r["key"]: r["source_job"] for r in b_old["rows"]}
        if old == "b24":                                   # b24 records the design job as the source; its baseline rows are the controls
            base_of = {k: b_old["ws_control"][k.split("_")[2] if k.startswith("TQ1S") else k.split("_")[1]] for k in base_of}
        new = "f" + old[1:]
        write(new, [{"key": r["key"], "layer": r["layer"], "base": base_of[r["key"]], "cond": cond_of(r["spec"])} for r in b_old["rows"]])
        b_new = DB.build(new)
        n_rows += len(b_new["rows"])
        diff = [r_o["key"] for r_o, r_n in zip(b_old["rows"], b_new["rows"]) if r_o["spec"] != r_n["spec"] or any(r_o[f] != r_n[f] for f in FIELDS)]
        ok(f"A: {old} written as a rows file builds the same {len(b_old['rows'])} rows: spec, id, layer, stage, source, model set, reference, heavy",
           len(b_old["rows"]) == len(b_new["rows"]) > 0 and not diff and not b_new["problems"] and b_new["problems"] == b_old["problems"],
           f"diff {diff[:4]} problems {b_new['problems'][:2]}")
        if old in frozen:
            got = {r["key"]: r["expected_id"] for r in b_new["rows"]}
            ok(f"A: {old}: the ids from the rows file equal the frozen experiments rows.json (what was fed and judged)", got == frozen[old],
               str({k: (got.get(k), v) for k, v in frozen[old].items() if got.get(k) != v})[:300])
        if old != "b24":
            ok(f"A: {old}: source job, in_E true, unbiased false as the old builder", all(
                r_o["source_job"] == r_n["source_job"] and r_n["in_E"] is True and r_n["unbiased"] is False and r_o["in_E"] and not r_o["unbiased"]
                for r_o, r_n in zip(b_old["rows"], b_new["rows"])))
    ok("A: 45 rows compared in all (9 + 9 + 15 + 1 + 1 + 10)", n_rows == 45, str(n_rows))
    b33 = DB.build("f33")
    ok("A: the build says where the rows came from and their sha256", b33["form"] == "variants" and b33["rows_in"]["file"] == "experiments/f33_t/rows_in.json"
       and b33["rows_in"]["sha256"] == DB.rows_in_sha256("f33") and len(b33["rows_in"]["sha256"]) == 64)
    p33 = DB.rows_in_path("f33")
    lf = p33.read_bytes().replace(b"\r\n", b"\n")
    p33.write_bytes(lf.replace(b"\n", b"\r\n"))
    ok("A: the sha256 is the same for CRLF and LF copies of the file (Windows working tree, Linux deploy)", DB.rows_in_sha256("f33") == b33["rows_in"]["sha256"])
    p33.write_bytes(lf)

    # ---------------------------------------------------------------- B
    rows_dir("rows_strict")
    good = one({"load": "F1714"})
    write("g1", good)
    ok("B: a minimal file builds one row", [r["key"] for r in DB.build("g1")["rows"]] == ["X1"] and not DB.build("g1")["problems"])
    ok("B: a batch without a rows file is unknown, in build and on the command line", "unknown batch" in refused(DB.build, "g9")
       and refused(DB.main, ["dry-run", "g9"]) and not DB.known_batch("g9") and DB.known_batch("g1") and DB.known_batch("b33"))
    write("b33", good, folder="b33_shadow")
    ok("B: a rows file under the name of a batch in BATCHES is ignored (the old builder stays in charge)", DB.rows_in_path("b33") is None)
    shutil.rmtree(DB.ROWS_IN_ROOT / "b33_shadow")
    for label, kw in (("wrong format", {"format": "x"}), ("another batch name inside", {"batch": "g3"}), ("another form", {"form": "new_designs"}),
                      ("an unknown top-level key", {"extra": 1})):
        write("g2", good, **kw)
        ok(f"B: {label} is refused", refused(DB.build, "g2"))
    for label, bad_rows in (("no rows", []), ("rows not a list", {})):
        write("g2", bad_rows)
        ok(f"B: {label} is refused", refused(DB.build, "g2"))
    for label, rows in (("two conditions in one row", one({"load": "F1714", "mesh": 1.94})), ("an unknown condition", one({"friction": 0.3})),
                        ("a key with a space", one({"load": "F1714"}, key="X 1")), ("a row with an extra field", [{**good[0], "note": "x"}]),
                        ("a row without a layer", [{k: v for k, v in good[0].items() if k != "layer"}]),
                        ("repeated keys", good + one({"load": "F3839"}))):
        write("g2", rows)
        ok(f"B: {label} is refused", refused(DB.build, "g2"))
    write("g2", good + one({"load": "F3839"}, key="X2"))
    ok("B: the same two rows with distinct keys build", len(DB.build("g2")["rows"]) == 2)
    write("g4", good, folder="g4_a")
    write("g4", good, folder="g4_b")
    ok("B: two rows files for one batch are refused", "more than one" in refused(DB.build, "g4"))
    ok("B: names that are not batch names find nothing", DB.rows_in_path("G1") is None and DB.rows_in_path("../g1") is None and DB.rows_in_path("") is None)

    # ---------------------------------------------------------------- C
    write("g5", one({"load": "F1714"}, base="db_ws_nothing_00000000"))
    ok("C: a base that is not in the queue is refused", "no readable spec.json" in refused(DB.build, "g5"))
    write("g5", one({"load": "F1714"}, base=REF))
    ok("C: an intact reference as the base is refused", "not a baseline row" in refused(DB.build, "g5"))
    sts_row = DB.build("g1")["rows"][0]
    d_sts = J.QROOT / sts_row["expected_id"]
    d_sts.mkdir()
    (d_sts / "spec.json").write_text(json.dumps(sts_row["spec"], default=float))
    (d_sts / "DONE").write_text("")
    write("g5", one({"mesh": 1.94}, base=sts_row["expected_id"], layer="STS-1 mesh"))
    ok("C: a base that already carries a condition (cfg) is refused: conditions do not stack", "cfg" in refused(DB.build, "g5"))
    shutil.rmtree(d_sts)
    write("g5", one({"load": "F1714"}))
    (J.QROOT / CTRL / "DONE").unlink()
    ok("C: a base that is not DONE is a problem, not a crash", [p for p in DB.build("g5")["problems"] if CTRL in p and "must be DONE" in p])
    (J.QROOT / CTRL / "DONE").write_text("")

    # ---------------------------------------------------------------- D
    def ids(batch, cond, layer="STS-1"):
        write(batch, one(cond, layer=layer))
        return [r["expected_id"] for r in DB.build(batch)["rows"]]

    for label, cond, layer in (("mesh 2.5 (no reference rule)", {"mesh": 2.5}, "STS-1 mesh"), ("mesh as text", {"mesh": "1.94"}, "STS-1 mesh"),
                               ("an unknown load", {"load": "F9999"}, "STS-1"), ("torsion definition C", {"torsion": {"def": "C", "T_Nm": 10}}, "TQ-1 smoke"),
                               ("torsion without T_Nm", {"torsion": {"def": "A"}}, "TQ-1 smoke"), ("torsion with an extra key", {"torsion": {"def": "B", "T_Nm": 10, "preload": 5}}, "TQ-1 smoke"),
                               ("a pose with an unknown key", {"pose": {"dx": 1}}, "PF-1 smoke"), ("a pose that moves nothing", {"pose": {"de": 0}}, "PF-1 smoke"),
                               ("an empty pose", {"pose": {}}, "PF-1 smoke"), ("foam_refine with an extra key", {"foam_refine": {"h": 1.0, "dist_min": 1}}, "F5 smoke"),
                               ("foam_refine h true", {"foam_refine": {"h": True}}, "F5 smoke"), ("foam_refine h 0", {"foam_refine": {"h": 0}}, "F5 smoke")):
        write("g6", one(cond, layer=layer))
        ok(f"D: {label} is refused", refused(DB.build, "g6"))
    write("g6", one({"foam_refine": {"h": 2.0}}, base=DB.F5_SMOKE_BASE, layer="F5 smoke"))
    ok("D: foam_refine h not finer than the mesh is a problem (the hook's own check)", [p for p in DB.build("g6")["problems"] if "foam_refine h" in p])
    ok("D: T_Nm 10 and 10.0 give the same id; 20 gives another", ids("g6", {"torsion": {"def": "B", "T_Nm": 10}}, "TQ-1 smoke")
       == ids("g6", {"torsion": {"def": "B", "T_Nm": 10.0}}, "TQ-1 smoke") != ids("g6", {"torsion": {"def": "B", "T_Nm": 20}}, "TQ-1 smoke"))
    ok("D: pose de 1 and 1.0 give the same id", ids("g6", {"pose": {"de": 1}}, "PF-1 smoke") == ids("g6", {"pose": {"de": 1.0}}, "PF-1 smoke"))
    write("g6", [{"key": "P1", "layer": "PF-1 smoke", "base": CTRL, "cond": {"pose": {"rot_deg": 2, "de": -1, "dalpha_deg": 0.5, "ds": 1}}}])
    r6 = DB.build("g6")["rows"][0]
    ok("D: a pose with all four quantities: keys in the hook's order, floats, every one in the tag",
       list(r6["spec"]["pose_fixed"].items()) == [("de", -1.0), ("ds", 1.0), ("rot_deg", 2.0), ("dalpha_deg", 0.5)]
       and r6["spec"]["tag"].endswith("_pf_de-1_ds+1_rot+2_da+0.5") and r6["spec"].get("fric_only") and r6["stage"] == "db_cd", r6["spec"]["tag"])
    write("g6", [{"key": "M206", "layer": "STS-1 mesh", "base": CTRL, "cond": {"mesh": 2.06}}])
    r6 = DB.build("g6")["rows"][0]
    ok("D: mesh 2.06: db_nz, bonded, the b1 reference of that mesh, passes the reference rule",
       r6["stage"] == "db_nz" and r6["spec"]["h_int"] == 2.06 and r6["intact_job"] == R206 and r6["ref_key"] == "REF_h2.06" and r6["model_set"] == "fric+bond"
       and not DB.build("g6")["problems"], str(DB.build("g6")["problems"])[:300])
    (J.QROOT / R206 / "DONE").unlink()
    ok("D: a reference that is not DONE is a problem", [p for p in DB.build("g6")["problems"] if "REF_h2.06" in p])
    (J.QROOT / R206 / "DONE").write_text("")

    # ---------------------------------------------------------------- E
    before = (dict(DB.LAYER_SOURCE), DB.SLOW_START_LAYERS)
    write("g7", one({"load": "F1714"}, layer="NEW-1 sts"))
    ok("E: a new layer that is not declared is refused", "is new" in refused(DB.build, "g7"))
    write("g7", one({"load": "F1714"}, layer="NEW-1 sts"), layers={"NEW-1 sts": {"source": "made_up"}})
    ok("E: a new layer with a source that does not exist is refused", "is new" in refused(DB.build, "g7"))
    write("g7", one({"load": "F1714"}, layer="NEW-1 sts"), layers={"NEW-1 sts": {"source": "cond_anchor", "selection": "iid"}})
    ok("E: a layer declaration may only hold source (condition rows are never iid)", refused(DB.build, "g7"))
    write("g7", one({"load": "F1714"}, layer="STS-1"), layers={"OTHER": {"source": "noise"}})
    ok("E: a declared layer that no row uses is refused", "unused" in refused(DB.build, "g7"))
    write("g7", one({"load": "F1714"}, layer="STS-1"), layers={"STS-1": {"source": "noise"}})
    ok("E: an existing layer declared with another source is refused", "exists with source" in refused(DB.build, "g7"))
    write("g7", one({"load": "F1714"}, layer="b33"), layers={"b33": {"source": "cond_anchor"}})
    ok("E: a layer named like a batch is refused (its release file would be the batch's)", "not usable" in refused(DB.build, "g7"))
    ok("E: none of the refused files changed the layer tables", (dict(DB.LAYER_SOURCE), DB.SLOW_START_LAYERS) == before)
    write("g7", one({"load": "F1714"}, layer="NEW-1 sts"), layers={"NEW-1 sts": {"source": "cond_anchor"}})
    r7 = DB.build("g7")["rows"][0]
    ok("E: a declared new layer is registered with its source, selection stratum, and is slow start",
       r7["source"] == "cond_anchor" and r7["selection"] == "stratum" and DB.LAYER_SOURCE["NEW-1 sts"] == "cond_anchor" and "NEW-1 sts" in DB.SLOW_START_LAYERS
       and DB.SLOW_START_LAYERS[:len(before[1])] == before[1])

    # ---------------------------------------------------------------- G
    rows_dir("rows_designs")

    def wd(name, rows, **over):
        d = DB.ROWS_IN_ROOT / f"{name}_t"
        d.mkdir(parents=True, exist_ok=True)
        doc = {"format": DB.ROWS_IN_FORMAT, "batch": name, "form": "new_designs", "rows": rows, **over}
        (d / "rows_in.json").write_text(json.dumps({k: v for k, v in doc.items() if v is not None}, indent=1, default=float), encoding="utf-8")

    def drows(const, with_label=True):
        return [dict(zip(("label", "e", "A0", "bone_mm3", "u13"), (x[0], x[1], x[2], x[3], list(x[4])) if with_label else (f"{n:02d}", x[0], x[1], x[2], list(x[3]))))
                for n, x in enumerate(const, 1)]

    HEAD = {"f31": dict(layer="R2", stage="db_al", tag_prefix="r2", mode="fric", al_group="r2", al_problem="F_f1_bone_near_3b", requires_done=list(DB.UROW_CURVE)),
            "f30": dict(layer="OF-1", stage="db_ws", tag_prefix="of1", mode="fric", al_group="of1", al_problem="one_factor_shape", requires_done=list(DB.UROW_CURVE)),
            "f25": dict(layer="OPT-1", stage="db_al", tag_prefix="opt1", mode="full", al_group="opt1", al_problem="F_f1_bone")}
    DEFS = {"f31": drows(DB.R2_ROWS), "f30": drows(DB.OF1_ROWS), "f25": drows(DB.OPT1_ROWS, with_label=False)}
    XF = FIELDS + ("source_job", "in_E", "unbiased", "al_group", "al_problem", "e_star", "e_forced", "layer_pos")
    n_d = 0
    for old, folder in (("b31", "b31_r2"), ("b30", "b30_of1"), ("b25", "b25_opt1")):
        new = "f" + old[1:]
        b_old = DB.build(old)
        wd(new, DEFS[new], **HEAD[new])
        b_new = DB.build(new)
        n_d += len(b_new["rows"])
        diff = [r_o["key"] for r_o, r_n in zip(b_old["rows"], b_new["rows"]) if r_o["spec"] != r_n["spec"] or any(r_o[f] != r_n[f] for f in XF)]
        ok(f"G: {old} written as a new_designs file builds the same {len(b_old['rows'])} rows: spec, id, key, layer, selection, source job, group, offsets",
           len(b_old["rows"]) == len(b_new["rows"]) > 0 and not diff and not b_new["problems"] and not b_old["problems"] and b_new["ws_control"] == b_old["ws_control"],
           f"diff {diff[:4]} problems {b_new['problems'][:2]}")
        fz = {r["label"]: r["job_id"] for r in json.load(open(EXP / folder / "rows.json", encoding="utf-8"))["rows"]}
        got = {r["key"]: r["expected_id"] for r in b_new["rows"]}
        ok(f"G: {old}: the ids from the file equal the frozen experiments rows.json", got == fz, str({k: (got.get(k), v) for k, v in fz.items() if got.get(k) != v})[:300])
    ok("G: 35 new-design rows compared (15 + 12 + 8)", n_d == 35, str(n_d))
    one_d = DEFS["f31"][:1]
    for label, rows, over in (("stage db_cd", one_d, {"stage": "db_cd"}), ("mode bond", one_d, {"mode": "bond"}), ("a tag prefix with a capital", one_d, {"tag_prefix": "R2"}),
                              ("no al_problem", one_d, {"al_problem": None}), ("an unknown top-level key", one_d, {"winners": ["a"]}),
                              ("requires_done not a list", one_d, {"requires_done": "x"}),
                              ("12 coordinates", [{**one_d[0], "u13": one_d[0]["u13"][:12]}], {}), ("a coordinate of 1.5", [{**one_d[0], "u13": [1.5] + one_d[0]["u13"][1:]}], {}),
                              ("a label with a space", [{**one_d[0], "label": "r2 01"}], {}), ("a row without A0", [{k: v for k, v in one_d[0].items() if k != "A0"}], {}),
                              ("the same label twice", one_d + one_d, {})):
        wd("g8", rows, **{**HEAD["f31"], **over})
        ok(f"G: {label} is refused", refused(DB.build, "g8"))
    wd("g8", one_d, **HEAD["f31"])
    ok("G: the one-row file itself builds without problems", not DB.build("g8")["problems"])
    wd("g8", [{**one_d[0], "A0": one_d[0]["A0"] + 5.0}], **HEAD["f31"])
    ok("G: a size that differs from the 0-FE record is a problem", [p for p in DB.build("g8")["problems"] if "differs from the 0-FE record" in p])
    wd("g8", [{**one_d[0], "e": one_d[0]["e"] + 0.5}], **HEAD["f31"])
    ok("G: an entry offset that templating does not give at that size is a problem", DB.build("g8")["problems"])
    i_m = list(DB.b2_phase().vars).index("m")
    wd("g8", [{**one_d[0], "u13": [0.0 if j == i_m else x for j, x in enumerate(one_d[0]["u13"])]}], **HEAD["f31"])
    ok("G: a design with m below 1 is a problem", [p for p in DB.build("g8")["problems"] if ": m " in p and "< 1" in p], str(DB.build("g8")["problems"])[:200])
    wd("g8", one_d, **{**HEAD["f31"], "requires_done": ["db_ws_nothing_00000000"]})
    ok("G: a required row that is not DONE is a problem", [p for p in DB.build("g8")["problems"] if "db_ws_nothing_00000000" in p])
    wd("g8", one_d, **{**HEAD["f31"], "layer": "NEW-2", "layers": {"NEW-2": {"source": "al_adaptive", "selection": "iid"}}})
    ok("G: a new layer may not be declared iid (iid rows must come from a seeded rule in code)", refused(DB.build, "g8"))
    wd("g8", one_d, **{**HEAD["f31"], "layer": "NEW-2", "layers": {"NEW-2": {"source": "al_adaptive", "selection": "adaptive"}}})
    r8 = DB.build("g8")["rows"][0]
    ok("G: a new adaptive layer is registered: source, selection adaptive, slow start; the row is in E and not unbiased",
       r8["source"] == "al_adaptive" and r8["selection"] == "adaptive" and DB.LAYER_SELECTION["NEW-2"] == "adaptive" and "NEW-2" in DB.SLOW_START_LAYERS and r8["in_E"] and not r8["unbiased"])
    wd("g8", one_d, **{**HEAD["f31"], "layers": {"R2": {"source": "al_adaptive", "selection": "stratum"}}})
    ok("G: an existing layer declared with another selection is refused", "exists with source" in refused(DB.build, "g8"))

    # ---------------------------------------------------------------- F
    root = queue("feed")
    rows_dir("rows_feed")
    pf = write("h1", one({"load": "F1714"}) + one({"load": "F3839"}, key="X2"))
    before_files = sorted(str(x.relative_to(root)) for x in root.rglob("*"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = DB.main(["dry-run", "h1"])
    out = buf.getvalue()
    ok("F: dry run of a file batch exits 0, lists 2 jobs, writes nothing", rc == 0 and "jobs (2):" in out and before_files == sorted(str(x.relative_to(root)) for x in root.rglob("*")), out[-300:])
    b = DB.build("h1")
    man = DB.open_manifest("h1", b, {"key": "k"}, lambda m: None, aux={})
    ok("F: a new manifest records the rows file and its sha256", man["rows_in"] == b["rows_in"] and man["rows_in"]["sha256"] == DB.rows_in_sha256("h1"))
    DB._write_json(DB.manifest_path("h1"), man)
    ok("F: restart with the same file is accepted", DB.open_manifest("h1", DB.build("h1"), {"key": "k"}, lambda m: None, aux={})["rows_in"] == b["rows_in"])
    doc = json.loads(pf.read_text(encoding="utf-8"))
    pf.write_text(json.dumps({**doc, "note": "edited after the first start"}, indent=1), encoding="utf-8")
    why = refused(lambda: DB.open_manifest("h1", DB.build("h1"), {"key": "k"}, lambda m: None, aux={}))
    ok("F: restart with a changed file is refused even when the rows are the same", "rows_in.json changed since the manifest was written" in why, why[:200])
    DB.manifest_path("h1").unlink()
    pf.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    old_b = DB.build("b33")
    ok("F: an old batch has no rows file in its build, and its manifest check is as before", "rows_in" not in old_b
       and "rows_in" not in DB.open_manifest("b33", old_b, {"key": "k"}, lambda m: None, aux={}))

    DB._ALLOW_NON_LINUX = True
    saved = (DB.disk_free_gib, DB.femur_geom_key, DB.aux_md5)
    DB.disk_free_gib, DB.femur_geom_key, DB.aux_md5 = (lambda p=None: 100.0), (lambda: {"key": "k"}), (lambda: {})
    try:
        calls = []

        def edit_then_stop(s):
            calls.append(s)
            if len(calls) == 1:
                pf.write_text(json.dumps({**doc, "note": "edited while feeding"}, indent=1), encoding="utf-8")
            elif len(calls) > 3:
                (root / DB.STOP_NAME).write_text("")

        with contextlib.redirect_stdout(io.StringIO()):
            why = refused(lambda: DB.feed("h1", poll=0, sleep=edit_then_stop))
        man2 = json.loads(DB.manifest_path("h1").read_text(encoding="utf-8")) if DB.manifest_path("h1").exists() else {}
        ok("F: a rows file edited while the feeder runs stops it on the next pass, and the manifest records the halt",
           "rows_in.json changed or disappeared while feeding" in why and any(e.get("event") == "halt" for e in man2.get("events", [])) and len(calls) <= 2,
           f"{why[:200]} calls {len(calls)}")
        submitted = sorted(d.name for d in J.QROOT.iterdir() if d.name.startswith("db_cd_") and "F1714" in d.name or "F3839" in d.name)
        ok("F: before the halt the first pass submitted the two rows with the expected ids", submitted == sorted(r["expected_id"] for r in b["rows"]), str(submitted))
    finally:
        DB._ALLOW_NON_LINUX = False
        DB.disk_free_gib, DB.femur_geom_key, DB.aux_md5 = saved

    # ---------------------------------------------------------------- H
    # The real row files of the repository: built here (Windows, the fake queue) they give the job ids frozen from the Linux dry run.
    queue("real_files")
    DB.ROWS_IN_ROOT = REAL_ROWS
    n_real = 0
    for ri in sorted(EXP.glob("b*_*/rows_in.json")):
        fz = ri.parent / "rows.json"
        doc = json.loads(ri.read_text(encoding="utf-8"))
        absent = [r["base"] for r in doc.get("rows", []) if "base" in r and not (J.QROOT / r["base"] / "spec.json").exists()]
        if not fz.exists() or absent:
            print(f"SKIP H: {ri.parent.name}: " + ("no frozen rows.json yet" if not fz.exists() else f"base rows not in the local fake queue {absent[:2]}"), flush=True)
            continue
        b_real = DB.build(doc["batch"])
        got = {r["key"]: r["expected_id"] for r in b_real["rows"]}
        want = {r["label"]: r["job_id"] for r in json.loads(fz.read_text(encoding="utf-8"))["rows"]}
        n_real += 1
        ok(f"H: {ri.parent.name}: its row file builds on Windows the {len(want)} job ids frozen from the Linux dry run; the sha256 is that of the file",
           got == want and len(want) > 0 and b_real["rows_in"]["sha256"] == DB.rows_in_sha256(doc["batch"]),
           str({k: (got.get(k), v) for k, v in want.items() if got.get(k) != v})[:300] + f" problems {b_real['problems'][:2]}")
    ok("H: b34 (the first row-file batch of the repository) was among them", n_real >= 1 or not (EXP / "b34_r2sts" / "rows.json").exists(), str(n_real))
finally:
    J.QROOT, J.RESULTS, DB.ROWS_IN_ROOT = REAL_Q, REAL_R, REAL_ROWS
    shutil.rmtree(BASE, ignore_errors=True)

n_fail = sum(not c for _, c in checks)
print(f"{len(checks) - n_fail}/{len(checks)} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
