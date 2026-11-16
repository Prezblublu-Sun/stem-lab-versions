"""【自由】fea.run 的运行设定：它的声明。只管怎么跑（排队、超时、归档放在哪），不影响算出来的数，不进 made_by。

写法见 stemlab/contract/formats/declaration.py。照它写的设定，declaration 里的 of 写 "fea.run"，name 写 "run"；
核心启动时照这份声明核（规则只在契约里）。run.py 读这几项；换一份 run.py，这份声明跟着它换。
声明改了，哈希就变：照旧声明登记的运行设定不再收，要照新的重新登记一份。

测试轮的取值是拆内核以前 run.py 和 export.py 里的默认值（那时写在导出设定里，不写就用它们）。
"""

SOURCE = "拆内核以前 plugins/fea/run.py、export.py 的默认值"

DECLARATION = {
    "name": "run",
    "groups": ["排队", "时限", "归档"],
    "items": [
        {"name": "build_slots", "label": "同时建模的作业数", "group": "排队", "type": "integer",
         "meaning": "同时出柄的模型、建模、后处理的作业最多几个。求解另按机器清单里这台的求解槽排",
         "range": {"min": 1, "max": 64}, "per_point": False, "required": True, "test": 2, "test_source": SOURCE},
        {"name": "build_timeout_s", "label": "出柄的模型、建模、后处理的时限", "group": "时限", "type": "number", "unit": "s",
         "meaning": "一次出柄的模型、建模或后处理最多跑多久，超过就把它结束，这个作业归成出错",
         "range": {"min": 0, "max": 604800, "min_open": True}, "per_point": False, "required": True, "test": 3600,
         "test_source": SOURCE},
        {"name": "solve_timeout_s", "label": "求解的时限", "group": "时限", "type": "number", "unit": "s",
         "meaning": "一次求解最多跑多久。有限元包建模时在 solve 里给了 timeout_s 的，以它给的为准",
         "range": {"min": 0, "max": 604800, "min_open": True}, "per_point": False, "required": True, "test": 21600,
         "test_source": SOURCE},
        {"name": "derive_timeout_s", "label": "算推导量的时限", "group": "时限", "type": "number", "unit": "s",
         "meaning": "算一次推导量最多等多久，超过就算没算出来，这个作业归成出错",
         "range": {"min": 0, "max": 86400, "min_open": True}, "per_point": False, "required": True, "test": 600,
         "test_source": SOURCE},
        {"name": "archive_root", "label": "归档放在哪", "group": "归档", "type": "text",
         "meaning": "作业留下的文件复制到哪个文件夹下（再按实验分）。不写就放在这个实验自己的 work/archive/ 下",
         "per_point": False, "required": False, "test": None, "test_source": SOURCE},
    ],
}
