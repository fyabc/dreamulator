"""Heightmap importer — decode elevation from external tool exports.

Supports formats commonly produced by terrain design tools (Gaea, World Machine,
Photoshop):

- 16-bit PNG (single-channel grayscale)
- 16-bit TIFF (integer)
- 32-bit float TIFF (Gaea native output)

All formats are normalised to a float64 array in [0, 1] and optionally resampled
to the project's target resolution.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 16-bit quantisation constant
_UINT16_MAX_F = 65535.0


@dataclass
class ImportResult:
    """Result of importing a heightmap file."""

    elevation: np.ndarray  # 2-D float64 array in [0, 1]
    source_width: int
    source_height: int
    source_format: str  # e.g. "png-16bit", "tiff-float32", "tiff-uint16"
    was_resampled: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_heightmap(
    data: bytes,
    *,
    filename: str = "",
    target_width: int | None = None,
    target_height: int | None = None,
) -> ImportResult:
    """Import a heightmap from raw file bytes.

    The function auto-detects the format from the file header and decodes to a
    normalised [0, 1] float64 array.  If *target_width* / *target_height* are
    given and differ from the source resolution, the array is resampled via
    bilinear interpolation.

    Args:
        data: Raw file bytes.
        filename: Original filename (used for format hint if header detection
            is ambiguous).
        target_width: Desired output width (resampled if different).
        target_height: Desired output height (resampled if different).

    Returns:
        ImportResult with the decoded elevation and metadata.

    Raises:
        ValueError: If the file format is unrecognised or the data is corrupt.
    """
    fmt, elevation = _decode(data, filename)
    src_h, src_w = elevation.shape

    was_resampled = False
    if target_width and target_height and (target_width, target_height) != (src_w, src_h):
        elevation = _resample(elevation, target_width, target_height)
        was_resampled = True

    return ImportResult(
        elevation=elevation,
        source_width=src_w,
        source_height=src_h,
        source_format=fmt,
        was_resampled=was_resampled,
    )


# ---------------------------------------------------------------------------
# Format detection and decoding
# ---------------------------------------------------------------------------


# Magic bytes for common image formats
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_TIFF_LE_MAGIC = b"II\x2a\x00"  # little-endian TIFF
_TIFF_BE_MAGIC = b"MM\x00\x2a"  # big-endian TIFF
_TIFF_BIGTIFF_LE = b"II\x2b\x00"  # BigTIFF little-endian
_TIFF_BIGTIFF_BE = b"MM\x00\x2b"  # BigTIFF big-endian


def _detect_format(data: bytes) -> str:
    """Detect image format from magic bytes."""
    if data[:8] == _PNG_MAGIC:
        return "png"
    if data[:4] in (_TIFF_LE_MAGIC, _TIFF_BE_MAGIC, _TIFF_BIGTIFF_LE, _TIFF_BIGTIFF_BE):
        return "tiff"
    # Fallback: check extension hint
    return "unknown"


def _decode(data: bytes, filename: str) -> tuple[str, np.ndarray]:
    """Decode file bytes to (format_label, normalised_2d_array)."""
    fmt = _detect_format(data)

    if fmt == "png":
        return _decode_png(data)
    elif fmt == "tiff":
        return _decode_tiff(data)
    else:
        # Try PNG first, then TIFF, then give up
        try:
            return _decode_png(data)
        except Exception:
            pass
        try:
            return _decode_tiff(data)
        except Exception:
            pass
        ext = Path(filename).suffix.lower() if filename else ""
        raise ValueError(
            f"Unsupported heightmap format (bytes={data[:16]!r}, extension={ext!r}). "
            "Supported formats: 16-bit PNG, 16-bit TIFF, 32-bit float TIFF."
        )


def _decode_png(data: bytes) -> tuple[str, np.ndarray]:
    """Decode a PNG heightmap to normalised [0, 1]."""
    buf = io.BytesIO(data)
    img = Image.open(buf)

    if img.mode == "I;16":
        arr = np.array(img, dtype=np.uint16).astype(np.float64) / _UINT16_MAX_F
        fmt_label = "png-16bit"
    elif img.mode == "I":
        arr = np.array(img, dtype=np.float64)
        arr_max = arr.max()
        if arr_max > _UINT16_MAX_F:
            arr = arr / arr_max if arr_max > 0 else arr
        else:
            arr = arr / _UINT16_MAX_F
        fmt_label = "png-32bit"
    elif img.mode == "L":
        arr = np.array(img, dtype=np.float64) / 255.0
        fmt_label = "png-8bit"
        logger.warning("Importing 8-bit PNG — precision is limited to 256 levels")
    else:
        gray = img.convert("L")
        arr = np.array(gray, dtype=np.float64) / 255.0
        fmt_label = "png-converted"
        logger.warning("Converting multi-channel PNG to grayscale")

    return fmt_label, np.clip(arr, 0.0, 1.0)


def _decode_tiff(data: bytes) -> tuple[str, np.ndarray]:
    """Decode a TIFF heightmap to normalised [0, 1].

    Uses the ``tifffile`` library for reliable handling of 16-bit integer and
    32-bit float TIFF files produced by Gaea, World Machine, etc.
    """
    import tifffile

    buf = io.BytesIO(data)
    arr = tifffile.imread(buf)

    if arr.ndim == 3:
        # Multi-channel TIFF — take the first channel
        arr = arr[:, :, 0]
        logger.warning("Multi-channel TIFF detected — using first channel only")

    if arr.ndim != 2:
        raise ValueError(f"Expected 2-D TIFF array, got shape {arr.shape}")

    dtype = arr.dtype
    if np.issubdtype(dtype, np.floating):
        # 32-bit or 64-bit float TIFF — values should already be in [0, 1]
        # but some tools output in arbitrary ranges, so normalise if needed
        arr = arr.astype(np.float64)
        vmin, vmax = float(arr.min()), float(arr.max())
        if vmin < 0.0 or vmax > 1.0:
            logger.info(
                "Float TIFF range [%.4f, %.4f] — normalising to [0, 1]",
                vmin,
                vmax,
            )
            rng = vmax - vmin
            arr = (arr - vmin) / rng if rng > 0 else np.zeros_like(arr)
        fmt_label = f"tiff-float{dtype.itemsize * 8}"
    elif dtype == np.uint16:
        arr = arr.astype(np.float64) / _UINT16_MAX_F
        fmt_label = "tiff-uint16"
    elif dtype == np.uint8:
        arr = arr.astype(np.float64) / 255.0
        fmt_label = "tiff-uint8"
        logger.warning("8-bit TIFF — precision is limited to 256 levels")
    elif dtype == np.int16:
        # Some tools use signed 16-bit; shift to unsigned range
        arr = (arr.astype(np.float64) + 32768.0) / _UINT16_MAX_F
        fmt_label = "tiff-int16"
    elif dtype == np.uint32:
        arr = arr.astype(np.float64) / 4294967295.0
        fmt_label = "tiff-uint32"
    else:
        # Last resort: cast and normalise
        arr = arr.astype(np.float64)
        vmin, vmax = float(arr.min()), float(arr.max())
        rng = vmax - vmin
        arr = (arr - vmin) / rng if rng > 0 else np.zeros_like(arr)
        fmt_label = f"tiff-{dtype}"

    return fmt_label, np.clip(arr, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


def _resample(
    elevation: np.ndarray,
    target_width: int,
    target_height: int,
) -> np.ndarray:
    """Resample a 2-D elevation array to the target resolution.

    Uses PIL's high-quality LANCZOS resampling for downsampling and BILINEAR
    for upsampling.

    Args:
        elevation: 2-D float64 array in [0, 1].
        target_width: Desired width in pixels.
        target_height: Desired height in pixels.

    Returns:
        Resampled 2-D float64 array in [0, 1].
    """
    src_h, src_w = elevation.shape

    # Convert to 16-bit for PIL (preserves precision during resampling)
    quantised = (np.clip(elevation, 0.0, 1.0) * _UINT16_MAX_F).astype(np.uint16)
    img = Image.fromarray(quantised, mode="I;16")

    is_downscale = (target_width < src_w) or (target_height < src_h)
    resample = Image.LANCZOS if is_downscale else Image.BILINEAR

    img_resized = img.resize((target_width, target_height), resample)
    result = np.array(img_resized, dtype=np.uint16).astype(np.float64) / _UINT16_MAX_F

    logger.info(
        "Resampled heightmap: %dx%d → %dx%d (%s)",
        src_w,
        src_h,
        target_width,
        target_height,
        "LANCZOS" if is_downscale else "BILINEAR",
    )
    return result
