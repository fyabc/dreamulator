# 能量平衡模型 (Energy Balance Model)

> 本文档描述 dreamulator 气候引擎（Phase 3A）中使用的大气能量平衡模型。
> 对应源码：`src/dreamulator/engine/climate_physics.py`

---

## 1. 恒星辐射与平衡温度

### 核心公式

行星在没有大气情况下的黑体平衡温度：

$$T_{eq} = \left(\frac{L_*}{16\pi\sigma d^2}\right)^{1/4}$$

其中：
- $L_*$：恒星光度（W）。$L_\odot = 3.828 \times 10^{26}$ W
- $d$：行星轨道半长轴（m）。1 AU = $1.496 \times 10^{11}$ m
- $\sigma$：Stefan-Boltzmann 常数 = $5.670374419 \times 10^{-8}$ W/m²/K⁴
- 因子 $1/16$ 来自：球面积分（$1/4$）+ 截面比（$1/4$）的组合

### 实用形式（太阳单位）

$$T_{eq} = 255 \times \left(\frac{L_*/L_\odot}{(d/\text{AU})^2} \times (1 - \alpha)\right)^{1/4} \text{ K}$$

其中 $\alpha$ 为 Bond 反照率。

### 地球参考值

| 参数 | 值 |
|------|-----|
| Bond 反照率 | 0.306 |
| 平衡温度 | 254.6 K（−18.6 °C） |
| 地表实际平均温度 | 288 K（+15 °C） |
| 温室增温 | **+33 K** |

### 对应源码

```python
dreamulator.engine.climate_physics.equilibrium_temperature(
    stellar_luminosity_sol, orbital_distance_au, albedo
) -> float  # Kelvin
```

---

## 2. 温室效应

### 简化模型

$$T_{surface} = T_{eq} + \Delta T_{greenhouse}$$

地球 $\Delta T_{greenhouse} \approx 33$ K，主要贡献来自 H₂O、CO₂、CH₄。

对于不同大气成分，$\Delta T_{greenhouse}$ 可通过以下公式近似：

$$\Delta T_{greenhouse} = 33 \times \frac{P_{atm}}{P_\oplus} \times f_{comp}$$

其中 $f_{comp}$ 是大气成分因子（地球 = 1.0，纯 N₂ = 0.0，CO₂ 丰富 = 1.5+）。

### 对应源码

```python
dreamulator.engine.climate_physics.surface_temperature(
    teq_kelvin, greenhouse_warming_K
) -> float  # Kelvin
```

---

## 3. 纬度温度梯度

### sin² 模型

现实地球的纬度温度分布近似为：

$$T(\phi) = T_{eq\_lat} - \Delta T_{lat} \times \sin^2\phi$$

其中：
- $\phi$：纬度（弧度）
- $\Delta T_{lat}$：赤道-极地温差。地球 ≈ 45 °C
- $T_{eq\_lat}$：**赤道**表面温度，而非全球平均

### 全球平均 ↔ 赤道温度的转换

$\sin^2\phi$ 在球面上的面积加权平均值为 $1/3$，因此：

$$T_{eq\_lat} = T_{mean} + \frac{\Delta T_{lat}}{3}$$

**示例**（地球，$T_{mean} = 15$ °C，$\Delta T_{lat} = 45$ °C）：

| 纬度 | $\sin^2\phi$ | 温度 |
|------|-------------|------|
| 0°（赤道） | 0.00 | **30 °C** |
| 30° | 0.25 | 18.8 °C |
| 45° | 0.50 | 7.5 °C |
| 60° | 0.75 | −3.8 °C |
| 90°（极地） | 1.00 | **−15 °C** |

### 参数范围

| 类地行星 | ΔT_lat | 说明 |
|---------|--------|------|
| 快速自转（$P_{rot} < 1$ day） | 40–50 °C | 强环流 → 有效热量传输 |
| 中等自转（$P_{rot} \approx 1$ day） | 45–60 °C | 地球类型 |
| 慢速自转（$P_{rot} \gg 1$ day） | 60–100 °C | 弱环流 → 极端温差 |
| 潮汐锁定 | 100–200 °C | 永昼面极热、永夜面极冷 |

### 对应源码

```python
dreamulator.engine.climate_physics.latitude_temperature(
    t_surface_mean_c, lat_rad, lat_gradient_c
) -> np.ndarray  # °C at each latitude
```

---

## 4. 海拔递减率

### 湿绝热递减率

$$T(h) = T_{surface} - \Gamma \times h$$

其中 $\Gamma \approx 6.5$ °C/km（湿绝热递减率，地球平均）。

| 递减率类型 | 值 (°C/km) | 条件 |
|-----------|-----------|------|
| 干绝热 | 9.8 | 未饱和空气 |
| 湿绝热 | 4–7（典型 6.5） | 饱和空气（云内） |
| 等温 | 0 | 逆温层 |
| 超绝热 | > 9.8 | 强烈地面加热 |

### 对应源码

```python
dreamulator.engine.climate_physics.altitude_lapse_rate(
    temperature_c, elevation_m, lapse_rate_c_km
) -> np.ndarray  # altitude-corrected °C
```

---

## 5. 季节变化

### 太阳赤纬

$$\delta = \varepsilon \times \sin\left(2\pi \times \frac{d - 80}{P_{orb}}\right)$$

其中 $\varepsilon$ 为轴倾角，$d$ 为年积日（0 = 北半球冬至）。

### 温度季节振幅

$$\Delta T_{season}(\phi) = A \times |\sin\phi| \times \sqrt{\sin\varepsilon}$$

其中 $A \approx 15$ °C 为参考振幅。极地振幅最大，赤道最小。

### 对应源码

```python
dreamulator.engine.climate_physics.seasonal_temperature(
    t_mean_c, lat_rad, axial_tilt_deg, orbital_period_days, day_of_year,
    seasonal_amplitude_c
) -> dict  # {'jan', 'jul', 'today', 'annual_range'}
```

---

## 6. 行星参数的影响

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
| N₂ | 无 | 78% |
| O₂ | 无 | 21% |

---

## 参考资料

- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.). Elsevier. Ch. 2–4.
- Pierrehumbert, R.T. (2010). *Principles of Planetary Climate*. Cambridge University Press.
- [Energy Balance Model — Wikipedia](https://en.wikipedia.org/wiki/Energy_balance_model)
- [Climate Sensitivity — IPCC AR6](https://www.ipcc.ch/report/ar6/wg1/)
