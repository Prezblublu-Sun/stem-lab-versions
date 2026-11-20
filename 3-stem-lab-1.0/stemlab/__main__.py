"""python -m stemlab            开页面（加 --open 顺手打开浏览器）
python -m stemlab --watch N  看护进程：页面服务启动实验时自己起它，不用手敲。"""
import argparse
import os
import sys
import webbrowser

from . import runs, web


def main():
    p = argparse.ArgumentParser(prog="python -m stemlab", description="stem-lab：一个操作台加一个仪表盘")
    p.add_argument("--data", default=os.path.join(os.path.dirname(runs.SYSTEM), "data"),
                   help="数据放哪：账本、做法的留底、每个实验的目录（默认是仓库里的 data/）")
    p.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    p.add_argument("--open", action="store_true", help="开好以后打开浏览器")
    p.add_argument("--watch", type=int, help=argparse.SUPPRESS)
    a = p.parse_args()
    data = os.path.abspath(a.data)
    if a.watch:
        return runs.watch(data, a.watch)
    sys.stdout.reconfigure(errors="replace")
    os.makedirs(data, exist_ok=True)
    try:
        srv = web.make_server(data, a.port)
    except OSError as err:
        sys.exit(f"端口 {a.port} 开不了（可能已经开着一个 stem-lab）：{err}\n换一个端口：python -m stemlab --port 8766")
    url = f"http://127.0.0.1:{a.port}/"
    print(f"stem-lab 开好了：{url}\n数据在：{data}")
    if not data.isascii():
        print("提醒：数据目录的路径里有非 ASCII 字符，以后 Abaqus 在里面跑会认不得。")
    print("关掉这个窗口（或按 Ctrl+C）就关了页面；在跑的实验不受影响。", flush=True)
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


main()
