"""The fake solver. Runs in the job folder, reads the deck the fake kernel (or the fake FE package) wrote, and leaves what a
solver would leave: a log, one file per finished step, and a "done" mark when the analysis completed.

If the environment variable FAKE_SOLVER_TRACE names a folder, every run notes there how many fake solvers
were running at the moment it started, so a test can see that the solve slots were respected."""
import json
import os
import pathlib
import sys
import time


def solve(deck: dict) -> int:
    with open("solver.log", "a") as log:
        log.write("step 1 started\n")
        log.flush()
        pathlib.Path("step1.json").write_text(json.dumps({"step": 1, "u": deck["length"] * 0.001}))
        if deck["behave"] in ("diverge", "loose"):
            log.write("***ERROR: TOO MANY ATTEMPTS MADE FOR THIS INCREMENT\n")
            return 1
        if deck["behave"] == "hang":
            log.write("step 2 started and never ends\n")
            log.flush()
            time.sleep(600)
        time.sleep(deck["seconds"])
        pathlib.Path("step2.json").write_text(json.dumps({"step": 2, "u": deck["length"] * 0.002}))
        log.write("THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n")
    pathlib.Path("done").write_text("")
    return 0


def main() -> int:
    deck = json.loads(pathlib.Path(sys.argv[1]).read_text())
    trace = os.environ.get("FAKE_SOLVER_TRACE")
    if not trace:
        return solve(deck)
    folder = pathlib.Path(trace)
    folder.mkdir(parents=True, exist_ok=True)
    mine = folder / f"{os.getpid()}.running"
    mine.write_text("")
    try:
        with open(folder / "seen.txt", "a") as seen:
            seen.write(f"{len(list(folder.glob('*.running')))}\n")
        return solve(deck)
    finally:
        mine.unlink()


if __name__ == "__main__":
    sys.exit(main())
