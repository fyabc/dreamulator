# 审计第一波 T2：文档↔代码数值一致性扫描

> 日期：2026-08-15 · 方法：对 `docs/` 中的数值声明（参数默认值、性能数字、物理常数）
> 逐一对照代码/配置值。参数型矛盾已由技术债 #22（world_parameters.yaml + doc_render）
> 自动化解，本清单扫残余的**物理声明型/默认值型/术语型**矛盾。
> 本轮聚焦两个高密度文件：`docs/design/geological-pipeline.md`、`docs/knowledge/climatology/energy_balance.md`。

---

## 一、结论速览

发现并修复 **9 处**矛盾/漂移；另记录 **2 处待复核/OPEN**。核心模式：

1. **"已废弃"标记撒谎**（文档说废弃了、代码还在用）——PlateVelocity 是典型；
2. **旧方案术语残留**（"洪水填充"已被 Cortial 2019 Voronoi 替代，文档仍当现状描述）；
3. **默认值漂移**（doc 写主力分辨率当默认值）；
4. **命名漂移**（物理参数 `earth_gradient_c` vs 配置字段 `lat_gradient_earth_c`）。

## 二、矛盾清单（已修复）

| # | 位置 | 文档值 | 代码值 | 处置 |
|---|---|---|---|---|
| 1 | geological-pipeline.md:327 | `num_nodes` 默认 200,000 | `pipeline_types.py:45` 默认 100_000 | 已改为 100,000，注明 gaia-m 主力用 200,000 |
| 2 | geological-pipeline.md:651 | "PlateVelocity 将被废弃"（将来时） | `models.py:340` + `voronoi_generator.py:283` 仍在定义/使用 | 已改为"仍在使用（Euler pole 迁移进行中）" |
| 3 | geological-pipeline.md:2010 | "PlateVelocity 废弃·不再使用" | 同上 | 已改为"⚠️ 仍在使用" |
| 4 | geological-pipeline.md:2329 | "PlateVelocity ❌ 废弃" | 同上 | 已改为"⚠️ 仍在使用" |
| 5 | geological-pipeline.md:142-143 | "板块洪水填充而非 Voronoi 最近邻"（当现状描述） | 现方案为 Cortial 2019 加权 Voronoi 重分区（洪水填充已被替代） | 已改为 Cortial 2019 表述 |
| 6 | geological-pipeline.md:658 | `speed_range` "洪水填充速度范围" | 同上 | 已改为"板块生长速度范围" |
| 7 | geological-pipeline.md:2020 | `plate_generator.py` "种子选取 + 洪水填充" | plate_generator.py 用 Cortial 2019 Voronoi | 已改为 Cortial 2019 |
| 8 | energy_balance.md:81 | "代码标定 `earth_gradient_c=40`" | 配置字段实为 `lat_gradient_earth_c`（`climate_simulator.py:150` 传参） | 已改用配置字段名 |
| 9 | test_doc_render.py:332 | 期望 `**1592 倍**` | giant_brightness.md:22 现为 `**约 560 倍**`（1.91/0.0034≈562） | 已改测试锚点为 560 |

## 三、待复核 / OPEN

1. ~~**PlateVelocity 的 Euler pole 迁移是否完成**~~ → ✅ 已解决（选 A，2026-08-15）：
   完成迁移，删除整条 legacy 链——`manager.generate_map()`（零调用方）、
   `terrain_generator.py`、`voronoi_generator.py` 的 `generate_voronoi`/`assign_cells_to_plates`、
   `PlateVelocity` 模型 + `TectonicPlate.velocity` 字段、`maps.py` 的 3 个 "Legacy — ignored"
   字段。`sample_heightmap`（高程导入工作流在用）保留。文档已同步为"已删除"。

2. ~~**§2.5 性能表 500K 分辨率疑似笔误**~~ → ✅ 已修复：`500K` 的"等效栅格分辨率"
   `~4096×2048` 改为 `~6144×3072`（按 √(500K/200K)≈1.58× 递推，介于 200K 与 1M 之间）。

3. **`earth_gradient_c` 命名漂移（代码层）**（OPEN，超出文档扫描范围）：
   物理函数参数 `earth_gradient_c`（`climate_physics.py:191`）与配置字段
   `lat_gradient_earth_c`（`climate.py` 覆写列表 + `terrain_config.yaml`）同名异名，
   建议后续统一命名（偏 `lat_gradient_earth_c`）。

4. ~~**剩余"洪水填充"引用**~~ → ✅ 已处理：6 处"洪水填充"术语改为"Cortial 2019
   Voronoi 剖分"；保留 2 处历史上下文（"替代早期洪水填充"、"洪水填充 → Cortial 2019"）。

## 四、附带发现（代码卫生，非文档矛盾）

- **`climate.py` 的 `_DEFAULT_*` 类常量是死代码**（`climate.py:68-74`）：
  `_DEFAULT_LAPSE_RATE`/`_DEFAULT_LAT_GRADIENT`/`_DEFAULT_GREENHOUSE`/
  `_DEFAULT_EVAP_BASE`/`_DEFAULT_OROGRAPHIC_EFF`/`_DEFAULT_WIND_BLOCK`/
  `_DEFAULT_ITCZ_LAG` 只定义、从未被引用（`run()` 用 `TerrainPipelineConfig`），
  且 `_DEFAULT_LAT_GRADIENT=45.0` 与真实默认 `lat_gradient_c=40.0` 不一致。
  建议删除或与 `TerrainPipelineConfig` 默认值对齐。

## 五、待继续扫描（本轮未覆盖）

本轮聚焦两个高密度文件；以下表面尚未系统核对：

- `docs/design/roadmap.md`（性能数字、快照参数）
- `docs/design/ocean-currents-model.md`、`climate-pipeline.md`、`climate-validation.md`
- `docs/knowledge/astrobiology/alternative-solvents.md`（45 处）、`geology/terrain_synthesis.md`（37 处）
  等物理常数密集文件
- `README.md` / `CLAUDE.md` 中的数字
- 各 §参数表 的完整字段核对（如 geological-pipeline.md 的 `speed_range`/`fill_jitter` 是否仍为真实参数）

## 出处

- 默认值：`src/dreamulator/map/pipeline_types.py`、`src/dreamulator/engine/climate_physics.py`
- 模型：`src/dreamulator/map/models.py`（PlateVelocity:340、TectonicPlate.velocity:363）
- 使用点：`src/dreamulator/map/voronoi_generator.py:283`
- 参数解析：`src/dreamulator/engine/climate.py:154`、`src/dreamulator/map/climate_simulator.py:150`
