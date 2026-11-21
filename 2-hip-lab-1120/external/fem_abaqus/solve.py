"""求解的入口：在作业文件夹里跑 Abaqus，算完把 odb 导出成 CSV，写 solve.json。跑完才返回。

    python code/solve.py <作业名，比如 m_fric> <核数> <Abaqus 启动器的位置>

怎么跑、怎么判成没成、许可取不到时怎么等，都是旧系统的 run_abaqus.py，原样用（和参照包的 solve.py 一样）。
这里多做三件事：
    没算完的作业，把已经算出来的那几步也导出来（放在 <作业名>_csv_partial/），失败前算出来的步留得下来；
    记下用的是哪个启动器、求解器报的是哪一版 Abaqus（从 .dat、.msg 的开头读）：跟着 solve.json 归档；
    odb 在导出之后删掉：它很大，场已经在 CSV 里了。
求解的时限由运行设定管（solve_timeout_s：超了由起它的一方把它和它起的进程一起结束），这里给 run_abaqus 的是它管得着的最长的时限。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # 包在只读的地方跑：不往包里写 __pycache__

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "legacy"))
LIMIT = 7 * 24 * 3600.0             # 运行设定的 solve_timeout_s 最多就是 7 天
LEFTOVERS = (".odb", ".mdl", ".stt", ".prt", ".res", ".sim", ".023", ".abq", ".pac", ".sel", ".lck")


def release(where: Path, unit: str) -> str | None:
    """求解器自己报的版本，比如 2025。读不出来是 None。"""
    for suffix in (".dat", ".msg"):
        path = where / f"{unit}{suffix}"
        if path.is_file():
            found = re.search(r"Abaqus\s+(20\d\d(?:[.\-][\w.\-]+)?)", path.read_text(encoding="utf-8", errors="ignore")[:20000])
            if found:
                return found.group(1)
    return None


def main() -> int:
    import run_abaqus as RA

    unit, cpus, launcher = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    RA.LAUNCHER = launcher
    where = Path.cwd()
    result = RA.run_and_export(where / f"{unit}.inp", cpus=cpus, timeout=LIMIT)
    odb = where / f"{unit}.odb"
    if result.get("status") != "OK" and odb.exists():
        partial = RA.export_odb(odb, where / f"{unit}_csv_partial")
        result["partial_export"] = partial.get("status")
    result["launcher"] = launcher
    result["release"] = release(where, unit)
    (where / "solve.json").write_text(json.dumps({unit: result}, default=float), encoding="utf-8")
    for leftover in (where / f"{unit}{suffix}" for suffix in LEFTOVERS):
        if leftover.is_file():
            leftover.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
