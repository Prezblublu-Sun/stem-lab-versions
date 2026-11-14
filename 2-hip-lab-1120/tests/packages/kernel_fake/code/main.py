"""A fake kernel. It speaks the kernel conventions written in stemlab/contract/formats/package.py
without any real geometry or solver, so the plugins can be walked through end to end.

How a design behaves is chosen by design["behave"]:
    ok       fits, meshes, converges
    misfit   does not fit into the bone (also any length above 60)
    mesh     meshing fails
    diverge  the solver stops after the first step: too many attempts
    loose    the same, but the stem had visibly come loose before the solver gave up
    crash    the kernel itself dies while building, leaving no result
    env      building reports an environment problem
    flaky    an environment problem the first time this point is built, fine afterwards
             (remembered in the folder named by the environment variable FAKE_KERNEL_STATE)
    hang     the solver never finishes on its own
"""
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent


def fits(design: dict) -> bool:
    return design.get("behave", "ok") != "misfit" and design["length"] <= 60


def template(job: dict) -> dict:
    rows = []
    for one in job["designs"]:
        design = one["design"]
        info = {"bone_removed": design["length"] * 100.0}
        if not fits(design):
            info["reason"] = "no entry offset lets this stem fit"
        rows.append({"name": one["name"], "feasible": fits(design), "info": info})
    return {"designs": rows}


def build(job: dict) -> dict:
    design, where = job["point"]["design"], pathlib.Path(job["job"])
    behave = design.get("behave", "ok")
    time.sleep(job.get("settings", {}).get("build_seconds", 0))
    if not fits(design):
        return {"status": "misfit", "reason": "no entry offset lets this stem fit", "pre": {"bone_removed": None}}
    if behave == "mesh":
        return {"status": "mesh_failed", "reason": "meshing failed after retries: overlapping facets"}
    if behave == "env":
        return {"status": "env", "reason": "the licence server did not answer"}
    if behave == "flaky":
        seen = pathlib.Path(os.environ["FAKE_KERNEL_STATE"]) / job["point"]["name"]
        if not seen.exists():
            seen.parent.mkdir(parents=True, exist_ok=True)
            seen.write_text("")
            return {"status": "env", "reason": "the licence server did not answer"}
    if behave == "crash":
        print("fake kernel: crashing on purpose", flush=True)
        sys.exit(3)
    where.mkdir(parents=True, exist_ok=True)
    deck = {"length": design["length"], "load": job["point"]["conditions"]["load"], "behave": behave,
            "seconds": job.get("settings", {}).get("seconds", 0)}
    (where / "deck.json").write_text(json.dumps(deck))
    (where / "mesh.json").write_text(json.dumps({"nodes": 100 + int(design["length"]), "elements": 50}))
    return {"status": "built", "reason": "", "pre": {"bone_removed": design["length"] * 100.0},
            "solve": {"command": ["{python}", str(HERE / "solver.py"), "deck.json"]}}


def post(job: dict, out: pathlib.Path) -> dict:
    where = pathlib.Path(job["job"])
    log = (where / "solver.log").read_text() if (where / "solver.log").exists() else ""
    keep = {"mesh": ["mesh.json"], "settings": ["deck.json"], "process": ["solver.log"] if log else [],
            "fields": [name for name in ("step1.json", "step2.json") if (where / name).exists()]}
    if not (where / "done").exists():
        if "TOO MANY ATTEMPTS" in log:
            loose = json.loads((where / "deck.json").read_text())["behave"] == "loose"
            return {"status": "unstable" if loose else "not_converged",
                    "reason": "TOO MANY ATTEMPTS MADE FOR THIS INCREMENT"
                              + ("; the stem had already slipped 400 um at 40% of the load" if loose else ""),
                    "steps": {"done": len(keep["fields"]), "total": 2}, "keep": keep}
        return {"status": "env", "reason": "the solver left no result and no error", "steps": {"done": 0, "total": 2}, "keep": keep}
    deck = json.loads((where / "deck.json").read_text())
    slip = [deck["length"] / 10.0 * step for step in range(1, 6)]
    (out / "interface_slip.json").write_text(json.dumps(slip))
    return {"status": "ok", "reason": "", "labels": {"rotation": deck["load"] / (deck["length"] * 1000.0), "contact": 0.5},
            "fields": {"interface_slip": "interface_slip.json"}, "steps": {"done": 2, "total": 2}, "keep": keep,
            "solver": {"name": "fake-solver", "version": "1.0"}}


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text())
    result = {"template": template, "build": build}[job["mode"]](job) if job["mode"] != "post" else post(job, out)
    (out / "result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
