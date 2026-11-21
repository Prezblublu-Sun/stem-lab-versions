"""Another fake strategy, as different from strategy_fake as can be: it simply picks the longest feasible stems.

It exists to show that swapping the strategy needs no change in the opt plugin.
"""
import json
import pathlib
import sys


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    fine = sorted((one for one in job["candidates"] if one["feasible"]), key=lambda one: (-one["design"]["length"], one["name"]))
    chosen = [{"name": one["name"], "score": one["design"]["length"], "why": "one of the longest stems that fit"} for one in fine[:job["count"]]]
    (out / "result.json").write_text(json.dumps({"chosen": chosen, "model": None}), encoding="utf-8")


if __name__ == "__main__":
    main()
