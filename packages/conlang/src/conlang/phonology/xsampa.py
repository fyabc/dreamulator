"""ASCIIPA ↔ X-SAMPA conversion for eSpeak-NG TTS integration.

X-SAMPA is the ASCII encoding natively understood by eSpeak-NG.
This module bridges ASCIIPA tokens to X-SAMPA strings, enabling
direct audio synthesis of ASCIIPA-encoded words.
"""

from __future__ import annotations

# Core ASCIIPA → X-SAMPA mapping
ASCIIPA_TO_XSAMPA: dict[str, str] = {
    # Brace macros
    "{sh}": "S",
    "{zh}": "Z",
    "{ch}": "tS",
    "{j}": "dZ",
    "{th}": "T",
    "{dh}": "D",
    "{ng}": "N",
    "{ny}": "J",
    "{kh}": "x",
    "{gh}": "G",
    "{lh}": "K",  # Approximation
    # Turned/escaped
    "\\a": "6",
    "\\e": "@",
    "\\v": "V",
    "\\m": "M\\",
    "\\r": "r\\",
    "\\h": "H",
    "\\w": "W",
    "\\y": "L",
    # Small caps
    "I": "I",
    "U": "U",
    "E": "E",
    "O": "O",
    "A": "A",
    # Implosives
    "<b": "b_<",
    "<d": "d_<",
    "<g": "g_<",
    # Ejectives (using X-SAMPA > modifier)
    "p'": "p_>",
    "t'": "t_>",
    "k'": "k_>",
    # Clicks (eSpeak may need -v zu flag)
    "|": "|\\",
    "!": "!\\",
    # Superscript modifiers
    "^h": "_h",
    "^w": "_w",
    "^j": "_j",
    # Subscript modifiers
    "_o": "_0",
    "_v": "_v",
    # Nasalization
    "~": "~",
    # Length
    ":": ":",
}


def asciipa_to_xsampa(asciipa_str: str) -> str:
    """Convert an ASCIIPA string to X-SAMPA for eSpeak-NG.

    Args:
        asciipa_str: ASCIIPA-encoded string.

    Returns:
        X-SAMPA string wrapped in ``[[ ]]`` for eSpeak.
    """
    from conlang.phonology.asciipa import ASCIIPATokenizer

    tokenizer = ASCIIPATokenizer()
    tokens = tokenizer.tokenize(asciipa_str)
    xsampa_parts: list[str] = []

    for tok in tokens:
        mapped = ASCIIPA_TO_XSAMPA.get(tok.raw)
        if mapped:
            xsampa_parts.append(mapped)
        elif tok.is_structural:
            if tok.raw == ".":
                xsampa_parts.append(" ")  # syllable break → space in X-SAMPA
            elif tok.raw == ":":
                xsampa_parts.append(":")
            else:
                xsampa_parts.append(tok.raw)
        else:
            xsampa_parts.append(tok.raw)

    return "[[" + " ".join(xsampa_parts) + "]]"


def speak(
    asciipa_str: str,
    output_file: str = "output.wav",
    *,
    language: str = "en",
    speed: int = 130,
) -> bool:
    """Synthesize speech from an ASCIIPA string using eSpeak-NG.

    Args:
        asciipa_str: ASCIIPA-encoded string.
        output_file: Path for the output .wav file.
        language: eSpeak language code (use 'zu' for clicks).
        speed: Speech speed (words per minute).

    Returns:
        True if synthesis succeeded, False otherwise.
    """
    import shutil
    import subprocess

    if not shutil.which("espeak-ng"):
        return False

    xsampa = asciipa_to_xsampa(asciipa_str)
    cmd = [
        "espeak-ng",
        "-v", language,
        "-s", str(speed),
        "-w", output_file,
        xsampa,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
