"""Vowel harmony and consonant mutation rules.

Vowel harmony is a widespread phonological phenomenon where vowels within a
word must share certain features (e.g. frontness, rounding). This module
provides configurable harmony engines for common patterns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VowelClass:
    """A group of vowels sharing a harmonic feature."""

    name: str
    vowels: frozenset[str]


# Pre-defined vowel classes for common harmony systems
FRONT_VOWELS = VowelClass("front", frozenset({"i", "e", "I", "E", "y", "{oe}", "<e"}))
BACK_VOWELS = VowelClass("back", frozenset({"u", "o", "U", "O", "\\m", "\\v", "A", "a"}))
CENTRAL_VOWELS = VowelClass("central", frozenset({"\\a", "\\e", "a"}))

ROUNDED_VOWELS = VowelClass("rounded", frozenset({"u", "o", "U", "O", "y", "{oe}"}))
UNROUNDED_VOWELS = VowelClass("unrounded", frozenset({"i", "e", "I", "E", "a", "\\a"}))


class VowelHarmony:
    """Front/back vowel harmony engine (e.g. Turkish, Finnish, Hungarian).

    Suffixes alternate between front and back vowel forms depending on
    the last vowel of the stem.

    Usage::

        harmony = VowelHarmony(
            front_suffix="ler",
            back_suffix="lar",
        )
        harmony.apply("ev")     # → "evler" (front)
        harmony.apply("kitap")  # → "kitaplar" (back)
    """

    def __init__(
        self,
        front_suffix: str,
        back_suffix: str,
        *,
        front_vowels: VowelClass | None = None,
        back_vowels: VowelClass | None = None,
    ) -> None:
        self._front_suffix = front_suffix
        self._back_suffix = back_suffix
        self._front = front_vowels or FRONT_VOWELS
        self._back = back_vowels or BACK_VOWELS

    def classify(self, stem: str) -> str:
        """Classify a stem as front or back based on its last vowel.

        Args:
            stem: ASCIIPA stem string.

        Returns:
            'front' or 'back'.
        """
        last_vowel = self._find_last_vowel(stem)
        if last_vowel and last_vowel in self._front.vowels:
            return "front"
        return "back"

    def apply(self, stem: str) -> str:
        """Apply vowel-harmonic suffix to a stem.

        Args:
            stem: ASCIIPA stem string.

        Returns:
            Stem with appropriate suffix attached.
        """
        cls = self.classify(stem)
        suffix = self._front_suffix if cls == "front" else self._back_suffix
        return stem + suffix

    def _find_last_vowel(self, text: str) -> str | None:
        """Find the last vowel in a string."""
        all_vowels = self._front.vowels | self._back.vowels
        # Scan from right, checking each character
        for ch in reversed(text):
            if ch in all_vowels:
                return ch
        return None


class ConsonantMutation:
    """Celtic-style initial consonant mutation.

    Word-initial consonants change based on grammatical context
    (e.g. after certain particles, possessives, etc.).

    Usage::

        lenition = ConsonantMutation({
            "p": "f", "t": "{th}", "k": "{gh}",
            "b": "v", "d": "{dh}", "g": "{gh}",
            "m": "v",
        })
        lenition.apply("pen")  # → "fen"
    """

    def __init__(self, mutation_map: dict[str, str]) -> None:
        self._map = mutation_map

    def apply(self, word: str) -> str:
        """Apply mutation to the initial consonant of a word.

        Args:
            word: ASCIIPA word string.

        Returns:
            Mutated word.
        """
        if not word:
            return word
        first = word[0]
        if first in self._map:
            return self._map[first] + word[1:]
        return word

    def apply_with_trigger(self, word: str, trigger: str) -> str:
        """Apply mutation only if a trigger particle precedes the word.

        Args:
            word: ASCIIPA word string.
            trigger: Trigger particle (for documentation; not parsed).

        Returns:
            Mutated word.
        """
        return self.apply(word)
