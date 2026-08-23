# Wave 1 审计：geological-pipeline.md 与当前构造/侵蚀代码字段脱节

> 日期：2026-08-23
> 方法：`scripts/check_doc_refs.py`（引用活性检查）+ 逐字段对照 `pipeline_types.py` / `plate_generator.py` / `tectonic_simulator.py`
> 结论：`docs/design/geological-pipeline.md`（2199 行）引用的 ~20 个字段名与当前代码不符——构造/侵蚀代码经历了一轮字段改名（加 `ocean_`/`plate_`/`boundary_` 前缀、speed 两标量合成 tuple），但文档 §3/§5/§6/§8 未同步。

## 一、已改名（有当前等价）

| 文档旧名（`geological-pipeline.md` 行） | 当前名（`pipeline_types.py` 行） |
|---|---|
| `speed_range`（593） | `plate_speed_range_cm_yr`（51） |
| `speed_min_cm_yr` / `speed_max_cm_yr`（629–630） | 合并进 `plate_speed_range_cm_yr`（tuple，51） |
| `speed_multiplier`（PlateSeed，1557） | `growth_speed_multiplier` |
| `ridge_depth_m`（763） | `ocean_ridge_depth_m`（379） |
| `max_age_myr`（765） | `ocean_max_age_myr`（381） |
| `max_age_depth_m`（766） | `ocean_max_age_depth_m`（382） |
| `influence_radius_km`（650） | `boundary_influence_km`（185） |
| `_ocean_m`（703） | `noise_amplitude_ocean_m`（240）/ `regional_noise_amplitude_ocean_m`（247） |
| `f_orog`（1294） | `orographic_efficiency`（302） |
| `evaporation_rate_mm`（1249） | `evaporation_base_mm`（299） |

## 二、已移除 / 重构（代码中无对应）

| 文档字段（行） | 现状 |
|---|---|
| `remove_net_rotation`（631） | 已移除（无净旋转移除逻辑） |
| `subduction_type`（655、1564） | 已移除（俯冲现由 `_subduction_uplift` 处理，无「类型」枚举） |
| `velocity_threshold_cm_yr`（671） | 已移除 |
| `v_normal_m_yr` / `v_tangential_m_yr`（649–650） | 已移除（现为标量 `_plate_velocity_cm_yr`） |
| `lloyd_tolerance`（261） | 已移除（改为固定 `lloyd_iterations=8`，无收敛判据） |
| `lake_min_area_km2`（1248） | 已移除 |
| `river_order_thresholds`（1247） | 已移除（现为 `river_order` / `classify_rivers`） |
| `detect_lakes_and_endorheic`（1178） | 已移除（现拆为 `is_lake` / `endorheic`） |

## 三、处置

1. 按 §二 把 `geological-pipeline.md` 中旧名替换为当前名；
2. 已移除字段对应的段落（§5 净旋转、§5 边界分类的 `subduction_type`/`velocity_threshold_cm_yr`、§8 湖泊/河流阈值表）标注「已由实现变更移除」或删除，并补当前实现的实际参数名；
3. 修复后重跑 `scripts/check_doc_refs.py` 确认 `geological-pipeline.md` 无 `NOT_IN_CODE`。
