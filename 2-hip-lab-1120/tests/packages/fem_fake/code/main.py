"""A fake FE package. It speaks the fem conventions written in stemlab/contract/formats/package.py
without a real mesher or solver, so fea.run can be walked through end to end.

It reads the design back from the stem model it is handed (the stem model copies the design of its point).
How it behaves is chosen by that design's behave, as the fake kernel does:
    ok       meshes and converges
    mesh     meshing fails
    diverge  the solver stops after the first step: too many attempts
    loose    the same, but the stem had visibly come loose before the solver gave up
    crash    the package itself dies while building, leaving no result
    env      building reports an environment problem
    flaky    an environment problem the first time this point is built, fine afterwards
             (remembered in the folder named by the environment variable FAKE_KERNEL_STATE)
    hang     the solver never finishes on its own
With no implant (stem_model is null) it builds a bone-only model that behaves like ok, as if the length were 20.

The FE setting of the point (job["settings"]) may say: load (N, given per point in the tests), seconds (how long the fake
solver takes), build_seconds (how long building takes), load_point (a name reference: where the load goes).
load_point is looked up in the stem model or in the bone model, and what it found is written into the deck,
so a test can see that the name reference reached the package together with the stem model.
job["programs"] (where the programs its manifest lists are installed, taken from the machine list) goes into the deck as well.

The bone model comes as two things: job["bone_model"], the folder its geometry files are in, and job["bone"], its manifest
already read as the current version by the caller. This package reads job["bone"] and never opens the manifest in the folder,
so it need not know older versions. What it saw of the bone goes into the deck too (see bone_seen).
"""
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
BONE_ONLY = {"length": 20.0, "behave": "ok"}


def _stem(job: dict):
    folder = job.get("stem_model")
    return json.loads((pathlib.Path(folder) / "stem_model.json").read_text()) if folder else None


def where_is(reference, stem, bone: dict):
    """Look a name reference up: {"ref": "stem.feature.taper_center"} or {"ref": "bone.landmark.head_center"}.
    bone is the manifest of the bone model as the caller handed it over (job["bone"])."""
    if not reference:
        return None
    source, part, name = reference["ref"].split(".")
    if source == "stem":
        return {"feature": stem["features"], "axis": {k: v["point"] for k, v in stem["axes"].items()}}.get(part, {}).get(name, name)
    return bone["landmarks"][name]["xyz"] if part == "landmark" else name


def bone_seen(job: dict) -> dict:
    """What reached this package of the bone model: the version its manifest was handed over in, how its anatomical frame
    was fixed, and its regions told apart by role (not by name): the file, whether it is there in the folder, the material model."""
    listed, folder = job["bone"], pathlib.Path(job["bone_model"])
    return {"format": listed["format"], "frame": listed["frame"]["method"],
            "regions": {region["role"]: {"file": region["geometry"]["file"], "there": (folder / region["geometry"]["file"]).is_file(),
                                         "material": (region["material"] or {}).get("model")} for region in listed["regions"]}}


def build(job: dict) -> dict:
    stem, settings = _stem(job), job.get("settings") or {}
    design = stem["design"] if stem else BONE_ONLY
    behave = design.get("behave", "ok")
    time.sleep(settings.get("build_seconds", 0))
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
        print("fake FE package: crashing on purpose", flush=True)
        sys.exit(3)
    where = pathlib.Path(job["job"])
    where.mkdir(parents=True, exist_ok=True)
    deck = {"length": design["length"], "load": settings["load"], "behave": behave, "seconds": settings.get("seconds", 0),
            "implant": stem is not None, "load_point": where_is(settings.get("load_point"), stem, job["bone"]),
            "programs": job.get("programs"), "bone": bone_seen(job)}
    (where / "deck.json").write_text(json.dumps(deck))
    (where / "mesh.json").write_text(json.dumps({"nodes": 100 + int(design["length"]), "elements": 50}))
    return {"status": "built", "reason": "", "pre": {"n_nodes": 100 + int(design["length"])},
            "solve": {"command": ["{python}", str(HERE / "solver.py"), "deck.json"]}}


def post(job: dict, source: pathlib.Path, out: pathlib.Path) -> dict:
    where = pathlib.Path(job["job"])
    where = where if where.is_absolute() else source / where
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
    result = build(job) if job["mode"] == "build" else post(job, source, out)
    (out / "result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
