# 太阳系无生命天体的气候划分——学界实践调研（UCC v2 参照目标）

> 日期：2026-09-21 ｜ 性质：deep-research 证据文档（2026-09-24 自 private/reviews 迁入库）。
> 方法：五路并行文献调研（Mars / Titan / Venus / Moon-无大气 / 通用框架），每条文献至少抓到
> 摘要级核验；禁止编造，负结果如实记录。完整证据文件（含检索日志、判据原文全引、抓取渠道与
> 失败路径）在 `private/reviews/_research/ucc-taxonomy-{mars,titan,venus,moon,frameworks}.md`，Titan 合并节
> 另见 `ucc-taxonomy-titan-section.md`。
> 核实等级：**已核实原文**（抓到摘要/全文并确认所引判据）＞**仅摘要**＞**元数据核实**
> （作者/标题/期刊/DOI 经 Crossref/OpenAlex 等交叉确认、摘要未抓到）＞**未核实**（显式标注）。
> 对照基线：UCC v1（热量带 4 节点 × 供需 4 档 + continental/water_stress 修饰语，
> `docs/ucc/specification.md`）与四天体实测
> （`docs/ucc/examples/{mars,titan,venus,moon}.md`）。

---

## §0 执行摘要

- **Mars**：无被广泛采用的正式气候分类（唯一 Köppen 化尝试 = Hargitai LPSC 2010 会议摘要，
  温度-only A–F 带，未被主流采用）；主流按变量轴组织——纬度/Ls、气压 vs 三相点（Haberle 2001
  「液态水有利区」29% 面积）、尘暴分类、挥发分稳定纬度界、古气候干旱度指数（Kite & Noblet
  2022 显式 "climate zonation"）。含义：火星类均质是物理事实，区分轴在气压-三相点与世界级气候态。
- **Titan**：无正式分区，但有稳定非正式区域词汇（极地湖区/赤道干旱沙丘带/中纬云带/ITCZ 迁移带）
  与供需型收支语言（Schneider 2012 净降水−输运−蒸发平衡；Faulk 2020 "polar moist climes and
  equatorial deserts"）。含义：跨溶剂广义需求模型（甲烷版 AI）有文献同构概念。
- **Venus**：高置信负结果——无气候分区；表面唯一有效空间轴 = **高度**（递减率 7–8.5 K/km；
  Maxwell「雪线」= 等 T、P 等高线）；分类只出现在垂直分层与气候态类型学（runaway、Arid/Aqua
  情景）。含义：-H 高度修饰语与世界级态前缀证据最强；热侧域门必须落地（实测 100% Ra-w 活证）。
- **Moon/无大气天体**：「气候」概念不存在（主流文献 climat* 0 次）；正式词汇 = **cold trap**
  （年最高温 <110 K ⇔ 冰保存 >1 Gyr）、**PSR**（光照几何二元单元）、纬度×地方时坐标系；
  Mercury 完整复用。含义：光照 regime 描述量有一手支撑，纳入 UCC 须声明语义扩展。
- **通用框架**：无统一跨行星标准；五类独立实践（第 5 类 2026-09-27 补入）= 温度阈值气候态（Wolf 2017 四态 235/250/
  275–315/330 K）、动力 regime（Haqq-Misra 2018 三 regime）、GCM 互比较场景（THAI/CUISINES）、
  地球分类移植（**同行评审论文为零**，唯一应用是硕士论文）、实践者/世界构建业余型
  （PBS 三部曲，灰色文献，对照分析 → `ucc-beyond-koppen-geiger-2026-09-27.md`）。含义：格点级「热量×供需」两轴组合
  是文献空位，最近先例 = Del Genio 2019 aridity index。
- **总结论**：四天体类均质**不是 UCC 缺陷**——学界同样不做格点级分类，空间信息住在别的轴上。
  v2 候选优先级（证据强度）：**F 世界级气候态前缀** ＞ **B 高度-气压修饰语** ＞ **C 广义挥发分
  供需** ＞ **D 光照 regime** ＞ **E 尘轴**（弱，缓行）；前置修复 = 热侧域门（详 §6）。任务书
  预设的 17 处引文经查证不存在，勘误见 §5.1。

---

## §1 Mars：无正式分类，变量轴组织 + 古气候「态」文献

### 1.1 结论

学界没有被广泛采用的、正式发表的火星气候分类方案（Köppen 那种有名字、有阈值、期刊发表的
scheme）。这是经多渠道检索确认的负结果（Crossref/OpenAlex/S2/NTRS/HAL/Europe PMC + 期刊
全量扫描，检索日志见证据文件 §1.2）。唯一直接对应物是 **Hargitai 的 Köppen 式「Mars climate
zone map」**，但载体是 LPSC 会议摘要（2010 #1199）与后续书章，未被 GCM/MCD、着陆区气候或
early-Mars climate states 任何主流文献线采用。主流实践 = 用变量轴（纬度、Ls、高度/气压、
尘、挥发分、轨道周期、干旱度）组织气候描述，而非命名气候区。

### 1.2 已发表的分区/分类实践（判据原文）

1. **Hargitai 2010（LPSC #1199，已核实原文——LPI PDF 全文）**：唯一 Köppen 化尝试。
   > "A Köppen-style climate classification system was created using a modified system based
   > on thermal criteria only, because of the lack of plants and liquid water precipitation
   > on Mars."
   
   A–F 带判据 = Tmax/Tmin 阈值 × 霜覆盖时间比例 × 纬度（如 A/B 带 Tmax > −15 °C、Tmin >
   −45 °C、无霜；F2 极地 Tmax < −70 °C、Tmin < −110 °C、终年霜）。数据源 TES 7.5 火星年。
   注意其温度-only 简化正是「无液态水降水 → 干湿轴失效」的显式声明——与我们 Mars 实测
   （P≡0 → C_TV 无定义、供需轴 OOD/MI）的处理同构。
2. **Haberle et al. 2001（JGR 106:23317，已核实原文）**：三相点分区——现代火星最接近
   「物理阈值气候分区」的实践。
   > "…there are five 'favorable' regions where these requirements are satisfied: between 0°
   > and 30°N in the plains of Amazonis, Arabia, and Elysium; and in the Southern Hemisphere
   > impact basins of Hellas and Argyre. The combined area of these regions represents 29%
   > of the planet's surface area."
   
   判据 = 表面气压与温度同时越过水三相点（611 Pa / 0 °C）+ 年累积时长（Amazonis 37 sols、
   Hellas 70 degree-days）。**气压是显式分类变量**。
3. **Schorghofer & Aharonson 2005（JGR 110:E05003，已核实原文）**：挥发分稳定纬度界——
   "Ground ice is expected down to ~49° latitude…frost at latitudes poleward of ~30°"。
   事实上的纬度气候带（zonally averaged boundaries），驱动变量 = 升华-凝结平衡。
4. **Kass et al. 2016（GRL 43:6111，已核实原文）**：尘暴事件分类——"Regional-scale storms
   are defined as events where the temperature exceeds 200 K"（50 Pa 带均昼温），季节序 A/B/C
   命名。罕见的有显式阈值的火星气候事件分类（事件级，非格点气候区）。
5. **Kite & Noblet 2022（GRL 49:e2022GL101150，已核实原文）**：古气候干旱度分带——
   > "We built a globally-distributed database of constraints on Mars late-stage paleolake
   > size relative to catchment area (aridity index), and found evidence for **climate
   > zonation** as Mars was drying out."
   
   分区变量 = 干旱度指数（古湖/流域面积比）× 高度 × 纬度 × 时间。**这是火星文献中显式使用
   "climate zonation" 且用供需型指数的少数实例**——与 UCC 供需档概念同构（但对象是古火星）。
6. **气候「态」文献（时间轴分类）**：Kite & Conway 2024（Nat Geo 17:10，已核实原文）——
   early Mars "seven major climate transitions"（离散态序列）；Kite 2019（SSR 215:16，已核实
   原文）——9 条定量地质约束 × 模型「真值表」（气压区间 0.012–1 bar、river-forming duty
   cycle <10%）；Wordsworth 2016（AREPS 44:381，已核实原文）——"steady-state cold vs
   episodically warm" 两态；Liu et al. 2023（Nature 620:303，已核实原文）——晚近火星
   「冰期（0.4–2.1 Ma）/间冰期」二分，倾角振幅驱动，纬度依赖冰尘幔（LDM）为证据。
7. **GCM/MCD 组织方式（非命名分区）**：Forget et al. 1999（JGR 104:24155，已核实原文）用
   zonal-mean × 季节组织输出；MCD（Millour et al. 2018/2026，HAL 摘要已核实）的「分类」=
   气候平均态（clim）vs 具体火星年情景（MY24–32）× 有无全球尘暴；着陆区实践（Martinez et al.
   2017 SSR 210:187 综述、Newman et al. 2021 SSR 217:20 Jezero 多模型预测，均已核实原文）按
   变量 × 时间尺度（日/季/年际）与 Ls 相位组织，**无分类语言**。

### 1.3 关键论文清单（精简；全表 24 条见证据文件 §3）

| 作者/年份 | 标题（原文） | 期刊 | DOI | 核实状态 |
|---|---|---|---|---|
| Hargitai 2010 | Mars climate zone map based on TES data | LPSC XLI #1199 | — | **已核实原文**（PDF 全文） |
| Haberle et al. 2001 | On the possibility of liquid water on present-day Mars | JGR 106:23317 | 10.1029/2000JE001360 | **已核实原文** |
| Schorghofer & Aharonson 2005 | Stability and exchange of subsurface ice on Mars | JGR 110:E05003 | 10.1029/2004JE002350 | **已核实原文** |
| Kass et al. 2016 | Interannual similarity in the Martian atmosphere during the dust storm season | GRL 43:6111 | 10.1002/2016GL068978 | **已核实原文** |
| Kite & Noblet 2022 | High and Dry: Billion-Year Trends in the Aridity of River-Forming Climates on Mars | GRL 49:e2022GL101150 | 10.1029/2022GL101150 | **已核实原文** |
| Kite & Conway 2024 | Geological evidence for multiple climate transitions on Early Mars | Nat Geo 17:10 | 10.1038/s41561-023-01349-2 | **已核实原文** |
| Kite 2019 | Geologic Constraints on Early Mars Climate | SSR 215:16 | 10.1007/s11214-018-0575-5 | **已核实原文** |
| Wordsworth 2016 | The Climate of Early Mars | AREPS 44:381 | 10.1146/annurev-earth-060115-012355 | **已核实原文** |
| Liu et al. 2023 | Martian dunes indicative of wind regime shift in line with end of ice age | Nature 620:303 | 10.1038/s41586-023-06206-1 | **已核实原文** |
| Forget et al. 1999 | Improved general circulation models of the Martian atmosphere… | JGR 104:24155 | 10.1029/1999JE001025 | **已核实原文** |
| Martinez et al. 2017 | The Modern Near-Surface Martian Climate: …Viking to Curiosity | SSR 210:187 | 10.1007/s11214-017-0360-x | **已核实原文** |
| Newman et al. 2021 | Multi-model Meteorological and Aeolian Predictions for Mars 2020… | SSR 217:20 | 10.1007/s11214-020-00788-2 | **已核实原文** |
| Hecht 2002 | Metastability of Liquid Water on Mars | Icarus 156:373 | 10.1006/icar.2001.6794 | **已核实原文** |
| Watanabe et al. 2025 | Behaviors of Martian CO2-driven dry climate system… | Icarus 116795 | 10.1016/j.icarus.2025.116795 | 仅摘要 |
| Zurek & Martin 1993 | Interannual variability of planet-encircling dust storms on Mars | JGR 98:3247 | 10.1029/92JE02936 | 元数据核实 |
| Mellon & Jakosky 1995 | The distribution and behavior of Martian ground ice… | JGR 100:11781 | 10.1029/95JE01027 | 元数据核实 |
| Laskar et al. 2004 | Long term evolution and chaotic diffusion of the insolation quantities of Mars | Icarus 170:343 | 10.1016/j.icarus.2004.04.005 | 元数据核实 |
| Lewis et al. 1999 | A climate database for Mars | JGR 104:24177 | 10.1029/1999JE001024 | 元数据核实 |

### 1.4 变量轴表（学界实际用什么区分火星气候）

| 变量轴 | 用法/判据 | 代表文献 | UCC 现状对照 |
|---|---|---|---|
| 纬度带（zonal） | GCM 输出组织；冰稳定界 ~49°、霜界 ~30° | Forget 1999；Schorghofer 2005 | 热量带隐式承载（实测全 polar，纬度信息在 t_mean 场） |
| 季节相位 Ls | 着陆区/MCD/尘季全部按 Ls 组织 | Newman 2021；MCD | 分箱=火星月（Ls），已对齐 |
| 高度/气压 vs 三相点 611 Pa | 五个「液态水有利区」（29% 面积）；早 Mars 气压 0.012–1 bar | Haberle 2001；Kite 2019；Hecht 2002 | **无气压描述量**（数据在文件里、不进分类）→ 候选轴 B |
| 尘暴尺度分类 | global vs regional（A/B/C，50 Pa 温度 >200 K） | Zurek & Martin 1993；Kass 2016 | 无不透明度描述量 → 候选轴 E（弱） |
| 挥发分循环 | CO2 冷凝/坍缩态（低倾角）、水冰稳定、霜 | Watanabe 2025；Wordsworth 2016 | 冷侧 OOD 门即「升华物理另起炉灶」的声明 |
| 轨道参数（倾角/日照周期） | 冰期/间冰期式时间态；45° 高倾角态 | Liu 2023；Forget 2006；Laskar 2004 | 世界级时间轴，非格点 → 候选轴 F 的世界档案维度 |
| 干旱度指数（古气候） | 古湖/流域面积比 ×高度×纬度，显式 "climate zonation" | Kite & Noblet 2022 | **AI 同构**——但现代火星 P≡0、供需轴 OOD |
| 命名地理区域 | Amazonis/Arabia/Elysium/Hellas/Argyre（非正式气候单元） | Haberle 2001；Forget 2006 | 无对应（我们按 cell 分类，不需要区域名） |

---

## §2 Titan：无正式分区，稳定区域词汇 + 供需型收支语言

### 2.1 结论

文献中不存在正式发表的 Titan 气候分区/分类方案（无「Titan 版 Köppen」、无官方气候带命名、
「cloud provinces」不是 Titan 术语——多渠道检索确认，日志见证据文件 §1）。学界实际使用
**非正式但高度稳定的区域词汇**：极地湖区（polar lakes/seas）、赤道干旱沙丘带（equatorial
dune belt / "predominantly arid climate"）、中纬云带（30–60°S 持续带）、ITCZ 迁移带、冬极
乙烷云帽（>50–60°N 准均匀平流层云）。唯一显式 Köppen 化尝试是 **Olcott 2024（Yale 本科
毕业论文，未经同行评审）**：用 TAM 按表面温度 × 降水 × 季节变率三变量制作 Titan 气候分区图
（"taking inspiration from Earth's Köppen-Geiger Climate Classification we utilized the Titan
Atmospheric Model (TAM) to create a climate map for Titan"，已核实原文）——它是「Titan 有
distinct climate regions 但尚无标准分类」现状的直接书面证据。

### 2.2 已发表的区域化实践（判据原文）

1. **观测云气候学 = 纬度带 × 季节（Ls）× 半球的编目**（最接近「气候分区」的操作实践）：
   - Rodriguez et al. 2011（Icarus 216:89，已核实原文，HAL 开放稿）——观测上最明确的纬度带
     分区："sporadic clouds at southern high and mid-latitudes, rare clouds in the equatorial
     region, and…a long-lived cloud cap above the north pole, ubiquitous poleward of 60°N…
     in a latitude band between 30°S and 60°S [clouds were continuously observed]…only a dozen
     clouds were observed closer to the equator."
   - Brown et al. 2010（Icarus 205:571，已核实原文）——半球不对称 + 云「省」二分：中纬对流云
     仅南半球；>50°N 准均匀乙烷云帽是平流层下沉型，与对流云属不同机制单元。
   - Turtle et al. 2011 GRL（已核实原文，CICLOPS PDF）——云区**季节迁移**四类：南极对流区 /
     北极+北中纬（春分前出现）/ 低纬大云系 / 南中纬-副热带（零星弱季节）。
   - Schaller et al. 2009（Nature 460:873，已核实原文）——「湿高纬 vs 干热带」二分原句：
     "Methane clouds, lakes and most fluvial features…have been observed in the moist high
     latitudes, while the tropics have been nearly devoid of convective clouds and have shown
     an abundance of wind-carved surface features like dunes."
   - Turtle et al. 2011 Science（已核实原文）——赤道干旱带判据经典句："the vast expanses of
     dunes that dominate Titan's equatorial regions require a predominantly arid climate."
   - Roe et al. 2005（Science 310:477，已核实原文）——**经度轴**存在：中纬云簇聚集于
     350°W/40°S，排除季节解释，指向地表局地源（geysering/cryovolcanism）。
2. **GCM 甲烷循环 = 季节雨带迁移 + 极地冷阱 + 低纬变干**：
   - Newman et al. 2016（Icarus 267:106，TitanWRF，已核实原文）——文献中最接近「定量分区
     判据」的表述：降水 "(a) frequent strong polar upwelling during spring and summer in each
     hemisphere, and (b) the Inter-Tropical Convergence Zone (ITCZ)…seasonally shifting
     Hadley cells"；"(5) TitanWRF produces drying of low and mid latitudes with net transport
     of surface methane to high latitudes…the favored pole for surface methane is the one with
     winter occurring closest to perihelion."
   - Lora et al. 2015（Icarus 250:516，TAM，已核实原文）——表面液体稳定性作分区判据：
     "Surface liquids are unstable at mid- and low-latitudes, and quickly migrate poleward."
   - Mitchell et al. 2011（Nat Geo 4:589，已核实原文）——赤道雨的波动组织（equinoctial
     chevron storms，Kelvin 波）；Mitchell 2012（ApJL 756:L26，已核实原文-摘要）——甲烷循环
     强度 = 降水/蒸发通量（能量收支约束）——**P/E 型强度指标存在，但无命名的干旱度指数**。
3. **表面液体收支 = 事实上的「供需」分区**（与 UCC AI 最同构的文献线）：
   - Schneider et al. 2012（Nature 481:58，已核实原文）——供需账本原句：
     > "The net precipitation in polar regions is balanced in the annual mean by slow
     > along-surface methane transport towards mid-latitudes, and subsequent evaporation.
     > In low latitudes, rare but intense storms occur around the equinoxes, producing enough
     > precipitation to carve surface features."

     「净降水 − 表面输运 − 蒸发」年均平衡即分区判据；赤道带定义 = 「罕见但强烈的分点风暴」。
   - Faulk et al. 2020（Nat Astron 4:390，已核实原文）——成因分区命名：
     "…producing the observed **polar moist climes and equatorial deserts**."（陆地水文-大气
     耦合：低中纬入渗 + 流向高纬盆地。）
   - Faulk et al. 2017（Nat Geo 10:827，已核实原文）——极端降水频率-强度做区域判别：
     "the most extreme storms tend to occur in the mid-latitudes, where observed alluvial fans
     are most concentrated."
   - Tokano et al. 2006（Nature 442:432，已核实原文）——与风暴区互补的全球弱降水背景态：
     "methane precipitation occurs wherever there is slow upward motion…persistent component
     of Titan's methane hydrological cycle."
4. **综述的区域词汇**：Mitchell & Lora 2016（AREPS 44:353 "The Climate of Titan"，已核实
   原文）——"weak baroclinic storms form at the boundary of Titan's **wet and dry regions**"；
   Hayes et al. 2018（Nat Geo 11:306，已核实原文）——组织框架是「时间尺度嵌套」（geologic /
   orbital / seasonal / storm）而非空间分区；Hörst 2017（JGR 122:432，已核实原文-摘要）。
   均无命名气候带。

### 2.3 关键论文清单（精简；全表 39 条见证据文件 §3）

| 作者/年份 | 标题（原文） | 期刊 | DOI | 核实状态 |
|---|---|---|---|---|
| Schneider et al. 2012 | Polar methane accumulation and rainstorms on Titan from simulations of the methane cycle | Nature 481:58 | 10.1038/nature10666 | **已核实原文** |
| Faulk et al. 2020 | Titan's climate patterns and surface methane distribution due to the coupling of land hydrology and atmosphere | Nat Astron 4:390 | 10.1038/s41550-019-0963-0 | **已核实原文** |
| Faulk et al. 2017 | Regional patterns of extreme precipitation on Titan consistent with observed alluvial fan distribution | Nat Geo 10:827 | 10.1038/ngeo3043 | **已核实原文** |
| Newman et al. 2016 | Simulating Titan's methane cycle with the TitanWRF General Circulation Model | Icarus 267:106 | 10.1016/j.icarus.2015.11.028 | **已核实原文** |
| Lora et al. 2015 | GCM simulations of Titan's middle and lower atmosphere and comparison to observations | Icarus 250:516 | 10.1016/j.icarus.2014.12.030 | **已核实原文** |
| Lora et al. 2019 | A model intercomparison of Titan's climate and low-latitude environment | Icarus 333:113 | 10.1016/j.icarus.2019.05.031 | **已核实原文** |
| Rodriguez et al. 2011 | Titan's cloud seasonal activity from winter to spring with Cassini/VIMS | Icarus 216:89 | 10.1016/j.icarus.2011.07.031 | **已核实原文** |
| Brown et al. 2010 | Clouds on Titan during the Cassini prime mission: A complete analysis of the VIMS data | Icarus 205:571 | 10.1016/j.icarus.2009.08.024 | **已核实原文** |
| Turtle et al. 2011 | Rapid and extensive surface changes near Titan's equator: Evidence of April showers | Science 331:1414 | 10.1126/science.1201063 | **已核实原文** |
| Turtle et al. 2011 | Seasonal changes in Titan's meteorology | GRL 38:L03203 | 10.1029/2010GL046266 | **已核实原文** |
| Schaller et al. 2009 | Storms in the tropics of Titan | Nature 460:873 | 10.1038/nature08193 | **已核实原文** |
| Tokano et al. 2006 | Methane drizzle on Titan | Nature 442:432 | 10.1038/nature04948 | **已核实原文** |
| Mitchell & Lora 2016 | The Climate of Titan | AREPS 44:353 | 10.1146/annurev-earth-060115-012428 | **已核实原文** |
| Hayes et al. 2018 | A post-Cassini view of Titan's methane-based hydrologic cycle | Nat Geo 11:306 | 10.1038/s41561-018-0103-y | **已核实原文** |
| Mitchell et al. 2011 | Locally enhanced precipitation organized by planetary-scale waves on Titan | Nat Geo 4:589 | 10.1038/ngeo1219 | **已核实原文** |
| Roe et al. 2005 | Geographic Control of Titan's Mid-Latitude Clouds | Science 310:477 | 10.1126/science.1116760 | **已核实原文** |
| Rannou et al. 2006 | The latitudinal distribution of clouds on Titan | Science 311:201 | 10.1126/science.1118424 | **已核实原文** |
| Tokano 2011 | Precipitation Climatology on Titan | Science 331:1393 | 10.1126/science.1204092 | **已核实原文**（官方一句摘要；正文 Köppen 句未核实） |
| Tokano 2008 | Dune-forming winds on Titan and the influence of topography | Icarus 194:243 | 10.1016/j.icarus.2007.10.007 | 元数据核实 |
| Tokano 2009 | Impact of seas/lakes on polar meteorology of Titan: Simulation by a coupled GCM-Sea model | Icarus 204:619 | 10.1016/j.icarus.2009.07.032 | 元数据核实 |
| Mitchell 2012 | Titan's transport-driven methane cycle | ApJL 756:L26 | 10.1088/2041-8205/756/2/L26 | **已核实原文**（摘要） |
| Olcott 2024 | Titan's Hydrologic Cycle（Yale 本科毕业论文，非同行评审） | Yale senior thesis | earth.yale.edu | **已核实原文**（全文） |

### 2.4 变量轴表

| 变量轴 | 用法/判据 | 代表文献 | UCC 现状对照 |
|---|---|---|---|
| 纬度带 | 极地 >60° / 中纬 30–60° / 赤道；云频率编目 | Rodriguez 2011；Brown 2010 | 热量带全 polar 退化（真实物理：t_range ~1.6 K） |
| 季节 Ls / 半球相位 | 云区季节迁移；分点触发赤道风暴 | Turtle 2011 GRL；Mitchell 2011 | 分箱 = Titan 年 1/12，已对齐；C_TV 0.63 表达集中 |
| ITCZ/汇聚带位置 | Titan 版 ITCZ 迁移幅度远超地球 | Tokano 2011；Mitchell & Lora 2016 | 无环流描述量（世界级前缀候选，轴 F） |
| 半球不对称 | 北湖多南湖少；判据 = 北夏在远日点更长、净降水更大 | Schneider 2012；Newman 2016 | 世界级轨道参数，非格点 |
| 地表液体分布 | 湖海 vs 干涸带；表面液体稳定性 | Lora 2015；Faulk 2020；Brown 2009 | Po/Pn 二分（qsurf>0.05 m）是粗代理 |
| **蒸发-降水收支** | 净降水−输运−蒸发年均平衡；P/E 通量强度 | Schneider 2012；Mitchell 2012；Lora 2024 | **AI 同构但 demand_model=None（MI）**→ 候选轴 C |
| 极端降水频率-强度 | 中纬最强极端风暴 ↔ 冲积扇纬度分布 | Faulk 2017；Turtle 2011 Science | 无强度分布描述量（C_TV 只表达时间集中） |
| 经度/地理控制 | 350°W/40°S 云簇，地表局地源 | Roe 2005；Griffith 2005 | 无（格点分类天然含经度信息，不需要轴） |
| 云型-高度轴 | 对流甲烷云 vs 平流层乙烷云帽 vs 层状 drizzle | Rannou 2006；Tokano 2006 | 无垂直维度（我们只分类表面气候） |
| 轨道长周期（Croll-Milankovitch） | 湖泊分布长期再分配；古气候 | Hayes 2018；Lora 2014 | 世界级时间轴（分支系统的天然位置） |

---

## §3 Venus：无气候分区——高度是表面唯一空间轴，分类住在「气候态」里

### 3.1 结论

**高置信负结果**：Venus 没有任何正式气候分区/分类（12 条 WebSearch + Crossref/OpenAlex/S2/
NTRS/HAL/EuropePMC 检索全记录在证据文件 §1）。学界对 Venus 气候的实际处理是四种：垂直结构
分层（VIRA 参考大气：T/P/ρ = f(高度, 纬度)；云层 upper/middle/lower + hazes）、纬度-高度
剖面的动力学描述（superrotation、cold collar、暖极涡——动力学特征名，非气候区）、**气候态
类型学**（runaway/moist greenhouse、type I/II 行星、Arid/Aqua-Venus 情景——时间演化轴与
系外行星归类，不是现代表面的空间分区）、数据/模型 intercomparison（纬度 bin × 地方时 bin）。

### 3.2 实际的分区/分层实践（判据与数值原文）

1. **高度 → 温度（表面气候主变量轴）**：
   - Meadows & Crisp 1996（JGR 101:4595，已核实原文）——"nightside averaged temperature
     lapse rates of **−7 to −7.5 K/km in the lowest 6 km**…smaller…than those inferred from
     earlier measurements and greenhouse models (**−8 to −8.5 K/km**) [Seiff, 1983]"；且
     "high-elevation regions are substantially cooler"（T(elevation) 被显式用作辐射反演变量）。
   - Singh 2019（Sci Rep 9:1137，已核实原文；⚠️ 其「高海拔只冷 ~3 K」结论与自引的绝热预期
     矛盾、与 M&C 1996 相左，属非常规结论，只采信其 lapse rate 估算与「纬度无显著变化」）——
     "lapse rate (dT/dz) of about 7.6 K km⁻¹…For about **13 km change in Venus topography, a
     temperature change of about 100 K** is expected"；"Surface temperatures do not show any
     significant variation with changing latitudes because only a small amount (**~2.5%**) of
     solar energy reaches the surface."
   - Strezoski & Treiman 2022（PSJ 3，已核实原文）——**高度作为 T、P 代理被显式使用的最强
     证据**：Maxwell Montes「雪线」= "a single common elevation (and thus temperature and
     pressure)"，且 "not at a constant elevation—it is ∼3.5 km higher in the NW than the SE"
     （snow shadow，用等高线空间变化反推环流）。即金星表面化学分带实际用**等 T、P 等高线**
     表达。
   - VIRA/NASA Venus-GRAM（Seiff et al. 1985 元数据核实、内容经四个独立已核实来源交叉确认；
     NASA/TM-20210022168 全文核实）——官方参考大气的变量轴 = **(高度, 纬度) 0–100 km、
     (高度, 地方时) 100–150 km、(高度, SZA) 150–250 km，无地表分区维度**。
   - Lebonnois & Schubert 2017（Nat Geo 10:470，已核实原文）——"the deepest 12 km…behaves
     like a **supercritical fluid**"（~700 K、~75 bar）。注意「supercritical」是物理状态描述，
     不是气候区名；**未检索到把超临界 CO2 或「干旱度」用于 Venus 表面气候分类的文献**。
2. **环流「区」= 动力学描述，非气候分区**：cold collar（Tellmann et al. 2009 JGR，已核实
   原文：纬度 ~60–65°、对流层顶 +7 km、温度 −60 K；Ando et al. 2020 Sci Rep，已核实原文：
   "~65° latitude near the cloud top"）、暖极涡（Ando et al. 2016 Nat Commun 7:10398，已核实
   原文："the observed Venus polar vortex is warmer than the midlatitudes at cloud-top levels"）、
   中纬 jet 与云顶超旋 100–110 m/s（Read & Lebonnois 2018 AREPS 46:175，已核实开放全文）。
   这些是有纬度带的准「区」，但全部是动力学特征名，无文献将其编纂为气候区。
3. **云层垂直分层**（最接近「垂直气候分层」的实践）：Esposito et al. 1983（Venus 书章，已核实
   原文-摘要）——"main cloud deck at 45–70 km altitude, with thinner hazes above and below…
   subdivided into upper, middle and lower cloud levels"。**注意：任务预设的「A/B/C」字母命名
   查不到**；实际命名 = upper/middle/lower + hazes。对流区分层：Moroz & Rodin 2002（已核实
   原文）——两个对流区（表面边界层 + 49–55 km）；稳定度分层：Ando et al. 2020（50–58 km
   低稳定层等）。
4. **intercomparison 语言**：观测互比较（Limaye et al. 2017 Icarus 294:124，已核实原文）=
   "five latitude bins and three local time bins"，目标是更新 VIRA；上层大气 GCM 互比较
   （Martinez et al. 2025/26 Icarus，已核实原文-摘要）= nominal simulations/metrics 语言。
   **无 CMIP 式表面气候互比较项目，无 regime/zone 分类学。**
5. **气候态框架（时间演化轴）**：Kasting 1988（Icarus 74:472，元数据核实；内容经 Way 2020
   原文间接核实）——moist vs runaway greenhouse 两态；Hamano, Abe & Genda 2013（Nature
   497:607，已核实原文）——"type I planets (such as Earth)…type II planets (possibly such as
   Venus)…desiccated by hydrodynamic escape"；Way & Del Genio 2020（JGR 125:e2019JE006276，
   已核实原文+接受稿全文）——情景分类学 **Arid-Venus / 10m-Venus / 310m-Venus / 158m-Aqua /
   310m-Earth × 年代（4.2/2.9/0.715 Ga）**，"optimistic Venus zone"；Way et al. 2016（GRL 43，
   已核实原文）——"Venus's climate could have remained habitable until at least 715 million
   years ago"；Donahue et al. 1982（Science 216:630，已核实原文）——D/H 百倍富集 = 水存量历史
   约束（是气候态分类的输入，本身不产生分区）。**「arid/aqua」湿度词汇在 Venus 文献中的真实
   用法 = 古气候情景名与系外行星归类，不是现代表面的干旱度分区。**

### 3.3 关键论文清单（精简；全表 35 条见证据文件 §3）

| 作者/年份 | 标题（原文） | 期刊 | DOI | 核实状态 |
|---|---|---|---|---|
| Meadows & Crisp 1996 | Ground-based near-infrared observations of the Venus nightside… | JGR 101:4595 | 10.1029/95JE03567 | **已核实原文** |
| Singh 2019 | Venus nightside surface temperature | Sci Rep 9:1137 | 10.1038/s41598-018-38117-x | **已核实原文**（⚠️ 部分结论非常规，慎引） |
| Strezoski & Treiman 2022 | The "Snow Line" on Venus's Maxwell Montes… | PSJ 3 | 10.3847/PSJ/ac9f3a | **已核实原文** |
| Lebonnois & Schubert 2017 | The deep atmosphere of Venus and the possible role of density-driven separation of CO2 and N2 | Nat Geo 10:470 | 10.1038/ngeo2971 | **已核实原文** |
| Tellmann et al. 2009 | Structure of the Venus neutral atmosphere as observed by…VeRa… | JGR 114 | 10.1029/2008JE003204 | **已核实原文** |
| Ando et al. 2016 | The puzzling Venusian polar atmospheric structure reproduced by a GCM | Nat Commun 7:10398 | 10.1038/ncomms10398 | **已核实原文** |
| Ando et al. 2020 | Thermal structure of the Venusian atmosphere from the sub-cloud region to the mesosphere… | Sci Rep 10:3448 | 10.1038/s41598-020-59278-8 | **已核实原文**（全文） |
| Read & Lebonnois 2018 | Superrotation on Venus, on Titan, and Elsewhere | AREPS 46:175 | 10.1146/annurev-earth-082517-010137 | **已核实原文**（开放全文） |
| Esposito et al. 1983 | The clouds and hazes of Venus | Venus（书章） | 10.2307/j.ctv25c4z16.20 | **已核实原文**（摘要） |
| Way & Del Genio 2020 | Venusian Habitable Climate Scenarios… | JGR 125:e2019JE006276 | 10.1029/2019JE006276 | **已核实原文**（全文） |
| Hamano, Abe & Genda 2013 | Emergence of two types of terrestrial planet on solidification of magma ocean | Nature 497:607 | 10.1038/nature12163 | **已核实原文** |
| Donahue et al. 1982 | Venus Was Wet: A Measurement of the Ratio of Deuterium to Hydrogen | Science 216:630 | 10.1126/science.216.4546.630 | **已核实原文** |
| Limaye et al. 2017 | The thermal structure of the Venus atmosphere: Intercomparison… | Icarus 294:124 | 10.1016/j.icarus.2017.04.020 | **已核实原文** |
| Justh et al. 2021 | Venus Global Reference Atmospheric Model (Venus-GRAM): User Guide | NASA/TM-20210022168 | — | **已核实原文**（全文） |
| Kasting 1988 | Runaway and moist greenhouse atmospheres and the evolution of Earth and Venus | Icarus 74:472 | 10.1016/0019-1035(88)90116-9 | 元数据核实（内容经 Way 2020 间接核实） |
| Seiff et al. 1985 (VIRA) | Models of the structure of the atmosphere of Venus from the surface to 100 kilometers altitude | Adv Space Res 5(11):3 | 10.1016/0273-1177(85)90197-8 | 元数据核实（内容四源交叉确认） |

### 3.4 变量轴表

| 变量轴 | 实际用法 | 代表文献 | UCC 现状对照 |
|---|---|---|---|
| **高度/气压 (z, P)** | 表面气候第一变量：T(z) 7–8.5 K/km；13 km 地形幅 → ~100 K；雪线=等 T,P 线；深层 12 km 超临界域 | M&C 1996；Singh 2019；Strezoski 2022；Lebonnois & Schubert 2017 | t_mean 408–469 °C 差异**已在数据里**、类码全同（100% Ra-w）→ 候选轴 B（-H 修饰语） |
| 纬度 | 表面几乎无效（2.5% 透光率）；云顶/上层：赤道-极 ΔT ~30 K、cold collar ~60–65° | Tellmann 2009；Ando 2016/2020 | 热量带若有纬度梯度自然会分——退化是物理，非缺陷 |
| 地方时/昼夜 | intercomparison 3 个 LT bin；GCM dayside/nightside；GRAM 高层轴 | Limaye 2017；Martinez 2025 | 我们取固定地方时切片（已声明，表面日较差可忽略） |
| 垂直结构带 | 对流区/稳定度分层/云层 upper-middle-lower/superrotation 域 | Moroz & Rodin 2002；Esposito 1983；Ando 2020 | 无垂直维度——**根本不可比**（我们只分类表面） |
| 气候态/演化时段 | moist vs runaway；type I/II；Arid/Aqua 情景 × 年代 | Kasting 1988；Hamano 2013；Way 2020 | 世界级元数据 → 候选轴 F（世界档案前缀） |
| 太阳活动/光谱 | 上层大气 GCM 差异主因 | Martinez 2025 | 世界级输入参数（astronomy 层） |

---

## §4 Moon 与无大气天体：没有「气候」，有正式的热环境分类词汇

### 4.1 结论

月球/无大气天体**不存在「气候分类」概念**——这是词频级可证的负结果：Williams et al. 2017
（Icarus 283:300，Diviner 全球温度气候学奠基论文，已核实全文 26 页）与 Schorghofer 2025
（arXiv:2502.06056 月冰理论综述，已核实全文）中 `climat*` 均 **0 次**；Paige 2010 /
Williams 2019 / Watson 1961 摘要亦无。主流术语是 **thermal environment**（Sefton-Nash 2023
Encyclopedia of Lunar Science 条目标题即 "Surface and Near-Surface Thermal Environment of the
Moon"）、**airless body**、**surface-bounded exosphere**。检索到的唯一标题级用 "climate" 的
期刊论文是 Kramm et al. 2022（Natural Science [SCIRP]，非主流渠道，气象学界作者——反例）。
但该领域有**正式的、定量的分类词汇**（cold trap / PSR / 近永久光照区 / 纬度带×地方时气候学
坐标系），且 Mercury 文献完整复用（Deutsch et al. 2016/2018；共同源头 Vasavada, Paige & Wood
1999 的 Moon+Mercury 双子热模型）。

### 4.2 已发表的分类实践（判据原文）

1. **Cold trap（温度阈值 × 挥发分保存时标）**——判据链 Watson 1961 → Paige 2010 →
   Williams 2019 → Schorghofer 2025：
   - Watson, Murray & Brown 1961a（JGR 66:1598，**已核实原文**——公开扫描全文）：原始判据
     = 120 K 上限（"We are using 120°K, however, because it is a reasonable upper limit"）+
     升华速率限制逃逸（对月球寿命积分损失预算）+ PSR 纬度界 78°（"the permanently shaded
     areas can occur only north of latitude 78°N and south of latitude 78°S"，面积分数
     1.2×10⁻⁴）。1961b（JGR 66:3033，摘要已核实）是 "cold traps" 一词的原始出处。
   - Paige et al. 2010（Science 330:479，摘要已核实）："widespread surface and near-surface
     cryogenic regions that **extend beyond the boundaries of persistent shadow**"——温度定义
     与光照定义解耦；LCROSS 撞击点地下 38 K。
   - Williams et al. 2019（JGR 124:2505，摘要已核实）——**现代操作判据原文**："surfaces
     **below 110 K** capable of cold trapping water **over 1 Gyr**"（冬季面积 ×2.8 南 / ×4.3 北）。
   - Schorghofer 2025（arXiv:2502.06056，已核实全文）："a threshold of ~110 K for
     cold-trapping is very defensible"；"negligible" = 100 kg/m²（~10 cm）冰/Gyr；地下版判据 =
     持续 <110 K；冷阱有**地质年龄轴**（">3.4 Ga 前几乎无 PSR"；LCROSS 点 ~0.9 Ga）。
2. **PSR / 近永久光照区（光照几何分类单元）**：Mazarico et al. 2011（Icarus 211:1066，NTRS
   官方摘要核实）——PSR 正式定义 "areas that **never receive direct solar illumination**"
   （二元单元，面积统计北 12,866 / 南 16,055 km²，计算域至 75–80° 纬度）；「近永久光照」不是
   二元单元而是连续统计（Shackleton 坑缘某点连续光照 240 天、最长连续黑暗 1.5 天）。衍生
   词汇：seasonally shadowed regions（Williams 2019，"much more extensive than the PSRs"）、
   non-polar permanent shadows（低至 ~60° 纬度，McGovern 2013 经 Williams 2017 参考表核实）、
   **micro cold traps**（Sefton-Nash et al. 2019 Icarus 332:1，摘要核实："shadowed also from
   secondary and higher order radiation"）。
3. **温度气候学的组织方式（坐标系而非命名分类）**：Williams et al. 2017（Icarus 283:300，
   **已核实全文**）——binning = "0.5° latitude and longitude and 0.25 h of local time"；
   纬度带实践 = **zonal mean + 距平**（"Anomalous maximum and minimum temperatures are
   highlighted by subtracting the zonal mean temperatures from maps"，正午均温随纬度按
   cos^(1/4)θ 下降）；地形热表征 = 反射率 × 热惯量（TI）双轴（定性，无命名类别）；关键数字：
   赤道日最高 387–397 K、日出前最低 ~95 K、晨昏不对称 ~30 K、高岩石丰度夜温距平 >50 K。
   Williams et al. 2019（JGR 124:2505，摘要核实）——极区产品 = ±80° 极射影 × 固定地方时 ×
   冬/夏（subsolar 纬度符号二分）。
4. **可推广性（Mercury）**：Deutsch et al. 2016（Icarus 280:158，NTRS 摘要核实）——水星 PSR
   测绘 65°N–90°N，"All large radar-bright deposits…collocate with regions of shadow"；
   Deutsch et al. 2018（JGR，微冷阱）——"a large fraction of the polar ice on Mercury resides
   inside micro cold-traps (of scales 10–100 m)"。词汇与方法学均为月球的直接移植。

### 4.3 关键论文清单（精简；全表 15 条见证据文件 §5）

| 作者/年份 | 标题（原文） | 期刊 | DOI | 核实状态 |
|---|---|---|---|---|
| Watson, Murray & Brown 1961a | On the Possible Presence of Ice on the Moon | JGR 66:1598 | 10.1029/JZ066i005p01598 | **已核实原文**（全文） |
| Watson, Murray & Brown 1961b | The behavior of volatiles on the lunar surface | JGR 66:3033 | 10.1029/JZ066i009p03033 | 摘要已核实 |
| Paige et al. 2010 | Diviner Lunar Radiometer Observations of Cold Traps in the Moon's South Polar Region | Science 330:479 | 10.1126/science.1187726 | 摘要已核实（双源） |
| Williams et al. 2017 | The global surface temperatures of the Moon as measured by the Diviner Lunar Radiometer Experiment | Icarus 283:300 | 10.1016/j.icarus.2016.08.012 | **已核实原文**（全文） |
| Williams et al. 2019 | Seasonal Polar Temperatures on the Moon | JGR Planets 124:2505 | 10.1029/2019JE006028 | 摘要已核实 |
| Mazarico et al. 2011 | Illumination conditions of the lunar polar regions using LOLA topography | Icarus 211:1066 | 10.1016/j.icarus.2010.10.030 | 摘要已核实（NTRS 官方） |
| Sefton-Nash et al. 2019 | Evidence for ultra-cold traps and surface water ice in the lunar south polar crater Amundsen | Icarus 332:1 | 10.1016/j.icarus.2019.06.002 | 摘要已核实 |
| Schorghofer 2025 | Current Theories of Lunar Ice | arXiv:2502.06056 | — | **已核实原文**（全文） |
| Gläser et al. 2021 | Temperatures Near the Lunar Poles and Their Correlation With Hydrogen Predicted by LEND | JGR Planets 126:e2020JE006598 | 10.1029/2020JE006598 | 摘要已核实 |
| Deutsch et al. 2016 | Comparison of areas in shadow from imaging and altimetry in the north polar region of Mercury… | Icarus 280:158 | 10.1016/j.icarus.2016.06.015 | 摘要已核实（NTRS） |
| Sefton-Nash 2023 | Surface and Near-Surface Thermal Environment of the Moon | Encyclopedia of Lunar Science | 10.1007/978-3-319-14541-9_14 | 元数据核实 |
| Vasavada, Paige & Wood 1999 | Near-Surface Temperatures on Mercury and the Moon and the Stability of Polar Ice Deposits | Icarus 141:179 | 10.1006/icar.1999.6175 | 元数据核实 |

### 4.4 变量轴表

| 变量轴 | 用法/判据 | 代表文献 | UCC 现状对照 |
|---|---|---|---|
| 纬度带 | zonal mean + cos^(1/4)θ；界标 ±80°/75°/78°/~60°/65°N | Williams 2017/2019；Mazarico 2011；Watson 1961 | 热量带 Cn/Pn 二分承载（实测：赤道 Cn-x、极地 Pn） |
| **光照 regime** | PSR（二元：never direct illumination）/ seasonally shadowed / micro cold trap / 近永久光照（统计） | Mazarico 2011；Williams 2019；Sefton-Nash 2019 | 无显式描述量；地方时分箱部分隐式代理（PSR cell 全箱冷）→ 候选轴 D |
| **温度阈值 × 保存时标** | 120 K（原始）→ **110 K ⇔ 1 Gyr**（现代操作判据）；地下版=持续 <110 K | Watson 1961；Williams 2019；Schorghofer 2025 | **t_max 同构**（我们的分箱均温极值即「最暖时能否保存挥发分」的代理）；冷侧 OOD 门与之同思路 |
| 地方时（diurnal） | 0.25 h bins；晨昏不对称 ~30 K；Tmax/Tmin | Williams 2017 | 实测 Moon 分箱 = 12×2h 地方时，完全对齐 |
| 季节 | subsolar 纬度符号定冬/夏（二元）；Draconic year 346.62 d | Williams 2019 | 月球季节弱（1.54° 倾角），累积产品已平均 |
| 热物性（TI/反射率/岩石丰度） | 「low/high reflectance × low/high TI」双轴表征 | Williams 2017 | 无——**不可比**（表面物性层，非气候层） |
| 深度（表面 vs 地下） | 表面峰值温度判据 → 地下持续温度判据（vapor pumping） | Schorghofer 2025；Gläser 2021 | 无垂直维度（同 Venus，只分类表面） |
| 地质时间（冷阱年龄） | PSR 年龄谱（>3.4 Ga 几乎无）；"old cold traps should have more ice" | Schorghofer 2025 | 无（世界级时间轴，分支系统可承载） |

---

## §5 通用框架：五类独立实践，无统一标准（压缩节）

**结论**：截至 2026-09，不存在统一的、被社区公用的跨行星气候分类标准（没有行星界的
Köppen）。实际存在五类彼此独立的分类实践（1-4 类的详细判据原文与 30 条文献表见
`private/reviews/_research/ucc-taxonomy-frameworks.md`；第 5 类为 2026-09-27 补入）：

1. **气候态温度阈值型**（行星级，一球一态）：**Wolf et al. 2017**（ApJ 837:107，已核实
   摘要）四态 = snowball (Ts<235 K) / waterbelt (235–250 K) / temperate (275–315 K) /
   moist greenhouse (>330 K)，可居上限 ~355 K；Goldblatt 2015（Astrobiology，已核实摘要）
   纯水汽大气四态 + **禁态区间**（290–350、550–900 K 无稳态——多稳态与路径依赖）；
   **Ramirez 2020**（MNRAS 494:259，已核实摘要）证明**阈值本身随 N₂ 分压/云/恒星型移动**
   （runaway ~330 K → ~300 K 或更低）；Abe et al. 2011（Astrobiology，已核实摘要）行星类型
   （land/aqua）× 倾角 → HZ 边界辐照阈值；Yang et al. 2017（Nat Geo 10:556，已核实摘要）
   态转变**可达性**（冰质世界 snowball → moist/runaway 直跳）；Kasting 1988（元数据核实，
   两态框架原始出处）。
2. **环流/动力 regime 型**：**Haqq-Misra et al. 2018**（ApJ 852:67，已核实摘要）三 regime
   判据 = 赤道 Rossby 变形半径与 Rhines 长度各自 vs 行星半径（slow / Rhines / rapid rotator，
   附恒星 Teff 与自转周期区间）；Noda et al. 2017（Icarus 282:1，已核实摘要）同步自转
   aquaplanet 环流 Type-I–IV（III→IV 突变 + 多平衡）；Kaspi & Showman 2015（ApJ 804:60，
   已核实摘要）六参数 regime 空间。
3. **GCM 参数空间/互比较型**：Way/Del Genio 2019 系列（已核实摘要）——**Del Genio et al.
   2019 III（ApJ，arXiv:1910.03479）"assess fractional habitability using an aridity index
   that measures the net supply of water to the land" 是 UCC 供需档（AI=P/Eref）最近的已核实
   先例**（格点级供需比，但只聚合为行星分数）；互比较 = Yang et al. 2019（ApJ 875，已核实
   摘要：G 星模型间差 ≤8 K、M 星 20–30 K）+ THAI 协议与三部曲（Fauchez 2020 GMD 13:707、
   Turbet/Sergeev/Fauchez 2022 PSJ——分类语言是**场景**：land/aqua × modern-Earth/pure-CO₂，
   方差即不确定度）+ CUISINES exoMIP 元框架（Sohl et al. 2024 PSJ 5:175）。
4. **地球分类移植型（Köppen-on-other-worlds）**：**同行评审论文为零**（强负结果，检索日志见
   证据文件 §4 N7）。唯一正式应用 = Wester & Bergwall 2025（Uppsala 硕士论文，DiVA
   diva2:2023931，已核实摘要）：Köppen-Geiger + 湿球温度用于古火星与 TRAPPIST-1 d/e（其
   TRAPPIST-1 d「赤道热沙漠+极区热带」反常分布暴露了直接套用地球公式不处理潮汐锁定几何的
   风险）。地球侧工具链成熟：Lohmann et al. 1993（Köppen 作 GCM 诊断，元数据核实）、Kiang
   et al. 2026（EGUsphere 预印本，已核实摘要：Köppen 类 → 植被边界条件查找表，含
   "generalized planetary version" 措辞）。
   另有编码型：Plávalová & Rosaev 2024（arXiv:2409.09666，已核实摘要）四参数系外行星编码，
   温度轴 = 轨道 Dyson 温度 F/W/G/R 四类（金星 EG0t、地球 EW0t）——层次是轨道辐射平衡温度，
   非表面格点气候，不可直接对标 UCC。

5. **实践者/世界构建业余型（2026-09-27 补入）**：worldbuildingpasta（笔名，ExoPlaSim
   世界构建实践者，worldbuildingpasta.blogspot.com）的「Beyond the Köppen-Geiger Climate
   Classification System」三部曲（Part I 2024-12 扩展与替代方案综述、Part II 2025-03
   「Pasta Bioclimate System」（PBS）设计正文、Part III 2025-05 自评；博客，**灰色文献、
   非同行评审**，定位 = 实践者方法论参照；**已核实原文**——全文抓取存档
   `private/research/ucc-beyond-koppen-geiger-part{1,2,3}.md`（原文因版权不转载入库），
   与 UCC 的逐维对照分析 → `ucc-beyond-koppen-geiger-2026-09-27.md`（本目录））。
   PBS 以**预测生物群系**为第一目标做 Köppen 的替代而非扩展：9 参数（生长度日 GDD 及其
   光照限制版 GDDl、生长中断因子 GInt（冷侧 <15 °C 与**热侧 45→60 °C** 双侧累积）、
   AET/PET 干旱度 Ar/GAr（生长季加权）、雨热相位 GrS、水涝 Evr、含「干冷荒 CG」的
   MinIce）→ T/C/H/E/A/O 群 + 成体系优先级规则；光照是一等分类变量（~200 W/m² 光合
   减速阈值）；系外适配 = 月长修正累计 + productivity 生物学旋钮 + 多文件拼年。对 UCC
   最有价值的三处：GrS 及其**几十个失败替代方案清单**（雨热相位描述量的实现级先例 +
   免费负结果）；Teacup Ae 短年行星实测教训（短年 → GDD 不足 → 苔原蔓延，productivity
   旋钮补偿 → 温带带消失——UCC「本地采样窗口契约 + 物理家族 profile」路线的独立外部
   印证，与 nacrea 100 d 年直接相关）；反面教材 = 作者为迁就 ExoPlaSim 偏差把 GrS 阈值
   1.15→0.8 重调（模型偏差↔阈值耦合的活案例，印证 UCC profile 版本化 + provenance
   声明的动机）。其转述文献（Olson et al. 2001 WWF 生态区、Haxeltine & Prentice 1996
   BIOME3、IUCN Global Ecosystem Typology、ASCE Penman-Monteith / Hargreaves PET 等）
   均为**博客转述、元数据核实**级，按需再升级原文核实。

**对 UCC 的定位**：文献中「行星级温度态分类」与「格点级气候带分类」是两个不互通的层次；
没有任何已发表工作同时做「热量 × 供需」两轴的**格点级**分类并跨行星使用——UCC v1 的两轴
组合是文献空位（既是新颖性，也是无先例可对标的风险）。PBS（第 5 类）是「地球分类移植零
同行评审」判词下完成度最高的实践者样本，但其产品仍是单层分区标签：连续描述量作为产品层、
部分有效状态、时间基准契约与家族 profile 架构在全部五类实践中均无先例。所有已核实的温度
阈值都带**标定域**（随大气成分/水库存/恒星型移动），与仓库「闭合知识论分类 + 标定域声明」
纪律同构。

### 5.1 勘误框：任务书预设引文的核实结果（重要，防再引用）

任务书与调研提示中预设的以下引文，经多数据库穷尽检索（Crossref/OpenAlex/S2/PubMed/arXiv/
NTRS/作者主页/期刊全量扫描）**判定不存在或题录有误**；主线另用独立 WebSearch 复核了其中
三条最大载荷项（Koll 2021、THAI、Tian 2015），同样零命中。功能替代文献如下：

| # | 预设引文 | 核实结果 | 真实对应物 |
|---|---|---|---|
| 1 | Haqq-Misra et al. "Too Hot for Advanced Intelligence…"（THAI 四态，arXiv:2109.01131，230/320/450 K 阈值） | **查无此文**（arXiv:2109.01131 实为数学论文；五库+作者全量档案 99 条均无） | 四态温度阈值 = Wolf et al. 2017（235/250/275–315/330/355 K）；「THAI」真名 = TRAPPIST-1 互比较（场景分类） |
| 2 | Koll et al. 2021 Nature "Global climate patterns of fast-rotating aquaplanets" | **查无此文**（Koll 本人官网全列表无；CrossRef/OpenAlex/arXiv 零命中；所传 DOI 实为 miRNA 论文） | 环流 regime 分类 = Haqq-Misra et al. 2018 + Noda et al. 2017 + Kaspi & Showman 2015 |
| 3 | Koll et al. 2019 ApJ 884:108 "Characterizing Exoplanet Habitability…" | **查无此文**（ApJ 884:108 实为 Moór et al. 碎片盘论文） | 地球 GCM 扫参数空间 = Wolf et al. 2017 + Way/Del Genio 2019 系列 |
| 4 | Tian 2015 Earth-Science Reviews "Climate transitions and habitability of rocky planets" | **查无此文**（CrossRef 标题+作者+期刊窗口全零） | 气候转变概念 = Kasting 1988 / Yang 2017 NatGeo / Goldblatt 2015 / Ramirez 2020 |
| 5 | Yang et al. 2017 ApJ 845:95 系外行星 GCM 互比较 | **查无此文**（VizieR J/ApJ/845/95 not found） | 互比较起点 = Yang et al. 2019 ApJ 875 + THAI |
| 6 | Numaguchi et al. 行星 GCM 互比较 | **无此文**（Numaguchi 是地球 GCM 开发者，非互比较作者） | 同上（Yang 2019/THAI/CUISINES） |
| 7 | Martinez et al. 2017 "Insolation cycles as driver of Holocene martian climate" | **查无此文**（Geology/GRL 窗口全量扫描、DOI 探针 404、作者主页无） | 倾角周期驱动 = Liu et al. 2023 Nature；Martinez et al. 2017 真实论文 = SSR 210:187 近表面气候综述 |
| 8 | Wordsworth 2016 SSR "The Habitability of Early Mars: Carbon Condensation…" | **查无此文**（疑为两篇真实文献的混合幻觉） | Wordsworth 2016 = AREPS "The Climate of Early Mars"；SSR 综述 = Kite 2019 |
| 9 | 术语 "sandhiatus" | **全网 0 命中** | 真实措辞 = "long globally-dry intervals"（Kite 2019）/"long dry spells"（Kite & Conway 2024） |
| 10 | Limaye 1986 Icarus "Venus: Global structure of winds and temperatures" | **查不到**（CrossRef 全量扫描 Limaye 1986–87 Icarus 仅木星论文） | 环流综述 = Limaye 2007 JGR / Read & Lebonnois 2018 |
| 11 | Limaye et al. 2017 JGR "Venus's polar vortices…" | **查不到** | 极涡 = Ando et al. 2016 Nat Commun；Muto et al. 2017 Icarus（polar oval） |
| 12 | Venus 云层 A/B/C 字母命名 | **查不到** | 实际命名 = upper/middle/lower cloud + hazes（Esposito 1983） |
| 13 | Hamano et al. 2013 Nature "Runaway greenhouse and water loss of early Venus-like planets" | 该标题**查不到** | 真实论文 = Hamano, Abe & Genda 2013 Nature "Emergence of two types of terrestrial planet…" |
| 14 | Glaze et al. 2023 lunar thermal | **不存在**（Crossref 作者检索排除） | Sefton-Nash 2023 Encyclopedia of Lunar Science 条目 |
| 15 | Sefton-Nash et al. 2013 "A survey of lunar polar temperatures" | **查无此文** | Sefton-Nash et al. 2019 Icarus（Amundsen ultra-cold traps） |
| 16 | Williams et al. 2017/2019 题录 | **年份互换** | 全球温度 = Williams 2017 **Icarus**；极区季节 = Williams 2019 **JGR Planets** |
| 17 | Titan 七条预设（Turtle "Rapid…cloud changes" Icarus 2009、Mitchell "22 years of Hubble"、Lora "meteorology of Titan's autumn"、Lora "methane cycle and seasonal cycle"、Tokano "Hydrometeorological variability at Titan's poles"、Faulk 2017 GRL "Seasonal surface hydrology…"、Trainer 2014 "Chemical variability…"） | **全部查不到**（渠道：Crossref 期刊内作者枚举、CICLOPS/科隆/UCLA/Yale 书目页、Lora 2019 参考文献全表） | 云气候 = Turtle 2011 Science/GRL；甲烷循环 GCM = Newman 2016 + Lora 2015；轨道-水文 = **Schneider et al. 2012 Nature**（Faulk 2017 GRL 的内容实际对应此文）；真实 Faulk 2017 = Nat Geo 冲积扇论文 |

**教训**（与仓库 memory「citation-verify-primary-source」一致）：凭印象写入调研提示的引文
错误率极高（本轮 17 处预设引文 0 处完全正确）；所有进入文档的引用必须走「抓到摘要/原文 →
标注核实等级」流程。负结果与勘误本身是本调研的一级产出。

---

## §6 对 UCC v2 的含义（核心产出）

### 6.0 总判断：类均质的根因诊断

四天体 UCC 实测的类分布高度均质（Mars 100% Pn、Titan 100% Pn/Po、Venus 100% Ra-w、
Moon 94% Cn-x + 6% Pn）。本调研的核心发现是：**学界对这些天体同样不做格点级气候分类**——
四个天体全部没有正式分区方案（Mars 唯一尝试是会议摘要、Titan 唯一尝试是本科毕业论文、
Venus/Moon 连「气候分区」概念都不存在）。这不是巧合：这些天体的气候空间信息**本来就不住在
「热量 × 水供需」两轴上**，而住在别处——Venus 住在高度轴与气候态类型学里，Moon 住在光照
几何与挥发分保存判据里，Mars 住在气压-三相点关系与轨道周期里，Titan 住在甲烷收支与纬度-
季节云气候学里。

因此 UCC v2 的正确方向**不是**把热量/供需两轴为这些天体切得更细（那会违反共享阈值纪律，
且没有文献先例），而是三层分工：
1. **世界级前缀**承载「这是哪类行星气候」（runaway/薄 CO2 冷干/甲烷水文/无大气——学界
   跨行星分类最成熟的一支正是这种行星级类型学）；
2. **修饰语/新描述量**承载 cell 级剩余空间信息（高度、光照 regime、气压-相态）；
3. **广义需求模型**让供需轴在可算的世界（Titan）复活、在不可算的世界（Venus 热侧、Moon
   无大气）诚实拒绝。

### 6.1 变量轴 → UCC 三分映射（任务问题 6 的直接回答）

**(a) 描述量已能表达、只是分类轴不分**（改动最小、收益立现）：

| 差异 | 所在天体 | 现状 | 证据 |
|---|---|---|---|
| 高度-温度效应（61 °C t_mean 跨度全在数据里，类码全同） | Venus | t_mean 408–469 °C；100% Ra-w | M&C 1996、Singh 2019、Strezoski & Treiman 2022（雪线=等 T,P 线）——高度是金星表面气候第一变量【一手分区实践】 |
| 季节振幅 vs 日较差（continental 修饰语点亮，语义随 time_basis 变） | Mars 68% / Moon 100% | 修饰语已工作，`time_basis` 声明已随文件走 | Williams 2017 的地方时 binning 与我们 Moon 实测同构【一手实践】 |
| 降水时间集中度（C_TV 0.63，单季风暴主导） | Titan | C_TV 有效输出，不进类码 | Schneider 2012（分点风暴）、Newman 2016（ITCZ 季节迁移）——Titan 降水的季节集中是一级气候特征【一手实践】 |
| 最暖/最冷分箱极值（「能否保存挥发分/越过相变」） | Moon 冷阱、Mars 三相点 | t_max/t_min 已有；冷阱判据（年最高温 <110 K）与 t_max **同构** | Watson 1961 → Williams 2019（110 K ⇔ 1 Gyr）【一手分区实践，阈值属另一物理域】 |

**(b) 需要新描述量**（文献有同构概念，我们缺字段）：

| 缺失描述量 | 天体 | 文献同构 | 证据等级 |
|---|---|---|---|
| 气压 vs 溶剂三相点（p_mean/p_triple 或「箱均越过三相点的时长」） | Mars | Haberle 2001 五个「液态水有利区」（p、T 双越 611 Pa/0 °C，29% 面积） | **一手分区实践** |
| 跨溶剂参考需求 Eref（甲烷版 Hamon：Clausius–Clapeyron 换溶剂潜热/摩尔质量） | Titan | Schneider 2012 收支句、Mitchell 2012 P/E 强度、Faulk 2020 "polar moist climes and equatorial deserts"；Del Genio 2019 III aridity index（系外行星格点级） | **一手概念存在、统一指数属我们首创** |
| 光照 regime（直射光照时间分数 / 最长连续黑暗时长） | Moon（及水星型世界） | Mazarico 2011 PSR 定义与统计、Williams 2019 seasonally shadowed、Sefton-Nash 2019 micro cold traps | **一手分区实践**（但该领域不称之为气候） |
| 升华-凝结预算（冷阱型供需：升华通量 vs 温度阈值 × 时标） | Moon/Mars 极区 | Schorghofer 2025（110 K、100 kg/m²/Gyr「negligible」判据）、Schorghofer & Aharonson 2005（49°/30° 纬度界） | **一手判据存在** |
| 尘/不透明度时序 | Mars | Kass 2016（50 Pa 温度 >200 K 事件阈值）、MCD 有/无全球尘暴情景 | 弱（事件分类实践，非气候分区） |

**(c) 根本不可比**（UCC 不应也无法表达，如实声明边界）：

| 学界变量 | 天体 | 为什么不可比 |
|---|---|---|
| 垂直结构分层（云层 upper/middle/lower、对流区、稳定度、superrotation 域） | Venus/Titan | UCC 只分类**表面**气候；学界这些「分层」是大气柱结构，不是地表分区 |
| 热惯量/反射率/岩石丰度（TI 双轴地形表征） | Moon | 表面物性层（geology），非气候层 |
| 气候态类型学（runaway/moist greenhouse、type I/II、Arid/Aqua 情景 × 地质年代） | Venus/Mars | 时间演化轴与行星级——属世界档案/天文层元数据，不属格点分类（但应做世界级前缀，见轴 F） |
| Köppen 植被拟合语义 | 全部 | 无生命天体无植被锚点；Hargitai 的「thermal criteria only」简化和 Olcott 的三变量尝试都是去掉生物轴后的移植——与我们「Köppen 只作并列参照列」的立场一致 |
| 「气候」一词本身 | Moon | 学界叫 thermal environment；我们给 Moon 出 UCC 类码属于**语义扩展**，须在 time_basis/temperature_kind 声明旁再加一条领域声明（现有 provenance 已部分做到） |

### 6.2 候选新轴清单（按证据强度排序）

> 每轴五项：文献支撑 / 所需新描述量 / 共享阈值纪律兼容性 / 预期区分度收益 / 证据等级
> （**A** = 有一手论文分区实践；**B** = 仅综述或概念提及；**C** = 我们推断）。

**轴 F：世界级气候态前缀（世界档案字段，非 cell 级轴）** —— 证据等级 **A（最强）**
- 文献支撑：跨行星分类最成熟的一支。Wolf 2017 四态（235/250/275–315/330/355 K，全球均温
  阈值）；Goldblatt 2015 禁态区间；Ramirez 2020 阈值随成分/恒星型移动（标定域声明的文献
  依据）；Kasting 1988、Hamano 2013 type I/II、Way & Del Genio 2020 Arid/Aqua-Venus 情景；
  动力 regime 支：Haqq-Misra 2018 三 regime、Noda 2017 Type-I–IV。提案 §3.5/3.6 的 C<n>/TL
  体制码属同一层。
- 所需新描述量：无 cell 级新量；世界档案增 `climate_state:` 声明字段（如 `runaway`/
  `thin_co2_cold`/`methane_hydrology`/`airless`），值由世界作者/引擎从天文-大气输入派生。
- 共享阈值兼容性：**完全兼容**——世界级声明不改 cell 级共享阈值；正是「方案与档案分离」
  原则（提案 §2.2）的用途。
- 区分度收益：直接回应「类分布均质」的第一根因——Venus 是 runaway 态、Mars 是薄 CO2 冷干
  态、Moon 无大气，这些信息本在世界级；让 cell 级分类硬表达世界类型是层次错误。四天的
  100% 同类分布加上前缀后立即可读（`runaway:Ra-w` vs `methane:Pn` 语义完全不同）。
- 备注：学界行星级分类（一球一态）与格点级分类（Köppen 谱系）在文献中**不互通**；UCC 用
  前缀把两层接起来，无直接先例但两半各有一手支撑。

**轴 B：高度-气压修饰语（-H）+ 三相点关系描述量** —— 证据等级 **A**
- 文献支撑：Venus 表面气候 = f(z)（M&C 1996 递减率、Singh 2019 13 km→100 K、Strezoski &
  Treiman 2022 雪线=等 T,P 等高线、VIRA 变量轴=(h,lat)）；Mars 液态水有利区按 p>611 Pa
  划界（Haberle 2001，29% 面积）；提案 §3.7 已有 Trewartha 式 -H 设计（海平面修正后热量带
  改变 → 标记「海拔抬出来的带」），§9 已否证「局部气压液窗」方向（θ 只用 P₀）。
- 所需新描述量：cell 高度/气压已在 mesh 数据里（Venus 文件带 surface_pressure、Mars 带
  MOLA 高程）；分类器只需「递减率修正后落带是否改变」判定 + （可选）`p_triple_margin`
  描述量 = p_mean 相对主导溶剂三相点的比值。递减率是声明的经验值（认识论类别：近似推导，
  干绝热 g/Cp 可派生——Venus 7.6 K/km = g/Cp 正是推导值）。
- 共享阈值兼容性：兼容——修饰语不改主类；-H 判据用的递减率全局共享（按世界气体常数/重力
  派生，属「可推导量」，满足引擎纪律第 1 条）。
- 区分度收益：Venus 100% Ra-w 立即分裂为「高地（408–437 °C）/低地（448–469 °C）」两个
  可读单元——这是金星表面唯一真实的气候分异；Mars 可标记「夏季正午越过三相点」的低地
  （Hellas/Argyre 与实测 t_max −28.7 °C 的日均口径差异正好说明需要更高频数据或三相点
  描述量来承载这条信息）。
- 备注：与热侧域门联动——Venus 装门翻 Rn 后，-H 是剩余的唯一空间信息，收益反而更大。

**轴 C：广义挥发分供需（跨溶剂 AI + 升华预算）** —— 证据等级 **B+（一手概念、无统一指数）**
- 文献支撑：Titan 收支语言（Schneider 2012 净降水−输运−蒸发平衡、Mitchell 2012 P/E 强度、
  Faulk 2020 polar moist/equatorial deserts、Faulk 2017 极端降水-冲积扇对应）；Mars 古气候
  aridity index 显式 "climate zonation"（Kite & Noblet 2022）；Moon/Mercury 冷阱 = 升华
  预算判据（Watson 1961、Williams 2019、Schorghofer 2025）；系外行星格点级先例 Del Genio
  2019 III。**没有任何文献把这三者统一成一个跨溶剂指数**——统一化属我们首创（提案 §3.2
  已预留「跨溶剂 PET 广义化是 Phase 3」）。
- 所需新描述量：溶剂表（相窗、潜热、摩尔质量——提案 §3.1 已有设计）+ 溶剂版参考需求模型
  （Clausius–Clapeyron 广义 Hamon 或直接能量收支式）；冷阱型世界用「升华通量 vs 保存时标」
  替代 Eref。`demand_model` 元数据字段已存在，换声明即可（知识文档 §4 的升级路径已写明）。
- 共享阈值兼容性：**有条件兼容**——AI 阈值（0.2/0.5/1.0）可全局共享，但必须声明「同一
  指数在不同溶剂下的标定域未经验证」（与 Hamon 声明同构）；溶剂物性常数是可推导量，不是
  裸调参数。风险：泰坦实测 P 从赤道 11–19 mm 到南极 3785–4084 mm（两个量级以上跨度），
  广义 Eref 落地后 AI 区分度预期显著，但正确性无从对标观测（Titan 无实测降水气候学）——
  验收只能走「模型自洽 + 与文献区域词汇定性对应」（双轨验收的创作轨）。
- 区分度收益：Titan 从全 Pn 变为可分「极地湖区（湿）/中纬（过渡）/赤道沙丘带（干）」——
  正是文献区域词汇的类码化；这是四天体中唯一「供需轴复活后有大收益」的世界。Mars 升华霜
  预算可作二级收益（痕量、不冒充降水——保持声明式导入纪律）。

**轴 D：光照 regime 描述量（无大气天体）** —— 证据等级 **A（词汇一手）+ C（纳入 UCC 是我们推断）**
- 文献支撑：PSR 正式定义与面积统计（Mazarico 2011）、cold trap 操作判据（Williams 2019：
  年最高温 <110 K ⇔ 保存 >1 Gyr）、seasonally shadowed / micro cold trap / 近永久光照
  （Sefton-Nash 2019、Mazarico 2011）；Mercury 完整复用（Deutsch 2016/2018）。
- 所需新描述量：`illumination_fraction`（直射光照时间分数，几何可算）或直接从现有地方时
  分箱派生「全箱无直射」判据；挥发分保存门 = t_max < T_coldtrap（溶剂相关阈值，水=110 K
  有文献、CO2/CH4 冷阱温度可由相图派生）。
- 共享阈值兼容性：兼容——光照分数是几何量（无自由参数）；冷阱阈值来自溶剂相图+保存时标
  声明（110 K ⇔ 1 Gyr 是文献值，换时标须重新声明）。但注意学界判据针对**表面峰值温度**
  （非分箱均值），我们 t_max 是分箱均值极值——口径差异须声明（与知识文档 §2「分箱均值
  不是天气」同一条纪律）。
- 区分度收益：Moon 5.9% Pn 中可区分「永影冷阱（有冰潜力）」与「高纬正常光照区」；94%
  Cn-x 内部不变（学界对非极区月面同样不做更细分区——zonal mean + 距平已是全部）。收益
  中等，但它是「月面唯一有正式分类词汇的轴」，且水星/其他无大气世界直接复用。
- 诚实声明：把 PSR/cold trap 纳入「气候分类」是我们对学界 thermal environment 词汇的
  语义扩展（学界不用 climate 一词）——文件 provenance 须携带该声明。

**轴 E：尘/凝结循环（不透明度轴）** —— 证据等级 **C（弱，建议缓行）**
- 文献支撑：Mars 尘暴 global/regional A/B/C（Kass 2016 有显式阈值，但是**事件**分类）；
  MCD「有/无全球尘暴」情景；Titan 霾（Hörst 2017，化学-气候耦合，无分区实践）。
- 所需新描述量：柱不透明度/尘载荷时序——我们的数据链（MCD 导出）目前不含。
- 共享阈值兼容性：无文献先例阈值可共享（200 K@50 Pa 是事件判据，不能直接挪用为气候分箱）。
- 区分度收益：不明——四天体实测的类均质根因都不是尘（Mars 均质因温度全在冷侧门下）。
- 判定：**不满足「没有可重复证据就不添加」的停止规则**（与 v1 拒绝降水集中度修饰语同一
  标准），缓行；若未来做火星尘暴季节的工作世界再议。

### 6.3 前置修复（非新轴，登记缺口）

**热侧域门**：Venus 实测 100% Ra-w 是「契约有效、物理无意义」的活体实锤（Hamon 在 737 K
纯算术外推）。文献侧佐证：Ramirez 2020 证明温度阈值型分类的阈值随大气成分移动——任何
需求/分类公式都有标定域。落地后 Venus 翻 Rn，与冷侧 OOD 门对称。这是 v2 的先决项，
已在知识文档 §8 登记。

### 6.4 优先级与验证路径建议

1. **热侧域门**（修复，先行）→ Venus 类码翻正。
2. **轴 F 世界级前缀**（世界档案字段 + 前端显示）→ 四天体类均质立即获得语境；不动分类器。
3. **轴 B -H 修饰语**（提案 §3.7 设计已成熟，数据已在）→ Venus 内部第一次出现空间分异；
   Mars 得三相点标记（可选描述量 `p_triple_margin`）。
4. **轴 C 广义供需**（工作量最大：溶剂表 + 甲烷 Eref）→ Titan 供需轴复活；验收走双轨
   （模型自洽 + 与文献区域词汇定性对应），AI 阈值保持全局共享并声明跨溶剂标定域未验证。
5. **轴 D 光照 regime**（小描述量 + 语义扩展声明）→ Moon 冷阱可辨；顺带覆盖水星型世界。
6. **轴 E 尘轴**：缓行（停止规则）。

每步遵守「每轮只新增一个闭合假设」纪律：1–3 可合并为一轮（都不动 AI 语义），4 单独一轮
（改需求模型 = 改 AI 语义版本），5 单独一轮。所有新阈值注明认识论类别（守恒/近似推导/
观测拟合/数值稳定化）与标定域。

---

## §7 参考文献全表

状态标记：**[原文]** = 已核实原文（抓到摘要/全文并确认所引判据）；**[摘要]** = 仅摘要；
**[元数据]** = 题录经 Crossref/OpenAlex 等交叉核实、摘要未抓到；**[间接]** = 内容经其他
已核实原文引述确认；**[全文]** = 开放获取全文已读。检索与抓取渠道全记录见各证据文件。

### Mars（§1）

- Hargitai, H. (2010). "Mars climate zone map based on TES data." LPSC XLI, #1199. **[原文-全文]**
- Haberle, R.M., McKay, C.P., Schaeffer, J., Cabrol, N.A., Grin, E.A., Zent, A.P., Quinn, R. (2001). "On the possibility of liquid water on present-day Mars." *JGR Planets* 106(E10):23317–23326. doi:10.1029/2000JE001360. **[原文]**
- Schorghofer, N., Aharonson, O. (2005). "Stability and exchange of subsurface ice on Mars." *JGR Planets* 110:E05003. doi:10.1029/2004JE002350. **[原文]**
- Kass, D.M., Kleinböhl, A., McCleese, D.J., Schofield, J.T., Smith, M.D. (2016). "Interannual similarity in the Martian atmosphere during the dust storm season." *GRL* 43:6111–6118. doi:10.1002/2016GL068978. **[原文]**
- Zurek, R.W., Martin, L.J. (1993). "Interannual variability of planet-encircling dust storms on Mars." *JGR* 98(E2):3247–3259. doi:10.1029/92JE02936. **[元数据]**
- Kite, E.S., Noblet, A. (2022). "High and Dry: Billion-Year Trends in the Aridity of River-Forming Climates on Mars." *GRL* 49:e2022GL101150. doi:10.1029/2022GL101150. **[原文]**
- Kite, E.S., Conway, S.J. (2024). "Geological evidence for multiple climate transitions on Early Mars." *Nature Geoscience* 17:10–19. doi:10.1038/s41561-023-01349-2. **[原文]**
- Kite, E.S. (2019). "Geologic Constraints on Early Mars Climate." *Space Sci. Rev.* 215:16. doi:10.1007/s11214-018-0575-5. **[原文]**
- Wordsworth, R. (2016). "The Climate of Early Mars." *Annu. Rev. Earth Planet. Sci.* 44:381–408. doi:10.1146/annurev-earth-060115-012355. **[原文]**
- Watanabe, Y., Tajika, E., Kamada, A. (2025). "Behaviors of Martian CO2-driven dry climate system and conditions for atmospheric collapses." *Icarus* 116795. doi:10.1016/j.icarus.2025.116795. **[摘要]**
- Liu, J., et al.（含 Head, J., Li, C.）(2023). "Martian dunes indicative of wind regime shift in line with end of ice age." *Nature* 620:303–309. doi:10.1038/s41586-023-06206-1. **[原文]**
- Forget, F., Haberle, R.M., Montmessin, F., Levrard, B., Head, J.W. (2006). "Formation of Glaciers on Mars by Atmospheric Precipitation at High Obliquity." *Science* 311:368–371. doi:10.1126/science.1120335. **[原文]**
- Laskar, J., Correia, A.C.M., Gastineau, M., Joutel, F., Levrard, B., Robutel, P. (2004). "Long term evolution and chaotic diffusion of the insolation quantities of Mars." *Icarus* 170:343–364. doi:10.1016/j.icarus.2004.04.005. **[元数据]**
- Forget, F., Hourdin, F., Fournier, R., et al. (1999). "Improved general circulation models of the Martian atmosphere from the surface to above 80 km." *JGR* 104(E10):24155–24175. doi:10.1029/1999JE001025. **[原文]**
- Lewis, S.R., Collins, M., Read, P.L., Forget, F., et al. (1999). "A climate database for Mars." *JGR* 104(E10):24177–24194. doi:10.1029/1999JE001024. **[元数据]**
- Millour, E., Forget, F., Spiga, A., et al. (2018/2026). "The Mars Climate Database (MCD version 5.3)" HAL insu-04393379；"The Latest Mars Climate Database, MCD version 6.2" EPSC 2026, HAL hal-05732751. **[原文-摘要]**
- Martinez, G.M., Newman, C.N., et al.（16 人）(2017). "The Modern Near-Surface Martian Climate: A Review of In-situ Meteorological Data from Viking to Curiosity." *Space Sci. Rev.* 210:187–290. doi:10.1007/s11214-017-0360-x. **[原文]**
- Newman, C.E., de la Torre-Juárez, M., et al.（17 人）(2021). "Multi-model Meteorological and Aeolian Predictions for Mars 2020 and the Jezero Crater Region." *Space Sci. Rev.* 217:20. doi:10.1007/s11214-020-00788-2. **[原文]**
- Hecht, M.H. (2002). "Metastability of Liquid Water on Mars." *Icarus* 156(2):373–386. doi:10.1006/icar.2001.6794. **[原文]**
- Mellon, M.T., Jakosky, B.M. (1995). "The distribution and behavior of Martian ground ice during past and present epochs." *JGR* 100(E6):11781–11799. doi:10.1029/95JE01027. **[元数据]**

### Titan（§2）

- Schneider, T., Graves, S.D.B., Schaller, E.L., Brown, M.E. (2012). "Polar methane accumulation and rainstorms on Titan from simulations of the methane cycle." *Nature* 481:58–61. doi:10.1038/nature10666. **[原文]**
- Faulk, S.P., Lora, J.M., Mitchell, J.L., Milly, P.C.D. (2020). "Titan's climate patterns and surface methane distribution due to the coupling of land hydrology and atmosphere." *Nature Astronomy* 4:390–398. doi:10.1038/s41550-019-0963-0. **[原文]**
- Faulk, S.P., Mitchell, J.L., Moon, S., Lora, J.M. (2017). "Regional patterns of extreme precipitation on Titan consistent with observed alluvial fan distribution." *Nature Geoscience* 10:827–831. doi:10.1038/ngeo3043. **[原文]**
- Newman, C.E., Richardson, M.I., Lian, Y., Lee, C. (2016). "Simulating Titan's methane cycle with the TitanWRF General Circulation Model." *Icarus* 267:106–134. doi:10.1016/j.icarus.2015.11.028. **[原文-全文]**
- Lora, J.M., Lunine, J.I., Russell, J.L. (2015). "GCM simulations of Titan's middle and lower atmosphere and comparison to observations." *Icarus* 250:516–528. doi:10.1016/j.icarus.2014.12.030. **[原文]**
- Lora, J.M., Tokano, T., Vatant d'Ollone, J., Lebonnois, S., Lorenz, R.D. (2019). "A model intercomparison of Titan's climate and low-latitude environment." *Icarus* 333:113–126. doi:10.1016/j.icarus.2019.05.031. **[原文-全文]**
- Lora, J.M., Mitchell, J.L. (2015). "Titan's asymmetric lake distribution mediated by methane transport due to atmospheric eddies." *GRL* 42:6213–6220. doi:10.1002/2015GL064912. **[元数据]**
- Lora, J.M. (2024). "Moisture transport and the methane cycle of Titan's lower atmosphere." *Icarus* 422:116241. doi:10.1016/j.icarus.2024.116241. **[元数据]**
- Lora, J.M., Lunine, J.I., Russell, J.L., Hayes, A.G. (2014). "Simulations of Titan's paleoclimate." *Icarus* 243:264–273. doi:10.1016/j.icarus.2014.08.042. **[元数据]**
- Rodriguez, S., et al. (2011). "Titan's cloud seasonal activity from winter to spring with Cassini/VIMS." *Icarus* 216:89–110. doi:10.1016/j.icarus.2011.07.031. **[原文-全文]**
- Rodriguez, S., et al. (2009). "Global circulation as the main source of cloud activity on Titan." *Nature* 459:678–682. doi:10.1038/nature08014. **[原文]**
- Brown, M.E., Roberts, J.E., Schaller, E.L. (2010). "Clouds on Titan during the Cassini prime mission: A complete analysis of the VIMS data." *Icarus* 205:571–580. doi:10.1016/j.icarus.2009.08.024. **[原文-全文]**
- Brown, M.E., et al. (2009). "Discovery of lake-effect clouds on Titan." *GRL* 36:L01103. doi:10.1029/2008GL035964. **[原文]**
- Turtle, E.P., et al. (2011). "Rapid and extensive surface changes near Titan's equator: Evidence of April showers." *Science* 331:1414–1417. doi:10.1126/science.1201063. **[原文]**
- Turtle, E.P., et al. (2011). "Seasonal changes in Titan's meteorology." *GRL* 38:L03203. doi:10.1029/2010GL046266. **[原文-全文]**
- Turtle, E.P., et al. (2018). "Titan's Meteorology Over the Cassini Mission: Evidence for Extensive Subsurface Methane Reservoirs." *GRL* 45:5320–5328. doi:10.1029/2018GL078170. **[原文]**
- Schaller, E.L., Roe, H.G., Schneider, T., Brown, M.E. (2009). "Storms in the tropics of Titan." *Nature* 460:873–875. doi:10.1038/nature08193. **[原文]**
- Roe, H.G., et al. (2005). "Geographic Control of Titan's Mid-Latitude Clouds." *Science* 310:477–479. doi:10.1126/science.1116760. **[原文]**
- Griffith, C.A., et al. (2005). "The Evolution of Titan's Mid-Latitude Clouds." *Science* 310:474–477. doi:10.1126/science.1117702. **[原文]**
- Rannou, P., Montmessin, F., Hourdin, F., Lebonnois, S. (2006). "The latitudinal distribution of clouds on Titan." *Science* 311:201–205. doi:10.1126/science.1118424. **[原文]**
- Tokano, T., McKay, C.P., Neubauer, F.M., et al. (2006). "Methane drizzle on Titan." *Nature* 442:432–435. doi:10.1038/nature04948. **[原文]**
- Tokano, T. (2011). "Precipitation Climatology on Titan." *Science* 331:1393–1394. doi:10.1126/science.1204092. **[原文-摘要]**（正文 Köppen 句未核实）
- Tokano, T. (2008). "Dune-forming winds on Titan and the influence of topography." *Icarus* 194:243–262. doi:10.1016/j.icarus.2007.10.007. **[元数据]**
- Tokano, T. (2009). "Impact of seas/lakes on polar meteorology of Titan: Simulation by a coupled GCM-Sea model." *Icarus* 204:619–636. doi:10.1016/j.icarus.2009.07.032. **[元数据]**
- Mitchell, J.L., Ádámkovics, M., Caballero, R., Turtle, E.P. (2011). "Locally enhanced precipitation organized by planetary-scale waves on Titan." *Nature Geoscience* 4:589–592. doi:10.1038/ngeo1219. **[原文]**
- Mitchell, J.L. (2012). "Titan's transport-driven methane cycle." *ApJL* 756:L26. doi:10.1088/2041-8205/756/2/L26. **[原文-摘要]**
- Mitchell, J.L., Lora, J.M. (2016). "The Climate of Titan." *Annu. Rev. Earth Planet. Sci.* 44:353–380. doi:10.1146/annurev-earth-060115-012428. **[原文]**
- Hayes, A.G., Lorenz, R.D., Lunine, J.I. (2018). "A post-Cassini view of Titan's methane-based hydrologic cycle." *Nature Geoscience* 11:306–313. doi:10.1038/s41561-018-0103-y. **[原文]**
- Hörst, S.M. (2017). "Titan's atmosphere and climate." *JGR Planets* 122:432–482. doi:10.1002/2016JE005240. **[原文-摘要]**
- Roe, H.G. (2012). "Titan's Methane Weather." *Annu. Rev. Earth Planet. Sci.* 40:355–382. doi:10.1146/annurev-earth-040809-152548. **[原文]**
- Olcott (2024). "Titan's Hydrologic Cycle." Yale senior thesis（非同行评审）. **[原文-全文]**

### Venus（§3）

- Meadows, V.S., Crisp, D. (1996). "Ground-based near-infrared observations of the Venus nightside: The thermal structure and water abundance near the surface." *JGR* 101:4595–4622. doi:10.1029/95JE03567. **[原文]**
- Seiff, A. (1983). "Thermal structure of the atmosphere of Venus." in *Venus* (Univ. Arizona Press), 215–279. doi:10.2307/j.ctv25c4z16.15. **[间接]**（递减率数值经 M&C 1996 摘要引述核实）
- Seiff, A., Schofield, J.T., Kliore, A.J., Taylor, F.W., Limaye, S.S., et al. (1985). "Models of the structure of the atmosphere of Venus from the surface to 100 kilometers altitude"（VIRA）. *Adv. Space Res.* 5(11):3–58. doi:10.1016/0273-1177(85)90197-8. **[元数据]**（内容经四个独立已核实来源交叉确认）
- Singh, S. (2019). "Venus nightside surface temperature." *Sci. Rep.* 9:1137. doi:10.1038/s41598-018-38117-x. **[原文-全文]**（⚠️ 部分结论非常规，慎引）
- Strezoski, G., Treiman, A. (2022). "The 'Snow Line' on Venus's Maxwell Montes: Varying Elevation Implies a Dynamic Atmosphere." *Planet. Sci. J.* 3. doi:10.3847/PSJ/ac9f3a. **[原文]**
- Lebonnois, S., Schubert, G. (2017). "The deep atmosphere of Venus and the possible role of density-driven separation of CO2 and N2." *Nature Geoscience* 10:470–473. doi:10.1038/ngeo2971. **[原文]**
- Lebonnois, S., et al. (2010). "Superrotation of Venus' atmosphere analyzed with a full general circulation model." *JGR* 115. doi:10.1029/2009JE003458. **[原文]**
- Read, P.L., Lebonnois, S. (2018). "Superrotation on Venus, on Titan, and Elsewhere." *Annu. Rev. Earth Planet. Sci.* 46:175–202. doi:10.1146/annurev-earth-082517-010137. **[原文-全文]**
- Tellmann, S., Pätzold, M., Häusler, B., Bird, M.K., Tyler, G.L. (2009). "Structure of the Venus neutral atmosphere as observed by the Radio Science experiment VeRa on Venus Express." *JGR* 114. doi:10.1029/2008JE003204. **[原文]**
- Ando, E., Sugimoto, N., Takagi, M., Kashimura, Y., Imamura, T., Matsuda, H. (2016). "The puzzling Venusian polar atmospheric structure reproduced by a general circulation model." *Nature Communications* 7:10398. doi:10.1038/ncomms10398. **[原文]**
- Ando, E., et al. (2020). "Thermal structure of the Venusian atmosphere from the sub-cloud region to the mesosphere as observed by radio occultation." *Sci. Rep.* 10:3448. doi:10.1038/s41598-020-59278-8. **[原文-全文]**
- Esposito, L.W., Knollenberg, R.G., Marov, M.Ya., Toon, O.B., Turco, R.P. (1983). "The clouds and hazes of Venus." in *Venus* (Univ. Arizona Press), 484–564. doi:10.2307/j.ctv25c4z16.20. **[原文-摘要]**
- Moroz, L.V., Rodin, A.V. (2002). "How Many Convective Zones Are There in the Atmosphere of Venus?" *Solar System Research* 36:492–494. doi:10.1023/A:1022105219868. **[原文]**
- Linkin, V.M., et al. (1986). "Thermal Structure of the Venus Atmosphere in the Middle Cloud Layer." *Science* 231(4744):1420. doi:10.1126/science.231.4744.1420. **[原文]**
- Limaye, S.S., Lebonnois, S., Mahieux, A., et al. (2017). "The thermal structure of the Venus atmosphere: Intercomparison of Venus Express and ground based observations of vertical temperature and density profiles." *Icarus* 294:124–155. doi:10.1016/j.icarus.2017.04.020. **[原文]**
- Martinez, C., Karyu, H., Brecht, A., Gilli, G., Lebonnois, S., Kuroda, T., et al. (2025/2026). "Comparison of General Circulation Models of the Venus upper atmosphere." *Icarus*. doi:10.1016/j.icarus.2025.116901; arXiv:2512.16693. **[原文-摘要]**
- Justh, N.R., Cianciolo, A., Hoffman, C. (2021). "Venus Global Reference Atmospheric Model (Venus-GRAM): User Guide." NASA/TM-20210022168. **[原文-全文]**
- Kasting, J.F. (1988). "Runaway and moist greenhouse atmospheres and the evolution of Earth and Venus." *Icarus* 74:472–494. doi:10.1016/0019-1035(88)90116-9. **[元数据+间接]**
- Hamano, K., Abe, Y., Genda, H. (2013). "Emergence of two types of terrestrial planet on solidification of magma ocean." *Nature* 497:607–610. doi:10.1038/nature12163. **[原文]**
- Donahue, T.M., Hoffman, J.H., Hodges, R.R., Watson, A.J. (1982). "Venus Was Wet: A Measurement of the Ratio of Deuterium to Hydrogen." *Science* 216(4546):630–633. doi:10.1126/science.216.4546.630. **[原文]**
- Way, M.J., Anthony, A., Del Genio, A.D., Loeb, N., Kiang, N.Y., Way, S., Wolf, E.T. (2016). "Was Venus the first habitable world of our solar system?" *GRL* 43. doi:10.1002/2016GL069790. **[原文]**
- Way, M.J., Del Genio, A.D. (2020). "Venusian Habitable Climate Scenarios: Modeling Venus Through Time and Applications to Slowly Rotating Venus-Like Exoplanets." *JGR Planets* 125(5):e2019JE006276. doi:10.1029/2019JE006276. **[原文-全文]**
- Limaye, S.S., Zhang, P., et al. (2007). "Venus atmospheric circulation: Known and unknown." *JGR Planets* 112. doi:10.1029/2006JE002814. **[元数据]**（勘误 #10 替代锚）
- Muto, M., et al. (2017). "Morphology and temporal variation of the polar oval of Venus revealed by VMC/Venus Express visible and UV images." *Icarus* 295:110–118. doi:10.1016/j.icarus.2017.06.014. **[元数据]**（勘误 #11 替代锚）

### Moon / 无大气天体（§4）

- Watson, K., Murray, B.C., Brown, H. (1961a). "On the Possible Presence of Ice on the Moon." *JGR* 66(5):1598–1600. doi:10.1029/JZ066i005p01598. **[原文-全文]**
- Watson, K., Murray, B.C., Brown, H. (1961b). "The behavior of volatiles on the lunar surface." *JGR* 66(9):3033–3045. doi:10.1029/JZ066i009p03033. **[摘要]**
- Paige, D.A., Siegler, M.A., Zhang, J.A., et al. (2010). "Diviner Lunar Radiometer Observations of Cold Traps in the Moon's South Polar Region." *Science* 330(6003):479–482. doi:10.1126/science.1187726. **[摘要]**（双源一致）
- Williams, J.-P., Paige, D.A., Greenhagen, B.T., Sefton-Nash, E. (2017). "The global surface temperatures of the Moon as measured by the Diviner Lunar Radiometer Experiment." *Icarus* 283:300–325. doi:10.1016/j.icarus.2016.08.012. **[原文-全文]**
- Williams, J.-P., Greenhagen, B.T., Paige, D.A., Schorghofer, N., Sefton-Nash, E., Hayne, P.O., Lucey, P.G., Siegler, M.A., Aye, K.-N. (2019). "Seasonal Polar Temperatures on the Moon." *JGR Planets* 124:2505–2521. doi:10.1029/2019JE006028. **[摘要]**
- Mazarico, E., Neumann, G.A., Smith, D.E., Zuber, M.T., Torrence, M.H. (2011). "Illumination conditions of the lunar polar regions using LOLA topography." *Icarus* 211(2):1066–1081. doi:10.1016/j.icarus.2010.10.030. **[摘要]**（NTRS 官方）
- Sefton-Nash, E., Williams, J.-P., Greenhagen, B.T., et al. (2019). "Evidence for ultra-cold traps and surface water ice in the lunar south polar crater Amundsen." *Icarus* 332:1–13. doi:10.1016/j.icarus.2019.06.002. **[摘要]**
- Sefton-Nash, E. (2023). "Surface and Near-Surface Thermal Environment of the Moon." *Encyclopedia of Lunar Science*, Springer. doi:10.1007/978-3-319-14541-9_14. **[元数据]**
- Schorghofer, N. (2025). "Current Theories of Lunar Ice." arXiv:2502.06056. **[原文-全文]**
- Gläser, P., Sanin, A., Williams, J.-P., Mitrofanov, I., Oberst, J. (2021). "Temperatures Near the Lunar Poles and Their Correlation With Hydrogen Predicted by LEND." *JGR Planets* 126:e2020JE006598. doi:10.1029/2020JE006598. **[摘要]**
- Deutsch, A.N., Chabot, N.L., Mazarico, E., Ernst, C.M., Head, J.W., Neumann, G.A. (2016). "Comparison of areas in shadow from imaging and altimetry in the north polar region of Mercury and implications." *Icarus* 280:158–171. doi:10.1016/j.icarus.2016.06.015. **[摘要]**
- Deutsch, A.N., et al. (2018). "Ice in Micro Cold Traps on Mercury: Implications for Age and Origin." *JGR Planets*. doi:10.1029/2018JE005644. **[摘要]**（NTRS 稿）
- Vasavada, A.R., Paige, D.A., Wood, S.E. (1999). "Near-Surface Temperatures on Mercury and the Moon and the Stability of Polar Ice Deposits." *Icarus* 141(2):179–193. doi:10.1006/icar.1999.6175. **[元数据]**
- McGovern, J.A., Bussey, D.B., Greenhagen, B.T., Paige, D.A., Cahill, J.T., Spudis, P.D. (2013). "Mapping and characterization of non-polar permanent shadows on the lunar surface." *Icarus* 223:566–581. **[间接]**（经 Williams 2017 全文参考表核实）
- Kramm, G., Mölders, N., Berger, S., Dlugi, R. (2022). "On the Solar Climate of the Moon and the Resulting Surface Temperature Distribution." *Natural Science* (SCIRP) 14:386–420. doi:10.4236/ns.2022.149034. **[元数据]**（「climate」标题级反例）

### 通用框架（§5）

- Wolf, E.T., Shields, A.L., Kopparapu, R.K., Haqq-Misra, J., Toon, O.B. (2017). "Constraints on Climate and Habitability for Earth-like Exoplanets Determined from a General Circulation Model." *ApJ* 837:107. doi:10.3847/1538-4357/aa5ffc; arXiv:1702.03315. **[原文]**
- Goldblatt, C. (2015). "Habitability of waterworlds: runaway greenhouses, atmospheric expansion and multiple climate states of pure water atmospheres." *Astrobiology*. doi:10.1089/ast.2014.1268; arXiv:1503.04835. **[原文]**
- Ramirez, R.M. (2020). "The effect of high nitrogen pressures on the habitable zone and an appraisal of greenhouse states." *MNRAS* 494:259–270. doi:10.1093/mnras/staa603. **[原文]**
- Abe, Y., Abe-Ouchi, A., Sleep, N.H., Zahnle, K.J. (2011). "Habitable Zone Limits for Dry Planets." *Astrobiology* 11(5):443–460. doi:10.1089/ast.2010.0545. **[原文]**
- Yang, J., Ding, F., Ramirez, R.M., Peltier, W.R., Hu, Y., Liu, Y. (2017). "Abrupt climate transition of icy worlds from snowball to moist or runaway greenhouse." *Nature Geoscience* 10:556–560. doi:10.1038/ngeo2994. **[原文]**
- Leconte, J., Forget, F., Charnay, B., Wordsworth, R., Pottier, A. (2013). "Increased insolation threshold for runaway greenhouse processes on Earth-like planets." *Nature* 504:268–271. doi:10.1038/nature12827. **[原文]**
- Forget, F., Leconte, J. (2014). "Possible climates on terrestrial exoplanets." *Phil. Trans. R. Soc. A* 372:20130084. doi:10.1098/rsta.2013.0084. **[原文]**
- Haqq-Misra, J., Wolf, E.T., Joshi, M., Zhang, X., Kopparapu, R.K. (2018). "Demarcating Circulation Regimes of Synchronously Rotating Terrestrial Planets within the Habitable Zone." *ApJ* 852:67. doi:10.3847/1538-4357/aa9f1f; arXiv:1710.00435. **[原文]**
- Noda, S., Ishiwatari, M., Nakajima, K., et al. (2017). "The circulation pattern and day-night heat transport in the atmosphere of a synchronously rotating aquaplanet: Dependence on planetary rotation rate." *Icarus* 282:1–18. doi:10.1016/j.icarus.2016.09.004. **[原文]**
- Kaspi, Y., Showman, A.P. (2015). "Atmospheric dynamics of terrestrial exoplanets over a wide range of orbital and atmospheric parameters." *ApJ* 804:60. doi:10.1088/0004-637X/804/1/60; arXiv:1407.6349. **[原文]**
- Way, M.J., Del Genio, A.D., Aleinov, I., Clune, T.L., Kelley, M., Kiang, N.Y. (2019). "Climates of Warm Earth-like Planets I: 3-D Model Simulations." *ApJS*. doi:10.3847/1538-4365/aae9e1; arXiv:1808.06480. **[原文]**
- Del Genio, A.D., Way, M.J., Kiang, N.Y., Aleinov, I., Puma, M.J., Cook, B. (2019). "Climates of Warm Earth-Like Planets III: Fractional Habitability from a Water Cycle Perspective." *ApJ*. doi:10.3847/1538-4357/ab57fd; arXiv:1910.03479. **[原文]**（UCC 供需档最近先例：aridity index = net supply of water to the land）
- Yang, J., Leconte, J., Wolf, E.T., Merlis, T.A., Koll, D.D.B., Forget, F., Abbot, D.S. (2019). "Simulations of Water Vapor and Clouds on Rapidly Rotating and Tidally Locked Planets: a 3D Model Intercomparison." *ApJ* 875. doi:10.3847/1538-4357/ab09f1; arXiv:1912.11329. **[原文]**
- Fauchez, T.J., Turbet, M., Selsis, F., et al.（13 人）(2020). "TRAPPIST-1 Habitable Atmosphere Intercomparison (THAI). Motivations and protocol version 1.0." *GMD* 13:707–716. doi:10.5194/gmd-13-707-2020; arXiv:2002.10950. **[原文]**
- Turbet, M., Ehrenreich, D., Lovis, C., et al. (2022). "THAI. I. Dry Cases—The Fellowship of the GCMs." *PSJ* 3:211. doi:10.3847/PSJ/ac6cf0. **[原文]**
- Sergeev, D.E., et al. (2022). "THAI. II. Moist Cases—The Two Waterworlds." *PSJ* 3:212. doi:10.3847/PSJ/ac6cf2. **[原文]**
- Fauchez, T.J., et al. (2022). "THAI. III. Simulated Observables—the Return of the Spectrum." *PSJ*. doi:10.3847/PSJ/ac6cf1. **[原文]**
- Sohl, L.E., Fauchez, T.J., Domagal-Goldman, S., et al. (2024). "The CUISINES Framework for Conducting Exoplanet Model Intercomparison Projects, Version 1.0." *PSJ* 5:175. doi:10.3847/PSJ/ad5830; arXiv:2406.09275. **[原文]**
- Zhang, X. (2020). "Atmospheric Regimes and Trends on Exoplanets and Brown Dwarfs." *Res. Astron. Astrophys.* 20(7):99. doi:10.1088/1674-4527-20-7/099; arXiv:2006.13384. **[原文]**
- Shields, A.L. (2019). "The Climates of Other Worlds: A Review of the Emerging Field of Exoplanet Climatology." *ApJS* 243:30. doi:10.3847/1538-4365/ab2fe7. **[原文]**
- Plávalová, E., Rosaev, A. (2024). "Classifications for Exoplanet and Exoplanetary Systems – Could it be developed? I. Exoplanet classification." arXiv:2409.09666. **[原文]**
- Wester, K., Bergwall, F. (2025). "Is Earth the exception? Probing TRAPPIST-1 Habitability through Mars' and Earth's Past." Uppsala University 硕士论文, DiVA diva2:2023931. **[原文-摘要]**（Köppen-Geiger 跨世界应用唯一正式实例，非同行评审）
- Kiang, N.Y., Lui, C.Y.J., Sohl, L., Guzewich, S. (2026). "Ent Köppen-Geiger v1.0, a software tool for generating Earth System Model global vegetation boundary conditions for alternative climates." EGUsphere 预印本. doi:10.5194/egusphere-2026-4262. **[原文]**
- Lohmann, U., Sausen, R., Bengtsson, L., Cubasch, U., Perlwitz, J., Roeckner, E. (1993). "The Köppen climate classification as a diagnostic tool for general circulation models." *Climate Research* 3:177–193. doi:10.3354/cr003177. **[元数据]**
- Méndez, A., Rivera-Valentín, E.G., Schulze-Makuch, D., et al.（20+ 人）(2021). "Habitability Models for Astrobiology." *Astrobiology* 21(8):1017–1027. doi:10.1089/ast.2020.2342. **[原文]**
- Haqq-Misra, J. (2026). "Exploring TRAPPIST-1 Climate States with an Energy Balance Model." *Open J. Astrophys.* 9. doi:10.33232/001c.165290. **[原文]**
- Haqq-Misra, J. (2026). "Limit cycles and the climate history of Mars." *Icarus* 449:116945. doi:10.1016/j.icarus.2026.116945. **[元数据]**

---

*调研执行：五个并行子代理（Mars/Titan/Venus/Moon/通用框架）+ 主线独立复核（勘误框 #1/#2/#4
经主线 WebSearch 二次确认）。原始下载件与批量检索脚本留痕在 `private/reviews/_research/`（tmp/、_scratch/、
_round*.py/.json 等）。本文档所有引文判据均出自上表「已核实」条目的摘要或开放全文原句；
未核实数值一律未采用。*
