"""A fake stem space. It speaks the stem_space conventions written in stemlab/contract/formats/package.py
without any real geometry, so fea.run can be walked through end to end.

The design has two items: length (mm) and behave. How a design behaves at the "model" step is chosen by behave:
    ok          fits and hands over a well-formed stem model (the fake FE package reads behave again from it)
    misfit      does not fit into the bone (also any length above 60)
    stem_env    reports an environment problem
    stem_crash  dies without leaving a result
    badmodel    says ok but hands over a stem model that is not well formed
    noname      says ok, the stem model is well formed, but it lacks a name the manifest promised (taper_center)
Other values of behave (mesh, diverge, loose, crash, env, hang ...) are for the fake FE package: here they are like ok.

The placement setting may say cut_drop (mm): how far below the reference the cut is. It moves the cut and adds to the bone removed.

At the "model" step the bone model must come the way the convention says: job["bone"] is its manifest, already read as the
current version by the caller (job["bone_model"] is still the folder). Handed anything else, this package reports an error.
"""
import json
import pathlib
import sys

FAILS = {"stem_env": ("env", "the licence server did not answer")}


def fits(design: dict) -> bool:
    return design.get("behave", "ok") != "misfit" and design["length"] <= 60


def removed(design: dict, settings: dict) -> float:
    return design["length"] * 100.0 + float(settings.get("cut_drop", 0.0)) * 10.0


def template(job: dict) -> dict:
    rows = []
    for one in job["designs"]:
        design = one["design"]
        info = {"bone_removed": removed(design, job.get("settings") or {})}
        if not fits(design):
            info["reason"] = "no entry offset lets this stem fit"
        rows.append({"name": one["name"], "feasible": fits(design), "info": info})
    return {"designs": rows}


def stem_model(design: dict, settings: dict) -> tuple[dict, dict]:
    """A well-formed stem model: its manifest, and its files (name -> text)."""
    length, drop = float(design["length"]), float(settings.get("cut_drop", 0.0))
    files = {"geometry/body.step": "ISO-10303-21; fake stem body\n", "faces/interface.stl": "solid interface\nendsolid interface\n"}
    model = {
        "format": 1, "files": sorted(files), "units": {"length": "mm"}, "dimension": "3d", "design": design,
        "regions": [{"name": "body", "role": "body", "geometry": {"kind": "solid", "file": "geometry/body.step"},
                     "material": {"model": "elastic", "E": 110000.0, "nu": 0.3}}],
        "faces": {"interface": {"region": "body", "file": "faces/interface.stl"}},
        "features": {"taper_center": [0.0, 0.0, length], "tip": [0.0, 0.0, 0.0]},
        "axes": {"stem_axis": {"point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]}},
        "placement": {"frame": {"origin": [0.0, 0.0, -drop], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]},
                      "cut": {"point": [0.0, 0.0, length - drop], "normal": [0.0, 0.0, 1.0]}, "removed": None,
                      "landmarks": ["head_center"]},
        "templating": {"bone_removed": removed(design, settings)},
    }
    return model, files


def model(job: dict, out: pathlib.Path) -> dict:
    design, settings = job["point"]["design"], job.get("settings") or {}
    behave = design.get("behave", "ok")
    if (job.get("bone") or {}).get("format") != 2 or "head_center" not in job["bone"]["landmarks"]:
        return {"status": "error", "reason": "the bone manifest was not handed over read as version 2 (job['bone'])", "pre": {}}
    if not fits(design):
        return {"status": "misfit", "reason": "no entry offset lets this stem fit", "pre": {"bone_removed": None}}
    if behave in FAILS:
        status, reason = FAILS[behave]
        return {"status": status, "reason": reason, "pre": {}}
    if behave == "stem_crash":
        print("fake stem space: crashing on purpose", flush=True)
        sys.exit(3)
    manifest, files = stem_model(design, settings)
    if behave == "badmodel":
        del manifest["axes"]
    if behave == "noname":
        del manifest["features"]["taper_center"]
    where = out / "model"
    for rel, text in files.items():
        (where / rel).parent.mkdir(parents=True, exist_ok=True)
        (where / rel).write_text(text)
    (where / "stem_model.json").write_text(json.dumps(manifest))
    return {"status": "ok", "reason": "", "pre": {"bone_removed": removed(design, settings)}}


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text())
    result = template(job) if job["mode"] == "template" else model(job, out)
    (out / "result.json").write_text(json.dumps(result))


if __name__ == "__main__":
    main()
