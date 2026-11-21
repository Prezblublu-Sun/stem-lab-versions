"""两台机器对得上。要连上机器清单里的 worker（Linux 那台）才能跑，所以平时的检查不跑它：

    python -m pytest tests/cross -m cross

在远端只动 /tmp 下一个这次测试自己建的文件夹，测完删掉。连不上就跳过。
"""
