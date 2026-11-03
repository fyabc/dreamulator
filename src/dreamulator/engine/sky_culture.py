"""Sky-culture derivation — pure functions, no IO (the sky_background precedent).

The cross-file contract lives here: asterism edges and star_names keys must
reference background-object ids from the astronomy layer's derived sky
catalogue.  Referenceable ids are the authored stars and the deep-sky objects;
procedural starfield ids are excluded on purpose — their numbering shifts
whenever the starfield spec (seed/count/limit) changes, so a stale reference
would silently point at a different star instead of failing validation.

The engine (``civilization.py``) turns a non-empty error list into a build
failure; ``derive_sky_culture`` itself only normalizes (deduplicates edges),
so the two steps stay independently testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.models.sky_culture import SkyCulture, SkyCultureDerived, SkyCultureInput

if TYPE_CHECKING:
    from dreamulator.models.sky_background import SkyBackgroundDerived


def collect_reference_ids(background: SkyBackgroundDerived) -> set[str]:
    """Ids a sky culture may reference: authored stars + deep-sky objects."""
    return {star.id for star in background.stars if star.source == "authored"} | {
        dso.id for dso in background.deep_sky
    }


def validate_cultures(cultures: list[SkyCulture], valid_ids: set[str]) -> list[str]:
    """Referential integrity against the sky catalogue. [] = valid.

    Structural problems (empty figures, self-edges, duplicate ids) are already
    rejected by the Pydantic validators; this pass only reports references that
    do not resolve, one message per offending id, so a build failure lists
    everything the author has to fix at once.
    """
    errors: list[str] = []
    for culture in cultures:
        for asterism in culture.asterisms:
            for a, b in asterism.lines:
                for ref in (a, b):
                    if ref not in valid_ids:
                        errors.append(
                            f"asterism {asterism.id!r} (culture {culture.id!r}): "
                            f"unknown background object id {ref!r}"
                        )
        for star_id in culture.star_names:
            if star_id not in valid_ids:
                errors.append(
                    f"culture {culture.id!r}: star_names references unknown id {star_id!r}"
                )
    return errors


def normalize_edges(lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Deduplicate unordered edge pairs, keeping first-occurrence order."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for a, b in lines:
        key = (a, b) if a <= b else (b, a)
        if key not in seen:
            seen.add(key)
            out.append((a, b))
    return out


def derive_sky_culture(source: SkyCultureInput) -> SkyCultureDerived:
    """Input → derived: normalize edges (validation ran before this point)."""
    cultures = [
        culture.model_copy(
            update={
                "asterisms": [
                    asterism.model_copy(update={"lines": normalize_edges(asterism.lines)})
                    for asterism in culture.asterisms
                ]
            }
        )
        for culture in source.cultures
    ]
    return SkyCultureDerived(cultures=cultures)
