"""坏插件在源码里犯的事。这个文件从不被运行：它只给源码扫描和依赖规则看，看它们报不报、报的是哪一行。

下面每一处越界后面的注释写着它在第几行，测试照着这个行号核对。
"""
from stemlab.hooks import handle                                    # 第 5 行：import 挂点的子模块
from stemlab.hooks.publish import publish                           # 第 6 行：import 挂点的子模块
from stemlab.registry import register                               # 第 7 行：绕过挂点直接用登记


def peek(experiment):
    with open("data/experiments/" + experiment + "/record.jsonl", "ab") as record:     # 第 11 行：直接碰 data/ 和链文件
        record.write(b"{}\n")
    return open("H:/projects/Hip-lab/data/registry/register.jsonl").read()              # 第 13 行


def sneak(folder):
    return register.register_output, publish, handle, folder        # 第 17 行：只许 publish.py 叫的函数
