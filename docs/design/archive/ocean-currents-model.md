# 基础洋流系统实施计划（roadmap 3A.3）

> 状态：方案草案（2026-08-07），待批准后实施
> 涉及：`src/dreamulator/map/`、`src/dreamulator/engine/climate.py`、前端地图图层、`docs/knowledge/climatology/`
> 前置阅读：`docs/knowledge/climatology/ocean_currents.md`（科学底座，已齐备）、
> `docs/design/geological-pipeline.md`（临界洋流需求）、
> 乐意 Ajax《季风世界》EP1 视频分析（前端双语言实证）
> 上游依赖（均已就绪）：风场 stage 2 ✅、高程锚定 + `sea_level_offset_m` ✅（v0.18.0）

---

## 〇、结论速览

1. **模型选型：Stommel 流函数解（β 平面摩擦涡度方程）为主干，Ekman 层做诊断**。
   理由：① 流函数形式在赤道无 `1/f` 奇点（β=2Ωcosφ/a 在赤道最大而非零）——
   gaia-m 慢自转（Ω=0.31Ω⊕、3.25 天潮汐锁定）下地转求逆会除零，流函数是唯一
   全程良态的极小模型；② 西边界强化（WBC）作为摩擦边界层自然涌现，不需要
   手贴 ×3 系数（只留校验阈值）；③ 海峡闸口可在流函数框架内以"跨盆地输运
   约束"表达，直接对接 gaia-m 临界洋流剧情。
2. **SST 修正走"沿流平流松弛"**：复用 BFS 水汽的既有思路（沿输送方向迭代松弛），
   不做有限差分平流格式——无稳定性问题、在 CVT 不规则网格天然成立，
   暖流增温/寒流降温/衰减尺度全部由迭代参数控制。
3. **前端按乐意 Ajax 实证的"双语言"做**：教科书箭头带（SVG overlay，暖流品红/
   寒流青绿，少量粗弧线+箭头端，可标注命名洋流）+ 科研流线场（CPU 烘焙进
   DataTexture，ANGLE-safe）。他在 EP1 里相隔 24 秒先后放出两种画法
   （f_0312 箭头带 → f_0336 流线场），"先大众能懂的、再专业加固可信度"——
   我们做成同一图层的两种可切换渲染。
4. **数据流零新增栅格端点**：逐 cell 流速分量写进 `cvt_mesh.json`（气候回写
   既有通道），前端本地烘焙/积分流线，静态模式自动可用；仅"命名洋流路径"
   走一个新 JSON 产物（按 CLAUDE.md 三文件同步）。
5. **验收锚点**：温度 RMSE 12.87°C → <8°C（roadmap M3，earth/climate-dev 离线验证）；
   gaia-m 四条临界洋流用例（heightmap 计划 §4.4）。

---

## 一、现状盘点（2026-08-07 行号级勘察）

### 1.1 气候管线中的挂载点

`simulate_climate`（`map/climate_simulator.py:68`）四阶段：

| 阶段 | 内容 | 与洋流的关系 |
|------|------|--------------|
| 1 温度 | 全球标量 → 纬度剖面 → 陆地直减；`_ocean_surface_temperature`（:374-412）为**纯纬度 SST 剖面**（28°C 赤道 → −30·sin²φ，70° sigmoid 接海冰） | **SST 无经度/洋流修正——洋流热输送的直接挂载点** |
| 2 风场 | 地转风（图梯度 :272-333 + f 参数 :212-226，赤道 \|f\|<1e-8 回退）0.4 + 三圈环流 0.6 合成（:187），地形阻挡 | 风应力 τ 的输入已就绪，但风矢量**不写 cell、不持久化**，仅 BFS 内部用 |
| 3 BFS 水汽 | 海洋蒸发（Clausius-Clapeyron）→ 顺风 BFS 12 趟 → 降水 | 蒸发用 `temperature_c`——SST 修正后自然受益，无需改动 |
| 4 Köppen | 最冷/最热月 + 降水 | 自动吃到修正后的温度 |

**插入位置：stage 2（风）之后、stage 3（BFS）之前**，新设 stage 2.5：
风 → τ → 流函数解 → 流速场 → SST 平流修正 + 上升流诊断 → 修正后的 SST
进入 stage 3 蒸发与 stage 4 Köppen。**单向单遍**（不做 SST↔风 迭代回耦合，
记入已知限制；可选 Picard 迭代留 config 开关位，默认关）。

### 1.2 已有的与缺的

| 资产 | 现状 |
|------|------|
| `ekman_current_direction`（`climate_physics.py:475-519`） | **孤儿**：全库零调用、零测试；逐 cell Python 循环未向量化；±45° 偏转 + 2% 风速符合教科书。本期**改造复用**为上升流/表层偏转诊断 |
| `num_gyres: int = 5`（`pipeline_types.py:247-248`） | 死参数，零使用——**删除**（技术债教训：不留占位旋钮） |
| `docs/knowledge/climatology/ocean_currents.md` | 科学底座齐备：§1.1 Ekman、§1.2 Sverdrup/Stommel、§1.3 慢自转环流更大（gaia-m 适用）、§2 热盐双稳态、§3 海峡闸门（ITF/巴拿马/德雷克）、§5 引擎对应表（现状 ❌ 待填） |
| `export_equirectangular`（`export.py:47`） | 任意 cell 字段名可导出——洋流标量场（流速幅值）零改动可出 PNG |
| `VoronoiCell`（`models.py:118-229`） | 无风/洋流字段；新增字段须 `Optional`（旧世界 mesh 兼容） |
| 气候回写 `_update_source_mesh`（`engine/climate.py:224-260`） | 洋流字段加入回写清单 → 前端经 cvt_mesh.json 直接可用 |

### 1.3 gaia-m 特殊性（参数标定依据）

- 自转 3.25 天（Ω=0.31Ω⊕）→ β 弱、罗斯贝变形尺度大 → **环流圈更少更大**
  （ocean_currents.md §1.3 明示"不应照地球模板"）；climate 段已按慢自转标定
  （hadley_extent_deg 55、polar_cell_start_deg 75）。
- 潮汐锁定：永久昼/夜半球 → SST 经度梯度本来就存在（未来扩展项，本期不做）。
- **已修正（2026-08-09）：前导点褶皱山系**（原"前导点褶皱山系"，~90°E）——实测地形为大陆南缘高山带（最高 ~9 km），非微陆块/岛弧/浅峡。此处无低纬通道——Aegis 深渊洋 ↔ 虚空洋的洋流交换不经过此区。**临界海峡候选点需重新评估**（见 geography.md 2026-08 修正记录）。

#### 1.3.1 基于实测地形的临界海峡（2026-08-09 分析）

经手动查验 + 洋面局部密度检测，确认以下两处为 gaia-m 主要临界海峡：

**① #32361 — 前导点山系南侧海峡（71°E, 21°N）**

- 深度 −106 m，极浅；R=8 跳洋面密度 128 cell
- 连接 Aegis 深渊洋（向星点海洋）与东方大洋的**唯一低纬通道**
- **临界性**：gaia-m 版印尼贯穿流（ITF）analog。冰期 −120 m 海退时
  通道从 ~128 cell 缩窄至几乎关闭→两大洋 SST 分异→可能改变 Hadley
  环流的纬向非对称性（向星 vs 背星热力差异扩大）
- **对海平面最敏感的临界海峡**——浅水底质 + 长通道

**② #60705 — 大裂谷海狭窄段（−89°E, −12°S）**

- 深度 −2577 m，R=8 密度 86 cell——**深水型**瓶颈
- 四板块交汇，裂谷海最窄处，两侧陆地海拔 162–3517 m
- **临界性**：gaia-m 版直布罗陀 analog，但机制不同。不受冰期海平面
  影响（太深），临界性来自**构造收窄**——板块运动使瓶颈变窄→限制
  裂谷海南北盆地水体交换→盐度升高→可能形成独立深水团。在百万年
  构造尺度上存在"关闭→蒸发→盐层"的墨西拿危机式终态
- 验收用例：构造参数扫描（`tectonic_steps` 增加→瓶颈几何变化→
  两侧 SST/盐度分异）


**其他海峡（不纳入本期设计）**：

- #14716（−4°E, 45°N）：北方内海唯一出口，浅水 −104 m。依赖北极
  周缘裂谷，属构造-海平面联合敏感型。留待后续自动检测算法成熟后评估。
- #4261（160°E, 66°N）：双板块北极海峡，白令海峡 analog。深度 −105 m。
- 南大洋环极通道（~50°S）：宽阔深水，无狭窄瓶颈。gaia-m 两圈环流下
  为下沉高压带而非西风带，不构成地球式 ACC 临界性。

---

## 二、物理模型选型

### 2.1 候选对比

| 方案 | 形态 | 优 | 劣 | 裁决 |
|------|------|----|----|------|
| A. 纯 Ekman 漂移（roadmap 子任务 1 字面式） | `current = rotate(wind, 45°×sign(φ)) × 0.02` 逐 cell | 半小时能写完 | **无盆地几何、无环流闭合**：画出来是风的回声不是洋流；海峡输运无从谈起 | 否（降级为诊断量） |
| B. Sverdrup 无摩擦输运 | β·V = curl(τ)/ρ₀ 直接反演 | 物理干净 | 需除以 β 求输运后还要**另外手造西边界流闭合**；β→0 处奇性需人工压制 | 否 |
| C. **Stommel 摩擦流函数** | β ψ_x + R ∇²ψ = −curl(τ)/(ρ₀H)，ψ\|海岸=0 | ① 流函数在赤道良态（β 项不含 1/f）；② WBC 是方程的边界层解，强度/宽度由 R/β 自然给出；③ ψ 差 = 输运 → 海峡流量有天然表达；④ 球面 CVT 上就是稀疏线性方程组，scipy 一行解 | 需要逐盆地组装稀疏矩阵（工程量主要在这） | **✅ 主干** |
| D. 分层/时变原方程（MOM 式） | 原始方程时间积分 | 真物理、可出 ENSO 式振荡 | 与"基础洋流"目标差两个数量级工作量；稳定性/调参深坑 | 远期（§十登记） |

### 2.2 选定形态（C + A 诊断）

**主干方程**（每个连通海洋盆地独立求解，ψ 在海岸 cell 上 Dirichlet=0）：

```
β(φ) ∂ψ/∂x + R ∇²ψ = − curl_z(τ) / (ρ_w H_ml)
```

- τ = ρ_air C_D |u| u，C_D=1.2e-3、ρ_air 用 `pressure_from_temperature` 既有气压
  （C_D/ρ_air 取常数起步，入 config）；
- β = 2Ω cosφ / a（a=行星半径，从 config 来——**不用地球值**）；
- H_ml = 混合层深度（默认 50 m，config）；R = 底摩擦系数（调参主旋钮）；
- 求解：`scipy.sparse.linalg.gmres`（非对称算子，对角预处理）；
  ~72k 海洋 cell（gaia-m 100k×72%）秒级。

**流速场**：u = (−∂ψ/∂y, ∂ψ/∂x)（图梯度再取切向分量）。**单位关键**：方程右端
已除以 ρ_w·H_ml，故 ψ 的单位是 m²/s（输运流函数），其梯度 ∇ψ 的单位直接是 m/s
——**不要再除以 H_ml**（历史 bug：`velocity /= h_ml` 重复除了一次混合层深度，
把 gaia-m 洋流压到 ~0.9 cm/s，实际应为 ~46 cm/s）；这就是可视化与热输送用的洋流场
（正压近似，深度平均）。

**CFL 带来的 CVT 适配洞察**：MPAS-Ocean（NCAR 全球大洋模型）的网格正是
**Spherical Centroidal Voronoi Tessellation（SCVT）**——与我们同构。
它证明了 CVT 是海洋建模的自然选择，原因有三：① Voronoi cell 天然是有限体积法
的控制体；② hex-dominant 邻接（~6 neighbors/cell）让梯度与通量表达简洁均匀；
③ 无经纬网极点奇性。但 MPAS 用的是全 TRiSK C-grid 方案（速度在边心、
质量在 cell 心、涡度在三角形顶点），针对原始方程自由面时间积分——
对我们的稳态正压流函数模型严重过重，不采纳。

#### 2.2.1 无 Voronoi 边几何的离散化（仅用 cell-center 数据）

当前 `VoronoiCell`（models.py:118-229）存储 cell 位置 (x,y,z)、面积 `area_km2`、
邻接表 `neighbors`，但**不存** Voronoi 多边形顶点 / 边长度 / 边切向量。
三个算子都能仅用 cell-center 数据计算——这避免了向 mesh 增加几何数据的开销：

**∇²ψ（图 Laplacian，均匀加权）**

```
∇²ψ|_i = (1/A_i) Σ_{j∈N(i)} (ψ_j − ψ_i)
       → L_ii = −k_i / A_i,   L_ij = 1/A_i  (j∈N(i))
```

对于经过 Lloyd 松弛的 CVT（近正六边形），边距比 l_ij/d_ij ≈ 1/√3 ≈ 0.577，
近乎常数——Laplacian 的**形状**是精确的（与各向同性扩散算子一致），
常数差异被 R 的调参吸收。均匀权重天然保证 L 对称，CG 收敛性优于非对称加权。

**∂ψ/∂x（东向梯度投影）**

图梯度 ∇ψ_i（`_compute_graph_gradient`，climate_simulator.py:272-333）已经
返回 (N,3) 切向量。东向分量只需在其上做投影：

```
∂ψ/∂x|_i = ∇ψ_i · east_i
```

其中 east_i 是 cell i 的局部东向单位矢量（从球坐标直接算，已有设施）。
这给出线性算子 G_east：ψ → Σ_j g_ij ψ_j。G_east 与 L 的**非零模式完全一致**
（都是 cell + 邻居），稀疏组装零新增复杂度。

**curl_z(τ)（风应力旋度，梯度-"分量方式"——不用 Stokes 线积分）**

Stokes 线积分绕 Voronoi 多边形确实需要边几何。但利用向量恒等式：

```
curl_z(τ) = ∂τ_north/∂x_east − ∂τ_east/∂x_north
```

分三步：
1. 将风矢量 τ（3D 切向量，stage 2 已算出）分解为东/北标量分量 τ_east, τ_north；
2. 分别对两个标量场调用 `_compute_graph_gradient` → ∇τ_e, ∇τ_n（两个 (N,3)）；
3. curl_z = (∇τ_n · east) − (∇τ_e · north)。

**与 `_compute_graph_gradient` 的深度复用**：curl_z 所用到的三样东西（图梯度、
东/北方向矢量、边表）全都是气候管线现有的。新增代码主要是稀疏矩阵组装 +
盆地 BFS 提取 + CG 调用——**零新 mesh 几何数据**。

#### 2.2.2 备选降级方案：启发式环流（零求解）

若慢自转 gaia-m 下 CG 不收敛或收敛到非物理解，有一个降级逃生路径：
**FreezeDriedMangos/realistic-planet-generation-and-simulation**（GitHub）在
p5js 的球面 Voronoi grid 上做了纯几何环流——按纬度带分组海洋 cell 成 gyre、
每 cell 流向由距 gyre 边界的距离和邻居的相对位置决定。没有 PDE 求解，
西边界强化需手贴系数、海峡输运无法定量表达。

此方案可在 P0 早期作为**原型验证**（半天出图，验证管线集成与前端渲染的正确性），
但最终须切回 Stommel——因其"海峡输运定量表达式"是 gaia-m 临界洋流需求的
必需品（§4.4 的 flux ∝ A 无法由 gyre 分组给出）。

**Ekman 诊断量**（不重复造环流）：
- 表层偏转流：`ekman_current_direction` 向量化后输出"风生表层分量"，供上升流
  诊断与箭头带图层的可选偏转；
- 上升流指数：沿岸 cell 的 Ekman 输运散度（离岸风 → 冷异常），东边界判定 =
  沿岸 cell 且盆地方位在其西侧（邻接几何直接算）。
- 注：`ekman_current_direction`（climate_physics.py:475-519）当前为逐 cell Python
  循环——P0 同时做向量化改造（numpy + 球面叉积代替局部东-北平面旋转，
  对齐 climate_simulator.py:361 的 `np.cross(nodes_xyz, grad_p)` 风格）。

### 2.3 SST 修正：semi-Lagrangian 沿流溯源

不写平流微分格式。对每个海洋 cell，沿 −u（上游）方向逐 cell 回溯距离
L = |u|·τ，取回溯终点的 SST：

    L = |u|·τ                        # 暖异常在 τ 内被海气交换耗散前流过的距离
    SST[i] = SST_ref[回溯终点(i, L)]  # 暖水沿流搬运，无逐格衰减

- **τ = ρ_w·c_p·H_ml / λ** 是表层 SST 调整时间（海气阻尼时间）：
  - ρ_w=1025 kg/m³（海水密度）、c_p=4000 J/(kg·K)（海水比热）、
    H_ml=50 m（混合层深度）、λ≈25 W/(m²·K)（海气阻尼系数，Haney 1971
    经验值 ~15–35 W/(m²·K)，随风速变化）
  - 代入得 τ ≈ 95 天（~3 个月），`ocean_sst_advection_days` 默认 90。
  - 对比旧的扩散松弛（λ=0.1、passes=8，Courant 数 0.8 < 1）只传播 < 1 格、
    anomaly ~0.3°C；semi-Lagrangian 让 WBC（|u| ~ 0.4 m/s）回溯 ~1200 km、
    anomaly 达 +3~5°C。
- 回溯只在海洋 cell 内进行（陆地阻挡洋流，且陆地温度为气温非 SST）；
- 收敛后 `sst_anomaly = SST_final − SST_ref`，写回海洋 cell 的 `temperature_C`；
- **沿岸陆地辐射**：距海岸 ≤ `coastal_influence_km`（默认 500）的陆地 cell
  按距离衰减吃一部分 anomaly（海洋性气候）——用既有的 BFS 距离场设施。

**温度 anomaly 沿风输送到陆地（层次 2，ocean → land 耦合）**：洋流/上升流产生的
海洋 SST anomaly 沿盛行风通过 wind-biased graph diffusion（复用 BFS 的 Laplacian +
GMRES）扩散到陆地——有符号，暖流（WBC）偏暖下游海岸、寒流（EBC，洪堡型）偏冷。
`ocean_temperature_diffusivity` 标定传播距离。取代旧的各向同性
`diffuse_heat_graph` 耦合（`advect_temperature_anomaly`）。

### 2.4 海峡闸口参数化（临界洋流钩子）

对每对相邻盆地，扫描"海峡 cell"（海洋 cell、两侧 ≤ d 内均有陆地、且处于
两盆地分水处）：

```
通道截面积 A = 宽度(几何) × max(0, sea_level_offset_m − elevation_m)   # 钉扎高程已就绪
输运 T_strait = C_d · A · sqrt(2 g' Δh)    # 水力学约束流，Δh 取两盆地 ψ 换算的水位差
```

- 实现方式：在流函数组装阶段把海峡 cell 对以"输运约束"耦合两盆地的解
  （等价于给 Dirichlet 海岸开一个有限导通的口）；
- **海平面敏感性是内生属性**：elevation pin（v0.18.0 已交付）钉住海峡深度后，
  `sea_level_offset_m` −120 m → A→0 → 通道关闭，无需专门分支逻辑；
- 呼吸潮 ±11 m：同一机制代入 offset 序列即可得脉动输运（本期只做稳态快照
  参数化，时变序列留 §十）。

---

## 三、数据模型与产物

### 3.1 VoronoiCell 新字段（全部 Optional，旧 mesh 兼容）

| 字段 | 单位约定（CLAUDE.md：单位入名） | 说明 |
|------|------|------|
| `ocean_current_east_m_s: float \| None` | 东向分量 | 陆地为 None |
| `ocean_current_north_m_s: float \| None` | 北向分量 | 同上 |
| `sst_anomaly_c: float \| None` | °C（相对纬度剖面的偏差） | 前端寒暖流着色依据 |

同步镜像：前端 `types.ts`；回写清单：`engine/climate.py:_update_source_mesh`。

### 3.2 新配置段（`pipeline_types.py` "Ocean" 小节，替换死参数 num_gyres）

```yaml
ocean:
  currents_enabled: true            # 总开关（A/B 与回归守卫用）
  drag_coefficient: 1.2e-3
  mixed_layer_depth_m: 50.0
  bottom_friction_m_s: <标定>       # Stommel R，主调参旋钮
  sst_advection_passes: 8
  sst_relaxation_rate: 0.1
  coastal_influence_km: 500.0
  upwelling_enabled: true
```

`currents_enabled: false` 时逐位回归旧输出（测试守卫 + 旧世界逃生门）。

### 3.3 引擎产物

| 产物 | 位置 | 用途 |
|------|------|------|
| 逐 cell 三分量字段 | cvt_mesh.json（回写） | 前端烘焙/流线积分、静态模式 |
| `ocean_currents.json`（新） | maps/{planet_id}/ | 命名洋流路径：折线 + 输运量 + 寒暖标志 + 可选名称；前端箭头带图层数据源 |
| `ocean_current_speed.png`（可选） | maps/{planet_id}/ | `export_equirectangular(field=...)` 零改动出图，视频素材 |
| climate_summary.yaml 追加段 | 层 derived | 盆地数、最大输运（Sv）、WBC/内部流速比、SST anomaly 统计 |

`ocean_currents.json` 需按 CLAUDE.md 三文件同步：`api_routes/maps.py`（新端点或
并入 `features`）+ `scripts/export_static.py` + `frontend/src/api/staticClient.ts`。

---

## 四、前端呈现方案（重点斟酌项）

### 4.1 设计依据：乐意 Ajax 的"双语言信任构建术"

帧级实证（`leyi-ajax-map-presentation-analysis.md` §二）：

| 画法 | 帧证据 | 视觉特征 | 我们的对应 |
|------|--------|----------|-----------|
| **教科书箭头带** | EP1 f_0312 | 粗弧形带 + 箭头端，**暖流品红 / 寒流青绿**，叠素净底图，配海名标签 | `bands` 模式（SVG overlay） |
| **科研流线场** | EP1 f_0336 | 细密流线 + 微型方向箭头，蓝紫渐变 | `streamlines` 模式（烘焙纹理） |

他相隔 24 秒先后使用两种画法——同一现象的两种视觉语言互为可信度背书。
我们做成**同一图层的两种渲染开关**（默认同开，即他"先箭头后流线"的叠态）。

### 4.2 技术路线（受 ANGLE bug 约束）

现行架构 = Three.js WebGLRenderer + **CPU 烘焙 DataTexture** + GPU 只做 vUv
采样的 4 槽合成 shader + SVG overlay（经纬网/悬停）；AMD ANGLE/D3D11 顶点属性
插值 bug 的规避策略是"一切颜色进 CPU 烘焙"。前端**无矢量箭头/粒子先例**。

| 模式 | 路线 | 理由 |
|------|------|------|
| `streamlines` | **CPU 烘焙进 DataTexture**：海洋上按流速加权播种 ~1-3k 种子点，RK2 沿逐 cell 流速积分（含经向环绕），逐段画线，透明度/蓝紫渐变 ∝ 流速 | 完全复用 layerBakes 既有管线（bakeCellLayer :329-355 同构），GPU 路径零新风险；10 万 cell 级矢量绝不上 SVG |
| `bands` | **SVG overlay**：消费 `ocean_currents.json` 的 top-N（≤16）命名路径，polyline + arrow marker，暖流品红/寒流青绿（色值按 sst_anomaly 符号），线宽 ∝ 输运，可挂竖排名称标签 | 数量少、要清晰缩放与标签——正是 MapSvgOverlay（经纬网/悬停）的既有能力域；标签能力为"碎门暖流"等剧情命名留口 |

- 图层注册：`ColorMode` + `'currents'`，kind=**feature**、group=**气候**
  （LAYER_GROUPS 气候组首个成员；koppen 帮助文案已预留"未来的洋流"措辞）。
  feature 槽当前仅 boundaries 一员——若多层 feature 共享合成槽，按其既有
  共烘焙机制并入；不合则加第 5 sampler（纯采样，ANGLE-safe）。
- 面板：沿用现状扁平列表加一行（`map-layer-panel-redesign` 未实施，不互为
  阻塞）；子模式开关（bands/streamlines 复选）放该行展开区。
- 3D Globe 自动受益（同一合成纹理贴球，GlobeViewerPage:178）。
- 静态模式：逐 cell 分量在 cvt_mesh.json（已导出）→ 流线烘焙纯客户端可行，
  零新增导出；`ocean_currents.json` 走三文件同步。

### 4.3 与"机构化包装"的衔接

箭头带 + 标签天然就是"学术图版"素材，后续导出模板（测绘署附件框，
`map-layer-refactor` 后续项）直接套。命名洋流（碎门暖流/双镜水道寒流…）
同时是 narrate 的词汇来源——`ocean_currents.json` 的 name 字段留给
geography.yaml 或独立 yaml 作者命名（本期仅预留字段，不实现命名配置）。

---

## 五、验证与测试

### 5.1 单元测试（新 `tests/test_map/test_ocean_circulation.py`，纯模块无 IO）

沿用合成带状网格 fixture 模式（test_climate_simulator `_build_test_mesh` 100 cell
+ validation 12×12）：

1. 风应力：量级与方向（τ ∝ |u|u）；
2. curl_z：合成纬向风带 → 副热带/副极地 curl 符号交替正确；
3. **理想化矩形盆地**（合成网格挖出方形海盆）：
   - ψ 海岸=0、无 NaN、确定性（两次求解逐位一致）；
   - 北半球副热带环流**反气旋**方向正确（符号约定错在这条测试现形）；
   - WBC 输运/内部输运 ≥ 2.5（西边界强化涌现的证据）；
   - 南半球符号翻转；赤道西向流（信风驱动）方向正确；
4. Ekman 诊断：已知风向下上升流指数符号正确；向量化后与旧逐 cell 实现数值一致；
5. SST 平流松弛：WBC 侧出现 +3~+8°C 极区方向暖异常、东边界 −2~−5°C 冷异常，
   异常包络断言（roadmap 数值）；`passes=0` → 逐位等于纬度剖面（退化守卫）；
6. 海峡：两盆地+狭窄道合成网格——输运 ∝ 截面积；面积→0 → 输运→0；
   ±11 m 水位摆动 → 输运脉动幅度与面积变化一致（呼吸潮最小验证，
   对应 heightmap §4.4 用例 3）。

### 5.2 集成测试（test_climate_simulator.py 扩展）

- `currents_enabled` 开：海洋 cell 洋流字段非 None 且有限；
- 关：**逐位回归**现状输出（回归守卫，保护既有世界）；
- 开 + 固定 seed：两次运行逐位一致（确定性）。

### 5.3 端到端验证

| 用例 | 指标 | 目标 |
|------|------|------|
| **earth/climate-dev 离线验证** | 温度 RMSE vs 观测 | 12.87°C → **<8°C**（roadmap M3） |
| gaia-m 形态目检 | 环流圈数目/尺度 | 慢自转预期：更少更大（不照搬地球五圈） |
| gaia-m §4.4 用例 1 | 海峡 150 m 深、海平面 0 → 流量 >0，两侧 SST 梯度被抹平 | 通过 |
| gaia-m §4.4 用例 2 | 海平面 −120 m → 通道关闭、两侧 SST 分异、全球均温偏移 | 通过 |
| 性能 | 100k cell 洋流阶段耗时 | < 60 s（整条气候管线现约 2 分钟量级） |

§4.4 用例 4（双稳态迟滞）需要非线性反馈（SST↔风↔流迭代），超出本期稳态
范围——验收降级为"几何双态（开/关）对应两种环流构型"，真迟滞登记 §十。

---

## 六、分阶段实施

| 阶段 | 内容 | 工作量 | 产出/闸门 |
|------|------|--------|-----------|
| **P0** | 纯计算模块 `map/ocean_circulation.py`（无 IO 无 RNG，遵循"纯计算模块分离"）：风应力、curl、流函数组装+求解、流速、Ekman 诊断、SST 松弛、海峡输运 + 全部 5.1 单测 | 3–4 天 | 单测全绿 |
| **P1** | 引擎集成：simulate_climate stage 2.5、VoronoiCell 字段、config 段（删 num_gyres）、回写清单、climate_summary 追加段 + 5.2 集成测试；`ekman_current_direction` 向量化并接线（climate-pipeline.md ⏳ → ✅） | 2–3 天 | build gaia-m 全绿、关闭开关逐位回归 |
| **P2** | 标定与验证：earth/climate-dev RMSE 调参（R、passes、λ）、gaia-m 形态目检 + 用例 1/2、`ocean_current_speed.png` 导出 | 2–3 天 | RMSE <8°C；gaia-m 用例通过 |
| **P3** | 海峡闸口精修（若 P0 的简化版不足以过用例 2）：盆地识别、海峡扫描、输运约束耦合；gaia-m 前导点褶皱山系钉 3–5 个浅峡 feature（geography.yaml 迭代） | 3–5 天 | §4.4 用例 1/2/3 |
| **P4** | 前端双语言图层：烘焙流线 + SVG 箭头带 + ColorMode/LAYER_HELP/helpContent + `ocean_currents.json` 端点三文件同步 + 静态站本地验证（CLAUDE.md 硬要求） | 4–5 天 | 静态站洋流图层可见、控制台无 404 |

总计 ~3 周。分支策略：`feat/ocean-currents` 单分支推进（P0-P4 强耦合），
完工直接合 main 推送（既定工作流，不走 PR）。

### 6.1 工作流注意

- 洋流只跑在**气候引擎**里：geological 引擎自 v0.16 起已跳过内联气候遍
  （geological.py stage 0.0a），无重复计算问题；重建命令 =
  `dreamulator build <world>`（或 `--only climate`）。
- earth/climate-dev 的 ETOPO1 真实高程**只跑气候不跑地质**（同 terrain-dev 教训）。

---

## 七、风险与对策

| 风险 | 对策 |
|------|------|
| 慢自转下 β 弱 → ψ 幅值过大/病态 | β 用 2Ωcosφ/a 全幅值；对 ψ 做物理上限幅（输运上限 ~100 Sv 量级截断并 warning）；标定阶段观察 gaia-m 实际环流尺度 |
| **curl_z(τ) 的梯度-分量方式**是"便宜但没在球面 CVT 上验证过"的新用法 | P0 单元测试用矩形盆地解析风场（curl_z 有闭合形式）验证数值误差 <5%；若不达则降级为 Stokes 线积分路径（但需要给 mesh 补边几何——约 +20% 工期，记作应急缓冲） |
| 图 Laplacian 均匀权重的边距比近似（l/d ≈ 常数）在剧烈非均匀 cell（如 pentagon）处失效 | CVT after Lloyd 的 cell 面积 CV <5%——近似有效；若 gaia-m 局部出现畸形 cell（pentagon 聚集在边界），**Laplacian 改用 1/(A_i×d_ij) 加权**（改动量：一个权重数组替换常数，稀疏装配同一 loop） |
| **球面图 Laplacian 的奇异性**（文献警告：graph Laplacian 在球面上 singular——零空间=常数函数） | **对本问题无影响**：每个盆地 ψ=0 Dirichlet 海岸边界消除了零空间；CG 在正定 + 固定边界条件下无条件收敛。验证：单测中各盆地求解后 ψ 不包含常数分量（海岸 zero 约束强制唯一解） |
| 符号约定错（南半球/赤道方向） | 5.1 第 3 组方向断言先行（实现前先写测试定符号）——环流反向的 bug 在单测立刻暴露 |
| SST↔风 无回耦合 → 修正被低估 | 已知限制入 climate-pipeline.md；Picard 迭代留开关位不实现 |
| 性能回退 | 稀疏 CG + 全 numpy 向量化；>60 s 触发预警则改分盆地并行（盆地天然解耦） |
| 前端 feature 槽机制不明 | P4 开工先读 useGPUTerrain/layerBakes 现行合成路径再定并层或加槽（两者都 ANGLE-safe） |
| **CG 不收敛 / 收敛到错解**（极端参数组合或慢自转+复杂盆地形状） | 有 §2.2.2 的启发式环流作为逃生出口（纯几何、零求解、半天原型验证）；若触发降级，则牺牲海峡输运定量精度（gaia-m §4.4 用例退回定性验收） |

---

## 八、文档同步清单（CLAUDE.md 硬要求）

1. `docs/knowledge/climatology/ocean_currents.md`：§5 引擎对应表填 ✅ + 源码引用；
   `CLAUDE.md` 索引行更新（ekman 状态）；
2. `docs/design/climate-pipeline.md`：stage 2.5 新章节、函数表、验证现状
   （RMSE 数字更新）、ekman ⏳→✅；
3. `docs/design/roadmap.md`：3A.3 子任务逐项勾销、M3 状态、P0 行；
   **登记新条目**（来自视频分析净增量）：洋流时变/翻转振荡（乐意 Ajax 机制）、
   气候年际-年代际变率模态；
4. `docs/design/geological-pipeline.md`：§8 指针 + :2280 checklist "实现简化洋流" 勾选；
5. `docs/worldbuilding/design_patterns.md`：ocean 配置段模式（yaml 示例 + 调参表）；
6. `frontend/src/components/map/helpContent.ts`：currents 图层帮助（记忆库规则）；
7. `CHANGELOG.md`：Added（洋流模型 + 前端双语言图层）/Changed（气候输出含洋流修正，
   `currents_enabled: false` 可回退）。

---

## 九、与既有计划的接口

- **heightmap 计划 §四**：本计划是其 P0 依赖"洋流模型"的落地；§4.4 验收用例
  1–3 纳入本期（P2/P3），用例 4（迟滞）降级登记；
- **map-layer-panel-redesign**（待实现）：currents 图层按气候组预注册，面板
  重构实施时直接归组，无冲突；
- **bilibili-video-plan**：第 3 期"呼吸的海洋"的图版素材（箭头带截图、流线场、
  开/关双态对比图）由 P4 直接供给。

---

## 十、不在本期范围（登记不实施）

| 项 | 原因 | 去向 |
|----|------|------|
| 时变洋流 / ENSO 式翻转振荡（乐意 Ajax "4 月–10 年不可预测"） | 需时间步进 + 非线性回耦合，是另一个系统 | roadmap 新条目（视频分析净增量 #1/#2） |
| 季风洋流季节反转（索马里型） | 依赖季节循环模块（3A.2 🚧） | 随 3A.2 |
| 热盐环流全解（Stommel 两盒盐度双稳态） | 本期只做几何闸口双态；盐度场不存在 | 远期 |
| 潮汐锁定永久昼夜的 SST 经度强迫 | 独立议题（climate-pipeline.md :265 次行星半球强迫方向） | 随温度精细化后续 |
| 海峡命名配置（碎门暖流等作者命名） | 字段已留，配置化随 gaia-m 剧情迭代 | P2 前导点褶皱山系精修时顺手 |
