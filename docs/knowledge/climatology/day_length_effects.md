# 日长对天气与气候的影响

本文整理自转变慢、太阳日变长（数个地球日量级）时，短时天气与长期气候会出现哪些变化，以及
对同步绕行巨行星的卫星特有的两项光照效应（巨行星的食与巨行星辐射）。以 Nacrea（太阳日约
3.2 地球日，白天和黑夜各约 39 小时）为例给出量级，结论适用于太阳日为数天、但大气环流仍属
类地体制的世界。

## 1. 关键尺度

| 量 | 表达式 | 地球 | Nacrea |
|---|---|---:|---:|
| 自转角速度 Ω | 2π / 恒星日 | 7.29×10⁻⁵ s⁻¹ | 2.32×10⁻⁵ s⁻¹（0.32 倍） |
| 科氏参数 f（45°） | 2Ω sinφ | 1.03×10⁻⁴ s⁻¹ | 3.3×10⁻⁵ s⁻¹ |
| 惯性周期等于太阳日的纬度 | sinφ_c = 恒星日 /(2 × 太阳日) | 约 30° | 约 29° |
| 黑夜长度（赤道附近） | 太阳日 / 2 | 12 小时 | 约 39 小时 |

惯性周期等于太阳日的纬度 φ_c 在两个世界几乎相同，因为两者的太阳日都接近恒星日；
φ_c 由比值决定，与日长本身无关。

## 2. 短时天气

1. **日较差增大。** 黑夜越长，陆地持续辐射冷却的时间越长，晴夜的最低温越低；白天越长，地表
   与边界层的加热越充分。内陆、沙漠和高原的日较差会明显大于地球同类地区，中纬度晴夜结霜更
   常见；海面热容量大，日较差几乎不变。具体量级取决于地表热容量、湿度与云，需要输出周日变化
   的模拟来定量。
2. **对流与局地环流的日循环更强。** 长白天使午后对流更深、持续更久；长黑夜使逆温、辐射雾和
   冷空气湖持续更久。海陆风的线性理论（Rotunno 1983）表明，在日循环频率大于 f 的纬度带（即
   φ < φ_c），海陆风以重力波形式传播，能深入内陆很远；在 φ > φ_c 的纬度带，海陆风被惯性约束
   在海岸附近。
3. **惯性-周日共振。** 在 φ_c 附近，周日变化的风强迫与惯性振荡共振，夜间低空急流与海洋近惯性
   混合被放大（Shibuya、Sato & Nakanishi 2014）。惯性半周期在 φ_c 处等于半个太阳日，所以夜间
   边界层与地面解耦后，急流峰值出现在黎明前后；这一点在地球和 Nacrea 上同构。
4. **天气系统更大、更慢。** f 变小，罗斯贝变形半径按 1/f 增大（Nacrea 约为地球的 3 倍），气旋与
   反气旋的尺度更大、数量更少，斜压不稳定更弱。理想化水球实验中，热带气旋的尺度随自转变慢而
   增大，受莱因斯尺度约束（Chavas & Reed 2019）。

## 3. 长期气候

1. **数天的日长仍属快自转的类地体制。** 自转变慢的主要变化是云的分布、高度和厚度（Guzewich 等
   2020）；在 ROCKE-3D 的扫描中，宜居面积比例的极大值出现在恒星日为地球 8–32 倍处（Jansen 等
   2019）；更慢、直至同步自转时，日照面云量大增并开始主导气候（Komacek & Abbot 2019）。日长为
   数天时，最主要的变化是 Hadley 环流变宽（`atmospheric_circulation.md`）。
2. **硅酸盐风化可能接近最强。** Jansen、Scharf、Way & Del Genio（2019）用 ROCKE-3D 发现，类地
   行星的硅酸盐风化速率在自转周期约 4 天时达到最大，原因是降水与径流的分布随自转改变。风化是
   碳酸盐-硅酸盐恒温器的汇，风化越强，火山 CO₂ 的冲高被拉回得越快。这一结论来自单一模型的
   扫描，适合作定性论据。
3. **周日整流。** 对流、云与积雪对周日循环的响应是非线性的，周日变化的平均效应不等于日平均
   强迫的效应。数天量级的整流预计不大，需要输出周日变化的模拟确认。

## 4. 同步卫星特有的光照：巨行星的食与巨行星辐射

同步绕行巨行星的卫星，近巨行星半球始终看到巨行星停在天空同一位置，由此产生两项行星所没有的
光照效应（Heller 2012；Heller & Barnes 2013）：

- **巨行星的食。** 卫星穿过巨行星的阴影时恒星被遮。食只发生在卫星位于巨行星背后的轨道相位，
  此时向着恒星的正是近巨行星半球，所以食总是发生在近巨行星半球的当地正午附近，远半球不受
  影响。对全球的轨道平均日照，食最多减少约 6.4%（Heller 2012）；在约十个巨行星半径以外，
  食的影响可以忽略。
- **巨行星辐射。** 巨行星反射的星光（随巨行星相位变化，近巨行星半球的当地午夜为满相）与巨行星
  自身的热红外辐射照到近巨行星半球。卫星靠近巨行星时这项能量可达每平方米十瓦以上（Heller &
  Barnes 2013）。它削弱近巨行星半球的夜间降温，造成近、远两个半球日较差的不对称。

**Nacrea 的量级（粗估，用于判断是否值得建模）。** Aegis 半径 71,355 km，Nacrea 轨道半径约
723,300 km，(R/a)² ≈ 0.0097；Aegis 的 Bond 反照率 0.343。

| 项 | 估算 | 结果 |
|---|---|---|
| 食季内的日照损失 | 每个太阳日一次食，初亏到复圆约 2.45 小时，约占太阳日的 3% | 食季内全球平均日照少约 3% |
| 长期平均的日照损失 | 每 Aegis 年约 2 个食季，每季约 10 天，约占 20% 的时间 | 全球平均约 0.6%，约 1.9 W/m²（大气顶，全部落在近 Aegis 半球） |
| Aegis 热红外 | 只计 Aegis 吸收的星光再辐射约 206 W/m²，乘以 (R/a)²；若 Aegis 有类木星的内热，再乘约 1.7 | 近 Aegis 点约 2–3.4 W/m²，全球平均约 0.5–0.85 W/m² |
| Aegis 反射光 | 1254.9 W/m² × 0.343 × (R/a)² × 满相因子 2/3 | 近 Aegis 点满相时约 2.8 W/m²，全球平均约 0.35 W/m² |

两项在全球平均上大致抵消，但时空结构完全不同：巨行星辐射是近半球持续的、偏向夜间的加热；
食是近半球正午附近的间歇性冷却，集中在每年两个约 10 天的食季里，食季的次数还随卫星轨道面
约 10 年的进动在每年 5–9 次之间变化。

**现有模型的处理。** 主流三维 GCM（ExoPlaSim、ROCKE-3D、ExoCAM、Generic PCM）都没有现成的
卫星模块。已有的工作是：一维纬向能量平衡模型同时纳入了巨行星辐射与食（Forgan & Kipping
2013；Forgan & Yotov 2014；Forgan & Dobos 2016），并结合潮汐加热讨论卫星的宜居区（Dobos、
Heller & Turner 2017）；Haqq-Misra & Heller（2018）在理想化的 GFDL GCM 中加入了巨行星辐射，
发现它通过极地放大使卫星极区增暖，但没有纳入食（理由是对距离十个巨行星半径以外的卫星可以
忽略）。在 GCM 里同时模拟两者，需要修改辐射代码：按卫星的轨道相位和食季窗口给恒星通量加上
时间掩膜，并加一个方向固定、强度随相位变化的巨行星短波与长波源。

## 与项目的关联

- Nacrea 的 GCM 参照臂（`docs/usage/exoplasim-gcm.md`）开启了周日变化，但输出是约 10 个太阳日的
  平均，不保存周日统计；也没有模拟 Aegis 的食与辐射。气候引擎用常数 `sub_planet_warming_c`
  近似近 Aegis 半球的增暖，没有计入食的冷却（`docs/design/proposals/climate-layer-improvement.md`
  §7 的「卫星特有光照」一条）。
- 硅酸盐风化与潮汐热流的关系：nacrea 设计笔记 0014。
- 宽 Hadley 环流与弱斜压：`atmospheric_circulation.md`、nacrea 设计笔记 0008。

## 参考资料

- Chavas, D. R., & Reed, K. A. (2019). Dynamical aquaplanet experiments with uniform thermal forcing: System dynamics and implications for tropical cyclone genesis and size. *JAS*, 76, 2257–2274.
- Dobos, V., Heller, R., & Turner, E. L. (2017). The effect of multiple heat sources on exomoon habitable zones. *A&A*, 601, A91.
- Forgan, D., & Dobos, V. (2016). Exomoon climate models with the carbonate-silicate cycle and viscoelastic tidal heating. *MNRAS*, 457, 1233–1241.
- Forgan, D., & Kipping, D. (2013). Dynamical effects on the habitable zone for Earth-like exomoons. *MNRAS*, 432, 2994–3004.
- Forgan, D., & Yotov, V. (2014). The effect of planetary illumination on climate modelling of Earth-like exomoons. *MNRAS*, 441, 3513–3523.
- Guzewich, S. D., et al. (2020). The impact of planetary rotation rate on the reflectance and thermal emission spectrum of terrestrial exoplanets around Sun-like stars. *ApJ*（arXiv:2002.02549）.
- Haqq-Misra, J., & Heller, R. (2018). Exploring exomoon atmospheres with an idealized general circulation model. *MNRAS*, 479, 3477–3489.
- Heller, R. (2012). Exomoon habitability constrained by energy flux and orbital stability. *A&A*, 545, L8.
- Heller, R., & Barnes, R. (2013). Exomoon habitability constrained by illumination and tidal heating. *Astrobiology*, 13, 18–46.
- Jansen, T., Scharf, C., Way, M., & Del Genio, A. (2019). Climates of warm Earth-like planets. II. Rotational "Goldilocks" zones for fractional habitability and silicate weathering. *ApJ*, 875, 79.
- Komacek, T. D., & Abbot, D. S. (2019). The atmospheric circulation and climate of terrestrial planets orbiting Sun-like and M dwarf stars over a broad range of planetary parameters. *ApJ*, 871, 245.
- Rotunno, R. (1983). On the linear theory of the land and sea breeze. *JAS*, 40, 1999–2009.
- Shibuya, R., Sato, K., & Nakanishi, M. (2014). Diurnal wind cycles forcing inertial oscillations: A latitude-dependent resonance phenomenon. *JAS*, 71, 767–781.
