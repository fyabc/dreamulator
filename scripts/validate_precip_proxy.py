#!/usr/bin/env python3
"""Geomorphic precipitation proxy validation — vs the authoritative climate engine.

Compares the simple erosion precipitation proxy (``map/precip_proxy.py``) against
the climate engine's simulated annual precipitation (already baked into
``cvt_mesh.json`` by ``dreamulator build``).  The proxy is what the fluvial
erosion loop uses (inside the geological layer, upstream of climate); this script
measures how well it approximates the authoritative field.

Interpretation:
  - high correlation / low bias → the simple proxy is adequate for erosion forcing;
  - low correlation / wrong zonal shape → the proxy needs the directional
    Smith & Barstad (2004) orographic rain-shadow, or a better latitude base.

Precipitation spans several orders of magnitude, so both linear and log-space
correlation are reported (linear RMSE is dominated by wet regions).

Usage::

    uv run python scripts/validate_precip_proxy.py
    uv run python scripts/validate_precip_proxy.py --world gaia-m --data-dir private/worlds
    uv run python scripts/validate_precip_proxy.py --coupling none   # compare uniform proxy
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_mesh(data_dir: Path, world: str, planet: str, branch: str | None) -> object | None:
    from pydantic import TypeAdapter

    from dreamulator.map.models import CVTMesh

    search_dirs = [data_dir / world]
    if branch:
        search_dirs.insert(0, data_dir / world / "branches" / branch)
    for base in search_dirs:
        p = base / "maps" / planet / "cvt_mesh.json"
        if p.exists():
            from dreamulator.map.export import decompress_mesh_bytes

            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(p.read_bytes()))
    return None


def _arrays(mesh) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Extract elevation, latitude (deg), authoritative precip, and land mask."""
    elevation = np.array([c.elevation for c in mesh.cells], dtype=np.float64)
    lat_deg = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    precip = np.array(
        [c.precipitation_mm if c.precipitation_mm is not None else np.nan for c in mesh.cells],
        dtype=np.float64,
    )
    is_land = elevation >= 0.0
    return elevation, lat_deg, precip, is_land


def _report(
    coupling: str,
    proxy: np.ndarray,
    precip: np.ndarray,
    lat: np.ndarray,
    is_land: np.ndarray,
    band: float,
):
    land = is_land & ~np.isnan(precip)
    p = proxy[land]
    r = precip[land]
    lat_d = np.degrees(lat)[land]

    diff = p - r
    rmse = float(np.sqrt(np.mean(diff**2)))
    bias = float(np.mean(diff))
    corr = float(np.corrcoef(p, r)[0, 1])
    corr_log = float(np.corrcoef(np.log10(p + 1.0), np.log10(r + 1.0))[0, 1])

    print(f"\n=== climate_coupling = {coupling!r} (land-only) ===")
    print(
        f"  RMSE={rmse:.0f} mm/yr  bias={bias:+.0f} mm/yr  "
        f"corr={corr:.3f}  corr_log={corr_log:.3f}"
    )

    # Zonal profile (proxy vs authoritative), 5° bands.
    n_bands = int(round(180.0 / band))
    p_sum = np.zeros(n_bands)
    r_sum = np.zeros(n_bands)
    cnt = np.zeros(n_bands, dtype=int)
    for i in range(len(p)):
        b = int(np.clip((90.0 - lat_d[i]) / band, 0, n_bands - 1))
        p_sum[b] += p[i]
        r_sum[b] += r[i]
        cnt[b] += 1
    p_mean = np.where(cnt > 0, p_sum / np.maximum(cnt, 1), np.nan)
    r_mean = np.where(cnt > 0, r_sum / np.maximum(cnt, 1), np.nan)
    centers = np.array([90.0 - band * (b + 0.5) for b in range(n_bands)])

    print(f"  {'lat':>5} {'proxy':>8} {'climate':>8} {'bias':>8}")
    for b in range(n_bands):
        if cnt[b] == 0:
            continue
        print(
            f"  {centers[b]:>5.0f}° {p_mean[b]:>8.0f} {r_mean[b]:>8.0f} "
            f"{p_mean[b] - r_mean[b]:>+8.0f}"
        )

    verdict = (
        "adequate (shape matches — amplitude/calibration only)"
        if corr_log > 0.7
        else "inadequate (wrong zonal/orographic shape — needs Smith & Barstad rain-shadow)"
    )
    print(f"  → {verdict}")
    return {
        "rmse": round(rmse, 1),
        "bias": round(bias, 1),
        "corr": round(corr, 3),
        "corr_log": round(corr_log, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="private/worlds")
    parser.add_argument("--world", default="gaia-m")
    parser.add_argument("--planet", default="satellite_gaiam")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--coupling", default="proxy", choices=["proxy", "none", "both"])
    parser.add_argument("--precip-proxy-base-mm", type=float, default=None)
    parser.add_argument("--band", type=float, default=5.0)
    args = parser.parse_args()

    from dreamulator.map.pipeline_types import TerrainPipelineConfig
    from dreamulator.map.precip_proxy import geomorphic_precipitation

    root = _find_project_root()
    data_dir = (root / args.data_dir).resolve()

    mesh_path = data_dir / args.world / "maps" / args.planet / "cvt_mesh.json"
    print(f"Loading mesh: {mesh_path}")
    mesh = _load_mesh(data_dir, args.world, args.planet, args.branch)
    if mesh is None:
        print("  ERROR: no mesh found (run `dreamulator build` first)")
        return

    elevation, lat_deg, precip, is_land = _arrays(mesh)
    lat_rad = np.radians(lat_deg)
    n_land = int(is_land.sum())
    n_with_precip = int((~np.isnan(precip) & is_land).sum())
    print(f"cells={mesh.num_cells}, land={n_land}, with climate precip={n_with_precip}")
    if n_with_precip == 0:
        print("  ERROR: no precipitation_mm in the mesh — is the climate engine built?")
        return

    # Load the world's actual circulation params (hadley extent, storm track,
    # rotation, radius) so the proxy uses the SAME zonal physics as the built
    # climate, not the Earth defaults.
    from dataclasses import replace

    config_path = data_dir / args.world / "layers" / "geological" / "input" / "terrain_config.yaml"
    base_config = (
        TerrainPipelineConfig.from_yaml(config_path)
        if config_path.exists()
        else TerrainPipelineConfig()
    )
    print(
        f"  proxy config: hadley={base_config.hadley_extent_deg}°, "
        f"storm={base_config.storm_track_amplitude_mm}, "
        f"evap={base_config.evaporation_base_mm}, R={base_config.radius_km} km"
    )

    from dreamulator.map.hydrology import build_adjacency

    xyz = mesh.cell_xyz
    neighbors, dists_km = build_adjacency(mesh.cells, base_config.radius_km, xyz)
    dists_m = [[d * 1000.0 for d in ds] for ds in dists_km]

    proxy_base = (
        args.precip_proxy_base_mm
        if args.precip_proxy_base_mm is not None
        else base_config.precip_proxy_base_mm
    )
    couplings = ["proxy", "none"] if args.coupling == "both" else [args.coupling]
    for coupling in couplings:
        config = replace(base_config, climate_coupling=coupling, precip_proxy_base_mm=proxy_base)
        proxy = geomorphic_precipitation(
            elevation, lat_deg, xyz, is_land, neighbors, dists_m, config
        )
        _report(coupling, proxy, precip, lat_rad, is_land, args.band)


if __name__ == "__main__":
    main()
