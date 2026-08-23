# AI CLI 命令组设计

> 来源：2026-07-25 讨论记录（提取自早期设计笔记）。

---

## 1. 概述

将现有的 `narrate` 命令扩展为独立的 `ai` 子命令组，引入 **Entity ID 机制** 作为精确寻址手段。

## 2. 基础命令

| 子命令 | 功能 | 示例 |
|--------|------|------|
| `ai narrate` | 现有叙述功能迁移 | `dreamulator ai narrate --id aegis` |
| `ai imagine` | 基于现有设定推演未来 | `dreamulator ai imagine --world earth/ERE-if --id ERE` |
| `ai civ` | **地理→文明推演**：给定气候带（Köppen）+ 地理锚点 + 地形 + 邻近关系，用真实文明史类比建议可能孕育的文明种子（类型/经济基础/与邻区互动），锚定到 civilizations.yaml | `dreamulator ai civ --world gaia-m --anchor "北方大陆南岸"` |

> `ai civ` 是命令组的**第四向**（前三个是「数据→叙事」「意图→数据」「Tags→名字/角色」）：
> **气候画像 → 文明种子**。它补上文明种子设计缺失的那块——从气候
> 自动生成文明种子候选，再由人（或 `ai assist`）锚定成结构化数据。实现见附录 D。

## 3. 实用工具型命令

| 子命令 | 功能 | 场景 |
|--------|------|------|
| `ai trace` | 沿 DAG 向上游追溯因果链，解释某个设定的"成因" | 调查饥荒为何爆发 |
| `ai critique` | 让 AI 扮演严苛的"世界观编辑"，寻找违背物理/历史逻辑的硬伤 | 检查沙漠帝国为何有木材出口 modifier |
| `ai reconcile` | 当两个分支存在矛盾数据时，AI 生成自洽的背景故事缝合两者 | 分支 A（冰川）vs 分支 B（雨林）合并 |

## 4. 创意型命令

| 子命令 | 功能 | 场景 |
|--------|------|------|
| `ai mythologize` | 将科学推演数据转化为原住民视角的神话/宗教典籍 | 大陆撕裂事件 → 《深渊之歌》古卷 |
| `ai perspective` | 针对同一历史事件生成多个利益相关方的"平行记录" | 战役的胜者史书 / 败者挽歌 / 平民日记 / 后世史学家评价 |
| `ai linguistics` | 根据生态特征和文明 Tags 生成符合人造语言规则的地名/人名 | 极寒高山游牧部落城市名：Khar-Dûm |
| `ai fork` | What-if 自动分支：提出假设 → 自动拉分支 → 修改参数 → 运行推演 → 生成差异报告 | 如果希克苏鲁伯陨石未撞击地球？ |
| `ai tavern` | AI 扮演酒馆老板，搭配其他酒客插话，娓娓道来世界历史 | `dreamulator ai tavern --world earth/ERE-if --id ERE` |
| `ai persona` | 将文明状态降维锻造成 SillyTavern V2 规范的角色卡 | 生成法纳尔官僚或安纳托利亚军阀的角色卡 |
| `ai lorebook` | 将 DAG 节点树自动编译为 SillyTavern 兼容的 Lorebook | 导入 ERE 世界线进行跑团 |
| `ai oracle` | 交互式概率 What-if 推演终端，AI 扮演"神谕"给出带概率的预言 | "如果 1916 年我们没背刺同盟国？" |

## 5. TUI 交互式入口

- `dreamulator ai`（不带子命令）进入 TUI 交互式环境
- 自然语言路由（LLM Function Calling 自动解析意图 → 调用对应命令）
- 持久化会话管理（`~/.dreamulator/sessions.db` SQLite）
- 工作上下文锁定（`/focus <entity_id>` 类似 `cd`）
- 斜杠命令系统（`/worlds`, `/tavern`, `/diff`, `/save`）
- 双屏联动：TUI 生成结果 → 自动链接跳转 Web UI 3D 可视化
- 技术栈：`Textual`/`Rich` 做 TUI 渲染，`SQLite` 做状态管理

## 6. 前端 UI 集成（Phase 3C 扩展）

### Entity Inspector + AI Console 双面板

- 点击地图上任何实体 → 右侧滑出结构化数据面板
- 底部快捷操作卡片：Narrate / Trace / Imagine / Mythologize
- 科学视角 ↔ 神话视角切换开关

### Global Copilot 悬浮窗

- 右下角可折叠对话框，自然语言下达复杂指令
- 后端 Function Calling 自动映射为内部函数

**注意**：AI 功能仅在本地动态部署（FastAPI 模式）下可用，静态页面暂不放开。

## 7. 实施优先级

| 优先级 | 计划项 | 理由 |
|--------|--------|------|
| **P0** | `ai` 命令组重构 + narrate 迁移 | CLI 用户入口，整合现有功能 |
| **P1** | 前端实体级 AI 侧边栏 | 核心 UI 体验升级 |
| **P1** | 智能上下文工程（RAG + Token 预估） | 保障 AI 调用质量和成本 |
| **P1** | `ai civ` 地理→文明推演（附录 D） | 文明种子设计的核心中间层，衔接气候画像与 civilizations.yaml |
| **P2** | TUI 交互式入口 | 依赖 `ai` 命令组实现 |
| **P3** | SillyTavern 生态对接 | 作为差异化长期竞争力 |

---

## 附录 A：LLM Agent 八种角色

> 来源：2026-08 设计讨论。LLM 在 Dreamulator 中的角色不是"替代引擎"，而是连接人类直觉与引擎精度的**认知中间层**。

```
人类的模糊意图 ←→ [LLM 认知界面] ←→ 结构化数据（YAML/JSON）←→ 引擎推演
```

### 角色总览

| # | 角色 | 功能 | 对应命令 |
|---|------|------|---------|
| 1 | **意图翻译器** | 自然语言 → geography.yaml/cell edits | `ai assist` |
| 2 | **逆向工程师** | "想让这里多雨" → 分析需要什么地形修改 | `ai assist` |
| 3 | **尺度评估员** | 判断编辑影响范围，建议用 geography 还是 edits | `ai assist` |
| 4 | **特征转化器** | 批量 edits.json → 归纳为 geography 预定义特征 | `ai assist` |
| 5 | **物理审计员** | 检查世界设定的物理自洽性 | `ai critique` |
| 6 | **类比推理器** | "像东亚海岸线" → 提取特征并生成修改方案 | `ai assist` |
| 7 | **叙事一致性守卫** | 设定文档 vs 地图数据交叉验证 | `ai critique` |
| 8 | **协作协调员** | 多作者编辑冲突检测与调解建议 | 远期 |

### 角色详解

#### 1. 意图翻译器

将模糊的创作意图翻译为引擎可执行的结构化指令：

```
输入："在北方大陆西岸做一个峡湾群"
输出：
  - id: northern_fjords
    type: coastline_modifier
    anchor: {lat: 65, lon: -10, radius_deg: 8}
    constraints:
      style: "fjord_dominated"
      depth_m: [-300, -100]
      inlet_density: 0.8
    source_reference: "Norwegian coastline analog"
```

#### 2. 逆向工程师

从目标效果反推所需的物理条件改变，给出多种方案（按侵入性排序）：

```
输入："cell #12345 的降水量太低了，想要增加"
推理链：
  1. 当前：年降水 400mm，位于山脉背风坡
  2. 诊断：BFS 水汽被山脉阻挡（雨影效应）
  3. 方案 A（最小侵入）：山脉开缺口，海拔降 500m，下游也会变湿
  4. 方案 B（中等侵入）：调整板块汇聚角度，影响范围较大
  5. 方案 C（局部方案）：引入大型水体增加蒸散，仅影响 200km 半径
```

#### 3. 尺度评估员

判断用户编辑是否需要世界设定层面的解释：

| 空间范围 | 物理影响 | 建议处理 |
|---------|---------|---------|
| < 100 km² | 局部 | edits.json，无需额外解释 |
| < 10,000 km² | 区域 | geography feature + 简短说明 |
| > 10,000 km² | 大陆级 | geography feature + 更新设定文档 + 重建下游 |

#### 4. 特征转化器

识别 edits.json 中的空间模式，判断能否归纳为 seed-independent 的 geography 特征：

```
输入：47 个 cell elevation 覆写，分布在 NW-SE 弧形带上
分析：
  1. 空间模式：弧形凹陷，平均深 -800m，宽 ~50km
  2. 地质类比：红海裂谷 / 贝加尔湖
  3. 建议：转化为 rift_valley feature → 换 seed 后自动保留
```

#### 5. 物理审计员

全面审计世界的物理自洽性，输出分级报告（error > warning > info）。示例见 `ai critique` 命令。

#### 6. 类比推理器

提取现实世界地理特征的**特征向量**并映射到当前世界：

```
用户："让这个海岸线更像东亚"
分析：
  东亚特征向量: {岛弧链, 边缘海×3, 分形维数~1.3, 大河三角洲, 俯冲海沟}
  当前特征向量: {复杂度低, 无岛弧, 无边缘海, 三角洲×1, 无海沟}
  缺失: [岛弧, 边缘海, 海岸线复杂度, 海沟]
修改方案: 生成 geography.yaml features 补全缺失项
```

---

## 附录 B：`ai assist` 设计命令

### 定位

与现有 `ai` 命令（方向：数据 → 叙事）不同，`ai assist` 的方向是 **意图 → 数据**：

| | 现有 ai 命令 | ai assist |
|--|------------|----------|
| 方向 | 结构化数据 → 人类可读内容 | 人类模糊意图 → 结构化编辑 |
| 用户说 | "给我讲讲这个世界" | "帮我改这个世界" |
| 输出 | 文本/故事 | YAML/JSON 编辑提案 |

### 命令签名

```
dreamulator ai assist <world> [options]

Options:
  --region <lat,lon,radius>   目标区域
  --task <type>               任务类型: analyze|suggest|validate|convert
  --interactive               交互模式（多轮对话）
  --dry-run                   仅输出提案，不应用修改
```

### 子任务

| 子任务 | 功能 |
|--------|------|
| `analyze` | 分析指定区域的地形/气候/生态特征，输出结构化摘要 |
| `suggest` | 根据用户意图生成修改方案（自然语言 → geography.yaml / edits.json） |
| `validate` | 验证编辑提案的物理合理性和级联影响 |
| `convert` | 检查 edits.json 是否能归纳为 geography 预定义特征 |

### LLM 可调用的工具集

```python
tools = [
    # 查询类
    "query_cell(cell_id) -> CellInfo",
    "query_region(bbox) -> RegionSummary",
    "query_adjacency(cell_id) -> [NeighborInfo]",

    # 分析类
    "analyze_coastline(region) -> CoastlineMetrics",
    "analyze_drainage(cell_id) -> WatershedInfo",
    "analyze_climate_pattern(region) -> ClimateProfile",

    # 生成类
    "propose_geography_feature(description) -> FeatureYAML",
    "propose_edits(goal, region) -> [EditProposal]",

    # 验证类
    "validate_edit(edit) -> ValidationResult",
    "assess_cascade_impact(edit) -> ImpactReport",
]
```

---

## 附录 C：地图可视化与 LLM

### 无视觉能力模型的替代方案

对于纯文本模型，将地图转化为结构化文本表示：

1. **统计摘要 + 空间索引**：世界概要（海陆比、板块数、Köppen 分布、主要地貌特征列表）
2. **低分辨率 ASCII 地图**：~50×25 字符 + 图例
3. **图结构表示**：板块邻接图（节点=板块面积/类型，边=边界类型/速率）
4. **空间查询接口**：LLM 通过 Function Calling 调用查询函数"感知"地图位置

### 有视觉能力模型的闭环流程

```
Step 1: 渲染地图（多视角：全局等距圆柱 + 目标区域放大 + 图层叠加）
    ↓
Step 2: 构建 Prompt（图像 + 结构化世界参数 + 用户请求 + 可用工具列表）
    ↓
Step 3: 视觉模型分析（海岸线形态、板块边界模式、气候带分布、地球类比匹配）
    ↓
Step 4: 生成结构化修改方案（geography.yaml features / edits.json / 参数变更）
    ↓
Step 5: 引擎执行（build pipeline）+ 渲染修改后地图
    ↓
Step 6: Before/After 对比渲染 → 返回报告
```

### 理想场景

用户一句话 "这个海岸线改成东亚风格" → Agent 自主完成：分析当前海岸线特征向量 → 对比东亚特征向量（岛弧、边缘海、分形维数）→ 生成 geography.yaml 修改 → 验证物理合理性 → 渲染 before/after 对比图 → 返回报告。

### 实施路线

| Phase | 内容 | 时间 |
|-------|------|------|
| 1 | `ai assist` CLI + 基础意图翻译 | 近期 |
| 2 | 地图渲染 API + 视觉 Prompt 模板 | +1 月 |
| 3 | Agent 自主工作流（分析→方案→验证→执行→对比） | +2 月 |
| 4 | 地球类比检索库 + 风格迁移 + 协作调解 | 远期 |

---

## 附录 D：`ai civ` — 地理→文明推演

> 来源：2026-08 讨论。补上文明种子设计缺失的一块——从气候画像自动生成
> 文明种子候选，而非纯手工锚定。

### 定位

现有命令三向：①数据→叙事（narrate/imagine）、②意图→数据（assist）、③Tags→名字/角色
（linguistics/persona）。`ai civ` 是**第四向：气候画像 → 文明种子**。

### 输入 / 输出

| | 内容 |
|---|---|
| **输入** | 地理区域（坐标锚点/命名地貌）+ 该区 Köppen 分布（如「Af-Am-Aw 连续区」「狭长 Cfb/Csb 沿岸带」）+ 地形 + 邻近关系（海/内海/山脉/苔原） |
| **输出** | 该区域可能孕育的文明种子：类型（农耕帝国/海洋城邦/游牧/渔猎）、经济基础（作物/畜牧/渔业/贸易）、与邻区的互动（征服/贸易/殖民）、并锚定到 civilizations.yaml 的 seed 结构 |

### 核心机制：真实文明史类比

`ai civ` 复用附录 A「类比推理器」的思路，但类比对象从**地貌**换成**文明史**：

| 气候条件 | 文明史类比 | 产出文明形态 |
|---|---|---|
| Af 雨林 | 刚果/几内亚海岸/亚马逊 | 密林河畔、薯类园艺、分散酋邦 |
| Am 季风 | 印度西海岸/东南亚 | 稻作、高密度农耕国家 |
| Aw 稀树草原 | 萨赫勒/德干 | 谷物、骑兵、大型帝国 |
| Cfb 温带海洋 | 不列颠/西欧 | 海洋、小麦、海贸 |
| Csb 地中海 | 希腊/罗马 | 橄榄/葡萄/小麦、沿海城邦、海洋帝国 |
| 狭长 Cfb 沿岸（内陆 ET） | 挪威/南智利/太平洋西北 | 海洋渔猎/贸易民、峡湾城邦串 |
| 内海湾区零星 Cfb | 波罗的海/白海 | 内海沿岸部落/小城邦、渔猎+海贸走廊 |

### 命令签名

```
dreamulator ai civ <world> [options]
  --anchor <region>     地理锚点（坐标或命名地貌，如 "北方大陆南岸"）
  --climate <koppen>    覆盖气候带（默认自动从地图读）
  --depth <n>           推演深度：1=文明类型 2=经济+互动 3=完整种子（写入 civilizations.yaml）
  --analog <name>       指定类比（如 "西非草原帝国"）替代自动检索
```

### 与其它模块的关系

- **上游**：`climate_portrait.md`（气候画像）+ `map` 层（Köppen 分布、地理锚点）。
- **下游**：生成候选 → 人审（或 `ai assist`）→ 锚定成 `civilizations.yaml` seed。
- **与「类比推理器」的区别**：后者做「地貌特征 → geography.yaml 修改」，`ai civ` 做
  「气候+地貌 → 文明形态」，是文明层（3C）的种子生成器。
