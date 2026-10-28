"""Prepare a separate S1 input batch with fixed accepted TD statistics.

Continuous source corrections are integrated by the source caller. This IO
step adds their footprint means to the frozen float32 S3 condition, records
the encoded coarse field and its statistical reference, and copies the
unchanged climate channels. The original input batch stays available.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from typing import TYPE_CHECKING, Any

import numpy as np

from .td_canvas_worker import validate_coarse_statistics

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_refined_canvas(
    reference_canvas: Path,
    output_canvas: Path,
    correction_m: np.ndarray,
    coarse_field: Path,
    coarse_reference: Path,
    *,
    source: dict[str, Any],
    quadrature: int,
    query_prefix: Sequence[tuple[int, int]] = (),
) -> Path:
    """Write an isolated, reviewable input batch using an integrated source delta.

    The supplied six-channel TD field includes the new mean and the accepted
    mean-minus-p5 spread, with the four encoded climate channels unchanged.
    Source metadata describes the geometry, reference stages and integration.
    """
    if output_canvas.exists():
        raise FileExistsError("refinement output must be a new input batch")
    if not source or quadrature < 1:
        raise ValueError("refinement needs source provenance and a positive quadrature order")
    meta_path = reference_canvas / "canvas.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ncell = int(meta["geometry"]["ncell"])
    pad = int(meta["generation"]["edge_padding_cells"])
    height_path = reference_canvas / "conditioning/heightmap.npy"
    height = np.load(height_path)
    delta = np.asarray(correction_m, dtype=np.float64)
    if height.dtype != np.float32 or height.shape != (ncell, ncell):
        raise ValueError("reference height must use the canvas's float32 footprint grid")
    if delta.shape != height.shape or not np.isfinite(delta).all():
        raise ValueError("source correction must be finite and match the footprint grid")
    for name, digest in meta["conditioning_sha256"].items():
        if _sha(reference_canvas / "conditioning" / f"{name}.npy") != digest:
            raise ValueError(f"reference conditioning checksum mismatch: {name}")
    candidate, reference = np.load(coarse_field), np.load(coarse_reference)
    expected = (6, ncell + 2 * pad, ncell + 2 * pad)
    if candidate.shape != expected or reference.shape != expected:
        raise ValueError("coarse field shape does not match the padded canvas")
    validate_coarse_statistics(candidate, reference)
    chunk_cells = int(meta["geometry"].get("chunk_cells", 8))
    if any(min(c) < 0 or (max(c) + 1) * chunk_cells > ncell for c in query_prefix):
        raise ValueError("query prefix must lie within the reference canvas's footprint grid")
    new_height = (height.astype(np.float64) + delta).astype(np.float32)
    if not np.isfinite(new_height).all():
        raise ValueError("corrected height exceeds the finite float32 range")
    output_canvas.mkdir(parents=True)
    for name in ("conditioning", "climate", "geometry_fields"):
        origin = reference_canvas / name
        if origin.exists():
            shutil.copytree(origin, output_canvas / name)
    np.save(output_canvas / "conditioning/heightmap.npy", new_height)
    geometry = output_canvas / "geometry_fields"
    geometry.mkdir(exist_ok=True)
    np.save(geometry / "height_correction_m.npy", delta)
    sources = output_canvas / "coarse_source"
    sources.mkdir()
    shutil.copy2(coarse_field, sources / "field.npy")
    shutil.copy2(coarse_reference, sources / "reference.npy")
    meta = copy.deepcopy(meta)
    meta["conditioning_sha256"]["heightmap"] = _sha(output_canvas / "conditioning/heightmap.npy")
    meta["height_refinement"] = {
        "format": "frozen-source-refinement-v1",
        "source": source,
        "quadrature": quadrature,
        "reference_canvas_sha256": _sha(meta_path),
        "reference_heightmap_sha256": _sha(height_path),
        "correction": {
            "path": "geometry_fields/height_correction_m.npy",
            "sha256": _sha(geometry / "height_correction_m.npy"),
            "units": "m; spherical footprint mean",
        },
        "structure_policy": "fixed reference S3 structure, followed by the source correction",
    }
    meta["coarse_source"] = {
        "format": "fixed-coarse-statistics-v1",
        "field": {"path": "coarse_source/field.npy", "sha256": _sha(sources / "field.npy")},
        "reference": {
            "path": "coarse_source/reference.npy",
            "sha256": _sha(sources / "reference.npy"),
        },
        "shape": list(expected),
        "encoding": "TD mean, p5 and four climate channels; float32",
        "spread_policy": "reference mean-minus-p5",
        "query_prefix": [list(c) for c in query_prefix],
        "query_policy": "last-prefix-result-v1",
    }
    (output_canvas / "canvas.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return output_canvas
