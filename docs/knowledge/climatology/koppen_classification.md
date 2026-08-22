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

## 2. 二字母与三字母含义

Köppen 代码 = **主群字母**（首字母）+ **二字母（降水特征）** + **三字母（温度特征）**。
二字母多为德语缩写（Köppen 为德国人）：f=feucht（湿润）、s=sommertrocken（夏干）、
w=wintertrocken（冬干）、m=Monsun（季风）、W=Wüste（沙漠）、S=Steppe（草原）、
T=Tundra（苔原）、F=Frost（冰盖）；h=heiß（热）、k=kalt（冷）。a/b/c/d 无德语词源，
只是温度等级的顺次字母（a 最热 → d 最冷）。

### 二字母（降水特征）

| 字母 | 含义 | 用于群 |
|------|------|--------|
| f | 全年湿润，无干季 | A, C, D |
| m | 季风，短干季但年降水充足 | A |
| w | 冬干（旱季在低太阳半年） | A, C, D |
| s | 夏干（旱季在高太阳半年） | A, C, D |
| W | 沙漠 | B |
| S | 草原/半干旱 | B |
| T | 苔原 | E |
| F | 冰盖 | E |

### 三字母（温度特征）

| 字母 | 含义 | 用于群 |
|------|------|--------|
| h | 热（年均温 ≥ 18°C） | B |
| k | 冷（年均温 < 18°C） | B |
| a | 炎夏（最热月 ≥ 22°C） | C, D |
| b | 暖夏（最热月 < 22°C 且 ≥ 4 个月 ≥ 10°C） | C, D |
| c | 凉夏（1–3 个月 ≥ 10°C） | C, D |
| d | 严冬（最冷月 < −38°C） | D |

> 组合规则：A、E 群无三字母；B = W/S + h/k；C = s/w/f + a/b/c；D = s/w/f + a/b/c/d。
> `As`（热带夏干型）理论存在但极罕见，本实现不输出（A 群只出 Af/Am/Aw）。

## 3. 干旱阈值（B 群）

```
P_threshold = 20 · T_annual + offset
offset = 280 (暖季湿：p_warm > 0.7·P_annual) / 140 (均匀) / 0 (冷季湿：p_cold > 0.7·P_annual)
```

（单位 mm，T 单位 °C；即经典 Köppen 公式的 cm 制 ×10 版本。`p_warm`/`p_cold`
为最暖/最冷 6 个月的降水合计，由 `warm_cold_half_precip` 给出。）
BW/BS 分界：P < 10·T → 沙漠（W），否则草原（S）；h/k 由 T_annual > 18°C 分热/冷。

## 4. 亚型

| 群 | 亚型判据（实现版） | 代码 |
|----|-------------------|------|
| A | Af: p_dry > 60mm；Am: p_dry ≥ 100 − P/25；否则 Aw | 季风/稀树草原分界 |
| C | s: 最暖 6 月中最干月 < 最冷 6 月中最湿月 / 3 且 < 40mm（地中海型）；w: 最冷 6 月中最干月 < 最暖 6 月中最湿月 / 10；f: 均非；a/b/c 按 t_hot/t_cold | Csa/Csb/Cwa/… |
| D | s/w/f 同 C（D 的 s 无 40mm 阈值）；a/b/c 按 t_hot 与 t_cold 分级 | Dfb/Dfc/… |
| E | ET: t_hot ∈ (0, 10]；EF: t_hot ≤ 0 | 苔原/冰盖 |

> **s/w 季节判别（2026-08 修复）**：早期实现以 `p_wet > 3·p_dry` 判「干夏」，
> 只看干湿比、不看季节——被固定 0.4 的 `p_wet/p_dry ≡ 2.33` 掩盖，月度化后暴露，
> 导致「冬干」的副热带被误标为 Csb。现改为**季节感知**（Kottek et al. 2006）：
> 按月度温度分最暖/最冷半年，干季在暖半年 = s、在冷半年 = w。需传入
> `seasonal_precip_extremes()` 的四个半年极值；缺省时回退到旧的干湿比启发式。

## 5. 空类（理论存在、地球上无现代类比）

柯本矩阵里存在一个**理论成立、但经典教科书称地球上没有任何气象站符合**的亚型：**Dsd**（夏干型极端严寒大陆性）。

- **条件**：D（最冷月 < 0°C）+ s（最暖半年最干月 < 最冷半年最湿月 / 3，D 群无 40mm 阈值）+ d（最冷月 < −38°C，且 1–3 个月 ≥ 10°C）。
- **为何地球上不存在**：`d`（−38°C）要求深居大陆腹地（西伯利亚型），那里冬季被西伯利亚高压控制、**冬干**（只会是 `w`/`f`，不是 `s`）；而 `s`（夏干冬雨）要求大陆西海岸（地中海式），海洋调节使冬季极难降到 −38°C。两个条件在地球地理上**互斥**。
- **对 dreamulator 的意义**：Dsd 是「排列组合存在、但需要特殊地理配置才非空」的哨兵空类。异星上若出现「高纬西海岸 + 极强大陆性 + 夏干」的配置，Dsd 才可能非空——可用于检验引擎「不把地球地理硬编码成分类边界」。

## 6. 输入需求

分类需要**月度极值**（t_cold/t_hot、p_dry/p_wet）与**半年降水极值**
（最暖/最冷 6 月的最干/最湿月，供 s/w 季节判别）。月度数据来自光照驱动的
`compute_seasonal_climate()`（`engine/climate_seasonality.py`，roadmap 3A.2 月度化）。

## 7. 与引擎的对应关系

| 知识 | 引擎 | 状态 |
|------|------|------|
| 五主群 + 亚型阈值 | `climate_physics.py:koppen_classify()` | ✅ |
| 月度极值来源 | `climate_seasonality.py:compute_seasonal_climate()` | ✅（3A.2） |
| 半年降水极值 | `climate_seasonality.py:seasonal_precip_extremes()` | ✅ |
| 海洋分区替代 | `ocean_provinces.md` | 📋 3A.5 |

## 参考资料

- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie I.C*.
- Beck, H.E. et al. (2018). "Present and future Köppen–Geiger climate classification maps at 1-km resolution." *Scientific Data 5:180214*.
- Peel, M.C. et al. (2007). "Updated world map of the Köppen-Geiger climate classification." *HESS 11*.
