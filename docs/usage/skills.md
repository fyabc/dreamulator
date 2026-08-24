# Claude Code 技能（Skill）

本页速查 dreamulator 的 Claude Code 自定义技能（`.claude/commands/`）。技能在
Claude Code 里以 `/技能名 参数` 触发；技能文件本身是完整指令（角色/工作流/维度清单），
本页只给「触发方式 + 典型用法 + 依赖 + 产出」。

## 技能列表

| 技能 | 用途 | 触发示例 |
|---|---|---|
| `/grill-world` | 拷问世界设定（设定 vs 引擎派生事实 vs 理论），跨层找矛盾并产出决策记录 | `/grill-world nacrea civilizations` |
| `/read-map` | 视觉 + 数据双路交叉校验读取地图图层，抽取海陆/气候/生态/文明结构 | `/read-map nacrea` |
| `/narrate` | 生成世界口语化描述 | `/narrate earth --branch pangea` |

---

## /grill-world — 世界设定拷问

**守护轴（harness）的交互式入口**（设计见 [harness.md](../design/harness.md) §9、§14）。

- **触发**：`/grill-world <world> [layer] [质疑]`
- **依赖**（守护轴内核，均已落地）：
  - 取证入口 `guard/critique.py::gather_facts(world, branch)` —— 一次拿全
    `{fact_context, queries, dimensions}`（answerer 只许从这里取证，防幻觉）
  - 事实上下文 `guard/facts.py::build_fact_context`（实体目录 + 各层 derived summary）
  - 天空几何 `engine/sky_geometry.py`（视直径/天空位置/凌掩/Hill 球/视亮度/潮汐）
  - 空间查询 `map/query.py::cell_facts`（koppen/驯化潜力/离岸距离）
  - 查询注册表 `query_registry.list_queries()`（7 原语 JSON Schema = function-calling tools）
- **工作流**：①捕获 → ②取证 → ③拷问（逐维）→ ④判定（矛盾清单）→ ⑤处置 → ⑥发布 → ⑦入库
- **产出**：矛盾清单 + 决策记录 `data/worlds/<world>/design-notes/00NN-<slug>.md`
  （ADR：`status` / `checked_against` / 结论），由 `guard check` 后续自动过期检测。

> griller/answerer 的**子代理互审**（Workflow 多代理）需用户显式授权才启用；
> 当前 `/grill-world` 是单代理逐维循环，事实库已就绪。

## /read-map — 地图结构双路抽取

**视觉路**（形状/拓扑/位置）+ **数据路**（面积/占比/连通性）交叉校验。单一来源原则：
数值以 `cvt_mesh.json` 为准，视觉只用于定性。

- **触发**：`/read-map <world> [--planet <id>]`
- **依赖**：带视觉能力的模型（纯文本模型读图返回 `[Unsupported Image]`，需先 `/model` 切换）
- **流程**：投影换算（等距圆柱）→ 视觉路（定性）→ 数据路（定量）→ 交叉校验落笔
- **产出**：实测值写入设定文档（只写当前设定）；视觉与数据冲突 → 以数据为准；
  数据与设定冲突 → 决策记录（不静默改设定）

## /narrate — 世界口语化描述

调用 `dreamulator narrate` 后端（Claude API），生成世界描述。

- **触发**：`/narrate <world> [--branch <b>] [--model <m>]`
- **依赖**：`uv sync --extra narrate`（首次）+ Anthropic API key
- **产出**：口语化世界描述（直接展示，不加额外解释）
