# 造山带与海沟的格子平均地形

> 技术债 43 的物理依据与地球标定。引擎实现见 `docs/design/pipelines/geological-pipeline.md` §6.1（历史契约）、
> §7.1 第 1、2b、2c 步与 §7.2；设计理由与已否证方向见 `docs/design/proposals/orogen-topography.md`。
> 地球数字除特别说明外，均为 earth 根世界 20 万格网格（格距约 54 km）上 ETOPO 基岩的格子平均。

## 1 格子平均语义与亚格子起伏

一个格子需要三个量才能完整描述地形：平均高程、亚格子起伏与峰顶高程。GCM 的次网格地形参数化正是这样做的：
Lott & Miller（1997）按 Baines & Palmer（1990）给每格四个亚格子量（标准差 μ、各向异性、坡度、走向），并按
Wallace et al.（1983）把平均高程之上的若干倍 μ 解释为亚格子山峰的包络。重力换算的峰顶上限（地球 8848 m，
nacrea 8443 m）约束的是这个包络，不是平均高程：地球在 0.5° 网格上格子平均高程最高约 5.85 km，在 1° 网格上
约 5.41 km。

μ 有物理上限。活跃造山带 10 km 窗口内的局地起伏多在 1000–2000 m，起伏接近约 1500 m 时侵蚀率急剧上升，起伏
被阈值坡度限制；侵蚀跟不上时改由地壳性质限制并形成高原（Montgomery & Brandon 2002）。所以高原内部平均高程
很高但 μ 小，前楔前缘平均高程中等但 μ 大。

**标定**（观测拟合）：用 Copernicus 90 m DEM 完全覆盖的 2722 个陆地格（喜马拉雅—青藏、中安第斯、阿尔卑斯、
阿哈加尔、提贝斯提、阿巴拉契亚、大平原），对 ETOPO 格子平均坡度 S 拟合

  μ = c·Δx·S / (1 + c·Δx·S / μ_sat)，c ≈ 0.97，μ_sat ≈ 2.9 km（对数残差标准差 0.69，即每格约 2 倍）。

峰顶在平均之上的中位数为 3.5μ（GCM 包络口径的 2μ 偏低）；按此推算的地球最高峰 8190 m 落在珠峰所在格。

**TD 画布的峰顶上限在模型本身。** terrain-diffusion 的高程条件是 23 km 粗格的块平均。喜马拉雅画布无论用真实
23 km 块平均、54 km 平均均匀摊开还是双线性插值作条件，生成的最高点都约 5.9 km（真实 8.7 km）；安第斯约
4.7–4.9 km（真实 6.9 km）。格子平均语义不会降低画布峰顶。

## 2 留存缩短量与 Airy 增厚

大陆地壳增厚 ΔH 时，按 Airy 均衡地表抬升 h = ΔH·(ρm − ρc)/ρm。取 ρc = 2800、ρm = 3300 kg/m³，每抬升 1 km
需要增厚约 6.6 km（其中 5.6 km 为山根）。青藏高原平均约 5 km，对应在 35 km 参考地壳上增厚约 33 km，与接收
函数观测到的 70–80 km 地壳一致。

造山带内的地壳截面积 A = L_ret·H0 由留在造山带内的缩短量给出。碰撞型：

  L_ret = (min(L, 3000 km) − W_m − U·τ_b) × (1 − e) + φ·L_pre

- L 是碰撞以来积分的汇聚量，截在 3000 km（地球最大碰撞约 2500–3000 km）。
- W_m ≈ 180 km 是俯冲板块被吞没的减薄陆缘（阿拉伯陆缘，McQuarrie & van Hinsbergen 2013）；U·τ_b 是板片断离前
  被拖下的陆壳（Capitanio et al. 2010；Ingalls et al. 2016），τ_b 伊朗约 10 My、青藏约 25 My。
- e 是侧向逃逸比，由出口推出：上覆板块面向大洋的海沟按 Houseman & England（1993）的静岩压力侧边界以约四分之一
  压入速率外移；与正在远离的相邻板块之间的非汇聚边界取远离分量（安纳托利亚，Reilinger et al. 2006；印支，
  Tapponnier et al. 1982）。按段计算 e = Σ 出口速度 × 格距 × exp(−D/W) / (U·W)。青藏约 0.29（文献约 0.3，
  Replumaz & Tapponnier 2003）。
- φ·L_pre 是碰撞前安第斯型阶段的贡献。安第斯型边缘只有 φ·L。φ 在地球洋陆边缘上按汇聚量加权约 0.026，中位数
  约 0.015，中安第斯约 0.07，阿拉斯加与日本约 0.004；上覆板块朝海沟的速度只给出缩短速率的上界（Heuret &
  Lallemand 2005），中安第斯的异常需要板间摩擦（Sobolev & Babeyko 2005；Lamb & Davis 2003）。

**地球体积检验**（海拔 400 m 以上的造山带体积，Müller 2019 积分汇聚量作规定输入）：

| 情形 | 青藏 | 伊朗 | 安纳托利亚 | 中安第斯 |
|---|---|---|---|---|
| 观测（10³ km³） | 14 160 | 1528 | 587 | — |
| 现今速率 × 统一时长，f = 0.5 | +45% | 4.0 倍 | 5.4 倍 | — |
| 积分汇聚量，扣除陆缘与断离前俯冲 | +72% | +34% | 2.8 倍 | — |
| 再加按段计算的侧向逃逸 | +57% | −21% | −29% | — |
| 引擎实现（逐格留存缩短量，翼部 0.6°） | +9% | −25% | −14% | −29% |

## 3 平均高程上限与高原

造山带不能无限长高：山越高，抵抗重力所需的水平应力越大，超过岩石圈所能传递的力后，造山带改为向外扩展，平均
高程成为边界压应力的「压力计」（Molnar & Lyon-Caen 1988）；下地壳受热变弱后形成低坡度高原（Willett, Beaumont &
Fullsack 1993）。碰撞型上限由力平衡给出：Airy 补偿厚地壳在单位边界长度上的浮力

  ΔF(h) = ρc·g·h·(H0 + h·ρm / (2Δρ))

等于可传递的力 F_L（薄黏性板方程的浮力项，England & McKenzie 1982；Sonder & England 1986）。F_L 用青藏高原面
5.0 km 标定（约 7.1×10¹² N/m），nacrea（g = 10.28 m/s²）约 4.82 km；F_L 随应变速率 (U/W)^(1/n) 的变化未计入。
安第斯型上限受俯冲带界面剪应力限制（Lamb & Davis 2003），取阿尔蒂普拉诺 3.8 km 按 1/g 缩放（假设）。增厚量
超过上限时宽度增长以保持体积守恒，高原自然出现。

## 4 剖面

双向逆冲造山带的前楔维持最小临界楔角，后楔维持最大楔角，长大后回落到最小楔角（Willett et al. 1993；Davis,
Suppe & Dahlen 1983）。格子平均剖面的翼部坡度在地球上是：上覆侧 0.57–0.74°（青藏北缘 0.57°、安第斯东翼 0.74°），
俯冲侧两极（喜马拉雅前缘 2.81°，扎格罗斯 0.31°，阿尔卑斯北翼 0.43°），中位数约 0.6°。决定前缘陡缓的底部摩擦
与压入体强度需要岩性信息。

前陆挠曲的挠曲参数 α = [4D/((ρm − ρ_填充)·g)]^¼ 约 100 km（Te 50 km），与 54 km 格子同级；前陆盆地被沉积物填到
出口高度后只比相邻地台低 200–500 m（DeCelles & Giles 1996），对格子平均影响小。

## 5 海沟

海沟格子的平均深度等于俯冲板块的年龄深度加上断板挠曲在格子范围内的平均。俯冲板块在沟轴处断开、只受端部荷载：

  w(x) = −W0·e^(−x/α)·cos(x/α)，α = [4D/((ρm − ρw)·g)]^¼，D = E·Te³/(12(1 − ν²))

（Caldwell et al. 1976；Turcotte & Schubert 式 3.159）。外隆起高约 0.04·W0，在 π·α 处；地球格子平均的外隆起约
0.2 km，带弯矩的完整剖面 Wb/W0 约 0.1–0.25，端部荷载模型偏低。

- Te 与板龄几乎无关（15–40 km），因为弯曲断层与屈服削弱了板块（Craig & Copley 2014；Contreras-Reyes & Osses
  2010）；取 25 km，地球 α ≈ 65 km，随 g 按 g^(−¼) 变化。
- W0 取 2.0 km：ETOPO 沟轴格比同板块 250–450 km 外的海底低的中位数 1.17 km，按 54 km 接触格的平均因子 0.62
  反推约 1.9 km；文献典型 0.5–2.5 km。
- 地球格子平均：深于 6000/7000/8000 m 的海洋格子 1014/144/30 个；沟轴（边界 120 km 内最深格）中位数 −5788 m，
  最深一成 −8102 m；沟轴到陆地的距离第 10 百分位约 120 km，中位数 230 km。

## 6 弧前带

洋陆边缘上覆板块的前缘是骑在板片上的临界楔（Davis et al. 1983）。地球洋陆边缘上，上覆一侧的格子平均剖面从沟轴
格（中位数 −4.2 km）大致线性抬升，约 150 km 处到达海平面，回归坡度 1.55°；增生型约 0.9°（卡斯卡迪亚），侵蚀型
约 2.4°（中安第斯），差别由底部摩擦与沉积供给决定（Clift & Vannucchi 2004：汇聚快于约 6 cm/yr、海沟沉积薄于
1 km 时偏侵蚀）。沟轴到海岸的距离中位数 154 km（第 10 百分位 97 km）。中安第斯的山体从离沟轴约 150 km 起抬升。
板片在弧下的深度约 105 km（Syracuse & Abers 2006），弧沟距离约 240 km（Perrin et al. 2018）。

## 7 板内起伏

老造山带的衰减律见 `terrain_synthesis.md` §4.3，动力地形见同文 §4.3.1。地幔柱穹隆高 500–1200 m、宽 1000–1500 km
（Crough 1983）；King & Adam（2014）表 3：阿法尔宽约 1000 km、高约 0.9 km，霍加尔约 650 km、0.44 km，达尔富尔约
700 km、0.34 km，夏威夷约 1200 km、0.8 km；穹隆高度与浮力通量只弱相关。

## 8 参数与认识论类别

| 参数 | 取值 | 类别 | 标定域与不确定度 |
|---|---|---|---|
| ρc、ρm | 2800、3300 kg/m³ | 观测约束 | 地壳与上地幔平均密度，±3% |
| 参考地壳厚度 H0 | 35 km | 观测约束 | 地球大陆平均，±5 km |
| 被吞没的减薄陆缘宽度 W_m | 180 km | 观测拟合 | 阿拉伯陆缘；被动陆缘减薄带 150–200 km |
| 碰撞后陆壳俯冲时长 τ_b | 缺省 10 My | 观测拟合 | 伊朗约 10 My，青藏约 25 My（由体积反推） |
| 碰撞以来汇聚量上限 | 3000 km | 观测拟合 | 地球新生代碰撞 |
| 侧向逃逸比 e | 由出口推出 | 近似推导 | 被动出口四分之一压入速率；衰减长度取前缘长度为假设 |
| 安第斯型缩短比 φ | 缺省 0.026 | 观测拟合 | 地球洋陆边缘按汇聚量加权；逐边缘 0.004–0.07 |
| 平均高程上限 | 碰撞型力平衡（地球 5.0 km、nacrea 4.82 km）；安第斯型 3.8 km × 9.81/g | 近似推导加观测标定 | 强度系数暂取 1；1/g 标度为假设 |
| 翼部坡度 | 0.6° | 观测拟合 | 地球格子平均翼部坡度中位数；陡前缘类别未建 |
| μ 与坡度 | c 0.97，μ_sat 2.9 km，峰顶 3.5μ | 观测拟合 | Copernicus 90 m，每格约 2 倍误差 |
| 海沟 Te | 25 km | 观测拟合 | 地球海沟 15–40 km，与板龄无相关 |
| 沟轴下弯 W0 | 2.0 km | 观测拟合 | ETOPO 格子平均反推；文献 0.5–2.5 km |
| 弧前楔面坡度 α | 1.55° | 观测拟合 | 增生型约 0.9°，侵蚀型约 2.4° |
| 老造山带衰减时间 τ | 70 My | 观测拟合 | 含均衡回弹；范围 50–130 My |
| 老造山带残留脊线 h_r | 400 m | 观测拟合 | 地球约 300 My、未再抬升的老带 |
| 动力地形幅度 A | 水负载 800 m，陆上约 550 m | 观测拟合 | 地球残余地形二阶分量峰值 0.8 ± 0.1 km |

## 9 参考文献

- Baines, P. G., & Palmer, T. N. (1990). Rationale for a new physically based parametrization of
  subgrid-scale orographic effects. ECMWF Technical Memorandum 169.
- Burke, K. (1996). The African plate. *South African Journal of Geology*, 99, 339–410.
- Capitanio, F. A., Morra, G., Goes, S., Weinberg, R. F., & Moresi, L. (2010). India–Asia convergence driven by the subduction of the Greater Indian continent. *Nature Geoscience*, 3, 136–139.
- Caldwell, J. G., Haxby, W. F., Karig, D. E., & Turcotte, D. L. (1976). On the applicability of a
  universal elastic trench profile. *Earth and Planetary Science Letters*, 31, 239–246.
- Contreras-Reyes, E., & Osses, A. (2010). Lithospheric flexure modelling seaward of the Chile trench:
  implications for oceanic plate weakening in the trench outer rise region. *Geophysical Journal
  International*, 182, 97–112.
- Craig, T. J., & Copley, A. (2014). An explanation for the age independence of oceanic elastic thickness
  estimates from flexural profiles at subduction zones, and implications for continental rheology.
  *Earth and Planetary Science Letters*, 392, 207–216.
- Clift, P., & Vannucchi, P. (2004). Controls on tectonic accretion versus erosion in subduction zones:
  implications for the origin and recycling of the continental crust. *Reviews of Geophysics*, 42, RG2001.
- Crough, S. T. (1983). Hotspot swells. *Annual Review of Earth and Planetary Sciences*, 11, 165–193.
- Dahlen, F. A. (1990). Critical taper model of fold-and-thrust belts and accretionary wedges.
  *Annual Review of Earth and Planetary Sciences*, 18, 55–99.
- Davies, D. R., Valentine, A. P., Kramer, S. C., Rawlinson, N., Hoggard, M. J., Eakin, C. M., & Wilson,
  C. R. (2019). Earth's multi-scale topographic response to global mantle flow. *Nature Geoscience*, 12, 845–850.
- Davis, D., Suppe, J., & Dahlen, F. A. (1983). Mechanics of fold-and-thrust belts and accretionary
  wedges. *Journal of Geophysical Research*, 88(B2), 1153–1172.
- DeCelles, P. G., & Giles, K. A. (1996). Foreland basin systems. *Basin Research*, 8(2), 105–123.
- Egholm, D. L., Nielsen, S. B., Pedersen, V. K., & Lesemann, J.-E. (2009). Glacial effects limiting
  mountain height. *Nature*, 460, 884–887.
- Egholm, D. L., Knudsen, M. F., & Sandiford, M. (2013). Lifespan of mountain ranges scaled by feedbacks
  between landsliding and erosion by rivers. *Nature*, 498, 475–478.
- England, P., Houseman, G., & Sonder, L. (1985). Length scales for continental deformation in convergent, divergent, and strike-slip environments: analytical and approximate solutions for a thin viscous sheet model. *Journal of Geophysical Research*, 90(B5), 3551–3557.
- Hager, B. H., Clayton, R. W., Richards, M. A., Comer, R. P., & Dziewonski, A. M. (1985). Lower mantle
  heterogeneity, dynamic topography and the geoid. *Nature*, 313, 541–545.
- Hager, B. H., & Clayton, R. W. (1989). Constraints on the structure of mantle convection using seismic
  observations, flow models, and the geoid. In *Mantle Convection* (pp. 657–763). Gordon and Breach.
- Heuret, A., & Lallemand, S. (2005). Plate motions, slab dynamics and back-arc deformation. *Physics of
  the Earth and Planetary Interiors*, 149, 31–51.
- Hoggard, M. J., White, N., & Al-Attar, D. (2016). Global dynamic topography observations reveal limited
  influence of large-scale mantle flow. *Nature Geoscience*, 9, 456–463.
- Houseman, G., & England, P. (1993). Crustal thickening versus lateral expulsion in the Indian-Asian continental collision. *Journal of Geophysical Research*, 98(B7), 12233–12249.
- Ingalls, M., Rowley, D. B., Currie, B., & Colman, A. S. (2016). Large-scale subduction of continental crust implied by India–Asia mass-balance calculation. *Nature Geoscience*, 9, 848–853.
- Jamieson, A. J., Fujii, T., Mayor, D. J., Solan, M., & Priede, I. G. (2010). Hadal trenches: the
  ecology of the deepest places on Earth. *Trends in Ecology & Evolution*, 25(3), 190–197.
- King, S. D., & Adam, C. (2014). Hotspot swells revisited. *Physics of the Earth and Planetary
  Interiors*, 235, 66–83.
- Lamb, S., & Davis, P. (2003). Cenozoic climate change as a possible cause for the rise of the Andes. *Nature*, 425, 792–797.
- Lallemand, S., Heuret, A., Faccenna, C., & Funiciello, F. (2008). Subduction dynamics as revealed by
  trench migration. *Tectonics*, 27, TC3014.
- Leech, M. L. (2001). Arrested orogenic development: eclogitization, delamination, and tectonic collapse.
  *Earth and Planetary Science Letters*, 185, 149–159.
- Lott, F., & Miller, M. J. (1997). A new subgrid-scale orographic drag parametrization: its
  formulation and testing. *Quarterly Journal of the Royal Meteorological Society*, 123, 101–127.
- McQuarrie, N., & van Hinsbergen, D. J. J. (2013). Retrodeforming the Arabia-Eurasia collision zone: Age of collision versus magnitude of continental subduction. *Geology*, 41(3), 315–318.
- Molnar, P., & Lyon-Caen, H. (1988). Some simple physical aspects of the support, structure, and
  evolution of mountain belts. *GSA Special Paper*, 218, 179–207.
- Montgomery, D. R., & Brandon, M. T. (2002). Topographic controls on erosion rates in tectonically
  active mountain ranges. *Earth and Planetary Science Letters*, 201, 481–489.
- Oncken, O., Hindle, D., Kley, J., Elger, K., Victor, P., & Schemmann, K. (2006). Deformation of the central Andean upper plate system — facts, fiction, and constraints for plateau models. In *The Andes* (pp. 3–27). Springer.
- Perrin, A., Goes, S., Prytulak, J., Rondenay, S., & Davies, D. R. (2018). Mantle wedge temperatures and
  their potential relation to volcanic arc location. *Earth and Planetary Science Letters*, 501, 67–77.
- Pazzaglia, F. J., & Brandon, M. T. (1996). Macrogeomorphic evolution of the post-Triassic Appalachian
  mountains determined by deconvolution of the offshore basin sedimentary record. *Basin Research*, 8, 255–278.
- Pinet, P., & Souriau, M. (1988). Continental erosion and large-scale relief. *Tectonics*, 7, 563–582.
- Reilinger, R., et al. (2006). GPS constraints on continental deformation in the Africa-Arabia-Eurasia continental collision zone and implications for the dynamics of plate interactions. *Journal of Geophysical Research*, 111, B05411.
- Replumaz, A., & Tapponnier, P. (2003). Reconstruction of the deformed collision zone between India and Asia by backward motion of lithospheric blocks. *Journal of Geophysical Research*, 108(B6), 2285.
- Schellart, W. P. (2008). Overriding plate shortening and extension above subduction zones: a parametric
  study to explain formation of the Andes Mountains. *GSA Bulletin*, 120, 1441–1454.
- Sobolev, S. V., & Babeyko, A. Y. (2005). What drives orogeny in the Andes? *Geology*, 33, 617–620.
- Stephenson, S. N., Hoggard, M. J., Holdt, M. C., & White, N. (2024). Continental residual topography
  extracted from global analysis of crustal structure. *Journal of Geophysical Research: Solid Earth*, 129,
  e2023JB026735.
- Syracuse, E. M., & Abers, G. A. (2006). Global compilation of variations in slab depth beneath arc
  volcanoes and implications. *Geochemistry, Geophysics, Geosystems*, 7, Q05017.
- Tapponnier, P., Peltzer, G., Le Dain, A. Y., Armijo, R., & Cobbold, P. (1982). Propagating extrusion tectonics in Asia: New insights from simple experiments with plasticine. *Geology*, 10, 611–616.
- Turcotte, D. L., & Schubert, G. (2014). *Geodynamics* (3rd ed.). Cambridge University Press.
- Wallace, J. M., Tibaldi, S., & Simmons, A. J. (1983). Reduction of systematic forecast errors in the
  ECMWF model through the introduction of an envelope orography. *Quarterly Journal of the Royal
  Meteorological Society*, 109, 683–717.
- Watts, A. B., & Burov, E. B. (2003). Lithospheric strength and its relationship to the elastic and
  seismogenic layer thickness. *Earth and Planetary Science Letters*, 213, 113–131.
- Willett, S., Beaumont, C., & Fullsack, P. (1993). Mechanical model for the tectonics of doubly
  vergent compressional orogens. *Geology*, 21, 371–374.
