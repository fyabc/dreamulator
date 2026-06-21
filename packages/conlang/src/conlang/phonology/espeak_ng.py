"""IPA Unicode → eSpeak-NG Kirshenbaum format converter.

eSpeak-NG does NOT accept X-SAMPA directly. It uses an internal ASCII
notation based on the Kirshenbaum system. This module converts Unicode
IPA strings to that format, wrapped in ``[[ ]]`` for eSpeak input.

Mapping data extracted from ipapy's ``kirshenbaum.dat``:
    - Source: https://github.com/pettarin/ipapy (MIT License)
    - Author: Alberto Pettarin (Copyright 2016-2019)
    - Only the mapping table was extracted; no ipapy runtime code is used.

.. warning::
    **Non-pulmonic consonant limitations**: eSpeak-NG cannot synthesize
    clicks (ǀ ǃ ǁ ǂ) via the ``[[...]]`` phoneme input — they are
    hardcoded as capital-letter alert sounds. Ejectives (pʼ tʼ kʼ) and
    implosives (ɓ ɗ ɠ) require specific language voices (e.g. Amharic,
    Abkhaz) and cannot be triggered from the general phoneme interface.
    Languages heavily reliant on non-pulmonic consonants (e.g. Vha'Klik)
    cannot be properly synthesized with this backend.

    TODO: Introduce ToucanTTS (IMS-Toucan) as an optional neural TTS
    backend that supports articulatory feature input for non-pulmonic
    consonants. See ``private/tts-toucan-integration.md``.

Usage::

    from conlang.phonology.espeak_ng import ipa_to_kirshenbaum, speak

    # Convert Unicode IPA to eSpeak format
    k = ipa_to_kirshenbaum("həlˈoʊ")
    # → "[[h @ l ' o U]]"

    # Synthesize and play
    speak("həlˈoʊ", play=True)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# IPA Unicode → Kirshenbaum mapping table
# ---------------------------------------------------------------------------
# Extracted from ipapy kirshenbaum.dat (https://github.com/pettarin/ipapy, MIT).
# Format: Unicode character → Kirshenbaum ASCII string.
#
# Notes on Kirshenbaum conventions used by eSpeak-NG:
#   - Angle brackets for features: <h>=aspirated, <vcd>=voiced, <w>=labialized
#   - Dot suffix for retroflex: t.=ʈ, d.=ɖ, n.=ɳ, s.=ʂ, z.=ʐ, l.=ɭ, r.=ɻ
#   - Dot suffix also for flap: *.=ɽ
#   - Backtick for implosive/ejective: b`=ɓ, d`=ɗ, p`=pʼ, t`=tʼ, k`=kʼ
#   - Exclamation for clicks: p!=ʘ, t!=ǀ, c!=ǃ, c!=ǂ, l!=ǁ
#   - Bracket for dental: t[=t̪, d[=d̪, s[=s̪, z[=z̪
#   - Single quote for primary stress: '
#   - Comma for secondary stress: ,
#   - Colon for length: :
#   - Hash for syllable break: #
# ---------------------------------------------------------------------------

IPA_TO_KIRSHENBAUM: dict[str, str] = {
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
    # Plosives: dental
    "t̪": "t[",
    "d̪": "d[",
    # Plosives: retroflex
    "ʈ": "t.",
    "ɖ": "d.",
    # Plosives: palatal
    "c": "c",
    "ɟ": "J",
    # Plosives: uvular
    "ɢ": "G",
    # === Nasals ===
    "m": "m",
    "ɱ": "M",
    "n": "n",
    "ɳ": "n.",
    "ɲ": "n^",
    "ŋ": "N",
    "ɴ": "n\"",
    "n̪": "n[",
    # === Sibilant affricates ===
    "ts": "ts",       # t͡s
    "dz": "dz",       # d͡z
    "tʃ": "tS",       # t͡ʃ
    "dʒ": "dZ",       # d͡ʒ
    # === Sibilant fricatives ===
    "s": "s",
    "z": "z",
    "ʃ": "S",
    "ʒ": "Z",
    "ʂ": "s.",
    "ʐ": "z.",
    "ɕ": "S;",
    "ʑ": "Z;",
    # === Non-sibilant fricatives ===
    "ɸ": "P",
    "β": "B",
    "f": "f",
    "v": "v",
    "θ": "T",
    "ð": "D",
    "ç": "C",
    "ʝ": "C<vcd>",
    "x": "x",
    "ɣ": "Q",
    "χ": "X",
    "ʁ": "g\"",
    "ħ": "H",
    "ʕ": "H<vcd>",
    "h": "h",
    "ɦ": "h<?>",
    # === Approximants ===
    "ʋ": "r<lbd>",
    "ɹ": "r",
    "ɻ": "r.",
    "j": "j",
    "ɰ": "j<vel>",
    "w": "w",
    # === Flaps ===
    "ɾ": "*",
    "ɽ": "*.",
    # === Trills ===
    "ʙ": "b<trl>",
    "r": "r<trl>",
    "ʀ": "r\"",
    # === Lateral approximants ===
    "l": "l",
    "ɭ": "l.",
    "ʎ": "l^",
    "ʟ": "l<vel>",
    # === Lateral fricatives ===
    "ɬ": "s<lat>",
    "ɮ": "z<lat>",
    # === Non-pulmonic: clicks ===
    "ʘ": "p!",
    "ǀ": "t!",
    "ǃ": "c!",
    "ǂ": "c!",
    "ǁ": "l!",
    # === Non-pulmonic: implosives ===
    "ɓ": "b`",
    "ɗ": "d`",
    "ʄ": "J`",
    "ɠ": "g`",
    "ʛ": "G`",
    # === Non-pulmonic: ejectives ===
    "pʼ": "p`",
    "tʼ": "t`",
    "kʼ": "k`",
    "sʼ": "s`",
    "fʼ": "f`",
    "θʼ": "T`",
    # === Vowels: close ===
    "i": "i",
    "y": "y",
    "ɨ": "i\"",
    "ʉ": "u\"",
    "ɯ": "u-",
    "u": "u",
    # === Vowels: near-close ===
    "ɪ": "I",
    "ʏ": "I.",
    "ʊ": "U",
    # === Vowels: close-mid ===
    "e": "e",
    "ø": "Y",
    "ɘ": "@<umd>",
    "ɵ": "@.<umd>",
    "ɤ": "o-",
    "o": "o",
    # === Vowels: mid ===
    "ə": "@",
    # === Vowels: open-mid ===
    "ɛ": "E",
    "œ": "W",
    "ɜ": "V\"",
    "ɞ": "O\"",
    "ʌ": "V",
    "ɔ": "O",
    # === Vowels: near-open ===
    "æ": "&",
    # === Vowels: open ===
    "a": "a",
    "ɶ": "a.",
    "ɑ": "A",
    "ɒ": "A.",
    # === Diacritics (combining characters) ===
    "ʰ": "<h>",       # U+02B0 aspirated
    "ʷ": "<w>",       # U+02B7 labialized
    "ʲ": ";",         # U+02B2 palatalized
    "˞": "<r>",       # U+02DE rhotacized (used as superscript)
    "̥": "<o>",        # U+0325 voiceless (combining)
    "̬": "<vcd>",      # U+032C voiced (combining)
    "̤": "<?>",        # U+0324 breathy-voiced (combining)
    "̪": "[",          # U+032A dental (combining)
    "̃": "~",          # U+0303 nasalized (combining)
    "̩": "-",          # U+0329 syllabic (combining)
    "̽": "<umd>",      # U+033D mid-centralized (combining)
    # === Suprasegmentals ===
    "ˈ": "'",         # U+02C8 primary stress
    "ˌ": ",",         # U+02CC secondary stress
    "ː": ":",         # U+02D0 long
    ".": "#",         # U+002E syllable break
    # === Tone letters (Chao) ===
    "˥": "5",         # U+02E5 extra-high
    "˦": "4",         # U+02E6 high
    "˧": "3",         # U+02E7 mid
    "˨": "2",         # U+02E8 low
    "˩": "1",         # U+02E9 extra-low
    # === Tone diacritics (combining) ===
    "̋": "5",          # U+030B extra-high
    "́": "4",          # U+0301 high
    "̄": "3",          # U+0304 mid
    "̀": "2",          # U+0300 low
    "̏": "1",          # U+030F extra-low
    "̌": "5",          # U+030C rising
    "̂": "4",          # U+0302 falling
}

# Multi-character IPA sequences that should be matched before single chars.
# Sorted by length (longest first) for greedy matching.
_MULTI_CHAR_IPA: list[tuple[str, str]] = sorted(
    [(k, v) for k, v in IPA_TO_KIRSHENBAUM.items() if len(k) > 1],
    key=lambda x: -len(x[0]),
)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def ipa_to_kirshenbaum(ipa_str: str, *, wrap: bool = False) -> str:
    """Convert a Unicode IPA string to Kirshenbaum format.

    Multi-character IPA sequences (e.g. ``tʃ``, ``dʒ``) are matched
    greedily before single characters.

    Stress markers are placed adjacent to the following phoneme (no space).
    Syllable breaks have spaces on both sides.

    Unmapped characters are passed through as-is.

    Args:
        ipa_str: Unicode IPA string (e.g. ``"həlˈoʊ"``).
        wrap: If True, wrap output in ``[[ ]]`` for eSpeak-NG input.

    Returns:
        Kirshenbaum string.
    """
    # Strip common bracket markers
    cleaned = ipa_str.strip().strip("/[]")

    parts: list[str] = []
    i = 0
    while i < len(cleaned):
        matched = False
        # Try multi-character matches first (greedy)
        for ipa_seq, k_seq in _MULTI_CHAR_IPA:
            if cleaned[i : i + len(ipa_seq)] == ipa_seq:
                parts.append(k_seq)
                i += len(ipa_seq)
                matched = True
                break
        if not matched:
            ch = cleaned[i]
            mapped = IPA_TO_KIRSHENBAUM.get(ch)
            if mapped is not None:
                parts.append(mapped)
            elif ch == " ":
                parts.append("#")  # word boundary → syllable break
            else:
                parts.append(ch)
            i += 1

    # Build output: all phonemes, stress markers, and syllable breaks
    # are concatenated without any spaces.
    result = "".join(parts)
    if wrap:
        return "[[" + result + "]]"
    return result


def asciipa_to_kirshenbaum(asciipa_str: str, *, wrap: bool = False) -> str:
    """Convert an ASCIIPA string to Kirshenbaum format.

    Goes through IPA as intermediate: ASCIIPA → IPA → Kirshenbaum.

    Args:
        asciipa_str: ASCIIPA-encoded string.
        wrap: If True, wrap output in ``[[ ]]`` for eSpeak-NG input.

    Returns:
        Kirshenbaum string.
    """
    from conlang.phonology.asciipa import asciipa_to_ipa

    ipa = asciipa_to_ipa(asciipa_str)
    return ipa_to_kirshenbaum(ipa, wrap=wrap)


def to_kirshenbaum(
    text: str, input_format: str = "asciipa", *, wrap: bool = False
) -> str:
    """Convert a phonetic string to Kirshenbaum format.

    Args:
        text: Input phonetic string.
        input_format: One of ``'asciipa'``, ``'ipa'``, ``'kirshenbaum'``.
        wrap: If True, wrap output in ``[[ ]]`` for eSpeak-NG input.

    Returns:
        Kirshenbaum string.

    Raises:
        ValueError: If input_format is not recognized.
    """
    fmt = input_format.lower().strip()
    if fmt == "asciipa":
        return asciipa_to_kirshenbaum(text, wrap=wrap)
    elif fmt == "ipa":
        return ipa_to_kirshenbaum(text, wrap=wrap)
    elif fmt in ("kirshenbaum", "kirs", "espeak"):
        return text
    else:
        raise ValueError(
            f"Unknown input format: {input_format!r}. "
            f"Supported: 'asciipa', 'ipa', 'kirshenbaum'."
        )


# ---------------------------------------------------------------------------
# TTS: eSpeak-NG synthesis
# ---------------------------------------------------------------------------


def find_espeak() -> str | None:
    """Find the eSpeak-NG executable.

    Returns:
        Path to espeak-ng if found, None otherwise.
    """
    path = shutil.which("espeak-ng")
    if path:
        return path
    return shutil.which("espeak")


def synthesize(
    text: str,
    output_file: str | Path,
    *,
    input_format: str = "asciipa",
    language: str = "en",
    speed: int = 130,
    pitch: int = 50,
) -> bool:
    """Synthesize speech to a .wav file using eSpeak-NG.

    Args:
        text: Phonetic string to synthesize.
        output_file: Path for the output .wav file.
        input_format: Input format (``'asciipa'``, ``'ipa'``, ``'kirshenbaum'``).
        language: eSpeak language code (use ``'zu'`` for clicks).
        speed: Speech speed in words per minute.
        pitch: Pitch (0–99, default 50).

    Returns:
        True if synthesis succeeded, False otherwise.
    """
    import logging

    logger = logging.getLogger("conlang.phonology.espeak_ng")

    espeak = find_espeak()
    if espeak is None:
        return False

    kirs = to_kirshenbaum(text, input_format, wrap=True)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        espeak,
        "-v", language,
        "-s", str(speed),
        "-p", str(pitch),
        "-w", str(output_file),
        kirs,
    ]
    logger.debug("eSpeak-NG command: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Playback: cross-platform audio player
# ---------------------------------------------------------------------------


def _play_wav(wav_path: Path) -> bool:
    """Play a .wav file using the system's default audio player."""
    system = platform.system()

    if system == "Darwin":
        return _run_player(["afplay", str(wav_path)])
    elif system == "Windows":
        ps_script = f"(New-Object Media.SoundPlayer '{wav_path}').PlaySync()"
        return _run_player(["powershell", "-c", ps_script])
    else:
        for player in ("aplay", "paplay", "ffplay"):
            if shutil.which(player):
                args = [player, str(wav_path)]
                if player == "ffplay":
                    args = ["ffplay", "-nodisp", "-autoexit", str(wav_path)]
                return _run_player(args)
        return False


def _run_player(cmd: list[str]) -> bool:
    """Run a player command, suppressing output."""
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


def speak(
    text: str,
    *,
    input_format: str = "asciipa",
    output: str | Path | None = None,
    play: bool = False,
    language: str = "en",
    speed: int = 130,
    pitch: int = 50,
) -> Path | None:
    """Synthesize speech and optionally play it.

    Converts input to Kirshenbaum format (eSpeak-NG's native notation),
    runs eSpeak-NG to produce a .wav file, and optionally plays it.

    Args:
        text: Phonetic string (ASCIIPA, IPA, or Kirshenbaum).
        input_format: Input format (``'asciipa'``, ``'ipa'``, ``'kirshenbaum'``).
        output: Output .wav path. If None and ``play=True``, uses a temp file.
        play: If True, play the audio after synthesis.
        language: eSpeak language code.
        speed: Speech speed in words per minute.
        pitch: Pitch (0–99).

    Returns:
        Path to the generated .wav file, or None.

    Raises:
        RuntimeError: If eSpeak-NG is not installed or synthesis fails.
    """
    import logging

    logger = logging.getLogger("conlang.phonology.espeak_ng")

    espeak_path = find_espeak()
    logger.debug("Looking for eSpeak-NG: %s", espeak_path or "NOT FOUND")
    if espeak_path is None:
        raise RuntimeError(
            "eSpeak-NG not found. Install it with:\n"
            "  Windows: choco install espeak-ng  (or download from GitHub)\n"
            "  macOS:   brew install espeak-ng\n"
            "  Linux:   sudo apt install espeak-ng"
        )

    kirs = to_kirshenbaum(text, input_format)
    logger.debug("Input: %s (format=%s)", text, input_format)
    logger.debug("Kirshenbaum: %s", kirs)

    wav_path: Path
    is_temp = False
    if output is not None:
        wav_path = Path(output)
    elif play:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        wav_path = Path(tmp.name)
        is_temp = True
    else:
        return None

    ok = synthesize(
        kirs,
        wav_path,
        input_format="kirshenbaum",
        language=language,
        speed=speed,
        pitch=pitch,
    )
    if not ok:
        if is_temp:
            wav_path.unlink(missing_ok=True)
        raise RuntimeError("eSpeak-NG synthesis failed.")

    if play:
        try:
            _play_wav(wav_path)
        finally:
            if is_temp:
                wav_path.unlink(missing_ok=True)

    return wav_path
