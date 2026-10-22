# 潮汐加热的热流尺度、宜居界限与生物影响

本文整理潮汐加热（以及其他内部热源）对行星表面与生物圈影响的数量级知识：用什么尺度衡量热流，
文献给出的宜居上下限，内部热流如何通过火山与碳循环影响气候，以及地球大火成岩省与大灭绝的
对应关系。最后一节说明如何从有限长度的模拟估计「多久出现一次某强度的事件」。

## 1. 热流尺度

| 天体 | 全球平均表面热流 | 来源 |
|---|---:|---|
| 地球 | 约 0.09 W/m²（全球约 46 TW） | Davies & Davies 2010 |
| 木卫一（Io） | 约 2–2.5 W/m² | Lainey 等 2009（天体测量反演的潮汐耗散） |

地球的热流主要来自放射性衰变与原始热的冷却，潮汐的贡献可以忽略；Io 的热流几乎全部来自潮汐，
表面被火山持续重铺。架空世界的内部热流通常以这两个点为标尺，例如「约 6 倍地球」「约 0.3 倍 Io」。

内部热流作为直接的地表能量输入一般很小：1 W/m² 只相当于日照的百分之一量级。但它可以和
温室气体的辐射强迫相比，CO₂ 倍增的强迫约 3.7 W/m²（Myhre 等 1998）。所以热流从 0.4 升到
2 W/m² 时，直接加热相当于 CO₂ 倍增强迫的约一半；更大的影响往往来自火山脱气改变大气成分。

## 2. 文献中的宜居界限

| 界限 | 数值 | 含义 | 来源与认识论类别 |
|---|---:|---|---|
| 上限 h_max | 约 2 W/m² | 达到 Io 水平时，地表重铺太快，很可能阻止生物圈形成 | Barnes 等 2009 的工作假设，以 Io 为锚；Jackson、Barnes & Greenberg 2008 用同一量级讨论系外行星 |
| 下限 h_min | 约 0.04 W/m² | 低于它板块构造可能停止，参照火星 | Barnes 等 2009 的工作假设 |
| 失控温室 | 数百 W/m² | 潮汐加热本身足以触发失控温室 | Barnes 等 2013 |
| 宜居卫星的加热与光照联合约束 | — | 卫星的潮汐加热与恒星、行星光照共同决定是否越过失控温室门槛 | Heller & Barnes 2013 |

h_max 与 h_min 都不是观测定论，而是以太阳系天体为锚的经验界限。2 W/m² 的含义是「长期维持在
这个水平，地表很难保持稳定的复杂生态」，不是「一越过就立即灭绝」。

## 3. 生物影响的分级

文献只给出两个可靠节点：地球约 0.09 W/m² 对应正常的地表生物圈，Io 级约 2 W/m² 对应宜居上限。
下面的中间档是在这两点之间按对数插值，再借地球地质记录定性描述，属于**定性插值**，用于叙事
分级，不是物理推导：

| 等级 | 热流 | 对生物的含义 |
|---|---|---|
| 0 级，地球式 | 约 0.1 W/m² | 火山活动局部、间歇 |
| 1 级，增强 | 0.1–0.5 W/m² | 火山与热液明显更活跃，热液生态丰富，生物以适应为主 |
| 2 级，高 | 0.5–1.0 W/m² | 火山常态化，区域性扰动频繁，物种更替偏快，没有持续的全球危机 |
| 3 级，很高 | 1.0–2.0 W/m² | 相当于大火成岩省规模的活动持续数十万年；变暖、海洋酸化与缺氧风险显著；高热时期开始时有灭绝脉冲的风险 |
| 4 级，Io 级 | 2.0 W/m² 以上 | 超出文献的宜居上限，地表频繁重铺，复杂地表生命面临灭绝级风险 |

同一热流的冲击大小还取决于热量释放方式：以海底扩张与热液为主时冲击较小，以陆上溢流玄武岩
的脉冲喷发为主时冲击较大。

## 4. 地球类比：大火成岩省与大灭绝

- 地球显生宙（约 5.4 亿年）有五次大灭绝（Raup & Sepkoski 1982），平均约每 1 亿年一次。
  灭绝规模越大越稀少：Raup（1991）用「杀灭曲线」描述灭绝比例与平均等待时间的关系，大多数
  时间段的灭绝风险很低，极少数时段集中了大部分灭绝。
- 多次大灭绝与大火成岩省喷发在时间上高度吻合（Wignall 2001；Bond & Wignall 2014；Ernst &
  Youbi 2017）。二叠纪末西伯利亚暗色岩的岩浆活动跨越灭绝前后（Burgess & Bowring 2015）。
- 并非每个大火成岩省都引起大灭绝，结果取决于喷发速率、释放的挥发物和被岩浆加热的围岩
  （例如煤层与蒸发岩）。
- 恢复很慢：二叠纪末灭绝之后，变暖、酸雨、海洋酸化和缺氧在 5–6 百万年里反复出现，少数类群
  在 1–3 百万年内快速分化，但稳定、复杂的生态系统直到危机后 8–9 百万年才重新出现（Chen &
  Benton 2012）。

所以对一个内部热流会周期性升高的世界，关键量不只是热流峰值，还有高热时期的间隔与生物圈恢复
时间的比较：如果高热时期的间隔（例如数十万年）远短于完整恢复所需的数百万年，生物圈可能长期
处于未完全恢复的状态。

## 5. 从有限模拟估计事件频率

长期轨道积分通常只能覆盖百万年量级，而灭绝级事件的间隔是亿年量级。用有限长度的记录估计
「某强度的事件多久来一次」，标准工具是极值统计（Coles 2001）：

- **重现期与重现水平。** 把时间序列切成等长的块，取每块的最大值，拟合广义极值分布（GEV）；
  或者统计超过某个高阈值的事件，拟合广义帕累托分布。由此得到「重现期 T 内期望出现一次的
  最大值」，也就是重现水平。
- **尾部类型决定外推。** GEV 的形状参数 ξ 区分三类尾部：ξ = 0（Gumbel 型，指数类尾部）时重现
  水平随 ln T 增长；ξ < 0 时存在上界，重现水平随 T 饱和；ξ > 0 时是重尾，重现水平按幂律增长。
  外推到远超数据长度的重现期时，结果几乎完全由 ξ 决定。
- **适用条件。** 记录要大致平稳（去掉初始的爬升期），块与块之间要近似独立（块长大于去相关
  时间），并且外推倍数通常只取数据长度的几倍。如果过程还有更慢的分量（例如整体水平以更长的
  时间尺度漂移），有效的独立样本数由慢分量决定。
- **补足样本。** 平行运行多个只差微小初值扰动的成员（集合运行），比延长单条轨迹更快地增加
  独立样本；有物理机制时，先用记录拟合一个符合机制的随机模型，再用蒙特卡洛外推，比纯曲线
  拟合更可靠。

## 6. 加热的空间分布与热管火山

潮汐加热在天体内部并不均匀。Beuthe（2013）证明，球对称分层天体内的耗散功率是三个角函数 Ψ_A、Ψ_B、Ψ_C 的
线性组合：角函数只由潮汐势决定，权重由内部结构决定。三个角函数由潮汐势模平方 |Φ|² 的 0、2、4 阶球谐分量
组合而成：Ψ_A = Ψ₀ + Ψ₂ + Ψ₄，Ψ_B = Ψ₀ + Ψ₂/2 − 2Ψ₄/3，Ψ_C = Ψ₀ − Ψ₂ + Ψ₄/6。耗散位置不同，主导的角函数
也不同：

- **深部地幔**（液核之上）：偏心率潮下加热集中在两极（Segatz et al. 1988；Beuthe 2013）。
- **软流圈薄层**（贴着更硬的一层的软弱层，例如上地幔的部分熔融层）：径向与切向之间的剪切主导，加热接近图样 B。
  偏心率潮下极大在赤道附近，这是木卫一火山分布的主流解释。

**哪种潮主导。** 同步自转卫星的总耗散功率正比于 21/2·e² + 3/2·sin²ψ（e 为偏心率，ψ 为自转轴与轨道法线的
夹角；Beuthe 2013 式 42）。偏心率很小而 ψ 不可忽略时，倾角潮主导。

**倾角潮的图样 B。** 取 x 指向主星（向星点）、y 沿自转轴，倾角潮势正比于 x·y。代入上面的组合，按全球平均归一后，
软流圈薄层的加热是

  Ĥ = 2.5·(x² + y²) − 10·x²·y²

它在向星点、背星点与南北两极都取极大值 2.5，在与主星成 90° 的赤道上为零，向星子午线上纬度 ±45° 处也为零。图样
很宽：Ĥ 大于 1 的区域约占半个球面。

**热管火山。** 热流超过板块传导能力时，多出的热由岩浆平流带出，称为热管（Moore & Webb 2013）。每排出 1 W/m²
约生成每百万年 5 km 的岩层（岩浆密度 3000 kg/m³，每千克从熔融冷却到地表带出约 2 MJ）。木卫一是唯一观测到的
热管天体，它给出三个可用的标定：

- 全球热流约 1.0×10¹⁴ W（Veeder et al. 2012），经约 417 个火山口排出（Radebaugh et al. 2001），每口约
  2.4×10¹¹ W；
- 盾状火山起伏小于 3 km、侧翼坡度 0.2–0.6°（Schenk et al. 2004），熔岩黏度低、铺得很远；
- 每年重铺约 1 cm，却没有与加热极大对应的高原：持续重铺的地壳处于稳态，新岩层掩埋旧层，旧层在底部重熔或
  拆沉返回地幔。

## 与项目的关联

- nacrea 的潮汐热流统计、生物影响评估与灭绝频率外推：nacrea 设计笔记 0014。
- 卫星自转-轨道失配如何决定潮汐热流：`docs/knowledge/astrophysics/satellite_system_stability.md` §10。
- 热管火山省的实现（加热图样、潮汐热流时间线、喷口与盾状火山）：`src/dreamulator/map/heat_pipe.py` 与
  `map/island_catalog.py`，设计见 `docs/design/proposals/island-catalog.md`。
- 火山 CO₂ 的地质历史框架：`docs/knowledge/climatology/atmospheric_co2_ch4_history.md`。

## 参考资料

- Barnes, R., Jackson, B., Greenberg, R., & Raymond, S. N. (2009). Tidal limits to planetary habitability. *ApJ*, 700, L30.
- Barnes, R., Mullins, K., Goldblatt, C., et al. (2013). Tidal Venuses: Triggering a climate catastrophe via tidal heating. *Astrobiology*, 13, 225.
- Beuthe, M. (2013). Spatial patterns of tidal heating. *Icarus*, 223, 308–329.
- Bond, D. P. G., & Wignall, P. B. (2014). Large igneous provinces and mass extinctions: An update. *GSA Special Paper*, 505.
- Burgess, S. D., & Bowring, S. A. (2015). High-precision geochronology confirms voluminous magmatism before, during, and after Earth's most severe extinction. *Science Advances*, 1, e1500470.
- Chen, Z.-Q., & Benton, M. J. (2012). The timing and pattern of biotic recovery following the end-Permian mass extinction. *Nature Geoscience*, 5, 375.
- Coles, S. (2001). *An Introduction to Statistical Modeling of Extreme Values*. Springer.
- Davies, J. H., & Davies, D. R. (2010). Earth's surface heat flux. *Solid Earth*, 1, 5.
- Ernst, R. E., & Youbi, N. (2017). How Large Igneous Provinces affect global climate, sometimes cause mass extinctions, and represent natural markers in the geological record. *Palaeogeography, Palaeoclimatology, Palaeoecology*, 478, 30–52.
- Heller, R., & Barnes, R. (2013). Exomoon habitability constrained by illumination and tidal heating. *Astrobiology*, 13, 18–46.
- Jackson, B., Barnes, R., & Greenberg, R. (2008). Tidal heating of terrestrial extrasolar planets and implications for their habitability. *MNRAS*, 391, 237.
- Lainey, V., Arlot, J.-E., Karatekin, Ö., & van Hoolst, T. (2009). Strong tidal dissipation in Io and Jupiter from astrometric observations. *Nature*, 459, 957.
- Moore, W. B., & Webb, A. A. G. (2013). Heat-pipe Earth. *Nature*, 501, 501–505.
- Myhre, G., Highwood, E. J., Shine, K. P., & Stordal, F. (1998). New estimates of radiative forcing due to well mixed greenhouse gases. *GRL*, 25, 2715.
- Radebaugh, J., et al. (2001). Paterae on Io: a new type of volcanic caldera? *JGR*, 106, 33005–33020.
- Raup, D. M. (1991). A kill curve for Phanerozoic marine species. *Paleobiology*, 17, 37–48.
- Raup, D. M., & Sepkoski, J. J. (1982). Mass extinctions in the marine fossil record. *Science*, 215, 1501–1503.
- Schenk, P. M., Wilson, R. R., & Davies, A. G. (2004). Shield volcano topography and the rheology of lava flows on Io. *Icarus*, 169, 98–110.
- Segatz, M., Spohn, T., Ross, M. N., & Schubert, G. (1988). Tidal dissipation, surface heat flow, and figure of viscoelastic models of Io. *Icarus*, 75, 187–206.
- Veeder, G. J., et al. (2012). Io: Volcanic thermal sources and global heat flow. *Icarus*, 219, 701–722.
- Wignall, P. B. (2001). Large igneous provinces and mass extinctions. *Earth-Science Reviews*, 53, 1.
