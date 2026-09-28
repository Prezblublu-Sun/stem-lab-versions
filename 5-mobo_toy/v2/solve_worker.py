"""本机 Abaqus 求解 worker：本机只做求解。只用标准库 + run_abaqus（v1 的运行器：许可重试、超时判 L4、odb 导出失败判 L5）。

循环：
1. 在 Linux 队列里找 READY 作业，用 `mv READY CLAIMED` 原子认领；
2. 取回作业目录里的全部 .inp，放进 v2/runs/q/<job_id>/；
3. 每个 .inp 是一个求解单元，最多 SLOTS 个单元并行，每个 CPUS 核；摩擦模型优先；
4. 一个作业的全部单元结束后，把 QoI 需要的 CSV（摩擦：RELEASE/LOAD_CONTACT；粘接：LOAD_ENER、LOAD_S；
   完整股骨：LOAD_ENER）和 solve.json 推回 Linux 的作业目录，写 SOLVED；删除本地 odb 等大文件，留日志。
停止：本机建 v2/runs/worker.STOP，或 Linux 上建 ~/mobo_toy_v2/queue/STOP；在跑的单元会先跑完。
ssh 失败写日志、等 30 s 再试（WiFi 断连）；求解失败照实写进 solve.json，由 Linux 判级。
"""
from __future__ import annotations

import io
import json
import pathlib
import shutil
import sys
import tarfile
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import remote as R  # noqa: E402
import run_abaqus as RA  # noqa: E402

SLOTS = 2
CPUS = 4
TIMEOUT = 6 * 3600       # s/单元。v1 默认 900 s 太短：1.0 mm 网格的摩擦模型要 40–60 min；且 Windows 上
                         # subprocess 超时要等孙进程结束才返回，会把实际已算完的作业误判 L4
LOCAL = HERE / "runs" / "q"
LOG = HERE / "runs" / "worker.log"
STOP_LOCAL = HERE / "runs" / "worker.STOP"
KEEP = {"fric": ["RELEASE_CONTACT.csv", "LOAD_CONTACT.csv"], "bond": ["LOAD_ENER.csv", "LOAD_S.csv"],
        "intact": ["LOAD_ENER.csv", "LOAD_S.csv"]}      # 完整股骨的应力场：应力屏蔽对比图要用（2026-09-28 23:00）
Q = "~/mobo_toy_v2/queue"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


def kind_of(stem: str) -> str:
    return "fric" if stem.endswith("_fric") else "bond" if stem.endswith("_bond") else "intact"


def claim_next(n: int) -> list[str]:
    # 按 READY 标记的时间先来先服务（ls -tr）。原先按名字排序，bo_…_s0 的后续轮次总排在 s1/s2 的初始点前面，
    # 三个种子被串行化（2026-09-28 11:35 观察：s0 已到第 6 轮，s2 一个都没算）。改后在 12:00 暂停后的重启生效。
    out = R.sh(f"cd {Q} 2>/dev/null && ls -tr -d */READY 2>/dev/null | head -n {n} || true", timeout=60)
    got = []
    for line in out.split():
        jid = line.split("/")[0]
        try:
            R.sh(f"cd {Q}/{jid} && mv READY CLAIMED", timeout=60)
            got.append(jid)
        except R.RemoteError:
            pass                                                   # 被别的 worker 抢先，或状态已变
    return got


def fetch(jid: str) -> list[pathlib.Path]:
    d = LOCAL / jid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    r = R._ssh(f"cd {Q}/{jid} && tar -cf - *.inp", timeout=600)
    if r.returncode != 0:
        raise R.RemoteError(f"fetch {jid}: {r.stderr.decode(errors='replace')[-500:]}")
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        tf.extractall(d, filter="data")
    inps = sorted(d.glob("*.inp"), key=lambda p: (kind_of(p.stem) != "fric", p.name))  # 摩擦模型先跑
    if not inps:
        raise RuntimeError(f"job {jid} has no .inp files")
    return inps


def push(jid: str, results: dict) -> None:
    d = LOCAL / jid
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for stem, r in results.items():
            if r.get("status") == "OK":
                for f in KEEP[kind_of(stem)]:
                    p = d / f"{stem}_csv" / f
                    if not p.exists():
                        r["status"], r["reason"] = "L5", f"missing export {p.name}"
                        continue
                    tf.add(p, arcname=f"{stem}_csv/{f}")
        data = json.dumps(results, indent=1, default=str).encode()
        ti = tarfile.TarInfo("solve.json"); ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    R.sh(f"cd {Q}/{jid} && tar -xf - && touch SOLVED", stdin=buf.getvalue(), timeout=600)


def cleanup(jid: str) -> None:
    d = LOCAL / jid
    for p in d.iterdir():
        if p.suffix in (".odb", ".inp", ".mdl", ".stt", ".prt", ".res", ".sim", ".023", ".abq", ".pac", ".sel") or p.is_dir():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)


def stop_requested() -> bool:
    if STOP_LOCAL.exists():
        return True
    try:
        return R.sh(f"test -e {Q}/STOP && echo yes || echo no", timeout=60).strip() == "yes"
    except R.RemoteError:
        return False


def main():
    log(f"worker start: SLOTS={SLOTS} CPUS={CPUS} TIMEOUT={TIMEOUT}")
    pending_units: list[tuple[str, pathlib.Path]] = []
    jobs: dict[str, dict] = {}                          # jid -> {"left": n, "results": {}}
    running = {}
    backoff = 0
    with ThreadPoolExecutor(SLOTS) as ex:
        while True:
            try:
                if not pending_units and len(running) < SLOTS:
                    if stop_requested():
                        if not running:
                            log("stop requested; exiting")
                            return
                    else:
                        for jid in claim_next(1):
                            try:
                                inps = fetch(jid)
                            except Exception as e:                                  # noqa: BLE001
                                log(f"{jid}: fetch failed: {e}")
                                push(jid, {"fetch": {"status": "L4", "reason": f"fetch failed: {e}"}})
                                continue
                            jobs[jid] = {"left": len(inps), "results": {}}
                            pending_units += [(jid, p) for p in inps]
                            log(f"{jid}: claimed, {len(inps)} units")
                backoff = 0
            except R.RemoteError as e:
                backoff = min(backoff + 30, 300)
                log(f"ssh error (retry in {backoff} s): {str(e)[:300]}")
                time.sleep(backoff)
                continue
            while pending_units and len(running) < SLOTS:
                jid, inp = pending_units.pop(0)
                running[ex.submit(RA.run_and_export, inp, cpus=CPUS, timeout=TIMEOUT)] = (jid, inp)
            if not running:
                time.sleep(15)
                continue
            done, _ = wait(list(running), timeout=30, return_when=FIRST_COMPLETED)
            for fut in done:
                jid, inp = running.pop(fut)
                try:
                    r = fut.result()
                except Exception as e:                                              # noqa: BLE001
                    r = {"status": "L4", "reason": f"runner exception: {type(e).__name__}: {e}"}
                jobs[jid]["results"][inp.stem] = r
                jobs[jid]["left"] -= 1
                log(f"{jid}/{inp.stem}: {r.get('status')} {r.get('wall_s', 0):.0f} s {r.get('reason', '')[:120]}")
                if jobs[jid]["left"] == 0:
                    for attempt in range(10):
                        try:
                            push(jid, jobs[jid]["results"])
                            break
                        except R.RemoteError as e:
                            log(f"{jid}: push failed (attempt {attempt + 1}): {str(e)[:200]}")
                            time.sleep(30)
                    else:
                        log(f"{jid}: push failed permanently; local results kept in {LOCAL / jid}")
                        continue
                    cleanup(jid)
                    jobs.pop(jid)
                    log(f"{jid}: pushed, SOLVED")


if __name__ == "__main__":
    main()
