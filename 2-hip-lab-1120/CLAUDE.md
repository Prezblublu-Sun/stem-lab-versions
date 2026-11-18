# CLAUDE.md

stem-lab 1.0：管实验的系统。设计的依据是 `docs/蓝图.md`，拿不准一段代码该不该写、该放哪，回到蓝图的五条原则判断。
现在实际怎么搭（固定什么、导入什么，一件事从目标到提交怎么走，用什么测试证明，文档在哪）见 `docs/搭建方法.md`。
蓝图里“以后要你给”的四样是怎么定的，见 `docs/四样的决定.md`。

## 能写的
- plugins/*/ 里没标冻结的文件，和 plugins/*/tests/
- stemlab/desk/ui/、stemlab/board/，和 tests_free/：界面和仪表盘的测试，另有自由代码里要经真的核心走一遍的测试
  （`tests_free/recon/`：CT 骨源经重建插件；`tests_free/strategies/`：选点策略）
- external/：把外面的东西做成能登记的包或数据的做法（内核包、柄空间包、推导量定义、旧数据库的转换、选点策略）。
  external/ 自己不在检查的范围里；选点策略的测试放在 tests_free/strategies/，M1 柄空间包的放在 tests_free/stem_space/，所以跟着检查跑。
  选点的算法有哪几种、怎么用，见 `docs/优化算法.md`
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
- 场的代理放在哪、能学哪种场、还有哪几件事没定，见 `docs/场的代理.md`。
- 数据、候选池、预测器、一份预测的清单记着是哪个内核算的（made_by），不同内核的数不放在一起用：见 `docs/不同内核的数据.md`。
  新写的、会产出这几样东西的代码要照样记上。
- 外部审查的原文和逐条核对的结果在 `docs/审查/`：哪些成立、哪些已改、哪些等你定。
- 发布第一版还要做什么，见 `docs/发布第一版.md`。科学验收只评估、不挡发布（2026-11-15 定的）。
- 固定什么、导入什么：冻结的部分管住记账的规矩、格式、防止看了结果再改的评判规则、每种实验的流程骨架，和登记后的模型版本。
  经常要调的设计量和设定（设计、条件和初始条件、网格、求解、接触和绑定、分析步、哪根骨、训练和优化的设置）作为登记的设定导入，
  照模型或实验类型声明的项核验，不写死在代码里，也不为了和原项目一致写死；原项目只当参照。
  不是一概不绑：该固定的照样固定。现有的问题和目标见 `docs/审查/2026-11-15-冻结的代码不绑来源.md`。
- 设计空间放在包里（2026-11-15 定的）：FEA 只有一套流程；管柄的形状和放置策略的包叫“柄空间”，换设计空间就发布一个新的柄空间包。
  原来的“内核”拆成柄空间包（柄的形状和放置）和有限元包（照 Abaqus 的设定建模、求解、后处理）。
  FEA 有两种实验（2026-11-16 定）：`fea.run` 收柄空间包（不填就是无植入物）加有限元包，几份设定都照包的声明写，
  运行设定照 `plugins/fea/running.py` 的声明；`fea.reference` 是参照包那条，输入表和拆内核以前的 `fea.run` 一样，只用来对照。
  拆到哪一步、还剩什么，见 `docs/拆内核.md`。
  有限元的做法照 Abaqus 的设定；默认值随包放入，只用来跑测试轮。
  分层和四种实验的重新设计见 `docs/核心、插件和模型包.md`，骨模型的写法见 `docs/骨模型的写法.md`，
  设定的声明和包的清单的格式见 `docs/设定的声明和包的清单.md`（都是草案，等你看）。
- 验证试验怎么设计见 `docs/验证实验.md`，验证代码怎么搭见 `docs/验证代码.md`（还没写）。验证用自己的账（`H:\stemlab-validation\`），
  不碰仓库的 `data\`；远端作业根目录和 FEA 归档也用验证自己的。
- CT 重建（`plugins/recon/ct.py`、`solids.py`，说明在 `docs/CT重建.md`）要 SimpleITK、VTK、pymeshlab 三个库。
  它们在 `pyproject.toml` 的 `recon` 这一组里，只在操作台这台装；worker 用 `uv sync --no-default-groups`，不装。
  - 代码里不写 `import vtk`（那会把一百多个模块连同渲染的全装进来），用 `ct.toolkit()`，它只装用得到的八个模块。
  - 这台 Windows 上有 360。它的实时防护（360rp.exe）会在这些库装完或机器重启后第一次被加载时，把加载过的 DLL 打开并占住
    （连 gmsh 的也会），占着的时候 Python 加载它们会报“DLL load failed … 另一个程序正在使用此文件”或 WinError 32，
    `uv sync` 往缓存里改名也会报“拒绝访问”。2026-11-14 它一占几十分钟不放，直到重启；11-15 重启后占了几分钟，放开之后再加载就不占了。
    碰到了先等几分钟再跑一遍，别连着重试（每试一次它多占一批）。是谁占的可以用 Windows 的重启管理器查实。
    不要去动 360 的设置，也不要绕开它：告诉用户，由用户决定（比如把 `.venv` 加进它的信任区）。
    2026-11-14 这三个库是用 `pip install --no-deps` 照锁里的版本装进 `.venv` 的，之后 `uv sync --inexact --frozen` 认为环境和锁一致。
  - 要这三个库的测试在库加载不了时会跳过并写明原因：看到跳过，不等于那部分验过了。
  - 对当时产物的回归（要 `H:\hip resource` 和旧的 CT 项目，只读）：`python -m pytest plugins/recon/tests/test_ct_reference.py -m science -s`。
- 运行 Python 带 UTF-8 开关：PowerShell 写 `$env:PYTHONUTF8='1'`，Bash 写 `PYTHONUTF8=1`。
- 操作台的命令行：`python -m stemlab.desk <命令>`，`python -m stemlab.desk -h` 看有哪些命令。
  操作台的网页：`python -m stemlab.desk web`（只有本机打得开）；仪表盘：`python -m stemlab.board`。
- 平时的检查不跑这三组，要用的时候单独跑：
  - 跨机测试，要连得上机器清单里的 worker：`python -m pytest tests/cross -m cross`。
    它只动 worker 上 `/tmp` 下自己建的临时文件夹，测完删掉。
  - 科学验收，要旧系统的文件（只读）和 Abaqus：`python -m pytest tests/science -m science`。
  - 界面和仪表盘换一份写法、固定的测试照过，要几分钟：`python -m pytest tests/swap -m swap`。改了界面的约定就跑一遍。
- 三样测试工具在开发依赖里（worker 不装）；每条目标用哪种测试来证明，见 `docs/审查/2026-11-15-修改目标.md`：
  - 属性测试（Hypothesis）：文件名以 `_properties.py` 结尾，共用的设置在 `tests/properties.py`。平时的检查每次试同一批例子；
    要多找就设 `STEMLAB_HYPOTHESIS=explore` 再跑。还没做到的目标写成 `xfail(strict=True)`，原因里写《修改目标》的编号；
    改好之后它会过、检查跟着不过，这时把标记去掉。
  - 快检查（ruff，只开最基本的几类）：`.venv\Scripts\ruff.exe check stemlab plugins tests tests_free external worker_env`，几秒钟。
    不在完整检查里；改的时候先跑它，完整检查仍是“做完”的标准。
  - 变异测试（pytest-gremlins，不改盘上的文件；mutmut 在 Windows 上要 WSL，所以不用它）：
    `python -m pytest <几个快测试> --gremlins --gremlin-targets=<要改坏的文件>`。只对契约和核心里定规则的文件、配它们的快测试跑，
    几十秒到几分钟；全套检查太慢，不拿来跑变异。不进平时的检查。
- 认得命令叫什么、页面上有什么的测试放在 tests_free/；tests/ 里固定的测试不靠界面和仪表盘里面的东西
  （`tests/guard/test_ui_is_free.py` 守着），它们才可以整个重写。
- 提交前钩子在 `.githooks/`，每个克隆启用一次：`git config core.hooksPath .githooks`。
- 插件里只 import `stemlab.hooks` 这个门面。要用 remote 时写 `from stemlab import hooks`，再用 `hooks.remote`；
  不要 `from stemlab.hooks import remote`，那是 import 挂点的子模块，依赖规则会报。
- 插件的字符串里不要写 `data/` 开头的路径（扫描会当成是在碰账本）；包里的 `data` 文件夹用拼出来的路径。
- `gmsh.initialize()` 会把所在进程的 PATH 截短。在会再起别的程序的进程里用 gmsh，用完把 `os.environ["PATH"]` 放回去。
- 旧系统（`H:\projects\Femoral implant generation`）只读：不改它的文件，不在它里面起任何进程。
