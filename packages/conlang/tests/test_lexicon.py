"""Tests for lexicon module."""

import tempfile
from pathlib import Path

from conlang.lexicon.database import LexiconDatabase
from conlang.lexicon.entry import LexemeEntry, PartOfSpeech, Register
from conlang.lexicon.etymology import DerivationType, EtymologyChain, EtymologyRecord


class TestLexiconDatabase:
    """Tests for the lexicon database."""

    def setup_method(self) -> None:
        self.db = LexiconDatabase()

    def test_add_and_get(self) -> None:
        entry = LexemeEntry(id="lex_001", form="!i:55", gloss="sacred")
        self.db.add(entry)
        assert self.db.get("lex_001") is not None
        assert self.db.get("lex_001").gloss == "sacred"

    def test_duplicate_raises(self) -> None:
        entry = LexemeEntry(id="lex_001", form="!i:55", gloss="sacred")
        self.db.add(entry)
        import pytest

        with pytest.raises(ValueError, match="Duplicate"):
            self.db.add(entry)

    def test_remove(self) -> None:
        entry = LexemeEntry(id="lex_001", form="!i:55", gloss="sacred")
        self.db.add(entry)
        self.db.remove("lex_001")
        assert self.db.get("lex_001") is None

    def test_filter_by_pos(self) -> None:
        self.db.add(LexemeEntry(id="1", form="a", pos=PartOfSpeech.NOUN))
        self.db.add(LexemeEntry(id="2", form="b", pos=PartOfSpeech.VERB))
        nouns = self.db.filter(pos=PartOfSpeech.NOUN)
        assert len(nouns) == 1
        assert nouns[0].id == "1"

    def test_filter_by_register(self) -> None:
        self.db.add(LexemeEntry(id="1", form="a", register_level=Register.SACRED))
        self.db.add(LexemeEntry(id="2", form="b", register_level=Register.NEUTRAL))
        sacred = self.db.filter(register=Register.SACRED)
        assert len(sacred) == 1

    def test_search(self) -> None:
        self.db.add(LexemeEntry(id="1", form="!i:55", gloss="sacred fire"))
        self.db.add(LexemeEntry(id="2", form="p'a", gloss="guard"))
        results = self.db.search("sacred")
        assert len(results) == 1
        assert results[0].id == "1"

    def test_forms_list(self) -> None:
        self.db.add(LexemeEntry(id="1", form="!i:55", gloss="a"))
        self.db.add(LexemeEntry(id="2", form="p'a", gloss="b"))
        forms = self.db.forms_list()
        assert "!i:55" in forms
        assert "p'a" in forms

    def test_save_and_load(self) -> None:
        self.db.add(LexemeEntry(id="1", form="!i:55", gloss="sacred"))
        self.db.add(LexemeEntry(id="2", form="p'a", gloss="guard"))

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        try:
            self.db.save(path)
            loaded = LexiconDatabase.load(path)
            assert len(loaded) == 2
            assert loaded.get("1").gloss == "sacred"
        finally:
            path.unlink(missing_ok=True)


class TestEtymologyChain:
    """Tests for etymology tracking."""

    def setup_method(self) -> None:
        self.chain = EtymologyChain()

    def test_add_and_trace(self) -> None:
        self.chain.add(
            EtymologyRecord(
                id="ety_001",
                descendant_id="lex_modern",
                ancestor_ids=["lex_proto"],
                derivation_type=DerivationType.SOUND_CHANGE,
                rules_applied=["click_collapse"],
            )
        )
        ancestors = self.chain.trace_ancestors("lex_modern")
        assert len(ancestors) == 1
        assert ancestors[0].ancestor_ids == ["lex_proto"]

    def test_multi_step_trace(self) -> None:
        self.chain.add(
            EtymologyRecord(
                id="ety_001",
                descendant_id="lex_modern",
                ancestor_ids=["lex_middle"],
            )
        )
        self.chain.add(
            EtymologyRecord(
                id="ety_002",
                descendant_id="lex_middle",
                ancestor_ids=["lex_proto"],
            )
        )
        ancestors = self.chain.trace_ancestors("lex_modern")
        assert len(ancestors) == 2

    def test_derivation_tree(self) -> None:
        self.chain.add(
            EtymologyRecord(
                id="ety_001",
                descendant_id="lex_child",
                ancestor_ids=["lex_parent_a", "lex_parent_b"],
                derivation_type=DerivationType.COMPOUND,
            )
        )
        tree = self.chain.get_derivation_tree("lex_child")
        assert tree["id"] == "lex_child"
        assert len(tree["children"]) == 2
