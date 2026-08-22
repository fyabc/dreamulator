#!/usr/bin/env python3
"""Pre-download all climate validation reference data.

Downloads ETOPO1 elevation (~400 MB) and Beck et al. (2018) Koppen map
(~68 MB) to the system temp directory, where they are cached and reused
by ``import_earth_elevation.py`` and ``convert_koppen_map.py``.

Usage::

    uv run python scripts/download_validation_data.py          # download all
    uv run python scripts/download_validation_data.py --dry-run  # show what would be downloaded

After download, the following commands can run offline:

    uv run python scripts/import_earth_elevation.py --skip-download
    uv run python scripts/convert_koppen_map.py --tif <cached_zip>
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
                        f"\r  {mb:5.0f} / {total/(1024*1024):.0f} MB ({pct:.0f}%)",
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


# ── main ──────────────────────────────────────────────────────────────


def main() -> None:
    dry_run = "--dry-run" in sys.argv

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

    print()
    if dry_run:
        print("Dry run complete. Run without --dry-run to download.")
    else:
        print("All validation data ready. You can now run:")
        print("  uv run python scripts/import_earth_elevation.py --skip-download")
        print("  uv run python scripts/convert_koppen_map.py")
        print("  uv run dreamulator climate validate earth --spatial")


if __name__ == "__main__":
    main()
