"""Summarise an ExoPlaSim NetCDF run into comparable diagnostics.

Extracts the quantities the offline-oracle comparisons need (jet latitude and
strength, Hadley-cell poleward boundary via the mass streamfunction, thermal
gradients, eddy variance) from a postprocessed ``MOST.?????.nc`` file.  Pure
netCDF4 + numpy; no ExoPlaSim import.

Conventions:

- ``ua``/``va`` are (time, lev, lat, lon) in m/s on the model's sigma levels;
  the *lowest* model level is the last ``lev`` index (sigma closest to 1).
- The Hadley boundary is the first sign change of the Eulerian mass
  streamfunction poleward of the cell core at the level of maximum
  overturning (ported from the PoC ``analyse_streamfunction.py`` fix —
  the velocity-potential ``psi`` variable must not be used; its zero line
  tracks the ITCZ, not the cell boundary).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import netCDF4
import numpy as np

_G = 9.80665  # m/s²; only affects streamfunction *magnitude*, not its sign
_2PI = 2.0 * np.pi

# A wind field whose maximum stays below this is "dead" — the signature of a
# unit/config bug (the 2026-10-05 radius bug produced ~1e-5 m/s).
WIND_ALIVE_THRESHOLD_MS = 1.0


def _tail(a: np.ndarray, n: int, axis: int = 0) -> np.ndarray:
    n = min(n, a.shape[axis])
    return a[-n:]


def mass_streamfunction(
    va: np.ndarray,
    ps: np.ndarray,
    lat_deg: np.ndarray,
    levp: np.ndarray,
    radius_m: float,
    gravity: float = _G,
) -> np.ndarray:
    """Eulerian meridional mass streamfunction ``Psi(lev, lat)`` in kg/s.

    ``va`` (t, lev, lat, lon) m/s and ``ps`` (t, lat, lon) hPa are time-means
    or single records; ``levp`` are the half-level sigmas (nlev+1 values).
    """
    vbar = np.mean(va, axis=2)  # (lev, lat)
    psbar = np.mean(ps, axis=1) * 100.0  # (lat,) Pa
    dsigma = np.diff(levp)  # (lev,)
    cosphi = np.cos(np.radians(lat_deg))
    flux = vbar * psbar[None, :] * dsigma[:, None]
    psi = (2.0 * _2PI * radius_m / gravity) * cosphi[None, :] * np.cumsum(flux, axis=0)
    return np.asarray(psi)


def hadley_boundary_deg(lat_deg: np.ndarray, psi: np.ndarray) -> float:
    """Poleward Hadley-cell edge (degrees) in the northern hemisphere.

    Returns 90.0 when the streamfunction keeps one sign all the way to the
    pole (single-cell regime expected for slow rotators).
    """
    north = lat_deg > 0
    lat_n = lat_deg[north]
    psi_n = psi[:, north]
    core = int(np.argmin(np.abs(lat_n - 15.0)))
    lev = int(np.argmax(np.abs(psi_n[:, core])))
    psi_core = psi_n[lev]
    s = float(np.sign(psi_core[core]))
    if s == 0.0:
        return 90.0
    for i in range(core - 1, -1, -1):  # scan poleward (lat descending)
        if np.sign(psi_core[i]) != s:
            return abs(float(lat_n[i + 1]))
    return 90.0


def summarize(
    nc_path: str | Path,
    *,
    radius_m: float = 6.37122e6,
    gravity: float = _G,
    tail_records: int = 6,
) -> dict[str, Any]:
    """Extract the oracle-comparison diagnostics from one run.

    ``radius_m``/``gravity`` should match the mapped ExoPlaSim parameters
    (they set physical units of the streamfunction only).
    """
    ds = netCDF4.Dataset(str(nc_path))
    try:
        lat = np.asarray(ds.variables["lat"])  # already degrees (units: deg)
        ua = np.asarray(ds.variables["ua"][:])
        va = np.asarray(ds.variables["va"][:])
        ta = np.asarray(ds.variables["ta"][:])
        out: dict[str, Any] = {
            "nc": str(nc_path),
            "n_records": int(ua.shape[0]),
        }

        ua_t = _tail(ua, tail_records)
        va_t = _tail(va, tail_records)
        ta_t = _tail(ta, tail_records)

        out["max_abs_ua_ms"] = float(np.abs(ua).max())
        out["max_abs_va_ms"] = float(np.abs(va).max())
        out["eddy_std_ua_ms"] = float(ua_t.std(axis=0).max())

        u_zm = np.mean(ua_t, axis=(0, 3))  # (lev, lat)
        jlev, jlat = np.unravel_index(np.argmax(u_zm), u_zm.shape)
        out["jet_speed_ms"] = float(u_zm[jlev, jlat])
        out["jet_lat_deg"] = float(lat[jlat])

        t_zm = np.mean(ta_t, axis=(0, 3))
        i_eq = int(np.argmin(np.abs(lat)))
        out["t_eq_c"] = float(t_zm[:, i_eq].mean() - 273.15)
        out["t_pole_c"] = float(0.5 * (t_zm[:, 0].mean() + t_zm[:, -1].mean()) - 273.15)
        out["t_global_c"] = float(ta_t.mean() - 273.15)

        if "levp" in ds.variables and "ps" in ds.variables:
            levp = np.asarray(ds.variables["levp"][:])
            ps_t = _tail(np.asarray(ds.variables["ps"][:]), tail_records)
            psi = mass_streamfunction(
                np.mean(va_t, axis=0),
                np.mean(ps_t, axis=0),
                lat,
                levp,
                radius_m,
                gravity,
            )
            out["hadley_boundary_deg"] = hadley_boundary_deg(lat, psi)
            out["psi_max_kgs"] = float(np.abs(psi).max())

        out["wind_alive"] = out["max_abs_ua_ms"] > WIND_ALIVE_THRESHOLD_MS
        return out
    finally:
        ds.close()


__all__ = [
    "WIND_ALIVE_THRESHOLD_MS",
    "hadley_boundary_deg",
    "mass_streamfunction",
    "summarize",
]
