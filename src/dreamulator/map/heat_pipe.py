"""Heat-pipe volcanic provinces of a tidally heated body (technical debt 44, phase C).

Design: ``docs/design/proposals/island-catalog.md`` §1.4 and §3.2; the heat budget of the
hybrid heat-pipe and plate regime is nacrea design-note 0017.  This module holds the pure
parts: the tidal heating pattern, the province partition, the heat-pipe magma rate and the
timeline of tidal heat flow.  ``island_catalog`` builds the volcanoes from them.

Heating pattern.  With a small eccentricity the obliquity tide dominates the heating (total
power ∝ 21/2·e² + 3/2·sin²ψ, Beuthe 2013 eq. 42).  For a synchronous rotator its potential is
∝ x·y, with x towards the primary and y along the spin axis.  Dissipation in a thin soft layer
(a partially molten asthenosphere above a stiffer mantle, the natural seat of heat-pipe melt)
follows Beuthe's pattern B, the radial–tangential shear term; from the degree 0, 2 and 4 parts
of |x·y|² (Beuthe 2013 eq. 36) it is, normalised to a global mean of 1,

    Ĥ = 2.5·(x² + y²) − 10·x²·y²,

with maxima of 2.5 at the sub- and anti-primary points and at both poles, and zeros on the
equator 90° from the primary.  The degree-3 tide (≈ R/a, about 1% for nacrea) is neglected.

Heat-pipe magma.  Plates carry the conductive share q_plate of the heat (half-space cooling of
the authored plate speed, ``tidal_physics.plate_heat_flux_w_m2``); the local tidal heat beyond
it leaves as magma, m = max(q(t)·a·Ĥ − q_plate, 0) / (ρ·L) with ρ = 3000 kg/m³ and L = 2 MJ/kg
of latent plus sensible heat (0017 §4): 1 W/m² is about 5.26 km of rock per Myr.  ``a`` is the
activity of the province in that tidal phase.

Timeline.  The world gives the recent global heat flow (``recent``, a canonical trajectory) and
the ensemble statistics of quiet stretches and tidal phases for the older part of the window;
older segments are drawn with a seeded generator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from pathlib import Path

PROVINCES: tuple[str, ...] = ("sub", "anti", "north", "south")

#: Rock produced per unit heat-pipe flux: 1 W/m² over a year, divided by ρ·L (0017 §4).
_MAGMA_DENSITY = 3000.0
_HEAT_PER_KG = 2.0e6
KM_PER_MY_PER_W_M2 = 3.15576e13 / (_MAGMA_DENSITY * _HEAT_PER_KG) / 1000.0


class RecentHeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_kyr: float = Field(gt=0.0)
    heat_flow_w_m2: list[float] = Field(min_length=1)


class EnsembleHeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiet_median_kyr: float = Field(gt=0.0)
    quiet_sigma_ln: float = Field(ge=0.0)
    quiet_heat_flow_w_m2: tuple[float, float]
    active_median_kyr: float = Field(gt=0.0)
    active_sigma_ln: float = Field(ge=0.0)
    active_max_kyr: float = Field(gt=0.0)
    active_heat_flow_w_m2: tuple[float, float]


class TidalHeatHistory(BaseModel):
    """``layers/geological/input/tidal_heat_history.yaml``."""

    model_config = ConfigDict(extra="forbid")

    recent: RecentHeat
    ensemble: EnsembleHeat
    active_threshold_w_m2: float = Field(gt=0.0)
    province_activity_sigma_ln: float = Field(default=0.0, ge=0.0)
    latest_phase_activity: dict[str, float] = Field(default_factory=dict)

    @field_validator("latest_phase_activity")
    @classmethod
    def _known_provinces(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - set(PROVINCES)
        if unknown:
            raise ValueError(f"unknown provinces {sorted(unknown)}; expected {PROVINCES}")
        return v


def load_tidal_heat_history(path: Path | None) -> TidalHeatHistory | None:
    """Read the world's tidal heat history (None when the file is absent)."""
    import yaml

    if path is None or not path.exists():
        return None
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return TidalHeatHistory.model_validate(data)


def heating_pattern(xyz: np.ndarray) -> np.ndarray:
    """Obliquity-tide heating of a thin soft layer, Beuthe's pattern B, global mean 1.

    ``xyz`` are unit vectors in the map frame (x towards the primary, y along the spin axis).
    """
    x, y = xyz[..., 0], xyz[..., 1]
    out: np.ndarray = 2.5 * (x * x + y * y) - 10.0 * x * x * y * y
    return out


def province_index(xyz: np.ndarray) -> np.ndarray:
    """Index into ``PROVINCES`` of the heating maximum each point belongs to."""
    x, y = xyz[..., 0], xyz[..., 1]
    out: np.ndarray = np.where(
        np.abs(x) >= np.abs(y), np.where(x >= 0.0, 0, 1), np.where(y >= 0.0, 2, 3)
    )
    return out


@dataclass(frozen=True)
class HeatSegment:
    """A stretch of the timeline: quiet or a tidal phase, in Myr before present."""

    young_myr: float
    old_myr: float
    heat_w_m2: float
    active: bool
    activity: tuple[float, float, float, float]  # per province, in ``PROVINCES`` order

    @property
    def mid_myr(self) -> float:
        return 0.5 * (self.young_myr + self.old_myr)


def heat_segments(
    hist: TidalHeatHistory, window_myr: float, rng: np.random.Generator
) -> list[HeatSegment]:
    """Quiet stretches and tidal phases from the present back to ``window_myr``, newest first."""
    thr = hist.active_threshold_w_m2
    step = hist.recent.step_kyr / 1000.0
    raw: list[tuple[float, float, float, bool]] = []  # young, old, heat·duration, active
    for k, q in enumerate(hist.recent.heat_flow_w_m2):
        young, old = max((k - 0.5) * step, 0.0), (k + 0.5) * step
        if young >= window_myr:
            break
        old = min(old, window_myr)
        act = q > thr
        if raw and raw[-1][3] == act:
            y0, _, hd, _ = raw[-1]
            raw[-1] = (y0, old, hd + q * (old - young), act)
        else:
            raw.append((young, old, q * (old - young), act))
    t = raw[-1][1] if raw else 0.0
    ens = hist.ensemble
    active = bool(raw[-1][3]) if raw else True
    while t < window_myr:
        active = not active
        if active:
            dur = ens.active_median_kyr * math.exp(ens.active_sigma_ln * rng.standard_normal())
            dur = min(dur, ens.active_max_kyr)
            q = float(rng.uniform(*ens.active_heat_flow_w_m2))
        else:
            dur = ens.quiet_median_kyr * math.exp(ens.quiet_sigma_ln * rng.standard_normal())
            q = float(rng.uniform(*ens.quiet_heat_flow_w_m2))
        old = min(t + dur / 1000.0, window_myr)
        raw.append((t, old, q * (old - t), active))
        t = old
    out: list[HeatSegment] = []
    latest_seen = False
    s = hist.province_activity_sigma_ln
    for young, old, hd, act in raw:
        ones = (1.0, 1.0, 1.0, 1.0)
        activity = ones
        if act:
            if not latest_seen:
                latest = hist.latest_phase_activity
                activity = tuple(float(latest.get(p, 1.0)) for p in PROVINCES)  # type: ignore[assignment]
                latest_seen = True
            elif s > 0.0:
                draws = np.exp(s * rng.standard_normal(4) - 0.5 * s * s)
                activity = tuple(float(a) for a in draws)  # type: ignore[assignment]
        out.append(HeatSegment(young, old, hd / max(old - young, 1e-12), act, activity))
    return out


def heat_pipe_rate_km_my(
    xyz: np.ndarray, heat_w_m2: float, activity: np.ndarray, plate_heat_w_m2: float
) -> np.ndarray:
    """Heat-pipe magma production (km of rock per Myr) at the given points."""
    a = activity[province_index(xyz)]
    excess = heat_w_m2 * a * heating_pattern(xyz) - plate_heat_w_m2
    out: np.ndarray = np.maximum(excess, 0.0) * KM_PER_MY_PER_W_M2
    return out
