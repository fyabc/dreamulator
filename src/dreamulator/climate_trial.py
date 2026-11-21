"""Compute an isolated EBM result from a world's existing geological mesh."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Callable

    from dreamulator.map.pipeline_types import TerrainPipelineConfig


BROWSER_TRIAL_MAX_CELLS = 20_000


class TrialUnavailableError(ValueError):
    """The selected map cannot be used as a local trial source."""


class TrialForcing(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    axial_tilt_deg: float | None = Field(default=None, ge=0, le=90)
    rotation_period_days: float | None = Field(default=None, gt=0)
    albedo: float | None = Field(default=None, ge=0, le=1)
    greenhouse_warming_k: float | None = Field(default=None, ge=0)

    @staticmethod
    def config_field(name: str) -> str:
        return "greenhouse_warming_K" if name == "greenhouse_warming_k" else name

    @classmethod
    def from_config(cls, config: TerrainPipelineConfig) -> TrialForcing:
        return cls.model_validate(
            {name: getattr(config, cls.config_field(name)) for name in cls.model_fields}
        )


class TrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch: str | None = Field(default=None, pattern=r"^[\w-][\w.-]*$")
    forcing: TrialForcing = Field(default_factory=TrialForcing)


class TrialProgress(BaseModel):
    stage: str
    started_at: float
    cells: int | None = None
    months_done: int | None = None
    months_total: int | None = None
    moisture_pass: int | None = None


@dataclass(frozen=True)
class TrialSource:
    config: TerrainPipelineConfig
    mesh_path: Path


def resolve_trial_source(world_dir: Path, planet_id: str, branch: str | None) -> TrialSource:
    """Use the formal input resolution and require existing astronomical and geological data."""
    from dreamulator.engine.climate import (
        ClimateEngine,
        _is_reference_anchor,
        geological_mesh_candidates,
    )
    from dreamulator.engine.physical_inputs import load_planets
    from dreamulator.resolver import LayerResolver

    if branch is None and _is_reference_anchor(world_dir):
        raise TrialUnavailableError("reference_anchor")

    layers = LayerResolver(world_dir, branch).resolve_all_layers()
    inputs = {layer.value: source.input_dir for layer, source in layers.items() if source.input_dir}
    derived = {
        layer.value: source.derived_dir for layer, source in layers.items() if source.derived_dir
    }
    engine = ClimateEngine(world_dir, 0, layer_input_dirs=inputs, layer_derived_dirs=derived)
    planet_path = engine.find_input("planets.yaml")
    if planet_path is None or engine.find_input("stellar_derived.yaml") is None:
        raise TrialUnavailableError("build_inputs")
    planets, _ = load_planets(planet_path)
    planet = next((candidate for candidate in planets if candidate.id == planet_id), None)
    if planet is None:
        raise TrialUnavailableError("body_not_supported")

    base = world_dir / "branches" / branch if branch is not None else world_dir
    candidates, _ = geological_mesh_candidates(
        derived, inputs, base / "maps", planet_id=planet_id, world_dir=world_dir
    )
    mesh_path = next((path for path in candidates if path.parent.name == planet_id), None)
    if mesh_path is None:
        raise TrialUnavailableError("build_mesh")
    config, _ = engine.resolve_config(planet)
    return TrialSource(config, mesh_path)


def compute_trial(
    source: TrialSource,
    forcing: TrialForcing,
    output: Path,
    budget: int,
    *,
    diagnostic_pngs: bool = True,
    on_progress: Callable[[TrialProgress], None] | None = None,
) -> None:
    """Run the production solver and exporter without touching the input files."""
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.map.export import (
        DYNAMIC_CELL_FIELDS,
        MESH_FILENAME,
        export_climate_layers,
        load_cvt_mesh_model,
        save_cvt_mesh,
    )
    from dreamulator.map.models import VoronoiCell

    progress = TrialProgress(stage="reading", started_at=monotonic())

    def publish() -> None:
        if on_progress is not None:
            on_progress(progress)
            return
        temp = output / "progress.tmp"
        temp.write_text(progress.model_dump_json(), encoding="utf-8")
        temp.replace(output / "progress.json")

    def phase(stage: str) -> None:
        progress.stage = stage
        progress.started_at = monotonic()
        progress.months_done = progress.months_total = progress.moisture_pass = None
        publish()

    def month(done: int, total: int) -> None:
        if done == 0:
            progress.moisture_pass = (progress.moisture_pass or 0) + 1
        progress.months_done, progress.months_total = done, total
        publish()

    publish()
    mesh = load_cvt_mesh_model(source.mesh_path)
    progress.cells = mesh.num_cells
    if mesh.num_cells * 32 * 1024 > budget:
        raise TrialUnavailableError("memory_budget")

    defaults = [(name, VoronoiCell.model_fields[name]) for name in DYNAMIC_CELL_FIELDS]
    for cell in mesh.cells:
        for name, field in defaults:
            setattr(cell, name, field.get_default(call_default_factory=True))
    for name, value in forcing.model_dump(exclude_none=True).items():
        setattr(source.config, forcing.config_field(name), value)

    simulate_climate(mesh, source.config, on_progress=phase, on_precipitation_month=month)
    phase("export")
    save_cvt_mesh(output / MESH_FILENAME, mesh)
    export_climate_layers(mesh, output, source.config, diagnostic_pngs=diagnostic_pngs)
    if not (output / "climate_monthly.msgpack").is_file():
        raise TrialUnavailableError("missing_result")


def _worker() -> None:
    world_dir, planet_id, directory, memory_bytes = sys.argv[1:]
    output = Path(directory)
    budget = int(memory_bytes)
    if sys.platform.startswith("linux"):
        import resource

        current, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = min(budget, current) if current != resource.RLIM_INFINITY else budget
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    try:
        request = TrialRequest.model_validate_json((output / "request.json").read_bytes())
        source = resolve_trial_source(Path(world_dir), planet_id, request.branch)
        compute_trial(source, request.forcing, output, budget)
    except (TrialUnavailableError, MemoryError) as error:
        reason = "memory_budget" if isinstance(error, MemoryError) else str(error)
        (output / "error.txt").write_text(reason, encoding="utf-8")
        raise SystemExit(1) from error


if __name__ == "__main__":
    _worker()
