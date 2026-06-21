"""Unicode IPA ↔ X-SAMPA conversion.

X-SAMPA is a standardized ASCII encoding of IPA symbols.
All conversions in this module use **Unicode IPA as the universal
intermediate format**.  Other notations (ASCIIPA, Kirshenbaum, etc.)
convert to/from IPA first.

.. note::
    For TTS with eSpeak-NG, use :mod:`conlang.phonology.espeak_ng` instead.
    eSpeak-NG uses the Kirshenbaum system internally, NOT X-SAMPA.

Usage::

    from conlang.phonology.xsampa import ipa_to_xsampa, to_xsampa

    ipa_to_xsampa("θɪŋk")          # → "[[TINk]]"
    to_xsampa("{th}I{ng}k", "asciipa")  # → "[[TINk]]"  (via IPA)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Unicode IPA → X-SAMPA mapping table
# ---------------------------------------------------------------------------
IPA_TO_XSAMPA: dict[str, str] = {
    # === Pulmonic consonants: plosives ===
    "p": "p",
    "b": "b",
    "t": "t",
    "d": "d",
    "k": "k",
    "ɡ": "g",  # U+0261 (IPA g)
    "g": "g",  # ASCII g also accepted
    "q": "q",
    "ʔ": "?",
    # === Nasals ===
    "m": "m",
    "ɱ": "F",
    "n": "n",
    "ɳ": "n`",
    "ɲ": "J",
    "ŋ": "N",
    "ɴ": "N\\",
    # === Trills ===
    "ʙ": "B\\",
    "r": "r",
    "ʀ": "R\\",
    # === Taps/flaps ===
    "ɾ": "4",
    "ɽ": "r`",
    # === Fricatives ===
    "ɸ": "p\\",
    "β": "B",
    "f": "f",
    "v": "v",
    "θ": "T",
    "ð": "D",
    "s": "s",
    "z": "z",
    "ʃ": "S",
    "ʒ": "Z",
    "ʂ": "s`",
    "ʐ": "z`",
    "ç": "C",
    "ʝ": "j\\",
    "x": "x",
    "ɣ": "G",
    "χ": "X",
    "ʁ": "R",
    "ħ": "X\\",
    "ʕ": "?\\",
    "h": "h",
    "ɦ": "h\\",
    # === Lateral fricatives ===
    "ɬ": "K",
    "ɮ": "K\\",
    # === Approximants ===
    "ʋ": "P",
    "ɹ": "r\\",
    "ɻ": "r\\`",
    "j": "j",
    "ɰ": "M\\",
    "w": "w",
    # === Lateral approximants ===
    "l": "l",
    "ɭ": "l`",
    "ʎ": "L",
    "ʟ": "L\\",
    # === Non-pulmonic: clicks ===
    "ʘ": "O\\",
    "ǀ": "|\\",
    "ǃ": "!\\",
    "ǂ": "=\\",
    "ǁ": "||\\",
    # === Non-pulmonic: implosives ===
    "ɓ": "b_<",
    "ɗ": "d_<",
    "ʄ": "J\\_<",
    "ɠ": "g_<",
    "ʛ": "G\\_<",
    # === Vowels: close ===
    "i": "i",
    "y": "y",
    "ɨ": "1",
    "ʉ": "} ",
    "ɯ": "M",
    "u": "u",
    # === Vowels: near-close ===
    "ɪ": "I",
    "ʏ": "Y",
    "ʊ": "U",
    # === Vowels: close-mid ===
    "e": "e",
    "ø": "2",
    "ɘ": "@\\",
    "ɵ": "8",
    "ɤ": "7",
    "o": "o",
    # === Vowels: mid ===
    "ə": "@",
    # === Vowels: open-mid ===
    "ɛ": "E",
    "œ": "9",
    "ɜ": "3",
    "ɞ": "3\\",
    "ʌ": "V",
    "ɔ": "O",
    # === Vowels: near-open ===
    "æ": "{",
    "ɐ": "6",
    # === Vowels: open ===
    "a": "a",
    "ɶ": "&",
    "ɑ": "A",
    "ɒ": "Q",
    # === Diacritics (superscript / combining) ===
    "ʰ": "_h",
    "ʷ": "_w",
    "ʲ": "_j",
    "˞": "`",
    "̥": "_0",       # U+0325 voiceless
    "̬": "_v",       # U+032C voiced
    "̤": "_t",       # U+0324 breathy
    "̪": "_d",       # U+032A dental
    "̃": "~",        # U+0303 nasalized
    "̩": "=",        # U+0329 syllabic
    # === Suprasegmentals ===
    "ˈ": '"',       # U+02C8 primary stress
    "ˌ": "%",       # U+02CC secondary stress
    "ː": ":",       # U+02D0 long
    ".": ".",       # syllable break
    # === Tone letters ===
    "˥": "_T",
    "˦": "_H",
    "˧": "_M",
    "˨": "_L",
    "˩": "_B",
}

# Multi-character IPA sequences matched before single chars (longest first).
_MULTI_CHAR_IPA: list[tuple[str, str]] = sorted(
    [(k, v) for k, v in IPA_TO_XSAMPA.items() if len(k) > 1],
    key=lambda x: -len(x[0]),
)


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------


def ipa_to_xsampa(ipa_str: str) -> str:
    """Convert a Unicode IPA string to X-SAMPA.

    Args:
        ipa_str: Unicode IPA string (e.g. ``"θɪŋk"``).

    Returns:
        X-SAMPA string wrapped in ``[[ ]]``.
    """
    cleaned = ipa_str.strip().strip("/[]")

    parts: list[str] = []
    i = 0
    while i < len(cleaned):
        matched = False
        for ipa_seq, x_seq in _MULTI_CHAR_IPA:
            if cleaned[i : i + len(ipa_seq)] == ipa_seq:
                parts.append(x_seq)
                i += len(ipa_seq)
                matched = True
                break
        if not matched:
            ch = cleaned[i]
            mapped = IPA_TO_XSAMPA.get(ch)
            if mapped is not None:
                parts.append(mapped)
            elif ch == " ":
                parts.append(" ")
            else:
                parts.append(ch)
            i += 1

    return "[[" + " ".join(parts) + "]]"


def to_xsampa(text: str, input_format: str = "asciipa") -> str:
    """Convert a phonetic string to X-SAMPA via Unicode IPA.

    All input formats are first converted to Unicode IPA, then to X-SAMPA.

    Args:
        text: Input phonetic string.
        input_format: One of ``'asciipa'``, ``'ipa'``, ``'xsampa'``.

    Returns:
        X-SAMPA string wrapped in ``[[ ]]``.

    Raises:
        ValueError: If input_format is not recognized.
    """
    fmt = input_format.lower().strip()
    if fmt == "asciipa":
        from conlang.phonology.asciipa import asciipa_to_ipa

        ipa = asciipa_to_ipa(text)
        return ipa_to_xsampa(ipa)
    elif fmt == "ipa":
        return ipa_to_xsampa(text)
    elif fmt in ("xsampa", "x-sampa"):
        if text.startswith("[[") and text.endswith("]]"):
            return text
        return f"[[{text}]]"
    else:
        raise ValueError(
            f"Unknown input format: {input_format!r}. "
            f"Supported: 'asciipa', 'ipa', 'xsampa'."
        )
