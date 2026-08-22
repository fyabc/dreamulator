"""Affix rule builders — convenience functions for common morphological patterns.

Provides factory functions for creating common affix patterns found in
natural and constructed languages: agglutinative suffix chains, fusional
portmanteau morphemes, and templatic morphology.
"""

from __future__ import annotations

from conlang.morphology.fst import (
    AffixRule,
    AffixType,
    Morpheme,
    MorphologicalRule,
)


def suffix_rule(
    name: str,
    suffix_form: str,
    *,
    gloss: str = "",
    category: str = "",
    stem_changes: list[tuple[str, str]] | None = None,
) -> MorphologicalRule:
    """Create a simple suffix rule.

    Args:
        name: Rule name (e.g. 'plural').
        suffix_form: ASCIIPA suffix form.
        gloss: Meaning label.
        category: Grammatical category.
        stem_changes: Optional (pattern, replacement) pairs for stem modification.

    Returns:
        MorphologicalRule with a single suffix AffixRule.
    """
    return MorphologicalRule(
        name=name,
        category=category,
        affix_rules=[
            AffixRule(
                affix=Morpheme(form=suffix_form, gloss=gloss or name.upper()),
                affix_type=AffixType.SUFFIX,
                stem_changes=stem_changes or [],
            )
        ],
    )


def prefix_rule(
    name: str,
    prefix_form: str,
    *,
    gloss: str = "",
    category: str = "",
) -> MorphologicalRule:
    """Create a simple prefix rule.

    Args:
        name: Rule name.
        prefix_form: ASCIIPA prefix form.
        gloss: Meaning label.
        category: Grammatical category.

    Returns:
        MorphologicalRule with a single prefix AffixRule.
    """
    return MorphologicalRule(
        name=name,
        category=category,
        affix_rules=[
            AffixRule(
                affix=Morpheme(form=prefix_form, gloss=gloss or name.upper()),
                affix_type=AffixType.PREFIX,
            )
        ],
    )


def agglutinative_chain(
    name: str,
    suffixes: list[tuple[str, str]],
    *,
    category: str = "",
) -> MorphologicalRule:
    """Create an agglutinative suffix chain.

    Each suffix expresses exactly one grammatical feature, attached in order.

    Args:
        name: Rule name (e.g. 'case_number').
        suffixes: List of (suffix_form, gloss) pairs.
        category: Grammatical category.

    Returns:
        MorphologicalRule with ordered suffix chain.

    Example::

        agglutinative_chain(
            "turkish_like",
            [("ler", "PL"), ("den", "ABL")],
        )
        # ev → ev-ler-den  (from the houses)
    """
    rules = [
        AffixRule(
            affix=Morpheme(form=form, gloss=gloss),
            affix_type=AffixType.SUFFIX,
        )
        for form, gloss in suffixes
    ]
    return MorphologicalRule(
        name=name,
        category=category,
        affix_rules=rules,
    )
