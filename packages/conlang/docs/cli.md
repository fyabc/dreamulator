# 命令行工具

## 独立 CLI

安装后可直接使用 `conlang` 命令：

```bash
conlang version                                         # 查看版本
conlang convert "{th}I{ng}k"                            # ASCIIPA → IPA（默认）
conlang convert "θɪŋk" -f ipa -t asc                   # IPA → ASCIIPA
conlang tokenize "p^h a . {ng} o"                       # Token 拆解
conlang speak "p^h a . t a"                             # 发音（需要 eSpeak-NG）
conlang speak "θɪŋk" -f ipa -o think.wav               # IPA 输入，保存 .wav
conlang sca run --rules rules.sca --lexicon words.yaml  # 运行音变
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

### `conlang convert`

在多种音标表示法之间互转。所有转换均经由 Unicode IPA 作为中间格式。

```bash
# ASCIIPA → IPA（默认）
$ conlang convert "{th}I{ng}k"
θɪŋk

# IPA → ASCIIPA
$ conlang convert "həlˈoʊ" -f ipa -t asciipa

# IPA → Kirshenbaum
$ conlang convert "həlˈəʊ" -f ipa -t kir

# IPA → X-SAMPA
$ conlang convert "həlˈəʊ" -f ipa -t xs

# 逐字符描述
$ conlang convert "həlˈəʊ" -f ipa --chars

# 校验 IPA 合法性
$ conlang convert "həlˈəʊ" -f ipa --check
```

**格式别名**：以下缩写可替代完整格式名使用：

| 别名 | 完整名 |
|:---|:---|
| `kir` | `kirshenbaum` |
| `xs` | `xsampa` |
| `asc` | `asciipa` |

> 参见 [`docs/asciipa-vs-xsampa.md`](./asciipa-vs-xsampa.md) 了解各方案的设计差异。

### `conlang sca run`

从文件加载 SCA 规则和词典，执行音变模拟。

```bash
$ conlang sca run --rules rules.sca --lexicon words.yaml
| a → t a
! i → t^h i
p' a → p^h a
```

可用 `--output` 参数将结果写入文件。

### `conlang speak`

将音标字符串合成为语音并播放或保存为 .wav 文件。底层通过 eSpeak-NG 实现。

**前置要求**：需要安装 [eSpeak-NG](https://github.com/espeak-ng/espeak-ng)。

```bash
# Windows
choco install espeak-ng

# macOS
brew install espeak-ng

# Linux
sudo apt install espeak-ng
```

**基本用法**：

```bash
# 默认 ASCIIPA 格式，直接播放
$ conlang speak "p^h a . t a"

# IPA 格式输入
$ conlang speak "həlˈoʊ" --format ipa

# Kirshenbaum 格式（eSpeak-NG 内部格式；缩写 -f kir 亦可）
$ conlang speak "h @ l 'o U" -f kirshenbaum
```

**保存到文件**：

```bash
# 保存为 .wav，不播放
$ conlang speak "k^w a" -o output.wav --no-play

# 保存并播放
$ conlang speak "k^w a" -o output.wav
```

**参数**：

| 参数 | 缩写 | 说明 | 默认值 |
|:---|:---|:---|:---|
| `text` | — | 音标字符串（必填） | — |
| `--format` | `-f` | 输入格式：`asciipa` (`asc`)、`ipa`、`kirshenbaum` (`kir`) | `asciipa` |
| `--output` | `-o` | 输出 .wav 文件路径 | 不保存 |
| `--play` / `--no-play` | — | 是否播放音频 | `--play` |
| `--language` | `-l` | eSpeak 语言代码（搭嘴音用 `zu`） | `en` |
| `--speed` | `-s` | 语速（词/分钟） | `130` |
| `--pitch` | `-p` | 音调（0–99） | `50` |

**跨平台播放**：自动检测系统音频播放器：
- macOS：`afplay`
- Windows：PowerShell `SoundPlayer`
- Linux：`aplay`（ALSA）→ `paplay`（PulseAudio）→ `ffplay`

**格式转换**：输入会先转换为 Kirshenbaum 格式（eSpeak-NG 的内部音标系统）再传给引擎。映射数据提取自 [ipapy](https://github.com/pettarin/ipapy)（MIT 许可证）。

| 输入（ASCIIPA） | IPA | Kirshenbaum | 说明 |
|:---|:---|:---|:---|
| `p^h` | pʰ | `p<h>` | 送气修饰 |
| `{sh}` | ʃ | `S` | 花括号宏 |
| `{ng}` | ŋ | `N` | 花括号宏 |
| `{th}` | θ | `T` | 花括号宏 |
| `<b` | ɓ | `b`` | 内爆音 |
| `p'` | pʼ | `p`` | 挤喉音 |
| `{!}` | ǃ | `c!` | 搭嘴音（花括号） |
| `\e` | ə | `@` | 转义/倒置 |
| `!` | ˈ | `'` | 主重音（结构性） |

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
