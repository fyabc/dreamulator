# 气候学知识库

## 已有文档

- `energy_balance.md` — 能量平衡模型（EBM）、温室效应、纬度温度梯度
- `atmospheric_circulation.md` — 地转风、Hadley/Ferrel/Polar 环流、科里奥利力
- `precipitation.md` — 水汽输送、地形降水、ITCZ、雨影效应
- `ocean_currents.md` — 风生流、Ekman 输运、热盐环流、大洋环流
- `koppen_classification.md` — Köppen 气候分类系统
- `ocean_provinces.md` — Longhurst 海洋生物地球化学省份（海洋版 Köppen）

## 关键参考

- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.). Elsevier.
- Peixoto, J.P., & Oort, A.H. (1992). *Physics of Climate*. Springer.
- Koppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie*.
- Pierrehumbert, R.T. (2010). *Principles of Planetary Climate*. Cambridge.

## 与引擎实现的对应关系

| 知识文档 | 引擎模块 | 输出 |
|---------|---------|------|
| `energy_balance.md` | `climate_physics.py:equilibrium_temperature()` | 全球平均温度 |
| `energy_balance.md` | `climate_physics.py:latitude_temperature()` | 纬度温度分布 |
| `atmospheric_circulation.md` | `climate_physics.py:hadley_cell_wind()` | 风场矢量 |
| `precipitation.md` | `climate_simulator.py:_compute_precipitation_bfs()` | 年降水量 |
| `ocean_currents.md` | `climate_physics.py:ekman_current_direction()` | 洋流矢量 |
| `koppen_classification.md` | `climate_physics.py:koppen_classify()` | 气候类型 |
