"""A fake derived-quantity definition: the 95th percentile of the interface slip, taken here as 0.95 x the maximum."""
import json
import pathlib
import sys

source, out = map(pathlib.Path, sys.argv[1:3])
job = json.loads((source / "job.json").read_text())
where = pathlib.Path(job["fields"]["interface_slip"])
slip = json.loads((where if where.is_absolute() else source / where).read_text())
(out / "result.json").write_text(json.dumps({"derived": {"slip_p95": 0.95 * max(slip)}}))
