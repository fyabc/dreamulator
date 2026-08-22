"""Tests for morphology module."""

from conlang.morphology.affix import prefix_rule, suffix_rule
from conlang.morphology.fst import FSTEngine
from conlang.morphology.harmony import ConsonantMutation, VowelHarmony


class TestFSTEngine:
    """Tests for the FST morphological engine."""

    def setup_method(self) -> None:
        self.fst = FSTEngine()
        self.fst.add_rule(suffix_rule("plural", "lar", gloss="PL"))
        self.fst.add_rule(suffix_rule("ablative", "dan", gloss="ABL"))
        self.fst.add_rule(prefix_rule("negation", "ma", gloss="NEG"))

    def test_suffix_attachment(self) -> None:
        result = self.fst.inflect("ev", ["plural"])
        assert result == "evlar"

    def test_chained_suffixes(self) -> None:
        result = self.fst.inflect("ev", ["plural", "ablative"])
        assert result == "evlardan"

    def test_prefix_attachment(self) -> None:
        result = self.fst.inflect("bil", ["negation"])
        assert result == "mabil"

    def test_no_rules_noop(self) -> None:
        result = self.fst.inflect("ev", [])
        assert result == "ev"

    def test_unknown_rule_ignored(self) -> None:
        result = self.fst.inflect("ev", ["nonexistent"])
        assert result == "ev"

    def test_parse_suffix(self) -> None:
        result = self.fst.parse("evlar")
        assert result is not None
        assert len(result) == 2
        assert result[0] == ("ev", "ROOT")
        assert result[1][1] == "plural"


class TestVowelHarmony:
    """Tests for vowel harmony engine."""

    def setup_method(self) -> None:
        self.harmony = VowelHarmony(
            front_suffix="ler",
            back_suffix="lar",
        )

    def test_front_vowel_stem(self) -> None:
        """Stem with front vowel → front suffix."""
        assert self.harmony.apply("ev") == "evler"
        assert self.harmony.apply("git") == "gitler"

    def test_back_vowel_stem(self) -> None:
        """Stem with back vowel → back suffix."""
        assert self.harmony.apply("araba") == "arabalar"
        assert self.harmony.apply("okul") == "okullar"

    def test_classify(self) -> None:
        assert self.harmony.classify("ev") == "front"
        assert self.harmony.classify("araba") == "back"


class TestConsonantMutation:
    """Tests for consonant mutation."""

    def setup_method(self) -> None:
        self.mutation = ConsonantMutation({
            "p": "f",
            "t": "{th}",
            "k": "{gh}",
            "b": "v",
        })

    def test_mutation_applied(self) -> None:
        assert self.mutation.apply("pen") == "fen"
        assert self.mutation.apply("bwa") == "vwa"

    def test_no_mutation(self) -> None:
        assert self.mutation.apply("man") == "man"

    def test_empty_word(self) -> None:
        assert self.mutation.apply("") == ""
