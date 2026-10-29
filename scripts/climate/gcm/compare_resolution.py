"""Audit configured GCM contrasts with Gaussian areas and a common elapsed tail.

Example::

    python scripts/climate/gcm/compare_resolution.py \
        --run T42=archive/t42 --run T85=archive/t85 \
        --tail-days 3600 --out exports/mosaic/resolution-comparison

The first run is the reference. Regional contributions use positive spherical
overlap integrals on its grid. They describe differences rather than assign
causes. Native clear-sky fluxes, when present, separate cloud radiative effects
from clear-sky fluxes without disabling clouds in the integration.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib
import netCDF4
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from dreamulator.gcm.area_remap import gaussian_rectilinear_coverage  # noqa: E402
from dreamulator.gcm.diagnostics import equinox_day_from_declination  # noqa: E402
from dreamulator.gcm.native_partition import gaussian_parent_partition  # noqa: E402

FIELDS = [
    "tas",
    "rst",
    "rlut",
    "rsut",
    "clt",
    "alb",
    "sic",
    "prw",
    "rss",
    "rls",
    "prc",
    "prl",
    "rstcs",
    "rlutcs",
    "rsutcs",
    "rsscs",
]


def diffusion_decay_per_day(
    parameters: dict[str, Any], truncation: int, wavenumber: int
) -> dict[str, float]:
    """Linear diffusion rates on a common spherical-harmonic wavenumber."""
    n0 = parameters["critical_wavenumber"]
    scale = (max(0, wavenumber - n0) / (truncation - n0)) ** parameters["power"]
    return {
        key: scale / parameters[key + "_days"] for key in ["TDISST", "TDISSQ", "TDISSZ", "TDISSD"]
    }


def effective_parameters(run: Path) -> dict[str, Any]:
    """Read the parameters printed after Fortran's resolution-specific presets."""
    text = (run / "MOST_DIAG.00000").read_text(encoding="utf-8")
    block = re.search(r"&PLASIM_NL\b(.*?)/", text, re.S | re.I)
    if block is None:
        raise ValueError(f"No effective PLASIM_NL in {run}")
    fields = dict(re.findall(r"^\s*(\w+)\s*=\s*(.*?)\s*$", block[1], re.M))
    keys = [
        "MPSTEP",
        "NDEL",
        "NHDIFF",
        "TDISST",
        "TDISSQ",
        "TDISSZ",
        "TDISSD",
        "NFILTER",
        "NFILTEREXP",
        "FILTERKAPPA",
        "NGPTFILTER",
        "NSPVFILTER",
    ]
    result: dict[str, Any] = {k: fields[k].rstrip(" ,") for k in keys if k in fields}
    for key in ["TDISST", "TDISSQ", "TDISSZ", "TDISSD"]:
        # The diagnostic block precedes dayseccheck. Its explicit conversion
        # messages identify day-valued inputs; T42 presets are already seconds.
        token = fields[key].strip().split(",")[0].split("*")[-1]
        value = float(token)
        was_days = f"old maxval({key.lower()})" in text
        result[key + "_days"] = value if was_days else value / 86400
    result["power"] = int(fields["NDEL"].strip().split(",")[0].split("*")[-1])
    result["critical_wavenumber"] = int(fields["NHDIFF"].rstrip(" ,"))
    result["step_seconds"] = float(fields["MPSTEP"].rstrip(" ,")) * 60
    return result


def read_run(run: Path, window: tuple[float, float]) -> dict[str, Any]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    parameters = effective_parameters(run)
    with netCDF4.Dataset(run / "MOST.00000.nc") as ds:
        lat = np.asarray(ds["lat"][:], float)
        lon = np.asarray(ds["lon"][:], float)
        order = np.argsort(lat)
        lat = lat[order]
        _, weights = np.polynomial.legendre.leggauss(len(lat))
        area = weights[:, None] * np.ones((1, len(lon))) / (2 * len(lon))
        clock = np.asarray(ds["time"][:], float)
        days = clock * parameters["step_seconds"] / 86400
        selected = np.flatnonzero((days >= window[0]) & (days <= window[1]))
        year = manifest["params"]["year"]
        equinox = equinox_day_from_declination(
            clock,
            np.asarray(ds["zdec"][:], float),
            orbital_year_days=year,
            steps_per_model_day=86400 / parameters["step_seconds"],
        )
        phase = ((days - equinox) % year) / year
        bins = np.minimum((phase * 12).astype(int), 11)
        counts = np.bincount(bins[selected], minlength=12)
        if (counts == 0).any():
            raise ValueError(f"Tail lacks orbital seasons in {run}: {counts.tolist()}")
        temporal = 1 / (12 * counts[bins[selected]])
        fields, series = {}, {}
        for key in FIELDS:
            if key not in ds.variables:
                continue
            value = np.asarray(ds[key][selected], float)[:, order]
            if key == "tas":
                value -= 273.15
            elif key in ("prc", "prl"):
                value *= 1000 * 86400
            fields[key] = np.einsum("t,tij->ij", temporal, value)
            series[key] = np.sum(value * area, axis=(1, 2))
        fields["incoming"] = fields["rst"] - fields["rsut"]
        fields["ntr"] = fields["rst"] + fields["rlut"]
        if "rstcs" in fields:
            fields["sw_cre"] = fields["rst"] - fields["rstcs"]
            fields["lw_cre"] = fields["rlut"] - fields["rlutcs"]
        mask = np.asarray(ds["lsm"][0], float)[order]
        profiles = {}
        for key in ["cl", "hur", "clw"]:
            if key in ds.variables:
                value = np.asarray(ds[key][selected], float)[:, :, order]
                profiles[key] = np.einsum("t,tlij,ij->l", temporal, value, area).tolist()
        globals_ = {k: float(np.sum(v * area)) for k, v in fields.items()}
        truncation = int(manifest["model_options"]["resolution"].lstrip("T"))
        parameters["diffusion_decay_per_day"] = {
            str(n): diffusion_decay_per_day(parameters, truncation, n)
            for n in [20, 30, 40]
            if n <= truncation
        }
        if parameters.get("NFILTER") == "2":
            kappa = float(parameters["FILTERKAPPA"])
            power = int(parameters["NFILTEREXP"])
            parameters["exponential_filter_gain_per_transform"] = {
                str(n): float(np.exp(-kappa * (n / truncation) ** power))
                for n in [20, 30, 40]
                if n <= truncation
            }
        return {
            "path": str(run),
            "parameters": parameters,
            "manifest": manifest,
            "latitude": lat,
            "longitude": lon,
            "area": area,
            "fields": fields,
            "series": series,
            "days": days[selected],
            "phase_counts": counts.tolist(),
            "globals": globals_,
            "mask": mask,
            "profiles": profiles,
        }


def remap(source: dict[str, Any], target: dict[str, Any]) -> dict[str, np.ndarray]:
    partition = gaussian_parent_partition(
        source["latitude"],
        source["longitude"],
        radius_km=1,
        spacing_km=100,
    )
    mu, weights = np.polynomial.legendre.leggauss(len(target["latitude"]))
    del mu
    lat_edges = np.degrees(np.arcsin(np.clip(np.r_[-1, -1 + np.cumsum(weights)], -1, 1)))
    lat_edges[-1] = 90
    nlon = len(target["longitude"])
    lon_edges = (np.arange(nlon + 1) - 0.5) * 360 / nlon
    coverage = gaussian_rectilinear_coverage(partition, lat_edges, lon_edges)
    return {k: coverage.means(v.ravel()) for k, v in source["fields"].items()}


def compare(reference: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    fields = remap(other, reference)
    area = reference["area"]
    lat = reference["latitude"][:, None]
    difference = {k: fields[k] - reference["fields"][k] for k in fields}
    errors = {k: float(np.sum(fields[k] * area) - other["globals"][k]) for k in fields}
    regions = {
        "tropics_30S_30N": np.abs(lat) < 30,
        "midlatitudes_30_60": (np.abs(lat) >= 30) & (np.abs(lat) < 60),
        "polar_60_90": np.abs(lat) >= 60,
    }
    budget = {}
    for name, mask in regions.items():
        fraction = float(np.sum(area * mask))
        budget[name] = {
            "area_fraction": fraction,
            "contributions": {k: float(np.sum(v * area * mask)) for k, v in difference.items()},
        }
    a, b = reference["globals"], other["globals"]
    sa, sb = a["incoming"], b["incoming"]
    alpha, beta = -a["rsut"] / sa, -b["rsut"] / sb
    result = {
        "global_differences": {k: b[k] - a[k] for k in fields},
        "regional_budget": budget,
        "remap_integral_errors": errors,
        "absorbed_shortwave_accounting": {
            "incoming_term": (sb - sa) * (1 - (alpha + beta) / 2),
            "reflectance_term": -(beta - alpha) * (sa + sb) / 2,
        },
    }
    if "rstcs" in fields:
        result["clear_sky_accounting"] = {
            "sw_cre_difference": b["sw_cre"] - a["sw_cre"],
            "clear_asr_difference": b["rstcs"] - a["rstcs"],
            "lw_cre_difference": b["lw_cre"] - a["lw_cre"],
            "clear_lw_difference": b["rlutcs"] - a["rlutcs"],
        }
    return result


def plot(runs: dict[str, dict[str, Any]], output: Path) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    panels = [
        ("tas", "Near-surface temperature (°C)", 1),
        ("rst", "Absorbed shortwave (W/m²)", 1),
        ("clt", "Total cloud cover (%)", 100),
        ("sic", "Global-area sea ice (%)", 100),
        ("alb", "Surface albedo (%)", 100),
        ("prw", "Column water vapour (kg/m²)", 1),
    ]
    for ax, (key, title, scale) in zip(axes.flat, panels, strict=True):
        for label, run in runs.items():
            ax.plot(run["latitude"], run["fields"][key].mean(axis=1) * scale, label=label)
        ax.set_title(title)
        ax.set_xlabel("Latitude (°)")
        ax.set_xticks(np.arange(-90, 91, 30))
        ax.grid(alpha=0.25)
    axes[0, 0].legend()
    figure.savefig(output / "zonal-comparison.png", dpi=180)
    plt.close(figure)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="append", required=True, help="label=directory")
    ap.add_argument("--tail-days", type=float, default=3600)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    paths = {label: Path(path) for label, path in (value.split("=", 1) for value in args.run)}
    endpoints = []
    for path in paths.values():
        step = effective_parameters(path)["step_seconds"]
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        with netCDF4.Dataset(path / "MOST.00000.nc") as ds:
            # Fixed-duration controls declare interval edges. Native output
            # timestamps precede the final step, by different amounts at each
            # timestep; using that edge keeps identical five-day intervals.
            endpoints.append(
                manifest["model_options"].get(
                    "duration_24h_days",
                    float(ds["time"][-1]) * step / 86400,
                )
            )
    end = min(endpoints)
    window = (end - args.tail_days, end)
    runs = {label: read_run(path, window) for label, path in paths.items()}
    reference = next(iter(runs.values()))
    output = {
        "tail_24h_days": args.tail_days,
        "common_record_window_24h_days": window,
        "scope": (
            "common elapsed tail and equal orbital-phase bins; finite-area regional differences"
        ),
        "runs": {
            label: {
                key: run[key]
                for key in ["path", "parameters", "manifest", "globals", "phase_counts", "profiles"]
            }
            for label, run in runs.items()
        },
        "contrasts": {label: compare(reference, other) for label, other in list(runs.items())[1:]},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    plot(runs, args.out)
    print(json.dumps({label: run["globals"] for label, run in runs.items()}, indent=2))


if __name__ == "__main__":
    main()
