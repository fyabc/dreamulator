# 架空世界设计模式

在 dreamulator 数据模型中表达常见天文/地质构型的方法。每个模式说明其科学背景、YAML 编码方式和注意事项。

---

## 特洛伊天体与拉格朗日点

### 科学背景

限制性三体问题中，两个大质量天体（如行星与卫星）的引力场存在五个拉格朗日点（L1–L5），其中 L4 和 L5 分别位于较小天体轨道前方和后方 60° 处，具有动力学稳定性。

处于 L4/L5 的小天体称为**特洛伊天体**（Trojan）。现实中的例子：

- **日-木 L4/L5**：数千颗特洛伊小行星（希腊营 / 特洛伊营）
- **地-月 L4/L5**：理论预测稳定，目前仅发现少量尘埃云（Kordylewski 云）

### 数据编码

特洛伊天体与主天体共享除平近点角外的所有轨道参数，通过 60° 的平近点角差实现等边三角形构型：

```yaml
# stellar.yaml — 地月系统 L4 特洛伊小行星示例

orbits:
  # 主天体（月球）
  - body_id: satellite_moon
    parent_id: planet_earth
    semi_major_axis_au: 0.002569
    eccentricity: 0.0549
    inclination_deg: 5.145
    longitude_ascending_node_deg: 125.08
    argument_of_periapsis_deg: 318.15
    mean_anomaly_epoch_deg: 135.27

  # L4 特洛伊天体 — 同轨道，领先 60°
  - body_id: satellite_companion
    parent_id: planet_earth
    semi_major_axis_au: 0.002569     # 与主天体相同
    eccentricity: 0.0549             # 与主天体相同
    inclination_deg: 5.145           # 与主天体相同
    longitude_ascending_node_deg: 125.08
    argument_of_periapsis_deg: 318.15
    mean_anomaly_epoch_deg: 75.27    # 135.27 − 60° = 75.27

bodies:
  - id: satellite_moon
    name: Moon
    body_type: natural_satellite
    mass_earth: 0.0123
    radius_km: 1737.4
    # ...

  - id: satellite_companion
    name: Companion
    body_type: trojan_asteroid       # 标记为特洛伊天体
    mass_earth: 1.5e-11              # 质量可忽略
    radius_km: 12.0
    # ...
```

### 几何原理

两个天体绕同一中心运行、轨道半径相同、平近点角相差 60° 时，三者构成等边三角形：

```
          Companion (M = 75.27°)
         /                    \
      a                        a
       /                        \
    Earth ————————————————————— Moon (M = 135.27°)
                    a
```

### 注意事项

- **L4（前方 60°）**：`M_trojan = M_primary − 60°`
- **L5（后方 60°）**：`M_trojan = M_primary + 60°`
- 特洛伊天体的质量应远小于两个主天体（通常 ≤ 10⁻⁴ 倍较小主天体质量），否则 L4/L5 不再稳定
- `body_type` 建议使用 `trojan_asteroid` 以区分普通卫星
- 此编码方式表达的是某一时刻（epoch）的静态构型。如需模拟拉格朗日点的长期动力学稳定性，需要引擎层面的限制性三体问题修正
