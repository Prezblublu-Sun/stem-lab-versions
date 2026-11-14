"""求解的入口：在作业文件夹里跑 Abaqus，算完把 odb 导出成 CSV，写 solve.json。跑完才返回。

    python code/solve.py <单元名，比如 m_fric> <核数> <时限秒> [Abaqus 启动器的位置]

怎么跑、怎么判成没成、许可取不到时怎么等，都是旧系统的 run_abaqus.py，原样用。
这里只多做一件事：没算完的作业，把已经算出来的那几步也导出来（放在 <单元名>_csv_partial/），
这样失败前算出来的步留得下来，内核的后处理也有东西可看。odb 在导出之后删掉：它很大，场已经在 CSV 里了。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "legacy"))


def main() -> int:
    import run_abaqus as RA

    unit, cpus, limit = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    if len(sys.argv) > 4:
        RA.LAUNCHER = sys.argv[4]
    where = Path.cwd()
    result = RA.run_and_export(where / f"{unit}.inp", cpus=cpus, timeout=limit)
    odb = where / f"{unit}.odb"
    if result.get("status") != "OK" and odb.exists():
        partial = RA.export_odb(odb, where / f"{unit}_csv_partial")
        result["partial_export"] = partial.get("status")
    (where / "solve.json").write_text(json.dumps({unit: result}, default=float), encoding="utf-8")
    for leftover in (odb, *(where / f"{unit}{suffix}" for suffix in (".mdl", ".stt", ".prt", ".res", ".sim", ".023", ".abq", ".pac", ".sel"))):
        if leftover.is_file():
            leftover.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
