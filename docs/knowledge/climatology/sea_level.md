# 海平面与气候

本文整理全球平均海平面随温度变化的物理、时间尺度，以及海平面变化反过来作用于气候的途径。海峡因海平面
变化而开合的水力学见 [ocean_currents.md](ocean_currents.md) §3。

## 1. 海平面变化的两个来源

### 1.1 冰量

陆地冰盖储存的水折算成海平面当量为

  Δη = (ρ_i / ρ_w) · V_ice / A_ocean

其中 ρ_i ≈ 917 kg/m³ 是冰的密度，ρ_w ≈ 1000 kg/m³（淡水口径），V_ice 是冰盖体积，A_ocean 是海洋面积。
海洋面积占比越大，同样的冰量对应的海平面变化越小。

冰盖厚度由底部剪应力决定。理想塑性冰盖（Vialov/Nye 剖面）的中心厚度为

  H ≈ √(2 τ₀ L / (ρ_i g))

τ₀ 是底部剪应力（约 50–100 kPa，观测拟合；Cuffey & Paterson 2010），L 是冰盖半宽，g 是重力加速度。因此体积随面积超线性增长，理论上
V ∝ A^{5/4}。实际冰盖的平均厚度变化不大：格陵兰约 1.7 km（约 2.9 × 10⁶ km³ 分布在约 1.7 × 10⁶ km² 上；Morlighem et al. 2017），
南极约 1.9 km（约 2.65 × 10⁷ km³ 分布在约 1.4 × 10⁷ km² 上；Fretwell et al. 2013）。粗估时可以用「平均厚度约 1.8 km ×
可结冰面积」，并按 H ∝ g^{−1/2} 修正重力。

能长冰盖的前提是高纬或高海拔存在陆地，并且积雪能全年不化。高纬陆地越多，冰量项越大；高纬几乎没有陆地的
行星，海平面对温度的敏感度会退化到只剩热膨胀和山地冰川。

### 1.2 热膨胀

  Δη_thermo ≈ α · ΔT_ocean · H_ocean

α 是海水热膨胀系数，随水温升高而增大（近 0 °C 时约 0.5 × 10⁻⁴ K⁻¹，20 °C 时约 2.5 × 10⁻⁴ K⁻¹），ΔT_ocean 是
全海深平均的升温，H_ocean 是平均海深。模型给出的两千年承诺值约为每开尔文全球升温 0.4 m，模型间区间约
0.2–0.6 m/K（Levermann et al. 2013）。

## 2. 地球上的数值

| 量 | 数值 | 口径与来源 |
|---|---|---|
| 两千年承诺海平面敏感度（合计） | 约 2.3 m/K | 热膨胀、山地冰川、格陵兰与南极冰盖之和；Levermann et al. 2013 |
| 其中热膨胀 | 约 0.4 m/K | 同上，近似线性 |
| 其中南极冰盖 | 约 1.2 m/K | 同上，近似线性 |
| 末次冰盛期海平面 | 约 −134 m | 接地冰比今天多约 5.2 × 10⁷ km³；Lambeck et al. 2014 |
| 末次冰盛期全球降温 | −6.1 K（95% 区间 −6.5 至 −5.7 K） | Tierney et al. 2020 |
| 冰期段的有效斜率 | 约 20 m/K | 由上两行相除，比间冰期附近陡一个量级 |
| 海平面与 CO₂ 的地质时间尺度关系 | S 形：冰期端很陡，冰盖全部消失后进入平台 | Foster & Rohling 2013 |
| 冰消期平均上升速率 | 约 12 m/kyr；融水脉冲 1A 期间至少 40 mm/yr | Lambeck et al. 2014 |
| 冰期内千年尺度波动 | 幅度可达 35 m，速率可达 2 cm/yr | Siddall et al. 2003 |

## 3. 时间尺度

- 热膨胀：上层海洋几十年，深海一到两千年才能达到平衡。
- 冰盖增长：取决于积累速率。地球上从冰期开始到冰盛期约 8–9 万年；按每年 0.1 m 水当量的积累，长成 1.8 km
  厚的冰盖约需 2 万年。
- 冰盖消融：约 1 万年即可完成。增长慢、消融快，冰盖体积对强迫存在滞回，这是冰期旋回呈锯齿形的原因之一
  （Abe-Ouchi et al. 2013）。

因此，周期短于冰盖增长时间的强迫只能驱动部分冰量响应，海平面摆幅小于平衡态估计。

## 4. 海平面变化对气候的反作用

- **陆架出露**：海退使陆架变成陆地，改变反照率和大陆度；高纬的出露陆架还能让冰盖继续扩张，形成正反馈。
- **海峡开合**：浅海峡的输运随门槛水深的 1.5–2 次方变化，海平面接近门槛时，海峡成为阈值开关，见
  [ocean_currents.md](ocean_currents.md) §3。
- **陆架碳与营养盐**：海平面下降时陆架有机质和磷被带入深海，提高生物泵效率，降低大气 CO₂（Broecker 1982）。

## 5. 在模型中的处理

PlaSim 与 ExoPlaSim 的海陆掩膜由输入的 `.sra` 文件给定，整个运行中不变；冰川模块只把全年不化的积雪标记为
冰川并抬高地形，不计算冰流，也不从海洋扣除水量（Fraedrich et al. 2005；Paradise et al. 2022）。所以在这类 GCM
中海平面只是边界条件：要研究海平面的影响，需要按新海平面生成掩膜后重跑。dreamulator 的做法是用
`scripts/climate/gcm/make_landmap.py` 从按新海平面重标的网格生成掩膜。

估算一个世界的海平面范围时，可以把 GCM 中全年积雪的陆地当作冰盖在平衡态下的可能范围，再乘以平均厚度并
加上热膨胀。由于 GCM 没有冰盖本身的高度和反照率反馈，这样得到的冷端是下限。

## 参考资料

- Abe-Ouchi, A. et al. (2013). Insolation-driven 100,000-year glacial cycles and hysteresis of ice-sheet volume. *Nature* 500. doi:10.1038/nature12374
- Broecker, W. (1982). Glacial to interglacial changes in ocean chemistry. *Prog. Oceanogr.* 11. doi:10.1016/0079-6611(82)90007-6
- Foster, G. & Rohling, E. (2013). Relationship between sea level and climate forcing by CO2 on geological timescales. *PNAS* 110. doi:10.1073/pnas.1216073110
- Cuffey, K. M. & Paterson, W. S. B. (2010). *The Physics of Glaciers* (4th ed.). Academic Press.
- Fraedrich, K. et al. (2005). The Planet Simulator: Towards a user friendly model. *Meteorol. Z.* 14. doi:10.1127/0941-2948/2005/0043
- Fretwell, P. et al. (2013). Bedmap2: improved ice bed, surface and thickness datasets for Antarctica. *The Cryosphere* 7. doi:10.5194/tc-7-375-2013
- Lambeck, K. et al. (2014). Sea level and global ice volumes from the Last Glacial Maximum to the Holocene. *PNAS* 111. doi:10.1073/pnas.1411762111
- Levermann, A. et al. (2013). The multimillennial sea-level commitment of global warming. *PNAS* 110. doi:10.1073/pnas.1219414110
- Morlighem, M. et al. (2017). BedMachine v3: Complete bed topography and ocean bathymetry mapping of Greenland. *GRL* 44. doi:10.1002/2017GL074954
- Paradise, A. et al. (2022). ExoPlaSim: Extending the Planet Simulator for exoplanets. *MNRAS* 511. doi:10.1093/mnras/stac172
- Siddall, M. et al. (2003). Sea-level fluctuations during the last glacial cycle. *Nature* 423. doi:10.1038/nature01690
- Tierney, J. et al. (2020). Glacial cooling and climate sensitivity revisited. *Nature* 584. doi:10.1038/s41586-020-2617-x
