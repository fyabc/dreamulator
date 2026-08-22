# 海洋气候分区 — Longhurst 生物地球化学省份

> 海洋学中等价于 Köppen 气候分类的全球分区系统。
> 用于替代单一 "Ocean" 标签，为海洋 cell 赋予有意义的气候/生态分区。

---

## 1. 概述

**Alan R. Longhurst** (1995, 1998, 2007) 提出将全球海洋划分为层级化的生物地球化学省份。该系统依据物理海洋过程（洋流、上升流、混合层深度）和生物地球化学特征（浮游植物生长模式、营养盐分布）进行分区。

**层级结构**：
```
4 大群系 (Biomes)
  └── ~54 生物地球化学省份 (Provinces)，各有四字母代号
```

---

## 2. 四大群系 (Biomes)

### 2.1 极地群系 (Polar)

- **位置**：高纬度（北极、南大洋）
- **SST**：< 4°C，有季节性海冰
- **物理特征**：
  - 冬季极深混合层（>500 m）
  - 夏季浅层 stratification（冰融化驱动）
  - 光照极端季节变化（极昼/极夜）
- **生产力**：短暂但强烈的夏季藻华
- **驱动因素**：辐射季节极端 + 海冰 + 深层营养上涌

### 2.2 西风带群系 (Westerlies)

- **位置**：中纬度 30°–60°（所有大洋）
- **SST**：5–20°C，强季节变化
- **物理特征**：
  - 冬季深混合层 → 营养盐补充
  - 春夏 stratification → 藻华
  - 受西风带风应力驱动
- **生产力**：春季/秋季两次藻华（温带双峰型）
- **驱动因素**：季节混合层变化 + 中尺度涡旋

### 2.3 信风带群系 (Trade-Winds / Tropical-Subtropical)

- **位置**：低纬度 0°–30°（开阔大洋）
- **SST**：> 20°C，季节变化小
- **物理特征**：
  - 永久 stratification（暖表层 + 冷深层）
  - 副热带环流中心：极寡营养（"海洋沙漠"）
  - 赤道上升流：周期性营养盐补充
  - 信风驱动表层辐散
- **生产力**：环流中心极低；赤道带中等（上升流）
- **驱动因素**：永久 stratification + 信风 + ITCZ

### 2.4 海岸边界群系 (Coastal Boundary Zone)

- **位置**：大陆架、边缘海、沿岸上升流区
- **SST**：变化大（受沿岸流和陆地影响）
- **物理特征**：
  - 西边界暖流（Gulf Stream、黑潮）→ 高温高盐
  - 东边界寒流（Humboldt、加那利、Benguela）→ 低温 + 上升流
  - 大陆架：浅水混合，河流输入
  - 上升流区：风驱动深层冷水上涌
- **生产力**：全球最高（上升流区 + 大陆架）
- **驱动因素**：风应力旋度 + 海岸地形 + 河流输入

---

## 3. 分类判据（简化实现用）

对于 dreamulator 气候引擎，不需要完整的 54 省分类。用物理代理变量实现简化版：

### 输入变量（引擎已有或计划中）

| 变量 | 来源 | 状态 |
|------|------|------|
| 纬度 `lat` | CVT mesh cell | ✅ |
| 海表温度 SST | climate_simulator | ✅ |
| 风场 `wind[cell]` | climate_simulator | ✅ |
| 海岸距离 | 邻接图 BFS | ✅ 可计算 |
| 洋流方向 | Phase 3A.3 | 🚧 |
| 风应力旋度（上升流指标） | ∇×wind | ✅ 可从风场推导 |

### 简化分类规则

```python
# Level 1: Biome
if dist_to_coast < 500 km:
    biome = COASTAL
elif abs(lat) > 60 or SST < 4:
    biome = POLAR
elif abs(lat) > 30:
    biome = WESTERLIES
else:
    biome = TRADES

# Level 2: Province (需要洋流)
if biome == COASTAL:
    if western_boundary and warm_current:
        province = COASTAL_WBC
    elif eastern_boundary and upwelling:
        province = COASTAL_EBC
    else:
        province = COASTAL_SHELF
elif biome == TRADES:
    if abs(lat) < 5:
        province = EQUATORIAL
    else:
        province = GYRE_CENTER
elif biome == POLAR:
    if permanent_ice:
        province = POLAR_ICE
    else:
        province = POLAR_SEASONAL
elif biome == WESTERLIES:
    province = WESTERLIES  # 暂不细分
```

---

## 4. 与 Köppen 的类比

| 陆地 Köppen | 海洋 Longhurst | 共同物理驱动 |
|------------|---------------|-------------|
| E (极地/冰原) | POLAR | 高纬 + 低温 + 辐射不足 |
| D (大陆性) | WESTERLIES | 中纬 + 季节变化 + 气旋活动 |
| A (热带) | TRADES (赤道部分) | 低纬 + 高温 + 对流 |
| B (干旱) | TRADES (环流中心) | 下沉气流 + 永久 stratification = "海洋沙漠" |
| C (温带) | COASTAL (暖流区) | 中纬 + 海洋调节 |

---

## 5. 颜色方案建议（前端图层）

| Province | 颜色 | 含义 |
|----------|------|------|
| POLAR_ICE | #a8d8ea (浅冰蓝) | 永久冰 |
| POLAR_SEASONAL | #6bb5d9 (冷蓝) | 季节冰 |
| WESTERLIES | #4a90b8 (深蓝绿) | 温带大洋 |
| TRADES_GYRE | #1a5276 (暗蓝) | 副热带"沙漠" |
| EQUATORIAL | #27ae60 (绿) | 赤道上升流 |
| COASTAL_WBC | #e74c3c (暖红) | 西边界暖流 |
| COASTAL_EBC | #8e44ad (紫) | 东边界寒流/上升流 |
| COASTAL_SHELF | #f39c12 (橙黄) | 大陆架 |

---

## 参考资料

- Longhurst, A.R. (1995). "Seasonal cycles of pelagic production and consumption."
  *Progress in Oceanography*, 36, 77–167.
  https://www.sciencedirect.com/science/article/abs/pii/0079661195000151

- Longhurst, A.R. (2007). *Ecological Geography of the Sea*, 2nd Edition.
  Academic Press.
  https://shop.elsevier.com/books/ecological-geography-of-the-sea/longhurst/978-0-12-455521-1

- Reygondeau, G. et al. (2013). "Dynamic biogeochemical provinces in the global ocean."
  *Global Biogeochemical Cycles*, 27, 1046–1058.
  https://agupubs.onlinelibrary.wiley.com/doi/10.1002/gbc.20089

- Fay, A.R. & McKinley, G.A. (2014). "Global open-ocean biomes: mean and temporal variability."
  *Earth System Science Data*, 6, 273–284.
  https://essd.copernicus.org/articles/6/273/2014/essd-6-273-2014.pdf

- Longhurst code — Wikipedia:
  https://en.wikipedia.org/wiki/Longhurst_code

- Marine Regions — Longhurst Provinces:
  https://www.marineregions.org/gazetteer.php?p=details&id=22538

- NASA CCE — Bioinformatic Mapping of Ocean Biogeochemical Provinces:
  https://cce.nasa.gov/mtg06_ab_presentations/109_196_ab_pres.pdf
