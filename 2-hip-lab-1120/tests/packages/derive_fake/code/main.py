"""A fake derived-quantity definition: the 95th percentile of the interface slip, taken here as 0.95 x the maximum.

On the fea.run path the job also carries the bone model: job["bone_model"] is its folder and job["bone"] its manifest,
already read as the current version by the caller. Handed a bone model any other way, this definition gives no result.
"""
import json
import pathlib
import sys

source, out = map(pathlib.Path, sys.argv[1:3])
job = json.loads((source / "job.json").read_text())
if "bone_model" in job and (job.get("bone") or {}).get("format") != 2:
    sys.exit("the bone manifest was not handed over read as version 2 (job['bone'])")
where = pathlib.Path(job["fields"]["interface_slip"])
slip = json.loads((where if where.is_absolute() else source / where).read_text())
(out / "result.json").write_text(json.dumps({"derived": {"slip_p95": 0.95 * max(slip)}}))
