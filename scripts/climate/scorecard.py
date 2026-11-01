"""Climate engine scorecard: one table per world, for the acceptance criteria.

Implements the measurement side of the acceptance criteria in
``docs/design/pipelines/climate-validation.md`` §8.  Two tables:

* **Earth** (model branch against the observations imported into ``earth`` root):
  Köppen class and group agreement, land temperature RMSE for the June–August and
  December–February halves, seasonal precipitation pattern correlation, wet-season
  phase, and annual biases.  Every statistic is computed per continent and then
  averaged with equal weight, so a large continent cannot hide a small one's
  regression.  A truth swap reports what the same Köppen classifier gives with the
  observed temperature and the model's precipitation, and the other way round, which
  says which stage costs the most.
* **nacrea** (root parametric build against the GCM branch as a *reference*, not a
  truth): zonal temperature and precipitation, land Köppen group shares and seasonal
  amplitude, with the GCM's unreliable regions excluded.

Stage timings come from the world's ``build_profile.json`` when present.

Usage::

    uv run python scripts/climate/scorecard.py                 # both tables
    uv run python scripts/climate/scorecard.py --world earth
    uv run python scripts/climate/scorecard.py --json out.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from dreamulator.engine.climate_physics import koppen_classify
from dreamulator.engine.climate_seasonality import seasonal_precip_extremes
from dreamulator.import_solar_common import load_monthly_climate
from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path.cwd()
WORLDS = ROOT / "data" / "worlds"

#: Continents as longitude/latitude boxes, in the six-way split used by the
#: comparable implementations, so the equal-weight mean is comparable too.  A box
#: is (lat_min, lat_max, lon_min, lon_max); land cells outside every box (small
#: islands, Antarctica) are reported separately and do not enter the mean.
CONTINENTS: dict[str, tuple[float, float, float, float]] = {
    "North America": (15.0, 84.0, -170.0, -52.0),
    "South America": (-56.0, 15.0, -82.0, -34.0),
    "Europe": (35.0, 72.0, -11.0, 40.0),
    "Africa": (-35.0, 37.0, -18.0, 52.0),
    "Asia": (5.0, 78.0, 40.0, 180.0),
    "Australia": (-45.0, -10.0, 112.0, 154.0),
}

#: The GCM's own unreliable regions, excluded from the nacrea comparison
#: (climate-validation §8): its slab ocean has no currents, so the mid-to-high
#: latitude sea is cold-biased, and its ~310 km grid cannot resolve islands.
GCM_EXCLUDED_OCEAN_LAT = (45.0, 75.0)
GCM_GRID_KM = 310.0


@dataclass
class World:
    """One world's cell fields, loaded from a built mesh."""

    name: str
    lat: np.ndarray
    lon: np.ndarray
    area_km2: np.ndarray
    is_land: np.ndarray
    elevation_m: np.ndarray
    t_annual_c: np.ndarray
    p_annual_mm: np.ndarray
    koppen: np.ndarray
    pressure_anomaly_hpa: np.ndarray | None = None
    wind_east_m_s: np.ndarray | None = None
    wind_north_m_s: np.ndarray | None = None
    t_monthly_c: np.ndarray | None = None
    p_monthly_mm: np.ndarray | None = None
    neighbours: list[Sequence[int]] = field(default_factory=list)


def load_world(world: str, planet: str, branch: str | None, *, monthly: bool = True) -> World:
    """Load one world's (or branch's) built mesh and monthly climate."""
    base = WORLDS / world
    maps = (base / "branches" / branch / "maps" / planet) if branch else (base / "maps" / planet)
    path = find_mesh_file(maps)
    if path is None:
        raise FileNotFoundError(f"no mesh under {maps}; build the world first")
    mesh = load_cvt_mesh_model(path)
    cells = mesh.cells
    t_monthly = p_monthly = None
    if monthly and (maps / "climate_monthly.msgpack").exists():
        t_monthly, p_monthly, _ = load_monthly_climate(maps / "climate_monthly.msgpack")
    return World(
        name=f"{world}/{branch}" if branch else world,
        lat=np.array([c.lat for c in cells]),
        lon=np.array([c.lon for c in cells]),
        area_km2=np.array([c.area_km2 for c in cells]),
        is_land=np.array([(c.elevation or 0.0) > 0.0 for c in cells]),
        elevation_m=np.array([c.elevation or 0.0 for c in cells]),
        t_annual_c=np.array([_or_nan(c.temperature_C) for c in cells]),
        p_annual_mm=np.array([_or_nan(c.precipitation_mm) for c in cells]),
        koppen=np.array([(c.koppen_class or "") for c in cells], dtype=object),
        # The absolute field when the world carries one, else the older anomaly:
        # both are reduced to a departure from their own zonal mean before use.
        pressure_anomaly_hpa=np.array(
            [
                _or_nan(
                    c.slp_annual_hpa
                    if c.slp_annual_hpa is not None
                    else c.pressure_anomaly_annual_hpa
                )
                for c in cells
            ]
        ),
        wind_east_m_s=np.array([_or_nan(c.wind_east_m_s) for c in cells]),
        wind_north_m_s=np.array([_or_nan(c.wind_north_m_s) for c in cells]),
        t_monthly_c=t_monthly,
        p_monthly_mm=p_monthly,
        neighbours=[c.neighbors for c in cells],
    )


def _or_nan(value: float | None) -> float:
    return float("nan") if value is None else float(value)


#: Eastern-boundary upwelling coasts.  The alongshore wind there drives the cold
#: tongues that in turn drive the fog deserts, so each box reports its own
#: equatorward wind: (lat_min, lat_max, lon_min, lon_max, equatorward sign of the
#: northward component).
UPWELLING_COASTS: dict[str, tuple[float, float, float, float, float]] = {
    "Peru": (-20.0, -5.0, -82.0, -76.0, 1.0),
    "Benguela": (-28.0, -17.0, 10.0, 14.0, 1.0),
    "Canary": (20.0, 30.0, -19.0, -13.0, -1.0),
    "California": (32.0, 42.0, -128.0, -120.0, -1.0),
    "Somali": (0.0, 12.0, 48.0, 56.0, -1.0),
}

#: Below this speed a wind has no meaningful direction, so direction agreement
#: skips the cell instead of scoring noise.
CALM_M_S: float = 0.5

#: Ocean basins for the equal-weight pressure statistics, so a basin's share of
#: the sea does not set its share of the score: (lat_min, lat_max, lon_min,
#: lon_max).  A box whose lon_min exceeds lon_max crosses the date line.
OCEAN_BASINS: dict[str, tuple[float, float, float, float]] = {
    "N Atlantic": (5.0, 65.0, -80.0, 0.0),
    "S Atlantic": (-50.0, 5.0, -60.0, 20.0),
    "N Pacific": (5.0, 60.0, 120.0, -100.0),
    "S Pacific": (-50.0, 5.0, 160.0, -75.0),
    "Indian": (-45.0, 25.0, 40.0, 115.0),
    "Southern": (-70.0, -50.0, -180.0, 180.0),
}

#: Centres of action: the named pressure features whose place and strength the
#: wind structure depends on.  (lat_min, lat_max, lon_min, lon_max, sign) with
#: sign −1 for a low and +1 for a high; a box may cross the date line.
PRESSURE_CENTRES: dict[str, tuple[float, float, float, float, float]] = {
    "Icelandic low": (52.0, 70.0, -45.0, -5.0, -1.0),
    "Aleutian low": (42.0, 60.0, 160.0, -150.0, -1.0),
    "Siberian high": (42.0, 62.0, 80.0, 120.0, 1.0),
    "Azores high": (22.0, 42.0, -45.0, -15.0, 1.0),
    "Hawaii high": (22.0, 42.0, -160.0, -130.0, 1.0),
    "St Helena high": (-35.0, -15.0, -20.0, 5.0, 1.0),
    "Easter high": (-35.0, -15.0, -110.0, -85.0, 1.0),
    "Mascarene high": (-35.0, -15.0, 60.0, 95.0, 1.0),
}


def box_mask(
    lat: np.ndarray, lon: np.ndarray, box: tuple[float, float, float, float]
) -> np.ndarray:
    """Cells inside a lat/lon box; a box with lon_min > lon_max crosses the date line."""
    lat0, lat1, lon0, lon1 = box
    within_lat = (lat >= lat0) & (lat <= lat1)
    within_lon = (lon >= lon0) & (lon <= lon1) if lon0 <= lon1 else (lon >= lon0) | (lon <= lon1)
    return within_lat & within_lon


def zonal_departure(values: np.ndarray, lat: np.ndarray, step: float = 2.0) -> np.ndarray:
    """Departure of a field from its own zonal mean, band by band.

    Both pressure fields are reduced this way before they are compared: the
    engine models an anomaly whose reference is its own, and the observations
    are an absolute pressure, so only the longitudinal structure — which is what
    the centres of action and the wind's cross-isobar flow are about — is
    common ground.
    """
    out = np.full(values.shape, np.nan)
    edges = np.arange(-90.0, 90.0 + step, step)
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        band = (lat >= low) & (lat < high) & np.isfinite(values)
        if band.any():
            out[band] = values[band] - values[band].mean()
    return out


def wind_direction_match(
    model_east: np.ndarray,
    model_north: np.ndarray,
    obs_east: np.ndarray,
    obs_north: np.ndarray,
    mask: np.ndarray,
    within_deg: float = 45.0,
) -> float:
    """Share of cells whose wind direction is within ``within_deg`` of observed."""
    speed_model = np.hypot(model_east, model_north)
    speed_obs = np.hypot(obs_east, obs_north)
    use = mask & (speed_model > CALM_M_S) & (speed_obs > CALM_M_S)
    if not use.any():
        return float("nan")
    cosine = (model_east[use] * obs_east[use] + model_north[use] * obs_north[use]) / (
        speed_model[use] * speed_obs[use]
    )
    return float(np.mean(np.arccos(np.clip(cosine, -1.0, 1.0)) <= np.radians(within_deg)))


def observed_pressure(path: Path, count: int) -> np.ndarray:
    """Observed annual sea-level pressure per cell (hPa) from ``climate_obs.json``."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    out = np.full(count, np.nan)
    for key, value in data["cells"].items():
        index = int(key)
        if index < count:
            out[index] = float(value.get("slp_obs_hpa", np.nan))
    return out


def pressure_table(
    model: World, obs_slp: np.ndarray
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Pressure statistics: per region (equal weight) and per centre of action."""
    if model.pressure_anomaly_hpa is None:
        return {}, {}
    model_dep = zonal_departure(model.pressure_anomaly_hpa, model.lat)
    obs_dep = zonal_departure(obs_slp, model.lat)

    regions: dict[str, dict[str, float]] = {}
    for name, box in CONTINENTS.items():
        mask = model.is_land & box_mask(model.lat, model.lon, box)
        if mask.sum() >= 50:
            regions[name] = {
                "cells": int(mask.sum()),
                "rmse_hpa": _rmse(model_dep[mask], obs_dep[mask]),
                "pattern_corr": _correlation(model_dep[mask], obs_dep[mask]),
            }
    for name, box in OCEAN_BASINS.items():
        mask = ~model.is_land & box_mask(model.lat, model.lon, box)
        if mask.sum() >= 50:
            regions[name] = {
                "cells": int(mask.sum()),
                "rmse_hpa": _rmse(model_dep[mask], obs_dep[mask]),
                "pattern_corr": _correlation(model_dep[mask], obs_dep[mask]),
            }

    centres: dict[str, dict[str, float]] = {}
    for name, (lat0, lat1, lon0, lon1, sign) in PRESSURE_CENTRES.items():
        mask = box_mask(model.lat, model.lon, (lat0, lat1, lon0, lon1))
        usable = mask & np.isfinite(model_dep) & np.isfinite(obs_dep)
        if usable.sum() < 20:
            continue
        index = np.flatnonzero(usable)
        # Strength = the box's most extreme departure in the feature's own sense.
        model_extreme = index[np.argmax(sign * model_dep[usable])]
        obs_extreme = index[np.argmax(sign * obs_dep[usable])]
        centres[name] = {
            "model_hpa": float(sign * model_dep[model_extreme]),
            "obs_hpa": float(sign * obs_dep[obs_extreme]),
            "model_lat": float(model.lat[model_extreme]),
            "model_lon": float(model.lon[model_extreme]),
            "obs_lat": float(model.lat[obs_extreme]),
            "obs_lon": float(model.lon[obs_extreme]),
        }
    return regions, centres


def observed_wind(path: Path, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Observed annual surface wind components per cell from ``climate_obs.json``."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    east = np.full(count, np.nan)
    north = np.full(count, np.nan)
    for key, value in data["cells"].items():
        index = int(key)
        if index < count:
            east[index] = float(value.get("uwnd_obs_m_s", np.nan))
            north[index] = float(value.get("vwnd_obs_m_s", np.nan))
    return east, north


def continent_masks(world: World) -> dict[str, np.ndarray]:
    """Land masks per continent box, plus the land each box misses."""
    masks: dict[str, np.ndarray] = {}
    claimed = np.zeros(world.lat.size, dtype=bool)
    for name, (lat0, lat1, lon0, lon1) in CONTINENTS.items():
        mask = (
            world.is_land
            & (world.lat >= lat0)
            & (world.lat <= lat1)
            & (world.lon >= lon0)
            & (world.lon <= lon1)
        )
        masks[name] = mask
        claimed |= mask
    masks["(other land)"] = world.is_land & ~claimed
    return masks


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    good = np.isfinite(a) & np.isfinite(b)
    return float(np.sqrt(np.mean((a[good] - b[good]) ** 2))) if good.any() else float("nan")


def _bias(a: np.ndarray, b: np.ndarray) -> float:
    good = np.isfinite(a) & np.isfinite(b)
    return float(np.mean(a[good] - b[good])) if good.any() else float("nan")


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    good = np.isfinite(a) & np.isfinite(b)
    if good.sum() < 3:
        return float("nan")
    x, y = a[good], b[good]
    if x.std() == 0 or y.std() == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def half_year_means(monthly: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Summer-half and winter-half means, by hemisphere (months are Jan-first)."""
    jja = monthly[:, 5:8].mean(axis=1)
    djf = monthly[:, [11, 0, 1]].mean(axis=1)
    north = lat >= 0.0
    summer = np.where(north, jja, djf)
    winter = np.where(north, djf, jja)
    return summer, winter


def wet_season_phase_match(p_model: np.ndarray, p_obs: np.ndarray, mask: np.ndarray) -> float:
    """Share of cells whose wettest month falls within one month of the observed one."""
    if not mask.any():
        return float("nan")
    wet_model = p_model[mask].argmax(axis=1)
    wet_obs = p_obs[mask].argmax(axis=1)
    gap = np.abs(wet_model - wet_obs)
    gap = np.minimum(gap, 12 - gap)
    return float(np.mean(gap <= 1))


def koppen_from_monthly(
    t_monthly: np.ndarray, p_monthly: np.ndarray, is_land: np.ndarray
) -> np.ndarray:
    """Köppen codes from monthly temperature and precipitation (the engine's rules)."""
    p_dry_summer, p_wet_winter, p_dry_winter, p_wet_summer = seasonal_precip_extremes(
        t_monthly, p_monthly
    )
    order = np.argsort(t_monthly, axis=1)
    rows = np.arange(t_monthly.shape[0])[:, None]
    codes = koppen_classify(
        t_mean_c=t_monthly.mean(axis=1),
        t_cold_c=t_monthly.min(axis=1),
        t_hot_c=t_monthly.max(axis=1),
        p_annual_mm=p_monthly.sum(axis=1),
        p_dry_mm=p_monthly.min(axis=1),
        p_wet_mm=p_monthly.max(axis=1),
        p_warm_mm=p_monthly[rows, order[:, 6:]].sum(axis=1),
        p_cold_mm=p_monthly[rows, order[:, :6]].sum(axis=1),
        p_dry_summer_mm=p_dry_summer,
        p_wet_winter_mm=p_wet_winter,
        p_dry_winter_mm=p_dry_winter,
        p_wet_summer_mm=p_wet_summer,
        is_land=is_land,
        t_months_ge10=(t_monthly >= 10.0).sum(axis=1),
    )
    return np.array(codes, dtype=object)


def koppen_obs_codes(path: Path, count: int) -> np.ndarray:
    """Observed Köppen codes per cell from ``koppen_obs.json`` (Beck et al.)."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    codes = np.array([""] * count, dtype=object)
    for key, value in data["cells"].items():
        index = int(key)
        if index < count:
            codes[index] = value if isinstance(value, str) else value.get("koppen", "")
    return codes


def agreement(model: np.ndarray, obs: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    """Köppen class and major-group agreement over a mask (ignoring unlabelled cells)."""
    use = mask & (obs != "") & (model != "")
    if not use.any():
        return float("nan"), float("nan")
    same_class = np.mean([a == b for a, b in zip(model[use], obs[use], strict=True)])
    same_group = np.mean([a[:1] == b[:1] for a, b in zip(model[use], obs[use], strict=True)])
    return float(same_class), float(same_group)


def earth_table(branch: str) -> dict[str, Any]:
    """The Earth scorecard: per continent, equally weighted, plus the truth swap."""
    model = load_world("earth", "planet_earth", branch)
    obs_maps = WORLDS / "earth" / "maps" / "planet_earth"
    t_obs, p_obs, _ = load_monthly_climate(obs_maps / "climate_monthly.msgpack")
    if model.t_monthly_c is None or model.p_monthly_mm is None:
        raise FileNotFoundError(f"{model.name} has no monthly climate; build the branch first")
    if t_obs.shape != model.t_monthly_c.shape:
        raise ValueError(
            f"observation grid {t_obs.shape} does not match the model grid "
            f"{model.t_monthly_c.shape}; both must use the same mesh"
        )

    # Köppen references: Version 1 (Beck 2018) and, when it has been converted,
    # the 2023 release.  Both are reported; the first drives the truth swap.
    maps_dir = WORLDS / "earth" / "branches" / branch / "maps" / "planet_earth"
    references: dict[str, np.ndarray] = {
        "beck2018": koppen_obs_codes(maps_dir / "koppen_obs.json", model.lat.size)
    }
    if (maps_dir / "koppen_obs_beck2023.json").exists():
        references["beck2023"] = koppen_obs_codes(
            maps_dir / "koppen_obs_beck2023.json", model.lat.size
        )
    obs_codes = references["beck2018"]
    wind_obs_east, wind_obs_north = observed_wind(maps_dir / "climate_obs.json", model.lat.size)
    obs_slp = observed_pressure(maps_dir / "climate_obs.json", model.lat.size)
    pressure_regions, pressure_centres = pressure_table(model, obs_slp)
    t_summer_m, t_winter_m = half_year_means(model.t_monthly_c, model.lat)
    t_summer_o, t_winter_o = half_year_means(t_obs, model.lat)
    p_summer_m, p_winter_m = half_year_means(model.p_monthly_mm, model.lat)
    p_summer_o, p_winter_o = half_year_means(p_obs, model.lat)

    rows: dict[str, dict[str, float]] = {}
    for name, mask in continent_masks(model).items():
        if not mask.any():
            continue
        same_class, same_group = agreement(model.koppen, obs_codes, mask)
        other = {
            f"koppen_class_{key}": agreement(model.koppen, codes, mask)[0]
            for key, codes in references.items()
            if key != "beck2018"
        }
        rows[name] = {
            "cells": int(mask.sum()),
            "koppen_class": same_class,
            "koppen_group": same_group,
            **other,
            "t_summer_rmse_c": _rmse(t_summer_m[mask], t_summer_o[mask]),
            "t_winter_rmse_c": _rmse(t_winter_m[mask], t_winter_o[mask]),
            "p_summer_corr": _correlation(p_summer_m[mask], p_summer_o[mask]),
            "p_winter_corr": _correlation(p_winter_m[mask], p_winter_o[mask]),
            "wet_phase_match": wet_season_phase_match(model.p_monthly_mm, p_obs, mask),
            "wind_dir_match": wind_direction_match(
                model.wind_east_m_s,
                model.wind_north_m_s,
                wind_obs_east,
                wind_obs_north,
                mask,
            ),
            "t_bias_c": _bias(model.t_monthly_c.mean(axis=1)[mask], t_obs.mean(axis=1)[mask]),
            "p_bias_mm": _bias(model.p_monthly_mm.sum(axis=1)[mask], p_obs.sum(axis=1)[mask]),
        }
    counted = [name for name in CONTINENTS if name in rows]
    mean = {
        key: float(np.nanmean([rows[name][key] for name in counted]))
        for key in rows[counted[0]]
        if key != "cells"
    }

    # Truth swap: which stage costs the most (observed field substituted in).
    land = model.is_land
    swap_t = koppen_from_monthly(t_obs, model.p_monthly_mm, land)
    swap_p = koppen_from_monthly(model.t_monthly_c, p_obs, land)
    both = koppen_from_monthly(t_obs, p_obs, land)
    swap = {
        "model": agreement(model.koppen, obs_codes, land)[0],
        "observed_temperature": agreement(swap_t, obs_codes, land)[0],
        "observed_precipitation": agreement(swap_p, obs_codes, land)[0],
        "both_observed": agreement(both, obs_codes, land)[0],
    }
    # Eastern-boundary alongshore wind: the input coastal upwelling and the SST
    # convection gate depend on (the round proposal's precipitation entry).
    coasts: dict[str, dict[str, float]] = {}
    for name, (lat0, lat1, lon0, lon1, sign) in UPWELLING_COASTS.items():
        sea = (
            ~model.is_land
            & (model.lat >= lat0)
            & (model.lat <= lat1)
            & (model.lon >= lon0)
            & (model.lon <= lon1)
        )
        if not sea.any():
            continue
        coasts[name] = {
            "cells": int(sea.sum()),
            "model_equatorward_m_s": float(np.nanmean(sign * model.wind_north_m_s[sea])),
            "obs_equatorward_m_s": float(np.nanmean(sign * wind_obs_north[sea])),
            "model_zonal_speed_m_s": float(np.nanmean(np.abs(model.wind_east_m_s[sea]))),
            "obs_zonal_speed_m_s": float(np.nanmean(np.abs(wind_obs_east[sea]))),
            "dir_match": wind_direction_match(
                model.wind_east_m_s,
                model.wind_north_m_s,
                wind_obs_east,
                wind_obs_north,
                sea,
            ),
        }
    return {
        "world": model.name,
        "reference": "earth root observations (NCEP/GPCP monthly); Köppen: "
        + ", ".join(references),
        "continents": rows,
        "upwelling_coasts": coasts,
        "pressure_regions": pressure_regions,
        "pressure_centres": pressure_centres,
        "pressure_equal_weight": {
            key: float(np.nanmean([row[key] for row in pressure_regions.values()]))
            for key in ("rmse_hpa", "pattern_corr")
        }
        if pressure_regions
        else {},
        "equal_weight_mean": mean,
        "truth_swap_koppen_class": swap,
        "timings_s": stage_timings(WORLDS / "earth"),
    }


def landmass_area_km2(world: World) -> np.ndarray:
    """Area of the connected landmass each land cell belongs to (km²)."""
    size = np.zeros(world.lat.size)
    seen = np.zeros(world.lat.size, dtype=bool)
    for start in np.flatnonzero(world.is_land):
        if seen[start]:
            continue
        stack = [int(start)]
        seen[start] = True
        group = [int(start)]
        while stack:
            current = stack.pop()
            for other in world.neighbours[current]:
                if 0 <= other < world.is_land.size and world.is_land[other] and not seen[other]:
                    seen[other] = True
                    stack.append(int(other))
                    group.append(int(other))
        total = float(world.area_km2[group].sum())
        size[group] = total
    return size


def zonal_means(
    values: np.ndarray, lat: np.ndarray, mask: np.ndarray, step: float = 15.0
) -> dict[str, float]:
    """Area-unweighted means per latitude band, over a mask."""
    out: dict[str, float] = {}
    edges = np.arange(-90.0, 90.0 + step, step)
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        band = mask & (lat >= low) & (lat < high) & np.isfinite(values)
        if band.sum() >= 10:
            out[f"{low:+.0f}..{high:+.0f}"] = float(values[band].mean())
    return out


def nacrea_table(branch: str) -> dict[str, Any]:
    """The nacrea scorecard: root parametric build against the GCM branch."""
    model = load_world("nacrea", "satellite_nacrea", None)
    reference = load_world("nacrea", "satellite_nacrea", branch)
    if model.lat.size != reference.lat.size:
        raise ValueError("the root build and the GCM branch use different meshes")

    # Exclude what the GCM cannot be trusted on (climate-validation §8).
    low, high = GCM_EXCLUDED_OCEAN_LAT
    cold_sea = ~model.is_land & (np.abs(model.lat) >= low) & (np.abs(model.lat) <= high)
    small_island = model.is_land & (landmass_area_km2(model) < GCM_GRID_KM**2)
    usable = ~(cold_sea | small_island)
    land = usable & model.is_land

    amplitude_model = (
        model.t_monthly_c.max(axis=1) - model.t_monthly_c.min(axis=1)
        if model.t_monthly_c is not None
        else np.full(model.lat.size, np.nan)
    )
    amplitude_reference = (
        reference.t_monthly_c.max(axis=1) - reference.t_monthly_c.min(axis=1)
        if reference.t_monthly_c is not None
        else np.full(model.lat.size, np.nan)
    )
    groups: dict[str, dict[str, float]] = {}
    for label, codes in (("model", model.koppen), ("reference", reference.koppen)):
        area = model.area_km2[land]
        letters = np.array([code[:1] if code else "" for code in codes[land]], dtype=object)
        total = area.sum()
        groups[label] = {
            letter: float(area[letters == letter].sum() / total)
            for letter in ("A", "B", "C", "D", "E")
        }
    return {
        "world": model.name,
        "reference": f"nacrea/{branch} (a reference model, not a truth)",
        "excluded": {
            "cold_sea_cells": int(cold_sea.sum()),
            "small_island_cells": int(small_island.sum()),
            "usable_share": float(usable.mean()),
        },
        "zonal_temperature_c": {
            "model": zonal_means(model.t_annual_c, model.lat, usable),
            "reference": zonal_means(reference.t_annual_c, model.lat, usable),
        },
        "zonal_precipitation_mm": {
            "model": zonal_means(model.p_annual_mm, model.lat, usable),
            "reference": zonal_means(reference.p_annual_mm, model.lat, usable),
        },
        "land_seasonal_amplitude_k": {
            "model": zonal_means(amplitude_model, model.lat, land),
            "reference": zonal_means(amplitude_reference, model.lat, land),
        },
        "land_koppen_group_share": groups,
        "timings_s": stage_timings(WORLDS / "nacrea"),
    }


def stage_timings(world_dir: Path) -> dict[str, float]:
    """Stage wall times from the world's ``build_profile.json`` (empty when absent)."""
    path = world_dir / "build_profile.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    stages = profile.get("stages") or profile.get("phases") or {}
    if isinstance(stages, dict):
        return {str(k): float(v) for k, v in stages.items() if isinstance(v, int | float)}
    return {
        str(entry.get("name")): float(entry.get("seconds", entry.get("wall_s", 0.0)))
        for entry in stages
        if isinstance(entry, dict)
    }


def _show_earth(table: dict[str, Any]) -> None:
    print(f"\n=== Earth: {table['world']} against {table['reference']}")
    extra = [key for key in next(iter(table["continents"].values())) if "koppen_class_" in key]
    header = (
        f"{'continent':<15}{'cells':>7}{'Köppen':>9}{'group':>8}"
        f"{'T sum':>8}{'T win':>8}{'P sum':>8}{'P win':>8}{'wet φ':>8}"
        f"{'ΔT':>7}{'ΔP':>8}{'wind':>7}"
        + "".join(f"{key.removeprefix('koppen_class_'):>10}" for key in extra)
    )
    print(header)
    for name, row in table["continents"].items():
        print(
            f"{name:<15}{row['cells']:>7}{row['koppen_class'] * 100:>8.1f}%"
            f"{row['koppen_group'] * 100:>7.1f}%{row['t_summer_rmse_c']:>8.2f}"
            f"{row['t_winter_rmse_c']:>8.2f}{row['p_summer_corr']:>8.3f}"
            f"{row['p_winter_corr']:>8.3f}{row['wet_phase_match'] * 100:>7.1f}%"
            f"{row['t_bias_c']:>7.2f}{row['p_bias_mm']:>8.0f}{row['wind_dir_match'] * 100:>6.1f}%"
            + "".join(f"{row[key] * 100:>9.1f}%" for key in extra)
        )
    mean = table["equal_weight_mean"]
    print(
        f"{'equal weight':<15}{'':>7}{mean['koppen_class'] * 100:>8.1f}%"
        f"{mean['koppen_group'] * 100:>7.1f}%{mean['t_summer_rmse_c']:>8.2f}"
        f"{mean['t_winter_rmse_c']:>8.2f}{mean['p_summer_corr']:>8.3f}"
        f"{mean['p_winter_corr']:>8.3f}{mean['wet_phase_match'] * 100:>7.1f}%"
        f"{mean['t_bias_c']:>7.2f}{mean['p_bias_mm']:>8.0f}{mean['wind_dir_match'] * 100:>6.1f}%"
        + "".join(f"{mean[key] * 100:>9.1f}%" for key in extra)
    )
    print(
        "  (T in K RMSE for the summer / winter half; P as pattern correlation; ΔT, ΔP annual bias)"
    )
    regions = table.get("pressure_regions") or {}
    if regions:
        mean = table["pressure_equal_weight"]
        print("  sea-level pressure, departure from the zonal mean (model vs NCEP)")
        print(f"    {'region':<14}{'cells':>6}{'RMSE hPa':>10}{'pattern r':>11}")
        for name, row in regions.items():
            print(
                f"    {name:<14}{row['cells']:>6}{row['rmse_hpa']:>10.2f}"
                f"{row['pattern_corr']:>11.3f}"
            )
        print(
            f"    {'equal weight':<14}{'':>6}{mean['rmse_hpa']:>10.2f}{mean['pattern_corr']:>11.3f}"
        )
    centres = table.get("pressure_centres") or {}
    if centres:
        print("  centres of action: strength (hPa from the zonal mean) and position")
        print(f"    {'centre':<16}{'model':>8}{'obs':>8}{'model lat/lon':>18}{'obs lat/lon':>18}")
        for name, row in centres.items():
            print(
                f"    {name:<16}{row['model_hpa']:>8.1f}{row['obs_hpa']:>8.1f}"
                f"{row['model_lat']:>9.0f}{row['model_lon']:>9.0f}"
                f"{row['obs_lat']:>9.0f}{row['obs_lon']:>9.0f}"
            )
    coasts = table.get("upwelling_coasts") or {}
    if coasts:
        print("  eastern-boundary alongshore wind (equatorward, m/s) — drives coastal upwelling")
        print(f"    {'coast':<12}{'cells':>6}{'model':>8}{'obs':>8}{'dir<45°':>9}")
        for name, row in coasts.items():
            print(
                f"    {name:<12}{row['cells']:>6}{row['model_equatorward_m_s']:>8.2f}"
                f"{row['obs_equatorward_m_s']:>8.2f}{row['dir_match'] * 100:>8.1f}%"
            )
    swap = table["truth_swap_koppen_class"]
    print("  truth swap, Köppen class on land:")
    for key, value in swap.items():
        print(f"    {key:<24}{value * 100:5.1f}%")


def _show_nacrea(table: dict[str, Any]) -> None:
    print(f"\n=== nacrea: {table['world']} against {table['reference']}")
    excluded = table["excluded"]
    print(
        f"  excluded {excluded['cold_sea_cells']} mid-latitude sea cells and "
        f"{excluded['small_island_cells']} small-island cells; "
        f"{excluded['usable_share'] * 100:.1f}% of cells usable"
    )
    for title, key in (
        ("zonal temperature (°C)", "zonal_temperature_c"),
        ("zonal precipitation (mm/yr)", "zonal_precipitation_mm"),
        ("land seasonal amplitude (K)", "land_seasonal_amplitude_k"),
    ):
        block = table[key]
        print(f"  {title}")
        for band in block["model"]:
            model = block["model"][band]
            ref = block["reference"].get(band, float("nan"))
            print(
                f"    {band:<12}model {model:9.1f}   reference {ref:9.1f}   Δ {model - ref:+9.1f}"
            )
    groups = table["land_koppen_group_share"]
    print("  land Köppen group share")
    for letter in ("A", "B", "C", "D", "E"):
        print(
            f"    {letter}  model {groups['model'][letter] * 100:5.1f}%   "
            f"reference {groups['reference'][letter] * 100:5.1f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--world", choices=["earth", "nacrea", "both"], default="both", help="which table to print"
    )
    parser.add_argument("--earth-branch", default="climate-dev", help="Earth model branch")
    parser.add_argument("--nacrea-branch", default="gcm-t42-712", help="nacrea reference branch")
    parser.add_argument("--json", type=Path, help="also write the tables to this JSON file")
    args = parser.parse_args()

    out: dict[str, Any] = {}
    if args.world in ("earth", "both"):
        out["earth"] = earth_table(args.earth_branch)
        _show_earth(out["earth"])
    if args.world in ("nacrea", "both"):
        out["nacrea"] = nacrea_table(args.nacrea_branch)
        _show_nacrea(out["nacrea"])
    if args.json:
        args.json.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
