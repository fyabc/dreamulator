# 文明层半格式化管理设计

> 从 `roadmap.md` 拆分而来（2026-08-04）。这是 Phase 3C 的详细设计提案。
> 路线图与优先级见 [roadmap.md](roadmap.md)。

**目标**：将文明层从 "Wiki 文档堆" 升级为 "事件溯源 + 状态机"。

---

## 1. 架构核心思想

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

## 2. 子层级详解

### Layer 1：实体与修饰器（Entities & Modifiers）

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

### Layer 2：原子化事件流（Atomic Event Stream）

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

### Layer 3：LLM 编译为 Wiki（只读渲染层）

```
输入: YAML { type: "succession_crisis", actors: ["byzantine_empire"],
             asabiya: 0.28, year: 402 }
输出:
  "纪元 402 年，由于精英阶层的过度膨胀与帝国凝聚力的瓦解，
   拜占庭陷入了惨烈的王位争夺战。三位皇子各自割据一方，
   曾经繁荣的商路被战火截断……"
```

## 3. 可替换性设计

为实现"容纳多种建模方案、方便快速切换"，采用**策略模式**：

```python
class CivModelProtocol(Protocol):
    """文明建模策略接口"""
    def compute_carrying_capacity(self, ecology: EcologyData) -> float: ...
    def step_population(self, state: CivState, dt: float) -> None: ...
    def check_events(self, state: CivState) -> list[Event]: ...

class HANDYModel:    # Motesharrei et al. (2014) 资源-人口 ODE
class SDTModel:      # Turchin 结构-人口理论
class TainterModel:  # 复杂性边际收益递减
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

## 4. 为什么这解决了协作冲突

**之前**：两作者改同一个国家 Wiki → Markdown Merge Conflict（无法解决）
**之后**：两作者各自提交 YAML Modifier → Git 合并 YAML 数组 → DAG 引擎叠加计算

```
分支 A: add_modifier { drought_severity: 0.8 }
分支 B: add_modifier { tech_bonus: "+30%" }
合并后: 系统同时拥有干旱 + 科技加成 → ODE 计算净效应
```
