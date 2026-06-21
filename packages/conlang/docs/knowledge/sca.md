# SCA（Sound Change Applier）知识库

> 本文档是 SCA 音变理论的通用知识参考。
> 如需了解 conlang 包中 SCA 引擎的具体用法，请参阅 [SCA 开发指南](../sca-guide.md)。

---

## 一、什么是 SCA

SCA（Sound Change Applier，音变应用器）是一种自动化工具，用于将**有序音变规则**批量施加到一组词汇上，模拟语言的历史演变过程。

核心思想：

> **输入**：原始语（Proto-language）的词汇表 + 有序音变规则列表
>
> **输出**：后代语（Descendant language）的词汇表

SCA 的哲学基础是**新语法学派假说（Neogrammarian Hypothesis）**：音变是规则的、无例外的（sound change is regular and exceptionless）。这一假说由 19 世纪德国莱比锡学派提出，至今仍是历史比较语言学的基石。

### 与手动推演的关系

手动推演数百个词的音变极其繁琐且容易出错。SCA 将这一过程自动化，同时保证规则执行的一致性和可重复性。

---

## 二、规则语法

### 2.1 基本格式

所有主流 SCA（包括 Zompist SCA²、Lexurgy、TriSCA 以及本项目的引擎）共享同一核心语法：

```
TARGET > OUTPUT / LEFT_ENV _ RIGHT_ENV
```

读作："TARGET 在 LEFT\_ENV 和 RIGHT\_ENV 之间变成 OUTPUT。"

| 符号 | 含义 |
|:---|:---|
| `>` | "变成"（分隔目标与结果） |
| `/` | "在如下环境中" |
| `_` | **目标位置标记**（必填，代表 TARGET 所在之处） |

示例：

```
p > f / V _ V      # p 在两个元音之间变成 f（元音间弱化）
t > t^h / # _      # t 在词首变成送气 t
k > {ch} / _ i     # k 在 i 前颚化
a > e              # 无条件：所有 a 变成 e
```

### 2.2 删除与插入

**删除**（Deletion）：OUTPUT 留空。

```
h > / V _ V        # 元音间的 h 消失（h-deletion）
```

**插入**（Epenthesis）：TARGET 留空，环境中除 `_` 外至少有一个符号。

```
> i / s _ t        # 在 s 和 t 之间插入 i（打破辅音簇）
```

### 2.3 词边界

`#` 表示词的开头或结尾：

```
p > b / # _        # 词首 p 浊化为 b
t > / _ #          # 词尾 t 脱落（词尾除音）
p > p^h / # _      # 词首送气化
```

SCA² 等工具还将空格视为词边界：多词行中，`#` 规则对每个词独立生效。

### 2.4 音类（Categories）

音类是一组音素的命名集合，用单个大写字母或命名标识符表示：

```
V = i e a o u           # 元音类
C = p t k b d g         # 辅音类
F = i e                 # 前元音
Stop = p t k b d g      # 塞音
```

在规则中引用音类时，TARGET 与 OUTPUT 中的音类**按位对应**（1:1 mapping）：

```
V > Vh / _ #           # 词尾元音变长（假设 Vh 是长元音类）
# V = i e a o u，Vh = i: e: a: o: u:
# i→i:, e→e:, a→a:, o→o:, u→u:（一一对应）
```

**即时音类（Nonce Categories）**：用方括号临时创建，无需预先定义：

```
t > s / _ [ie]         # t 在 i 或 e 前变成 s
```

### 2.5 概率音变（Probabilistic Rules）

传统 SCA（如 SCA²）仅支持确定性规则。本项目扩展了概率标签：

```
k > {ch} / _ i [0.4]   # k 在 i 前有 40% 概率颚化
```

概率音变模拟**词汇扩散（Lexical Diffusion）**——王士元（William S.-Y. Wang）于 1969 年提出的理论：音变并非瞬间作用于所有词，而是逐词扩散，高频词往往率先完成变化。

```
实际概率 = 基础概率 × 词频
```

---

## 三、常见音变类型

### 3.1 同化（Assimilation）

一个音变得与相邻音更相似。

```
n > m / _ [pb]         # n 在双唇音前变成 m（部位同化）
s > z / V _ V          # 元音间清擦音浊化（清浊同化）
```

### 3.2 异化（Dissimilation）

相邻音变得更不相似，避免发音困难。

```
l > r / _ l            # 两个 l 相邻时，第一个变成 r
```

### 3.3 弱化（Lenition）

辅音的阻碍程度降低，常发生在元音间或重读音节后。

弱化梯度（以双唇音为例）：

```
p → b → v → w → Ø（完全脱落）
```

```
p > b / V _ V          # 清塞→浊塞
b > v / V _ V          # 浊塞→擦音
v > w / V _ V          # 擦音→近音
```

### 3.4 强化（Fortition）

弱化的逆过程，常发生在词首。

```
w > v / # _            # 词首近音强化为擦音
```

### 3.5 颚化（Palatalization）

辅音在前高元音（i, e）前向硬腭方向移动。

```
k > {ch} / _ F         # 其中 F = i e（前元音类）
t > ts / _ i
```

### 3.6 元音推移（Vowel Shift）

元音系统性移动，通常由链式音变驱动（见第四节）。

### 3.7 脱落（Deletion / Loss）

音素消失，常发生在非重读音节或词尾。

```
h > / V _ V            # 元音间 h 脱落
a > / _ #              # 词尾元音脱落（apocope）
```

### 3.8 音位易位（Metathesis）

相邻音素位置互换，本质上是**不规则**的音变。

```
# SCA² 用 \\ 表示目标串的反转
# 本项目暂无原生支持，需手动拆分规则
```

### 3.9 合流与分裂

**合流（Merger）**：两个音素合并为一个，减少音位数量。

```
e > i                  # e 和 i 合流（e-i merger）
```

**分裂（Split）**：一个音素在特定环境下分化为两个音位，增加音位数量。条件是分裂后的新音素必须出现在能产生对立的语境中。

---

## 四、链式音变（Chain Shifts）

链式音变是 SCA 中最关键也最易出错的部分。当一个音位系统的多个成员联动移动时，就形成链式音变。

### 4.1 拉链（Drag Chain / Pull Chain）

高位音素先移走，留下空位，低位音素随后填补。

以格林定律（Grimm's Law）的塞音子系统为例：

```
// Step 1: 送气塞音先擦化（腾出空位）
p^h > f
t^h > {th}
k^h > x

// Step 2: 清塞音变成送气（填补空位）
p > p^h
t > t^h
k > k^h

// Step 3: 浊塞音变清（填补清塞空位）
b > p
d > t
g > k
```

**关键约束**：规则必须严格按时序书写。如果 Step 1 和 Step 2 顺序颠倒，所有 p 会先变成 p^h，然后 p^h 再变成 f——导致 p 和 p^h 合并，音位对比丧失。

### 4.2 推链（Push Chain）

低位音素先向上挤压，迫使高位音素移走。

```
// Step 1: 浊塞先清化（推挤清塞）
b > p
d > t
g > k

// Step 2: 原来的清塞被挤走（变成送气或擦音）
p > f
t > {th}
k > x
```

同样存在顺序依赖：若 Step 2 先执行，清塞先消失，浊塞清化时就没有"推挤"效果。

### 4.3 元音大推移（Great Vowel Shift）

英语历史上的经典拉链案例（14-17 世纪）：

```
// 长元音系统性高化
a: > e:
e: > i:
i: > ai    # 最高元音"溢出"变成双元音
```

---

## 五、历史语言学经典规律

### 5.1 印欧语系

| 规律 | 核心机制 | SCA 示例 |
|:---|:---|:---|
| **格林定律** | 辅音链式推移 | 见上节 |
| **维尔纳定律** | 重音位置决定擦音清浊 | `f > v / [+accent] _ ` |
| **格拉斯曼定律** | 相邻送气音异化 | `t^h > t / _ ... t^h` |
| **RUKI 定律** | s 在特定音后变 ʂ | `s > {sh} / [ruki] _` |

### 5.2 汉藏语系

| 规律 | 核心机制 | SCA 示例 |
|:---|:---|:---|
| **声调发生学** | 韵尾脱落 → 声调诞生 | `V{'} > V:35`（喉塞韵尾→上声） |
| **全浊清化** | 中古全浊声母按声调分化 | 平声送气、仄声不送气 |
| **尖团合流** | k/ts 在 i,y 前→tɕ | `k > {ch} / _ F`（F = i e） |

---

## 六、音变的条件与触发环境

### 6.1 位置条件

| 位置 | 符号 | 常见音变 |
|:---|:---|:---|
| 词首 | `# _` | 强化（Fortition）、送气化 |
| 词尾 | `_ #` | 脱落（Apocope）、除音 |
| 元音间 | `V _ V` | 弱化（Lenition）、浊化 |
| 重读音节 | `[+stress] _` | 元音保持、辅音强化 |
| 非重读音节 | `[-stress] _` | 元音弱化（→ schwa）、脱落 |

### 6.2 相邻音素条件

| 条件 | 示例 |
|:---|:---|
| 在清音前 | `b > p / _ [ptk]` |
| 在前元音前 | `k > {ch} / _ [ie]` |
| 在鼻音后 | `b > m / [mn] _` |
| 在辅音簇中 | `> i / s _ t`（插入） |

---

## 七、最佳实践

### 7.1 规则顺序的重要性

SCA 规则**严格按书写顺序执行**。同样的规则集合，不同顺序产生不同结果。

```
// 正确：先擦化，后送气化
p^h > f
p > p^h

// 错误：顺序颠倒导致合并
p > p^h      # 所有 p 变成 p^h
p^h > f      # 所有 p^h（包括原来的 p）变成 f
```

### 7.2 从小词典开始

先用 20-50 个核心词验证规则集，确认音变结果符合预期后再扩展到完整词典。

### 7.3 验证新音位的独立性

引入新音素后，检查它是否能与其他音素形成**最小对立（Minimal Pair）**。如果只是环境变体（allophone），则不构成音位分裂。

### 7.4 分阶段书写

将音变按历史阶段分组，每组用注释标注时期：

```
// === Phase 1: 搭嘴音崩溃 ===
| > t
! > t^h

// === Phase 2: 挤喉音退化 ===
p' > p^h
t' > t^h
```

### 7.5 警惕不规则音变

Metathesis（易位）和 Haplology（叠音脱落）本质上是不规则的。SCA 处理这类音变时需要特别小心，通常建议手动处理例外词汇。

---

## 八、主流 SCA 工具对比

| 工具 | 规则格式 | 概率支持 | 特征矩阵 | 多字符 Token |
|:---|:---|:---|:---|:---|
| **SCA²**（Zompist） | `target/replacement/env` | ❌ | ❌ | ❌（单字符） |
| **Lexurgy** | `target => output / env` | ❌ | ✅ | ✅ |
| **TriSCA** | `target > output / env` | ❌ | ❌ | ❌ |
| **ASCA** | `target > output / env` | ❌ | 部分 | ✅ |
| **本项目** | `target > output / env [prob]` | ✅ | ✅（计划中） | ✅（Token-aware） |

本项目的核心优势是 **Token-aware**：基于 ASCIIPA 词法分析器，`{sh}`、`p^h`、`<b` 等多字符结构被视为不可分割的原子 Token，规则不会误伤其内部组件。

---

## 参考资料

- Zompist. [SCA² — Sound Change Applier Help](https://www.zompist.com/scahelp.html)
- Wang, W. S.-Y. (1969). *Competing changes as a cause of residue*. Language, 45(1), 9-25.
- Trask, R. L. (2000). *The Dictionary of Historical and Comparative Linguistics*. Routledge.
- Conlang WikiBooks. [Common Sound Changes](https://en.wikibooks.org/wiki/Conlang/Intermediate/History/Common_sound_changes)
- Stephen Escher. [How to Evolve Your Conlang – Part 1: Sound Change](https://stephenescher.blog/2020/08/30/how-to-evolve-your-conlang-part-1-sound-change/)
