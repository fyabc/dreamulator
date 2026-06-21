# 命令行工具

## 独立 CLI

安装后可直接使用 `conlang` 命令：

```bash
conlang version                                         # 查看版本
conlang asciipa encode "θɪŋk"                          # IPA → ASCIIPA
conlang asciipa decode "{th}I{ng}k"                     # ASCIIPA → IPA
conlang tokenize "p^h a . {ng} o"                       # Token 拆解
conlang sca run --rules rules.sca --lexicon words.yaml  # 运行音变
```

### `conlang asciipa encode`

将 Unicode IPA 字符串转换为 ASCIIPA 编码。

```bash
$ conlang asciipa encode "θɪŋk"
{th} I {ng} k
```

### `conlang asciipa decode`

将 ASCIIPA 字符串转换回 Unicode IPA。

```bash
$ conlang asciipa decode "{th}I{ng}k"
θɪŋk
```

### `conlang tokenize`

显示 ASCIIPA 字符串的词法拆解结果。

```bash
$ conlang tokenize "p^h a . {ng} o"
ASCIIPA: p^h a . {ng} o
Tokens (5):
  'p^h'  base='p'  mods=('^h',)
  'a'  base='a'  mods=()
  '.'  base='.'  mods=()
  '{ng}'  base='{ng}'  mods=()
  'o'  base='o'  mods=()
```

### `conlang sca run`

从文件加载 SCA 规则和词典，执行音变模拟。

```bash
$ conlang sca run --rules rules.sca --lexicon words.yaml
| a → t a
! i → t^h i
p' a → p^h a
```

可用 `--output` 参数将结果写入文件。

## Dreamulator 集成

在 dreamulator 项目中，通过 `dreamulator conlang` 子命令使用：

```bash
dreamulator conlang evolve earth vha_klik --generations 5  # 多代音变模拟
dreamulator conlang tokenize "!i:55"                        # Token 拆解
```

### `dreamulator conlang evolve`

对指定世界中的一种语言运行多代音变模拟，以表格形式展示每一代的演变结果。

参数：
- `world` — 世界名称
- `language` — 语言 ID（`languages/` 下的目录名）
- `--generations, -g` — 模拟代数（默认 5）
- `--seed` — 覆盖随机种子

### `dreamulator conlang tokenize`

与独立 `conlang tokenize` 功能相同。

## 语言数据目录结构

语言数据存放在 `layers/civilization/input/languages/<语言ID>/` 目录下：

```
languages/vha_klik/
├── sca_rules.sca       # SCA 音变规则脚本
├── lexicon.yaml        # 词典（YAML 格式）
├── phonology.yaml      # 音位表
└── morphology.yaml     # 形态规则
```

### SCA 规则文件格式（`.sca`）

```sca
// 注释以 // 或 # 开头

// 定义音类
V = i e a o u
Click = | ! || =

// Phase 1: 搭嘴音崩溃
| > t
! > t^h
|| > l

// Phase 2: 挤喉音退化（带概率标签）
p' > p^h [0.8]
k' > k^h [0.8]
```

### 词典文件格式（`.yaml`）

```yaml
entries:
  - word: "|a:55"
    gloss: "气/灵魂"
    frequency: 0.95
  - word: "p'a"
    gloss: "守护"
    frequency: 0.80
  - word: "<b a"
    gloss: "母亲"
    frequency: 0.70
```

也支持简单列表格式：

```yaml
- "|a:55"
- "p'a"
- "<b a"
```
