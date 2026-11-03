"""Sky-culture models — the civilization layer's authored star lore.

The counterpart of the astronomy layer's sky background: cultures name and
connect background objects strictly by their stable ids (the Stellarium
sky-culture model).  No positions are ever copied into this file, so an
authored star can move in ``sky_background.yaml`` without breaking any
culture, and the future myth-strata layer consumes asterism ids the same way.

Two structural guarantees live in the validators (empty figures, self-edges,
duplicate culture/asterism ids); the cross-file guarantee — every referenced
id exists among the astronomy layer's authored stars and deep-sky objects —
needs the sky-background catalogue, so it is checked by the engine
(``engine/sky_culture.py``) at build time and fails the build when violated.
Procedural starfield ids are deliberately not referenceable: their numbering
shifts with the starfield spec, so a stale reference would silently point at
a different star instead of failing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class Asterism(BaseModel):
    """One constellation figure: a name, its lore, and the edges to draw.

    ``lines`` is an unordered-pair edge list (Stellarium's constellation
    format), so branched figures work; the renderer samples each edge along
    the great circle between its two endpoints.
    """

    id: str = Field(description="Stable identifier, e.g. 'asterism_arrow'")
    name: str = Field(description="The asterism's name in this culture")
    meaning: str | None = Field(
        default=None, description="Lore / mnemonic text shown in the inspector"
    )
    lines: list[tuple[str, str]] = Field(
        description="Edges as pairs of background-object ids (authored star or deep-sky)"
    )

    @model_validator(mode="after")
    def _check_figure(self) -> Asterism:
        if not self.lines:
            raise ValueError(f"asterism {self.id!r}: lines must contain at least one edge")
        for a, b in self.lines:
            if a == b:
                raise ValueError(f"asterism {self.id!r}: self-edge ({a!r}, {a!r}) is not a line")
        return self


class SkyCulture(BaseModel):
    """One culture's view of the sky: asterisms plus per-star names."""

    id: str = Field(description="Stable identifier, e.g. 'culture_xiangxing'")
    name: str = Field(description="Display name of the culture")
    description: str | None = Field(
        default=None, description="Short note on the culture's relation to the sky"
    )
    star_names: dict[str, str] = Field(
        default_factory=dict,
        description="Background-star id -> this culture's proper name for it",
    )
    asterisms: list[Asterism] = Field(default_factory=list)


class SkyCultureInput(BaseModel):
    """`layers/civilization/input/sky_culture.yaml` — authored star lore."""

    cultures: list[SkyCulture] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> SkyCultureInput:
        seen_cultures: set[str] = set()
        seen_asterisms: set[str] = set()
        for culture in self.cultures:
            if culture.id in seen_cultures:
                raise ValueError(f"duplicate sky-culture id {culture.id!r}")
            seen_cultures.add(culture.id)
            for asterism in culture.asterisms:
                if asterism.id in seen_asterisms:
                    raise ValueError(
                        f"asterism id {asterism.id!r} appears in more than one culture"
                    )
                seen_asterisms.add(asterism.id)
        return self


class SkyCultureDerived(BaseModel):
    """`layers/civilization/derived/sky_culture.yaml` — validated, edges deduplicated.

    Always written by the civilization engine (empty ``cultures`` when the
    world has no authored sky culture), so consumers can fetch unconditionally
    after a build — the astronomy engine's sky_background posture.
    """

    cultures: list[SkyCulture] = Field(default_factory=list)
