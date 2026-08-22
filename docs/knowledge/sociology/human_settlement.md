# 人类宜居性与农业适宜性

> 文明层「宜居等级 / 农业等级」两个 derived 图层的科学底座。
> 对应源码：`src/dreamulator/engine/habitability.py` 的 `habitability_score()` /
> `agriculture_score()`（以及布尔版本 `classify_habitable_coast()` /
> `classify_agricultural_core()`）。

## 一、核心概念

文明在哪里起源，由「人能定居」和「人能产粮」两条线决定。前者是**宜居性**
（settleability），后者是**农业适宜性**（agricultural suitability）。两者独立——
凉湿海洋性 ET（法罗/因纽特型）宜居但不产粮：定居的门槛（不过冷、不旱、可达海岸）
低于农业的门槛（生长季够暖）。这是 dreamulator 把两个图层做成「两条线」的物理依据。

## 二、宜居性三因子

### 2.1 温度：人类气候生态位（Human Climate Niche）

Xu et al. (2020, PNAS) 用 6000 年考古/人口数据发现，人类始终聚集在一个狭窄的温度带内：
**年均温 ~11–15°C（众数 ~13°C）**。该生态位不随土壤肥力或 NPP 变化，说明是「温度」本身
而非「资源」在主导定居。冷侧陡降（定居壁垒），暖侧有热带次峰（20–25°C 季风区）。

dreamulator 实现：宜居热因子用**不对称生态位带**（峰值 13°C，冷侧 σ=6、暖侧 σ=18），
忠实 Xu 2020 的「冷侧陡降、暖侧缓降（热带次峰）」形态。

### 2.2 降水：干旱栅

雨养定居的降水下限约 500 mm（半干旱分界，dreamulator roadmap 口径）。严格的干旱指标是
**UNEP 干燥度指数 AI = P/PET**（<0.5 半干旱、<0.2 干旱），但 PET 需要辐射/温度数据；
dreamulator 用 P 的线性 ramp `min(1, P/500)` 近似。

### 2.3 海岸：正交维度（非宜居因子）

Small & Nicholls (2003, JCR) 定义「近岸带」= 距海岸 100 km 且海拔 <100 m，栅格数据下
承载 ~23% 全球人口、密度约全球平均的 3×。这是「人**选择**住在海边」（贸易/渔业/经济）
的人口分布事实，**不是可定居性限制**——人类绝大多数住在内陆河谷、大陆腹地。

dreamulator 实现：海岸**不进入**宜居分数，由独立字段 `distance_to_coast_km` 承载
（种子发现的 `is_coastal` / `coastal_fraction` 消费之）。宜居等级 = 温度带 × 干旱 ramp。

## 三、农业适宜性三因子

### 3.1 生长度日（Growing Degree Days）

McMaster & Wilhelm (1997, AFM)：`GDD = Σ max(T_mean − T_base, 0)`，作物发育速率与累积
热单位成正比。玉米基温 T_base = 10°C（Cross & Zuber 1972）。这是农业热适宜性的标准指标。

dreamulator 实现：月分辨率代理 `min(1, (t_hot − 10°C) / 15°C)`——用最热月超林线的程度
近似整个生长季的累积热单位。

### 3.2 林线（Tree-line）

乔木/作物需最热月 >10°C 才能完成生长季——即 Köppen C/D 与 E 的分界（Köppen 1936；
Peel et al. 2007）。高山树线的生长季均温约 6.7°C（Körner & Paulsen 2004），与 10°C
最热月等温线是同一树线在不同度量下的表达。

dreamulator 实现：农业等级在 `t_hot ≤ 10°C` 处**硬零**（无乔木/作物）。

### 3.3 土壤肥力

USDA 土纲 → 肥力分级（见 [`../ecology/soil_orders.md`](../ecology/soil_orders.md)）。
软土/淋溶土=高、强风化/冻土=低，直接决定农业潜力。

## 四、与 dreamulator 的映射

| 图层 | 因子链 | 公式（0–100） |
|------|--------|--------------|
| 宜居等级 | 温度带 × 降水 | `100 · N(T; 13, σ) · min(1, P/500)`（N = 不对称生态位带，冷 σ=6 / 暖 σ=18）|
| 农业等级 | 林线闸 × 热 × 水 × 土 | `t_hot ≤ 10 → 0；否则 100 · min(1, (t_hot−10)/15) · min(1, P/1000) · w_soil` |

其中 N 为不对称生态位带因子，w_soil = {high: 1.0, medium: 0.5, low: 0.25}。

## 参考资料

- Xu, C., Kohler, T. A., Lenton, T. M., Svenning, J.-C., & Scheffer, M. (2020).
  "Future of the human climate niche." *PNAS* 117(21):11350–11355.
  https://doi.org/10.1073/pnas.1910114117
- McMaster, G. S., & Wilhelm, W. W. (1997). "Growing degree-days: one equation,
  two interpretations." *Agricultural and Forest Meteorology* 87(4):291–300.
- Small, C., & Nicholls, R. J. (2003). "A global analysis of human settlement in
  coastal zones." *Journal of Coastal Research* 19(3):584–599.
- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie*.
- Peel, M. C., Finlayson, B. L., & McMahon, T. A. (2007). "Updated world map of the
  Köppen–Geiger climate classification." *Hydrology and Earth System Sciences* 11:1633–1644.
- Körner, C., & Paulsen, J. (2004). "A world-wide study of high altitude treeline
  temperatures." *Journal of Biogeography* 31(5):713–732.
