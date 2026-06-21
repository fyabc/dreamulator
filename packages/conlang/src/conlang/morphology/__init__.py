"""Morphology module — FST engine, affix rules, and vowel harmony."""

from conlang.morphology.fst import FSTEngine, MorphologicalRule
from conlang.morphology.harmony import ConsonantMutation, VowelHarmony

__all__ = ["FSTEngine", "MorphologicalRule", "VowelHarmony", "ConsonantMutation"]
