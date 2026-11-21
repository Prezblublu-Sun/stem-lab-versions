"""Independent check of the b1b expected ids (does not import stage_db): for each of the 24 FD-0 pilot designs take b1's source job
spec, keep its physical keys, set kind variant / stage db_fd / h_int 2.4 / intact_job = the h 2.4 reference, and hash with jobs.job_id.
Compares with the DRY-RUN-JSON of `stage_db.py dry-run b1b` (path argv[1]). Run on Linux: cd ~/mobo_toy_v2/code && ../run.sh <this> <dry.txt>"""
import json
import sys

sys.path.insert(0, "v2")
import jobs as J  # noqa: E402

DROP = {"created", "stage", "tag", "kind", "bond_only", "fric_only", "intact_job", "gate", "source_job", "load_case", "deck_code", "ofat",
        "jitter", "collar_w_original"}
txt = open(sys.argv[1], encoding="utf-8").read()
dj = json.loads(txt[txt.index("DRY-RUN-JSON") + len("DRY-RUN-JSON"):].strip().lstrip(":").strip())
rows = dj["jobs"]
ref = {"h_int": 2.4, "femur_id": "sawbone3406", "neck_axis": "isthmus", "kind": "intact", "stage": "db_ref", "tag": "intact_h2.4"}
ref_id = J.job_id({**ref, "created": "x"})
man1 = json.load(open(str(J.RESULTS / "db_manifest_b1.json")))
n_ok, bad = 0, []
for r in rows:
    key = r["key"]
    if r["layer"] == "REF":
        print(key, r["expected_id"], "independent", ref_id, "OK" if r["expected_id"] == ref_id else "DIFF")
        n_ok += r["expected_id"] == ref_id
        continue
    c = key.split("_", 2)[2]
    src = man1["rows"][f"FD0_h2.5_{c}"]["source_job"]
    s = json.loads((J.QROOT / src / "spec.json").read_text())
    unknown = sorted(k for k in s if k in DROP and k not in ("created", "stage", "tag", "kind", "bond_only", "fric_only", "intact_job"))
    phys = {k: v for k, v in s.items() if k not in DROP}
    spec = {**phys, "kind": "variant", "stage": "db_fd", "tag": "x", "h_int": 2.4, "intact_job": ref_id, "created": "x"}
    jid = J.job_id(spec)
    ok = jid == r["expected_id"]
    n_ok += ok
    if not ok:
        bad.append((key, r["expected_id"], jid, unknown))
    print(key, src, r["expected_id"], "OK" if ok else f"DIFF independent {jid} (meta keys dropped {unknown})")
print(f"{n_ok}/{len(rows)} equal; bad {bad}")
