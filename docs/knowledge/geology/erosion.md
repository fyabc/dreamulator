# 流水侵蚀：stream power + 坡面扩散 + 地貌降水代理

> 实现：`src/dreamulator/map/erosion.py`（循环）、`map/precip_proxy.py`（代理）
> 设计：`docs/design/geological-pipeline.md` §10 · 验证：`scripts/validate_precip_proxy.py`

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
- **n 控坡度依赖**：n 越大，陡坡（山峰）侵蚀越强；
- 折中 `m=0.75, n=1.5`（θ=0.5）是「源头少被切、主干主导」的常见取法（nacrea 采用）。

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
地貌，扩散只作用坡面尺度）。更新后陆 cell 下限 clamp 到 `sea_level + 1 m`（v1 不做海侵）。

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

## 参考

- Howard, A. D. (1994). A detachment-limited model of drainage basin evolution.
  *Water Resources Research*, 30(7), 2261–2285.
- Braun, J., & Willett, S. D. (2013). A very efficient O(n), implicit and parallel
  method to solve the stream power equation. *Geomorphology*, 180–181, 170–179.
- Smith, R. B., & Barstad, I. (2004). A linear theory of orographic precipitation.
  *Journal of the Atmospheric Sciences*, 61(12), 1377–1391.
- Fastscape/Landlab：侵蚀模型把降水作为外部场 `water__unit_flux_in` →
  `surface_water__discharge` → stream power（本代理采用同一「代理场 → 流量 → 下切」
  架构）。
