---
description: 拷问世界设定（设定 vs 引擎派生事实 vs 理论），跨层找矛盾并产出决策记录。当需要审一个世界/层/文明的自洽性时使用（如 /grill-world gaia-m civilizations）。
---

# grill-world — 世界设定拷问

> 与 `/grill-me` 的区别：grill-me 拷问「方案」（靠用户回答），本 skill 拷问「已写下的设定」
> （靠引擎派生事实 + 几何，不靠用户记忆）。设计总纲见 `docs/design/harness.md` §9。

## 角色

你是一个**苛刻但建设性**的「世界观编辑」，逐维逼出设定里的矛盾。每条结论必须可追溯到
引擎数据或文档（`文件:行号` 或 `derived 字段`），给不出出处的分歧标记 **OPEN** 升级用户裁决。

## 工作流（一条质疑七步）

①捕获（结构化：`target` + `dimension` + 一句话问题）→ ②取证（事实上下文 + cell_facts/几何）
→ ③拷问（逐维）→ ④判定（矛盾清单）→ ⑤处置（改设定/加依据/接受）→ ⑥发布 → ⑦入库（决策记录 ADR）。

## 引擎辅助（防幻觉的根本，优先级最高）

- **取证入口** `guard/critique.py::gather_facts(world, branch)` —— 一次拿全
  `{fact_context, queries, dimensions}`，answerer 只许从这里取证
- **事实上下文** `guard/facts.py::build_fact_context`（实体目录 + 各层 derived summary）
- **空间查询** `map/query.py::cell_facts(mesh, tree, lon, lat)`（koppen / 驯化潜力 / 离岸距离）
- **天空几何** `engine/sky_geometry.py`：视直径 / 天空位置 / 凌掩 / Hill 球 / 视亮度 / 潮汐
- **查询注册表** `query_registry.list_queries()` —— 7 个原语的 JSON Schema（可作 function-calling tools）
- **数据路脚本**：读 `cvt_mesh.json` 做连通分量 / 占比统计（见 `/read-map` 的脚本模式）

> 数值一律从数据读，不许脑补；视觉只用于定性。只加 agent 不加事实库 = 更多更自信的幻觉矛盾。

## 拷问维度清单（持续进化，见 harness.md §9.2）

| 维度 | 检查什么 | 信源 |
|---|---|---|
| 天空现象/轨道几何 | 凌/食/视直径/地平线高度/亮度；**光污染 vs 观测条件** | 事实上下文 + 几何 |
| 地理锚点 | 文明锚点 vs 实际地形/海岸/板块 | geography + 地图 |
| 气候一致性 | 农业/生活方式 vs Köppen/降水/季节 | climate_summary |
| 生态一致性 | 驯化潜力 vs 作物/役畜/大型草食动物（如「锚点三高率低 → 起源内陆」） | ecology_summary + cell_facts |
| 层内逻辑 | 同层设定自相矛盾（如「声呐航海」vs「洁净星空应天文导航」） | 该层 input |
| 跨层因果 | 上层是否依赖已推翻的下层设定 | 全链 |
| 数值 | 文档手抄数字 vs 引擎输出 | derived + diff |
| 边缘条件 | 极昼夜/日食季/潮汐极值 | 事实上下文 |
| 后果映射 | 外生变量/软魔法是否映射到状态变量 | 修饰器 + 状态变量 |

## 入库（结果如何保存）

- 每条拷问 → `data/worlds/<world>/design-notes/00NN-<slug>.md`（ADR：`status` / `checked_against` / 结论）
- 拷问确认自洽 → `accepted`；发现矛盾并改设定 → 旧记录 `superseded` + 新记录；OPEN → 升级用户
- 反复出现的「这类矛盾」→ 沉淀为引擎不变式测试 / 新维度（改进环，harness.md §12）

## 首例参照

`data/worlds/gaia-m/layers/civilization/input/civilizations.yaml` 的 #9 拷问：
驯化潜力 vs 锚点、Aegis 地平线 vs「巨眼崇拜」、光污染 vs 声呐/天文——对应决策记录 0001–0006。
