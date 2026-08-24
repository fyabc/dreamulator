# 恒星日与太阳日（Synodic Day）

## 核心概念

一个天体的"一天"有两种定义，取决于参照系：

| 术语 | 定义 | 参照物 | 地球值 |
|------|------|--------|--------|
| **恒星日**（sidereal day） | 天体绕自转轴相对**远处恒星**转 360° 的时间 | 惯性空间 | 23h 56m 4.09s |
| **太阳日**（solar / synodic day） | 天体上某点**再次朝向其所绕恒星**（"正午→正午"）的时间 | 所绕恒星 | 24h 0m 0s |

两者不同是因为：在一个恒星日内，天体沿轨道前进了一段角度（地球每天 ~1°），
必须再多转一点才能让恒星回到同一经线。一年下来，太阳日比恒星日**少整整一圈**
（一年内太阳日数 = 恒星日数 − 1）。

## 关键公式

对**顺行**（自转方向与公转同向）天体，取频率之差（即周期倒数之差）：

$$\frac{1}{T_{\text{solar}}} = \left| \frac{1}{T_{\text{sidereal}}} - \frac{1}{T_{\text{year}}} \right|$$

其中 `T_year` 是天体绕中心恒星的公转周期。**逆行**（如金星）取和：

$$\frac{1}{T_{\text{solar}}} = \frac{1}{T_{\text{sidereal}}} + \frac{1}{T_{\text{year}}}$$

推广的哥白尼公式（相合周期 S、恒星周期 P）：

- 内行星：`1/S = 1/P − 1/P⊕`
- 外行星：`1/S = 1/P⊕ − 1/P`

## 潮汐锁定的特例（世界构建关键）

被中心天体潮汐锁定的卫星，其**恒星日 = 绕中心天体的公转周期**（自转与公转同步），
例如月球恒星日 = 27.32 d（恒星月）。但它的**太阳日仍由上述公式决定**，并**不等于**恒星日：

- **月球**（锁定于地球，绕日周年 365.25 d）：
  太阳日 = 1/(1/27.32 − 1/365.25) = **29.53 d**（朔望月）——月球上一昼夜约 29.5 个地球日。
- **Nacrea**（锁定于 Aegis，Aegis 绕 Ignis 周期 67 d）：
  恒星日 = 3.25 d（= 绕 Aegis 公转周期）；太阳日 = 1/(1/3.25 − 1/67) = **3.42 d**。

> 注意术语陷阱：天文学里"synodic day"若以**被锁定的中心天体**为参照（月球相对地球），
> 则因潮汐锁定而为无穷大（永远同一面朝向中心天体）；但**太阳日**以**恒星**为参照，
> 是有限的、且通常是世界构建里"昼夜"的真正含义。二者不可混淆。

## 现实参考

| 天体 | 恒星日 | 公转周期 | 太阳日 | 备注 |
|------|--------|---------|--------|------|
| 地球 | 23.93 h | 365.25 d | 24 h | 顺行，差 3m56s |
| 月球 | 27.32 d | （绕地球） | 29.53 d | 潮汐锁定于地球 |
| 水星 | 58.65 d | 88 d | 176 d | 3:2 自旋-轨道共振，太阳日 = 2 公转周期 |
| 金星 | 243 d | 224.7 d | 117 d | 逆行，太阳日短于恒星日 |

地球太阳日年内有 ±51 s 波动（轨道偏心率 + 轴倾角所致），24 h 是**平均太阳日**。

## 对引擎与模拟的启示

1. **科里奥利力 / 风场用恒星日**：`f = 2Ω sin φ` 里的 Ω 是天体**绝对自转角速度**
   （恒星日），不是太阳日。大气/海洋的旋转动力学依赖恒星日。
2. **昼夜热循环用太阳日**：白天/黑夜的周期是**太阳日**，只在模拟**日变化**（非平衡态）
   时才有意义。纯平衡 EBM 不区分二者。
3. **潮汐锁定的相位漂移**：潮汐周期（= 绕中心天体公转周期）与太阳日通常不同，二者以
   **拍频** `1/(1/T_tide − 1/T_solar)` 缓慢漂移——这是潮间带热环境随"年"周期性平均的根源
   （见 `data/worlds/nacrea/layers/geological/input/tidal_effects.md` §大潮相位漂移）。

## 极昼/极夜时长公式（零偏心率近似）

太阳赤纬近似为 ``δ(t) = ε·sin(2πt/P)``（ε 为有效倾角，P 为年长，t 从分点起算；
零偏心率近似）。纬度 φ 处出现极昼的条件是 ``δ ≥ 90° − |φ|``，即
``sin θ > c``，其中 ``c = (90° − |φ|)/ε``。一个周期内满足该条件的时间占比为

$$f_{\text{极昼}} = \frac{\pi - 2\arcsin c}{2\pi} \quad (0 \le c \le 1)$$

- c ≥ 1（纬度低于极圈 90°−ε）：无极昼，f = 0
- 极点（|φ| = 90°）：c = 0，f = 1/2（半年极昼、半年极夜）
- 地球北角（71.2°N，ε=23.44°）：f ≈ 0.204，约 74 天（几何值；计入大气折射后
  与观测的 ~76 天午夜太阳季一致）

极圈纬度即 ``90° − ε``（地球 ±66.56°、Nacrea ±81°）。

**引擎实现**：`engine/stellar_physics.py::polar_day_fraction_of_year` /
`polar_circle_latitude_deg` / `solar_day_days`；世界参数汇总
（太阳日、年长、极昼、一年日数等）由 `engine/physical_inputs.py::
build_system_catalog` 在 build 时写入 `system_catalog.yaml`（每颗天体的 `derived` 段）。

## 参考资料

- Wikipedia, "Synodic day" — https://en.wikipedia.org/wiki/Synodic_day
- ESA Navipedia, "Solar and Sidereal Times relationship" — https://gssc.esa.int/navipedia/index.php?title=Solar_and_Sidereal_Times_relationship
- Durham University, "Lunar Sidereal and Synodic Periods" — https://astro.dur.ac.uk/~ams/users/lunar_sid_syn.html
- Murray, C. D., & Dermott, S. F. (1999). *Solar System Dynamics*. Cambridge University Press.（轨道周期与自转周期换算）
- Wikipedia, "Midnight sun" — https://en.wikipedia.org/wiki/Midnight_sun （极昼时长与赤纬近似）
