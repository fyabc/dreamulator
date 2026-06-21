"""IPA character information — Unicode names and validation.

Provides human-readable descriptions for IPA characters, used by the
``conlang convert --chars`` command. Data is derived from the standard
IPA chart and Unicode character names.
"""

from __future__ import annotations


# IPA character descriptions: Unicode codepoint → (display_char, description)
# Covers the most common IPA symbols used in conlang work.
_IPA_CHAR_INFO: dict[int, tuple[str, str]] = {
    # === Pulmonic consonants: plosives ===
    0x0070: ("p", "voiceless bilabial plosive"),
    0x0062: ("b", "voiced bilabial plosive"),
    0x0074: ("t", "voiceless alveolar plosive"),
    0x0064: ("d", "voiced alveolar plosive"),
    0x006B: ("k", "voiceless velar plosive"),
    0x0261: ("ɡ", "voiced velar plosive"),
    0x0071: ("q", "voiceless uvular plosive"),
    0x0262: ("ɢ", "voiced uvular plosive"),
    0x0294: ("ʔ", "voiceless glottal plosive"),
    0x0063: ("c", "voiceless palatal plosive"),
    0x025F: ("ɟ", "voiced palatal plosive"),
    0x0288: ("ʈ", "voiceless retroflex plosive"),
    0x0256: ("ɖ", "voiced retroflex plosive"),
    # === Nasals ===
    0x006D: ("m", "voiced bilabial nasal"),
    0x0271: ("ɱ", "voiced labiodental nasal"),
    0x006E: ("n", "voiced alveolar nasal"),
    0x0273: ("ɳ", "voiced retroflex nasal"),
    0x0272: ("ɲ", "voiced palatal nasal"),
    0x014B: ("ŋ", "voiced velar nasal"),
    0x0274: ("ɴ", "voiced uvular nasal"),
    # === Trills ===
    0x0299: ("ʙ", "voiced bilabial trill"),
    0x0072: ("r", "voiced alveolar trill"),
    0x0280: ("ʀ", "voiced uvular trill"),
    # === Taps/flaps ===
    0x027E: ("ɾ", "voiced alveolar tap"),
    0x027D: ("ɽ", "voiced retroflex flap"),
    # === Fricatives ===
    0x0278: ("ɸ", "voiceless bilabial fricative"),
    0x03B2: ("β", "voiced bilabial fricative"),
    0x0066: ("f", "voiceless labiodental fricative"),
    0x0076: ("v", "voiced labiodental fricative"),
    0x03B8: ("θ", "voiceless dental fricative"),
    0x00F0: ("ð", "voiced dental fricative"),
    0x0073: ("s", "voiceless alveolar fricative"),
    0x007A: ("z", "voiced alveolar fricative"),
    0x0283: ("ʃ", "voiceless postalveolar fricative"),
    0x0292: ("ʒ", "voiced postalveolar fricative"),
    0x0282: ("ʂ", "voiceless retroflex fricative"),
    0x0290: ("ʐ", "voiced retroflex fricative"),
    0x00E7: ("ç", "voiceless palatal fricative"),
    0x029D: ("ʝ", "voiced palatal fricative"),
    0x0078: ("x", "voiceless velar fricative"),
    0x0263: ("ɣ", "voiced velar fricative"),
    0x03C7: ("χ", "voiceless uvular fricative"),
    0x0281: ("ʁ", "voiced uvular fricative"),
    0x0127: ("ħ", "voiceless pharyngeal fricative"),
    0x0295: ("ʕ", "voiced pharyngeal fricative"),
    0x0068: ("h", "voiceless glottal fricative"),
    0x0266: ("ɦ", "voiced glottal fricative"),
    # === Lateral fricatives ===
    0x026C: ("ɬ", "voiceless alveolar lateral fricative"),
    0x026E: ("ɮ", "voiced alveolar lateral fricative"),
    # === Approximants ===
    0x028B: ("ʋ", "voiced labiodental approximant"),
    0x0279: ("ɹ", "voiced alveolar approximant"),
    0x027B: ("ɻ", "voiced retroflex approximant"),
    0x006A: ("j", "voiced palatal approximant"),
    0x0270: ("ɰ", "voiced velar approximant"),
    0x0077: ("w", "voiced labial-velar approximant"),
    # === Lateral approximants ===
    0x006C: ("l", "voiced alveolar lateral approximant"),
    0x026D: ("ɭ", "voiced retroflex lateral approximant"),
    0x028E: ("ʎ", "voiced palatal lateral approximant"),
    0x029F: ("ʟ", "voiced velar lateral approximant"),
    # === Non-pulmonic: clicks ===
    0x0298: ("ʘ", "bilabial click"),
    0x01C0: ("ǀ", "dental click"),
    0x01C3: ("ǃ", "alveolar click"),
    0x01C2: ("ǂ", "palatal click"),
    0x01C1: ("ǁ", "lateral click"),
    # === Non-pulmonic: implosives ===
    0x0253: ("ɓ", "voiced bilabial implosive"),
    0x0257: ("ɗ", "voiced alveolar implosive"),
    0x0284: ("ʄ", "voiced palatal implosive"),
    0x0260: ("ɠ", "voiced velar implosive"),
    0x029B: ("ʛ", "voiced uvular implosive"),
    # === Vowels: close ===
    0x0069: ("i", "close front unrounded vowel"),
    0x0079: ("y", "close front rounded vowel"),
    0x0268: ("ɨ", "close central unrounded vowel"),
    0x0289: ("ʉ", "close central rounded vowel"),
    0x026F: ("ɯ", "close back unrounded vowel"),
    0x0075: ("u", "close back rounded vowel"),
    # === Vowels: near-close ===
    0x026A: ("ɪ", "near-close near-front unrounded vowel"),
    0x028F: ("ʏ", "near-close near-front rounded vowel"),
    0x028A: ("ʊ", "near-close near-back rounded vowel"),
    # === Vowels: close-mid ===
    0x0065: ("e", "close-mid front unrounded vowel"),
    0x00F8: ("ø", "close-mid front rounded vowel"),
    0x0258: ("ɘ", "close-mid central unrounded vowel"),
    0x0275: ("ɵ", "close-mid central rounded vowel"),
    0x0264: ("ɤ", "close-mid back unrounded vowel"),
    0x006F: ("o", "close-mid back rounded vowel"),
    # === Vowels: mid ===
    0x0259: ("ə", "mid central unrounded vowel (schwa)"),
    # === Vowels: open-mid ===
    0x025B: ("ɛ", "open-mid front unrounded vowel"),
    0x0153: ("œ", "open-mid front rounded vowel"),
    0x025C: ("ɜ", "open-mid central unrounded vowel"),
    0x025E: ("ɞ", "open-mid central rounded vowel"),
    0x028C: ("ʌ", "open-mid back unrounded vowel"),
    0x0254: ("ɔ", "open-mid back rounded vowel"),
    # === Vowels: near-open ===
    0x00E6: ("æ", "near-open front unrounded vowel"),
    0x0250: ("ɐ", "near-open central unrounded vowel"),
    # === Vowels: open ===
    0x0061: ("a", "open front unrounded vowel"),
    0x0276: ("ɶ", "open front rounded vowel"),
    0x0251: ("ɑ", "open back unrounded vowel"),
    0x0252: ("ɒ", "open back rounded vowel"),
    # === Suprasegmentals ===
    0x02C8: ("ˈ", "primary stress"),
    0x02CC: ("ˌ", "secondary stress"),
    0x02D0: ("ː", "long"),
    0x02D1: ("ˑ", "half-long"),
    0x002E: (".", "syllable break"),
    # === Tone letters ===
    0x02E5: ("˥", "extra-high level tone"),
    0x02E6: ("˦", "high level tone"),
    0x02E7: ("˧", "mid level tone"),
    0x02E8: ("˨", "low level tone"),
    0x02E9: ("˩", "extra-low level tone"),
    # === Diacritics (superscript) ===
    0x02B0: ("ʰ", "aspirated"),
    0x02B7: ("ʷ", "labialized"),
    0x02B2: ("ʲ", "palatalized"),
    0x02DE: ("˞", "rhotacized"),
    # === Common ASCII characters used in IPA ===
    0x0067: ("g", "voiced velar plosive (ASCII variant)"),
}


def describe_char(ch: str) -> tuple[str, str] | None:
    """Get the IPA description for a character.

    Args:
        ch: A single Unicode character.

    Returns:
        Tuple of (display_char, description) if the character is a known
        IPA symbol, None otherwise.
    """
    return _IPA_CHAR_INFO.get(ord(ch))


def describe_string(text: str) -> list[tuple[str, str, str, str | None]]:
    """Describe each character in a string.

    Args:
        text: Unicode string to describe.

    Returns:
        List of (char, hex_code, description_or_None, unicode_name) tuples.
    """
    import unicodedata

    results: list[tuple[str, str, str, str | None]] = []
    for ch in text:
        cp = ord(ch)
        hex_code = f"U+{cp:04X}"
        info = _IPA_CHAR_INFO.get(cp)
        desc = info[1] if info else None
        try:
            uni_name = unicodedata.name(ch)
        except ValueError:
            uni_name = None
        results.append((ch, hex_code, desc or uni_name or "UNKNOWN", uni_name))
    return results


def validate_ipa(text: str) -> tuple[bool, list[str]]:
    """Check if all characters in a string are recognized IPA symbols.

    Args:
        text: Unicode string to validate.

    Returns:
        Tuple of (is_valid, list_of_invalid_characters).
    """
    invalid: list[str] = []
    for ch in text:
        if ch == " " or ch in "/[]":
            continue  # brackets and spaces are structural, not phonemic
        cp = ord(ch)
        if cp not in _IPA_CHAR_INFO:
            # Also accept basic Latin letters that double as IPA
            if ch.isascii() and ch.isalpha():
                continue
            invalid.append(ch)
    return (len(invalid) == 0, invalid)
