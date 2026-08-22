# USDA 土壤分类（Soil Taxonomy）与肥力

> 为 dreamulator 生态引擎的土壤层提供参考。土壤是"地质母岩 × 气候"的中间产物，
> 直接决定植被类型与农业潜力（文明层的输入）。

---

## 一、USDA 12 土纲（Soil Order）

USDA Soil Taxonomy 的最高分类等级是 **土纲（soil order）**，共 12 纲，按
诊断特征（诊断层、诊断特性、土壤水分/温度状况）划分。以下按"环境形成条件"
归组（诊断特征以 USDA 官方定义为准）。

| 土纲 | 英文 | 形成环境 / 诊断特征 | 肥力 |
|------|------|--------------------|:----:|
| 软土 | Mollisol | 深厚暗色表层（mollic epipedon），温带草原，有机质丰富 | 高 |
| 淋溶土 | Alfisol | 温带森林，中等淋溶，黏化层 | 高 |
| 变性土 | Vertisol | 膨胀收缩黏土，干湿季交替（裂隙 + 翻转） | 高 |
| 火山灰土 | Andisol | 火山灰母质，低容重、高持水 | 高 |
| 有机土 | Histosol | 高有机质（湿地/泥炭），水饱和 | 中 |
| 始成土 | Inceptisol | 弱发育，仅有雏形层（cambic） | 中 |
| 新成土 | Entisol | 极年轻，无诊断层（陡坡/新沉积/沙丘） | 中 |
| 老成土 | Ultisol | 温暖湿润，高度淋溶，盐基饱和度低（亚热带） | 低 |
| 氧化土 | Oxisol | 强烈风化，铁铝氧化物富集（热带雨林） | 低 |
| 灰土 | Spodosol | 冷湿酸性，铁铝淋溶淀积（北方针叶林） | 低 |
| 干旱土 | Aridisol | 干旱，蒸发 > 降水，钙积/盐积 | 低 |
| 冻土 | Gelisol | 永冻层，高纬/高山 | 低 |

**肥力梯度逻辑**：高肥力 = 有机质丰富（mollisol）、中等淋溶保留养分（alfisol）、
火山灰矿物新鲜（andisol）；低肥力 = 强风化淋失（oxisol/ultisol）、酸性贫瘠
（spodosol）、缺水（aridisol）、低温（gelisol）。

---

## 二、dreamulator 的简化映射（`classify_soil`）

引擎不模拟土壤形成过程（那是地质层的事），而是用"气候(T/P) + 母岩 → 土纲查表"的
一步映射。当前仅用温度与降水判定 9 纲；其余 3 纲需额外输入，留接口：

| 土纲 | 需要的额外输入 | 现状 |
|------|--------------|------|
| Andisol | 火山活动（lithosphere.volcanic_activity） | 预留 |
| Histosol | 湿地/排水状况 | 预留 |
| Entisol | 坡度/沉积年龄 | 预留（暂并入 fallback） |

**判定阈值**（`engine/ecology_physics.py:classify_soil`）：

```
T ≤ 0°C                          → gelisol   （永冻）
P < 250 mm                       → aridisol  （干旱）
T > 18°C（热带）:
    P ≥ 2000 → oxisol（强风化雨林）
    P ≥ 1000 → ultisol（高度淋溶）
    else     → vertisol（干湿季稀树草原）
5 < T ≤ 18°C（温带）:
    P ≥ 1500 → ultisol（温带雨林）
    P ≥ 700  → alfisol（温带森林）
    P ≥ 300  → mollisol（温带草原）
    else     → aridisol
0 < T ≤ 5°C（寒带）:
    P ≥ 500  → spodosol（北方针叶林）
    P ≥ 200  → inceptisol（寒温带灌丛）
    else     → gelisol
海洋/非大陆地壳                   → None
```

肥力由土纲查表（`_SOIL_FERTILITY`），输出 `high` / `medium` / `low` 三档。

**与文明层的接口**：`soil_fertility` 是"农业潜力"的直接输入——比 P0 的
"气候 → 可驯化标签"更物理（同一气候下，mollisol 草原可种谷物，oxisol 雨林
则因养分淋失而贫瘠）。

---

## 三、参考来源

- Soil Survey Staff. *Keys to Soil Taxonomy*, 13th ed. USDA-NRCS (2022) —
  https://www.nrcs.usda.gov/resources/guides-and-instructions/keys-to-soil-taxonomy
- USDA-NRCS. *Soil Taxonomy* 12 orders — https://www.nrcs.usda.gov/conservation-basics/natural-resource-concerns/soil/soil-taxonomy
- 中文土纲名称对照：中国土壤分类与 USDA 土纲对应关系（氧化土=铁铝土、软土=黑土、淋溶土=棕壤等）。

## 相关文档

- `../geology/` — 母岩/火山活动（andisol 的输入来源）
- `../climatology/` — 温度/降水（土纲判定的输入）
- `ecological_mathematical_models.md` §6 — NPP 与土壤碳周转
