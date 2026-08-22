"""Per-stage intermediate caching for the terrain generation pipeline.

Each pipeline stage writes its result to ``_cache/`` alongside a manifest
that records input fingerprints.  On subsequent runs, stages whose inputs
have not changed are skipped and loaded from disk instead.

This is an **internal implementation detail** of the pipeline — cache files
are binary (pickle) and should not be hand-edited.  To force a full rebuild,
delete the ``_cache/`` directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dreamulator.models.simulation import ComputationManifest, StepRecord

if TYPE_CHECKING:
    from dreamulator.map.pipeline_types import TerrainPipelineConfig

logger = logging.getLogger(__name__)

_CACHE_DIR = "_cache"
_MANIFEST_FILE = "manifest.json"


# ── helpers ───────────────────────────────────────────────────────────


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    """SHA-256 of a file, or empty string if it doesn't exist."""
    if not path.exists():
        return ""
    return _sha256_hex(path.read_bytes())


def _config_fingerprint(config: TerrainPipelineConfig, stages: list[str]) -> str:
    """Deterministic fingerprint of the configuration fields relevant to *stages*.

    Serialises a subset of config fields to sorted JSON so that field order is
    stable even if the Pydantic model serialises keys in a different order
    between runs.
    """
    # Fields that each stage reads from config (declared here for visibility).
    stage_fields: dict[str, list[str]] = {
        "mesh": [
            "num_nodes",
            "jitter_sigma",
            "lloyd_iterations",
            "fibonacci_offset",
            "radius_km",
            "seed",
        ],
        "plates": [
            "num_plates",
            "plate_size_factor_min",
            "plate_size_factor_max",
            "seed",
        ],
        "tectonics": [
            "tectonic_steps",
            "resample_every",
            "convergence_rate_mm_yr",
            "trench_arc",
            "seed",
        ],
        "boundaries": [
            "boundary_inner_sigma",
            "boundary_outer_sigma",
            "seed",
        ],
        "terrain": [
            "continental_elevation_m",
            "ocean_depth_m",
            "noise_octaves",
            "noise_lacunarity",
            "noise_persistence",
            "noise_base_freq",
            "sea_level_offset_m",
            "isostasy_tail_compression",
            "seed",
        ],
    }

    relevant: dict[str, Any] = {}
    cfg_dict = asdict(config)
    for stage in stages:
        for field in stage_fields.get(stage, []):
            if field in cfg_dict:
                relevant[field] = cfg_dict[field]
    # sort keys for deterministic serialisation
    return _sha256_hex(json.dumps(relevant, sort_keys=True, default=str).encode())


# ── cache store / load ────────────────────────────────────────────────


class TerrainCache:
    """Manages per-stage cached intermediate results."""

    def __init__(self, output_dir: Path) -> None:
        self.cache_dir = output_dir / _CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.cache_dir / _MANIFEST_FILE

    # ---- manifest -----------------------------------------------------

    def read_manifest(self) -> ComputationManifest | None:
        """Read the existing manifest, or None."""
        if not self.manifest_path.exists():
            return None
        try:
            return ComputationManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except Exception:
            logger.warning("Corrupt cache manifest — ignoring", exc_info=True)
            return None

    def write_manifest(self, manifest: ComputationManifest) -> None:
        self.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    # ---- stage cache --------------------------------------------------

    def _pickle_path(self, stage: str) -> Path:
        return self.cache_dir / f"{stage}.pkl"

    def has_valid(self, stage: str, fingerprint: str) -> bool:
        """True if *stage* has a cached result whose fingerprint matches."""
        manifest = self.read_manifest()
        if manifest is None:
            return False
        for step in manifest.steps:
            if step.engine == stage:
                return step.input_files.get("fingerprint", "") == fingerprint
        return False

    def load(self, stage: str) -> Any:
        """Load cached data for *stage*.  Returns None on failure."""
        path = self._pickle_path(stage)
        if not path.exists():
            logger.info("Cache miss for stage '%s': file not found.", stage)
            return None
        try:
            with path.open("rb") as f:
                return pickle.load(f)
        except Exception:
            logger.warning("Failed to load cache for stage '%s'.", stage, exc_info=True)
            return None

    def save(self, stage: str, data: Any, fingerprint: str) -> None:
        """Save *data* for *stage* and update the manifest."""
        path = self._pickle_path(stage)
        with path.open("wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

        # Update manifest
        manifest = self.read_manifest() or ComputationManifest(
            world_name="",
            seed=0,
            steps=[],
            generated=datetime_mock(),
        )
        # Remove previous record for this stage if present
        manifest.steps = [s for s in manifest.steps if s.engine != stage]
        now = datetime_mock()
        manifest.steps.append(
            StepRecord(
                engine=stage,
                input_files={"fingerprint": fingerprint},
                output_files={},
                parameters={},
                started=now,
                completed=now,
                success=True,
            )
        )
        manifest.generated = now
        self.write_manifest(manifest)


def datetime_mock() -> Any:
    """Import-safe datetime.now()."""
    from datetime import datetime as _dt

    return _dt.now()


# ── high-level API ────────────────────────────────────────────────────


@dataclass
class CacheConfig:
    """Controls which stages participate in caching."""

    enabled: bool = True
    stages: list[str] = dc_field(
        default_factory=lambda: ["mesh", "plates", "tectonics", "boundaries", "terrain"]
    )
    geography_hash: str = ""  # set by the pipeline before cache lookups


def build_stage_fingerprint(
    stage: str,
    config: TerrainPipelineConfig,
    *,
    geography_hash: str = "",
    upstream_fingerprints: dict[str, str] | None = None,
) -> str:
    """Build the input fingerprint for a single stage."""
    parts: list[str] = []
    parts.append(_config_fingerprint(config, [stage]))
    if geography_hash:
        parts.append(geography_hash)
    if upstream_fingerprints:
        for dep in _stage_dependencies(stage):
            if dep in upstream_fingerprints:
                parts.append(upstream_fingerprints[dep])
    return _sha256_hex("|".join(parts).encode())


def _stage_dependencies(stage: str) -> list[str]:
    """Logical upstream stages that *stage* depends on."""
    _deps: dict[str, list[str]] = {
        "mesh": [],
        "plates": ["mesh"],
        "tectonics": ["plates"],
        "boundaries": ["plates", "tectonics"],
        "terrain": ["tectonics", "boundaries"],
    }
    return _deps.get(stage, [])
