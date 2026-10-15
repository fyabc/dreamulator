# 气候学知识库

## 已有文档

- `energy_balance.md` — 能量平衡模型（EBM）、温室效应、1D EBM 经向温度分布、大陆度、副热带下沉增温及其干燥度门控（Hamon PET + UNEP AI）、季节 EBM、质量守恒水汽收支（完整方程：地形凝结 φ 衰减 + 冷阱上风路由 + 收敛哨兵）、土壤水桶（Manabe 1969，周期稳态）
- `ocean_provinces.md` — Longhurst 海洋生物地球化学省份（海洋版 Köppen）
- `atmospheric_circulation.md` — 科里奥利、三胞环流、地转风、温度-气压耦合（位温 θ）、季风边界层风 + 标定锚点、跨赤道季风西风带（2026-08 自实现反写 + 季风 f→0 教训）
- `polar_pressure_regimes.md` — 极地高/低压的热力 vs 动力机制、两圈/三圈体制的联动指纹（纬向平均极地 SLP 符号、极地东/西风、ψ 翻转次数、极地降水体制）、GCM 对照证据（2026-10）
- `koppen_classification.md` — Köppen 五主群 + 亚型阈值表（2026-08 自实现反写）
- `climate_classification_comparison.md` — 四大分类体系比较（Köppen / Trewartha / Thornthwaite / Holdridge）与 dreamulator 适配建议（2026-08）
- 统一气候描述（UCC）→ **已迁至专门目录 `docs/ucc/`**（主文档 `docs/ucc/specification.md`：时间基准契约、连续描述量、Hamon-1961 需求模型声明与有效域、分类 profile v1 与 L2 实验冻结依据）
- `ocean_currents.md` — 风生/热盐环流、海峡闸门动力学、ENSO 类振荡（3A.3 科学底座）
- `precipitation.md` — 水汽输送、降水相态（雨/雪 + Clausius–Clapeyron）、地形降水与雨影（CC 抬升凝结 H_cc、LCL、降水效率，Smith 1979 / Houze 2012）、海岸辐合、SST 对流门（WTG）、对流临界雨出门（Neelin-Peters-Hales）
- `obliquity_ice_albedo.md` — 轴倾角只重新分配日照（全球年平均恒为 S/4，极点年平均 S·sin ε/π），冰反照率把高纬夏季的增量整流成全球净增温；在 GCM 中检验时的注意事项（必须固定轨道）；EBM 为什么复现不了（全球均温锚定、冰反照率只做局地降温）
- `day_length_effects.md` — 日长（太阳日数天）对天气与气候的影响：日较差、对流与海陆风日循环、惯性-周日共振纬度、天气系统尺度、硅酸盐风化随自转的极大、同步卫星特有的巨行星食与巨行星辐射（含 Nacrea 量级粗估与现有模型的处理）、极端天气（温带风暴与热带气旋的自转标度律、寒潮与热浪、夜间强对流，含 Nacrea 与地球的 GCM 对照）
- `atmospheric_co2_ch4_history.md` — 地球大气 CO2/CH4 地质历史（显生宙逐期表 + 前寒武、CH4 快变量/CO2 慢变量框架、冰期旋回耦合、火山-风化稳态与脉冲放大标度律、世界构建锚点速查表；2026-10 nacrea 路线 1 调研沉淀）

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
| `energy_balance.md` §4.5 | `climate_simulator.py`（`subsidence_warming_c`，Stage 1） | 副热带下沉增温（等面积均质化） |
| `energy_balance.md` §4.6 | `climate_physics.py:subsidence_aridity_gate()`（Stage 3.5） | 下沉增温的干燥度门控释放 |
| `energy_balance.md` §6 | `climate_seasonality.py:compute_seasonal_climate()` | 月度温度/降水（显式热输送 + 冰反照率） |
| `obliquity_ice_albedo.md` §4 | `climate_seasonality.py:solve_1d_ebm_temperature()`、`climate_physics.py:ice_albedo_feedback()` | 倾角的纬向重新分配（全球冰反照率耦合未实现） |
| `energy_balance.md` §8 | `climate_simulator.py:_solve_moisture_budget()` | 质量守恒水汽收支 |
| `atmospheric_circulation.md` | `climate_physics.py:hadley_cell_wind()` | 风场矢量 |
| `polar_pressure_regimes.md` | `climate_simulator.py`（`hadley_extent_deg`/`polar_cell_start_deg` 体制切换） | 两圈/三圈体制与极地气压/降水体制 |
| `precipitation.md` | `climate_simulator.py:_compute_precipitation_monthly_budget()` | 年/月降水量 |
| `ocean_currents.md` | `map/ocean_circulation.py`（`solve_ocean_gyre` 等） | 洋流矢量 |
| `koppen_classification.md` | `climate_physics.py:koppen_classify()` | 气候类型 |
| `docs/ucc/specification.md` | `map/ucc.py:compute_descriptors()` / `classify_v1()` | 气候描述量 / UCC 分类 |
