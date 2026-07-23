# 竞品分析与后续开发路线图

> 基于 `private/chats/chat-多人共创世界观项目实例.txt` 开发讨论 + 网络调研。  
> 最后更新：2026-07-24

---

## 一、核心优势总结

相比市面上三大类世界构建工具，Dreamulator 有三个不可替代的护城河：

### 1. 物理因果（Causality）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| [**Azgaar**](https://azgaar.github.io/Fantasy-Map-Generator/) | 启发式随机生成（heuristics），气候与地形无因果关联 | 基于 `physics → chemistry → climate` DAG 推演，"因为有暖流所以是雨林" |
| [**Inkarnate**](https://inkarnate.com/) / [**Wonderdraft**](https://www.wonderdraft.net/) | 纯手绘，无任何物理验证 | 引擎自动校验设定自洽性 |
| [**World Anvil**](https://www.worldanvil.com/) / [**Novelcrafter**](https://novelcrafter.com/) | "设定集维基"，无物理约束 | 科学约束的输入校验 + DAG 级联影响追踪 |

### 2. 版本控制（Versioning）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| [**Gleba**](https://github.com/Calandiel/Gleba) | 单机沙盒，无分支/合并概念 | Git 风格分支系统 + `_inherit` 继承 + 多人共创 |
| **所有竞品** | 设定冲突无法追踪 | DAG Diff：修改地质层 → 自动标记下游气候/文明层为 Dirty |

### 3. AI 语义缝合（AI-Semantics）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| **World Anvil** | AI 辅助写作，但无数据验证 | LLM 读取结构化 YAML → 编译为叙事，而非 LLM 直接写文本 |
| **Novelcrafter** | 纯文本 AI 辅助 | 科学数据 → `narrate` 命令 → 物理自洽的故事 |

**定位总结**：Azgaar 提供世界观的**画布**，World Anvil 提供世界观的**图书馆**，Dreamulator 构建世界观的**物理引擎与因果引擎**。

---

## 二、后续开发方向（细化）

### Phase 2.5：地形真实感增强（当前优先级最高）

**目标**：修复 terrain-dev 等测试数据中暴露的地形生成问题，提升陆地真实感。

**背景**：当前 CVT 管线虽能生成基本海陆分布，但在以下方面与真实地球差异明显，
需要先修复这些底层问题，再进入气候推演（3A），否则错误的地形会级联放大到气候/文明层。

**子任务**：

#### 2.5a：大陆形状与分布优化

| 问题 | 改进方向 |
|------|---------|
| 板块洪水填充产生碎片化大陆 | 引入大陆聚合度参数，合并临近同类型 cell 为连片大陆 |
| 大陆位置随机，无纬度偏好 | 参考地球：中低纬度大陆面积更大，极区以海洋为主 |
| 大陆面积分布不合理 | 引入 Zipf/Pareto 分布约束大陆面积（少数大 + 多数小） |
| 无超大陆/裂解周期概念 | 可选的"超大陆初始态"模板（如 Pangea-like），再自动裂解 |

#### 2.5b：山脉与地形特征改进

| 问题 | 改进方向 |
|------|---------|
| 山脉仅出现在板块边界 | 增加热点火山链（如夏威夷-皇帝海山链）、地壳穹隆 |
| 边界山脉的高斯衰减过于平滑 | 引入不对称剖面（迎风坡陡、背风坡缓）+ 更高的峰谷比 |
| 无高原/盆地/裂谷等特殊地貌 | 在汇聚/离散/转换边界分别生成对应的典型地貌组合 |
| 无冰川侵蚀痕迹 | 可选的高纬度/高海拔冰川地形（U 形谷、冰斗、角峰） |

#### 2.5c：海岸线与大陆架

| 问题 | 改进方向 |
|------|---------|
| 海陆过渡生硬（无大陆架） | 在海岸线外增加指数衰减的大陆架深度剖面 |
| 无峡湾/溺谷/三角洲 | 基于河流出口 + 潮差参数的微型海岸特征 |
| 岛屿弧/海沟缺失 | 汇聚型边界外生成岛弧 + 海沟地形对 |

#### 2.5d：噪声参数标定与验证

| 问题 | 改进方向 |
|------|---------|
| fBm 噪声参数凭经验设定 | 对比真实 DEM（ETOPO1/GEBCO）的功率谱，标定 amplitude/persistence |
| 噪声各向同性，无构造走向 | 引入各向异性噪声（沿山脉走向拉伸） |
| 缺乏定量质量评估 | 开发地形质量指标：高程直方图双峰性、粗糙度-尺度关系、流域统计 |

#### 2.5e：标准测试世界

| 问题 | 改进方向 |
|------|---------|
| 修改参数后无法量化影响 | 建立标准测试世界（seed=42, num_nodes=4096），每次改动后对比快照 |

> 自动化地形质量检查（CI 集成、噪声功率谱验证等）暂不实施——在地形效果稳定前难以定义有效的定量指标。

**预期产出**：
- 标准测试世界配置文件（seed=42, num_nodes=4096）
- 修改 `terrain_synthesizer.py`, `plate_generator.py` — 上述算法改进
- terrain-dev 世界线地形质量显著提升

**预计工期**：3–4 周

---

### Phase 3A：气候与流体引擎

**目标**：从经验公式升级为简化 GCM（大气环流模型）。

| 功能 | 说明 |
|------|------|
| 能量平衡模型（EBM） | 基于恒星辐射 + 大气成分计算全球温度分布 — [参考](https://en.wikipedia.org/wiki/Energy_balance_model) |
| 科里奥利力 + 风带 | 基于行星自转模拟 [Hadley/Ferrel/Polar 环流](https://en.wikipedia.org/wiki/Atmospheric_circulation) |
| 地形雨影效应 | 山脉阻挡 → 迎风坡多雨 + 背风坡干旱 — [orographic lift](https://en.wikipedia.org/wiki/Orographic_lift) |
| 洋流模拟 | 风驱动 + [热盐环流](https://en.wikipedia.org/wiki/Thermohaline_circulation) |

**输出**：temperature.png, precipitation.png, ocean_currents.json  
**竞品对比**：当用户问"如果自转反向会怎样"，Azgaar 无法回答，Dreamulator 可精确模拟。

### Phase 3B：侵蚀与河流生成

**目标**：水力侵蚀 + 河流网络。当前 `river_generator.py` 和 `erosion.py` 为占位。

| 功能 | 算法 |
|------|------|
| [D8 流向](https://en.wikipedia.org/wiki/Flow_direction) | 8 方向最陡下降 |
| 流量累积 | 上游集水面积 → 河流宽度 |
| 水力侵蚀 | 基于流量的河道下切 + 坡面侵蚀 |
| [沉积物搬运](https://en.wikipedia.org/wiki/Sediment_transport) | 侵蚀 → 搬运 → 三角洲沉积 |

### Phase 3C：文明半格式化管理（详见 §三）

**目标**：将文明层从 "Wiki 文档堆" 升级为 "事件溯源 + 状态机"。

### Phase 3D：世界线合并的可视化 Diff

**目标**：将 Git Diff 从文本差异升级为地理热力图 + 文明状态对比。

| 功能 | 说明 |
|------|------|
| DAG 影响半径分析 | 上游修改 → 自动高亮受影响的网格 |
| 混沌预警 | [Lyapunov exponent](https://en.wikipedia.org/wiki/Lyapunov_exponent) > 0 → 弹出 "蝴蝶效应警告" |
| 蒙特卡洛不确定性 | N 次 [Monte Carlo perturbation](https://en.wikipedia.org/wiki/Monte_Carlo_method) → 置信区间可视化 |

### Phase 3E：LLM 叙事引擎

**目标**：`narrative_bridge.py` — 结构化数据 → 史诗叙事。  
LLM 读取 YAML/JSON 数据变动，自动生成符合逻辑的世界线变动编年史。

---

## 三、文明层半格式化管理方案

### 3.1 架构核心思想

**Wiki 文档不应该是数据源，而应该是渲染产物。**

文明层数据从 "非结构化 Markdown" 重构为三层半格式化架构：

```
┌─────────────────────────────────────────────┐
│  Layer 3: 渲染层 (只读)                      │
│  LLM compile: YAML/JSON → Markdown/Wiki      │
├─────────────────────────────────────────────┤
│  Layer 2: 事件流 (Event Stream)              │
│  Atomic events: famine, war, migration, ...  │
├─────────────────────────────────────────────┤
│  Layer 1: 实体与修饰器 (Entities & Modifiers)│
│  States, tags, numerical modifiers           │
└─────────────────────────────────────────────┘
```

### 3.2 子层级详解

#### Layer 1：实体与修饰器（Entities & Modifiers）

借鉴 [Paradox Clausewitz Engine](https://eu4.paradoxwikis.com/Map_modding) 标签与修饰器系统 + [Cliodynamics（Peter Turchin）](https://peterturchin.com/cliodynamics/) 量化历史变量。

```yaml
# civilizations.yaml
entities:
  - id: "byzantine_empire"
    name: "拜占庭帝国"
    type: "empire"
    tags: ["feudal", "orthodox", "maritime_trade"]
    modifiers:
      - type: "ecological_blessing"
        source: "mediterranean_climate"
        effect: { grain_yield: "+20%", carrying_capacity: 1.3 }
      - type: "political_instability"
        source: "elite_overproduction"
        effect: { asabiya: "-0.1/yr", revolt_risk: 0.15 }

variables:
  asabiya: 0.65         # 社会凝聚力（Turchin 模型）
  elite_index: 0.4      # 精英过剩指数
  complexity: 1200      # Tainter 复杂性投入
  marginal_return: 0.3  # 边际收益
```

#### Layer 2：原子化事件流（Atomic Event Stream）

借鉴 [Dwarf Fortress Legends Mode](https://dwarffortresswiki.org/index.php/Legends) 的 Event Sourcing 模型。

```yaml
# events.yaml
events:
  - id: evt_0421
    type: "succession_crisis"
    year: 402
    actors: ["byzantine_empire"]
    trigger:
      condition: "asabiya < 0.3 AND elite_index > 0.7"
    modifiers_applied:
      - { target: "byzantine_empire", mod: "civil_war", duration: "5yr" }
    narrative_seed: "王位继承争议引发内战"

  - id: evt_0422
    type: "environmental_collapse"
    year: 405
    trigger:
      condition: "carrying_capacity < 0.5 * baseline"
    modifiers_applied:
      - { target: "byzantine_empire", mod: "famine", severity: 0.8 }
```

#### Layer 3：LLM 编译为 Wiki（只读渲染层）

```
输入: YAML { type: "succession_crisis", actors: ["byzantine_empire"],
             asabiya: 0.28, year: 402 }
输出:
  "纪元 402 年，由于精英阶层的过度膨胀与帝国凝聚力的瓦解，
   拜占庭陷入了惨烈的王位争夺战。三位皇子各自割据一方，
   曾经繁荣的商路被战火截断……"
```

### 3.3 可替换性设计

为实现"容纳多种建模方案、方便快速切换"，采用**策略模式**：

```python
class CivModelProtocol(Protocol):
    """文明建模策略接口"""
    def compute_carrying_capacity(self, ecology: EcologyData) -> float: ...
    def step_population(self, state: CivState, dt: float) -> CivState: ...
    def check_events(self, state: CivState) -> list[Event]: ...

class [HANDYModel](https://doi.org/10.1016/j.ecolecon.2014.02.015):    # Motesharrei et al. (2014) 资源-人口 ODE
class [SDTModel](https://peterturchin.com/structural-demographic-theory/):  # Turchin 结构-人口理论
class [TainterModel](https://en.wikipedia.org/wiki/Joseph_Tainter):    # 复杂性边际收益递减
class SimpleTagModel:      # 纯标签驱动（向后兼容现有 Wiki 风格）
```

配置文件切换：
```yaml
# terrain_config.yaml
civ_model:
  strategy: "handy"  # handy | sdt | tainter | simple
  params:
    beta_C: 0.03    # 平民出生率
    alpha_C: 1e-6   # 资源消耗系数
    gamma: 0.01     # 资源再生率
```

### 3.4 为什么这解决了协作冲突

**之前**：两作者改同一个国家 Wiki → Markdown Merge Conflict（无法解决）  
**之后**：两作者各自提交 YAML Modifier → Git 合并 YAML 数组 → DAG 引擎叠加计算

```
分支 A: add_modifier { drought_severity: 0.8 }
分支 B: add_modifier { tech_bonus: "+30%" }
合并后: 系统同时拥有干旱 + 科技加成 → ODE 计算净效应
```

---

## 四、其他可扩展的酷炫功能

### 4.1 交互式世界线浏览器

类似 GitHub Network Graph，可视化分支树 + 关键事件节点。  
用户可以拖拽时间轴，看世界在不同分支下的演化对比。

### 4.2 实时协作模式

- WebSocket 多人同时编辑同一世界
- 类 Google Docs 的协作体验 + Git 版本控制
- 每个创作者的修改实时推送到 DAG 引擎 → 即时预览下游影响

### 4.3 AI 顾问模式

- 用户在 YAML 中设定模糊目标（如 "我希望北大陆出现一个游牧帝国"）
- LLM 分析当前世界状态 → 建议需要修改哪些层级的参数
- 用户确认 → 引擎自动注入 Modifier → 推演 → 生成叙事

### 4.4 世界导出包

- 一键导出完整世界为 ZIP（含 elevation.png + voronoi.json + civilizations.yaml + LLM 生成的 Wiki）
- 导入到 TTRPG 工具（[Foundry VTT](https://foundryvtt.com/), [World Anvil](https://www.worldanvil.com/)）
- 导出视频素材：球面旋转动画 + 时间推移（timelapse）地图变化

### 4.5 文明演化回放（Timelapse）

- 类似 [《文明》系列](https://civilization.com/) 的地图回放
- 从初始地质状态到文明兴衰的完整时间线动画
- 可直接导出为视频素材（B 站视频核心素材）

---

## 五、实施优先级

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| **P0** | **地形真实感增强（Phase 2.5）** | **3–4 周** | ★★★★★ |
| P0 | 文明层半格式化 Schema | 1–2 周 | ★★★★★ |
| P0 | 气候引擎（EBM） | 2–3 周 | ★★★★★ |
| P1 | LLM 叙事桥 | 1 周 | ★★★★ |
| P1 | 文明演化回放（Timelapse） | 2 周 | ★★★★ |
| P2 | 水力侵蚀 + 河流 | 2–3 周 | ★★★ |
| P2 | 世界线 Diff 可视化 | 2 周 | ★★★ |
| P3 | AI 顾问模式 | 1–2 周 | ★★ |
| P3 | 实时协作 | 3–4 周 | ★★ |
| P3 | 世界导出包 | 1 周 | ★★ |

---

---

## 参考链接

### 竞品

| 工具 | 链接 | 类型 |
|------|------|------|
| Azgaar's Fantasy Map Generator | https://azgaar.github.io/Fantasy-Map-Generator/ | 地图生成 |
| Inkarnate | https://inkarnate.com/ | 手绘地图 |
| Wonderdraft | https://www.wonderdraft.net/ | 手绘地图 |
| World Anvil | https://www.worldanvil.com/ | 设定管理 |
| Novelcrafter | https://novelcrafter.com/ | AI 写作辅助 |
| Gleba | https://github.com/Calandiel/Gleba | 科学模拟 |
| Foundry VTT | https://foundryvtt.com/ | TTRPG 平台 |

### 设计概念

| 概念 | 链接 | 来源 |
|------|------|------|
| Clausewitz Engine (Paradox) | https://eu4.paradoxwikis.com/Map_modding | P 社游戏引擎 |
| Dwarf Fortress Legends | https://dwarffortresswiki.org/index.php/Legends | 程序化历史生成 |
| Cliodynamics | https://peterturchin.com/cliodynamics/ | Peter Turchin |
| HANDY Model | https://doi.org/10.1016/j.ecolecon.2014.02.015 | Motesharrei et al. (2014) |
| SDT (Structural-Demographic Theory) | https://peterturchin.com/structural-demographic-theory/ | Peter Turchin |
| Joseph Tainter — Complexity Collapse | https://en.wikipedia.org/wiki/Joseph_Tainter | 复杂性边际收益递减 |
| Seshat Global History Databank | https://seshatdatabank.info/ | 全球历史数据库 |
| Energy Balance Model | https://en.wikipedia.org/wiki/Energy_balance_model | 气候科学 |
| Atmospheric Circulation | https://en.wikipedia.org/wiki/Atmospheric_circulation | 大气环流 |
| Orographic Lift | https://en.wikipedia.org/wiki/Orographic_lift | 地形抬升 |
| Thermohaline Circulation | https://en.wikipedia.org/wiki/Thermohaline_circulation | 热盐环流 |
| Lyapunov Exponent | https://en.wikipedia.org/wiki/Lyapunov_exponent | 混沌理论 |
| Monte Carlo Method | https://en.wikipedia.org/wiki/Monte_Carlo_method | 不确定性量化 |
| D8 Flow Direction | https://en.wikipedia.org/wiki/Flow_direction | 水文模型 |
| Sediment Transport | https://en.wikipedia.org/wiki/Sediment_transport | 沉积物搬运 |

### 内部文档

- `docs/usage/map-workflow.md` — 地图工作流指南
- `docs/usage/terrain-pipeline.md` — 地形生成管线技术参考
- `docs/usage/civmap-guide.md` — 文明地图使用指南
- `docs/usage/project-structure.md` — 层级架构与分支管理
- `docs/design/map_system_design.md` — 历史 ADR
- `private/chats/chat-多人共创世界观项目实例.txt` — 原始讨论记录

---

*此文档将随开发进展持续更新。*
