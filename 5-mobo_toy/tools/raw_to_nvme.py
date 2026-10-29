"""Move the raw Abaqus CSV folders of exported, DONE db_* design / variant jobs from the root disk to the NVMe, leaving a symlink.

User approval 2026-10-29 (one-week FEA plan, section 4 option A). Scope:
  - jobs listed in an export's jobs.txt, name db_* but not db_ref_* (the intact references are read by every new bond post-processing,
    so they stay on the root disk and new jobs never depend on the NVMe);
  - status DONE, spec kind design / variant;
  - folders m_fric_csv / m_bond_csv that are real directories (a symlink = already moved).
Per folder: copy -> md5 of every file on both sides -> rename the original to <name>.moving -> symlink -> md5 again through the symlink
-> delete the original. Any mismatch or error: the copy is removed, the original restored and kept, the folder reported (never silent).
Manifest (append): /mnt/nvme/mobo_raw/MANIFEST.tsv  (utc, job, folder, file, bytes, md5).
usage: python3 raw_to_nvme.py <jobs.txt> [--limit N] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

Q = pathlib.Path.home() / "mobo_toy_v2" / "queue"
DST = pathlib.Path("/mnt/nvme/mobo_raw")
FOLDERS = ("m_fric_csv", "m_bond_csv")


def md5(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tree(d: pathlib.Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_size, md5(p)) for p in sorted(d.rglob("*")) if p.is_file()}


def move(job: str, folder: str, man) -> str:
    src = Q / job / folder
    dst = DST / job / folder
    if dst.exists():
        raise RuntimeError(f"{dst} exists already")
    a = tree(src)
    dst.mkdir(parents=True)
    for rel in a:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, dst / rel)
        st = (src / rel).stat()
        os.utime(dst / rel, (st.st_atime, st.st_mtime))
    b = tree(dst)
    if a != b:
        shutil.rmtree(dst)
        raise RuntimeError("copy differs from the original (copy removed)")
    tmp = src.with_name(folder + ".moving")
    src.rename(tmp)
    try:
        src.symlink_to(dst, target_is_directory=True)
        if tree(src) != a:
            raise RuntimeError("check through the symlink failed")
    except Exception:
        if src.is_symlink():
            src.unlink()
        tmp.rename(src)
        shutil.rmtree(dst, ignore_errors=True)
        raise
    shutil.rmtree(tmp)
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for rel, (sz, h) in a.items():
        man.write(f"{t}\t{job}\t{folder}\t{rel}\t{sz}\t{h}\n")
    man.flush()
    return f"{sum(v[0] for v in a.values())} bytes, {len(a)} files"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not os.path.ismount("/mnt/nvme"):
        raise SystemExit("/mnt/nvme is not mounted")
    todo = []
    for job in pathlib.Path(a.jobs).read_text().split():
        if not job.startswith("db_") or job.startswith("db_ref_"):
            continue
        d = Q / job
        if not (d / "DONE").exists():
            continue
        if json.loads((d / "spec.json").read_text()).get("kind") not in ("design", "variant"):
            continue
        todo += [(job, f) for f in FOLDERS if (d / f).is_dir() and not (d / f).is_symlink()]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(todo)} folders to move", flush=True)
    if a.dry_run:
        return
    DST.mkdir(exist_ok=True)
    ok, bad, nbytes = 0, [], 0
    with open(DST / "MANIFEST.tsv", "a", encoding="utf-8") as man:
        for job, f in todo:
            try:
                r = move(job, f, man)
                ok += 1
                nbytes += int(r.split()[0])
            except Exception as ex:                        # reported, original kept
                bad.append((job, f, f"{type(ex).__name__}: {ex}"))
                print(f"FAILED {job}/{f}: {ex}", flush=True)
    print(json.dumps({"moved": ok, "failed": len(bad), "bytes": nbytes, "free_root": shutil.disk_usage("/").free}), flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
