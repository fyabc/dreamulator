# 降水：水汽输送、相态与地形效应

> 为 dreamulator 气候引擎的降水模块提供参考。降水由质量守恒水汽收支（`climate_simulator.py:_solve_moisture_budget`）
> + 地形效应（翻山雨影/Föhn）+ 相态（雨/雪）转换构成。本文档补记降水相态与
> 低温降水（雪）的科学底座，以及 2026-08-13 发现的一处低温降水骤降 bug。

---

## 一、饱和水汽压与 Clausius–Clapeyron 方程

饱和水汽压 $e_s$ 随温度**指数**上升（Clausius–Clapeyron 关系）：

$$
\frac{1}{e_s}\frac{de_s}{dT} = \frac{L_v}{R_v T^2}
$$

- 积分近似（**Magnus 公式**，引擎 `climate_simulator.py:985` 采用）：$e_s = 611.2\cdot\exp\!\left(\frac{17.67\,T}{T+243.5}\right)$，$T$ 为 °C。
- **每升温 1°C，$e_s$ 增加约 6–7%**——这是"暖湿 / 冷干"的根本来源。
- **三相点（0°C）$e_s = 611.2$ Pa，不为 0**；冰面饱和水汽压略低于过冷液态水（混合云中冰晶增长、液滴蒸发，是温带降水的微物理引擎）。
- 比湿 $q = 0.622\,e_s/P$（$P$ 为气压）。

**对引擎的含义**：低温区的 $q_{sat}$ 确实远低于暖区（−0.3°C 时约为 15°C 的 35%），
但**不会在冰点附近趋近 0**——任何让"降水在 T<0°C 时崩溃到 ~0"的公式都是有问题的。

---

## 二、降水相态：雨 vs 雪（临界温度）

气温跨过冰点时，降水**相态改变**（雨 → 雪），但**总量不消失**：

- **临界气温法**（水文模型通用）：单阈值（如 ~1°C）或双阈值（0–2°C 区间线性插值）
  把降水分为雨/雪（VIC、SWAT、HBV 等）。
- **地面气温 0–2°C** 是雨雪判别关键区间；地面日最低气温 2°C 可作简单分界。
- **降雪比例存在阈值效应**：雨雪过渡带（降雪比例 0.13–0.87）对升温最敏感；
  低于 0.13 为降雨主导，高于 0.87 为降雪主导。
- **关键结论**：冻原/冰原（T<0°C）年降水仍有 **~200–400 mm**（以降雪为主），
  而非接近 0。引擎把高纬冻原降水衰减到 ~5 mm 是**过度**的。

---

## 三、内陆干旱梯度与沿海增强（引擎实现）

`climate_simulator.py` Step 6.5–6.6 建模"离海洋越远越干"：

- **内陆干旱梯度**：离海岸图距离 $d$ 超过阈值后，$P\propto\exp(-(d-\text{threshold})/e_{\text{fold}})$，
  其中 $e_{\text{fold}}\propto u\cdot(q_{sat}/q_{ref})$（风速 × 湿度标度）。
- **沿海增强**：向岸风携带海洋水汽 → 沿海 cell 降水增强，$f\in[0.5,1.5]$。

---

## 四、修复记录（2026-08-13）

**现象**：#20243（沿海 1 跳，52.93°N，4.6°C）降水 1114 mm，邻接的 #19866
（内陆 2 跳，53.14°N，−0.3°C）降水仅 5 mm——一格 ~50 km 内骤降 99.5%。

**根因**（日志定位）：骤降主因是 Step 6.5 内陆干旱的
`e_fold = 800·(u/5)·(q_sat/q_ref)`——把湿度 `q_sat` 错误地耦合进"传输距离"。
低温（−0.3°C，q_sat/q_ref≈0.35）+ 弱风（u=1）叠加，e_fold 从参考 800 km 骤减
到 56 km，离海岸 246 km 的冻原内陆被衰减 97.7%。沿海增强（Step 6.6）几乎无贡献
（弱风下 factor≈1.01）。

**修复**：`e_fold` 和 `threshold` 去掉 `q_sat` 依赖，改为只随风速：
`e_fold = 800·(u/5)`、`threshold = 500·(u/5)`。物理依据：**传输距离 ∝ 风速**
（风把水汽吹多远），湿度影响的是水汽**量**（经蒸发体现），而非传输**距离**。

**效果**：#19866 从 5 mm 恢复到 ~89 mm（冻原量级），骤降从 200 倍降到 ~26 倍。

---

## 参考来源

- 陈仁升等. *固液态降水分离方法探讨* — [ResearchGate PDF](https://www.researchgate.net/profile/Chen_Rensheng/publication/283600062_A_discuss_of_the_separating_solid_and_liquid_precipitations/links/568e601208aef987e567b150.pdf)
- 中国天山山区降水形态分离及降雪影响因素分析 — [知网](https://d.wanfangdata.com.cn/thesis/Y3443596)
- 我国中东部平原临界气温条件下降水相态判别 — [气象期刊](http://qxqk.nmc.cn/qx/ch/reader/view_abstract.aspx?file_no=20190801&st=alljournals)
- 陈亚宁团队：全球变暖加速亚洲高山区降雪率变化（阈值 0.13/0.87）— [中亚生态与环境研究中心](http://www.rceeca.com/kyjz/info/2025/93945.html)
- Clausius–Clapeyron 实现（Breeze.jl）— [GitHub](https://github.com/NumericalEarth/Breeze.jl/blob/3eeb010c90b0861476ef77e62ff478a36baec2b5/src/Thermodynamics/clausius_clapeyron.jl)
- 温度依赖降水（精确非线性山地波）— [Springer J. Math. Fluid Mech.](https://link.springer.com/article/10.1007/s00021-025-00946-y)
- 气溶胶对温度–降水标度的间接效应（CC 标度 6.1–8.6%/°C）— [ACP](https://acp.copernicus.org/articles/20/6207/2020/acp-20-6207-2020.html)

## 相关文档

- `energy_balance.md` — 温度（降水相态与 q_sat 的输入）
- `atmospheric_circulation.md` — 风场（水汽输送 + 沿海增强的驱动力）
- `koppen_classification.md` — 降水阈值（Köppen 分类输入）
