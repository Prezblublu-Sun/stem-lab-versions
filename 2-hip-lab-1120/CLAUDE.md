# CLAUDE.md

stem-lab 1.0：管实验的系统。设计的依据是 `docs/蓝图.md`，拿不准一段代码该不该写、该放哪，回到蓝图的五条原则判断。
蓝图里“以后要你给”的四样是怎么定的，见 `docs/四样的决定.md`。

## 能写的
- plugins/*/ 里没标冻结的文件，和 plugins/*/tests/
- stemlab/desk/ui/、stemlab/board/，和它们的测试 tests_free/
- external/：把外面的东西做成能登记的包或数据的做法（内核包、推导量定义、旧数据库的转换）。不在检查的范围里
- worker_env/：把 worker 的环境照锁装出来的做法。不在检查的范围里

## 只能读，不能改
- stemlab/contract/、registry/、experiments/、hooks/、desk/core/、desk/__main__.py
- plugins/*/ 里标了冻结的文件
- tests/、conftest.py、FROZEN、.importlinter、.gitattributes、machines.json

哪些文件标了冻结，以 `FROZEN` 清单里列的为准。科学验收的线在 `tests/science/lines.py`，也在只能读的范围里：线由人定。

## 每次改完
- 跑 python -m stemlab.desk.core.check。不过就不算做完
- 不为了让检查通过去改测试、清单或规则。过不了就停下来说明原因

## 环境
- Python 用仓库里的 `.venv`（Windows：`.venv\Scripts\python.exe`），从仓库根目录运行。
  环境由 `uv.lock` 装出来：`.venv\Scripts\uv.exe sync --inexact`。
- worker 那台的环境由同一份 `uv.lock` 装出来，放在机器清单里它的 `python` 指的地方（`<根>/venv/bin/python`）：
  `python worker_env/sync.py` 装，加 `--check` 只核对、不装。不用 sudo，只动 `<根>/` 那一个文件夹。
  改了 `uv.lock`，两边都要重装。
- 运行 Python 带 UTF-8 开关：PowerShell 写 `$env:PYTHONUTF8='1'`，Bash 写 `PYTHONUTF8=1`。
- 操作台的命令行：`python -m stemlab.desk <命令>`，`python -m stemlab.desk -h` 看有哪些命令。
  操作台的网页：`python -m stemlab.desk web`（只有本机打得开）；仪表盘：`python -m stemlab.board`。
- 平时的检查不跑这三组，要用的时候单独跑：
  - 跨机测试，要连得上机器清单里的 worker：`python -m pytest tests/cross -m cross`。
    它只动 worker 上 `/tmp` 下自己建的临时文件夹，测完删掉。
  - 科学验收，要旧系统的文件（只读）和 Abaqus：`python -m pytest tests/science -m science`。
  - 界面和仪表盘换一份写法、固定的测试照过，要几分钟：`python -m pytest tests/swap -m swap`。改了界面的约定就跑一遍。
- 认得命令叫什么、页面上有什么的测试放在 tests_free/；tests/ 里固定的测试不靠界面和仪表盘里面的东西
  （`tests/guard/test_ui_is_free.py` 守着），它们才可以整个重写。
- 提交前钩子在 `.githooks/`，每个克隆启用一次：`git config core.hooksPath .githooks`。
- 插件里只 import `stemlab.hooks` 这个门面。要用 remote 时写 `from stemlab import hooks`，再用 `hooks.remote`；
  不要 `from stemlab.hooks import remote`，那是 import 挂点的子模块，依赖规则会报。
- 插件的字符串里不要写 `data/` 开头的路径（扫描会当成是在碰账本）；包里的 `data` 文件夹用拼出来的路径。
- `gmsh.initialize()` 会把所在进程的 PATH 截短。在会再起别的程序的进程里用 gmsh，用完把 `os.environ["PATH"]` 放回去。
- 旧系统（`H:\projects\Femoral implant generation`）只读：不改它的文件，不在它里面起任何进程。
