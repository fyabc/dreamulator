---
title: "Nacrea 决策台账的现行依据与复核范围"
type: design-note
tags: [guard, astronomy, habitability, evidence]
date: 2026-11-17
status: accepted
checked_against:
  physics: ''
  chemistry: ''
  astronomy: fe421edc3daf7d5104a9c86733d56de1ee1261b0e41fa2438f4a7453ca83bf6b
  geological: 0743a3776ce8651c7d8c43c406deb42c5dbc09c4d675931f4e4659a429147071
  climate: <no-yaml>
  ecology: <no-yaml>
  civilization: f25d0cd65920a64490031592737fa87a0af40bf5023dd30261903484cb0e556f
---

# 0024 — 决策台账的现行依据与复核范围

## 1. 采用范围

本记录承接[形成史 0003](0003-system-formation.md)、[卫星设计 0004](0004-satellite-systems.md)和
[宜居保护 0006](0006-habitability-protection.md)的现行结论。形成过程和卫星命名继续沿用已采用的设定，
现今数值以输入文件和引擎实体目录为准。形成史属于有理论依据的历史设定，动力学验证只覆盖实际积分的构型与时段。
卫星架构的动力学依据由[0009](0009-satellite-architecture.md)和[0014](0014-tidal-heat-long-term-statistics.md)维护。

本次为十一条缺少机器检查依据的已接受记录登记七层 YAML 输入指纹和完整正文基线，并保持其正文及接受状态。
这些基线从本次复核开始生效；原接受时点没有保存的基线仍没有历史证据。机器检查能发现后续输入变化、正文变化和
已模板化事实的变化，手写数字的重新测量仍按各记录的采用范围执行。

## 2. 形成史与卫星系统的现今参数

以下数值读取天文学层的 `system_catalog.yaml`。轨道半长轴表示天体轨道的大小；希尔半径表示该天体的引力影响范围，
它本身不能证明卫星能长期存活。距离单位 AU 是地球与太阳的平均距离。

| 行星 | 现今日心半长轴 | 引擎计算的希尔半径 | 已采用的卫星数量与类型 |
|---|---|---|---|
| Ember | {{ entities.planet_ember.semi_major_axis_au }} AU。 | {{ entities.planet_ember.hill_radius_km | round1 }} km。 | 设定中没有卫星。 |
| Crucible | {{ entities.planet_crucible.semi_major_axis_au }} AU。 | {{ entities.planet_crucible.hill_radius_km | round1 }} km。 | 设定中保留一颗近轨道小卫星 Cinder。 |
| Boreal | {{ entities.planet_boreal.semi_major_axis_au | round(7) }} AU。 | {{ entities.planet_boreal.hill_radius_km | round1 }} km。 | 设定中有三颗非共振、宽间距的规则卫星。 |
| Glacis | {{ entities.planet_glacis.semi_major_axis_au | round(7) }} AU。 | {{ entities.planet_glacis.hill_radius_km | round1 }} km。 | 设定中有一颗规则内卫星和一颗逆行捕获外卫星。 |
| Sentinel | {{ entities.planet_sentinel.semi_major_axis_au }} AU。 | {{ entities.planet_sentinel.hill_radius_km | round1 }} km。 | 设定中有两颗不规则捕获卫星。 |

Ember 与 Crucible 仍位于保守宜居带内边缘以内。Ignis 的光度为 {{ entities.star_ignis.luminosity_sol }} 倍太阳光度，
保守宜居带的内边缘为 {{ entities.star_ignis.habitable_zone.runaway_greenhouse_au | round(6) }} AU，
外边缘为 {{ entities.star_ignis.habitable_zone.max_greenhouse_au | round(6) }} AU。
这一区间由一维气候阈值近似推出，不能单独认证某个世界的宜居性。

Ember 无卫星和 Crucible 有 Cinder 的设定继续采用。当前引擎计算两颗行星的自转周期与公转周期并不完全相同，
因此本记录采用数值周期，并将它们描述为近同步自转。它们的自转周期分别为
{{ entities.planet_ember.rotation_period_days }} 和 {{ entities.planet_crucible.rotation_period_days }} 地球日，
公转周期分别为 {{ entities.planet_ember.period_days }} 和 {{ entities.planet_crucible.period_days }} 地球日。
无卫星的形成原因和 Cinder 的远期坠落属于历史与演化设定，当前希尔半径检查只提供几何约束。

Umbra 的半径为 {{ entities.satellite_umbra.radius_km | round1 }} km，公转周期为
{{ entities.satellite_umbra.period_days }} 地球日。其宽间距构型与潜在冰下海洋设定继续采用，
数百万年的稳定性筛查和内部热流估算分别按 0004 的范围解释。

## 3. 宜居保护的事实与设定依据

Ignis 的质量为 {{ entities.star_ignis.mass_sol }} 倍太阳质量，年龄为 {{ entities.star_ignis.age_gyr }} Gyr，
其中 1 Gyr 是十亿地球年。引擎估算的主序寿命为 {{ entities.star_ignis.ms_lifetime_gyr | round1 }} Gyr。
恒星年龄提供活动随年龄衰减的背景依据；当前世界没有恒星 XUV 辐射历史和大气逃逸的完整计算。
早期保留水和大气，以及现今活动较温和，继续作为采用的世界历史与环境设定。

Aegis 的赤道表面磁场输入为 {{ entities.planet_aegis.magnetic_field_strength_ut | round1 }} μT，
Nacrea 的自身磁场输入为 {{ entities.satellite_nacrea.magnetic_field_strength_ut | round1 }} μT。
引擎在 Nacrea 轨道处估算的母行星磁场为 {{ entities.satellite_nacrea.parent_magnetic_field_at_orbit_ut }} μT。
前两项是作者输入，后一项是磁场空间衰减的近似计算。磁场会影响带电粒子运动，XUV 光子仍能到达大气。
Heller 与 Zuluaga 的研究讨论了巨行星磁环境对卫星的影响，也指出辐射带的风险；这支持分析磁环境的必要性。
早期大气能否保留还取决于辐射、恒星风、初始挥发分与补给过程。

现行潮汐参数采用[0014](0014-tidal-heat-long-term-statistics.md)的 CTL045 方案，永久形状参数
J₂ 为 0.0008，洛夫数 k₂ 为 0.20、h₂ 为 0.40。CTL 表示固定时滞潮汐模型；洛夫数描述天体对潮汐的形变响应。
Nacrea 当前轨道偏心率为 {{ entities.satellite_nacrea.eccentricity }}，这是历元快照。
偏心率阻尼时标的近似计算为 {{ entities.satellite_nacrea.tidal_e_damping_timescale_yr | round0 }} 地球年，
长期受迫变化与倾角潮的热流使用 0014 的积分结果。

现今热流有两种明确的口径：[0021](0021-heat-co2-ice-history.md)的轨道检查点历史参考取中心两万年平均，
当代值约为 0.19346 W/m²；地质生产的 `tidal_heat_history.yaml` 使用归一化简化序列，当代输入为 0.18 W/m²。
热流、熔融核与长期磁场之间的演化联系继续作为机制解释，现有计算没有认证磁场贯穿全部地质史。

Aegis 的引力聚焦、吸收和弹射会共同改变小天体通量。现有工程没有给出撞击体种群的联合积分，
因此撞击率的净倍数和大撞击重现期属于叙事量级设定。挥发分补给与偶发撞击冬天的叙事继续采用，
后续需要定量撞击率时再按相应种群和轨道做验证。

## 4. 其余记录的复核结论

以下记录的采用范围保持不变。每条记录的 `baseline_registered_at` 和 `review_scope` 标明本次登记日期与范围，
人工证据列表保存在 `evidence_sources` 中。

| 记录 | 本次复核后沿用的结论与检查依据 |
|---|---|
| [0011](0011-civilization-earth-comparison.md) | 地球类比保留在设计档案中。该记录的气候表是历史 EBM 构建结果，现今对外气候引用 0013。 |
| [0012 附录](0012-appendix-gcm-runs.md) | 运行配置与复现命令作为实验档案保留。现行 CO₂ 扫描采用 20 分钟步长；较早的 45 分钟步长实验按各自配置解释。 |
| [0012](0012-climate-gcm-calibration.md) | GCM 定标与 CO₂ 情景范围继续采用。现行配置由正典运行清单和分支的 `climate_metadata.json` 核查；地球参照偏差按原记录登记。 |
| [0013](0013-climate-canon-source.md) | 对外气候继续采用 `gcm-t42-712`，根世界 EBM 继续服务开发。该记录引用的字段来源旁车文件当前缺失，本次来源核查使用现有运行清单、冻结清单和分支气候元数据。 |
| [0014](0014-tidal-heat-long-term-statistics.md) | CTL045、J₂、洛夫数与当代历元的选择继续采用，输入文件与记录相符。百万年积分只支持已计算时段，十亿年灭绝重现期仍待研究。 |
| [0017](0017-heat-flow-mountains.md) | 热管火山与板块输热共存的解释继续采用。`terrain_config.yaml` 的平均板块速度为 12.5 cm/年，火山活动输入为 3；输热分配属于该记录列明的近似估算。 |
| [0018](0018-geography-inventory.md) | 地理测量方法与 2026-10-22 的快照统计保留。地形重生成后按同一方法重新测量，快照数字保持原日期。 |
| [0020](0020-tropical-cyclones-storm-tracks.md) | 每个当地轨道年约七个热带气旋的创作设定继续采用，依据是生成潜势的量级换算；温带风暴轴按高频 GCM 统计解释。 |
| [0021](0021-heat-co2-ice-history.md) | 最近两百万年的分期、时序与变化量级继续作为参考历史，数据由附表保留。历史冰库存估算与当前画布冰厚各有计算口径。 |
| [0022](0022-insolation-recalibration.md) | 恒星质量与年长锁定的辐照方案继续采用，现行输入与最终裁决相符。历史候选表继续按文首历史范围解释。 |
| [0023](0023-world-island-dissected-highland.md) | 世界岛中央深切高地的裁决继续采用，已安装画布的完整重生成仍待执行，对外地理文字随重生成结果更新。 |

Nacrea 的 CO₂ 输入为 {{ (entities.satellite_nacrea.atmosphere.composition.CO2 * 1000000) | round0 }} ppm，
引擎温室参数为 {{ entities.satellite_nacrea.atmosphere.greenhouse_factor | round1 }} K，自转周期为
{{ entities.satellite_nacrea.rotation_period_days }} 地球日，轴倾角为 {{ entities.satellite_nacrea.axial_tilt_deg }}°。
Aegis 的半长轴为 {{ entities.planet_aegis.semi_major_axis_au }} AU，轨道偏心率为
{{ entities.planet_aegis.eccentricity }}。天文学目录从瞬时轨道根数推得的 Aegis 周期为
{{ entities.planet_aegis.period_days }} 地球日；冻结 GCM 配置的固定年长为 99.819592 地球日。
两者分别用于瞬时轨道推导与固定轨道气候实验。GCM 的名义 712 ppm 支路按清单中的最终总压折算为约 711.5 ppm，
这是加上 CO₂ 分压后的总压口径，0012 的运行表保留这一实际值。

本记录的动态模板读取两种世界上下文共有的天文学实体。现今 GCM 气候统计继续由 0012 与 0013 维护，
根世界和气候分支各自的聚合统计按其模型解释。

## 5. 来源与方法

- [天文输入](../layers/astronomy/input/stellar.yaml)和[地质输入](../layers/geological/input/planets.yaml)定义现今自变量，天文学实体目录提供上述动态事实。
- [地形配置](../layers/geological/input/terrain_config.yaml)和[热流历史输入](../layers/geological/input/tidal_heat_history.yaml)定义生产采用值。
- [守护轴管线](../../../../docs/design/pipelines/guard-ledger.md)规定输入、事实和台账状态的检查方式。
- [Heller 与 Zuluaga（2013）](https://arxiv.org/abs/1309.0811)讨论系外卫星的磁环境与宜居性，DOI 为 10.1088/2041-8205/776/2/L33。

台账检查通过的含义是登记的引用与依据一致。科学结论按每个模型的适用范围、独立参照与数值验证判定。
