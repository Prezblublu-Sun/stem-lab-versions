# stem-lab

股骨柄实验系统在新地址的重建。系统是一个操作台加一个仪表盘。
现在有：地基（实验记录、插件的挂点）、操作台（命令行和网页两种用法，带定时值守）、只读的仪表盘、一个示范插件。
真实的插件（重建、FEA、代理、优化各种实际操作）都还没有。

旧系统（`mobo_toy`、`ml3406`、`db3406`、Linux 主机）和这里没有任何连接。

## 里面有什么

| 位置 | 是什么 |
|---|---|
| `stemlab/record.py` | 地基。一个实验一个文件夹，里面的 `record.jsonl` 只追加，是唯一的事实。九项内容都由它算出来 |
| `stemlab/plugins.py` | 挂点。一个插件要报的四样：名字版本类别、要哪几项设置、怎么启动停止报任务状态、产出什么 |
| `stemlab/console.py` | 操作台，命令行用法。操作实验并把操作记下来；看实验只读记录 |
| `stemlab/console_web.py`、`console.html` | 操作台，网页用法。做的每件事都经过 `console.py`，自己不碰记录 |
| `stemlab/watch.py` | 定时值守。隔一会儿叫一次运行中实验的插件报任务状态 |
| `stemlab/dashboard.py`、`dashboard.html` | 仪表盘。只读实验记录和机器信息，给一个本机网页 |
| `stemlab/machines.py` | 机器信息的采集：CPU、内存、GPU、磁盘 |
| `machines.json` | 要看哪几台机器。不进 git，样子见 `machines.example.json` |
| `plugins/demo/` | 示范插件。什么都不算，只用来走通地基 |
| `experiments/` | 实验记录和产出。用的时候才出现，不进 git |
| `tests/` | 地基的测试 |
| `docs/实验记录格式.md` | 一个实验记什么，以及定下来的几条规定 |

地基的三个文件不认识任何具体的插件，也不认识类别。插件之间互不调用，
一个的产出给另一个当设置，只经过实验记录。

## 怎么用

在本文件夹里运行。命令有英文和中文两种写法，是同一个。

```bash
PYTHONUTF8=1 python -m stemlab plugins
```

```bash
PYTHONUTF8=1 python -m stemlab new demo --note "想做什么" --tag 试跑
```

```bash
PYTHONUTF8=1 python -m stemlab set E0001 点 --value '["p1","p2"]' --source "手填"
```

```bash
PYTHONUTF8=1 python -m stemlab start E0001
```

```bash
PYTHONUTF8=1 python -m stemlab refresh
```

```bash
PYTHONUTF8=1 python -m stemlab show E0001
```

| 命令 | 中文 | 做什么 |
|---|---|---|
| `plugins` | `插件` | 装着哪些插件，各要什么设置、产出什么 |
| `new 插件名` | `新建` | 新建一个实验，给出编号 |
| `set 编号 设置名` | `设置` | 启动前填一项设置。内容四选一：`--value` 一个值；`--file` 复制原文；`--ref` 只记位置和哈希；`--from-exp 编号 --output 产出名` 用另一个实验的产出 |
| `start` `pause` `resume` `stop` `retry` | `启动` `暂停` `继续` `停止` `重试` | 操作。每次记一条 |
| `refresh [编号]` | `刷新` | 叫插件看一眼任务走到哪了。不给编号就看所有运行中的 |
| `show 编号` | `看` | 一个实验的九项 |
| `list` | `列表` | 所有实验，一行一个 |
| `note` `tag` | `备注` `标签` | 随时可以加 |
| `check [编号]` | `核对` | 核对记录有没有被改过 |
| `watch` | `值守` | 定时值守，见下 |

`--home 文件夹` 可以把 `experiments` 和 `plugins` 换到别处，写在命令名前面。

## 网页操作台

```bash
PYTHONUTF8=1 python -m stemlab.console_web
```

然后打开 http://127.0.0.1:8792/ 。能做的和命令行一样：

- 看每个插件报的四样
- 新建实验；按插件报的设置项填设置（一个值、复制文件、只记位置、另一个实验的产出），写来路
- 启动、暂停、继续、停止、重试；现在不能做的按钮是灰的
- 看一个实验的九项，重点是实际设置；加备注、加减标签
- 核对记录
- 重新读插件（插件文件夹里加了、拔了、改了插件之后点一下）

网页操作台能改东西，所以只开在本机，没有换地址的开关；改东西的请求要带一个专门的请求头，别的网页发不出来。
`--port` 换端口，`--home` 换文件夹，`--every` 换值守的间隔，`--no-watch` 不开值守。

## 定时值守

任务状态要有人叫插件去看才会更新。值守就是隔一会儿（默认 15 秒）叫一次所有运行中实验的插件报任务状态。
它放在操作台这一边，两种开法：

- 网页操作台开着的时候，值守跟着开着。页面顶上显示上一次什么时候看的、看了哪些实验。
- 不开网页时：`PYTHONUTF8=1 python -m stemlab watch`（`--every 秒数`，按 Ctrl+C 停）。

几条：

- 值守只看运行中的实验。没启动的、暂停的、停止的、结束的不动。
- 一个 home 同一时刻只有一处在值守。第二处会等着，第一处退出后自己接上。
- 同一个实验一次只让一处动：网页、命令行、值守同时动它时，后到的等着（值守不等，这一次跳过）。
- 一个实验的插件出错或记录读不了，记下来，不拦别的实验。

## 仪表盘

```bash
PYTHONUTF8=1 python -m stemlab.dashboard
```

然后打开 http://127.0.0.1:8791/ 。网页每 5 秒自己更新一次，显示：

- 机器：每台的 CPU、内存、GPU 占用和显存、磁盘
- 进行中的实验：每个任务走到哪
- 刚结束的、问题、还没启动的

仪表盘只读。它不叫任何插件，不往任何地方写；记录没变就不重读。
`--port` 换端口，`--home` 换文件夹，`--host` 默认只在本机能打开。

机器写在 `machines.json` 里，两种：

| kind | 怎么读 |
|---|---|
| `本机` | 直接读系统；GPU 起一个一直开着的 `nvidia-smi` |
| `ssh` | 开一条 ssh 长连接，循环跑在那一头，每 5 秒打印一组数。`ssh` 一栏写完整的连接命令 |

送到远端跑的只有这几样，都是读：`nproc`、`head -1 /proc/stat`、读 `/proc/meminfo`、
`nvidia-smi --query-gpu=…`、`df -Pk`。仪表盘关掉，连接断开，那一头的循环跟着退出。

## 几条规定

- 设置在启动时存定。启动后不能改，要改就新建一个实验。
- 任务状态只有五种：排队、运行、完成、失败、停止。插件自己的阶段名另写。
- 出问题是正常的。任务失败、插件报错都记成问题，不拦别的任务和别的实验。
- 仪表盘不会让任务往前走。任务状态在操作台叫 `refresh` 的时候、或值守看的时候才更新。

## 加一个插件

在 `plugins/` 下建一个文件夹，里面放 `plugin.py`，照 `plugins/demo/plugin.py` 的样子填四样，
文件末尾留一个 `PLUGIN = 你的类()`。地基和别的插件都不用改。

## 测试

```bash
PYTHONUTF8=1 python -m pytest tests -q -p no:cacheprovider
```

| 文件 | 测什么 |
|---|---|
| `tests/test_base.py` | 地基和命令行操作台 |
| `tests/test_dashboard.py` | 仪表盘和机器信息 |
| `tests/test_watch.py` | 定时值守；一个实验一次只让一处动 |
| `tests/test_console_web.py` | 网页操作台；操作台、值守、仪表盘、地基连起来的整体测试 |

测试都用临时文件夹当 home，不碰正式的 `experiments/`。
