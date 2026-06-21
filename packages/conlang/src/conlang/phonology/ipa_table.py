"""IPA ↔ ASCIIPA mapping tables.

Complete bidirectional mapping between Unicode IPA symbols and ASCIIPA
ASCII representations. Covers pulmonic consonants, non-pulmonic consonants
(clicks, implosives, ejectives), vowels, diacritics, and suprasegmentals.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# IPA → ASCIIPA  (Unicode symbol → ASCII representation)
# ---------------------------------------------------------------------------
IPA_TO_ASCIIPA_MAP: dict[str, str] = {
    # === Pulmonic Consonants ===
    # Plosives
    "p": "p",
    "b": "b",
    "t": "t",
    "d": "d",
    "k": "k",
    "ɡ": "g",  # IPA uses ɡ (U+0261), not g
    "g": "g",  # Also accept ASCII g
    "q": "q",
    "ʔ": "{'}",
    # Nasals
    "m": "m",
    "n": "n",
    "ɲ": "{ny}",
    "ŋ": "{ng}",
    "ɴ": "N",
    # Trills
    "r": "r",
    "ʀ": "R",
    "ʙ": "B",
    # Taps/Flaps
    "ɾ": "{r}",
    "ɽ": "r>",
    # Fricatives
    "ɸ": "{ph}",
    "β": "{B}",
    "f": "f",
    "v": "v",
    "θ": "{th}",
    "ð": "{dh}",
    "s": "s",
    "z": "z",
    "ʃ": "{sh}",
    "ʒ": "{zh}",
    "ʂ": "s>",
    "ʐ": "z>",
    "ç": "{hy}",
    "x": "x",
    "ɣ": "{gh}",
    "χ": "{X}",
    "ʁ": "{R}",
    "ħ": "h=",
    "ʕ": "{'>}",
    "h": "h",
    "ɦ": "h.v",
    # Lateral fricatives
    "ɬ": "{lh}",
    "ɮ": "{lzh}",
    # Approximants
    "ʋ": "{v}",
    "ɹ": "\\r",
    "ɻ": "\\r>",
    "j": "j",
    "ɰ": "{M}",
    "w": "w",
    # Lateral approximants
    "l": "l",
    "ɭ": "l>",
    "ʎ": "\\y",
    "ʟ": "L",
    # Small caps / turned
    "ɐ": "\\a",
    "ə": "\\e",
    "ʌ": "\\v",
    "ɯ": "\\m",
    "ɥ": "\\h",
    "ʍ": "\\w",
    # Retroflex
    "ʈ": "t>",
    "ɖ": "d>",
    "ɳ": "n>",
    # Implosives
    "ɓ": "<b",
    "ɗ": "<d",
    "ʄ": "<j",
    "ɠ": "<g",
    "ʛ": "<G",
    # Clicks
    "ǀ": "|",
    "ǃ": "!",
    "ǁ": "||",
    "ǂ": "=",
    "ʘ": "{click}",
    # === Vowels ===
    # Close
    "i": "i",
    "y": "y",
    "ɨ": "i=",
    "ʉ": "u=",
    "ɯ": "\\m",
    "u": "u",
    # Near-close
    "ɪ": "I",
    "ʏ": "Y",
    "ʊ": "U",
    # Close-mid
    "e": "e",
    "ø": "{oe}",
    "ɘ": "<e",
    "ɵ": "o=",
    "ɤ": "{uh}",
    "o": "o",
    # Mid
    "ɛ": "E",
    "œ": "{OE}",
    "ɜ": "3",
    "ɞ": "{3r}",
    "ʌ": "\\v",
    "ɔ": "O",
    # Near-open
    "æ": "{&}",
    "ɐ": "\\a",
    # Open
    "a": "a",
    "ɶ": "{&oe}",
    "ɑ": "A",
    "ɒ": "<A",
    # === Diacritics (suprasegmentals) ===
    "ʰ": "^h",
    "ʷ": "^w",
    "ʲ": "^j",
    "˞": "^r",
    "̥": "_o",
    "̬": "_v",
    "̪": "_T",
    "̤": "_h",
    "̰": "_c",
    "̟": "_a",
    "̠": "_r",
    "̝": "_u",
    "̞": "_d",
    "̚": "_n",
    "̃": "~",
    "ː": ":",
    "ˈ": "!",
    "ˌ": ",",
    ".": ".",
}

# ---------------------------------------------------------------------------
# ASCIIPA → IPA  (reverse mapping, built automatically + manual overrides)
# ---------------------------------------------------------------------------
ASCIIPA_TO_IPA_MAP: dict[str, str] = {}

# Auto-generate reverse mapping
for _ipa, _asciipa in IPA_TO_ASCIIPA_MAP.items():
    if _asciipa not in ASCIIPA_TO_IPA_MAP:
        ASCIIPA_TO_IPA_MAP[_asciipa] = _ipa

# Manual overrides for ambiguous reverse mappings
ASCIIPA_TO_IPA_MAP.update(
    {
        # Brace macros
        "{sh}": "ʃ",
        "{zh}": "ʒ",
        "{ch}": "tʃ",
        "{j}": "dʒ",
        "{th}": "θ",
        "{dh}": "ð",
        "{ng}": "ŋ",
        "{ny}": "ɲ",
        "{kh}": "x",
        "{gh}": "ɣ",
        "{'}": "ʔ",
        "{r}": "ɾ",
        "{lh}": "ɬ",
        "{lzh}": "ɮ",
        "{ph}": "ɸ",
        "{B}": "β",
        "{X}": "χ",
        "{R}": "ʁ",
        "{'>}": "ʕ",
        "{M}": "ɰ",
        "{v}": "ʋ",
        "{click}": "ʘ",
        "{&}": "æ",
        "{oe}": "ø",
        "{OE}": "œ",
        "{uh}": "ɤ",
        # Escaped/turned
        "\\a": "ɐ",
        "\\e": "ə",
        "\\v": "ʌ",
        "\\m": "ɯ",
        "\\r": "ɹ",
        "\\h": "ɥ",
        "\\w": "ʍ",
        "\\y": "ʎ",
        # Mirrored
        "<e": "ɘ",
        "<A": "ɒ",
        # Small caps
        "I": "ɪ",
        "U": "ʊ",
        "E": "ɛ",
        "O": "ɔ",
        "A": "ɑ",
        "B": "ʙ",
        "G": "ɢ",
        "N": "ɴ",
        "R": "ʀ",
        "L": "ʟ",
        "Y": "ʏ",
        # Retroflex
        "t>": "ʈ",
        "d>": "ɖ",
        "n>": "ɳ",
        "s>": "ʂ",
        "z>": "ʐ",
        "r>": "ɽ",
        "l>": "ɭ",
        # Barred
        "i=": "ɨ",
        "u=": "ʉ",
        "o=": "ɵ",
        "h=": "ħ",
        # Implosives
        "<b": "ɓ",
        "<d": "ɗ",
        "<j": "ʄ",
        "<g": "ɠ",
        "<G": "ʛ",
        # Clicks
        "|": "ǀ",
        "!": "ǃ",
        "||": "ǁ",
        "=": "ǂ",
        # Structural
        ".": ".",
        ":": "ː",
    }
)


# ---------------------------------------------------------------------------
# Feature categories for SCA engine
# ---------------------------------------------------------------------------

PULMONIC_STOPS = ["p", "b", "t", "d", "k", "g", "q"]
NASALS = ["m", "n", "{ny}", "{ng}", "N"]
FRICATIVES = [
    "f",
    "v",
    "{th}",
    "{dh}",
    "s",
    "z",
    "{sh}",
    "{zh}",
    "x",
    "{gh}",
    "h",
    "{lh}",
]
APPROXIMANTS = ["\\r", "j", "w", "l"]
VOWELS = [
    "i",
    "y",
    "I",
    "U",
    "e",
    "{oe}",
    "E",
    "a",
    "{&}",
    "\\a",
    "\\v",
    "o",
    "O",
    "u",
    "\\m",
    "\\e",
    "A",
]

# Default category map for SCA
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "C_stops": PULMONIC_STOPS,
    "C_nasals": NASALS,
    "C_fricatives": FRICATIVES,
    "C_approximants": APPROXIMANTS,
    "V": VOWELS,
}
