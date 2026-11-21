"""A stand-in FE package for the test of the M1 stem space. No mesher, no solver: it reads the stem model it is
handed and looks up the name references of its setting in it. Building succeeds only if what it was pointed to is there:
    contact_faces   a face group of the stem model ({"ref": "stem.faces.interface"}): its file must be in the stem model
    load_point      a feature point of the stem model, or a landmark of the bone model
What it found goes into the deck and into pre, so the test can see that the stem model reached the FE side whole.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def looked_up(job: dict) -> dict:
    folder = pathlib.Path(job["stem_model"])
    stem = json.loads((folder / "stem_model.json").read_text(encoding="utf-8"))
    settings = job["settings"]
    source, part, name = settings["contact_faces"]["ref"].split(".")
    patch = folder / stem[part][name]["file"]
    source, part, name = settings["load_point"]["ref"].split(".")
    if source == "stem":
        point = stem["features"][name]
    else:       # the manifest of the bone model, handed over by the caller already read as the current version
        point = job["bone"]["landmarks"][name]["xyz"]
    solid = folder / stem["regions"][0]["geometry"]["file"]
    return {"interface_kb": patch.stat().st_size / 1000.0, "solid_kb": solid.stat().st_size / 1000.0, "load_point": point,
            "load": settings["load"], "material": stem["regions"][0]["material"], "design": stem["design"],
            "frame": stem["placement"]["frame"]}


def build(job: dict) -> dict:
    try:
        found = looked_up(job)
    except (KeyError, OSError, ValueError) as error:
        return {"status": "error", "reason": f"the stem model lacks what the setting points to: {type(error).__name__}: {error}"}
    where = pathlib.Path(job["job"])
    where.mkdir(parents=True, exist_ok=True)
    (where / "deck.json").write_text(json.dumps(found), encoding="utf-8")
    return {"status": "built", "reason": "", "pre": {"interface_kb": found["interface_kb"]},
            "solve": {"command": ["{python}", str(HERE / "solver.py")]}}


def post(job: dict, out: pathlib.Path) -> dict:
    where = pathlib.Path(job["job"])
    keep = {"mesh": [], "settings": ["deck.json"], "process": ["solver.log"] if (where / "solver.log").exists() else [], "fields": []}
    if not (where / "done").exists():
        return {"status": "env", "reason": "the solver left no result", "steps": {"done": 0, "total": 1}, "keep": keep}
    deck = json.loads((where / "deck.json").read_text(encoding="utf-8"))
    (out / "interface_slip.json").write_text(json.dumps([1.0, 2.0, 4.0]), encoding="utf-8")
    return {"status": "ok", "reason": "", "labels": {"load_seen": deck["load"]}, "fields": {"interface_slip": "interface_slip.json"},
            "steps": {"done": 1, "total": 1}, "keep": keep, "solver": {"name": "none", "version": "0"}}


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    result = {"ok": True} if job["mode"] == "echo" else build(job) if job["mode"] == "build" else post(job, out)
    (out / "result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
