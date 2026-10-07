---
title: "宽 Hadley 环流的临界不稳定性（未来丰富设定源）"
type: design
tags: [circulation, instability, baroclinic, superrotation, enrichment]
status: proposed
---

# 0008 · 宽 Hadley 环流的临界不稳定性（未来丰富设定源）

> 记录 Nacrea 宽 Hadley 环流的两个「临界不稳定性」，作为后续丰富设定的**候选来源**
> （看情况是否实现）。物理底座见 `docs/knowledge/climatology/atmospheric_circulation.md` §7。
>
> **更新历史**：2026-09 初版（单圈假设，hadley_extent_deg=90）。2026-10-07 路线 1
> GCM 定标：Hadley 外缘按 ExoPlaSim 六臂同值校准为 52°（`terrain_config.yaml`
> hadley_extent_deg=52，极圈浅极地胞 52–90°），背景段随之改写；两个不稳定性
> 候选的地位不变。

## 背景

Nacrea Ω≈0.32 Ω⊕（恒星日 3.14 d）是**宽 Hadley 慢自转体制**：Hadley 胞外缘
52°（GCM 定标值），其外为浅弱的极地胞，**没有组织化的 Ferrel 胞**——但也不是
「干净的单圈」：它处在两个临界不稳定性的边缘，这是 Nacrea 区别于「干净宽
Hadley」的物理特征，可用来丰富环流/气候纹理。

## ① 弱斜压不稳定（已在引擎，可进一步丰富）

**判据**：罗斯贝变形半径 L_R = NH/f，超临界性 S = (a/L_R)²。口径：N = 0.01 s⁻¹、
对流层顶标高 H = 8 km（NH = 80 m/s）；f = 2Ω sin45°，Ω = 0.319 Ω⊕（恒星自转
3.138 d）；a = 6817 km。

| | f(45°) | L_R | a/L_R | S |
|---|---|---|---|---|
| Nacrea | 3.28e-5 s⁻¹ | ~2440 km | ~2.8 | ~7.8 |
| 地球 | 1.03e-4 s⁻¹ | ~780 km | ~8.2 | ~67 |

斜压涡旋（地球 Ferrel 胞的驱动机制）在 a/L_R ≈ 1–2 处 onset。Nacrea a/L_R≈2.8
刚好在 onset 之上——**斜压涡旋刚好激活但很弱**，不足以组织成连贯 Ferrel 胞。
结合 GCM 定标（ExoPlaSim T21 四臂同值：Hadley 外缘 52.6° → `hadley_extent_deg=52`，
2026-10-07），现行体制图景 = **宽 Hadley（0–52°）+ 高纬浅极地胞（52–90°）的
两圈体制**：斜压活动集中于 52° 外缘附近与高纬锋区，而非地球的 30–60° Ferrel
带（§7.6「涡旋减弱而不为零」）。

- **现状**：`_baroclinic_band`（技术债 20⑥）从经向温度梯度推导斜压雨带，nacrea
  得到弱而真实的斜压带（幅度口径以现行构建的诊断输出为准，待 GCM 轮 02 的
  风暴带输出复核）。
- **未来丰富**：若想体现「临界」性质，可给瞬变涡旋加显式弱波动（斜压驻波分量 / 弱
  风暴路径），而非现在的纯定常斜压带。

## ② 赤道惯性不稳定 / 超旋转（未实现，Venus/Titan 型）

慢自转（Ω 小）→ 赤道 f→0 → 赤道区**边际惯性不稳定**，角动量可在赤道集中 → **赤道超
旋转**（Venus/Titan 典型特征）。Kaspi & Showman (2015)：慢自转 → 单一副热带急流 +
赤道超旋转。

- **现状**：引擎无急流核心结构、无赤道超旋转（§5「无急流核心结构」）。
- **未来丰富**：可给慢自转行星加弱赤道超旋转（赤道风场反转），影响 ITCZ 水汽辐合与
  降水分布。

## 决策

暂不实现，两条都留作「看情况」的丰富设定源。当前引擎的弱斜压带已足够体现「临界」。
GCM offline-oracle 已上线（`src/dreamulator/gcm/`，ExoPlaSim T21 harness；nacrea
定标判决见 `docs/design/proposals/nacrea-insolation-recalibration.md` 与
`climate-gcm-plan.md`）——未来若需更精细的环流纹理，实现前先用 GCM 输出仲裁
参数带（本轮 hadley_extent_deg 47→52 即为 GCM 仲裁的实例）。

## 参考

- Kaspi, Y., & Showman, A. P. (2015). "Atmospheric dynamics of terrestrial exoplanets
  over a wide range of orbital and atmospheric parameters." *ApJ* 804:60.
- Vallis, G. K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 5, 12.
- 关联：`docs/knowledge/climatology/atmospheric_circulation.md` §7.1/§7.4/§7.6。
