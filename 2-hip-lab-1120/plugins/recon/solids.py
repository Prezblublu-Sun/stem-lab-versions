"""【自由】转成 FEA 要的两个实体。

CAD 骨源的两个实体本来就是 FEA 要的样子：原样用，一个字节不动。这样内核认实体认的是文件的哈希，
重建前后是同一个文件，对得上。CT 骨源要从表面重建出实体，1.0 不做。
"""
from __future__ import annotations

from pathlib import Path

NAMES = ("cortical", "cancellous")


def from_cad(folder: Path, files: dict) -> dict:
    """CAD 骨源里的两个实体文件：{"cortical": 文件, "cancellous": 文件}。"""
    found = {name: Path(folder) / str(files[name]) for name in NAMES}
    missing = [str(path.name) for path in found.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"骨源里没有这几个文件：{missing}")
    if found["cortical"].resolve() == found["cancellous"].resolve():
        raise ValueError("皮质和松质不能是同一个文件")
    return found
