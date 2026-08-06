# Köppen 气候分类

dreamulator 的 Köppen 实现映射与阈值表。本文为 `climate_physics.py:koppen_classify()`
的反写（2026-08），验证对照 Beck et al. (2018)。

## 1. 五主群

| 群 | 判据 | 语义 |
|----|------|------|
| A | t_cold > 18°C | 热带 |
| B | P_annual < 干燥阈值 | 干旱 |
| C | t_cold ∈ [−3, 18)°C 且 t_hot ≥ 10°C | 温带 |
| D | t_cold < −3°C 且 t_hot ≥ 10°C | 大陆性 |
| E | t_hot < 10°C | 极地 |

海洋 cell 输出 `"Ocean"`（不参与分类；海洋分区见 `ocean_provinces.md`）。

## 2. 干旱阈值（B 群）

```
P_threshold = 20 · T_annual + offset
offset = 28 (p_wet > 2·p_dry，夏干型) / 14 (p_dry > 2·p_wet，冬干型) / 0 (均匀)
```

（单位 mm，T 单位 °C；即经典 Köppen 公式的 cm 制 ×10 版本。）
BW/BS 分界：P < 10·T → 沙漠（W），否则草原（S）；h/k 由 T_annual > 18°C 分热/冷。

## 3. 亚型

| 群 | 亚型判据（实现版） | 代码 |
|----|-------------------|------|
| A | Af: p_dry > 60mm；Am: p_dry ≥ 100 − P/25；否则 Aw | 季风/稀树草原分界 |
| C | s: p_wet > 3·p_dry 且 p_dry < 40（地中海型）；w: 冬干；f: 均匀；a/b: t_hot > 22°C | Csa/Csb/Cwa/… |
| D | s/w/f 同 C；a/b/c 按 t_hot 与 t_cold 分级 | Dfb/Dfc/… |
| E | ET: t_hot ∈ (0, 10]；EF: t_hot ≤ 0 | 苔原/冰盖 |

## 4. 输入需求

分类需要**月度极值**（t_cold/t_hot、p_dry/p_wet）。当前管线以简化季节项
（倾角驱动振幅）估计月值——第三字母（s/w/m/f）的准确率因此受限；
roadmap 3A.2 的月度化是直接改进路径。验证现状：群组准确率 53.9%
（v0.11.0 vs Beck 2018，见 `design/climate-validation.md` §7 与
`usage/validation-workflow.md`）。

## 5. 与引擎的对应关系

| 知识 | 引擎 | 状态 |
|------|------|------|
| 五主群 + 亚型阈值 | `climate_physics.py:koppen_classify()` | ✅ |
| 月度极值来源 | `climate_simulator.py:seasonal_temperature()` 简化项 | 🚧（3A.2 月度化） |
| 海洋分区替代 | `ocean_provinces.md` | 📋 3A.5 |

## 参考资料

- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie I.C*.
- Beck, H.E. et al. (2018). "Present and future Köppen–Geiger climate classification maps at 1-km resolution." *Scientific Data 5:180214*.
- Peel, M.C. et al. (2007). "Updated world map of the Köppen-Geiger climate classification." *HESS 11*.
