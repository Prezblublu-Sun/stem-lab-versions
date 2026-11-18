"""A stand-in FE package for the test of the bed-support derivation. No mesher, no solver.

After the stand-in solver has run, it hands back an interface point cloud made from the stem model alone, in the frame
of the bone model, with the arrays the bed support reads (X, area, d_canal, collar): rings of nodes around the stem axis,
from the shoulder towards the tip. The same nodes, in the stem's own frame, go into cloud.json in the job folder (kept
with the settings), so the test can work out the expected bed support without this file's transform.
"""
import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
RADIUS, RINGS, PER_RING = 7.0, 24, 24           # mm; rings 1.5 mm apart starting 1 mm below the shoulder


def nodes() -> list[dict]:
    """The nodes in the stem's own frame (x medial, y anterior, z along the stem axis)."""
    made = []
    for ring in range(RINGS):
        s = 1.0 + 1.5 * ring
        for k in range(PER_RING):
            angle = math.radians(7.5 + 15.0 * k)
            made.append({"x": [RADIUS * math.cos(angle), RADIUS * math.sin(angle), s], "area": 1.5,
                         "thickness": 0.11 + 0.05 * s, "collar": ring == 0 and k == 0})
    return made


def build(job: dict) -> dict:
    try:
        stem = json.loads((pathlib.Path(job["stem_model"]) / "stem_model.json").read_text(encoding="utf-8"))
        frame = stem["placement"]["frame"]
    except (KeyError, OSError, TypeError, ValueError) as error:
        return {"status": "error", "reason": f"no stem model to make a cloud from: {type(error).__name__}: {error}"}
    where = pathlib.Path(job["job"])
    where.mkdir(parents=True, exist_ok=True)
    made = nodes()
    (where / "cloud.json").write_text(json.dumps({"frame": frame, "nodes": made, "load": job["settings"]["load"]}), encoding="utf-8")
    return {"status": "built", "reason": "", "pre": {"n_nodes": len(made)}, "solve": {"command": ["{python}", str(HERE / "solver.py")]}}


def post(job: dict, out: pathlib.Path) -> dict:
    import numpy as np

    where = pathlib.Path(job["job"])
    keep = {"mesh": [], "settings": ["cloud.json"], "process": ["solver.log"] if (where / "solver.log").exists() else [], "fields": []}
    if not (where / "done").exists():
        return {"status": "env", "reason": "the solver left no result", "steps": {"done": 0, "total": 1}, "keep": keep}
    said = json.loads((where / "cloud.json").read_text(encoding="utf-8"))
    frame = {key: np.asarray(value, float) for key, value in said["frame"].items()}
    local = np.array([node["x"] for node in said["nodes"]])
    X = frame["origin"] + local[:, :1] * frame["x"] + local[:, 1:2] * frame["y"] + local[:, 2:] * frame["z"]
    np.savez(out / "interface.npz", X=X, area=np.array([node["area"] for node in said["nodes"]]),
             d_canal=-np.array([node["thickness"] for node in said["nodes"]]),
             collar=np.array([node["collar"] for node in said["nodes"]], bool))
    return {"status": "ok", "reason": "", "labels": {"load_seen": said["load"]}, "fields": {"interface": "interface.npz"},
            "steps": {"done": 1, "total": 1}, "keep": keep, "solver": {"name": "none", "version": "0"}}


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    result = {"ok": True} if job["mode"] == "echo" else build(job) if job["mode"] == "build" else post(job, out)
    (out / "result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
