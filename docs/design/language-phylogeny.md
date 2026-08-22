# 语言谱系子系统设计稿（Language Phylogeny）

> 状态：**设计稿 / 待开发**（2026-08-15，interlude 讨论产物）
> 前置阅读：`packages/conlang/README.md`（已有能力）、`vision.md` §2/§5、
> `architecture.md`（层级与分支）
> 知识基础：`packages/conlang/docs/knowledge/`（比较法、音系类型学、
> 声调发生学、音变库、工具调研）

---

## 1. 背景与目标

dreamulator 的文明层已经支持给文化实体挂接语言
（`Culture.language_id` → `layers/civilization/input/languages/<id>/`），
`packages/conlang` 独立包提供了音变引擎（SCA）、形态学引擎与带词源链的
词典库。但目前缺失一块关键能力：**语言随历史演化**。现实中的语言不是
静态设定，而是从共同祖语分化、在接触中互相借用、随族群兴衰存亡的
动态系统。

本设计稿提出"语言谱系子系统"：把语言的演化纳入 dreamulator 的
推演管线，让一个世界的语言面貌是**从祖语推演出来的派生结果**，
而不是逐个手写的静态设定。

### 1.1 核心洞见：语族树与分支系统同构

历史语言学的树模型与 dreamulator 的分支系统逐字对应：

| 语言学 | dreamulator |
|---|---|
| 祖语（proto-language） | 基干分支（main） |
| 迁徙/隔离导致的分化 | 分支点（fork） |
| 分化点之前的状态共享 | 分支继承（`_inherit`） |
| 分化后各支独立演变 | 分支仅存分叉层及之后的数据 |
| 接触借用（Sprachbund） | 跨分支 merge 边 → 语言 DAG |

这意味着：dreamulator 现有的分支机制在概念上已经"懂"语言谱系，
缺的只是把语言的输入/派生数据挂进这套机制。

### 1.2 与 dreamulator 数据范式的映射

| dreamulator 范式 | 语言谱系对应物 |
|---|---|
| `input/`（人/LLM 写的设定） | 祖语音系、祖语词表、音变规则清单（可由 LLM 起草） |
| `derived/`（引擎计算） | 女儿语词表、屈折形式、地名、语族树文件 |
| 种子化 RNG 可复现 | 音变应用、借词抽取、竞争模拟全部走种子化 RNG |
| 手动覆盖 + 一致性校验 | 用户可手改女儿语词；引擎用规则反推预期值并比对（类比天文引擎 20% 阈值） |
| LLM 只做语义渲染 | LLM 可起草祖语词表语义，但**女儿语词形必须由规则引擎计算**——防止 LLM"幻想"音变 |

## 2. 核心概念速览（面向不熟语言学的读者）

- **祖语**：一个语族的共同祖先，如原始印欧语。创作者设定的起点。
- **音变**：发音随时间发生的规律性变化，如"元音间的 p 变成 f"。
  音变是**条件化、按顺序应用**的——这是语言"演化"的主要机制。
- **女儿语**：祖语经不同音变路线分化出的后代语言。同一祖语 +
  不同规则（或同一组规则但顺序不同）→ 不同的女儿语。
- **同源词**：不同语言中源自同一祖语词的词（英语 father / 拉丁语 pater）。
- **借词**：从邻居语言直接搬来的词，**绕过**本语音变——借词的
  音韵轮廓能暴露它的来源与借入年代。
- **底层（substrate）**：被同化民族的语言虽死亡，仍在新语言中留下
  痕迹（地名、本地物产词、口音）。
- **比较法**：从女儿语反推祖语的方法。本子系统做正向（祖语→女儿语），
  比较法可用于反向校验。

## 3. 数据模型草案

### 3.1 目录结构（挂在世界的文明层输入下）

```
data/worlds/<world>/layers/civilization/input/languages/
├── proto_kaelic/                  # 祖语（一个语言对象一个目录）
│   ├── language.yaml              # 元数据：名称、类型学参数、父语引用
│   ├── phonology.yaml             # 音位清单、音节模板、重音规则
│   ├── lexicon.yaml               # 祖语词表（核心词 + 领域词，带语义场）
│   └── changes/
│       ├── 010_first_shift.sca    # 音变规则（有序，SCA 语法）
│       └── 020_lenition.sca
├── kaelic_north/                  # 女儿语：引用父语 + 自己的增量
│   ├── language.yaml              # parent: proto_kaelic, split_year: -1200
│   ├── changes/
│   │   └── 030_nordic_shift.sca
│   └── overrides.yaml             # （可选）手动覆盖的词形
└── _phylogeny.yaml                # 语族树 + 借用边 + 灭绝标记
```

### 3.2 语族树文件 `_phylogeny.yaml`（草案）

```yaml
tree:
  - id: proto_kaelic
    era: [-2000, -1200]          # 使用年代区间（世界内纪年）
  - id: kaelic_north
    parent: proto_kaelic
    split_year: -1200
    split_cause: migration        # 关联文明层的迁徙事件 ID
borrowing_edges:                   # 接触借用（树的横向边）
  - from: kaelic_north
    to: thalassic_trade_pidgin
    period: [-400, 100]
    intensity: 0.3                 # 借词概率缩放
extinct: []                        # 死亡语言列表（对象保留，见 §4.4）
```

导出兼容格式：`derived/languages/phylogeny.newick`（Newick 文本，
便于与 LingPy/EDICTOR/BEAST 等学术工具互通）。

### 3.3 派生输出（引擎计算，禁止手改）

```
layers/civilization/derived/languages/
├── <id>/lexicon.json              # 女儿语词表（每词附演化轨迹）
├── <id>/toponyms.json             # 地名（附词源层序）
└── cognates.json                  # 同源词集（CognateSet）
```

每个派生词条记录完整推演链：`祖语词形 → 规则1 → 中间形 → 规则2 → …`，
与 conlang 包现有的 `etymology.py` 词源链模型对齐。

## 4. 演化机制

### 4.1 分化（speciation）

触发条件与文明层联动：人群迁徙/地理隔离事件（如山脉隆起、跨海迁徙）
产生分裂点。分裂时记录 `(父语言, 时间, 迁徙事件 ID, 初始方言差异种子)`。
分化速率由**隔离度 × 时间 × 接触度**决定：持续接触的两支只是方言，
彻底隔离数百年才成为不同语言。实现上可用"距离/接触矩阵"调节
各支音变规则的激进程度。

### 4.2 音变应用

直接复用 conlang 包的 `SCAEngine`（环境匹配、概率规则、词频加权、
世代模拟）。每支女儿语 = 父语规则序列 + 本支新增规则，按文件序号
串行应用。**同一组规则换顺序即可产生不同女儿语**
（feeding/bleeding 效应，见 conlang 知识库 sound-change-library.md §10）。

### 4.3 借用（borrowing）

- 借词概率按词类分层：文化词（贸易品、宗教、技术）易借，
  核心词（Swadesh 表）难借；
- 借词必须过**借入方音系过滤**：源词形经借入方的音节模板与
  音位清单适配（复用 SCA 的音类机制）；
- 借用事件写入词源链：`loan from <lang> at <year>`；
- 长期高强度接触 → 结构趋同（Sprachbund）：可先只建模词汇借用，
  结构借用（语序、形态趋同）列为远期。

### 4.4 死亡与底层残留

语言死亡时**不删除语言对象**：标记 `extinct`，词表转为"底层来源池"。
后继语言按概率从池中抽取：
- 地名/河名（河流名最保守——欧洲河名多源于前印欧语底层）；
- 本地动植物、地形、农业词汇；
- （远期）口音/句法干扰。

语言竞争动力学可用 Abrams–Strogatz 模型（*Nature* 424: 900, 2003）：
说话人比例 + 威望参数 s 的竞争 ODE，弱势语指数衰减至亡。
威望可挂钩文明层的权力/声望变量。

### 4.5 地名分层（与地图子系统联动）

地名是**化石化的词源层序**，机制：

1. **通名库**（河/山/堡/渡/港）× 各语言；地名 = 通名 + 修饰语；
2. **改名 = 对旧名施加新语言的音系适配规则**（复用音变引擎，
   而不是重新生成）；
3. **意译（calque）**：逐语素翻译旧名；
4. **化石保留**：地名音变慢于普通词汇——实现为"地名只应用
   部分规则"或冻结某历史阶段的词形。

挂接点：地图 Voronoi cell 的地名字段。政权更迭时触发改名管线，
旧名进入该 cell 的词源层序。

## 5. 与 conlang 包的分工

| 层 | 归属 | 内容 |
|---|---|---|
| 语言内部机制 | `packages/conlang` | 音系编码（ASCIIPA）、音变引擎（SCA）、形态学（FST）、词典/词源模型、文字转写（roadmap Phase 4） |
| 语言之间的历史 | 主仓本子系统 | 语族树、分裂事件、借用网络、地名分层、语言竞争、与文明层/地图层的挂接 |
| 知识文档 | `packages/conlang/docs/knowledge/` | 比较法、类型学、音变库等（已入库） |

原则：**conlang 包保持独立可用**（`pip install conlang`），不依赖
dreamulator；本子系统是它之上的编排层。

## 6. 异星发声模式（xenophonetics）

> 生态层生成智慧物种后，其**发声器官**可能与人不同（鸣管 / 喙 / 鼻囊 / 多重声道）。
> 人类语言的演化规律依赖人类声道，因此异星语言的音系与音变应**从发声器官推导**，
> 而非套用人类 IPA。知识基础见 `docs/knowledge/linguistics/xenophonetics.md`
> （生物声学 + 异星语音学）。

### 6.1 两种模式

| 模式 | 适用 | 音系来源 |
|---|---|---|
| **模式 1：人类发声** | earth 文明层分支 + 其他世界强制 Modifier（发声与人类一致） | 现有 `packages/conlang`（IPA + 音变引擎） |
| **模式 2：异星发声** | 生态层推演出非人发声器官的物种 | 从 `Species.vocal_organs` 推导音位库存 + 音变倾向 |

### 6.2 生态 → 语言的接口

- **输入**：生态层 `Species` 数据模型新增 `vocal_organs` 字段（声源类型 / 调音器 / 共鸣腔）。
- **输出**：语言层音位库存 + 音变规则集（均 derived）。
- **映射**（理论强，source-filter theory + articulatory phonetics）：
  - 声源类型 → 发声机制（喉 / 鸣管双声源 / 鼻囊）→ 音高范围、能否双声源
  - 调音器 → 音位库存（无唇 → 无双唇音；喙 → 无唇塞音；声道长度 → 元音空间 F1/F2）
- **自由度**：创作者在 input 层指定 `vocal_organs` 解剖特征（hard 约束），音位库存/音变规则由引擎推导（derived）。

### 6.3 音变规则的理论基础（强）

异星音变从发声器官的 **articulatory constraints（发音约束）** 出发，不是"随便设计"：

- **Ohala 的 listener-based sound change**：音变 = 听者误解析（misperception）发音约束产生的连续信号。
- **Blevins《Evolutionary Phonology》(2004)**：CHANGE（误听）/ CHANCE（歧义切分）/ CHOICE（语速变体）。
- 推论：**发声器官不同 → articulatory constraints 不同 → 可能的误听/音变不同 → 语言变迁规律不同**。

实现：`packages/conlang` 音变引擎新增「articulatory constraints」参数层，音变规则从器官特征生成/筛选。

### 6.4 ASCIIPA 的异星扩展

ASCIIPA 的「特征即代码」哲学（base + 修饰符 = 特征束，`@bind` 作用域隔离）比 IPA 更适合异星
语言——IPA 是有限符号清单（人类器官），ASCIIPA 是组合式特征编码。扩展只需：

- 新增声源/调音器特征（`@bind source = syrinx`、`@bind articulator = beak` 等）。
- 双声源/多通道是唯一需新概念的难点（需「声道层」记法），其余为特征数据扩展。

### 6.5 分期（异星模式，独立于 §8 的 A–E 人类主线）

- **异星语音 A**：`vocal_organs` 字段 + 声源/调音器 → 音位库存推导（单声道，复用 ASCIIPA 特征化）。
- **异星语音 B**：articulatory constraints → 音变规则生成（Ohala/Blevins 参数化）；双声源/多通道后置。

## 7. 一致性校验回路（"比较法往返"）

dreamulator 的一致性哲学在语言层的落地：

1. **手动覆盖校验**：用户手改女儿语词时，引擎用音变规则正向计算
   预期值并比对；偏差超阈值记 warning（对齐天文引擎范式）；
2. **比较法往返测试**：生成女儿语后，用同源词检测工具（LingPy
   LexStat 类算法）对派生词表做同源判定，验证能否恢复祖语词形与
   语族树拓扑。这是对"音变规则集是否产生可信谱系信号"的端到端测试；
3. **类型学健康检查**：音库规模/音节结构/声调的耦合约束
   （见 conlang 知识库 phonology-typology.md）作为生成时的校验项。

## 8. 分期实施建议

| 阶段 | 内容 | 依赖 |
|---|---|---|
| A | 祖语 + 单一音变链 + 派生词表；`language.yaml` schema；CLI `conlang evolve` 升级为谱系感知 | conlang 包现有 SCA |
| B | 语族树 + 多分支分化；`_phylogeny.yaml`；Newick 导出；分支继承语义（世界分支 fork 时语言树同步 fork） | A |
| C | 借用边 + 地名词源分层（地图挂接）；底层残留池 | B + 地图 cell 地名 |
| D | 语言竞争 ODE（Abrams-Strogatz，挂文明层威望）；比较法往返校验 | B + 文明层状态量 |
| E | 文字系统传播（文字谱系独立于语言谱系）；社会语域（神圣语/俗语分别演化） | conlang roadmap Phase 2/4 |

## 9. 开放问题

1. **语言数据的层级归属**：目前挂在 `civilization/input/languages/`。
   是否需要独立的 `language` 层（介于 ecology 与 civilization 之间）？
   建议暂不新增层，等机制稳定后再议。
2. **世界分支 fork 时的语言树语义**：地质层分支改变地形 → 迁徙路线
   改变 → 语言分化事件不同。语言树应作为文明层的派生结果随分支
   重算，还是作为输入随分支继承？倾向前者（派生），但需评估成本。
3. **计算成本**：词表规模 × 规则数 × 世代数的组合；建议核心词表
   200–500 词起步（社区实践值），领域词按需扩展。
4. **与 narrate 的接口**：语言谱系可为 AI 叙述提供词源细节
   （"这座城市名字的本义已经没人记得"——底层残留的叙事价值）。

## 参考资料

- 调研全文：主仓 `private/research/2026-08-15-conlang-methodology-tools.md`
- Abrams, D. M. & Strogatz, S. H. (2003). Modelling the dynamics of language death. *Nature* 424: 900.
- Bouckaert, R. et al. (2012). Mapping the Origins and Expansion of the Indo-European Language Family. *Science* 337: 957–960.（及其争议：Chang et al. 2015, *Language* 91(1)）
- List, J.-M. et al. LingPy / EDICTOR / Lexibank（lexibank.clld.org）
- GenLang：Cai, A. & Martens, C. (2023). EXAG @ AIIDE 2023, CEUR Vol-3626.
- Johnson, M. R. (2016). Procedural Generation of Linguistics, Dialects, Naming Conventions and Spoken Sentences. PCG Workshop.（Ultima Ratio Regum）
- Rosenfelder, M. *The Language Construction Kit*（Language families 章）.
- 托尔金语族案例：Eldamo（eldamo.org）；*Parma Eldalamberon* 19.
