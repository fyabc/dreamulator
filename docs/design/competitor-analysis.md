# 竞品分析

> 从 `roadmap.md` 拆分而来（2026-08-04）。开发路线图见 [roadmap.md](roadmap.md)。
> 基于 `private/chats/chat-多人共创世界观项目实例.txt` 开发讨论 + 网络调研。

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
| **World Anvil** | AI 辅助写作，无数据验证 | LLM 读取结构化 YAML → 编译为叙事，而非 LLM 直接写文本 |
| **Novelcrafter** | 纯文本 AI 辅助 | 科学数据 → `narrate` 命令 → 物理自洽的故事 |

**定位总结**：Azgaar 提供世界观的**画布**，World Anvil 提供世界观的**图书馆**，Dreamulator 构建世界观的**物理引擎与因果引擎**。

---

## 二、参考链接

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
