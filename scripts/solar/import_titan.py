#!/usr/bin/env python3
"""Import the Titan reference body (UCC-01 4d, earth anchor world): TAM hydrology.

Single consistent source: the TAM (Titan Atmospheric Model, Yale — Lora group)
coupled land-hydrology/atmosphere run, Zenodo 10.5281/zenodo.3473571
(CC-BY-4.0), file ``full_phys.hydro.k1e-5.y241-250.nc`` — T21 grid (64 lon ×
32 Gaussian lat, ~5.6°), 10 Titan years (2029 averaging windows):

- ``tsurf``  surface temperature (K) — with Titan's thick atmosphere the
  near-surface air ≈ surface; declared as the temperature input.
- ``precip`` total methane precipitation (kg/m²/s) → mm of **liquid CH₄**
  (ρ = 422.6 kg/m³), the physically honest depth of the solvent that falls.
- ``qsurf``  surface liquid methane (m) → time-mean > 0.05 m marks the methane
  seas/lakes as ``water_class="ocean"`` (~1.5% of the grid — consistent with
  the observed northern-lakes coverage); UCC then treats them like oceans
  (thermal band only, supply axis n/a, code letter ``o``).
- ``dtd``    topography used for runoff (m) — used as the elevation field
  (relative relief ~1.4 km; possibly datum-offset by the hydrology scheme,
  declared in provenance).

Time contract — the extreme case anticipated in the plan: 1 Titan year =
10756.5 Earth-days (Saturn orbit 29.46 yr); 12 bins ≈ 896.4 Earth-days each,
phase-anchored to (days-since-epoch mod Titan year).  Titan's *surface*
seasonal amplitude is ~1 K, so the phase choice is second-order (declared).

Demand model: **not applied** (demand_model=None → AI/deficit = missing_input).
Hamon is a liquid-*water* empirical formula; a methane solvent at 94 K is out
of its scope (knowledge doc §6).  The cold-side OOD gate would also fire
(t_max ≈ −178 °C < 0), but declaring "no demand model applies" is the stronger,
honester status.  Expected classes: land = Pn, seas = Po (polar band: every
bin-mean is far below the 10 °C node).

Epistemic status: ucc-review §6.2 **L4** — GCM climatology, a model, not
error-free truth.  Citation: Lora, Faulk, Mitchell & Milly (2019), Zenodo
10.5281/zenodo.3473571 (CC-BY-4.0).

Data cache: ``private/tmp/solar/titan_hydro_k1e-5_y241-250.nc`` (232 MB;
download from the Zenodo record when missing).

Usage:
    uv run python scripts/solar/import_titan.py [--mesh-nodes 3000]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

from dreamulator.import_solar_common import (  # noqa: E402
    apply_climate_to_mesh,
    build_mesh_from_dem,
    register_solar_planet,
    sample_regular_grid,
    write_climate_monthly,
    write_climate_secondary,
    write_ucc_yearly,
)

_CACHE = _ROOT / "private/tmp/solar"
_NC = "titan_hydro_k1e-5_y241-250.nc"
_NC_URL = "https://zenodo.org/records/3473571/files/full_phys.hydro.k1e-5.y241-250.nc"

TITAN_RADIUS_KM = 2574.7
TITAN_YEAR_DAYS = 10_756.5  # Saturn orbit 29.46 yr × 365.25
TITAN_BIN_DAYS = TITAN_YEAR_DAYS / 12.0
CH4_RHO_KG_M3 = 422.6  # liquid methane near the triple point
SEA_THRESHOLD_M = 0.05  # time-mean surface liquid marking methane seas


def _regularize(
    field: np.ndarray, lat_g: np.ndarray, out_shape: tuple[int, int] = (181, 360)
) -> np.ndarray:
    """Interpolate a (nlat, 64) Gaussian-lat × uniform-lon field onto a regular
    1° grid (rows 90N→90S, cols −180→179).  Polar caps beyond the Gaussian
    grid (±85.8°) clamp to the edge row — declared flat polar fill."""
    from scipy.interpolate import RegularGridInterpolator

    nlat, nlon = field.shape
    lon_g = np.arange(nlon) * (360.0 / nlon)
    # Wrap longitude: pad one column on each side.
    lon_ext = np.concatenate([[lon_g[0] - 360.0 / nlon], lon_g, [lon_g[-1] + 360.0 / nlon]])
    data_ext = np.concatenate([field[:, -1:], field, field[:, :1]], axis=1)
    itp = RegularGridInterpolator(
        (lat_g, lon_ext), data_ext, method="linear", bounds_error=False, fill_value=None
    )
    h, w = out_shape
    lats = np.linspace(90.0, -90.0, h)
    lons = np.linspace(-180.0, 180.0, w, endpoint=False) % 360.0
    lats_c = np.clip(lats, lat_g[0], lat_g[-1])
    pts = np.stack([np.repeat(lats_c, w), np.tile(lons, h)], axis=1)
    return itp(pts).reshape(h, w)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mesh scaled to the TAM T21 grid (~5.6°, 2048 points — every field: T,
    # precip, qsurf, topo): 3k cells ≈ 3.7° spacing, mild oversampling for
    # rendering without inventing detail the GCM doesn't have.
    parser.add_argument("--mesh-nodes", type=int, default=3_000)
    parser.add_argument("--data-dir", type=Path, default=_ROOT / "data/worlds")
    parser.add_argument("--proxy", default=None, help="HTTP proxy for curl downloads")
    args = parser.parse_args()

    nc_path = _CACHE / _NC
    if not nc_path.exists():
        print("Downloading TAM-hydro NetCDF (232 MB) from Zenodo …")
        import subprocess

        attempts = []
        if args.proxy:
            attempts.append(["curl", "-sSL", "--proxy", args.proxy, "-o", str(nc_path), _NC_URL])
        attempts.append(["curl", "-sSL", "-o", str(nc_path), _NC_URL])
        for cmd in attempts:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0 and nc_path.exists() and nc_path.stat().st_size > 100_000_000:
                break
            nc_path.unlink(missing_ok=True)
        if not nc_path.exists():
            raise RuntimeError(f"download failed: {_NC_URL}")

    import netCDF4

    print(f"Reading {nc_path} …")
    ds = netCDF4.Dataset(nc_path)
    lat_g = np.asarray(ds["lat"][:], dtype=np.float64)
    time_d = np.asarray(ds["time"][:], dtype=np.float64)
    dt_d = np.asarray(ds["average_DT"][:], dtype=np.float64)
    tsurf = np.asarray(ds["tsurf"][:], dtype=np.float64)  # (T, 32, 64) K
    precip = np.asarray(ds["precip"][:], dtype=np.float64)  # kg/m²/s
    qsurf = np.asarray(ds["qsurf"][:], dtype=np.float64)  # m
    dtd = np.asarray(ds["dtd"][:], dtype=np.float64)  # (32, 64) m

    # --- Bin the record into 12 Titan-year phase bins -----------------------
    phase = np.mod(time_d, TITAN_YEAR_DAYS)
    bin_idx = np.clip((phase // TITAN_BIN_DAYS).astype(int), 0, 11)
    t_bins = np.empty((12, *tsurf.shape[1:]))
    p_bins = np.zeros((12, *precip.shape[1:]))  # mm liquid CH4 per bin
    for b in range(12):
        m = bin_idx == b
        w = dt_d[m]
        t_bins[b] = np.average(tsurf[m], axis=0, weights=w)
        # Rate variable across ~10 occurrences of this phase bin: take the
        # DT-weighted MEAN rate, then × bin window seconds → kg/m² per bin →
        # mm liquid CH4.  (Summing over steps would multiply by the ~10 years
        # the record spans — each bin must be one climatological bin.)
        rate_bin = np.average(precip[m], axis=0, weights=w)
        p_bins[b] = rate_bin * (TITAN_BIN_DAYS * 86_400.0) * 1000.0 / CH4_RHO_KG_M3
    qsurf_mean = np.average(qsurf, axis=0, weights=dt_d)

    p_ann_kg = p_bins.sum(axis=0).mean() * CH4_RHO_KG_M3 / 1000.0
    print(
        f"  tsurf {tsurf.min():.1f}–{tsurf.max():.1f} K | precip annual "
        f"{p_ann_kg:.0f} kg/m² global-mean"
    )
    sea_frac = float((qsurf_mean > SEA_THRESHOLD_M).mean())
    print(f"  seas (qsurf_mean > {SEA_THRESHOLD_M} m): {sea_frac:.2%} of grid")

    # --- Regularize onto 1° grids (Gaussian lat → equidistant) --------------
    dem_reg = _regularize(dtd, lat_g)
    t_reg = np.stack([_regularize(t_bins[b], lat_g) for b in range(12)])
    p_reg = np.stack([_regularize(p_bins[b], lat_g) for b in range(12)])
    q_reg = _regularize(qsurf_mean, lat_g)
    reg_meta = {"lat_start": 90.0, "dlat": -1.0, "lon_start": -180.0, "dlon": 1.0}

    map_dir = register_solar_planet(args.data_dir, "satellite_titan")

    mesh = build_mesh_from_dem(
        dem_reg,
        **reg_meta,
        radius_km=TITAN_RADIUS_KM,
        num_nodes=args.mesh_nodes,
        output_dir=map_dir,
        planet_id="satellite_titan",
        source="TAM T21 topography `dtd` (Zenodo 10.5281/zenodo.3473571, CC-BY-4.0)",
        source_resolution="~5.6° GCM grid (runoff topography; possibly datum-offset)",
    )

    lats = np.array([c.lat for c in mesh.cells], dtype=np.float64)
    lons = np.array([c.lon for c in mesh.cells], dtype=np.float64)
    t_monthly = np.empty((mesh.num_cells, 12))
    p_monthly = np.empty((mesh.num_cells, 12))
    for b in range(12):
        # T: K → °C
        t_monthly[:, b] = sample_regular_grid(t_reg[b], **reg_meta, lats=lats, lons=lons) - 273.15
        p_monthly[:, b] = sample_regular_grid(p_reg[b], **reg_meta, lats=lats, lons=lons)
    q_cells = sample_regular_grid(q_reg, **reg_meta, lats=lats, lons=lons)
    water_class = np.where(q_cells > SEA_THRESHOLD_M, "ocean", "land").astype(str)
    n_sea = int((water_class == "ocean").sum())
    print(f"  Methane-sea cells: {n_sea}/{mesh.num_cells} ({n_sea / mesh.num_cells:.2%})")

    write_climate_monthly(
        map_dir,
        t_monthly,
        p_monthly,
        bin_days=TITAN_BIN_DAYS,
        month_0="titan_year_phase_0_arbitrary_anchor",
        extra_metadata={
            "time_basis": (
                f"12 bins of {TITAN_BIN_DAYS:.1f} Earth-days = 1 Titan year "
                f"({TITAN_YEAR_DAYS} d, Saturn orbit 29.46 yr); phase anchor = "
                "record day-number mod Titan year (surface seasons ~1 K — declared "
                "second-order)"
            ),
            "precipitation_units": "mm of liquid CH4 per bin (kg/m² ÷ 422.6 kg/m³)",
            "temperature_kind": "TAM tsurf (surface; near-surface air ≈ surface on Titan)",
        },
    )
    apply_climate_to_mesh(map_dir, t_monthly.mean(axis=1), p_monthly.sum(axis=1), water_class)
    write_climate_secondary(
        map_dir, source="TAM hydro run k1e-5 y241-250 (Zenodo 3473571) — see provenance"
    )

    combos = write_ucc_yearly(
        map_dir,
        data_source="gcm-climatology",
        provenance={
            "gcm": "TAM coupled land-hydrology/atmosphere (Lora, Faulk, Mitchell & "
            "Milly 2019; Zenodo 10.5281/zenodo.3473571, CC-BY-4.0), run "
            "full_phys.hydro.k1e-5, years 241–250 (10 Titan years, 2029 windows)",
            "temperature": "TAM `tsurf` (K→°C), DT-weighted bin means; 12 Titan-year "
            "phase bins (896.4 Earth-days each)",
            "precipitation": "TAM `precip` (methane, kg/m²/s) integrated per bin → mm "
            "liquid CH₄ (ρ=422.6 kg/m³); p_total per Titan year (10756.5 Earth-days)",
            "demand_model_note": "NOT applied — Hamon is a liquid-water formula; a "
            "methane solvent at 94 K is out of scope (knowledge doc §6). AI/deficit "
            "= missing_input by declaration (the cold-side OOD gate would also fire).",
            "seas": f"water_class=ocean where time-mean qsurf > {SEA_THRESHOLD_M} m "
            f"(methane seas/lakes, {n_sea} cells)",
            "topography": "TAM `dtd` runoff topography (~5.6° GCM grid; possibly "
            "datum-offset — relative relief only)",
            "epistemic_status": "L4 GCM climatology (ucc-review §6.2): a model, not "
            "error-free truth",
        },
        demand_model=None,
    )
    print("Land classes:", sorted(combos.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    main()
