"""A fake reconstruction method. It speaks the recon_method conventions written in stemlab/contract/formats/package.py
without reading any real geometry, so recon.draft and recon.finalize can be walked through end to end.

The source folder holds two "solids", cortical.step and cancellous.step (a few bytes each; a file whose bytes contain
"open" counts as not closed), marks.json (where the landmarks are: name -> [x, y, z]) and, optionally, measures.json
(a few numbers taken as "measured on the source": they cannot be measured again at finalize, so the manifest's kept names them).

    draft      the regions are the two files; the landmarks are the ones in marks.json; the numbers are the volume of each
               solid (from the file size), whether it is closed, and whatever measures.json holds
    finalize   moves landmarks and swaps solids the way the edits say (the writing in plugins/recon/review.py), measures
               the volumes and closedness again, how much each volume changed and how far the landmarks moved from the
               candidate's, and names the numbers from measures.json in kept

The reconstruction setting says side, extent (whole or proximal), anteversion_deg (only for a proximal piece) and behave:
    ok          as above
    slow        as above, after three seconds
    error       reports an error            env       reports an environment problem
    crash       dies without leaving a result
    garbage     forgets the lesser trochanter
    relative    gives the solid files as relative paths
    badname     names the first region "../cortical"
    keep_wrong  at finalize, also names cortical_volume_mm3 in kept, which the manifest does not say it cannot redo
"""
import json
import math
import os
import pathlib
import sys
import time

PARTS = {"cortical": 16800.0, "cancellous": 155.0}         # region -> Young's modulus (MPa)
KEPT = ("head_fit_rms_mm", "neck_wall_min_mm")
FOUND = {"method": "fake_marks", "version": "1", "params": {}}
FAILS = {"error": ("error", "the fake method was told to fail"), "env": ("env", "the fake licence server did not answer")}


def as_text(path: pathlib.Path) -> str:
    return path.as_posix()


def measured(files: dict) -> dict:
    found = {}
    for name, path in files.items():
        content = path.read_bytes()
        found[f"{name}_volume_mm3"] = 1000.0 * len(content)
        found[f"{name}_watertight"] = b"open" not in content
    return found


def bone(settings: dict, files: dict, landmarks: dict, history: list) -> dict:
    """The parts of a bone model the method hands back, written the version 2 way."""
    behave, whole = settings.get("behave", "ok"), settings["extent"] == "whole"
    regions = [{"name": name, "role": name, "geometry": {"kind": "solid", "format": "step", "file": as_text(path)},
                "volume_mm3": 1000.0 * len(path.read_bytes()), "material": {"model": "elastic", "E": PARTS[name], "nu": 0.3}}
               for name, path in files.items()]
    if behave == "relative":
        for region in regions:
            region["geometry"]["file"] = os.path.relpath(region["geometry"]["file"])
    if behave == "badname":
        regions[0]["name"] = "../cortical"
    if behave == "garbage":
        landmarks = {name: point for name, point in landmarks.items() if name != "lesser_trochanter"}
    frame = {"file": "the fake source's own coordinates"}
    if not whole:
        frame["anteversion_deg"] = settings["anteversion_deg"]
    return {"how": "cad", "side": settings["side"], "bone_type": "synthetic",
            "coverage": {"extent": settings["extent"], "proximal_mm": 80.0, "distal_mm": 400.0 if whole else 150.0},
            "frame": frame, "regions": regions, "landmarks": landmarks, "history": history}


def draft(job: dict) -> dict:
    source = pathlib.Path(job["source"])
    files = {name: source / f"{name}.step" for name in PARTS}
    missing = [path.name for path in files.values() if not path.is_file()] + [name for name in ("marks.json",) if not (source / name).is_file()]
    if missing:
        return {"status": "error", "reason": f"the source has no {missing}"}
    marks = json.loads((source / "marks.json").read_text())
    landmarks = {name: {"xyz": [float(v) for v in xyz], "definition": dict(FOUND), "fit": {"rms_mm": 0.1}} for name, xyz in marks.items()}
    extra = json.loads((source / "measures.json").read_text()) if (source / "measures.json").is_file() else {}
    history = [{"step": "import", "what": "two fake solids taken from the source as they are"},
               {"step": "landmarks", "what": "landmarks read from marks.json"}]
    made = bone(job["settings"], files, landmarks, history)
    todo = [{"item": name, "doubt": False, "why": "read from marks.json: have a look"} for name in sorted(landmarks)]
    return dict(made, status="ok", reason="", measures={**extra, **measured(files)}, todo=todo)


def finalize(job: dict, out: pathlib.Path) -> dict:
    listed = job.get("bone") or {}
    if listed.get("format") != 2:
        return {"status": "error", "reason": "the candidate's manifest was not handed over read as version 2 (job['bone'])"}
    folder = pathlib.Path(job["draft"])
    files = {region["name"]: folder / region["geometry"]["file"] for region in listed["regions"] if region["name"] in PARTS}
    before = {name: point["xyz"] for name, point in listed["landmarks"].items()}
    landmarks = {}
    for name, point in listed["landmarks"].items():              # a candidate read from version 1 knows only a sentence
        said = point["definition"]
        definition = said if said.get("method") is not None else dict(FOUND, text=said.get("text") or "from version 1")
        landmarks[name] = {"xyz": point["xyz"], "definition": definition, "fit": point["fit"] if point["fit"] is not None else {}}
    history = list(listed["history"])
    edits = json.loads((pathlib.Path(job["edits"]) / "edits.json").read_text()) if job.get("edits") else None
    if edits is None:
        history.append({"step": "review", "what": "no edits: the candidate is finalized as it is"})
    else:
        for name, change in (edits.get("landmarks") or {}).items():
            moved = f"moved {math.dist(before[name], change['xyz']):.2f} mm, " if name in before else "added, "
            landmarks[name] = {"xyz": [float(v) for v in change["xyz"]], "fit": {},
                               "definition": {"method": "manual", "version": "1", "params": {},
                                              "text": f"set by hand ({edits['by']}): {change['why']}"}}
            history.append({"step": "edit", "what": f"landmark {name}: {moved}by {edits['by']}, because {change['why']}"})
        for name, change in (edits.get("solids") or {}).items():
            files[name] = pathlib.Path(job["edits"]) / change["file"]
            history.append({"step": "edit", "what": f"solid {name} replaced with {change['file']}: by {edits['by']}, because {change['why']}"})
    made = bone(job["settings"], files, landmarks, history)
    numbers, old = measured(files), listed.get("measures") or {}
    for name in files:
        was = old.get(f"{name}_volume_mm3")
        numbers[f"{name}_volume_change"] = abs(numbers[f"{name}_volume_mm3"] - was) / was if was else None
    shifts = [math.dist(before[name], point["xyz"]) for name, point in landmarks.items() if name in before]
    numbers["landmark_shift_max_mm"] = max(shifts) if shifts else None
    kept = [name for name in KEPT if name in old]
    if job["settings"].get("behave") == "keep_wrong":
        kept.append("cortical_volume_mm3")
    return dict(made, status="ok", reason="", measures=numbers, kept=kept)


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text())
    behave = job["settings"].get("behave", "ok")
    if behave == "slow":
        time.sleep(3.0)
    if behave == "crash":
        print("fake recon method: crashing on purpose", flush=True)
        sys.exit(3)
    if behave in FAILS:
        status, reason = FAILS[behave]
        result = {"status": status, "reason": reason}
    else:
        result = draft(job) if job["mode"] == "draft" else finalize(job, out)
    (out / "result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
