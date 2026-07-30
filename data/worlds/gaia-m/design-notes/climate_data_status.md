# 气候数据状态

首跑：2026-07-31，v0.13.2 引擎（含 falsy-zero 轴倾角修复）。

生成命令：

```bash
uv run dreamulator build gaia-m --only climate --force
```

## 产物

- `layers/climate/derived/climate_summary.yaml` — 全球/陆/海温湿统计 + 柯本类计数 + 模拟参数
- `maps/satellite_gaiam/`：`temperature.png`、`precipitation.png`、`koppen.json`、`climate_metadata.json`
- `cvt_mesh.json` — 全 10 万 cell 回写 `temperature_C` / `precipitation_mm` / `koppen_class`（前端柯本图层与 cell inspector 读这个）

## 当前模型近似（解读本份数据须知）

1. **轨道参数静默回退**：引擎尚未实现卫星世界的轨道/光度解析
   （`_load_orbital_distance` 硬编码返回 1.0 AU；光度查找按 `planet.orbits`
   找恒星 ID，对卫星必然失配 → 默认 1.0 L☉）。本份数据按
   **1 AU 绕太阳 + 33 K 温室**计算，而非真实的 0.0357 L☉ @ 0.2795 AU
   （约 46% 地球日照）。注意：真实日照 + 33 K 温室 ≈ −30 °C 全球冰封，
   与设定的宜居假设矛盾——正式化之前需要重新设计温室气体参数。
   `climate_summary.yaml` 的 `simulation_parameters` 如实记录了所用参数，可追溯。
2. **潮汐锁定仅为快速自转近似**：自转周期（3.25 d）只进入科氏力；
   没有昼夜半球、次恒星点热源、经度不对称。产出为**纬向对称**气候——
   设定中的 Aegis 半球增温 1.5–2 °C、50–60° 哈德里圈、双直射雨季
   均不可表达。`engine/climate_seasonality.py` 的复合倾角模块写好了但尚未接线。
3. **轴倾角 0.0 已正确生效**：无季节；柯本分类中不含任何 D 类
   （无最冷月概念）即此因。极地无季节增温 → EF/ET 冰原占约 13%。

## 后续引擎任务

- [ ] 卫星世界的轨道/光度解析（消除 L=1.0、d=1.0 静默回退），配套重校温室参数
- [ ] 接线 `climate_seasonality.py`（复合倾角、20.1 天快季节）
- [ ] 潮汐锁定经度效应（昼-夜温度对比、Aegis 半球增温）
