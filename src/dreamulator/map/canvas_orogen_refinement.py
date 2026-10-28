"""Native mountain-source preparation for the normal canvas CLI.

Selected sources replace their original geological contributions in an isolated
S3 input batch. Sphere-area quadrature checks convergence before the pinned TD
worker prepares fixed reference statistics. The existing layout, coverage,
structure, climate and unselected inputs are retained.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Self

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canvas_refinement import prepare_refined_canvas
from .orogen_source import (
    CollisionParameterPolicy,
    FrozenOrogenReplacement,
    orogen_source_from_native,
)
from .td_canvas import CanvasGeometry
from .terrain_source import integrate_source_correction

if TYPE_CHECKING:
    from collections.abc import Callable

    from .orogen_contract import OrogenContract
    from .pipeline_types import TerrainPipelineConfig


class OrogenSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    collision_segment_ids: tuple[str, ...] = ()
    paleo_suture_ids: tuple[str, ...] = ()
    collision_parameter_policy: CollisionParameterPolicy = "conservative_arc"
    statistics_reference: Path | None = None

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        if not self.collision_segment_ids and not self.paleo_suture_ids:
            raise ValueError("select at least one native mountain source")
        if self.collision_parameter_policy != "conservative_arc" and not self.collision_segment_ids:
            raise ValueError("a collision parameter policy requires selected collision segments")
        for ids in (self.collision_segment_ids, self.paleo_suture_ids):
            if any(not name for name in ids) or len(set(ids)) != len(ids):
                raise ValueError("mountain source ids must be nonempty and unique")
        return self


class CanvasRefinementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str | None = None
    planet: str | None = None
    orogens: dict[str, OrogenSelection] = Field(min_length=1)
    quadrature_orders: tuple[int, ...] = (8, 16, 32, 64, 128)

    @model_validator(mode="after")
    def check_orders(self) -> Self:
        if (
            len(self.quadrature_orders) < 2
            or any(order < 2 for order in self.quadrature_orders)
            or any(
                b <= a
                for a, b in zip(self.quadrature_orders, self.quadrature_orders[1:], strict=False)
            )
        ):
            raise ValueError("provide at least two strictly increasing quadrature orders")
        return self

    @classmethod
    def load(cls, path: Path) -> CanvasRefinementConfig:
        config = cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        config.orogens = {
            cid: selection.model_copy(
                update={"statistics_reference": (path.resolve().parent / origin).resolve()}
            )
            if (origin := selection.statistics_reference) is not None
            else selection
            for cid, selection in config.orogens.items()
        }
        return config


@dataclass
class NativeOrogenInputs:
    fields: dict[str, np.ndarray]
    contract: OrogenContract
    geometry: dict[str, Any]
    config: TerrainPipelineConfig
    metadata: dict[str, Any]
    provenance: dict[str, Any]

    def source(self, selection: OrogenSelection) -> FrozenOrogenReplacement:
        return orogen_source_from_native(
            self.fields,
            self.contract,
            self.geometry,
            self.config.paleo_sutures,
            collision_segment_ids=selection.collision_segment_ids,
            paleo_suture_ids=selection.paleo_suture_ids,
            collision_parameter_policy=selection.collision_parameter_policy,
            radius_km=float(self.metadata["radius_km"]),
            gravity_m_s2=self.config.gravity_m_s2,
            base_m=self.config.continental_elevation_m,
            reference_id=str(self.metadata["source"]["terrain_fingerprint"]),
        )


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_native_inputs(
    world_dir: Path, map_dir: Path, *, branch: str | None, planet: str
) -> NativeOrogenInputs:
    """Resolve physical/author inputs by branch and read the matching source contract."""
    from dreamulator.engine.geological import GeologicalEngine
    from dreamulator.models.layers import LAYER_ORDER
    from dreamulator.resolver import LayerResolver

    from .orogen_contract import load_orogen_contract
    from .terrain_source_export import load_terrain_source_fields

    resolver = LayerResolver(world_dir, branch)
    inputs, derived = {}, {}
    for layer in LAYER_ORDER:
        if (directory := resolver.get_input_dir(layer)) is not None:
            inputs[layer.value] = directory
        if (directory := resolver.get_derived_dir(layer)) is not None:
            derived[layer.value] = directory
    config, warnings = GeologicalEngine(
        world_dir, 42, layer_input_dirs=inputs, layer_derived_dirs=derived
    )._load_config({"planet_id": planet})
    if config is None:
        raise ValueError(f"geological source configuration could not be loaded: {warnings}")
    archive, contract_path = map_dir / "terrain_sources.npz", map_dir / "orogen_contract.json"
    fields, meta = load_terrain_source_fields(archive)
    if not np.isclose(config.radius_km, meta["radius_km"], rtol=1e-12, atol=0):
        raise ValueError("author physics and geological source archive have different radii")
    document = json.loads(contract_path.read_text(encoding="utf-8"))
    return NativeOrogenInputs(
        fields,
        load_orogen_contract(contract_path),
        document["geometry"],
        config,
        meta,
        {
            "planet": planet,
            "branch": branch,
            "archive_sha256": _sha(archive),
            "schema_sha256": _sha(archive.with_suffix(".json")),
            "contract_sha256": _sha(contract_path),
            "configuration_warnings": warnings,
        },
    )


integrate_orogen_correction = integrate_source_correction


def _copy_inputs(reference: Path, target: Path) -> None:
    target.mkdir(parents=True)
    shutil.copy2(reference / "canvas.json", target / "canvas.json")
    for name in ("conditioning", "climate", "geometry_fields", "coarse_source"):
        if (reference / name).exists():
            shutil.copytree(reference / name, target / name)


def refine_canvas_layout(
    reference: Path,
    output: Path,
    cfg: CanvasRefinementConfig,
    inputs: NativeOrogenInputs,
    *,
    prepare_statistics: Callable[[Path, Path, Path], None],
) -> Path:
    """Prepare the entire independent layout before installing its verified inputs.

    Reference chunks remain in their original batch. Unselected canvas inputs,
    ownership tables, layout coverage and reference climate are copied unchanged.
    A failure preserves the complete reference and leaves no output batch.
    """
    if output.exists():
        raise FileExistsError("refined layout output must be a new batch")
    layout = json.loads((reference / "layout.json").read_text(encoding="utf-8"))
    ids = [row["id"] for row in layout["canvases"]]
    if len(set(ids)) != len(ids) or any(
        Path(name).parts != (name,) or name in (".", "..") for name in ids
    ):
        raise ValueError("layout canvas ids must be unique directory names")
    if not set(cfg.orogens).issubset(ids):
        raise ValueError("selected mountain canvases must belong to the reference layout")
    from .td_canvas_worker import _read_conditioning, read_coarse_source

    for cid in ids:
        original = reference / cid
        meta = json.loads((original / "canvas.json").read_text(encoding="utf-8"))
        _read_conditioning(original, meta)
        if "coarse_source" in meta:
            read_coarse_source(original, meta)
    # Check source construction and original S3 reference status before any expensive preparation.
    sources = {}
    statistical_references = {}
    for cid, selection in cfg.orogens.items():
        meta = json.loads((reference / cid / "canvas.json").read_text(encoding="utf-8"))
        if "height_refinement" in meta or "height_source" in meta:
            raise ValueError("native replacement requires the original S3 reference batch")
        if not np.isclose(
            meta["geometry"]["radius_km"], inputs.metadata["radius_km"], rtol=1e-12, atol=0
        ):
            raise ValueError("reference canvas and native source sphere radii must match")
        sources[cid] = inputs.source(selection)
        if selection.statistics_reference is not None:
            origin = selection.statistics_reference
            accepted = json.loads((origin / "canvas.json").read_text(encoding="utf-8"))
            if accepted.get("id") != cid or any(
                accepted.get(key) != meta.get(key)
                for key in ("geometry", "generation", "structure")
            ):
                raise ValueError("accepted statistics must use the same canvas and model inputs")
            if "coarse_source" not in accepted:
                raise ValueError("accepted statistics need their self-contained frozen field")
            arrays = _read_conditioning(origin, accepted)
            original_arrays = _read_conditioning(reference / cid, meta)
            if any(
                arrays[key].tobytes() != original_arrays[key].tobytes()
                for key in arrays
                if key != "heightmap"
            ):
                raise ValueError("accepted statistical reference changed a climate input")
            read_coarse_source(origin, accepted)
            statistical_references[cid] = {
                "canvas": str(origin.resolve()),
                "canvas_sha256": _sha(origin / "canvas.json"),
                "field_sha256": accepted["coarse_source"]["field"]["sha256"],
                "reference_sha256": accepted["coarse_source"]["reference"]["sha256"],
            }
    output.parent.mkdir(parents=True, exist_ok=True)
    receipts = {}
    with TemporaryDirectory(prefix=".canvas-refine-", dir=output.parent) as temporary:
        base = Path(temporary)
        batch, working = base / "batch", base / "working"
        batch.mkdir()
        for name in ("owner_points.npy", "owner_canvas.npy"):
            shutil.copy2(reference / name, batch / name)
        for cid in ids:
            original = reference / cid
            if cid not in cfg.orogens:
                _copy_inputs(original, batch / cid)
                continue
            meta = json.loads((original / "canvas.json").read_text(encoding="utf-8"))
            g = meta["geometry"]
            geometry = CanvasGeometry(g["center_lat"], g["center_lon"], g["radius_km"], g["ncell"])
            correction, integrated = integrate_orogen_correction(
                sources[cid], geometry, cfg.quadrature_orders
            )
            candidate = working / cid / "candidate"
            _copy_inputs(original, candidate)
            height = np.load(original / "conditioning/heightmap.npy")
            np.save(
                candidate / "conditioning/heightmap.npy",
                (height.astype(np.float64) + correction).astype(np.float32),
            )
            meta["conditioning_sha256"]["heightmap"] = _sha(
                candidate / "conditioning/heightmap.npy"
            )
            (candidate / "canvas.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            statistical_reference = original
            if cid in statistical_references:
                configured_origin = cfg.orogens[cid].statistics_reference
                assert configured_origin is not None
                statistical_reference = working / cid / "statistical_reference"
                _copy_inputs(configured_origin, statistical_reference)
                if (
                    _sha(statistical_reference / "canvas.json")
                    != statistical_references[cid]["canvas_sha256"]
                ):
                    raise ValueError("accepted statistical reference changed during preparation")
            reference_meta = json.loads(
                (statistical_reference / "canvas.json").read_text(encoding="utf-8")
            )
            stats = working / cid / "statistics"
            prepare_statistics(statistical_reference, candidate, stats)
            destination = prepare_refined_canvas(
                original,
                batch / cid,
                correction,
                stats / "field.npy",
                stats / "reference.npy",
                source={
                    **sources[cid].metadata,
                    "native_inputs": inputs.provenance,
                    "integration": integrated,
                    "statistics_reference": statistical_references.get(cid),
                },
                quadrature=int(integrated["quadrature"]),
                query_prefix=tuple(
                    tuple(pair)
                    for pair in reference_meta.get("coarse_source", {}).get("query_prefix", [])
                ),
            )
            receipt = json.loads((stats / "receipt.json").read_text(encoding="utf-8"))
            if receipt["reference_canvas_sha256"] != _sha(
                statistical_reference / "canvas.json"
            ) or receipt["candidate_canvas_sha256"] != _sha(candidate / "canvas.json"):
                raise ValueError("prepared statistical fields belong to different input batches")
            for name in ("field", "reference"):
                if _sha(stats / f"{name}.npy") != receipt[name]["sha256"]:
                    raise ValueError("prepared statistical field checksum mismatch")
            proof = destination / "preparation"
            proof.mkdir()
            shutil.copy2(stats / "receipt.json", proof / "statistics.json")
            if (stats / "prepare.log").exists():
                shutil.copy2(stats / "prepare.log", proof / "prepare.log")
            receipts[cid] = {
                "integration": integrated,
                "statistics": receipt,
                "statistics_reference": statistical_references.get(cid),
            }
        layout["height_refinement"] = {
            "format": "native-orogen-layout-v1",
            "config": cfg.model_dump(mode="json"),
            "native_inputs": inputs.provenance,
            "reference_layout_sha256": _sha(reference / "layout.json"),
            "canvases": receipts,
        }
        (batch / "layout.json").write_text(json.dumps(layout, indent=1), encoding="utf-8")
        if output.exists():
            raise FileExistsError("refined output was created during batch preparation")
        batch.rename(output)
    return output
