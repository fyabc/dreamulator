#!/usr/bin/env python3
"""Prepare a complete terrain-refined precipitation archive from a pinned GCM source.

Example:
    python scripts/climate/gcm/refine_precipitation.py --world data/worlds/nacrea \
        --planet satellite_nacrea --baseline native-precipitation.npz \
        --weather snapshots.nc --out refined-precipitation.npz

This preparation leaves the world unchanged. The resulting archive is consumed
by gcm_to_mesh.py --precipitation-field and export canvas's climate refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

SRC = Path(__file__).resolve().parents[3] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dreamulator.gcm.diagnostics import (  # noqa: E402
    equinox_day_from_declination,
    orbital_phase_of_records,
)
from dreamulator.gcm.mapping import map_world  # noqa: E402
from dreamulator.gcm.native_partition import NativePrecipitationField  # noqa: E402
from dreamulator.gcm.terrain_exposure import (  # noqa: E402
    refine_large_scale_precipitation,
    terrain_exposure_index,
)
from dreamulator.gcm.to_mesh import bilinear_to_points  # noqa: E402
from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model  # noqa: E402
from dreamulator.map.td_canvas import unit_vectors  # noqa: E402


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def weather_directions(
    weather: Path,
    *,
    orbital_year_days: float,
    steps_per_model_day: float,
    gravity_m_s2: float,
    directions: int,
) -> dict[str, np.ndarray]:
    """Integrate rain-weighted flow directions over all phase bins of a weather year."""
    import netCDF4  # noqa: PLC0415

    with netCDF4.Dataset(weather) as ds:
        order = np.argsort(ds["lat"][:])
        lat = np.asarray(ds["lat"][:], float)[order]
        lon = np.asarray(ds["lon"][:], float)
        time = np.asarray(ds["time"][:], float)
        origin = equinox_day_from_declination(
            time,
            np.asarray(ds["zdec"][:], float),
            orbital_year_days=orbital_year_days,
            steps_per_model_day=steps_per_model_day,
        )
        phase = orbital_phase_of_records(
            time,
            orbital_year_days=orbital_year_days,
            steps_per_model_day=steps_per_model_day,
            perihelion_day=origin,
        )
        months = np.minimum((phase * 12).astype(int), 11)
        counts = np.bincount(months, minlength=12)
        if not (counts > 0).all() or not np.allclose(np.diff(time), np.diff(time)[0]):
            raise ValueError("weather must cover all phase months with regular time intervals")
        rain = np.zeros((12, directions, len(lat) * len(lon)))
        parent = np.arange(len(lat) * len(lon))[None, :]
        for start in range(0, len(time), 64):
            stop = min(start + 64, len(time))
            prl = np.asarray(ds["prl"][start:stop], float)[:, order].reshape(stop - start, -1)
            u = np.asarray(ds["ua"][start:stop, -1], float)[:, order].reshape(stop - start, -1)
            v = np.asarray(ds["va"][start:stop, -1], float)[:, order].reshape(stop - start, -1)
            angle = np.mod(np.arctan2(u, v), 2 * np.pi)
            bins = np.floor(angle * directions / (2 * np.pi) + 0.5).astype(int) % directions
            np.add.at(rain, (months[start:stop, None], bins, parent), prl)
        total = rain.sum(axis=1, keepdims=True)
        weights = np.divide(rain, total, out=np.zeros_like(rain), where=total > 0)
        height = np.maximum(np.asarray(ds["sg"][0], float)[order] / gravity_m_s2, 0)
    return {
        "latitude": lat,
        "longitude": lon,
        "rain_weight": weights,
        "height": height,
        "phase_counts": counts,
        "frames": np.asarray(len(time)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", required=True, type=Path)
    parser.add_argument("--planet", required=True)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--weather", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--directions", type=int, default=32)
    parser.add_argument("--step-minutes", type=float, default=45.0)
    args = parser.parse_args()
    parameters = map_world(args.world, args.planet)
    baseline = NativePrecipitationField.load(args.baseline)
    p = baseline.partition
    driver = weather_directions(
        args.weather,
        orbital_year_days=parameters.year,
        steps_per_model_day=1440 / args.step_minutes,
        gravity_m_s2=parameters.gravity,
        directions=args.directions,
    )
    expected_lat = np.degrees(np.arcsin(np.polynomial.legendre.leggauss(p.shape[0])[0]))
    expected_lon = np.arange(p.shape[1]) * 360 / p.shape[1]
    if (
        (len(driver["latitude"]), len(driver["longitude"])) != p.shape
        or not np.allclose(driver["latitude"], expected_lat, atol=2e-5, rtol=0)
        or not np.allclose(driver["longitude"], expected_lon, atol=1e-8, rtol=0)
    ):
        raise ValueError("weather and precipitation must use the same native grid")
    mesh_path = find_mesh_file(args.world / "maps" / args.planet)
    if mesh_path is None:
        raise ValueError("the source world needs its existing geological mesh")
    mesh = load_cvt_mesh_model(mesh_path)
    lat = np.array([c.lat for c in mesh.cells])
    lon = np.array([c.lon for c in mesh.cells])
    elevation = np.maximum([c.elevation for c in mesh.cells], 0.0)
    tree = cKDTree(unit_vectors(lat, lon))

    def fine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return elevation[tree.query(unit_vectors(a, b), workers=8)[1]]

    def coarse(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return bilinear_to_points(driver["latitude"], driver["longitude"], driver["height"], a, b)

    ratio = []
    for direction in range(args.directions):
        bearing = direction * 2 * np.pi / args.directions
        values = [
            terrain_exposure_index(
                p.latitude,
                p.longitude,
                bearing,
                p.radius_km,
                sampler,
                integration_spacing_km=p.spacing_km,
            )
            for sampler in (fine, coarse)
        ]
        ratio.append(values[0] / values[1])
    field = refine_large_scale_precipitation(
        baseline,
        np.array(ratio),
        driver["rain_weight"],
        provenance={
            "baseline_sha256": file_sha256(args.baseline),
            "weather_sha256": file_sha256(args.weather),
            "source_mesh_sha256": file_sha256(mesh_path),
            "weather_frames": int(driver["frames"]),
            "phase_counts": driver["phase_counts"].tolist(),
            "step_minutes": args.step_minutes,
            "fine_terrain_sampling": "nearest geological CVT elevation, sea level on ocean",
            "native_terrain_sampling": "bilinear GCM surface geopotential divided by gravity",
        },
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    field.save(args.out)
    print(json.dumps(field.metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
