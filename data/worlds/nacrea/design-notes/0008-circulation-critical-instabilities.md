---
title: "单圈环流的临界不稳定性（未来丰富设定源）"
type: design
tags: [circulation, instability, baroclinic, superrotation, enrichment]
status: proposed
---

# 0008 · 单圈环流的临界不稳定性（未来丰富设定源）

> 记录 Nacrea 单圈环流的两个「临界不稳定性」，作为后续丰富设定的**候选来源**（看情况
> 是否实现）。物理底座见 `docs/knowledge/climatology/atmospheric_circulation.md` §7。

## 背景

Nacrea Ω=0.31 Ω⊕ 是单圈环流（Hadley 胞直抵极地，`hadley_extent_deg=90`）。但单圈不是
「干净稳定」的——它处在两个临界不稳定性的边缘，这是 Nacrea 区别于「干净单圈」的物理
特征，可用来丰富环流/气候纹理。

## ① 弱斜压不稳定（已在引擎，可进一步丰富）

**判据**：罗斯贝变形半径 L_R = NH/f，超临界性 S = (a/L_R)²。

| | f(45°) | L_R | a/L_R | S |
|---|---|---|---|---|
| Nacrea | 3.2e-5 s⁻¹ | ~2800 km | ~2.4 | ~6 |
| 地球 | 1.03e-4 s⁻¹ | ~870 km | ~7.8 | ~61 |

斜压涡旋（Ferrel 胞的驱动机制）在 a/L_R ≈ 1–2 处 onset。Nacrea a/L_R≈2.4 刚好在 onset
之上——**斜压涡旋刚好激活但很弱**，不足以组织成连贯 Ferrel 胞，故「主导单圈 + 弱瞬变
涡旋」（§7.6「涡旋减弱而不为零」）。

- **现状**：`_baroclinic_band`（技术债 20⑥）已从经向温度梯度推导斜压雨带，nacrea 得到
  弱而真实的斜压带（有效幅度 ~560 mm）。
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
若未来引入简化 GCM（roadmap P3「GCM PoC 能正常跑起来」）或需更精细的环流纹理，再按需
实现。

## 参考

- Kaspi, Y., & Showman, A. P. (2015). "Atmospheric dynamics of terrestrial exoplanets
  over a wide range of orbital and atmospheric parameters." *ApJ* 804:60.
- Vallis, G. K. (2017). *Atmospheric and Oceanic Fluid Dynamics*, ch. 5, 12.
- 关联：`docs/knowledge/climatology/atmospheric_circulation.md` §7.1/§7.4/§7.6。
