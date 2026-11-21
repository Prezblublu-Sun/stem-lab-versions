"""V2A 报告的 plotstyle 覆盖：登记表、配置、报告目录都指到 v2，不改 v1 文件。任何 V2A 报告脚本先 import 本模块。

Linux 上没有 Arial：字体回退到度量兼容的 Liberation Sans（用户级安装在 ~/.local/share/fonts），并关掉找字体的告警。
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
os.environ["MOBO_SPEC"] = str(HERE / "reports" / "spec.yaml")
os.environ["MOBO_CONFIG"] = str(HERE / "config_v2a.yaml")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import plotstyle as ps  # noqa: E402

ps.REPORTS = HERE / "reports"
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
ps.plt.rcParams["font.family"] = ["Arial", "Liberation Sans", "Microsoft YaHei", "DejaVu Sans"]
