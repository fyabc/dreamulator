# ASCIIPA vs. X-SAMPA

> 参见：[X-SAMPA — 维基百科](https://zh.wikipedia.org/wiki/X-SAMPA)

X-SAMPA 是 1990 年代为在纯 ASCII 环境中表示 IPA 而设计的编码方案。ASCIIPA 解决的是同一个问题，但采用了不同的设计思路。

## 可读性：密码本 vs. 自解释语法

X-SAMPA 是一个**扁平的字符映射表**：每个 IPA 符号被分配一个任意的 ASCII 字符，彼此之间没有逻辑关联。

| IPA | X-SAMPA | 记忆方式 |
|:---|:---|:---|
| ɐ | `6` | 死记：6 号 = 倒置 a |
| ɜ | `3` | 死记：3 号 = 央元音 |
| θ | `T` | 死记：大写 T = theta |
| ʃ | `S` | 死记：大写 S = sh |
| ŋ | `N` | 死记：大写 N = ng |

ASCIIPA 采用**视觉转义**和**语义宏**，让写法本身携带含义：

| IPA | ASCIIPA | 记忆方式 |
|:---|:---|:---|
| ɐ | `\a` | 反斜杠 = 翻转 a |
| ə | `\e` | 反斜杠 = 翻转 e |
| θ | `{th}` | th = 英语 think |
| ʃ | `{sh}` | sh = 英语 ship |
| ŋ | `{ng}` | ng = 英语 sing |
| ʈ | `t>` | t + 右钩 = 卷舌 t |
| ɓ | `<b` | 左钩 + b = 内爆 b |

不需要查表，看到写法就能猜出读音。

## 可扩展性：固定映射 vs. 组合生成

X-SAMPA 为每个 IPA 符号分配固定的 ASCII 字符。当需要表达带有多个附加特征的音素时，只能堆叠后置修饰符（如 `t`_\`_h 表示送气卷舌 t），可读性急剧下降，且修饰符顺序没有统一规范。

ASCIIPA 将音标解耦为 **基础字符 + 正交修饰符**：

```
p^h     送气 p        （上标 h）
p^w     唇化 p        （上标 w）
p_o     清化 p        （下标 o）
p^h_o   送气 + 清化 p （可自由组合）
```

修饰符是正交的，可以自由堆叠，不需要为每种组合预定义映射。这意味着：

- **特征音变规则**可以直接操作特征维度（如"所有送气音在某环境下失去送气"），而不必逐个音素穷举
- **方言微调**可以通过 `{t_a_h}` 这样的花括号封装，把任意特征组合打包为一个独立的"局部音位"
- **`@bind` 指令**允许不同语言或方言在同一文档中重载符号含义，互不污染

## 对比总结

| | X-SAMPA | ASCIIPA |
|:---|:---|:---|
| 特殊符号 | 随机占用数字和大写字母 | 语义化宏与视觉转义 |
| 附加特征 | 后置修饰符堆叠，顺序无规范 | 前置/上标/下标，正交可组合 |
| 多特征音素 | 需预定义或手动堆叠 | 自由组合 + 花括号封装 |
| 符号冲突处理 | 无机制 | `@bind` 作用域隔离 |

## 其他 ASCII-IPA 方案

- [Kirshenbaum (Usenet ASCII-IPA)](https://en.wikipedia.org/wiki/Usenet_ASCII-IPA_transcription) — 维基百科
- [Kirshenbaum ASCII-IPA 详细规范 (PDF)](https://web.archive.org/web/20110927070959/http://www.kirshenbaum.net/IPA/ascii-ipa.pdf) — Internet Archive
