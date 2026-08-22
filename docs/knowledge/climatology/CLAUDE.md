# 气候学知识库

## 已有文档

- `energy_balance.md` — 能量平衡模型（EBM）、温室效应、1D EBM 经向温度分布、大陆度、季节 EBM、辐合驱动降水
- `ocean_provinces.md` — Longhurst 海洋生物地球化学省份（海洋版 Köppen）
- `atmospheric_circulation.md` — 科里奥利、三胞环流、地转风、温度-气压耦合（2026-08 自实现反写）
- `koppen_classification.md` — Köppen 五主群 + 亚型阈值表（2026-08 自实现反写）
- `climate_classification_comparison.md` — 四大分类体系比较（Köppen / Trewartha / Thornthwaite / Holdridge）与 dreamulator 适配建议（2026-08）
- `ocean_currents.md` — 风生/热盐环流、海峡闸门动力学、ENSO 类振荡（3A.3 科学底座）
- `precipitation.md` — 水汽输送、降水相态（雨/雪 + Clausius–Clapeyron）、地形降水、内陆干旱梯度（2026-08 自实现反写 + 低温骤降修复）

## 规划中的文档

## 关键参考

- Hartmann, D.L. (2016). *Global Physical Climatology* (2nd ed.). Elsevier.
- Peixoto, J.P., & Oort, A.H. (1992). *Physics of Climate*. Springer.
- Koppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie*.
- Pierrehumbert, R.T. (2010). *Principles of Planetary Climate*. Cambridge.

## 与引擎实现的对应关系

| 知识文档 | 引擎模块 | 输出 |
|---------|---------|------|
| `energy_balance.md` | `climate_physics.py:equilibrium_temperature()` | 全球平均温度 |
| `energy_balance.md` §3 | `climate_seasonality.py:solve_1d_ebm_temperature()` | 纬向年均温（1D EBM 谱解） |
| `energy_balance.md` §4 | `climate_simulator.py`（`ebm_diffusion_land_wm2k`） | 大陆度（海陆年均对比） |
| `energy_balance.md` §6 | `climate_seasonality.py:compute_seasonal_climate()` | 月度温度/降水（显式热输送 + 冰反照率） |
| `energy_balance.md` §8 | `climate_simulator.py:_meridional_convergence()` | 辐合驱动降水 |
| `atmospheric_circulation.md` | `climate_physics.py:hadley_cell_wind()` | 风场矢量 |
| `precipitation.md` | `climate_simulator.py:_compute_precipitation_bfs()` | 年降水量 |
| `ocean_currents.md` | `climate_physics.py:ekman_current_direction()` | 洋流矢量 |
| `koppen_classification.md` | `climate_physics.py:koppen_classify()` | 气候类型 |
