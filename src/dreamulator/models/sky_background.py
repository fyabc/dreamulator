"""Sky-background models — the authored "universe setting" around a system.

The background sky (neighbour stars, deep-sky objects, the galactic band and
transient-event hooks) is fixed on the celestial sphere: directions are unit
vectors in the catalog's ecliptic frame and never propagate with time (proper
motions are mas/yr — far below a pixel on world timescales).  Planetarium
software keeps exactly this split: a static direction+magnitude catalogue
that the renderer rotates into the observer frame (Stellarium's star/DSO
catalogues), separate from the ephemeris of system bodies.

Two consumers beyond the sky view are designed for from the start:
`transient_events` feeds the ecology layer (rare supernova / GRB radiation
forcing) and the star ids feed civilization-layer sky cultures (constellation
lines reference ids, never copy positions — the Stellarium sky-culture model),
so authored positions can move in this file without breaking either layer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DeepSkyType(StrEnum):
    """Visual/physical class of a deep-sky object (sprite family + ecology hooks)."""

    NEBULA = "nebula"
    CLUSTER = "cluster"
    GALAXY = "galaxy"
    REMNANT = "remnant"  # supernova remnant — the ecology hook's quiet cousin


class TransientEventType(StrEnum):
    """Rare high-energy events the ecology layer samples from."""

    SUPERNOVA = "supernova"
    GRB = "grb"


class StarVariability(BaseModel):
    """Variable-star classification (GCVS-style) — a narrative anchor, not a series.

    The sky view renders the star's baseline magnitude; the variability record
    feeds civilization-layer lore (an omens calendar around an erupting arrow
    tip, say).  ``magnitude`` on the star is the quiescent/mean level.
    """

    type: str = Field(description="GCVS-style type, e.g. 'gamma_cassiopeiae'")
    magnitude_range: tuple[float, float] | None = Field(
        default=None,
        description="Numerical (min, max) the brightness stays between, e.g. (-1.3, -0.3)",
    )
    period_days: float | None = Field(
        default=None, gt=0, description="Pulsation/eruption cycle; None = irregular"
    )

    @model_validator(mode="after")
    def _check_range(self) -> StarVariability:
        if self.magnitude_range is not None and self.magnitude_range[0] > self.magnitude_range[1]:
            raise ValueError("magnitude_range must be numerical (min, max), got reversed bounds")
        return self


class BackgroundStar(BaseModel):
    """A hand-placed neighbour star.

    Hybrid magnitude input (the stellar.yaml precedent): give the apparent
    magnitude directly, or luminosity + distance and the engine derives the
    (bolometric-approximate) apparent magnitude.
    """

    id: str = Field(description="Stable identifier, e.g. 'star_neighbor_vega_like'")
    name: str | None = Field(
        default=None, description="Display name (sky cultures reference ids, not names)"
    )
    ecliptic_lon_deg: float = Field(
        ge=0.0, lt=360.0, description="Ecliptic longitude in the catalog frame"
    )
    ecliptic_lat_deg: float = Field(
        ge=-90.0, le=90.0, description="Ecliptic latitude in the catalog frame"
    )
    magnitude: float | None = Field(
        default=None, description="Baseline apparent magnitude as seen from the system"
    )
    luminosity_sol: float | None = Field(
        default=None, gt=0, description="Bolometric luminosity in L_sun (alternative input)"
    )
    distance_pc: float | None = Field(
        default=None, gt=0, description="Distance in parsec (with luminosity_sol)"
    )
    temperature_k: float = Field(
        default=5800.0, gt=0, description="Effective temperature — the marker colour"
    )
    variability: StarVariability | None = Field(
        default=None, description="Variable-star classification (lore anchor)"
    )

    @model_validator(mode="after")
    def _check_magnitude_inputs(self) -> BackgroundStar:
        if self.magnitude is None and (self.luminosity_sol is None or self.distance_pc is None):
            raise ValueError(
                f"background star {self.id!r}: provide magnitude, or luminosity_sol + distance_pc"
            )
        return self


class DeepSkyObject(BaseModel):
    """A deep-sky object: direction + type + angular size + magnitude."""

    id: str
    name: str | None = None
    type: DeepSkyType
    ecliptic_lon_deg: float = Field(ge=0.0, lt=360.0)
    ecliptic_lat_deg: float = Field(ge=-90.0, le=90.0)
    angular_size_deg: float = Field(
        default=0.5, gt=0, description="Long-axis angular size on the sky"
    )
    magnitude: float = Field(default=6.0, description="Integrated apparent magnitude")


class GalacticBand(BaseModel):
    """The procedural Milky-Way analogue: a great-circle band, not a texture.

    The band plane is given by its pole in the catalog frame; the renderer
    draws a soft band of `width_deg` around the corresponding great circle.
    """

    pole_lon_deg: float = Field(ge=0.0, lt=360.0)
    pole_lat_deg: float = Field(ge=-90.0, le=90.0)
    width_deg: float = Field(default=12.0, gt=0, le=60.0)
    brightness: float = Field(default=0.35, gt=0, le=1.0, description="Peak band opacity scale")


class TransientEvent(BaseModel):
    """A rare high-energy event hook (ecology layer consumes; the sky view
    only marks its direction when the epoch window contains the instant)."""

    id: str
    type: TransientEventType
    ecliptic_lon_deg: float = Field(ge=0.0, lt=360.0)
    ecliptic_lat_deg: float = Field(ge=-90.0, le=90.0)
    epoch_window_days: tuple[float, float] | None = Field(
        default=None,
        description="Inclusive [start, end] window in epoch days; None = authored later",
    )
    peak_magnitude: float | None = Field(default=None, description="Apparent magnitude at peak")
    rate_per_myr: float | None = Field(
        default=None, gt=0, description="Ecology-layer sampling rate"
    )


class WanderingObject(BaseModel):
    """A passing object that is far away now (a flyby star, say).

    Direction + distance are the CURRENT state; the encounter metadata
    records the close pass.  The sky view does not render these (naked-eye
    invisible) — this is canon data for lore and the future forensic-astronomy
    thread (long-period comet radiants converging on the incoming direction).
    """

    id: str
    name: str | None = None
    object_type: str = Field(description="Free-form classification, e.g. 'm_dwarf_binary'")
    ecliptic_lon_deg: float = Field(ge=0.0, lt=360.0)
    ecliptic_lat_deg: float = Field(ge=-90.0, le=90.0)
    distance_pc: float = Field(gt=0, description="Current distance from the system")
    magnitude: float | None = Field(default=None, description="Current combined apparent magnitude")
    close_approach_au: float | None = Field(default=None, gt=0)
    encounter_age_myr: float | None = Field(
        default=None, description="Millions of years since perihelion"
    )


class StarfieldSpec(BaseModel):
    """The seeded procedural faint-star field that fills the naked-eye sky.

    Deterministic by construction (same seed + count + limit = same stars),
    so reproducibility holds and authors tune density, not positions.
    """

    seed: int = Field(default=0, description="RNG seed for direction/magnitude/temperature draws")
    count: int = Field(default=900, ge=0, le=20000, description="Number of procedural stars")
    magnitude_limit: float = Field(
        default=6.5, description="Faint end of the generated distribution"
    )


class SkyBackgroundInput(BaseModel):
    """`layers/astronomy/input/sky_background.yaml` — the universe setting."""

    frame: Literal["ecliptic"] = Field(
        default="ecliptic",
        description="Directions are ecliptic lon/lat in the catalog frame (the orbits: frame)",
    )
    starfield: StarfieldSpec = Field(default_factory=StarfieldSpec)
    stars: list[BackgroundStar] = Field(default_factory=list)
    deep_sky: list[DeepSkyObject] = Field(default_factory=list)
    galactic_band: GalacticBand | None = None
    transient_events: list[TransientEvent] = Field(default_factory=list)
    wandering_objects: list[WanderingObject] = Field(default_factory=list)


class BackgroundStarDerived(BaseModel):
    """A renderable star: direction as a unit vector + resolved magnitude."""

    id: str
    name: str | None = None
    magnitude: float
    temperature_k: float
    unit: tuple[float, float, float]
    source: Literal["authored", "starfield"]
    variability: StarVariability | None = None


class DeepSkyObjectDerived(BaseModel):
    id: str
    name: str | None = None
    type: DeepSkyType
    magnitude: float
    angular_size_deg: float
    unit: tuple[float, float, float]


class GalacticBandDerived(BaseModel):
    pole_unit: tuple[float, float, float]
    width_deg: float
    brightness: float


class TransientEventDerived(BaseModel):
    id: str
    type: TransientEventType
    unit: tuple[float, float, float]
    epoch_window_days: tuple[float, float] | None = None
    peak_magnitude: float | None = None
    rate_per_myr: float | None = None


class WanderingObjectDerived(BaseModel):
    id: str
    name: str | None = None
    object_type: str
    unit: tuple[float, float, float]
    distance_pc: float
    magnitude: float | None = None
    close_approach_au: float | None = None
    encounter_age_myr: float | None = None


class SkyBackgroundDerived(BaseModel):
    """`layers/astronomy/derived/sky_background.yaml` — what the sky view reads."""

    frame: Literal["ecliptic"] = "ecliptic"
    starfield: StarfieldSpec = Field(default_factory=StarfieldSpec)
    stars: list[BackgroundStarDerived] = Field(default_factory=list)
    deep_sky: list[DeepSkyObjectDerived] = Field(default_factory=list)
    galactic_band: GalacticBandDerived | None = None
    transient_events: list[TransientEventDerived] = Field(default_factory=list)
    wandering_objects: list[WanderingObjectDerived] = Field(default_factory=list)
