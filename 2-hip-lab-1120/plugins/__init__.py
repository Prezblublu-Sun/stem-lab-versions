"""四个插件：八种实验类型具体怎么算。

插件只 import stemlab.hooks 这个门面，互不相用。每个插件里少数文件是冻结的（别人依赖的格式和规则），
其余自由，由测试守着。要用 remote 时写 from stemlab import hooks，再用 hooks.remote。
"""
