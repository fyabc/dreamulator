"""Resolve and update the formal build grid without modifying derived maps."""

from __future__ import annotations

from hashlib import sha256
from io import StringIO
from pathlib import Path
from stat import S_IMODE
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from dreamulator.engine.geological import GeologicalEngine
from dreamulator.map.export import find_mesh_file
from dreamulator.models.layers import Layer, get_layer_index

if TYPE_CHECKING:
    from dreamulator.resolver import LayerResolver

MIN_BUILD_CELLS = 100
MAX_BUILD_CELLS = 200_000
_FLAT_SECTIONS = ("planet", "terrain", "plates", "noise", "climate", "export")


class WorldGrid(BaseModel):
    """The saved cell count and the count actually present in the last map."""

    num_cells: int | None = Field(default=None, gt=0, strict=True)
    built_cells: int | None = Field(default=None, gt=0, strict=True)
    reuses_mesh: bool
    source: str | None = None
    read_only: Literal["reference", "inherited", "fixed", "published", "unavailable"] | None = None
    revision: str | None = None
    min_cells: int = MIN_BUILD_CELLS
    max_cells: int = MAX_BUILD_CELLS


class WorldGridUpdate(BaseModel):
    num_cells: int = Field(ge=MIN_BUILD_CELLS, le=MAX_BUILD_CELLS, strict=True)
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


def grid_engine(resolver: LayerResolver, seed: int) -> GeologicalEngine:
    layers = resolver.resolve_all_layers()
    target = resolver.world_dir
    if resolver.branch_name:
        target = target / "branches" / resolver.branch_name
    return GeologicalEngine(
        resolver.world_dir,
        seed,
        layer_input_dirs={
            key.value: item.input_dir for key, item in layers.items() if item.input_dir
        },
        layer_derived_dirs={
            key.value: item.derived_dir for key, item in layers.items() if item.derived_dir
        },
        maps_output_dir=target / "maps",
    )


def grid_inherited(resolver: LayerResolver) -> bool:
    fork = resolver.get_fork_layer()
    return fork is not None and get_layer_index(fork) > get_layer_index(Layer.GEOLOGICAL)


def _built_grid(engine: GeologicalEngine) -> int | None:
    map_dir = engine.maps_output_dir / engine._detect_planet_id()
    metadata = map_dir / "map.yaml"
    if find_mesh_file(map_dir) is None or not metadata.is_file():
        return None
    data = yaml.safe_load(metadata.read_text(encoding="utf-8"))
    value = data.get("voronoi_num_cells") if isinstance(data, dict) else None
    return value if type(value) is int and value > 0 else None


def _authored_source(engine: GeologicalEngine) -> Path | None:
    path = engine.find_input("terrain_config.yaml") or engine.find_input("planets.yaml")
    if (
        path is None
        or not path.is_file()
        or not path.resolve().is_relative_to(engine.world_dir.resolve())
    ):
        return None
    relative = path.relative_to(engine.world_dir)
    if relative.parent.parts[-3:] != ("layers", "geological", "input"):
        return None
    if path.name == "planets.yaml":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        planets = data.get("planets") if isinstance(data, dict) else None
        if not isinstance(planets, list) or not planets or not isinstance(planets[0], dict):
            return None
    return path


def read_world_grid(
    resolver: LayerResolver, seed: int, *, reference: bool = False, published: bool = False
) -> WorldGrid:
    engine = grid_engine(resolver, seed)
    inherited = grid_inherited(resolver)
    cells, reuses_mesh = engine.preview_mesh_cells(inherited=inherited)
    built = _built_grid(engine)
    path = None if reuses_mesh else _authored_source(engine)
    reason = (
        "published"
        if published
        else "reference"
        if reference
        else "inherited"
        if inherited
        else "fixed"
        if reuses_mesh
        else "unavailable"
        if path is None
        else None
    )
    source = path.relative_to(engine.world_dir).as_posix() if path else None
    revision = None
    if reason is None and path is not None and source is not None:
        revision = sha256(f"{source}\0{cells}\0".encode() + path.read_bytes()).hexdigest()
    return WorldGrid(
        num_cells=cells if not reference else built,
        built_cells=built,
        reuses_mesh=reuses_mesh,
        source=source,
        read_only=reason,
        revision=revision,
    )


def write_world_grid(resolver: LayerResolver, settings: WorldGrid, cells: int) -> None:
    if settings.source is None or settings.read_only is not None:
        raise ValueError("The grid is read-only")
    root = resolver.world_dir
    source = root / settings.source
    target = root / "branches" / resolver.branch_name if resolver.branch_name else root
    path = target / "layers" / "geological" / "input" / source.name
    if not target.resolve().is_relative_to(root.resolve()) or not path.resolve().is_relative_to(
        target.resolve()
    ):
        raise ValueError("The grid input must be inside the selected branch")

    editor = YAML()
    editor.preserve_quotes = True
    data = editor.load(source.read_text(encoding="utf-8"))
    if source.name == "terrain_config.yaml":
        if data is None:
            data = {}
        sections = [data, *(data.get(name) for name in reversed(_FLAT_SECTIONS))]
        location = next(
            (
                (section, key)
                for key in ("voronoi_num_cells", "num_cells", "num_nodes")
                for section in sections
                if isinstance(section, dict) and key in section
            ),
            (data, "num_nodes"),
        )
        location[0][location[1]] = cells
    else:
        planet = data["planets"][0]
        if not isinstance(planet.get("terrain"), dict):
            planet["terrain"] = {}
        planet["terrain"]["num_nodes"] = cells

    contents = StringIO()
    editor.dump(data, contents)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(contents.getvalue())
            temp.close()
            temp_path.chmod(S_IMODE(source.stat().st_mode))
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)
