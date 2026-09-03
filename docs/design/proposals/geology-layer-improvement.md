# 地质层改进方案

> **状态**：综合方案——§1 ✅、§2 ✅、§3（sagitta 收窄/宽度/断陷盆地/渗漏转换/热点链群岛化/海岸过渡/边界整形统一 ✅、
> 分段脊 ✅、分类修正+噪声调参 ✅）、§5.5 大陆裂谷速率 ✅、§5.6 半包围 ✅、§5.7 边界对齐海岸（方案 2）✅、§7 网格精度无关性 ✅、§8 ✅。
> §4 部分（噪声粗糙化 ✅、造山带/裂谷形态 ✅、裂谷海宽度沿走向变化仍提案）。
> **实现参考**：已实现各节的技术参数/流程见 [pipelines/geological-pipeline.md](../pipelines/geological-pipeline.md)；
> 本文件保留设计依据（物理第一性 + 调研）与遗留 roadmap（裂谷海宽度分段、板块时间演化、速度瓶颈）。
> 2026-09-01 整合（吸收 plate-motion-coherence + geography-tectonics-reconciliation 两份提案，并补调研）。
>
> 原则：每个决策有**物理第一性**、**地球真实参考**或**业界成熟方案**三者之一支撑；同物理
> （所有世界同一套引擎）；第一性 > 启发式。

---

## 0 总览

地质层的改进按物理依赖排序：

| # | 主题 | 状态 | 依赖 |
|---|---|---|---|
| §1 | 板块运动相干化 | ✅ 已实现 | — |
| §2 | 裂谷与离散边界（半地堑断块） | ✅ 已实现（A/B/C/D） | — |
| §3 | 板块边界几何（犬牙 → 物理） | 部分（sagitta 收窄 ✅、§3.6 宽度 ✅、§3.7 渗漏转换 ✅、§3.8 断陷盆地/地垒 ✅、§3.9 海岸过渡 ✅、§3.10 热点链群岛化 ✅、§3.11 边界整形统一 ✅、分段脊 ✅、§3.12 分类修正+噪声调参 ✅） | — |
| §4 | geography 锚定地貌真实化 | 部分（噪声粗糙化 ✅、造山带/裂谷形态 ✅） | §5 |
| §5 | geography ↔ 板块运动协调 | ✅ 已实现（§5.5 大陆裂谷速率 ✅、§5.6 半包围 ✅、§5.7 边界对齐海岸 ✅） | §3 |

---

## 1 板块运动相干化（✅ 已实现）

**问题**：Cortial 2019 随机欧拉极 → 板块运动方向彼此独立 → 相对速度方向在边界切平面近似
随机均匀 → 转换边界占比 69.6%（地球 28.5%）。

**物理依据**：
- 潮汐加热空间格局（[Beuthe 2013](https://archive.org/details/arxiv-1212.4630)）：同步自转卫星、
  液态核外岩石地幔 → 耗散在潮汐轴两端最高 → **degree-2 order-0 格局**（向星/背星点上涌，
  90° 环带下沉）。
- 板块运动非随机（[Lithgow-Bertelloni & Richards 1993](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/93GL00168)）：
  极向/环向分解，toroidal/poloidal 比值 0.2–0.6。

**实现**：degree-2 极向场 `v(P) = A·c·(c·P − â)`（c = P·â，â = 潮汐轴）+ 最小二乘反演
每个板块的刚体欧拉极 `min‖ω_k×P_i − v_target(P_i)‖²`。净旋转（degree-1 toroidal）因规范
抵消（全局刚体旋转被板块精确吸收、相对速度不变）未实现。

**对流谐波（方向 3，✅ 已实现）**：纯极向场是梯度（无旋），刚体拟合被强制 ⊥ 潮汐轴 → 所有
板块 ω 同向 → 相对运动纯剪切 → 转换主导。叠加 `convection_harmonics` 个 degree-2 **环向**对流胞
（`c·(âₖ×P)` 差速旋转，随机轴向、幅度 `convection_harmonic_amp`~0.3），代表内部加热的多胞对流
涡量，使拟合欧拉极发散（angle-to-tidal-axis spread 8.7°→66°）。

**结果**：transform 69.6%→33.7%（相干化）；环向谐波后欧拉极发散，配合 §3.12 的 v_n-only 分类，
transform 3%（见 §3.12）。离散/汇聚/转换 36/30/34（地球式三等分），tortuosity p99 102→30。

---

## 2 裂谷与离散边界（半地堑断块，✅ 已实现）

### 2.1 物理：半地堑分段是主导形态

真实大陆裂谷（东非、贝加尔、Basin and Range）的主体是**半地堑（half-graben）**，不是对称
地堑（[Scholz et al. 1998](https://www.science.gov/topicpages/l/lake+tanganyika+africa)；Friedmann &
Burbank 1995）：

- 盆地由**单一陡倾边界断层**（45–60°）界定 → **一侧抬升（footwall 裂谷肩）、一侧下沉
  （hanging-wall 盆地）**，不对称是本质。
- 裂谷沿走向**分段**成 ~70×130 km 的「倾角域」（dip domain），相邻段**倾角极性交替**，
  由调节带/转换带/relay ramp 连接。
- footwall 抬升 >1500 m（裂谷肩），盆地可深 6–10 km（贝加尔 1640 m、坦噶尼喀 1471 m）。

这统一了「断块地垒」与「不对称」两件事：**它们都是半地堑结构的体现**——交替极性的半地堑
= 断块；单侧 footwall 抬升 = 不对称。

### 2.2 现状缺陷

`terrain_synthesizer._asymmetric_boundary_effects` 离散分支：
- 大陆裂谷 = 对称高斯中央谷 + 两道对称高斯肩（`|d|` 的函数，天然对称），无断块、无半地堑
  极性交替。
- 裂谷海已成形但浅（−26 m）；`uplift_mod`（岛弧起伏噪声）把整条裂谷振幅砍半。
- 洋脊形态与扩张速率脱钩（慢扩张的「中央谷+裂谷山」画在了快扩张的 Nacrea 上）。

### 2.3 方案

- **A — 加深裂谷海 + 速率门控**（已实现）：裂谷深度 0.6→0.8×，`uplift_mod` 只调肩不调谷；
  并加**扩张速率门控**——快裂谷（`rate ≥ continental_rift_sea_rate_cm_yr`=6 cm/yr，红海型）
  降成海、慢裂谷（东非型）浅地堑留在海面以上。否则 §2A 加深后慢裂谷也被拖下海面 →
  「大陆处处是蜿蜒裂谷海」。
- **B — 半地堑不对称**（已实现）：有符号距离 `ds = d·side·polarity`——`side`（`_divergent_side_sign`）
  由 plate 归属的 canonical 顺序（`pa < pb`，与 boundary_detector 一致）定 cell 在边界哪侧；
  `polarity` = ~400 km fBm 阈值 ±1，相邻段极性交替。裂谷肩只在 `ds > 0`（footwall）一侧，
  另一侧是 hanging-wall 盆地，取代原来的两道对称肩。
- **C — 断块**（已实现）：裂谷带内叠加走向对齐的高频断块噪声（复用 `_anisotropic_fbm`，
  `noise_scale×4` 高频 + strike 各向异性，fault_amp 600 m，只限 `d < σ_div`），产出沿走向拉长的
  地垒/地堑块。
- **D — 洋脊按扩张速率**：已实现三层区分 + 快(>9 cm/yr)=单一轴部隆起 / 慢(<5)=中央谷+裂谷山
  / 中=过渡（Nacrea 全速率 12 cm/yr → 单一轴部隆起）。

---

## 3 板块边界几何（犬牙 → 物理）

### 3.1 现状根因

三层随机叠加：Voronoi cell 对齐 + `boundary_noise`（随机翻转 ~10%）+ `boundary_warp`
（噪声扭曲测地距离，nacrea=0.3）→ tortuosity p99=102（earth 7.7），随机犬牙。

### 3.2 物理边界形态（[Frisch et al. 2011](https://link.springer.com/book/10.1007/978-3-540-76504-2)）

| 类型 | 真实形态 | 已有基础 |
|---|---|---|
| 汇聚 | **小圆弧**（[Frank 1968](https://www.nature.com/articles/220363a0) 岛弧曲率） | `trench_arc` 已实现（sagitta 已收窄，见下） |
| 离散 | **分段脊 + 转换断层直角错列**（en-echelon） | en-echelon 已实现（§3.11） |
| 转换 | **直线**（绕欧拉极的小圆） | `transform_straighten` 已实现 |

**离散边界诊断（2026-09 实测）**：分段脊已实现（§3.11），但实测发现离散边界的蜿蜒**主要不是缺分段脊，
而是海沟弧过深**——`_trench_arc_relaxation` 的 sagitta 曾按 `0.10–0.30×chord` 与段长成正比，
长段弧深可达 ~700 km（真实 Frank 1968 观测 sagitta/chord ~0.07–0.08、弧深 200–300 km），
全程翻转 ~11.7% 表面，把相邻离散边界间接搅成犬牙。已把 `s_target` 收到 `0.03–0.10×chord`，
蜿蜒明显减轻。残余的「斜向性」（边界走向与相对运动夹 31–49°）是 Voronoi 剖分的板块形状本身，
「翻 cell 到某条线」（几何弦或 ⊥ 扩张方向）实测都会让边界变长——非后处理可纠正，需从剖分层级
做「运动学一致」（见 §5 板块边界对齐）。

### 3.3 方案

用物理边界几何替代随机扭曲：汇聚走小圆弧（`trench_arc` 推广到全类型）、转换走直线、离散走
分段脊+错列。`boundary_warp`/`boundary_noise` 只保留低频分段弯曲（岛弧/造山带），去掉随机犬牙。

### 3.4 边界带宽度按类型分级（✅ 已实现，汇聚带后由 §3.6 取代）

**现状**：宽度由单一 `boundary_influence_km`（默认 500，private/nacrea 已改 250）统一驱动，
各类型只是乘同一 σ 的不同子倍数——汇聚 `sigma_conv = 0.8σ`（200 km）、离散 `sigma_div = 0.6σ`
（150 km）、转换 `sigma_trans = 0.4σ`（100 km，仅粗糙度带）。结果三种带宽同处 100–200 km
量级（4:3:2），挤压带与张裂带视觉宽度相近。

**地球参考**（Frisch 2011）：

| 类型 | 真实宽度 | 量级 |
|---|---|---|
| 汇聚（造山带/海沟） | 海沟—弧后 150–400 km；安第斯 ~100–200、喜马拉雅 ~250 km | ~10² km |
| 离散（洋脊轴部/大陆裂谷） | 洋脊轴部隆起/中央谷 1–30 km；东非裂谷 30–80 km | ~10¹ km |
| 转换（断层带） | 圣安德烈斯断层带 1–5 km（含变形带 ~100 km） | ~10⁰ km |

真实宽度 **汇聚 ≫ 离散 > 转换（约 10:3:1）**，当前 4:3:2 不符——离散/转换各宽了一个数量级。

**方案**：把 `boundary_influence_km` 拆成按类型独立的绝对带宽（`convergent_width_km` /
`divergent_width_km` / `transform_width_km`），默认对齐上表量级，不再共享单一 σ。转换的粗糙度
带也改由 `transform_width_km` 驱动（当前「1.5× 噪声、~100 km 带」是启发式，随 §7 网格精度
原则一并按真实宽度重构）。

### 3.5 沿走向宽度变化（分段）

**现状**：断裂带沿走向的宽度基本恒定——离散 `sigma_div`、转换 `sigma_trans` 都是全局常数；仅汇聚
的前缘 `sigma_front = σ_conv·(1−0.5·asym)·(0.7+0.6u)` 有 ±30% 的宽度变化。且 `u`（=`arc_u`）是
**全局 fBm 噪声**（`fbm_on_points(base_freq=8)`，~800 km 波长），汇聚的宽度、汇聚的高度
（`seg_mod = 1.6u−0.25`）、离散裂谷肩的高度（`seg_mod = 0.7+0.6u`）三者共用同一场——平滑的
球面噪声，没有「段」的结构，宽度与高度被同一 `u` 强制耦合。

**地球参考**：真实断裂带沿走向的宽度变化来自**分段结构**——裂谷的倾角域（dip domain，
~70×130 km，相邻极性交替，Scholz 1998，见 §2）、造山带的 salient/recess 与构造结（orogenic
knot）。段是离散的，段内宽度相对稳定、段间由 relay ramp / 转换带连接，宽度可在段间跳变。

**方案**：把「沿走向宽度调制」从全局 fBm 改为**分段弧长参数**——沿每条边界段累加测地弧长，
按 ~100 km 尺度切段，段内宽度慢变、段间可跳变；宽度与高度解耦（高度由 uplift 幅度定、宽度由
段宽定，不再共用同一 `u`）。与 §2 裂谷分段、§3.4 按类型宽度共用同一套「分段」基础设施。

**已实现（近似）**：用**量化高频 fBm**（`width_u`，base_freq 24 → ~270 km，量化到 3 档）取代
全局 `u` 驱动**汇聚带**宽度——`sigma_front` 改用 `width_u`，与高度 `seg_mod`（仍用 `arc_u`）
解耦。**离散带已回退**：裂谷海宽度不是 `sigma_div`（亚网格谷底），而是「大陆地壳被 rift 压到
海面以下」的范围，由**深度**决定（见 §8 地壳类型正交化）——后续应调深度而非宽度。转换
`sigma_trans` 因在 BFS 中用单一 σ，暂未加宽度变化。

### 3.6 山带/裂谷宽度的时间累积（临界楔，✅ 已实现）

**现状**：山带宽度是静态参数 `convergent_width_km`（nacrea 220 km），一条边界从头到尾同宽；
构造演化里 `_subduction_uplift` / `_collision_orogeny` 只按 `dt × 速率` 累加**高程**（山越演越高），
**不累加宽度**（山不会越演越宽）——与临界楔「宽度随缩短量增长」矛盾。

**物理**：造山带是临界楔（Davis, Suppe & Dahlen 1983），以临界锥角自相似生长，**宽度随累积
缩短量 S 增长**（物质在楔趾增生，维持恒定锥角）。宽度差异的根源是边界类型——大陆碰撞因浮力
大陆岩石圈低角度广域俯冲 → 变形分布数千 km（青藏 ~2500 km 汇聚 → ~1000 km 宽、地壳 70 km）；
洋壳俯冲因致密板片作「底板」→ 变形局域（安第斯 ~200–700 km）；flat-slab 俯冲把变形推入内陆
700–1500 km（落基山 Laramide）。大陆裂谷是分布式伸展，宽度沿走向 50→200 km（东非，岩石圈强度
/地幔柱几何驱动）。

**地球参考**：宽度/汇聚比 `k` = 碰撞 ~0.4（青藏 1000 km / 2500 km）、俯冲 ~0.1–0.2（安第斯
300 km / ~3500 km）；`w_0` ~ 50–100 km（初始碰撞带）、`w_max` ~ 1000 km（碰撞）/ ~400 km（俯冲）。

**方案**：把「累积汇聚量」从演化传给地形合成——
1. **演化阶段**：给每条边界 cell 追踪 `S = ∫ v_n dt`（相对汇聚速率沿边界法向分量 × 时间步），
   逐 cell 累积成 cell 字段（与 `arc_state` 类似的持久状态）。
2. **地形合成阶段**：山带宽度改为 `orogen_width = min(w_max, w_0 + k_type × S)`，
   `k_type` 由地壳类型定（陆-陆碰撞 0.35、陆-洋/洋-洋俯冲 0.15）。
3. **沿走向变化自然涌现**：欧拉极使同一边界不同位置汇聚速率不同 → `S` 沿走向不同 → 宽度沿
   走向不同；地壳类型切换再给宽度一个台阶。

### 3.7 渗漏转换（leaky transform，✅ 已实现）

**物理**：转换断层当相对运动与断层走向斜交时，带上伸展分量（**渗漏转换**），形成**拉分盆地
（pull-apart basin）**——死海（−430 m）、索尔顿海槽（Salton Trough）。渗漏的根源是板块重组改变
相对运动方向，使旧断层不再与运动平行。极快扩张下转换断层甚至维持不住，被微板块/重叠扩张中心
取代（东太平洋海隆 145–160 km/Myr）。

**地球参考**：死海转换（大陆渗漏转换 + 拉分盆地）、San Andreas 索尔顿海槽、Romanche 断裂带
（~900 km 错列记录脊迁移史）。

**实现**：
- `VoronoiCell` 新增 `tangential_fraction`（`v_t/v_total`，boundary_detector 段分类时计算并随
  边界属性传播）。
- transform 分支按 `v_t/v_total` 细分：`≥ 0.9` 纯走滑（现状，仅粗糙度）；`< 0.9` 且 `v_n < 0`
  （伸展性斜向，transtension）叠加拉分盆地沉降，幅度 ∝ 斜向度（`v_t/v_total=0.7` 时最深
  `transform_leaky_basin_depth_m`=400 m，死海 −430 m 量级）。
- 盆地沿走向连续（相邻渗漏 cell 不互相沉降）、垂直走向半深盆缘；只对伸展（`v_n<0`）形成拉分，
  挤压性斜向（transpression）会隆起、不沉降。

### 3.8 断陷盆地与地垒-地堑的可视化（✅ 已实现）

**现状**：边界汇聚带的地形合成只有「不对称山 + 海沟」，无断陷盆地机制（`interior_basin_chance`
只挂在 `interior_orogeny` 的内部古造山带上）。大陆裂谷的断块噪声 `fault_amp = 600 m` 被区域
噪声（±1200 m）和谷底深度（−1600 m）淹没，地垒-地堑不可见。

**物理**：断陷盆地（山间盆地）是**超临界楔**的伸展塌陷（Davis 1983），出现在宽、成熟造山带
（安第斯 Altiplano-Puna、青藏柴达木、阿尔卑斯内部盆地），不是均匀概率。地垒-地堑是大陆裂谷的
**本质结构**（Scholz 1998 半地堑倾角域），~100% 出现，随机性只在极性（哪一侧抬升）。

**方案**：
1. **地垒可见**：把 `fault_amp` 提为可调参数并加大（600 → ~1200 m），使断块起伏超过区域噪声。
2. **断陷盆地**：山带沿走向分段后，对**超宽段**（S 大、楔体过陡）以一定概率叠加一个拉长断陷
   盆地沉降（幅度 ∝ 山带宽度），位置在山后（上覆板一侧）。

### 3.9 海岸高程过渡（✅ 已实现）

**物理**：真实活动边缘（安第斯）确有海岸高山，但过渡带通常有海岸平原或至少一段缓坡；被动边缘
（大西洋型）有完整的大陆架 + 海岸平原。活动边缘海岸（离岸 0–50 km）是海岸山脉/平原（500–1500 m），
主弧高山（4000–6000 m）在内陆 100–200 km。

**实现**：
- **根因**：`_smooth_land_discontinuities`（图拉普拉斯平滑，最后运行）把 coastline cell 向陆侧
  高山邻居均值混合，抹掉了 `_apply_coastal_plain` 的海岸过渡。改为**排除 coastline cell**（保持
  过渡值，仍作为内陆 cell 的平滑邻居）。
- 海岸 cell 目标 `mountain_coast_ratio = 0.15`（内陆高山的 15%，即海岸山脉量级），过渡带
  `min_strip_km` 加宽到 ~3 cell（150 km），主弧高山离岸 2–3 cell 才恢复。
- coastline 检测统一为「所有陆上 cell（海拔高于海平面）且有海洋邻居」，不论地壳类型——
  O-C 俯冲带下插侧（物理上是海沟）和大陆海岸山一起平滑。
- **钉扎过抬（O-C 海沟变山）**：`_apply_geography_pins` 的 `pin_exponent > 1`（削峰）对偏差对称
  指数化，把 feature 软边上的深沟 cell 从 ~−14 km 抬到 +5.8 km（§3.9 违规，如 #168289/#162710）。
  改为只放大「高于目标」的下压方向，低于目标（海沟）线性上拉——海沟保持在海底（~−8 km），
  不再被抬成山。
- 结果：大陆海岸临海 >2000 m 的 cell 从 314 → 0；`coastal_plain_width_km`=100。

### 3.10 热点链群岛化（✅ 已实现）

**物理**：热点是固定地幔柱，板块在其上移动，火山**间歇性喷发**——每个火山在热点处生成、随后随
板块移走，形成一串**分离的火山岛/海山**（间距 ≈ 喷发周期 × 板块速率，夏威夷 ~50–100 km），
相邻火山之间是海或淹没的海山。

**实现**（`_generate_hotspots`）：
- 链沿欧拉极小圆（局部速度方向，每步重算 `velocity = ω×r`）按**真实测地 km** 追踪，火山沿链
  以 `hotspot_eruption_interval_km`（180 km）离散放置，替代逐 cell 连续抬升。
- 每个火山是钟形隆起（`cos(π/2·d/r)`），基底半径 `hotspot_volcano_radius_km`（100 km）、高度
  `hotspot_active_height_m`（8500 m，相对海底）；随弧长 `arc` 线性沉降
  `h = active_height − subsidence·arc`（`hotspot_subsidence_m_per_km` = 4 m/km），链尾沉成海山。
- 链长 `hotspot_chain_length_km`（1200 km）；追踪到非洋壳或**跨板块边界**（`plate_id` 变化）即止
  ——链记录单一板块的运动轨迹（Wilson 1963）。
- 所有几何量用真实 km（`config.radius_km`），网格精度无关（§7）。

### 3.11 边界整形统一（`_shape_boundary_segments`，✅ 已实现）

**问题**：Cortial 2019 的 Voronoi 边界是「阶梯状犬牙」（cell 边界锯齿），叠加噪声扭曲后还有大尺度蜿蜒；
旧最终整形是三个各管一段的 pass——`_trench_arc_relaxation`（汇聚弧）+ `_straighten_transform_boundaries`
（转换直线）+ `_smooth_partition`（去犬牙）——汇聚弧过深还反过来搅乱相邻离散边界（§3.2 诊断）。

**实现**：合并为一个 `_shape_boundary_segments`（`tectonic_simulator.py`），替换最终整形阶段的三个 pass：
1. 每条边界先用 `_split_bent_segment` **在弯折处切段**（递归，偏差 >30% 弦即切）；
2. 每段判类型——汇聚（`v_n > 0.5 cm/yr`）→ **弓成小圆弧**（抛物线 sagitta=0.15，朝洋侧/较快盘）；
   离散/转换 → **拉直**（sagitta=0，翻 cell 到弦）；
3. 段与段之间自然形成弯折。

**结果**：002/013（陆-陆碰撞）是单弧（0.15）；岛弧（洋壳俯冲）由演化期的 `_trench_arc_relaxation`
保留；飞地由 `_merge_plate_enclaves` 兜底（0 非单连通）。

**分段脊（§3.2，✅ 已实现）**：离散边界现在主动引入 en-echelon 错列——按洋中脊分段尺度
（`ridge_segment_length_km`=150 km）切成段，错列用随机游走（每段沿洋脊法向 ±100 km、重中心化），
连续段协同阶梯而非 iid 抖动；转换/超短脊仍拉直。

### 3.12 边界分类修正 + 噪声扭曲调参（✅ 已实现）

**问题（2026-09 实测）**：三类边界中转换占比过高（51.8%）、每条边界类型单一、且边界呈「大圆」
（Voronoi 测地弧，不弯曲）——「超长转换 + 单一类型 + 板块太圆」。

**根因**（三个，逐一修）：
1. **切向阈值误判**：`classify_boundary` 原先 `v_t/v_total > 0.7 → transform`，把「斜向」边界
   （v_n 显著 + v_t 更大）误判成 transform。地质学正确的判据是**类型由法向分量 v_n 的符号决定**
   （Stein & Wysession：motion parallel=transform、away=divergent、toward=convergent）——v_n 决定
   地壳消减/增生/守恒，切向分量是独立量（`tangential_fraction`，供 §3.7 渗漏转换），不该覆盖基本类型。
2. **质心分类太粗**：`_classify_boundary_segments` 按连通性把整条连续边界聚成一段、用段质心速度分类
   一次，v_n 沿走向的真实变化（−8~+8 cm/yr）被抹平。改为**沿走向按局部 v_n 子分段**，每子段单独分类。
3. **Voronoi 大圆固有 + 噪声扭曲太弱**：球面 Voronoi 边界本就是大圆；Cortial 2019 §3 的噪声扭曲
   （`build_cell_cost`）本应掰弯它，但 `base_freq=0.6`（波长 > 整个球面）+ 幅度 0.3 太弱，且 warp 在
   整形前跑被 straighten/bow 抹平。修法：`base_freq`→2.0、warp 挪到整形后、幅度→0.6。

**结果**：转换占比 51.8%→3%（潮汐锁定世界斜向快速运动，v_n 5~11 + v_t 12~25，几乎无纯转换——这是
诚实结果，非分类错误）；混合边界从 0 条→5 条（如 004–012_b 汇聚+离散+转换三类）；最直边界 dev/chord
p10 0.059→0.079，板块不再特别圆。

---

## 4 geography 锚定地貌真实化（部分已实现：噪声粗糙化 + 造山带/裂谷形态）

**现状**（`geography.py._feature_kernel`）：每个 feature 是「椭圆/圆 + cosine 钟形核」的偏置场，
叠加成 land-bias 场 → 全局阈值分配地壳。本质是「光滑椭圆 + 可选 fBm」，大陆椭圆状、海岸线光滑、
边界处无造山带/裂谷结构。

**分析**：锚定地貌不应是「椭圆色块」，而应是一块**被地形设施塑造的地壳**——大陆边缘有造山带
（汇聚）、裂谷（离散）、内部低地、岛弧。地形设施的**位置**依赖板块边界（§5，已落地）；但**形状**
（粗糙化、散碎、分段）独立于 §5，直接在 geography 噪声层 + terrain 合成层做。

**已实现**：
- **锚定地貌噪声粗糙化**：`geography.py` 给 feature 加 `noise_amplitude`（`_FEATURE_NOISE_SEED_OFFSET` +
  `feature_noise_seed()`），`_feature_kernel` 注入 fBm 噪声，打破高原/裂谷的椭圆规整形状。
- **古造山带形态**（`terrain_synthesizer.py._apply_interior_landforms`）：长度封顶
  `belt_length_deg = 2.0 + 8.0·rand²`（大部分 ~600 km、最长 ~1200 km）+ `_angle_ap > angle_ab` 长度过滤，
  大圆造山带从「长条」变为「散碎短段」；去掉 `min(n_belts, 4)` 硬封顶，`interior_orogeny_count`
  真正生效（belt 数随面积缩放）。
- **裂谷形态**：同造山带——长度封顶 + 过滤，避免「贯穿板块的单条长裂谷」（如 #78129 的 206-cell 裂谷）。

**遗留**：§3.5 的「裂谷海宽度沿走向变化」（transitional 带宽度分段）仍为提案。

---

## 5 geography ↔ 板块运动协调（核心架构）

### 5.1 矛盾本质

- `geography.yaml` 锚定「大陆 A 在 (lon,lat)」= 静态目标地貌。
- Cortial 2019 板块独立生成 → 板块边界落在任意位置（与大陆边缘无关）→ 造山带/裂谷出现在
  错误位置。
- `reapply_after_tectonics` 只重贴地壳颜色，没修板块边界 → 物理不一致。

**本质**：真实世界大陆就是板块（大陆地壳坐大陆板块上），大陆-海洋边界就是（或曾是）板块边界。
Dreamulator 让大陆与板块独立生成 → 边界不对齐 → 矛盾。

### 5.2 业界两条路线

| 引擎 | 路线 | 机制 |
|---|---|---|
| [**Gleba**](https://indiegoblin.com/games/gleba-v012)（科学） | **co-specify + 正向模拟** | 用户同时导入 **crustmap**（大陆/洋壳图）+ **platemap**（板块图+运动点）；[官方要求](https://itch.io/t/6057077/how-to-get-started-with-crustmap-and-platemap-imports)「地壳边界必须与板块边界对齐」，否则造山带不出现 → 正向板块模拟，地形既符布局又符物理 |
| [**Azgaar FMG**](https://azgaar.github.io/Fantasy-Map-Generator/)（艺术） | **纯高度图，无板块模拟** | 高度图模板（Hill/Pit/Range/Trough）+ 笔刷，用户**手动**赋予构造意义，不做板块演化 |

Dreamulator 介于两者之间：有板块模拟（近 Gleba），但锚定用偏置场（近 Azgaar 的简化）。

### 5.3 反向演化不可行

用户提出「反向演化」（从目标地貌反推板块历史）。对 Cortial 2019 不可行：
- 时间演化含**不可逆过程**（俯冲消亡/裂解/侵蚀），算子不可逆；
- 同一地貌有**无穷多历史**（非唯一），反演无良定义。

Gleba 不做反向演化——它通过**让初始条件（板块+运动）与目标地貌一致，再正向演化**来协调。

### 5.4 修复方向（正向演化 + 一致初始条件）

1. **板块从 geography 派生**（Gleba 式，最彻底）：大陆/洋盆定义板块（或板块边界跟随大陆-海洋
   边界），再赋相干运动、正向演化。改动大（重写板块剖分与 geography 接口）。
2. **板块边界对齐大陆边缘**（折中）：保留 Voronoi 板块，重跑分区时给「大陆边缘」加权，把板块
   边界「吸」到大陆-海洋边界附近。
3. **锚定 + 松弛**（最小）：把造山带/裂谷/岛弧约束到「靠近大陆边缘的板块边界」，并让
   `reapply_after_tectonics` 同时修板块边界。

**已实现方案 2**（见 §5.7）：保留 Voronoi 板块，重跑分区时给「大陆边缘」加权，把板块边界「吸」
到海岸附近。方案 1 改动太大（重写板块剖分 + geography 接口）、方案 3 太弱，方案 2 取折中。

### 5.5 大陆裂谷速率偏快（✅ 已实现）

相干运动（§1）给的是海洋型板块速率，未区分大陆/洋壳。物理上大陆岩石圈更厚（~150 km 克拉通
根 vs 洋壳 ~7 km）、更难破裂，且含大陆的板块往往动得慢（非洲 ~2 cm/yr vs 太平洋 ~10 cm/yr）。

**实现**（`_assign_coherent_euler_poles`）：欧拉极拟合后，按板块的**大陆 cell 占比**线性减速
`slowdown = 1 − (1 − continental_plate_speed_factor) × cont_frac`，`continental_plate_speed_factor`
= 0.3（非洲/太平洋速率比）。纯大陆板块减速到 0.3×，纯海洋不减速，混合板块按占比插值。

**结果**：大陆板块 ~3.5 cm/yr、混合 ~7.4、海洋 ~9.2；大陆裂谷离散速率 median 3.0 cm/yr vs
洋中脊 10.8（减速 ~3.6×）。

### 5.6 板块形状不规则（半包围，✅ 已实现）

Cortial 2019 Voronoi 剖分 + 噪声扭曲 + 构造演化产生不规则板块形状——如 plate_014 C 形半包围
plate_011_a（#30822 附近，divergent 边界）。这不是 1-cell 犬牙，trench_arc/转换拉直管不到；
是板块**剖分/演化**层面的遗留问题。

**根因（实测）**：两处来源——
1. **裂谷碎片非凸**（剖分）：原 `_partition_cells` 加权多源 Dijkstra 产生非凸碎片，一个大碎片可
   C 形半包围一个小碎片。
2. **演化包裹**（演化）：小碎片在 50 步「质心旋转 + 加权 Voronoi + 海沟弧」演化中被相邻大盘
   逐渐包裹成「洞」（实测 span 高达 ~350°，即单邻居包裹 >95% 视界）。

**物理依据**：`plate_tectonics.md`——图上 Voronoi 天然凸，板块永不包围；真实板块是凸块，
无「洞」板块（小板块如 Scotia/Juan de Fuca 也有 ≥2 个显著邻居）。

**实现**：
- **剖分**：`_partition_cells` 改为递归平面切割（small-circle 裂谷裂缝），保证碎片凸；logistic
  阈值保留大小偏态（power-law）。
- **演化**：新增 `_merge_enclosed_plates`——单个邻居包裹 > 240°（2/3 视界）且面积 < 2% 的小板块
  被吸入包裹者（拓扑上是「洞」，非构造板块）。

**结果**：最差「半包围」span 351°→186°（186° 为正常的双板块边界），消除「洞」板块
（板块数 30→25）。

### 5.7 板块边界对齐大陆边缘（方案 2，✅ 已实现）

**实现**（§5.4 方案 2 折中：保留 Voronoi 板块，重跑分区时给大陆边缘加权）：

- **地壳掩码复用**：`geography.compute_geography_land_mask` 把 `apply_geography_crust` 的
  `field`/`fbm`/`score`/top-N 掩码逻辑抽成纯函数，海岸代价场与地壳分配共用（不重复算 fBm）。
- **海岸代价场**：`geography.build_geography_coast_cost` 返回
  `coast_cost = 1 + w·max(0, 1 − d/band)`（`d` = 到海岸线的测地距离，复用 `distance.geodesic_bfs`；
  `w = geography_boundary_weight`=4.0，`band` ≈ 2×平均 cell 间距）。海岸带高代价 → 加权
  Dijkstra 里陆/洋波前的相遇点（边界）被钉在海岸上。
- **地理对齐种子**：`plate_generator.select_geography_seeds` 给每个 ≥0.5% 面积的大陆/大洋连通域
  在内部（`|field|` 最大处）放 1 个种子，剩余名额用最远点采样铺在非海岸 cell —— 大陆 = 板块、
  大洋 = 板块。
- **贯穿演化**：初始剖分（`_generate_plates_impl`）与构造演化重采样（`_evolve_cortial2019` 的
  `partition_cost`）与最终 warp（`warp_boundaries` 噪声代价 × 海岸代价）都用同一**固定**海岸
  代价场（不随漂移地壳变）——边界全程锚向固定海岸线，与最终 `reapply_after_tectonics` 重锚的
  同一海岸线对齐。
- **纯程序化世界零改动**：无 geography 时 `select_plate_seeds` + `_voronoi_partition` +
  `unit_cost` 原样，同物理原则不受影响。

**结果**（nacrea，w=4.0）：边界对齐率（板块边界 cell 落在海岸上的占比）12.0%（随机基线 ~7%），
板块 25 个（与「seed=42 实测 25」一致）。大陆主体被大陆板块覆盖、大洋主体被大洋板块覆盖。

**目标界定**：方案 2 承诺「边界吸到海岸**附近**」而非精确重合（Voronoi 凸胞不能贴合非凸海岸线，
§5.3/§5.6 已论证）；且「板块可海陆兼有」（如印度板块），故海岸不必逐条是板块边界。

---

## 6 实现顺序

| 顺序 | 项 | 依赖 | 规模 | 依据 |
|---|---|---|---|---|
| 1 | §2 裂谷（半地堑 A/B/C） | — | 小-中 | 半地堑分段（Scholz 1998）；前端可见问题 |
| 2 | §3 边界几何（犬牙→弧段/直线/分段脊 + §3.4 宽度分级 + §3.5 分段） | — | 中 | Frank 1968 / Frisch 2011 / Scholz 1998 |
| 3 | §5 板块边界对齐大陆边缘（方案 2） | §3 | 大 | Gleba crustmap+platemap 边界对齐 |
| 4 | §4 锚定地貌真实化（复用造山带/裂谷） | §5 | 中 | 依赖边界对齐后 |

先做独立、见效快的 §2/§3，再攻核心架构 §5，最后 §4 水到渠成。§7（网格精度无关性）是横切
清理项，可与任一步并行或插队。

---

## 7 交叉原则：网格精度无关性（真实距离单位，✅ 已实现）

**原则**：所有「宽度/距离/带宽」参数与计算**必须以真实长度（km，球面测地距离）为单位**，
不得用「cell 数量 / hop 次数」作距离。切换网格精度（`num_nodes`）后，物理形态应近似不变，
仅采样分辨率改变。

**实现**：抽 `distance.geodesic_bfs` / `geodesic_bfs_with_source`（逐边 `arccos(x·y)·R` 累加）作为
唯一参考实现，替换 terrain/boundary 里 8 处 `cell_km = √(4πR²/n)` 平均间距近似（净删 ~120 行）；同时
修两个明确错误——`_compute_boundary_strike` 硬编码 6371 → `config.radius_km`、`_compute_ocean_age_depth`
的 `4R/√n` → `√(4πR²/n)`；并修 `_bfs_distance` 的 `cell_radius_km * 2.0` 命名混淆（参数实为间距，
×2 让距离系统性偏大 2 倍）。

`tectonic_simulator._bfs_distance` 保留「平均间距」hop 步长（已去掉 ×2）而非逐边 arccos——它是构造
演化中间步骤、性能敏感（50 步循环 + adj 扁平数组），距离精度对 uplift 平滑函数影响小。

**审计勘误**：`tiny_threshold = num_cells·0.0015` 实为**面积比例**（0.15% 表面积，cell 面积均匀时
等价于 0.15% cell 数），不随分辨率缩放，非「纯 cell 数量阈值」——不改。

---

## 8 地壳类型正交化（取消程序化 transitional，✅ 已实现）

**决策**：程序化管线里取消 `transitional` 地壳，`crust_type` 只留 continental/oceanic 二分；
「海陆/浅深」改由 `water_class`（+ `elevation` 水深）表达。

**原因**：地质上的「过渡地壳」由地壳厚度/成分定义（15–25 km，裂谷陆缘/岛弧），**不是高程**。
原 `classify_sea_land` 的「±50m 近海平面 → transitional」实为「大陆架/浅海」，与地质概念混淆。

**改动**：
- 删除 `classify_sea_land`（terrain_synthesizer）及其 ±50m transitional 改标 + 岛弧改标。
- `ocean_circulation` 的「ocean 判据」从 `crust_type in (oceanic, transitional)` 改为
  `water_class == "ocean"`（含陆架/裂谷海，正确的连通性海陆分类）。
- `transitional` 退化为仅真实地球 CRUST1.0 导入（`crust1.py`）的合法值。

**后果**：裂谷海 = 大陆地壳被 rift 压到海面以下（不再有「transitional 带」），其宽度由 rift
**深度**决定（谷底压多深、哪些 cell 落到海面以下），是 terrain 合成层的事——后续调深度而非宽度。

**遗留问题（✅ 已修复，§4 前置）**：取消 transitional 后曾暴露出——`crust_type` 实为 geography
land-bias 场的「海陆代理」（全局阈值 ≈ 海岸线），**不是地质地壳**。实测曾有 ~2000 cell「land 但
oceanic 地壳」（海岸错位）。修复：`_apply_continental_shelf` 里把 shelf cell（近岸浅水、
`shelf_width` 内）从 oceanic 划回 continental——陆壳边界 = 海岸线 + 大陆架，而非海岸线本身。
结果：大陆地壳 28%→41.5%（对齐地球 ~40% 含陆架）；「land 但 oceanic」1996→237（剩余为火山岛/
岛弧，本就该是洋壳）。

---

## 参考资料

- Beuthe, M. (2013). *Spatial patterns of tidal heating*. Icarus 223(1). [arXiv:1212.4630](https://archive.org/details/arxiv-1212.4630)
- Lithgow-Bertelloni et al. (1993). *Toroidal-poloidal partitioning of plate motions since 120 Ma*. GRL 20(5). [doi:10.1029/93GL00168](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/93GL00168)
- Scholz, C. A. et al. (1998). *Comparative sequence stratigraphy of … East African and Baikal rifts*. — 半地堑分段、倾角域交替。
- Frank, F. (1968). *Curvature of Island Arcs*. Nature. — 岛弧小圆弧。
- Frisch, Meschede & Blakey (2011). *Plate Tectonics*. Springer. — 边界形态（岛弧/转换/洋脊）。
- Cortial et al. (2019). *Procedural Tectonic Planets*. CGF 38(2). [doi:10.1111/cgf.13614](https://onlinelibrary.wiley.com/doi/10.1111/cgf.13614)
- [Gleba — Calandiel 幻想世界模拟器](https://indiegoblin.com/games/gleba-v012) + [crustmap/platemap 导入说明](https://itch.io/t/6057077/how-to-get-started-with-crustmap-and-platemap-imports)
- [Azgaar's Fantasy Map Generator](https://azgaar.github.io/Fantasy-Map-Generator/) — 高度图模板，无板块模拟。
- 源码：`map/plate_generator.py`、`map/geography.py`、`map/terrain_synthesizer.py`、`map/boundary_detector.py`。
