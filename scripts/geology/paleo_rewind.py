#!/usr/bin/env python3
"""Rewind a world's plates to earlier times (geological timeline M1 diagnostic).

Reads a built planet map (mesh + ``plates.json``) without changing it, then:

1. synthesizes a present-day seafloor age field from the ridges and the plate
   Euler poles (``dreamulator.map.paleo_kinematics.synthesize_seafloor_age``);
2. for each requested epoch, drops ocean younger than the epoch, rotates every
   remaining crust parcel back about its plate's present Euler pole, and
   resamples onto the same mesh (``rewind``);
3. derives crust type, age and elevation at that epoch (``paleo_fields``), using
   the world's own ocean age-depth parameters from ``terrain_config.yaml``.

By default the plates are first converted to the reconstruction model
(``--plate-model blocks``, ``reconstruction_plates``): continental blocks stay
rigid and split only where a present convergent boundary cuts them through, and
every plate's Euler pole is refitted to the present velocity field; ridges are
then the plate-boundary ocean cells that open.  ``--plate-model present`` uses
the map's own plates and its divergent boundary flags (right for the earth map,
whose plates and boundaries are PB2002 observations).

M1 holds the Euler poles fixed, fills gaps with old ocean and keeps continental
elevation unchanged; see
``docs/design/proposals/geological-timeline.md`` §4 and §10.

Outputs into ``--out-dir``: ``summary.json`` (age statistics, passive-margin
ages, and per epoch the land, gap, overlap and dropped areas), one
``epoch_<t>.npz`` per epoch, and with ``--plot`` ``seafloor_age.png``,
``age_area.png`` and ``epochs.png``.

``--observed-age`` checks the synthetic age against an observed age grid (a
netCDF ``lon``/``lat``/``z`` grid in Myr, e.g. Seton et al. 2020,
https://www.earthbyte.org/webdav/ftp/earthbyte/agegrid/2020/Grids/age.2020.1.GeeK2007.6m.nc;
needs the ``validation`` extra for netCDF4).  Use it on the earth map, whose
plates and boundaries are PB2002 observations; the summary gains an
``observed_age`` block and ``--plot`` adds ``age_vs_observed.png``.

Usage::

    uv run python scripts/geology/paleo_rewind.py \
        data/worlds/nacrea/maps/satellite_nacrea --out-dir /tmp/paleo --plot
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from dreamulator.map.export import find_mesh_file, load_cvt_mesh_model
from dreamulator.map.paleo_kinematics import (
    PaleoFields,
    PlateKinematics,
    RewoundState,
    adjacency_csr,
    boundary_cells,
    paleo_fields,
    reconstruction_plates,
    rewind,
    ridge_half_rates,
    synthesize_seafloor_age,
)
from dreamulator.map.pipeline_types import TerrainPipelineConfig, lonlat_to_xyz

DEFAULT_EPOCHS = (0.0, 10.0, 20.0, 40.0, 60.0, 80.0, 100.0)


class World:
    """Present-day mesh and plates as flat arrays, plus the fields M1 needs."""

    def __init__(self, map_dir: Path) -> None:
        path = find_mesh_file(map_dir)
        if path is None:
            raise SystemExit(f"no mesh file in {map_dir}")
        cells = load_cvt_mesh_model(path).cells
        plates = json.loads((map_dir / "plates.json").read_text(encoding="utf-8"))
        if isinstance(plates, dict):
            plates = plates["plates"]
        self.plate_ids: list[str] = [p["id"] for p in plates]
        index = {pid: k for k, pid in enumerate(self.plate_ids)}
        omega = np.array(
            [
                [ep["x"], ep["y"], ep["z"]]
                for ep in (p.get("euler_pole") or {"x": 0, "y": 1, "z": 0} for p in plates)
            ],
            dtype=float,
        )
        omega *= np.array([(p.get("euler_pole") or {}).get("omega_rad_yr", 0.0) for p in plates])[
            :, None
        ]

        self.lon = np.array([c.lon for c in cells])
        self.lat = np.array([c.lat for c in cells])
        x, y, z = lonlat_to_xyz(self.lon, self.lat)
        xyz = np.column_stack([x, y, z])
        area = np.array([c.area_km2 for c in cells])
        missing = [c.plate_id for c in cells if c.plate_id not in index]
        if missing:
            raise SystemExit(f"{len(missing)} cells reference plates missing from plates.json")
        ptr, idx = adjacency_csr([list(c.neighbors) for c in cells])
        self.kin = PlateKinematics(
            xyz=xyz,
            nbr_ptr=ptr,
            nbr_idx=idx,
            plate=np.array([index[str(c.plate_id)] for c in cells], dtype=np.int64),
            omega=omega,
            continental=np.array([c.crust_type == "continental" for c in cells]),
            area_km2=area,
            # the cell areas tile the sphere, so they fix the radius without metadata
            radius_km=float(np.sqrt(area.sum() / (4 * np.pi))),
        )
        self.elevation = np.array([c.elevation for c in cells], dtype=float)
        self.divergent = np.array([c.boundary_type == "divergent" for c in cells])
        self.convergent = np.array([c.boundary_type == "convergent" for c in cells])


def ocean_params(map_dir: Path, config_path: Path | None) -> dict[str, float]:
    """Ocean age-depth parameters: the world's terrain_config, else engine defaults."""
    d = TerrainPipelineConfig()
    params = {
        "ridge_depth_m": d.ocean_ridge_depth_m,
        "subsidence_coeff": d.ocean_subsidence_coeff,
        "max_depth_m": d.ocean_max_age_depth_m,
    }
    if config_path is None:
        # data/worlds/<world>/maps/<map> → data/worlds/<world>/layers/geological/input
        guess = map_dir.parent.parent / "layers" / "geological" / "input" / "terrain_config.yaml"
        config_path = guess if guess.exists() else None
    if config_path is not None:
        ocean = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("ocean", {})
        params["ridge_depth_m"] = float(ocean.get("ridge_depth_m", params["ridge_depth_m"]))
        params["subsidence_coeff"] = float(
            ocean.get("subsidence_coeff", params["subsidence_coeff"])
        )
        params["max_depth_m"] = float(ocean.get("max_age_depth_m", params["max_depth_m"]))
    return params


def weighted_percentiles(values: np.ndarray, weights: np.ndarray, qs: list[float]) -> list[float]:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w) / w.sum()
    return [float(np.interp(q / 100.0, cum, v)) for q in qs]


def age_summary(w: World, age: np.ndarray, half: np.ndarray) -> dict[str, Any]:
    kin = w.kin
    ocean = ~kin.continental
    aged = ocean & np.isfinite(age)
    qs = [50.0, 90.0, 99.0]
    pct = weighted_percentiles(age[aged], kin.area_km2[aged], qs)
    ridges = np.isfinite(half)
    # Passive margins: oceanic cells touching continental crust of the same plate.
    margin = np.zeros(kin.n, dtype=bool)
    for i in np.flatnonzero(aged):
        nb = kin.neighbors(int(i))
        margin[i] = bool(np.any(kin.continental[nb] & (kin.plate[nb] == kin.plate[i])))
    out: dict[str, Any] = {
        "ridge_cells": int(ridges.sum()),
        "half_rate_cm_yr_p10_50_90": [
            round(float(v), 2) for v in np.percentile(half[ridges], [10, 50, 90])
        ]
        if ridges.any()
        else [],
        "ocean_area_constrained_frac": round(
            float(kin.area_km2[aged].sum() / kin.area_km2[ocean].sum()), 4
        ),
        "age_myr_area_p50_p90_p99": [round(v, 1) for v in pct],
        "age_myr_max": round(float(np.nanmax(age)), 1),
    }
    if margin.any():
        out["passive_margin_age_myr_p10_50_90"] = [
            round(v, 1)
            for v in weighted_percentiles(age[margin], kin.area_km2[margin], [10, 50, 90])
        ]
    return out


def epoch_summary(w: World, st: RewoundState, f: PaleoFields) -> dict[str, Any]:
    a = w.kin.area_km2
    total = a.sum()
    cont0 = a[w.kin.continental].sum()
    return {
        "t_myr": st.t_myr,
        "land_frac": round(float(a[f.elevation_m > 0].sum() / total), 4),
        "continental_area_ratio": round(float(a[f.continental].sum() / cont0), 4),
        "gap_frac": round(float(a[st.gap].sum() / total), 4),
        "overlap_frac": round(float(a[st.overlap].sum() / total), 4),
        "dropped_ocean_frac": round(float(a[st.dropped].sum() / total), 4),
    }


def sample_observed_age(path: Path, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Nearest-node sample of a regular lon/lat age grid (NaN where masked)."""
    import netCDF4

    with netCDF4.Dataset(path) as ds:
        glon = np.asarray(ds.variables["lon"][:], dtype=float)
        glat = np.asarray(ds.variables["lat"][:], dtype=float)
        z = np.ma.filled(ds.variables["z"][:].astype(float), np.nan)
    ix = np.clip(np.rint((lon - glon[0]) / (glon[1] - glon[0])).astype(int), 0, glon.size - 1)
    iy = np.clip(np.rint((lat - glat[0]) / (glat[1] - glat[0])).astype(int), 0, glat.size - 1)
    sampled: np.ndarray = z[iy, ix]
    return sampled


def observed_summary(w: World, age: np.ndarray, obs: np.ndarray) -> dict[str, Any]:
    both = np.isfinite(age) & np.isfinite(obs)
    a, o, wt = age[both], obs[both], w.kin.area_km2[both]
    err = a - o
    ocean_obs = np.isfinite(obs)
    by_bin = {}
    for lo, hi in ((0, 20), (20, 50), (50, 100), (100, 200)):
        s = (o >= lo) & (o < hi)
        if s.any():
            by_bin[f"{lo}-{hi}"] = {
                "median_synthetic_myr": round(weighted_percentiles(a[s], wt[s], [50])[0], 1),
                "median_abs_err_myr": round(
                    weighted_percentiles(np.abs(err[s]), wt[s], [50])[0], 1
                ),
            }
    return {
        "cells_compared": int(both.sum()),
        "observed_ocean_covered_frac": round(
            float(w.kin.area_km2[both].sum() / w.kin.area_km2[ocean_obs].sum()), 4
        ),
        "pearson_r": round(float(np.corrcoef(a, o)[0, 1]), 3),
        "median_err_myr": round(weighted_percentiles(err, wt, [50])[0], 1),
        "median_abs_err_myr": round(weighted_percentiles(np.abs(err), wt, [50])[0], 1),
        "by_observed_age": by_bin,
    }


def plot_observed(w: World, age: np.ndarray, obs: np.ndarray, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    both = np.isfinite(age) & np.isfinite(obs)
    s = max(0.05, 2.0e4 / w.kin.n)
    fig, axes = plt.subplots(1, 3, figsize=(18, 4.8), gridspec_kw={"width_ratios": [2, 2, 1.2]})
    for ax, field, title in ((axes[0], age, "synthetic"), (axes[1], obs, "observed")):
        ok = np.isfinite(field)
        sc = ax.scatter(
            w.lon[ok], w.lat[ok], s=s, c=field[ok], cmap="turbo_r", vmin=0, vmax=200, lw=0
        )
        ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", title=f"{title} age (Myr)")
    fig.colorbar(sc, ax=axes[:2], shrink=0.8)
    axes[2].hexbin(obs[both], age[both], gridsize=60, extent=(0, 200, 0, 200), mincnt=1, bins="log")
    axes[2].plot([0, 200], [0, 200], "k--", lw=0.8)
    axes[2].set(xlabel="observed (Myr)", ylabel="synthetic (Myr)", xlim=(0, 200), ylim=(0, 200))
    fig.savefig(out / "age_vs_observed.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot(
    w: World,
    age: np.ndarray,
    slices: list[tuple[RewoundState, PaleoFields]],
    out: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kin = w.kin
    s = max(0.05, 2.0e4 / kin.n)

    fig, ax = plt.subplots(figsize=(13, 6.5))
    ax.scatter(w.lon[kin.continental], w.lat[kin.continental], s=s, c="0.75", lw=0)
    unc = ~kin.continental & ~np.isfinite(age)
    ax.scatter(w.lon[unc], w.lat[unc], s=s, c="0.45", lw=0)
    aged = np.isfinite(age)
    sc = ax.scatter(w.lon[aged], w.lat[aged], s=s, c=age[aged], cmap="turbo_r", lw=0)
    fig.colorbar(sc, ax=ax, shrink=0.8, label="synthetic seafloor age (Myr)")
    ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xlabel="lon", ylabel="lat")
    ax.set_title("Synthetic seafloor age (light grey: continent, dark grey: unconstrained ocean)")
    fig.savefig(out / "seafloor_age.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    bins = np.arange(0.0, float(np.nanmax(age)) + 10.0, 5.0).tolist()
    ax.hist(age[aged], bins=bins, weights=kin.area_km2[aged] / 1e6, color="tab:blue")
    ax.set(xlabel="age (Myr)", ylabel="ocean area per 5 Myr (M km²)")
    ax.set_title("Seafloor area by age")
    fig.savefig(out / "age_area.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    ncol = 2
    nrow = (len(slices) + 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(13, 3.4 * nrow), squeeze=False)
    for ax, (st, f) in zip(axes.ravel(), slices, strict=False):
        z = np.clip(f.elevation_m, -6000, 4000)
        ax.scatter(w.lon, w.lat, s=s, c=z, cmap="terrain", vmin=-6000, vmax=4000, lw=0)
        ax.scatter(w.lon[st.gap], w.lat[st.gap], s=s, c="red", lw=0)
        ax.scatter(w.lon[st.overlap], w.lat[st.overlap], s=s, c="magenta", lw=0)
        ax.set(xlim=(-180, 180), ylim=(-90, 90), aspect="equal", xticks=[], yticks=[])
        ax.set_title(f"−{st.t_myr:g} Myr  (red: gap, magenta: overlap)", fontsize=9)
    for ax in axes.ravel()[len(slices) :]:
        ax.axis("off")
    fig.savefig(out / "epochs.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map_dir", type=Path, help="planet map dir (mesh + plates.json)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--epochs", type=float, nargs="+", default=list(DEFAULT_EPOCHS))
    ap.add_argument("--terrain-config", type=Path, default=None)
    ap.add_argument("--min-opening-cm-yr", type=float, default=0.2)
    ap.add_argument("--plate-model", choices=("blocks", "present"), default="blocks")
    ap.add_argument("--observed-age", type=Path, default=None, help="netCDF age grid (Myr)")
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    w = World(args.map_dir)
    params = ocean_params(args.map_dir, args.terrain_config)
    model: dict[str, Any] = {"kind": args.plate_model}
    divergent = w.divergent
    if args.plate_model == "blocks":
        rp = reconstruction_plates(w.kin, w.convergent)
        a = w.kin.area_km2
        moved = rp.plate != w.kin.plate
        model |= {
            "continental_blocks": int(rp.block.max()) + 1,
            "reassigned_area_frac": round(float(a[moved].sum() / a.sum()), 4),
            "velocity_misfit_cm_yr_p50_p90": [
                round(float(v), 2) for v in weighted_percentiles(rp.misfit_cm_yr, a, [50, 90])
            ],
        }
        w.kin = replace(w.kin, plate=rp.plate, omega=rp.omega)
        divergent = boundary_cells(w.kin)
    half, offset = ridge_half_rates(w.kin, divergent, args.min_opening_cm_yr)
    age, _ = synthesize_seafloor_age(w.kin, half, offset)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "map_dir": str(args.map_dir),
        "cells": w.kin.n,
        "radius_km": round(w.kin.radius_km, 2),
        "spacing_km": round(w.kin.spacing_km, 1),
        "ocean_params": params,
        "plate_model": model,
        "present": age_summary(w, age, half),
        "epochs": [],
    }
    obs = None
    if args.observed_age is not None:
        obs = sample_observed_age(args.observed_age, w.lon, w.lat)
        summary["observed_age"] = observed_summary(w, age, obs)
        print(json.dumps(summary["observed_age"], indent=2, ensure_ascii=False))
    slices: list[tuple[RewoundState, PaleoFields]] = []
    for t in sorted(args.epochs):
        st = rewind(w.kin, age, t)
        f = paleo_fields(w.kin, st, w.elevation, age, **params)
        slices.append((st, f))
        summary["epochs"].append(epoch_summary(w, st, f))
        np.savez_compressed(
            args.out_dir / f"epoch_{t:g}.npz",
            plate=f.plate,
            continental=f.continental,
            age_myr=f.age_myr,
            elevation_m=f.elevation_m,
            gap=st.gap,
            overlap=st.overlap,
        )
        print(json.dumps(summary["epochs"][-1], ensure_ascii=False))
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary["present"], indent=2, ensure_ascii=False))
    if args.plot:
        plot(w, age, slices, args.out_dir)
        if obs is not None:
            plot_observed(w, age, obs, args.out_dir)


if __name__ == "__main__":
    main()
