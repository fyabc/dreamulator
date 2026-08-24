---
title: "决策记录（ADR）"
type: overview
---

# 决策记录（ADR）

本目录存放 Nacrea 世界的**决策记录**（ADR，Architecture Decision Records），记录跨层设计理由与
关键参数决策的「为什么」。每条决策带状态（`accepted` / `deprecated` / `superseded`），沿用
守护轴约定（`docs/design/harness.md`）。

## 核心设计哲学

Nacrea 世界严格遵循 Dreamulator 的**自变量/因变量分离**原则：

- **自变量（创意设定）**：由世界设计者直接指定的参数，如恒星光度、行星质量、轨道偏心率等。这些是"输入"，反映创作者的意图。
- **因变量（物理推导）**：由引擎根据自变量通过物理公式自动计算的参数，如公转周期、平衡温度、宜居带边界等。这些是"输出"，不允许手动覆盖（除非通过一致性校验）。

这种分离防止了"物理幻想"——确保所有衍生数据在物理上自洽。

## 决策清单

| 编号 | 决策 | 状态 |
|------|------|------|
| [0001](0001-stellar-parameters.md) | 恒星与行星系参数设计决策 | accepted |
| [0002](0002-eccentricity.md) | 偏心率设定依据 | accepted |
| [0003](0003-system-formation.md) | 系统形成史与共振验证 | accepted |
| [0004](0004-satellite-systems.md) | 其他行星的卫星系统设计 | proposed |
| [0005](0005-orbital-inclination.md) | 轨道倾角 9° 的设定原因 | accepted |
| [0006](0006-habitability-protection.md) | 红矮星环境下的宜居保护（耀斑生存 + 撞击概率） | accepted |
| [0007](0007-aegis-seasonal-eccentricity.md) | Aegis 偏心率调高（距离季主导的半球不对称季节） | proposed |
