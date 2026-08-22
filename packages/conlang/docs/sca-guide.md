# SCA 开发指南

> 本文档介绍如何使用 conlang 包中的 SCA 引擎进行音变模拟。
> SCA 的理论基础与规则语法详解，请参阅 [SCA 知识库](knowledge/sca.md)。

---

## 概览

`SCAEngine` 是 Token-aware 的音变引擎。与基于单字符替换的传统 SCA 不同，本引擎先将 ASCIIPA 字符串拆解为不可分割的 Token（如 `{sh}`、`p^h`、`<b`），然后对 Token 序列施加规则——不会误伤多字符结构的内部组件。

源文件：`src/conlang/phonology/sca.py`

---

## 快速开始

```python
from conlang.phonology import SCAEngine

sca = SCAEngine(seed=42)
sca.add_category("V", "i e a o u")
sca.add_rules([
    "p > f / V _ V",     # 元音间弱化
    "t > s / V _ V",
    "k > h / V _ V",
])

sca.apply("t a p a")     # → "t a f a"
sca.apply("a k a t a")   # → "a h a s a"
```

---

## 规则语法速查

完整语法说明见 [SCA 知识库 § 规则语法](knowledge/sca.md#二规则语法)。

```
TARGET > OUTPUT / LEFT_ENV _ RIGHT_ENV [PROBABILITY]
```

| 部分 | 说明 | 示例 |
|:---|:---|:---|
| `TARGET` | 要替换的 Token | `p`, `{sh}`, `p^h` |
| `OUTPUT` | 替换结果（留空=删除） | `f`, `{zh}`, 空 |
| `LEFT_ENV` | 左环境（留空=任意） | `V`, `#` |
| `_` | 目标位置（必填） | |
| `RIGHT_ENV` | 右环境（留空=任意） | `V`, `#`, `F` |
| `[PROB]` | 概率标签 0.0–1.0（可选） | `[0.4]` |

### 特殊环境符号

| 符号 | 含义 |
|:---|:---|
| `_` | 目标位置标记 |
| `#` | 词边界（词首或词尾） |
| `V`, `C` 等 | 引用已定义的音类 |

---

## API 参考

### 初始化

```python
sca = SCAEngine(seed=42)    # seed 用于可复现的概率模拟
```

### 音类管理

```python
# 单个音类（空格分隔字符串或列表）
sca.add_category("V", "i e a o u")
sca.add_category("Front", ["i", "e"])

# 批量添加
sca.add_categories({
    "V": "i e a o u",
    "C": "p t k b d g",
    "Stop": ["p", "t", "k"],
})
```

### 规则管理

```python
# 单条规则
sca.add_rule("p > f / V _ V")

# 批量规则（保持顺序）
sca.add_rules([
    "p^h > f",
    "p > p^h",
])

# 清除所有规则
sca.clear_rules()
```

### 词汇加载

```python
# 从列表加载
sca.load_lexicon(["p a t a", "a k a", "| a:55"])

# 从词频字典加载
sca.load_lexicon({"p a t a": 0.9, "a k a": 0.3})

# 从 YAML 文件加载
sca.load_lexicon_file("lexicon.yaml")
```

YAML 格式支持两种写法：

```yaml
# 简单列表
- "|a:55"
- "p'a"

# 带元数据
entries:
  - word: "|a:55"
    gloss: "spirit"
    frequency: 0.95
  - word: "p'a"
    gloss: "guard"
    frequency: 0.80
```

### 从文件加载规则

```python
sca.load_rules_file("sound_changes.sca")
```

`.sca` 文件格式：

```sca
// 这是注释
# 这也是注释

// 音类定义
V = i e a o u
C = p t k b d g

// Phase 1: 弱化
p > f / V _ V
t > s / V _ V

// Phase 2: 脱落
h > / V _ V
```

### 应用规则

```python
# 单词（确定性，单次遍历）
result = sca.apply("p a t a")

# 带词频的概率应用
result = sca.apply_with_frequency("p a t a", frequency=0.8)

# 批量应用（对已加载的词典）
results = sca.apply_all()
# → {"p a t a": "p a s a", "a k a": "a h a"}
```

### 世代模拟

```python
history = sca.simulate_generations(
    generations=5,
    frequencies={"p a": 0.9, "t a": 0.1},
)
# → {"p a": ["p a", "p a", "b a", ...], "t a": ["t a", ...]}
```

`simulate_generations` 模拟多代人的音变过程，高频词变化更快（`actual_prob = base_prob × frequency`）。

---

## 常见用法示例

### 格林定律（Grimm's Law）微缩版

```python
sca = SCAEngine(seed=42)
sca.add_category("V", "i e a o u")

# 拉链：送气先走，清音填补，浊音上推
sca.add_rules([
    "p^h > f",
    "t^h > {th}",
    "k^h > x",
    "p > p^h",
    "t > t^h",
    "k > k^h",
    "b > p",
    "d > t",
    "g > k",
])
```

> ⚠️ **顺序至关重要**：拉链必须先移高位音素，再让低位填补。顺序错误会导致音位合并。
> 详见 [SCA 知识库 § 链式音变](knowledge/sca.md#四链式音变chain-shifts)。

### 瓦克里克语方言演化

```python
sca = SCAEngine(seed=42)
sca.add_category("V", "i e a o u")

# Phase 1: 搭嘴音崩溃
sca.add_rules(["| > t", "! > t^h", "|| > l"])

# Phase 2: 挤喉音退化
sca.add_rules(["p' > p^h", "t' > t^h", "k' > k^h"])

# Phase 3: 内爆音浊化
sca.add_rules(["<b > b", "<d > d", "<g > g"])

sca.load_lexicon(["| a", "! i", "p' a", "<b a"])
results = sca.apply_all()
# {"| a": "t a", "! i": "t^h i", "p' a": "p^h a", "<b a": "b a"}
```

### 概率音变 + 词汇扩散

```python
sca = SCAEngine(seed=42)
sca.add_category("V", "i e a o u")
sca.add_rule("k > {ch} / _ i [0.4]")    # 40% 概率颚化

# 高频词更可能完成音变
sca.load_lexicon({"a k i": 0.9, "p a k i": 0.1})
history = sca.simulate_generations(generations=10)
```

---

## 测试

```bash
# 运行 SCA 相关测试
cd packages/conlang && uv run pytest tests/test_sca.py -v
```

测试覆盖了：

| 测试类 | 覆盖内容 |
|:---|:---|
| `TestSCABasic` | 无条件替换、环境匹配、词边界、多规则叠加 |
| `TestSCAChainShift` | 拉链、推链的正确性 |
| `TestVhaKlikEvolution` | 瓦克里克语方言演化集成测试 |
| `TestSCAProbabilistic` | 概率规则、词频加权 |

---

## 调试技巧

1. **分阶段验证**：在规则集中间插入断点，逐阶段检查中间结果
2. **最小复现**：用单个词 + 单条规则验证语法是否正确
3. **检查 Token 化**：确认 ASCIIPA Tokenizer 对输入的分词是否符合预期

   ```python
   from conlang.phonology import ASCIIPATokenizer
   tokenizer = ASCIIPATokenizer()
   tokenizer.tokenize("{th}I{ng}k")
   # → Token('{th}'), Token('I'), Token('{ng}'), Token('k')
   ```

4. **打印 Rule 对象**：解析后的规则可以检查各字段

   ```python
   sca.add_rule("p > f / V _ V")
   print(sca._rules[-1])
   # Rule(target='p', output='f', left_env='V', right_env='V', ...)
   ```

---

## 已知限制与未来计划

| 功能 | 当前状态 | 计划 |
|:---|:---|:---|
| 特征矩阵规则 `[+aspirated] > [-aspirated]` | ❌ | Phase 2 |
| 社会语域过滤器 | ❌ | Phase 2 |
| Metathesis（易位） | ❌ | 待评估 |
| 多字符 Token 支持 | ✅ | — |
| 概率音变 | ✅ | — |
| 世代模拟 | ✅ | — |

详见 [路线图](roadmap.md)。
