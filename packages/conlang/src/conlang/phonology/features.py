"""Phoneme feature matrices for feature-based sound change rules.

Each phoneme is described by a set of binary/multivalued distinctive features
(e.g. [+voice], [-nasal], [place:velar]). This enables SCA rules like:

    [+aspirated] > [-aspirated] / [-stressed] __

instead of enumerating individual phonemes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FeatureValue(Enum):
    """Binary feature value."""

    PLUS = "+"
    MINUS = "-"


@dataclass(frozen=True)
class PhonemeFeatures:
    """Distinctive feature matrix for a single phoneme.

    Attributes:
        base: The ASCIIPA base character (e.g. 'p', 't', 'k').
        voice: Voicing (+voiced / -voiceless).
        nasal: Nasality.
        aspirated: Aspiration.
        labialized: Labialization.
        palatalized: Palatalization.
        place: Place of articulation (e.g. 'bilabial', 'alveolar', 'velar').
        manner: Manner of articulation (e.g. 'stop', 'fricative', 'nasal').
        airflow: Airflow mechanism ('pulmonic', 'ejective', 'implosive', 'click').
        extra: Additional custom features.
    """

    base: str
    voice: FeatureValue = FeatureValue.MINUS
    nasal: FeatureValue = FeatureValue.MINUS
    aspirated: FeatureValue = FeatureValue.MINUS
    labialized: FeatureValue = FeatureValue.MINUS
    palatalized: FeatureValue = FeatureValue.MINUS
    place: str = ""
    manner: str = ""
    airflow: str = "pulmonic"
    extra: dict[str, str] = field(default_factory=dict)

    def matches(self, feature_query: dict[str, str]) -> bool:
        """Check if this phoneme matches a feature query.

        Args:
            feature_query: Dict of feature_name → expected_value.
                E.g. {'voice': '+', 'manner': 'stop'}

        Returns:
            True if all queried features match.
        """
        for key, expected in feature_query.items():
            actual = getattr(self, key, self.extra.get(key))
            if actual is None:
                return False
            if isinstance(actual, FeatureValue):
                if actual.value != expected:
                    return False
            elif str(actual) != expected:
                return False
        return True


# ---------------------------------------------------------------------------
# Built-in feature database for common ASCIIPA phonemes
# ---------------------------------------------------------------------------

_FEATURE_DB: dict[str, PhonemeFeatures] = {
    # Pulmonic stops
    "p": PhonemeFeatures(base="p", place="bilabial", manner="stop"),
    "b": PhonemeFeatures(base="b", voice=FeatureValue.PLUS, place="bilabial", manner="stop"),
    "t": PhonemeFeatures(base="t", place="alveolar", manner="stop"),
    "d": PhonemeFeatures(base="d", voice=FeatureValue.PLUS, place="alveolar", manner="stop"),
    "k": PhonemeFeatures(base="k", place="velar", manner="stop"),
    "g": PhonemeFeatures(base="g", voice=FeatureValue.PLUS, place="velar", manner="stop"),
    "q": PhonemeFeatures(base="q", place="uvular", manner="stop"),
    # Nasals
    "m": PhonemeFeatures(
        base="m", voice=FeatureValue.PLUS, nasal=FeatureValue.PLUS,
        place="bilabial", manner="nasal",
    ),
    "n": PhonemeFeatures(
        base="n", voice=FeatureValue.PLUS, nasal=FeatureValue.PLUS,
        place="alveolar", manner="nasal",
    ),
    "{ng}": PhonemeFeatures(
        base="{ng}", voice=FeatureValue.PLUS, nasal=FeatureValue.PLUS,
        place="velar", manner="nasal",
    ),
    # Fricatives
    "f": PhonemeFeatures(base="f", place="labiodental", manner="fricative"),
    "v": PhonemeFeatures(
        base="v", voice=FeatureValue.PLUS, place="labiodental", manner="fricative",
    ),
    "s": PhonemeFeatures(base="s", place="alveolar", manner="fricative"),
    "z": PhonemeFeatures(
        base="z", voice=FeatureValue.PLUS, place="alveolar", manner="fricative",
    ),
    "{sh}": PhonemeFeatures(base="{sh}", place="postalveolar", manner="fricative"),
    "{zh}": PhonemeFeatures(
        base="{zh}", voice=FeatureValue.PLUS, place="postalveolar", manner="fricative",
    ),
    "{th}": PhonemeFeatures(base="{th}", place="dental", manner="fricative"),
    "{dh}": PhonemeFeatures(
        base="{dh}", voice=FeatureValue.PLUS, place="dental", manner="fricative",
    ),
    "h": PhonemeFeatures(base="h", place="glottal", manner="fricative"),
    # Approximants
    "l": PhonemeFeatures(
        base="l", voice=FeatureValue.PLUS, place="alveolar", manner="lateral",
    ),
    "{r}": PhonemeFeatures(
        base="{r}", voice=FeatureValue.PLUS, place="alveolar", manner="tap",
    ),
    "w": PhonemeFeatures(
        base="w", voice=FeatureValue.PLUS, place="bilabial", manner="approximant",
    ),
    "j": PhonemeFeatures(
        base="j", voice=FeatureValue.PLUS, place="palatal", manner="approximant",
    ),
    # Implosives
    "<b": PhonemeFeatures(
        base="<b", voice=FeatureValue.PLUS, place="bilabial", manner="stop",
        airflow="implosive",
    ),
    "<d": PhonemeFeatures(
        base="<d", voice=FeatureValue.PLUS, place="alveolar", manner="stop",
        airflow="implosive",
    ),
    "<g": PhonemeFeatures(
        base="<g", voice=FeatureValue.PLUS, place="velar", manner="stop",
        airflow="implosive",
    ),
    # Clicks
    "|": PhonemeFeatures(base="|", place="dental", manner="click", airflow="click"),
    "!": PhonemeFeatures(base="!", place="alveolar", manner="click", airflow="click"),
    "||": PhonemeFeatures(base="||", place="lateral", manner="click", airflow="click"),
    "=": PhonemeFeatures(base="=", place="palatal", manner="click", airflow="click"),
    # Vowels
    "i": PhonemeFeatures(base="i", voice=FeatureValue.PLUS, place="front", manner="vowel"),
    "e": PhonemeFeatures(base="e", voice=FeatureValue.PLUS, place="front", manner="vowel"),
    "a": PhonemeFeatures(base="a", voice=FeatureValue.PLUS, place="central", manner="vowel"),
    "o": PhonemeFeatures(base="o", voice=FeatureValue.PLUS, place="back", manner="vowel"),
    "u": PhonemeFeatures(base="u", voice=FeatureValue.PLUS, place="back", manner="vowel"),
}


def get_features(phoneme: str) -> PhonemeFeatures | None:
    """Look up distinctive features for a phoneme.

    Args:
        phoneme: ASCIIPA phoneme string (e.g. 'p', '{sh}', '<b').

    Returns:
        PhonemeFeatures if found, None otherwise.
    """
    return _FEATURE_DB.get(phoneme)


def find_phonemes(**features: str) -> list[str]:
    """Find all phonemes matching the given feature constraints.

    Args:
        **features: Feature name → expected value pairs.

    Returns:
        List of matching ASCIIPA phoneme strings.

    Example::

        find_phonemes(manner="stop", voice="-")  # → ['p', 't', 'k', 'q']
    """
    result = []
    for name, pf in _FEATURE_DB.items():
        if pf.matches(features):
            result.append(name)
    return result
