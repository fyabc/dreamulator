"""Lexicon database — persistent storage and querying of lexical entries.

Supports YAML-based persistence, filtering by part of speech, semantic
field, register, and full-text search over glosses and forms.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from conlang.lexicon.entry import CognateSet, LexemeEntry, PartOfSpeech, Register


class LexiconDatabase:
    """In-memory lexicon database with YAML persistence.

    Usage::

        db = LexiconDatabase()
        db.add(LexemeEntry(id="lex_001", form="!i:55", gloss="sacred"))
        db.add(LexemeEntry(id="lex_002", form="p'a", gloss="guard"))

        # Query
        sacred_words = db.filter(register=Register.SACRED)
        nouns = db.filter(pos=PartOfSpeech.NOUN)

        # Persist
        db.save("lexicon.yaml")

        # Load
        db2 = LexiconDatabase.load("lexicon.yaml")
    """

    def __init__(self) -> None:
        self._entries: dict[str, LexemeEntry] = {}
        self._cognates: dict[str, CognateSet] = {}

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def add(self, entry: LexemeEntry) -> None:
        """Add a lexical entry.

        Args:
            entry: LexemeEntry to add.

        Raises:
            ValueError: If an entry with the same ID already exists.
        """
        if entry.id in self._entries:
            raise ValueError(f"Duplicate entry ID: {entry.id}")
        self._entries[entry.id] = entry

    def update(self, entry: LexemeEntry) -> None:
        """Update an existing entry.

        Args:
            entry: Updated LexemeEntry.

        Raises:
            KeyError: If no entry with this ID exists.
        """
        if entry.id not in self._entries:
            raise KeyError(f"Entry not found: {entry.id}")
        self._entries[entry.id] = entry

    def remove(self, entry_id: str) -> None:
        """Remove an entry by ID.

        Args:
            entry_id: Entry identifier.

        Raises:
            KeyError: If no entry with this ID exists.
        """
        if entry_id not in self._entries:
            raise KeyError(f"Entry not found: {entry_id}")
        del self._entries[entry_id]

    def get(self, entry_id: str) -> LexemeEntry | None:
        """Get an entry by ID.

        Args:
            entry_id: Entry identifier.

        Returns:
            LexemeEntry if found, None otherwise.
        """
        return self._entries.get(entry_id)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[LexemeEntry]:
        return iter(self._entries.values())

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def filter(
        self,
        *,
        pos: PartOfSpeech | None = None,
        register: Register | None = None,
        semantic_field: str | None = None,
        tag: str | None = None,
        min_frequency: float | None = None,
    ) -> list[LexemeEntry]:
        """Filter entries by criteria.

        Args:
            pos: Filter by part of speech.
            register: Filter by register.
            semantic_field: Filter by semantic field (prefix match).
            tag: Filter by tag.
            min_frequency: Minimum frequency threshold.

        Returns:
            List of matching entries.
        """
        results: list[LexemeEntry] = []
        for entry in self._entries.values():
            if pos is not None and entry.pos != pos:
                continue
            if register is not None and entry.register_level != register:
                continue
            if semantic_field is not None and not entry.semantic_field.startswith(
                semantic_field
            ):
                continue
            if tag is not None and tag not in entry.tags:
                continue
            if min_frequency is not None and entry.frequency < min_frequency:
                continue
            results.append(entry)
        return results

    def search(self, query: str) -> list[LexemeEntry]:
        """Full-text search over forms and glosses.

        Args:
            query: Search string (case-insensitive substring match).

        Returns:
            List of matching entries.
        """
        query_lower = query.lower()
        results: list[LexemeEntry] = []
        for entry in self._entries.values():
            if query_lower in entry.form.lower() or query_lower in entry.gloss.lower():
                results.append(entry)
        return results

    def forms_list(self) -> list[str]:
        """Get all word forms (for feeding into SCA engine).

        Returns:
            List of ASCIIPA form strings.
        """
        return [e.form for e in self._entries.values()]

    def frequency_map(self) -> dict[str, float]:
        """Get word → frequency mapping (for SCA generational simulation).

        Returns:
            Dict of form → frequency.
        """
        return {e.form: e.frequency for e in self._entries.values()}

    # ------------------------------------------------------------------
    # Cognate management
    # ------------------------------------------------------------------

    def add_cognate_set(self, cognate: CognateSet) -> None:
        """Add a cognate set.

        Args:
            cognate: CognateSet to add.
        """
        self._cognates[cognate.id] = cognate

    def get_cognates(self, cognate_id: str) -> CognateSet | None:
        """Get a cognate set by ID."""
        return self._cognates.get(cognate_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Save the database to a YAML file.

        Args:
            path: Output file path.
        """
        adapter = TypeAdapter(list[LexemeEntry])
        entries_data = adapter.dump_python(list(self._entries.values()), mode="json")

        cognate_adapter = TypeAdapter(list[CognateSet])
        cognates_data = cognate_adapter.dump_python(
            list(self._cognates.values()), mode="json"
        )

        data = {
            "lexicon": entries_data,
            "cognates": cognates_data,
        }

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: str | Path) -> LexiconDatabase:
        """Load a database from a YAML file.

        Args:
            path: Input file path.

        Returns:
            Populated LexiconDatabase.
        """
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        db = cls()

        if "lexicon" in data:
            adapter = TypeAdapter(list[LexemeEntry])
            entries = adapter.validate_python(data["lexicon"])
            for entry in entries:
                db.add(entry)

        if "cognates" in data:
            cognate_adapter = TypeAdapter(list[CognateSet])
            cognates = cognate_adapter.validate_python(data["cognates"])
            for cognate in cognates:
                db.add_cognate_set(cognate)

        return db
