#!/usr/bin/env python3
"""Generate a zonal-mean reference from CHELSA-TraCE21k LGM GeoTIFFs.

Turns the annual bioclimatic GeoTIFFs (``bio01`` annual mean temperature and
``bio12`` annual precipitation) into 2° zonal-mean arrays for LGM validation.

The input GeoTIFFs are 30 arc-sec (1 km) global grids (20880 × 43200), so the
script streams them strip-by-strip (one latitude row per strip) rather than
loading the full ~3.6 GB float32 raster into memory.

Download the LGM time slice (``-190`` = -21 000 BP; 100-year steps, time_bp =
(yr_id − 20) × 100) from the CHELSA-TraCE21k S3 bucket::

    https://os.zhdk.cloud.switch.ch/chelsav1/chelsa_trace/bio/CHELSA_TraCE21k_bio01_-190_V1.0.tif
    https://os.zhdk.cloud.switch.ch/chelsav1/chelsa_trace/bio/CHELSA_TraCE21k_bio12_-190_V1.0.tif

(``bio01`` = annual mean temperature, ``bio12`` = annual precipitation.)

Usage::

    uv run python scripts/generate_lgm_reference.py \
        --temp private/tmp/climatology/lgm/bio01_-190.tif \
        --precip private/tmp/climatology/lgm/bio12_-190.tif \
        --time-bp -21000 \
        --output tests/validation/reference/lgm_zonal_reference.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tifffile

# 2° bands 90N .. 88S (90 values), matching _ZONAL_TEMP_REF indexing in
# validate_climate.py: array[0]=90N, array[45]=0, array[89]=88S.
_N_BANDS = 90
_BAND_LATS = np.array([90.0 - 2.0 * i for i in range(_N_BANDS)])
_NODATA = -3.4e38


def _zonal_mean_2deg(path: Path) -> tuple[np.ndarray, dict[str, float]]:
    """Return (zonal_mean[90], stats) for a striped 1-km GeoTIFF.

    Streams one row-strip at a time, masks the GDAL nodata sentinel, and bins
    row means into 2° latitude bands (90N → 88S).  Bands north of the raster's
    top edge stay NaN.
    """
    band_sum = np.zeros(_N_BANDS, dtype=np.float64)
    band_cnt = np.zeros(_N_BANDS, dtype=np.int64)
    all_vals_sum = 0.0
    all_vals_cnt = 0
    lat0: float | None = None
    dlat: float | None = None

    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        nrows, _ncols = page.shape
        for t in page.tags:
            if t.name == "ModelPixelScaleTag":
                dlat = float(t.value[1])
            elif t.name == "ModelTiepointTag":
                lat0 = float(t.value[4])
        if lat0 is None or dlat is None:
            raise SystemExit(f"No georeferencing found in {path}")

        for r, seg in enumerate(page.segments()):
            data = np.asarray(seg[0], dtype=np.float32).ravel()
            valid = data > _NODATA / 2.0  # mask the -3.4e38 nodata sentinel
            row_mean = float(np.mean(data[valid])) if valid.any() else np.nan
            lat = lat0 - r * dlat
            band = int(np.clip(np.round((90.0 - lat) / 2.0), 0, _N_BANDS - 1))
            if np.isfinite(row_mean):
                band_sum[band] += row_mean
                band_cnt[band] += 1
                all_vals_sum += row_mean
                all_vals_cnt += 1
            if r + 1 >= nrows:
                break

    zonal = np.full(_N_BANDS, np.nan, dtype=np.float64)
    nz = band_cnt > 0
    zonal[nz] = band_sum[nz] / band_cnt[nz]
    stats = {
        "global_mean": all_vals_sum / max(all_vals_cnt, 1),
        "zonal_min": float(np.nanmin(zonal)),
        "zonal_max": float(np.nanmax(zonal)),
        "n_rows": nrows,
        "n_valid_bands": int(nz.sum()),
    }
    return zonal, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp", required=True, help="bio01 annual mean temp GeoTIFF")
    parser.add_argument("--precip", required=True, help="bio12 annual precip GeoTIFF")
    parser.add_argument("--time-bp", type=int, default=-21000, help="Time slice in years BP")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    print("Computing temperature zonal mean (bio01) ...")
    temp, temp_stats = _zonal_mean_2deg(Path(args.temp))
    print(f"  global mean = {temp_stats['global_mean']:.2f} °C, "
          f"zonal range = {temp_stats['zonal_min']:.1f} .. {temp_stats['zonal_max']:.1f}, "
          f"{temp_stats['n_valid_bands']}/{_N_BANDS} bands")

    print("Computing precipitation zonal mean (bio12) ...")
    precip, precip_stats = _zonal_mean_2deg(Path(args.precip))
    print(f"  global mean = {precip_stats['global_mean']:.0f} mm/yr, "
          f"zonal range = {precip_stats['zonal_min']:.0f} .. {precip_stats['zonal_max']:.0f}, "
          f"{precip_stats['n_valid_bands']}/{_N_BANDS} bands")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "description": "CHELSA-TraCE21k LGM annual zonal-mean climatology at 2° bands "
            "(90N→88S; bands north of 84N are NaN — raster top edge)",
            "time_bp": args.time_bp,
            "lat_bands_deg": _BAND_LATS.tolist(),
            "temperature_c": [None if np.isnan(v) else round(float(v), 2) for v in temp],
            "precipitation_mm_yr": [None if np.isnan(v) else round(float(v), 1) for v in precip],
            "sources": {
                "temperature": "CHELSA-TraCE21k bio01 (annual mean temperature)",
                "precipitation": "CHELSA-TraCE21k bio12 (annual precipitation)",
            },
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON saved: {out}")


if __name__ == "__main__":
    main()
