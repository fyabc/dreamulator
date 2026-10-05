"""Shared import machinery for Solar-System reference bodies (UCC-01 4d).

Mars / Moon / Venus / Titan are **bodies inside the real-world reference-anchor
world** (``SOLAR_WORLD = "earth"`` — the name is historical; the world is the
real-data anchor, never built), not separate pseudo-worlds.  External data
(GCM climatologies, or observation-grade products for the Moon) is sampled onto
a per-body CVT mesh under ``maps/<planet_id>/``; IDs follow the root's
stellar.yaml conventions (``satellite_*`` for moons).  Epistemic status differs
per body — GCM climatology is ucc-review §6.2 **L4** (cross-world pressure
test, NOT error-free truth), Diviner is observation-grade *surface*
temperature — so every importer must pass an explicit ``data_source`` +
``provenance`` that lands inside the exported files.

Pipeline per body (mirrors the earth importers minus plates/water mask/
currents):

1. :func:`register_solar_planet` — validate planet_id in world.yaml + maps dir
2. :func:`build_mesh_from_dem` — CVT mesh + DEM sampling + elevation.png + map.yaml
3. :func:`write_climate_monthly` — quantized 12-bin climatology msgpack
4. :func:`apply_climate_to_mesh` — annual T/P into mesh cell fields (frontend)
5. :func:`write_climate_secondary` — temperature/precipitation PNG + metadata
6. :func:`write_ucc_yearly` — UCC descriptors + current-profile classification

Time contract (knowledge doc §2): bins carry durations.  Earth/Nacrea use 12
equal *reference months* (365.25/12 d); Mars bins are Martian months
(687/12 d ≈ 57.25 Earth-d), Titan's would be ~2.46 Earth-years each.  The
monthly msgpack and the yearly UCC file therefore carry an explicit
``bin_days`` (+ derived ``window_days``) so ``p_total`` semantics travel with
the data.  AI/deficit are window invariants and stay directly comparable.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import msgpack
import numpy as np

from .result_contract import REFERENCE_MONTH_DAYS, result_metadata

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "LMD_LS_CENTERS",
    "SOLAR_WORLD",
    "apply_climate_to_mesh",
    "build_mesh_from_dem",
    "load_lmd_slices",
    "load_monthly_climate",
    "parse_lmd_slice",
    "register_solar_planet",
    "sample_regular_grid",
    "write_climate_monthly",
    "write_climate_secondary",
    "write_ucc_yearly",
]


# ---------------------------------------------------------------------------
# Planet registration (inside the real-world reference-anchor world)
# ---------------------------------------------------------------------------

SOLAR_WORLD = "earth"
"""The real-world reference-anchor world that hosts the Solar-System bodies.

The name "earth" is historical — the world is the real-data anchor (never
built), and Mars / Moon / Venus / Titan live inside it as additional
``planet_ids`` (one real-world anchor, many bodies) rather than as separate
pseudo-worlds.  IDs follow the root's ``stellar.yaml`` conventions:
``planet_mars``, ``planet_venus``, ``satellite_moon``, ``satellite_titan``.
"""


def register_solar_planet(
    worlds_dir: Path,
    planet_id: str,
    *,
    world_name: str = SOLAR_WORLD,
) -> Path:
    """Return the maps dir for a Solar-System body inside the anchor world.

    ``planet_id`` must already be listed in the world's ``world.yaml`` (that
    file is hand-maintained — a YAML round-trip here would destroy its
    comments); this function only creates the maps directory and validates
    membership with an actionable error.
    """
    import yaml

    world_dir = worlds_dir / world_name
    config_path = world_dir / "world.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} not found — is --data-dir correct?")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    planet_ids = list(data.get("planet_ids") or [])
    if planet_id not in planet_ids:
        raise ValueError(
            f"'{planet_id}' is not in {config_path} planet_ids {planet_ids} — "
            "add it there first (the file is hand-maintained to preserve comments)."
        )
    if not data.get("reference_anchor", False):
        raise ValueError(
            f"world '{world_name}' is not reference_anchor: true — Solar-System "
            "bodies must never be engine-built."
        )
    map_dir = world_dir / "maps" / planet_id
    map_dir.mkdir(parents=True, exist_ok=True)
    return map_dir


# ---------------------------------------------------------------------------
# Grid sampling + mesh
# ---------------------------------------------------------------------------


def sample_regular_grid(
    data: np.ndarray,
    *,
    lat_start: float,
    dlat: float,
    lon_start: float,
    dlon: float,
    lats: np.ndarray,
    lons: np.ndarray,
) -> np.ndarray:
    """Bilinear-sample a regular lat/lon grid at scattered (lat, lon) points.

    ``lat_start``/``lon_start`` are the centre coordinates of ``data[0, 0]``;
    ``dlat`` is negative for north-first rows.  Longitude wraps; latitude
    clamps at the poles.  A sample whose four corners are partly NaN falls
    back to the nearest valid corner (nearest-neighbour, not extrapolation).
    """
    h, w = data.shape
    # Clamp latitude to the grid extent BEFORE flooring; the interpolation
    # weight must be relative to the clamped row index (otherwise points
    # beyond the last row silently extrapolate from the wrong pair).
    fy = np.clip((lats - lat_start) / dlat, 0.0, max(h - 1, 0))
    fx = (lons - lon_start) / dlon
    y0c = np.clip(np.floor(fy).astype(np.int64), 0, max(h - 2, 0))
    y1c = np.minimum(y0c + 1, h - 1)
    wy = fy - y0c
    x0 = np.floor(fx).astype(np.int64)
    wx = fx - x0
    x0c = np.mod(x0, w)
    x1c = np.mod(x0 + 1, w)
    v00 = data[y0c, x0c]
    v01 = data[y0c, x1c]
    v10 = data[y1c, x0c]
    v11 = data[y1c, x1c]

    with np.errstate(invalid="ignore"):
        top = v00 * (1.0 - wx) + v01 * wx
        bot = v10 * (1.0 - wx) + v11 * wx
        out = top * (1.0 - wy) + bot * wy
        # NaN fallback: nearest valid corner.
        nan = ~np.isfinite(out)
        if nan.any():
            corners = np.stack([v00, v01, v10, v11])  # (4, N)
            valid = np.isfinite(corners)
            any_valid = valid.any(axis=0)
            first_valid = np.argmax(valid, axis=0)
            nearest = corners[first_valid, np.arange(lats.shape[0])]
            out = np.where(nan & any_valid, nearest, out)
    return np.asarray(out, dtype=np.float64)


LMD_LS_CENTERS = [15 + 30 * m for m in range(12)]
"""Ls bin centres (15°, 45°, …, 345°) used by the LMD web-interface fetches."""


def parse_lmd_slice(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Parse one LMD (MCD/VCD) web-interface ASCII map.

    Layout (verified against MCD v6.1 and VCD v2.3 outputs, 2026-09-21)::

        ### header comments (version / scenario / Ls / altitude / averaging)
        ---- ||  <latitudes, −90…+90 ascending, full precision>
        ---------...
        +000 ||  <nlat values>   ← rows are EAST LONGITUDES 0…360, labels are
        +003 ||  ...               floor()'d ints; lon 0 and 360 rows duplicate

    Returns ``(data (nlon, nlat), lons, lats, header_lines)``.  The exact lon
    axis is reconstructed as ``linspace(first, last, n)`` — valid because the
    floor()'d labels preserve the endpoints (0 and 360).
    """
    header: list[str] = []
    lats: np.ndarray | None = None
    lons: list[float] = []
    rows: list[list[float]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("###"):
            header.append(line.lstrip("#").strip())
        elif "||" in line:
            left, right = line.split("||", 1)
            vals = [float(x) for x in right.split()]
            if left.startswith("----"):
                lats = np.array(vals, dtype=np.float64)
            else:
                lons.append(float(left.strip().lstrip("+")))
                rows.append(vals)
        # bare '------' separator lines carry no data
    if lats is None or not rows:
        raise ValueError(f"{path.name}: no lat header / data rows found")
    data = np.array(rows, dtype=np.float64)  # (nlon, nlat)
    if data.shape[1] != len(lats):
        raise ValueError(f"{path.name}: {data.shape[1]} columns vs {len(lats)} latitudes")
    lons_arr = np.linspace(lons[0], lons[-1], len(lons))
    return data, lons_arr, lats, header


def load_lmd_slices(cache_dir: Path, prefix: str) -> tuple[np.ndarray, dict[str, float], list[str]]:
    """Load the 12 Ls-bin LMD ASCII maps → (field (12, nlat, nlon), sampler meta, header).

    Files are ``{prefix}_ls{NNN}.txt`` as fetched by
    ``scripts/solar/fetch_lmd_slices.py``; unit conversion (K → °C etc.) is the
    caller's job.  ``meta`` has the lat_start/dlat/lon_start/dlon keys expected
    by :func:`sample_regular_grid`.
    """
    bins: list[np.ndarray] = []
    meta: dict[str, float] | None = None
    header0: list[str] = []
    for ls in LMD_LS_CENTERS:
        path = cache_dir / f"{prefix}_ls{ls:03d}.txt"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing — fetch via scripts/solar/fetch_lmd_slices.py")
        data, lons, lats, header = parse_lmd_slice(path)
        arr = data.T  # (nlon, nlat) → (nlat, nlon), rows follow the lats axis
        if meta is None:
            meta = {
                "lat_start": float(lats[0]),
                "dlat": float(np.mean(np.diff(lats))),
                "lon_start": float(lons[0]),
                "dlon": float(np.mean(np.diff(lons))),
            }
            header0 = header
        elif arr.shape != bins[0].shape:
            raise ValueError(f"{path.name}: shape {arr.shape} != {bins[0].shape}")
        bins.append(arr)
    assert meta is not None
    return np.stack(bins), meta, header0


def build_mesh_from_dem(
    dem: np.ndarray,
    *,
    lat_start: float,
    dlat: float,
    lon_start: float,
    dlon: float,
    radius_km: float,
    num_nodes: int = 50_000,
    seed: int = 42,
    output_dir: Path,
    planet_id: str,
    source: str,
    source_resolution: str,
) -> Any:
    """Generate the CVT mesh, sample the DEM onto cells, write mesh/png/yaml.

    ``radius_km`` MUST be the target body's radius — TerrainPipelineConfig
    defaults are Earth's (silent-error pitfall, see memory
    earth-defaults-engine-pitfall).  Returns the CVTMesh.
    """
    from .import_earth_elevation import save_elevation_png
    from .map.cvt_mesh import generate_cvt_mesh
    from .map.pipeline_types import TerrainPipelineConfig

    config = TerrainPipelineConfig(
        seed=seed,
        num_nodes=num_nodes,
        lloyd_iterations=8,
        jitter_sigma=0.3,
        radius_km=radius_km,
    )
    print(f"  Generating CVT mesh ({num_nodes} nodes, R={radius_km} km) …")
    mesh = generate_cvt_mesh(config)

    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    elev = sample_regular_grid(
        dem,
        lat_start=lat_start,
        dlat=dlat,
        lon_start=lon_start,
        dlon=dlon,
        lats=lats,
        lons=lons,
    )
    for c, e in zip(mesh.cells, elev, strict=True):
        c.elevation = float(e)
        # No hydrosphere split by default; water-bearing worlds (Titan's methane
        # seas) override water_class after this call.
        c.water_class = "land"

    from .map.export import MESH_FILENAME, save_cvt_mesh

    output_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = output_dir / MESH_FILENAME
    # No plate boundaries on these worlds → distance_to_boundary_km = inf;
    # save_cvt_mesh's JSON intermediate keeps non-finite values sanitized
    # (strict JSON, browser-safe).
    save_cvt_mesh(mesh_path, mesh)
    print(f"  Wrote {mesh_path.name} ({mesh_path.stat().st_size / 1e6:.1f} MB)")

    # elevation.png (2048×1024 resample) + map.yaml.
    png_w, png_h = 2048, 1024
    grid_lats = np.linspace(90.0, -90.0, png_h)
    grid_lons = np.linspace(-180.0, 180.0, png_w, endpoint=False)
    glon, glat = np.meshgrid(grid_lons, grid_lats)
    png_grid = sample_regular_grid(
        dem,
        lat_start=lat_start,
        dlat=dlat,
        lon_start=lon_start,
        dlon=dlon,
        lats=glat.ravel(),
        lons=glon.ravel(),
    ).reshape(png_h, png_w)
    e_min, e_max = float(np.nanmin(dem)), float(np.nanmax(dem))
    save_elevation_png(np.nan_to_num(png_grid, nan=e_min), output_dir, min_m=e_min, max_m=e_max)

    import yaml

    map_yaml = {
        "planet_id": planet_id,
        "projection": "equirectangular",
        "width": png_w,
        "height": png_h,
        "elevation_min_m": e_min,
        "elevation_max_m": e_max,
        "sea_level_m": 0.0,
        "elevation_range_m": [round(e_min, 1), round(e_max, 1)],
        "pipeline_version": "solar-import",
        "source": source,
        "source_resolution": source_resolution,
        "num_plates": 0,
    }
    with (output_dir / "map.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(map_yaml, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print("  Wrote map.yaml")
    return mesh


# ---------------------------------------------------------------------------
# Climate monthly / mesh fields / secondary exports
# ---------------------------------------------------------------------------


def write_climate_monthly(
    output_dir: Path,
    t_monthly: np.ndarray,
    p_monthly: np.ndarray,
    *,
    bin_days: float = REFERENCE_MONTH_DAYS,
    month_0: str = "vernal_equinox",
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Write the quantized climate_monthly.msgpack (same schema as the engine).

    ``bin_days`` declares the duration of each of the 12 bins — reference month
    for earth/nacrea, Martian month for Mars, etc.  P is mm *per bin*.
    """
    from .map.export import _quantize_int16

    t_q, t_s, t_o = _quantize_int16(np.asarray(t_monthly, dtype=np.float64))
    p_q, p_s, p_o = _quantize_int16(np.asarray(p_monthly, dtype=np.float64))
    payload: dict[str, Any] = {
        "num_cells": t_monthly.shape[0],
        "months": t_monthly.shape[1],
        "dtype": "int16",
        "t_monthly": t_q,
        "t_scale": t_s,
        "t_offset": t_o,
        "p_monthly": p_q,
        "p_scale": p_s,
        "p_offset": p_o,
        "temperature_range_c": [float(np.min(t_monthly)), float(np.max(t_monthly))],
        "precipitation_range_mm": [float(np.min(p_monthly)), float(np.max(p_monthly))],
        "month_0": month_0,
        "bin_days": float(bin_days),
        "window_days": float(bin_days) * t_monthly.shape[1],
    }
    if extra_metadata:
        payload.update(extra_metadata)
    out = output_dir / "climate_monthly.msgpack"
    out.write_bytes(msgpack.packb(payload))
    print(f"  Wrote {out.name} ({out.stat().st_size / 1e6:.1f} MB)")


def load_monthly_climate(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """Decode climate_monthly.msgpack → (t (N,12) °C, p (N,12) mm/bin, bin_days)."""
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = int(d["num_cells"]), int(d["months"])

    def deq(name: str) -> np.ndarray:
        q = np.frombuffer(d[name], dtype=np.int16).astype(np.float64)
        scale = float(d[name.removesuffix("_monthly") + "_scale"])
        offset = float(d[name.removesuffix("_monthly") + "_offset"])
        return q.reshape(n, m) * scale + offset

    bin_days = float(d.get("bin_days", REFERENCE_MONTH_DAYS))
    return deq("t_monthly"), deq("p_monthly"), bin_days


def apply_climate_to_mesh(
    output_dir: Path,
    t_annual: np.ndarray,
    p_annual: np.ndarray,
    water_class: np.ndarray | None = None,
) -> None:
    """Write annual T/P (and optionally water_class) into the mesh cell fields.

    ``water_class`` overrides the all-land default for worlds with a surface
    liquid inventory (Titan's methane seas → "ocean"; declared per world).
    """
    from .map.export import find_mesh_file, load_cvt_mesh_model, save_cvt_mesh

    mesh_path = find_mesh_file(output_dir)
    if mesh_path is None:
        raise FileNotFoundError(f"no mesh file under {output_dir}")
    mesh = load_cvt_mesh_model(mesh_path)
    for c, t, p in zip(mesh.cells, t_annual, p_annual, strict=True):
        c.temperature_C = float(t)
        c.precipitation_mm = float(p)
    if water_class is not None:
        for c, w in zip(mesh.cells, water_class, strict=True):
            c.water_class = str(w)
    save_cvt_mesh(mesh_path, mesh)
    print("  Applied annual T/P to mesh cell fields")


def write_climate_secondary(
    output_dir: Path,
    *,
    width: int = 2048,
    height: int = 1024,
    source: str,
) -> None:
    """temperature.png / precipitation.png / climate_metadata.json (no Köppen)."""
    from .map.export import (
        export_equirectangular,
        export_layer_png,
        find_mesh_file,
        load_cvt_mesh_model,
    )

    mesh_path = find_mesh_file(output_dir)
    if mesh_path is None:
        raise FileNotFoundError(f"no mesh file under {output_dir}")
    mesh = load_cvt_mesh_model(mesh_path)
    t_grid = export_equirectangular(mesh, width, height, field="temperature_C")
    p_grid = export_equirectangular(mesh, width, height, field="precipitation_mm")
    export_layer_png(
        t_grid, output_dir / "temperature.png", float(t_grid.min()), float(t_grid.max())
    )
    export_layer_png(
        p_grid, output_dir / "precipitation.png", float(p_grid.min()), float(p_grid.max())
    )
    meta = {
        "source": source,
        "temperature_range_c": [float(t_grid.min()), float(t_grid.max())],
        "precipitation_range_mm": [float(p_grid.min()), float(p_grid.max())],
        "koppen_classes": [],
        "export_resolution": [width, height],
    }
    (output_dir / "climate_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("  Wrote temperature.png / precipitation.png / climate_metadata.json")


# ---------------------------------------------------------------------------
# UCC yearly (generalization of scripts/earth/export_earth_yearly.py)
# ---------------------------------------------------------------------------


def write_ucc_yearly(
    output_dir: Path,
    *,
    data_source: str,
    provenance: dict[str, str],
    demand_model: str | None = "hamon-1961",
    demand_daylength_h: float = 12.0,
    climate_state: str | None = None,
    lapse_rate_c_per_km: float | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Compute UCC descriptors + current-profile classes → climate_yearly.msgpack.

    Reads ``climate_monthly.msgpack`` + the mesh's ``water_class`` from
    ``output_dir``.  ``demand_model=None`` skips the reference-demand
    computation entirely (AI/deficit → ``missing_input`` — the Moon case: no
    atmosphere, no PET model applies).  ``bin_days`` travels from the monthly
    file into Hamon's accumulation window and the yearly metadata.

    ``climate_state`` declares the world-level regime (axis F vocabulary,
    ``ucc.CLIMATE_STATES``) and ``lapse_rate_c_per_km`` the declared
    environmental lapse rate enabling the ``-H`` highland modifier (None for
    airless bodies — no lapse rate exists, the modifier is not applicable).

    Returns the land class distribution (code → cell count) for console output.
    """
    from .engine.climate_physics import potential_evapotranspiration_hamon_monthly
    from .map.export import find_mesh_file, load_cvt_mesh
    from .map.ucc import (
        PHASE_CODE_LETTERS_V2,
        PROFILE_CURRENT,
        SHAPE_CODE_LETTERS_V2,
        STATUS_CODES,
        SUPPLY_BANDS_CURRENT,
        THERMAL_BANDS_CURRENT,
        yearly_cell_arrays,
    )

    t_monthly, p_monthly, bin_days = load_monthly_climate(output_dir / "climate_monthly.msgpack")
    n = t_monthly.shape[0]

    _mesh_path = find_mesh_file(output_dir)
    if _mesh_path is None:
        raise FileNotFoundError(f"no mesh file under {output_dir}")
    mesh = load_cvt_mesh(_mesh_path)
    water_class = np.array([c.get("water_class") or "" for c in mesh["cells"]], dtype=str)
    if len(water_class) != n:
        raise ValueError("mesh/monthly cell-count mismatch")

    et_monthly: np.ndarray | None = None
    if demand_model == "hamon-1961":
        # Same demand model as the engine-side descriptors (declared, not
        # FAO-56-calibrated); bin_days sets the accumulation window so the
        # rate basis matches the P bins.
        et_monthly = potential_evapotranspiration_hamon_monthly(t_monthly, bin_days)
    elif demand_model is not None:
        raise ValueError(f"unsupported demand_model {demand_model!r}")

    is_land = water_class == "land"
    elevation_m = (
        np.array([float(c.get("elevation") or 0.0) for c in mesh["cells"]])
        if lapse_rate_c_per_km is not None
        else None
    )
    print(f"  Computing UCC descriptors + {PROFILE_CURRENT} classification ({n} cells) …")
    arrays = yearly_cell_arrays(
        t_monthly,
        p_monthly,
        et_monthly,
        is_land,
        elevation_m=elevation_m,
        lapse_rate_c_per_km=lapse_rate_c_per_km,
    )

    payload: dict[str, Any] = {
        **result_metadata(),
        "num_cells": n,
        "months": 12,
        "dtype": "float32",
        "demand_model": demand_model,
        "demand_daylength_h": demand_daylength_h,
        "freeze_threshold_c": 0.0,
        "status_codes": list(STATUS_CODES),
        "profile": PROFILE_CURRENT,
        "thermal_bands": list(THERMAL_BANDS_CURRENT),
        "supply_bands": list(SUPPLY_BANDS_CURRENT),
        "shape_codes": list(SHAPE_CODE_LETTERS_V2),
        "phase_codes": list(PHASE_CODE_LETTERS_V2),
        "bin_days": float(bin_days),
        "window_days": float(bin_days) * 12,
        "data_source": data_source,
        "provenance": provenance,
        # p_total dual-basis closure (astra ledger #9): p_total_mm follows the
        # declared local window (e.g. per Martian year); p_total_ref365_mm is
        # the rate-normalized 365.25-day view for cross-world comparison.
        "p_total_basis": "local_window",
        **{k: v.tobytes() for k, v in arrays.items()},
        "p_total_ref365_mm": (arrays["p_total_mm"] * (365.25 / (float(bin_days) * 12))).tobytes(),
    }
    # World-level declarations (axis F + the -H modifier's lapse rate): written
    # only when declared — absent keys read as "not declared" downstream.
    if climate_state is not None:
        payload["climate_state"] = climate_state
    if lapse_rate_c_per_km is not None:
        payload["lapse_rate_c_per_km"] = lapse_rate_c_per_km
    if extra_metadata:
        payload.update(extra_metadata)
    out = output_dir / "climate_yearly.msgpack"
    out.write_bytes(msgpack.packb(payload))
    print(f"  Wrote {out.name} ({out.stat().st_size / 1e6:.1f} MB)")

    # Land class distribution for the console summary.
    ucc_thermal = arrays["ucc_thermal"]
    ucc_supply = arrays["ucc_supply"]
    combos: dict[str, int] = {}
    for i in range(n):
        if not is_land[i]:
            continue
        t_name = THERMAL_BANDS_CURRENT[ucc_thermal[i]]
        s_name = SUPPLY_BANDS_CURRENT[ucc_supply[i]] if ucc_supply[i] != 255 else "n-a"
        key = f"{t_name}/{s_name}"
        combos[key] = combos.get(key, 0) + 1
    return combos
