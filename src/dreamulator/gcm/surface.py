"""Build ExoPlaSim ``.sra`` surface files from dreamulator meshes.

ExoPlaSim takes land/terrain via ``configure(landmap=..., topomap=...)``,
which copy the given files to ``N<nlats>_surf_0172.sra`` (land binary mask,
code 172) and ``N<nlats>_surf_0129.sra`` (surface geopotential, code 129) in
the workdir.  The ``.sra`` format (reverse-engineered from the shipped
``PlanetGrid.ipynb`` writer and ``plasim/src/surfmod.f90:surface_ini`` reader,
2026-10-06) is **plain text**:

- header: 8 free-format integers ``[kcode, 0, 20170927, 0, NLON, NLAT, 0, 0]``
  (third field is an arbitrary date; month field 0 = constant annual field);
- body: ``NLAT*NLON`` values in free format, flat row-major over
  **latitude +90 → −90** (plasim ``jlat=1`` is the northernmost Gaussian
  latitude) and **longitude 0 → 360**; the shipped writer groups 8 values per
  line with ``%9.3f``, which this module reproduces.

The horizontal grid is the model's Gaussian grid: latitudes from
``exoplasim.pyfft.inigau(nlat)`` (or an equivalent Gauss-Legendre quadrature
when the ``[gcm]`` extra is absent), longitudes uniform.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

_SRA_DATE = 20170927  # arbitrary date stamp used by the shipped writer
KCODE_LAND_MASK = 172  # lsm, land binary mask
KCODE_GEOPOTENTIAL = 129  # sg, surface geopotential (m²/s²)


def gaussian_latitudes(nlat: int) -> np.ndarray:
    """Gaussian latitudes in degrees, **ascending** (south → north).

    Uses exoplasim's own quadrature when available so the grid matches the
    model exactly; falls back to numpy's Legendre nodes otherwise (identical
    nodes up to rounding).
    """
    try:
        import exoplasim.pyfft as pyfft  # noqa: PLC0415

        sid, _ = pyfft.inigau(nlat)
        sid_arr: np.ndarray[tuple[int], np.dtype[np.float64]] = np.asarray(sid, dtype=np.float64)
        # inigau returns nodes in descending latitude; normalise to ascending
        # so both backends (pyfft / leggauss) agree across environments
        return np.sort(np.degrees(np.arcsin(sid_arr)))
    except Exception:  # noqa: BLE001 -- extra not installed; fall back
        # Gauss-Legendre nodes x in (-1,1) ascending = sin(lat)
        x = np.polynomial.legendre.leggauss(nlat)[0]
        return np.degrees(np.arcsin(x))


def uniform_longitudes(nlon: int) -> np.ndarray:
    """Uniform longitudes in degrees, 0 → 360 (cell centres)."""
    return np.arange(nlon) / float(nlon) * 360.0


def write_sra(
    path: str | Path,
    kcode: int,
    field: np.ndarray,
    nlat: int,
    nlon: int,
) -> Path:
    """Write a constant (month 0) ``.sra`` file.

    ``field`` has shape ``(nlat, nlon)`` with latitudes **ascending**; the file
    stores them north → south, matching the plasim reader convention.
    """
    field = np.asarray(field, dtype=float)
    if field.shape != (nlat, nlon):
        raise ValueError(f"field shape {field.shape} != ({nlat}, {nlon})")
    header = [kcode, 0, _SRA_DATE, 0, nlon, nlat, 0, 0]
    flat = field[::-1, :].reshape(-1)  # north → south, row-major
    lines = [" ".join(f"{v:9.3f}" for v in flat[i : i + 8]) for i in range(0, flat.size, 8)]
    text = " ".join(f"{h:11d}" for h in header) + "\n" + "\n".join(lines) + "\n"
    path = Path(path)
    path.write_text(text, encoding="utf-8")
    return path


def _mesh_arrays(mesh_path: str | Path) -> dict[str, np.ndarray]:
    """Per-cell lat/lon (deg), area (km²), elevation (m) and land flag of a mesh."""
    from dreamulator.map.export import load_cvt_mesh_model  # noqa: PLC0415

    mesh = load_cvt_mesh_model(Path(mesh_path))
    return {
        "lat": np.array([c.lat for c in mesh.cells], dtype=float),
        "lon": np.array([c.lon for c in mesh.cells], dtype=float),
        "area": np.array([c.area_km2 for c in mesh.cells], dtype=float),
        "elevation": np.array([c.elevation for c in mesh.cells], dtype=float),
        "is_land": np.asarray([str(c.water_class) != "ocean" for c in mesh.cells]),
    }


def _unit_vectors(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    lat_r, lon_r = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack(
        [np.cos(lat_r) * np.cos(lon_r), np.cos(lat_r) * np.sin(lon_r), np.sin(lat_r)], axis=-1
    )


def land_mask_from_mesh(mesh_path: str | Path, nlat: int, nlon: int) -> tuple[np.ndarray, float]:
    """Nearest-cell regrid of a dreamulator CVT mesh land mask to the Gaussian grid.

    Returns ``(mask, land_fraction)`` where ``mask`` is ``(nlat, nlon)`` of
    0.0/1.0 with ascending latitudes.  Nearest-neighbour on the sphere is exact
    enough for T21 smoke runs; area-weighted fractions are a later refinement.
    """
    from scipy.spatial import cKDTree  # noqa: PLC0415

    cells = _mesh_arrays(mesh_path)
    # NOTE: mesh.cell_xyz is NOT aligned with mesh.cells ordering (verified
    # 2026-10-06: 97.8% of directions disagree) — build the tree from the
    # cells' own lat/lon instead.
    xyz = _unit_vectors(cells["lat"], cells["lon"])
    is_land = cells["is_land"]
    tree = cKDTree(xyz)

    lat = gaussian_latitudes(nlat)
    lon = uniform_longitudes(nlon)
    lon_r = np.radians(lon)
    lat_r = np.radians(lat)
    # grid points as unit vectors; file order handled by write_sra
    gx = np.cos(lat_r)[:, None] * np.cos(lon_r)[None, :]
    gy = np.cos(lat_r)[:, None] * np.sin(lon_r)[None, :]
    gz = np.sin(lat_r)[:, None] * np.ones_like(lon_r)[None, :]
    _, idx = tree.query(np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1))
    mask = is_land[idx].astype(float).reshape(nlat, nlon)
    return mask, float(is_land.mean())


def make_landmap(
    mesh_path: str | Path, out_path: str | Path, nlat: int = 32, nlon: int = 64
) -> tuple[Path, float]:
    """Write the land-mask ``.sra`` for a mesh; returns ``(path, land_fraction)``."""
    mask, frac = land_mask_from_mesh(mesh_path, nlat, nlon)
    return write_sra(out_path, KCODE_LAND_MASK, mask, nlat, nlon), frac


def grid_land_elevation(
    lat: np.ndarray,
    lon: np.ndarray,
    area: np.ndarray,
    elevation: np.ndarray,
    is_land: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """Area-weighted mean land elevation (m) per Gaussian grid box (pure function).

    Box edges are the midpoints between Gaussian latitudes (poles at ±90°) and
    the uniform longitude spacing centred on each grid longitude.  Only land
    cells contribute, so coastal boxes are not dragged down by sea level;
    negative land elevations (depressions) count as 0.  Boxes the ``mask``
    marks as land but that contain no land cell (the nearest-cell mask and the
    box average can disagree at coasts) take the nearest land cell's
    elevation.  Ocean boxes are 0.  Returns ``(nlat, nlon)`` with ascending
    latitudes, the same layout as ``mask``.
    """
    from scipy.spatial import cKDTree  # noqa: PLC0415

    nlat, nlon = mask.shape
    glat = gaussian_latitudes(nlat)
    lat_edges = np.concatenate([[-90.0], 0.5 * (glat[1:] + glat[:-1]), [90.0]])
    dlon = 360.0 / nlon
    land_elev = np.clip(elevation[is_land], 0.0, None)
    land_lat, land_lon, land_area = lat[is_land], lon[is_land] % 360.0, area[is_land]
    ilat = np.clip(np.searchsorted(lat_edges, land_lat, side="right") - 1, 0, nlat - 1)
    ilon = np.floor((land_lon + 0.5 * dlon) / dlon).astype(int) % nlon
    flat = ilat * nlon + ilon
    weight = np.bincount(flat, weights=land_area, minlength=nlat * nlon)
    total = np.bincount(flat, weights=land_area * land_elev, minlength=nlat * nlon)
    mean = np.divide(total, weight, out=np.zeros_like(total), where=weight > 0)
    out = mean.reshape(nlat, nlon)

    empty = (mask > 0.5) & (weight.reshape(nlat, nlon) == 0)
    if empty.any() and land_elev.size:
        tree = cKDTree(_unit_vectors(land_lat, land_lon))
        glon = uniform_longitudes(nlon)
        jlat, jlon = np.nonzero(empty)
        _, idx = tree.query(_unit_vectors(glat[jlat], glon[jlon]))
        out[jlat, jlon] = land_elev[idx]
    return np.where(mask > 0.5, out, 0.0)


def make_topomap(
    mesh_path: str | Path,
    out_path: str | Path,
    gravity_m_s2: float,
    nlat: int = 32,
    nlon: int = 64,
) -> tuple[Path, dict[str, float]]:
    """Write the surface-geopotential ``.sra`` (code 129, m²/s²) for a mesh.

    Geopotential = ``gravity_m_s2`` × grid-box mean land elevation (see
    :func:`grid_land_elevation`), 0 over ocean, on the same land mask as
    :func:`make_landmap` so the two files agree box by box.  ExoPlaSim's
    shipped Earth file uses the same unit (max ≈ 4.77e4 m²/s² ≈ 4.9 km).
    Returns ``(path, stats)`` with the land-box mean and maximum elevation (m).
    """
    mask, _ = land_mask_from_mesh(mesh_path, nlat, nlon)
    cells = _mesh_arrays(mesh_path)
    elev = grid_land_elevation(
        cells["lat"], cells["lon"], cells["area"], cells["elevation"], cells["is_land"], mask
    )
    land = mask > 0.5
    w = np.cos(np.radians(gaussian_latitudes(nlat)))[:, None] * np.ones((1, nlon))
    stats = {
        "mean_land_elevation_m": float((elev * w)[land].sum() / w[land].sum())
        if land.any()
        else 0.0,
        "max_elevation_m": float(elev.max()),
    }
    path = write_sra(out_path, KCODE_GEOPOTENTIAL, gravity_m_s2 * elev, nlat, nlon)
    return path, stats


__all__: Sequence[str] = (
    "KCODE_GEOPOTENTIAL",
    "KCODE_LAND_MASK",
    "gaussian_latitudes",
    "grid_land_elevation",
    "land_mask_from_mesh",
    "make_landmap",
    "make_topomap",
    "uniform_longitudes",
    "write_sra",
)
