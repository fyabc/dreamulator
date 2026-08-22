# SCA Phase 2 设计稿：特征音变规则（Feature-based Sound Change Rules）

> 状态：**设计稿 / 待开发**（2026-08-15，interlude 讨论产物）
> 对应 `docs/roadmap.md` Phase 2 第一项（特征矩阵音变规则）
> 前置阅读：`docs/knowledge/sca.md`（现有规则语法）、
> `docs/knowledge/comparative-method.md` §4（喉音理论案例）、
> `docs/knowledge/phonology-typology.md`

---

## 1. 背景：现有 SCA 的局限

当前 `src/conlang/phonology/sca.py` 的规则是**音段字符串级**的：

```
p > f / V _ V          # 把字面上的 p 在元音间变成 f
```

这能表达大部分音变，但有三个表达力缺口：

1. **自然类（natural class）无法一笔写完**。"所有塞音在词尾清化"
   要逐个音段列规则（p>∅/t>k/…）；真实音变作用于发音特征
   （[+stop]），不作用于音段清单。
2. **抽象音段无法建模**。喉音理论式的设计（见 comparative-method.md
   §4）需要"音值不确定、只有功能属性的音段"——例如 *h₂ 的唯一
   定义是"使相邻 e 变成 a，然后自身消失"。字符串规则里它只是一个
   普通符号，其特征行为（着色、延长补偿）要靠散落的规则手动拼凑，
   容易漏、难以校验。
3. **跨音段特征传播不便**。元音和谐、鼻化扩散、声调传播这类
   "特征在词内蔓延"的音变，字符串规则写起来笨拙且易错。

社区参照：Lexurgy（GPL，Kotlin）与 Brassica（Haskell）都已实现
区别特征规则——这是 conlang 工具的事实标准能力（见
`docs/knowledge/conlang-tools.md`）。

## 2. 目标

1. 支持**特征条件与特征结果**的规则：`[+voice] > [-voice] / _ #`；
2. 支持**自定义抽象特征**（如 `[+a-color]`），用于幽灵音段设计；
3. 与现有字符串规则**共存**（不破坏瓦克里克语等既有示例）；
4. 规则应用仍走 `SCAEngine` 的既有管线（环境匹配、概率、词频加权、
   世代模拟、种子化 RNG）。

## 3. 特征系统设计

### 3.1 特征库（内置 + 可扩展）

`src/conlang/phonology/features.py` 已有特征矩阵骨架，扩展为完整库：

**辅音特征**：
- 发音方式：`[manner: stop/fricative/nasal/approximant/lateral/trill]`
- 发音部位：`[place: labial/dental/alveolar/palatal/velar/uvular/pharyngeal/glottal]`
- 声门状态：`[±voice]`、`[±aspirated]`、`[±ejective]`、`[±implosive]`
- 气流机制：`[airstream: pulmonic/click]`

**元音特征**：
- `[height: high/mid/low]`、`[backness: front/central/back]`、
  `[±round]`、`[±long]`、`[±nasal]`
- **声调特征**（预留，供 tonogenesis 规则包使用，见
  `docs/knowledge/tonogenesis.md`）：`[tone: high/mid/low/rise/fall/checked]`

**自定义抽象特征**（幽灵音段的关键）：
- 用户可为任意音段声明私有特征，如 `[+a-color]`、`[+o-color]`。
  抽象特征**不预设任何发音含义**——这正是索绪尔式"代数功能定义"
  的工程化。

### 3.2 音段描述 = 特征束

每个音段在词表中以 ASCIIPA token 表示（现有 tokenizer 不变），
其特征束从特征矩阵查询得到；未知音段可由用户显式声明特征束：

```yaml
# phonology.yaml 中的抽象音段声明
abstract_segments:
  - segment: h2           # ASCIIPA 写法
    features: [+consonantal, +a-color]     # 只有功能，没有音色
  - segment: h3
    features: [+consonantal, +o-color]
```

## 4. 规则语法草案

在现有 `X > Y / A _ B` 骨架上扩展三类成分：

```
# (1) 特征条件/结果（方括号）
[+voice] > [-voice] / _ #            # 词尾清化
V > [+nasal] / _ N                   # 鼻音前元音鼻化

# (2) 特征选择器（选出一类音段作为目标）
[manner:stop] > ∅ / _ #              # 所有塞音词尾脱落

# (3) 抽象特征传播/触发
V:high > V:mid / _ [+a-color]        # 高元音在 a 着色音旁降低
e > a / _ C[+a-color]                # 元音着色
C[+a-color] > ∅                      # 着色音消失（留下"疤痕"）
```

语义细节：
- 规则内特征表达式求值顺序与现有一致：**按序串行**，支持
  feeding/bleeding（见 sound-change-library.md §10）；
- 概率规则 `[0.X]` 与词频加权对特征规则同样生效；
- 字符串规则与特征规则可混排在同一规则文件中，按序执行。

## 5. 杀手级测试用例：复现喉音理论

以 comparative-method.md §4 的喉音案例做端到端集成测试——
它同时检验抽象特征、着色、延长补偿、消失四类能力：

**祖语设定**（约 8 个词根足够）：
- 音系：元音 e a o i u；抽象音段 h1（不着色）、h2（[+a-color]）、
  h3（[+o-color]）；
- 词例：`peh2ter`（父）、`h2ster`（星）、`h1esti`（是）、
  `h3ekto`（八）、`dheh1`（放置）等。

**规则链**（对应三大结构效应）：

```
# 着色：相邻 e 按喉音特征变色
e > a / _ C[+a-color]
e > o / _ C[+o-color]

# 延长补偿：e + 喉音 + 辅音 → 长元音
V > [+long] / _ C[+laryngeal] C

# 词首补元音（prothesis）：词首喉音消失后补 e/a/o
∅ > a / # _ C[+a-color]
∅ > o / # _ C[+o-color]
∅ > e / # _ C[+laryngeal]

# 喉音本体消失
C[+laryngeal] > ∅
```

**期望的女儿语输出**（对照现实希腊语痕迹）：
- `peh2ter` → `patēr`（a 着色 + 延长）
- `h2ster` → `aster`（词首补 a + 消失）
- `h1esti` → `esti`（词首补 e）
- `h3ekto` → `oktō`（o 着色）

**测试断言**：
1. 输出与上表逐词一致（确定性种子下）；
2. 女儿语中**不存在任何喉音 token 残留**；
3. 每个输出词的 etymology 链完整记录"哪条规则在哪一步产生了
   哪个变化"——疤痕可追溯。

这个测试同时是文档：它演示了"幽灵音段设计模式"的完整工作流
（在祖语埋下将消失的音段 → 女儿语获得元音交替/延长/补元音疤痕 →
世界内学者可从疤痕反推）。

## 6. 实现要点

| 模块 | 改动 |
|---|---|
| `features.py` | 扩展特征库 + 自定义特征声明 + 特征束查询 API |
| `sca.py` | 规则解析器扩展（特征表达式）；应用引擎对 token 做特征匹配；抽象特征传播 |
| `asciipa.py` | 原则上不变；抽象音段沿用普通 token 语法 |
| 新文件（建议） | `tests/test_feature_rules.py`（含喉音理论端到端用例） |

分两步落地：
1. **2a**：特征条件/结果 + 自然类选择器（覆盖词尾清化、鼻化扩散等
   常规需求）；
2. **2b**：自定义抽象特征 + 传播语义 + 喉音理论测试用例。

## 7. 与 roadmap 其他项的关系

- **声调特征**（本稿 §3.1 预留）：tonogenesis 规则包
  （tonogenesis.md §4）依赖声调进入特征系统，可在 2b 之后作为
  独立增量交付；
- **类推与借用 pass**：特征系统不解决"例外系统化"问题——
  类推平整与借词绕过是独立的规则阶段（见 sound-change-library.md
  §9 与主仓 `docs/design/language-phylogeny.md` §6），建议列为
  Phase 2 的后续独立项；
- **社会语域过滤器**（roadmap Phase 2 第三项）：与本稿正交——
  语域是"对哪些词应用规则"的过滤器，特征是"规则怎么写"的表达能力。

## 8. 开放问题

1. **特征冲突仲裁**：一个音段同时匹配多条特征规则时的应用顺序
   已有（按序串行），但同一规则内多个特征改变的原子性需要明确
   （建议：单条规则的所有特征改变原子应用）。
2. **alpha 记法（±变量）**：如 `αvoice > αvoice`（同化）是否需要？
   初期可用两条显式规则替代，暂不实现。
3. **特征完备性**：UPSID/PHOIBLE 中罕见音段的特征描述可能不全，
   允许用户以 YAML 覆盖任何音段的特征束。

## 参考资料

- 调研全文：主仓 `private/research/2026-08-15-conlang-methodology-tools.md`
- Lexurgy 规则文档：https://www.lexurgy.com/sc （特征语法参照）
- Brassica：https://github.com/bradrn/brassica （特征系统参照）
- 喉音理论：`docs/knowledge/comparative-method.md` §4；
  Saussure (1879)、Kuryłowicz (1927)。
- Chomsky, N. & Halle, M. (1968). *The Sound Pattern of English*.
  Harper & Row.（区别特征框架的经典来源；本设计采用其简化教学版）
- Clements, G. N. & Hume, E. V. (1995). The internal organization of
  speech sounds. In Goldsmith (ed.) *The Handbook of Phonological Theory*.
