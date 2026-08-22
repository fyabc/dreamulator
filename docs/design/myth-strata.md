# 神话层累数据模型设计稿（Myth Stratigraphy）

> 状态：**设计稿 / 待开发**（2026-08-15，interlude 讨论产物）
> 前置阅读：`vision.md` §3（拥抱粗粒化）/§5（关系即本质）、
> `docs/knowledge/sociology/myth-phylogenetics.md`（知识底座）
> 相关设计：`language-phylogeny.md`（母题传播与语言树联动）

---

## 1. 背景与目标

文明层需要"上古文明记忆"：神话、传说、母题——它们不是静态装饰，
而是**随人群迁徙分化、在传承中层累变形的文化遗产**。现实学术用
系统发生比较法（PCM）从观察到的神话分布反推祖型；dreamulator 作为
生成器做正向问题：**从祖型神话出发，经分裂、变异、借用、层累，
生成世界内各文化观察到的神话分布**。

这与语言谱系的设计完全同构（祖语→女儿语 ↔ 祖型神话→各文化变体），
两者共享同一套架构思想，数据上也可以联动（母题沿语言树传播）。

### 1.1 两种认知视角（本设计的核心）

同一份数据支持两种视角：

- **上帝视角（创作者）**：知道完整推演 DAG——祖型神话、每次变异、
  每次借用、每个物理锚点。对应 `input/` + 引擎内部状态；
- **研究视角（世界内学者）**：只看到各文化现存的神话变体
  （碎片化、有缺失），做竞争性重建——同源说 vs 传播说 vs
  独立发明说，学派争论。对应 `derived/` 的可观察部分。

**两种视角共享同一份数据，零额外维护**。世界内学者的"错误但合理"
的理论不是 bug，而是被设计出来的内容（现实模板：喉音理论被嘲笑
50 年；印欧起源安纳托利亚说 vs 草原说至今未决）。

## 2. 核心概念

- **母题（motif）**：可编码的最小叙事单元，如"射手射落多余之日"
  "七位天女被追逐"。对应现实民俗学的 motif/mytheme 概念
  （Thompson 母题索引、Berezkin 母题库为分类参照）。
- **祖型神话（proto-myth）**：上古节点上定义的母题组合体，携带
  核心 mytheme 特征集。
- **变体（variant）**：母题在某文化、某时代的具体形态（叙事文本、
  角色替换、情节增删）。
- **被见证（attestation）**：变体在世界内留下证据的事件
  （口头传统的记录年代、文献、考古遗存）。
- **层累（stratification）**：神话在传承中被历史化、被宗教叠写、
  被重新解释的过程——变形不是噪声，而是**携带历史信息的沉积层**。

## 3. 数据模型草案

### 3.1 母题即 UUID 实体

遵循 `vision.md` §5"关系即本质"：同一母题在不同文化中的不同名字
指向同一个 UUID（如同 Mars/Ares/荧惑指向同一实体）。

```yaml
# layers/civilization/input/myths/motifs/motif_sun_archer.yaml
id: motif_sun_archer              # 稳定 ID；底层用 UUID
name_zh: 射手射落多余之日
mythemes:                          # 核心特征集（可编码结构）
  - multiple_suns                  # 多个太阳
  - excessive_heat                 # 焦土灾难
  - archer_hero                    # 射手英雄
  - survivor_single_sun            # 留一日
core_semantics: 解释"为何只有一个太阳"的起源叙事
proto_attestation:                 # 祖型被设定的上古节点
  era: -8000                       # 世界内纪年
  carrier_culture: proto_riverfolk # 承载人群（文明层实体 ID）
```

### 3.2 谱系：树 + 网络

```yaml
# layers/civilization/input/myths/phylogeny.yaml
nodes:
  - motif: motif_sun_archer
    variant: v_twin_archers        # 某文化的变体
    parent: motif_sun_archer@proto # 垂直继承
    changes:                       # 沿边发生的变异（层累机制，见 §4）
      - euhemerization             # 神射手 → 人间帝王
      - calendric_overlay          # 叠加历法解释（旬制）
    attested: -500
borrow_edges:                      # 水平传播边
  - from: motif_sun_archer@v_x
    to: motif_moon_tamer@v_y
    via: trade_route_cell_142      # 传播路径（地图 cell）
    era: -300
```

纯树不现实（神话高度可借），**树 + 借用边 = 神话 DAG**。
现实研究（Tehrani 2013）正是靠网络分析识别出东亚"虎姑婆"是
两条谱系的杂交——生成时也应显式建模这种杂交事件。

### 3.3 派生输出（世界内可观察层）

```
layers/civilization/derived/myths/
├── attestations.json              # 各文化现存变体分布（研究视角的数据源）
├── reconstruction_hypotheses.json # （远期）世界内学者的竞争重建
└── motif_map.json                 # 母题地理分布（前端可视化）
```

## 4. 层累机制库（变异规则）

现实案例归纳出的机制类型——神话沿谱系边变异的"规则库"
（每条都是真实发生过的模式，详见知识库 myth-phylogenetics.md §3）：

| 规则 | 定义 | 现实案例 |
|---|---|---|
| `euhemerization` 历史化 | 神 → 传说帝王 → 凡人 | 中国古史层累；希腊欧赫迈罗斯化 |
| `etiologic_inversion` 知识叙事化 | 历法/星官知识失落后被重新解释为故事 | 织女星官 → 牛女叙事；"十日" → 旬制神话化 |
| `religious_overlay` 宗教叠写 | 新宗教吸收旧神职能 | 猕猴祖神话佛教化（观音化身 + 罗刹女） |
| `fragment_hybridization` 碎片杂交 | 两条谱系的模块重组 | 虎姑婆 = 小红帽 × 狼和七只小山羊 |
| `astronomical_personification` 天文拟人化 | 天体关系 → 追逐/婚配 | 猎户追逐昴星团 |
| `numeric_tension` 数字张力 | 观测与传说数字差催生解释 | "丢失的普勒阿得斯"；六连星 |
| `motif_loss` / `motif_gain` | 母题丢失/添加 | 常规谱系变异 |

规则应用参数：各机制的触发概率可挂接文明层状态
（宗教更迭事件触发 `religious_overlay`；历法知识失传触发
`etiologic_inversion`）——**层累不是随机变形，而是与文明事件
因果关联的变形**。

## 5. 物理锚定（dreamulator 的独特优势）

现实民俗学只能靠独立锚点旁证口头传统年代（Nunn & Reid 2016 的
≥7000 年洪水记忆；Norris 的恒星自行）。dreamulator 的引擎**拥有
ground truth**：

1. **可定年事件**：日食、海侵海退、超新星、撞击、气候突变——
   由引擎计算，带精确年代（事件 UUID）；
2. **神话引用事件**：祖型/变体的 mytheme 可锚定事件
   （"大洪水" ↔ 冰后期海侵的具体模拟结果）；
3. **世界内断代**：学者用锚点事件给神话定年——锚点选择本身
   可以成为学派争论点；
4. **可信度梯度设计**：刻意放置不同"树性"的母题——核心创世神话
   强垂直继承；trickster 故事沿商路传播；大河流域洪水神话独立发明。
   世界内学者争论"同源还是趋同"，争论即世界质感。

**口头传统年代上限**应作为世界参数：保守设定 ~7–10 kyr（Nunn & Reid
实证锚点）；若世界采用"深度神话"宇宙法则（如 branch/deep-mythology），
可放宽至万年以上——争议理论作为分支宪法，见 §7。

## 6. 与 dreamulator 各子系统的挂接

| 子系统 | 挂接方式 |
|---|---|
| 文明层实体 | 母题承载者 = `Culture`/聚落实体；宗教更迭事件触发叠写规则 |
| 语言谱系（language-phylogeny.md） | 母题沿语言树传播（Mace & Pagel 范式）；神话词汇进入语言词表（神名、圣语词——对应 conlang roadmap 的"社会语域"） |
| 地图层 | 传播路径 = 地图 cell 邻接/商路；圣地 = cell 标记 |
| narrate | **认知姿态参数**（§6.1） |
| 实体网络（Moltke 远期） | 母题 UUID 实体最终并入实体网络引擎 |

### 6.1 narrate 的认知姿态扩展

给叙述系统加一个参数：

- `omniscient`：读全部 input + derived，输出创作者视角的完整谱系；
- `in_world_scholar`：只读 `attestations.json`（现存变体分布），
  不知道祖型，输出带置信度与学派争议的推测性重建。

这是"双视角共享一份数据"的产品化出口：同一次构建可以生成两种
叙事——上帝视角的设定书，与世界内学者视角的"考古报告"。

## 7. 认识论定位：争议理论作为可能性

知识库（myth-phylogenetics.md）对现实研究做了三档可信度标注
（共识/弱校准/大胆假说）。本子系统消费这些知识的原则：

1. **共识机制**（层累机制库、树+网络模型、锚定断代）直接作为
   引擎硬规则；
2. **争议性年代学主张**（万年级深度传承、走出非洲神话共祖、
   野人=古人类记忆）不进入默认引擎，而作为**可切换的宇宙法则**：
   `main` 分支用保守参数；`branch/deep-mythology` 可开启深度传承——
   对齐 vision.md §4"分支系统作为多元宇宙的宪法"；
3. **世界内科学包含争议**：生成世界时，刻意保留证据含糊的开放
   问题（两个学派都能自圆其说）——一个"一切已定论"的世界内
   学术是不真实的。

## 8. 分期实施建议

| 阶段 | 内容 |
|---|---|
| A | 母题实体 schema（YAML）+ 祖型定义 + 静态变体分布；narrate 可引用 |
| B | 谱系引擎：分裂（随文明迁徙事件）+ 层累机制库 + 派生 attestations |
| C | 借用边 + 碎片杂交；与语言谱系联动（母题沿语言树传播） |
| D | 物理锚定（引擎事件 ↔ 母题引用）；前端母题分布图/时间轴 |
| E | 世界内学者重建生成（reconstruction_hypotheses）+ narrate 认知姿态参数 |

## 9. 开放问题

1. **mytheme 编码方案**：自由标签 vs 受控词表（参照 Thompson 母题
   索引或 Berezkin 分类）？受控词表利于引擎规则匹配，但限制创作
   自由。倾向"受控核心集 + 自由扩展标签"。
2. **神话与宗教的关系**：宗教系统（尚未实装）与神话层累的边界——
   宗教叠写规则依赖宗教更迭事件，可能需要先定义宗教实体的最小 schema。
3. **借用强度参数**：与语言借用边是否共用同一接触矩阵？
   倾向共用（商路同时传播故事与词汇）。
4. **叙事文本生成**：mytheme 结构 → 具体叙事文本由 LLM 渲染
   （对齐 vision.md §2"LLM 作为血肉填充"）；结构是 input/derived，
   文本是渲染产物。

## 参考资料

- 知识底座：`docs/knowledge/sociology/myth-phylogenetics.md`
- 调研全文：主仓 `private/research/2026-08-15-pcm-cultural-phylogenetics.md`、
  `2026-08-15-myth-case-studies.md`
- Graça da Silva, S. & Tehrani, J. J. (2016). *R. Soc. Open Sci.* 3: 150645.
- Tehrani, J. J. (2013). *PLOS ONE* 8: e78871.
- Nunn, P. D. & Reid, N. J. (2016). *Australian Geographer* 47: 11–25.
- Witzel, E. J. M. (2012). *The Origins of the World's Mythologies*. OUP.
- d'Huy, J. (2020). *Cosmogonies. La préhistoire des mythes*. La Découverte.
- 王小盾 (1997). 汉藏语猴祖神话的谱系.《中国社会科学》第 6 期.
