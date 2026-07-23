# 竞品分析与后续开发路线图

> 基于 `private/chats/chat-多人共创世界观项目实例.txt` 开发讨论 + 网络调研。  
> 最后更新：2026-07-24

---

## 一、核心优势总结

相比市面上三大类世界构建工具，Dreamulator 有三个不可替代的护城河：

### 1. 物理因果（Causality）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| **Azgaar** | 启发式随机生成（heuristics），气候与地形无因果关联 | 基于 `physics → chemistry → climate` DAG 推演，"因为有暖流所以是雨林" |
| **Inkarnate / Wonderdraft** | 纯手绘，无任何物理验证 | 引擎自动校验设定自洽性 |
| **World Anvil / Novelcrafter** | "设定集维基"，无物理约束 | 科学约束的输入校验 + DAG 级联影响追踪 |

### 2. 版本控制（Versioning）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| **Gleba** | 单机沙盒，无分支/合并概念 | Git 风格分支系统 + `_inherit` 继承 + 多人共创 |
| **所有竞品** | 设定冲突无法追踪 | DAG Diff：修改地质层 → 自动标记下游气候/文明层为 Dirty |

### 3. AI 语义缝合（AI-Semantics）

| 竞品 | 弱项 | Dreamulator 优势 |
|------|------|-----------------|
| **World Anvil** | AI 辅助写作，但无数据验证 | LLM 读取结构化 YAML → 编译为叙事，而非 LLM 直接写文本 |
| **Novelcrafter** | 纯文本 AI 辅助 | 科学数据 → `narrate` 命令 → 物理自洽的故事 |

**定位总结**：Azgaar 提供世界观的**画布**，World Anvil 提供世界观的**图书馆**，Dreamulator 构建世界观的**物理引擎与因果引擎**。

---

## 二、后续开发方向（细化）

### Phase 3A：气候与流体引擎

**目标**：从经验公式升级为简化 GCM（大气环流模型）。

| 功能 | 说明 |
|------|------|
| 能量平衡模型（EBM） | 基于恒星辐射 + 大气成分计算全球温度分布 |
| 科里奥利力 + 风带 | 基于行星自转模拟 Hadley/Ferrel/Polar 环流 |
| 地形雨影效应 | 山脉阻挡 → 迎风坡多雨 + 背风坡干旱 |
| 洋流模拟 | 风驱动 + 热盐环流 |

**输出**：temperature.png, precipitation.png, ocean_currents.json  
**竞品对比**：当用户问"如果自转反向会怎样"，Azgaar 无法回答，Dreamulator 可精确模拟。

### Phase 3B：侵蚀与河流生成

**目标**：水力侵蚀 + 河流网络。当前 `river_generator.py` 和 `erosion.py` 为占位。

| 功能 | 算法 |
|------|------|
| D8 流向 | 8 方向最陡下降 |
| 流量累积 | 上游集水面积 → 河流宽度 |
| 水力侵蚀 | 基于流量的河道下切 + 坡面侵蚀 |
| 沉积物搬运 | 侵蚀 → 搬运 → 三角洲沉积 |

### Phase 3C：文明半格式化管理（详见 §三）

**目标**：将文明层从 "Wiki 文档堆" 升级为 "事件溯源 + 状态机"。

### Phase 3D：世界线合并的可视化 Diff

**目标**：将 Git Diff 从文本差异升级为地理热力图 + 文明状态对比。

| 功能 | 说明 |
|------|------|
| DAG 影响半径分析 | 上游修改 → 自动高亮受影响的网格 |
| 混沌预警 | 李雅普诺夫指数 > 0 → 弹出 "蝴蝶效应警告" |
| 蒙特卡洛不确定性 | N 次微扰模拟 → 置信区间可视化 |

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

借鉴 Paradox 克劳塞维茨引擎 + 历史动力学（Cliodynamics）变量。

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

借鉴《矮人要塞》的 Event Sourcing 模型。

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

class HANDYModel:          # 基于常微分方程的资源-人口模型
class SDTModel:            # Turchin 结构-人口理论
class TainterModel:        # Tainter 复杂性边际收益递减
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
- 导入到 TTRPG 工具（Foundry VTT, World Anvil）
- 导出视频素材：球面旋转动画 + 时间推移（timelapse）地图变化

### 4.5 文明演化回放（Timelapse）

- 类似《文明》系列的地图回放
- 从初始地质状态到文明兴衰的完整时间线动画
- 可直接导出为视频素材（B 站视频核心素材）

---

## 五、实施优先级

| 优先级 | 模块 | 预计工作量 | 关键性 |
|--------|------|-----------|--------|
| P0 | 文明层半格式化 Schema | 1-2 周 | ★★★★★ |
| P0 | 气候引擎（EBM） | 2-3 周 | ★★★★★ |
| P1 | LLM 叙事桥 | 1 周 | ★★★★ |
| P1 | 文明演化回放（Timelapse） | 2 周 | ★★★★ |
| P2 | 水力侵蚀 + 河流 | 2-3 周 | ★★★ |
| P2 | 世界线 Diff 可视化 | 2 周 | ★★★ |
| P3 | AI 顾问模式 | 1-2 周 | ★★ |
| P3 | 实时协作 | 3-4 周 | ★★ |
| P3 | 世界导出包 | 1 周 | ★★ |

---

*此文档将随开发进展持续更新。路线图讨论详见 `private/chats/chat-多人共创世界观项目实例.txt`。*
