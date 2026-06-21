# conlang

**人造语言开发工具包** —— 用代码设计、编码和演化自创语言。

> *ASCIIPA 是 IPA 的语法糖 —— 一套人类易读易写的纯文本音标表示方案。*

## 特性

- **ASCIIPA 编码系统** —— 纯 ASCII 音标表示语言，通过转义符、花括号宏和 LaTeX 风格上下标语法映射到 IPA。告别 `UnicodeDecodeError`，无需特殊字体
- **SCA 音变模拟器** —— 基于 Token 词法分析的音变引擎，支持环境匹配、词边界、概率规则、词频加权的世代模拟，以及链式音变（推链/拉链）
- **形态学引擎** —— 基于规则的有限状态转换器（FST），支持前缀/后缀/中缀/环缀、元音和谐、辅音突变
- **词典数据库** —— Pydantic 模型 + YAML 持久化，支持词性、语域、语义场过滤，全文搜索，以及词源追踪链
- **双模式部署** —— 既可 `pip install conlang` 独立使用，也可作为 [dreamulator](../../README.md) 文明层的子模块集成

## 技术栈

| 层 | 技术 |
|---|---|
| 核心语言 | Python 3.12+ |
| 数据模型 | Pydantic v2 |
| 持久化 | PyYAML |
| 语音合成（可选） | eSpeak-NG via X-SAMPA |
| 包管理 | uv / hatchling |

## 快速开始

### 前置要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 安装

```bash
# 独立安装
pip install conlang

# 或在 dreamulator 项目中通过 workspace 自动安装
cd dreamulator && uv sync --all-extras
```

### 第一个例子

```python
from conlang.phonology import ASCIIPATokenizer, SCAEngine

# 1. 将 ASCIIPA 字符串拆解为不可分割的 Token
tokenizer = ASCIIPATokenizer()
tokens = tokenizer.tokenize("{th}I{ng}k")
# → Token('{th}'), Token('I'), Token('{ng}'), Token('k')

# 2. 定义音变规则并运行
sca = SCAEngine()
sca.add_category("V", "i e a o u")
sca.add_rules([
    "p > f / V _ V",     # 元音间弱化
    "t > s / V _ V",
    "k > h / V _ V",
])
sca.apply("t a p a")    # → "t a f a"
sca.apply("a k a t a")  # → "a h a s a"
```

### 瓦克里克语方言演化（完整示例）

```python
from conlang.phonology import SCAEngine

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

## ASCIIPA 语法速查表

ASCIIPA（读作 /æˈskiːpə/）是一门面向纯文本环境的音标领域特定语言（DSL）。核心哲学：**特征即代码**。

### 辅音

| 类型 | 语法 | IPA | 说明 |
|:---|:---|:---|:---|
| 花括号宏 | `{sh}` `{zh}` `{ch}` | ʃ ʒ tʃ | 英语直觉映射 |
| | `{th}` `{dh}` `{ng}` | θ ð ŋ | |
| 大写映射 | `I` `U` `E` `O` `A` | ɪ ʊ ɛ ɔ ɑ | Small Caps |
| | `B` `G` `N` `R` `L` | ʙ ɢ ɴ ʀ ʟ | |
| 转义/倒置 | `\a` `\e` `\v` `\m` | ɐ ə ʌ ɯ | 反斜杠 = 物理翻转 |
| | `\r` `\h` `\w` `\y` | ɹ ɥ ʍ ʎ | |
| 镜像 | `<e` `<A` | ɘ ɒ | 左右翻转 |
| 卷舌 | `t>` `d>` `n>` `s>` | ʈ ɖ ɳ ʂ | 右钩 |
| 横穿 | `i=` `u=` `o=` `h=` | ɨ ʉ ɵ ħ | 横杠 |
| 内爆音 | `<b` `<d` `<g` | ɓ ɗ ɠ | 左钩 |
| 挤喉音 | `p'` `t'` `k'` | pʼ tʼ kʼ | 撇号 |
| 搭嘴音 | `\|` `!` `\|\|` `=` | ǀ ǃ ǁ ǂ | 几何形状 |

### 修饰符

| 类型 | 语法 | IPA | 说明 |
|:---|:---|:---|:---|
| 上标 | `^h` `^w` `^j` | ʰ ʷ ʲ | LaTeX 风格 |
| 下标 | `_o` `_v` `_t` | ̥ ̬ ̪ | |
| 鼻化 | `~` | ̃ | 置于元音后 |
| 音节 | `.` | . | IPA 官方标准 |
| 重音 | `!` | ˈ | 置于音节前 |
| 长音 | `:` | ː | 置于元音后 |
| 声调 | `:55` `:214` | 五度制 | 置于音节末 |

### 文档级指令

```asciipa
@bind click_set          # 交换符号含义，解决冲突
  ! = alveolar_click     # 裸 ! 现在表示搭嘴音
  | = dental_click
@endbind

@unbind !                # 恢复默认
```

## 命令行工具

### 独立 CLI

```bash
conlang version                                    # 查看版本
conlang asciipa encode "θɪŋk"                     # IPA → ASCIIPA
conlang asciipa decode "{th}I{ng}k"                # ASCIIPA → IPA
conlang tokenize "p^h a . {ng} o"                  # Token 拆解
conlang sca run --rules rules.sca --lexicon words.yaml  # 运行音变
```

### Dreamulator 集成

```bash
dreamulator conlang evolve earth vha_klik --generations 5  # 多代音变模拟
dreamulator conlang tokenize "!i:55"                        # Token 拆解
```

语言数据存放在 `layers/civilization/input/languages/<语言ID>/` 目录下：

```
languages/vha_klik/
├── sca_rules.sca       # SCA 音变规则脚本
├── lexicon.yaml        # 词典（YAML 格式）
├── phonology.yaml      # 音位表
└── morphology.yaml     # 形态规则
```

## 项目结构

```
packages/conlang/
├── pyproject.toml                 # 独立包配置
├── src/conlang/
│   ├── phonology/                 # 语音学模块
│   │   ├── asciipa.py             #   ASCIIPA 词法分析器 + IPA 互转
│   │   ├── ipa_table.py           #   IPA 音标映射表
│   │   ├── sca.py                 #   SCA 音变引擎
│   │   ├── features.py            #   音素特征矩阵
│   │   └── xsampa.py              #   X-SAMPA 转换 + TTS 桥接
│   ├── morphology/                # 形态学模块
│   │   ├── fst.py                 #   有限状态转换器引擎
│   │   ├── affix.py               #   词缀规则工厂函数
│   │   └── harmony.py             #   元音和谐 + 辅音突变
│   ├── lexicon/                   # 词汇学模块
│   │   ├── entry.py               #   词典条目 Pydantic 模型
│   │   ├── database.py            #   YAML 持久化数据库
│   │   └── etymology.py           #   词源追踪链
│   └── cli.py                     # 独立 CLI 入口
└── tests/                         # 测试套件
```

## 开发

```bash
# 运行测试
cd packages/conlang && uv run pytest

# 从 dreamulator 根目录运行全部测试
uv run pytest packages/conlang/tests/ tests/

# 代码检查
uv run ruff check packages/conlang/src/ packages/conlang/tests/
uv run ruff format packages/conlang/src/ packages/conlang/tests/
uv run mypy packages/conlang/src/

# 独立构建分发包
cd packages/conlang && uv build
```

## 路线图

- [x] **Phase 1** —— phonology（ASCIIPA + SCA）、morphology（FST）、lexicon（词典库）
- [ ] **Phase 2** —— SCA v2（概率音变 + 词频加权 + 世代模拟）、特征矩阵音变规则
- [ ] **Phase 3** —— syntax 句法模块（语序生成器、依存句法树）
- [ ] **Phase 4** —— orthography 文字系统模块（Abjad/Abugida/Syllabary 转写器）
- [ ] **Phase 5** —— eSpeak-NG TTS 深度集成、神经网络语音合成

## 许可证

MIT
