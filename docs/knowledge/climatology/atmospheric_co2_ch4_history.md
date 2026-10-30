# 地球大气 CO2 与 CH4 的地质历史（世界构建参照）

> 2026-10-06 自 nacrea 路线 1 辐照重标定调研沉淀（nacrea 终案 pCO2 = 712 ppm
> 的历史类比核验 + 火山 CH4 温室把手评估）。用途：给架空世界的
> 大气组成设定提供「地球历史上什么时期长这样」的对照锚，以及碳循环第一性
> 标度律。温室物理基础见 `energy_balance.md`；晚型星宜居带约束见
> `../astrophysics/hz_inner_edge_cool_stars.md`。

## 1. 双气体框架：慢变量与快变量

| | CO2 | CH4 |
|---|-----|-----|
| 角色 | 慢变量（地质节律） | 快变量（生态/气候节律） |
| 主源 | 火山/变质脱气（~0.06-0.12 GtC/yr） | 生物产甲烷（湿地/肠道/厌氧沉积，~550 Mt CH4/yr 现代）+ 少量地质（蛇纹石化/热液，~1-5 Mt/yr） |
| 主汇 | 硅酸盐风化（碳酸盐-硅酸盐循环） | OH 氧化（有氧大气寿命 ~9-12 yr） |
| 大气滞留 | ~10⁵ yr（风化时间尺度） | ~10 yr |
| 辐射强迫 | ΔF = 5.35·ln(C/C₀) W/m²（Myhre 1998） | ΔF = 0.036·(√C−√C₀) W/m²，C 单位 ppbv |
| 分子效力 | 基准 | ~28-30×（100 yr GWP）；低浓度区效率最高（√律未饱和） |
| 稳态逻辑 | pCO2_ss = C₀·(V/W_eff)^(1/n)，n≈0.3-0.5——脱气率不确定度被 1/n≈2-3.3 次方放大 | burden = 源通量 × 寿命——**有氧世界里 CH4 浓度直接量度生物通量** |

推论（世界构建用）：氧化大气的行星上，气候显著的 CH4（>50 ppm）只能由
生物圈维持（需 10²-10³× 现代地球通量或低 O2）；**火山/非生物 CH4 上限仅
~0.01-0.05 ppm**（10-50 ppb：源 3-15 Mt/yr × 寿命 ~10 yr ÷ 载荷换算
2960 Mt/ppm；ΔT ≲ +0.2 K），只配当大气化学色彩，**不是温室把手**。
地球锚验证：现代 1.87 ppm = 5.5 Gt 载荷 = 550 Mt/yr × 9 yr ✓。要 CH4
温室 = 太古宙式无氧/低氧世界或产甲烷生物圈设定（类地生物圈量级的
产甲烷可支撑 0.3-2 ppm，即 +0.5-1.3 K 的微调档）。

## 2. CO2 地质历史（显生宙逐期 + 前寒武）

代理三类：硼同位素（有孔虫，海表 pH）、古土壤碳酸盐/铁氧化物（土壤
pCO2）、气孔密度/指数（陆生植物）。系统整合见 Steinthorsdottir et al.
2025（Treatise in Geochemistry 综述，引 Zachos 2008 与 Zhang 2020
PhanSST）与 CO2PIP 社区项目；新生代专篇 Hönisch et al. 2023（Science）。

| 时期 | pCO2 (ppm) | 气候态 | 备注 |
|------|-----------|--------|------|
| 太古宙（>2.5 Ga） | 10⁴-10⁵ 级（模型） | 弱太阳悖论下温和 | CO2+CH4 混合温室；碳酸盐-海水缓冲上限争议 |
| 寒武纪 | ~4000-7000（GEOCARB）；Franks 气孔约束 <2000 | 暖，无冰 | 高低估计之争 = 代理系统学问题（CO2PIP 在统一） |
| 奥陶纪 | ~2400-4500 → 末期 <1000 | 早暖晚冷 | 晚奥陶冰期与 CO2 跌破阈值同步（Royer 2006） |
| 泥盆纪 | ~1500-3000 → 末期下降 | 陆生植物崛起 → 风化加速 | 植物登陆 = 长期 CO2 泵开启 |
| 石炭纪 | **~400-800（低谷）** | **晚古生代大冰期** | 煤炭埋藏巅峰（木质素分解者未演化）= 碳汇极盛 |
| 二叠纪 | ~700-3000（波动大） | 冰期→回暖 | Breecker 2009 古土壤：晚期 >3000 之争 |
| 三叠纪-侏罗纪 | ~1000-2500 | 温室 | CAMP 大火成岩省（三叠纪末）瞬时脉冲 |
| 白垩纪 | ~600-2000（新综合偏 600-900 中段） | 热室高峰（中段 OAE） | 海底大火成岩省 + 快速洋壳扩张 |
| 古新世-始新世 | ~700-1800；**EECO ~50 Ma 1000-1600** | 最热（PETM 瞬时 >2000） | Hönisch 2023：51 Ma 峰 ~1600 |
| 始新世-渐新世界（33.9 Ma） | 跌破 **~600-750** | 南极冰盖建立 | CO2 阈值穿越的教科书案例 |
| 中中新世大暖期 MMCO（17-15 Ma） | **~500-700**（Guillermic 511±201） | +3-6°C，南极缩减 | **nacrea 712 ppm 的主类比档**（带 +1σ 上缘） |
| 上新世（4-3 Ma） | **~400-450** | +2-3°C，海平面 +5-25 m | 现代增暖的「最近似态」 |
| 第四纪冰期旋回（800 kyr 冰芯直测） | **180-280** 振荡 | 冰期-间冰期 | 与 CH4 350-800 ppbv 同相耦合（§3） |
| 工业革命前 | 280 | 间冰期 | — |
| 现代（2020s） | ~420 | 人为增暖 | 3 Myr 来最高 |

**跨期规律**：
1. **冰川阈值 ~500-750 ppm**（Royer et al. 2006：显生宙所有大冰期都在
   CO2 <1000 ppm 时发生，多数 <750）——低太阳常数时期阈值更低。
2. **热室需 >1000-1500 ppm**（显生宙尺度）。
3. 长期趋势 = 下降：陆生植物风化泵（泥盆纪起）+ 有机碳埋藏 + 太阳亮度
   渐增（+6%/Gyr）共同拉低 CO2 需求。
4. 瞬态脉冲（大火成岩省、PETM）叠加在慢趋势上，10⁴-10⁵ yr 衰减 =
   风化负反馈的响应时间。

## 3. CH4 地质历史

| 时期 | CH4 量级 | 机制/事件 |
|------|----------|-----------|
| 太古宙（3.5-2.5 Ga） | **100-1000+ ppm（有机霾假说）** | 产甲烷菌主导（无 O2、无 OH 汇）；CH4 霾防紫外但可致反温室降温（Zahnle/Catling-Kasting 系） |
| 大氧化事件 GOE（~2.4-2.2 Ga） | **崩塌至 <100 ppm** | O2 → OH 汇启动，CH4 温室塌缩——可能触发/加剧休伦冰期（「甲烷危机」） |
| 元古宙（2.2-0.8 Ga） | ~10-100 ppm（低 O2 缓冲） | 产甲烷持续但受硫酸盐/NOx 压制；雪球地球期进一步压低 |
| 显生宙氧化世界 | 基线 ~350-800 ppbv（生物湿地控制） | 与气候/湿地面积紧耦合 |
| 古生代缺氧事件（泥盆纪 Kellwasser、石炭-二叠过渡） | 可能 >1000-2000 ppbv（Rasmussen et al. 2012） | 广布缺氧水体 + 湿地 = 产甲烷极盛；高 CH4/低 O2 组合 |
| PETM（56 Ma） | 浓度无约束；δ¹³C −3‰ 全球负偏 | 甲烷水合物释放假说（¹³C 极轻碳源）——瞬态 <10 kyr |
| 第四纪（800 kyr 冰芯直测，EPICA/Vostok） | **冰期 350-400 / 间冰期 600-800 ppbv** | 热带-高纬湿地面积随冰量摆动；与 CO2、温度同相 |
| 全新世异常上升（~5 kyr 前起） | 580 → 700 ppbv | 农业（稻田/反刍）——Ruddiman「早期人类世」假说 |
| 工业革命前 / 现代 | 700-750 / ~1900 ppbv | 人为（化石燃料泄漏 + 农业 + 湿地扰动） |

**耦合振荡机制（第四纪范式）**：米兰科维奇节拍 → 高纬日照 → 冰量与
湿地面积 → CH4（快，百年-千年）与 CO2（慢，千年：南大洋通风/生物泵/
溶解度）同相响应 → 放大轨道强迫 ~2-3×。**CH4 是「冰期旋回的快指针」、
CO2 是「慢指针」**——冰芯里两条曲线与温度三者的相位关系是古气候学的
定标基石。

## 4. 火山-风化稳态与脉冲放大（世界构建标度律）

长期 pCO2 由脱气-风化平衡设定（§1 公式）。数值直觉（nacrea 案例标定，
2026-10-06）：

- 潮汐加热型火山（内热 4×⊕、板块 3×、扩张 2.4×）→ 脱气 2.5-4×⊕ ≈
  0.15-0.4 GtC/yr；冷凉气候风化折扣（f(T)~0.65）× 构造新鲜度红利
  （×1.3）→ W_eff ~2-2.5×⊕ → **稳态 pCO2 数百-数万 ppm，随参数在
  450-20,000 ppm 大带宽滑动**——设定侧要拿住的是「稳态落在目标气候
  所需 pCO2 附近」这条自洽线，而非单点数。
- **脉冲放大律**：脱气以周期 T_puls 振荡（幅度 ±A%），若风化响应时标
  τ_W = n×(库存/通量) ≪ T_puls，则 pCO2 准静态跟随：摆幅 ≈ (1±A)^(1/n)。
  n=0.3、±50% 脉冲 → pCO2 ×/÷3.9 → ΔF ±7 W/m² → **ΔT ±2-3 K 冰期旋回
  （火山驱动，非轨道驱动）**。低 pCO2 基座（数百 ppm）缓冲弱、放大最猛；
  高 pCO2 基座（万 ppm 级）反而钝化。谷值不得跌破无冰下限（雪ball 触发），
  这约束「平均脱气率 ≥ 脉冲谷值补偿」。
- 验证工具：ExoPlaSim carbonmod（`VOLCANCO2` 以地球脱气为单位、
  `NCARBON`/`NCO2EVOLVE` 开关）可直接数值积分该稳态与脉冲响应。
- **内部热流到脱气的标度。** 板块构造下洋壳生成与俯冲速率约正比于全球热流的平方，脱气随之变化，
  变质脱碳正比于热流的 1–2 次方（Sleep & Zahnle 2001）；以火山为主要散热方式的热管体制下，
  岩浆通量正比于热流（Moore & Webb 2013）。所以脱气 ∝ Q^a，a 取 1–2。
- **风化一侧的时间尺度。** 硅酸盐风化负反馈的响应时间约 17–38 万年（Colbourn、Ridgwell & Lenton
  2015），持续更久的脱气变化会让 pCO₂ 接近新的稳态。新鲜玄武岩只占大陆约 5% 却贡献大陆硅酸盐风化
  耗碳的 30–35%（Dessert 等 2003），所以大规模喷发之后风化能力本身会升高；造山抬升经物质供给加强
  风化，但时间尺度为百万到千万年，主要决定长期基线。
- **地球大灭绝的 CO₂ 尺度。** 三叠纪末中大西洋岩浆省每一次脉冲使 pCO₂ 约翻倍到三倍（Schaller、
  Wright & Kent 2011）；二叠纪末约 7.5 万年内从约 430 ppm 升到约 2500 ppm（Wu 等 2021），火山碳排放
  总量约 3.6 万 Gt 碳、峰值每年约 5 Gt（Cui 等 2021）。灭绝与 CO₂ 的快速上升相伴，长期偏高的 CO₂
  本身（如白垩纪）并不对应灭绝；对内部热流起伏的世界，灭绝的触发量应取热流或脱气相对前一段的
  升幅，而不是绝对值（nacrea 的应用见设计笔记 0014 §4）。

### 4.1 热流驱动的约化碳库存响应

潮汐火山背景下，可以用简化的脱气与风化库存方程估算长期 CO₂ 历史。
Valencia 等（2018）将潮汐构造、玄武岩更新与碳循环相联系；热管体制中岩浆散热与热流的线性标度
提供脱气变化的近似依据（Moore 与 Webb 2013）。单位岩浆含碳量与脱气效率固定时，
脱气比率 v 可近似取潮汐热流相对于参考值的比率。适用域是以岩浆输运为主要变化来源的背景。

新鲜玄武岩同时提供风化反应物。以地球玄武岩占大陆硅酸盐耗碳的份额 f_b 为参考，
可用 `w = 1 + f_b(v − 1)` 表达有效风化能力。f_b 取 0.30–0.35，
供给比例与风化能力同步变化属于情景近似；海底风化、岩石暴露年代及生物作用需要另行建模。
该假设与脱气近似共同定义热流的碳循环响应，世界的具体含碳量和反应效率作为输入保留。

Walker 型风化表达常用直接 CO₂ 指数约 0.3，以及约 13.7 K 的有效温度尺度，
后者包含温度和径流的气候响应（Penman 等 2020）。在气温随对数浓度的局部灵敏度为 λ 时，
有效指数可写为 `β = 0.3 + λ/13.7 K`。λ 由对应世界的气候快照估计，
全球均温灵敏度用于全球约化模型；显式空间风化应消费当地温度、径流与岩性。

令 r 为与大气浓度成比例的有效海洋与大气碳库存，可用
`dr/dt = (v − w r^β)/(βτ)` 表达源汇响应。
在参考态 r = v = w = 1 附近，该式的线性恢复时间为 τ。
τ 的参考量级为 17–38 万年；在暖期和新鲜岩石供给增加时，实际恢复速度随状态改变。
初始碳库存与一个现今浓度锚点确定归一化，历史峰谷由积分求出。
该模型的源、汇与库存变化可在归一化单位内闭合，绝对碳通量需要额外的库存及海洋分配资料。

这一近似用于合理的历史情景与时间尺度检查。它保持热流、岩浆脱气、风化能力和大气浓度的不同语义，
气候与海洋化学反馈的适用性按相应输入检验。

## 5. 世界构建速查（锚点表）

| 目标世界画像 | CO2 | CH4 | 地球历史类比 |
|--------------|-----|-----|--------------|
| 冰室-间冰期振荡世界 | 200-300 ppm | 400-800 ppbv | 第四纪 |
| 暖温带冰缘世界（**nacrea 终案档**：Ts ~11°C、海冰 ~20%） | **712 ppm**（450-800 窗口内） | 0.1 ppm（火山 30-50 ppb + 湿地生物 ~50 ppb 暂记，氧化大气） | 上新世/MMCO 的 CO2 + 凉化偏移（低光度恒星补偿） |
| 热室世界（无哺乳动物型生理压力） | 1000-2000 ppm | 湿地强化 | 白垩纪/EECO |
| 太古宙式有机霾世界 | 10⁴ ppm 级 | 100-1000 ppm | 太古宙（无 O2 前提） |
| 雪球逃逸中世界 | 0.1-1 bar（积累中） | 痕量 | 新元古代雪球后盖帽碳酸盐期 |

## 学术参考

- Steinthorsdottir, M., et al. (2025). Phanerozoic atmospheric CO2
  reconstructed with proxies and models. *Treatise in Geochemistry* (综述，
  含 Zachos 2008 / Zhang 2020 整合)。
- Zachos, J. C., et al. (2008). An early Cenozoic perspective on greenhouse
  warming and carbon-cycle dynamics. *Nature*, 451, 279.
- Hönisch, B., et al. (2023). Toward a Cenozoic history of atmospheric CO2.
  *Science*, 382, eadi5177.
- Royer, D. L., et al. (2006). CO2-forced climate thresholds during the
  Phanerozoic. *Geology*, 34, 545.（冰川阈值 <500-750 ppm）
- Franks, P. J., et al. (2014). New constraints on atmospheric CO2
  concentration for the Phanerozoic. *GRL*, 41.（气孔约束低值派）
- Breecker, D. O., et al. (2009). Atmospheric CO2 concentrations during
  ancient greenhouse climates were similar to those predicted for A.D. 2100.
  *PNAS*.（古土壤高值派）
- Zhang, X., et al. (2020). PhanSST / 显生宙海表温度与 pCO2 数据库；
  CO2PIP 社区整合项目（paleo-co2.org）。
- Catling, D. C., & Kasting, J. F. (2017). The Archean atmosphere (综述).
  *Science Advances* / PMC 7043912.（甲烷有机霾）
- Rasmussen, C. M. Ø., et al. (2012). 显生宙大气 CH4 与缺氧事件。
- EPICA Dome C 800 kyr CH4/CO2 冰芯记录（NOAA Paleoclimatology study 6093）；
  Sowers (2010) 同位素源解析；Delmotte et al. (2004) Vostok 四旋回。
- Archer, D. (2011). *The Long Thaw*. Princeton UP.（碳循环长时标命运）
- Myhre, G., et al. (1998). New estimates of radiative forcing due to CO2,
  CH4 and N2O. *GRL*, 25, 2715.（两条 ΔF 公式出处）
- Colbourn, G., Ridgwell, A., & Lenton, T. M. (2015). The time scale of the silicate weathering negative
  feedback on atmospheric CO2. *Global Biogeochemical Cycles*, 29, 583–596.
- Cui, Y., et al. (2021). Massive and rapid predominantly volcanic CO2 emission during the end-Permian
  mass extinction. *PNAS*, 118, e2014701118.
- Dessert, C., Dupré, B., Gaillardet, J., François, L. M., & Allègre, C. J. (2003). Basalt weathering laws
  and the impact of basalt weathering on the global carbon cycle. *Chemical Geology*, 202, 257–273.
- Moore, W. B., & Webb, A. A. G. (2013). Heat-pipe Earth. *Nature*, 501, 501–505.
- Schaller, M. F., Wright, J. D., & Kent, D. V. (2011). Atmospheric PCO2 perturbations associated with the
  Central Atlantic Magmatic Province. *Science*, 331, 1404–1409.
- Sleep, N. H., & Zahnle, K. (2001). Carbon dioxide cycling and implications for climate on ancient Earth.
  *JGR*, 106, 1373–1399.
- Wu, Y., et al. (2021). Six-fold increase of atmospheric pCO2 during the Permian–Triassic mass extinction.
  *Nature Communications*, 12, 2137.
- Ruddiman, W. F. (2003). The anthropogenic greenhouse era began thousands
  of years ago. *Climatic Change*, 61, 261.（全新世 CH4 农业上升）
- Valencia, D., Tan, V. Y. Y., & Zajac, Z. (2018). Habitability from Tidally Induced Tectonics.
  *The Astrophysical Journal*, 857, 106. [doi:10.3847/1538-4357/aab767](https://doi.org/10.3847/1538-4357/aab767)。
- Penman, D. E., Caves Rugenstein, J. K., Ibarra, D. E., & Winnick, M. J. (2020).
  Silicate weathering as a feedback and forcing in Earth's climate and carbon cycle.
  *Earth-Science Reviews*, 209, 103298. [doi:10.1016/j.earscirev.2020.103298](https://doi.org/10.1016/j.earscirev.2020.103298)。
