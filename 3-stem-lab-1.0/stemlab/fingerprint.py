"""指纹：一个文件或一个文件夹的 SHA-256。

文件夹的指纹 = 把里面每个文件的“相对路径 + 指纹”按路径排好，再算一次 SHA-256。
每个文件各自的指纹也留下来，内容变了就说得出是哪个文件变了。
__pycache__ 和 .pyc 是 Python 自己生成的缓存，不算内容，跳过。
"""
import hashlib
import os


def _file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def of(path):
    """返回 (总指纹, {相对路径: 指纹})。"""
    if os.path.isfile(path):
        h = _file(path)
        return h, {os.path.basename(path): h}
    files = {}
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if not name.endswith(".pyc"):
                full = os.path.join(root, name)
                files[os.path.relpath(full, path).replace(os.sep, "/")] = _file(full)
    listing = "".join(f"{rel}\t{h}\n" for rel, h in sorted(files.items()))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest(), files


def check(path, fp, files):
    """现在的内容和记下时一不一样。一样返回 None；不一样返回一句话，说哪些文件不一样。"""
    if not os.path.exists(path):
        return f"找不到了：{path}"
    now_fp, now_files = of(path)
    if now_fp == fp:
        return None
    changes = [f"{r} 变了" for r in sorted(files) if r in now_files and now_files[r] != files[r]]
    changes += [f"{r} 没了" for r in sorted(files) if r not in now_files]
    changes += [f"{r} 是多出来的" for r in sorted(now_files) if r not in files]
    more = f"……一共 {len(changes)} 处" if len(changes) > 8 else ""
    return "；".join(changes[:8]) + more
