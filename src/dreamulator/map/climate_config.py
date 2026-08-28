"""Load a world's climate config with physical parameters resolved.

The build pipeline resolves a world's climate config in two steps that the
diagnostic scripts historically skipped:

1. ``TerrainPipelineConfig.from_yaml(terrain_config.yaml)`` — the authored
   climate/terrain knobs.
2. ``resolve_and_apply_physical_parameters`` — the *authoritative* physical
   fields (rotation, radius, gravity, albedo, greenhouse, stellar luminosity,
   orbital distance) from ``planets.yaml`` / ``stellar.yaml``, which override
   the terrain config's copies.

Skipping step 2 silently ran non-Earth worlds with Earth's default physical
parameters (e.g. ``radius_km=6371``, ``greenhouse_warming_K`` default), which
produced the wrong climate (the nacrea "20 vs 10 Köppen classes" discrepancy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.map.pipeline_types import TerrainPipelineConfig

if TYPE_CHECKING:
    from pathlib import Path


class _PhysicalResolver:
    """Minimal ``find_input`` provider for ``resolve_and_apply_physical_parameters``.

    Replicates ``BaseEngine.find_input``'s layer-chain search without pulling in
    the full engine (which is not available outside a build).
    """

    def __init__(self, input_dirs: dict[str, Path], derived_dirs: dict[str, Path]) -> None:
        from dreamulator.models.layers import Layer

        self.layer = Layer.CLIMATE
        self.layer_input_dirs = input_dirs
        self.layer_derived_dirs = derived_dirs

    def find_input(self, relative_path: str) -> Path | None:
        from dreamulator.models.layers import LAYER_ORDER

        search: list[str] = []
        if self.layer.value in self.layer_input_dirs or self.layer.value in self.layer_derived_dirs:
            search.append(self.layer.value)
        for layer in reversed(LAYER_ORDER):
            if layer.value != self.layer.value:
                search.append(layer.value)
        for layer_name in search:
            dirs = (
                self.layer_derived_dirs.get(layer_name),
                self.layer_input_dirs.get(layer_name),
            )
            for d in dirs:
                if d is not None:
                    path = d / relative_path
                    if path.exists():
                        return path
        return None


def load_world_climate_config(
    world_dir: Path,
    planet_id: str | None = None,
    branch: str | None = None,
) -> tuple[TerrainPipelineConfig, list[str]]:
    """Load a world's climate config (terrain_config + physical parameters).

    Args:
        world_dir: World root directory.
        planet_id: Preferred planet id (falls back to the first planet).
        branch: Optional branch name.

    Returns:
        (config, warnings); mirrors the build pipeline's resolution so
        diagnostics on non-Earth worlds use the same physical inputs.
    """
    from dreamulator.models.layers import LAYER_ORDER
    from dreamulator.resolver import LayerResolver

    resolver = LayerResolver(world_dir, branch)

    input_dirs: dict[str, Path] = {}
    derived_dirs: dict[str, Path] = {}
    for layer in LAYER_ORDER:
        idir = resolver.get_input_dir(layer)
        if idir is not None:
            input_dirs[layer.value] = idir
        ddir = resolver.get_derived_dir(layer)
        if ddir is not None:
            derived_dirs[layer.value] = ddir

    config = TerrainPipelineConfig()
    # Per-file lookup: a branch that overrides some geological inputs (e.g.
    # planets.yaml) still inherits the root world's terrain_config.yaml.
    terrain_cfg_path = resolver.find_input_file("geological", "terrain_config.yaml")
    if terrain_cfg_path is not None:
        config = TerrainPipelineConfig.from_yaml(terrain_cfg_path)

    from dreamulator.engine.physical_inputs import resolve_and_apply_physical_parameters

    phys_resolver = _PhysicalResolver(input_dirs, derived_dirs)
    warnings = resolve_and_apply_physical_parameters(
        phys_resolver,  # type: ignore[arg-type]  # resolver only needs find_input
        config,
        planet_id=planet_id,
    )
    return config, warnings


def load_climate_config(
    world_dir: Path,
    world: str,
    planet_id: str,
    branch: str | None,
    num_cells: int,
) -> TerrainPipelineConfig:
    """Resolve the climate config for a world (diagnostic-script entry point).

    The ``earth`` validation world uses the shared-physics Earth config; any
    other world loads its authored ``terrain_config.yaml`` + physical params.
    """
    if world == "earth":
        from dreamulator.validate_climate import build_earth_validation_config

        return build_earth_validation_config(num_cells)
    config, _ = load_world_climate_config(world_dir, planet_id, branch)
    return config
