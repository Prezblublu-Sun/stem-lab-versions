"""契约：所有定义和纯函数。

读完这一个包，就知道任何一条历史数据怎么读、任何一个操作此刻能不能做。
只用标准库，不 import 别的块。

    layout.py       data/ 的布局和编号的写法
    kinds.py        十六种种类；登记的一条记录长什么样
    origin.py       来路的两种形状
    hashing.py      哈希：字节、文件、JSON 值、文件夹、输入指纹
    chain.py        只追加的哈希链，两条链共用
    entries.py      实验记录的十二种条目；每轮必记的来历
    states.py       状态、状态表、由记录算出现状
    plugin_api.py   插件接口：类型、四个动作、handle
    versions.py     每种格式现在的版本；旧版本怎么转成现在的形状
    machines.py     机器清单的格式
    formats/        文件夹形态的东西：共用的清单，和各自的格式

碰盘的只有这几处，别的都是纯函数：
    hashing.hash_file、hashing.list_tree、hashing.hash_tree          读
    formats.manifest.read_manifest、formats.manifest.check_format   读
    formats.points.read_points                                      读
    formats.manifest.write_manifest、formats.points.write_points    写调用方给的文件夹
"""


class Refused(Exception):
    """被拒：这个操作现在不能做，或者这样东西登记不上、这一条记不上。

    带着说给人看的原因。被拒的时候什么都没有写下。各块都用这一个，界面只用认它。
    """
