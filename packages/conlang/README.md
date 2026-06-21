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
| 语音合成（可选） | eSpeak-NG via Kirshenbaum 映射 |
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

### 瓦克里克语方言演化

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

## 文档

- [ASCIIPA 语法速查表](docs/asciipa-reference.md) —— 辅音、修饰符、文档级指令的完整语法
- [ASCIIPA vs. X-SAMPA](docs/asciipa-vs-xsampa.md) —— 可读性与可扩展性对比
- [命令行工具](docs/cli.md) —— 独立 CLI 和 Dreamulator 集成命令参考
- [项目结构](docs/project-structure.md) —— 模块说明与文件职责
- [开发指南](docs/development.md) —— 测试、lint、构建
- [路线图](docs/roadmap.md) —— 当前进度与未来计划

## 许可证

MIT
