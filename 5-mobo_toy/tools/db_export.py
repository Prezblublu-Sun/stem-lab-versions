#!/usr/bin/env python3
"""db3406 exporter: Sawbones 3406 FE jobs -> database rows + interface point clouds (plan D4).

Plan: H:/projects/application/research-log/neck_implant_2026-10-02/3406数据库规划_两天一周一月_2026-10-25.md
(sections 1.2, 1.4, 1.6, 1.8, 2.2 D4, 2.3). Not part of the FE pipeline: none of the 8 hashed files, jobs.py,
stage_neckopt.py, stability.py, ... is modified; pipeline modules are imported READ-ONLY and only inside `emit`.

Sub-commands
  emit      Read job directories read-only (Linux ~/mobo_toy_v2/queue, or a local root of extracted job dirs on
            Windows, --queue-root) and produce the export members of one batch:
                export/<batch>/rows.jsonl        one row per job (DONE and FAILED; failed rows have empty labels)
                export/<batch>/context.json      code hashes, aux md5, femur geometry key, selection, versions
                export/<batch>/exclusion.json    exclusion set E (design keys of optimisation-selected designs,
                                                 scanned over the WHOLE queue, not only the selected jobs)
                export/<batch>/inventory.json    every 3406 job dir in the queue with its state (check 8)
                export/<batch>/export_log.json   timings, sizes, errors, guard report, re-aggregation errors
                fields/iface_<batch>_NNN.npz     CSR shards of the interface point clouds (concatenated arrays + off)
                STREAM_MANIFEST.json             sha256 + size of every member (computed on the emitting side)
            Default output: an uncompressed tar stream on STDOUT (nothing is written on Linux; all prints of the
            pipeline modules are redirected to stderr). --out-dir DIR writes the members into DIR instead.
            A write guard (sys.addaudithook) blocks and REPORTS every file write / delete / subprocess outside
            --out-dir, so the read-only promise is enforced, not just intended.
            --list-only: print ONE listing of the queue (JSON on stdout: every 3406 job dir with its state + the selected
            names) and stop; `pull --list-only` freezes it as <version>/jobs.txt + jobs_inventory.json.
            --results-root DIR: where neckopt_p11..14.json (BO records), db_manifest_*.json (stage_db D1 manifests) and
            db_seed_*.json (CD-0 seed) are read (default: jobs.RESULTS on Linux; on Windows the snapshot written by
            `db_archive.py results`). A missing results root is an error, never "no records".
  pull      Windows side. Runs `emit` on Linux over ssh with THIS FILE streamed to the remote python on stdin
            (`run.sh - emit ...`, pinned `nice -n 19 taskset -c 4-11`, single-threaded BLAS), extracts the tar stream
            into the version dir, checks every member's sha256 against STREAM_MANIFEST.json, then runs finalize.
            Batches run over a FROZEN job list: `pull --list-only --select-3406 --finished-only --out V` once, then
            `pull --jobs-file V/jobs.txt --offset k --limit n --batch b00x --out V` (a live `pull --select-3406` is refused:
            jobs inserted into the live queue would shift the offsets between batches).
            Any failure (exception, disk gate, bad manifest) closes the stream, kills ssh, writes PULL_BAD.json with the
            exception and the received members, moves the batch (and its received shards) to export/<batch>.BAD, and
            re-raises / exits non-zero.
            Disk gates: Linux free < 15 GB -> the remote emit refuses to start; output drive free < --min-free-gb
            (default 50) or H: free < 50 GB -> stop (checked before start and before every member).
  finalize  Database-level step over all verified batches of a version dir: provenance overrides, exclusion set E,
            unbiased flag, design-grouped split, OOD flags, replicate groups (friction and bonded separately), the femur
            registry (<db-root>/femur_registry.json: femur_id -> femur_geom_key bound to job time); writes scalars.csv,
            scalars.npz, splits.json, manifest.json, femur_registry.json and copies schema.json / DATA_CARD.md /
            CHANGELOG.md / README.md from the db root when present.
  publish   Mark a finalized, QA'd version directory as published (writes PUBLISHED.json with the sha256 of manifest.json and qa_report.json
            after checking every file against manifest.files). finalize refuses a published directory. `publish --check` verifies one later.
  schema    Write schema.json (every column: type, unit, range, source, when it must be filled).
  info      Print the environment the exporter would use (code hash, aux md5, femur key, cache, free disk).

Formats: numpy (.npz, no pickle) + csv/json only (the Linux pipeline venv has no pyarrow/h5py/zarr/pandas).
CLAUDE.md section 11: failures are never swallowed. A job that cannot be exported still gets a row with
export_status = "error" and the reasons in export_errors; emit / pull / finalize exit non-zero when any error
occurred (unless --allow-errors) and list them. Node numbering is never assumed to agree between designs: every
point cloud stores its own node labels and its own triangles.

Typical use (Windows, Git Bash or PowerShell; the venv python):
    python tools/db_export.py pull --jobs sb13_init_050d50bd v3406_dx_5feb1d8a_d0.2_a0a68c8e --batch b000 \
        --out "H:/projects/Femoral implant generation/db3406/v0.1"
    python tools/db_export.py pull --list-only --select-3406 --finished-only --out V          (freeze jobs.txt once)
    python tools/db_export.py pull --jobs-file V/jobs.txt --offset 0 --limit 60 --batch b000 --out V --no-finalize
    python tools/db_export.py finalize --out "H:/projects/Femoral implant generation/db3406/v0.1"
On Linux directly (writes nothing, tar on stdout):
    cd ~/mobo_toy_v2/code && nice -n 19 taskset -c 4-11 ~/mobo_toy_v2/run.sh /path/db_export.py emit --jobs ... > x.tar
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import traceback

import numpy as np

EXPORTER_VERSION = "db_export 0.2.6 (2026-11-11, result_class / result_code columns; F (bed support) columns; manifest.export_provenance)"
FEMUR_ID = "sawbone3406"
FEMUR_VERSIONS = {FEMUR_ID: ("3406R_v1_hollowcore", True)}          # plan 2.1: hollow-core model until the user answers
EXPECTED_CODE_HASH = "6d7af243d0"
STEPS = ("RELEASE", "LOAD", "UNLOAD", "LOAD2")
OPEN_UM = 1.0                                                       # post_m1.OPEN_UM (closed <=> gap <= 1 um)
DESIGN_VARS = ("L", "alpha", "h_cut", "m", "rho_tip", "q", "lam", "g_ml", "g_ap", "n_a", "n_p", "tau_a", "tau_p")
BOUNDS = {"v1": {"L": (20.0, 45.0), "alpha": (15.0, 45.0), "h_cut": (16.0, 32.0), "m": (0.5, 2.0), "rho_tip": (0.10, 0.50),
                 "q": (0.5, 3.0), "lam": (1.0, 2.2), "g_ml": (0.35, 0.65), "g_ap": (0.35, 0.65), "n_a": (2.0, 6.0),
                 "n_p": (2.0, 6.0), "tau_a": (-0.30, 0.30), "tau_p": (-0.30, 0.30)}}   # stage_neckopt.PHASES[11..14]
# Bed support F ("床支撑" of the FEA indicator template, one of the optimisation targets): F = sum A / max(t, t_floor) over the stem-body
# interface nodes with zeta <= zeta_max and |theta| <= theta_max. t = -d_canal (foam thickness between the stem face and the canal wall),
# zeta = distance from cref towards distal along the neck axis, theta = angle about the stem axis from the calcar side. Constants of the 3406
# femur: another femur needs its own. The same numbers as mesh_F in the judging files of b28 and later (b25 carries the old axis); they are
# also in ops/facts.json (bed_F_*), and a test holds the two together. This is the MESH version (from the exported interface nodes). The
# 0-FE version that selection scripts use (experiments/b28_fam/prep/data/opt3_geom.py) samples the surface itself and is not a column yet.
BED_F = {"zeta_max_mm": 15.0, "theta_max_deg": 45.0, "t_floor_mm": 0.25,
         "u_neck": (0.92228, 0.06137, 0.38162),                                       # geometry.json neck_axis.u, model frame, toward the head
         "cref": (37.65271204198696, 0.8509371708090849, 41.89415555538172),         # geometry.json stems.sb13_a105_91e458e3.cut_centre (A's cut centre)
         "n3": (0.381, 0.025, -0.924)}                                                # distal direction projected on the neck section, calcar side
HASHED_FILES = ("femur_real.py", "geom3d.py", "fe3d_geom.py", "model3d_v2.py", "post.py", "config_v2a.yaml",
                "model3d_m1.py", "post_m1.py")
# not in the job hash but able to change results (plan 1.6 trap 2) + the modules that compute labels in this export
AUX_FILES = ("inp_writer.py", "v2/jobs.py", "v2/femur_3406.py", "v2/collar_rule.py", "v2/stability.py", "v2/bond_collar.py",
             "v2/torsion_load.py", "v2/pose_fixed.py", "v2/foam_refine.py",
             "v2/import_stem.py", "v2/resorption.py", "v2/shielding.py", "abaqus/odb_export.py")
# femur geometry key (plan 1.6 trap 3), SAME definition as v2/stage_db.femur_geom_key() (D1): role -> file; the STEP paths are the
# ones femur_3406.load_cfg() puts into cfg['femur'] (= these files under the code root)
FEMUR_GEOM_ROLES = {"femur_3406.py": "v2/femur_3406.py", "step_cortical": "v2/data/femur_3406/3406R_cortical.STEP",
                    "step_cancellous": "v2/data/femur_3406/3406R_cancellous_v2.STEP"}
FEMUR_GEOM_FILES = tuple(FEMUR_GEOM_ROLES.values())
FEMUR_GEOM_KEY_RULE = ("sha256(''.join(f'{role}:{sha256(file)}\\n' for role in sorted(roles))).hexdigest()[:16], roles femur_3406.py / "
                       "step_cancellous / step_cortical (= stage_db.femur_geom_key()['key'])")
# exclusion set E (plan 1.4): job-name prefixes whose designs were picked by an optimiser or by a BO-derived box.
# db_bd_ = the plan's BD offset-variant stratum (BO-derived). stage_db.py v1.1 puts the bond-only PARTNER jobs under stage db_bo
# (layers "BD mesh" / "BD h2.0", source bond_partner), never db_bd. db_* jobs also enter E through their manifest source (E_SOURCES).
E_JOB_PREFIXES = ("sb13_a", "sb14_a", "db_cr_", "db_crt_", "db_bd_", "db_opt_", "db_ws_")
E_SOURCES = {"bo_p13", "bo_p14", "corner", "corner_test", "offset_variant", "opt_verify", "a9_baseline", "a9_bo", "gen_verify",
             "al_adaptive", "bound_scan"}   # bound_scan: stage_db b14, one-factor m / alpha scan of the BO design A. al_adaptive: the non-random active-learning picks (stage_db b5; plan 1.4 exclusion set E)
ARM_SOURCES = {"bo_p13", "bo_p14"}
CANDIDATE_JOBS = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "B'": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
                  "D": "sb14_a26_96c5ab9b", "a62": "sb13_a62_1e4338ee"}   # progress summary 50 h section 4 + corner check
SELECTIONS = ("iid", "stratum", "adaptive", "corner_test")
# db_* stage prefix -> (source, selection) used only to CROSS-CHECK the manifest (every db_* row needs a D1 manifest or seed entry);
# None = no rule. db_bo = stage_db.py v1.1 bond-only partners (source bond_partner); db_bd = offset variants (see E_JOB_PREFIXES).
DB_STAGE_RULES = {"db_sf": ("sf", "iid"), "db_cr": ("corner", "stratum"), "db_crt": ("corner_test", "corner_test"),
                  "db_bd": ("offset_variant", "stratum"), "db_bo": ("bond_partner", "stratum"), "db_nz": ("noise", "stratum"), "db_opt": ("opt_verify", "stratum"),
                  "db_ref": ("intact_ref", "stratum"), "db_cd": None, "db_fd": None, "db_al": None, "db_ws": ("bound_scan", "stratum")}
# D1 manifest selection values -> db3406 selection (the raw value is kept in source_detail)
MANIFEST_SELECTION = {"reference": "stratum", "stratum": "stratum", "iid": "iid", "adaptive": "adaptive", "corner_test": "corner_test"}
SEED_LAYER_SOURCE = {"CD-0": "cond_anchor"}                         # results/db_seed_CD0.json (deck/db_seed/db_seed_cd0.py)
LAYER_S0 = "S0"                                                      # plan 1.3: the existing jobs (not written by stage_db)
# BO-state records (results/neckopt_p<phase>.json) must exist for these job-name prefixes (pool_idx, round, rotation)
RECORD_REQUIRED_PREFIXES = ("sb11_init_", "sb13_init_", "sb13_a", "sb14_a")
BATCH_RE = re.compile(r"^[A-Za-z0-9_\-]+$")                          # batch names: no dots (".BAD" / ".replaced." dirs are skipped)
LINUX_HOST = "linux-user@<linux-ip>"
LINUX_KEY = "~/.ssh/id_ed25519_lrlbackup"
SSH_EXE = r"C:\Program Files\Git\usr\bin\ssh.exe"
LINUX_MIN_FREE_GB = 15.0
H_MIN_FREE_GB = 50.0
SPLIT_RULE = "bucket = int(sha1(design_key).hexdigest(), 16) % 100; bucket < 15 -> test, 15..24 -> val, else train"
REAGG_TOL = 1e-6
REAGG_KEYS = ("rot_first", "contact_load", "contact_load2", "f1", "foam_p05", "foam_p50", "foam_lt1")


# ================================================================================================ column catalogue
# (name, type, unit, lo, hi, req, source, description)
# req: always | spec | design | prep | done | fric | bond | intact | optional | reserved
#   fric = filled exactly for DONE rows with has_fric_model; bond = DONE design/variant rows with has_bond_model;
#   for any non-DONE row the fric / bond / field columns MUST be empty (failed rows have empty labels).
COLUMNS: list[tuple] = []


def _c(name, typ, unit="", lo=None, hi=None, req="optional", source="", desc=""):
    COLUMNS.append((name, typ, unit, lo, hi, req, source, desc))


def _build_columns():
    S, R, P, ST, RS, F, X, FN = ("spec.json", "result.json", "prep.json", "stability.py (stability.stability)",
                                 "resorption.design_rows (= stage_neckopt._calcar)", "fields shard (this exporter)",
                                 "export (computed)", "finalize")
    # --- identity
    _c("row_id", "str", "", req="always", source=X, desc="stable row id; = job_id (one row per FE job)")
    _c("job_id", "str", "", req="always", source="queue dir name", desc="<stage>_<tag>_<hash8>")
    _c("stage", "str", "", req="spec", source=S)
    _c("tag", "str", "", req="spec", source=S)
    _c("kind", "str", "", req="spec", source=S, desc="design | variant | intact")
    _c("status", "str", "", req="always", source="jobs.state", desc="DONE | FAILED | SOLVED | CLAIMED | READY | NEW | MISSING")
    _c("design_key", "str", "", req="design", source=X,
       desc="sha1 hex of the 13 physical design values (order DESIGN_VARS) each round(v, 6) formatted %.6f, joined by ','")
    _c("realization_key", "str", "", req="design", source=X,
       desc="sha1 of [design_key, femur_id, femur_geom_key, collar_rule, margin_check, a_bounds_max, neck_axis, min_A0, entry_offset]")
    _c("spec_hash", "str", "", req="spec", source=X, desc="sha1 of spec.json without stage/tag/created (sort_keys, default=float)")
    _c("cond_key", "str", "", req="spec", source=X, desc="sha1 of the effective condition values (delta, mu, E_canc, load, h_far, ...)")
    _c("fidelity", "str", "", req="spec", source=X, desc="h<h_int> (+ refinement flags later)")
    _c("code_hash", "str", "", req="optional", source=P + " code_hash, else recomputed job id",
       desc="jobs.code_hash() of the 8 hashed files at prep time")
    _c("code_hash_source", "str", "", req="always", source=X, desc="prep.json | job_id_recomputed | unknown")
    _c("code_hash_now", "str", "", req="always", source="jobs.code_hash() at export")
    _c("job_id_matches_code", "bool", "", req="spec", source="jobs.job_id(spec) == dir name under code_hash_now")
    _c("aux_code_md5", "str", "", req="always", source=X, desc="md5 over 'path:md5' lines of AUX_FILES at export time")
    _c("exporter_version", "str", "", req="always", source=X)
    _c("export_batch", "str", "", req="always", source=X)
    _c("export_time_utc", "str", "", req="always", source=X)
    _c("export_host", "str", "", req="always", source=X)
    # --- femur
    _c("femur_id", "str", "", req="spec", source=S, desc="'' = CT femur (not expected in db3406)")
    _c("femur_geom_key", "str", "", req="spec", source=X,
       desc="femur_3406.py + both STEP files of the exporting host; " + FEMUR_GEOM_KEY_RULE +
            ". Bound to job time by femur_geom_verified (see femur_registry.json)")
    _c("femur_geom_verified", "bool", "", req="optional", source=X + " / " + FN,
       desc="the geometry files hashed into femur_geom_key are the ones this job was prepped with: on the prep host (Linux "
            "queue) every file mtime <= prep.json mtime (basis files_older_than_prep); elsewhere finalize checks the femur "
            "registry window (basis registry). Must be true for every row with has_prep (QA check 4)")
    _c("femur_geom_basis", "str", "", req="optional", source=X + " / " + FN,
       desc="files_older_than_prep | registry | no_prep | '' (not verified)")
    _c("femur_model_version", "str", "", req="spec", source=X, desc="3406R_v1_hollowcore (plan 2.1 default)")
    _c("hollow_core", "bool", "", req="spec", source=X, desc="cancellous core bottom modelled as empty (unconfirmed)")
    _c("neck_axis", "json", "", req="spec", source=S)
    _c("femur_pose_match", "bool", "", req="prep", source=P + " femur_hook vs femur used by this export",
       desc="cut centre and baked neck axis of the export femur equal the prep-time values (<= 1e-9 mm)")
    _c("femur_pose_dev_mm", "float", "mm", 0.0, None, req="prep", source=X)
    _c("solver", "str", "", req="done", source="solve.json", desc="abaqus (odb_meta.odb *.odb) | the entry's 'solver' key")
    _c("solver_basis", "str", "", req="optional", source=X,
       desc="'' = solve.json; 'provenance <file>: <evidence>' = filled by finalize --provenance (solve.json overwritten after the solve)")
    _c("steps", "json", "", req="prep", source=P + " steps (else the step names in solve.json odb_meta)",
       desc="analysis steps of the model, e.g. PRESSFIT, RELEASE, LOAD, UNLOAD, LOAD2")
    _c("collar_rule", "str", "", req="optional", source=S)
    _c("margin_check", "str", "", req="optional", source=S)
    _c("a_bounds_max", "float", "mm2", 0.0, None, req="optional", source=S)
    _c("ref_cut_mm", "float", "mm", 0.0, None, req="optional", source=S)
    _c("min_A0_mm2", "float", "mm2", 0.0, None, req="design", source=S)
    # --- design (13 physical + 13 unit)
    units = {"L": "mm", "alpha": "deg", "h_cut": "mm", "m": "mm"}
    phys_rng = {"L": (5, 100), "alpha": (0, 90), "h_cut": (0, 60), "m": (-1, 5), "rho_tip": (0, 1), "q": (0, 10), "lam": (0.5, 5),
                "g_ml": (0, 1), "g_ap": (0, 1), "n_a": (1, 20), "n_p": (1, 20), "tau_a": (-1, 1), "tau_p": (-1, 1)}
    for k in DESIGN_VARS:
        _c(k, "float", units.get(k, "1"), *phys_rng[k], req="design", source=S + (" h_cut" if k == "h_cut" else " design"),
           desc="physical design variable")
    for k in DESIGN_VARS:
        _c("u_" + k, "float", "1", None, None, req="design", source=X, desc=f"unit coordinate of {k} under bounds_version")
    _c("bounds_version", "str", "", req="design", source=X, desc="v1 = current bounds (stage_neckopt PHASES[11..14])")
    _c("in_bounds_v1", "bool", "", req="design", source=X)
    _c("cap_h_mm", "float", "mm", 0.0, 10.0, req="optional", source=S)
    _c("collar_w_mm", "float", "mm", 0.0, 10.0, req="design", source=S)
    # --- conditions
    _c("delta_spec_mm", "float", "mm", 0.0, 1.0, req="optional", source=S + " delta (empty = model default)")
    _c("delta_mm", "float", "mm", 0.0, 1.0, req="optional", source=P + " delta (effective)")
    _c("mu", "float", "1", 0.0, 2.0, req="optional", source=P)
    _c("E_canc_MPa", "float", "MPa", 1.0, 1e5, req="prep", source=P + " E_canc (effective)")
    _c("load_R_N", "float", "N", 0.0, 2e4, req="spec", source="jobs.femur_for(spec).cfg['load'] (effective)")
    _c("alpha_front_deg", "float", "deg", -90, 90, req="spec", source="effective cfg load")
    _c("alpha_sagit_deg", "float", "deg", -90, 90, req="spec", source="effective cfg load")
    _c("head_coupling_radius_mm", "float", "mm", 0, 100, req="spec", source="effective cfg load")
    _c("load_vec_N", "json", "N", req="prep", source=P + " load_N (model frame: +x medial, +y posterior, +z proximal)")
    _c("load_vec_norm_N", "float", "N", 0.0, 2e4, req="prep", source=X)
    _c("h_int_mm", "float", "mm", 0.5, 5.0, req="spec", source=S)
    _c("h_int_prep_mm", "float", "mm", 0.5, 5.0, req="prep", source=P + " h_int (design / variant) or h_roi (intact)")
    _c("h_far_mm", "float", "mm", 0.5, 20.0, req="prep", source=P)
    _c("slip_tol", "float", "1", 0.0, 1.0, req="optional", source=P)
    _c("cycles", "int", "1", 0, 10, req="optional", source=P)
    _c("interference", "str", "", req="optional", source=P)
    _c("torque", "bool", "", req="optional", source=P)
    _c("entry_offset_forced_mm", "float", "mm", -20, 20, req="optional", source=S + " entry_offset")
    _c("torsion", "json", "", req="optional", source=S + " torsion (v2/torsion_load.py)", desc="non-empty: a couple on the head nodes on top of load_vec_N; torque_stem_axis_Nmm does not include it")
    _c("pose", "json", "", req="optional", source=S + " pose_fixed (v2/pose_fixed.py)", desc="non-empty: the size is the nominal one and only the pose moved; the cavity follows the stem")
    _c("foam_refine", "json", "", req="optional", source=S + " foam_refine (v2/foam_refine.py)", desc="non-empty: bone within dist_min of the stem-bone interface meshed at h (F5); h_int_mm is the production size elsewhere")
    _c("cfg_override", "json", "", req="optional", source=S + " cfg")
    _c("bond_only", "bool", "", req="spec", source=S)
    _c("fric_only", "bool", "", req="spec", source=S)
    _c("has_prep", "bool", "", req="always", source="prep.json exists")
    _c("has_fric_model", "bool", "", req="always", source="m_fric_csv/ exists (DONE rows)")
    _c("has_bond_model", "bool", "", req="always", source="m_bond_csv/ exists (DONE rows)")
    _c("torque_stem_axis_Nmm", "float", "N*mm", None, None, req="prep", source=X,
       desc="((H - P0) x F) . ax with H = femoral head centre (HEADN coupling centre), P0/ax = stem pose, F = load_vec_N")
    _c("moment_shoulder_bend_Nmm", "float", "N*mm", 0.0, None, req="prep", source=X, desc="|(H - P0) x F - T ax|")
    _c("cons_delta", "bool", "", req="prep", source=X, desc="spec delta (when given) == prep delta")
    _c("cons_load", "bool", "", req="prep", source=X, desc="|load_N| == cfg resultant and load_N direction == cfg angles (1e-6)")
    _c("cons_h_int", "bool", "", req="prep", source=X, desc="spec h_int == prep h_int / h_roi")
    _c("spec_in_result_match", "bool", "", req="optional", source="result.json spec copy == spec.json (empty for intact rows)")
    # --- template features (prep.json; 0-FE)
    for k, u, lo, hi in (("alpha", "deg", 0, 90), ("e", "mm", -20, 20), ("A0", "mm2", 0, 5000), ("contact", "1", 0, None),
                         ("s_bind", "mm", None, None), ("volume", "mm3", 0, None), ("margin", "mm", -1, 5)):
        _c("tpl_" + k, "float", u, lo, hi, req="prep" if k != "contact" else "optional", source=P + " templating." + k)
    _c("e_star_mm", "float", "mm", req="reserved", source="D3 tpl_record.py (not in v0.1)")
    _c("A0_star_mm2", "float", "mm2", req="reserved", source="D3 tpl_record.py")
    _c("e_margin", "float", "1", req="reserved", source="D3 tpl_record.py")
    FOAM = ("foam thickness t = -canal_sdf(X) at the bone-side interface nodes of the stem body (no collar), i.e. stem surface -> "
            "endosteal (core) surface distance; area-weighted with the nodal pair areas (qoi.wquantile); same definition as "
            "corner check 2026-10-25 section 2.1 (corner_calc/analyst/corner_job.py fe.foam_t)")
    _c("foam_thk_p05_mm", "float", "mm", -5, 50, req="fric", source=F, desc="area-weighted P05 of t. " + FOAM)
    _c("foam_thk_p50_mm", "float", "mm", -5, 50, req="fric", source=F, desc="area-weighted P50 of t. " + FOAM)
    _c("area_foam_lt1_mm2", "float", "mm2", 0, 1e4, req="fric", source=F, desc="body interface area with t < 1 mm. " + FOAM)
    _c("bone_resected_mm3", "float", "mm3", 0, None, req="optional", source=P + " bone_loss.resected_mm3")
    _c("bone_reamed_mm3", "float", "mm3", 0, None, req="optional", source=P + " bone_loss.reamed_mm3")
    _c("bone_total_mm3", "float", "mm3", 0, None, req="optional", source=P + " bone_loss.total_mm3")
    _c("stem_volume_mm3", "float", "mm3", 0, None, req="optional", source=P)
    # --- quality
    _c("fail_level", "str", "", req="optional", source="FAILED.json level (L1..L5)")
    _c("fail_stage", "str", "", req="optional", source="FAILED.json stage")
    _c("fail_reason", "str", "", req="optional", source="FAILED.json reason (first 500 chars)")
    _c("result_code", "str", "", req="optional", source="FAILED.json code (jobs._fail writes it from 2026-11-11 on); else finalize: "
       "v2/result_codes.for_job(status, fail_level, fail_stage, fail_reason)",
       desc="what kind of outcome: ok for a DONE row, a name from v2/result_codes.CODES for a FAILED row, empty for an unfinished row")
    _c("result_class", "str", "", req="optional", source="finalize: the class of result_code (v2/result_codes.CODES)",
       desc="OK / DESIGN / NUMERIC / ENV / ERROR / SKIP / UNKNOWN: what to do next and what a selection strategy may be told; "
            "fail_level says where it failed, this says what kind of failure it is")
    _c("n_tet_cortex", "int", "1", 0, None, req="optional", source=P)
    _c("n_tet_cancellous", "int", "1", 0, None, req="optional", source=P)
    _c("n_tet_stem", "int", "1", 0, None, req="optional", source=P)
    _c("n_tet_total", "int", "1", 0, None, req="optional", source=P)
    _c("n_nodes", "int", "1", 0, None, req="optional", source=P)
    _c("n_pairs", "int", "1", 0, None, req="optional", source=P + " (all interface node pairs)")
    _c("n_pairs_cortex", "int", "1", 0, None, req="optional", source=P)
    _c("interface_area_mm2", "float", "mm2", 0, None, req="optional", source=P)
    _c("mesh_algo", "int", "1", req="optional", source=P + " mesh_attempt.algorithm3d")
    _c("mesh_h_used_mm", "float", "mm", req="optional", source=P + " mesh_attempt.h_int")
    _c("mesh_section_points", "int", "1", req="optional", source=P + " mesh_attempt.section_points")
    _c("mesh_retries", "int", "1", 0, None, req="optional", source=P + " len(mesh_attempt.previous_errors)")
    _c("mesh_min_vol_mm3", "float", "mm3", 0, None, req="optional", source=P + " min over mesh_quality.min_vol")
    _c("solve_wall_s_fric", "float", "s", 0, None, req="optional", source="solve.json m_fric.wall_s")
    _c("solve_wall_s_bond", "float", "s", 0, None, req="optional", source="solve.json m_bond.wall_s")
    _c("solve_tries_fric", "int", "1", 0, None, req="optional", source="solve.json")
    _c("solve_tries_bond", "int", "1", 0, None, req="optional", source="solve.json")
    _c("export_status", "str", "", req="always", source=X, desc="ok | error (see export_errors)")
    _c("export_errors", "json", "", req="optional", source=X, desc="list of error strings (empty list = none)")
    _c("export_warnings", "json", "", req="optional", source=X)
    _c("extra_result_keys", "json", "", req="optional", source=R, desc="numeric result.json keys without a column (never dropped silently)")
    # --- friction labels (stability.py), all segments: first = LOAD-RELEASE, rev = LOAD2-UNLOAD, perm = UNLOAD-RELEASE
    for seg in ("first", "rev", "perm"):
        _c(f"rot_{seg}_deg", "float", "deg", 0, 90, req="fric", source=ST, desc="|omega| of the area-weighted rigid fit, stem body")
        _c(f"rot_axial_{seg}_deg", "float", "deg", 0, 90, req="fric", source=ST)
        _c(f"rot_tilt_{seg}_deg", "float", "deg", 0, 90, req="fric", source=ST)
        _c(f"rot_tilt_ap_{seg}_deg", "float", "deg", -90, 90, req="fric", source=ST, desc="signed, about e_ap (varus/valgus)")
        _c(f"rot_tilt_ml_{seg}_deg", "float", "deg", -90, 90, req="fric", source=ST, desc="signed, about e_ml (flexion)")
        _c(f"subsid_{seg}_um", "float", "um", -1e5, 1e5, req="fric", source=ST, desc="translation at P0 along ax (+ = into bone)")
        _c(f"lateral_{seg}_um", "float", "um", 0, 1e5, req="fric", source=ST)
        _c(f"rigid_fit_rms_{seg}_um", "float", "um", 0, 1e5, req="fric", source=ST)
    KNIFE = ("DIAGNOSTIC ONLY (prefix diag_, never a label): node set chosen by a knife-edge comparison; a 1e-13 mm femur pose "
             "change (other platform / cache) moved 160-250 nodes and the value by 0.5-12 % in the 2026-10-25 test")
    _c("diag_rot_first_prox_deg", "float", "deg", 0, 90, req="fric", source=ST + " rot_first_prox_deg",
       desc="proximal half (s <= median). " + KNIFE)
    _c("diag_rot_axial_first_prox_deg", "float", "deg", 0, 90, req="fric", source=ST + " rot_axial_first_prox_deg", desc=KNIFE)
    _c("diag_rot_tilt_first_prox_deg", "float", "deg", 0, 90, req="fric", source=ST + " rot_tilt_first_prox_deg", desc=KNIFE)
    _c("slip_axial_p95_um", "float", "um", 0, 1e5, req="fric", source=ST)
    _c("slip_circ_p95_um", "float", "um", 0, 1e5, req="fric", source=ST)
    _c("contact_area_load_mm2", "float", "mm2", 0, 1e4, req="fric", source=ST, desc="body area with gap <= 1 um at LOAD")
    _c("contact_frac_load", "float", "1", 0, 1, req="fric", source=ST)
    _c("contact_area_load2_mm2", "float", "mm2", 0, 1e4, req="fric", source=ST)
    _c("contact_frac_load2", "float", "1", 0, 1, req="fric", source=ST)
    _c("body_interface_mm2", "float", "mm2", 0, 1e4, req="fric", source=ST)
    _c("diag_bench_cx_h_stem_mm", "float", "mm", req="optional", source=ST + " virtual bench bench_cx_h_stem_mm", desc=KNIFE)
    _c("diag_bench_cx_h_bone_mm", "float", "mm", req="optional", source=ST + " virtual bench bench_cx_h_bone_mm", desc=KNIFE)
    _c("diag_bench_cx_n_stem", "int", "1", 0, None, req="optional", source=ST + " bench_cx_n_stem",
       desc="marker nodes 0 < h <= 10 mm. " + KNIFE)
    _c("diag_bench_cx_n_bone", "int", "1", 0, None, req="optional", source=ST + " bench_cx_n_bone",
       desc="marker nodes -5 <= h < 0 mm. " + KNIFE)
    for seg in ("first", "rev", "perm"):
        for q, u, lo, hi in (("rot", "deg", 0, 90), ("rot_axial", "deg", 0, 90), ("rot_tilt", "deg", 0, 90),
                             ("subsid", "um", -1e5, 1e5), ("lateral", "um", 0, 1e5)):
            _c(f"diag_bench_cx_{q}_{seg}_{u}", "float", u, lo, hi, req="optional",
               source=ST + f" virtual bench (reference) bench_cx_{q}_{seg}_{u}", desc=KNIFE)
    _c("rot_record_deg", "float", "deg", 0, 90, req="optional", source="results/neckopt_p<phase>.json record rot_first_deg")
    _c("rot_record_match", "bool", "", req="optional", source=X, desc="|rot_first_deg - rot_record_deg| <= 1e-9 * rot")
    # --- micromotion / contact (result.json, post_m1)
    for k, u, lo, hi in (("f1_p95_um", "um", 0, 1e5), ("f1_rev_p50_um", "um", 0, 1e5), ("f1_rev_max_um", "um", 0, 1e5),
                         ("f1_first_p95_um", "um", 0, 1e5), ("f1_first_p50_um", "um", 0, 1e5), ("normal_rev_p95_um", "um", 0, 1e5),
                         ("area_frac_gt40", "1", 0, 1), ("area_frac_gt150", "1", 0, 1), ("open_frac_release", "1", 0, 1),
                         ("open_frac_load", "1", 0, 1), ("open_frac_load2", "1", 0, 1), ("gap_p95_release_um", "um", -1e5, 1e5),
                         ("gap_p95_load2_um", "um", -1e5, 1e5), ("n_pairs_body", "1", 0, None), ("interface_area_body_mm2", "mm2", 0, 1e4),
                         ("cortex_area_frac", "1", 0, 1), ("f1_closed_p95_um", "um", 0, 1e5), ("f1_canc_p95_um", "um", 0, 1e5),
                         ("cpress_release_p50", "MPa", 0, 1e4), ("cpress_release_p95", "MPa", 0, 1e4), ("cpress_release_max", "MPa", 0, 1e5),
                         ("cpress_release_mean_all", "MPa", 0, 1e4), ("status_frac_stick", "1", 0, 1), ("status_frac_slip", "1", 0, 1),
                         ("status_frac_open", "1", 0, 1), ("stick_cslip_p95_um", "um", 0, 1e5), ("stick_cslip_max_um", "um", 0, 1e5),
                         ("slide_cslip_p95_um", "um", 0, 1e5), ("f1_cslip_p95_um", "um", 0, 1e5), ("frac_open", "1", 0, 1)):
        req = "optional" if k in ("f1_closed_p95_um", "f1_canc_p95_um", "stick_cslip_p95_um", "stick_cslip_max_um",
                                  "slide_cslip_p95_um") else "fric"
        _c(k, "int" if k == "n_pairs_body" else "float", u, lo, hi, req=req,
           source=R + (" n_pairs" if k == "n_pairs_body" else " interface_area" if k == "interface_area_body_mm2" else ""),
           desc=("CPRESS: reference only (Lame check bias -24 % / +11 %)" if k.startswith("cpress") else
                 "body (no collar) micromotion P95 of the 2nd cycle, post_m1 f1" if k == "f1_p95_um" else ""))
    # --- bonded labels
    _c("vm_p99_MPa", "float", "MPa", 0, 1e4, req="bond", source=R + " vm_p99", desc="stem von Mises P99 (bonded LOAD)")
    _c("vm_max_MPa", "float", "MPa", 0, 1e5, req="bond", source=R + " vm_max")
    _c("n_stem_elems_in_bone", "int", "1", 0, None, req="bond", source=R)
    _c("sed_gruen7", "float", "MPa", 0, 100, req="optional", source=R + " (bonded: zone SED; intact: gruen7)")
    _c("sed_gruen1", "float", "MPa", 0, 100, req="optional", source=R)
    _c("f2_g7_loss_pct", "float", "%", -1e6, 100, req="bond", source=R, desc="legacy mixed cortex+cancellous loss; not the G7 label")
    _c("f2_g1_loss_pct", "float", "%", -1e6, 100, req="bond", source=R)
    _c("sed_chg_pct", "float", "%", -100, 1e6, req="bond", source=RS,
       desc="calcar SED change, fixed scheme, zone G7, cortex only, vs the row's intact_job (negative = shielding)")
    _c("ssi_pct", "float", "%", -1e6, 100, req="bond", source=RS, desc="stress shielding index, same zone (positive = shielding)")
    _c("calcar_error", "str", "", req="optional", source=RS)
    _c("intact_job_spec", "str", "", req="optional", source=S + " intact_job", desc="must equal intact_job (result.json) on bonded rows")
    _c("intact_job", "str", "", req="bond", source=R + " intact_job")
    _c("intact_substituted_h", "float", "mm", req="optional", source=R)
    _c("ref_match", "bool", "", req="bond", source=X,
       desc="intact_job has the row's femur_id, h_int, load, E_canc, neck_axis, h_far and baked femur geometry (plan 1.6 trap 4); "
            "spec AND prep level (prep E_canc, h_roi vs h_int, h_far, load_N to 1e-9); result.json intact_job == spec intact_job")
    _c("ref_mismatch", "json", "", req="optional", source=X)
    _c("intact_gruen7_vol_mm3", "float", "mm3", 0, None, req="intact", source=R + " (intact rows)")
    _c("intact_gruen1_vol_mm3", "float", "mm3", 0, None, req="intact", source=R + " (intact rows)")
    # --- fields
    _c("field_shard", "str", "", req="fric", source=F, desc="fields/<name>.npz holding this row's point cloud")
    _c("field_index", "int", "1", 0, None, req="fric", source=F)
    _c("field_n_nodes", "int", "1", 1, None, req="fric", source=F)
    _c("field_n_tri", "int", "1", 0, None, req="fric", source=F)
    _c("F", "float", "mm", 0, None, req="optional", source="finalize: bed_support() on the row's interface point cloud (fields shard)",
       desc="bed support, mesh version: sum A / max(t, 0.25 mm) over stem-body nodes with zeta <= 15 mm and |theta| <= 45 deg; t = -d_canal; "
            "3406 constants in manifest.bed_F; empty for rows without a point cloud")
    _c("F_area_mm2", "float", "mm2", 0, None, req="optional", source="finalize: bed_support()", desc="nodal area inside the F zone")
    _c("F_n_nodes", "int", "1", 0, None, req="optional", source="finalize: bed_support()", desc="stem-body nodes inside the F zone")
    _c("F_t_min_mm", "float", "mm", None, None, req="optional", source="finalize: bed_support()", desc="smallest t = -d_canal inside the F zone (before the 0.25 mm floor)")
    _c("F_frac_floor", "float", "1", 0, 1, req="optional", source="finalize: bed_support()", desc="share of the zone's area where t < 0.25 mm, so the floor decides")
    _c("tri_area_ratio", "float", "1", 0.9, 1.1, req="fric", source=F, desc="sum of triangle areas / sum of nodal pair areas")
    _c("iface_force_load_N", "json", "N", req="optional", source=F + " sum of bone-side CNORMF+CSHEARF at LOAD")
    _c("iface_force_err_load", "float", "1", 0, 0.05, req="optional", source=F, desc="|sum F - load| / |load| at LOAD")
    _c("iface_force_err_load2", "float", "1", 0, 0.05, req="optional", source=F)
    for k in REAGG_KEYS:
        _c(f"fld_err_{k}", "float", "1", 0, REAGG_TOL, req="fric", source=F, desc="relative re-aggregation error from the stored shard")
    # --- selection / provenance
    _c("source", "str", "", req="always", source=X + " / provenance",
       desc="sobol_init_p11 | sobol_init_p13 | bo_p13 | bo_p14 | d13 | v3406_ref | smoke_p11 | diag | intact_ref | db_* rows: the "
            "D1 manifest source (cond_anchor, noise, fid_h25, fid_h14, bond_partner, intact_ref, sf, corner, ...)")
    _c("source_detail", "str", "", req="optional", source=X)
    _c("selection", "str", "", req="always", source=X + " / provenance",
       desc="iid | stratum | adaptive | corner_test (D1 manifest 'reference' -> stratum; raw value in source_detail)")
    _c("layer", "str", "", req="always", source="D1 manifest / CD-0 seed layer; S0 for the existing (non-db_*) jobs",
       desc="plan 1.3 layer: S0 | CD-0 | NZ-1 | FD-0 h2.5 | FD-0 h1.4 | REF | BD mesh | BD h2.0 | ...")
    _c("manifest_refs", "json", "", req="optional", source="results/db_manifest_<batch>.json rows / results/db_seed_*.json jobs",
       desc="every manifest entry that resolved to this job: [file:key, ...] (also for an existing job adopted by D1 dedup)")
    _c("provenance", "str", "", req="always", source=X + " / " + FN,
       desc="rule (stage-prefix rules + neckopt records) | the D1 manifest / seed file name | a finalize --provenance file name")
    _c("acq_name", "str", "", req="optional", source="neckopt records / provenance",
       desc="sobol (initial batches) | qLogNEHVI (arm rows with a BO record; name from the stage_neckopt docstring, the records "
            "do not store it) | empty when unknown")
    _c("acq_round", "int", "1", -1, None, req="optional", source="neckopt records round")
    _c("acq_model_version", "str", "", req="reserved", source="provenance")
    _c("acq_pred_mean", "float", "", req="reserved", source="provenance")
    _c("acq_pred_sd", "float", "", req="reserved", source="provenance")
    _c("pool_idx", "int", "1", 0, None, req="optional", source="neckopt records pool_idx")
    _c("record_phase", "int", "1", 11, 14, req="optional", source="neckopt_p<phase>.json holding a record of this job")
    _c("w_iid", "float", "1", 0, None, req="reserved", source="density-ratio weight (later)")
    _c("source_job", "str", "", req="optional", source=S + " source_job")
    _c("source_job_n_tet_total", "int", "1", 0, None, req="optional", source="prep.json of source_job")
    _c("source_job_design_key", "str", "", req="optional", source=X)
    _c("in_family_phases", "json", "", req="spec", source="stage_neckopt.Phase(p).in_family(spec), p = 11..14")
    _c("in_E", "bool", "", req="always", source=FN, desc="design_key in the exclusion set E (plan 1.4)")
    _c("sf_bo_overlap", "bool", "", req="always", source=FN, desc="SF row whose design was also solved by an arm (A3 test only)")
    _c("unbiased", "bool", "", req="always", source=FN, desc="selection == 'iid' and not in_E and not sf_bo_overlap")
    _c("replicate_group", "str", "", req="optional", source=FN,
       desc="FRICTION replicates (plan 2.3): sha1[:12] of ('fric', realization_key, cond_key, fidelity) over DONE rows with "
            "has_fric_model; set when the group has > 1 row (rows are kept, never deleted)")
    _c("replicate_of", "str", "", req="optional", source=FN,
       desc="first job (by t_done_utc, then job_id) of the friction replicate group; empty for that job itself")
    _c("replicate_group_bond", "str", "", req="optional", source=FN,
       desc="BONDED replicates: sha1[:12] of ('bond', realization_key, cond_key, fidelity, intact_job) over DONE rows with "
            "has_bond_model; set when the group has > 1 row")
    _c("replicate_of_bond", "str", "", req="optional", source=FN, desc="first job of the bonded replicate group; empty for that job")
    # --- split / OOD
    _c("split_bucket", "int", "1", 0, 99, req="design", source=FN, desc=SPLIT_RULE)
    _c("split", "str", "", req="design", source=FN, desc="train | val | test (by design_key)")
    _c("test_iid", "bool", "", req="always", source=FN, desc="unbiased and split == test")
    _c("test_corner", "bool", "", req="always", source=FN, desc="selection == corner_test (CR-T)")
    _c("a3_test_only", "bool", "", req="always", source=FN, desc="= sf_bo_overlap")
    _c("ood_alpha_gap", "bool", "", req="design", source=FN, desc="27 <= alpha <= 33 deg")
    _c("ood_bo_region", "bool", "", req="design", source=FN, desc="design_key solved by arm 13/14 (or sf_bo_overlap)")
    _c("ood_cond_extreme", "bool", "", req="always", source=FN, desc="load_R_N >= 3500 or delta_mm >= 0.15")
    _c("ood_widened", "bool", "", req="design", source=FN, desc="bounds_version != v1")
    _c("ood_femur", "bool", "", req="always", source=FN, desc="femur_id != sawbone3406")
    # --- time (UTC from marker mtimes; spec 'created' is local time without zone)
    for k, src in (("t_spec_utc", "spec.json mtime"), ("t_prep_utc", "prep.json mtime"),
                   ("t_ready_utc", "READY / CLAIMED mtime (rename keeps READY's mtime)"), ("t_solved_utc", "SOLVED mtime"),
                   ("t_done_utc", "DONE mtime"), ("t_failed_utc", "FAILED.json mtime")):
        _c(k, "str", "UTC ISO 8601", req="optional", source=src)
    _c("created_local", "str", "local", req="optional", source=S + " created (reference only; ambiguous at the DST change)")


_build_columns()
COLNAMES = [c[0] for c in COLUMNS]
COLTYPE = {c[0]: c[1] for c in COLUMNS}
assert len(COLNAMES) == len(set(COLNAMES)), "duplicate column names"
LABEL_REQ = ("fric", "bond")
RESULT_MAP = {"n_pairs": "n_pairs_body", "interface_area": "interface_area_body_mm2", "vm_p99": "vm_p99_MPa", "vm_max": "vm_max_MPa",
              "gruen7_vol_mm3": "intact_gruen7_vol_mm3", "gruen1_vol_mm3": "intact_gruen1_vol_mm3", "gruen7": "sed_gruen7",
              "gruen1": "sed_gruen1"}
RESULT_SKIP = {"spec", "solve", "templating", "n_tet", "bone_loss", "job_id", "model", "intact_job", "intact_substituted_h",
               "fric_only", "bond_only", "h_cut_mm"}
RESULT_COLS = {c[0] for c in COLUMNS if c[6].startswith("result.json")} - {"intact_job", "intact_substituted_h", "spec_in_result_match"}
STAB_COLS = {c[0] for c in COLUMNS if c[6].startswith("stability.py (")}
STAB_REQUIRED = {c[0] for c in COLUMNS if c[6].startswith("stability.py (") and c[5] == "fric"}


def stab_key(col: str) -> str:
    """stability.stability() key of a column (the knife-edge diagnostics carry the prefix diag_ in the database)."""
    return col[5:] if col.startswith("diag_") else col


STAB_KEY_TO_COL = {stab_key(c): c for c in STAB_COLS}
assert len(STAB_KEY_TO_COL) == len(STAB_COLS)


def schema_dict() -> dict:
    cols = []
    for name, typ, unit, lo, hi, req, src, desc in COLUMNS:
        cols.append({"name": name, "type": typ, "unit": unit, "range": [lo, hi], "required": req, "source": src, "description": desc})
    return {"schema_version": "db3406-scalars 0.1", "generated_by": EXPORTER_VERSION,
            "csv": {"encoding": "utf-8", "missing": "", "nan": "nan", "bool": ["true", "false"], "json": "compact JSON text",
                    "float": "Python repr (round-trips exactly)"},
            "required_semantics": {
                "always": "non-empty in every row", "spec": "non-empty when spec.json was readable", "design": "non-empty for kind design/variant",
                "prep": "non-empty when has_prep is true and kind is design/variant", "done": "non-empty for status DONE",
                "fric": "non-empty exactly for DONE rows with has_fric_model; empty for every non-DONE row",
                "bond": "non-empty exactly for DONE design/variant rows with has_bond_model; empty for every non-DONE row",
                "intact": "non-empty for DONE intact rows", "optional": "may be empty", "reserved": "defined but not filled in this version"},
            "design_vars": list(DESIGN_VARS), "bounds": BOUNDS, "split_rule": SPLIT_RULE,
            "field_shard": FIELD_DOC, "columns": cols}


FIELD_DOC = {
    "file": "fields/iface_<batch>_<NNN>.npz (np.savez_compressed, no pickle)",
    "csr": "job j owns node rows off[j]:off[j+1] and triangle rows tri_off[j]:tri_off[j+1]; tri holds LOCAL node indices",
    "per_job": {"job_id": "[J] str", "row_id": "[J] str", "off": "[J+1] int64", "tri_off": "[J+1] int64",
                "frame": "[J,4,3] float64: P0 (shoulder centre on the cut plane), ax (stem axis, distal, unit), e_ml, e_ap (femur.pose)",
                "load_vec": "[J,3] float64 N (prep load_N)"},
    "per_node": {"X": "[N,3] f64 mm bone-side node, world (model) frame", "nrm": "[N,3] f64 outward stem normal, world",
                 "area": "[N] f64 mm2 nodal tributary area", "interf": "[N] f64 mm applied interference (0 next to cortex)",
                 "cortex": "[N] bool", "collar": "[N] bool", "node_bone": "[N] int64 Abaqus label (bone side)",
                 "node_stem": "[N] int64 label of the stem twin", "rel": "[N,4,3] f64 mm u_stem - u_bone, world, steps RELEASE/LOAD/UNLOAD/LOAD2",
                 "loc": "[N,3] f32 mm (s, x_ml, x_ap) in the stem frame", "srt": "[N,3] f32 (s mm, r mm, theta rad = atan2(x_ap, x_ml))",
                 "nloc": "[N,3] f32 normal in the stem frame",
                 "d_canal": "[N] f64 mm canal_sdf (<0 inside the cancellous core); foam thickness = -d_canal",
                 "d_outer": "[N] f32 mm outer_sdf", "cpress": "[N,4] f32 MPa bone node CPRESS per step (reference only)",
                 "cstatus": "[N,4] f32 CSTATUS (2 stick, 1 slip, else open)", "copen": "[N,4] f32 mm COPEN",
                 "gap": "[N,4] f32 um = -(interf + rel . nrm) * 1e3 (closed <=> gap <= 1 um)",
                 "cforce": "[N,2,3] f32 N bone-side CNORMF + CSHEARF at LOAD, LOAD2 (nan when the CSV is absent)"},
    "triangles": "bone faces of the C3D10 mesh whose 6 nodes are interface nodes and which belong to exactly one bone element, "
                 "each split into 4 linear triangles via the mid-side nodes",
    "reaggregation": "rot_first = |omega| of rigid_fit(X[body], rel[:,LOAD]-rel[:,RELEASE], area[body]) in degrees; "
                     "contact_area_<s> = sum area[body][gap_<s> <= 1 um]; f1 = wquantile(|tangential rel LOAD2 - UNLOAD| um, area, 0.95) over body; "
                     "foam_p05 / foam_p50 = wquantile(-d_canal[body], area[body], 0.05 / 0.5); foam_lt1 = sum area[body][-d_canal < 1 mm]",
}


# ================================================================================================ small helpers
def utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_utc() -> str:
    return utc(time.time())


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()


def jdump(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=_jdefault)


def _jdefault(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pathlib.Path,)):
        return str(o)
    return float(o)


def _r6(v: float) -> str:
    x = round(float(v), 6)
    if x == 0:
        x = 0.0
    return f"{x:.6f}"


def design_key(design: dict, h_cut: float) -> str:
    """sha1 hex of the 13 physical values (DESIGN_VARS order), each round(v, 6) formatted %.6f, joined by ','."""
    v = {**design, "h_cut": h_cut}
    return sha1(",".join(_r6(v[k]) for k in DESIGN_VARS))


def unit_coords(design: dict, h_cut: float, bv: str = "v1") -> dict:
    v = {**design, "h_cut": h_cut}
    return {k: (float(v[k]) - BOUNDS[bv][k][0]) / (BOUNDS[bv][k][1] - BOUNDS[bv][k][0]) for k in DESIGN_VARS}


def spec_hash(spec: dict) -> str:
    core = {k: spec[k] for k in sorted(spec) if k not in ("stage", "tag", "created")}
    return hashlib.sha1(json.dumps(core, sort_keys=True, default=float).encode()).hexdigest()


def split_of(dk: str) -> tuple[int, str]:
    b = int(hashlib.sha1(dk.encode()).hexdigest(), 16) % 100
    return b, ("test" if b < 15 else "val" if b < 25 else "train")


def md5_file(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def free_gb(path) -> float:
    return shutil.disk_usage(str(path)).free / 1e9


def csv_present(p: pathlib.Path) -> bool:
    """An odb CSV is present as <name>.csv or (cleaned job dirs) <name>.csv.gz -- the same fallback as qoi._csv / post_m1."""
    p = pathlib.Path(p)
    return p.exists() or pathlib.Path(str(p) + ".gz").exists()


def femur_geom_key_of(sha_by_role: dict) -> str:
    """Same arithmetic as v2/stage_db.femur_geom_key()['key'] (D1)."""
    return hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(sha_by_role.items())).encode()).hexdigest()[:16]


def parse_utc(s: str | None) -> float | None:
    if not s:
        return None
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc).timestamp()


def _num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v)
    return v


def log(*a):
    print("[db_export]", *a, file=sys.stderr, flush=True)


# ================================================================================================ pure numerics (shared with db_qa)
def rigid_fit_np(X: np.ndarray, R: np.ndarray, w: np.ndarray | None = None):
    """Same arithmetic as stability.rigid_fit: R ~ t + omega x (X - c), weighted least squares. Returns (t, omega, c, rms)."""
    c = X.mean(0) if w is None else (X * w[:, None]).sum(0) / w.sum()
    Q = X - c
    n = len(X)
    A = np.zeros((3 * n, 6))
    A[0::3, 0] = A[1::3, 1] = A[2::3, 2] = 1.0
    A[0::3, 4], A[0::3, 5] = Q[:, 2], -Q[:, 1]
    A[1::3, 3], A[1::3, 5] = -Q[:, 2], Q[:, 0]
    A[2::3, 3], A[2::3, 4] = Q[:, 1], -Q[:, 0]
    b = R.reshape(-1)
    sw = np.ones(3 * n) if w is None else np.repeat(np.sqrt(w / w.mean()), 3)
    sol, *_ = np.linalg.lstsq(A * sw[:, None], b * sw, rcond=None)
    res = b - A @ sol
    return sol[:3], sol[3:], c, float(np.sqrt(np.mean(res ** 2)))


def wquantile_np(x: np.ndarray, w: np.ndarray, q: float) -> float:
    """Same as qoi.wquantile behind post_m1._wq (finite values only)."""
    ok = np.isfinite(x)
    if not ok.any():
        return float("nan")
    x, w = x[ok], w[ok]
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    c /= w.sum()
    return float(np.interp(q, c, x))


def reaggregate(sh: dict, j: int) -> dict:
    """Recompute rot_first_deg, contact_area_load(2)_mm2 and f1_p95_um of job j from a loaded shard."""
    a, b = int(sh["off"][j]), int(sh["off"][j + 1])
    X, n, w, di = sh["X"][a:b], sh["nrm"][a:b], sh["area"][a:b], sh["interf"][a:b]
    rel = sh["rel"][a:b]                                               # [n,4,3]
    body = ~sh["collar"][a:b].astype(bool)
    Rr = rel[:, 1] - rel[:, 0]
    _, om, _, _ = rigid_fit_np(X[body], Rr[body], w[body])
    out = {"rot_first": float(np.degrees(np.linalg.norm(om)))}
    for k, s in (("contact_load", 1), ("contact_load2", 3)):
        gap = -(di[body] + (rel[body, s] * n[body]).sum(1)) * 1e3
        out[k] = float(w[body][gap <= OPEN_UM].sum())
    rv = rel[:, 3] - rel[:, 2]
    tang = rv - (rv * n).sum(1)[:, None] * n
    slip = np.linalg.norm(tang, axis=1) * 1e3
    out["f1"] = wquantile_np(slip[body], w[body], 0.95)
    out.update(foam_features(np.asarray(sh["d_canal"][a:b], np.float64), w, body))
    return out


def foam_features(d_canal: np.ndarray, area: np.ndarray, body: np.ndarray) -> dict:
    """Foam thickness t = -canal_sdf at the body interface nodes, area-weighted (corner check 2026-10-25 section 2.1)."""
    t = -np.asarray(d_canal, np.float64)[body]
    w = np.asarray(area, np.float64)[body]
    return {"foam_p05": wquantile_np(t, w, 0.05), "foam_p50": wquantile_np(t, w, 0.5), "foam_lt1": float(w[t < 1.0].sum())}


REAGG_REF = {"rot_first": "rot_first_deg", "contact_load": "contact_area_load_mm2", "contact_load2": "contact_area_load2_mm2",
             "f1": "f1_p95_um", "foam_p05": "foam_thk_p05_mm", "foam_p50": "foam_thk_p50_mm", "foam_lt1": "area_foam_lt1_mm2"}
assert tuple(REAGG_REF) == REAGG_KEYS


def rel_err(a, b) -> float:
    if a is None or b is None:
        return float("nan")
    a, b = float(a), float(b)
    if a == b:
        return 0.0
    return abs(a - b) / max(abs(b), 1e-12)


TET_FACES = ((0, 1, 2, 4, 5, 6), (0, 1, 3, 4, 8, 7), (1, 2, 3, 5, 9, 8), (0, 2, 3, 6, 9, 7))   # C3D10: corners a,b,c + mids ab,bc,ca


def interface_triangles(bone_conn: np.ndarray, pair_bone: np.ndarray) -> np.ndarray:
    """Linear triangles (local pair indices) of the bone-side interface: faces of the C3D10 bone tets whose 6 nodes are all
    interface nodes and that belong to exactly one bone element, each split into 4 via the mid-side nodes."""
    if len(pair_bone) == 0 or len(bone_conn) == 0:
        return np.zeros((0, 3), np.int32)
    lab_max = int(max(int(bone_conn.max()), int(pair_bone.max())))
    loc = np.full(lab_max + 1, -1, np.int64)
    loc[pair_bone] = np.arange(len(pair_bone))
    faces = np.concatenate([bone_conn[:, list(f)] for f in TET_FACES])          # [4E,6] labels
    key = np.sort(faces[:, :3], 1)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    once = cnt[inv.ravel()] == 1
    on = (loc[faces] >= 0).all(1)
    F = loc[faces[once & on]]                                                    # [M,6] local indices
    a, b, c, ab, bc, ca = (F[:, i] for i in range(6))
    T = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)])
    return T.astype(np.int32)


def tri_area(Xl: np.ndarray, T: np.ndarray) -> float:
    if len(T) == 0:
        return 0.0
    p = Xl[T]
    return float(0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1).sum())


# ================================================================================================ write guard
_GUARD = {"on": False, "allowed": [], "blocked": [], "allow_subprocess": False, "busy": False}
_WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_TRUNC", 0)
_PATH_EVENTS = {"os.remove", "os.rmdir", "os.truncate", "os.chmod", "os.chown", "os.utime", "os.symlink", "os.link",
                "shutil.rmtree", "os.rename", "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.move",
                "shutil.chown", "tempfile.mkstemp", "tempfile.mkdtemp", "os.mkfifo", "os.mknod"}
_PROC_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile", "pty.spawn"}


def _gpath(p):
    try:
        return os.path.realpath(os.fsdecode(p))
    except TypeError:
        return None


def _gallowed(p) -> bool:
    rp = _gpath(p)
    if rp is None:
        return True
    if rp in (os.devnull, "/dev/null", "/dev/stdout", "/dev/stderr"):
        return True
    return any(rp == a or rp.startswith(a.rstrip(os.sep) + os.sep) for a in _GUARD["allowed"])


def _gblock(event, what):
    _GUARD["blocked"].append(f"{event}: {what}")
    raise PermissionError(f"db_export write guard: {event} {what!r} is outside the allowed output dir(s) {_GUARD['allowed']}")


def _ghook(event, args):
    if not _GUARD["on"] or _GUARD["busy"]:
        return
    _GUARD["busy"] = True
    try:
        if event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            if isinstance(path, int) or path is None:
                return
            w = (isinstance(mode, str) and any(ch in mode for ch in "wax+")) or (isinstance(flags, int) and bool(flags & _WFLAGS))
            if w and not _gallowed(path):
                _gblock(event, os.fsdecode(path))
        elif event == "os.mkdir":
            path = args[0]
            if not os.path.isdir(os.fsdecode(path)) and not _gallowed(path):
                _gblock(event, os.fsdecode(path))
        elif event in _PATH_EVENTS:
            for p in args:
                if isinstance(p, (str, bytes, os.PathLike)) and not _gallowed(p):
                    _gblock(event, os.fsdecode(p))
        elif event in _PROC_EVENTS and not _GUARD["allow_subprocess"]:
            _gblock(event, str(args[:2])[:200])
    finally:
        _GUARD["busy"] = False


def install_guard(allowed: list[str]) -> None:
    _GUARD["allowed"] = [os.path.realpath(a) for a in allowed]
    if not _GUARD.get("hooked"):
        sys.addaudithook(_ghook)
        _GUARD["hooked"] = True
    _GUARD["on"] = True


# ================================================================================================ output sinks
class TarSink:
    """Uncompressed tar stream (mode 'w|') on a binary file object; members from bytes; sha256 per member."""

    def __init__(self, fileobj):
        self.tf = tarfile.open(fileobj=fileobj, mode="w|", format=tarfile.PAX_FORMAT)
        self.manifest = {}

    def add(self, name: str, data: bytes) -> None:
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        ti.mtime = int(time.time())
        ti.mode = 0o644
        self.tf.addfile(ti, io.BytesIO(data))
        self.manifest[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

    def close(self, extra: dict) -> None:
        body = json.dumps({"members": self.manifest, **extra}, indent=1, sort_keys=True).encode()
        ti = tarfile.TarInfo("STREAM_MANIFEST.json")
        ti.size = len(body)
        ti.mtime = int(time.time())
        self.tf.addfile(ti, io.BytesIO(body))
        self.tf.close()


class DirSink:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.manifest = {}

    def add(self, name: str, data: bytes) -> None:
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        self.manifest[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

    def close(self, extra: dict) -> None:
        batch = extra.get("batch", "b")
        body = json.dumps({"members": self.manifest, **extra}, indent=1, sort_keys=True).encode()
        (self.root / "export" / batch).mkdir(parents=True, exist_ok=True)
        (self.root / "export" / batch / "STREAM_MANIFEST.json").write_bytes(body)
        bad = verify_members(self.root, self.manifest)
        (self.root / "export" / batch / ("EMIT_BAD.json" if bad else "EMIT_OK.json")).write_text(
            json.dumps({"verified_utc": now_utc(), "errors": bad}, indent=1))


def verify_members(root: pathlib.Path, manifest: dict) -> list:
    errs = []
    for name, m in manifest.items():
        p = root / name
        if not p.exists():
            errs.append(f"{name}: missing")
            continue
        if p.stat().st_size != m["size"] or sha256_file(p) != m["sha256"]:
            errs.append(f"{name}: sha256/size mismatch")
    return errs


# ================================================================================================ pipeline access (emit only)
class Pipeline:
    """Lazy, read-only access to the pipeline modules (jobs, stability, post_m1, resorption, stage_neckopt, geom3d)."""

    def __init__(self, code_root: pathlib.Path, queue_root: pathlib.Path | None):
        self.code_root = pathlib.Path(code_root).resolve()
        v2 = self.code_root / "v2"
        if not (v2 / "jobs.py").exists():
            raise FileNotFoundError(f"code root {self.code_root} has no v2/jobs.py")
        for p in (str(v2), str(self.code_root)):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, str(self.code_root))
        sys.path.insert(0, str(v2))
        os.environ.setdefault("MPLBACKEND", "Agg")
        import jobs as J
        import geom3d as G
        import post_m1 as PM
        import stability as ST
        self.J, self.G, self.PM, self.ST = J, G, PM, ST
        if queue_root is not None:
            J.QROOT = pathlib.Path(queue_root).resolve()             # runtime attribute only; jobs.py itself is not changed
        self.qroot = J.QROOT
        self._RS = None
        self._NO = None
        self._phases = None

    @property
    def RS(self):
        if self._RS is None:
            import resorption as RS
            self._RS = RS
        return self._RS

    def phases(self):
        if self._phases is None:
            import stage_neckopt as NO
            self._NO = NO
            self._phases = {p: NO.Phase(p) for p in (11, 12, 13, 14) if p in NO.PHASES}
        return self._phases


def load_records(results_root: pathlib.Path, files: dict) -> dict:
    """BO-state records of phases 11..14 (results/neckopt_p<phase>.json): job_id -> phase, pool_idx, round, rot_first_deg, bonded.
    A job recorded in two phases is an error (raised)."""
    out = {}
    for ph in (11, 12, 13, 14):
        p = results_root / f"neckopt_p{ph}.json"
        if not p.exists():
            continue
        b = p.read_bytes()
        files[p.name] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mtime_utc": utc(p.stat().st_mtime)}
        s = json.loads(b)
        for r in list(s.get("records", [])) + list(s.get("pending", []) if isinstance(s.get("pending"), list) else []):
            j = r.get("job_id")
            if not j:
                continue
            if j in out and out[j]["phase"] != ph:
                raise ValueError(f"{j} has records in neckopt_p{out[j]['phase']}.json and {p.name}")
            out.setdefault(j, {"phase": ph, **{k: r.get(k) for k in ("pool_idx", "round", "rot_first_deg", "bonded")}})
    return out


def load_db_provenance(results_root: pathlib.Path, files: dict, records: dict) -> tuple[dict, list]:
    """Provenance of db_* jobs written by the submitters themselves (plan 2.2 D1), keyed by job id:
      results/db_manifest_<batch>.json (v2/stage_db.py: rows{key: {layer, source, selection, pool_idx, intact_job, femur_model_version,
                                        hollow_core, source_job, condition_id, id, dedup, ...}}, femur_geom_key{key, files})
      results/db_seed_*.json           (deck/db_seed/db_seed_cd0.py: jobs{key: id}, specs{key: spec with db_layer, db_cond, source_job,
                                        femur_model_version}); layer CD-0 -> source cond_anchor, selection stratum; pool_idx = the
                                        source job's BO record.
    Returns (job_id -> [entries], problems). Unreadable / malformed files raise (never skipped)."""
    prov, probs = {}, []
    for p in sorted(results_root.glob("db_manifest_*.json")):
        b = p.read_bytes()
        files[p.name] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mtime_utc": utc(p.stat().st_mtime)}
        man = json.loads(b)
        gk = (man.get("femur_geom_key") or {}).get("key")
        for key, m in (man.get("rows") or {}).items():
            jid = m.get("id")
            if not jid:
                continue
            prov.setdefault(jid, []).append({
                "file": p.name, "key": key, "kind": "manifest", "batch": man.get("batch"), "layer": m.get("layer"),
                "source": m.get("source"), "selection_raw": m.get("selection"), "pool_idx": m.get("pool_idx"),
                "intact_job": m.get("intact_job"), "femur_model_version": m.get("femur_model_version") or man.get("femur_model_version"),
                "hollow_core": m.get("hollow_core", man.get("hollow_core")), "source_job": m.get("source_job"),
                "condition_id": m.get("condition_id"), "dedup": m.get("dedup"), "design_code": m.get("design_code"),
                "manifest_femur_geom_key": gk, "manifest_code_hash": man.get("code_hash")})
    for p in sorted(results_root.glob("db_seed_*.json")):
        b = p.read_bytes()
        files[p.name] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b), "mtime_utc": utc(p.stat().st_mtime)}
        s = json.loads(b)
        specs = s.get("specs") or {}
        for key, jid in (s.get("jobs") or {}).items():
            sp = specs.get(key)
            if sp is None:
                probs.append(f"{p.name}: job {key} -> {jid} has no spec entry")
                continue
            layer = sp.get("db_layer")
            src = SEED_LAYER_SOURCE.get(layer)
            if src is None:
                probs.append(f"{p.name}: {key}: db_layer {layer!r} has no source mapping (SEED_LAYER_SOURCE)")
            rec = records.get(sp.get("source_job") or "") or {}
            prov.setdefault(jid, []).append({
                "file": p.name, "key": key, "kind": "seed", "batch": s.get("batch"), "layer": layer, "source": src,
                "selection_raw": "stratum", "pool_idx": rec.get("pool_idx"), "intact_job": sp.get("intact_job"),
                "femur_model_version": sp.get("femur_model_version"), "hollow_core": None, "source_job": sp.get("source_job"),
                "condition_id": sp.get("db_cond"), "dedup": None, "design_code": None, "manifest_femur_geom_key": None,
                "manifest_code_hash": s.get("code_hash"), "seed_spec": sp})
    return prov, probs


class Context:
    def __init__(self, P: Pipeline, batch: str, odb_export_md5: str | None, results_root: str | None = None,
                 default_code_root: bool = True):
        self.P, self.batch = P, batch
        J = P.J
        self.code_hash = J.code_hash()
        root = P.code_root
        aux, aux_src = {}, {}
        for f in AUX_FILES:
            p = root / f
            aux[f] = md5_file(p) if p.exists() else None
            aux_src[f] = "code_root" if p.exists() else "absent"
        if aux.get("abaqus/odb_export.py") is None and odb_export_md5:      # the Windows worker's copy (not on Linux)
            aux["abaqus/odb_export.py"] = odb_export_md5
            aux_src["abaqus/odb_export.py"] = "passed by pull from the Windows repo"
        self.aux, self.aux_src = aux, aux_src
        default_q = (pathlib.Path.home() / "mobo_toy_v2" / "queue").resolve()
        self.queue_complete = pathlib.Path(P.qroot).resolve() == default_q
        # prep host = the Linux queue read with the code the jobs were prepped with: only there do file mtimes bind to job time
        self.prep_host = self.queue_complete and default_code_root
        self.aux_md5 = hashlib.md5("".join(f"{k}:{v}\n" for k, v in sorted(aux.items())).encode()).hexdigest()
        geo, mt = {}, {}
        for role, f in FEMUR_GEOM_ROLES.items():
            p = root / f
            if not p.exists():
                raise FileNotFoundError(f"femur geometry file missing: {p}")
            geo[role] = sha256_file(p)
            mt[role] = p.stat().st_mtime
        self.femur_geom = geo
        self.femur_geom_mtime = mt
        self.femur_geom_mtime_max = max(mt.values())
        self.femur_geom_key = femur_geom_key_of(geo)
        self.hashed_md5 = {f: md5_file(root / "v2" / f) for f in HASHED_FILES}
        self.host = socket.gethostname()
        self.t_utc = now_utc()
        self.results_root = pathlib.Path(results_root).expanduser().resolve() if results_root else pathlib.Path(J.RESULTS).resolve()
        if not self.results_root.is_dir():
            raise FileNotFoundError(f"results root {self.results_root} does not exist: the BO records (neckopt_p11..14.json) and the "
                                    "db_* manifests would be missing (on Windows pass --results-root <db3406/raw/results/<snapshot>>)")
        self.results_files = {}
        self.records = load_records(self.results_root, self.results_files)
        self.db_prov, self.db_prov_problems = load_db_provenance(self.results_root, self.results_files, self.records)
        self._fm = {}

    def femur(self, spec: dict):
        """jobs.femur_for(spec) (the femur stability.py uses), cached per (femur_id, neck_axis, h_cut, cfg) in this process."""
        key = jdump({k: spec.get(k) for k in ("femur_id", "neck_axis", "h_cut", "cfg")})
        if key not in self._fm:
            if len(self._fm) >= 3:                                      # each femur object holds ~0.2 GB of distance fields
                self._fm.clear()
            self._fm[key] = self.P.J.femur_for(spec)
        return self._fm[key]

    def as_dict(self) -> dict:
        return {"exporter_version": EXPORTER_VERSION, "batch": self.batch, "export_time_utc": self.t_utc, "host": self.host,
                "code_root": str(self.P.code_root), "queue_root": str(self.P.qroot), "code_hash_now": self.code_hash,
                "expected_code_hash": EXPECTED_CODE_HASH, "hashed_files_md5": self.hashed_md5, "aux_files_md5": self.aux,
                "aux_files_source": self.aux_src, "aux_code_md5": self.aux_md5, "queue_complete": self.queue_complete,
                "prep_host": self.prep_host, "femur_geom_files_sha256": self.femur_geom, "femur_geom_key": self.femur_geom_key,
                "femur_geom_key_rule": FEMUR_GEOM_KEY_RULE,
                "femur_geom_files_mtime_utc": {k: utc(v) for k, v in self.femur_geom_mtime.items()},
                "femur_geom_mtime_max_utc": utc(self.femur_geom_mtime_max),
                "femur_versions": FEMUR_VERSIONS, "results_root": str(self.results_root), "results_files": self.results_files,
                "n_records": len(self.records), "n_db_prov_jobs": len(self.db_prov), "db_prov_problems": self.db_prov_problems,
                "python": sys.version, "numpy": np.__version__}


def _read_json(p: pathlib.Path, errs: list, what: str):
    try:
        return json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        errs.append(f"{what}: {type(e).__name__}: {e}")
        return None


def _mtime(p: pathlib.Path):
    return p.stat().st_mtime if p.exists() else None


def classify(name: str, spec: dict, rec: dict | None) -> dict:
    stage = str(spec.get("stage", ""))
    kind = spec.get("kind")
    out = {"source": None, "selection": None, "source_detail": stage, "acq_name": None, "acq_round": None, "pool_idx": None,
           "record_phase": None, "layer": LAYER_S0}
    if rec:
        out.update(record_phase=rec["phase"], acq_round=rec.get("round"), pool_idx=rec.get("pool_idx"))
    if stage.startswith("db_"):                                     # provenance from the D1 manifest / seed (apply_db_provenance)
        pre = "_".join(stage.split("_")[:2])
        rule = DB_STAGE_RULES.get(pre)
        out["layer"] = None
        if rule:
            out.update(source=rule[0], selection=rule[1])
    elif kind == "intact":
        out.update(source="intact_ref", selection="stratum")
    elif name.startswith("sb11_init_"):
        out.update(source="sobol_init_p11", selection="iid", acq_name="sobol")
    elif name.startswith("sb13_init_"):
        out.update(source="sobol_init_p13", selection="iid", acq_name="sobol")
    elif name.startswith("sb11_smoke_"):
        out.update(source="smoke_p11", selection="stratum")
    elif name.startswith("sb13_a") or name.startswith("sb14_a"):
        # acquisition name only when the BO record says this job was an acquisition (round > 0, pool_idx); never guessed
        out.update(source="bo_p13" if name.startswith("sb13") else "bo_p14", selection="adaptive",
                   acq_name="qLogNEHVI" if (rec and rec.get("pool_idx") is not None and (rec.get("round") or 0) > 0) else None)
    elif stage.startswith("d13"):
        out.update(source="d13", selection="stratum")
    elif stage == "v3406":
        out.update(source="v3406_ref", selection="stratum")
    elif stage == "sbdiag":
        out.update(source="diag", selection="stratum")
    return out


def apply_db_provenance(row: dict, spec: dict, entries: list | None, ctx_femur_key: str, errs: list) -> None:
    """db_* rows: layer / source / selection / pool_idx from the D1 manifest or the CD-0 seed (load_db_provenance); cross-checked
    against the stage rule, spec intact_job, femur_model_version / hollow_core and the manifest's femur_geom_key. Any disagreement
    or a missing entry is an export error. Non-db rows that a manifest adopted (D1 dedup 'existing') only get manifest_refs.
    A db_* row adopted by a later batch (dedup 'existing') keeps the provenance of the batch that submitted it; the adopting entry
    only adds to manifest_refs, but must still agree on intact_job and femur_model_version."""
    name, stage = row["job_id"], str(spec.get("stage", ""))
    if entries:
        row["manifest_refs"] = sorted(f"{e['file']}:{e['key']}" for e in entries)
    if not stage.startswith("db_"):
        return
    if not entries:
        errs.append(f"db_* job {name} has no entry in results/db_manifest_*.json or results/db_seed_*.json (unknown provenance)")
        return
    keys = ("layer", "source", "selection_raw", "pool_idx", "intact_job", "femur_model_version")
    origin = [e for e in entries if e.get("dedup") != "existing"] or entries
    e0 = origin[0]
    first = {k: e0.get(k) for k in keys}
    for e in origin[1:]:
        diff = {k: (first[k], e.get(k)) for k in keys if e.get(k) != first[k]}
        if diff:
            errs.append(f"provenance entries disagree for {name}: {e0['file']}:{e0['key']} vs {e['file']}:{e['key']}: {diff}")
    for e in entries:
        if e not in origin:
            diff = {k: (first[k], e.get(k)) for k in ("intact_job", "femur_model_version") if e.get(k) != first[k]}
            if diff:
                errs.append(f"provenance entries disagree for {name}: {e0['file']}:{e0['key']} vs {e['file']}:{e['key']}: {diff}")
    sel = MANIFEST_SELECTION.get(str(e0.get("selection_raw")))
    if sel is None:
        errs.append(f"{e0['file']}:{e0['key']}: selection {e0.get('selection_raw')!r} has no db3406 mapping")
    if not e0.get("source"):
        errs.append(f"{e0['file']}:{e0['key']}: no source")
    rule_src = row.get("source")                                   # from DB_STAGE_RULES (classify), when the stage has a rule
    if rule_src is not None and e0.get("source") != rule_src:
        errs.append(f"{name}: manifest source {e0.get('source')!r} != stage rule {rule_src!r}")
    row.update(layer=e0.get("layer"), source=e0.get("source"), selection=sel, pool_idx=_num(e0.get("pool_idx")),
               provenance=e0["file"],
               source_detail=f"{e0['file']}:{e0['key']} (layer {e0.get('layer')}, selection {e0.get('selection_raw')}, "
                             f"condition {e0.get('condition_id')}, source_job {e0.get('source_job')})")
    if (e0.get("intact_job") or None) != (spec.get("intact_job") or None):
        errs.append(f"{name}: manifest intact_job {e0.get('intact_job')!r} != spec intact_job {spec.get('intact_job')!r}")
    if e0.get("source_job") and spec.get("source_job") and e0["source_job"] != spec["source_job"]:
        errs.append(f"{name}: manifest source_job {e0['source_job']!r} != spec source_job {spec['source_job']!r}")
    if not row.get("source_job") and e0.get("source_job"):         # stage_db specs carry no source_job (META key, manifest only)
        row["source_job"] = e0["source_job"]
    fmv = e0.get("femur_model_version")
    if fmv is not None and fmv != row.get("femur_model_version"):
        errs.append(f"{name}: manifest femur_model_version {fmv!r} != exporter {row.get('femur_model_version')!r}")
    if spec.get("femur_model_version") is not None and spec["femur_model_version"] != row.get("femur_model_version"):
        errs.append(f"{name}: spec femur_model_version {spec['femur_model_version']!r} != exporter {row.get('femur_model_version')!r}")
    if e0.get("hollow_core") is not None and bool(e0["hollow_core"]) != bool(row.get("hollow_core")):
        errs.append(f"{name}: manifest hollow_core {e0['hollow_core']!r} != exporter {row.get('hollow_core')!r}")
    if e0.get("manifest_femur_geom_key") is not None and e0["manifest_femur_geom_key"] != ctx_femur_key:
        errs.append(f"{name}: manifest femur_geom_key {e0['manifest_femur_geom_key']} != this export's {ctx_femur_key}")
    if e0.get("seed_spec") is not None:                             # the seed json holds the submitted spec: must be the job's spec
        a = {k: v for k, v in e0["seed_spec"].items() if k not in ("created",)}
        b = {k: v for k, v in spec.items() if k not in ("created",)}
        if jdump(a) != jdump(b):
            errs.append(f"{name}: spec.json differs from the spec recorded in {e0['file']} ({e0['key']})")


def build_field(P: Pipeline, ctx: Context, jd: pathlib.Path, spec: dict, tpl: dict, fm, errs: list):
    """Interface point cloud of one friction job (adapted from 10-22 nn_extract_iface.py; world arrays kept in float64 so the
    scalars re-aggregate exactly)."""
    PM = P.PM
    p = PM.pairs(jd)
    pb, ps = p["pair_bone"].astype(np.int64), p["pair_stem"].astype(np.int64)
    if len(np.unique(pb)) != len(pb):
        raise ValueError("pair_bone labels are not unique")
    lut = np.full(p["n"] + 1, -1, dtype=np.int64)
    lut[p["node_labels"]] = np.arange(len(p["node_labels"]))
    if (lut[pb] < 0).any() or (lut[ps] < 0).any():
        raise ValueError("pair node labels missing from mesh3d.npz node_labels")
    X = p["nodes"][lut[pb]].astype(np.float64)
    U = {s: PM._utab(jd / "m_fric_csv" / f"{s}_U.csv", p["n"]) for s in STEPS}
    rel = np.stack([U[s][ps] - U[s][pb] for s in STEPS], 1)                      # [n,4,3] mm world
    if not np.isfinite(rel).all():
        raise ValueError("missing displacement for some interface node pairs")
    nrm = np.asarray(p["pair_normal"], np.float64)
    area = np.asarray(p["pair_area"], np.float64)
    interf = np.asarray(p["pair_interf"], np.float64)
    n = len(pb)
    cp, cs, co = (np.full((n, 4), np.nan, np.float32) for _ in range(3))
    for i, s in enumerate(STEPS):
        f = jd / "m_fric_csv" / f"{s}_CONTACT.csv"
        if not csv_present(f):                                       # .csv or .csv.gz (qoi._csv reads both)
            errs.append(f"m_fric_csv/{f.name} missing (also no .gz)")
            continue
        C = PM._ctab(f, p["n"])
        for arr, k in ((cp, "CPRESS"), (cs, "CSTATUS"), (co, "COPEN")):
            if k in C:
                arr[:, i] = C[k][pb]
            else:
                errs.append(f"m_fric_csv/{f.name}: field {k} missing")
    cf = np.full((n, 2, 3), np.nan, np.float32)
    for i, s in enumerate(("LOAD", "LOAD2")):
        f = jd / "m_fric_csv" / f"{s}_CFORCE.csv"
        if not csv_present(f):                                       # a missing contact-force file is an error, not NaN forces
            errs.append(f"m_fric_csv/{f.name} missing (also no .gz)")
            continue
        cf[:, i] = PM._ftab(f, p["n"])[pb]
    gap = np.stack([-(interf + (rel[:, i] * nrm).sum(1)) * 1e3 for i in range(4)], 1)
    P0, ax, e_ml, e_ap = (np.asarray(v, np.float64) for v in fm.pose(tpl["alpha"], tpl["e"]))
    axn = ax / np.linalg.norm(ax)
    B = np.stack([axn, e_ml / np.linalg.norm(e_ml), e_ap / np.linalg.norm(e_ap)])
    loc = (X - P0) @ B.T
    nloc = nrm @ B.T
    srt = np.stack([loc[:, 0], np.hypot(loc[:, 1], loc[:, 2]), np.arctan2(loc[:, 2], loc[:, 1])], 1)
    m = np.load(jd / "mesh3d.npz")
    bone_conn = np.concatenate([m[k] for k in ("cortex_conn", "cancellous_conn") if k in m.files]).astype(np.int64)
    T = interface_triangles(bone_conn, pb)
    collar = np.asarray(p["pair_collar"], bool)
    d_canal = np.asarray(fm.canal_sdf(X), np.float64)                 # float64: the foam features re-aggregate exactly
    arr = {"X": X, "nrm": nrm, "area": area, "interf": interf, "cortex": np.asarray(p["pair_cortex"], bool),
           "collar": collar, "node_bone": pb, "node_stem": ps, "rel": rel,
           "loc": loc.astype(np.float32), "srt": srt.astype(np.float32), "nloc": nloc.astype(np.float32),
           "d_canal": d_canal, "d_outer": np.asarray(fm.outer_sdf(X), np.float32),
           "cpress": cp, "cstatus": cs, "copen": co, "gap": gap.astype(np.float32), "cforce": cf}
    meta = {"frame": np.stack([P0, axn, e_ml, e_ap]), "tri": T, "foam": foam_features(d_canal, area, ~collar)}
    return arr, meta


class ShardBuilder:
    PER_NODE = ("X", "nrm", "area", "interf", "cortex", "collar", "node_bone", "node_stem", "rel", "loc", "srt", "nloc", "d_canal",
                "d_outer", "cpress", "cstatus", "copen", "gap", "cforce")

    def __init__(self, batch: str, size: int):
        self.batch, self.size, self.k = batch, size, 0
        self.items = []

    def add(self, row: dict, arr: dict, meta: dict, load_vec):
        self.items.append((row, arr, meta, load_vec))

    def full(self) -> bool:
        return len(self.items) >= self.size

    def flush(self, sink, log_out: dict):
        if not self.items:
            return
        name = f"iface_{self.batch}_{self.k:03d}"
        J = len(self.items)
        off = np.zeros(J + 1, np.int64)
        toff = np.zeros(J + 1, np.int64)
        off[1:] = np.cumsum([len(a["area"]) for _, a, _, _ in self.items])
        toff[1:] = np.cumsum([len(m["tri"]) for _, _, m, _ in self.items])
        out = {k: np.concatenate([a[k] for _, a, _, _ in self.items]) for k in self.PER_NODE}
        out.update(off=off, tri_off=toff, tri=np.concatenate([m["tri"] for _, _, m, _ in self.items]).astype(np.int32),
                   frame=np.stack([m["frame"] for _, _, m, _ in self.items]),
                   load_vec=np.array([lv if lv is not None else [np.nan] * 3 for _, _, _, lv in self.items], np.float64),
                   job_id=np.array([r["job_id"] for r, _, _, _ in self.items]), row_id=np.array([r["row_id"] for r, _, _, _ in self.items]),
                   steps=np.array(STEPS), doc=np.array(json.dumps(FIELD_DOC)), version=np.array(EXPORTER_VERSION))
        bio = io.BytesIO()
        np.savez_compressed(bio, **out)
        data = bio.getvalue()
        sh = dict(np.load(io.BytesIO(data), allow_pickle=False))           # check what is actually stored
        for j, (row, _, _, _) in enumerate(self.items):
            row["field_shard"], row["field_index"] = name, j
            chk = reaggregate(sh, j)
            for k, ref in REAGG_REF.items():
                e = rel_err(chk[k], row.get(ref))
                row[f"fld_err_{k}"] = e
                if not (e <= REAGG_TOL):
                    row["export_errors"].append(f"field re-aggregation {k}: rel err {e:.3g} > {REAGG_TOL:g} ({chk[k]!r} vs {row.get(ref)!r})")
        sink.add(f"fields/{name}.npz", data)
        log_out.setdefault("shards", []).append({"name": name, "n_jobs": J, "n_nodes": int(off[-1]), "bytes": len(data)})
        self.items = []
        self.k += 1


def ref_check(P: Pipeline, ctx: Context, spec: dict, row: dict) -> tuple[bool, list]:
    """Plan 1.6 trap 4: the intact reference must match femur_id, h_int, load, E_canc, neck_axis, h_far and femur_geom_key."""
    rid = spec.get("intact_job")
    bad = []
    if not rid:
        return False, ["no intact_job in spec"]
    rd = P.qroot / rid
    rspec = _read_json(rd / "spec.json", bad, f"intact {rid} spec.json") if (rd / "spec.json").exists() else None
    rprep = _read_json(rd / "prep.json", bad, f"intact {rid} prep.json") if (rd / "prep.json").exists() else None
    if rspec is None:
        return False, bad + [f"intact {rid}: spec.json missing"]
    if rspec.get("kind") != "intact":
        bad.append(f"intact {rid}: kind {rspec.get('kind')}")
    if not (rd / "DONE").exists():
        bad.append(f"intact {rid}: not DONE")
    for k in ("femur_id", "h_int", "E_canc"):
        if rspec.get(k) != spec.get(k):
            bad.append(f"{k}: ref {rspec.get(k)!r} vs row {spec.get(k)!r}")
    if jdump(rspec.get("neck_axis")) != jdump(spec.get("neck_axis")):
        bad.append(f"neck_axis: ref {rspec.get('neck_axis')!r} vs row {spec.get('neck_axis')!r}")
    try:
        lr = dict(ctx.femur(rspec).cfg["load"])
        lw = dict(ctx.femur(spec).cfg["load"])
        if jdump(lr) != jdump(lw):
            bad.append(f"load: ref {lr} vs row {lw}")
    except Exception as e:  # noqa: BLE001
        bad.append(f"load comparison failed: {type(e).__name__}: {e}")
    hf_ref = (rprep or {}).get("h_far", rspec.get("h_far", 6.0))
    hf_row = row.get("h_far_mm")
    if hf_row is not None and hf_ref is not None and abs(float(hf_ref) - float(hf_row)) > 1e-9:
        bad.append(f"h_far: ref {hf_ref} vs row {hf_row}")
    # prep level (what was actually built): E_canc, interface / ROI mesh size, h_far, applied load vector
    if rprep is None:
        bad.append(f"intact {rid}: prep.json missing (cannot compare the effective E_canc / h_roi / h_far / load_N)")
    else:
        for what, a, b in (("prep E_canc", rprep.get("E_canc"), row.get("E_canc_MPa")),
                           ("prep h_roi (ref) vs h_int (row)", rprep.get("h_roi", rprep.get("h_int")), row.get("h_int_prep_mm")),
                           ("prep h_far", rprep.get("h_far"), row.get("h_far_mm"))):
            if a is None or b is None:
                bad.append(f"{what}: missing (ref {a!r}, row {b!r})")
            elif abs(float(a) - float(b)) > 1e-9:
                bad.append(f"{what}: ref {a} vs row {b}")
        la, lb = rprep.get("load_N"), row.get("load_vec_N")
        if la is None or lb is None:
            bad.append(f"prep load_N missing (ref {la!r}, row {lb!r})")
        elif np.max(np.abs(np.subtract(la, lb))) > 1e-9 * max(1.0, float(np.linalg.norm(la))):
            bad.append(f"prep load_N: ref {la} vs row {lb}")
    if row.get("intact_job") != rid:                                  # ref_check runs on bonded DONE rows: result.json must name it
        bad.append(f"result.json intact_job {row.get('intact_job')!r} != spec intact_job {rid!r}")
    fh_ref = (rprep or {}).get("femur_hook") or {}
    fh_row = row.get("_femur_hook") or {}
    na_r, na_w = (fh_ref.get("neck_axis") or {}).get("u_baked"), (fh_row.get("neck_axis") or {}).get("u_baked")
    if na_r is None or na_w is None:
        bad.append("femur geometry: baked neck axis missing in the prep.json of the ref or the row (cannot compare)")
    elif np.max(np.abs(np.subtract(na_r, na_w))) > 1e-9:
        bad.append("femur geometry: baked neck axis of ref and row differ")
    return (not bad), bad


def export_job(P: Pipeline, ctx: Context, jd: pathlib.Path, with_fields: bool):
    J, G = P.J, P.G
    row = {c: None for c in COLNAMES}
    errs, warns = [], []
    row.update(row_id=jd.name, job_id=jd.name, code_hash_now=ctx.code_hash, aux_code_md5=ctx.aux_md5,
               exporter_version=EXPORTER_VERSION, export_batch=ctx.batch, export_time_utc=ctx.t_utc, export_host=ctx.host,
               export_errors=errs, export_warnings=warns, code_hash_source="unknown", has_prep=False, has_fric_model=False,
               has_bond_model=False)
    field = None
    status = J.state(jd)
    row["status"] = status
    for k, f in (("t_spec_utc", "spec.json"), ("t_prep_utc", "prep.json"), ("t_solved_utc", "SOLVED"), ("t_done_utc", "DONE"),
                 ("t_failed_utc", "FAILED.json")):
        row[k] = utc(_mtime(jd / f))
    row["t_ready_utc"] = utc(_mtime(jd / "READY") or _mtime(jd / "CLAIMED"))
    if status == "MISSING":
        errs.append("spec.json missing")
        row.update(source="unknown", selection="stratum", layer="unknown", provenance="none")
        return row, None
    spec = _read_json(jd / "spec.json", errs, "spec.json")
    if spec is None:
        row.update(source="unknown", selection="stratum", layer="unknown", provenance="none")
        return row, None
    kind = spec.get("kind")
    row.update(stage=spec.get("stage"), tag=spec.get("tag"), kind=kind, created_local=spec.get("created"), spec_hash=spec_hash(spec),
               bond_only=bool(spec.get("bond_only")), fric_only=bool(spec.get("fric_only")), cfg_override=spec.get("cfg"),
               h_int_mm=_num(spec.get("h_int")), delta_spec_mm=_num(spec.get("delta")), entry_offset_forced_mm=_num(spec.get("entry_offset")),
               collar_rule=spec.get("collar_rule"), margin_check=spec.get("margin_check"), a_bounds_max=_num(spec.get("a_bounds_max")),
               torsion=spec.get("torsion"), pose=spec.get("pose_fixed"), foam_refine=spec.get("foam_refine"),
               ref_cut_mm=_num(spec.get("ref_cut_mm")), min_A0_mm2=_num(spec.get("min_A0")), source_job=spec.get("source_job"),
               intact_job_spec=spec.get("intact_job"))
    fid = spec.get("femur_id")
    row["femur_id"] = fid or ""
    row["neck_axis"] = spec.get("neck_axis")
    if fid in FEMUR_VERSIONS:
        row["femur_geom_key"] = ctx.femur_geom_key
        row["femur_model_version"], row["hollow_core"] = FEMUR_VERSIONS[fid]
    else:
        row["femur_geom_key"], row["femur_model_version"], row["hollow_core"] = "", "CT", False
        errs.append(f"femur_id {fid!r} is not a 3406 femur")
    try:
        row["job_id_matches_code"] = J.job_id(spec) == jd.name
    except Exception as e:  # noqa: BLE001
        errs.append(f"job_id recompute: {type(e).__name__}: {e}")
    # ---- design
    dsg = None
    if kind in ("design", "variant"):
        dsg = G.design_of_spec(spec)
        h_cut = float(spec.get("h_cut", 25.0))
        for k in DESIGN_VARS:
            row[k] = float(h_cut if k == "h_cut" else dsg[k])
        u = unit_coords(dsg, h_cut, "v1")
        for k in DESIGN_VARS:
            row["u_" + k] = u[k]
        row["bounds_version"] = "v1"
        row["in_bounds_v1"] = all(-1e-9 <= u[k] <= 1 + 1e-9 for k in DESIGN_VARS)
        row["cap_h_mm"] = _num(spec["design"].get("cap_h"))
        row["collar_w_mm"] = float(spec["design"].get("collar_w", 0.0))
        row["design_key"] = design_key(dsg, h_cut)
        row["realization_key"] = sha1(jdump([row["design_key"], row["femur_id"], row["femur_geom_key"], spec.get("collar_rule"),
                                             spec.get("margin_check"), spec.get("a_bounds_max"), spec.get("neck_axis"),
                                             spec.get("min_A0"), spec.get("entry_offset")]))
    # ---- FAILED
    if (jd / "FAILED.json").exists():
        fj = _read_json(jd / "FAILED.json", errs, "FAILED.json") or {}
        row.update(fail_level=fj.get("level"), fail_stage=fj.get("stage"), fail_reason=str(fj.get("reason", ""))[:500],
                   result_code=fj.get("code"))                      # None for records before 2026-11-11: finalize fills it from the text
    # ---- prep
    prep = None
    if (jd / "prep.json").exists():
        prep = _read_json(jd / "prep.json", errs, "prep.json")
    if prep is not None:
        row["has_prep"] = True
        row["code_hash"] = prep.get("code_hash")
        row["code_hash_source"] = "prep.json"
        # femur geometry bound to job time (plan 1.6 trap 3): the hashed files must predate this job's prep
        t_prep = (jd / "prep.json").stat().st_mtime
        if ctx.femur_geom_mtime_max <= t_prep:
            if ctx.prep_host:
                row["femur_geom_verified"], row["femur_geom_basis"] = True, "files_older_than_prep"
            else:                                                    # mtimes of another host's copy say nothing about job time
                row["femur_geom_verified"], row["femur_geom_basis"] = False, ""
                warns.append("not the prep host: femur_geom_key is bound to job time by finalize (femur registry window)")
        else:
            row["femur_geom_verified"], row["femur_geom_basis"] = False, ""
            msg = (f"femur geometry files modified after this job's prep (newest {utc(ctx.femur_geom_mtime_max)} > prep.json "
                   f"{utc(t_prep)}): the export-time femur_geom_key is not the job-time geometry")
            (errs if ctx.prep_host else warns).append(msg + ("" if ctx.prep_host else " (not the prep host; finalize checks the registry)"))
        row["h_int_prep_mm"] = _num(prep.get("h_int", prep.get("h_roi")))
        st_ = prep.get("steps")
        row["steps"] = list(st_) if isinstance(st_, list) else None
        row["delta_mm"] = _num(prep.get("delta"))
        row["mu"] = _num(prep.get("mu"))
        row["E_canc_MPa"] = _num(prep.get("E_canc"))
        row["h_far_mm"] = _num(prep.get("h_far"))
        row["slip_tol"] = _num(prep.get("slip_tol"))
        row["cycles"] = _num(prep.get("cycles"))
        row["interference"] = prep.get("interference")
        row["torque"] = prep.get("torque")
        row["load_vec_N"] = prep.get("load_N")
        nt = prep.get("n_tet") or {}
        row.update(n_tet_cortex=nt.get("cortex"), n_tet_cancellous=nt.get("cancellous"), n_tet_stem=nt.get("stem"),
                   n_tet_total=(sum(int(v) for v in nt.values()) if nt else None), n_nodes=prep.get("n_nodes"),
                   n_pairs=prep.get("n_pairs"), n_pairs_cortex=prep.get("n_pairs_cortex"),
                   interface_area_mm2=_num(prep.get("interface_area_mm2")), stem_volume_mm3=_num(prep.get("stem_volume_mm3")))
        ma = prep.get("mesh_attempt") or {}
        row.update(mesh_algo=ma.get("algorithm3d"), mesh_h_used_mm=_num(ma.get("h_int")), mesh_section_points=ma.get("section_points"),
                   mesh_retries=(len(ma.get("previous_errors") or []) if ma else None))
        mv = ((prep.get("mesh_quality") or {}).get("min_vol") or {}).values()
        row["mesh_min_vol_mm3"] = float(min(mv)) if mv else None
        tp = prep.get("templating") or {}
        for k in ("alpha", "e", "A0", "contact", "s_bind", "volume", "margin"):
            row["tpl_" + k] = _num(tp.get(k))
        bl = prep.get("bone_loss") or {}
        row.update(bone_resected_mm3=_num(bl.get("resected_mm3")), bone_reamed_mm3=_num(bl.get("reamed_mm3")),
                   bone_total_mm3=_num(bl.get("total_mm3")))
        row["_femur_hook"] = prep.get("femur_hook")
        h_prep = prep.get("h_int", prep.get("h_roi"))
        row["cons_h_int"] = h_prep is not None and spec.get("h_int") is not None and abs(float(h_prep) - float(spec["h_int"])) < 1e-12
        if spec.get("delta") is not None:
            row["cons_delta"] = prep.get("delta") is not None and abs(float(prep["delta"]) - float(spec["delta"])) < 1e-12
        elif kind in ("design", "variant"):
            row["cons_delta"] = prep.get("delta") is not None
        elif kind == "intact":
            row["cons_delta"] = True
    if prep is None:
        row["femur_geom_basis"] = "no_prep"                          # no model was built: nothing to bind (labels are empty)
    if prep is None and row["job_id_matches_code"]:
        row["code_hash"], row["code_hash_source"] = ctx.code_hash, "job_id_recomputed"
    # ---- effective load + femur pose
    fm = None
    try:
        fm = ctx.femur(spec)
        L = fm.cfg["load"]
        row.update(load_R_N=float(L["resultant_N"]), alpha_front_deg=float(L["alpha_front_deg"]), alpha_sagit_deg=float(L["alpha_sagit_deg"]),
                   head_coupling_radius_mm=float(L.get("head_coupling_radius_mm", float("nan"))))
    except Exception as e:  # noqa: BLE001
        errs.append(f"femur_for: {type(e).__name__}: {e}")
    if prep is not None and row["load_vec_N"] is not None and row["load_R_N"] is not None:
        F = np.asarray(row["load_vec_N"], float)
        row["load_vec_norm_N"] = float(np.linalg.norm(F))
        af = math.degrees(math.atan2(abs(F[0]), abs(F[2])))
        asg = math.degrees(math.atan2(abs(F[1]), abs(F[2])))
        row["cons_load"] = (abs(row["load_vec_norm_N"] - row["load_R_N"]) <= 1e-6 * row["load_R_N"]
                            and abs(af - row["alpha_front_deg"]) < 1e-6 and abs(asg - row["alpha_sagit_deg"]) < 1e-6)
    if fm is not None and prep is not None and prep.get("femur_hook"):
        fh = prep["femur_hook"]
        try:
            dev = float(np.max(np.abs(np.asarray(fh["cut_centre_m"], float) - np.asarray(fm.C03, float))))
            na = (fh.get("neck_axis") or {}).get("u_baked")
            na_now = (fm.lm.get("neck_axis") or {}).get("u_baked")
            if na is not None and na_now is not None:
                dev = max(dev, float(np.max(np.abs(np.subtract(na, na_now)))))
            row["femur_pose_dev_mm"] = dev
            row["femur_pose_match"] = dev <= 1e-9
            if dev > 1e-9:
                errs.append(f"femur pose differs from prep time by {dev:.3g} (cut centre / neck axis)")
        except Exception as e:  # noqa: BLE001
            errs.append(f"femur pose check: {type(e).__name__}: {e}")
    tpl = (prep or {}).get("templating")
    if fm is not None and tpl and row["load_vec_N"] is not None:
        try:
            P0, ax, _, _ = fm.pose(tpl["alpha"], tpl["e"])
            ax = np.asarray(ax, float) / np.linalg.norm(ax)
            Mv = np.cross(np.asarray(fm.H, float) - np.asarray(P0, float), np.asarray(row["load_vec_N"], float))
            T = float(Mv @ ax)
            row["torque_stem_axis_Nmm"] = T
            row["moment_shoulder_bend_Nmm"] = float(np.linalg.norm(Mv - T * ax))
        except Exception as e:  # noqa: BLE001
            errs.append(f"load moments: {type(e).__name__}: {e}")
    # ---- condition key
    fr = spec.get("foam_refine")
    row["fidelity"] = f"h{float(spec.get('h_int', float('nan'))):g}" + (f"+f5h{float(fr['h']):g}" if isinstance(fr, dict) and fr.get("h") is not None else "")
    cfg_other = {k: v for k, v in (spec.get("cfg") or {}).items() if k != "load"}
    f5_key = {"foam_refine": fr} if fr is not None else {}           # only F5 rows: older rows keep their cond_key bit for bit
    row["cond_key"] = sha1(jdump({**f5_key, "delta": row["delta_mm"] if row["delta_mm"] is not None else row["delta_spec_mm"], "mu": row["mu"],
                                  "E_canc": row["E_canc_MPa"] if row["E_canc_MPa"] is not None else spec.get("E_canc"),
                                  "R": row["load_R_N"], "af": row["alpha_front_deg"], "as": row["alpha_sagit_deg"],
                                  "hcr": row["head_coupling_radius_mm"], "h_far": row["h_far_mm"], "slip_tol": row["slip_tol"],
                                  "cycles": row["cycles"], "interference": row["interference"], "torque": row["torque"],
                                  "lagrange": spec.get("lagrange"), "cfg_other": cfg_other, "entry_offset": spec.get("entry_offset")}))
    # ---- solve.json
    if (jd / "solve.json").exists():
        sv = _read_json(jd / "solve.json", errs, "solve.json") or {}
        for nm, col in (("m_fric", "fric"), ("m_bond", "bond")):
            if nm in sv:
                row[f"solve_wall_s_{col}"] = _num(sv[nm].get("wall_s"))
                row[f"solve_tries_{col}"] = _num(sv[nm].get("tries"))
        solvers, steps_by_model = set(), {}
        for nm, ent in sorted(sv.items()):
            if not isinstance(ent, dict):
                continue
            om = ent.get("odb_meta") or {}
            if ent.get("solver"):
                solvers.add(str(ent["solver"]).lower())
            elif str(om.get("odb", "")).lower().endswith(".odb"):
                solvers.add("abaqus")
            if om.get("steps"):
                steps_by_model[nm] = [s.get("name") for s in om["steps"]]
        if len(solvers) == 1:
            row["solver"] = solvers.pop()
        elif len(solvers) > 1:
            errs.append(f"solve.json: more than one solver {sorted(solvers)}")
        if row["steps"] is None and steps_by_model:                 # intact / bond-only models: prep.json has no 'steps'
            row["steps"] = steps_by_model[sorted(steps_by_model)[0]]
    if status == "DONE" and row["solver"] is None:
        errs.append("solver not identifiable from solve.json (no 'solver' key and no *.odb in odb_meta)")
    # ---- selection
    rec = ctx.records.get(jd.name)
    row.update(classify(jd.name, spec, rec))
    row["provenance"] = "rule"
    if jd.name.startswith(RECORD_REQUIRED_PREFIXES) and kind in ("design", "variant") and rec is None:
        errs.append(f"no BO record for {jd.name} in {ctx.results_root}/neckopt_p11..14.json (pool_idx / round / acq lost; on Windows "
                    "pass --results-root <db3406/raw/results/<snapshot>>)")
    apply_db_provenance(row, spec, ctx.db_prov.get(jd.name), ctx.femur_geom_key, errs)
    if rec and rec.get("rot_first_deg") is not None:
        row["rot_record_deg"] = float(rec["rot_first_deg"])
    if row.get("source_job"):                                     # spec source_job, else the manifest's (apply_db_provenance)
        sj = P.qroot / row["source_job"]
        try:
            ssp = json.loads((sj / "spec.json").read_text())
            if ssp.get("design") is not None:
                row["source_job_design_key"] = design_key(G.design_of_spec(ssp), float(ssp.get("h_cut", 25.0)))
            if (sj / "prep.json").exists():
                nt = json.loads((sj / "prep.json").read_text()).get("n_tet") or {}
                row["source_job_n_tet_total"] = sum(int(v) for v in nt.values()) if nt else None
        except Exception as e:  # noqa: BLE001
            errs.append(f"source_job {row['source_job']}: {type(e).__name__}: {e}")
    if kind in ("design", "variant"):
        try:
            ph = P.phases()
            row["in_family_phases"] = [p for p, o in ph.items() if o.in_family(spec)]
        except Exception as e:  # noqa: BLE001
            errs.append(f"in_family: {type(e).__name__}: {e}")
    else:
        row["in_family_phases"] = []
    # ---- results
    if status == "DONE":
        res = _read_json(jd / "result.json", errs, "result.json")
        if res is None:
            row["export_status"] = "error"
            return row, None
        if "spec" in res:
            row["spec_in_result_match"] = jdump(res.get("spec")) == jdump(spec)
        elif kind != "intact":                                         # intact results carry no spec copy: left empty (n/a)
            row["spec_in_result_match"] = False
            errs.append("result.json has no spec copy")
        if kind == "intact":
            for k in ("gruen7", "gruen1", "gruen7_vol_mm3", "gruen1_vol_mm3"):
                row[RESULT_MAP[k]] = _num(res.get(k))
        elif kind in ("design", "variant"):
            has_f, has_b = (jd / "m_fric_csv").is_dir(), (jd / "m_bond_csv").is_dir()
            row["has_fric_model"], row["has_bond_model"] = has_f, has_b
            if has_f == bool(spec.get("bond_only")):
                errs.append(f"m_fric_csv present = {has_f} but bond_only = {bool(spec.get('bond_only'))}")
            if has_b == bool(spec.get("fric_only")):
                errs.append(f"m_bond_csv present = {has_b} but fric_only = {bool(spec.get('fric_only'))}")
            extra = {}
            for k, v in res.items():
                if k in RESULT_SKIP:
                    continue
                col = RESULT_MAP.get(k, k)
                if col in RESULT_COLS:
                    row[col] = _num(v)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    extra[k] = v
            if extra:
                warns.append(f"result keys without a column: {sorted(extra)}")
            if has_b:
                row["intact_job"] = res.get("intact_job")
                row["intact_substituted_h"] = _num(res.get("intact_substituted_h"))
                try:
                    rows_rs, _ = P.RS.design_rows(jd.name, iname=spec["intact_job"]) if spec.get("femur_id") else P.RS.design_rows(jd.name)
                    g7 = next((r for r in rows_rs if r["scheme"] == "fixed" and r["zone"] == "G7" and r["tissue"] == "cortex"), {})
                    for k in ("ssi_pct", "sed_chg_pct"):
                        v = g7.get(k)
                        row[k] = None if v is None or not np.isfinite(v) else float(v)
                    if row["sed_chg_pct"] is None:
                        errs.append("calcar: G7 cortex sed_chg_pct missing (zone volume < MIN_VOL?)")
                except Exception as e:  # noqa: BLE001
                    row["calcar_error"] = f"{type(e).__name__}: {str(e)[:300]}"
                    errs.append(f"calcar: {row['calcar_error']}")
                ok, bad = ref_check(P, ctx, spec, row)
                row["ref_match"], row["ref_mismatch"] = ok, (bad or None)
                if not ok:
                    errs.append(f"intact reference mismatch: {bad}")
            if has_f:
                try:
                    st = P.ST.stability(jd)
                    for k, v in st.items():
                        if k in STAB_KEY_TO_COL:
                            row[STAB_KEY_TO_COL[k]] = _num(v)
                        elif isinstance(v, (int, float)) and not isinstance(v, bool):
                            extra[f"stability.{k}"] = v
                            warns.append(f"stability key without a column: {k}")
                    missing = sorted(stab_key(c) for c in STAB_REQUIRED if stab_key(c) not in st)
                    if missing:
                        errs.append(f"stability: keys missing from the result: {missing}")
                except Exception as e:  # noqa: BLE001
                    errs.append(f"stability: {type(e).__name__}: {str(e)[:300]}")
                if row["rot_record_deg"] is not None and row["rot_first_deg"] is not None:
                    row["rot_record_match"] = rel_err(row["rot_first_deg"], row["rot_record_deg"]) <= 1e-9
                if with_fields:
                    try:
                        t = res.get("templating") or tpl
                        arr, meta = build_field(P, ctx, jd, spec, t, ctx.femur(spec), errs)
                        T = meta["tri"]
                        row["field_n_nodes"], row["field_n_tri"] = int(len(arr["area"])), int(len(T))
                        fo = meta["foam"]
                        row["foam_thk_p05_mm"], row["foam_thk_p50_mm"], row["area_foam_lt1_mm2"] = \
                            fo["foam_p05"], fo["foam_p50"], fo["foam_lt1"]
                        row["tri_area_ratio"] = tri_area(arr["X"], T) / float(arr["area"].sum())
                        lv = row["load_vec_N"]
                        if lv is not None:
                            Lv = np.asarray(lv, float)
                            for i, s in enumerate(("load", "load2")):
                                Fs = arr["cforce"][:, i].astype(np.float64)
                                if np.isfinite(Fs).all():
                                    tot = Fs.sum(0)
                                    if s == "load":
                                        row["iface_force_load_N"] = tot.tolist()
                                    row[f"iface_force_err_{s}"] = float(np.linalg.norm(tot - Lv) / np.linalg.norm(Lv))
                        field = (arr, meta, lv)
                    except Exception as e:  # noqa: BLE001
                        errs.append(f"field: {type(e).__name__}: {str(e)[:300]}\n{traceback.format_exc()[-600:]}")
            row["extra_result_keys"] = extra or None
    elif status != "FAILED":
        warns.append(f"job is {status} (not finished); labels empty")
    if row.get("selection") is None:
        warns.append("selection not derivable from stage rules; needs a provenance entry (finalize)")
    row["export_status"] = "error" if errs else "ok"
    return row, field


def select_jobs(P: Pipeline, a) -> list[pathlib.Path]:
    if a.jobs:
        out = []
        for j in a.jobs:
            d = P.qroot / j
            if not d.is_dir():
                raise FileNotFoundError(f"job dir {d} does not exist")
            out.append(d)
        return out
    sel = []
    for d in sorted(P.qroot.iterdir()):
        sp = d / "spec.json"
        if not d.is_dir() or not sp.exists():
            continue
        try:
            if json.loads(sp.read_text()).get("femur_id") == FEMUR_ID:
                sel.append(d)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{sp}: unreadable spec ({e}) -- refusing to silently skip it")
    sel = sel[a.offset:]
    return sel[:a.limit] if a.limit else sel


def queue_scan(P: Pipeline, db_prov: dict | None = None) -> tuple[dict, dict, list]:
    """(exclusion set E over the whole queue, inventory of every 3406 job dir, notes).
    E = designs of jobs named E_JOB_PREFIXES + designs of db_* jobs whose manifest source is in E_SOURCES; a db_* job without any
    manifest / seed entry enters E conservatively (noted) -- its own row is an export error anyway."""
    E, inv, notes = {}, {}, []
    db_prov = db_prov or {}
    for d in sorted(P.qroot.iterdir()):
        sp = d / "spec.json"
        if not d.is_dir() or not sp.exists():
            continue
        try:
            spec = json.loads(sp.read_text())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{sp}: unreadable spec ({e})")
        if spec.get("femur_id") != FEMUR_ID:
            continue
        inv[d.name] = {"state": P.J.state(d), "stage": spec.get("stage"), "kind": spec.get("kind")}
        if spec.get("design") is None:
            continue
        why = None
        if d.name.startswith(E_JOB_PREFIXES):
            why = "name prefix"
        elif str(spec.get("stage", "")).startswith("db_"):
            ents = db_prov.get(d.name) or []
            if not ents:
                why = "db_* job without manifest entry (conservative)"
                notes.append(f"{d.name}: db_* job without a D1 manifest / seed entry -> design put into E conservatively")
            elif any(e.get("source") in E_SOURCES for e in ents):
                why = "manifest source"
        if why:
            dk = design_key(P.G.design_of_spec(spec), float(spec.get("h_cut", 25.0)))
            E.setdefault(dk, []).append(d.name)
    return E, inv, notes


def job_listing(P: Pipeline, a) -> dict:
    """ONE listing of the queue for a frozen job list (pull --list-only): every 3406 job dir with its state, and the selection."""
    inv = {}
    for d in sorted(P.qroot.iterdir()):
        sp = d / "spec.json"
        if not d.is_dir() or not sp.exists():
            continue
        try:
            spec = json.loads(sp.read_text())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"{sp}: unreadable spec ({e}) -- refusing to silently skip it")
        if spec.get("femur_id") == FEMUR_ID:
            inv[d.name] = {"state": P.J.state(d), "stage": spec.get("stage"), "kind": spec.get("kind")}
    if a.jobs:
        missing = [j for j in a.jobs if j not in inv]
        if missing:
            raise FileNotFoundError(f"--jobs not found among the 3406 job dirs of {P.qroot}: {missing}")
        sel = sorted(set(a.jobs))
    else:
        sel = sorted(inv)
    if a.finished_only:
        sel = [j for j in sel if inv[j]["state"] in ("DONE", "FAILED")]
    excl = tuple(getattr(a, "exclude_prefix", None) or ())
    if excl:
        sel = [j for j in sel if not j.startswith(excl)]
    return {"kind": "db3406 frozen job list", "listed_utc": now_utc(), "host": socket.gethostname(), "queue_root": str(P.qroot),
            "exporter_version": EXPORTER_VERSION, "femur_id": FEMUR_ID,
            "filter": {"select_3406": bool(a.select_3406), "jobs": a.jobs, "finished_only": bool(a.finished_only),
                       "exclude_prefix": list(excl)},
            "inventory": inv, "jobs": sel,
            "by_state": {s: sum(1 for v in inv.values() if v["state"] == s) for s in sorted({v["state"] for v in inv.values()})}}


def cmd_emit(a) -> int:
    t0 = time.time()
    if a.list_only:                                                      # one listing, JSON on stdout, nothing written anywhere
        real = os.fdopen(os.dup(1), "wb", buffering=0)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
        sys.dont_write_bytecode = True
        if not a.no_guard:
            install_guard([])
        home = pathlib.Path.home()
        code_root = pathlib.Path(a.code_root).expanduser() if a.code_root else home / "mobo_toy_v2" / "code"
        P = Pipeline(code_root, pathlib.Path(a.queue_root).expanduser() if a.queue_root else None)
        lst = job_listing(P, a)
        lst["guard_blocked"] = list(_GUARD["blocked"])
        real.write(json.dumps(lst, indent=1, sort_keys=True).encode())
        real.close()
        log(f"list-only: {len(lst['jobs'])} jobs selected of {len(lst['inventory'])} 3406 job dirs {lst['by_state']}")
        return 0 if not _GUARD["blocked"] else 3
    if a.out_dir is None:                                                # tar on the real stdout; every print goes to stderr
        real = os.fdopen(os.dup(1), "wb", buffering=0)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
        sink = TarSink(real)
        allowed = []
    else:
        out = pathlib.Path(a.out_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)
        sink = DirSink(out)
        allowed = [str(out)]
    sys.dont_write_bytecode = True
    if not a.no_guard:
        install_guard(allowed + [str(pathlib.Path(p).resolve()) for p in (a.guard_allow or [])])
    home = pathlib.Path.home()
    fl = free_gb(home)
    if fl < LINUX_MIN_FREE_GB and a.out_dir is None:
        log(f"DISK GATE: free {fl:.1f} GB < {LINUX_MIN_FREE_GB} GB on {home}; refusing to start")
        sink.close({"batch": a.batch, "aborted": f"disk gate {fl:.1f} GB"})
        return 4
    code_root = pathlib.Path(a.code_root).expanduser() if a.code_root else home / "mobo_toy_v2" / "code"
    default_code = pathlib.Path(code_root).resolve() == (home / "mobo_toy_v2" / "code").resolve()
    P = Pipeline(code_root, pathlib.Path(a.queue_root).expanduser() if a.queue_root else None)
    ctx = Context(P, a.batch, a.odb_export_md5, a.results_root, default_code_root=default_code)
    if ctx.code_hash != EXPECTED_CODE_HASH:
        log(f"WARNING code hash now {ctx.code_hash} != expected {EXPECTED_CODE_HASH}")
    for pr in ctx.db_prov_problems:
        log(f"PROVENANCE PROBLEM: {pr}")
    jobs = select_jobs(P, a)
    log(f"batch {a.batch}: {len(jobs)} jobs, code {ctx.code_hash}, femur key {ctx.femur_geom_key}, records {len(ctx.records)}, "
        f"db provenance {len(ctx.db_prov)} jobs, prep host {ctx.prep_host}, free {fl:.1f} GB")
    E, inv, e_notes = queue_scan(P, ctx.db_prov)
    shards = ShardBuilder(a.batch, a.shard_size)
    rows, timing, elog = [], [], {}
    for i, jd in enumerate(jobs):
        t1 = time.time()
        try:
            row, fld = export_job(P, ctx, jd, not a.no_fields)
        except Exception as e:  # noqa: BLE001  -- an exporter bug must still leave a row and an error, never a silent gap
            row = {c: None for c in COLNAMES}
            row.update(row_id=jd.name, job_id=jd.name, status=P.J.state(jd), export_status="error", source="unknown", selection="stratum", layer="unknown", provenance="none",
                       export_errors=[f"exporter crash: {type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"],
                       export_warnings=[], exporter_version=EXPORTER_VERSION, export_batch=a.batch, export_time_utc=ctx.t_utc,
                       export_host=ctx.host, code_hash_now=ctx.code_hash, aux_code_md5=ctx.aux_md5, code_hash_source="unknown",
                       has_prep=False, has_fric_model=False, has_bond_model=False)
            fld = None
        if fld is not None:
            shards.add(row, *fld)
            if shards.full():
                shards.flush(sink, elog)
                if a.out_dir is None and free_gb(home) < LINUX_MIN_FREE_GB:
                    row["export_errors"].append("Linux disk gate tripped during export")
        rows.append(row)
        dt = time.time() - t1
        timing.append({"job": jd.name, "s": dt, "status": row["status"], "n_nodes": row.get("field_n_nodes")})
        log(f"{i + 1}/{len(jobs)} {jd.name} {row['status']} {row['export_status']} {dt:.1f}s"
            + (f" errors: {row['export_errors']}" if row["export_errors"] else ""))
    shards.flush(sink, elog)
    for r in rows:
        if ctx.db_prov_problems and str(r.get("stage") or "").startswith("db_"):
            r["export_errors"].append(f"provenance files have problems: {ctx.db_prov_problems[:5]}")
        r["export_status"] = "error" if r["export_errors"] else "ok"
        r.pop("_femur_hook", None)
    errors = {r["job_id"]: r["export_errors"] for r in rows if r["export_errors"]}
    body = "\n".join(json.dumps(r, sort_keys=True, default=_jdefault) for r in rows).encode() + b"\n"
    pre = f"export/{a.batch}"
    sink.add(f"{pre}/rows.jsonl", body)
    sink.add(f"{pre}/context.json", json.dumps(ctx.as_dict(), indent=1, sort_keys=True, default=_jdefault).encode())
    sink.add(f"{pre}/exclusion.json", json.dumps({"rule": f"design_key of every queue job whose name starts with {list(E_JOB_PREFIXES)}, "
                                                           f"and of db_* jobs whose manifest source is in {sorted(E_SOURCES)}",
                                                   "candidates": CANDIDATE_JOBS, "design_keys": E, "notes": e_notes},
                                                  indent=1, sort_keys=True).encode())
    sink.add(f"{pre}/inventory.json", json.dumps({"femur_id": FEMUR_ID, "jobs": inv, "selected": [d.name for d in jobs],
                                                   "selection_args": {"jobs": a.jobs, "select_3406": bool(a.select_3406),
                                                                      "offset": a.offset, "limit": a.limit,
                                                                      "frozen_list_sha256": a.frozen_sha256,
                                                                      "frozen_list_offset": a.frozen_offset,
                                                                      "frozen_list_limit": a.frozen_limit},
                                                   "listed_utc": ctx.t_utc}, indent=1, sort_keys=True).encode())
    mx = {}
    for k in REAGG_REF:
        v = [float(r[f"fld_err_{k}"]) for r in rows if r.get(f"fld_err_{k}") is not None]
        mx[k] = {"max": max(v) if v else None, "n": len(v), "n_nan": sum(1 for x in v if x != x)}
    elog.update({"batch": a.batch, "n_rows": len(rows), "n_error_rows": len(errors), "errors": errors, "timing": timing,
                 "wall_s": time.time() - t0, "guard_blocked": list(_GUARD["blocked"]), "free_gb_start": fl, "fld_err": mx})
    sink.add(f"{pre}/export_log.json", json.dumps(elog, indent=1, sort_keys=True, default=_jdefault).encode())
    sink.close({"batch": a.batch, "exporter_version": EXPORTER_VERSION, "closed_utc": now_utc(), "n_rows": len(rows),
                "n_error_rows": len(errors), "guard_blocked": list(_GUARD["blocked"])})
    log(f"done: {len(rows)} rows, {len(errors)} with errors, guard blocked {len(_GUARD['blocked'])}, {time.time() - t0:.1f}s")
    if _GUARD["blocked"]:
        log("GUARD BLOCKED WRITES: " + "; ".join(_GUARD["blocked"][:20]))
    if errors:
        for j, e in list(errors.items())[:20]:
            log(f"ERROR {j}: {e}")
    return 0 if not errors and not _GUARD["blocked"] else 3


# ================================================================================================ pull (Windows side)
def _check_out_disk(out: pathlib.Path, min_free: float) -> None:
    f = free_gb(out)
    if f < min_free:
        raise SystemExit(f"DISK GATE: {out.anchor or out} has {f:.1f} GB free < {min_free} GB")
    h = pathlib.Path("H:/")
    if h.exists():
        fh = free_gb(h)
        if fh < H_MIN_FREE_GB:
            raise SystemExit(f"DISK GATE: H: has {fh:.1f} GB free < {H_MIN_FREE_GB} GB")


REMOTE_ENV = ("PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 "
              "NUMEXPR_NUM_THREADS=1 MPLBACKEND=Agg")


REMOTE_CWD_RE = re.compile(r"^[A-Za-z0-9_$/.\-]+$")


def _remote(a, args: list) -> str:
    script = a.remote_script or "-"
    cwd = getattr(a, "remote_cwd", None) or "$HOME/mobo_toy_v2/code"   # emit reads code / queue by absolute paths; cwd is cosmetic
    if not REMOTE_CWD_RE.match(cwd):
        raise SystemExit(f"--remote-cwd {cwd!r}: letters, digits, $ / . _ - only")
    return (f"cd {cwd} && exec env {REMOTE_ENV} nice -n 19 taskset -c 4-11 timeout {int(a.remote_timeout)} "
            f"$HOME/mobo_toy_v2/run.sh {shlex.quote(script) if script != '-' else '-'} " + " ".join(shlex.quote(x) for x in args))


def remote_emit_cmd(a, odb_md5: str | None, jobs: list | None = None, frozen: dict | None = None) -> str:
    args = ["emit", "--batch", a.batch, "--shard-size", str(a.shard_size)]
    jobs = jobs if jobs is not None else a.jobs
    if jobs:
        args += ["--jobs", *jobs]
    else:
        args += ["--select-3406", "--offset", str(a.offset)] + (["--limit", str(a.limit)] if a.limit else [])
    if frozen:
        args += ["--frozen-sha256", frozen["sha256"], "--frozen-offset", str(frozen["offset"]), "--frozen-limit", str(frozen["limit"])]
    if a.no_fields:
        args.append("--no-fields")
    if odb_md5:
        args += ["--odb-export-md5", odb_md5]
    return _remote(a, args)


def remote_list_cmd(a) -> str:
    args = ["emit", "--list-only"]
    if a.jobs:
        args += ["--jobs", *a.jobs]
    else:
        args.append("--select-3406")
    if a.finished_only:
        args.append("--finished-only")
    if a.exclude_prefix:
        args += ["--exclude-prefix", *a.exclude_prefix]
    return _remote(a, args)


class _NullTar:
    """Stand-in when the remote side produced no tar stream at all (the problem is already recorded)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())


def _safe_member(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and (name == "STREAM_MANIFEST.json" or p.parts[0] in ("export", "fields"))


def _abort_proc(proc, wait_s: float = 30.0) -> str:
    """Close our end of the stream, kill the producer (ssh) and reap it; never blocks longer than wait_s."""
    notes = []
    for f in (proc.stdout,):
        try:
            if f is not None:
                f.close()
        except Exception as e:  # noqa: BLE001
            notes.append(f"close stdout: {type(e).__name__}: {e}")
    try:
        proc.kill()
    except Exception as e:  # noqa: BLE001
        notes.append(f"kill: {type(e).__name__}: {e}")
    try:
        rc = proc.wait(timeout=wait_s)
        notes.append(f"producer rc {rc} after kill")
    except subprocess.TimeoutExpired:
        notes.append(f"producer did not exit within {wait_s:.0f} s after kill")
    return "; ".join(notes)


def quarantine_batch(out: pathlib.Path, batch: str, rep: dict, received: dict, partial: list) -> pathlib.Path:
    """Failed pull: write PULL_BAD.json into export/<batch>/, move the batch's received shards (and any .part file) into it, and
    rename export/<batch> -> export/<batch>.BAD (.BAD.2, ... if taken). finalize skips dotted dirs; nothing half-received stays
    where a later finalize / QA would read it."""
    bdir = out / "export" / batch
    bdir.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in sorted(set(received) | set(partial)):
        src = out / name
        if not src.exists() or not name.startswith("fields/"):
            continue
        dst = bdir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        moved.append(name)
    rep = {**rep, "moved_into_bad_dir": moved}
    (bdir / "PULL_BAD.json").write_text(json.dumps(rep, indent=1, default=str))
    if (bdir / "PULL_OK.json").exists():                       # never leave an OK marker next to a BAD report
        os.replace(bdir / "PULL_OK.json", bdir / "PULL_OK.json.stale")
    k, target = 1, out / "export" / f"{batch}.BAD"
    while target.exists():
        k += 1
        target = out / "export" / f"{batch}.BAD.{k}"
    replace_retry(bdir, target)
    return target


def replace_retry(src: pathlib.Path, dst: pathlib.Path, tries: int = 40, delay: float = 0.25) -> None:
    """os.replace with retries on PermissionError: on Windows a just-closed file (virus scan, indexer) can briefly block renaming its
    directory (seen once in the 2026-10-26 unit test). Still failing after ~10 s -> the PermissionError is raised."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def receive_stream(argv: list, stdin, out: pathlib.Path, batch: str, min_free_gb: float, errlog: pathlib.Path,
                   wait_timeout: float = 1500.0) -> dict:
    """Run the producer (ssh ... emit, or any argv writing an export tar on stdout), extract its members into `out` with a
    per-member sha256, and compare with STREAM_MANIFEST.json. On ANY exception (disk gate SystemExit, write error, bad stream,
    KeyboardInterrupt) the stream is closed, the producer killed and reaped (<= 30 s), PULL_BAD.json written, the batch moved to
    export/<batch>.BAD and the exception re-raised. Returns {got, manifest, problems, rc, wall_s}."""
    t0 = time.time()
    got, problems, partial = {}, [], []
    manifest = None
    fault_after = int(os.environ.get("DB_EXPORT_TEST_FAIL_AFTER_MEMBERS") or 0)   # test hook only: raise after N received members
    with open(errlog, "wb") as fe:
        proc = subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE, stderr=fe)
        try:
            tf = None
            try:
                tf = tarfile.open(fileobj=proc.stdout, mode="r|")
            except tarfile.ReadError as e:
                problems.append(f"remote produced no tar stream ({e}); see {errlog.name}")
            with (tf if tf is not None else _NullTar()) as tf:
                for m in tf:
                    if not m.isfile():
                        problems.append(f"non-file member {m.name!r} ignored")
                        continue
                    if not _safe_member(m.name):
                        problems.append(f"unsafe member name {m.name!r} rejected")
                        continue
                    fh = tf.extractfile(m)
                    if m.name == "STREAM_MANIFEST.json":
                        manifest = json.loads(fh.read())
                        continue
                    _check_out_disk(out, min_free_gb)
                    dst = out / m.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dst.with_name(dst.name + ".part")
                    partial.append(m.name + ".part")
                    h = hashlib.sha256()
                    n = 0
                    with open(tmp, "wb") as fo:
                        for blk in iter(lambda: fh.read(1 << 20), b""):
                            h.update(blk)
                            fo.write(blk)
                            n += len(blk)
                    os.replace(tmp, dst)
                    partial.pop()
                    got[m.name] = {"sha256": h.hexdigest(), "size": n}
                    if fault_after and len(got) >= fault_after:
                        raise RuntimeError(f"test fault injection after {len(got)} members (DB_EXPORT_TEST_FAIL_AFTER_MEMBERS)")
            rest = proc.stdout.read()                                # tar padding after the end-of-archive blocks
            if rest.strip(b"\0"):
                problems.append(f"{len(rest)} bytes of non-padding data after the tar stream")
            try:
                rc = proc.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                problems.append(f"producer still running {wait_timeout:.0f} s after the stream ended: killed")
                _abort_proc(proc)
                rc = proc.returncode
        except BaseException as e:
            note = _abort_proc(proc)
            rep = {"batch": batch, "remote_cmd": argv[-1] if argv else None, "exception": f"{type(e).__name__}: {e}",
                   "traceback": traceback.format_exc()[-3000:], "abort": note, "received": got, "partial": partial,
                   "problems": problems, "wall_s": time.time() - t0, "failed_utc": now_utc()}
            fe.close()                                               # Windows cannot rename a dir with an open file
            where = quarantine_batch(out, batch, rep, got, partial)
            print(f"pull {batch}: FAILED ({type(e).__name__}: {e}); stream closed, producer killed ({note}); batch moved to {where}",
                  file=sys.stderr)
            raise
    return {"got": got, "manifest": manifest, "problems": problems, "rc": rc, "wall_s": time.time() - t0, "partial": partial}


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_frozen_list(out: pathlib.Path, jobs_file: str) -> tuple[list, dict]:
    """The frozen job list of a version dir: <out>/jobs.txt + <out>/jobs_inventory.json (pull --list-only). The jobs file given
    must be byte-identical to the one recorded in jobs_inventory.json."""
    jf = pathlib.Path(jobs_file)
    inv_p = out / "jobs_inventory.json"
    if not inv_p.exists():
        raise SystemExit(f"{inv_p} missing: freeze the list first with `pull --list-only --out {out}`")
    inv = json.loads(inv_p.read_text())
    b = jf.read_bytes()
    if _sha256_bytes(b) != inv.get("jobs_txt_sha256"):
        raise SystemExit(f"{jf} (sha256 {_sha256_bytes(b)[:12]}) is not the frozen list recorded in {inv_p} "
                         f"({str(inv.get('jobs_txt_sha256'))[:12]})")
    names = [x.strip() for x in b.decode().splitlines() if x.strip()]
    if names != inv.get("jobs"):
        raise SystemExit(f"{jf}: names differ from {inv_p}['jobs']")
    return names, inv


def cmd_pull_list(a, out: pathlib.Path) -> int:
    jt, ji = out / "jobs.txt", out / "jobs_inventory.json"
    if (jt.exists() or ji.exists()) and not a.overwrite:
        raise SystemExit(f"{jt} / {ji} exist (the frozen list of this version dir); use --overwrite to replace it")
    cmd = remote_list_cmd(a)
    ssh = [a.ssh, "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", "-i", os.path.expanduser(a.key), a.host, cmd]
    me = pathlib.Path(__file__).resolve()
    with open(me, "rb") as fin:
        p = subprocess.run(ssh, stdin=fin if not a.remote_script else subprocess.DEVNULL, capture_output=True, timeout=a.remote_timeout + 60)
    if p.returncode != 0:
        raise SystemExit(f"remote list failed (rc {p.returncode}):\n{p.stderr.decode(errors='replace')[-2000:]}")
    lst = json.loads(p.stdout)
    if lst.get("kind") != "db3406 frozen job list" or lst.get("guard_blocked"):
        raise SystemExit(f"unexpected listing ({lst.get('kind')!r}, guard blocked {lst.get('guard_blocked')})")
    body = ("\n".join(lst["jobs"]) + "\n").encode()
    lst["jobs_txt_sha256"] = _sha256_bytes(body)
    lst["remote_cmd"] = cmd
    lst["frozen_utc"] = now_utc()
    tmp = jt.with_name("jobs.txt.part")
    tmp.write_bytes(body)
    (out / "jobs_inventory.json.part").write_text(json.dumps(lst, indent=1, sort_keys=True))
    os.replace(tmp, jt)
    os.replace(out / "jobs_inventory.json.part", ji)
    print(f"frozen job list: {len(lst['jobs'])} jobs of {len(lst['inventory'])} 3406 job dirs {lst['by_state']} -> {jt} "
          f"(sha256 {lst['jobs_txt_sha256'][:12]}, listed {lst['listed_utc']})")
    return 0


def cmd_pull(a) -> int:
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if a.list_only:
        return cmd_pull_list(a, out)
    if not BATCH_RE.match(a.batch):
        raise SystemExit(f"--batch {a.batch!r}: letters, digits, '_' and '-' only")
    frozen, jobs = None, None
    if a.jobs_file:
        names, _ = read_frozen_list(out, a.jobs_file)
        sl = names[a.offset:]
        sl = sl[:a.limit] if a.limit else sl
        if not sl:
            raise SystemExit(f"--offset {a.offset} --limit {a.limit}: no jobs left in the frozen list ({len(names)} jobs)")
        jobs = sl
        frozen = {"sha256": _sha256_bytes(pathlib.Path(a.jobs_file).read_bytes()), "offset": a.offset, "limit": a.limit}
    elif not a.jobs:
        raise SystemExit("pull over the live queue (--select-3406 with --offset / --limit) is refused: freeze the list first with "
                         "`pull --list-only --select-3406 [--finished-only] --out V`, then `pull --jobs-file V/jobs.txt ...`")
    _check_out_disk(out, a.min_free_gb)
    bdir = out / "export" / a.batch
    if bdir.exists():
        if not a.overwrite:
            raise SystemExit(f"{bdir} exists; use another --batch or --overwrite")
        stamp = now_utc().replace(":", "").replace("-", "")
        old = out / "export" / f"{a.batch}.replaced.{stamp}"
        for p in sorted((out / "fields").glob(f"iface_{a.batch}_*.npz")) if (out / "fields").exists() else []:
            (bdir / "fields").mkdir(parents=True, exist_ok=True)
            os.replace(p, bdir / "fields" / p.name)
        os.replace(bdir, old)
        print(f"--overwrite: previous batch moved to {old}")
    me = pathlib.Path(__file__).resolve()
    odb = me.parent.parent / "abaqus" / "odb_export.py"
    odb_md5 = md5_file(odb) if odb.exists() else None
    cmd = remote_emit_cmd(a, odb_md5, jobs, frozen)
    ssh = [a.ssh, "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", "-i", os.path.expanduser(a.key), a.host, cmd]
    bdir.mkdir(parents=True, exist_ok=True)
    errlog = bdir / "remote_stderr.log"
    with open(me, "rb") as fin:
        res = receive_stream(ssh, fin if not a.remote_script else subprocess.DEVNULL, out, a.batch, a.min_free_gb, errlog,
                             wait_timeout=a.remote_timeout + 300)
    got, manifest, problems, rc, wall = res["got"], res["manifest"], res["problems"], res["rc"], res["wall_s"]
    if manifest is None:
        problems.append("stream ended without STREAM_MANIFEST.json (remote emit aborted?)")
        tail = errlog.read_text(errors="replace").strip().splitlines()[-3:] if errlog.exists() else []
        problems += [f"remote stderr: {x}" for x in tail]
    else:
        mem = manifest.get("members", {})
        for k, v in mem.items():
            if k not in got:
                problems.append(f"{k}: in manifest but not received")
            elif got[k] != v:
                problems.append(f"{k}: sha256/size differ (Linux {v}, Windows {got[k]})")
        for k in got:
            if k not in mem:
                problems.append(f"{k}: received but not in manifest")
        if manifest.get("aborted"):
            problems.append(f"remote aborted: {manifest['aborted']}")
    rep = {"batch": a.batch, "remote_cmd": cmd, "rc": rc, "wall_s": wall, "received": got, "problems": problems,
           "bytes": sum(v["size"] for v in got.values()), "verified_utc": now_utc(), "frozen_list": frozen}
    ok = not problems and rc in (0, 3)
    print(f"pull {a.batch}: rc {rc}, {len(got)} members, {rep['bytes'] / 1e6:.2f} MB, {wall:.1f} s, problems {len(problems)}")
    for p in problems:
        print("  PROBLEM:", p)
    if not ok:
        where = quarantine_batch(out, a.batch, rep, got, res.get("partial") or [])
        print(f"  batch moved to {where} (PULL_BAD.json inside)")
        return 2
    (bdir / "PULL_OK.json").write_text(json.dumps(rep, indent=1))
    if rc == 3:
        print(f"  remote emit reported per-job errors (see {errlog} and export/{a.batch}/export_log.json)")
    if a.no_finalize:
        return rc
    rc2 = finalize(out, a.db_root, a.provenance, a.allow_errors, registry=a.registry)
    return rc if rc else rc2


# ================================================================================================ finalize
def batch_dirs(out: pathlib.Path) -> tuple[list, list]:
    """(batch dirs to use, skipped dirs): names with a dot are quarantined (<b>.BAD, <b>.BAD.2) or replaced (<b>.replaced.<utc>)."""
    exp = out / "export"
    if not exp.exists():
        raise SystemExit(f"{exp} does not exist")
    use, skip = [], []
    for p in sorted(x for x in exp.iterdir() if x.is_dir()):
        (use if BATCH_RE.match(p.name) else skip).append(p)
    return use, skip


def _load_rows(out: pathlib.Path) -> tuple[list, dict, dict, list]:
    rows, E, inv, ctxs = [], {}, {}, []
    use, skip = batch_dirs(out)
    for p in skip:
        print(f"  skipping quarantined / replaced batch dir export/{p.name}")
    for b in use:
        ok = (b / "PULL_OK.json").exists() or (b / "EMIT_OK.json").exists()
        if not ok:
            raise SystemExit(f"batch {b.name}: no PULL_OK.json / EMIT_OK.json -- not verified; re-pull it or remove the directory")
        with open(b / "rows.jsonl", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
        ex = json.loads((b / "exclusion.json").read_text())
        for dk, js in ex["design_keys"].items():
            E.setdefault(dk, set()).update(js)
        iv = json.loads((b / "inventory.json").read_text())
        inv[b.name] = iv
        ctxs.append(json.loads((b / "context.json").read_text()))
    return rows, E, inv, ctxs


def _load_provenance(paths) -> dict:
    out = {}
    for p in paths or []:
        p = pathlib.Path(p)
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data if isinstance(data, list) else [{"job_id": k, **v} for k, v in data.items()]
        else:
            with open(p, newline="", encoding="utf-8") as fh:
                items = list(csv.DictReader(fh))
        for it in items:
            j = it.get("job_id")
            if not j:
                raise SystemExit(f"{p}: provenance entry without job_id: {it}")
            out[j] = {**{k: (v if v != "" else None) for k, v in it.items() if k != "job_id"}, "_file": p.name}
    return out


PROV_KEYS = {"source": str, "selection": str, "acq_name": str, "acq_round": int, "acq_model_version": str, "acq_pred_mean": float,
             "acq_pred_sd": float, "pool_idx": int, "w_iid": float, "source_detail": str, "layer": str}
# solve-record evidence (a DONE job whose solve.json was overwritten after the solve): filled only where emit left the cell empty,
# only together with a non-empty solver_evidence; removes exactly the export error SOLVER_ERR
SOLVE_PROV_KEYS = {"solver": str, "solve_wall_s_fric": float, "solve_wall_s_bond": float, "solve_tries_fric": int, "solve_tries_bond": int}
SOLVER_ERR = "solver not identifiable from solve.json"


def apply_solve_evidence(r: dict, pv: dict, errs: list) -> None:
    keys = [k for k in SOLVE_PROV_KEYS if pv.get(k) is not None]
    if not keys:
        return
    ev = str(pv.get("solver_evidence") or "").strip()
    if not ev:
        errs.append(f"{r['job_id']}: provenance {pv['_file']} gives {keys} without solver_evidence")
        return
    for k in keys:
        v = SOLVE_PROV_KEYS[k](pv[k])
        if r.get(k) is None:
            r[k] = v
        elif (r[k] != v) if not isinstance(v, float) else abs(float(r[k]) - v) > 1.0:
            errs.append(f"{r['job_id']}: provenance {pv['_file']} {k} {v!r} != exported {r[k]!r} (only empty cells are filled)")
    if pv.get("solver") is not None:
        r["solver_basis"] = f"provenance {pv['_file']}: {ev}"
        r["export_errors"] = [e for e in (r.get("export_errors") or []) if not str(e).startswith(SOLVER_ERR)]
        r["export_status"] = "error" if r["export_errors"] else "ok"


def replicate_groups(rows: list) -> dict:
    """Plan 2.3 / check 11. Friction replicates: DONE rows with has_fric_model, same (realization_key, cond_key, fidelity).
    Bonded replicates, separately: DONE rows with has_bond_model, same (realization_key, cond_key, fidelity, intact_job).
    A bonded job and a friction-only job with the same geometry and condition are therefore friction replicates of each other
    whenever both carry the friction model. Returns {'fric': {gid: [rows]}, 'bond': {gid: [rows]}} for groups of > 1 row."""
    out = {"fric": {}, "bond": {}}
    for r in rows:
        if r.get("status") != "DONE" or not r.get("realization_key"):
            continue
        if r.get("has_fric_model"):
            g = sha1(jdump(["fric", r["realization_key"], r.get("cond_key"), r.get("fidelity")]))[:12]
            out["fric"].setdefault(g, []).append(r)
        if r.get("has_bond_model"):
            g = sha1(jdump(["bond", r["realization_key"], r.get("cond_key"), r.get("fidelity"), r.get("intact_job")]))[:12]
            out["bond"].setdefault(g, []).append(r)
    for k in out:
        out[k] = {g: sorted(rs, key=lambda r: (r.get("t_done_utc") or "9999", r["job_id"])) for g, rs in out[k].items() if len(rs) > 1}
    return out


def bed_support(X: np.ndarray, area: np.ndarray, d_canal: np.ndarray, collar: np.ndarray, P0: np.ndarray, ax: np.ndarray) -> dict:
    """F and what it is made of, for one interface point cloud (BED_F). The arithmetic is, line for line, mesh_F of the judging files of b28
    and later, so the values agree to the last bit. Pure."""
    N3, C = np.array(BED_F["n3"]), np.array(BED_F["cref"])
    U = np.array(BED_F["u_neck"]) / np.linalg.norm(list(BED_F["u_neck"]))
    body = ~collar
    X, w, t = X[body], area[body], -d_canal[body]
    q = X - P0
    rad = q - (q @ ax)[:, None] * ax
    em = N3 - (N3 @ ax) * ax
    em /= np.linalg.norm(em)
    ep = np.array([0.0, 1.0, 0.0]) - ax[1] * ax
    ep /= np.linalg.norm(ep)
    th = np.degrees(np.arctan2(rad @ ep, rad @ em))
    m = (-(X - C) @ U <= BED_F["zeta_max_mm"]) & (np.abs(th) <= BED_F["theta_max_deg"])
    n, a_sum = int(m.sum()), float(w[m].sum())
    return {"F": float((w[m] / np.maximum(t[m], BED_F["t_floor_mm"])).sum()), "F_area_mm2": a_sum, "F_n_nodes": n,
            "F_t_min_mm": float(t[m].min()) if n else None,
            "F_frac_floor": float(w[m][t[m] < BED_F["t_floor_mm"]].sum() / a_sum) if a_sum > 0 else None}


BED_F_COLS = ("F", "F_area_mm2", "F_n_nodes", "F_t_min_mm", "F_frac_floor")


def apply_bed_support(out: pathlib.Path, rows: list) -> tuple[int, list]:
    """Fill the F columns of every 3406 row that has a point cloud (field_shard, field_index), reading the shards under out/fields.
    Returns (rows filled, errors). A shard that is missing, or holds another job at that index, is an error for that row; the row keeps empty
    F columns. Rows of another femur are left empty: the constants are the 3406 femur's."""
    for r in rows:
        for k in BED_F_COLS:
            r[k] = None
    by_shard, errs, n = {}, [], 0
    for r in rows:
        if r.get("field_shard") and r.get("field_index") is not None and r.get("femur_id") == FEMUR_ID:
            by_shard.setdefault(str(r["field_shard"]), []).append(r)
    for name in sorted(by_shard):
        p = out / "fields" / f"{name}.npz"
        if not p.is_file():
            errs += [f"{r['job_id']}: field shard {name}.npz is missing, F not computed" for r in by_shard[name]]
            continue
        z = np.load(p, allow_pickle=False)
        jobs = [str(j) for j in z["job_id"]]
        off, frame, X_, ar, dc, co = z["off"], z["frame"], z["X"], z["area"], z["d_canal"], z["collar"]
        for r in by_shard[name]:
            j = int(r["field_index"])
            if not 0 <= j < len(jobs) or jobs[j] != r["job_id"]:
                errs.append(f"{r['job_id']}: field shard {name}.npz index {j} holds {jobs[j] if 0 <= j < len(jobs) else 'nothing'}, F not computed")
                continue
            a, b = int(off[j]), int(off[j + 1])
            r.update(bed_support(X_[a:b], ar[a:b], dc[a:b], co[a:b], frame[j, 0], frame[j, 1]))
            n += 1
    return n, errs


def _repo_module(rel: str):
    """Load a module of this repo by path (finalize only: `emit` runs from stdin on Linux and has no repo around it)."""
    import importlib.util
    p = pathlib.Path(__file__).resolve().parents[1] / rel
    spec = importlib.util.spec_from_file_location("_db_export_" + p.stem, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                                       # dataclasses / NamedTuple look their module up by name
    spec.loader.exec_module(mod)
    return mod


def apply_result_codes(rows: list, RC=None) -> None:
    """result_code / result_class of every finished row (v2/result_codes.py). A code the job itself wrote wins over the text."""
    RC = RC or _repo_module("v2/result_codes.py")
    for r in rows:
        res = RC.for_job(str(r.get("status")), r.get("fail_level"), r.get("fail_stage"), r.get("fail_reason"),
                         r.get("result_code") if str(r.get("status")) == "FAILED" else None)
        r["result_code"], r["result_class"] = (res.code, res.klass) if res else (None, None)


def finalize_rows(rows: list, E_scan: dict, prov: dict) -> tuple[list, list, dict]:
    """Provenance, E, unbiased, split, OOD, replicates. Returns (rows, errors, E_info). Pure (no I/O) for testing."""
    errs = []
    seen = {}
    for r in rows:
        if r["job_id"] in seen:
            errs.append(f"{r['job_id']}: exported in more than one batch")
        seen[r["job_id"]] = r
    apply_result_codes(rows)
    for r in rows:
        r["provenance"] = r.get("provenance") or "rule"              # emit sets rule / the D1 manifest or seed file
        pv = prov.get(r["job_id"])
        if pv:
            for k, typ in PROV_KEYS.items():
                if pv.get(k) is not None:
                    r[k] = typ(pv[k])
            if any(pv.get(k) is not None for k in PROV_KEYS):
                r["provenance"] = pv["_file"]
            apply_solve_evidence(r, pv, errs)
        if r.get("selection") not in SELECTIONS:
            errs.append(f"{r['job_id']}: selection {r.get('selection')!r} not in {SELECTIONS} (needs a provenance entry)")
        if r.get("source") is None:
            errs.append(f"{r['job_id']}: source missing (needs a provenance entry)")
        if not r.get("layer"):
            errs.append(f"{r['job_id']}: layer missing (db_* rows need a D1 manifest / seed entry)")
    E = {dk: set(js) for dk, js in E_scan.items()}
    arm = {dk for dk, js in E_scan.items() if any(j.startswith(("sb13_a", "sb14_a")) for j in js)}
    for r in rows:
        dk = r.get("design_key")
        if not dk:
            continue
        src = r.get("source") or ""
        pv = prov.get(r["job_id"]) or {}
        flag_e = str(pv.get("in_E", "")).lower() in ("1", "true", "yes")
        if src in E_SOURCES or (src.startswith("al") and r.get("selection") != "iid") or flag_e:
            E.setdefault(dk, set()).add(r["job_id"])
        if src in ARM_SOURCES:
            arm.add(dk)
    for r in rows:
        dk = r.get("design_key")
        r["in_E"] = bool(dk and dk in E)
        r["sf_bo_overlap"] = bool(dk and r.get("source") == "sf" and dk in arm)
        r["unbiased"] = bool(r.get("selection") == "iid" and not r["in_E"] and not r["sf_bo_overlap"])
        if dk:
            b, s = split_of(dk)
            r["split_bucket"], r["split"] = b, s
            a = r.get("alpha")
            r["ood_alpha_gap"] = a is not None and 27.0 <= float(a) <= 33.0
            r["ood_bo_region"] = dk in arm or r["sf_bo_overlap"]
            r["ood_widened"] = r.get("bounds_version") not in (None, "v1")
        else:
            r["split_bucket"] = r["split"] = None
            r["ood_alpha_gap"] = r["ood_bo_region"] = r["ood_widened"] = None
        r["test_iid"] = bool(r["unbiased"] and r.get("split") == "test")
        r["test_corner"] = r.get("selection") == "corner_test"
        r["a3_test_only"] = r["sf_bo_overlap"]
        R_, d_ = r.get("load_R_N"), r.get("delta_mm") if r.get("delta_mm") is not None else r.get("delta_spec_mm")
        r["ood_cond_extreme"] = bool((R_ is not None and R_ >= 3500.0) or (d_ is not None and d_ >= 0.15))
        r["ood_femur"] = r.get("femur_id") != FEMUR_ID
    for r in rows:
        r["replicate_group"] = r["replicate_of"] = r["replicate_group_bond"] = r["replicate_of_bond"] = None
    rg = replicate_groups(rows)
    for kind, (cg, co) in (("fric", ("replicate_group", "replicate_of")), ("bond", ("replicate_group_bond", "replicate_of_bond"))):
        for g, rs in rg[kind].items():
            for i, r in enumerate(rs):
                r[cg] = g
                r[co] = None if i == 0 else rs[0]["job_id"]
    info = {"n_E": len(E), "E_jobs": {dk: sorted(js) for dk, js in E.items()}, "n_arm": len(arm),
            "replicate_groups": {k: {g: [r["job_id"] for r in rs] for g, rs in v.items()} for k, v in rg.items()}}
    return rows, errs, info


REGISTRY_FORMAT = "db3406 femur registry 1"
REGISTRY_RULE = ("one femur_geom_key per femur_id, for ever: a changed femur_3406.py / STEP under the same femur_id is an error (plan 1.6 "
                 "trap 3: new geometry -> new femur_id). windows = [files mtime, export time] intervals in which the prep host (Linux "
                 "queue) held exactly these files; a row prepped strictly inside a window is bound to the key (basis registry) even "
                 "when re-exported elsewhere")


def apply_femur_registry(rows: list, ctxs: list, registry: dict | None, version: str) -> tuple[dict, list, dict]:
    """Bind femur_geom_key to job time and keep the db-level registry (pure; finalize does the I/O).
    Returns (new registry, errors, info). Rows with has_prep that are neither verified at emit (prep host: files older than prep)
    nor inside a registry window are errors."""
    reg = json.loads(json.dumps(registry)) if registry else {"format": REGISTRY_FORMAT, "rule": REGISTRY_RULE, "femurs": {}}
    if reg.get("format") != REGISTRY_FORMAT:
        return reg, [f"femur registry format {reg.get('format')!r} != {REGISTRY_FORMAT!r}"], {}
    errs, info = [], {}
    by_f = {}
    for r in rows:
        if r.get("femur_id"):
            by_f.setdefault(r["femur_id"], []).append(r)
    for f, rs in sorted(by_f.items()):
        keys = sorted({r.get("femur_geom_key") for r in rs if r.get("femur_geom_key")})
        if len(keys) != 1:
            errs.append(f"femur_id {f}: {len(keys)} femur_geom_keys in this version {keys} (one geometry per femur_id)")
            continue
        K = keys[0]
        wins = []
        for c in ctxs:
            if c.get("prep_host") and c.get("femur_geom_key") == K and c.get("femur_geom_mtime_max_utc") and c.get("export_time_utc"):
                wins.append([c["femur_geom_mtime_max_utc"], c["export_time_utc"]])
        ent = reg["femurs"].get(f)
        action = "extend"
        if ent is not None and ent.get("femur_geom_key") != K:
            errs.append(f"femur_id {f}: femur_geom_key {K} differs from the registered {ent.get('femur_geom_key')} (registered "
                        f"{ent.get('registered_utc')} by {ent.get('registered_by')}): a femur geometry change needs a new femur_id "
                        "(plan 1.6 trap 3); nothing registered")
            continue
        if ent is None:
            if not wins:
                errs.append(f"femur_id {f}: not registered and no prep-host (Linux queue) batch in this version: cannot bind "
                            f"femur_geom_key {K} to job time")
                continue
            ctx0 = next(c for c in ctxs if c.get("prep_host") and c.get("femur_geom_key") == K)
            ent = {"femur_geom_key": K, "files_sha256": ctx0.get("femur_geom_files_sha256"), "key_rule": FEMUR_GEOM_KEY_RULE,
                   "femur_model_version": rs[0].get("femur_model_version"), "hollow_core": rs[0].get("hollow_core"), "windows": [],
                   "registered_utc": now_utc(), "registered_by": f"{version}/{ctx0.get('batch')}", "first_prep_utc": None,
                   "last_prep_utc": None, "n_rows_verified": 0, "history": []}
            action = "register"
            reg["femurs"][f] = ent
        for m, T in wins:                                           # merge: same files mtime -> extend the window's end
            for w in ent["windows"]:
                if w[0] == m:
                    w[1] = max(w[1], T)
                    break
            else:
                ent["windows"].append([m, T])
        ent["windows"].sort()
        n_reg, bad = 0, []
        for r in rs:
            if not r.get("has_prep"):
                continue
            if r.get("femur_geom_verified") is True:
                continue
            tp = r.get("t_prep_utc")
            if tp and any(w[0] < tp <= w[1] for w in ent["windows"]):
                r["femur_geom_verified"], r["femur_geom_basis"] = True, "registry"
                n_reg += 1
            else:
                bad.append(r["job_id"])
        if bad:
            errs.append(f"femur_id {f}: {len(bad)} rows not bound to job time (prep time outside every registry window "
                        f"{ent['windows']}): {bad[:20]}")
        ver = [r["t_prep_utc"] for r in rs if r.get("femur_geom_verified") is True and r.get("t_prep_utc")]
        if ver:
            ent["first_prep_utc"] = min([x for x in (ent.get("first_prep_utc"), min(ver)) if x])
            ent["last_prep_utc"] = max([x for x in (ent.get("last_prep_utc"), max(ver)) if x])
        ent["n_rows_verified"] = max(int(ent.get("n_rows_verified") or 0), len(ver))
        ent["history"].append({"utc": now_utc(), "version": version, "action": action, "n_rows": len(rs), "n_verified": len(ver),
                               "n_verified_by_registry": n_reg, "windows_from_this_version": wins})
        info[f] = {"key": K, "action": action, "n_rows": len(rs), "n_verified": len(ver), "n_by_registry": n_reg, "n_unbound": len(bad)}
    return reg, errs, info


def fmt_cell(v, typ: str) -> str:
    if v is None:
        return ""
    if typ == "float":
        f = float(v)
        return "nan" if f != f else ("inf" if f == math.inf else "-inf" if f == -math.inf else repr(f))
    if typ == "int":
        return str(int(v))
    if typ == "bool":
        return "true" if v else "false"
    if typ == "json":
        if isinstance(v, list) and not v:
            return "[]"
        return jdump(v)
    return str(v)


def write_scalars(out: pathlib.Path, rows: list) -> None:
    rows = sorted(rows, key=lambda r: r["job_id"])
    tmp = out / "scalars.csv.part"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLNAMES)
        for r in rows:
            w.writerow([fmt_cell(r.get(c), COLTYPE[c]) for c in COLNAMES])
    os.replace(tmp, out / "scalars.csv")
    num = [c for c in COLNAMES if COLTYPE[c] in ("float", "int", "bool")]
    M = np.full((len(rows), len(num)), np.nan)
    present = np.zeros((len(rows), len(num)), np.uint8)
    for i, r in enumerate(rows):
        for k, c in enumerate(num):
            v = r.get(c)
            if v is not None:
                M[i, k] = float(v)
                present[i, k] = 1
    strs = {c: np.array([("" if r.get(c) is None else str(r.get(c))) for r in rows]) for c in
            ("row_id", "job_id", "design_key", "stage", "status", "source", "selection", "split", "field_shard")}
    with open(out / "scalars.npz.part", "wb") as fh:
        np.savez_compressed(fh, num=M, present=present, num_columns=np.array(num), **{"s_" + k: v for k, v in strs.items()})
    os.replace(out / "scalars.npz.part", out / "scalars.npz")


PUBLISHED_NAME = "PUBLISHED.json"
PUBLISH_OUTSIDE = ("manifest.json", "qa_report.json", PUBLISHED_NAME)       # files of a version dir that manifest.files does not list


def publish(out: pathlib.Path, check: bool = False) -> int:
    """Mark a version directory as published, or (--check) verify that a published one is still what was published.

    Publishing needs: manifest.json; every file it lists present with the listed size and sha256; no file on disk that it does not list
    (except manifest.json, qa_report.json and PUBLISHED.json); qa_report.json. It then writes PUBLISHED.json with the sha256 of manifest.json
    and of qa_report.json. After that finalize refuses to run on this directory: a published version does not change. Documents are edited at
    the database root only; the copies in the version directory are frozen with the manifest.
    Exit code: 0 published / still as published; 3 not publishable / changed since; 2 usage."""
    out = pathlib.Path(out).resolve()
    mp, qp, pp = out / "manifest.json", out / "qa_report.json", out / PUBLISHED_NAME
    if not mp.is_file():
        print(f"{out}: no manifest.json (run finalize first)")
        return 2
    man = json.loads(mp.read_text(encoding="utf-8"))
    errs = verify_members(out, man.get("files") or {})
    listed = set(man.get("files") or {})
    errs += [f"{p.relative_to(out).as_posix()}: on disk but not in manifest.files" for p in sorted(out.rglob("*"))
             if p.is_file() and p.relative_to(out).as_posix() not in listed and p.name not in PUBLISH_OUTSIDE and not p.name.endswith(".part")]
    if not qp.is_file():
        errs.append("qa_report.json: missing (run tools/db_qa.py on this version first)")
    now = {"version_dir": out.name, "manifest_sha256": sha256_file(mp), "qa_report_sha256": sha256_file(qp) if qp.is_file() else None,
           "exporter_version": man.get("exporter_version"), "n_rows": man.get("n_rows")}
    if check:
        if not pp.is_file():
            print(f"{out.name}: not published (no {PUBLISHED_NAME})")
            return 3
        was = json.loads(pp.read_text(encoding="utf-8"))
        errs += [f"{k}: published {was.get(k)!r}, now {now[k]!r}" for k in now if was.get(k) != now[k]]
        print(f"{out.name}: published {was.get('published_utc')}; {len(errs)} difference(s) since")
        for e in errs[:40]:
            print("  CHANGED", e)
        return 3 if errs else 0
    if pp.is_file():
        print(f"{out.name}: already published ({json.loads(pp.read_text(encoding='utf-8')).get('published_utc')}); use --check to verify it")
        return 3
    if errs:
        print(f"{out.name}: not publishable, {len(errs)} problem(s):")
        for e in errs[:40]:
            print("  PROBLEM", e)
        return 3
    pp.write_text(json.dumps({**now, "published_utc": now_utc(), "published_by": EXPORTER_VERSION}, indent=1) + "\n", encoding="utf-8")
    print(f"{out.name}: published ({now['n_rows']} rows, manifest {now['manifest_sha256'][:12]}, qa_report {now['qa_report_sha256'][:12]})")
    return 0


def finalize(out: pathlib.Path, db_root: str | None, provenance, allow_errors: bool, registry: str | None = None) -> int:
    out = pathlib.Path(out).resolve()
    if (out / PUBLISHED_NAME).is_file():
        raise SystemExit(f"{out} is published ({PUBLISHED_NAME} exists): a published version is not finalized again. Export a new version directory.")
    # which code and which inputs this finalize ran with (ops/provenance.py), taken before anything is written
    here = pathlib.Path(__file__).resolve()
    export_prov = _repo_module("ops/provenance.py").record("export", {
        "exporter": here, "result_codes": here.parents[1] / "v2" / "result_codes.py", "jobs_list": out / "jobs.txt",
        **{f"provenance_{i}": pp for i, pp in enumerate(provenance or [])}})
    rows, E, inv, ctxs = _load_rows(out)
    prov = _load_provenance(provenance)
    rows, errs, einfo = finalize_rows(rows, E, prov)
    n_bed, bed_errs = apply_bed_support(out, rows)                   # F from the interface point clouds of this version
    errs += bed_errs
    for pp in provenance or []:                                      # keep the override files with the version (audit)
        pp = pathlib.Path(pp).resolve()
        dst = out / "provenance" / pp.name
        if pp != dst.resolve():
            dst.parent.mkdir(exist_ok=True)
            shutil.copy2(pp, dst)
    warns = []
    unknown = sorted(set(prov) - {r["job_id"] for r in rows})
    if unknown:
        warns.append(f"{len(unknown)} provenance entries for jobs not in this version (ignored): {unknown[:10]}")
    if not any(c.get("queue_complete") for c in ctxs):
        errs.append("no batch scanned the full Linux queue: the exclusion set E only covers the exported roots "
                    "(add a Linux batch, or pass the Linux exclusion.json via a provenance in_E file)")
    rf = {}
    for c in ctxs:                                                   # the provenance inputs each batch read (BO records, D1 manifests)
        for name, v in (c.get("results_files") or {}).items():
            rf.setdefault(name, {}).setdefault(v.get("sha256"), []).append(c.get("batch"))
    for name, by in sorted(rf.items()):
        if len(by) > 1 and name.startswith("neckopt_p"):
            warns.append(f"batches read different versions of {name}: {by} (BO state changed between batches?)")
    # femur registry: one femur_geom_key per femur_id, bound to job time (plan 1.6 trap 3)
    root = pathlib.Path(db_root) if db_root else None
    reg_path = pathlib.Path(registry) if registry else ((root / "femur_registry.json") if root else None)
    if reg_path is None:
        errs.append("no --db-root / --registry: the femur registry cannot be read or updated")
        reg_old = None
    else:
        reg_old = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else None
    reg_new, rerrs, rinfo = apply_femur_registry(rows, ctxs, reg_old, out.name)
    errs += rerrs
    export_errs = {r["job_id"]: r.get("export_errors") for r in rows if r.get("export_errors")}
    reg_updated = False
    if reg_path is not None and not reg_path.parent.exists():
        errs.append(f"registry dir {reg_path.parent} does not exist")
    if reg_path is not None and not errs and not export_errs:     # db-level registry only from a clean version (not --allow-errors)
        tmp = reg_path.with_name(reg_path.name + ".part")
        tmp.write_text(json.dumps(reg_new, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, reg_path)
        reg_updated = True
    elif reg_path is not None:
        warns.append(f"femur registry {reg_path} NOT updated ({len(errs)} finalize errors, {len(export_errs)} rows with export "
                     "errors); this version's copy is in femur_registry.json")
    (out / "femur_registry.json").write_text(json.dumps(reg_new, indent=1, sort_keys=True), encoding="utf-8")
    write_scalars(out, rows)
    if root and root.exists():
        for f in ("schema.json", "DATA_CARD.md", "CHANGELOG.md", "README.md"):
            if (root / f).exists():
                shutil.copy2(root / f, out / f)
    if not (out / "schema.json").exists():
        (out / "schema.json").write_text(json.dumps(schema_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    splits = {"rule": SPLIT_RULE, "counts": {}, "design_keys": {}}
    for r in rows:
        s = r.get("split")
        if s:
            splits["design_keys"].setdefault(s, set()).add(r["design_key"])
            splits["counts"][s] = splits["counts"].get(s, 0) + 1
    splits["design_keys"] = {k: sorted(v) for k, v in splits["design_keys"].items()}
    splits["test_iid_jobs"] = sorted(r["job_id"] for r in rows if r.get("test_iid"))
    splits["test_corner_jobs"] = sorted(r["job_id"] for r in rows if r.get("test_corner"))
    splits["unbiased_jobs"] = sorted(r["job_id"] for r in rows if r.get("unbiased"))
    splits["exclusion_set_E"] = einfo["E_jobs"]
    (out / "splits.json").write_text(json.dumps(splits, indent=1, sort_keys=True))
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest.json" and not p.name.endswith(".part"):
            files[p.relative_to(out).as_posix()] = {"sha256": sha256_file(p), "size": p.stat().st_size}
    man = {"version_dir": out.name, "finalized_utc": now_utc(), "exporter_version": EXPORTER_VERSION, "n_rows": len(rows),
           "by_status": {k: sum(1 for r in rows if str(r.get("status")) == k) for k in sorted({str(r.get("status")) for r in rows})},
           "by_source": {k: sum(1 for r in rows if str(r.get("source")) == k) for k in sorted({str(r.get("source")) for r in rows})},
           "n_unbiased": sum(1 for r in rows if r.get("unbiased")), "n_E_design_keys": einfo["n_E"],
           "code_hash": sorted({str(r.get("code_hash")) for r in rows}), "aux_code_md5": sorted({str(r.get("aux_code_md5")) for r in rows}),
           "femur": sorted({(str(r.get("femur_id")), str(r.get("femur_model_version")), str(r.get("femur_geom_key"))) for r in rows}),
           "split_rule": SPLIT_RULE, "batches": [c.get("batch") for c in ctxs], "contexts": ctxs,
           "skipped_batch_dirs": [p.name for p in batch_dirs(out)[1]], "replicate_groups": einfo["replicate_groups"],
           "femur_registry": {"path": str(reg_path) if reg_path else None, "info": rinfo, "updated": reg_updated},
           "by_result_class": {k: sum(1 for r in rows if str(r.get("result_class")) == k) for k in sorted({str(r.get("result_class")) for r in rows})},
           "export_provenance": export_prov,
           "bed_F": {**{k: (list(v) if isinstance(v, tuple) else v) for k, v in BED_F.items()}, "version": "mesh", "n_rows": n_bed,
                     "note": "F = sum A / max(t, t_floor) over stem-body nodes with zeta <= zeta_max and |theta| <= theta_max; constants of the 3406 femur"},
           "finalize_errors": errs, "finalize_warnings": warns, "rows_with_export_errors": export_errs, "files": files}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True, default=_jdefault))
    rg = einfo["replicate_groups"]
    print(f"finalize {out}: {len(rows)} rows, {man['n_unbiased']} unbiased, E {einfo['n_E']} design keys, replicate groups "
          f"fric {len(rg['fric'])} / bond {len(rg['bond'])}, femur registry {rinfo}, "
          f"{len(errs)} finalize errors, {len(export_errs)} rows with export errors")
    for w in warns:
        print("  FINALIZE WARNING:", w)
    for e in errs:
        print("  FINALIZE ERROR:", e)
    for j, e in list(export_errs.items())[:30]:
        print("  EXPORT ERROR", j, e)
    return 0 if (allow_errors or (not errs and not export_errs)) else 3


# ================================================================================================ schema / info / cli
def cmd_schema(a) -> int:
    p = pathlib.Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(schema_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {p} ({len(COLUMNS)} columns)")
    return 0


def cmd_info(a) -> int:
    home = pathlib.Path.home()
    code_root = pathlib.Path(a.code_root).expanduser() if a.code_root else home / "mobo_toy_v2" / "code"
    P = Pipeline(code_root, pathlib.Path(a.queue_root).expanduser() if a.queue_root else None)
    ctx = Context(P, "info", None, a.results_root)
    d = ctx.as_dict()
    d["free_gb_home"] = free_gb(home)
    import femur_3406 as F6
    key = F6._cache_key(F6.load_cfg(None))
    d["femur_cache"] = {"key": key, "exists": (F6.CACHE / f"femur_3406_{key}.npz").exists()}
    print(json.dumps(d, indent=1, default=_jdefault))
    return 0


def idle_priority() -> None:
    """Windows: run this process at IDLE priority (the FE worker shares the machine). Linux: the remote command uses nice 19."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x40)          # IDLE_PRIORITY_CLASS
        except Exception as e:  # noqa: BLE001
            log(f"could not set IDLE priority: {e}")


def main(argv=None) -> int:
    idle_priority()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit")
    e.add_argument("--jobs", nargs="*")
    e.add_argument("--select-3406", action="store_true", help="all job dirs whose spec femur_id is sawbone3406 (sorted)")
    e.add_argument("--offset", type=int, default=0)
    e.add_argument("--limit", type=int, default=0)
    e.add_argument("--batch", default="b000")
    e.add_argument("--shard-size", type=int, default=64)
    e.add_argument("--code-root")
    e.add_argument("--queue-root")
    e.add_argument("--results-root", help="neckopt_p11..14.json + db_manifest_*.json + db_seed_*.json (default jobs.RESULTS)")
    e.add_argument("--out-dir", help="write members into this dir instead of a tar stream on stdout")
    e.add_argument("--no-fields", action="store_true")
    e.add_argument("--no-guard", action="store_true")
    e.add_argument("--guard-allow", nargs="*")
    e.add_argument("--odb-export-md5")
    e.add_argument("--list-only", action="store_true", help="print one queue listing (JSON) and stop")
    e.add_argument("--finished-only", action="store_true", help="--list-only: keep DONE / FAILED jobs only")
    e.add_argument("--exclude-prefix", nargs="*", help="--list-only: drop job names starting with these (e.g. db_)")
    e.add_argument("--frozen-sha256", help=argparse.SUPPRESS)
    e.add_argument("--frozen-offset", type=int, help=argparse.SUPPRESS)
    e.add_argument("--frozen-limit", type=int, help=argparse.SUPPRESS)
    p = sub.add_parser("pull")
    p.add_argument("--jobs", nargs="*")
    p.add_argument("--select-3406", action="store_true", help="with --list-only only (a live --select-3406 pull is refused)")
    p.add_argument("--list-only", action="store_true", help="freeze ONE listing as <out>/jobs.txt + jobs_inventory.json")
    p.add_argument("--finished-only", action="store_true", help="--list-only: keep DONE / FAILED jobs only")
    p.add_argument("--exclude-prefix", nargs="*", help="--list-only: drop job names starting with these (e.g. db_ for v0.1)")
    p.add_argument("--jobs-file", help="<out>/jobs.txt written by --list-only; --offset / --limit slice it")
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--batch", default="b000")
    p.add_argument("--shard-size", type=int, default=64)
    p.add_argument("--no-fields", action="store_true")
    p.add_argument("--out", required=True)
    p.add_argument("--db-root", help="db3406 root (femur_registry.json, schema.json, DATA_CARD.md); required unless --no-finalize")
    p.add_argument("--registry", help="femur registry json (default <db-root>/femur_registry.json)")
    p.add_argument("--provenance", nargs="*")
    p.add_argument("--min-free-gb", type=float, default=H_MIN_FREE_GB)
    p.add_argument("--host", default=LINUX_HOST)
    p.add_argument("--key", default=LINUX_KEY)
    p.add_argument("--ssh", default=SSH_EXE)
    p.add_argument("--remote-script", help="path of a deployed copy on Linux (default: stream this file on stdin)")
    p.add_argument("--remote-timeout", type=float, default=1200)
    p.add_argument("--remote-cwd", help="working dir of the remote emit (default $HOME/mobo_toy_v2/code; it reads by absolute paths)")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-finalize", action="store_true")
    p.add_argument("--allow-errors", action="store_true")
    f = sub.add_parser("finalize")
    f.add_argument("--out", required=True)
    f.add_argument("--db-root", required=True, help="db3406 root (femur_registry.json, schema.json, DATA_CARD.md)")
    f.add_argument("--registry", help="femur registry json (default <db-root>/femur_registry.json)")
    f.add_argument("--provenance", nargs="*")
    f.add_argument("--allow-errors", action="store_true")
    pb = sub.add_parser("publish")
    pb.add_argument("--out", required=True)
    pb.add_argument("--check", action="store_true", help="verify a published version against its PUBLISHED.json; write nothing")
    s = sub.add_parser("schema")
    s.add_argument("--out", default="H:/projects/Femoral implant generation/db3406/schema.json")
    i = sub.add_parser("info")
    i.add_argument("--code-root")
    i.add_argument("--queue-root")
    i.add_argument("--results-root")
    a = ap.parse_args(argv)
    if a.cmd == "emit" and not a.jobs and not a.select_3406:
        ap.error("give --jobs or --select-3406")
    if a.cmd == "pull" and not a.jobs and not a.select_3406 and not a.jobs_file:
        ap.error("give --jobs, --jobs-file, or --list-only --select-3406")
    if a.cmd == "pull" and a.jobs_file and (a.jobs or a.select_3406 or a.list_only):
        ap.error("--jobs-file excludes --jobs / --select-3406 / --list-only")
    if a.cmd == "pull" and not a.db_root and not a.no_finalize and not a.list_only:
        ap.error("--db-root is required (finalize reads / updates the femur registry there); or pass --no-finalize")
    if a.cmd == "emit":
        return cmd_emit(a)
    if a.cmd == "pull":
        return cmd_pull(a)
    if a.cmd == "finalize":
        return finalize(pathlib.Path(a.out), a.db_root, a.provenance, a.allow_errors, registry=a.registry)
    if a.cmd == "publish":
        return publish(pathlib.Path(a.out), check=a.check)
    if a.cmd == "schema":
        return cmd_schema(a)
    return cmd_info(a)


if __name__ == "__main__":
    sys.exit(main())
