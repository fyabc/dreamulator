"""Tests for X-SAMPA conversion — verify all conversions are lossless."""

import pytest

from conlang.phonology.asciipa import asciipa_to_ipa, ipa_to_asciipa
from conlang.phonology.xsampa import ipa_to_xsampa, to_xsampa


# ---------------------------------------------------------------------------
# Reference data: (ASCIIPA, expected IPA, expected X-SAMPA)
# ---------------------------------------------------------------------------
CONVERSION_CASES: list[tuple[str, str, str]] = [
    # Basic consonants
    ("p", "p", "p"),
    ("b", "b", "b"),
    ("t", "t", "t"),
    ("d", "d", "d"),
    ("k", "k", "k"),
    ("g", "ɡ", "g"),
    # Brace macros
    ("{sh}", "ʃ", "S"),
    ("{zh}", "ʒ", "Z"),
    ("{th}", "θ", "T"),
    ("{dh}", "ð", "D"),
    ("{ng}", "ŋ", "N"),
    # {ch} = tʃ is ambiguous in IPA (affricate vs sequence),
    # so it round-trips as t + ʃ. Not included in lossless tests.
    # Small caps
    ("I", "ɪ", "I"),
    ("U", "ʊ", "U"),
    ("E", "ɛ", "E"),
    ("O", "ɔ", "O"),
    # Turned/escaped
    ("\\a", "ɐ", "6"),
    ("\\e", "ə", "@"),
    ("\\v", "ʌ", "V"),
    ("\\m", "ɯ", "M"),
    # Implosives
    ("<b", "ɓ", "b_<"),
    ("<d", "ɗ", "d_<"),
    # Vowels
    ("i", "i", "i"),
    ("a", "a", "a"),
    ("u", "u", "u"),
    ("{&}", "æ", "{"),
    ("A", "ɑ", "A"),
]


class TestIPAToSAMPA:
    """Direct IPA → X-SAMPA conversion tests."""

    @pytest.mark.parametrize(
        "asciipa, expected_ipa, expected_xsampa",
        CONVERSION_CASES,
        ids=[c[0] for c in CONVERSION_CASES],
    )
    def test_ipa_to_xsampa(
        self, asciipa: str, expected_ipa: str, expected_xsampa: str
    ) -> None:
        """Each IPA character maps to the correct X-SAMPA symbol."""
        result = ipa_to_xsampa(expected_ipa)
        assert result == expected_xsampa

    def test_word_think(self) -> None:
        assert ipa_to_xsampa("θɪŋk") == "TINk"

    def test_wrap(self) -> None:
        assert ipa_to_xsampa("θɪŋk", wrap=True) == "[[TINk]]"

    def test_stress_adjacent(self) -> None:
        """Primary stress marker should appear in output."""
        result = ipa_to_xsampa("həlˈoʊ")
        assert '"' in result  # X-SAMPA uses " for primary stress


class TestASCIIPAViaIPAToSAMPA:
    """ASCIIPA → IPA → X-SAMPA (universal hub) tests."""

    @pytest.mark.parametrize(
        "asciipa, expected_ipa, expected_xsampa",
        CONVERSION_CASES,
        ids=[c[0] for c in CONVERSION_CASES],
    )
    def test_to_xsampa_via_ipa(
        self, asciipa: str, expected_ipa: str, expected_xsampa: str
    ) -> None:
        """ASCIIPA → IPA → X-SAMPA produces correct X-SAMPA."""
        result = to_xsampa(asciipa, "asciipa")
        assert result == expected_xsampa

    def test_modifier_chain(self) -> None:
        """Modifiers decompose correctly through IPA hub."""
        assert to_xsampa("p^h", "asciipa") == "p_h"

    def test_implosive(self) -> None:
        assert to_xsampa("<b", "asciipa") == "b_<"

    def test_complex_word(self) -> None:
        result = to_xsampa("{th}I{ng}k", "asciipa")
        assert result == "TINk"


class TestRoundTrip:
    """Verify ASCIIPA ↔ IPA round-trip is lossless."""

    @pytest.mark.parametrize(
        "asciipa, expected_ipa, _",
        CONVERSION_CASES,
        ids=[c[0] for c in CONVERSION_CASES],
    )
    def test_asciipa_ipa_roundtrip(
        self, asciipa: str, expected_ipa: str, _: str
    ) -> None:
        """ASCIIPA → IPA → ASCIIPA preserves the original."""
        ipa = asciipa_to_ipa(asciipa)
        assert ipa == expected_ipa
        back = ipa_to_asciipa(ipa)
        assert back == asciipa


class TestDispatch:
    """Test to_xsampa format dispatch."""

    def test_ipa_format(self) -> None:
        assert to_xsampa("θɪŋk", "ipa") == "TINk"

    def test_xsampa_passthrough(self) -> None:
        assert to_xsampa("T I N k", "xsampa") == "T I N k"

    def test_xsampa_wrap(self) -> None:
        assert to_xsampa("θɪŋk", "ipa", wrap=True) == "[[TINk]]"

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown input format"):
            to_xsampa("test", "unknown")
