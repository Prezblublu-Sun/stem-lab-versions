"""属性测试共用的：Hypothesis 的两套设置，和几种常用的生成办法。

属性测试不写具体的用例，写“永远成立的话”，由 Hypothesis 生成成千上万种输入去试；找到反例，就自动缩成最短的一个再报出来。
文件名以 _properties.py 结尾的测试都是这一种。

两套设置，用环境变量 STEMLAB_HYPOTHESIS 选：
    check     平时的检查（默认）。每条试的是固定的一批例子（derandomize），同一份代码每次跑结果都一样，不会今天过、明天不过
    explore   想多找一找的时候：每次换一批随机的例子，多试很多。找到反例会印出一串能重现它的字符（@reproduce_failure）
              PowerShell：$env:STEMLAB_HYPOTHESIS='explore'; python -m pytest tests -k properties
两套都不往盘上存例子（database=None），所以仓库里不会多出 .hypothesis/。

还没做到的目标写成 xfail(strict=True) 的测试，原因里写着是《修改目标》的哪一条：现在它不过是预料之中的；
改好之后它会过，strict 让这时候整个检查不过，提醒把这个标记去掉。
"""
from __future__ import annotations

import os

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

settings.register_profile("check", max_examples=200, derandomize=True, database=None, deadline=None, print_blob=True)
settings.register_profile("explore", max_examples=5000, derandomize=False, database=None, deadline=None, print_blob=True,
                          suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("STEMLAB_HYPOTHESIS", "check"))

# JSON 写得出的字符串：不含单独的代理码位（它们编不成 UTF-8）
TEXT = st.text(st.characters(exclude_categories=("Cs",)), max_size=12)
SCALARS = (st.none() | st.booleans() | st.integers(-(2 ** 63), 2 ** 63)
           | st.floats(allow_nan=False, allow_infinity=False) | TEXT)
# 任意的 JSON 值：标量，或者套几层的列表和对象
JSON = st.recursive(SCALARS, lambda inner: st.lists(inner, max_size=4) | st.dictionaries(TEXT, inner, max_size=4), max_leaves=12)
# 链上一条的内容（链自己填的 seq、prev、this 除外）
BODIES = st.dictionaries(TEXT.filter(lambda key: key not in ("seq", "prev", "this")), JSON, max_size=5)
