"""Review sandbox (d13colrev): run a Python script with an audit hook that BLOCKS and logs every write-type
filesystem operation outside ALLOW. Usage: sandbox_run.py <log.json> <script.py> [args...]
Blocked operations raise PermissionError inside the script (so an attempted write fails loudly)."""
import json
import os
import runpy
import sys

ALLOW = os.path.realpath(os.path.expanduser("~/mobo_toy_v2/deck/D13_test_d13colfix"))
WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
LOG = []
MUT = {"os.mkdir": (0,), "os.rename": (0, 1), "os.replace": (0, 1), "os.remove": (0,), "os.unlink": (0,), "os.rmdir": (0,),
       "os.symlink": (0, 1), "os.link": (0, 1), "os.truncate": (0,), "os.chmod": (0,), "os.chown": (0,), "os.utime": (0,),
       "shutil.copyfile": (1,), "shutil.copytree": (1,), "shutil.rmtree": (0,), "shutil.move": (0, 1), "shutil.copymode": (1,),
       "shutil.copystat": (1,), "tempfile.mkstemp": (0,), "tempfile.mkdtemp": (0,), "os.removexattr": (0,), "os.setxattr": (0,)}


def _ok(p):
    if isinstance(p, int):
        return True                     # fd-relative: the fd itself was opened through a checked open
    try:
        rp = os.path.realpath(os.fsdecode(p))
    except Exception:                   # noqa: BLE001
        return False
    return rp == ALLOW or rp.startswith(ALLOW + os.sep)


def hook(ev, args):
    if ev == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if isinstance(path, int):
            return
        w = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and isinstance(flags, int) and flags & WFLAGS)
        if w:
            ok = _ok(path)
            LOG.append({"ev": ev, "path": os.fsdecode(path), "mode": mode, "flags": flags, "allowed": ok})
            if not ok:
                raise PermissionError(f"sandbox: write blocked: {path} mode {mode} flags {flags}")
    elif ev in MUT:
        paths = [args[i] for i in MUT[ev] if i < len(args)]
        if ev == "os.mkdir" and paths and not isinstance(paths[0], int) and os.path.isdir(os.fsdecode(paths[0])) and not _ok(paths[0]):
            LOG.append({"ev": ev, "path": os.fsdecode(paths[0]), "allowed": True, "note": "already exists (no-op)"})
            return
        ok = all(_ok(p) for p in paths)
        LOG.append({"ev": ev, "path": [os.fsdecode(p) if not isinstance(p, int) else p for p in paths], "allowed": ok})
        if not ok:
            raise PermissionError(f"sandbox: {ev} blocked: {paths}")


def main():
    log, script = sys.argv[1], sys.argv[2]
    sys.argv = [script] + sys.argv[3:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    sys.addaudithook(hook)
    rc = 0
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if not isinstance(e.code, int) and e.code is not None:
            print(f"SystemExit: {e.code}", file=sys.stderr)
    finally:
        blocked = [x for x in LOG if not x["allowed"]]
        with open(log, "w") as fh:
            json.dump({"n_events": len(LOG), "blocked": blocked, "events": LOG}, fh, indent=1)
        print(f"[sandbox] {len(LOG)} write-type events, {len(blocked)} BLOCKED outside {ALLOW}", file=sys.stderr, flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
