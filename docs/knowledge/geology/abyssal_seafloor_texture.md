# 深海底的小尺度地貌：深海丘陵、海山、破碎带与沉积覆盖

## 核心概念

洋底在几十千米以上的尺度由两条规律决定：洋中脊轴部的形态随扩张速率变化（见
`mid_ocean_ridge_morphology.md`），离开轴部后洋底按半空间冷却随年龄下沉。在 1 到 20 km 这个
频段，洋底的主体是**深海丘陵**（abyssal hills）。它们是洋壳在洋脊轴部附近由正断层和火山作用
形成的一列列长条状隆起，离开轴部后随板块整体搬走，形态被「冻结」下来，之后只被沉积慢慢掩埋。
深海丘陵是地球上分布最广的地貌，覆盖了大部分洋底。

这个频段在地球的全球测深产品里也基本是合成的。卫星测高反演重力只能分辨半波长约 6 km 以上的
结构，船测多波束覆盖的洋底只有约两成。SYNBATH（Sandwell 等 2022）因此在重力反演的测深上叠加了
一个统计合成的深海丘陵频段，参数取自洋底年龄、古扩张速率、古洋脊走向和沉积厚度。也就是说，
「真实地球的海底细节」在全球产品里本来就是按板块构造参数推出来的统计纹理，而不是观测值。

## 深海丘陵的统计模型

Goff 与 Jordan（1988）把深海丘陵描述为一个各向异性的冯·卡门随机场，二维功率谱为

$$P(\mathbf{k}) \propto H^2 \left[1 + u(\mathbf{k})^2\right]^{-(\nu+1)},\qquad
u(\mathbf{k})^2 = \left(\frac{k}{k_s}\right)^2\cos^2(\theta-\theta_s) + \left(\frac{k}{k_n}\right)^2\sin^2(\theta-\theta_s)$$

其中 k 与 θ 是波数矢量的模与方位角，θ_s 是丘陵走向的方位角，H 是均方根起伏，ν 是赫斯特数，
分形维数 D = 3 − ν。特征波数与报告用的特征宽度 λ_n（垂直走向）和特征长度 λ_s（平行走向）的换算是
k_n = 2√(2(ν+0.5))/λ_n，k_s 同理（Goff 与 Arbic 2010 式 1 到 4）。

Goff 与 Arbic（2010）汇编了 Goff 等（1997）的近洋脊测区平均值（全扩张速率 24 到 160 mm/yr），按形成时的
全扩张速率线性内插或外推给出未受沉积覆盖的参数。下表数值从其图 1 读出，读图误差约 5%：

| 全扩张速率与洋脊类型 | 均方根起伏 H | 特征宽度 λ_n | 长宽比 λ_s/λ_n |
|---|---|---|---|
| 约 26 mm/yr，中央裂谷型 | 约 235 m | 约 8.2 km | 约 3.3 |
| 约 35 到 39 mm/yr，中央裂谷型 | 约 200 到 220 m | 约 5.7 km | 约 2.6 到 3.0 |
| 约 74 mm/yr，中央裂谷型 | 约 170 m | 约 4.0 km | 约 6.0 |
| 约 75 mm/yr，过渡型 | 约 98 m | 约 3.1 km | 约 6.3 |
| 约 76 到 160 mm/yr，轴部高地型 | 约 57 到 62 m | 约 1.8 到 3.0 km | 约 5.1 到 6.6 |

规律有三条。第一，慢速扩张的丘陵更高、更宽，线状性也更弱（长宽比小）。第二，在中央裂谷型转为
轴部高地型的约 75 mm/yr 处，起伏与宽度有一个明显台阶，这与 `mid_ocean_ridge_morphology.md` 里约
80 mm/yr 的轴部形态转换是同一件事。第三，中央裂谷型一侧起伏随速率下降而增大，轴部高地型一侧与
速率基本无关。同一速率下各测区相对平均值的散布为：起伏约 20% 到 30%，宽度与长度约 30% 到 50%；
洋脊分段与洋壳厚度是次级因素。分形维数不随速率变化，未受沉积覆盖时取 D = 2.2，即 ν = 0.8。
走向 θ_s 取形成时的洋脊走向，也就是古扩张方向的法向。

沉积覆盖的修正采用 Webb 与 Jordan（2001）用扩散型远洋沉积模型得到的经验式，S 为沉积总厚度，
下标 0 表示未受覆盖的值：

- 起伏：H(S) = H₀ − S/2；当 S/2 ≥ H₀ 时 H = 0，即沉积厚于约两倍起伏时丘陵被完全掩埋。
- 宽度与长度：λ_n = λ_n0·(1 + 1.3·S/H₀)，λ_s 同式（λ_s 一式是 Goff 与 Arbic 的假设）。
- 分形维数：S/H₀ ≤ 0.1 时 D = 2.2 − 1.5·S/H₀，更厚时 D = 2.05。

扩张速率依赖的物理来源与洋脊轴部形态相同：慢速扩张时岩浆供应不足，洋壳主要靠正断层拉开，
断块起伏大；快速扩张时岩浆供应充足，断层间距和断距都小（Goff 1991；Small 1998）。这些关系的认识论
类别是观测拟合，标定域是地球全扩张速率约 24 到 160 mm/yr。独立测区可作散布参照：大西洋中脊南纬 31°
的一条 0 到 66 Ma 剖面（半扩张速率 13 到 32 mm/yr）测得起伏 57 到 142 m，与扩张速率的相关系数只有
−0.47，海山密度为每平方千米 0 到 0.033 座（Christeson 等 2020）。它的起伏低于上表同速率的平均值，
说明单条剖面可以落在散布区间的下沿。

## 海山

海山是板内或洋脊附近的火山锥，全球高于 1 km 的约有两万五千座（Wessel 等 2010 按测高数据外推）。SYNBATH 用高斯形状
h = h₀·exp(−r²/2σ²) 表达，宽度取 σ = 2.4·h₀（两者同为长度单位），并把最大坡度限制在约 0.25。
本库已有火山目录与固定建成翼坡（`volcanic_geometry.md`），海山的位置和体积应从热点轨迹和火山
目录推出，而不是另外撒点。

## 转换断层与破碎带

洋脊被转换断层分段，段间的错距把不同年龄的洋壳并在一起。由于洋底深度随年龄的平方根下沉，
两侧年龄差会在破碎带上产生一个深度台阶，台阶高度可以直接从已有的下沉律算出，不需要新参数。
破碎带走向平行于板块相对运动方向，因而也与深海丘陵走向垂直，这是地球洋底最显眼的方向纹理。

## 沉积覆盖与深海平原

远洋沉积持续累积，所以老洋底的丘陵比新洋底的更平缓；累积速率的量级（文献常引每百万年数米）尚未逐条核对来源，实现前需查证。靠近大陆边缘的盆地
另有浊流带来的陆源沉积，可以把丘陵整个填平成**深海平原**，坡度极缓（具体阈值实现前需查证）。深海平原的分布
因此取决于两件事：离陆源有多近，以及中间有没有洋脊或海沟拦截浊流。

## 与本库的关系

画布链的海底由 terrain-diffusion 生成。它的海底训练数据是 ETOPO1（格距约 1.85 km，本身大部分来自
重力反演），高程经过带符号平方根变换，海洋区也没有气候条件，所以模型在海底只学到了平滑的
大尺度形态，丘陵频段几乎为空。这是训练数据决定的结构性缺陷，加条件场无法补出数据里没有的频段，
另训模型也缺少足够的高分辨率海底样本。

本库的洋底年龄目前不是从板块运动学推出的等时线，而是按到最近离散边界与汇聚边界的距离比例插值
（`terrain_synthesizer.py` 的 `_compute_ocean_age_depth`）。深海丘陵的走向与起伏都需要洋壳形成时
的洋脊走向和扩张速率，所以先要有沿板块运动轨迹回溯的年龄和形成速率字段，纹理合成才有可推导的
输入。

海底高程不进 GCM，气候层对海洋格子取海平面，所以这类改动只影响地图观感与潮汐、洋流一类的诊断，
下游风险低。

## 不确定度与适用范围

- 起伏与宽度随扩张速率的关系来自地球测区统计，散布大，属于观测拟合；外推到岩浆供应显著不同的
  世界时应声明标定域。
- 合成纹理是统计意义上正确的随机场，不对应任何具体的真实丘陵；它只保证频谱、走向和起伏的
  空间分布与构造背景一致。
- 地幔柱附近的洋壳（如岩浆供应异常高的洋脊段）起伏偏小，不完全服从扩张速率关系。

## 参考资料

- Goff, J. A., & Jordan, T. H. (1988). Stochastic modeling of seafloor morphology: Inversion of Sea Beam data for second-order statistics. *JGR*, 93(B11).
- Goff, J. A. (1991). A global and regional stochastic analysis of near-ridge abyssal hill morphology. *JGR*, 96(B13).
- Goff, J. A., & Arbic, B. K. (2010). Global prediction of abyssal hill roughness statistics for use in ocean models from digital maps of paleo-spreading rate, paleo-ridge orientation, and sediment thickness. *Ocean Modelling*, 32, 36–43.
- Webb, H. F., & Jordan, T. H. (2001). Quantifying the distribution and transport of pelagic sediments on young abyssal hills. *Geophysical Research Letters*, 28(13).（经 Goff 与 Arbic 2010 转引）
- Christeson, G. L., 等 (2020). South Atlantic Transect: Variations in oceanic crustal structure at 31°S. *Geochemistry, Geophysics, Geosystems*, 21.
- Small, C. (1998). Global systematics of mid-ocean ridge morphology. In *Faulting and Magmatism at Mid-Ocean Ridges*, AGU Monograph 106.
- Sandwell, D. T., Goff, J. A., Gevorgian, J., 等 (2022). Improved bathymetric prediction using geological information: SYNBATH. *Earth and Space Science*, 9.
- Wessel, P., Sandwell, D. T., & Kim, S.-S. (2010). The global seamount census. *Oceanography*, 23(1).
- Timko, P. G., Arbic, B. K., Goff, J. A., 等 (2017). Impact of synthetic abyssal hill roughness on resolved motions in numerical global ocean tide models. *Ocean Modelling*, 112.
