#!/usr/bin/env python3
"""Fetch 2D ASCII climatology slices from the LMD planetary climate databases'
registration-free web interfaces (MCD = Mars, VCD = Venus).

The full NetCDF archives require email registration (LMD team); the public web
form (``mcd_python`` / ``vcd_python``) generates **2D ASCII slices** on demand.
This script automates the recipe proven on 2026-09-20/21 (Mars: 36 files;
Venus: same architecture):

    POST {base}/cgi-bin/{db}cgi.py        (Referer: {base}/)
        var1=<var>  var2=  datekeyhtml=1  ls=<bin centre>  localtime=12.
        latitude=-90 90  longitude=0 360  zkey=3  altitude=1.  dust=1
        hrkey=0  averaging=loct  zonmean=off  diumean=off  animation=off
        proj=cyl  colorm=jet  dpi=80

    → response HTML contains ``<a href='../txt/<hash>.txt'>``; GET that file.

``averaging=loct`` = diurnal mean over all local times (verified via the ASCII
header comment) — **MCD only**: the VCD CGI hangs indefinitely on ``loct``
(observed 2026-09-21), so Venus fetches use ``--averaging off`` with a fixed
``--localtime`` slice (declared in the world's provenance; Venus' surface
diurnal range is negligible under the 92-bar atmosphere).  Files are saved as
``{prefix}_ls{NNN}.txt``; existing files are skipped (resume-friendly).  Be
polite: 2.5 s between requests; ``--max-time`` guards against silent hangs.

Usage:
    uv run python scripts/solar/fetch_lmd_slices.py --db mcd --var t \
        --prefix mcd_t --out-dir private/tmp/solar/mars
    uv run python scripts/solar/fetch_lmd_slices.py --db vcd --var tsurf \
        --prefix vcd_tsurf --out-dir private/tmp/solar/venus
"""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path

_BASES = {
    "mcd": "https://www-mars.lmd.jussieu.fr/mcd_python",
    "vcd": "http://www-venus.lmd.jussieu.fr/vcd_python",
}
_LS_CENTERS = [15 + 30 * m for m in range(12)]
_TXT_HREF = re.compile(r"href=['\"]\.\./txt/([0-9a-f]+)\.txt['\"]")


def _curl(args: list[str], max_time: int = 300, proxy: str | None = None) -> bytes:
    # --max-time is essential: the VCD CGI silently hangs forever on some
    # parameter combinations (averaging=loct observed 2026-09-21).
    # Proxy is explicit (--proxy) or via curl's own HTTP(S)_PROXY env handling;
    # never hardcode a local proxy address here.
    attempts = []
    if proxy:
        attempts.append(["curl", "-sSL", "--max-time", str(max_time), "--proxy", proxy, *args])
    attempts.append(["curl", "-sSL", "--max-time", str(max_time), *args])
    r = subprocess.run(attempts[0], capture_output=True)
    if r.returncode != 0 and len(attempts) > 1:
        # Retry without explicit proxy (env may already provide one).
        r = subprocess.run(attempts[1], capture_output=True)
    r.check_returncode()
    return r.stdout


def fetch_slice(
    base: str,
    cgi: str,
    var: str,
    ls: int,
    extra: dict[str, str],
    averaging: str = "loct",
    localtime: str = "12.",
    max_time: int = 300,
    proxy: str | None = None,
) -> bytes:
    fields = {
        "var1": var,
        "var2": "",
        "datekeyhtml": "1",
        "ls": str(ls),
        "localtime": localtime,
        "latitude": "-90 90",
        "longitude": "0 360",
        "zkey": "3",
        "altitude": "1.",
        "dust": "1",
        "hrkey": "0",
        "averaging": averaging,
        "zonmean": "off",
        "diumean": "off",
        "animation": "off",
        "proj": "cyl",
        "colorm": "jet",
        "dpi": "80",
        **extra,
    }
    data = "&".join(f"{k}={v.replace(' ', '+')}" for k, v in fields.items())
    html = _curl(
        [
            "-X",
            "POST",
            "-H",
            f"Referer: {base}/",
            "-H",
            "Content-Type: application/x-www-form-urlencoded",
            "--data",
            data,
            f"{base}/cgi-bin/{cgi}",
        ],
        max_time=max_time,
        proxy=proxy,
    ).decode("utf-8", errors="replace")
    m = _TXT_HREF.search(html)
    if m is None:
        raise RuntimeError(f"Ls={ls}: no txt link in response ({len(html)} B HTML)")
    return _curl([f"{base}/txt/{m.group(1)}.txt"], max_time=max_time, proxy=proxy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", choices=sorted(_BASES), required=True)
    parser.add_argument("--var", required=True, help="variable code (see listvar.js)")
    parser.add_argument("--prefix", required=True, help="output filename prefix")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--extra",
        default="",
        help="extra POST fields as k=v,k=v (e.g. albedo_scena=1 for VCD)",
    )
    parser.add_argument(
        "--averaging",
        default="loct",
        help="loct = diurnal mean (MCD, verified); VCD hangs on loct — use off "
        "(2026-09-21) with a fixed --localtime slice instead",
    )
    parser.add_argument("--localtime", default="12.")
    parser.add_argument("--max-time", type=int, default=300, help="curl timeout per request")
    parser.add_argument("--sleep", type=float, default=2.5)
    parser.add_argument(
        "--proxy",
        default=None,
        help="HTTP proxy for curl (e.g. http://127.0.0.1:PORT); curl also honors "
        "the HTTP(S)_PROXY env vars",
    )
    args = parser.parse_args()

    base = _BASES[args.db]
    extra = dict(kv.split("=", 1) for kv in args.extra.split(",") if kv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for ls in _LS_CENTERS:
        out = args.out_dir / f"{args.prefix}_ls{ls:03d}.txt"
        if out.exists() and out.stat().st_size > 10_000:
            print(f"  skip {out.name} (exists)")
            continue
        print(f"  fetching {args.var} @ Ls={ls} …", flush=True)
        raw = fetch_slice(
            base,
            f"{args.db}cgi.py",
            args.var,
            ls,
            extra,
            averaging=args.averaging,
            localtime=args.localtime,
            max_time=args.max_time,
            proxy=args.proxy,
        )
        header = "\n".join(raw.decode("utf-8", errors="replace").splitlines()[:12])
        if "MCD" not in header and "VCD" not in header and "Climate Database" not in header:
            raise RuntimeError(f"Ls={ls}: response is not an LMD ASCII slice:\n{header[:400]}")
        out.write_bytes(raw)
        print(f"    → {out.name} ({len(raw)} B)")
        time.sleep(args.sleep)
    print(f"Done: 12 × {args.var} in {args.out_dir}")


if __name__ == "__main__":
    main()
