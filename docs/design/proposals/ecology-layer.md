# 生态层设计方案

> 状态：设计阶段（P0 已实施 v0.20.0；本版重写 P1–P3 架构，2026-08-12）
> 配套：路线图见 [roadmap.md](roadmap.md)；数学模型见 [ecological_mathematical_models.md](../knowledge/ecology/ecological_mathematical_models.md)
> 竞品调研：异星生命推演引擎见 [competitor-analysis.md](competitor-analysis.md)；《外星生物圈》方法论见 `private/plans/video/alien-biosphere-analysis.md`

---

## 〇、当前状态与设计决策

### 0.1 当前状态

P0 已全链路闭环（v0.20.0）：`EcologyEngine` 读气候数据，逐 cell 输出 `biome`（Whittaker 群系）、`npp_gc_m2_yr`（Miami NPP）、`domesticable_tags`（可驯化标签），写入 `cvt_mesh.json` + `ecology_summary.yaml`；前端有 Whittaker 群系 / NPP / 文明摇篮三个专题图层。

本版聚焦 P1–P3 的架构设计，解决两个根本问题：
1. 如何把生态层从"逐 cell 静态标签"升级为"有物种、有谱系、有食物网的推演体系"；
2. 如何让同一套架构同时容纳【类地球】【奇幻】【异星】三种生态风格。

### 0.2 设计决策记录（2026-08-12）

| # | 决策 | 理由 |
|---|------|------|
| 1 | **异星实例化器纳入设计**，接口先行、分阶段实现 | 架构上统一三种风格，避免异星推演成为"另起炉灶"的孤儿 |
| 2 | **生物地理分区先做 Udvardy 量级**（~193 省），预留更精细量级（WWF TEOW ~825 区）的接口 | Udvardy 更适合架空世界尺度；接口用 N 级嵌套而非硬编码 3 级 |
| 3 | **谱系树兼顾"精选 + 程序化填充"**：少数锚定物种详细设定，大部分叶子程序化生成简单设定 | 关系骨架先行的自然结果——精选物种是锚点，程序化物种是填充 |
| 4 | **实例化器互斥**，一个世界选一种风格；实现按简单程度排序（类地球 → 奇幻 → 异星） | 简单优先；互斥避免"混合风格"的约束冲突复杂度 |
| 5 | **异星推演核心（body plan / 演化树 / 食物网）留主仓，不抽独立包**；仅「物种图像输出」单独成模块（类比 `narrator.py`）；是否抽 `packages/specbio` 记为**开放问题** | 关系骨架（生态位/食物网/谱系）风格无关、独立可用（Madingley 功能群先例）；「具体物种设计」依赖关系骨架，抽出去不完整（conlang 包停更教训，见 `private/plans/video/alien-biosphere-analysis.md`） |

---

## 一、核心架构：关系骨架 + 实例化器

### 1.1 一句话

> **生态层 = 先建"生态位-营养级-谱系-生物地理"的关系骨架（风格无关），再用实例化器填充物种（风格相关）。**

这个架构直接回应用户的原始直觉（"把物种与物种关系剥离开，先构建关系，再填充物种"），并把它落地为项目既有的 `input/derived` 分离。

### 1.2 理论依据（有生态学主流支撑，无需范畴论背书）

| 理论 | 关键点 | 出处 |
|------|--------|------|
| **niche model** | "先铺生态位轴、再填物种"的生成式食物网模型，结构完全先于物种身份 | Williams & Martinez (2000), *Nature* 404:180–183 |
| **生态位理论** | 生态位自 Hutchinson 起定义在**环境/资源坐标轴**上，物种是"落入"坐标空间的点，而非反过来 | Hutchinson (1957)；Elton (1927)；Grinnell (1917) |
| **功能性状生态学** | 先定义性状轴与基础生态位，再把物种投影到性状空间 | McGill et al. (2006), *TREE* 21:178–185 |
| **网络生态学** | 食物网拓扑（连接度、模体、嵌套性）是独立于物种身份的结构属性 | Dunne et al. (2002)；Bascompte et al. (2003)；Milo et al. (2002) |

范畴论（olog 的 schema/instance 分离、把谱系树建成 operad 的 Phyl、范畴化反应网络）提供了更形式化的语言，但属于"锦上添花"而非"必要前提"。详见 [competitor-analysis.md](competitor-analysis.md)。

### 1.3 与 input/derived 的映射

```
关系骨架  ── 生态位轴 / 营养级图 / 谱系拓扑 / 生物地理分区 ── 风格无关
   │
   │  映射为：input 层（人类/LLM 指定"有什么关系"），或 derived 层（引擎从气候/地质导出）
   │
物种实例  ── body plan + 性状 + 名称 ── 风格相关
   │
   │  映射为：derived 层（类地球/异星实例化器推导），或 input 层（奇幻硬设定）
```

这符合 CLAUDE.md 既有约定："LLM 只改 input，引擎负责 derived——防止 LLM 幻想物理结果"。**结构骨架是 input/derived 皆可，物种实例是 derived（奇幻除外）。**

### 1.4 三种风格 = 同一种骨架下的三种实例化器

```
关系骨架（风格无关）—— 生态位轴 + 营养级图 + 谱系拓扑 + 生物地理分区
        │
        ├── 实例化器 A【类地球】：地球已知 body plan 模板 + 趋同演化填充
        │        （= 现有 P0 的延续，最成熟）
        │
        ├── 实例化器 B【奇幻】：人工 authored 物种硬设定插入
        │        （违反物理约束的物种 = input 层，标记 hard-set）
        │
        └── 实例化器 C【异星】：物理约束 → body plan 推导
                 （Karl Sims 式有向图基因型 + 约束评分函数，P3）
```

**关键洞察**：关系骨架是风格无关的。一条龙仍然占据"顶级掠食者"生态位、挂在谱系树的某分支、参与食物网——只是它的 body plan 是**人写的**（违反平方-立方律），而非推出来的。这对应 vision 的"硬度光谱"：类地球 = 高硬度（全推导）、异星 = 中高硬度（推导但约束不同）、奇幻 = 低硬度（硬设定）。

**诚实标注**：能全自动推导的只有类地球和异星的一部分（body plan、生态位、食物网）。奇幻中违反物理的部分（魔法、龙喷火、精灵永生）**无法推导**，只能作为 input 硬设定挂进结构骨架。这与"推演和硬设定的混合"定位一致。

---

## 二、关系骨架层（风格无关）

关系骨架由六个子结构组成，覆盖"坐标 → 能量流动 → 谱系 → 空间 → 地质中介 → 时间动态"。

### 2.1 生态位轴空间（Niche Axis Space）

**定义**：一个 n 维坐标空间，每维是一个环境/资源变量。这是 Hutchinson 超体积的离散化版本。

| 维度 | 来源 | 说明 |
|------|------|------|
| 温度 | 气候引擎 `temperature_C` | 直接导出 |
| 降水 | 气候引擎 `precipitation_mm` | 直接导出 |
| 光照 / PAR | 天文引擎（恒星光谱）+ `par_ratio` | 光合有效辐射，异星关键 |
| 营养级 | 引擎计算 | 生产者 / 初级消费者 / 次级 / 顶级 / 分解者 |
| 资源类型 | 引擎计算 | 光能 / 化能 / 碎屑 / 捕食 |
| 生境 | 地质引擎 `elevation` + 海陆 | 冠层 / 底栖 / 开阔平原 / 洞穴… |

**要点**：生态位轴**先于物种存在**——它是气候/地质引擎输出的直接衍生，不依赖任何具体生物。这正是"关系先行"的最底层。

### 2.2 生态位填充（功能群 / Niche Filling）

**定义**：在生态位轴上按规则生成"功能群（functional guild）"——即"待填充的生态位槽"。功能群是关系结构的一部分，**还不是物种**（如"大型食草动物""顶级掠食者""分解者"）。

**可借鉴的实现**（二选一或组合）：

| 方案 | 来源 | 做法 |
|------|------|------|
| **niche model** | Williams & Martinez (2000) | 在摄食层级轴上给每个物种分配 niche 值，按"每个消费者吃掉轴上连续一段猎物"生成食物网 |
| **Miche Tree** | Thrive / Auto-Evo（MIT 开源） | 生态位 = "能量来源的层级树"，每个节点挂一个"物理约束→适应度"评分函数，物种在叶子处竞争 |

**输出**：功能群列表 + 食物网拓扑（谁吃谁）。这对应数学骨架里 §4.3 的"体型排序生成营养连接"规则。

**食物网的完整性**——食物网必须是**闭合回路**，且不止捕食一种关系：

| 环节 | 说明 | 来源 |
|------|------|------|
| **生物量金字塔** | NPP → 各营养级生物量，经 Lindeman 10% 定律（5%–20%）逐级衰减。这是"生态 → 文明承载力"的直接前驱 | Lindeman (1942) |
| **分解者回路** | 碎屑 → 分解者 → 养分 → 生产者，是"下行"能量流动。生态学里"地上食物网 vs 地下食物网"是经典二分，缺分解者则食物网不闭合 | — |
| **互惠关系** | 捕食/竞争之外的传粉、种子传播、共生。**传粉**是"植被→动物→植被"的闭环，对"可驯化作物"（农业）至关重要 | Bascompte et al. (2003) |

### 2.3 谱系拓扑（Phylogenetic Topology）

**定义**：演化树的分叉结构 + 时间轴，**叶子未命名**——只有"拓扑 + 枝长"，物种后填。

| 元素 | 说明 |
|------|------|
| 分叉结构 | 适应辐射、异域成种、生物交换节点 |
| 时间轴 | 与地质年代表对齐（大灭绝、大氧化、适应辐射） |
| 关键创新 | 体节特化（tagmosis）、幼态延续（neoteny）等驱动分化的标记 |

**参考**：范畴论上这就是 Baez & Otter (2017) 的 Phyl operad（谱系拓扑作为独立数学对象）；实操上是《外星生物圈》的"进化枝思维"（先有祖先 body plan，再沿进化枝派生）。

**决策 #3 的落地**：谱系树支持**混合 detail_level**——少数"锚定物种"（人类精选，详细设定）作为树的骨架节点，大部分叶子由实例化器程序化填充为"简单设定"物种。

### 2.4 生物地理分区（Udvardy 量级 + 精细接口）

**定义**：把陆域划分为嵌套的生物地理区（realm → province → biome）。

**决策 #2 的落地**：先做 Udvardy 量级（8 realms → ~193 provinces → 14 biomes），但数据模型用 **N 级嵌套**而非硬编码 3 级，为后续升级到 WWF TEOW（825 ecoregions）预留接口。

| 层级 | Udvardy 量级 | 可扩展目标 |
|------|-------------|-----------|
| 大区 realm | 8 | 8 |
| 省 province | ~193 | ecoregion ~825 |
| 群系 biome | 14 | 14 |

**数据模型**：
```yaml
biogeographic_region:
  id: "6.9"                    # realm.province 编码（Udvardy 风格）
  name: "澳大利亚中央沙漠"
  level: 2                     # 嵌套深度（N 级可扩展）
  parent: "6"                  # 上级 region
  realm: "Australasian"
  biome: "desert"
  cells: [1234, 5678, ...]     # 关联的 Voronoi cell
```

### 2.5 土壤层（Soil）

**定义**：地质母岩 + 气候 → 土壤类型 → 植被类型 → 农业潜力。这是"地质 → 生态"最关键的**中介**——它决定了同一气候下能长什么植被、以及农业能种什么。

| 输入 | 来源 | 对生态的影响 |
|------|------|-------------|
| 母岩 / 基岩类型 | 地质引擎（crust_composition） | 土壤矿物组成 → 养分含量 |
| 温度 + 降水 | 气候引擎 | 风化速率、淋溶程度 → 土壤成熟度 |
| 地形（坡度/排水） | 地质引擎（elevation） | 侵蚀 vs 沉积 → 土层厚度 |

**输出**：土壤类型（简化为 USDA 土纲量级：氧化土/干旱土/淋溶土/新成土…）+ 肥力指标。土壤肥力是**文明农业潜力**的直接输入——比"气候 → 可驯化标签"的查表更物理。

**简化策略**（P1）：不模拟完整土壤形成过程（那是地质引擎的事），而是用"母岩 + 气候 → 土纲查表 + 肥力分级"的一步映射。留接口给未来地质层的风化/侵蚀引擎。

### 2.6 生态过程与动态（时间 + 空间）

关系骨架的**动态维度**——区别于 §2.3 谱系的"演化时间"（百万年），这里是"生态时间"（几十年到几百年）和"空间动态"。

| 过程 | 说明 | 对下游的影响 |
|------|------|-------------|
| **演替（succession）** | 扰动后先锋种 → 顶极群落的恢复序列 | r/K 策略偏向、群落稳定性 |
| **扰动 / 火（disturbance & fire）** | 火、干旱、风暴的频率与强度 | **草原/稀树草原的维持依赖火**（抑制乔木、释放养分）——这是"草原 → 谷物农业"文明摇篮的关键 |
| **物候（phenology）** | 生物生命周期与季节同步（迁徙/冬眠/落叶/开花） | 落叶 = f(降水季节性)；迁徙 = f(PSI, 体型)（《外星生物圈》EP8） |
| **扩散 / 迁徙（dispersal & migration）** | 活体物种的空间动态（季节迁徙、生物交换、入侵） | 生物地理分区从"静态"变"动态"（《外星生物圈》EP10/13） |

**简化策略**：P1 只做"扰动/火频率"和"物候"两个（它们直接决定群系和农业潜力）；P2 再做演替和扩散的完整动态。

---

## 三、物种实例化层（风格相关，互斥）

### 3.1 统一 Species 数据模型

三种实例化器输出**同一种** Species 结构，区别只在 `body_plan` 的填法和 `detail_level`。

```yaml
species:
  id: "species_xxx"
  name: "xxx"
  detail_level: detailed | summary | skeletal   # 精选 / 简设 / 程序化（决策 #3）

  phylogeny:
    parent: "species_xxx"        # 或 null（根）
    divergence_mya: 123.4
    clade: "xxx"                 # 所属进化枝

  niche:
    trophic_level: primary_consumer
    energy_source: herbivory
    biome: "temperate_grassland"
    habitat: "open_plains"
    body_mass_kg: 450.0          # 代谢标度理论的关键参数

  body_plan:                     # 实例化器决定填法（见下）
    symmetry: bilateral
    # ...

  traits: {}                     # 关键性状字典
  domestication:                 # 喂给文明层
    large_herbivores: high
    staple_crops: low
    draft_animals: high
```

**`detail_level` 语义**（决策 #3）：
- `detailed`：锚定物种，人工精选，含完整设定（名称、外观、习性、文明关联）
- `summary`：程序化生成的"有名字的物种"，含基本设定（生态位 + 身体结构 + 一句话描述）
- `skeletal`：程序化填充的"仅有参数"的物种（只占生态位，无独立叙事）

### 3.2 实例化器接口

```
Instantiator(
    skeleton: RelationSkeleton,   # 关系骨架（生态位槽 + 谱系位置 + 物理约束）
    world: PhysicalWorld,         # 世界物理参数（重力/大气/光谱/溶剂）
) -> list[Species]
```

**互斥**（决策 #4）：一个世界在 `world.yaml` 里指定一个 `ecology.style`，实例化器按 style 选择，不做混合。

### 3.3 实例化器 A：类地球（Terrestrial Template）

**最成熟，P0 的直接延续。**

- 输入：生态位槽（功能群）+ 世界物理（接近地球时适用）
- 做法：功能群 → 地球已知 body plan 模板的映射（"大型食草动物"→马/牛型，"顶级掠食者"→猫科型），趋同演化
- 输出：`detail_level` 多为 `summary`/`skeletal`，少数锚定物种 `detailed`
- 复用：P0 的 `domesticable_tags` 就是它的雏形（按群系查表）

### 3.4 实例化器 B：奇幻（Fantasy Authored）

**简单（纯 input），但需要标记"违反物理约束"。**

- 输入：authored 物种清单（精灵、巨龙、元素生物…）
- 做法：把 authored 物种**挂进关系骨架**——分配生态位槽、挂到谱系树、连入食物网
- 关键：body plan 不推导，直接是人写的；违反物理约束的部分（喷火、永生、魔法）标记为 `hard_set: true`，不参与物理一致性校验
- 输出：`detail_level` 多为 `detailed`（奇幻物种天然是"精选"的）

**与类地球的关系**：关系骨架完全相同，区别只在 D 层——奇幻物种是"硬设定填入"而非"推导生成"。

### 3.5 实例化器 C：异星（Alien Derivation）

**最难（P3），接口先行。**

- 输入：物理约束（重力、大气成分与密度、光谱、溶剂化学、温度范围）+ 关系骨架
- 做法：物理约束 → body plan 推导，两条可借鉴路径：

| 路径 | 来源 | 参数化方式 |
|------|------|-----------|
| 有向图基因型 | Karl Sims (1994) | 基因型 = 有向图（节点=身体块，连接=关节参数），同图编码形态 + 神经 |
| 声明式解剖 | Dwarf Fortress raws | `BODY`（部位）+ `BODY_DETAIL_PLAN`（组织层）+ `TISSUE/MATERIAL` 三层分离 |

- 约束推导层：把 SFWA/Lore Architect 的 checklist 硬编码为**评分函数**——重力→支撑结构、大气→呼吸/感官、能量源→营养级、溶剂化学→结构材料（CaCO₃ vs CaSO₄ vs SiO₂）
- 关键哲学：**"知道规则才能打破规则"**（《外星生物圈》方法论）——从物理约束出发，不从地球 body plan 出发

**⚠️ 前置依赖：化学层缺口**。异星实例化器的"生化约束"（溶剂化学 → 结构材料 → body plan）依赖 chemistry 层的元素丰度/溶剂信息，而 chemistry 层是当前 DAG 最薄弱的层（无引擎）。因此异星的生化约束部分短期只能**硬设定**（在 input 里手写"海洋是 H₂S 溶剂、结构材料是 CaSO₄"），长期需补一个 chemistry 层（哪怕只是"元素丰度 → 可用结构材料"的查表）。物理约束（重力/大气/光谱）不依赖 chemistry 层，可直接用天文/地质引擎现有输出 + 纯函数（平方-立方律等）。

**"不局限于地球特征"的实现方式**：
1. 自变量是物理约束，不是地球 body plan；
2. 平方-立方律是普遍约束（纯几何，与行星无关）；
3. 结构材料取决于海洋化学，而非默认 CaCO₃；
4. 对称性/头化/分节由"运动需求/固着滤食/环境"驱动，而非默认两侧对称。

**⚠️ 前置依赖二：地质史时间序列缺口**。「给定时间上地质史演变 → 演化树」需要跨越
数亿年的大陆漂移时间序列输入，而当前地质层只有静态 `geography.yaml`（无时间序列）。
没有它，演化树的「异域物种形成 / 大灭绝 / 生物交换」等时间事件无法触发。此缺口比
化学层缺口更根本，需在 P3b 之前补一个地质史时间序列（哪怕先是最简的「超大陆裂解 →
重拼」预设脚本）。

**子任务分解（对应 roadmap 3B.5 P3a/b/c）**：

| 子任务 | 交付 | 依赖 |
|---|---|---|
| P3a body plan 推导 | 物理约束 → 身体结构（纯函数：平方-立方律 / 对称性 / 头化 / 分节） | 天文/地质参数，无 DAG 依赖，**可先做**（早于 P1 骨架） |
| P3b 演化树 | 地质史时间序列 + 气候 → cladogenesis（异域 / 适应辐射 / 大灭绝 + 关键创新引擎） | P3a + 地质史时间序列 |
| P3c 图像输出 | body plan → 外观图（procedural 线稿起步，后接 LLM 生成） | P3a，独立模块（类比 `narrator.py`） |

**归属**：P3a/b 留主仓（见 §0.2 决策 #5）；P3c 单独成模块。是否抽 `packages/specbio`
待生态层 P1/P2 骨架成熟后重评。

---

## 四、与文明层的接口

生态层输出直接作为文明层 ODE 的参数（详见 [ecological_mathematical_models.md](../knowledge/ecology/ecological_mathematical_models.md) §10）：

```
生态输出                    →  文明模型参数
─────────────────────────────────────────────
NPP (gC/m²/yr)             →  HANDY: γ（资源再生率）
carrying capacity          →  HANDY: K
domesticable_tags          →  文明类型（agricultural / pastoral / maritime / 渔猎采集）
ecosystem_services         →  文明经济基础（木材/药材/授粉/土壤肥力/淡水）
niche_construction_potential →  文明技术路径（河狸筑坝 → 灌溉 → 城市）
智慧概率                    →  facultative vs obligate sapience（《外星生物圈》EP15）
灭绝风险（Allee 阈值）       →  SDT 崩溃触发器
```

**生态服务与生态位构建是"生态 → 文明"的桥**：

- **生态服务（ecosystem services）** 是 `keystone_resources` 的完整展开——不是"单个关键资源"，而是"木材/药材/授粉/土壤肥力/淡水/防洪"的资源集合，直接构成文明的经济基础。
- **生态位构建（niche construction）** 是生物**主动改造环境**的能力（河狸筑坝、白蚁丘、人类开垦）。**文明本质上就是大规模 niche construction**——这是生态层到文明层过渡最自然的概念桥：从"生物适应环境"到"生物改造环境"，文明是这条谱系的终点。

**三种风格的文明层差异**：
- 类地球文明：农业/畜牧路径，与地球历史可比
- 奇幻文明：无视 body plan 约束（精灵无需农业即可维持，因为有魔法），走"硬设定"文明路径
- 异星文明：body plan 约束技术路径（无手→无法用工具→智慧上限），走"物理约束文明"路径

---

## 五、可视化设计（前端）

复用成熟标准，不造轮子。可视化调研见 [competitor-analysis.md](competitor-analysis.md)（P0 三图层已实施）。

| 优先级 | 可视化 | 成熟方案 | 状态 |
|--------|--------|---------|------|
| **已有** | Whittaker 群系 / NPP / 文明摇篮 | — | ✅ v0.20.0 |
| **P1** | 生物地理分区图层 | WWF TEOW / Udvardy 三级嵌套 + 色块 | 📋 |
| **P1** | 植被/土地覆被图层 | Copernicus LCCS 分类与配色 | 📋 |
| **P2** | 交互式谱系树 | D3 collapsible + phylo.io 自动折叠；对标 Species: ALRE 的 clade diagram | 📋 |
| **P2** | 地质年代表 | ICS 螺旋配色 + ChronoZoom 缩放 | 📋 |
| **P2** | 食物网图 | d3-foodweb（营养级分层 + 力导向） | 📋 |
| **P2** | 生态位/性状空间 2D | wallace PCA 双标图 + hypervolume 凸包 | 📋 |
| **远期** | 双树对比（branch 联动） | phylo.io 双树对比 | 📋 ⭐差异化 |

**⭐ 差异化机会**：双树对比直接对应项目的 **branch 系统**——在 geological 层分叉 → 比较不同海陆分布下演化出的两棵生态树。这是现有工具都没有、而 DAG/branch 架构天然支持的。

---

## 六、实施路线

按"关系骨架先行，实例化器从简单到复杂"分阶段。

| 阶段 | 内容 | 依赖 | 复杂度 |
|------|------|------|--------|
| **P1** | 关系骨架：生态位轴 + 功能群填充 + 食物网（含生物量金字塔）+ 土壤层 + 生物地理分区（Udvardy）+ 类地球实例化器 | 气候/地质引擎输出 | 中 |
| **P2** | 谱系拓扑 + 食物网闭合（分解者回路/互惠）+ 生态过程（演替/扰动/火/物候/扩散）+ 前端可视化（谱系树/时间轴/食物网/生物地理图层） | P1 | 中 |
| **P3** | 异星实例化器（物理约束 → body plan，含生化约束——依赖化学层，短期硬设定） | P1 骨架 + 天文参数 + 化学层 | **高** |
| **P1.5** | 奇幻实例化器（authored 硬设定，纯 input，可插队） | P1 骨架 | 低 |

**实现顺序**（决策 #4 简单优先）：P1（类地球）→ P1.5（奇幻，纯 input 最简单）→ P2（谱系 + 可视化）→ P3（异星，最难）。

> 注：P1.5 奇幻实例化器虽然排在 P2 之前（实现简单），但它依赖 P1 的关系骨架；而 P2 的谱系拓扑是 P1 的另一半。实际排期可把"P1 骨架 + P1.5 奇幻 + P2 谱系"作为一个连贯批次，异星（P3）单独远期。

> 另：P3a（body plan 推导纯函数）不依赖关系骨架，可作为异星推演的探路石**提前实现**（见 §3.5）；这不改变 P3 主体（演化树 + 挂接）排在最后的定位。

---

## 参考资料

- Williams, R. J., & Martinez, N. D. (2000). "Simple rules yield complex food webs." *Nature* 404:180–183.
- Hutchinson, G. E. (1957). "Concluding Remarks." *Cold Spring Harbor Symposia on Quantitative Biology* 22:415–427.
- McGill, B. J., Enquist, B. J., Weiher, E., & Westoby, M. (2006). "Rebuilding community ecology from functional traits." *TREE* 21(4):178–185.
- Karl Sims (1994). "Evolving Virtual Creatures." *SIGGRAPH*.
- Thrive / Auto-Evo（MIT 开源）: <https://github.com/Revolutionary-Games/Thrive>
- Dwarf Fortress raws: <https://dwarffortresswiki.org/index.php/DF2014:Raw_file>
- Udvardy, M. D. F. (1975). "A Classification of the Biogeographical Provinces of the World." *IUCN Occasional Paper* 18.
- Olson, D. M. et al. (2001). "Terrestrial Ecoregions of the World." *BioScience* 51:933–938.
- *Alien Biosphere* by Biblaridion（方法论提取见 `private/plans/video/alien-biosphere-analysis.md`）
- **数学方程**：`docs/knowledge/ecology/ecological_mathematical_models.md`
