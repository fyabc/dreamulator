"""Download Beck et al.'s Köppen-Geiger GeoTIFF maps (the 2023 dataset family).

The scorecard reports Earth Köppen agreement against both Beck et al. (2018,
Version 1, handled by ``download_validation_data.py``) and this newer dataset, so
the number is comparable with other implementations of this model class.

**Why a fixed file id rather than a file listing.** figshare's API and web pages
sit behind a challenge that refuses this network (HTTP 403 / 202), while its
download host ``ndownloader.figshare.com`` serves files normally.  The default id
below is the archive the dataset's own home page (``gloh2o.org/koppen``) links as
the current release; it holds GeoTIFFs for several periods and resolutions.  To
fetch a different file, open the figshare item in a browser, copy the numeric id
out of its download link and pass ``--file-id``.

Usage::

    uv run python scripts/earth/download_beck2023.py                 # download + extract
    uv run python scripts/earth/download_beck2023.py --contents      # list the archive
    uv run python scripts/earth/download_beck2023.py --period 1991_2020 --resolution 0p0833333

Downloads resume where a previous run stopped, so a dropped connection only costs
the remaining bytes.
"""

from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

#: Download host that works from here (the API host does not).
DOWNLOAD_URL = "https://ndownloader.figshare.com/files/{file_id}"

#: Current Köppen-Geiger GeoTIFF archive as linked from gloh2o.org/koppen
#: (``koppen_geiger_tif.zip``, about 131 MB).  The dataset paper is
#: Beck et al. (2023), Scientific Data, figshare item 21789074.
DEFAULT_FILE_ID = 61012822

#: Period and grid extracted by default: the recent historical map at 0.1°
#: (about 11 km), the closest grid to Version 1's 5 arc-minute (0.0833°) map and
#: well below the 51 km CVT cell spacing.  The archive also holds 0.00833333°
#: (1 km), 0.5° and 1.0°, and the periods 1901_1930, 1931_1960, 1961_1990,
#: 1991_2020 plus two future windows per SSP.
DEFAULT_PERIOD = "1991_2020"
DEFAULT_RESOLUTION = "0p1"

DEFAULT_OUT = Path.home() / "beck2023"

#: figshare rejects some default agents.
HEADERS = {"User-Agent": "Mozilla/5.0 (dreamulator validation data fetch)"}


def _request(url: str, offset: int = 0, method: str = "GET") -> urllib.request.Request:
    headers = dict(HEADERS)
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return urllib.request.Request(url, headers=headers, method=method)


def remote_size_and_name(url: str) -> tuple[int, str]:
    """Total size and server-suggested filename, from a one-byte range request."""
    try:
        with urllib.request.urlopen(_request(url, offset=0), timeout=120) as response:
            disposition = response.headers.get("content-disposition", "")
            length = int(response.headers.get("content-length", 0))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"figshare refused the request (HTTP {exc.code}) for {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach figshare: {exc.reason}") from exc
    match = re.search(r"filename=([^;]+)", disposition)
    name = match.group(1).strip().strip('"') if match else "koppen_geiger.zip"
    return length, name


def download(url: str, target: Path, total: int) -> Path:
    """Download ``url`` into ``target``, resuming a partial file."""
    done = target.stat().st_size if target.exists() else 0
    if total and done >= total:
        print(f"[OK] already complete: {target} ({total / 1e6:.1f} MB)")
        return target
    print(
        f"→ {'resuming' if done else 'downloading'} {target.name} "
        f"({done / 1e6:.1f} / {total / 1e6:.1f} MB)"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(_request(url, offset=done), timeout=180) as response,
        target.open("ab") as handle,
    ):
        while chunk := response.read(1 << 20):
            handle.write(chunk)
            done += len(chunk)
            print(f"\r   {done / 1e6:8.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print(f"\r[OK] saved {target} ({done / 1e6:.1f} MB)      ")
    return target


def extract(archive: Path, out_dir: Path, period: str, resolution: str) -> list[Path]:
    """Extract the chosen period and grid (plus any legend) from the archive."""
    written: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        entries = [name for name in bundle.namelist() if not name.endswith("/")]
        wanted = [
            name
            for name in entries
            if (name.startswith(f"{period}/") and Path(name).stem.endswith(resolution))
            or Path(name).name.lower().startswith(("legend", "readme"))
        ]
        if not wanted:
            listing = "\n  ".join(entries[:40])
            raise SystemExit(
                f"nothing in {archive.name} matches period {period!r} and resolution "
                f"{resolution!r}.  It holds:\n  {listing}\n"
                "Pick names from this listing with --period / --resolution, or run "
                "--contents to see them all."
            )
        for name in wanted:
            destination = out_dir / Path(name).name
            with bundle.open(name) as source, destination.open("wb") as handle:
                handle.write(source.read())
            written.append(destination)
            print(f"[OK] extracted {destination} ({destination.stat().st_size / 1e6:.1f} MB)")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id", type=int, default=DEFAULT_FILE_ID, help="figshare file id")
    parser.add_argument("--period", default=DEFAULT_PERIOD, help="period to extract")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION, help="grid to extract")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="target directory")
    parser.add_argument("--contents", action="store_true", help="list the archive's files and stop")
    args = parser.parse_args()

    url = DOWNLOAD_URL.format(file_id=args.file_id)
    total, name = remote_size_and_name(url)
    archive = download(url, args.out / name, total)

    if args.contents:
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not entry.filename.endswith("/"):
                    print(f"{entry.file_size / 1e6:9.1f} MB  {entry.filename}")
        return

    extracted = extract(archive, args.out, args.period, args.resolution)
    print("\nready for the importer; the files are:")
    for path in extracted:
        print(f"  {path}")
    print(f"\npass this directory on: {args.out}")


if __name__ == "__main__":
    main()
