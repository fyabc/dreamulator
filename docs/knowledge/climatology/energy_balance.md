# 能量平衡模型 (Energy Balance Model)

> 本文档描述 dreamulator 气候引擎（Phase 3A）的大气能量平衡模型与降水物理。
> 对应源码：`src/dreamulator/engine/climate_physics.py`、`climate_seasonality.py`、
> `src/dreamulator/map/climate_simulator.py`。

---

## 1. 恒星辐射与平衡温度

### 核心公式

行星在没有大气情况下的黑体平衡温度：

$$T_{eq} = \left(\frac{L_*}{16\pi\sigma d^2}\right)^{1/4}$$

其中：
- $L_*$：恒星光度（W）。$L_\odot = 3.828 \times 10^{26}$ W
- $d$：行星轨道半长轴（m）。1 AU = $1.496 \times 10^{11}$ m
- $\sigma$：Stefan-Boltzmann 常数 = $5.670374419 \times 10^{-8}$ W/m²/K⁴
- 因子 $1/16$ 来自：球面积分（$1/4$）+ 截面比（$1/4$）

### 地球参考值

| 参数 | 值 |
|------|-----|
| Bond 反照率 | 0.306 |
| 平衡温度 | 254.6 K（−18.6 °C） |
| 地表实际平均温度 | 288 K（+15 °C） |
| 温室增温 | +33 K |

### 对应源码

```python
dreamulator.engine.climate_physics.equilibrium_temperature(
    stellar_luminosity_sol, orbital_distance_au, albedo
) -> float  # Kelvin
```

---

## 2. 温室效应

$$T_{surface} = T_{eq} + \Delta T_{greenhouse}$$

地球 $\Delta T_{greenhouse} \approx 33$ K（H₂O、CO₂、CH₄）。对不同大气成分：

$$\Delta T_{greenhouse} \approx 33 \times \frac{P_{atm}}{P_\oplus} \times f_{comp}$$

### 对应源码

```python
dreamulator.engine.climate_physics.surface_temperature(teq_kelvin, greenhouse_warming_K) -> float
```

---

## 3. 1D 能量平衡模型（经向温度分布）

### 核心公式

纬向平均温度 $T(\phi)$ 由稳态 1D 能量平衡模型（North 1975；Budyko 1969；climlab `EBM`）给出：

$$0 = D\,\frac{d}{dx}\Big[(1-x^2)\frac{dT}{dx}\Big] + Q(x)(1-\alpha) - (A + B\,T),\quad x=\sin\phi$$

- $Q(x)$：年均辐照（由 `monthly_insolation` 12 个月平均，随倾角/轨道变化）；
- $D$：经向扩散系数（W/m²/K，代表大气+海洋极向热输送）；
- $(A+BT)$：线性 OLR（Budyko 1969 出射长波辐射），$B$ 为辐射阻尼；
- $A$ 不是自由旋钮——内部标定使 $T_0$（Legendre n=0 模 = 面积加权全球均温）
  精确等于 `equilibrium_temperature` + `surface_temperature` 链给出的全球均温。

### Legendre 谱解法

Legendre 多项式 $P_n(x)$ 是扩散算子的本征函数（本征值 $-n(n+1)$），方程按模解耦：

$$T_n = \frac{Q_n(1-\alpha) - A\,\delta_{n0}}{B + D\,n(n+1)}$$

$Q_n$ 是吸收短波辐射 $Q(x)(1-\alpha)$ 的第 $n$ 阶 Legendre 系数。截断阶 $n_{legendre}=8$。

### 参数

| 参数 | 默认 | 含义 |
|------|------|------|
| `ebm_olr_b_wm2k` | 2.0 | 线性 OLR 系数 $B$（W/m²/K，Budyko 1969 物理量） |
| `ebm_diffusion_wm2k` | 0.35 | 经向扩散 $D$（W/m²/K，总输送 = 大气+海洋），Earth ΔT≈41°C 标定 |
| `ebm_diffusion_land_wm2k` | 0.2 | 陆地专用 $D$（仅大气输送，见 §4 大陆度） |

$D$ 由 caller 按自转标度：$D(\Omega) = D_\oplus \times P_{rot}^{0.3}$（Kaspi & Showman 2015
$\Delta T \propto \Omega^{0.3}$ 的等价形式——慢自转 → 更大 D → 更平的剖面）。稳态解自然
产生「输送压平」的副热带高原，对任意倾角/轨道自动适配。

### 对应源码

```python
dreamulator.engine.climate_seasonality.solve_1d_ebm_temperature(
    lat_rad, t_global_mean_c, *, albedo, obliquity_deg, solar_constant,
    orbital_period_days, eccentricity, perihelion_day, olr_b_wm2k, diffusion_wm2k,
) -> np.ndarray  # 纬向平均温度 °C
```

---

## 4. 大陆度（海陆温度对比）

1D EBM 给的是**纬向平均**温度，海陆同温。但陆地没有洋流输送，只有大气输送，所以
陆地温度更贴本地辐射平衡：**副热带更暖（BWh 保热）、极地更冷**。

### 物理

洋流承担地球极向热输送的 ~30–40%，陆地只看到大气 ~60%。故陆地用更小的扩散：

$$D_{land} \approx 0.6\,D_{total}$$

在 `simulate_climate` 中，1D EBM 用 `ebm_diffusion_land_wm2k`（默认 0.2）解陆地温度
（海洋随后被 `_ocean_surface_temperature` 覆盖），从而自然产生年均海陆对比。

### 效果（Earth climate-dev）

- 副热带陆地年均温回升 → `BWh→BWk`（热荒漠翻冷荒漠）从 3492 → 2284；
- 温度纬向 bias +2.6 → +1.5 °C。

### 对应源码

```python
# climate_simulator.py Stage 1
d_scaled = config.ebm_diffusion_land_wm2k * (config.rotation_period_days ** 0.3)
t_mean_C = solve_1d_ebm_temperature(lat_rad, t_surf_C, ..., diffusion_wm2k=d_scaled)
```

---

## 4.5 副热带下沉增温（Held-Hou 等面积均质化）

扩散 EBM 的经向输送是**纯下坡扩散**——把副热带（暖）的热量往极地扩散，所以副热带被
过度冷却（撒哈拉 21°C vs 观测 27–28°C），赤道则相对过暖（EBM 赤道 ~31°C vs 观测 ~26°C）。
但真实的 Hadley 环流在副热带是**下沉增温**（绝热压缩），翻转环流把热带-副热带均质化到
接近等温（Held & Hou 1980 的「等面积」约束：环流内的动力学温度 ≈ 该环流辐射平衡温度的
面积加权平均）。

`climate_simulator` Stage 1 在 EBM 陆地温度后、海洋 SST 覆盖前，把 Hadley 环流内
（|lat| < `hadley_extent_deg`）的陆地年均温松弛向该环流的**面积加权平均温度**
`t_cell = ⟨T·cosφ⟩/⟨cosφ⟩`，在环流边缘 ~8° 平滑过渡到 EBM。赤道降温、副热带增温一并
发生，均质化值对地球约 27.5°C（EBM 赤道 30.8°C 与 25°N 22.3°C 的等面积折中）。仅陆地
（海洋已由 SST 剖面覆盖）；`subsidence_warming_c=1.0`（0 关）。

参数与源码：

| 参数 | 默认 | 含义 |
|------|------|------|
| `subsidence_warming_c` | 1.0 | 均质化强度（1.0 = 完全等面积均质化，0 = 关） |

```python
# climate_simulator.py Stage 1（EBM 后、海洋 SST 前）
t_cell = np.average(t_mean_C[|lat| < φ_h], weights=cos(lat))  # 等面积均质化目标
t_mean_C[land] += subsidence_warming_c · w(|lat|) · (t_cell − t_mean_C[land])
```

参考：Held, I. M., & Hou, A. Y. (1980). *Nonlinear axially symmetric circulations in a
nearly inviscid atmosphere*. JAS 37, 515–533。

## 4.6 下沉增温的干燥度门控（4.2-①）

下沉增温物理上只属于哈得来胞的**干燥下沉支**：绝热压缩增温发生在副热带高压的下沉空气柱，
干地表无蒸发冷却，净增温全部体现在地表。湿润副热带边缘（季风海岸、Cfa 湿缘）年平下沉被
湿对流与蒸发冷却抵消，地表温度由局地辐射-平流平衡设定，不接受这份增温。§4.5 的均质化
增量因此在 Stage 1 存档（`_dt_subsidence`），Stage 3 降水落地后按干燥度**释放**（撤销）
湿润格的份额——温度步在降水之前，干燥度只能事后判定，这是 T↔P 双向耦合的单趟特例
（完整定点迭代见 `design/proposals/climate-steady-coupling.md`）。

门控三个维度（全部结点取自既有分类边界，无新调参）：

1. **只门控正增量**。增量为负处（赤道附近，均质化把过暖的赤道拉向胞均值）是**上升支**
   湿对流均质化、不是下沉增温，无论干湿一律保留。
2. **双干燥度指标取保守并集**（keep = max(keep_K, keep_AI)，两指标都说湿润才释放）：
   - **Köppen 干旱比** `r = P / max(20·T + offset, 1)`（offset 280/140/0 按暖冷半季
     集中度，Köppen 1936 / Kottek et al. 2006）：r ≤ 0.5（BW）全保留、r ≥ 1（湿润）
     全释放、BS 线性过渡。
   - **UNEP 干旱度指数** `AI = P / PET`，PET 用 Hamon (1961) 温度法：
     `PET_day = 29.8 · N_h · e_s(T) / T_K`（mm/day；e_s = 0.6108·exp(17.27T/(T+237.3)) kPa，
     Magnus；N 取 12 h——年均昼长处处 12 h，门控只作用于 |lat| ≲ 38°，季节 N×T 协变
     贡献 <5%）。年累计取 days_per_month = 365.25/12（**参考年基**）——AI 的分子
     （P，参考年率）与分母因此同窗，任何年长的世界都成立（时间基准约定见
     `climate-pipeline.md` §1）。参考值：20°C → ~2.86 mm/day ≈ 1045 mm/yr；
     27°C → ~1550 mm/yr。
     UNEP (1992) 分类：极旱 <0.05、干旱 0.05–0.2、半干旱 0.2–0.5、干半湿润 0.5–0.65、
     湿润 >0.65；keep 结点取 0.5 / 0.65（半干旱上界与湿润下界）。
   - **为什么需要 AI 第二判据**：引擎降水在**热下沉海岸系统性过湿**（下沉干燥缺参数化；
     波斯湾 modP ~475 vs obs ~175、撒哈拉西洋岸 391 vs 76、红海 454 vs 22）。单用
     Köppen r 会把这些真沙漠误判湿润、错误释放增温（格点级 −14°C）。AI 的分母 PET 随
     温度指数增长（Clausius-Clapeyron），27°C 下 PET ~1550 mm，P 过湿 3× 仍落在半干旱
     类——对模型降水误差鲁棒。
3. **高地豁免**（≥1500 m 不释放）。增量定义在海平面折算温度上、物理参照物是下沉支
   边界层，副热带边界层顶 ~850 hPa ≈ 1.5 km（标准大气）；更高地表与该层解耦（高原
   自身辐射平衡），且高地温度处理是独立登记项，门控不得暗中重调。

释放为**逐月均匀平移**（只作用月度序列；年温与 t_cold/t_hot 由终聚合
t_mean = ⟨t_monthly⟩ 重新导出——单一温度权威），季节振幅与暖冷半季月份排序不变。
单趟近似：Stage 2-3 消费的是释放前温度。

源码：`climate_physics.py` 纯函数 `dryness_offset_mm` / `dryness_threshold_mm` /
`potential_evapotranspiration_hamon` / `aridity_index_keep` / `subsidence_aridity_gate`
（`koppen_classify` 的 B 群阈值改调同一来源，单一事实源）；`climate_simulator.py`
Stage 1 存档 + Stage 3.5 释放。

参考：Hamon (1961) *Estimating potential evapotranspiration*, Proc. ASCE 87(HY3)
（公式形式另见 USGS HEC-HMS Hamon Method 文档：`ETo = c·(N/12)·ρ_sat`，c = 0.165 mm
per g/m³，与 29.8·N_h·e_s/T_K 恒等）；UNEP (1992) *World Atlas of Desertification*
（AI 分类）；Kottek et al. (2006) *Meteorologische Zeitschrift*（Köppen 阈值 offset）。

---

## 5. 海拔递减率

### 湿绝热递减率

$$T(h) = T_{surface} - \Gamma \times h$$

$\Gamma \approx 6.5$ °C/km（湿绝热递减率，地球平均）。

| 递减率类型 | 值 (°C/km) | 条件 |
|-----------|-----------|------|
| 干绝热 | 9.8 | 未饱和空气 |
| 湿绝热 | 4–7（典型 6.5） | 饱和空气（云内） |

### 温度依赖性

$$\Gamma(T) = \Gamma_{min} + (\Gamma_{max} - \Gamma_{min}) \cdot \sigma\!\left(\frac{T_{mid} - T}{T_{width}}\right)$$

暖（湿）极限 $\Gamma_{min} = 4.5$、冷（干）极限 $\Gamma_{max} = 6.5$ °C/km，logistic 过渡
$T_{mid} = 10$ °C、宽度 $T_{width} = 8$ °C，构造上有界于 $[\Gamma_{min}, \Gamma_{max}]$：

| T (°C) | 30 | 20 | 10 | 0 | −10 | −20 |
|--------|-----|-----|-----|-----|------|------|
| Γ (°C/km) | 4.65 | 4.95 | 5.5 | 6.05 | 6.35 | 6.45 |

暖空气含水汽多，凝结潜热减缓冷却 → 直减率更低。台站隐含有效地表递减率**按温度分裂而非
纬度**（2026-09-11 高地诊断，earth climate-dev）：热带高地 4.2–5.2（基多 4.5、库斯科 4.2、
亚的斯亚贝巴 4.4、阿尔蒂普拉诺 4.6–4.8），中高纬 ~6+。$\Gamma(T)$ 默认启用
（`variable_lapse_rate: true`），取代常数 6.5 与旧副热带硬纬度带（[15°, 35°] 边界在
青藏/安第斯/落基打出人工台阶线，且两个锚值 1.5/6.5 都与隐含值不符）。

### 对应源码

```python
dreamulator.engine.climate_physics.altitude_lapse_rate(temperature_c, elevation_m, lapse_rate_c_km)
dreamulator.engine.climate_physics.moist_lapse_rate(temperature_c)
```

---

## 6. 季节能量平衡模型

### 太阳赤纬

$$\delta = \arcsin(\sin\varepsilon \cdot \sin\nu)$$

$\varepsilon$ 为有效轴倾角，$\nu$ 为真近点角（圆轨道 $\nu = 2\pi d/P_{orb}$，偏心轨道加一阶
equation-of-center）。圆轨道下 $d=P/4$ 时 $\delta=+\varepsilon$（北半球夏至）。

### 日平均辐照

$$Q(\phi, \delta) = \frac{S_0}{\pi}\big[H_0 \sin\phi\sin\delta + \cos\phi\cos\delta\sin H_0\big]$$

日落时角 $H_0 = \arccos(-\tan\phi\tan\delta)$，极昼 $H_0=\pi$、极夜 $H_0=0$（Hartmann 2016 eq. 3.7）。

### 季节温度振幅（显式热输送）

季节振幅是季节 EBM（North & Coakley 1979；Budyko 1969）的周期解：

$$T_{amp} = \frac{\Delta Q_\omega(1-\alpha)}{\sqrt{B_{eff}^2 + (\omega C)^2}}$$

- $\Delta Q_\omega$：日平均辐照的年频率 Fourier 振幅（绝对量 W/m²）；
- $\omega = 2\pi/P_{orb}$：季节频率；
- $C$：下垫面热容量（J/m²/K，海陆差见下）；
- $B_{eff} = B + 6D$：**显式热输送的有效阻尼**——取季节信号主导的四极模 $n=2$，
  阻尼为 $B_{rad} + D\,n(n+1) = B + 6D$。这是与年平 1D EBM **同一个 D** 的显式经向
  热输送，取代旧版标定常数 `damping_b=10`（它把中纬的强涡旋阻尼错误套到极地，过度
  压扁了极地季节振幅）。

地球 $B_{eff} = 2 + 6\times0.35 = 4.1$ W/m²/K（旧值 10），极地季节振幅约大 2×，
夏季（t_hot）正确回暖越过 10°C/0°C 线。

### 季节冰反照率反馈

季节反照率随月度温度阈值切换（固定点迭代 3 次）：

$$\alpha(T_{summer}) = \begin{cases} \alpha_{ice} & T_{summer} < T_{freeze}\\ \alpha_{land} & T_{summer} \ge T_{freeze} \end{cases}$$

- **副极地（Dfc，60°N）**：夏季融雪 → 反照率降 → 表面变暗 → 更暖；
- **冰盖（EF，80°N）**：夏季仍冻结 → 反照率维持高 → 反射太阳 → 仍冷。

这是区分 Dfc 与 EF 的本质（ice-albedo 双稳态）。不冻 cell 的季节振幅按
$(1-\alpha_{ice})/(1-\alpha_{land})$ 缩小。

### 光谱冰反照率（恒星光谱依赖）

冰/雪在可见光（λ ≲ 1.1 µm）高反照、近红外（λ > 1.1 µm）强吸收，所以有效冰反照率
取决于宿主恒星光谱（Shields et al. 2012, *Astrobiology* 12:1023）：太阳型星能量集中在
可见 → 高冰反照（雪 0.8、冰 0.5）；M 矮星能量集中在红外 → 低冰反照（雪 0.6→0.47、
冰 0.3→0.24），从而**抑制 M 矮星的冰反照率反馈**、拓宽宜居带。

$$α_{ice}(T_{eff}) = \frac{\int α(λ)\,B_λ(T_{eff})\,dλ}{\int B_λ(T_{eff})\,dλ}$$

本项目用**两段式简化**（非 Shields 逐字公式——原文用实测光谱反照率曲线 + 非普朗克
M 矮谱）：

$$α_{eff} = α_{vis}\,f_{vis} + α_{nir}\,(1-f_{vis})$$

- $α_{vis}$ = `ice_albedo_surface`（默认 0.7，太阳谱下雪/冰反照）；
- $α_{nir}$ = 0.2（近红外冰反照，代码 `_ICE_NIR_ALBEDO`）；
- $f_{vis}$ = 黑体谱 λ < 1.1 µm 能量占比（不完全普朗克积分 `_blackbody_fraction_below`）。

归一化使太阳（5772 K）精确返回 `ice_albedo_surface`（地球行为不变）：

| 恒星 | T_eff | α_ice_eff |
|------|:---:|:---:|
| 太阳 | 5772 K | 0.700 |
| nacrea M1 | 3930.8 K | 0.563 |
| 3300 K 黑体 | 3300 K | 0.486 |

`stellar_temperature_k`（默认 5772）从天文层 `stellar_derived.yaml` 的 `computed_temperature`
注入，是推导量而非自由旋钮。源码 `climate_physics.spectral_ice_albedo`。

### 海陆热容量差（海洋性 vs 大陆性）

海洋混合层热容量大（$\rho_w c_p H_{ml} \approx 2\times10^8$ J/m²/K），陆地+大气
$\approx 2\times10^7$。热容量随距海岸距离指数插值（`seasonal_heat_capacity`，~500 km
e-folding）。这决定 C（海洋性）vs D（大陆性）分野——伦敦 Cfb vs 温尼伯 Dfb 相差 ~27°C。

### 内湖热容量（淡水湖，介于海陆之间）

大型内湖（里海/五大湖/程序化世界的内流海，`is_lake=True` 且 `water_class="ocean"`）
不是海洋混合层：它们是**大陆性水体**，表面温度与上空大陆空气平衡，且淡水在 0°C 封冻。
处理分两档（`climate_simulator.py` Stage 1）：

- **季节性冰湖**（年均陆地温度 T≥0）：表面温度取陆地 EBM 温度（而非开洋 SST 剖面），
  热容量 `seasonal_lake_heat_capacity = 4×10⁷` J/m²/K（≈ ρ_w·c_p·10 m 季节性温跃层，
  介于陆地 2×10⁷ 与海洋 2×10⁸ 之间），月度温度再钳制 ≥0°C（淡水冰点，物理常数非地球标定）。
  五大湖实测：冬季 0°C（观测 ~1°C）、夏季 ~19°C（观测 ~20°C）。
- **永久冰湖**（年均 T<0，如 nacrea 78–80°N 内流海）：保留海冰面剖面（`_ocean_surface_temperature`
  的冰分支已正确），因为封冻湖表面即冰面。

### 方向性海洋调节（东西向海陆不对称，4.1-B）

季节 EBM 的辐射余弦在深内陆给出 ~2× 观测振幅（莫斯科冬 −25 vs 观测 −9），因为缺**东西向**
海洋调节——盛行西风把海洋的小振幅季节循环送进内陆。修法是**方向性海洋调节**，双孪生分工
（`maritime_advection_scale_km`）：**年平版**（Stage 1，带冰门）把陆地年温向上风向海洋 SST
弛豫，定年水平；**月度版**（`simulate_climate` Stage 2 后）为**距平式**——只把陆地季节距平
向上风向海洋的距平阻尼，年均水平严格不变（水平弛豫会与年平版双重计费）：

```
A_land[m] ← (1−w)·A_land[m] + w·A_ocean[m],   w = exp(−dist_upwind / L)
A[m] = t[m] − ⟨t⟩（季节距平；⟨⟩ = 年均，两条距平序列年均皆为零 ⇒ 保均值）
```

- `dist_upwind`：沿**物理风**（`east_north_basis` 约定，与前端 `wind_east_m_s` 一致；原始
  `hadley_cell_wind` 的 `east = north × r̂` 指向物理西，需翻转 east 分量）逆推的上风向离岸距离；
- L = 1500 km 海洋气团 e 折长度；
- **振幅阻尼自然涌现**：海洋季节距平远小于陆地（海洋热容量大），阻尼把陆地过负的冬距平与
  过正的夏距平同时压向海洋形状——冬暖、夏凉、年均不变；深内陆与高地过大的季节振幅同向受益。
- 遗留（§7 冬季季风）：annual 西风带把哈尔滨逆推到暖渤海 → 误暖 +12.5，真实冬季应由西伯利亚
  冷高压外流主导，待技术债 24 修方向。

### 对应源码

```python
dreamulator.engine.climate_seasonality.monthly_temperature(
    q_monthly, t_mean_c, heat_capacity, *, olr_b_wm2k, diffusion_wm2k,
    orbital_period_days, albedo, ice_albedo, ice_threshold_c, ice_albedo_feedback,
) -> np.ndarray  # (N, 12) 月度温度 °C

dreamulator.engine.climate_seasonality.compute_seasonal_climate(...)  # 高层入口
```

### 可调参数

| 参数 | 默认 | 含义 |
|------|------|------|
| `ebm_olr_b_wm2k` | 2.0 | 辐射阻尼 $B_{rad}$（W/m²/K，与年平 EBM 共用） |
| `ebm_diffusion_wm2k` | 0.35 | 经向扩散 $D$（与年平 EBM 共用） |
| `seasonal_land_heat_capacity` | 2.0e7 | 陆地+大气热容量 $C_{land}$（J/m²/K） |
| `seasonal_ocean_heat_capacity` | 2.0e8 | 海洋混合层热容量 $C_{ocean}$（J/m²/K） |
| `seasonal_lake_heat_capacity` | 4.0e7 | 内湖季节性温跃层热容量 $C_{lake}$（J/m²/K，~10 m） |
| `seasonal_coastal_scale_km` | 500.0 | 海洋调节 e-folding 长度（km） |
| `maritime_advection_scale_km` | 1500.0 | 方向性海洋调节 e-folding 长度（km，0 关闭） |
| `seasonal_ice_albedo` | true | 季节冰反照率反馈开关 |
| `ice_albedo_surface` | 0.7 | 雪/冰反照率（太阳谱下；其他恒星按 `spectral_ice_albedo` 光谱加权） |
| `seasonal_ice_threshold_c` | 0.0 | 夏季温度低于此值视为冻结（°C） |

---

## 7. 行星参数的影响

### 反照率

- 冰雪覆盖 → 高反照率（0.6–0.9）→ 更冷 → 更多冰雪（正反馈）
- 海洋 → 低反照率（0.06–0.10）→ 吸收更多热量
- 植被 → 中等反照率（0.15–0.25）

### 大气成分对温室效应的影响

| 气体 | 温室强度 | 地球分压 |
|------|---------|---------|
| H₂O | 强 | 可变（0–4%） |
| CO₂ | 中 | 0.04%（420 ppm） |
| CH₄ | 很强 | 1.9 ppm |
| N₂ / O₂ | 无 | 78% / 21% |

---

## 8. 降水与水循环

### 总体结构（质量守恒水汽收支，2026-09 完整形式）

降水是一个**质量守恒的柱水汽收支方程**（Held & Soden 2006 的 $P-E=-\nabla\cdot(W\vec u)$
在雨出参数化下的形式）。当前完整形式（CLIM-02 机制迁移后，实现细节见
`climate-pipeline.md` §7）：

$$\nabla\cdot\big((1-\varphi)\,W\vec u\big) + k_{rain}(\mathbf x)\,W - \nabla\cdot(\kappa\nabla W) = E$$

$$P = k_{rain}(\mathbf x)\,W + P_{oro} + P_{route}$$

各项含义：

- $W$：柱水汽（可降水量，mm），全球均 ~25 mm（Trenberth & Smith 2005）。
- $\vec u$：地表风（m/s）；$E$：蒸发源（mm/yr，海洋格能量限制、陆地格土壤桶）。
- $k_{rain}$：雨出率（1/yr），基底 $1/\tau$ 乘空间调制因子（风暴路径、SST 对流门、
  海岸辐合、向星对流锚等）；$\tau$ = 水汽驻留时间 ≈ 9 天（Trenberth 1998；
  van der Ent & Tuinenburg 2016 复核）。
- $\kappa$：湍流扩散 ≈ 1e6 m²/s（大气涡旋扩散率，展宽 ITCZ 到观测 ~10° 雨带，
  扩散长度 $\sqrt{\kappa\tau}\approx 900$ km）。
- $\varphi$：**地形凝结份额**——空气跨上坡边抬升 $\Delta z$ 冷却 $\Gamma\Delta z$，
  Clausius–Clapeyron 给出饱和比湿下降 $\varphi = 1-\exp(-\max(\Delta z - z_{LCL},0)/H_{cc})$，
  其中 $H_{cc} = R_v T^2/(L_v\Gamma) \approx 2.0$–$2.6$ km 为抬升干燥尺度
  （$R_v$ = 水汽气体常数 461 J/(kg·K)，$L_v$ = 凝结潜热 2.5×10⁶ J/kg，
  $\Gamma$ = 湿绝热直减率），$z_{LCL}\approx 800$ m 为抬升凝结高度偏移
  （未饱和气块在 LCL 之下不凝结，Smith 1979）。
- $P_{oro}$：迎风地形凝结雨 = 各上坡入流边上 $\varphi\cdot|c|\cdot W_{上游}$ 之和
  （$c$ 为边平流系数）；背风雨影由同一机制**涌现**（翻山气流已被削耗），
  无需独立参数化。
- $P_{route}$：冷阱路由雨——冷空气柱钳制在饱和值 $W_{sat}(T)$，被钳掉的雨出率
  $k(W-W_{sat})^+$ 沿入流边按通量份额路由回上风暖格（这部分水汽本就在上游暖区
  凝结）。

- **质量守恒由构造保证**：通量项的全局对消残差恰为 $\sum P_{oro}$，冷阱截断量
  经 $P_{route}$ 原额归还，故面积加权 $\sum A\,P = \sum A\,E$ 精确成立。唯一例外
  是收敛哨兵（$\alpha\,k_{rain}\,W_{sat}$ 逐格年降水帽，数值稳定化类，咬合时
  warning 并在构建账本中记账）。
- 离散：CVT 图上迎风有限体积（边平均风速保证成对边通量反对称）+ 图扩散，
  直接稀疏 LU 求解；地形衰减是边系数的乘法修正，保持线性。
- **ITCZ / 副热带干带从 $\nabla\cdot(W\vec u)$ 自然涌现**——辐合处 $W$ 高 → $P$ 高，无纬度硬编码。

### 海洋蒸发（水汽源，能量限制）

海洋蒸发是**能量限制**的（潜热通量不能超过可用净表面辐射），不是 C–C 饱和斜率：

```
evaporation = evaporation_base_mm × (1 + 0.03 × (SST − 15))   # mm/yr
```

- `evaporation_base_mm` 默认 1000（15 °C 洋面年蒸发），标定使全球洋均蒸发 ≈ 1143 mm/yr
  （Trenberth 2009 实测）。~3%/°C 是能量限制响应（Trenberth 2009；Held & Soden 2006），
  非饱和水汽压的 ~7%/°C。
- **陆地蒸散 = 土壤水桶**（Manabe 1969 单层桶，`soil_bucket_monthly`）：储量 $S$
  （mm，容量 $C$ = 根区有效持水量，默认 150 mm）逐月闭合
  $P_m = E_m + R_m + \Delta S$，其中 $E_m = \min(E^{pot}_m,\ S + P_m)$ 为实际蒸散
  （能量上限、水量约束），$R_m$ 为超过容量的溢流（径流/补给）。年度周期迭代至
  **周期稳态**（年末储量 = 年初，$\sum \Delta S = 0$，故年尺度 $\sum P = \sum E + \sum R$）。
  干湿季记忆由此涌现：湿季以潜在速率蒸散并充满储量，干季抽取储量维持蒸散。
  桶的强迫 $P_m$ 来自第一遍月解（该遍陆地 ET 用 Budyko 曲线
  $E = E_{pot}\cdot P/(E_{pot}+P)$ 估计），桶 ET 再驱动第二遍月解——截断两遍定点，
  残差打印在构建日志。Budyko 曲线（Budyko 1974）保留两个角色：年解的水分限制
  固定点、桶的初始化。陆地潜在蒸散率 = `_LAND_EVAPOTRANSPIRATION_FRACTION`
  （≈0.55，土壤/植被相对开阔水面的削减）× 能量限制速率。全球陆均蒸散实测
  ≈ 490 mm/yr（Trenberth 2009 水量收支）——桶方案下模型给出 ~500 mm/yr。

### 水汽输送（迎风平流 + 湍流扩散）

柱水汽 $W$ 在 CVT 图上沿风场迎风平流（`_solve_moisture_budget`），边平均风速保证守恒，
湍流扩散项展宽 ITCZ。传播距离由 $L = u\tau$ 随风速自适配（慢自转风强 → 水汽穿透更远），
分辨率无关（用 km 定义的物理量）。

### 地形降水与雨影（预算内通量凝结，2026-09 机制迁移）

地形雨与雨影是**同一个守恒机制的两面**：空气跨上坡边抬升时按 Clausius–Clapeyron
凝结（份额 $\varphi$，公式见「总体结构」），凝结部分在迎风格雨出为 $P_{oro}$；
翻过屏障的气流已被削耗，背风少雨**自然涌现**，无需独立的雨影参数化。早期的
「迎风加法雨 + 背风乘法雨影」两处后处理已退役——它们各自破坏水量守恒
（凭空加水 / 静默删水）。

### 其他调制与守卫（全部在预算内核或账本内）

- $k_{rain}$ 空间调制：斜压风暴路径增强、§5-α SST 对流门、§5-β 对流临界门
  （默认关）、海岸不对称辐合（切片 3）、向星对流锚（切片 4，潮汐锁定世界）——
  均为乘法调制，任意调制场下守恒保持。
- 收敛哨兵：逐格年降水帽 $\alpha\,k_{rain}\,W_{sat}(\max(T,0^\circ C))$（α=8，
  数值稳定化类），咬合时 warning + 账本记账。
- 详见 `climate-pipeline.md` §7。

### 对应源码

```
dreamulator.map.climate_simulator._compute_precipitation_monthly_budget  # 月度预算编排 + 账本
dreamulator.map.climate_simulator._solve_moisture_budget                 # 守恒求解器（含 φ 衰减）
dreamulator.map.climate_simulator._apply_cold_trap                       # 饱和钳制 + 上风路由
dreamulator.map.climate_simulator._convergence_sentinel                  # 收敛哨兵
dreamulator.engine.climate_physics.cc_lift_drying_scale                  # H_cc 抬升干燥尺度
dreamulator.engine.climate_physics.soil_bucket_monthly                   # 土壤水桶（周期稳态）
dreamulator.engine.climate_physics.evaporation_rate                      # 能量限制蒸发
```

---

## 参考资料

- North, G.R., & Coakley, J.A. (1979). "Differences between seasonal and mean annual
  energy balance model calculations of climate and climate sensitivity." *J. Atmos. Sci.* 36, 1189.
- Budyko, M.I. (1969). "The effect of solar radiation variations on the climate of the Earth."
  *Tellus* 21, 611（线性 OLR $I = A + B T$ 的出处）.
- Manabe, S. (1969). "Climate and the ocean circulation: 1. The atmospheric
  circulation and the hydrology of the Earth's surface." *Mon. Wea. Rev.* 97,
  739–774（单层土壤水桶 $E = \min(E_{pot}, S+P)$ 的出处）.
- Kaspi, Y., & Showman, A.P. (2015). "Atmospheric dynamics of terrestrial exoplanets over a
  wide range of orbital and atmospheric parameters." *ApJ* 804:60（$\Delta T \propto \Omega^{0.3}$ 标度）.
- Shields, A.L., Bitz, C.M., Meadows, V.S., Joshi, M.M., & Robinson, T.D. (2012). "The effect of
  host star spectral energy distribution and ice-albedo feedback on the climate of extrasolar
  planets." *Astrobiology* 12:1023（M 矮星冰反照率抑制 + 雪 0.8→0.6 / 冰 0.5→0.3 锚点值）.
- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.). Elsevier. Eq. 3.7.
- Pierrehumbert, R.T. (2010). *Principles of Planetary Climate*. Cambridge University Press.
- climlab: Rose, B.E.J. https://climlab.readthedocs.io/（`EBM` / `EBM_seasonal` 的对标实现）.
- [Energy Balance Model — Wikipedia](https://en.wikipedia.org/wiki/Energy_balance_model)
- [Climate Sensitivity — IPCC AR6](https://www.ipcc.ch/report/ar6/wg1/)
