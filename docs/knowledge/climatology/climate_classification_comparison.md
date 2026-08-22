# 气候分类体系比较

> 基于 dreamulator 项目需求（系外行星气候分类 + 世界构建）的系统性调研。
> 当前引擎使用 Köppen–Geiger 分类，群组准确率 53.9%（vs Beck 2018）。
> 本文评估替代/互补方案，为后续扩展提供依据。

---

## 1. 主流分类体系

### 1.1 Köppen–Geiger（当前实现）

**输入**：年均温、最冷月温、最热月温、年降水、最干/最湿月降水。
**输出**：5 主群（A/B/C/D/E）+ 亚型字母（s/w/f/m 等），~30 类。

**优势**：
- **业界标准**——气候模型验证的默认参照（CMIP6 多模型评估的常用基准）
- 阈值直观（18°C 热带线、−3°C 温带线），实现简单
- 与植被边界的历史经验校准（1920s–30s 的实地对照）

**局限**：
- **季风描述差**（详见 §2）
- **阈值是地球植被的经验拟合**——18°C 热带线、−3°C 温带线在异星物理参数下无先验理由成立
- 中纬度过宽：C 群覆盖从伦敦（海洋性）到北京（大陆性季风）
- 第三字母（s/w/f）对月度数据的质量极其敏感——roadmap 3A.2 简化季节项是当前准确率瓶颈

**dreamulator 现状**：`climate_physics.py:koppen_classify()` 实现了全阈值表，海洋 cell 输出 `"Ocean"`。
验证数据：群组准确率 53.9%、A 类 33.3%、D 类 48.3%（v0.11.0 vs Beck 2018）。

---

### 1.2 Trewartha（1966，1980 修订）

**核心创新**：用"月均温 ≥ 10°C 的月数"替代 Köppen 的单一最冷月阈值来划分中纬度。

| 群 | 判据 | 语义 |
|----|------|------|
| A | 全年各月 ≥ 18°C（同 Köppen） | 热带 |
| C | ≥ 8 个月 ≥ 10°C | **亚热带**（Köppen 无此主群） |
| D | 4–7 个月 ≥ 10°C | **温带** |
| E | 1–3 个月 ≥ 10°C | **寒温带/亚北极** |
| F | 全部月 < 10°C | 极地 |

**优势**：
- **中纬度区分显著优于 Köppen**——伦敦和布里斯班不再同群
- 亚热带 (C) 独立出来，对应植被/土壤/文化边界更准
- 在亚洲和北美大陆效果最好

**局限**：
- **季风处理弱于 Köppen**：Trewartha 刻意淡化了 D 群的冬干/夏干区分（Dw vs Df），认为这些差别在植被/土壤上不显著——这对东亚季风区的描述是退步
- 干旱区 (B) 默认无温度亚型（除非使用可选的 Universal Thermal Scale）
- 海洋性/大陆性分界模糊（Do 类型混入了大陆性气候的地点）

**dreamulator 适配性**：★★★★☆
- 输入与 Köppen 完全相同（T, P 月度极值）——零新增数据需求
- 可作为前端专题图层的第二个"气候透镜"，用户切换 Köppen ↔ Trewartha
- 对 gaia-m 的慢自转（Hadley 扩展到 55°）来说，Trewartha 的亚热带独立主群可能更准确地捕捉中纬度过渡带

---

### 1.3 Thornthwaite（1948）

**核心创新**：引入**潜在蒸散 (PET)**，用能量+水双平衡替代 Köppen 的纯降水阈值。

四个指数：
1. **水分指数 (Im)**：`100 × (P − PET) / PET`——区分湿润/干燥
2. **热效率指数 (TE)**：年 PET（cm）
3. **季节性有效水分变异**
4. **夏季 PET 集中度**

**优势**：
- 最物理严谨的分类体系——能区分"干旱是因为不下雨"还是"干旱是因为太热蒸发太快"
- PET 显式建模了大气-陆地反馈（Köppen 完全不涉及）
- 36 个类别（Feddema 修订版），分辨率优于 Köppen

**局限**：
- **极度繁琐**——完整分类 ~79 步计算，不适合快速可视化
- 某些类别与土壤/植被分布的相关性反而不如更简单的分类（1966 年评估发现地中海灌丛带错配）
- PET 公式（Thornthwaite 原版）被批评为"仅约略的温度-蒸发关系"
- 在 CMIP6 评估中表现仅中等（Navarro et al. 2024："其地图应谨慎使用"）

**dreamulator 适配性**：★★☆☆☆（短期）→ ★★★★☆（长期）
- PET 需要 Hargreaves/Penman-Monteith 等额外计算——但我们已有温度和水汽数据，增加蒸发率计算可行
- 3B 侵蚀管线需要蒸散数据——PET 可能同时服务于多个子系统
- 实施成本显著高于 Trewartha，不建议作为"第二个透镜"的第一候选

---

### 1.4 Holdridge Life Zones（1947）

**核心创新**：基于**植物生理需求**的三角坐标系，而非气象经验阈值。

三个轴：
1. **生物温度 (Biotemperature)**：0–30°C 截断的年均温（<0°C 植物休眠、>30°C 热胁迫）
2. **年降水**
3. **PET 比**（潜在蒸散 / 降水），直接从生物温度和降水推导

输出：**37 个 life zone**（6 个生物温度带 × 8 个降水等级，去除非物理组合）。

**优势**：
- **最适合作系外行星的通用分类**——阈值基于植物生理而非地球特定植被边界
- 计算简单（只需年生物温度，不用月度数据）
- 与植被分布的相关性系统性地优于 Köppen 的部分群
- 可直接输出 `biome` 标签——与我们的生态层 P0（Whittaker 映射）形成交叉验证

**局限**：
- 不同研究对 life zone 的分组不一致（同一套 37 个 zone 可被不同作者归并为 9–13 个类别），导致跨研究对比困难
- 无法表达季节性（第三字母 w/s/f 全部不可用）
- 极地/荒漠的边界定义在不同 HLZ 变体中不统一

**dreamulator 适配性**：★★★★★
- 生物温度直接对接生态层（Whittaker 群系映射用同样的 T/P 输入）
- 不依赖月度极值（当前瓶颈 3A.2 不影响 HLZ 的主群准确率）
- 可作为"独立气候→生态验证层"：Köppen 和 Holdridge 各自分类 → 交叉验证 → 两种分类一致 → 高置信；一致度低 → 标记该 cell 为"分类不确定区"

---

### 1.5 Whittaker-Ricklefs Biomes

严格来说不是气候分类，而是**生物群系分类**（9 类）。已在我们生态层 P0 中使用。

### 1.6 类比分类（Venus/Earth/Mars analogue）

**核心思想**：不是逐 cell 分类，而是按**整行星的入射辐射（insolation）**把岩石行星归入太阳系三类类比。

| 类比 | 判据 | 物理 |
|------|------|------|
| **金星类比（Venus Zone）** | 入射辐射高于「失控温室」内边界 | 海洋完全蒸发、碳循环断裂、厚 CO₂ 大气 |
| **地球类比（Earth analogue）** | 在经典宜居带内 | 液态水海洋 + 硅酸盐碳循环 |
| **火星类比（Mars analogue）** | 入射辐射低于宜居带外边界 | 太冷，水冻结/逃逸 |

表面温度近似 `T_surf = T_eq + G_a`（G_a 为温室增量：金星 +511 K、地球 +34 K、火星 −0.2 K）。

- **优势**：输入极简（仅 insolation + 反照率），适合「这颗行星整体是什么气候」的粗粒度判定。
- **局限**：无空间分辨率，不能描述行星内部气候分异；对「宜居带内但潮汐锁定」的行星不区分（同为 Earth 类比，但眼球行星与地球截然不同）。
- **dreamulator 适配性**：★★★☆☆ — 可作 `astronomy` 层输出「行星类比标签」的快速起手（宜居带计算已含 Selsis 边界），但不能替代气候层的逐 cell 分类。

### 1.7 双稳态 regime（runaway greenhouse vs snowball）

**核心思想**：气候系统有强正反馈 → **多稳态**。同一颗行星（给定恒星、大气、含水量）可能落入两种截然不同的稳定态之一：

- **失控温室态（runaway greenhouse）**：水汽正反馈使海洋沸腾、水全进大气（金星化）。
- **雪球态（snowball）**：冰反照率正反馈使全球冰封（火星化 / 雪球地球）。

**关键结论（Forget & Leconte 2014）**：

- 双稳态的存在依赖**有效的冷阱（cold trap）**——潮汐锁定或极低倾角有利于冷阱形成 → 双稳态更易出现在 M/K 矮星周围。
- 存在**临界自转率**（约 2:1 锁相）：低于它，多稳态消失、冰反照率反馈被阻尼；**1:1 锁相的行星只有一种气候态**。

- **dreamulator 适配性**：★★★☆☆ — 当前引擎是单稳态（给定参数 → 唯一气候），没有建模「历史依赖/迟滞」。这是比「分类」更深的一层：引擎是否该输出「可能落入的多个气候态」。与 gaia-m 慢自转（接近 1:1 锁相）直接相关——按 Forget & Leconte，gaia-m 可能已处于「无双稳态」的临界自转区。

---

## 2. Köppen 对季风气候的失败（为什么中国不教它）

**核心问题**：Köppen 使用**最湿月与最干月降水比 > 10**作为季风判据，该阈值存在三个系统性缺陷：

### 2.1 过宽的亚热带
- 河南和越南北部同归 **Cwa**（冬季干旱的亚热带）——尽管实际气候体验差异巨大
- 华南大部分水稻种植区被归入 **Cfa**（均匀降水），因为冬夏降水差不超过 10 倍阈值——但它们确实有显著的干湿季

### 2.2 对短旱季的过度敏感
- 越南仅因 12–2 月旱季（3 个月旱 / 9 个月雨）被标为"强季风型"
- 但"3 个月旱 + 9 个月雨"和"3 个月雨 + 9 个月旱"在 Köppen 框架中都归入 Cwa——定性完全不同
- 大叻（越南南方高原）是近乎完美的温带海洋性气候（Cfb），仅因 3 个月旱季被归入 Cwa

### 2.3 10 倍降水比的双重含义
- P_wet/P_dry > 10 可能因为旱季极其干旱（真干旱气候），也可能因为雨季极其潮湿（真季风气候）——两种不同的物理机制，Köppen 无法区分
- 越南旱季仍有 20–30 mm 月降水（超过华北淮河以北），却在 Köppen 中与真正的干旱区同获"w"码

**中国教材的替代方案**：温度带 × 干湿区的二维分类（热带/亚热带/温带/寒带 × 湿润/半湿润/半干旱/干旱），不记忆字母代码，直接理解两个核心变量的物理含义。这是一种更"第一性原理"的教学方法。

---

## 3. 对 dreamulator 的启发

### 3.1 各体系互补，而非互斥

| 体系 | 对我们扮演的角色 |
|------|-----------------|
| **Köppen** | 保持为主分类（业界标准，模型验证的参照系） |
| **Trewartha** | 第二个"气候透镜"（前端切换，中纬度更准） |
| **Holdridge** | "异星验证层"（系外行星不依赖地球阈值）+ 生态桥接 |
| **Thornthwaite** | 远期——3B 侵蚀/水文管线需要 PET 时自然引入 |

### 3.2 实施优先级

| 阶段 | 内容 | 状态 |
|------|------|------|
| 当前 | Köppen–Geiger（已有） | ✅ |
| P2 | **Trewartha 补充分类**：纯函数模块 `engine/climate_physics.py:trewardha_classify()` + 前端专题图层切换 | 📋 新增 |
| P2 | **Holdridge Life Zones**：`engine/ecology_physics.py:holdridge_life_zone()` + 与 Whittaker 交叉验证 | 📋 新增 |
| P3 | **Thornthwaite PET 模块**：随 3B 侵蚀管线一同引入 | 远期 |

### 3.3 交叉验证策略（设计模式）

对每个 cell 输出**三种**分类标签：

```
cell.climate_classifications:
  koppen: "Cfa"
  trewartha: "DOak"         # 温带海洋性（解决 Cfa 过宽）
  holdridge: "warm_temperate_moist_forest"
```

前端提供一个"气候分类一致性"图层——三种分类一致的 cell 绿色、两种一致的黄色、三种都不一致的红色——帮助世界构建者识别"气候诊断高不确定区"。

---

## 参考

- Köppen, W. (1936). "Das geographische System der Klimate." *Handbuch der Klimatologie I.C*.
- Trewartha, G.T. (1966). *The Earth's Problem Climates*. University of Wisconsin Press.
- Thornthwaite, C.W. (1948). "An approach toward a rational classification of climate." *Geographical Review 38*.
- Holdridge, L.R. (1947). "Determination of world plant formations from simple climatic data." *Science 105*.
- Beck, H.E. et al. (2018). "Present and future Köppen–Geiger climate classification maps at 1-km resolution." *Scientific Data 5:180214*.
- Navarro, A. & Tapiador, F.J. (2024). "Climate classification systems for validating Earth System Models." *Environmental Research: Climate 3*(4).
- Selsis, F., Kasting, J.F., Levrard, B., Paillet, J., Ribas, I., & Delfosse, X. (2007). "Habitable planets around the star Gliese 581?" *A&A 476*（宜居带内边界 = 失控温室，外边界 = 最大温室；Venus/Earth/Mars 类比的基础）.
- Forget, F. & Leconte, J. (2014). "Possible climates on terrestrial exoplanets." *Phil. Trans. R. Soc. A 372*（双稳态 regime：runaway greenhouse vs snowball；临界自转率与潮汐锁定的关系）.
- 知乎 (2024). "为什么中国大陆的中学地理教科书不教柯本气候分类法？"
