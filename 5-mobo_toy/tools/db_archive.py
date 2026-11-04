#!/usr/bin/env python3
"""db3406 raw archive: one tar.xz per job, streamed from Linux over ssh straight to H: (plan 1.6, 2.2 D6). COPY ONLY.

    python tools/db_archive.py archive --jobs sb13_init_050d50bd d13bond_p13_a100_b1cce588_102676fb \
        [--out "H:/projects/Femoral implant generation/db3406/raw"] [--min-free-gb 50]
    python tools/db_archive.py verify  --out <raw dir> [--jobs ...]          offline re-check of stored archives
    python tools/db_archive.py extract --out <raw dir> --jobs ... --to <local queue root>   (for a Windows re-export)
    python tools/db_archive.py results [--out "H:/projects/Femoral implant generation/db3406/raw/results"]
        snapshot of ~/mobo_toy_v2/results/{neckopt_p11..14,db_manifest_*,db_seed_*}.json -> <out>/<UTC stamp>/ + SNAPSHOT.json
        (sha256 both ends; a file changing during the copy -> <stamp>.BAD); the Windows re-export reads it with
        `db_export.py emit --results-root <out>/<stamp>`

Per job:
  1. Linux (read-only, one ssh call): refuse unless the job is finished (DONE or FAILED.json) and Linux free >= 15 GB; list every
     regular file with size and sha256 (`find -type f` + `sha256sum`, pinned `nice -n 19 taskset -c 4-11`).
  2. Linux -> Windows stream (second ssh call): `tar -cf - <job> | xz -T2 -6 | tee >(sha256sum >&2)` under `bash -o pipefail`,
     same pinning; the archive bytes go to <out>/<job>.tar.xz.part on Windows, nothing is staged on Linux. The stream sha256 is
     computed on both ends and must agree.
  3. Windows: decompress the received archive (lzma + tarfile, streaming), sha256 every member and compare with the Linux list
     (same paths, sizes, hashes; no file missing or extra). Only then rename .part -> .tar.xz and write <job>.manifest.json
     (both ends' hashes, sizes, compression ratio, timings). Any mismatch -> <job>.tar.xz.BAD + non-zero exit.
  Disk gates: Linux free < 15 GB or output drive free < --min-free-gb (default 50; H: is always checked against 50 GB) -> stop.
  Nothing on Linux is ever deleted or modified by this tool (no rm / mv / write commands are sent).
  Symlinks: refused, except a job's m_fric_csv / m_bond_csv folder moved to the NVMe by adhoc/raw_to_nvme.py (a directory symlink
  to /mnt/nvme/mobo_raw/<job>/<same name>, user decision 2026-10-29). Those are followed: the listing uses `find -L`, the stream
  `tar -h`, and the manifest records them (dereferenced_links). A broken link (NVMe not mounted) is a non-regular entry -> refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tarfile
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db_export as DX  # noqa: E402

RAW_DEFAULT = "H:/projects/Femoral implant generation/db3406/raw"
QUEUE = "$HOME/mobo_toy_v2/queue"
PIN = "nice -n 19 taskset -c 4-11"
JOB_RE = re.compile(r"^[A-Za-z0-9_.+\-]+$")                          # + : fixed entry offsets, e.g. _ow_m1_e+2_
NVME_RAW = "/mnt/nvme/mobo_raw/"            # raw_to_nvme.py target: the only symlink targets an archive follows
LINKABLE = ("m_fric_csv", "m_bond_csv")


def ssh_base(a) -> list:
    return [a.ssh, "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", "-i", os.path.expanduser(a.key), a.host]


def run_ssh(a, cmd: str, timeout: float = 600) -> str:
    p = subprocess.run(ssh_base(a) + [cmd], capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ssh command failed (rc {p.returncode}): {cmd[:200]}\n{p.stderr.decode(errors='replace')[-1500:]}")
    return p.stdout.decode()


def linux_listing(a, job: str) -> dict:
    """State, free disk and the per-file size + sha256 list of one job (read-only)."""
    q = shlex.quote(job)
    cmd = (f"set -e; cd {QUEUE}; test -d {q}; "
           f"if [ -e {q}/DONE ]; then echo STATE DONE; elif [ -e {q}/FAILED.json ]; then echo STATE FAILED; else echo STATE UNFINISHED; fi; "
           f"echo FREE $(df -B1 --output=avail \"$HOME\" | tail -1); "
           f"echo SYMLINKS; find {q} -type l -printf '%p\\t%l\\n'; "
           f"echo SIZES; {PIN} find -L {q} -type f -printf '%s\\t%p\\n' | LC_ALL=C sort -t \"$(printf '\\t')\" -k2; "
           f"echo HASHES; {PIN} find -L {q} -type f -print0 | LC_ALL=C sort -z | {PIN} xargs -0 -r sha256sum; "
           f"echo LINKS $({PIN} find -L {q} ! -type f ! -type d | wc -l)")
    out = run_ssh(a, cmd)
    state, free, sizes, hashes, links, mode, symlinks = None, None, {}, {}, None, None, {}
    for line in out.splitlines():
        if line.startswith("STATE "):
            state = line.split()[1]
        elif line.startswith("FREE "):
            free = int(line.split()[1]) / 1e9
        elif line in ("SYMLINKS", "SIZES", "HASHES"):
            mode = line
        elif line.startswith("LINKS "):
            links = int(line.split()[1])
            mode = None
        elif mode == "SYMLINKS" and line:
            pth, tgt = line.split("\t", 1)
            symlinks[pth] = tgt
        elif mode == "SIZES" and line:
            s, pth = line.split("\t", 1)
            sizes[pth] = int(s)
        elif mode == "HASHES" and line:
            h, pth = line.split("  ", 1)
            hashes[pth] = h
    if set(sizes) != set(hashes):
        raise RuntimeError(f"{job}: Linux size and hash listings disagree ({len(sizes)} vs {len(hashes)} files)")
    return {"state": state, "free_gb": free, "files": {p: {"size": sizes[p], "sha256": hashes[p]} for p in sorted(sizes)},
            "n_special": links, "symlinks": symlinks}


def link_problems(job: str, symlinks: dict) -> list:
    """Symlinks an archive may follow: <job>/m_fric_csv or m_bond_csv -> /mnt/nvme/mobo_raw/<job>/<same name>. Others are problems."""
    bad = []
    for pth, tgt in symlinks.items():
        name = pth.split("/", 1)[1] if "/" in pth else ""
        if not (name in LINKABLE and tgt == f"{NVME_RAW}{job}/{name}"):
            bad.append(f"{pth} -> {tgt}")
    return bad


def stream_archive(a, job: str, dst_part: pathlib.Path, deref: bool = False) -> dict:
    q = shlex.quote(job)
    inner = (f"cd {QUEUE} && {PIN} tar {'-h ' if deref else ''}-cf - {q} | {PIN} xz -T{int(getattr(a, 'xz_threads', 2))} -{a.level} -c | tee >(sha256sum 1>&2)")
    cmd = f"bash -o pipefail -c {shlex.quote(inner)}"
    t0 = time.time()
    h = hashlib.sha256()
    n = 0
    errf = dst_part.with_name(dst_part.name + ".stderr")              # a file, not a pipe: no deadlock on a chatty stderr
    with open(dst_part, "wb") as fo, open(errf, "wb") as fe:
        p = subprocess.Popen(ssh_base(a) + [cmd], stdout=subprocess.PIPE, stderr=fe)
        try:
            for blk in iter(lambda: p.stdout.read(1 << 20), b""):
                fo.write(blk)
                h.update(blk)
                n += len(blk)
            rc = p.wait(timeout=a.stream_timeout)
        except BaseException:                                        # write error, disk full, Ctrl-C, timeout: never hang on ssh
            DX._abort_proc(p)
            raise
    err = errf.read_bytes().decode(errors="replace")
    errf.unlink()
    m = re.findall(r"^([0-9a-f]{64})  -$", err, re.M)
    return {"rc": rc, "stderr": err[-2000:], "linux_stream_sha256": m[-1] if m else None, "windows_sha256": h.hexdigest(),
            "bytes": n, "wall_s": time.time() - t0}


def members_of(archive: pathlib.Path) -> tuple[dict, list]:
    """sha256 + size of every regular member of a tar.xz (streaming); list of non-regular members."""
    out, special = {}, []
    with lzma.open(archive, "rb") as xf, tarfile.open(fileobj=xf, mode="r|") as tf:
        for m in tf:
            if m.isdir():
                continue
            if not m.isfile():
                special.append(m.name)
                continue
            fh = tf.extractfile(m)
            h = hashlib.sha256()
            n = 0
            for blk in iter(lambda: fh.read(1 << 20), b""):
                h.update(blk)
                n += len(blk)
            out[m.name] = {"size": n, "sha256": h.hexdigest()}
    return out, special


def compare(linux_files: dict, win_files: dict) -> list:
    errs = []
    for p, v in linux_files.items():
        w = win_files.get(p)
        if w is None:
            errs.append(f"{p}: in the Linux listing, not in the archive")
        elif w != v:
            errs.append(f"{p}: Linux {v} vs archive {w}")
    for p in win_files:
        if p not in linux_files:
            errs.append(f"{p}: in the archive, not in the Linux listing")
    return errs


def gate_local(out: pathlib.Path, min_free: float) -> None:
    f = DX.free_gb(out)
    if f < min_free:
        raise SystemExit(f"DISK GATE: {out} has {f:.1f} GB free < {min_free} GB")
    if pathlib.Path("H:/").exists() and DX.free_gb("H:/") < DX.H_MIN_FREE_GB:
        raise SystemExit(f"DISK GATE: H: has {DX.free_gb('H:/'):.1f} GB free < {DX.H_MIN_FREE_GB} GB")


def archive_one(a, job: str, out: pathlib.Path) -> dict:
    if not JOB_RE.match(job):
        raise ValueError(f"bad job name {job!r}")
    final = out / f"{job}.tar.xz"
    if final.exists() and not a.overwrite:
        return {"job": job, "status": "exists", "archive": str(final)}
    gate_local(out, a.min_free_gb)
    t0 = time.time()
    li = linux_listing(a, job)
    if li["free_gb"] is None or li["free_gb"] < DX.LINUX_MIN_FREE_GB:
        raise SystemExit(f"DISK GATE: Linux free {li['free_gb']} GB < {DX.LINUX_MIN_FREE_GB} GB")
    if li["state"] not in ("DONE", "FAILED") and not a.allow_unfinished:
        raise SystemExit(f"{job}: state {li['state']} -- only finished jobs are archived (files may still change)")
    if li["n_special"]:
        raise SystemExit(f"{job}: {li['n_special']} non-regular entries (broken symlink -- NVMe not mounted? -- or special file), refusing")
    lp = link_problems(job, li["symlinks"])
    if lp:
        raise SystemExit(f"{job}: symlinks other than the NVMe raw-data moves -- not handled, refusing: {lp[:5]}")
    part = out / f"{job}.tar.xz.part"
    try:
        st = stream_archive(a, job, part, deref=bool(li["symlinks"]))
    except BaseException as e:                                       # the stream died: quarantine what arrived, report, re-raise
        bad = out / f"{job}.tar.xz.BAD"
        if part.exists():
            os.replace(part, bad)
        (out / f"{job}.manifest.BAD.json").write_text(json.dumps(
            {"job": job, "failed_utc": DX.now_utc(), "exception": f"{type(e).__name__}: {e}", "files_linux": li["files"],
             "partial_archive": str(bad) if bad.exists() else None}, indent=1))
        print(f"{job}: stream FAILED ({type(e).__name__}: {e}); partial archive -> {bad.name}, report {job}.manifest.BAD.json",
              file=sys.stderr)
        raise
    errs = []
    if st["rc"] != 0:
        errs.append(f"remote tar | xz exited {st['rc']}: {st['stderr'][-500:]}")
    if st["linux_stream_sha256"] is None:
        errs.append("no stream sha256 from Linux")
    elif st["linux_stream_sha256"] != st["windows_sha256"]:
        errs.append(f"stream sha256 Linux {st['linux_stream_sha256']} != Windows {st['windows_sha256']}")
    t1 = time.time()
    win, special = members_of(part) if not errs else ({}, [])
    if special:
        errs.append(f"non-regular archive members: {special[:10]}")
    if not errs:
        errs += compare(li["files"], win)
    raw_bytes = sum(v["size"] for v in li["files"].values())
    rep = {"job": job, "state": li["state"], "archived_utc": DX.now_utc(), "linux_free_gb": li["free_gb"], "n_files": len(li["files"]),
           "raw_bytes": raw_bytes, "archive_bytes": st["bytes"], "ratio": st["bytes"] / raw_bytes if raw_bytes else None,
           "xz_level": a.level, "stream_wall_s": st["wall_s"], "verify_wall_s": time.time() - t1, "total_wall_s": time.time() - t0,
           "stream_sha256": {"linux": st["linux_stream_sha256"], "windows": st["windows_sha256"]},
           "files_linux": li["files"], "files_archive": win, "dereferenced_links": li["symlinks"], "errors": errs, "tool": DX.EXPORTER_VERSION.replace("db_export", "db_archive")}
    if errs:
        bad = out / f"{job}.tar.xz.BAD"
        os.replace(part, bad)
        (out / f"{job}.manifest.BAD.json").write_text(json.dumps(rep, indent=1))
        rep["status"] = "BAD"
        return rep
    os.replace(part, final)
    (out / f"{job}.manifest.json").write_text(json.dumps(rep, indent=1))
    rep["status"] = "ok"
    return rep


def cmd_archive(a) -> int:
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reps = []
    for j in a.jobs:
        r = archive_one(a, j, out)
        reps.append(r)
        print(f"{j}: {r['status']}" + (f"  {r['n_files']} files, raw {r['raw_bytes'] / 1e6:.1f} MB -> {r['archive_bytes'] / 1e6:.1f} MB "
                                       f"({r['ratio']:.3f}), stream {r['stream_wall_s']:.1f} s, verify {r['verify_wall_s']:.1f} s"
                                       if r["status"] in ("ok", "BAD") else ""))
        for e in r.get("errors", [])[:20]:
            print("   ERROR:", e)
        if r["status"] == "BAD":
            return 2
    return 0


RESULTS_DIR = "$HOME/mobo_toy_v2/results"
RESULTS_GLOBS = "neckopt_p1[1-4].json db_manifest_*.json db_seed_*.json"     # the provenance inputs of db_export emit
RESULT_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.json$")


def results_listing(a) -> dict:
    """name -> {sha256, size, mtime} of the provenance files in ~/mobo_toy_v2/results (read-only, one ssh call)."""
    inner = (f"cd {RESULTS_DIR} && shopt -s nullglob && for f in {RESULTS_GLOBS}; do "
             "printf '%s\\t%s\\t%s\\n' \"$(sha256sum < \"$f\" | cut -d' ' -f1)\" \"$(stat -c '%s %Y' \"$f\")\" \"$f\"; done")
    out = run_ssh(a, f"{PIN} bash -c {shlex.quote(inner)}")
    files = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        h, sm, name = line.split("\t")
        size, mt = sm.split()
        if not RESULT_NAME_RE.match(name):
            raise RuntimeError(f"unexpected results file name {name!r}")
        files[name] = {"sha256": h, "size": int(size), "mtime_utc": DX.utc(float(mt))}
    return files


def cmd_results(a) -> int:
    """Snapshot the provenance inputs (BO records neckopt_p11..14.json, stage_db manifests, CD-0 seed) to <out>/<UTC stamp>/ with
    sha256 on both ends + SNAPSHOT.json, so a Windows re-export (`db_export.py emit --results-root <that dir>`) keeps source,
    selection, pool_idx, round and layer. Copy only; a file that changes during the copy makes the snapshot BAD."""
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    gate_local(out, a.min_free_gb)
    stamp = DX.now_utc().replace(":", "").replace("-", "")
    part, final = out / f"{stamp}.part", out / stamp
    part.mkdir()
    t0 = time.time()
    before = results_listing(a)
    if not any(n.startswith("neckopt_p") for n in before):
        raise SystemExit(f"no neckopt_p11..14.json in {RESULTS_DIR}: nothing to snapshot")
    names = sorted(before)
    inner = f"cd {RESULTS_DIR} && {PIN} tar -cf - " + " ".join(shlex.quote(n) for n in names)
    errs, got = [], {}
    p = subprocess.Popen(ssh_base(a) + [inner], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=p.stdout, mode="r|") as tf:
            for m in tf:
                if not m.isfile() or "/" in m.name or not RESULT_NAME_RE.match(m.name) or m.name not in before:
                    raise RuntimeError(f"unexpected member {m.name!r}")
                data = tf.extractfile(m).read()
                (part / m.name).write_bytes(data)
                got[m.name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        p.stdout.read()
        rc = p.wait(timeout=120)
        if rc != 0:
            errs.append(f"remote tar exited {rc}: {p.stderr.read().decode(errors='replace')[-500:]}")
    except BaseException as e:
        DX._abort_proc(p)
        errs.append(f"stream failed: {type(e).__name__}: {e}")
        if not isinstance(e, Exception):
            raise
    after = results_listing(a)
    for n in names:
        b, w, z = before[n], got.get(n), after.get(n)
        if w is None:
            errs.append(f"{n}: not received")
        elif (w["sha256"], w["size"]) != (b["sha256"], b["size"]):
            errs.append(f"{n}: Windows sha256/size {w} != Linux listing {b}")
        if z is None or z["sha256"] != b["sha256"]:
            errs.append(f"{n}: changed on Linux during the snapshot (before {b['sha256'][:12]}, after {(z or {}).get('sha256', '')[:12]})")
    rep = {"created_utc": DX.now_utc(), "linux_dir": "~/mobo_toy_v2/results", "host": a.host, "files": before,
           "received_sha256": {n: v["sha256"] for n, v in got.items()}, "errors": errs, "wall_s": time.time() - t0,
           "tool": DX.EXPORTER_VERSION.replace("db_export", "db_archive"),
           "use": "db_export.py emit --results-root <this dir> (Windows re-export from the job archives)"}
    (part / "SNAPSHOT.json").write_text(json.dumps(rep, indent=1, sort_keys=True))
    if errs:
        bad = out / f"{stamp}.BAD"
        os.replace(part, bad)
        print(f"results snapshot BAD -> {bad}")
        for e in errs:
            print("   ERROR:", e)
        return 2
    os.replace(part, final)
    print(f"results snapshot {final}: {len(names)} files ({', '.join(names)}), {sum(v['size'] for v in before.values()) / 1e6:.2f} MB, "
          f"{rep['wall_s']:.1f} s, sha256 equal on both ends")
    return 0


def cmd_verify(a) -> int:
    out = pathlib.Path(a.out)
    jobs = a.jobs or sorted(p.name[:-len(".manifest.json")] for p in out.glob("*.manifest.json") if ".BAD" not in p.name)
    bad = 0
    for j in jobs:
        m = json.loads((out / f"{j}.manifest.json").read_text())
        arc = out / f"{j}.tar.xz"
        errs = []
        if DX.sha256_file(arc) != m["stream_sha256"]["windows"]:
            errs.append("archive sha256 differs from the manifest")
        win, special = members_of(arc)
        errs += compare(m["files_linux"], win) + [f"special member {s}" for s in special]
        print(f"{j}: {'ok' if not errs else 'BAD'} ({len(win)} members)")
        for e in errs[:20]:
            print("   ERROR:", e)
        bad += bool(errs)
    return 1 if bad else 0


def cmd_extract(a) -> int:
    out, to = pathlib.Path(a.out), pathlib.Path(a.to)
    to.mkdir(parents=True, exist_ok=True)
    for j in a.jobs:
        m = json.loads((out / f"{j}.manifest.json").read_text())
        with lzma.open(out / f"{j}.tar.xz", "rb") as xf, tarfile.open(fileobj=xf, mode="r|") as tf:
            for mem in tf:
                pp = pathlib.PurePosixPath(mem.name)
                if pp.is_absolute() or ".." in pp.parts or pp.parts[0] != j:
                    raise SystemExit(f"{j}: unsafe member {mem.name!r}")
                if mem.isdir():
                    (to / mem.name).mkdir(parents=True, exist_ok=True)
                    continue
                if not mem.isfile():
                    raise SystemExit(f"{j}: non-regular member {mem.name!r}")
                dst = to / mem.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                fh = tf.extractfile(mem)
                h = hashlib.sha256()
                with open(dst, "wb") as fo:
                    for blk in iter(lambda: fh.read(1 << 20), b""):
                        fo.write(blk)
                        h.update(blk)
                os.utime(dst, (mem.mtime, mem.mtime))                 # keep the Linux mtimes (t_*_utc columns come from them)
                want = m["files_linux"].get(mem.name, {}).get("sha256")
                if want != h.hexdigest():
                    raise SystemExit(f"{j}: {mem.name} sha256 {h.hexdigest()} != Linux {want}")
        print(f"{j}: extracted to {to / j} (sha256 verified per file)")
    return 0


def main(argv=None) -> int:
    DX.idle_priority()
    ap = argparse.ArgumentParser(description="db3406 raw archive (copy only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nm in ("archive", "verify", "extract", "results"):
        p = sub.add_parser(nm)
        p.add_argument("--out", default=RAW_DEFAULT + "/results" if nm == "results" else RAW_DEFAULT)
        p.add_argument("--jobs", nargs="*")
        if nm in ("archive", "results"):
            p.add_argument("--min-free-gb", type=float, default=DX.H_MIN_FREE_GB)
            p.add_argument("--host", default=DX.LINUX_HOST)
            p.add_argument("--key", default=DX.LINUX_KEY)
            p.add_argument("--ssh", default=DX.SSH_EXE)
        if nm == "archive":
            p.add_argument("--level", type=int, default=6)
            p.add_argument("--overwrite", action="store_true")
            p.add_argument("--allow-unfinished", action="store_true")
            p.add_argument("--stream-timeout", type=float, default=3600.0, help="seconds to wait for ssh after the stream ended")
            p.add_argument("--xz-threads", type=int, default=2, help="xz -T on Linux (plan: 2)")
        if nm == "extract":
            p.add_argument("--to", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "results":
        return cmd_results(a)
    if a.cmd == "archive":
        if not a.jobs:
            ap.error("--jobs is required")
        return cmd_archive(a)
    if a.cmd == "verify":
        return cmd_verify(a)
    if not a.jobs:
        ap.error("--jobs is required")
    return cmd_extract(a)


if __name__ == "__main__":
    sys.exit(main())
