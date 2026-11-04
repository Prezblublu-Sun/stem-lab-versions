"""DB3406 seed batch CD-0 (2026-10-25, user: start FE in parallel with tool development).

27 friction-only condition variants of the candidate designs, built like stage_deck's D13 variants:
  delta: A, B, B', C, D, a62 x delta 0.025 / 0.20 (12) + A, B, B', C, D, a62, init29 x delta 0.05 (7)
  sit-to-stand: B, D, a62, init29 x cfg.load F1714 / F3839 (8), same loads as stage_deck.D13_STS
Stage db_cd (never sb*: phase 11-14 in_family must stay false). Every spec key except stage/tag/created enters the
job id, so stage_db.py must reproduce these specs verbatim (or adopt the ids in results/db_seed_CD0.json).
Usage on Linux:  cd ~/mobo_toy_v2/code && ../run.sh <this file> [--submit]   (without --submit = dry run)
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "v2")
import jobs as J  # noqa: E402
import stage_neckopt as SN  # noqa: E402

DROP = ("created", "stage", "tag", "kind", "bond_only", "fric_only", "intact_job")
SRC = {"A": "sb13_a105_91e458e3", "B": "sb13_a78_b0f465da", "Bp": "sb13_a53_23a3f031", "C": "sb14_a29_6ad70033",
       "D": "sb14_a26_96c5ab9b", "a62": "sb13_a62_1e4338ee", "init29": "sb13_init_2943f28a"}
STS = {"F1714": {"resultant_N": 1714.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0},
       "F3839": {"resultant_N": 3839.0, "alpha_front_deg": 24.0, "alpha_sagit_deg": 8.0}}
META = {"kind": "variant", "fric_only": True, "db_layer": "CD-0", "femur_model_version": "3406R_v1_hollowcore"}


def src(job: str) -> dict:
    d = J.QROOT / job
    if not (d / "DONE").exists():
        raise SystemExit(f"source {job} is not DONE")
    s = json.loads((d / "spec.json").read_text())
    if s.get("femur_id") != "sawbone3406":
        raise SystemExit(f"source {job}: femur_id {s.get('femur_id')!r}")
    return {k: v for k, v in s.items() if k not in DROP}


def tag_of(code: str, cond: str) -> str:
    return f"{code}_{cond}"


def build() -> dict:
    out = {}
    for code in ("A", "B", "Bp", "C", "D", "a62"):
        for dl in (0.025, 0.20):
            s = src(SRC[code])
            out[f"CD0_delta{dl:g}_{code}"] = {**s, **META, "stage": "db_cd", "tag": tag_of(code, f"d{dl:g}"), "delta": dl,
                                               "db_cond": f"delta{dl:g}", "source_job": SRC[code]}
    for code in ("A", "B", "Bp", "C", "D", "a62", "init29"):
        s = src(SRC[code])
        out[f"CD0_delta0.05_{code}"] = {**s, **META, "stage": "db_cd", "tag": tag_of(code, "d0.05"), "delta": 0.05,
                                         "db_cond": "delta0.05", "source_job": SRC[code]}
    for code in ("B", "D", "a62", "init29"):
        for ln, L in STS.items():
            s = src(SRC[code])
            out[f"CD0_sts_{ln}_{code}"] = {**s, **META, "stage": "db_cd", "tag": tag_of(code, ln), "cfg": {"load": dict(L)},
                                            "load_case": "sit_to_stand", "db_cond": f"sts_{ln}", "source_job": SRC[code]}
    return out


def check(out: dict) -> list:
    probs = []
    phases = {p: SN.Phase(p) for p in (11, 12, 13, 14)}
    for k, s in out.items():
        if not str(s["stage"]).startswith("db_"):
            probs.append(f"{k}: stage {s['stage']!r} does not start with db_")
        for p, ph in phases.items():
            if ph.in_family(s):
                probs.append(f"{k}: spec is in_family of phase {p}")
        if s.get("fric_only") is not True or s.get("bond_only"):
            probs.append(f"{k}: must be friction-only")
        jid = J.job_id({**s, "created": "x"})
        h8 = jid.rsplit("_", 1)[-1]
        hits = [d.name for d in J.QROOT.glob(f"*_{h8}") if d.name != jid]
        if hits:
            probs.append(f"{k}: hash8 {h8} already used by {hits} (different stage/tag) - inspect before submitting")
    if len(out) != 27:
        probs.append(f"expected 27 specs, got {len(out)}")
    return probs


def main():
    out = build()
    probs = check(out)
    for k, s in out.items():
        jid = J.job_id({**s, "created": "x"})
        st = J.state(J.QROOT / jid)
        diff = {kk: s[kk] for kk in ("delta", "cfg", "load_case") if kk in s}
        print(f"{k:28s} {jid:44s} {st:8s} src {s['source_job']} {json.dumps(diff, default=float)}")
    if probs:
        raise SystemExit("REFUSED:\n" + "\n".join(probs))
    print(f"code_hash {J.code_hash()}; {len(out)} specs; checks passed")
    if "--submit" not in sys.argv:
        print("dry run only (no --submit)")
        return
    ids = {}
    for k, s in out.items():
        ids[k] = J.submit(s)
    rec = {"batch": "CD-0 seed", "submitted_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "code_hash": J.code_hash(),
           "note": "db3406 seed; stage_db.py must adopt these exact specs/ids", "jobs": ids, "specs": out}
    f = J.RESULTS / "db_seed_CD0.json"
    if f.exists():
        raise SystemExit(f"{f} exists; not overwriting")
    f.write_text(json.dumps(rec, indent=1, default=float))
    print(f"submitted {len(ids)} -> {f}")


if __name__ == "__main__":
    main()
