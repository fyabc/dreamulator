"""Explicit plate-pair polarity sources shared by tectonics and terrain.

Absolute plate speed depends on the reference frame. A declared slab side is
an authored or observational input, with its temporal scope recorded here.
Untimed declarations describe the present; dated intervals use geological
age (Myr before the present) and follow the same plate IDs through rotation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def plate_pair(a: str, b: str) -> tuple[str, str]:
    """Canonical pair key, independent of the order in a source or query."""
    return (a, b) if a < b else (b, a)


@dataclass(frozen=True)
class SubductionPolarity:
    """A slab-side declaration for a plate pair and a specified time span."""

    id: str
    plates: tuple[str, str]
    down_going: str
    source_kind: Literal["author", "observation"] = "author"
    evidence: str = ""
    valid_from_age_myr: float | None = None
    valid_until_age_myr: float = 0.0

    def __post_init__(self) -> None:
        if (
            not self.id
            or not isinstance(self.plates, (list, tuple))
            or len(self.plates) != 2
            or not all(self.plates)
        ):
            raise ValueError("polarity needs a source id and two plate ids")
        if self.plates[0] == self.plates[1] or self.down_going not in self.plates:
            raise ValueError("down_going must name one of two distinct plates")
        object.__setattr__(self, "plates", plate_pair(*self.plates))
        if self.source_kind not in ("author", "observation"):
            raise ValueError("polarity source_kind must be author or observation")
        if self.source_kind == "observation" and not self.evidence.strip():
            raise ValueError("observational polarity needs an evidence reference")
        end, start = self.valid_until_age_myr, self.valid_from_age_myr
        if not math.isfinite(end) or end < 0:
            raise ValueError("polarity ages must be finite and nonnegative")
        if start is None:
            if end != 0:
                raise ValueError("an untimed polarity describes only the present")
        elif not math.isfinite(start) or start < end or start == end > 0:
            raise ValueError("polarity valid_from_age_myr must be at least valid_until_age_myr")

    def applies_at(self, age_myr: float) -> bool:
        """Older endpoint included, younger endpoint excluded except at age zero."""
        if not math.isfinite(age_myr) or age_myr < 0:
            raise ValueError("query age must be finite and nonnegative")
        if self.valid_from_age_myr is None:
            return age_myr == 0
        return age_myr <= self.valid_from_age_myr and (
            age_myr > self.valid_until_age_myr or age_myr == self.valid_until_age_myr == 0
        )


def polarity_at_age(
    sources: Sequence[SubductionPolarity], age_myr: float = 0.0
) -> dict[tuple[str, str], SubductionPolarity]:
    """Resolve active source declarations, rejecting conflicting slab sides."""
    if not math.isfinite(age_myr) or age_myr < 0:
        raise ValueError("query age must be finite and nonnegative")
    resolved: dict[tuple[str, str], SubductionPolarity] = {}
    for source in sorted(sources, key=lambda s: s.id):
        if not source.applies_at(age_myr):
            continue
        previous = resolved.get(source.plates)
        if previous is not None and previous.down_going != source.down_going:
            raise ValueError(f"conflicting polarity sources {previous.id} and {source.id}")
        resolved.setdefault(source.plates, source)
    return resolved


def load_subduction_polarities(path: Path) -> list[SubductionPolarity]:
    """Read the additive ``subduction_polarities`` block in plate_history.yaml."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = [SubductionPolarity(**row) for row in data.get("subduction_polarities", [])]
    if len({s.id for s in sources}) != len(sources):
        raise ValueError("polarity source ids must be unique")
    # Active sets change at interval endpoints. Check the endpoints and the
    # open spans once, so a conflicting historical input fails during loading.
    epochs = sorted(
        {
            0.0,
            *[
                v
                for s in sources
                for v in (s.valid_from_age_myr, s.valid_until_age_myr)
                if v is not None
            ],
        }
    )
    for age in [*epochs, *[(a + b) / 2 for a, b in zip(epochs[:-1], epochs[1:], strict=True)]]:
        polarity_at_age(sources, age)
    return sources
