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

## 5. 海拔递减率

### 湿绝热递减率

$$T(h) = T_{surface} - \Gamma \times h$$

$\Gamma \approx 6.5$ °C/km（湿绝热递减率，地球平均）。

| 递减率类型 | 值 (°C/km) | 条件 |
|-----------|-----------|------|
| 干绝热 | 9.8 | 未饱和空气 |
| 湿绝热 | 4–7（典型 6.5） | 饱和空气（云内） |

### 温度依赖性

$$\Gamma(T) = 6.5 - 2.0 \times \exp(-T / 10\text{°C})$$

| T (°C) | 30 | 20 | 10 | 0 | −10 |
|--------|-----|-----|-----|-----|------|
| Γ (°C/km) | 4.6 | 5.1 | 5.7 | 6.2 | 6.5 |

暖空气含水汽多，凝结潜热减缓冷却 → 直减率更低。热带高地（基多 2850m 实测 13.5°C）用
统一 6.5 会偏离 5°C，用 $\Gamma(T)$ 后 14.2°C 吻合。启用方式 `variable_lapse_rate: true`。

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
| `seasonal_coastal_scale_km` | 500.0 | 海洋调节 e-folding 长度（km） |
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

### 总体结构（质量守恒水汽收支，2026-08 重推）

降水是一个**质量守恒的柱水汽收支方程**（Held & Soden 2006 的 $P-E=-\nabla\cdot(W\vec u)$
在雨出参数化下的形式）：

$$\nabla\cdot(W\vec u) + \frac{W}{\tau} - \kappa\nabla^2 W = E,\qquad P = \frac{W}{\tau}$$

- $W$：柱水汽（可降水量，mm），全球均 ~25 mm（Trenberth & Smith 2005）。
- $\tau$：水汽驻留时间 ≈ 9 天（Trenberth 1998；van der Ent & Tuinenburg 2016 复核）。
- $\kappa$：湍流扩散 ≈ 1e6 m²/s（大气涡旋扩散率，展宽 ITCZ 到观测 ~10° 雨带，
  扩散长度 $\sqrt{\kappa\tau}\approx 900$ km）。
- **质量守恒由构造保证**：$\int P = \int E$（通量项全局对消），不再有「只落 30% 水汽」的
  启发式因子。
- 离散：CVT 图上迎风有限体积（边平均风速保证通量守恒）+ 图扩散，直接稀疏 LU 求解。
- **ITCZ / 副热带干带从 $\nabla\cdot(W\vec u)$ 自然涌现**——辐合处 $W$ 高 → $P$ 高，无纬度硬编码。

### 海洋蒸发（水汽源，能量限制）

海洋蒸发是**能量限制**的（潜热通量不能超过可用净表面辐射），不是 C–C 饱和斜率：

```
evaporation = evaporation_base_mm × (1 + 0.03 × (SST − 15))   # mm/yr
```

- `evaporation_base_mm` 默认 1000（15 °C 洋面年蒸发），标定使全球洋均蒸发 ≈ 1143 mm/yr
  （Trenberth 2009 实测）。~3%/°C 是能量限制响应（Trenberth 2009；Held & Soden 2006），
  非饱和水汽压的 ~7%/°C。
- 陆地蒸散 = `_LAND_EVAPOTRANSPIRATION_FRACTION`（≈0.55）× 洋面速率，标定使全球陆均
  蒸散 ≈ 490 mm/yr（Trenberth 2009 水量收支）。

### 水汽输送（迎风平流 + 湍流扩散）

柱水汽 $W$ 在 CVT 图上沿风场迎风平流（`_solve_moisture_budget`），边平均风速保证守恒，
湍流扩散项展宽 ITCZ。传播距离由 $L = u\tau$ 随风速自适配（慢自转风强 → 水汽穿透更远），
分辨率无关（用 km 定义的物理量）。

### 地形降水与雨影

- 迎风坡抬升：`rain = W_upwind × min(0.20 × elev_gain/1000, 0.9)`（每 1000m 抬升转换 20% 柱水汽）；
- 雨影（背风坡）：降水 = 柱水汽 × 3%。

### 其他保留项（第一性）

- 斜压风暴路径、局地对流（暖陆地午后雷暴）、内陆干旱梯度、海岸不对称、Föhn 雨影、
  热带底线、次行星半球强迫——详见 `climate-pipeline.md`。

### 对应源码

```
dreamulator.map.climate_simulator._compute_precipitation_bfs   # 水汽收支 + 地形 + 保留项
dreamulator.map.climate_simulator._solve_moisture_budget       # 质量守恒水汽收支求解
dreamulator.engine.climate_physics.evaporation_rate            # 能量限制蒸发
```

---

## 参考资料

- North, G.R., & Coakley, J.A. (1979). "Differences between seasonal and mean annual
  energy balance model calculations of climate and climate sensitivity." *J. Atmos. Sci.* 36, 1189.
- Budyko, M.I. (1969). "The effect of solar radiation variations on the climate of the Earth."
  *Tellus* 21, 611（线性 OLR $I = A + B T$ 的出处）.
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
