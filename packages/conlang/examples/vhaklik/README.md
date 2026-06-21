# 瓦克里克语（Vha'Klik）综合示例

> 本示例通过一门完整的架空语言，展示 conlang 包的全部核心功能：
> ASCIIPA 编码、IPA 格式转换、TTS 语音合成、SCA 音变模拟。

---

## 背景设定

**瓦克里克语**（Vha'Klik，"守气语"）是绝息高原上守息教派使用的语言。

核心设定：

- **生理适应**：高原空气稀薄，持续呼气说话会导致缺氧。搭嘴音和内爆音利用口腔局部气压差发声，肺部可以保持闭气。
- **宗教哲学**："气（Vha）"= 灵魂。吸气 = 聚能（神圣），闭锁 = 守护（力量），呼气 = 泄魂（渎神）。
- **社会分层**：高阶语（100% 非肺部气流音）vs 低阶语（含肺部气流音，被嘲笑为"无魂之音"）。

---

## 音位表（高阶语）

### 辅音（非肺部气流）

| 类型 | ASCIIPA | IPA | 文化含义 |
|:---|:---|:---|:---|
| 搭嘴音（吸能） | `\|` `!` `\|\|` `=` | ǀ ǃ ǁ ǂ | 内省、聚能、神圣 |
| 挤喉音（锁能） | `p'` `t'` `k'` `s'` `{ch'}` | pʼ tʼ kʼ sʼ tʃʼ | 力量、决断、守护 |
| 内爆音（聚能） | `<b` `<d` `<j` `<g` | ɓ ɗ ʄ ɠ | 接纳天地之气 |

### 元音与声调

```
元音: i e a o u（可长可短 i: e: a: o: u:）
鼻化: i~ e~ a~ o~ u~（灵息态）
声调: :55（高平）:35（高升）:21（低降）:33（中平）
```

---

## 运行示例

### 一键运行 Python 脚本

```bash
cd packages/conlang
python examples/vhaklik/run_example.py
```

### 或使用 CLI 命令

```bash
# Token 化
conlang sca tokenize "p' a"
conlang sca tokenize "{!^h} \a~"

# 格式转换
conlang convert "|a:55" -t ipa
conlang convert "|a:55" -t xsampa
conlang convert "<d e:55" -t ipa

# TTS 发音（需安装 eSpeak-NG）
conlang speak "p' a" --language zu
conlang speak "<b a" --language zu -o mother.wav

# SCA 方言演化
conlang sca run \
  --rules examples/vhaklik/lowland_rules.sca \
  --lexicon examples/vhaklik/highland_lexicon.yaml
```

---

## 功能演示

### 1. ASCIIPA Token 化

ASCIIPA 词法分析器将字符串拆解为不可分割的 Token，确保 `{sh}`、`p^h`、`<b` 等多字符结构不被误伤。

```python
from conlang.phonology import ASCIIPATokenizer

tokenizer = ASCIIPATokenizer()
tokens = tokenizer.tokenize("|a:55")
# → Token('|'), Token('a'), Token(':55')

tokens = tokenizer.tokenize("p'a")
# → Token("p'"), Token("a")    # ' 是终端修饰符，不吞噬后续字符

tokens = tokenizer.tokenize("{ch'}i")
# → Token("{ch'}"), Token("i")  # 花括号宏是完整的黑盒
```

### 2. IPA 格式转换

ASCIIPA 通过 Unicode IPA 中转，可输出多种音标格式。

```python
from conlang.phonology.asciipa import asciipa_to_ipa
from conlang.phonology.xsampa import ipa_to_xsampa

# ASCIIPA → IPA
ipa = asciipa_to_ipa("|a:55")
# → "ǀa˥"（搭嘴音 + 高平调）

# IPA → X-SAMPA
xs = ipa_to_xsampa(ipa)
# → "|\a˥"
```

CLI 方式：

```bash
conlang convert "|a:55" -t ipa       # → ǀa˥
conlang convert "<d e:55" -t ipa     # → ɗe˥
conlang convert "p'a" -t xsampa      # → pa（经 IPA 中转）
```

### 3. TTS 语音合成

> ⚠️ **已知限制**：当前 TTS 后端 eSpeak-NG **无法正确发音瓦克里克语的核心音素**。
> 详见下方"TTS 引擎局限性"一节。
>
> <!-- TODO: 引入 ToucanTTS 作为可选后端，支持非肺部气流辅音的神经合成 -->

#### 当前后端：eSpeak-NG（参数式合成）

eSpeak-NG 通过 Kirshenbaum 格式接受音素输入：

```
ASCIIPA → Unicode IPA → Kirshenbaum → eSpeak-NG → .wav
```

```python
from conlang.phonology.espeak_ng import speak

# 合成并播放
speak("p' a", play=True, language="zu")

# 保存为文件
speak("<b a", output="mother.wav", language="zu")
```

#### eSpeak-NG 的局限性

eSpeak-NG 对**非肺部气流辅音**的支持存在严重缺陷：

| 音素类型 | 支持情况 | 说明 |
|:---|:---|:---|
| **搭嘴音**（ǀ ǃ ǁ ǂ） | ❌ 不支持 | `[[...]]` 音素语法无法触发搭嘴音。搭嘴音被硬编码为"大写字母提示音"，只能通过 `-k 1` 参数间接触发，无法作为正常音素输入 |
| **挤喉音**（pʼ tʼ kʼ） | ⚠️ 受限 | 必须切换到特定语言 Voice（阿姆哈拉语 `am`、阿布哈兹语 `ab`），无法通过英语或祖鲁语 Voice 直接触发 |
| **内爆音**（ɓ ɗ ɠ） | ⚠️ 受限 | 同上，依赖特定语言的字典规则映射，无法通过 `[[...]]` 语法直接使用 |

**根本原因**：eSpeak-NG 的非肺部辅音采用预录 WAV 波形拼接（而非共振峰实时计算），但这些音频样本被绑定在特定语言的音素表中，不暴露给通用的 `[[...]]` 音素输入接口。

**对瓦克里克语的影响**：由于高阶语 100% 由非肺部气流辅音构成（搭嘴音 + 挤喉音 + 内爆音），eSpeak-NG 无法正确合成任何高阶语词汇。低阶语（含肺部气流音）可以部分发音，但失去搭嘴音的平原方言仍不完整。

> <!-- TODO: 计划引入 IMS-Toucan (ToucanTTS) 作为可选 TTS 后端。
>      ToucanTTS 是基于 PyTorch 的神经语音合成系统，支持 7000+ 语言，
>      使用发音特征向量（articulatory features）表示音素，理论上可以合成
>      搭嘴音、挤喉音等非肺部气流辅音。详见 private/tts-toucan-integration.md -->

### 4. SCA 方言演化：高原语 → 平原方言

一支瓦克里克人沿河下山，在洪泛平原定居 4 代（约 150 年）后，语言发生了系统性的音变：

| 阶段 | 变化 | 理论驱动 |
|:---|:---|:---|
| Phase 1 | 搭嘴音崩溃：`\|→t` `!→t^h` `\|\|→l` `=→{ch}` | 标记性层级（最高标记最先消失） |
| Phase 2 | 挤喉音退化：`p'→p^h` `t'→t^h` `k'→k^h` | 富氧环境解除喉压约束 |
| Phase 3 | 内爆音浊化：`<b→b` `<d→d` `<g→g` | 与平原土著科因化 |
| Phase 4 | 声调合并（4→2）：`:55→:5` `:35→:5` `:33→:3` `:21→:3` | 系统简化 |

#### 使用 SCA 引擎

```python
from conlang.phonology import SCAEngine

engine = SCAEngine(seed=42)
engine.load_rules_file("examples/vhaklik/lowland_rules.sca")
engine.load_lexicon_file("examples/vhaklik/highland_lexicon.yaml")
results = engine.apply_all()

for proto, modern in results.items():
    print(f"{proto:20s} → {modern}")
```

#### 词汇演变对照

| 高原语 (Highland) | 平原语 (Lowland) | 含义 |
|:---|:---|:---|
| `\|a:55` | `t a :5` | 气 / 灵魂 |
| `!i:55` | `t^h i :5` | 神圣 |
| `\|\|o` | `l o` | 大地 |
| `<a` | `<a` | 母亲 |
| `<d e:55` | `d e :5` | 父亲 |
| `<g u` | `g u` | 力量 |
| `p'a` | `p^h a` | 守护 |
| `k'u` | `k^h u` | 力量爆发 |
| `s'a` | `s a` | 战吼 |

#### 祈祷文对照

```
高原语（古语）:
  |a:55 . !i:55 . ||o:55
  <d a~ . <d e~ . <d u~

平原语（现代）:
  t a :5 . t^h i :5 . l o :3
  d a n . d e n . g u n
```

> 平原人在念诵祈祷文时，会刻意放慢语速、压低声音，试图模仿古语的"庄重感"，但音素本身已完全肺化。

---

## 文件说明

| 文件 | 用途 |
|:---|:---|
| `run_example.py` | 可运行的 Python 综合演示脚本 |
| `highland_lexicon.yaml` | 高原语词汇表（SCA 输入） |
| `lowland_rules.sca` | 音变规则文件（高原 → 平原） |
| `README.md` | 本文档 |

---

## 相关文档

- [ASCIIPA 语法速查表](../../docs/asciipa-reference.md)
- [SCA 开发指南](../../docs/sca-guide.md)
- [SCA 知识库](../../docs/knowledge/sca.md) —— 音变理论与规则语法
- [命令行工具](../../docs/cli.md)
