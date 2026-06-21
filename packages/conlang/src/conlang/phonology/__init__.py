"""Phonology module — ASCIIPA encoding, IPA tables, SCA engine, and TTS."""

from conlang.phonology.asciipa import ASCIIPATokenizer
from conlang.phonology.sca import SCAEngine
from conlang.phonology.xsampa import speak

__all__ = ["ASCIIPATokenizer", "SCAEngine", "speak"]
