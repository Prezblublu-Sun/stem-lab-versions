#!/usr/bin/env python3
"""db3406 automatic checks (plan 3406数据库规划 section 1.8, the 14 checks; D5). numpy + csv + json only.

    python tools/db_qa.py --db "H:/projects/Femoral implant generation/db3406/v0.1"   [--json-out qa_report.json] [--max-list 30]

Reads <db>/scalars.csv, <db>/schema.json, <db>/fields/*.npz, <db>/femur_registry.json, <db>/jobs.txt + jobs_inventory.json (the
frozen job list, when the version was cut from one) and <db>/export/<batch>/{inventory,exclusion,context}.json written by
tools/db_export.py (quarantined / replaced batch dirs, i.e. names with a dot, are ignored). Every check prints PASS / FAIL / WARN / N/A
with the offending rows listed; nothing is silently skipped (a check that cannot run because its inputs are missing is a FAIL, not a
pass). Exit code 1 if any check FAILs.
Independent recomputations (not the exporter's flags): 2 re-aggregation from the shards (incl. foam thickness), 6 force balance from the
shard, 11 replicate groups (friction / bonded) + the 11 inventory pairs, 12 the unbiased filter in both directions, 13 every bonded row
against the reference's own row (prep-level E_canc, h_roi / h_int, h_far, load_N).
The re-aggregation (check 2) uses db_export.reaggregate, whose arithmetic is tested against stability.rigid_fit and
qoi.wquantile in tools/tests/test_db_tools.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db_export as DX  # noqa: E402

FORCE_TOL = 1e-3          # |sum of bone-side contact forces - applied load| / |load| (measured ~1e-7 on 3406 jobs)
H_PROD = 2.0
ENUMS = {"status": {"DONE", "FAILED", "SOLVED", "CLAIMED", "READY", "NEW", "MISSING"}, "kind": {"design", "variant", "intact"},
         "selection": set(DX.SELECTIONS), "split": {"train", "val", "test"}, "export_status": {"ok", "error"},
         "bounds_version": {"v1", "v2"}, "femur_geom_basis": {"files_older_than_prep", "registry", "no_prep"}}


def parse(cell: str, typ: str):
    if cell == "":
        return None
    if typ == "float":
        return float(cell)
    if typ == "int":
        return int(cell)
    if typ == "bool":
        if cell not in ("true", "false"):
            raise ValueError(f"bool cell {cell!r}")
        return cell == "true"
    if typ == "json":
        return json.loads(cell)
    return cell


class QA:
    def __init__(self, db: pathlib.Path, max_list: int = 30):
        self.db, self.max_list = db, max_list
        self.results = []
        self.schema = json.loads((db / "schema.json").read_text(encoding="utf-8"))
        self.cols = {c["name"]: c for c in self.schema["columns"]}
        with open(db / "scalars.csv", newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            self.header = next(rd)
            self.raw = [dict(zip(self.header, r)) for r in rd]
        self.rows, self.parse_errors = [], []
        for r in self.raw:
            t = {}
            for k, v in r.items():
                c = self.cols.get(k)
                try:
                    t[k] = parse(v, c["type"]) if c else v
                except Exception as e:  # noqa: BLE001
                    self.parse_errors.append(f"{r.get('job_id')}: {k}={v!r}: {e}")
                    t[k] = None
            self.rows.append(t)
        self.by_job = {r["job_id"]: r for r in self.rows}
        self.batches = DX.batch_dirs(db)[0] if (db / "export").exists() else []      # dotted dirs (.BAD, .replaced.) skipped
        self._shards = {}

    # -------------------------------------------------------------- helpers
    def add(self, cid: int, name: str, status: str, failures: list, info=None, n_checked: int | None = None):
        self.results.append({"id": cid, "name": name, "status": status, "n_failures": len(failures), "failures": failures,
                             "info": info, "n_checked": n_checked})

    def shard(self, name: str) -> dict:
        if name not in self._shards:
            self._shards[name] = dict(np.load(self.db / "fields" / f"{name}.npz", allow_pickle=False))
        return self._shards[name]

    def req_applies(self, req: str, r: dict) -> bool:
        st, kind = r.get("status"), r.get("kind")
        dv = kind in ("design", "variant")
        return {"always": True, "spec": st != "MISSING", "design": dv, "prep": bool(r.get("has_prep")) and dv, "done": st == "DONE",
                "fric": st == "DONE" and dv and bool(r.get("has_fric_model")),
                "bond": st == "DONE" and dv and bool(r.get("has_bond_model")), "intact": st == "DONE" and kind == "intact"}.get(req, False)

    # -------------------------------------------------------------- 1
    def c1_types(self):
        f = list(self.parse_errors)
        names = [c["name"] for c in self.schema["columns"]]
        if self.header != names:
            miss = [n for n in names if n not in self.header]
            extra = [n for n in self.header if n not in names]
            f.append(f"header differs from schema: missing {miss[:20]}, extra {extra[:20]}, order equal {self.header == names}")
        for c in self.schema["columns"]:
            if c["type"] in ("float", "int") and c["required"] != "reserved" and not c.get("unit"):
                f.append(f"schema: numeric column {c['name']} has no unit")
            for k in ("type", "unit", "range", "source", "required"):
                if k not in c:
                    f.append(f"schema: column {c['name']} lacks {k!r}")
        for r in self.rows:
            j = r.get("job_id")
            if r.get("export_status") == "error":
                f.append(f"{j}: export errors {r.get('export_errors')}")
            for c in self.schema["columns"]:
                k, v, req = c["name"], r.get(c["name"]), c["required"]
                applies = self.req_applies(req, r) if req in ("always", "spec", "design", "prep", "done", "fric", "bond", "intact") else False
                if applies and v is None:
                    f.append(f"{j}: {k} empty (required: {req})")
                if req in ("fric", "bond") and v is not None and not applies:
                    f.append(f"{j}: {k} filled although the row is {r.get('status')} / fric {r.get('has_fric_model')} / bond {r.get('has_bond_model')} (labels must be empty)")
                if v is None:
                    continue
                if k in ENUMS and v not in ENUMS[k]:
                    f.append(f"{j}: {k}={v!r} not in {sorted(ENUMS[k])}")
                if c["type"] in ("float", "int"):
                    x = float(v)
                    if math.isnan(x):
                        if req != "optional":
                            f.append(f"{j}: {k} is NaN (required: {req})")
                        continue
                    lo, hi = c["range"]
                    if (lo is not None and x < lo) or (hi is not None and x > hi):
                        f.append(f"{j}: {k}={x!r} outside [{lo}, {hi}] {c.get('unit', '')}")
        self.add(1, "column types, units, ranges, required / empty labels", "FAIL" if f else "PASS", f, n_checked=len(self.rows))

    # -------------------------------------------------------------- 2
    def c2_fields(self):
        f, mx, n = [], {k: 0.0 for k in DX.REAGG_REF}, 0
        for r in self.rows:
            j = r["job_id"]
            if not self.req_applies("fric", r):
                if r.get("field_shard"):
                    f.append(f"{j}: has a field shard but is not a DONE friction row")
                continue
            if not r.get("field_shard"):
                f.append(f"{j}: DONE friction row without a point cloud")
                continue
            try:
                sh = self.shard(r["field_shard"])
            except Exception as e:  # noqa: BLE001
                f.append(f"{j}: shard {r['field_shard']} unreadable: {e}")
                continue
            i = r["field_index"]
            if not (0 <= i < len(sh["job_id"])) or str(sh["job_id"][i]) != j:
                f.append(f"{j}: shard {r['field_shard']}[{i}] holds {sh['job_id'][i] if 0 <= i < len(sh['job_id']) else None}")
                continue
            a, b = int(sh["off"][i]), int(sh["off"][i + 1])
            if b - a != r.get("field_n_nodes"):
                f.append(f"{j}: shard has {b - a} nodes, row says {r.get('field_n_nodes')}")
            for k in ("X", "nrm", "area", "interf", "rel", "cpress", "gap", "cforce", "loc"):
                if len(sh[k]) != int(sh["off"][-1]):
                    f.append(f"{r['field_shard']}: per-node array {k} length {len(sh[k])} != off[-1] {int(sh['off'][-1])}")
            t0, t1 = int(sh["tri_off"][i]), int(sh["tri_off"][i + 1])
            T = sh["tri"][t0:t1]
            if len(T) and (T.min() < 0 or T.max() >= b - a):
                f.append(f"{j}: triangle indices outside the job's node range")
            chk = DX.reaggregate(sh, i)
            n += 1
            for k, ref in DX.REAGG_REF.items():
                e = DX.rel_err(chk[k], r.get(ref))
                mx[k] = max(mx[k], e) if e == e else float("nan")
                if not (e <= DX.REAGG_TOL):
                    f.append(f"{j}: {k} re-aggregated {chk[k]!r} vs scalar {ref}={r.get(ref)!r}: rel err {e:.3g} > {DX.REAGG_TOL:g}")
        info = {"max_rel_err": mx, "n_point_clouds": n, "canonical_grid": "not built in this version (96 x 64 (s, theta) grid is a later step); no grid error to report"}
        self.add(2, "point cloud re-aggregation (rotation, contact LOAD / LOAD2, micromotion) <= 1e-6", "FAIL" if f or n == 0 else "PASS",
                 f + ([] if n else ["no point clouds to check"]), info, n)

    # -------------------------------------------------------------- 3
    def c3_code(self):
        f, info = [], {}
        hashes = {}
        for r in self.rows:
            hashes.setdefault(r.get("code_hash") or "<empty>", []).append(r["job_id"])
            if r.get("job_id_matches_code") is False:
                f.append(f"{r['job_id']}: job id does not recompute under code_hash_now {r.get('code_hash_now')}")
        info["code_hash_groups"] = {k: len(v) for k, v in hashes.items()}
        for k, v in hashes.items():
            if k != DX.EXPECTED_CODE_HASH:
                f.append(f"code_hash {k}: {len(v)} rows (expected {DX.EXPECTED_CODE_HASH}) e.g. {v[:5]}")
        aux = {}
        for r in self.rows:
            aux.setdefault(r.get("aux_code_md5"), []).append(r["job_id"])
        info["aux_code_md5_groups"] = {k: len(v) for k, v in aux.items()}
        ctx_hashed = set()
        for b in self.batches:
            p = b / "context.json"
            if not p.exists():
                f.append(f"batch {b.name}: context.json missing")
                continue
            c = json.loads(p.read_text())
            ctx_hashed.add(json.dumps(c.get("hashed_files_md5"), sort_keys=True))
            info.setdefault("aux_files_md5", {})[b.name] = c.get("aux_files_md5")
        if len(ctx_hashed) > 1:
            f.append(f"hashed files differ between batches: {len(ctx_hashed)} variants")
        st = "FAIL" if f else ("WARN" if len(aux) > 1 else "PASS")
        self.add(3, "code_hash consistent; aux_code_md5 consistent or grouped", st, f, info, len(self.rows))

    # -------------------------------------------------------------- 4
    def c4_femur(self):
        f = []
        keys, basis = {}, {}
        for r in self.rows:
            if r.get("femur_id") == DX.FEMUR_ID:
                keys.setdefault((r.get("femur_geom_key"), r.get("femur_model_version")), []).append(r["job_id"])
            else:
                f.append(f"{r['job_id']}: femur_id {r.get('femur_id')!r}")
            if r.get("has_prep") and r.get("femur_pose_match") is not True:
                f.append(f"{r['job_id']}: femur pose at export differs from prep time (dev {r.get('femur_pose_dev_mm')})")
            basis[r.get("femur_geom_basis")] = basis.get(r.get("femur_geom_basis"), 0) + 1
            if r.get("has_prep") and r.get("femur_geom_verified") is not True:   # plan 1.6 trap 3: key bound to job time
                f.append(f"{r['job_id']}: femur_geom_key not bound to job time (femur_geom_verified {r.get('femur_geom_verified')}, "
                         f"basis {r.get('femur_geom_basis')!r})")
        if len(keys) != 1:
            f.append(f"{len(keys)} (femur_geom_key, femur_model_version) groups: {[(k[0][:12] if k[0] else k[0], k[1], len(v)) for k, v in keys.items()]}")
        # the db-level registry (copied into the version dir by finalize): one key per femur_id, rows inside its windows
        info = {"groups": {f"{(k[0] or '')[:16]}|{k[1]}": len(v) for k, v in keys.items()}, "basis": basis}
        rp = self.db / "femur_registry.json"
        if not rp.exists():
            f.append("femur_registry.json missing in the version dir (finalize writes it)")
        else:
            reg = json.loads(rp.read_text(encoding="utf-8"))
            fem = reg.get("femurs") or {}
            info["registry"] = {k: {"key": v.get("femur_geom_key"), "windows": v.get("windows")} for k, v in fem.items()}
            for r in self.rows:
                fid = r.get("femur_id")
                if not fid:
                    continue
                ent = fem.get(fid)
                if ent is None:
                    f.append(f"{r['job_id']}: femur_id {fid} is not in femur_registry.json")
                    continue
                if r.get("femur_geom_key") != ent.get("femur_geom_key"):
                    f.append(f"{r['job_id']}: femur_geom_key {r.get('femur_geom_key')} != registered {ent.get('femur_geom_key')} "
                             f"for {fid} (new geometry needs a new femur_id)")
                if r.get("femur_geom_basis") == "registry":
                    tp = r.get("t_prep_utc")
                    if not (tp and any(w[0] < tp <= w[1] for w in ent.get("windows") or [])):
                        f.append(f"{r['job_id']}: basis registry but t_prep_utc {tp} is outside every window {ent.get('windows')}")
        self.add(4, "femur_geom_key consistent, registered and bound to job time (job-time femur pose reproduced)",
                 "FAIL" if f else "PASS", f, info, len(self.rows))

    # -------------------------------------------------------------- 5
    def c5_cortex(self):
        f, flagged, n = [], [], 0
        for r in self.rows:
            if r.get("m") is None or r.get("n_pairs_cortex") is None:
                continue
            n += 1
            if r["m"] >= 0.5 - 1e-12 and r["n_pairs_cortex"] != 0:
                (flagged if r.get("pose") else f).append(f"{r['job_id']}: m {r['m']:.4f} >= 0.5 but n_pairs_cortex {r['n_pairs_cortex']}")
        self.add(5, "m >= 0.5 => no cortical interface pairs (pose rows flagged separately)", "FAIL" if f else "PASS", f,
                 {"pose_rows_flagged": flagged}, n)

    # -------------------------------------------------------------- 6
    def c6_force(self):
        f, mx, n = [], 0.0, 0
        for r in self.rows:
            if not self.req_applies("fric", r):
                continue
            j = r["job_id"]
            e = r.get("iface_force_err_load")
            if e is None:
                f.append(f"{j}: no interface force (LOAD_CFORCE.csv missing?)")
                continue
            n += 1
            mx = max(mx, e, r.get("iface_force_err_load2") or 0.0)
            if e > FORCE_TOL or (r.get("iface_force_err_load2") or 0.0) > FORCE_TOL:
                f.append(f"{j}: |sum F - load| / |load| = {e:.3g} (LOAD), {r.get('iface_force_err_load2')} (LOAD2) > {FORCE_TOL}")
            if r.get("field_shard"):                                   # independent recomputation from the stored point cloud
                sh = self.shard(r["field_shard"])
                i = r["field_index"]
                a, b = int(sh["off"][i]), int(sh["off"][i + 1])
                F = sh["cforce"][a:b, 0].astype(np.float64).sum(0)
                L = sh["load_vec"][i]
                e2 = float(np.linalg.norm(F - L) / np.linalg.norm(L))
                if not (e2 <= FORCE_TOL):
                    f.append(f"{j}: shard force balance {e2:.3g} > {FORCE_TOL}")
        self.add(6, "sum of interface contact forces = applied load", "FAIL" if f or n == 0 else "PASS",
                 f + ([] if n else ["no friction rows"]), {"max_rel_err": mx, "tol": FORCE_TOL}, n)

    # -------------------------------------------------------------- 7
    def c7_conditions(self):
        f, n = [], 0
        for r in self.rows:
            j = r["job_id"]
            for k in ("cons_delta", "cons_load", "cons_h_int", "spec_in_result_match"):
                if r.get(k) is False:
                    f.append(f"{j}: {k} is false")
            if r.get("has_prep") and r.get("kind") in ("design", "variant"):
                n += 1
                for k in ("cons_delta", "cons_load", "cons_h_int"):
                    if r.get(k) is None:
                        f.append(f"{j}: {k} not evaluated")
                ds, dm = r.get("delta_spec_mm"), r.get("delta_mm")
                if ds is not None and dm is not None and abs(ds - dm) > 1e-12:
                    f.append(f"{j}: spec delta {ds} != prep delta {dm}")
                lv = r.get("load_vec_N")
                if lv is not None and r.get("load_R_N") is not None:
                    if abs(float(np.linalg.norm(lv)) - r["load_R_N"]) > 1e-6 * r["load_R_N"]:
                        f.append(f"{j}: |load_N| {np.linalg.norm(lv)} != load_R_N {r['load_R_N']}")
        self.add(7, "spec delta / load agree with prep / result", "FAIL" if f else "PASS", f, None, n)

    # -------------------------------------------------------------- 8
    def c8_failures(self):
        f, info = [], {}
        if not self.batches:
            self.add(8, "failed rows present; failure rate per stratum", "FAIL", ["no export batches (inventory missing)"])
            return
        selected, inv_all, live, explicit, frozen_sha = set(), {}, [], [], set()
        for b in self.batches:
            p = b / "inventory.json"
            if not p.exists():
                f.append(f"batch {b.name}: inventory.json missing")
                continue
            iv = json.loads(p.read_text())
            selected |= set(iv.get("selected", []))
            for j, v in (iv.get("jobs") or {}).items():               # union inventory (the latest state seen wins)
                inv_all[j] = v
            sa = iv.get("selection_args") or {}
            if sa.get("frozen_list_sha256"):
                frozen_sha.add(sa["frozen_list_sha256"])
            elif sa.get("jobs"):
                explicit.append(b.name)
            else:
                live.append(b.name)
        for j in sorted(selected):
            r = self.by_job.get(j)
            if r is None:
                f.append(f"{j}: selected for export but has no row")
                continue
            st = inv_all.get(j, {}).get("state")
            if st == "FAILED" and r.get("status") != "FAILED":
                f.append(f"{j}: FAILED in the queue but row status {r.get('status')}")
        fin = lambda inv: sorted(j for j, v in inv.items() if v.get("state") in ("DONE", "FAILED"))  # noqa: E731
        fl = self.db / "jobs_inventory.json"
        if fl.exists():                                                # frozen job list (pull --list-only): the version's scope
            fz = json.loads(fl.read_text())
            jt = self.db / "jobs.txt"
            sha = DX.hashlib.sha256(jt.read_bytes()).hexdigest() if jt.exists() else None
            if sha != fz.get("jobs_txt_sha256"):
                f.append(f"jobs.txt sha256 {sha} != jobs_inventory.json {fz.get('jobs_txt_sha256')} (frozen list changed or missing)")
            listed = set(fz.get("jobs") or [])
            finv = {j: v for j, v in (fz.get("inventory") or {}).items() if j in listed}
            miss = [j for j in fin(finv) if j not in self.by_job]
            if miss:
                f.append(f"{len(miss)} DONE / FAILED jobs of the frozen list have no row: {miss[:30]}")
            for j in fin(finv):
                r = self.by_job.get(j)
                if r is not None and r.get("status") != finv[j]["state"]:
                    f.append(f"{j}: {finv[j]['state']} in the frozen list but row status {r.get('status')}")
            extra = sorted(set(self.by_job) - listed)
            if extra:
                f.append(f"{len(extra)} rows are not in the frozen list: {extra[:30]}")
            bad_b = [s for s in frozen_sha if s != fz.get("jobs_txt_sha256")]
            if bad_b or live or explicit:
                f.append(f"batches not cut from this frozen list: other lists {bad_b}, live --select-3406 {live}, explicit --jobs {explicit}")
            unl = [j for j in fin(fz.get("inventory") or {}) if j not in listed]
            info["frozen_list"] = {"n_jobs": len(listed), "listed_utc": fz.get("listed_utc"), "filter": fz.get("filter"),
                                   "finished_in_queue_but_not_listed": unl[:50], "n_finished_not_listed": len(unl)}
            info["coverage"] = f"frozen list: {len(listed)} jobs, {len(fin(finv))} finished"
        elif live:                                                     # live --select-3406 batches: every finished job must be there
            miss = [j for j in fin(inv_all) if j not in self.by_job]
            if miss:
                f.append(f"{len(miss)} DONE / FAILED 3406 jobs of the union inventory have no row (live --select-3406 batches "
                         f"{live} without a frozen list): {miss[:30]}")
            info["coverage"] = f"live --select-3406 batches {live}; union inventory {len(inv_all)} job dirs"
        else:
            info["coverage"] = f"explicit --jobs subset: {len(selected)} of {len(inv_all)} 3406 job dirs (no frozen list)"
        n_failed_inv = sorted(j for j, v in inv_all.items() if v.get("state") == "FAILED")
        info["failed_in_queue"] = n_failed_inv
        info["failed_in_queue_without_row"] = [j for j in n_failed_inv if j not in self.by_job]
        rate = {}
        for r in self.rows:
            s = r.get("source") or "?"
            d = rate.setdefault(s, {"n": 0, "failed": 0, "levels": {}})
            d["n"] += 1
            if r.get("status") == "FAILED":
                d["failed"] += 1
                lv = r.get("fail_level") or "?"
                d["levels"][lv] = d["levels"].get(lv, 0) + 1
        for d in rate.values():
            d["rate"] = d["failed"] / d["n"]
        info["failure_rate_by_source"] = rate
        subset = info["coverage"].startswith("explicit")
        self.add(8, "failed rows present (frozen job list complete); failure rate per stratum",
                 "FAIL" if f else ("WARN" if subset else "PASS"), f, info, len(selected))

    # -------------------------------------------------------------- 9
    def c9_split(self):
        f, sp = [], {}
        for r in self.rows:
            dk = r.get("design_key")
            if not dk:
                continue
            sp.setdefault(dk, set()).add(r.get("split"))
            b, s = DX.split_of(dk)
            if r.get("split") != s or r.get("split_bucket") != b:
                f.append(f"{r['job_id']}: split {r.get('split')}/{r.get('split_bucket')} != rule {s}/{b}")
        for dk, s in sp.items():
            if len(s) > 1:
                f.append(f"design {dk[:12]} in splits {sorted(map(str, s))}")
        cnt = {}
        for r in self.rows:
            cnt[r.get("split")] = cnt.get(r.get("split"), 0) + 1
        self.add(9, "no split leakage (one split per design_key)", "FAIL" if f else "PASS", f, {"rows_per_split": cnt,
                 "n_design_keys": len(sp)}, len(sp))

    # -------------------------------------------------------------- 10
    def c10_adaptive(self):
        n = len(self.rows)
        by = {}
        for r in self.rows:
            by[r.get("selection")] = by.get(r.get("selection"), 0) + 1
        fr = by.get("adaptive", 0) / n if n else float("nan")
        unb = sum(1 for r in self.rows if r.get("unbiased"))
        self.add(10, "adaptive share reported", "PASS", [], {"by_selection": by, "adaptive_fraction": fr, "n_unbiased": unb}, n)

    # -------------------------------------------------------------- 11
    # the 11 replicate groups of the 2026-10-25 inventory (plan 2.3; plan_db/d_inventory/dup_check_out.txt): same geometry and
    # condition, friction model. Whenever both members are in the database they must share one FRICTION replicate group.
    KNOWN_REPLICATES = (("sb11_smoke_b_h20_ea753c63", "sb11_smoke_f_h20_da62abd1"), ("sb13_a33_016e3ffa", "sb14_a2_016e3ffa"),
                        ("sb13_a35_2ca49a9e", "sb14_a4_d03cacaf"), ("sb13_init_05165065", "v3406_dx_c742b510_d0.1_a539b815"),
                        ("sb13_init_0abe8218", "v3406_dx_862b8fd2_d0.1_0ba5d637"), ("sb13_init_2943f28a", "v3406_dx_e07019d5_d0.1_cd27c658"),
                        ("sb13_init_39fd3724", "v3406_dx_a02759d3_d0.1_bd0ea75f"), ("sb13_init_c3782ec3", "v3406_dx_6c4e8053_d0.1_dad5b7e8"),
                        ("sb13_init_cd806312", "v3406_dx_b419afc2_d0.1_2cc12115"), ("sb13_init_ce80becf", "v3406_dx_5feb1d8a_d0.1_ae01c1d6"),
                        ("sb13_init_f62504b5", "v3406_delta_init07cb_d0.1_1d3ce21f"))
    LABEL_COLS = ("rot_first_deg", "contact_area_load2_mm2", "f1_p95_um")

    def c11_duplicates(self):
        """Own grouping (not db_export's): friction replicates = DONE + has_fric_model with equal (realization_key, cond_key,
        fidelity); bonded replicates = DONE + has_bond_model with equal (realization_key, cond_key, fidelity, intact_job)."""
        f, info = [], {}
        for kind, model, cg, co, extra in (("fric", "has_fric_model", "replicate_group", "replicate_of", ()),
                                           ("bond", "has_bond_model", "replicate_group_bond", "replicate_of_bond", ("intact_job",))):
            groups = {}
            for r in self.rows:
                if r.get("status") == "DONE" and r.get(model) and r.get("realization_key"):
                    k = (r["realization_key"], r.get("cond_key"), r.get("fidelity")) + tuple(r.get(x) for x in extra)
                    groups.setdefault(k, []).append(r)
            dup = {k: rs for k, rs in groups.items() if len(rs) > 1}
            in_dup = {r["job_id"] for rs in dup.values() for r in rs}
            spread = {}
            for k, rs in dup.items():
                gids = {r.get(cg) for r in rs}
                if len(gids) != 1 or None in gids:
                    f.append(f"{kind} replicates {[r['job_id'] for r in rs]} not flagged as one group ({cg} {sorted(map(str, gids))})")
                    continue
                first = sorted(rs, key=lambda r: (r.get("t_done_utc") or "9999", r["job_id"]))[0]["job_id"]
                for r in rs:
                    want = None if r["job_id"] == first else first
                    if r.get(co) != want:
                        f.append(f"{r['job_id']}: {co} {r.get(co)!r}, expected {want!r} (earliest DONE of the {kind} group)")
                if kind == "fric":                                      # the solver is deterministic on one mesh: report spread
                    for c in self.LABEL_COLS:
                        v = [r.get(c) for r in rs if r.get(c) is not None]
                        if len(v) > 1:
                            spread[c] = max(spread.get(c, 0.0), (max(v) - min(v)) / max(abs(max(v)), 1e-12))
            for r in self.rows:
                if r.get(cg) and r["job_id"] not in in_dup:
                    f.append(f"{r['job_id']}: {cg} {r[cg]} set but the row has no {kind} replicate")
            info[kind] = {"n_groups": len(dup), "groups": [[r["job_id"] for r in rs] for rs in dup.values()]}
            if kind == "fric":
                info[kind]["max_rel_label_spread"] = spread
        rows = self.by_job
        known = []
        for a, b in self.KNOWN_REPLICATES:
            if a in rows and b in rows:
                ok = rows[a].get("replicate_group") is not None and rows[a].get("replicate_group") == rows[b].get("replicate_group")
                known.append({"pair": [a, b], "same_friction_group": ok})
                if not ok:
                    f.append(f"inventory replicate pair {a} / {b} is not one friction replicate group "
                             f"({rows[a].get('replicate_group')!r} / {rows[b].get('replicate_group')!r})")
        info["known_inventory_pairs_present"] = len(known)
        info["known_inventory_pairs"] = known
        self.add(11, "repeated (realization, condition, fidelity) flagged, not deleted (friction and bonded separately)",
                 "FAIL" if f else "PASS", f, info, len(self.rows))

    # -------------------------------------------------------------- 12
    def c12_unbiased(self):
        f = []
        E, arm = set(), set()
        if not self.batches:
            f.append("no export batches (exclusion.json missing)")
        for b in self.batches:
            p = b / "exclusion.json"
            if not p.exists():
                f.append(f"batch {b.name}: exclusion.json missing")
                continue
            ex = json.loads(p.read_text())
            E |= set(ex["design_keys"])
            arm |= {dk for dk, js in ex["design_keys"].items() if any(str(j).startswith(("sb13_a", "sb14_a")) for j in js)}
        # recomputed here from the rows' own selection columns (plan 1.4), independent of the exporter's flags ...
        for r in self.rows:
            dk, src = r.get("design_key"), str(r.get("source") or "")
            if not dk:
                continue
            if src in DX.E_SOURCES or (src.startswith("al") and r.get("selection") != "iid"):
                E.add(dk)
            if src in DX.ARM_SOURCES:
                arm.add(dk)
        # ... plus provenance-file in_E flags (finalize --provenance), which only the exporter sees
        E |= {r["design_key"] for r in self.rows if r.get("in_E") and r.get("design_key")}
        n_exp = 0
        for r in self.rows:
            j, dk = r["job_id"], r.get("design_key")
            ov = bool(dk and r.get("source") == "sf" and dk in arm)
            expected = bool(r.get("selection") == "iid" and dk and dk not in E and not ov)
            n_exp += expected
            if bool(r.get("unbiased")) != expected:                     # BOTH directions: wrongly set and wrongly cleared
                f.append(f"{j}: unbiased {r.get('unbiased')} but the plan 1.4 filter gives {expected} (selection {r.get('selection')}, "
                         f"in E {dk in E if dk else None}, sf_bo_overlap {ov})")
            if bool(r.get("sf_bo_overlap")) != ov:
                f.append(f"{j}: sf_bo_overlap {r.get('sf_bo_overlap')} but recomputed {ov}")
            if dk and (dk in E) != bool(r.get("in_E")):
                f.append(f"{j}: in_E {r.get('in_E')} but design_key {'is' if dk in E else 'is not'} in E")
            if r.get("sf_bo_overlap") and r.get("split") == "train" and r.get("unbiased"):
                f.append(f"{j}: overlap design in the unbiased training set")
            if bool(r.get("test_iid")) != bool(expected and r.get("split") == "test"):
                f.append(f"{j}: test_iid {r.get('test_iid')} but unbiased {expected} / split {r.get('split')}")
        self.add(12, "unbiased = iid and not in E and not sf_bo_overlap (recomputed, both directions); E and unbiased disjoint",
                 "FAIL" if f else "PASS", f,
                 {"n_E": len(E), "n_unbiased": sum(1 for r in self.rows if r.get("unbiased")), "n_unbiased_expected": n_exp},
                 len(self.rows))

    # -------------------------------------------------------------- 13
    def c13_ref(self):
        """Exporter's ref_match AND an independent comparison of the reference's own row (it must be in this version):
        femur_id, femur_geom_key, neck_axis, spec h_int, prep-level E_canc, h_roi (ref) vs h_int (row), h_far, load_N (1e-9);
        result.json intact_job == spec intact_job."""
        f, n, n_indep = [], 0, 0
        for r in self.rows:
            if not self.req_applies("bond", r):
                continue
            n += 1
            j = r["job_id"]
            if r.get("ref_match") is not True:
                f.append(f"{j}: ref_match {r.get('ref_match')} {r.get('ref_mismatch')}")
            if r.get("sed_chg_pct") is None:
                f.append(f"{j}: bonded row without the G7 cortex SED label ({r.get('calcar_error')})")
            rid = r.get("intact_job")
            if rid != r.get("intact_job_spec"):
                f.append(f"{j}: result.json intact_job {rid!r} != spec intact_job {r.get('intact_job_spec')!r}")
            ref = self.by_job.get(rid)
            if ref is None:
                f.append(f"{j}: reference {rid!r} has no row in this version (cannot check it independently)")
                continue
            n_indep += 1
            if ref.get("kind") != "intact" or ref.get("status") != "DONE":
                f.append(f"{j}: reference {rid} is kind {ref.get('kind')} / {ref.get('status')}")
            for c in ("femur_id", "femur_geom_key", "femur_model_version"):
                if ref.get(c) != r.get(c):
                    f.append(f"{j}: {c} ref {ref.get(c)!r} vs row {r.get(c)!r}")
            if json.dumps(ref.get("neck_axis"), sort_keys=True) != json.dumps(r.get("neck_axis"), sort_keys=True):
                f.append(f"{j}: neck_axis ref {ref.get('neck_axis')!r} vs row {r.get('neck_axis')!r}")
            for c in ("h_int_mm", "h_int_prep_mm", "E_canc_MPa", "h_far_mm", "load_R_N", "alpha_front_deg", "alpha_sagit_deg"):
                a, b = ref.get(c), r.get(c)
                if a is None or b is None or abs(float(a) - float(b)) > 1e-9:
                    f.append(f"{j}: {c} ref {a!r} vs row {b!r}")
            la, lb = ref.get("load_vec_N"), r.get("load_vec_N")
            if la is None or lb is None or float(np.max(np.abs(np.subtract(la, lb)))) > 1e-9 * max(1.0, float(np.linalg.norm(la))):
                f.append(f"{j}: prep load_N ref {la!r} vs row {lb!r}")
        self.add(13, "bonded rows: intact reference matches (femur, geometry, neck axis, h_int / h_roi, E_canc, h_far, load_N)",
                 "FAIL" if f else ("PASS" if n else "N/A"), f, {"n_checked_against_ref_row": n_indep}, n)

    # -------------------------------------------------------------- 14
    def c14_db_rows(self):
        f, notes, n_db, n_mesh = [], [], 0, 0
        for r in self.rows:
            j, stage = r["job_id"], str(r.get("stage") or "")
            if stage.startswith("db_"):
                n_db += 1
                if j.startswith(("sb13_", "sb14_")):
                    f.append(f"{j}: db_* row with an arm job name")
                if r.get("in_family_phases"):
                    f.append(f"{j}: db_* row is in the family of phases {r['in_family_phases']} (would warm-start BO)")
                if r.get("kind") in ("design", "variant") and r.get("in_family_phases") is None:
                    f.append(f"{j}: db_* row without in_family_phases (family check not evaluated)")
                prov = str(r.get("provenance") or "")
                if not (r.get("layer") and r.get("layer") not in (DX.LAYER_S0, "unknown") and prov not in ("", "rule", "none")):
                    f.append(f"{j}: db_* row without D1 manifest / seed provenance (layer {r.get('layer')!r}, provenance {prov!r})")
        for r in self.rows:
            if r.get("kind") not in ("design", "variant") or r.get("h_int_mm") is None:
                continue
            if abs(r["h_int_mm"] - H_PROD) > 1e-9:
                n_mesh += 1
                ok = bool(r.get("has_bond_model")) or any(
                    o.get("bond_only") and o.get("realization_key") == r.get("realization_key") and o.get("fidelity") == r.get("fidelity")
                    for o in self.rows)
                if not ok:
                    f.append(f"{r['job_id']}: mesh variant h_int {r['h_int_mm']} without bonded result or same-mesh bond-only job (10-23 rule)")
        for r in self.rows:
            if r.get("bond_only") and r.get("source_job") and r.get("n_tet_total") is not None:
                s = r.get("source_job_n_tet_total")
                if s is None:
                    notes.append(f"{r['job_id']}: source job {r['source_job']} tet count unknown")
                elif int(s) != int(r["n_tet_total"]):
                    f.append(f"{r['job_id']}: bond-only tets {r['n_tet_total']} != source job {r['source_job']} tets {s}")
        st = "FAIL" if f else "PASS"
        self.add(14, "db_* rows outside the BO families; mesh variants bonded (10-23 rule); bond-only tets = source job",
                 st, f, {"n_db_rows": n_db, "n_mesh_variants": n_mesh, "notes": notes}, len(self.rows))

    def run(self) -> list:
        for fn in (self.c1_types, self.c2_fields, self.c3_code, self.c4_femur, self.c5_cortex, self.c6_force, self.c7_conditions,
                   self.c8_failures, self.c9_split, self.c10_adaptive, self.c11_duplicates, self.c12_unbiased, self.c13_ref,
                   self.c14_db_rows):
            try:
                fn()
            except Exception as e:  # noqa: BLE001  -- a crashing check is a FAIL, never a silent pass
                import traceback
                self.add(int(fn.__name__[1:].split("_")[0]), fn.__name__, "FAIL", [f"check crashed: {type(e).__name__}: {e}",
                                                                                    traceback.format_exc()[-800:]])
        self.results.sort(key=lambda d: d["id"])
        return self.results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="db3406 automatic checks (plan 1.8)")
    ap.add_argument("--db", required=True)
    ap.add_argument("--json-out")
    ap.add_argument("--max-list", type=int, default=30)
    a = ap.parse_args(argv)
    DX.idle_priority()
    db = pathlib.Path(a.db)
    for need in ("scalars.csv", "schema.json"):
        if not (db / need).exists():
            print(f"FAIL: {db / need} missing")
            return 1
    q = QA(db, a.max_list)
    res = q.run()
    n_fail = 0
    for d in res:
        print(f"[{d['status']:4}] {d['id']:2d}. {d['name']}  (checked {d['n_checked']}, failures {d['n_failures']})")
        if d["status"] == "FAIL":
            n_fail += 1
        for x in d["failures"][:a.max_list]:
            print("        -", str(x)[:400])
        if len(d["failures"]) > a.max_list:
            print(f"        ... {len(d['failures']) - a.max_list} more")
    out = pathlib.Path(a.json_out) if a.json_out else db / "qa_report.json"
    out.write_text(json.dumps({"db": str(db), "n_rows": len(q.rows), "n_fail": n_fail, "checks": res}, indent=1, default=str))
    print(f"{n_fail} of {len(res)} checks FAIL; report {out}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
