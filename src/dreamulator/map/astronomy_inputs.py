"""Orbit parameters of a built climate and the monthly top-of-atmosphere insolation they give.

Consumers outside the climate engine (the canvas S1 and the region pack) need
the same monthly insolation the climate engine used.  The climate build
records the orbit in ``climate_metadata.json``; this module reads it back and
evaluates the engine's own ``monthly_insolation``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


def load_astronomy(map_dir: Path) -> dict[str, Any] | None:
    """Insolation parameters from a map's ``climate_metadata.json`` (None when absent).

    ``perihelion_day`` is missing from climate builds that predate it; the
    season phase then defaults to perihelion at the vernal equinox, which moves
    monthly insolation on eccentric orbits but barely the annual sums.
    """
    path = map_dir / "climate_metadata.json"
    if not path.exists():
        return None
    meta = json.loads(path.read_text(encoding="utf-8"))
    keys = (
        "stellar_luminosity_sol",
        "orbital_distance_au",
        "orbital_period_days",
        "axial_tilt_deg",
    )
    if any(meta.get(k) is None for k in keys):
        return None
    out: dict[str, Any] = {k: float(meta[k]) for k in keys}
    out["eccentricity"] = float(meta.get("eccentricity") or 0.0)
    if meta.get("perihelion_day") is None:
        out["perihelion_day"] = 0.0
        out["perihelion_day_assumed"] = True
    else:
        out["perihelion_day"] = float(meta["perihelion_day"])
    return out


def solar_constant_w_m2(astronomy: dict[str, Any]) -> float:
    """Flux at the planet's mean distance, the climate engine's own scaling."""
    from dreamulator.engine.climate_physics import SOLAR_CONSTANT

    return float(
        SOLAR_CONSTANT * astronomy["stellar_luminosity_sol"] / astronomy["orbital_distance_au"] ** 2
    )


def monthly_toa_insolation(lat_deg: np.ndarray, astronomy: dict[str, Any]) -> np.ndarray:
    """Monthly-mean top-of-atmosphere insolation (W/m²), shape (N, 12)."""
    from dreamulator.engine.climate_seasonality import monthly_insolation

    return np.asarray(
        monthly_insolation(
            np.radians(np.asarray(lat_deg, dtype=np.float64).reshape(-1)),
            astronomy["axial_tilt_deg"],
            solar_constant_w_m2(astronomy),
            astronomy["orbital_period_days"],
            astronomy["eccentricity"],
            astronomy["perihelion_day"],
        )
    )
