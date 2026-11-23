"""Per-layer input projections for layer freshness.

Each engine layer records a projection of the authored inputs it reads after a
successful build.  The projection has two parts:

- ``files``: a content hash per authored input file.  YAML files are parsed
  and canonicalised, so comment and formatting edits do not count.
- ``parameters``: the values of registered shared parameters consumed by the
  layer.  Registered fields are stripped from the file hash, so changing a
  field this layer does not read (for example albedo for the geological layer)
  does not mark it stale.  Unregistered fields stay in the stripped document,
  which keeps the fallback conservative.

Status compares the current projection with the recorded one; a missing or
corrupt record falls back to the legacy mtime heuristic.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dreamulator.models.layers import Layer
from dreamulator.parameter_registry import ParameterSpec, load_registry, storage_values
from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path

    from dreamulator.engine.base import BaseEngine

logger = logging.getLogger(__name__)

PROJECTION_FILENAME = ".input-projection.json"
PROJECTION_SCHEMA = 1


class InputProjection(BaseModel):
    """Recorded inputs of one engine layer at build time."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(alias="schema", ge=1)
    layer: Layer
    registry_schema: int
    files: dict[str, str]
    parameters: dict[str, str]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> Any | None:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _hash_authored_file(path: Path) -> str:
    if path.suffix.lower() in {".yaml", ".yml"}:
        document = _load_yaml(path)
        if document is not None:
            return _sha256_text(_canonical(document))
    return _hash_file(path)


def _remove_path(node: Any, segments: list[str | int]) -> None:
    """Remove the leaf value at *segments*, ignoring missing branches."""
    if not segments:
        return
    head, rest = segments[0], segments[1:]
    if head == "*":
        if isinstance(node, list):
            for item in node:
                _remove_path(item, rest)
        return
    if isinstance(head, int):
        if isinstance(node, list) and -len(node) <= head < len(node):
            _remove_path(node[head], rest)
        return
    if isinstance(node, dict) and head in node:
        if rest:
            _remove_path(node[head], rest)
        else:
            node.pop(head, None)


def _project_registered_file(path: Path, specs: list[ParameterSpec], layer: Layer) -> str:
    """Project a file that carries registered parameters.

    The stripped document keeps every unregistered field, so an edit to one of
    them marks all readers stale.  Registered fields are represented only by
    the values consumed by this layer.
    """
    document = _load_yaml(path)
    if document is None:
        return _hash_file(path)
    stripped = copy.deepcopy(document)
    for spec in specs:
        _remove_path(stripped, spec.storage.path)
    consumed = {
        spec.id: storage_values(document, spec.storage.path)
        for spec in specs
        if layer in spec.consumers
    }
    return _sha256_text(_canonical({"consumed": consumed, "unregistered": stripped}))


def _authored_input_files(engine: BaseEngine) -> list[tuple[Path, str]]:
    """Existing authored input files for an engine, as (path, relative path)."""
    root = engine.world_dir.resolve()
    seen: set[str] = set()
    found: list[tuple[Path, str]] = []
    for name in [*engine.input_files, *engine.optional_input_files]:
        path = engine.find_input(name)
        if path is None:
            continue
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            continue
        if not _is_authored_input(relative):
            continue
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        found.append((path, key))
    return found


def _is_authored_input(relative: Path) -> bool:
    """True for ``layers/<layer>/input/...`` files (root or branch scope)."""
    parts = relative.parts
    return any(
        part == "layers" and index + 2 < len(parts) and parts[index + 2] == "input"
        for index, part in enumerate(parts)
    )


def _logical_input_path(relative: str) -> str:
    """Drop a ``branches/<name>/`` prefix so registry paths match both scopes."""
    parts = relative.split("/")
    if "layers" in parts:
        return "/".join(parts[parts.index("layers") :])
    return relative


def compute_input_projection(engine: BaseEngine) -> InputProjection:
    """Compute the current projection for one engine layer."""
    registry = load_registry()
    specs_by_file: dict[str, list[ParameterSpec]] = {}
    for spec in registry.parameters:
        specs_by_file.setdefault(spec.storage.file, []).append(spec)

    files: dict[str, str] = {}
    parameters: dict[str, str] = {}
    for path, relative in _authored_input_files(engine):
        logical = _logical_input_path(relative)
        specs = specs_by_file.get(logical)
        if specs:
            files[relative] = _project_registered_file(path, specs, engine.layer)
            document = _load_yaml(path)
            for spec in specs:
                if engine.layer not in spec.consumers:
                    continue
                values = storage_values(document, spec.storage.path) if document is not None else []
                parameters[spec.id] = _canonical(values)
        else:
            files[relative] = _hash_authored_file(path)

    return InputProjection(
        schema_version=PROJECTION_SCHEMA,
        layer=engine.layer,
        registry_schema=registry.schema_version,
        files=files,
        parameters=parameters,
    )


def write_input_projection(engine: BaseEngine) -> Path:
    """Write the current projection next to the layer's derived products."""
    projection = compute_input_projection(engine)
    target = engine.layer_output_dir / PROJECTION_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(projection.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return target


def load_input_projection(derived_dir: Path | None) -> InputProjection | None:
    """Read a recorded projection, or None when absent/corrupt/outdated."""
    if derived_dir is None:
        return None
    path = derived_dir / PROJECTION_FILENAME
    if not path.is_file():
        return None
    try:
        projection = InputProjection.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Ignoring corrupt input projection %s: %s", path, error)
        return None
    if projection.schema_version != PROJECTION_SCHEMA:
        return None
    return projection


def build_layer_engine(
    world_dir: Path,
    layer: Layer | str,
    branch: str | None,
    seed: int,
) -> BaseEngine | None:
    """Construct the engine for a layer without running it.

    Returns None for layers without an engine (physics, chemistry).
    """
    from dreamulator.engine import get_all_engines

    target = Layer(layer) if isinstance(layer, str) else layer
    engine_class = next((cls for cls in get_all_engines() if cls.layer is target), None)
    if engine_class is None:
        return None

    resolver = LayerResolver(world_dir, branch)
    sources = resolver.resolve_all_layers()
    inputs = {name.value: source.input_dir for name, source in sources.items() if source.input_dir}
    derived = {
        name.value: source.derived_dir for name, source in sources.items() if source.derived_dir
    }
    scope = world_dir / "branches" / branch if branch else world_dir
    return engine_class(
        world_dir,
        seed,
        layer_input_dirs=inputs,
        layer_derived_dirs=derived,
        layer_output_dir=scope / "layers" / target.value / "derived",
        maps_output_dir=scope / "maps",
    )


def current_input_projection(
    world_dir: Path,
    layer: Layer | str,
    branch: str | None,
    seed: int,
) -> InputProjection | None:
    """Current projection for a layer; None when it has no engine."""
    engine = build_layer_engine(world_dir, layer, branch, seed)
    if engine is None:
        return None
    return compute_input_projection(engine)
