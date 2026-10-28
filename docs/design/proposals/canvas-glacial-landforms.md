# 画布的冰川地貌

> **定位**：全球画布链的冰川地貌提案。高清画布上看不到峡湾、冰蚀槽谷、冰斗与冰蚀湖。本提案在 TD 生成之后、
> 水文之前加一个冰川侵蚀阶段，用冰期历史在基岩上刻出这些地貌。条件场与山地形态见
> [canvas-conditioning-structure.md](canvas-conditioning-structure.md)；画布链的现行实现见
> [pipelines/canvas-chain.md](../pipelines/canvas-chain.md)；冰量与海平面见 nacrea 设计笔记 0016。
>
> **状态**：提案（2026-10-25 立项），未开工。大河二次侵蚀另立提案，它与本提案共用全局汇流（§4.6）。

---

## 1 问题

群内反馈指出，北极画布的海岸平滑，没有峡湾，也没有冰蚀槽谷。原因有三个。

1. **条件场里没有冰期历史。** TD 的五个条件通道是高程、气温、降水及其季节性，取的都是现在（712 ppm）的气候。
   冰川地貌是过去冰期留下的：地球上的挪威、苏格兰和加拿大东部现在是温带或亚寒带气候，地貌却是冰期刻出来的。
   TD 只看现在的气候，无法知道一处地方曾经被冰覆盖过。
2. **现有冰盖区给的是冰面。** 网格的 `elevation` 是包括冰在内的地表高程（基岩 = `elevation − ice_thickness_m`），
   所以画布在现有冰盖上画的是平滑的冰面。这在冰盖内部是对的，问题在冰盖以外。
3. **北极画布的起伏低。** 峡湾要靠冰流集中进已有的河谷才能刻出来（§3.2），起伏低的地方没有可以集中冰流的谷地。

所以要补的地貌集中在两类地方：冰期时被冰覆盖、现在已经解冻的地区，以及高山上的山岳冰川区。现有冰盖之下的基岩
地貌在画布上看不到，不是本提案的目标。

## 2 Nacrea 的冰期条件

下面的数字取自 GCM 存档（t42r 的 712 ppm 与 140 ppm 两档）和正典网格。

- **冰期的冷端。** 0016 把 140 ppm 取作正典范围的冷端。与 712 ppm 相比，全球年均地表气温低 8.4 K，
  北纬 55–70° 一带低约 11 K，南纬 60° 以南低 14–18 K。
- **冰覆盖范围。** 全年积雪的陆地在 712 ppm 下约 16 M km²，北半球最南到 54°N；在 140 ppm 下约 26 M km²，
  北半球最南到 52°N，南半球扩到 49°S。GCM 里没有冰盖自身的高度与反照率反馈，所以冷端范围是下限。
  两者之差约 10 M km²，主要是北极大陆南缘、北方内海沿岸、世界岛北部与暮光大陆。这一片就是冰川地貌最集中的地方。
- **山岳冰川。** 网格上有约 8 km 的高峰，低纬也有。GCM 的格点分辨不出山岳冰川，所以要在网格上用月气温、
  月降水与递减率计算平衡线高度（§4.1）。初步估算表明，冷端平衡线比现在低约 1000 m（中位数），高纬可达约 1700 m。
  这一步用的是粗糙的经验公式，在热带明显偏低，只用来判断量级；正式计算由 §4.1 完成。
- **冰期的历史长度。** 正典写明 Nacrea 的冰期由混沌的地热与 CO₂ 变化驱动，没有轨道主周期，冰盖与海冰
  在冰期之间进退但从未消失。冰期的累计时长没有正典值，它决定侵蚀深度（§4.3），需要作者给出（§8）。
- **地热。** 当代地表热流约 0.19 W/m²，约为地球大陆的两到三倍。冰床更容易达到融点，所以 Nacrea 的冰盖
  底部温暖、能够滑动并侵蚀的比例应高于地球（§4.4）。

## 3 物理与文献依据

### 3.1 冰流与侵蚀

冰川侵蚀模型共用一组方程（Braun 等 1999；Tomkin & Braun 2002；Herman & Braun 2008；Egholm 等 2009、2011）。

- **物质平衡**：b = min(β (s − ELA), b_max)。s 是冰面高程，ELA 是平衡线高度，β 是物质平衡梯度
  （0.005–0.01 /yr），b_max 是积累上限（1–2 m 冰/yr，应随降水变化）。
- **冰的连续方程**：∂H/∂t = b − ∇·q，H 是冰厚，q 是冰通量。
- **浅冰近似的冰通量**：q = −[2A/(n+2)] (ρg)ⁿ H^(n+2) |∇s|^(n−1) ∇s，再加滑动项 u_b·H。
  Glen 流动律指数 n = 3，速率因子 A 取温冰的值。
- **滑动律**：u_b = A_s τ_bᵐ，τ_b = ρgH|∇s| 是底部剪应力。
- **磨蚀侵蚀**：ė = K_g |u_b|^l。Hallet（1979）的理论给 l = 1；Herman 等（2015）在 Franz Josef 冰川的拟合给
  l ≈ 2、K_g ≈ 2.7×10⁻⁷（单位 m^(1−l) yr^(l−1)）。Harbor（1992）证明仅靠这条律就能把 V 形横剖面磨成 U 形。
- **拔蚀**（Egholm 等 2012）：作用在面向下游的台阶上，使冰斗底变平，形成小型湖盆。

浅冰近似不计相邻冰体的纵向应力，在陡峭地形上刻出的 U 形谷与悬谷不够好；用高阶冰流（Blatter 型）或它的
神经网络代理可以解决（Egholm 等 2011；Cordonnier 等 2023；Jouvet 等 2021）。

侵蚀速率的观测值：温冰川约 0.1–10 mm/yr，多数在 1 mm/yr 以上；极地冷冰川不超过 0.01 mm/yr（Hallet 等 1996）。
冰的几何形态在 10²–10³ 年内达到平衡，基岩的改造则要 10⁵ 年以上：把谷底刻深 100–500 m 大约需要 100–500 kyr
的冰覆盖，相当于一个到几个冰期旋回。

### 3.2 地貌的成因

- **峡湾**：冰盖向外流出时，冰流被已有的河谷吸引。滑动越快侵蚀越强，谷越深吸引的冰越多，这一正反馈在冰盖边缘
  切出峡湾（Kessler 等 2008）。所以峡湾的位置由已有水系与冰通量决定，不能随机放置。
- **冰川锯**：侵蚀集中在平衡线及其上方，山地的面积–高程分布在平衡线附近出现峰值，平均高程被压在平衡线附近
  （Brozović 等 1997；Mitchell & Montgomery 2006；Egholm 等 2009）。这也给 8–9 km 高峰附近的地形提供了一条约束。
- **冰斗**：位于流域源头、平衡线附近；冰斗底高程常被当作古平衡线的代用指标（Barr & Spagnolo 2015）。
- **过深槽与湖盆**：出现在支流汇合处、谷地收窄处和平衡线以下冰通量最大的地方，也出现在软弱岩带
  （Cook & Swift 2012）。
- **地盾冰蚀湖区**：冰盖剥去风化层，沿裂隙与岩性弱带掏出几十米深的湖盆，总侵蚀量只有约 10–100 m
  （Krabbendam & Glasser 2011；Krabbendam & Bradwell 2014）。这类地貌主要由构造与风化决定，不是冰流动力学问题。
- **简化模型**：Hergarten（2021）与 OpenLEM（Liebl 等 2023）把冰通量看作正物质平衡沿汇流树累积，由通量和坡度
  得出滑动速度，再套类似河流功率律的侵蚀律。计算量与河流汇流相同，是 O(N)，面向造山带尺度的网格。
  Deal & Prasicek（2021）给出冰川谷纵剖面的解析稳态解。

### 3.3 现有实现

| 实现 | 许可 | 语言与硬件 | 可处理规模 | 是否计算侵蚀 |
|---|---|---|---|---|
| Cordonnier 等 2023 | Inria 专有，只可阅读 | Python 与 PyTorch，GPU | 每次 2048²，64 m 格距，单卡约 6 小时 | 磨蚀、拔蚀、泥石流、河流 |
| IGM（Jouvet） | GPL-3.0 | Python 与 TensorFlow，GPU | 每卡约 10⁶–10⁷ 格 | 有，ė = K_g u_b² |
| iSOSIA（Egholm） | 未公开，需向作者索取 | C/C++ | 约 10⁵–10⁶ 格 | 有 |
| OpenLEM（Hergarten） | 仓库无许可文件 | C++ | 造山带尺度 | 有，冰川功率律 |
| PISM | GPL-3.0 | C++ 与 MPI | 千米级格距 | 无，只能事后由滑动估算侵蚀潜力 |
| Landlab、Fastscape、OGGM | 宽松许可 | Python 或 C++ | — | 没有冰川侵蚀组件 |
| Gaea、World Machine | 商业 | — | — | 冰川节点是启发式滤镜，不是物理 |

## 4 方案

### 4.1 第 0 步：平衡线与物质平衡场

在网格上用月平均气温与月降水计算物质平衡，现在（gcm-t42-712）与冷端（140 ppm 运行投到网格）各算一份。
方法用正度日模型：消融量正比于月正积温，积累量是气温低于阈值的月份的降水，两者之和为零的高度即平衡线，
气温按递减率外推到不同高度。度日因子在地球上标定：用 earth root 的观测气候（ERA5 气温、GPCP 降水）
计算平衡线，与冰川观测的平衡线比较。

这一步的产物是两张平衡线高度场与一张冷端冰覆盖掩膜。冷端掩膜应与 GCM 140 ppm 的全年积雪范围大体一致，
不一致处要找出原因再继续。第 2 节里粗糙公式给出的热带平衡线偏低，这一步要解决这个问题。

### 4.2 第 1 步：TD 自身的冰川地貌响应

在地球上取挪威、不列颠哥伦比亚与巴塔哥尼亚三个窗口，用真实的条件场生成 TD 画布，与 Copernicus 实测对比峡湾
与 U 形谷的指标（§5）。TD 学的是现在的地球，挪威的条件场对应的正是冰期刻出的地貌，所以这一步能看出 TD 在
条件合适时能画出多少冰川地貌，也就是后处理需要补多少。这一步复用条件场提案已有的地球对照工具，只需 GPU 时间。

### 4.3 第 2 步：冰川侵蚀原型

在两个 nacrea 窗口上比较两种方法：北极大陆南缘的一段海岸（冰盖边缘，峡湾的主要候选区）和一条中纬高山。

- **方法甲，汇流型冰川功率律（CPU）。** 按 Hergarten（2021）的思路，冰通量是正物质平衡沿汇流树的累积，
  滑动速度由通量与坡度得出，侵蚀用 ė = K_g u_b^l，再加 Harbor 型的横剖面整形（谷宽随通量变化）。
  计算量与河流汇流同级，可以在 180 m 甚至 90 m 上直接计算，并与大河提案共用汇流。代码按论文自行实现。
- **方法乙，高阶冰流代理（GPU）。** 用 IGM 作为外部工具，在 360 m 上计算冰流与侵蚀，把侵蚀量 Δz 上采样后
  加到 90 m 画布上。IGM 是 GPL，按 ExoPlaSim 的方式放在独立环境中调用，不进入仓库代码。

两种方法都用同一个气候时间表：平衡线在现在与冷端之间摆动，总的冰覆盖时长取作者给定值（§8）。冰期海平面按
0016 的冷端取 −46 m，侵蚀可以低于这一海平面，回到现在的海平面后，被淹没的冰蚀槽谷就是峡湾。

选哪种方法由第 3 步的地球验证决定，而不是由画面效果决定。

### 4.4 底部热状态

冷底冰几乎不侵蚀（Koppes 等 2015），所以侵蚀要乘一张底部是否达到融点的掩膜。底温由地表年均温、冰厚、
积累率与地热热流估算（一维稳态温度剖面）。地热取正典的当代热流 0.19 W/m²，这会让 Nacrea 的温底冰比例
高于地球。这是近似推导，不确定度主要来自冰厚与积累率。

### 4.5 第 3 步：地球验证与全量生产

地球验证在斯堪的纳维亚做：取第 1 步生成的 TD 画布，套用末次冰期的平衡线下降（约 1000 m 量级，取自文献重建）
与时长，经冰川侵蚀阶段后，与 Copernicus 实测比较 §5 的指标。验证通过后，对 nacrea 所有落在冷端冰覆盖或
山岳冰川区内的分块计算，输出新的画布根目录（只含侵蚀量 Δz 的分块，原画布不动），总览图与水文读取叠加后的高程。

被侵蚀的体积要记账。第一版只记录体积，不做沉积；冰碛与冰水沉积平原的分配放到后续版本，届时沉积进入同一本账。

### 4.6 与大河提案和水文的关系

冰川的冰通量与大河的流量都需要跨画布的全局汇流，应只建一次、两边共用。阶段顺序是：TD 生成，然后冰川侵蚀，
然后大河二次侵蚀，最后水文。冰川侵蚀改变了谷地与湖盆，水文必须在它之后。

## 5 验收

**科学验收**（地球，对 Copernicus 实测）：

- 谷地横剖面形状：拟合 y = a·xᵇ 的指数 b，U 形谷约 1.5–2.5，V 形谷接近 1（Harbor 1992 的口径）。
- 峡湾：长度、最大水深与口门门槛的分布。
- 面积–高程分布在平衡线附近的峰值位置（Egholm 等 2009）。
- 冰蚀湖密度：每万平方千米的湖盆个数与面积分布。
- 收敛性：方法乙的 360 m 与 180 m 结果的差异；侵蚀体积账的闭合。

**创作验收**：北极画布海岸出现峡湾与槽谷，群内反馈认可。两类验收分开记录，不互相替代。

## 6 认识论分类

| 量 | 类别 | 标定域与不确定度 |
|---|---|---|
| 冰流方程与 Glen 律 n = 3 | 守恒定律加观测拟合 | 实验室与野外，n 的不确定度约 ±0.5 |
| 侵蚀律 K_g、l | 观测拟合 | 只来自少数冰川，K_g 的不确定度达一个数量级 |
| 度日因子 | 观测拟合 | 地球冰川，按 §4.1 重新标定 |
| 冷端气候（140 ppm） | 模型派生 | GCM 无冰盖反馈，冰覆盖为下限 |
| 冰期累计时长 | 作者输入 | 正典没有给定，侵蚀深度近似与它成正比 |
| 底部热状态 | 近似推导 | 一维稳态，冰厚与积累率误差主导 |
| 横剖面整形（方法甲） | 近似推导 | Harbor 1992 的数值结果 |

## 7 不采用的方向

- Gaea、World Machine 一类的冰川滤镜：启发式，不依赖冰期历史，同一参数在所有地方画出同样的谷。
- 随机放置峡湾或冰斗模板：违背峡湾由已有水系与冰通量决定的机制。
- 在全大陆 90 m 上直接跑显式浅冰近似：时间步长为天级，计算量不可接受，而且浅冰近似刻不好 U 形谷。
- 直接使用 Cordonnier 等（2023）的代码：许可不允许产品化；它的思路通过 IGM 获得。
- PISM：千米级格距，没有侵蚀。
- 把冰期历史作为 TD 的新条件通道：TD 的条件通道是固定的五个，重新训练不在本项目范围内。

## 8 需要作者裁决的问题

1. **冰期累计时长。** 侵蚀深度近似与它成正比。建议默认取相当于 300 kyr 的冷端冰覆盖：地球第四纪后期的
   冰期旋回大约留下这一量级的冰覆盖，足以刻出几百米深的槽谷。也可以从正典的长期循环推出一个值。
2. **现有冰盖下的基岩。** 画布画的是冰面，冰下基岩看不到。是否另外导出一张基岩高程（用于冰盖消融的情景）？
   本提案默认不做。
3. **阶段归属。** 冰川侵蚀阶段放在画布生成一侧（与 `export canvas` 子命令组同处），水文一侧读取新的画布根目录。

## 9 参考文献

- Anderson, R. S., Molnar, P., Kessler, M. A. (2006). Features of glacial valley profiles simply explained. *JGR Earth Surface* 111, F01004. doi:10.1029/2005JF000344
- Barr, I. D., Spagnolo, M. (2015). Glacial cirques as palaeoenvironmental indicators. *Earth-Science Reviews* 151, 48–78. doi:10.1016/j.earscirev.2015.10.004
- Braun, J., Zwartz, D., Tomkin, J. H. (1999). A new surface-processes model combining glacial and fluvial erosion. *Annals of Glaciology* 28, 282–290.
- Brozović, N., Burbank, D. W., Meigs, A. J. (1997). Climatic limits on landscape development in the northwestern Himalaya. *Science* 276, 571–574. doi:10.1126/science.276.5312.571
- Cook, S. J., Swift, D. A. (2012). Subglacial basins: their origin and importance in glacial systems and landscapes. *Earth-Science Reviews* 115, 332–372. doi:10.1016/j.earscirev.2012.09.009
- Cordonnier, G., et al. (2023). Forming terrains by glacial erosion. *ACM Transactions on Graphics* 42(4). doi:10.1145/3592422
- Deal, E., Prasicek, G. (2021). The sliding ice incision model. *Geophysical Research Letters* 48. doi:10.1029/2020GL089263
- Egholm, D. L., et al. (2009). Glacial effects limiting mountain height. *Nature* 460, 884–887. doi:10.1038/nature08263
- Egholm, D. L., et al. (2011). Modeling the flow of glaciers in steep terrains: the integrated second-order shallow ice approximation (iSOSIA). *JGR Earth Surface* 116, F02012. doi:10.1029/2010JF001900
- Hallet, B. (1979). A theoretical model of glacial abrasion. *Journal of Glaciology* 23, 39–50.
- Hallet, B., Hunter, L., Bogen, J. (1996). Rates of erosion and sediment evacuation by glaciers. *Global and Planetary Change* 12, 213–235.
- Harbor, J. M. (1992). Numerical modeling of the development of U-shaped valleys by glacial erosion. *GSA Bulletin* 104, 1364–1375.
- Hergarten, S. (2021). Modeling glacial and fluvial landform evolution at large scales using a stream-power approach. *Earth Surface Dynamics* 9, 937–952. doi:10.5194/esurf-9-937-2021
- Herman, F., Braun, J. (2008). Evolution of the glacial landscape of the Southern Alps of New Zealand. *JGR Earth Surface* 113, F02009.
- Herman, F., et al. (2015). Erosion by an Alpine glacier. *Science* 350, 193–195.
- Jouvet, G., et al. (2021). Deep learning speeds up ice flow modelling by several orders of magnitude. *Journal of Glaciology*. doi:10.1017/jog.2021.120
- Kessler, M. A., Anderson, R. S., Briner, J. P. (2008). Fjord insertion into continental margins driven by topographic steering of ice. *Nature Geoscience* 1, 365–369. doi:10.1038/ngeo201
- Koppes, M., et al. (2015). Observed latitudinal variations in erosion as a function of glacier dynamics. *Nature* 526, 100–103.
- Krabbendam, M., Glasser, N. F. (2011). Glacial erosion and bedrock properties in NW Scotland. *Geomorphology* 130, 374–383. doi:10.1016/j.geomorph.2011.04.022
- Krabbendam, M., Bradwell, T. (2014). Quaternary evolution of glaciated gneiss terrains. *Quaternary Science Reviews* 95, 20–42. doi:10.1016/j.quascirev.2014.03.013
- Liebl, M., et al. (2023). Exploring the potential of the stream-power approach for glacial landform evolution (OpenLEM). *Geoscientific Model Development* 16, 1315–1343. doi:10.5194/gmd-16-1315-2023
- Mitchell, S. G., Montgomery, D. R. (2006). Influence of a glacial buzzsaw on the height and morphology of the Cascade Range. *Quaternary Research* 65, 96–107. doi:10.1016/j.yqres.2005.08.018
- Tomkin, J. H., Braun, J. (2002). The influence of alpine glaciation on the relief of tectonically active mountain belts. *American Journal of Science* 302, 169–190.
