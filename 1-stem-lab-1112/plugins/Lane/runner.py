"""Lane 的运行器：在一个单独的进程里照着跑一份策略。

    python runner.py <这一次运行的文件夹>

读文件夹里的 job.json，固定随机种子，叫策略的 select(inputs)，把结果写成 done.json。
策略出任何错（包括自己退出）都写进 done.json，不往外抛。
文件夹里出现一个叫 stop 的文件时，这个进程自己退出。

这个文件不 import stemlab，也不认识实验记录。约定见同文件夹的 说明.md。
"""
import importlib.util
import json
import os
import random
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fix_seed(seed: int) -> None:
    """把已经装进来的随机数来源都固定住。没装进来的不去装。"""
    random.seed(seed)
    numpy = sys.modules.get("numpy")
    if numpy is not None:
        numpy.random.seed(seed)
    torch = sys.modules.get("torch")
    if torch is not None:
        torch.manual_seed(seed)


def plain(obj):
    """策略返回的东西里不是 JSON 的几种：路径；numpy 的数和数组。别的不认。"""
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "tolist"):
        return obj.tolist()
    raise TypeError(f"{type(obj).__name__} 存不成 JSON")


def packages() -> dict:
    """策略实际装进来的包和版本（标准库不算）。"""
    found = {}
    for name, module in sorted(sys.modules.items()):
        if "." in name or name in sys.stdlib_module_names or name.startswith("_"):
            continue
        version = getattr(module, "__version__", None)
        if isinstance(version, str):
            found[name] = version
    return found


def watch_stop(flag: Path) -> None:
    while not flag.exists():
        time.sleep(0.3)
    os._exit(3)


def run(job: dict) -> list:
    entry, seed = Path(job["entry"]), job["seed"]
    inputs = {}
    for name, item in job["inputs"].items():
        if item is None:
            inputs[name] = None
        elif "file" in item:
            inputs[name] = Path(item["file"])
        else:
            inputs[name] = item["value"]

    sys.path.insert(0, str(entry.parent))  # 策略可以 import 自己文件夹里的别的文件
    fix_seed(seed)
    spec = importlib.util.spec_from_file_location("lane_strategy", entry)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lane_strategy"] = module
    spec.loader.exec_module(module)
    select = getattr(module, "select", None)
    if not callable(select):
        raise RuntimeError("策略文件里没有叫 select 的函数")
    fix_seed(seed)  # 策略自己装进来的 numpy、torch 这时才固定得到
    returned = select(inputs)
    try:
        text = json.dumps(returned, ensure_ascii=False, allow_nan=False, default=plain)
    except (TypeError, ValueError) as err:
        raise RuntimeError(f"select 返回的东西存不成 JSON：{err}") from err
    return json.loads(text)


def main(run_dir: Path) -> int:
    if sys.path and Path(sys.path[0]).resolve() == HERE:
        sys.path.pop(0)  # 不让策略 import 到插件自己的文件
    threading.Thread(target=watch_stop, args=(run_dir / "stop",), daemon=True).start()
    began = time.time()
    try:
        job = json.loads((run_dir / "job.json").read_text(encoding="utf-8"))
        done = {"ok": True, "returned": run(job)}
    except BaseException as err:  # 策略出什么错都算数，连 sys.exit 也是
        done = {"ok": False, "error": f"{type(err).__name__}: {err}", "raw": traceback.format_exc()}
    done["seconds"] = round(time.time() - began, 3)
    done["packages"] = packages()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    tmp = run_dir / "done.json.tmp"
    tmp.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, run_dir / "done.json")
    return 0 if done["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
