"""Inspectable fields from a region's recorded refinement run."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dreamulator.map.region_inputs import REFINEMENT_INPUT_VERSION, file_sha256

if TYPE_CHECKING:
    from pathlib import Path

TD_CONDITION_FILES = {
    "elevation_m": "heightmap",
    "temperature_mean_c": "temperature",
    "temperature_std_c": "temperature_std",
    "precipitation_total_mm": "precipitation",
    "precipitation_cv_pct": "precipitation_cv",
}
TD_CONDITION_VERSION = "region-td-grid-v1"


def recorded_region_fields(
    pack_dir: Path, input_meta: dict[str, Any], refined: dict[str, Any] | None
) -> dict[str, dict[str, tuple[Path, str]]]:
    """Return only fixed paths backed by the product's recorded checksums."""
    source: dict[str, tuple[Path, str]] = {}
    grid: dict[str, tuple[Path, str]] = {}
    if not refined:
        return {"source": source, "grid": grid}
    contract = refined.get("cache_contract") or {}
    input_path = pack_dir / "input/meta.json"
    if not input_path.is_file() or contract.get("input_meta_sha256") != file_sha256(input_path):
        return {"source": source, "grid": grid}
    hashes = contract.get("inputs") or {}
    snapshot = input_meta.get("refinement_inputs") or {}
    if snapshot.get("version") == REFINEMENT_INPUT_VERSION and refined.get("td_revision"):
        for field in TD_CONDITION_FILES:
            rel = f"input/refinement/{field}.npy"
            entry = snapshot.get("fields", {}).get(field, {})
            digest = hashes.get(rel)
            if digest and entry.get("sha256") == digest and (pack_dir / rel).is_file():
                source[field] = (pack_dir / rel, digest)
    runoff = "input/runoff.mm.npy"
    if (
        refined.get("hydrology_weight") == "runoff"
        and hashes.get(runoff)
        and (pack_dir / runoff).is_file()
    ):
        source["runoff"] = (pack_dir / runoff, hashes[runoff])
    record = refined.get("td_conditions") or {}
    if refined.get("td_revision") and record.get("version") == TD_CONDITION_VERSION:
        for field in TD_CONDITION_FILES:
            digest = record.get("sha256", {}).get(field)
            path = pack_dir / "refined-out/td-conditions" / f"{field}.npy"
            if digest and path.is_file():
                grid[field] = (path, digest)
    return {"source": source, "grid": grid}
