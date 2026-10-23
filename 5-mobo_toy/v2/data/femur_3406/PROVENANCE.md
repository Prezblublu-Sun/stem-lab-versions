# v2/data/femur_3406 来源与变换（烘焙于 2026-10-23 17:05:22，gmsh 4.15.2）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
| `3406R_cortical.STEP` | `H:\projects\application\research-log\sawbone_3406_2026-10-23\churun_uncut_export\Cortical_AP214.STEP` | `63bac3ce9cf8a8cbda031420df6d34ba72b15f907a2b980b6d3c755748597752` | `9b1bf9494728c3533c9cd04db8669008c97dd88701ffea56cd7e12e6bd8cab1f` |
| `3406R_cancellous.STEP` | `H:\projects\application\research-log\sawbone_3406_2026-10-23\churun_uncut_export\Cancellou_AP214.STEP` | `416aba5430afabd5e13ecee189e912cf7ffa6994926eb9b4870824af801094f2` | `f478e1b4b5e79c2b52046ae578d377210a9f4e23efa0a1da0444d7c531969318` |

- 来源：Churun Lin 的未切割 Sawbones 3406（左股骨）Parasolid → 本机 SolidWorks 2025 转 STEP AP214（2026-10-23，见
  `H:/projects/application/research-log/sawbone_3406_2026-10-23/README_3406模型来源与核对_2026-10-23.md` 与 `churun_uncut_export/convert_log.txt`）。
- 变换：**只把 z 取反**，S = diag(1, 1, −1)，用 `gmsh.model.occ.affineTransform`；原生系 x 内侧、y 后方、z 远端（左股骨）
  ⇒ 烘焙后 x 内侧、y 后方、z 近端，并且左→右镜像。
- 为什么不用 README 的 A 系（x, −y, −z）：A 系是绕 x 转 180°，保持左股骨手性、+y 变成前方。计入哈希的代码假定
  右股骨且 +y 后方：`femur_real.landmarks` 取 argmax(y) 为后髁、前倾角符号 = −(u·ey)、`RealFemur.ant = (0, −1, 0)`，
  `model3d_v2.load_vector` 的 Bergmann → 模型符号也写死了 +y 后方（model3d_m1 按名导入同一函数）。A 系会让髁检测和载荷符号都错。
- 验收（重新导入）：皮质 271529.5 mm³ / 869 面，
  松质 128493.8 mm³ / 159 面；
  fragment(皮质, 松质) → 共享面 147 个（松质 159 面中），
  体积不变（271529.9 / 128493.8 mm³）。
  目标：271 529 / 127 952 mm³（±0.01 %）、869 / 155 面、147 个共享面。
- 原生体积：皮质 271529.4，松质 127956.2 mm³
  （gmsh 对裁剪 B 样条体积偏低约 4 %，与 SolidWorks 的 271.5 / 127.9 cm³ 一致）。
- 皮质壳是**开放**的（远端横销孔连通髓腔），无封闭的内膜空腔；松质芯（含头、颈）与皮质在同一坐标系，界面共形。
- **松质芯原件里有一条导针孔**（2026-10-23 发现）：半径 ≈ 2.29 mm、
  长 96.9 mm 的贯通孔，沿颈部从外侧皮质界面穿到头部芯表面
  （烘焙坐标 bbox [-14.5, -0.2, 71.0] …
  [71.4, 4.2, 122.2]，轴向
  [0.869, 0.007, 0.495] ⇒ 颈干角 ≈ 120°、前倾 ≈ 0°、离头心约 2 mm），
  由两张 97 × 4.4 mm 的条带面和两端的环面组成（gmsh 面号 [1, 153, 154, 155]）。
  泡沫芯没有这种孔：留着它，距离场在颈部多一道"墙"（模板化判穿透）、网格在柄旁留薄片。烘焙时在孔内并入一根圆柱
  （半径 2.49 mm，两端各退 0.3 mm 不伸进皮质）：
  松质体积 127951.9 → 128493.8 mm³
  （孔体积 542 mm³），
  面数 155 → 159；两端在皮质内表面下各留一个 ≤ 3 mm 深的盲窝（开口是斜的）。原件未动（research-log 里）。
- 数据不进 git（`.gitignore: v2/data/**/*.STEP`）；校验和在 `SHA256SUMS.txt`，`femur_3406.py` 的配置里也写死同样的 SHA256。
- 完整报告：`bake_report.json`。

## v2：扩孔再填（ream-and-refill）（烘焙于 2026-10-23 19:38:30，gmsh 4.15.2；`bake_3406.py --refill`）

| 输出 | 来源 | 来源 SHA256 | 输出 SHA256 |
|---|---|---|---|
| `3406R_cancellous_v2.STEP` | `H:\projects\application\research-log\sawbone_3406_2026-10-23\churun_uncut_export\Cancellou_AP214.STEP` | `416aba5430afabd5e13ecee189e912cf7ffa6994926eb9b4870824af801094f2` | `3455b8c9c21bb9f1eae62da357744b4ee1235939c8bc058fb29d0d109c0c7940` |
| `3406R_cortical.STEP`（不变，未重烘焙） | 同 v1 | 同 v1 | `9b1bf9494728c3533c9cd04db8669008c97dd88701ffea56cd7e12e6bd8cab1f` |

- 为什么：v1 的填孔圆柱两端各退 2.5 mm，在皮质内表面下留下两个盲窝，窝沿面与皮质内面以极小角度相交。
  S6（2026-10-23，`integration_2026-10-23/s6/s6_report.md` §4）发现 `model3d_v2.build_intact` 的 fragment(皮质, 松质) 在**头端孔口**
  （模型坐标约 (73.0, 0.4, 57.9)）碎片化出三个 0.01 mm 级顶点和三条 0.01 mm 级修剪曲线，皮质里生成 3 个 1.9e-9 mm³ 的退化四面体，
  被 `SLIVER_REL_TOL = 1e-7` 的门槛拒绝（L3）；换 HXT / 改 h 都在同一处失败，`occ.healShapes` 会把皮质壳撕成两个体。
  同一批设计建模里 6（皮质）/ 12（松质）个 1e-4 级薄片也来自孔口残留的 ≤ 0.05 mm² 碎面。
- 配方（`ream_refill()`，与 S6 的 `s6_fill_test.py` 相同）：在 v1 填孔之后，取同轴圆柱 T：半径 2.789 mm
  （= 填孔圆柱 2.489 + 0.3，即孔半径 2.29 + 0.5），
  两端各伸出孔口 4 mm（长 104.9 mm）；**芯 := (芯 − T) ∪ (T − 皮质实体)**。
  芯 − T 把填孔圆柱、两个盲窝和原件孔口的斜环面残片一起挖掉；T − 皮质实体落在骨内的那一块（2443.6 mm³，
  共 1 块中保留 1 块）两端恰好是皮质内表面的一部分：无盲窝、不与皮质重叠。
- 数字：松质体积 v1 128493.8 → 扩孔后 126172.3 → 再填后 128616.7 mm³
  （净增 **+122.9 mm³** = 两个盲窝；原件 127951.9，v1 填孔 +542）；
  面数 159 → 198；≤ 0.05 mm² 碎面 3 → 3
  （剩下的在 [[68.067, 1.61, 123.683], [-13.755, 2.121, 72.671], [-13.502, 4.033, 71.652]]，烘焙坐标）。
  重导入验收：松质 128616.7 mm³ / 198 面；fragment(皮质, 松质) → 1 + 1 个体，
  共享面 189（v1 147），皮质体积 271529.9（重导入 271529.5，即填充体没有伸进皮质）。
- 皮质 STEP 不变（SHA256 与 v1 相同，本次只核对，不重写）。校验和在 `SHA256SUMS_v2.txt`；完整报告 `bake_report_v2.json`。
- **默认仍是 v1**：`femur_3406.py` 的 `SHA256["cancellous"]` 与 `load_cfg()` 的路径未改；切换步骤（改路径 + SHA、换 SHA256SUMS、删哪些缓存）
  见 `H:/projects/application/research-log/sawbone_3406_2026-10-23/integration_2026-10-23/s1_rebake/SWITCHOVER.md`。
