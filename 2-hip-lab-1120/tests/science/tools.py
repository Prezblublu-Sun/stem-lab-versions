"""科学验收共用的小工具：旧系统的文件在哪、跑求解命令、从旧数据库里取一行。都只读旧系统。"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

BONE_ID = "sawbone3406"
LEGACY = Path(os.environ.get("STEMLAB_LEGACY", r"H:\projects\Femoral implant generation\sandbox\mobo_toy"))
LEGACY_DB = Path(os.environ.get("STEMLAB_LEGACY_DB", r"H:\projects\Femoral implant generation\db3406\v0.14\scalars.csv"))
ABAQUS = Path(os.environ.get("STEMLAB_ABAQUS", r"D:\SIMULIA\Commands\abq2025.bat"))
STEPS = {"cortical": "3406R_cortical.STEP", "cancellous": "3406R_cancellous_v2.STEP"}
ENV = {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def solve(built: dict, where: Path) -> None:
    """跑内核给的求解命令，等它跑完。"""
    command = [sys.executable if part == "{python}" else part for part in built["solve"]["command"]]
    done = subprocess.run(command, cwd=where, capture_output=True, timeout=built["solve"]["timeout_s"], env=dict(os.environ, **ENV))
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]


def legacy_rows(wanted=None) -> list[dict]:
    """旧数据库的各行（只读）。wanted 给了作业编号的一部分，就只要那一行。找不到就跳过。"""
    if not LEGACY_DB.is_file():
        pytest.skip(f"找不到旧数据库（{LEGACY_DB}）。换地方了就设 STEMLAB_LEGACY_DB")
    with open(LEGACY_DB, newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream) if wanted is None or wanted in row["job_id"]]
    if not rows:
        pytest.skip(f"旧数据库里没有 {wanted} 这一行")
    return rows
