"""Phonology module — ASCIIPA encoding, IPA tables, SCA engine, and TTS."""

from conlang.phonology.asciipa import ASCIIPATokenizer
from conlang.phonology.espeak_ng import speak
from conlang.phonology.sca import SCAEngine

__all__ = ["ASCIIPATokenizer", "SCAEngine", "speak"]
