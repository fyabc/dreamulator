# 流水侵蚀：stream power + 坡面扩散 + 地貌降水代理

> 实现：`src/dreamulator/map/erosion.py`（循环）、`map/precip_proxy.py`（代理）
> 设计：`docs/design/geological-pipeline.md` §10 · 验证：`scripts/validate_precip_proxy.py`
> 大尺度验收诊断：`scripts/diagnose_erosion.py`（§6）

地质层内部的地表演化循环（Phase 3B）：洼地填平 → D8 → 流量累积 → stream power
下切 + 坡面扩散，以**地貌降水代理**为强迫。不读气候引擎输出（气候是地质下游，
避免 DAG 环）。

算法由 `erosion_algorithm` 选择（当前仅 `stream_power`，保留扩展位）。**侵蚀精度由
`stream_power_dt_fraction` 旋钮控制**：小值（0.5）= 精确/慢，大值（~5）= 粗/快——
同一套物理、同一套参数，只差时间离散精度，大 dt 下结果更「糊」但总侵蚀量相近。

---

## 1. 河流下切（stream power law）

标准河道下切律（Howard 1994）：

```
E = K · Q^m · S^n
```

- `Q`：上游流量，用 `Q = P · A`（降水 × 汇水面积），归一化到大陆参考
  `Q_ref = precip_proxy_base_mm × 1e6 km²`（无量纲）。
- `S`：沿流向的坡降 `(h_i − h_j) / d_ij`（无量纲）。
- `m`/`n` 的选择有理论依据，见 §1.1。默认 `m = 0.5`、`n = 1`（单位流功率模型）。

### 1.1 m/n 指数选择（凹度指数）

关键约束是**比值 θ = m/n（凹度指数，concavity index）**：稳态下河流纵剖面满足
`S ∝ A^(−θ)`，自然河流 θ 经验值 **0.3–0.6**（Whipple & Tucker 1999；Lague 2014）。

两个标准组合（θ 都 ≈ 0.5）：

| 组合 | θ | 物理模型 | 依据 |
|------|---|---------|------|
| m=0.5, n=1 | 0.5 | 单位流功率（ω ∝ Q^0.5·S，因河宽 w ∝ Q^0.5） | Howard 1994 |
| m=1.0, n=2 | 0.5 | 剪应力（τ ∝ Q^0.5·S，E ∝ τ²） | 通用 |

- **m 控流量依赖**：m 越大，源头（低 Q）侵蚀越弱、主干（高 Q）越强；
- **n 控坡度依赖**：n 越大，陡坡（山峰）侵蚀越强。

**实现约束**：隐式三角精确解要求 **n=1**（n=1 时方程线性、每 cell 单一下游，
逆拓扑序一次遍历即精确解；Braun & Willett 2013）。动力学固定为
`E = K_eff · Q^m · S`（m 取 `stream_power_m`，nacrea 现用 0.7）；
`config.stream_power_n` **不进入动力学**，只用于分形 K/D 缩放的指数（§3）。
支持 n≠1 需迭代求解器（Fastscape 做法），属远期升级。

## 2. 坡面扩散（hillslope diffusion）

线性扩散律 `∂h/∂t = D ∇²h`，在图邻接上离散为图拉普拉斯：

```
lap(i) = Σ_j (h_j − h_i) / d_ij²    # 仅陆-陆边
```

作用等价于「热侵蚀/安息角」：坡面物质蠕移，把陡坡平滑掉。只作用坡面、不产生
河道，与 stream power 的河道下切互补。

## 3. 时间积分与分辨率无关（隐式格式，Fastscape 式）

`surface_evolution_time_myr` 是固定物理时长（0 = 禁用）；`dt = time /
stream_power_steps`（大、均匀，步数 ~20 与网格分辨率无关）。

**隐式格式**（Braun & Willett 2013），无条件稳定：

- **stream power 三角精确解**：n=1 时 `E = K·Q^m·S` 是线性的，且每个 cell 只有一个
  下游（流图是森林），按逆拓扑序（河口→源头）一次遍历即精确解；
- **坡面扩散 Jacobi**：小项（`D·dt/d² ≪ 1`），几次迭代收敛。

**分形 K / D 缩放**（消除坡度的分辨率依赖）：自然地形自仿射，坡度 `S ∝ Δx^(H−1)`、
曲率 `∇²h ∝ Δx^(H−2)`（H ≈ 0.5）。运行时按：

```
K_eff = K₀ · (Δx/reference_cell_km)^(n(1−H))    # 坡度补偿（stream power）
D_eff = D₀ · (Δx/reference_cell_km)^(2−H)       # 曲率补偿（坡面扩散）
```

自动换算，使输入的 `K₀`、`D₀` 都分辨率无关。**注意**：D 的标度（`Δx^(2−H)`，51 km 下
~364×）远强于 K（`Δx^(n(1−H))`，~19×），因为曲率比坡度对分辨率更敏感——所以坡面扩散
在粗网格上被大幅削弱，51 km 下即使调大 D 也很难磨平百公里级的河谷壁（那是区域尺度的
地貌，扩散只作用坡面尺度）。

## 3.1 亚网格河道宽度稀释（2026-08-25）

stream power 下切的是**河床**，不是整个 cell。自然河宽满足下游水力几何关系
`w = c_w · Q^0.5`（Q 单位 m³/s；Leopold & Maddock 1953，综合研究 c_w ≈ 3–10，
实现取 5）。cell 平均下切 = 河道下切 × 面积占比：

```
E_cell = E_channel · min(1, w / d)     # d = 沿流向的 cell 尺度
```

没有 `w/d` 因子时，D8 单流向把全部流量集中进单 cell 宽的细流，下切被高估 ~d/w
倍——51 km 网格上切出深达 1–2 km 的**网格级峡谷**（nacrea 实测：改前 5.5% 的
陆-陆相邻边高差 >500 m、最深单 cell 下切 −1927 m；改后深尾与陡边大幅下降）。
真实地球同分辨率无此特征（河谷宽度 1–20 km ≪ 51 km cell，见
`docs/design/competitor-analysis.md` §4.2.1 结论）。

**封堵坝 cell 豁免**：内流海封堵坝上的 cell 不做宽度稀释——海峡下切是沿鞍部
路径的集中缺口（notch）推进，缺口以全河道速率下切、切穿即海峡打开；若也按
w/d 稀释，cell 平均降到海平面所需时间被拉长 ~d/w 倍，远超物理缺口切穿时间。

## 3.2 海平面基准与内流海海侵缺口（2026-08-25）

下切过程中陆 cell 下限 clamp 到 `sea_level + 1 m`（不做一般性海侵）。两条
边界规则：

- **开洋海岸静止**：排入开阔海洋的陆 cell 不做基准面下切——无输沙极限的
   detachment-limited 律会让基准面沿河网上行、把全部低地夷平（nacrea 回归：
  放开后陆域平均剥蚀 97→155 m、Cfb −1069 cell，过度夷平）。海岸侵蚀属海洋
  过程（P2）。
- **内流海基准面下切**：排入**未连通外洋的海平面以下水体**（内流海）的陆
  cell 向海平面基准面下切（基准面 = 水面，不是水底——否则海岸 cell 会朝洋底
  深度失控下切）。封堵坝因此能被切到 clamp。

**缺口冲开（breach）**：侵蚀循环结束后跑一次海侵缺口通道——用 minimax
Dijkstra 从外洋算每个 cell 的「最低鞍部成本」（= priority flood 溢流水位，
Barnes et al. 2014 同源）；若某内流海的最低鞍部已被切到 `sea_level + 1 m`
（clamp）以内，则把该鞍部路径上所有残余陆 cell 降到 `sea_level − 5 m`
（新切开的海峡是浅的；5 m 只需保证「明确低于海平面」以建立水体连通，
后续加深属海洋过程）。这实现 roadmap §7 #7 的能力需求：**侵蚀能冲开被堵上
的浅海海峡**。验收测试：`tests/test_map/test_erosion.py::test_erosion_breaches_dammed_basin`。

## 4. 地貌降水代理（climate_coupling）

代理拆成**环流相关**与**环流无关**两部分，使**同一个代理适配任意环流体制**
（地球三圈、潮汐锁定单圈、任意 Hadley 边界）：

```
P(x) = P_base(lat; Ω, tilt, Hadley) · f_orog(x; U, ∇h)
```

### 4.1 纬向基础场（环流相关，`_zonal_base_precip`）

镜像气候引擎的纬向项（`climate_simulator.py` Step 3.5/6），复用同一批 config 旋钮：

- **ITCZ 对流峰**：以热赤道为中心的高斯，宽度 `σ = max(hadley × 0.35, 5°)`——
  单圈（H=90°）~31°、三圈（H=30°）~10.5°，随 Hadley 扩展自动变宽；
- **副热带抑制**：Hadley 边界处的干带，`σ = 2.5 / sin(H)`（罗斯贝变形半径标度）、
  幅度 0.6——单圈时收缩到极点；
- **风暴路径**：中纬高斯（仅 `storm_track_amplitude_mm > 0` 的多圈世界，单圈关闭）。

### 4.2 地形响应（环流无关，`_orographic_factor`）

线性 upslope 模型：`w = U · ∇h`（纬向风 `hadley_cell_wind` 被地形抬升/下沉），
`f = clip(1 + eff·w, 0.5, 1.5)`——迎风坡湿、背风坡干。这是
Smith & Barstad (2004) 线性地形降水模型的**零平流极限**；完整的傅里叶传递函数
（凝结水顺风平流）留后续。

### 4.3 验证

`scripts/validate_precip_proxy.py` 把代理与气候引擎的权威降水（`precipitation_mm`，
全量构建后回写进 `cvt_mesh.json`）做陆地逐 cell 对比。nacrea 实测
**`corr_log = 0.761`**（形状对、幅度标定问题）；残余偏差是陆地降水 ~2× 高于纬向
均值（气候引擎 BFS 把海洋水汽集中搬运到陆地，纬向基础场无法捕获），归 M3 标定。

## 5. 参数表

| 参数 | 默认 | 范围 | 物理含义 |
|------|------|------|----------|
| `erosion_algorithm` | `"none"` | none / stream_power | 侵蚀算法（当前仅 stream_power，保留扩展位） |
| `surface_evolution_time_myr` | 0 | 0–1000 | 侵蚀总时长（Myr；0=禁用，分辨率无关） |
| `stream_power_steps` | 20 | 1–200 | 隐式格式的均匀大步数（dt = time/steps） |
| `climate_coupling` | `"proxy"` | none/proxy/full | 降水强迫源 |
| `fluvial_erodibility` | 1.4e-3 | 1e-4–1e-2 | 参考分辨率下的侵蚀系数 K₀（m/yr） |
| `reference_cell_km` | 1.0 | — | K 缩放的参考分辨率（km） |
| `terrain_hurst_exponent` | 0.5 | 0.3–0.7 | 地形 Hurst 指数 H（坡度 S ∝ Δx^(H−1)） |
| `stream_power_m` / `_n` | 0.5 / 1.0 | — | 流量/坡降指数（θ=m/n≈0.5，见 §1.1） |
| `hillslope_diffusivity` | 1e-5 | 1e-6–1e-3 | 坡面扩散 D₀（m²/yr @ 1km，分形缩放） |
| `precip_proxy_base_mm` | 2000 | 100–4000 | 代理 ITCZ 峰振幅（≈ evaporation_base） |
| `sediment_routing` | `"bagnold"` | none / bagnold | 沉积路由（§5.5；none = 只下切、物质丢失） |
| `sediment_transport_efficiency` | 0.05 | 0.01–0.1 | Bagnold 输沙效率 ε（无量纲，Bagnold 1966） |

## 5.5 沉积物搬运与沉积（Bagnold 输沙能力，2026-08-26）

`sediment_routing: "bagnold"`（默认；`"none"` 为只下切的旧行为）。每个侵蚀子步
结束后跑一次 **source-to-sink 质量守恒路由**（实现 `_route_sediment`）：

1. **供给**：本子步降低的体积 `max(0, h_prev − h)·area` 成为泥沙载荷；
2. **输沙能力**（Bagnold 1966）：`cap = ε·(ρw/ρs)·Q·S·dt`——流水搬运泥沙的
   功率上限。ε 为 Bagnold 效率（文献 ~0.01–0.1，默认 0.05）；ρw/ρs =
   1000/2650。载荷超过能力就地沉积，其余传向下游；
3. **汇**：载荷到达水体 cell（外洋/内流海）全部沉积——**三角洲前积/陆架建造/
   湖泊充填**；
4. **封堵坝豁免**：坝路径上的 cell 不沉积（与宽度稀释豁免同理——缺口是亚网格
   的，溢流水道把泥沙带往外洋而非就地淤积），否则坝会被自己流域的供给淤埋、
   永远切不穿（§3.2 缺口机制失效）。

**与下切的关系**：不做额外床沙卷入（entrainment）——下切已由 stream power 步
完成，路由步只搬运其产物，避免双重侵蚀。坡面扩散的质量不严格守恒（加权方案，
小项），泥沙收支以此为已知近似。

**物理检验**：输沙能力 ∝ Q·S·dt，干流上能力巨大（远超供给）——泥沙几乎只在
S→0 处沉积（盆地底部、湖盆、海岸基准面），与真实「供给受限河流把泥沙送到
基准面」的行为一致。

## 6. 大尺度验收诊断与 nacrea 基线（2026-08-25，Phase 3B P0）

`scripts/diagnose_erosion.py <map_dir> [--time-myr N]`：从已构建网格读侵蚀产物，
输出大尺度验收指标（侵蚀量分布/总侵蚀体积/剥蚀速率、侵蚀前后高程分位与起伏度、
坡度统计、汇水面积分位与河网密度）。**验收哲学**（竞品分析 §4.2.1 结论）：
51 km 网格上侵蚀的合法产物是大尺度地貌改造与物质再分配，不是可见河谷；
河网可见性由河流矢量图层 + Gaea 局部精细化承担。

**nacrea 基线**（200k，seed 42，当前配置 K₀=1e-3、m=0.7、100 Myr、20 步，
含 §3.1 宽度稀释 + §3.2 基准面/缺口机制）：

| 指标 | 数值 | 判读 |
|------|------|------|
| 陆域平均剥蚀 | 2.0 m / 100 Myr = 2e-5 mm/yr | 比地球大陆均值（0.03–0.07 mm/yr，含构造供给）低 ~3 个数量级 |
| 最深单 cell 下切 | −1010 m | 主干峡谷深尾；无宽度稀释时约 −1900 m |
| 被侵蚀陆域占比 | 59.5%（中位仅 −0.5 m） | 下切集中在汇水 ≥20×cell 的 ~8% 陆域 |
| 起伏度 p95−p50 | 1223 → 1223 m | 大尺度地貌基本未动 |
| 气候回归（vs 侵蚀前地形构建） | T −0.17 °C、P −14 mm、Af −2137 cell | 高程微调的气候响应，量级可接受 |

**标定判断**：当前配置下侵蚀近乎休眠（2 m/100 Myr），不是过度下切。注意：
2026-08-22 同步进 `data/worlds` 的网格（平均剥蚀 97.6 m、最深 −1927 m）是
旧参数集的产物（历史已 squash，具体参数不可考）——下次发版重建会明显变弱。
**激进标定（向地球剥蚀速率靠拢）应先落地沉积物搬运（今日待办 #5-P1）**：
当前只下切不沉积、质量不守恒，单独调大 K₀ 只会放大物质丢失；先有
transport-limited 段与盆地充填，再按地球剥蚀率锚定 K₀。

## 参考

- Howard, A. D. (1994). A detachment-limited model of drainage basin evolution.
  *Water Resources Research*, 30(7), 2261–2285.
- Braun, J., & Willett, S. D. (2013). A very efficient O(n), implicit and parallel
  method to solve the stream power equation. *Geomorphology*, 180–181, 170–179.
- Smith, R. B., & Barstad, I. (2004). A linear theory of orographic precipitation.
  *Journal of the Atmospheric Sciences*, 61(12), 1377–1391.
- Leopold, L. B., & Maddock, T. Jr. (1953). The hydraulic geometry of stream
  channels and some physiographic implications. *USGS Professional Paper* 252.
  （下游水力几何 `w ∝ Q^0.5`，§3.1 宽度稀释的来源；系数综合研究范围 3–10）
- Barnes, R., Lehman, C., Mulla, D., & Dowling, R. (2014). Priority-flood: An
  optimal depression-filling and watershed-labeling algorithm for digital
  elevation models. *Computers & Geosciences*, 62, 117–127.（§3.2 minimax
  鞍部成本即 priority-flood 溢流水位视角）
- Fastscape/Landlab：侵蚀模型把降水作为外部场 `water__unit_flux_in` →
  `surface_water__discharge` → stream power（本代理采用同一「代理场 → 流量 → 下切」
  架构）。
