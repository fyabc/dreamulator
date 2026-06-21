"""ASCIIPA ↔ X-SAMPA conversion (legacy module).

.. note::
    For TTS with eSpeak-NG, use :mod:`conlang.phonology.espeak_ng` instead.
    eSpeak-NG uses the Kirshenbaum system internally, NOT X-SAMPA.
    This module is kept for backward compatibility and for tools that
    specifically require X-SAMPA format.

X-SAMPA is a standardized ASCII encoding of IPA symbols.
This module bridges ASCIIPA tokens to X-SAMPA strings.

Usage::

    from conlang.phonology.xsampa import speak, asciipa_to_xsampa

    # Generate a .wav file
    speak("p^h a . t a", output="hello.wav")

    # Play directly (cross-platform)
    speak("p^h a . t a", play=True)

    # Use a different input format
    speak("θɪŋk", input_format="ipa", play=True)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# ASCIIPA → X-SAMPA mapping table
# ---------------------------------------------------------------------------
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
    # Ejectives
    "p'": "p_>",
    "t'": "t_>",
    "k'": "k_>",
    # Clicks (eSpeak may need -v zu flag)
    "|": "|\\",
    "!": "!\\",
    "||": "ǁ",  # No standard X-SAMPA; pass through
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


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------


def asciipa_to_xsampa(asciipa_str: str) -> str:
    """Convert an ASCIIPA string to X-SAMPA for eSpeak-NG.

    Handles multi-character tokens by converting the base first, then
    appending each modifier's X-SAMPA equivalent.

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
        if tok.is_structural:
            if tok.raw == ".":
                xsampa_parts.append(" ")  # syllable break → space
            elif tok.raw == ":":
                xsampa_parts.append(":")
            else:
                xsampa_parts.append(tok.raw)
            continue

        # Try whole-token match first (e.g. "{sh}" → "S", "p'" → "p_>")
        whole = ASCIIPA_TO_XSAMPA.get(tok.raw)
        if whole is not None:
            xsampa_parts.append(whole)
            continue

        # Decompose: convert base, then each modifier
        base_xsampa = ASCIIPA_TO_XSAMPA.get(tok.base, tok.base)
        parts = [base_xsampa]
        for mod in tok.modifiers:
            mod_xsampa = ASCIIPA_TO_XSAMPA.get(mod, "")
            if mod_xsampa:
                parts.append(mod_xsampa)
        xsampa_parts.append("".join(parts))

    return "[[" + " ".join(xsampa_parts) + "]]"


def ipa_to_xsampa(ipa_str: str) -> str:
    """Convert a Unicode IPA string to X-SAMPA via ASCIIPA intermediate.

    Args:
        ipa_str: IPA string (Unicode).

    Returns:
        X-SAMPA string wrapped in ``[[ ]]``.
    """
    from conlang.phonology.asciipa import ipa_to_asciipa

    asciipa = ipa_to_asciipa(ipa_str)
    return asciipa_to_xsampa(asciipa)


def to_xsampa(text: str, input_format: str = "asciipa") -> str:
    """Convert a phonetic string to X-SAMPA.

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
        return asciipa_to_xsampa(text)
    elif fmt == "ipa":
        return ipa_to_xsampa(text)
    elif fmt in ("xsampa", "x-sampa"):
        # Already X-SAMPA; just wrap if not already wrapped
        if text.startswith("[[") and text.endswith("]]"):
            return text
        return f"[[{text}]]"
    else:
        raise ValueError(
            f"Unknown input format: {input_format!r}. "
            f"Supported: 'asciipa', 'ipa', 'xsampa'."
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
    # Fallback: try "espeak" (older version)
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
        input_format: Input format (``'asciipa'``, ``'ipa'``, ``'xsampa'``).
        language: eSpeak language code (use ``'zu'`` for clicks).
        speed: Speech speed in words per minute.
        pitch: Pitch (0–99, default 50).

    Returns:
        True if synthesis succeeded, False otherwise.
    """
    espeak = find_espeak()
    if espeak is None:
        return False

    xsampa = to_xsampa(text, input_format)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        espeak,
        "-v", language,
        "-s", str(speed),
        "-p", str(pitch),
        "-w", str(output_file),
        xsampa,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Playback: cross-platform audio player
# ---------------------------------------------------------------------------


def _play_wav(wav_path: Path) -> bool:
    """Play a .wav file using the system's default audio player.

    Args:
        wav_path: Path to the .wav file.

    Returns:
        True if playback was initiated, False if no player found.
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        return _run_player(["afplay", str(wav_path)])
    elif system == "Windows":
        # Use PowerShell's SoundPlayer for reliable playback
        ps_script = (
            f"(New-Object Media.SoundPlayer '{wav_path}').PlaySync()"
        )
        return _run_player(["powershell", "-c", ps_script])
    else:  # Linux / other Unix
        # Try aplay (ALSA), then paplay (PulseAudio), then ffplay
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

    This is the main entry point for TTS. It converts the input to X-SAMPA,
    runs eSpeak-NG to produce a .wav file, and optionally plays it.

    Args:
        text: Phonetic string (ASCIIPA, IPA, or X-SAMPA).
        input_format: Input format (``'asciipa'``, ``'ipa'``, ``'xsampa'``).
        output: Output .wav path. If None and ``play=True``, uses a temp file.
            If None and ``play=False``, no synthesis is performed.
        play: If True, play the audio after synthesis.
        language: eSpeak language code.
        speed: Speech speed in words per minute.
        pitch: Pitch (0–99).

    Returns:
        Path to the generated .wav file, or None if nothing was generated.

    Raises:
        RuntimeError: If eSpeak-NG is not installed.
    """
    if find_espeak() is None:
        raise RuntimeError(
            "eSpeak-NG not found. Install it with:\n"
            "  Windows: choco install espeak-ng  (or download from GitHub)\n"
            "  macOS:   brew install espeak-ng\n"
            "  Linux:   sudo apt install espeak-ng"
        )

    # Determine output path
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

    # Synthesize
    ok = synthesize(
        text,
        wav_path,
        input_format=input_format,
        language=language,
        speed=speed,
        pitch=pitch,
    )
    if not ok:
        if is_temp:
            wav_path.unlink(missing_ok=True)
        raise RuntimeError("eSpeak-NG synthesis failed.")

    # Play
    if play:
        try:
            _play_wav(wav_path)
        finally:
            if is_temp:
                wav_path.unlink(missing_ok=True)
            # If output was specified, keep the file

    return wav_path
