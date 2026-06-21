"""Lexicon module — dictionary entries, database, and etymology tracking."""

from conlang.lexicon.database import LexiconDatabase
from conlang.lexicon.entry import LexemeEntry
from conlang.lexicon.etymology import EtymologyChain

__all__ = ["LexiconDatabase", "LexemeEntry", "EtymologyChain"]
