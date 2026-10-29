# 亚格子岛屿目录

> **定位**：技术债 44（亚格子岛屿缺失）的设计提案。本文件只写物理依据、文献、当前方案与已否证方向；优先级在
> [roadmap.md](../roadmap.md)，实验记录进 git 与 CHANGELOG。
>
> **状态**：阶段 A–C 已实现（2026-10-22），D（环礁）与 E（画布盖印）未实施；作者裁决见 §8。依赖技术债 43 的格子平均语义（已实现）、0017 的热管与板块混合体制与
> 0014 的潮汐时间线。
>
> **约束**：nacrea 将在地形修复批次末尾整体重新生成，本提案不保留旧行为开关。

---

## 0 问题

1. **大多数岛屿小于一格。** 20 万格的格距约 54 km，绝大多数海岛与全部环礁都比格子小，格子平均高程仍是深海，
   地球与 nacrea 都显示不出来。生态层与文明层（远洋航海文化）需要知道哪里有岛、岛有多大。
2. **现有热点链与格子平均语义冲突。** `_generate_hotspots` 把半径 100 km、活动高度 8500 m 的余弦凸起直接叠在
   格子平均高程上；热点数（nacrea 9）、喷发间隔 180 km、链长 1200 km、每公里沉降 4 m 都是手设值。
3. **岛弧的位置不对。** 洋–洋岛弧抬升（`island_arc_height_m` 1500 m）的峰顶离边界约 70 km，地球上火山弧在板片
   深约 105 km 处，离海沟 150–300 km；抬升又是格子尺度的连续山脊，不是一串火山。
4. **永耀岛的存在由地理钉扎约束。** 它在 geography 中保留海岛地物，正典高程采用定版地质输出：
   岛心格平均高程约 1.55 km，亚格子峰顶约 1.8 km（§8 第 9 条）。

## 1 物理依据

### 1.1 岛屿是亚格子量

岛屿与海山的高度相对格距很小：夏威夷岛的火山体约 21 万 km³（含被挠曲压下的部分，Robinson & Eakins 2006），
摊到 54 km 格子上只相当于数百米到一两千米的格子平均抬升，而露出海面的面积多为几到几百 km²。所以岛屿用一个
目录（每个火山体的位置、年龄、体积、峰顶、出水面积与类型）表示，格子只记汇总量；格子平均高程只吸收火山体
体积的平均值。高清画布以后按目录盖印火山与环礁的剖面。

### 1.2 热点链

- **间距由挠曲决定，与板块速度无关。** 新火山口开在前一座火山挠曲应力为零处，介于挠曲沟与前缘隆起之间，
  间距 λ ∝ α = [4D/(Δρ·g)]^¼，D = E·Te³/(12(1 − ν²))，即 λ ∝ Te^¾·g^(−¼)（ten Brink 1991；Hieronymus &
  Bercovici 1999，同一模型给出夏威夷的 Loa、Kea 双列）。夏威夷沿每一列约 40–50 km（待核实）。
- **年龄随距离增加。** 年龄 = 到热点的距离 ÷ 板块速度（夏威夷—帝王链约 6000 km、8000 万年）。喷发间隔 = λ ÷
  板块速度；nacrea 板块速度约 12.5 cm/yr，Te 相近时间隔约 35 万年。
- **出水寿命。** 火山离开热点后先随穹隆衰减与自身载荷下沉，约 2.2–2.6 mm/yr；离开穹隆后按板块热沉降，每年
  百分之一到百分之五毫米（待核实）；高岛约 500–1500 万年被侵蚀并沉到海面附近（考艾岛约 500 万年仍高约 1.6 km），
  之后若礁体生长跟得上沉降就成为环礁，否则成为水下平顶海山。
- **数量。** 地球约 49 个热点，其中深源的「主热点」只有 7 个（Courtillot et al. 2003）。

### 1.3 火山体尺度

- 盾状火山的体积 = 岩浆通量 × 喷发间隔。夏威夷现今供给约 0.1–0.2 km³/yr（待核实），4750 万年至 500 万年前约
  0.017 km³/yr，此后约 0.05 km³/yr。
- 最大起伏约按 σ/(ρ·g) 随重力反比（奥林帕斯山约 22 km、g = 3.7 m/s²；地球最大火山体约 9 km 高出相邻海底）。
- 莫纳罗亚高出相邻海底约 9 km，基底半径约 100 km，水上侧翼约 3–12°，水下约 10–20°（待核实）。
- 挠曲沟宽约 π·α，深约载荷高度的 30–50%。

### 1.4 热管火山省

- **加热图样决定火山省的位置。** 偏心率很小时倾角潮主导潮汐加热（总功率 ∝ 21/2·e² + 3/2·sin²ψ，Beuthe 2013）。
  耗散发生在软流圈薄层（部分熔融层，热管熔体最自然的来源）时，加热按 Beuthe 的图样 B 分布，极大在向星点、背星点
  与南北两极，四处等强；推导见 `docs/knowledge/planetary_science/tidal_heating.md` §6。图样很宽，热流高时全球
  大部分地方都有热管岩浆。
- **地壳处于稳态，不形成相对高原。** 热管体制下地表持续被新岩层覆盖并向下平流（Moore & Webb 2013；Moore et al.
  2017），被掩埋的地壳在底部重熔或拆沉返回地幔，掩埋与返回相抵。木卫一每年重铺约 1 cm，却没有与加热极大对应的
  高原；它的高山是沉降应力造成的逆冲断块，不是火山体（Schenk et al. 2001）。所以热管岩浆的全球均匀部分属于基准面，
  火山省的地形表现是火山体，向星点与背星点的上涌抬升由已有的动力地形给出。
- **火山体是宽缓的盾。** 木卫一的盾状火山起伏小于 3 km，侧翼坡度只有 0.2–0.6°（Schenk et al. 2004）：热管熔岩
  黏度低、喷发率高，熔岩流铺得很远。木卫一约 1.0×10¹⁴ W 的内热（Veeder et al. 2012）经约 417 个火山口排出
  （Radebaugh et al. 2001），每口约 2.4×10¹¹ W。
- **火山省固定在潮汐参照系里**（0017 §5）：喷口相对向星方向固定，板块在上面移动，所以和热点一样，一座火山只在
  移过一个火山间距的时间里生长，之后被板块带走、被后来的熔岩流掩埋。
- **岩浆量**：热管每排 1 W/m² 合每百万年约 5.26 km 岩层（0017 §4，全球约 3100 km³/yr）。

### 1.5 岛弧

- 火山弧位于板片深约 105 km 处（Syracuse & Abers 2006，839 个火山中心，逐段 72–173 km，与板片下沉速率相关），
  弧沟距离约为该深度除以板片倾角的正切，一般 150–300 km。
- 弧上火山没有特征间距，火山成带，带长约为带宽的 10 倍（de Bremond d'Ars et al. 1995）；马里亚纳弧前缘的火山
  中心相距 35 ± 16 km（Baker et al. 2008）。

### 1.6 海山

卫星测高识别出约 13 000 座高于约 1.5 km 的海山，推算高于 1 km 的有约 10 万座（Wessel et al. 2010）；船测给出
±60° 纬度内高于 1 km 的约 3.9 万座，高度分布既不是纯指数也不是纯幂律（Hillier & Watts 2007）。出水的比例很小，
估计不到 1–2%（待核实）。

### 1.7 环礁

- 地球约 439 个环礁，其中约 268 个有陆地（Goldberg 2016），直径数 km 到数十 km。
- 礁体需要周最低海温约 18 °C 以上，年均 21.7–29.6 °C（Kleypas et al. 1999；Guan et al. 2015），分布到约
  30–32° 纬度。
- 达尔文点：礁体净生长低于沉降的纬度，地球约 29°N（库雷环礁，Grigg 1982）。
- 环礁依赖海温，所以在气候层之后判定。

## 2 竞品

- **GPlates**：由绝对参考系的板块运动预测热点迹（固定或移动热点），不生成单个火山体。
- **Azgaar Fantasy Map Generator**：用高度图模板（群岛、环礁模板）造岛，没有地质成因。
- **World Orogen、Gleba**：未找到岛屿放置方式的文档。
- **现行引擎**：随机热点种子加格子尺度凸起，见 §0。

## 3 方案

### 3.1 目录

地质层输出 `island_catalog.json`，每个火山体一条记录：编号、类型（热点、热管、岛弧、海山）、源编号、经纬度、
年龄（Myr）、体积（km³）、基底半径（km）、峰顶相对海面的高度（m）、出水面积（km²）、状态（活动、休眠火山岛、
侵蚀低岛、水下平顶海山；环礁由气候层之后追加）。格子新增汇总字段：岛数、出水面积占比、最高点。

### 3.2 源与火山口采样

1. **热管火山省**：当地热管热流 = max(q(t)·a·Ĥ − q_plate, 0)，Ĥ 为 §1.4 的加热图样（全球均值 1），q(t) 为
   潮汐热流时间线，q_plate 为板块按半空间冷却排出的热流，a 为该火山省在这一时期的活跃度。喷口按当地热管热流
   除以单口功率的密度做泊松采样，所以加热率高的地方火山密（作者 2026-10-21 要求从潮汐力场采样）。四个火山省
   （向星点、背星点、北极、南极）的活跃度每次潮汐期各自随机抽取（对数正态，带种子）；最近一次潮汐期的活跃度由
   作者给定，背星点偏弱（0.5），只建成次级岛屿。三阶潮汐约 1% 的不对称忽略。
2. **热点**：数量按地球面积比例给缺省（地球约 49 个，§8 第 3 条），位置在洋壳上带种子随机放置；火山间距按 §1.2 的
   挠曲尺度推出，双列交替。
3. **岛弧**：取洋–洋俯冲接触格（`orogen_contract.contact_polarity`），在上覆板块一侧、板片深约 105 km 处成带，
   带内火山按一维泊松过程放置，平均间距约 35–70 km。替代现行的岛弧抬升。
4. **海山**：洋壳上按地球统计的密度与高度分布放置背景海山，只记目录，不进格子平均。

### 3.3 时间积分

对每个源沿现今欧拉极回溯最近 2000 万年的板块运动（以后换成地质时间轴给出的运动史），按活动时间线放置
火山体：热点持续活动；热管火山省的岩浆量随潮汐热流变化，潮汐时间线在最近 200 万年用 0014 的正典轨迹（世界输入
`tidal_heat_history.yaml`，每 1 万年一个 2 万年滑动平均值），更早用按 0014 集合统计标定的带种子随机序列，静息段
与潮汐期交替。时间线按「静息段、潮汐期」分段，每段内每个喷口建一座火山。不放进板块正向演化：现状管线不搬运地壳，正向演化的混沌也会让岛屿随种子大幅漂移。

### 3.4 形态演化

火山体体积 = 岩浆通量 × 喷发间隔；高度由体积与侧翼坡度给出，不超过随 1/g 缩放的上限，减去挠曲沟。之后按穹隆
衰减、板块热沉降与侵蚀降低，峰顶沉到海面附近时交给环礁判定。热管火山的体积 = 单口岩浆量 × 生长时间（火山间距
÷ 板块速度，不超过所在时段）× 建体份额 0.2 × 0.5（挠曲山根）；其余岩浆铺成熔岩流，掩埋更早时段的火山。每块
地壳保留现存最高的一座。热管盾比挠曲波长宽，生长时已均衡补偿，不再加建成后的沉降。

### 3.5 与格子地形的耦合

- 格子平均高程吸收火山体体积的格内平均；热管火山省不加高原（§1.4），向星点与背星点的上涌抬升由动力地形给出。
  出水部分比格子还宽的火山由网格分辨，不计入亚格子岛屿汇总。
- 删除 `_generate_hotspots` 的格子尺度凸起与 `hotspot_*` 配置、洋–洋岛弧抬升与 `island_arc_height_m`。
- 永耀岛的存在由 geography 中的钉扎地物约束，正典高程采用定版输出（§8 第 9 条）。

### 3.6 大陆弱化场

热管火山省附近的大陆岩石圈局部变热变弱（0017），作为碰撞型平均高程上限的强度系数接入（技术债 43）。nacrea
的碰撞段离火山省中心都在 4700 km 以上，当前不起作用。

### 3.7 下游

生态层与文明层读取格子汇总字段与目录；环礁在气候层之后判定并追加到目录；高清画布在 TD 生成之后按目录盖印
火山锥与环礁的剖面（画布链，另行实施）。

## 4 参数与认识论类别

| 参数 | 取值 | 类别 | 标定域与不确定度 |
|---|---|---|---|
| 火山间距 λ | c·α(Te, g)，c 由夏威夷约 45 km 标定 | 近似推导加观测标定 | 夏威夷间距待核实 |
| 热点岩浆通量 | 约 0.05–0.2 km³/yr | 观测拟合 | 夏威夷，待核实 |
| 火山高度上限 | 约 9 km × 9.81/g | 近似推导 | 一阶论证 |
| 弧下板片深度 | 105 km | 观测拟合 | 72–173 km |
| 弧上火山平均间距 | 35–70 km，无特征间距 | 观测拟合 | 马里亚纳 35 ± 16 km |
| 海山密度 | 高于 1 km 的约 3.9–10 万座每地球大洋 | 观测拟合 | 两套统计相差约 2.5 倍 |
| 环礁海温条件 | 周最低 ≥ 18 °C，年均 21.7–29.6 °C | 观测拟合 | 达尔文点约 29°N |
| 热管火山省活跃度 | 每次潮汐期随机抽取，σ_ln 0.5 | 随机闭合（无标定） | 最近一期由作者给定 |
| 加热图样 | Ĥ = 2.5(x² + y²) − 10x²y² | 近似推导 | 倾角潮、软流圈薄层；三阶潮汐忽略 |
| 每 W/m² 的岩浆量 | 5.26 km/Myr | 近似推导 | ρ 3000 kg/m³，每千克 2 MJ（0017） |
| 热管单口功率 | 2.4×10¹¹ W | 观测拟合 | 木卫一 1.0×10¹⁴ W ÷ 417 个火山口 |
| 热管盾侧翼坡度 | 0.4° | 观测拟合 | 木卫一 0.2–0.6° |
| 热管建体份额 | 0.2 | 观测拟合（借用） | 地球侵入与喷出约 5 : 1，未对热管标定，高度不确定约两倍 |

## 5 验证

- **科学验收（地球）**：在地球分支上用真实板块运动与热点位置驱动目录，检验夏威夷链的间距与年龄、各大洋高于
  1 km 的海山与出水岛数量、岛弧位置与弧沟距离（对照 Syracuse & Abers 2006）、环礁的纬度分布（对照 Goldberg 2016）。
- **创作验收（nacrea）**：永耀岛是显著的高岛，向星点岛链符合 0017 的正典；背星点为次级岛屿；远洋航海所需的岛屿
  间距（文明层）。

## 6 分阶段实施

每阶段只新增一个闭合假设，并在地球上检验。

1. **A 目录与汇总字段**：数据模型、热点链（挠曲间距）、海山；删除格子尺度的热点凸起。已实现
   （`map/island_catalog.py`）：nacrea 约 43 条洋壳热点链、1337 座热点火山，出水岛约 630 个（热点约 250、
   海山约 380），出水面积约 12 万 km²。实现中补的两条闭合：火山体只有约一半高出原海底，另一半在挠曲山根里
   （Robinson & Eakins 2006）；老火山相对周围海底下沉 S(t) = 2 km × (1 − e^(−t/0.8 My))（夏威夷沉没礁体的初始
   速率约 2.5 mm/yr）。相邻锥体重叠处，格子抬升不超过覆盖它的最高火山。
2. **B 岛弧**：板片深度定位与一维泊松火山带，替代岛弧抬升。已实现（`island_catalog.arc_platform` 与目录的
   `arc` 火山）：弧轴离海沟 240 km（Perrin et al. 2018 的弧沟距离均值），岩浆供给每公里弧长 40 km³/Myr，五分之四
   侵入加厚弧地壳成格子尺度的平台（伊豆—小笠原—马里亚纳弧剖面给出两侧各 125 km 的加厚带），五分之一喷出建
   400 km³ 的弧火山。nacrea 约 1000 座弧火山，出水约 185 座、约 5.8 万 km²。
3. **C 热管火山省**：已实现（`map/heat_pipe.py` 与目录的 `heatpipe` 火山）：倾角潮软流圈加热图样、潮汐热流时间线、
   按热流定密度的喷口与宽缓盾状火山，地壳取稳态不加高原。nacrea 导出约 350 座热管火山（峰顶在海面下 2 km 以内），
   出水岛约 110 个、陆上火山约 80 座。永耀岛的存在保留地理钉扎约束，高程取定版输出。
4. **D 环礁**：气候层之后按海温与沉降判定。
5. **E 画布盖印**：画布链实施，另行排期。

## 7 已否证方向

- **把火山体直接叠在格子平均高程上**（现行实现）：8500 m 的格子尺度凸起与格子平均语义矛盾。
- **把岛屿放进板块正向演化**：现状管线不搬运地壳，正向演化的混沌让岛屿随种子大幅漂移（0017 §6）。
- **热管火山省按热点链规则放置高耸盾状火山**：热管体制的火山体低矮宽缓（§1.4）。
- **热管岩浆加厚地壳到拆沉上限再按 Airy 抬成高原**：图样很宽而热管重铺约 3.5 mm/yr，2000 万年内约一半洋壳加厚到
  上限、整体抬高约 4 km，浅深格局变成老洋壳高、年轻洋壳与加热极小区低，与稳态重铺的木卫一不符。
- **热管喷口取挠曲间距或固定的木卫一喷口密度**：前者约 17 万座火山，后者在加热弱的地方也一样密；喷口密度应随
  当地热管热流变化。
- **热管火山取 5° 锥体**：出水面积达数百万 km²，与木卫一 0.2–0.6° 的盾不符。

## 8 作者裁决（2026-10-21）

1. 热管火山省以加厚高原为主（物理优先）：大部分在水下，岛屿只在高原顶面接近海面处零星出现，主火山是例外。
2. 永耀岛的高度以目录推出值为准，删除 1700 m 的钉扎；创作验收要求它是显著的高岛（作者：不太低就行），推出值明显
   偏低时先复核火山省的岩浆通量与沉降参数这类允许的输入，不改物理。
3. 普通热点按地球面积比例给缺省数量（地球约 49 个；甲）。
4. 回溯时长取 2000 万年。
5. 岛弧与海山与热管火山省、热点一起进入本批。
6. 背星点火山省在最近一次潮汐期偏弱，只形成次级岛屿；火山口位置由潮汐加热场采样。

2026-10-22 补充：

7. 耗散层取软流圈薄层，接受四个火山省（甲）：北极大陆上的热管制造「极地火山小生境」，南极制造「极地洋底火山省
   特殊生态」。
8. 热管地壳取稳态（乙），火山省以火山群为主，取代第 1 条的「以加厚高原为主」。
9. 永耀岛在 Aegis 深渊洋中央的存在保留地理钉扎约束；正典采用定版地质输出，岛心格平均高程约 1.55 km，
   亚格子峰顶约 1.8 km（作者 2026-10-29）。目录热管盾的起伏约 1 km。

## 参考文献

- Baker, E. T., et al. (2008). Hydrothermal activity and volcano distribution along the Mariana arc. *Journal of
  Geophysical Research*, 113, B08S09.
- Beuthe, M. (2013). Spatial patterns of tidal heating. *Icarus*, 223, 308–329.
- Courtillot, V., Davaille, A., Besse, J., & Stock, J. (2003). Three distinct types of hotspots in the Earth's
  mantle. *Earth and Planetary Science Letters*, 205, 295–308.
- de Bremond d'Ars, J., Jaupart, C., & Sparks, R. S. J. (1995). Distribution of volcanoes in active margins.
  *Journal of Geophysical Research*, 100, 20421–20432.
- Goldberg, W. M. (2016). Atolls of the world: revisiting the original checklist. *Atoll Research Bulletin*, 610.
- Grigg, R. W. (1982). Darwin Point: a threshold for atoll formation. *Coral Reefs*, 1, 29–34.
- Guan, Y., Hohn, S., & Merico, A. (2015). Suitable environmental ranges for potential coral reef habitats in the
  tropical ocean. *PLoS ONE*, 10, e0128831.
- Hieronymus, C. F., & Bercovici, D. (1999). Discrete alternating hotspot islands formed by interaction of magma
  transport and lithospheric flexure. *Nature*, 397, 604–607.
- Hillier, J. K., & Watts, A. B. (2007). Global distribution of seamounts from ship-track bathymetry data.
  *Geophysical Research Letters*, 34, L13304.
- Kleypas, J. A., McManus, J. W., & Meñez, L. A. B. (1999). Environmental limits to coral reef development: where do
  we draw the line? *American Zoologist*, 39, 146–159.
- Moore, W. B., & Webb, A. A. G. (2013). Heat-pipe Earth. *Nature*, 501, 501–505.
- Moore, W. B., Simon, J. I., & Webb, A. A. G. (2017). Heat-pipe planets. *Earth and Planetary Science Letters*, 474,
  13–19.
- Kodaira, S., et al. (2007). Seismological evidence for variable growth of crust along the Izu intraoceanic arc.
  *Journal of Geophysical Research*, 112, B05104.
- Perrin, A., Goes, S., Prytulak, J., Rondenay, S., & Davies, D. R. (2018). Mantle wedge temperatures and their
  potential relation to volcanic arc location. *Earth and Planetary Science Letters*, 501, 67–77.
- Dimalanta, C., Taira, A., Yumul, G. P., Tokuyama, H., & Mochizuki, K. (2002). New rates of western Pacific island
  arc magmatism from seismic and gravity data. *Earth and Planetary Science Letters*, 202, 105–115.
- Radebaugh, J., Keszthelyi, L. P., McEwen, A. S., Turtle, E. P., Jaeger, W., & Milazzo, M. (2001). Paterae on
  Io: a new type of volcanic caldera? *Journal of Geophysical Research*, 106, 33005–33020.
- Peale, S. J., & Cassen, P. (1978). Contribution of tidal dissipation to lunar thermal history. *Icarus*, 36,
  245–269.
- Robinson, J. E., & Eakins, B. W. (2006). Calculated volumes of individual shield volcanoes at the young end of the
  Hawaiian Ridge. *Journal of Volcanology and Geothermal Research*, 151, 309–317.
- Schenk, P. M., Wilson, R. R., & Davies, A. G. (2004). Shield volcano topography and the rheology of lava flows on
  Io. *Icarus*, 169, 98–110.
- Schenk, P., Hargitai, H., Wilson, R., McEwen, A., & Thomas, P. (2001). The mountains of Io. *Journal of Geophysical
  Research*, 106, 33201–33222.
- Reymer, A., & Schubert, G. (1984). Phanerozoic addition rates to the continental crust and crustal growth.
  *Tectonics*, 3, 63–77.
- Takahashi, N., et al. (2007). Crustal structure and evolution of the Mariana intra-oceanic island arc. *Geology*,
  35, 203–206.
- White, S. M., Crisp, J. A., & Spera, F. J. (2006). Long-term volumetric eruption rates and magma budgets.
  *Geochemistry, Geophysics, Geosystems*, 7, Q03010.
- Syracuse, E. M., & Abers, G. A. (2006). Global compilation of variations in slab depth beneath arc volcanoes and
  implications. *Geochemistry, Geophysics, Geosystems*, 7, Q05017.
- Veeder, G. J., Davies, A. G., Matson, D. L., Johnson, T. V., Williams, D. A., & Radebaugh, J. (2012). Io: Volcanic
  thermal sources and global heat flow. *Icarus*, 219, 701–722.
- ten Brink, U. (1991). Volcano spacing and plate rigidity. *Geology*, 19, 397–400.
- Wessel, P., Sandwell, D. T., & Kim, S.-S. (2010). The global seamount census. *Oceanography*, 23(1), 24–33.
