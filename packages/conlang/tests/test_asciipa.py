"""Tests for ASCIIPA tokenizer and encoding."""

from conlang.phonology.asciipa import ASCIIPATokenizer, asciipa_to_ipa, ipa_to_asciipa


class TestASCIIPATokenizer:
    """Tests for the ASCIIPA tokenizer."""

    def setup_method(self) -> None:
        self.tokenizer = ASCIIPATokenizer()

    def test_basic_characters(self) -> None:
        tokens = self.tokenizer.tokenize("p t k")
        assert len(tokens) == 3
        assert [t.raw for t in tokens] == ["p", "t", "k"]

    def test_brace_macros(self) -> None:
        tokens = self.tokenizer.tokenize("{sh} {ng} {th}")
        assert len(tokens) == 3
        assert tokens[0].is_macro
        assert tokens[0].raw == "{sh}"
        assert tokens[1].raw == "{ng}"
        assert tokens[2].raw == "{th}"

    def test_superscript_modifiers(self) -> None:
        tokens = self.tokenizer.tokenize("p^h k^w t^j")
        assert len(tokens) == 3
        assert tokens[0].raw == "p^h"
        assert tokens[0].base == "p"
        assert tokens[0].modifiers == ("^h",)

    def test_subscript_modifiers(self) -> None:
        tokens = self.tokenizer.tokenize("n_o s_v")
        assert len(tokens) == 2
        assert tokens[0].raw == "n_o"
        assert tokens[0].modifiers == ("_o",)

    def test_escaped_turned(self) -> None:
        tokens = self.tokenizer.tokenize("\\a \\e \\v")
        assert len(tokens) == 3
        assert tokens[0].raw == "\\a"
        assert tokens[0].base == "\\a"

    def test_small_caps(self) -> None:
        tokens = self.tokenizer.tokenize("I U E O A")
        assert len(tokens) == 5
        assert [t.raw for t in tokens] == ["I", "U", "E", "O", "A"]

    def test_nasalization(self) -> None:
        tokens = self.tokenizer.tokenize("a~ o~")
        assert len(tokens) == 2
        assert tokens[0].raw == "a~"
        assert tokens[0].modifiers == ("~",)

    def test_ejective(self) -> None:
        tokens = self.tokenizer.tokenize("p' t' k'")
        assert len(tokens) == 3
        assert tokens[0].raw == "p'"
        assert tokens[0].modifiers == ("'",)

    def test_retroflex(self) -> None:
        tokens = self.tokenizer.tokenize("t> d> n>")
        assert len(tokens) == 3
        assert tokens[0].raw == "t>"
        assert tokens[0].base == "t"

    def test_implosives(self) -> None:
        tokens = self.tokenizer.tokenize("<b <d <g")
        assert len(tokens) == 3
        assert tokens[0].raw == "<b"

    def test_complex_word(self) -> None:
        """Vha'Klik sacred word: aspirated alveolar click + nasalized turned-a."""
        tokens = self.tokenizer.tokenize("{!^h} \\a~")
        assert len(tokens) == 2
        assert tokens[0].is_macro
        assert tokens[1].base == "\\a"
        assert tokens[1].modifiers == ("~",)

    def test_detokenize_roundtrip(self) -> None:
        original = "p^h a . t a"
        tokens = self.tokenizer.tokenize(original)
        result = self.tokenizer.detokenize(tokens)
        assert result == original

    def test_empty_string(self) -> None:
        tokens = self.tokenizer.tokenize("")
        assert tokens == []

    def test_syllable_dot(self) -> None:
        tokens = self.tokenizer.tokenize("ka.ta")
        # Should have: ka, ., ta
        assert len(tokens) >= 3


class TestIPAConversion:
    """Tests for IPA ↔ ASCIIPA conversion."""

    def test_ipa_to_asciipa_basic(self) -> None:
        result = ipa_to_asciipa("ʃɪŋk")
        assert "{sh}" in result
        assert "I" in result
        assert "{ng}" in result

    def test_ipa_to_asciipa_think(self) -> None:
        result = ipa_to_asciipa("θɪŋk")
        assert "{th}" in result

    def test_asciipa_to_ipa_basic(self) -> None:
        result = asciipa_to_ipa("{sh}")
        assert result == "ʃ"

    def test_asciipa_to_ipa_ng(self) -> None:
        result = asciipa_to_ipa("{ng}")
        assert result == "ŋ"

    def test_asciipa_to_ipa_turned(self) -> None:
        result = asciipa_to_ipa("\\e")
        assert result == "ə"
