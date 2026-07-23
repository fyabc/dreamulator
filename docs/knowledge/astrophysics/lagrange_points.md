# 特洛伊天体与拉格朗日点

> 从 `docs/worldbuilding/design_patterns.md` 迁移。  
> 标签：三体问题、轨道力学、特洛伊天体、拉格朗日点

---

## 科学背景

限制性三体问题中，两个大质量天体（如行星与卫星）的引力场存在五个拉格朗日点（L1–L5），其中 L4 和 L5 分别位于较小天体轨道前方和后方 60° 处，具有动力学稳定性。

处于 L4/L5 的小天体称为**特洛伊天体**（Trojan）。现实中的例子：

- **日-木 L4/L5**：数千颗特洛伊小行星（希腊营 / 特洛伊营）
- **地-月 L4/L5**：理论预测稳定，目前仅发现少量尘埃云（Kordylewski 云）
- **日-地 L4/L5**：理论稳定，但太阳系其他行星的引力扰动使其不稳定

## 关键公式

### 拉格朗日点位置

对于质量比为 $q = m_2/(m_1 + m_2) \ll 1$ 的系统（如行星-小行星），L4/L5 与两个主天体构成等边三角形：

- L4：轨道前方 60°
- L5：轨道后方 60°

### 稳定性条件

L4/L5 稳定的充要条件（Routh 判据）：

$$\frac{m_1 + m_2}{M} > 25$$

其中 $M$ 为特洛伊天体的质量。即**特洛伊天体质量必须远小于两个主天体**（通常 ≤ 10⁻⁴ 倍较小主天体质量）。

## 数据编码

在 dreamulator 中，特洛伊天体与主天体共享除平近点角外的所有轨道参数。

```yaml
# L4 特洛伊天体 — 同轨道，领先 60°
orbits:
  - body_id: satellite_companion
    parent_id: planet_earth
    semi_major_axis_au: 0.002569     # 与主天体相同
    eccentricity: 0.0549             # 与主天体相同
    inclination_deg: 5.145           # 与主天体相同
    mean_anomaly_epoch_deg: 75.27    # 主天体 − 60°
```

- **L4（前方 60°）**：`M_trojan = M_primary − 60°`
- **L5（后方 60°）**：`M_trojan = M_primary + 60°`
- `body_type` 建议使用 `trojan_asteroid`

## 相关文档

- `knowledge/astrophysics/orbital_mechanics.md`（待创建）
- `knowledge/astrophysics/stellar_physics.md`（待创建）

## 参考资料

- [Lagrange point — Wikipedia](https://en.wikipedia.org/wiki/Lagrange_point)
- [Trojan (celestial body) — Wikipedia](https://en.wikipedia.org/wiki/Trojan_(celestial_body))
- Murray, C. D., & Dermott, S. F. (1999). *Solar System Dynamics*. Cambridge University Press.
