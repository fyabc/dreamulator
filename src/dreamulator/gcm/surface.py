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


def land_mask_from_mesh(mesh_path: str | Path, nlat: int, nlon: int) -> tuple[np.ndarray, float]:
    """Nearest-cell regrid of a dreamulator CVT mesh land mask to the Gaussian grid.

    Returns ``(mask, land_fraction)`` where ``mask`` is ``(nlat, nlon)`` of
    0.0/1.0 with ascending latitudes.  Nearest-neighbour on the sphere is exact
    enough for T21 smoke runs; area-weighted fractions are a later refinement.
    """
    from scipy.spatial import cKDTree  # noqa: PLC0415

    from dreamulator.map.export import load_cvt_mesh_model  # noqa: PLC0415

    mesh = load_cvt_mesh_model(Path(mesh_path))
    # NOTE: mesh.cell_xyz is NOT aligned with mesh.cells ordering (verified
    # 2026-10-06: 97.8% of directions disagree) — build the tree from the
    # cells' own lat/lon instead.
    lat_c = np.radians(np.array([c.lat for c in mesh.cells], dtype=float))
    lon_c = np.radians(np.array([c.lon for c in mesh.cells], dtype=float))
    xyz = np.stack(
        [np.cos(lat_c) * np.cos(lon_c), np.cos(lat_c) * np.sin(lon_c), np.sin(lat_c)],
        axis=1,
    )
    is_land = np.asarray([str(c.water_class) != "ocean" for c in mesh.cells])
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


__all__: Sequence[str] = (
    "KCODE_GEOPOTENTIAL",
    "KCODE_LAND_MASK",
    "gaussian_latitudes",
    "land_mask_from_mesh",
    "make_landmap",
    "uniform_longitudes",
    "write_sra",
)
