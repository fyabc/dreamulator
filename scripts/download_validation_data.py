#!/usr/bin/env python3
"""Pre-download all climate validation reference data.

Downloads ETOPO1 elevation (~400 MB) and Beck et al. (2018) Koppen map
(~68 MB) to the system temp directory, where they are cached and reused
by ``import_earth_elevation.py`` and ``convert_koppen_map.py``, plus a
SODA v3.15.2 surface-current monthly climatology (~690 MB streamed via
OPeNDAP, folded to a ~19 MB netCDF under ``private/tmp/climatology/``)
consumed by ``import_earth_climate.py``.

Usage::

    uv run python scripts/download_validation_data.py          # download all
    uv run python scripts/download_validation_data.py --dry-run  # show what would be downloaded
    uv run python scripts/download_validation_data.py --skip-soda  # skip the (slow) SODA stream

After download, the following commands can run offline:

    uv run python scripts/import_earth_elevation.py --skip-download
    uv run python scripts/convert_koppen_map.py --tif <cached_zip>
    uv run python scripts/import_earth_climate.py
    uv run dreamulator climate validate earth --spatial

The download respects ``HTTPS_PROXY`` / ``HTTP_PROXY`` environment variables
(configured via ``settings.local.json`` in the project root).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

# ── ETOPO1 ────────────────────────────────────────────────────────────

_ETOPO1_URL = (
    "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/data/"
    "ice_surface/grid_registered/netcdf/ETOPO1_Ice_g_gmt4.grd.gz"
)
_ETOPO1_SIZE_MB = 400


def _download(url: str, dest: Path, label: str, size_mb: int) -> None:
    """Download *url* to *dest* with progress reporting."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    opener = urlopen
    if proxy:
        from urllib.request import ProxyHandler, build_opener

        handler = ProxyHandler({"https": proxy, "http": proxy})
        opener = build_opener(handler).open

    req = Request(url, headers={"User-Agent": f"dreamulator/{_version()}"})
    print(f"  Downloading {label} ({size_mb} MB) …")
    with opener(req, timeout=300) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    mb = downloaded / (1024 * 1024)
                    print(
                        f"\r  {mb:5.0f} / {total / (1024 * 1024):.0f} MB ({pct:.0f}%)",
                        end="",
                        flush=True,
                    )
    print()


def _version() -> str:
    try:
        from importlib.metadata import version as _v

        return _v("dreamulator")
    except Exception:
        return "0.0.0"


# ── SODA surface currents (APDRC OPeNDAP) ────────────────────────────

_SODA_DAP_URL = "http://apdrc.soest.hawaii.edu/dods/public_data/SODA/soda_3.15.2/monthly_u"
_SODA_START_YEAR = 1980  # dataset time axis: Jan 1980 onward, monthly (516 months)
_SODA_CLIM_YEARS = (1993, 2022)  # altimetry era used for the climatology
_SODA_SURFACE_LEVEL = 0  # lev[0] ≈ 5 m — the near-surface level
_SODA_DEST_RELPATH = "private/tmp/climatology/soda_currents_mon_clim.nc"
_SODA_SIZE_MB = 690  # approx. DAP transfer for surface u+v over 30 years


def download_soda_current_climatology(dest: Path) -> None:
    """Build a 12-month SODA v3.15.2 surface-current climatology via OPeNDAP.

    Streams monthly surface u/v (lev 0, ~5 m) year by year from the APDRC
    GrADS-DAP server — the DAP hyperslab keeps each transfer to ~11 MB per
    variable-year — and folds them into per-calendar-month means.  Output is
    a small netCDF: u/v (month 1–12, lat, lon) float32 m/s on SODA's native
    0.5° grid (lat −74.5..90, lon 0.5..360), NaN over land/ice and the
    uncovered far-southern ocean.

    Reference: Carton, Chepurin & Chen (2018), J. Climate 31:6967–6983,
    doi:10.1175/JCLI-D-18-0149.1 (SODA3); v3.15.2 datadoc at
    http://apdrc.soest.hawaii.edu/datadoc/soda_3.15.2.php.
    """
    import numpy as np
    import xarray as xr

    # libcurl (netCDF4's DAP backend) honours only the *lowercase* http_proxy
    # variable for http:// URLs; project env sets HTTP_PROXY (uppercase).
    if os.environ.get("HTTP_PROXY") and not os.environ.get("http_proxy"):
        os.environ["http_proxy"] = os.environ["HTTP_PROXY"]

    y0, y1 = _SODA_CLIM_YEARS
    t_end = (y1 - _SODA_START_YEAR + 1) * 12

    print(f"  Opening {_SODA_DAP_URL} …")
    with xr.open_dataset(_SODA_DAP_URL) as ds:
        n_time = ds.sizes["time"]
        if t_end > n_time:
            raise RuntimeError(
                f"SODA time axis shorter than expected ({n_time} < {t_end} months) — "
                "check _SODA_START_YEAR/_SODA_CLIM_YEARS against the dataset"
            )
        lat = np.asarray(ds["lat"].values, dtype=np.float64)
        lon = np.asarray(ds["lon"].values, dtype=np.float64)

        sums_u = np.zeros((12, len(lat), len(lon)), dtype=np.float64)
        sums_v = np.zeros_like(sums_u)
        cnt_u = np.zeros_like(sums_u, dtype=np.int32)
        cnt_v = np.zeros_like(sums_u, dtype=np.int32)

        for year in range(y0, y1 + 1):
            s = (year - _SODA_START_YEAR) * 12
            sl = slice(s, s + 12)
            u: np.ndarray | None = None
            v: np.ndarray | None = None
            for attempt in range(3):
                try:
                    u = np.asarray(ds["u"].isel(lev=_SODA_SURFACE_LEVEL, time=sl).values)
                    v = np.asarray(ds["v"].isel(lev=_SODA_SURFACE_LEVEL, time=sl).values)
                    break
                except OSError as exc:  # DAP transport hiccup — retry the year
                    if attempt == 2:
                        raise
                    print(f"    {year} attempt {attempt + 1} failed ({exc}); retrying…", flush=True)
            assert u is not None and v is not None
            fu, fv = np.isfinite(u), np.isfinite(v)
            sums_u += np.where(fu, u, 0.0)
            sums_v += np.where(fv, v, 0.0)
            cnt_u += fu
            cnt_v += fv
            print(f"    {year} accumulated ({year - y0 + 1}/{y1 - y0 + 1})", flush=True)

    clim_u = np.where(cnt_u > 0, sums_u / np.maximum(cnt_u, 1), np.nan).astype(np.float32)
    clim_v = np.where(cnt_v > 0, sums_v / np.maximum(cnt_v, 1), np.nan).astype(np.float32)

    dest.parent.mkdir(parents=True, exist_ok=True)
    out = xr.Dataset(
        {"u": (("month", "lat", "lon"), clim_u), "v": (("month", "lat", "lon"), clim_v)},
        coords={"month": np.arange(1, 13), "lat": lat, "lon": lon},
        attrs={
            "title": "SODA v3.15.2 surface (~5 m) ocean-current monthly climatology",
            "source": _SODA_DAP_URL,
            "climatology_years": f"{y0}-{y1}",
            "units": "m/s",
            "month_convention": "1=January (observation order, NOT the engine's March-first)",
            "reference": (
                "Carton, Chepurin & Chen (2018) J. Climate 31:6967-6983 "
                "doi:10.1175/JCLI-D-18-0149.1"
            ),
        },
    )
    out.to_netcdf(dest)
    print(f"[OK] SODA currents climatology saved: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


# ── main ──────────────────────────────────────────────────────────────


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    skip_soda = "--skip-soda" in sys.argv

    tmp = Path(tempfile.gettempdir())

    # 1. ETOPO1 elevation
    etopo_dir = tmp / "dreamulator_etopo1"
    etopo_gz = etopo_dir / "ETOPO1_Ice_g_gmt4.grd.gz"
    if etopo_gz.exists() and etopo_gz.stat().st_size > 1_000_000:
        print(f"[OK] ETOPO1 cached: {etopo_gz}")
    elif dry_run:
        print(f"→ ETOPO1 (will download ~{_ETOPO1_SIZE_MB} MB): {_ETOPO1_URL}")
    else:
        etopo_dir.mkdir(exist_ok=True)
        _download(_ETOPO1_URL, etopo_gz, "ETOPO1", _ETOPO1_SIZE_MB)
        print(f"[OK] ETOPO1 saved: {etopo_gz}")

    # 2. Beck et al. (2018) Koppen map (figshare ZIP)
    beck_dir = tmp / "dreamulator_koppen"
    beck_zip = beck_dir / "Beck_KG_V1.zip"
    beck_url = "https://ndownloader.figshare.com/files/12407516"
    beck_size = 68
    if beck_zip.exists() and beck_zip.stat().st_size > 1_000_000:
        print(f"[OK] Beck Koppen cached: {beck_zip}")
    elif dry_run:
        print(f"→ Beck Koppen (will download ~{beck_size} MB): {beck_url}")
    else:
        beck_dir.mkdir(exist_ok=True)
        _download(beck_url, beck_zip, "Beck Koppen", beck_size)
        print(f"[OK] Beck Koppen saved: {beck_zip}")

    # 3. SODA surface-current monthly climatology (import_earth_climate reads
    #    it for the observed ocean currents; falls back to the Stommel solver
    #    when absent).
    soda_nc = Path(__file__).resolve().parent.parent / _SODA_DEST_RELPATH
    if skip_soda:
        print("[--] SODA currents skipped (--skip-soda)")
    elif soda_nc.exists() and soda_nc.stat().st_size > 1_000_000:
        print(f"[OK] SODA currents climatology cached: {soda_nc}")
    elif dry_run:
        print(f"→ SODA currents (will stream ~{_SODA_SIZE_MB} MB via OPeNDAP): {_SODA_DAP_URL}")
    else:
        download_soda_current_climatology(soda_nc)

    print()
    if dry_run:
        print("Dry run complete. Run without --dry-run to download.")
    else:
        print("All validation data ready. You can now run:")
        print("  uv run python scripts/import_earth_elevation.py --skip-download")
        print("  uv run python scripts/convert_koppen_map.py")
        print("  uv run python scripts/import_earth_climate.py")
        print("  uv run dreamulator climate validate earth --spatial")


if __name__ == "__main__":
    main()
