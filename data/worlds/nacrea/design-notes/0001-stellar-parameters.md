---
title: "恒星与行星系参数设计决策"
type: design
tags: [stellar, parameters, design-rationale]
status: superseded by 0007
checked_against:
  physics: ''
  chemistry: ''
  astronomy: 90fd7148db6e1a2b65b44d33bc15a34f1353f8572eb6abf46eb88645afa37fbb
  geological: 217417b9ecf5de229c6823466dd4554c1e3eb2394cd6b98c7715283dd23c73da
  climate: <no-yaml>
  ecology: <no-yaml>
  civilization: 9ebb3179aacbe9b1db82d2bfec37a16c4582d43f20bc56c3c7463f5f0f3243d5
---

# 0001 · 恒星与行星系参数设计决策

> **更新历史**：2026-08 初版（M2V 红矮星方案，L=0.027→0.0357 L☉，√L 轨道
> 缩放）。2026-09 调参方案 B 落地（K8、0.59 M☉、0.0761 L☉），本文被 0007
> 取代。2026-10-07 路线 1 辐照重标定：[Fe/H]=−0.19 + 年长锁定轨道 →
> Ignis 终参数 0.65 M☉ / 0.1227 L☉ / 4365 K。正文收敛为「现行决策点 +
> 参数快照」，历史推理由 0007（调参档案）与
> `docs/design/proposals/nacrea-insolation-recalibration.md`（路线 1 终裁）承载。

本文是恒星 Ignis 与行星系参数的最早决策记录，具体方案已被 0007/0009 取代。
仍然有效的决策点：

1. **低质量恒星路线**：把宜居世界放在低质量恒星旁（主序寿命极长、宜居带
   近距、潮汐耦合强、耀斑风险可控）的设计动机不变；具体光谱型经两轮重标定
   收敛为**贫金属厚盘老 K 矮星（K6V，[Fe/H]=−0.19）**——5.9 Gyr 龄厚盘
   星的典型成分，贫金属使同质量恒星更热更亮（Eker 2018：L∝Z^−0.1、
   R∝Z^+0.05）。
2. **自变量集 = 质量 + 金属量 + 年龄**（混合输入模式）：光度 L 为引擎
   MLR+Z 修正值（零漂移落地），有效温度 T 为作者光谱钉值（偏差 0.5% 在
   一致性校验阈值内静默通过），半径 R 由 Stefan-Boltzmann 从 (L, T) 导出。
3. **轨道锚定**：Aegis 半长轴由「年长锁定」（99.8 d 历法保持不变）与宜居带
   位置（S_eff = 0.922）联合决定，推导全链见路线 1 提案。

## 现行参数快照（由引擎目录渲染）

| 参数 | 值 | 来源 |
|------|-----|------|
| 光谱型 | K6V | stellar.yaml 名义值（M=0.65 对应 K6/K7、T_eff=4365 对应 K5/K6 界） |
| 质量 M | {{ entities.star_ignis.mass_sol | round(4) }} M☉ | 自变量 |
| 光度 L | {{ entities.star_ignis.luminosity_sol }} L☉ | 引擎 MLR + 金属量修正 |
| 有效温度 T_eff | {{ entities.star_ignis.temperature_k | round0 }} K | 作者光谱钉值（GCM 定标点） |
| 年龄 | {{ entities.star_ignis.age_gyr }} Gyr | 自变量 |
| 主序寿命 | {{ entities.star_ignis.ms_lifetime_gyr | round1 }} Gyr | 引擎（Carroll & Ostlie 2017 标定） |
| 演化进度 τ | {{ entities.star_ignis.evolution_progress }} | 年龄 / 主序寿命 |
| Aegis 半长轴 | {{ entities.planet_aegis.semi_major_axis_au }} AU | 年长锁定 + 宜居带锚定 |
| Nacrea 光照 | {{ entities.satellite_nacrea.instellation_earth_ratio | round2 }} × 地球 | L / a²（S_eff 口径） |

卫星系与行星链的现行架构、认证与红线全部见 0009；形成史与宜居带/凝结线
数值见 0003。
