"""Finite-State Transducer (FST) engine for morphological processing.

An FST maps abstract morpheme sequences (e.g. ROOT + PLURAL + PAST) to
surface forms, applying morphophonological rules along the way.

This is a simplified, rule-based FST suitable for agglutinative and
fusional morphology patterns common in constructed languages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AffixType(str, Enum):
    """Type of morphological affix."""

    PREFIX = "prefix"
    SUFFIX = "suffix"
    INFIX = "infix"
    CIRCUMFIX = "circumfix"


@dataclass
class Morpheme:
    """A single morpheme (root or affix).

    Attributes:
        form: ASCIIPA surface form.
        gloss: Meaning or grammatical label (e.g. 'PL', 'PAST').
        is_root: Whether this is a lexical root.
    """

    form: str
    gloss: str = ""
    is_root: bool = False


@dataclass
class AffixRule:
    """A rule for attaching an affix to a stem.

    Attributes:
        affix: The affix morpheme to attach.
        affix_type: Prefix, suffix, infix, or circumfix.
        condition: Optional environment condition (e.g. 'after vowel-final stem').
        stem_changes: Optional list of (pattern, replacement) for stem modification.
        description: Human-readable description of the rule.
    """

    affix: Morpheme
    affix_type: AffixType = AffixType.SUFFIX
    condition: str | None = None
    stem_changes: list[tuple[str, str]] = field(default_factory=list)
    description: str = ""


@dataclass
class MorphologicalRule:
    """A named morphological process (e.g. plural formation).

    Attributes:
        name: Process name (e.g. 'plural', 'past_tense').
        category: Grammatical category (e.g. 'number', 'tense').
        affix_rules: Ordered list of affix rules for this process.
    """

    name: str
    category: str = ""
    affix_rules: list[AffixRule] = field(default_factory=list)


class FSTEngine:
    """Rule-based finite-state transducer for morphology.

    Usage::

        fst = FSTEngine()
        fst.add_rule(MorphologicalRule(
            name="plural",
            category="number",
            affix_rules=[AffixRule(
                affix=Morpheme(form="lar", gloss="PL"),
                affix_type=AffixType.SUFFIX,
            )],
        ))

        result = fst.inflect("kitap", ["plural"])
        # → "kitaplar"
    """

    def __init__(self) -> None:
        self._rules: dict[str, MorphologicalRule] = {}

    def add_rule(self, rule: MorphologicalRule) -> None:
        """Register a morphological process.

        Args:
            rule: MorphologicalRule to register.
        """
        self._rules[rule.name] = rule

    def inflect(self, root: str, features: list[str]) -> str:
        """Apply morphological processes to a root form.

        Processes are applied in the order specified by ``features``.

        Args:
            root: ASCIIPA root form.
            features: List of process names to apply (e.g. ['plural', 'past']).

        Returns:
            Inflected ASCIIPA form.
        """
        stem = root
        for feature in features:
            rule = self._rules.get(feature)
            if rule is None:
                continue
            for affix_rule in rule.affix_rules:
                stem = self._apply_affix(stem, affix_rule)
        return stem

    def parse(self, surface_form: str) -> list[tuple[str, str]] | None:
        """Attempt to parse a surface form into root + features.

        This is a simplified greedy parser that tries to strip affixes
        from the outside in.

        Args:
            surface_form: ASCIIPA surface form.

        Returns:
            List of (form, gloss) pairs if parseable, None otherwise.
        """
        remaining = surface_form
        found_features: list[tuple[str, str]] = []

        # Try stripping suffixes first, then prefixes
        changed = True
        while changed:
            changed = False
            for name, rule in self._rules.items():
                for affix_rule in rule.affix_rules:
                    stripped = self._try_strip(remaining, affix_rule)
                    if stripped is not None:
                        remaining = stripped
                        found_features.append((affix_rule.affix.form, name))
                        changed = True

        if found_features:
            return [(remaining, "ROOT")] + list(reversed(found_features))
        return None

    def _apply_affix(self, stem: str, rule: AffixRule) -> str:
        """Apply a single affix rule to a stem."""
        # Apply stem changes first
        modified_stem = stem
        for pattern, replacement in rule.stem_changes:
            modified_stem = modified_stem.replace(pattern, replacement)

        # Attach affix
        affix_form = rule.affix.form
        if rule.affix_type == AffixType.PREFIX:
            return affix_form + modified_stem
        elif rule.affix_type == AffixType.SUFFIX:
            return modified_stem + affix_form
        elif rule.affix_type == AffixType.INFIX:
            # Insert after first vowel (simplified)
            for i, ch in enumerate(modified_stem):
                if ch in "aeiouAEIOU":
                    return modified_stem[: i + 1] + affix_form + modified_stem[i + 1 :]
            return modified_stem + affix_form
        else:
            return modified_stem + affix_form

    def _try_strip(self, form: str, rule: AffixRule) -> str | None:
        """Try to strip an affix from a form, returning the stem if successful."""
        affix = rule.affix.form
        if rule.affix_type == AffixType.SUFFIX and form.endswith(affix):
            stem = form[: -len(affix)]
            # Reverse stem changes
            for pattern, replacement in reversed(rule.stem_changes):
                stem = stem.replace(replacement, pattern)
            return stem
        elif rule.affix_type == AffixType.PREFIX and form.startswith(affix):
            return form[len(affix) :]
        return None
