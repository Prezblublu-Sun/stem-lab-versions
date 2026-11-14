"""A fake strategy. It speaks the strategy conventions written in stemlab/contract/formats/package.py.

How it ranks the feasible candidates, by the first objective column:
    predictions given   by the predicted value (goal min: smallest first)
    data given          by the value in the nearest computed point (nearest in the numeric design items)
    neither             in an order shuffled with the seed: a stand-in for space filling

The manifest's "behave" makes it misbehave on purpose (never for the self-test job, which carries "note": "selftest"):
    best         nothing odd
    infeasible   puts every infeasible candidate in front of its picks
    unknown      puts a name that is not in the pool in front of its picks
    dice         ignores the seed: two runs of the same job pick differently
    crash        dies
"""
import json
import os
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent


def numbers(values: dict, names) -> list:
    return [values[name] for name in names if isinstance(values.get(name), (int, float)) and not isinstance(values[name], bool)]


def computed(folders, column: str) -> list:
    """(numeric design items, value of the column) of every computed point that has a value."""
    known = []
    for folder in map(pathlib.Path, folders):
        listed = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        design = sorted(one["name"] for one in listed["columns"] if one["role"] == "design")
        for line in (folder / "rows.jsonl").read_text(encoding="utf-8").split("\n"):
            if line.strip() and json.loads(line)["values"].get(column) is not None:
                values = json.loads(line)["values"]
                known.append((numbers(values, design), values[column]))
    return known


def main() -> None:
    source, out = map(pathlib.Path, sys.argv[1:3])
    job = json.loads((source / "job.json").read_text(encoding="utf-8"))
    listed = json.loads((HERE.parent / "manifest.json").read_text(encoding="utf-8"))
    behave = "best" if job.get("note") == "selftest" else listed.get("behave", "best")
    if behave == "crash":
        print("fake strategy: crashing on purpose", flush=True)
        sys.exit(4)
    goal = job["objective"]["objectives"][0]
    sign = 1.0 if goal["goal"] == "min" else -1.0
    fine = sorted((one for one in job["candidates"] if one["feasible"]), key=lambda one: one["name"])
    if job.get("predictions"):
        guess = {row["name"]: row["values"][goal["column"]] for row in job["predictions"]}
        ranked = sorted((one for one in fine if one["name"] in guess), key=lambda one: (sign * guess[one["name"]], one["name"]))
        scored = [(one, -sign * guess[one["name"]], f"predicted {goal['column']} = {guess[one['name']]:.6g}") for one in ranked]
        model = "the registered predictor"
    elif job.get("data"):
        known = computed(job["data"], goal["column"])

        def near(one) -> float:
            here = numbers(one["design"], sorted(one["design"]))
            return min(known, key=lambda row: sum((a - b) ** 2 for a, b in zip(here, row[0])))[1]

        ranked = sorted(fine, key=lambda one: (sign * near(one), one["name"]))
        scored = [(one, -sign * near(one), f"the nearest computed point has {goal['column']} = {near(one):.6g}") for one in ranked]
        model = "nearest neighbour on the given data"
    else:
        rng = random.Random(os.urandom(8) if behave == "dice" else job["seed"])
        rng.shuffle(fine)
        scored = [(one, float(len(fine) - place), "no model: order shuffled with the seed") for place, one in enumerate(fine)]
        model = None
    chosen = [{"name": one["name"], "score": score, "why": why} for one, score, why in scored[:job["count"]]]
    if behave == "infeasible":
        chosen = [{"name": one["name"], "score": 99.0, "why": "picked although it does not fit"}
                  for one in job["candidates"] if not one["feasible"]] + chosen
    if behave == "unknown":
        chosen.insert(0, {"name": "c9999", "score": 100.0, "why": "not in the pool"})
    (out / "result.json").write_text(json.dumps({"chosen": chosen, "model": model}), encoding="utf-8")


if __name__ == "__main__":
    main()
