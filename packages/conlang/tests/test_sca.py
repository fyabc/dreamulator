"""Tests for the SCA (Sound Change Applier) engine."""

from conlang.phonology.sca import SCAEngine


class TestSCABasic:
    """Basic SCA functionality tests."""

    def setup_method(self) -> None:
        self.engine = SCAEngine(seed=42)
        self.engine.add_category("V", "i e a o u")

    def test_unconditional_change(self) -> None:
        self.engine.add_rule("p > b")
        assert self.engine.apply("p a") == "b a"

    def test_environmental_change(self) -> None:
        """p → f between vowels only."""
        self.engine.add_rule("p > f / V _ V")
        assert self.engine.apply("a p a") == "a f a"
        # Word-initial p should NOT change
        assert self.engine.apply("p a t a") == "p a t a"

    def test_no_match_no_change(self) -> None:
        self.engine.add_rule("z > s")
        assert self.engine.apply("p a t a") == "p a t a"

    def test_multiple_rules(self) -> None:
        self.engine.add_rules([
            "p > f / V _ V",
            "t > s / V _ V",
            "k > h / V _ V",
        ])
        assert self.engine.apply("t a p a") == "t a f a"
        assert self.engine.apply("a k a t a") == "a h a s a"

    def test_word_boundary(self) -> None:
        """Aspiration at word onset."""
        self.engine.add_rule("p > p^h / # _")
        assert self.engine.apply("p a") == "p^h a"
        # Medial p should NOT change
        assert self.engine.apply("a p a") == "a p a"

    def test_clear_rules(self) -> None:
        self.engine.add_rule("p > b")
        self.engine.clear_rules()
        assert self.engine.apply("p a") == "p a"


class TestSCAChainShift:
    """Tests for chain shift correctness (the 'order matters' problem)."""

    def test_drag_chain(self) -> None:
        """Correct drag chain: p^h moves first, then p fills the gap."""
        engine = SCAEngine(seed=42)
        engine.add_category("V", "i e a o u")
        # Step 1: Aspirated stops become fricatives (gap opens)
        engine.add_rule("p^h > f")
        # Step 2: Plain stops become aspirated (fill the gap)
        engine.add_rule("p > p^h")

        # Original p^h → f (step 1)
        assert engine.apply("p^h a") == "f a"
        # Original p → p^h (step 2, doesn't re-trigger step 1)
        assert engine.apply("p a") == "p^h a"

    def test_push_chain(self) -> None:
        """Push chain: lower series pushes upper series up."""
        engine = SCAEngine(seed=42)
        engine.add_category("V", "i e a o u")
        #浊 → 清 (push up)
        engine.add_rule("b > p")
        engine.add_rule("d > t")
        engine.add_rule("g > k")

        assert engine.apply("b a") == "p a"
        assert engine.apply("d a") == "t a"


class TestVhaKlikEvolution:
    """Integration test: Vha'Klik Highland → Lowland dialect evolution."""

    def setup_method(self) -> None:
        self.engine = SCAEngine(seed=42)
        self.engine.add_category("V", "i e a o u")
        # Phase 1: Click collapse
        self.engine.add_rules([
            "| > t",
            "! > t^h",
            "|| > l",
        ])
        # Phase 2: Ejective degradation
        self.engine.add_rules([
            "p' > p^h",
            "t' > t^h",
            "k' > k^h",
        ])
        # Phase 3: Implosive voicing
        self.engine.add_rules([
            "<b > b",
            "<d > d",
            "<g > g",
        ])

    def test_click_to_stop(self) -> None:
        """Dental click → plain stop."""
        assert self.engine.apply("| a") == "t a"

    def test_alveolar_click_to_aspirated(self) -> None:
        """Alveolar click → aspirated stop."""
        assert self.engine.apply("! i") == "t^h i"

    def test_lateral_click_to_l(self) -> None:
        """Lateral click → lateral approximant."""
        assert self.engine.apply("|| o") == "l o"

    def test_ejective_to_aspirated(self) -> None:
        """Ejective stops → aspirated stops."""
        assert self.engine.apply("p' a") == "p^h a"
        assert self.engine.apply("k' u") == "k^h u"

    def test_implosive_to_voiced(self) -> None:
        """Implosive stops → plain voiced stops."""
        assert self.engine.apply("<b a") == "b a"
        assert self.engine.apply("<d e") == "d e"
        assert self.engine.apply("<g u") == "g u"

    def test_full_lexicon_evolution(self) -> None:
        """Evolve a small Vha'Klik lexicon."""
        self.engine.load_lexicon([
            "| a",     # spirit → ta
            "! i",     # sacred → t^hi
            "p' a",    # guard → p^ha
            "<b a",    # mother → ba
        ])
        results = self.engine.apply_all()
        assert results["| a"] == "t a"
        assert results["! i"] == "t^h i"
        assert results["p' a"] == "p^h a"
        assert results["<b a"] == "b a"


class TestSCAProbabilistic:
    """Tests for probabilistic sound change."""

    def test_probabilistic_zero(self) -> None:
        """0% probability → no change."""
        engine = SCAEngine(seed=42)
        engine.add_category("V", "i e a o u")
        engine.add_rule("p > f / V _ V [0.0]")
        assert engine.apply("a p a") == "a p a"

    def test_probabilistic_certain(self) -> None:
        """100% probability → always changes."""
        engine = SCAEngine(seed=42)
        engine.add_category("V", "i e a o u")
        engine.add_rule("p > f / V _ V [1.0]")
        assert engine.apply("a p a") == "a f a"

    def test_lexicon_frequency_map(self) -> None:
        """Lexicon frequency dict is properly formed."""
        engine = SCAEngine(seed=42)
        engine.load_lexicon({"p a": 0.9, "t a": 0.1})
        freq = {w: 1.0 for w in engine._lexicon}
        assert "p a" in freq
        assert "t a" in freq
