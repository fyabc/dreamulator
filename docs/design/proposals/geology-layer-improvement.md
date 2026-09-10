# 地质层改进方案

> **定位**：地质引擎改进的设计提案——物理第一性 + 文献 + 当前实现 + 未实现 proposal + 已否证方向。
> 职责分工见根 CLAUDE.md「任务文档分工」：执行顺序 → today；优先级/技术债 → roadmap；
> 实验记录/历史 → git。**本文件不写「旧值 → 新值」叙事、不写「已修复/遗留问题」历史。**
>
> **状态**：§1–§8 全部 ✅ 已实现（技术参数/流程见 [pipelines/geological-pipeline.md](../pipelines/geological-pipeline.md)）；
> 未实现 proposal 汇总见 §7。⚠️ 注：部分「已实现」的设计依据当前以本文件为事实源（pipelines 尚未
> 迁入，见 §8 待办）。
> 2026-09-01 整合（吸收 plate-motion-coherence + geography-tectonics-reconciliation 两份提案）；
> 2026-09-11 清理（剥离旧值→新值/已修复叙事，历史在 git）。
>
> 原则：每个决策有**物理第一性**、**地球真实参考**或**业界成熟方案**三者之一支撑；同物理
> （所有世界同一套引擎）；第一性 > 启发式。

---

## 0 总览

| 主题 | 状态 | 依赖 |
|---|---|---|
| §1 板块运动相干化（+ 对流谐波） | ✅ 已实现 | — |
| §2 裂谷与离散边界（半地堑断块） | ✅ 已实现（A/B/C/D） | — |
| §3 板块边界几何（犬牙 → 物理） | ✅ 已实现（宽度分级/临界楔/渗漏转换/断陷盆地/海岸过渡/热点链/边界整形/分段脊/分类修正） | — |
| §4 geography 锚定地貌真实化 | 部分（噪声粗糙化 ✅、造山带/裂谷形态 ✅；裂谷海宽度沿走向变化仍提案） | §5 |
| §5 geography ↔ 板块运动协调 | ✅ 已实现（裂谷速率/半包围/边界对齐海岸） | §3 |
| §8 地壳类型正交化 | ✅ 已实现 | — |
| §7 网格精度无关性（横切） | ✅ 已实现 | — |

---

## 1 板块运动相干化（✅ 已实现）

**问题**：Cortial 2019 随机欧拉极 → 板块运动方向彼此独立 → 相对速度方向在边界切平面近似
随机均匀 → 转换边界占比过高（地球 28.5%）。

**物理依据**：
- 潮汐加热空间格局（[Beuthe 2013](https://archive.org/details/arxiv-1212.4630)）：同步自转卫星、
  液态核外岩石地幔 → 耗散在潮汐轴两端最高 → **degree-2 order-0 格局**（向星/背星点上涌，
  90° 环带下沉）。
- 板块运动非随机（[Lithgow-Bertelloni & Richards 1993](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/93GL00168)）：
  极向/环向分解，toroidal/poloidal 比值 0.2–0.6。

**实现**：degree-2 极向场 `v(P) = A·c·(c·P − â)`（c = P·â，â = 潮汐轴）+ 最小二乘反演
每个板块的刚体欧拉极 `min‖ω_k×P_i − v_target(P_i)‖²`。净旋转（degree-1 toroidal）因规范
抵消（全局刚体旋转被板块精确吸收、相对速度不变）未实现。

**对流谐波**：纯极向场是梯度（无旋），刚体拟合被强制 ⊥ 潮汐轴 → 所有板块 ω 同向 → 相对运动
纯剪切 → 转换主导（**已否证方向**：纯极向场不够）。叠加 `convection_harmonics` 个 degree-2
**环向**对流胞（`c·(âₖ×P)` 差速旋转，随机轴向、幅度 `convection_harmonic_amp`~0.3），代表内部
加热的多胞对流涡量，使拟合欧拉极发散。

**当前**：转换占比 3%（潮汐锁定世界斜向快速运动、几乎无纯转换，是诚实结果而非分类错误）；
离散/汇聚/转换 36/30/34（地球式三等分）；tortuosity p99 30。

---

## 2 裂谷与离散边界（半地堑断块，✅ 已实现）

### 物理：半地堑分段是主导形态

真实大陆裂谷（东非、贝加尔、Basin and Range）的主体是**半地堑（half-graben）**，不是对称
地堑（[Scholz et al. 1998](https://www.science.gov/topicpages/l/lake+tanganyika+africa)；Friedmann &
Burbank 1995）：

- 盆地由**单一陡倾边界断层**（45–60°）界定 → **一侧抬升（footwall 裂谷肩）、一侧下沉
  （hanging-wall 盆地）**，不对称是本质。
- 裂谷沿走向**分段**成 ~70×130 km 的「倾角域」（dip domain），相邻段**倾角极性交替**，
  由调节带/转换带/relay ramp 连接。

这统一了「断块地垒」与「不对称」两件事：**它们都是半地堑结构的体现**——交替极性的半地堑
= 断块；单侧 footwall 抬升 = 不对称。

### 实现（A/B/C/D）

- **A — 加深裂谷海 + 速率门控**：裂谷深度 0.8×，`uplift_mod` 只调肩不调谷；加**扩张速率门控**
  ——快裂谷（`rate ≥ continental_rift_sea_rate_cm_yr`=6 cm/yr，红海型）降成海、慢裂谷（东非型）
  浅地堑留在海面以上。
- **B — 半地堑不对称**：有符号距离 `ds = d·side·polarity`——`side`（`_divergent_side_sign`）由
  plate 归属的 canonical 顺序定 cell 在边界哪侧；`polarity` = ~400 km fBm 阈值 ±1，相邻段极性
  交替。裂谷肩只在 `ds > 0`（footwall）一侧，另一侧是 hanging-wall 盆地。
- **C — 断块**：裂谷带内叠加走向对齐的高频断块噪声（复用 `_anisotropic_fbm`，高频 + strike
  各向异性，fault_amp 600 m，只限 `d < σ_div`），产出沿走向拉长的地垒/地堑块。
- **D — 洋脊按扩张速率**：三层区分——快(>9 cm/yr)=单一轴部隆起 / 慢(<5)=中央谷+裂谷山 / 中=过渡。

---

## 3 板块边界几何（犬牙 → 物理，✅ 已实现）

### 物理边界形态（[Frisch et al. 2011](https://link.springer.com/book/10.1007/978-3-540-76504-2)）

| 类型 | 真实形态 | 实现 |
|---|---|---|
| 汇聚 | **小圆弧**（[Frank 1968](https://www.nature.com/articles/220363a0) 岛弧曲率） | `trench_arc`（sagitta 收窄） |
| 离散 | **分段脊 + 转换断层直角错列**（en-echelon） | `_shape_boundary_segments`（分段脊） |
| 转换 | **直线**（绕欧拉极的小圆） | `transform_straighten` |

**边界宽度**（Frisch 2011）：汇聚 ≫ 离散 > 转换（~10:3:1）——按类型独立带宽
（`convergent_width_km` / `divergent_width_km` / `transform_width_km`），不再共享单一 σ。

### 已实现子项

- **临界楔宽度时间累积**（Davis, Suppe & Dahlen 1983）：山带宽度随累积缩短量 S 增长
  `orogen_width = min(w_max, w_0 + k_type × S)`，`k` = 碰撞 0.4 / 俯冲 0.1–0.2（青藏/安第斯）。
- **渗漏转换（leaky transform）**：转换断层斜交时叠加拉分盆地沉降（`tangential_fraction` 细分，
  `v_t/v_total < 0.9` 且伸展时，幅度 ∝ 斜向度；死海 −430 m 量级）。
- **断陷盆地**：超临界楔的伸展塌陷（Davis 1983），出现在宽成熟造山带；`fault_amp` 提到可见
  地垒-地堑。
- **海岸高程过渡**：排除 coastline cell 的图拉普拉斯平滑（保持海岸过渡值）；海岸 cell 目标
  `mountain_coast_ratio = 0.15`（海岸山脉量级）；钉扎过抬只放大下压方向（海沟保持海底）。
- **热点链群岛化**（Wilson 1963）：火山沿欧拉极小圆按真实测地 km 追踪、`hotspot_eruption_interval_km`
  离散放置，链尾随 `hotspot_subsidence_m_per_km` 沉成海山；跨板块边界即止。
- **边界整形统一**（`_shape_boundary_segments`）：弯折处切段 → 汇聚弓成小圆弧（抛物线
  sagitta=0.15）→ 离散/转换拉直；分段脊按 `ridge_segment_length_km` 切段、随机游走错列。
- **边界分类修正**：类型由**法向分量 v_n 的符号**决定（Stein & Wysession：motion parallel=transform、
  away=divergent、toward=convergent），切向分量是独立量（`tangential_fraction`，供渗漏转换），
  不覆盖基本类型；沿走向按局部 v_n 子分段（质心分类太粗）。

### 未实现

- **裂谷海宽度沿走向分段**（§3.5 transitional 带）：当前用量化高频 fBm 近似（汇聚带），离散带
  已回退——裂谷海宽度由「大陆地壳被 rift 压到海面以下」的**深度**决定（见 §8），后续应调深度
  而非宽度。

---

## 4 geography 锚定地貌真实化（部分已实现）

**分析**：锚定地貌不应是「椭圆色块」，而应是一块**被地形设施塑造的地壳**——大陆边缘有造山带
（汇聚）、裂谷（离散）、内部低地、岛弧。地形设施的**位置**依赖板块边界（§5，已落地）；但**形状**
（粗糙化、散碎、分段）独立于 §5。

**已实现**：锚定地貌噪声粗糙化（`_feature_kernel` 注入 fBm，打破椭圆规整）；古造山带形态（长度
封顶 `belt_length_deg = 2.0 + 8.0·rand²` + 角度过滤，从「长条」变「散碎短段」）；裂谷形态（同，
避免贯穿板块的单条长裂谷）。

**未实现**：裂谷海宽度沿走向变化（transitional 带宽度分段）。

---

## 5 geography ↔ 板块运动协调（核心架构，✅ 已实现）

### 矛盾本质

`geography.yaml` 锚定「大陆 A 在 (lon,lat)」= 静态目标地貌；Cortial 2019 板块独立生成 → 板块边界
落在任意位置 → 造山带/裂谷出现在错误位置。真实世界大陆就是板块（大陆地壳坐大陆板块上），
大陆-海洋边界就是（或曾是）板块边界。

### 业界两条路线

| 引擎 | 路线 | 机制 |
|---|---|---|
| [**Gleba**](https://indiegoblin.com/games/gleba-v012)（科学） | co-specify + 正向模拟 | 同时导入 crustmap + platemap，要求地壳边界与板块边界对齐 → 正向板块模拟 |
| [**Azgaar FMG**](https://azgaar.github.io/Fantasy-Map-Generator/)（艺术） | 纯高度图，无板块模拟 | 高度图模板 + 笔刷，手动赋予构造意义 |

**已否证方向**：反向演化（从目标地貌反推板块历史）——时间演化含不可逆过程（俯冲消亡/裂解/侵蚀）、
同一地貌有无穷多历史，反演无良定义。

### 修复方向（已实现方案 2）

1. **板块从 geography 派生**（Gleba 式，最彻底）——改动大（重写板块剖分 + geography 接口）。**未实现**。
2. **板块边界对齐大陆边缘**（折中）——保留 Voronoi 板块，重跑分区时给「大陆边缘」加权，把边界
   「吸」到海岸附近。**已实现**。
3. **锚定 + 松弛**（最小）——太弱，弃。

### 已实现子项

- **大陆裂谷速率门控**：按板块大陆 cell 占比线性减速（`continental_plate_speed_factor`=0.3，
  非洲/太平洋速率比）——大陆岩石圈更厚（~150 km 克拉通根 vs 洋壳 ~7 km）更难裂。
- **板块形状不规则（半包围/洞板块）**：递归平面切割（small-circle 裂谷裂缝）保证碎片凸 +
  `_merge_enclosed_plates`（单邻居包裹 >240° 且面积 <2% 吸入）消除「洞」板块。
- **板块边界对齐大陆边缘**：海岸代价场 `coast_cost = 1 + w·max(0, 1 − d/band)`（`w =
  geography_boundary_weight`=4.0）钉边界到海岸；地理对齐种子（每个 ≥0.5% 面积连通域放种子）；
  贯穿演化（初始剖分 + 重采样 + 最终 warp 用同一固定海岸代价场）；纯程序化世界零改动。
  **目标界定**：承诺「吸到海岸**附近**」而非精确重合（Voronoi 凸胞不能贴合非凸海岸线）。

---

## 6 地壳类型正交化（✅ 已实现）

**决策**：程序化管线里取消 `transitional` 地壳，`crust_type` 只留 continental/oceanic 二分；
「海陆/浅深」改由 `water_class`（+ `elevation` 水深）表达。地质上的「过渡地壳」由地壳厚度/成分
定义（15–25 km），**不是高程**——原「±50m 近海平面 → transitional」实为「大陆架/浅海」，与地质
概念混淆。

**当前**：`transitional` 退化为仅真实地球 CRUST1.0 导入（`crust1.py`）的合法值；大陆地壳 41.5%
（对齐地球 ~40% 含陆架，陆壳边界 = 海岸线 + 大陆架）；「land 但 oceanic」仅剩火山岛/岛弧
（本就该是洋壳）。

---

## 7 网格精度无关性（横切，✅ 已实现）

**原则**：所有「宽度/距离/带宽」参数与计算**必须以真实长度（km，球面测地距离）为单位**，
不得用「cell 数量 / hop 次数」作距离。切换网格精度（`num_nodes`）后，物理形态应近似不变，
仅采样分辨率改变。

**实现**：`distance.geodesic_bfs`（逐边 `arccos(x·y)·R` 累加）作为唯一参考实现，替换
terrain/boundary 里多处 `cell_km = √(4πR²/n)` 平均间距近似；修 `_compute_boundary_strike`
硬编码 6371 → `config.radius_km`、`_compute_ocean_age_depth` 的 `4R/√n` → `√(4πR²/n)` 等。
构造演化中间步骤（性能敏感）保留「平均间距」hop 步长。

---

## 8 未实现 proposal 汇总 + 待办

**未实现 proposal**：
- 裂谷海宽度沿走向分段（§3.5 transitional 带）。
- 方案 1：板块从 geography 派生（最彻底，重写板块剖分 + geography 接口）。

**待办**：本文件是部分「已实现」设计依据的事实源（§1–§8 的实现 detail 尚未迁入
`pipelines/geological-pipeline.md`），后续应迁入 pipelines、本文件只留「为什么」+ 未实现 proposal。

---

## 参考资料

- Beuthe, M. (2013). *Spatial patterns of tidal heating*. Icarus 223(1). [arXiv:1212.4630](https://archive.org/details/arxiv-1212.4630)
- Lithgow-Bertelloni et al. (1993). *Toroidal-poloidal partitioning of plate motions since 120 Ma*. GRL 20(5). [doi:10.1029/93GL00168](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/93GL00168)
- Scholz, C. A. et al. (1998). *Comparative sequence stratigraphy of … East African and Baikal rifts*. — 半地堑分段、倾角域交替。
- Frank, F. (1968). *Curvature of Island Arcs*. Nature. — 岛弧小圆弧。
- Frisch, Meschede & Blakey (2011). *Plate Tectonics*. Springer. — 边界形态。
- Davis, Suppe & Dahlen (1983). *Mechanics of fold-and-thrust belts and accretionary wedges*. — 临界楔。
- Wilson, J. T. (1963). *A possible origin of the Hawaiian Islands*. — 热点链。
- Cortial et al. (2019). *Procedural Tectonic Planets*. CGF 38(2). [doi:10.1111/cgf.13614](https://onlinelibrary.wiley.com/doi/10.1111/cgf.13614)
- [Gleba — Calandiel 幻想世界模拟器](https://indiegoblin.com/games/gleba-v012) + [crustmap/platemap 导入说明](https://itch.io/t/6057077/how-to-get-started-with-crustmap-and-platemap-imports)
- [Azgaar's Fantasy Map Generator](https://azgaar.github.io/Fantasy-Map-Generator/) — 高度图模板，无板块模拟。
- 源码：`map/plate_generator.py`、`map/geography.py`、`map/terrain_synthesizer.py`、`map/boundary_detector.py`。
