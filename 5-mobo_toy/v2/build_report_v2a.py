"""本机打印 V2A 报告：先从 Linux 取回 v2/reports/V2A_real_femur（图、表、验收），再用 v1 的 report.py（经 psv2 覆盖路径）
生成 Markdown / HTML / PDF。本机不做任何计算，只做 PDF 打印。

    python v2/build_report_v2a.py [--no-fetch]
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import psv2  # noqa: E402,F401
import remote as R  # noqa: E402
import report  # noqa: E402

if __name__ == "__main__":
    if "--no-fetch" not in sys.argv:
        R.fetch("code/v2/reports/V2A_real_femur", HERE / "reports")
    sys.exit(report.build("V2A", pdf=True))
