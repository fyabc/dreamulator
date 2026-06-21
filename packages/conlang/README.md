# `conlang`

### /kɒnlæŋ/ · Constructed Language Toolkit

> **Design, encode, and evolve constructed languages with code.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#)

---

## What is this?

`conlang` is a Python toolkit for constructed language (conlang) design. It provides:

- **ASCIIPA** — an ASCII-native phonetic alphabet that maps to IPA using escape-based modifiers, brace macros, and LaTeX-style syntax. No Unicode headaches.
- **SCA** — a token-aware Sound Change Applier that simulates historical sound change across generations, with support for probabilistic rules, word-frequency weighting, and chain shifts.
- **Morphology** — an FST-based engine for inflection, derivation, vowel harmony, and consonant mutation.
- **Lexicon** — a dictionary database with YAML persistence, semantic field management, and etymology tracking.

## Quick start

```bash
pip install conlang
```

```python
from conlang.phonology import ASCIIPATokenizer, SCAEngine

# Tokenize ASCIIPA
tokenizer = ASCIIPATokenizer()
tokens = tokenizer.tokenize("{th}I{ng}k")
# → Token('{th}'), Token('I'), Token('{ng}'), Token('k')

# Run sound change
sca = SCAEngine()
sca.add_category("V", "i e a o u")
sca.add_rules([
    "p > f / V _ V",     # Lenition between vowels
    "t > s / V _ V",
    "k > h / V _ V",
])
sca.apply("t a p a")    # → "t a f a"
sca.apply("k a t a")    # → "h a s a"
```

## ASCIIPA syntax cheat sheet

| Feature | Syntax | IPA |
|:---|:---|:---|
| Brace macro | `{sh}` | ʃ |
| Turned/escaped | `\a` | ɐ |
| Small caps | `I` | ɪ |
| Superscript | `^h` | ʰ |
| Subscript | `_o` | ̥ |
| Nasalization | `~` | ̃ |
| Ejective | `'` | ʼ |
| Retroflex | `>` | (hook) |
| Syllable | `.` | . |
| Stress | `!` | ˈ |

## CLI

```bash
conlang asciipa encode "θɪŋk"      # IPA → ASCIIPA
conlang asciipa decode "{th}I{ng}k"  # ASCIIPA → IPA
conlang sca run --rules rules.sca --lexicon words.yaml
conlang tokenize "p^h a . {ng} o"
```

## With dreamulator

`conlang` is designed to work standalone **and** as a subpackage of [dreamulator](https://github.com/your/dreamulator):

```bash
dreamulator conlang evolve earth vha_klik --generations 5
dreamulator conlang tokenize "!i:55"
```

Language data lives under `layers/civilization/input/languages/<lang_id>/`.

## License

MIT
