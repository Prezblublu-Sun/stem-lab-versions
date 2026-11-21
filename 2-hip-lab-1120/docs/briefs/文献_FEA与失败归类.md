# 文献依据简报：失败作业的归类，与 FE 验证的验收标准

日期：2026-11-13
对象：压配无骨水泥短柄 + 复合股骨的自动化隐式接触有限元流水线（Abaqus/Standard），输出供高斯过程代理模型和贝叶斯优化使用。

## 0. 阅读说明

- **【来源】**：数字或说法出自所引文献。第 3 节逐条写明我看到的是全文、摘要，还是别人的转述。
- **【建议】**：我提出的数值或做法，文献没有直接给出，只是有文献可以作参照。
- **【推算】**：我按公式自己算的。
- 核验途径：PubMed 检索工具、CrossRef、arXiv、出版社或机构页面、厂商文档。生物医学类条目的信息取自 PubMed（"根据 PubMed"），DOI 以链接给出。
- 没能核实的内容集中列在第 4 节，正文里凡用到都注明了。
- 检索词只用了通用学术词汇，没有带入任何项目信息。

---

## 1. 决策 1："求解不收敛"和"网格生成失败"归哪一类

### 1.1 建议

| 情形 | 归类 | 结果名 | 条件 |
|---|---|---|---|
| 许可证、磁盘、节点故障、被外部终止 | `retryable` | — | 失败原因在计算环境 |
| 网格器报错 | 先自动换设置重试；都失败后 `conclusion` | `mesh_failed` | 至少 2 档备选网格设置都失败【建议】 |
| 求解不收敛，换数值设置后收敛且通过验收 | `ok` | — | 行内记录用的是哪一档设置 |
| 求解不收敛，各档都失败，有物理失稳的证据 | `conclusion` | `unstable` | 证据条件见规则 3 |
| 求解不收敛，各档都失败，没有物理失稳的证据 | `conclusion`（失败率很低时可留作 `unclear`，见规则 6） | `not_computable` | 至少 3 档不同数值设置都失败【建议】 |
| 日志解析不出原因、错误码无文档、同一输入两次结果不同 | `unclear` | — | — |

要点是两句话：

1. **不收敛首次出现时不定类**，由流水线自动换数值设置重跑；全部失败后才入库，并且按有没有物理失稳证据分成两个结果名。
2. **`mesh_failed` 和 `not_computable` 是"设计点 × 当前数值配置"的性质，不是设计本身的物理性质。** 它们可以进数据集、可以让优化器避开，但不能对外说成"这个设计不可行"。

你提的方案"unclear，复现一次后转 conclusion"，我建议把"复现一次"换成"换数值设置后仍失败"。同一输入原样重跑，隐式求解基本会给出同样的结果，数值故障和物理失稳都能复现，区分不了二者【推理，没有文献直接讨论这一点】。原样重跑仍有一个用处：两次结果不同，说明有不确定性来源，应归 `unclear`。

#### 规则细节

**规则 1：先按失败发生的位置分流。**
- 计算环境原因 → `retryable`。【来源：Dakota 文档把 retry 选项定位于 "transient computing environment issues such as shared disk space, software license access, or networking problems"（A13）；Bussemaker 等写明 hidden constraint 不包括 "temporary problems such as software license availability or network problems"（A7）】
- 几何预检判定放不进髓腔 → `conclusion: no_fit`（你们已定）。这类约束不跑仿真就能判定，应排在仿真之前【来源：A1 §2.3】。建议同时输出一个连续量（最大干涉深度或重叠体积），这样它是可量化的约束，代理模型能学到"差多少"【建议】。
- 错误信息解读不了 → `unclear`。【来源：A1 §2.5，"an error message that cannot be interpreted is equivalent to such a flag and hence should be interpreted as hidden"】

**规则 2：网格失败。** 按固定顺序自动尝试备选设置，至少 2 档【建议】，例如全局种子尺寸 ×0.8、×1.25，或换四面体算法；必要时对切骨几何做极小平移。O'Rourke 的做法是布尔运算失败后把磨锉沿局部 x 轴平移 0.01 mm 再试【来源：B7 第 3 章】。任一档成功就继续求解，行内记录档位。全部失败 → `conclusion: mesh_failed`。

**规则 3：求解不收敛。** 自动走补救梯，至少 3 档不同的数值设置【建议】：
- R1：缩小初始增量和最大增量，放宽回退次数。Abaqus/Standard 默认不收敛时把增量缩到上一次的 25%，同一增量超过 5 次尝试就终止【来源：C1 "Solving Nonlinear Problems"】。
- R2：过盈单独放一个分析步，分多个增量消除，其间不加其他载荷。【来源：C1 "Contact Initialization for General Contact in Abaqus/Standard"，"It is generally recommended that you do not apply other loads while the interference fit is being resolved"】
- R3：接触稳定化。Abaqus 默认让阻尼系数在步内线性降到零【来源：C1 "Generally Applicable Contact Controls"】。结果必须通过 2.5 节的能量检查才算数。
- R4（可选）：接触区加密，或启用曲面平滑。

任一档收敛并通过 2.5 节的全局检查 → `ok`。全部失败后看证据：

物理失稳的证据【建议】：①和②必须同时成立，再加③或④之一。
- ① 过盈步已收敛，失败发生在加载步。
- ② 最后一个收敛增量的载荷比例小于 1。
- ③ 假体位移或界面微动随载荷加速增长，或已超过判废阈值。文献常用的微动阈值是 150 µm【来源：B2 摘要】。
- ④ msg 文件出现 numerical singularity 或 zero pivot 警告且位移很大。【来源：C1 "Common Difficulties…"，"'Numerical singularity' warning messages and very large displacements indicate unconstrained motion in a static analysis"】

成立 → `conclusion: unstable`。不成立（例如失败在过盈步、同一批节点反复开合、单元畸变）→ `conclusion: not_computable`。

**规则 4：数据集和优化怎么用这些行。**
- 响应量的 GP 只用 `ok` 行训练。【来源：A5 摘要，"A surrogate model for the objective function is built using the training set of computable points, only, whereas a probabilistic classification model is built using the union of the computable and non-computable training sets"；A2、A6 做法相同】
- `conclusion` 行不给响应值，不做填补，只作为"可算性"分类器的负例。
- 采集函数用期望改进乘以可行概率，或要求可行概率不低于下限。下限起点取 25%。【来源：A7，"A default value of PoVmin=25% is recommended"，理由是 "to promote sufficient exploration"；加权 EI 的做法见 A4 §1.4】
- 四个结果名分开存。对外陈述时，只有 `no_fit` 和 `unstable` 可以称为"设计不可行"；`mesh_failed` 和 `not_computable` 只能称为"当前流水线算不出"【建议】。

**规则 5：版本作废。** 网格设置、求解设置或代码版本变化后，`mesh_failed` 和 `not_computable` 行降回 `unclear` 并重跑【建议】。

**规则 6：按失败率决定保守还是积极。**【建议】
- 一批作业里 `mesh_failed` + `not_computable` 不超过 2%：`not_computable` 可以不入库，留作 `unclear`。优化器偶尔会重复提议这些点，但浪费很小，换来的是不会把数值故障错标成不可行。
- 2% 到 5%：按规则 4 入库。
- 超过 5%：停下来修模型或网格，不让优化器绕着走。
- 参照：骨科自动化 FE 流水线报道的失败比例在 1% 到 3% 之间【来源，见 1.3】。

**规则 7：定期审计失败是否真是设计点的性质。**【建议，方法出自 A11】 失败行累计 20 到 30 条后，用设计变量训练一个分类器预测"是否失败"，做交叉验证。AUC 达到 0.9 以上，说明失败在设计空间里有结构，归 `conclusion` 站得住；AUC 在 0.6 以下，说明失败与设计变量无关，应退回 `unclear` 排查。Lucas 等报告的是 AUC > 0.96【来源：A11 摘要】；Paja 等指出训练集和验证集的划分对结果影响很大，需要交叉验证【来源：A12，CrossRef 摘要转述】。0.9 和 0.6 这两个界是我定的。

**规则 8：失败时多记信息。**【建议】 记录失败阶段、最后收敛的步时间和载荷比例、回退次数、警告类别和计数、最后一个增量的最大位移增量、接触面积、ALLSD/ALLIE。A1 指出，仿真崩溃而没有标志时 "one has no way of knowing exactly what went wrong"，建模者用标志把原因表达出来，约束就从 hidden 变成 known（§2.4）。

### 1.2 依据

#### (a) 仿真优化和代理模型文献

1. **"算不出来"是一类独立的约束，有固定术语。** A1 的 QRAK 分类把约束分成可量化/不可量化、可松弛/不可松弛、先验/仿真、已知/隐藏。hidden constraint 的定义是 "not explicitly known to the solver"，"typically (but not necessarily) appears when the simulations crashes"（§2.4）。同一节写明 "A hidden constraint is not necessarily a bug in the simulator"。
2. **有明确原因的不收敛不算 hidden。** A1 §2.5 把 "A flag indicates that the convergence of some specific and identified numerical method inside the simulation could not converge" 列为 NUSK（不可量化、不可松弛、仿真型、已知）的例子，并说 "These are not hidden constraints since the reason for the violation can be identified"。只有 "The simulation failed to complete and nothing is displayed, or a simple flag is raised or an undocumented error number indicated" 才是 NUSH（hidden）。这支持把原因清楚的不收敛当作一条约束入库，把原因不明的归 `unclear`。
3. **失败点不进目标函数的代理模型，进一个单独的分类器。** A2（技术报告全文）："no information about the objective function can be learned from a run outside the valid set, and one wants to learn the boundaries of valid regions to avoid wasting runs"，用随机森林估计"是否返回有效值"。A5 用可算点建代理、用全部点建分类器。A6 提出分类与回归的联合 GP 模型。A10 用 "evaluability prediction function" 和动态阈值。A4 §1.4 引 Snoek 的学位论文：约束违反来自 "a simulation crashing or failing to terminate" 时，用可行概率加权的期望改进。
4. **文献把求解不收敛和网格失败都算进这一类。** A7 摘要："Evaluations might fail due to non-convergence of underlying solvers or infeasible geometry"。A8 摘要：设计评估 "typically comprising geometry creation, mesh generation and numerical simulation"，"Simple optimization routines tend to stall and require user intervention if a failure occurs at any of these stages"。A5 摘要列了三种原因："an unphysical configuration, an ill-posed problem, or a non-computable problem due to the limitation of numerical solvers"。注意 A5 用的词是 non-computable，没有说成不可行。
5. **文献默认失败是确定性的，临时故障另算。** A7："Hidden constraints are assumed to be deterministic"。A2："Herein we assume that the functional response is deterministic"。Dakota 把四种处置分开：abort、retry（临时环境问题）、recover（返回占位值，适用于 "a failed simulation may indicate a region of the design space to be avoided"）、continuation（适用于 "a failed simulation may be caused by an inadequate initial guess"）（A13）。这四种处置和你们的四类基本对得上，其中 continuation 对应本简报的补救梯。
6. **直接丢弃失败点的代价。** A7 把策略分成 rejection、replacement、prediction 三种。rejection 的缺点："the optimizer might get stuck suggesting the same infill point(s) over and over, because it cannot know that these infill points will fail to evaluate"。A7 的比较结论是预测可行概率的做法最好。
7. **失败能由参数预测，说明它可以是设计点的性质。** A11 摘要：约 8.5% 的气候模式算例 "failed for numerical reasons at combinations of POP2 parameter values"，支持向量机在独立验证集上预测失败，AUC > 0.96。注意作者说的是 numerical reasons：数值原因造成的失败同样可以在参数空间里有稳定的结构。
8. **可行域边界值得多采样。** A3 §4.2："It is sensible to sample heavily on the boundary of the constraint region where the response is quickly changing and local minima are likely to occur"。这是可行概率下限取得低（25%）的另一个理由。A5 摘要也承认方法在 "the feasible domain is a small portion of the design space" 时不占优。

没有找到的：明确讨论"把数值失败错标为不可行会造成多大偏差"的文献。下面两点是我的推论【推理】：
- 把数值故障标为不可行，会在设计空间里挖掉一块可能很好的区域，而且因为优化器不再去那里，错误不会自己纠正。规则 5、6、7 是针对这一点的。
- 反过来，如果失败与响应相关（不稳的假体更容易不收敛），把失败行简单丢掉，剩下的样本会低估不稳定的程度。缺失机制的一般框架见 A14（该文我只核对了题录，没有重读内容）。Viceconti 等的做法是把不稳定算例单独计数报告（B14）。

#### (b) 骨科 FE 研究怎么处理失败算例

大多数论文的摘要不报告失败算例，我能读到全文的只有少数几篇。读到的做法归为三种：

- **换数值设置重试，仍失败就剔除并说明。** O'Rourke 的博士论文（B7，全文）：髋臼杯植入用 Abaqus/Explicit，"if a simulation failed part way through, the time increment was decreased by 1 × 10⁻⁶ s"；第 6 章的 Kriging 训练集里 "a simulation failed due to mesh distortion during cup insertion but the remaining training set of 29 simulations built a surrogate model"。
- **把不稳定当作一种物理结果单独报告。** Viceconti 等（B14，摘要）：蒙特卡罗 1000 多例，"Twenty cases were found macroscopically unstable, due to a combination of unfavourable conditions. The rest of the Monte Carlo sample showed on average a peak micromotion…of 206 ± 159 µm"。不稳定的 20 例没有进均值。
- **在采样阶段就排除放不进去的方案。** Al-Dirini 等（B2、B3，摘要）：算法 "span the plausible surgical envelope of implant positions constrained by the endo-cortical boundary"。B2 "A total of 1952 models were generated and ran"，正好等于 16 根股骨 × 2 种柄 × 61 个方案，摘要没有提到失败。Cilla 等（B26，全文）的短柄参数化研究同样靠预设参数范围："The values were chosen to ensure a clinically admissible shape"，256 个模型，没有报告失败。

#### (c) 不收敛是数值问题还是物理失稳

两种都有文献依据，所以不能一律归 `conclusion`，也不能一律当作数值噪声。

**数值原因的依据：**
- Abaqus 文档列出的接触收敛困难包括：chattering（"If chattering continues, Abaqus/Standard may not be able to find a solution"）、过约束（"Overconstraints often lead to inaccurate solutions or failure to obtain a converged solution"）、接触面网格太粗、增量太大（C1 "Common Difficulties…"）。
- Ovesy 等（B16，摘要）："implicit finite element analysis of implant press-fit faces convergence issues due to contact and highly distorted elements"，他们因此改用显式算法。
- Bernakiewicz 和 Viceconti（B19，摘要）：接触刚度、收敛容差这些参数 "do not have a physical meaning"，其中 "contact stiffness and convergence tolerance, were found to play a crucial role in establishing the accuracy of the finite element results"。
- Nispel 等（B17，全文）的自动化流水线里，637 个椎体中 10 个、600 个椎间盘中 7 个失败。摘要写的是 "failed to converge"，正文查明的原因却是分割掩膜和表面网格缺陷（"self-intersecting faces were found, which led to failing FEM mesh generation"）。这也说明论文里的失败标签不一定可靠，归类要看分阶段的证据。

**物理原因的依据：**
- Abaqus 文档："In static problems rigid body motion occurs when a body is not sufficiently restrained"；没有阻尼时 "Abaqus/Standard may not obtain a converged solution due to an unconstrained rigid body mode"（C1）。靠摩擦和过盈固定的假体，接触不足时正是这种情况。
- Abaqus 文档："Some static problems may become unstable because of severe nonlinearity"；局部失稳问题 "have to be solved either dynamically or with the aid of (artificial) damping"（C1 "Solving Nonlinear Problems"）。
- Gersie 等（B15，摘要）：无骨水泥股骨髁假体，"simulations failed to converge for two specimens due to limited bone-implant contact"，5 个标本中的 2 个。
- Xu 等（B18，摘要）：某一骨折分型的空心钉固定模型不收敛，作者据此得出该分型 "cannulated screws alone provide insufficient fixation strength"。这是把不收敛直接读成物理结论的例子，摘要里没有给出其他佐证。我不建议照这样做。

### 1.3 文献里的失败比例和处置【来源】

| 研究 | 规模 | 失败数或比例 | 处置 | 所见范围 |
|---|---|---|---|---|
| Nispel 2025（B17）脊柱 | 637 椎体，600 椎间盘 | 10（1.6%），7（1.2%） | 剔除；归因于分割和表面网格 | 全文 |
| Viceconti 2006（B14）无骨水泥柄 | 1000 多例蒙特卡罗 | 20 例"宏观不稳定" | 单独计数，不进均值 | 摘要 |
| O'Rourke 2017（B7）髋臼杯 | 一个 Kriging 训练集 | 1 例因网格畸变失败，剩 29 例 | 剔除，用剩下的 29 例建代理 | 学位论文全文 |
| Gersie 2026（B15）股骨髁 | 5 个标本（一种材料模型配置下） | 2 例不收敛 | 作者归因于接触不足 | 摘要 |
| Galloway 2013（B8）胫骨托 | "328 models were successfully implanted and analysed" | 生成总数我没能核实 | — | 摘要 |
| Bah 2015（B1）短柄 | 109 例 CT，75 男 34 女 | 摘要未报告失败 | — | 摘要 |
| Al-Dirini 2019（B2）柄 | 1952 例 | 摘要未报告失败 | 采样受髓腔内皮质边界约束 | 摘要 |
| O'Rourke 2018（B6）髋臼杯 | 103 例 | 摘要未报告失败 | — | 摘要 |
| Bryan 2009（B9）股骨 | 1000 例 | 摘要未报告失败；"able to be used directly by the FE solver without remeshing" | — | 摘要 |
| Bryan 2012（B11）表面置换 | 400 例 | 摘要未报告失败 | — | 摘要 |
| Lucas 2013（A11）气候模式 | — | 约 8.5% | 用分类器预测 | 摘要 |
| Bussemaker 2024（A7）航空架构 | — | 引用他人：机翼设计最高 60%，翼型最高 82%；发动机算例约 50% | 可行概率分类器 | arXiv 全文 |

Taylor 和 Prendergast 的综述（B13）、Taylor 等的综述（B12）、Pettersen 等（B23、B24）、Reggiani 等（B21、B22）的摘要里都没有关于失败算例处置的内容；后四篇是 1 到 7 根股骨的验证研究，不涉及批量失败。

### 1.4 不同意见

1. **优化文献的做法更直接。** 就我读到的部分，A2、A5、A7、A8、A10 都是失败一次就当作约束违反，没有提到换数值设置重试。按这种做法，两种失败都应立即归 `conclusion`。理由是仿真昂贵、失败是确定性的。我不照搬的原因是隐式接触分析的收敛依赖数值设置（B16、B19、C1），立即定类会把求解器的局限算到设计头上。
2. **骨科 FE 的习惯更保守。** B7、B17 是重试后剔除并报告，从不把失败当作证据，相当于永远 `unclear`。代价是优化器会重复提议算不出的点（A7）。规则 6 在失败率低时采用的就是这种做法。
3. **把不收敛读成失稳。** B18 这样做，B14 和 B15 在一定程度上也是。支持的理由是欠约束的静力问题确实不收敛（C1）。反对的理由是 C1 同时列了多种纯数值原因。
4. **Dakota 的 continuation 思路**认为不收敛常常是初值问题，从最近的成功点逐步逼近就能算出来（A13）。如果采用，很多 `not_computable` 会变成 `ok`，但实现成本高。

### 1.5 仍需自行判断

- 补救梯有几档、每档改什么。档数越多，`not_computable` 越少，计算费用越高。
- 用较高档位算出来的结果，能不能和原设置的结果放在同一个数据集里。建议抽 20 个 `ok` 点，分别用原设置和 R3 设置算，要求关注量的差别小于 2.5 节的网格收敛容差【建议】。
- 物理失稳的证据条件，尤其是判废阈值取多少。
- `unstable` 是只进分类器，还是也作为"响应不小于阈值"的删失观测进回归模型。
- 规则 6 的 2% 和 5%，规则 7 的 AUC 界限，可行概率下限 25%（A7 的默认值来自航空问题，失败率比骨科流水线高得多）。

---

## 2. 决策 2：FE 验证（verification）的验收

### 2.1 建议

**小算例两个：**

- **V1：Lamé 过盈配合。** 两个同心弹性圆筒，材料不同：钛合金实心内筒，皮质骨等效材料外筒，径向过盈几十微米。有闭式解。它同时检查接触、过盈的施加方式、单位和材料。做两个版本：
  - V1a 轴对称单元，几何精确，检查算法本身。
  - V1b 三维，走生产流水线：同样的切骨布尔运算、自动网格、单元类型、单元尺寸与半径之比、接触算法、过盈施加方式。检查流水线对"曲面共形接触 + 微小过盈"的离散。
- **V2：在 V1 上做摩擦滑移。** 过盈建立后转动内筒（或在泊松比取 0 的版本里轴向推出），滑移扭矩或滑移力有闭式解。它检查切向接触，和你们关心的假体转动直接对应。

这两个算例是标准做法：NAFEMS R0081 的 10 个接触基准里，CGS-10 是 "Interference between two cylinders"，CGS-1 是 "Contact patch test"，CGS-3 是 "Hertzian contact"【来源：C4】。Altair 的验证手册用 R0081 的两圆筒过盈算例核对接触压力（C5；该页只写了报告号，按算例名称对应 CGS-10）。Abaqus 自己的 Verification Guide §1.6.13 只做了过盈功能测试，结论只有一句 "The interference is resolved in five increments"，没有和解析解比（C3）。所以用户自己做 Lamé 对比不是重复劳动。

**其余候选怎么用：**
- 悬臂梁或拉杆：只能检查单元、材料、边界和后处理脚本，不涉及接触。可以留作冒烟测试。
- Hertz 接触：Abaqus Benchmarks Guide §1.1.11 的标准算例。该节对 Abaqus/Explicit 的结果写的是最大接触压力 "within 1% of the classical solution"，对 Abaqus/Standard 只写了压力分布 "in good agreement with the analytical distribution"，没给百分比（C2）。它是非共形接触，和压配的共形接触差得远，优先级低于 V1。
- 接触 patch test：检查不匹配网格之间能否传递均匀压力。如果切骨后骨和假体的网格不匹配，值得加上。

**V1b 是最有信息量的一项，原因有两个：**

1. Abaqus 通用接触默认会把小的初始过盈量消掉而不产生应力："Small initial contact overclosures are resolved by default using strain-free adjustments to the positions of surface nodes"；要当作过盈配合必须显式指定（C1 "Contact Initialization for General Contact…"）。如果流水线用的是通用接触的默认设置，建模的 50 µm 过盈可能根本没有产生压力。V1 的压力为零就能发现。接触对（contact pair）的默认处理不同：旧版文档写的是默认把初始穿透当作过盈配合来消除（这一句我只在 6.6 版文档的检索摘录里见到，没有逐页核对），请按你们所用的版本和接触定义方式确认。
2. 曲面离散成小平面带来的几何误差，量级可以和过盈量相当。Abaqus 文档针对同心圆筒过盈配合写道：不做曲面平滑时，面对面接触的结果 "it is not unusual for the maximum deviation from the analytical pressure solution to be upward of 100%"，过盈相对几何偏差越小越严重；另一个例子里启用基于 CAD 的平滑后，Mises 应力与解析解的偏差从 33% 降到 "less than 3%"（C1 "Smoothing Contact Surfaces…"）。
   【推算】一次单元的弦高误差约为 h²/(8R)。R = 8 mm 时：单元边长 0.5 mm 对应 3.9 µm，1 mm 对应 15.6 µm，2 mm 对应 62.5 µm，而过盈量只有 50 µm。二次单元的中间节点如果落在真实曲面上，误差在 0.1 µm 以下；如果几何来自三角面片的布尔运算，中间节点落在面片上，误差又回到面片的精度。

### 2.2 Lamé 过盈配合的闭式解

符号：a 为内筒内半径（实心取 0），b 为名义配合半径，c 为外筒外半径；δ 为**径向**过盈量（直径过盈的一半）；E_i、ν_i 属于内筒，E_o、ν_o 属于外筒；p 为接触压力，取正值。

```
K_o = (c² + b²) / (c² − b²)
K_i = (b² + a²) / (b² − a²)        实心内筒 K_i = 1
```

**平面应力**（两筒轴向都自由，σ_z = 0）：

```
p = δ / { b · [ (K_o + ν_o)/E_o + (K_i − ν_i)/E_i ] }
```

**平面应变**（两筒轴向都约束，ε_z = 0）：

```
p = δ / { b · [ (1+ν_o)·((1−ν_o)·K_o + ν_o)/E_o + (1+ν_i)·((1−ν_i)·K_i − ν_i)/E_i ] }
```

**应力**（两种情形表达式相同，代入各自的 p）：

```
外筒 b ≤ r ≤ c:   σ_r = p·b²/(c²−b²)·(1 − c²/r²)      σ_θ = p·b²/(c²−b²)·(1 + c²/r²)
   r = b:  σ_r = −p,  σ_θ = p·K_o
   r = c:  σ_r = 0,   σ_θ = 2·p·b²/(c²−b²)

内筒 a ≤ r ≤ b:   σ_r = −p·b²/(b²−a²)·(1 − a²/r²)     σ_θ = −p·b²/(b²−a²)·(1 + a²/r²)
   实心:  σ_r = σ_θ = −p（处处相同）

平面应变另有 σ_z = ν·(σ_r + σ_θ)
```

**位移**：

```
平面应力:  u_o(b) = + p·b·(K_o + ν_o)/E_o
           u_i(b) = − p·b·(K_i − ν_i)/E_i
           u_o(b) − u_i(b) = δ
           u_o(c) = 2·p·b²·c / (E_o·(c² − b²))
平面应变:  u_o(c) = 2·(1 − ν_o²)·p·b²·c / (E_o·(c² − b²))
```

特例：同种材料、实心内筒、平面应力时 p = E·δ·(c² − b²) / (2·b·c²)。

推导【推算】：Lamé 解 σ_r = A − B/r²，σ_θ = A + B/r²，平面应力下 u = [(1−ν)·A·r + (1+ν)·B/r]/E。外筒在 r = b 受内压 p、r = c 自由；内筒在 r = b 受外压 p、r = a 自由；相容条件是 u_o(b) − u_i(b) = δ。平面应变把 E 换成 E/(1−ν²)、ν 换成 ν/(1−ν)。我用数值检查过：位移差等于 δ，同材料特例与简化式一致。公式形式与机械设计教科书里的压配公式相同，但教科书的公式编号我没有在本次核对（见第 4 节）。

**适用条件，实现时要对上：**
- 线弹性、小应变，两筒等长。
- 平面应力版本要求两筒能相对轴向滑动（两种材料的轴向应变不同），所以过盈消除阶段应无摩擦。
- 开着摩擦做过盈时，用平面应变版本（两筒两端都约束轴向），或者把两种材料的泊松比都设为 0。NAFEMS CGS-10 在 Altair 手册里的实现就是泊松比取 0（C5）。

**数值算例**【推算】。尺寸和材料取自文献：model 3406 复合股骨的髓腔直径 16 mm，皮质骨等效材料 E = 16.7 GPa、ν = 0.3，Ti6Al4V 取 E = 110 GPa、ν = 0.3【来源：E12 全文】；过盈 50 µm【来源：B1 摘要用 "interference-fit of 50 μm"，摘要没说是径向还是直径；B25 摘要给出的最优值也在 50 µm 左右，该摘要前文说的是直径过盈（"diametrical interference fit"）】。下面的算例把 50 µm 当作径向过盈；如果你们的 50 µm 指直径过盈，δ 取 0.025 mm，表中的压力、应力、位移和滑移载荷全部减半；摩擦系数 0.4【来源：B1 摘要】。

取 a = 0，b = 8 mm，c = 14 mm，长度 L = 30 mm，δ = 0.05 mm（径向），μ = 0.4：

| 量 | 平面应力 | 平面应变 | 泊松比全取 0 |
|---|---|---|---|
| 接触压力 p（MPa） | 43.93 | 46.16 | 49.20 |
| 外筒内壁环向应力 σ_θ(b)（MPa） | 86.53 | 90.91 | — |
| 外筒外壁环向应力 σ_θ(c)（MPa） | 42.60 | 44.76 | — |
| 外筒内壁径向位移 u_o(b)（µm） | 47.76 | 48.25 | — |
| 内筒表面径向位移 u_i(b)（µm） | −2.24 | −1.75 | — |
| 外筒外壁径向位移 u_o(c)（µm） | 35.71 | 34.14 | — |
| 法向合力 p·2πbL（kN） | 66.24 | 69.60 | 74.19 |
| 扭转滑移扭矩 T（N·m） | 212.0 | 222.7 | — |
| 轴向滑移力 F（kN） | — | — | 29.68 |

同样的尺寸，外筒换成松质骨等效泡沫（E = 0.155 GPa、ν = 0.3【来源：E12】）时，平面应力下的接触压力只有约 0.43 MPa【推算】，比皮质骨外筒低两个数量级。如果实际界面主要是泡沫，V1 应另做一个泡沫外筒的版本。

### 2.3 V2：摩擦滑移

```
接触面积     A = 2π·b·L
扭转滑移     T_slip = μ·p·A·b = 2π·μ·p·b²·L
轴向滑移     F_slip = μ·p·A   = 2π·μ·p·b·L
```

- 扭转版本：固定外筒外表面，给内筒端面施加绕轴转角，读扭矩平台值。线弹性下轴对称扭转不改变径向应力，p 保持均匀，结果是精确的【推理】。需要三维模型或带扭转自由度的轴对称单元。
- 轴向版本：泊松比不为 0 时，轴向力通过泊松效应改变接触压力，F_slip = μ·p·A 只是近似。把泊松比全取 0 可以消除这一耦合，剩下的只有端部局部效应【推理】。
- 两个检查分开做：滑移力对 μ 乘以 FE 自己输出的法向合力，这是自洽性检查，应当很准；滑移力对解析值，包含了 V1 的压力误差。

### 2.4 小算例的容差

下表的限值都是【建议】，右列是参照的文献数值【来源】。

| 检查量 | V1a 轴对称 | V1b 三维生产设置 | 参照 |
|---|---|---|---|
| 平均接触压力（法向合力除以面积）对解析值 | ±1% | ±3% 通过，超过 5% 不通过 | Abaqus Hertz 基准 "within 1%"（C2，Explicit 的结果）；本构代码验证的例子 "<3%"（D5 §4.4.1，D6 §2.1）；Altair 对 NAFEMS 两圆筒过盈算例的结果是 2.35 对 2.27，偏差约 3.5%（C5） |
| 外筒外壁径向位移 u_o(c) | ±1% | ±3% | 同上 |
| 外筒内外壁环向应力 | ±2% | ±5% | 同上 |
| 节点接触压力的散布（第 5 到第 95 百分位） | ±3% 以内 | ±15% 以内；超出就启用曲面平滑、改用二次几何或加密 | 不平滑时偏差可超过 100%，平滑后 Mises 应力偏差 <3%（C1） |
| V2 滑移力或扭矩对 μ × FE 法向合力 | ±1% | ±2% | 自洽性 |
| V2 滑移力或扭矩对解析值 | ±2% | ±5% | 同第一行 |
| 网格收敛：三套网格，求观测收敛阶，GCI 取安全系数 1.25 | GCI ≤ 1% | GCI ≤ 3% | GCI 公式和安全系数见 D13、D15；观测收敛阶是最严格的代码验证方式（D4 §2.4.1） |
| 压力为零或接近零 | 立即不通过 | 立即不通过 | 通用接触默认无应力调整（C1） |

GCI 的算法【来源：D15】：GCI = F_s·|ε| / (r^p − 1)，ε 为相邻两套网格结果的相对差，r 为网格加密比，p 为观测收敛阶，p = ln[(f₃ − f₂)/(f₂ − f₁)] / ln r；两套网格时 F_s = 3.0，三套及以上 F_s = 1.25；GCI₂₃ ≈ r^p·GCI₁₂ 说明已进入渐近区。

V1b 用一次四面体、边长 1 mm 左右时很可能过不了 ±3%。这不是算例设计得不好，这正是它要回答的问题：生产网格能不能分辨 50 µm 的过盈。

### 2.5 全模型的全局检查

限值是【建议】，右列是参照【来源】。

| 检查 | 通过 | 警告 | 不通过 | 参照 |
|---|---|---|---|---|
| 力平衡：反力之和加外载之和，除以外载合力，各方向分别算 | ≤ 0.5% | 0.5% 到 1% | > 1% | Abaqus 默认残差容差 R_n = 5 × 10⁻³，文档称 "rather strict by engineering standards"；修正量容差 C_n = 10⁻²（C1 "Commonly Used Control Parameters"） |
| 力矩平衡，对固定参考点 | ≤ 1% | 1% 到 2% | > 2% | 无文献数值 |
| 稳定化耗散能与应变能之比 ALLSD/ALLIE，步末 | ≤ 1% | 1% 到 5% | > 5% | Abaqus 自适应稳定化的默认精度容差 0.05，文档称它是 "a targeted value and can be exceeded in some situations"；接触稳定化要求比较 ALLSD 与 ALLSE（C1） |
| 接触阻尼应力对真实接触应力，步末 | ≤ 1% | — | — | Abaqus 要求比较 CDSTRESS 与 CSTRESS，"If the contact damping stresses are too high, you should decrease the damping"，没给数值（C1） |
| 网格收敛，整体量（转动、沉降、刚度） | 相邻两级变化 < 2% | 2% 到 5% | > 5% | "<5%" 见 D6 §2.1；B26 和 E12 用的都是 5% |
| 网格收敛，界面微动 | 变化 < 5% 且 < 5 µm | — | — | 评估初稳定性的方法需要 "an accuracy of 10–20 micrometer or better"（B20 摘要） |
| 接触罚刚度灵敏度：刚度乘以 10 | 关注量变化 < 5% | — | — | 接触刚度和收敛容差对结果精度起关键作用（B19 摘要），没给数值 |
| 残余穿透量 | ≤ 过盈量的 2%（50 µm 过盈对应 1 µm） | — | — | 无文献数值 |
| 网格质量 | 长宽比 > 3 的单元少于 5%，Jacobian < 0.7 的单元少于 5% | — | — | Burkhart 等的限值，我只见到二手转述（D10、D11）；B17 用的是长宽比 > 5 算差、差单元少于 10% |
| 独立求解器或独立建模的同一完好股骨模型 | 应变或刚度相差 ≤ 3% | — | — | 三个求解器之间平均 3.0%，两个商业代码之间 1.4%（E8 摘要） |
| 整体刚度对文献实验值 | ±10% 到 ±15% | — | — | 第四代复合骨试件间差异 < 10%，装夹差异 < 6%（E1 摘要）；大号试件差异 < 10%（E2 摘要） |
| 应变对实验的回归（仅当几何来自被测试件本身） | 斜率 0.9 到 1.1，R² ≥ 0.9，RMSE ≤ 15% | — | — | 见 2.7 |

几点说明：

- **关于力平衡容差，文献里没有惯例数值。** 我检索了 PubMed 和网页，没有找到生物力学论文报告"反力和对外载"的容差；Erdemir 等只要求报告收敛容差以及是否用默认值（D8）。0.5% 是借用 Abaqus 默认残差容差的数值。两者不是一回事：Abaqus 的判据是最大节点残差对时间平均节点力之比，不是整体合力。整体合力检查能抓到的是另一类问题：载荷集或单位弄错、载荷没有加满、步末还有阻尼力、读的不是最后一帧。
- **微动用百分位数，不用最大值。** 最大值对网格敏感。Al-Dirini 等用第 90 百分位微动（B5 摘要），O'Rourke 等用第 95 百分位（B6 摘要）。
- **数值容差不必比代理模型和实验的误差小很多。** Al-Dirini 等的 GP 代理对微动的均方根误差是 "< 20 µm"（B4 摘要）；FE 对实验微动的误差在 10 µm 量级（2.7）。把数值误差压到 5 µm 以内已经够用。
- **沙漏能、质量缩放这类能量检查针对的是显式动力学和减缩积分单元**（D10 摘要）。隐式静力分析加完全积分或二次四面体单元时，对应的检查是上表的稳定化耗散能。沙漏能占内能百分之几的经验值，我只见到论坛和二手转述，没有在原始文档里核实，所以没有列入。

### 2.6 标准和综述实际规定了什么【来源】

- **ASME V&V 40-2018 不给数值阈值。** ASME 页面的说明是：该标准 "provides a framework for assessing the relevance and adequacy of completed V&V activities"，不打算提供 "a quantitative method for establishing model credibility"，判断依靠 "sound engineering judgment"（D1）。它的框架是：关注问题 → 使用情境 → 模型风险（模型影响力 × 决策后果）→ 可信度目标 → 验证与确认 → 适用性（D4 第 2 节，全文）。可信度目标要和风险相称，由使用者自己定。FDA 2023 年的指南同样是 "a risk-informed framework for credibility assessment"（D3）。
- **ASME V&V 10-2019（2025 年重新确认）** 提供的是通用词汇、概念框架和一般性指导（D2），没有数值容差。
- **Anderson、Ellis 和 Weiss 2007 没有给出"网格加密变化小于 5%"。** 我在 PMC 全文正文里检索，没有出现 5% 这个数。文中的数值是例子：本构实现与解析解相差 "less than 3%"（§4.4.1），某个网格收敛例子里应变相差 "less than one percent"（§4.4.2）。文中说网格收敛应以打算验证的那个量为主要判据，并且 "Mesh convergence studies do not guarantee that model predictions are accurate"（§4.3）。
- **"<5%" 出自 Henninger 等 2010**（D6 §2.1）："Studies of spinal segments have suggested that a change of <5% in the solution output is adequate to ensure mesh convergence is complete"。原文引的是脊柱 FE 文献，参考文献表里有 Jones 和 Wilcox 2008（D7）；我取到的全文里引用标号被去掉了，所以不能确认这句话引的就是 D7。同一节还说："use of a commercial code does not relieve the user of the need for verification"。
- **代码验证的强度有等级。** D4 §2.4.1："Calculating an observed order of convergence is the most stringent form of code verification"；较弱的方式包括 "determination of the discretization error as part of a mesh refinement study or comparison to the results of a previously verified code"。
- **Erdemir 等 2012 是报告清单，不是验收标准。** 要求报告收敛容差、用于网格收敛的输出量、做过的简化算例（有已知解的）。文中有一句和本决策直接相关："Although verified individually, when combined, these algorithms may behave in an unstable fashion"（D8 "Verification" 一节）。这是把接触、过盈、摩擦合在一个算例里验证的理由。
- **Viceconti 等 2005 的社论**（D9）没有摘要，我没能读到正文。Erdemir 等对它的评价是：Clinical Biomechanics 要求仿真论文符合该社论列出的要求，但社论只有 "Model Selection"、"Proper Parameter Identification" 这样的概括性条目（D8）。
- **Burkhart 等 2013**（D10）摘要：所综述的骨 FE 模型里约 42% 没有充分验证，95% 没有评估网格质量，98% 没有评估能量平衡。具体限值见上表的二手转述。
- **Oefner 等 2021**（D12）是骨科与创伤生物力学 FE 的验证与确认报告清单，我只读到摘要，摘要里没有数值。
- **相关系数不等于一致性。** D6 §3.5 引 Bland 和 Altman："the correlation coefficient is not a measure of agreement; it is a measure of association"，建议用差值对均值的图。所以和实验比较时不能只看 R²。

### 2.7 复合股骨 FE 与实验或独立结果的一致程度【来源】

| 研究 | 对象 | 一致程度 | 所见范围 |
|---|---|---|---|
| MacLeod 2016（E8） | 第四代复合股骨，应变片 4 处；Abaqus、Ansys、FEBio | 求解器之间：平均 3.0%（r² > 0.99），两个商业代码 1.4%。对实验：试件特定模型 RMSE 13.8%（r² = 0.96）；通用几何模型 RMSE 134.5%（r² = 0.29）。股骨颈皮质厚度在试件间相差最多 48.4% | 摘要 |
| Dickinson 2011（E7） | 复合股骨，数字图像相关 | R² 0.83 到 0.92 | 摘要 |
| Grassi 2013（E6） | 6 根复合股骨，数字图像相关，每根约 5 万个点 | 相关系数接近 0.9；线性段斜率接近 1、截距接近 0（摘要原文写作 "the slope and intercept were close to zero and unity"，顺序应是写反了） | 摘要 |
| Stolk 2002（E9） | 复合股骨 + 骨水泥柄，应变片 | 斜率 0.82 到 1.03，R² > 0.98；目标是总体相差 10% 以内 | 摘要 |
| Completo 2007（E4） | 股骨远端，完好和植入，应变片 10 处 | 斜率 0.94 到 1.06，R² 0.92 到 0.99，RMSE < 12% | 摘要 |
| Completo 2007（E5） | 合成胫骨，完好和植入 | 总体相差 10% 以内，RMSE < 10% | 摘要 |
| Pal 2010（E10） | 复合股骨，表面置换；应变和微动 | 应变相关系数 0.92 到 0.95，回归斜率误差 12.8% 到 17.5%；微动实验 0 到 13.7 µm，FE 0 到 25 µm | 摘要 |
| Dubov 2011、Shah 2011（E14、E15） | 合成股骨 + 髋假体 + 钢板，应变片 | R² 0.90、斜率 0.96；R² 0.92、斜率 1.06 | 摘要 |
| Naghavi 2022（E12） | model 3406 复合股骨，应变片；Abaqus，C3D10 | 只给了 Bland–Altman 图，"all the dots are within the 95% confidence interval"；没有斜率和 R²。柄与周围材料是绑定接触，不是摩擦压配。网格收敛判据 5% | 全文 |
| Heiner 2008（E1） | 第四代复合股骨和胫骨，纯实验 | 刚度的试件间差异 < 10%，装夹差异 < 6% | 摘要 |
| Gardner 2010（E2） | 大号第四代复合股骨和胫骨各 30 根，纯实验 | 各项差异 < 10% | 摘要 |
| Cristofolini 1996（E11） | 早期复合股骨，纯实验 | 复合股骨间的差异比尸体股骨小 20 到 200 倍 | 摘要 |
| Papini 2007（E3） | 第三代复合股骨，FE 对实验的轴向和扭转刚度 | 摘要没有给 FE 对实验的数值 | 摘要 |

人体股骨和微动的参照值：
- 应变：R² = 0.91，RMSE 低于最大测量值的 10%（E16 摘要）；完好股骨 R² = 0.94、斜率 0.99，植入后 R² = 0.86、斜率 0.86（B24 摘要）。
- 微动：面对面接触单元 + 摩擦 + 初始压配的模型，均方根误差 10 µm，峰值误差 14 µm，其余建模方式误差都超过 20 µm（B20 摘要）；最大微动的误差为实测峰值的 12%（B21 摘要）；轴向转动 R² = 0.74，界面微动的预测 "limited success"（B23 摘要）。
- 过盈量对微动影响很大，忽略过盈会低估稳定性（B25 摘要）。

由此得到三点：

1. **小解析算例和全模型的"在容差内"不是一个量级。** 解析算例可以要求 1% 到 3%。同一模型换求解器是 1% 到 3%。全模型对实验，在几何取自被测试件的条件下，是斜率偏离 1 不超过 0.1 到 0.2、RMSE 10% 到 15%。
2. **通用几何不能拿来和具体试件的局部应变比。** E8 的 134.5% 对 13.8% 说明了这一点。如果你们的股骨几何是通用 CAD 而不是扫描被测试件，全模型只适合对整体刚度（E1、E2 的范围）。
3. **E8 提供了一个现成的独立对照。** 摘要称其模型和验证数据 "freely available online"。完好股骨部分可以和它比。型号和尺寸是否与你们的一致，摘要没写，需要查全文。

### 2.8 不同意见

1. **V&V 40 的立场是不该有固定百分比。** 容差应从使用情境和模型风险推出来（D1、D4）。按这个立场，上面两张表只是起点，应当写进一份事先定好的验证计划，并说明每个数为什么对你们的决策够用。
2. **"相邻两级变化小于 5%"不是误差估计。** Roache 和 Celik 一派要求三套网格、观测收敛阶和 GCI（D13、D14、D15）。生物力学的惯例是两套网格加 5%（D6、B26、E12）。我的建议是小算例用前者，全模型用后者并在少数代表点上做三套网格。
3. **和单点解析值比对是较弱的代码验证**，观测收敛阶才是最严格的（D4）。2.4 的表里因此加了 GCI 一行。
4. **网格质量限值不统一。** Burkhart 等的限值（二手转述）是长宽比 3、Jacobian 0.7、不合格单元少于 5%；B17 用的是长宽比 5、少于 10%，并引他人称这是常见指引。
5. **Anderson 等强调收敛了不等于准**（D5 §4.3）。小算例通过只说明接触、过盈和摩擦的实现没错，不说明全模型的微动是对的。

### 2.9 仍需自行判断

- 每个百分比的具体取值。有文献数值作参照的是：1%（Hertz 基准）、3%（本构验证的例子、求解器间差异）、3.5%（一个厂商对 CGS-10 的结果）、5%（网格收敛惯例、稳定化能量比）、10 到 20 µm（微动方法需要的精度）。
- V1b 过不了时怎么办：加密、换二次单元、启用曲面平滑，还是接受较大的散布并只用平均压力。
- V1 的外筒用皮质骨等效材料、泡沫，还是两种都做。
- 全模型要不要和文献实验比。几何是通用的话，只比整体刚度。
- 力平衡 0.5% 的限值。收敛的静力步通常远低于这个数，但我没有找到文献数值来支持更严的限。

---

## 3. 参考文献

每条末尾的方括号写明核验途径和我实际看到的范围。作者超过 8 人的只列第一作者。

### A. 仿真优化、代理模型、失败运行

- **A1** Le Digabel S, Wild SM. A taxonomy of constraints in black-box simulation-based optimization. *Optimization and Engineering* 25:1125–1143（CrossRef 记录年份 2023）. DOI [10.1007/s11081-023-09839-3](https://doi.org/10.1007/s11081-023-09839-3). 预印本 arXiv:1505.07881（2015，题为 "A Taxonomy of Constraints in Simulation-Based Optimization"）. [CrossRef + arXiv；读的是 arXiv 第 1 版全文，§2.3、§2.4、§2.5、§3.1、§3.2。正式发表版的措辞可能略有不同]
- **A2** Lee HKH, Gramacy RB, Linkletter C, Gray GA. Optimization subject to hidden constraints via statistical emulation. *Pacific Journal of Optimization* 7:467–478, 2011. 技术报告 UCSC-SOE-10-10（2010-03-24）. [Sandia 出版物页面 + UCSC 技术报告；读的是技术报告全文第 1–3 节。卷和页码取自 A1 的参考文献表，未见 DOI]
- **A3** Gramacy RB, Lee HKH. Optimization under unknown constraints. In: *Bayesian Statistics 9*, Oxford University Press, 2011, pp. 229–256. DOI [10.1093/acprof:oso/9780199694587.003.0008](https://doi.org/10.1093/acprof:oso/9780199694587.003.0008). arXiv:1004.4027. [CrossRef + arXiv；读的是 arXiv 全文，摘要、第 1 节、§4.2]
- **A4** Gelbart MA, Snoek J, Adams RP. Bayesian optimization with unknown constraints. arXiv:1403.5607, 2014. [arXiv；读的是全文 §1.3、§1.4、§3.1、§3.2、第 4 节。通常引作 UAI 2014 会议论文，会议卷页我没有核实]
- **A5** Sacher M, Duvigneau R, Le Maître O, Durand M, Berrini É, Hauville F, Astolfi J-A. A classification approach to efficient global optimization in presence of non-computable domains. *Structural and Multidisciplinary Optimization* 58:1537–1557, 2018. DOI [10.1007/s00158-018-1981-8](https://doi.org/10.1007/s00158-018-1981-8). [CrossRef + 出版社页面；只读到摘要]
- **A6** Bachoc F, Helbert C, Picheny V. Gaussian process optimization with failures: classification and convergence proof. *Journal of Global Optimization* 78:483–506, 2020. DOI [10.1007/s10898-020-00920-0](https://doi.org/10.1007/s10898-020-00920-0). [CrossRef + 出版社页面；只读到摘要：分类与回归的联合 GP 模型，在汽车风扇设计模型上测试]
- **A7** Bussemaker J, Saves P, Bartoli N, Lefebvre T, Nagel B. Surrogate-based optimization of system architectures subject to hidden constraints. AIAA AVIATION FORUM AND ASCEND 2024, paper 4401. DOI [10.2514/6.2024-4401](https://doi.org/10.2514/6.2024-4401). arXiv:2504.08721. [arXiv 页面 + arXiv HTML 第 1 版全文；摘要、第 1 节、§3.1、§3.3、第 5 节]
- **A8** Forrester AIJ, Sóbester A, Keane AJ. Optimization with missing data. *Proceedings of the Royal Society A* 462(2067):935–945, 2006. DOI [10.1098/rspa.2005.1608](https://doi.org/10.1098/rspa.2005.1608). [CrossRef；只读到摘要]
- **A9** Forrester AIJ, Sóbester A, Keane AJ. *Engineering Design via Surrogate Modelling: A Practical Guide*. John Wiley & Sons, 2008. ISBN 978-0-470-06068-1；AIAA 版 DOI [10.2514/4.479557](https://doi.org/10.2514/4.479557). [CrossRef + 出版社试读文件；看到目录（§5.5 "Missing Data"，§5.5.1 "Imputing Data for Infeasible Designs"）和序言第 xvi 页："most numerical schemes are rarely completely foolproof and will sometimes fail in unexpected ways"。§5.5 正文没有读到]
- **A10** Müller J, Day M. Surrogate optimization of computationally expensive black-box problems with hidden constraints. *INFORMS Journal on Computing* 31(4):689–702, 2019. DOI [10.1287/ijoc.2018.0864](https://doi.org/10.1287/ijoc.2018.0864). [EconPapers 题录页；只读到摘要]
- **A11** Lucas DD, Klein R, Tannahill J, Ivanova D, Brandon S, Domyancic D, Zhang Y. Failure analysis of parameter-induced simulation crashes in climate models. *Geoscientific Model Development* 6:1157–1171, 2013. DOI [10.5194/gmd-6-1157-2013](https://doi.org/10.5194/gmd-6-1157-2013). [CrossRef + 出版社页面；只读到摘要]
- **A12** Paja W, Wrzesień M, Niemiec R, Rudnicki WR. Application of all-relevant feature selection for the failure analysis of parameter-induced simulation crashes in climate models. *Geoscientific Model Development* 9:1065–1072, 2016. DOI [10.5194/gmd-9-1065-2016](https://doi.org/10.5194/gmd-9-1065-2016). [CrossRef；只见到摘要的转述]
- **A13** Sandia National Laboratories. Dakota 文档，"Simulation Failure Capturing"（6.21 版文档）. https://snl-dakota.github.io/docs/6.21.0/users/usingdakota/advanced/simulationfailurecapturing.html [读的是该页]
- **A14** Rubin DB. Inference and missing data. *Biometrika* 63(3):581–592, 1976. DOI [10.1093/biomet/63.3.581](https://doi.org/10.1093/biomet/63.3.581). [CrossRef；只核对了题录，内容本次没有重读，正文仅作为缺失机制的一般出处]

### B. 骨科 FE：群体研究、失败处置、接触与微动

以下条目的信息取自 PubMed。

- **B1** Bah MT, Shi J, Heller MO, et al. Inter-subject variability effects on the primary stability of a short cementless femoral stem. *J Biomech* 48(6):1032–42, 2015. PMID 25724937. DOI [10.1016/j.jbiomech.2015.01.037](https://doi.org/10.1016/j.jbiomech.2015.01.037). [摘要：109 例 CT，摩擦系数 0.4，过盈 50 µm。全文取不到]
- **B2** Al-Dirini RMA, Martelli S, O'Rourke D, Huff D, Zhang J, Clement JG, Besier T, Taylor M. Virtual trial to evaluate the robustness of cementless femoral stems to patient and surgical variation. *J Biomech* 82:346–356, 2019. PMID 30473137. DOI [10.1016/j.jbiomech.2018.11.013](https://doi.org/10.1016/j.jbiomech.2018.11.013). [摘要：1952 例；阈值 150 µm 和 7000 µε；位置受髓腔内皮质边界约束]
- **B3** Al-Dirini RMA, O'Rourke D, Huff D, Martelli S, Taylor M. Biomechanical robustness of a contemporary cementless stem to surgical variation in stem size and position. *J Biomech Eng* 140(9), 2018. PMID 29801163. DOI [10.1115/1.4039824](https://doi.org/10.1115/1.4039824). [摘要]
- **B4** Al-Dirini RMA, Martelli S, Taylor M. Computational efficient method for assessing the influence of surgical variability on primary stability of a contemporary femoral stem in a cohort of subjects. *Biomech Model Mechanobiol* 19(4):1283–1295, 2020（在线 2019）. PMID 31637534. DOI [10.1007/s10237-019-01235-0](https://doi.org/10.1007/s10237-019-01235-0). [摘要：GP 代理对 1036 个方案的 RMSE < 20 µm；另有一个拟合优度指标 0.81，摘要里它的符号显示为公式占位符，应是 R²]
- **B5** Al-Dirini RMA, Huff D, Zhang J, Besier T, Clement JG, Taylor M. Influence of collars on the primary stability of cementless femoral stems: a finite element study using a diverse patient cohort. *J Orthop Res* 36(4):1185–1195, 2018. PMID 28940776. DOI [10.1002/jor.23744](https://doi.org/10.1002/jor.23744). [摘要：用第 90 百分位微动]
- **B6** O'Rourke D, Al-Dirini RMA, Taylor M. Primary stability of a cementless acetabular cup in a cohort of patient-specific finite element models. *J Orthop Res* 36(3):1012–1023, 2018. PMID 28833500. DOI [10.1002/jor.23709](https://doi.org/10.1002/jor.23709). [摘要：103 例，第 95 百分位微动]
- **B7** O'Rourke DH. *Patient and Surgical Variability in the Primary Stability of Cementless Acetabular Cups for Computational Pre-Clinical Testing*. PhD thesis, Flinders University, 2017. https://flex.flinders.edu.au/file/5ae818de-9285-4309-bd6a-1939a6cfda43/1/ThesisORourke2017.pdf [学位论文全文；第 3 章方法（布尔失败后平移 0.01 mm，失败后减小时间增量），第 6 章结果（1 例网格畸变失败）。未经同行评议]
- **B8** Galloway F, Kahnt M, Ramm H, Worsley P, Zachow S, Nair P, Taylor M. A large scale finite element study of a cementless osseointegrated tibial tray. *J Biomech* 46(11):1900–6, 2013. PMID 23764172. DOI [10.1016/j.jbiomech.2013.04.021](https://doi.org/10.1016/j.jbiomech.2013.04.021). [摘要]
- **B9** Bryan R, Nair PB, Taylor M. Use of a statistical model of the whole femur in a large scale, multi-model study of femoral neck fracture risk. *J Biomech* 42(13):2171–6, 2009. PMID 19646700. DOI [10.1016/j.jbiomech.2009.05.038](https://doi.org/10.1016/j.jbiomech.2009.05.038). [摘要]
- **B10** Bryan R, Mohan PS, Hopkins A, Galloway F, Taylor M, Nair PB. Statistical modelling of the whole human femur incorporating geometric and material properties. *Med Eng Phys* 32(1):57–65, 2010. PMID 19932044. DOI [10.1016/j.medengphy.2009.10.008](https://doi.org/10.1016/j.medengphy.2009.10.008). [摘要：网格质量在采样过程中保持]
- **B11** Bryan R, Nair PB, Taylor M. Influence of femur size and morphology on load transfer in the resurfaced femoral head: a large scale, multi-subject finite element study. *J Biomech* 45(11):1952–8, 2012. PMID 22704609. DOI [10.1016/j.jbiomech.2012.05.015](https://doi.org/10.1016/j.jbiomech.2012.05.015). [摘要]
- **B12** Taylor M, Bryan R, Galloway F. Accounting for patient variability in finite element analysis of the intact and implanted hip and knee: a review. *Int J Numer Method Biomed Eng* 29(2):273–92, 2013. PMID 23255372. DOI [10.1002/cnm.2530](https://doi.org/10.1002/cnm.2530). [摘要；没有失败处置的内容]
- **B13** Taylor M, Prendergast PJ. Four decades of finite element analysis of orthopaedic devices: where are we now and what are the opportunities? *J Biomech* 48(5):767–78, 2015. PMID 25560273. DOI [10.1016/j.jbiomech.2014.12.019](https://doi.org/10.1016/j.jbiomech.2014.12.019). [摘要；没有失败处置的内容]
- **B14** Viceconti M, Brusi G, Pancanti A, Cristofolini L. Primary stability of an anatomical cementless hip stem: a statistical analysis. *J Biomech* 39(7):1169–79, 2006. PMID 15927191. DOI [10.1016/j.jbiomech.2005.03.024](https://doi.org/10.1016/j.jbiomech.2005.03.024). [摘要。"宏观不稳定"在模型里怎么判定，摘要没写]
- **B15** Gersie T, Bitter T, Freeman R, Verdonschot N, Janssen D. Influence of bone stress relaxation and abrasion on micromotions in uncemented femoral knee implants: a finite element study. *Med Eng Phys* 147(5), 2026. PMID 41916332. DOI [10.1088/1873-4030/ae5962](https://doi.org/10.1088/1873-4030/ae5962). [摘要]
- **B16** Ovesy M, Aeschlimann M, Zysset PK. Explicit finite element analysis can predict the mechanical response of conical implant press-fit in homogenized trabecular bone. *J Biomech* 107:109844, 2020. PMID 32517857. DOI [10.1016/j.jbiomech.2020.109844](https://doi.org/10.1016/j.jbiomech.2020.109844). [摘要]
- **B17** Nispel K, Lerchl T, Gruber G, Moeller H, Graf R, Senner V, Kirschke JS. From MRI to FEM: an automated pipeline for biomechanical simulations of vertebrae and intervertebral discs. *Front Bioeng Biotechnol* 12:1485115, 2025. PMID 39830685, PMC11739884. DOI [10.3389/fbioe.2024.1485115](https://doi.org/10.3389/fbioe.2024.1485115). [PMC 全文；§2.6、§3.1、§3.2、第 4 节。模型是线弹性、无接触]
- **B18** Xu J, Jiang Y, Wu W, et al. An Adams' Arch-based anatomical classification system guiding internal fixation strategies for non-displaced femoral neck fractures in elderly patients: a finite element analysis. *BMC Musculoskelet Disord* 27(1), 2026. PMID 42380997. DOI [10.1186/s12891-026-10082-x](https://doi.org/10.1186/s12891-026-10082-x). [摘要]
- **B19** Bernakiewicz M, Viceconti M. The role of parameter identification in finite element contact analyses with reference to orthopaedic biomechanics applications. *J Biomech* 35(1):61–7, 2002. PMID 11747884. DOI [10.1016/s0021-9290(01)00163-4](https://doi.org/10.1016/s0021-9290(01)00163-4). [摘要]
- **B20** Viceconti M, Muccini R, Bernakiewicz M, Baleani M, Cristofolini L. Large-sliding contact elements accurately predict levels of bone-implant micromotion relevant to osseointegration. *J Biomech* 33(12):1611–8, 2000. PMID 11006385. DOI [10.1016/s0021-9290(00)00140-8](https://doi.org/10.1016/s0021-9290(00)00140-8). [摘要]
- **B21** Reggiani B, Cristofolini L, Varini E, Viceconti M. Predicting the subject-specific primary stability of cementless implants during pre-operative planning: preliminary validation of subject-specific finite-element models. *J Biomech* 40(11):2552–8, 2007. PMID 17229427. DOI [10.1016/j.jbiomech.2006.10.042](https://doi.org/10.1016/j.jbiomech.2006.10.042). [摘要]
- **B22** Reggiani B, Cristofolini L, Taddei F, Viceconti M. Sensitivity of the primary stability of a cementless hip stem to its position and orientation. *Artif Organs* 32(7):555–60, 2008. PMID 18638310. DOI [10.1111/j.1525-1594.2008.00577.x](https://doi.org/10.1111/j.1525-1594.2008.00577.x). [摘要]
- **B23** Pettersen SH, Wik TS, Skallerud B. Subject specific finite element analysis of implant stability for a cementless femoral stem. *Clin Biomech* 24(6):480–7, 2009. PMID 19368993. DOI [10.1016/j.clinbiomech.2009.03.009](https://doi.org/10.1016/j.clinbiomech.2009.03.009). [摘要]
- **B24** Pettersen SH, Wik TS, Skallerud B. Subject specific finite element analysis of stress shielding around a cementless femoral stem. *Clin Biomech* 24(2):196–202, 2009. PMID 19103468. DOI [10.1016/j.clinbiomech.2008.11.003](https://doi.org/10.1016/j.clinbiomech.2008.11.003). [摘要]
- **B25** Abdul-Kadir MR, Hansen U, Klabunde R, Lucas D, Amis A. Finite element modelling of primary hip stem stability: the effect of interference fit. *J Biomech* 41(3):587–94, 2008. PMID 18036531. DOI [10.1016/j.jbiomech.2007.10.009](https://doi.org/10.1016/j.jbiomech.2007.10.009). [摘要]
- **B26** Cilla M, Borgiani E, Martínez J, Duda GN, Checa S. Machine learning techniques for the optimization of joint replacements: application to a short-stem hip implant. *PLoS One* 12(9):e0183755, 2017. PMID 28873093, PMC5584793. DOI [10.1371/journal.pone.0183755](https://doi.org/10.1371/journal.pone.0183755). [PMC 全文 §2.1、§2.2：256 个模型，C3D10，应变变化不超过 5% 视为收敛]

### C. Abaqus 文档和接触基准

- **C1** Dassault Systèmes SIMULIA. Abaqus 文档（弗吉尼亚理工镜像，URL 路径标为 2025 版，页面本身不显示版本号），以下各页：
  - "Commonly Used Control Parameters"：R_n 默认 5 × 10⁻³，C_n 默认 10⁻²。
  - "Convergence Criteria for Nonlinear Problems"：通量的空间平均和时间平均的定义；零通量判据默认 10⁻⁵。
  - "Solving Nonlinear Problems"：增量回退到 25%，超过 5 次终止；稳定化的耗散能比例默认 2.0 × 10⁻⁴，自适应稳定化精度容差默认 0.05；要求比较 ALLSD 与 ALLIE、粘性力 VF 与总体力。
  - "Common Difficulties Associated with Contact Modeling in Abaqus/Standard"。
  - "Generally Applicable Contact Controls in Abaqus/Standard"：接触稳定化的用途、限制和检查方法。
  - "Smoothing Contact Surfaces in Abaqus/Standard"。
  - "Contact Initialization for General Contact in Abaqus/Standard"。
  https://docs.software.vt.edu/abaqusv2025/English/ [逐页读过。镜像不是达索官方站点，数值请与你们所用版本的文档核对]
- **C2** Abaqus Benchmarks Guide, §1.1.11 "The Hertz contact problem"（科罗拉多大学镜像，2016 版）. https://ceae-server.colorado.edu/v2016/books/bmk/ch01s01ach11.html [读过该页]
- **C3** Abaqus Verification Guide, §1.6.13 "Contact with time-dependent prescribed interference values"（同一镜像，2016 版）. https://ceae-server.colorado.edu/v2016/books/ver/ch01s06abv92.html [读过该页]
- **C4** Prinja N, Feng Q. *NAFEMS Benchmark Tests for Finite Element Modelling of Contact, Gapping and Sliding*. NAFEMS, R0081, 2001. https://www.nafems.org/publications/resource_center/r0081/ [NAFEMS 页面：题名、作者、日期、10 个基准的名称。报告本身没有读到，CGS-10 的几何和参考值需要从报告取]
- **C5** Altair. OptiStruct 验证算例 OS-V: 0280 "Axisymmetric Elements, Interference Fit Between Two Cylinders". https://help.altair.com/hwsolvers/os/topics/solvers/os/nafems_nonlinear_static_analysis_axisymmetric_elements_interference_2_cylinders_r.htm [读过该页：引 NAFEMS R0081，过盈 20 mm，E = 206 GPa，泊松比 0，无摩擦；NAFEMS 接触压力 2.27，OptiStruct 2.35；页面没给单位和半径]

### D. 验证与确认

- **D1** ASME V&V 40-2018. *Assessing Credibility of Computational Modeling through Verification and Validation: Application to Medical Devices*. [ASME 标准页面的说明；标准正文没有读到]
- **D2** ASME V&V 10-2019 (R2025). *Standard for Verification and Validation in Computational Solid Mechanics*. [ASME 标准页面的说明]
- **D3** U.S. FDA. *Assessing the Credibility of Computational Modeling and Simulation in Medical Device Submissions*. Guidance, November 2023. Docket FDA-2021-D-0980. [FDA 页面的摘要]
- **D4** Viceconti M, Pappalardo F, Rodriguez B, Horner M, Bischoff J, Musuamba Tshinanu F. In silico trials: verification, validation and uncertainty quantification of predictive models used in the regulatory evaluation of biomedical products. *Methods* 185:120–127, 2021. PMID 31991193, PMC7883933. DOI [10.1016/j.ymeth.2020.01.011](https://doi.org/10.1016/j.ymeth.2020.01.011). [PubMed + PMC 全文；第 2 节]
- **D5** Anderson AE, Ellis BJ, Weiss JA. Verification, validation and sensitivity studies in computational biomechanics. *Comput Methods Biomech Biomed Engin* 10(3):171–84, 2007. PMID 17558646, PMC3361760. DOI [10.1080/10255840601160484](https://doi.org/10.1080/10255840601160484). [PubMed + PMC 全文正文；§4.2、§4.3、§4.4]
- **D6** Henninger HB, Reese SP, Anderson AE, Weiss JA. Validation of computational models in biomechanics. *Proc Inst Mech Eng H* 224(7):801–12, 2010. PMID 20839648, PMC2941217. DOI [10.1243/09544119JEIM649](https://doi.org/10.1243/09544119JEIM649). [PubMed + PMC 全文；§2.1、§3.5]
- **D7** Jones AC, Wilcox RK. Finite element analysis of the spine: towards a framework of verification, validation and sensitivity analysis. *Med Eng Phys* 30(10):1287–304, 2008. PMID 18986824. DOI [10.1016/j.medengphy.2008.09.006](https://doi.org/10.1016/j.medengphy.2008.09.006). [PubMed 摘要；摘要里没有 5% 这个数]
- **D8** Erdemir A, Guess TM, Halloran J, Tadepalli SC, Morrison TM. Considerations for reporting finite element analysis studies in biomechanics. *J Biomech* 45(4):625–33, 2012. PMID 22236526, PMC3278509. DOI [10.1016/j.jbiomech.2011.11.038](https://doi.org/10.1016/j.jbiomech.2011.11.038). [PubMed + PMC 全文]
- **D9** Viceconti M, Olsen S, Nolte L-P, Burton K. Extracting clinically relevant data from finite element simulations. *Clin Biomech* 20(5):451–4, 2005. PMID 15836931. DOI [10.1016/j.clinbiomech.2005.01.010](https://doi.org/10.1016/j.clinbiomech.2005.01.010). [PubMed 题录，社论，无摘要；正文没有读到]
- **D10** Burkhart TA, Andrews DM, Dunning CE. Finite element modeling mesh quality, energy balance and validation methods: a review with recommendations associated with the modeling of bone tissue. *J Biomech* 46(9):1477–88, 2013. PMID 23623312. DOI [10.1016/j.jbiomech.2013.03.022](https://doi.org/10.1016/j.jbiomech.2013.03.022). [PubMed 摘要；具体限值没有读到原文]
- **D11** Eliasson E, Wass J. *Industrialisation of a Finite Element Active Human Body Model for Vehicle Crash Simulations*. Master's thesis 2015:52, Chalmers University of Technology, 2015. https://publications.lib.chalmers.se/records/fulltext/218339/218339.pdf [全文；仅用作 D10 限值的二手转述："Less than 5% of the elements should have an aspect ratio above 3…Less than 5% of the elements should have a Jacobian below 0.7, preferably with the smallest Jacobian greater than 0.2"，以及内角偏差的限值]
- **D12** Oefner C, Herrmann S, Kebbach M, Lange H-E, Kluess D, Woiczinski M. Reporting checklist for verification and validation of finite element analysis in orthopedic and trauma biomechanics. *Med Eng Phys* 92:25–32, 2021. PMID 34167708. DOI [10.1016/j.medengphy.2021.03.011](https://doi.org/10.1016/j.medengphy.2021.03.011). [PubMed 摘要]
- **D13** Roache PJ. Perspective: a method for uniform reporting of grid refinement studies. *J Fluids Eng* 116(3):405–413, 1994. DOI [10.1115/1.2910291](https://doi.org/10.1115/1.2910291). [CrossRef 题录；公式和安全系数见 D15]
- **D14** Celik IB, Ghia U, Roache PJ, Freitas CJ, 等. Procedure for estimation and reporting of uncertainty due to discretization in CFD applications. *J Fluids Eng* 130(7):078001, 2008. DOI [10.1115/1.2960953](https://doi.org/10.1115/1.2960953). [CrossRef 题录，记录里没有作者字段；作者名取自检索结果，完整名单没有核实]
- **D15** NPARC Alliance CFD Verification and Validation Web Site（NASA Glenn Research Center）. "Examining Spatial (Grid) Convergence". https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html [读过该页：安全系数 3.0 和 1.25，算例里的 GCI、收敛阶和 Richardson 外推算式]

### E. 复合股骨的实验和 FE 验证

以下条目的信息取自 PubMed。

- **E1** Heiner AD. Structural properties of fourth-generation composite femurs and tibias. *J Biomech* 41(15):3282–4, 2008. PMID 18829031. DOI [10.1016/j.jbiomech.2008.08.013](https://doi.org/10.1016/j.jbiomech.2008.08.013). [摘要；刚度数值在正文，没有读到]
- **E2** Gardner MP, Chong ACM, Pollock AG, Wooley PH. Mechanical evaluation of large-size fourth-generation composite femur and tibia models. *Ann Biomed Eng* 38(3):613–20, 2010. PMID 20049637. DOI [10.1007/s10439-009-9887-7](https://doi.org/10.1007/s10439-009-9887-7). [摘要]
- **E3** Papini M, Zdero R, Schemitsch EH, Zalzal P. The biomechanics of human femurs in axial and torsional loading: comparison of finite element analysis, human cadaveric femurs, and synthetic femurs. *J Biomech Eng* 129(1):12–9, 2007. PMID 17227093. DOI [10.1115/1.2401178](https://doi.org/10.1115/1.2401178). [摘要]
- **E4** Completo A, Fonseca F, Simões JA. Experimental validation of intact and implanted distal femur finite element models. *J Biomech* 40(11):2467–76, 2007. PMID 17224158. DOI [10.1016/j.jbiomech.2006.11.012](https://doi.org/10.1016/j.jbiomech.2006.11.012). [摘要；摘要没写明试件是合成骨还是尸体骨]
- **E5** Completo A, Fonseca F, Simões JA. Finite element and experimental cortex strains of the intact and implanted tibia. *J Biomech Eng* 129(5):791–7, 2007. PMID 17887906. DOI [10.1115/1.2768382](https://doi.org/10.1115/1.2768382). [摘要]
- **E6** Grassi L, Väänänen SP, Amin Yavari S, Weinans H, Jurvelin JS, Zadpoor AA, Isaksson H. Experimental validation of finite element model for proximal composite femur using optical measurements. *J Mech Behav Biomed Mater* 21:86–94, 2013. PMID 23510970. DOI [10.1016/j.jmbbm.2013.02.006](https://doi.org/10.1016/j.jmbbm.2013.02.006). [摘要]
- **E7** Dickinson AS, Taylor AC, Ozturk H, Browne M. Experimental validation of a finite element model of the proximal femur using digital image correlation and a composite bone model. *J Biomech Eng* 133(1):014504, 2011. PMID 21186906. DOI [10.1115/1.4003129](https://doi.org/10.1115/1.4003129). [摘要]
- **E8** MacLeod AR, Rose H, Gill HS. A validated open-source multisolver fourth-generation composite femur model. *J Biomech Eng* 138(12), 2016. PMID 27618586. DOI [10.1115/1.4034653](https://doi.org/10.1115/1.4034653). [摘要]
- **E9** Stolk J, Verdonschot N, Cristofolini L, Toni A, Huiskes R. Finite element and experimental models of cemented hip joint reconstructions can produce similar bone and cement strains in pre-clinical tests. *J Biomech* 35(4):499–510, 2002. PMID 11934419. DOI [10.1016/s0021-9290(01)00213-5](https://doi.org/10.1016/s0021-9290(01)00213-5). [摘要]
- **E10** Pal B, Gupta S, New AMR, Browne M. Strain and micromotion in intact and resurfaced composite femurs: experimental and numerical investigations. *J Biomech* 43(10):1923–30, 2010. PMID 20392448. DOI [10.1016/j.jbiomech.2010.03.019](https://doi.org/10.1016/j.jbiomech.2010.03.019). [摘要]
- **E11** Cristofolini L, Viceconti M, Cappello A, Toni A. Mechanical validation of whole bone composite femur models. *J Biomech* 29(4):525–35, 1996. PMID 8964782. DOI [10.1016/0021-9290(95)00084-4](https://doi.org/10.1016/0021-9290(95)00084-4). [摘要]
- **E12** Naghavi SA, Lin C, Sun C, et al. Stress shielding and bone resorption of press-fit polyether-ether-ketone (PEEK) hip prosthesis: a sawbone model study. *Polymers* 14(21):4600, 2022. PMID 36365594, PMC9657056. DOI [10.3390/polym14214600](https://doi.org/10.3390/polym14214600). [PMC 全文；§2.2.2、§2.3.2、§2.3.3、§3.1]
- **E13** Naghavi SA, Tamaddon M, Garcia-Souto P, Moazen M, Taylor S, Hua J, Liu C. A novel hybrid design and modelling of a customised graded Ti-6Al-4V porous hip implant to reduce stress-shielding: an experimental and numerical analysis. *Front Bioeng Biotechnol* 11:1092361, 2023. PMID 36777247, PMC9910359. DOI [10.3389/fbioe.2023.1092361](https://doi.org/10.3389/fbioe.2023.1092361). [摘要；摘要里没有 FE 对实验的一致性数值，正文没有读，本简报没有引用它的数值]
- **E14** Dubov A, Kim SYR, Shah S, Schemitsch EH, Zdero R, Bougherara H. The biomechanics of plate repair of periprosthetic femur fractures near the tip of a total hip implant: the effect of cable-screw position. *Proc Inst Mech Eng H* 225(9):857–65, 2011. PMID 22070023. DOI [10.1177/0954411911410642](https://doi.org/10.1177/0954411911410642). [摘要]
- **E15** Shah S, Kim SYR, Dubov A, Schemitsch EH, Bougherara H, Zdero R. The biomechanics of plate fixation of periprosthetic femoral fractures near the tip of a total hip implant: cables, screws, or both? *Proc Inst Mech Eng H* 225(9):845–56, 2011. PMID 22070022. DOI [10.1177/0954411911413060](https://doi.org/10.1177/0954411911413060). [摘要]
- **E16** Schileo E, Taddei F, Malandrino A, Cristofolini L, Viceconti M. Subject-specific finite element models can accurately predict strain levels in long bones. *J Biomech* 40(13):2982–9, 2007. PMID 17434172. DOI [10.1016/j.jbiomech.2007.02.010](https://doi.org/10.1016/j.jbiomech.2007.02.010). [摘要；人体尸体股骨]

---

## 4. 没能核实或没有采用的内容

- **任务清单里的 "Huang et al."**：我没能确定指的是哪一篇。检索到的同姓作者论文都是关于失效概率估计或等值线定位的，不是关于仿真运行失败的处理，所以没有引用。
- **取不到全文、只读了摘要的骨科论文**：B1、B2、B3、B4、B6、B8、B9、B11、B12、B13、B14。这些论文正文里可能有失败算例的说明，摘要里没有。Galloway 2013 的"328 例成功"对应的生成总数没有核实。
- **Forrester 等的书 §5.5 "Missing Data" 正文**没有读到，只确认了章节存在。对其填补方法的描述来自 A8 的摘要和 A7 的转述。
- **Burkhart 等 2013 的具体限值**（长宽比、Jacobian、内角）只有 D11 的二手转述。它关于沙漏能和质量缩放的限值没有找到任何可核对的出处。
- **沙漏能或人工应变能占内能的百分比经验值**（1%、1% 到 2%、10%）只在论坛和厂商二手材料里见到，没有在 Abaqus 原始文档里核实。
- **Viceconti 等 2005 的社论正文**、**Oefner 等 2021 的清单正文**、**ASME V&V 40 和 V&V 10 的标准正文**都没有读到，相关描述来自摘要、标准页面说明和 D4、D8 的转述。
- **Henninger 等 2010 的 "<5%" 那句话引的是哪篇文献**：取到的全文里引用标号被去掉了。参考文献表里有 Jones 和 Wilcox 2008，但不能确认就是它。
- **Lamé 压配公式在教科书里的出处**（常见于机械设计教材的压配一节）：公式是我从 Lamé 解推出来并用数值检查过的，教科书的章节和公式编号没有在本次核对。
- **NAFEMS R0081 报告本身**没有读到。CGS-10 的几何、材料和参考值只见到 Altair 手册的转述，而且那一页没有给单位和半径。
- **Gelbart 等 2014 的会议卷页**、**Celik 等 2008 的完整作者名单**、**Lee 等 2011 的期号和 DOI** 没有核实。
- **Abaqus 文档**读的是大学镜像站。2025 版镜像的页面不显示版本号；基准和验证手册读的是 2016 版镜像。
- **力平衡容差的文献惯例**：没有找到。
- **明确讨论"把数值失败错标为不可行会造成偏差"的文献**：没有找到，1.2 节相关两点是我的推论。
