**模型**：矩形悬臂梁，x = 0 端全部节点固支（U1 = U2 = 0），x = L 端全部节点经分布耦合（均匀权重）连到参考点，参考点加 z 向 −10 N。线弹性、小变形、隐式静力单步，软件默认求解与收敛设置（Erdemir 2012 仿真结构项）。

**网格**：gmsh 2D，二阶 6 节点三角形 CPS6M，单元尺寸 2.5, 1.25, 0.625, 0.3125 mm，边界节点由 mesh2d 共形重采样。

**解析解**：Euler–Bernoulli 端部挠度 PL³/(3EI)，I = t h³/12；Timoshenko 加剪切项 PL/(κGA)，κ = 5/6。

**流程**：`inp_writer.write_cantilever` 写 .inp → `run_abaqus.run_and_export` 调用 abq2025.bat 求解 → `abaqus/odb_export.py` 在 Abaqus 内置 Python 下只用标准库导 CSV → 本脚本读参考点 U2。并发测试把四个网格的 .inp 复制到新目录同时提交；确定性测试把最细网格再跑一次逐位比较。

**运行器的失败处理**：许可失败排队重试；求解器未启动的启动器瞬时故障（本阶段实测出现过一次：并发作业刚结束时 Abaqus 驱动加载 win32file DLL 遇到 Windows 文件锁）判为可重试，不记 L4；其余未完成作业记 L4 并保留原因。