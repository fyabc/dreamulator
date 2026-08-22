"""Etymology tracking — word history and derivation chains.

Records the historical derivation of words, supporting:
- Direct derivation (A → B via sound change)
- Borrowing (word borrowed from another language)
- Compound formation (A + B → C)
- Semantic shift (same form, changed meaning)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DerivationType(str, Enum):
    """How a word was derived."""

    SOUND_CHANGE = "sound_change"
    BORROWING = "borrowing"
    COMPOUND = "compound"
    DERIVATION = "derivation"
    SEMANTIC_SHIFT = "semantic_shift"
    ANALOGY = "analogy"
    UNKNOWN = "unknown"


class EtymologyRecord(BaseModel):
    """A single etymology record linking ancestor → descendant.

    Attributes:
        id: Unique identifier.
        descendant_id: LexemeEntry.id of the derived word.
        ancestor_ids: LexemeEntry.ids of ancestor word(s).
        derivation_type: How the derivation occurred.
        source_language: Language the word was borrowed from (if borrowing).
        rules_applied: SCA rule names that produced this change (if sound change).
        notes: Free-form notes.
        period: Historical period label (e.g. 'Proto', 'Old', 'Middle').
    """

    id: str
    descendant_id: str
    ancestor_ids: list[str] = Field(default_factory=list)
    derivation_type: DerivationType = DerivationType.SOUND_CHANGE
    source_language: str = ""
    rules_applied: list[str] = Field(default_factory=list)
    notes: str = ""
    period: str = ""


class EtymologyChain:
    """Build and query etymology derivation chains.

    Usage::

        chain = EtymologyChain()
        chain.add(EtymologyRecord(
            id="ety_001",
            descendant_id="lex_modern_spirit",
            ancestor_ids=["lex_proto_spirit"],
            derivation_type=DerivationType.SOUND_CHANGE,
            rules_applied=["click_collapse", "tone_merger"],
        ))

        # Trace back
        ancestors = chain.trace_ancestors("lex_modern_spirit")
    """

    def __init__(self) -> None:
        self._records: dict[str, EtymologyRecord] = {}
        self._by_descendant: dict[str, list[str]] = {}  # descendant_id → record_ids

    def add(self, record: EtymologyRecord) -> None:
        """Add an etymology record.

        Args:
            record: EtymologyRecord to add.
        """
        self._records[record.id] = record
        self._by_descendant.setdefault(record.descendant_id, []).append(record.id)

    def get(self, record_id: str) -> EtymologyRecord | None:
        """Get a record by ID."""
        return self._records.get(record_id)

    def trace_ancestors(self, lexeme_id: str) -> list[EtymologyRecord]:
        """Trace the full ancestor chain for a word.

        Follows derivation links backwards through history.

        Args:
            lexeme_id: Starting LexemeEntry.id.

        Returns:
            List of EtymologyRecords from most recent to oldest ancestor.
        """
        visited: set[str] = set()
        result: list[EtymologyRecord] = []
        queue = [lexeme_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            record_ids = self._by_descendant.get(current_id, [])
            for rid in record_ids:
                record = self._records[rid]
                result.append(record)
                queue.extend(record.ancestor_ids)

        return result

    def get_derivation_tree(self, lexeme_id: str) -> dict:
        """Build a nested derivation tree for visualization.

        Args:
            lexeme_id: Root LexemeEntry.id.

        Returns:
            Nested dict representing the derivation tree.
        """
        records = self.trace_ancestors(lexeme_id)
        if not records:
            return {"id": lexeme_id, "children": []}

        tree: dict = {"id": lexeme_id, "children": []}
        for record in records:
            for ancestor_id in record.ancestor_ids:
                child = self.get_derivation_tree(ancestor_id)
                child["derivation"] = record.derivation_type.value
                tree["children"].append(child)

        return tree
