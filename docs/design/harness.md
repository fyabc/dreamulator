# 守护轴（Harness）：校验 · 审计 · 设定维护

> 状态：Draft 0.1 · 2026-08-16
> 定位：Dreamulator 的**第三条轨道（守护轴）**——在 [vision.md](vision.md) §2「双轨驱动」（ODE/SDE 引力骨架 + LLM 血肉）之外补齐的第三条：校验与维护。
> 关联：[vision.md](vision.md) 的 Fantasy Harness；[layer-control-model.md](layer-control-model.md) 的校验层；
> [audit-plan.md](audit-plan.md)（守护引擎那一半）；本文件补齐「守护世界」那一半并把两者统一。

---

## 0. 一句话定位

**引擎（生成轴）决定 Dreamulator 能造出什么；守护轴决定 Dreamulator 造出的东西能不能信任。**

Dreamulator 卖的是**严谨**。但严谨会腐烂：设定手抄漂移、文档过时、跨层矛盾累积、某个参数改了没人知道下游全塌了。守护轴就是防止严谨腐烂的机制——它是 [vision.md](vision.md) 里「Fantasy Harness（受控想象）」这个核心隐喻的**执行臂**，而不是一个可有可无的附加工具。

---

## 1. 为什么是「核心」而非「工具」

### 1.1 守护的是价值主张

[vision.md](vision.md) §2 确立了「**双轨驱动**」：**ODE/SDE 引力骨架**（第一轨）+ **LLM 血肉填充**（第二轨），其中「Harness（控制回路）」目前只是约束第二轨（LLM）的窄义机制。本文把这个 Harness **提升为与两条轨道并列的第三条轨道——守护轴**，并把它的作用域从「约束 LLM」推广到「校验整个引擎 + 世界」。

vision.md 反复强调：**「LLM 不是脱缰的野马，通过严格的 Harness 控制回路限制它」「不是一键生成黑箱」「透明的推演链路」「克制的法则」**。这些承诺靠前两条轨道只兑现了一半：

- **生成轴**（ODE/SDE 引力骨架 + DAG 引擎）：让「河流不倒流、承载力不凭空产生」；
- **守护轴**（校验/审计/维护，即本文）：让「设定不自相矛盾、文档不漂移、结论可追溯」。

vision.md 只把生成轴写全了，守护轴至今散落在 `validate`、`audit-plan.md`、`doc_render.py` 各处，没有自己的名字。**本文就是给它一个名字和位置。**

### 1.2 严谨会腐烂：`silent drift` + `stale memory`

业界三个阵营都撞上了同一堵墙，且都把它当作头号敌人：

- **Hermes Agent**（Nous Research）明说：「**过期记忆是 agent 异常行为的头号原因**」，把记忆维护当作一等公民（[源码剖析](https://www.alibabacloud.com/blog/603216)、[六大支柱](https://cloud.tencent.com.cn/developer/article/2663646)）。
- **OpenClaw 生态的 Genesis 框架**把使命直接写成「防止 **hallucination、silent drift、stale repo memory**」（[repo](https://github.com/boygotflames/Open-Genesis-for-Claude-code-Openclaw-Codex-Cursor-or-any-agent)）——这三个词与本文件要解决的敌人逐字对应。
- **Claude Code** 官方指引反复强调「把『必须每次都成立』的规则做成 hook，而非提示词」（[Steering 指南](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)）。

Dreamulator 的世界设定本质上也是一种「跨会话的记忆」——它同样会 silent drift、会 stale。守护轴就是把业界防漂移的经验，**提升到有 ground truth（引擎 derived 数据）可校验的层面**。

### 1.3 超越论：从「文本↔文本一致」到「文本↔物理一致」

这是守护轴作为核心、而非工具的**根本理由**。竞品的自维护都在做「**文本与文本一致**」：

| 竞品 | 机制 | 天花板 |
|---|---|---|
| Agent 框架（Claude Code / OpenClaw / Hermes） | 分层记忆 + 容量限制 + cron 轮换 | 记忆是 agent 自己写的文本，**无 ground truth**——只能判断「旧不旧」，不能判断「错没错」 |
| World Anvil | [Variables](https://www.worldanvil.com/learn/variables/tips-variables) 变量单点更新处处同步 + [Autolinker](https://blog.worldanvil.com/worldanvil/dev-news/world-anvils-most-requested-new-feature-the-autolinker/) 自动链接 | 变量是**手动打的文本**——防笔误漂移，不防逻辑漂移，没有任何东西检查「人口 6000 是否与承载力物理矛盾」 |

**Dreamulator 的变量锚定的是引擎确定性推演的 derived 数据**：

> World Anvil 的变量是「打字一次，处处同步」；Dreamulator 的变量是「引擎推演一次，处处同步**且处处可验证**」。

因此守护轴能防的，竞品防不了：别人只能判断「这条设定旧了」，Dreamulator 能判断「这条设定**错了**」——因为引擎有 ground truth。这是相对所有同类（agent 框架与世界托管平台）**不可复制的差异点**。

### 1.4 引擎即环境：苦涩的教训的正确读法

[《苦涩的教训》(Richard Sutton 2019)](http://www.incompleteideas.net/IncIdeas/BitterLesson.html) 的教训是
「往模型里灌人类知识（权重/先验/上下文）最终输给规模化的计算 + 学习」。守护轴的定位恰好是这条教训的
**正确回应**，而非反例：

- **确定性引擎 = 环境**（RL 意义）：外在于 LLM、有确定性转移函数、种子化可复现。LLM 改不了
  物理定律，只能去**适应**它——这与「往 LLM 里灌知识」天差地别。
- **知识放对地方才有效**：[《The Sweeter Lesson》](https://cacm.acm.org/opinion/the-sweeter-lesson/) 补了
  另一半——人类知识**注入学习模型**会失败（苦涩的教训），但**编码进确定性求解器/环境**却成功
  （SAT/SMT 求解器、物理引擎）。dreamulator 的物理（Kepler/EBM/板块）属于后者。
- **完整三角**：搜索 = 引擎（算物理）、学习 = LLM（写叙事）、守护轴 = 两者间的**对账**
  （校验和/指纹/渲染 diff）。这正是 vision.md「受控想象」的精确含义：LLM 自由想象，引擎定义
  世界，守护轴做控制。

**推论**：守护轴的核心价值在**确定性验证器**（§7 的 stale.py），不在「给 LLM 更聪明的事实库」——
给事实库 LLM 仍会幻觉，但对账能抓出幻觉（见 §9.1 的防幻觉优先级）。

---

## 2. 双轴架构：从「四层控制模型」到「正交双轴」

### 2.1 现状：校验层被「画在底部」而低估

[layer-control-model.md](layer-control-model.md) 定义每层四层架构：

```
Layer 4: Override（覆写层）   —— 最终裁决权
Layer 3: Constraint（约束层） —— 作者意图
Layer 2: Engine（引擎推演层） —— 物理后果
Layer 1: Validation（校验层） —— 自洽性守卫
```

现状：L2/L3/L4 已落地（引擎 DAG、`geography.yaml` 约束、`edits.json` 覆写），**L1 几乎全是纸面**（`validate` 命令只做语法级检查）。更关键的问题是：把它画成「第 1 层（底部）」在视觉上暗示它是地基，但校验**不是垂直栈里的一层**——它是**横切**的：横切每层、横切层间、横切「引擎代码」与「世界数据」两个对象。

### 2.2 目标：生成轴 × 守护轴

```
  生成轴 (Generation)                    守护轴 (Guard)
  ────────────────                      ────────────────
  Override ─┐                           校验（贯穿每层）
  Constraint├→ derived 数据             · 层内自洽（守恒律、不变式）
  Engine   ─┘                           · 跨层一致（文明↔气候↔天文）
                                        · 数值漂移检测（指纹+渲染 diff）
                                        · 外部一致性（vs 理论/文献）
```

生成轴是「产出」的流水线，守护轴是「校验」的横切面。两者正交：一个世界可以在生成轴上很丰富，同时在守护轴上被判定为「自相矛盾」。

### 2.3 两个守护对象

同一根守护轴，两个守护对象（这是本文件与 audit-plan.md 的**统一**关系）：

| 守护对象 | 名称 | 现有落点 | 状态 |
|---|---|---|---|
| **引擎代码** | 三波审计（工程卫生/物理/架构） | [audit-plan.md](audit-plan.md) | 已规划，第一波部分完成 |
| **世界设定** | 设定维护工作流（§3） | 散落：`validate`、`doc_render`、决策记录提案 | 未成形，本文件补全 |

两者共用同一套机制：证据锚定（`文件:行号` / 文献）、子代理互审（audit-plan §五）、校验和/指纹、单点裁决升级用户。

### 2.4 守护轴与创造性：检测 ≠ 裁决

守护轴与「用户自己加设定」的创造性并不对立——**守护轴是检测器，不是警察**。它只做「这里有个矛盾，
级别 X」的**标记**，不做「你必须改」的**裁决**；裁决权在四层控制模型里（[layer-control-model.md](layer-control-model.md)：
用户通过「写哪一层 + 用哪种约束类型」声明意图）。三条协调原则：

1. **检测与裁决分离**：守护轴只标记矛盾，用户决定「改设定 / 加覆写 / 补依据 / 接受并记录」。
2. **意图感知（intent-aware）**：区分「故意覆写」（创造力，已声明 → 记 `accepted` 决策记录）与
   「意外漂移」（技术债，未声明 → 标 `superseded` / 需复核）。
3. **硬度可配置**：守护轴严格度是 per-world / per-branch 的「硬度档」，随四层控制模型的
   `validation mode`（strict/lenient/off）+ 冲突策略（reject/warn/silent）走，不全局一刀切。

**用户「加设定」的五种方式 × 守护轴响应**：

| 用户想做的事 | 落到哪一层 | 守护轴应做 |
|---|---|---|
| 「这片大陆要有山脉」 | Constraint（`geography.yaml`） | 验证引擎是否满足约束；不满足 → warning |
| 「这个 cell 温度就是 30°C」 | Override（`edits.json`） | 检测到与物理推导不符 → info + 记 `accepted` 决策记录，不报错 |
| 「这个世界有魔力」 | Modifier（外生变量） | 校验「后果是否映射到状态变量」；映射不了 → warn |
| 「重力是地球 2 倍」 | physics.yaml override | 按 validation mode（strict/lenient/off）执行 |
| 「沙漠帝国出口木材」 | 叙事文档 | 拷问/grill 检测 → 用户四选一：改叙事 / 加覆写 / 补依据 / 接受并记录 |

业界对这个矛盾的解法见知识库 `docs/knowledge/agent-engineering/self-maintenance-patterns.md`
（hard/soft worldbuilding 光谱 + Sanderson 定律 + canon 管理）。

---

## 3. 设定维护工作流（守护世界的实例）

### 3.1 循环

```
                ┌──────── 写设定 (input yaml/md) ────────┐
                ▼                                        │
         构建/推演 (engine → derived)                     │
                ▼                                        │
   ┌──── 拷问/审计 (设定 vs derived vs 理论) ────┐        │
   │        └→ 发现矛盾 ──┐                       │        │
   │                      ▼                       │        │
   │        补全/修复 (改设定/补卫星/补理由/清文档/修数据) ──┘
   ▼
归档判定 (决策记录 + 构建指纹) → data/worlds/<world>/design-notes/
```

### 3.2 活动清单（映射 ai 命令组）

| 活动 | 说明 | 对应 ai 命令（[ai-cli-commands.md](ai-cli-commands.md)） |
|---|---|---|
| **拷问/审计** | 设定 vs derived vs 理论 | `ai critique`（角色 #5 物理审计员 + #7 叙事一致性守卫） |
| **设定补全** | 气候画像 → 文明种子等 | `ai civ`（附录 D）、`ai trace` |
| **文档清理** | 「只写当前设定」纪律 | 无命令，靠纪律 + 过期检测兜底 |
| **数据一致性** | 手写值 vs 引擎输出 | `ai critique` 数值一致性维度 |
| **外部调研** | 竞品/作品参照 | competitor-analysis 流程 |
| **过期检测** | 指纹 + 渲染 diff | `ai critique --check-stale`（新，§7） |

### 3.3 一条质疑的生命周期

无论问题从哪来（QQ 群 / GitHub issue / B 站弹幕），都走七步：

```
①捕获 → ②取证 → ③拷问/推演 → ④判定 → ⑤处置 → ⑥发布 → ⑦守望
         fact     griller/   决策记录 accepted   渲染回帖  audit check
         context  answerer   proposed 归档 /      FAQ 同步  定期扫
         queries  互审       superseded / 改设定  贴回社区  → 过期自动
                             deprecated          重跑(回到③)
```

使用场景（QQ 群实时拷问、GitHub issue→PR→CI、B 站评论区→批量拷问+自动同步 FAQ、多作者分支 merge 交叉验证、版本回溯、定时巡检）见 §14。

---

## 4. 共享后端：guard 内核

### 4.1 包结构

CLI、skill、API 三入口共享同一内核——**先例是 `narrator.py`**（CLI `narrate` + `/narrate` skill + `POST /narrate` 三处共享同一模块）。守护轴照抄：

```
CLI:  dreamulator ai critique  ─┐
skill: /grill-world            ─┼→ src/dreamulator/guard/ 共享内核
API:   POST /audit (future)    ─┘
      dreamulator guard check  ┘  (过期检测，独立命令)
```

```
src/dreamulator/
├── engine/          # 生成轴：DAG 引擎
├── map/             # 生成轴：地图子系统
├── civmap/          # 生成轴：文明地图
├── guard/           # ★ 守护轴（新，与 engine 平级）
│   ├── facts.py     #   事实上下文（扩展 doc_render，§5）
│   ├── queries.py   #   几何/空间查询（纯函数，§6）
│   ├── stale.py     #   过期检测（指纹 + 渲染 diff，§7）
│   └── critique.py  #   拷问编排（griller/answerer，§9）
├── narrator.py      # 先例：CLI + skill + API 共享
└── doc_render.py    # 先例：单一数据源渲染
```

内核四块全是**纯函数、无 RNG、可单测**（符合项目风格，见 `physical_inputs.py` 先例）。

### 4.2 入口分层

- **skill（交互式）**：`/grill-world` 走子代理互审、逐条追问，面向实时拷问；
- **CLI（批量/自动）**：`ai critique`、`guard check` 面向 CI、定时、发版前；
- **API（future）**：把结果暴露给前端/外部。

后端逻辑同一份，入口只是 UX 差异。

---

## 5. 事实上下文（= 扩展 doc_render）

### 5.1 `build_fact_context()`

`doc_render.py` 的设计原则已经是对的：**「模板是唯一 git 源，读时渲染，渲染产物从不落盘，所以永不漂移」**。`load_render_context()` 现已委托给 `build_fact_context()`，上下文从「参数」扩到「事实」。

**把这个机制从「参数」扩到「事实」，并**按「实体」而非「角色」组织**（见 §5.3）：

```python
# guard/facts.py
def build_fact_context(world_dir, branch=None) -> dict | None:
    """合并实体目录 + 各层 derived summary 为一个渲染上下文 + agent 事实库。

    不是手工拼装的平行 dict，而是「实体系统上的物化视图」：
    - entities：天体（system_catalog.yaml）+ 文明实体 + cell，按稳定 ID 寻址
    - aggregates：命名归约（气候/生态全局统计），带溯源，非实体
    """
    return {
        "entities": {
            "star_ignis": ...,        # system_catalog.yaml（实体属性，稳定 ID）
            "satellite_gaiam": ...,   # 目标体 Nacrea
            "planet_aegis": ...,      # 母行星（父链）
            # ... 其余天体按 ID
        },
        "aggregates": {
            "climate": ...,           # climate_summary.yaml（全局归约，非实体）
            "ecology": ...,           # ecology_summary.yaml
            "civilization": ...,      # habitability / seed
        },
        "spatial": ...,               # 预计算锚点事实（§6 查询的缓存）
    }
```

模板里天体属性按实体寻址：`{{ entities.satellite_gaiam.axial_tilt_deg }}`（旧的 `{{ body.axial_tilt_deg }}`
角色键已废弃，见 §5.3）。

这套上下文**三用**：
1. 设定文档模板（`{{ aggregates.climate.land_mean_t }}`）—— 文档永不手抄过期；
2. 决策记录模板（定量声明引用事实）—— 判定永不手抄过期；
3. **agent 事实库**（griller/answerer 只许从这里取证）—— 防幻觉。

### 5.2 引擎先导出，决策记录才引用

⚠️ 前置依赖：事实上下文里得**先有**拷问要引用的统计量。例如「季节温差中位数 0.8°C」目前 `climate_summary.yaml` 里**没有**，得**扩展各层 `*_summary.yaml`，把拷问需要的统计量导出**（季节温差、驯化潜力计数等）。这是「单一数据源」原则的延伸——不手抄、让引擎导出。

### 5.3 事实上下文 = 实体系统的物化视图（不是平行数据源）

事实上下文与 [vision.md](vision.md) §5 / [civilization-layer.md](civilization-layer.md) 的
**实体（Entity）**概念可结合——结合方式是把事实上下文做成**实体系统上的物化视图**，而非手工拼装的
平行 dict。关键区分两类事实：

| 类型 | 例子 | 处理 |
|---|---|---|
| **实体属性**（有身份） | `satellite_gaiam.axial_tilt_deg`、`star_ignis.luminosity_sol` | 按实体稳定 ID 寻址，直接来自 `system_catalog.yaml` |
| **聚合统计**（无身份） | `climate.land_mean_t`、`ecology.biome_counts` | 命名归约查询（非实体，但需稳定名 + 溯源） |

**证据**：曾经的 `world_parameters.yaml` 就是 `system_catalog.yaml` 的 `target_parameters` 段
**按角色（body/orbit/derived）压平的重复**——天文部分早已是实体，只是丢了身份。事实上下文直接
按实体寻址，消除了这个重复（技术债 #23 已清）。

**收益**（对守护轴最实在的是第 3 条）：
1. **单一数据源**：`world_parameters.yaml` 已删除，事实全部来自 `system_catalog`；
2. **稳定寻址**：实体键改名不破坏模板引用（字符串路径会）；
3. **逐事实过期检测**：实体键 + 溯源（哪实体、哪引擎、哪输入）→ 从「哪里变了」升级到
   「什么变了、为什么变、哪些决策记录受影响」，比整世界 `input_checksum` 精确。

**时机**：P0 起事实上下文即按实体寻址（slug 键）；等 roadmap 的 **Entity ID 系统（UUIDv7 + slug，
P2）**落地后，实体键升到 UUID，获得 rename-proof。旧模板语法 `{{ body.axial_tilt_deg }}` **直接废弃，
不保留别名**（现无外部依赖，不背技术债）。

---

## 6. 几何/空间查询（`queries.py`）

拷问矛盾的一大半是「几何没算」（巨眼崇拜、声呐航海、外卫星凌巨神星这类）。这些必须做成**纯函数查询**喂给 agent，而不是让 agent 心算：

```python
# guard/queries.py（纯函数，无 RNG，可单测）
aegis_visibility(lon_deg) -> {visible, altitude_deg, angular_size_deg}
    # 潮汐锁定几何：Aegis 11° 视直径、9° 倾角 → 某经度能否看到、仰角多少
satellite_transit(sat_id) -> "transit" | "occultation" | "neither"
    # 内卫星凌巨神星 vs 外卫星被巨神星掩
cell_facts(lon, lat) -> {koppen, domesticable_tags, distance_to_coast_km, ...}
    # 锚点空间查询
```

与 `physical_inputs._catalog_body_entry` 同风格：纯函数、引擎辅助、可独立测试。**这是「引擎能辅助吗」的正面回答：几何事实由引擎算，agent 只负责推理。**

---

## 7. 三级过期检测（`stale.py`）

复用 doc_render 已有能力，从粗到精三级：

**① 引用断裂（字段没了）** — 已内置，零成本。`SourceUndefined` 遇到不存在的 `{{ path }}` 会原样回显；checker 扫描渲染产物里残留的 `{{ ... }}`，就是「字段被删/改名」的信号。

**② 输入指纹不匹配** — 复用 `ComputationManifest.input_checksum`（`models/simulation.py`，已接入 `terrain_cache.py`）。每条决策记录记 `checked_against: <input_checksum>`；设定一改 → build 出新校验和 → `guard check` 比对 → 列出「输入已变」。

**③ 数值漂移（渲染 diff）** — 比 ② 更精准。决策记录的定量声明是模板（`{{ aggregates.climate.seasonal_range_C.land.median | round1 }} °C`）；`guard check` 重渲染当前上下文，diff 定量子集：

- 校验和变了 **但** 渲染结果没变 → 这条决策记录引用的事实没被改动 → **结论仍成立，不用重算**；
- 校验和变了 **且** 渲染结果变了 → 事实漂移 → **结论需复核**。

这区分了「设定改了但这条拷问不受影响」与「这条拷问的前提真的变了」——比单纯看校验和精准。

> ⚠️ **意图感知**：上述三级检测默认「不一致 = 意外漂移」。但用户**故意覆写**（如 `edits.json`
> 把某 cell 温度设为 30°C、`physics.yaml` 改重力）产生的「不一致」是**声明过的创造力**，不是漂移。
> `guard check` 遇到「已记录的故意覆写」时报「已知覆写 N 条」（info），而非误报 stale——见 §2.4、
> §8.1 的 `divergence` 标记。

### 决策状态（对齐 ADR）

采用 ADR（Architecture Decision Records，Nygard 2011）的生命周期，与业界主流一致：

| 状态 | 含义 | 触发 |
|---|---|---|
| `proposed` | 尚未定案 | 问题刚提出 |
| `accepted` | 已定案、当前有效 | 拷问后确认自洽（如「季节温差小是物理必然」） |
| `deprecated` | 不再推荐但保留（上下文变了） | 设定弃用但历史保留 |
| `superseded by <编号>` | 被新决策取代 | 拷问发现矛盾 → 改设定 → 旧记录被新记录取代，二者互相链接 |

**核心规则（ADR）：永不编辑已 accepted 的记录——用 supersede 取代它**，以保留决策历史。历史痕迹由
git commit 记录，不由文档保留「旧值→新值」叙事（遵守「只写当前设定」原则）。「删除还是重算」的答案：
`superseded` 即重算并写新记录；前提失效且无后继则标 `deprecated`。

---

## 8. 决策记录台账（ADR）

### 8.1 落点与 schema

采用 ADR 约定（业界主流，模板用 MADR），落点 `data/worlds/<world>/design-notes/`，编号 kebab-case 文件名
（`0001-seasonal-range-too-small.md`），平铺不嵌套。**`design-notes/` 已是代码库的一等「虚拟层」**（API
端点 + 前端「设计笔记」标签页 + 静态导出均支持），ADR 记录放这里自动获得 UI/API 支持：

```markdown
---
status: accepted           # proposed | accepted | deprecated | superseded by 0002-xxx
checked_against: <input_checksum>
divergence: intentional    # 可选：intentional = 故意覆写（创造性分歧），缺省 = 与引擎一致
---

# 0001 — 9° 倾角 + 67 天年是否使季节温差过小？

## 维度 / 目标层
物理一致性 / climate

## 定量事实（模板，读时渲染）
陆地季节温差中位数 {{ aggregates.climate.seasonal_range_C.land.median | round1 }} °C，
最大 {{ aggregates.climate.seasonal_range_C.land.max | round1 }} °C。

## 结论
符合物理（North & Coakley 1979 季节 EBM），无需改。
```

> **创造性分歧**：当用户**故意覆写**（Override / Modifier / physics override）时，决策记录带
> `divergence: intentional` 标记，含义是「这条设定明知偏离物理，是声明的创造力，不是漂移」。
> `guard check` 对这类记录报 info（已知覆写），不报 stale（见 §2.4 意图感知、§7）。

### 8.2 容量上限 + 强制剪枝（借鉴 Hermes）

台账不设上限会变坟场（三年后 `design-notes/` 全是过期条目，`guard check` 在坟场里捞针）。借鉴 Hermes 的
「**容量上限 + 超限写入失败**」：设一个世界一个上限（如 N 条 active 记录），超限时 `guard archive`
强制把最旧的 `accepted` 标 `deprecated` 归档，**写不进去而非静默追加**。

---

## 9. 拷问编排（`critique.py`）

### 9.1 griller/answerer 子代理互审

直接沿用 [audit-plan.md §五](audit-plan.md) 已写好的模式：

- **griller agent**：按维度清单（§9.2）生成问题；
- **answerer agent**：**只许从事实上下文 + 设定文档取证作答，每条必须附 `文件:行号` 或 `derived 字段` 或文献出处**；
- 给不出出处的分歧 → `OPEN` → 升级用户裁决；
- 用 Workflow 编排两者交替（需用户明确授权）。

> ⚠️ **防幻觉优先级**：事实上下文 > 维度清单 > 证据锚定 > 多代理。只加 agent、不给事实库，会产出**更多更自信的幻觉矛盾**。

### 9.2 维度清单（防遗漏）

| 维度 | 检查什么 | 信源 |
|---|---|---|
| 天空现象/轨道几何 | 凌/食/视直径/地平线可见性/天体亮度/光污染 vs 观测条件 | world_parameters + 几何查询 |
| 地理锚点 | 文明锚点 vs 实际地形/海岸/板块 | geography.yaml + 地图 |
| 气候一致性 | 农业/生活方式 vs Köppen/降水/季节 | climate_summary + climate_zones.md |
| 生态一致性 | 驯化潜力 vs 作物/役畜/大型草食动物 | ecology_summary + derived |
| 层内逻辑 | 同层设定自相矛盾 | 该层 input 文档 |
| 跨层因果 | 上层是否依赖已推翻的下层设定 | 全链 |
| 数值 | 文档手抄数字 vs 引擎输出 | derived + diff |
| 边缘条件 | 极昼夜/日食季/潮汐极值是否被考虑 | world_parameters + 设定 |
| 后果映射 | 外生变量/软魔法是否把后果映射到状态变量（Sanderson 第一定律） | 修饰器 + 状态变量 |

维度本身随使用**持续进化**（§12 改进环），不一次性写死。

### 9.3 与 grill-me / ai critique 的关系

| | grill-me（方案拷问） | 设定拷问（本机制） |
|---|---|---|
| 对象 | 人脑里的方案/设计 | 已写下的设定 vs 引擎数据 |
| 证据来源 | 靠用户回答 | 靠事实库 + 几何 + 文献，不靠用户记忆 |
| 交互 | 一次一问、交互式 | 批量、结构化、子代理互审 |
| 产出 | 更扎实的计划 | 矛盾清单 + 决策状态（ADR） |

共用 griller/answerer 机制与证据锚定约束，但对象与证据来源完全不同。`ai critique` 是本机制的 CLI 入口。

### 9.4 harness environment：ai 命令组的统一底层

§9 的底层——**事实上下文 + 原语 + 证据分级**——不止服务于 `ai critique`，而是整个
[ai-cli-commands.md](ai-cli-commands.md) 命令组（narrate / civ / assist / critique…）的**统一环境**。
各命令的区别不在「是否跑在 harness 里」，而在**产出类型**与**对想象的容忍度**。

**三件套**（都已落库，缺的是「统一」而非「新建」）：

| 组件 | 现有落点 | 作用 |
|---|---|---|
| 事实上下文 | `guard/facts.py::build_fact_context` | 感知：实体 + derived summary |
| 原语 / verifier 注册表 | `query_registry`（§6 的查询原语亦注册于此） | 真相：确定性可调用工具 |
| 证据分级协议 | 本条（此前仅存于 grill-world skill 纪律） | 诚实：verified / cited / intentional |

**verifier = 原语**：`QuerySpec.context` 已有 `None（无世界上下文）` 槽位——物理/化学 verifier
（配平、密度-温度、能量预算）就是 `context=None` 的原语，与 `cell_facts`（`context="entities"`）
这类世界查询**同源**。不另建注册表，往 `query_registry` 加 `@query` 条目即可，由改进环（§12）生长。
无插件/文献兜底时允许 LLM 自算，但须标 `computed⚠️`（「结果可能有误」）——这是待升级的过渡态
（补出处→`cited`，或声明为想象→`intentional`），不是合法终态。

**证据三分类**（统一契约，承接 §2.4 意图感知、§8.1 `divergence`）：

| 分类 | 来源 | 谁产出 |
|---|---|---|
| `verified` | 原语 / 引擎 derived | 无 LLM |
| `cited` | 文献 / WebSearch（附出处） | 检索 + 人可查 |
| `intentional` | LLM 想象，显式标注 | LLM，标记「非漂移」 |

「压制幻觉」不是禁止生成（narrate 本就是想象），而是**事实锚定 + 想象标注**：把 `verified` 的交给
原语/引擎，把 `intentional` 的显式标出，杜绝「LLM 自算冒充 verified」。各命令声明自己「期望用哪些
原语、容忍多少 intentional」——narrate 容忍度高（文风即 intentional），critique 容忍度低（结论必须
verified / cited）。

**可扩展性**：verifier 是纯函数、天然可插拔。扩展纪律复用引擎层——按学科命名空间（复用 `layers.py`，
ID 形如 `<layer>.<slug>`）、声明式注册（`@query`）、ADR 治理（`proposed→accepted` + 金丝雀单测）。
具体扩展结构（分级落点 / 自动加载 / 插件 SDK 等）**不预设**，待多人共创有实需时再定。

---

## 10. 硬/软分层（借鉴 Claude Code hook vs CLAUDE.md）

守护轴明确区分「**硬约束（= hook，100% 强制）**」与「**软建议（= 文档，~80% 遵从）**」：

| 层级 | 对应 | 机制 |
|---|---|---|
| 硬约束 | 引擎 derived + checksum + 渲染断链 + 物理不变式 | `guard check` 红灯，必须处理 |
| 软建议 | 决策记录的「结论需复核」、文档「应更新」 | 提示，不阻断 build |

**「必须每次都成立」的规则做成硬约束（hook），不要做成文档建议。** 这是从 Claude Code 官方指引吸收的最重要一条。

守护轴是「**硬度旋钮**」而非固定强度：其严格度挂到四层控制模型的 `validation mode`
（strict / lenient / off）与冲突策略（reject / warn_and_proceed / silent_override）上，per-world /
per-branch 可调——硬科幻世界默认 strict，软魔法分支可 lenient。守护轴**尊重**用户对每条设定声明的
硬度（Hard / Soft / Preference / Override），而非强加一个全局一致标准（见 §2.4）。

---

## 11. 守护轴自检（金丝雀）

守护轴本身也会 silent drift——「守护轴坏了」没人知道，是元层级的漂移。借鉴 Claude Code 的 synthetic canaries：在测试里放**已知答案的合成拷问**（一个已知矛盾的设定，验证它必然被 `guard` 抓出来），作为回归测试。`guard` 管线每次改动都要过金丝雀。

---

## 12. 改进环（决策记录 → 参数处置 → 引擎不变式）

决策记录的产出不能只进台账，要**反向沉淀**（借鉴 Anbao 的 `reflect → attribute → rule update`）：

1. 拷问反复发现的「这类矛盾」→ 沉淀成引擎的**不变式测试**（`tests/test_invariants.py`，见 audit-plan §四）；
2. 反复出现的拷问类型 → 沉淀成 `critique.py` 的**新维度**；
3. 拷问暴露的「手写自由参数」→ 归入 [audit-plan §三](audit-plan.md) 的**参数处置**（A 可推导 / B 创意旋钮 / C 经验常数），A 类替换为物理公式。

守护轴本身也要进化，而不是只守护别人。

---

## 13. 借鉴与超越

守护轴的工程参照——agent 框架（Claude Code / OpenClaw / Hermes）与世界托管平台（World Anvil）
如何防止系统随演化腐烂——已整理为知识库文档
`docs/knowledge/agent-engineering/self-maintenance-patterns.md`（含完整来源）。本节只留结论：

**可借经验**（已吸收进上文各节）：
1. 分层记忆 + 容量限制强删（Hermes）→ §8.2 决策记录容量上限；
2. 确定性 hook vs 建议（Claude Code）→ §10 硬/软分层；
3. cron 定时自主维护 + 自审计（OpenClaw AgentKeeper / Hermes Curator）→ §7 过期检测 + §11 金丝雀；
4. 变量单点更新（World Anvil）→ §5 事实上下文（但 dreamulator 的变量是引擎算的）。

**一个超越点**（§1.3）：从「文本↔文本一致」到「文本↔物理一致」。

---

## 14. 使用场景

### 14.1 QQ 群实时拷问

群友：「你这卫星季节温差这么小，是不是引擎出 bug 了？红矮星耀斑不会烤没大气吗？」你在 Claude Code 里
`/grill-world gaia-m "群友质疑：季节温差太小 + 红矮星耀斑问题"`。skill 结构化出两条拷问（`seasonal-range`
物理一致性 + `flare-retention` 天文一致性）→ 内核 `build_fact_context` + `queries` 取证 → griller/answerer
互审 → 产出两条决策记录：季节温差 `accepted`（9° 倾角 + 67 天年的物理必然），耀斑 `proposed → accepted`
（补写了磁层耦合依据，改 `stellar.yaml`）。`guard check` 自动发现 input 指纹变了，把受影响的记录标「需复核」。
你把渲染结果（数字来自引擎）贴回群，并附「可复核」链接。**群聊里随口一问，变成了可追溯的台账**——
三个月后有人问同样的问题，直接甩记录链接。

### 14.2 GitHub issue → PR → CI

网友提 issue：「裂谷海文明锚点在 Af/Aw，但驯化潜力全黑」。你开 feature 分支 `/grill-world` 确认矛盾
（`cell_facts(锚点)` 返回 domesticable_tags 全 low）→ 改锚点 → 提交 PR。CI 跑 `build` + `guard check`，
PR 页 bot 自动评论：3 条决策记录 superseded、2 条下游派生过期。你逐条复核 → merge → 关 issue 时附
决策记录链接。**评审者（甚至不懂物理的维护者）靠 CI 红绿灯判断「这次改动有没有弄脏旧结论」。**

### 14.3 B 站评论区 → 批量拷问 + FAQ

视频《我用物理引擎造了颗宜居卫星》评论区涌现几十条质疑。一个轻量环节把高频问题聚类成 8 个维度条目 →
`/grill-world --batch` 批量拷问 → 产出（a）决策记录台账（b）FAQ 页面 `docs/worldbuilding/gaia-m-faq.md`，
所有数字用 `{{ ... }}` 模板渲染。**FAQ 里的数字自动同步**——以后改倾角/潮汐，科普稿不用手动更新。
回应视频直接贴 FAQ + 台账链接，质疑从「你骗我」变成「你的推导公式我能查」。

### 14.4 多作者共建（分支 + merge 交叉验证）

A 改气候、B 写文明、C 加卫星，三人并行。各自 feature 分支用 `doc_render` 按分支继承渲染（B 的文明文档
渲染的是 B 分支的 world_parameters，不串 A 改了一半的参数）。merge 前 CI 跑 `guard check` + 跨层交叉验证：
C 的新卫星会不会和 B 的「巨眼崇拜」矛盾？A 改的气候会不会推翻 B 的农业类型？发现矛盾 → `ai reconcile`
缝合或标 OPEN 升级。**矛盾在被读者发现之前，先被 merge 门禁拦截。**

### 14.5 版本回溯——「这个设定当初为什么这么定？」

新人问「为什么倾角是 9° 不是 0° 或 23°？」。不翻聊天记录，直接 `grep design-notes/` 找到当年那条
`accepted` 决策记录（含公式、文献、构建指纹）。**决策记录台账就是世界设定的「决策记忆」**——每个
「为什么这么定」可追溯、可被后人推翻（推翻时旧记录 `superseded`，留下「谁、何时、为何推翻」的痕迹，
由 git commit 记录）。

### 14.6 定时巡检——「文档漂移机器人」

GitHub Actions 每周一跑 `guard check --all`。一旦有决策记录的 `checked_against` 不匹配当前 manifest，
或渲染残留 `{{ }}` 断链，bot 自动开 issue：「以下 5 条结论已过期，请复核」。**过期不是靠「我好像记得
改过什么」发现的，而是校验和 + 渲染 diff 自动报警。**

---

## 15. 分阶段落地

| 阶段 | 内容 | 交付物 | 依赖 | 状态 |
|---|---|---|---|---|
| **P0** | `build_fact_context` 扩展 + 各层 `*_summary.yaml` 补统计量 | 事实上下文 + 字段导出 | 无 | ✅ v0.31.0 |
| **P1** | `stale.py` + `guard check` 命令 + 决策记录模板/状态机（ADR） | 三级过期检测（①②③） | P0 | ✅ v0.31.0 |
| **P2** | `queries.py` 几何/空间查询（天空现象、锚点） | 纯函数 + 单测 | 无 | ✅ v0.31.0 |
| **P3** | `critique.py` 子代理互审 + `/grill-world` skill + 接 `ai critique` | 完整拷问入口 | P0–P2 | 🚧 内核 + skill ✅；「接 `ai critique` CLI」待 `ai` 命令组（roadmap P2） |

P0–P2 是**确定性内核**（纯函数、可单测、不依赖 LLM），先做扎实；P3 是 LLM 编排层，最后接。

---

## 16. 与其他文档的关系

- **总纲**：本文件（守护轴）；[vision.md](vision.md)（愿景，需补「守护轴」为第三条轨道，见 §1.1）。
- **守护引擎**：[audit-plan.md](audit-plan.md)（三波审计），是本文件「两个守护对象」之一。
- **守护世界**：本文件 §3–§12 补全。
- **机制复用**：[layer-control-model.md](layer-control-model.md)（校验层）、[ai-cli-commands.md](ai-cli-commands.md)（`ai critique`/`ai civ`/`ai trace`/`ai reconcile` 入口）。
- **单一数据源**：`doc_render.py`（渲染）、`physical_inputs.py::build_system_catalog`（system_catalog 派生数据）、`ComputationManifest`（校验和）。
- **先例**：`narrator.py`（CLI + skill + API 共享后端）。

---

## 参考资料

- 竞品/框架自维护：见 `docs/knowledge/agent-engineering/self-maintenance-patterns.md`
- ADR 决策记录约定（Nygard 2011，ThoughtWorks「Adopt」）：模板采用 MADR，见 [adr-tools](https://github.com/adr/adr-tools) / [MADR](https://github.com/adr/madr)
- 物理/气候（供 §9.2 维度取证引用）：
  - North & Coakley (1979)，季节能量平衡模型 `T_amp = ΔQ / sqrt(B² + (ωC)²)` —— 见 `src/dreamulator/engine/climate_seasonality.py`
  - Hartmann (2016)，*Global Physical Climatology*，eq. 3.7（日平均日照）
