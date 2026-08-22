#!/usr/bin/env python3
"""瓦克里克语（Vha'Klik）综合示例 —— 展示 conlang 包的全部核心功能。

运行方式（从 conlang 包根目录）：

    python examples/vhaklik/run_example.py

或通过模块方式：

    python -m examples.vhaklik.run_example
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# 确保从 src/ 导入（当直接运行脚本时）
_PKG_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PKG_ROOT / "src"))

# Windows 控制台 GBK 编码无法输出 IPA 字符，强制 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from conlang.phonology.asciipa import ASCIIPATokenizer, asciipa_to_ipa
from conlang.phonology.sca import SCAEngine
from conlang.phonology.xsampa import ipa_to_xsampa

# ---------------------------------------------------------------------------
# 数据路径
# ---------------------------------------------------------------------------
_EXAMPLE_DIR = Path(__file__).resolve().parent
_LEXICON_PATH = _EXAMPLE_DIR / "highland_lexicon.yaml"
_RULES_PATH = _EXAMPLE_DIR / "lowland_rules.sca"

# ---------------------------------------------------------------------------
# 瓦克里克语示例词汇（含注释）
# ---------------------------------------------------------------------------
SAMPLE_WORDS: list[tuple[str, str]] = [
    ("|a:55", "气 / 灵魂 (Vha)"),
    ("!i:55", "神圣"),
    ("||o", "大地"),
    ("<a", "母亲"),
    ("p'a", "守护"),
    ("<d e:55", "父亲"),
    ("k'u", "力量爆发"),
]


def print_header(title: str) -> None:
    """打印分节标题。"""
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


# ---------------------------------------------------------------------------
# 1. ASCIIPA Token 化
# ---------------------------------------------------------------------------
def demo_tokenize() -> None:
    print_header("1. ASCIIPA Token 化")
    print("  将 ASCIIPA 字符串拆解为不可分割的 Token，")
    print("  确保 {sh}、p^h、<b 等多字符结构不被误伤。\n")

    tokenizer = ASCIIPATokenizer()
    for word, gloss in SAMPLE_WORDS[:4]:
        tokens = tokenizer.tokenize(word)
        tok_strs = [t.raw for t in tokens]
        print(f"  {word:16s}  →  {tok_strs}")
        print(f"  {'':16s}     「{gloss}」")


# ---------------------------------------------------------------------------
# 2. IPA 格式转换
# ---------------------------------------------------------------------------
def demo_ipa_conversion() -> None:
    print_header("2. 格式转换：ASCIIPA → IPA → X-SAMPA")
    print("  ASCIIPA 通过 Unicode IPA 中转，可输出多种音标格式。\n")

    print(f"  {'ASCIIPA':20s}  {'IPA':20s}  {'X-SAMPA':20s}  {'含义'}")
    print(f"  {'-'*20}  {'-'*20}  {'-'*20}  {'-'*12}")

    for word, gloss in SAMPLE_WORDS:
        ipa = asciipa_to_ipa(word)
        xsampa = ipa_to_xsampa(ipa)
        print(f"  {word:20s}  {ipa:20s}  {xsampa:20s}  {gloss}")


# ---------------------------------------------------------------------------
# 3. SCA 方言演化
# ---------------------------------------------------------------------------
def demo_sca_evolution() -> None:
    print_header("3. SCA 方言演化：高原语 → 平原方言")
    print("  加载词汇表和音变规则，自动推演瓦克里克语的平原方言。\n")

    # 加载规则
    engine = SCAEngine(seed=42)
    engine.load_rules_file(_RULES_PATH)
    engine.load_lexicon_file(_LEXICON_PATH)
    results = engine.apply_all()

    print(f"  {'高原语 (Highland)':28s}  {'平原语 (Lowland)':28s}")
    print(f"  {'-'*28}  {'-'*28}")
    for proto, modern in results.items():
        print(f"  {proto:28s}  {modern:28s}")


# ---------------------------------------------------------------------------
# 4. 词汇演变对照（含推导过程）
# ---------------------------------------------------------------------------
def demo_evolution_detail() -> None:
    print_header("4. 词汇演变详解（逐规则追踪）")
    print("  以 '气/灵魂'（|a:55）为例，展示每一步音变过程。\n")

    word = "|a:55"
    gloss = "气 / 灵魂"
    print(f"  原始词：{word}  「{gloss}」\n")

    tokenizer = ASCIIPATokenizer()
    tokens = tokenizer.tokenize(word)
    print(f"  Token 化：{[t.raw for t in tokens]}")

    # 手动逐条规则应用
    rules = [
        ("| > t", "搭嘴音崩溃：| → t"),
        (":55 > :5", "声调合并：:55 → :5"),
    ]

    engine = SCAEngine(seed=42)
    current = word
    for rule_str, explanation in rules:
        engine.clear_rules()
        engine.add_rule(rule_str)
        new = engine.apply(current)
        if new != current:
            print(f"\n  规则：{rule_str}")
            print(f"  说明：{explanation}")
            print(f"  结果：{current} → {new}")
            current = new

    print(f"\n  最终结果：{word} → {current}  「灵魂（平原语）」")


# ---------------------------------------------------------------------------
# 5. TTS 发音（可选）
# ---------------------------------------------------------------------------
def demo_tts() -> None:
    print_header("5. TTS 语音合成（eSpeak-NG）")

    print("  ⚠ 已知限制：eSpeak-NG 无法正确发音瓦克里克语的核心音素。")
    print("    - 搭嘴音（ǀ ǃ ǁ ǂ）：[[...]] 音素语法无法触发")
    print("    - 挤喉音（pʼ tʼ kʼ）：需切换到特定语言 Voice")
    print("    - 内爆音（ɓ ɗ ɠ）：依赖特定语言字典规则")
    print()
    print("  高阶语 100% 由非肺部气流辅音构成，eSpeak-NG 无法合成。")
    print("  TODO: 计划引入 ToucanTTS 作为可选后端，支持神经合成。")
    print()

    try:
        from conlang.phonology.espeak_ng import find_espeak, to_kirshenbaum
    except ImportError:
        print("  ⚠ 未安装 TTS 依赖。运行：uv sync --extra tts")
        return

    if find_espeak() is None:
        print("  ⚠ 未找到 eSpeak-NG。安装方式：")
        print("    Windows: choco install espeak-ng")
        print("    macOS:   brew install espeak-ng")
        print("    Linux:   sudo apt install espeak-ng")
        return

    # 仅展示 Kirshenbaum 转换（TTS 需要系统音频设备）
    print("  Kirshenbaum 格式（eSpeak-NG 内部表示，仅供参考）：\n")
    for word, gloss in SAMPLE_WORDS[:4]:
        kirs = to_kirshenbaum(word, input_format="asciipa")
        print(f"  {word:16s}  →  {kirs:20s}  「{gloss}」")

    print("\n  发音命令示例（低阶语词汇，肺部气流音可正常发音）：")
    print("    conlang speak \"fu\" --language en")
    print("    conlang speak \"ha\" --language en -o death.wav")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   瓦克里克语（Vha'Klik）综合示例                        ║")
    print("║   \"守气语\" —— 绝息高原·守息教派                        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    demo_tokenize()
    demo_ipa_conversion()
    demo_sca_evolution()
    demo_evolution_detail()
    demo_tts()

    print_header("完成")
    print("  所有功能演示完毕。详细信息请参阅 README.md。\n")


if __name__ == "__main__":
    main()
