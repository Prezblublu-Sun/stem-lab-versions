"""界面和仪表盘整个换一份写法，别的块的测试照过。这是蓝图给“操作台界面和仪表盘”定的第二条验收。

这里有两套替身：desk_ui/ 顶替 stemlab/desk/ui/，board/ 顶替 stemlab/board/。它们是另一种写法——命令是另一套名字，
打印的是 JSON，页面是另一个样子、写的请求头也换了名字——只留着两样：蓝图定的文件名，和守边界的测试要的那几样约定
（见 tests/guard/test_readonly.py 开头）。

test_swap.py 把仓库抄一份，把那两个文件夹换成替身，在拷贝里把 tests/ 下固定的测试整个跑一遍。要几分钟，所以平时的检查不跑：

    python -m pytest tests/swap -m swap
"""
