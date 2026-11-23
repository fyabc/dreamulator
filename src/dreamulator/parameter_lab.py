"""Read and save registry parameters for the parameter lab.

The lab edits the parameters of one selected planet. Values are stored in the
single authored location declared by the registry; saves preserve YAML
comments, check a content revision, and can create a new branch at the
earliest consumer layer.

This is the backend counterpart of ``parameter_registry.py``; the frontend
imports the same registry for grouping and labels.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Mapping, MutableMapping
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml
from ruamel.yaml import YAML

from dreamulator.branch_manager import BranchManager
from dreamulator.models.layers import Layer, get_layer_index
from dreamulator.parameter_registry import ParameterSpec, load_registry
from dreamulator.resolver import LayerResolver


class ParameterLabConflictError(ValueError):
    """The storage files changed since the lab opened."""


class ParameterLabReadOnlyError(ValueError):
    """The selected world or parameter cannot be written."""


class ParameterLabUnavailableError(ValueError):
    """The selected planet is not defined in the parameter storage."""


def storage_location(spec: ParameterSpec) -> tuple[Layer, str]:
    """Split a registry storage file into its layer and input-relative path."""
    parts = Path(spec.storage.file).parts
    for index, part in enumerate(parts):
        if part == "layers" and index + 2 < len(parts) and parts[index + 2] == "input":
            layer = Layer(parts[index + 1])
            relative = "/".join(parts[index + 3 :])
            return layer, relative
    raise ValueError(f"Storage file is not an authored layer input: {spec.storage.file}")


def _effective_path(resolver: LayerResolver, spec: ParameterSpec) -> Path | None:
    layer, relative = storage_location(spec)
    return resolver.find_input_file(layer, relative)


def _target_path(world_dir: Path, branch: str | None, spec: ParameterSpec) -> Path:
    scope = world_dir / "branches" / branch if branch else world_dir
    return scope / spec.storage.file


def _revision(paths: list[Path], world_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        try:
            relative = path.resolve().relative_to(world_dir.resolve())
        except ValueError:
            relative = Path(path.name)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _planet_entries(document: Any) -> list[MutableMapping[str, Any]]:
    if not isinstance(document, Mapping):
        return []
    planets = document.get("planets")
    if not isinstance(planets, list):
        return []
    return [
        item for item in planets if isinstance(item, MutableMapping) and item.get("id") is not None
    ]


def _planet_entry(document: Any, planet_id: str) -> MutableMapping[str, Any] | None:
    return next((item for item in _planet_entries(document) if str(item["id"]) == planet_id), None)


def _planet_path_tail(spec: ParameterSpec) -> list[str | int] | None:
    path = spec.storage.path
    if len(path) >= 2 and path[0] == "planets" and path[1] == "*":
        return path[2:]
    return None


def _read_value(entry: MutableMapping[str, Any], tail: list[str | int]) -> Any:
    node: Any = entry
    for segment in tail:
        if isinstance(segment, str):
            if not isinstance(node, MutableMapping) or segment not in node:
                return None
            node = node[segment]
        elif isinstance(segment, int):
            if not isinstance(node, list) or not (-len(node) <= segment < len(node)):
                return None
            node = node[segment]
        else:
            return None
    return node


def _write_value(entry: MutableMapping[str, Any], tail: list[str | int], value: float) -> None:
    if not tail:
        raise ValueError("Parameter storage path must point to a scalar")
    node: Any = entry
    for segment in tail[:-1]:
        if not isinstance(segment, str):
            raise ValueError("Nested parameter paths must be mappings")
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            child = {}
            node[segment] = child
        node = child
    leaf = tail[-1]
    if not isinstance(leaf, str):
        raise ValueError("Parameter storage path must end in a mapping key")
    node[leaf] = value


def _validate_value(spec: ParameterSpec, value: float) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{spec.id} must be a number")
    bounds = spec.range
    if bounds is None:
        return
    if bounds.minimum is not None and value < bounds.minimum:
        raise ValueError(f"{spec.id} must be >= {bounds.minimum}")
    if bounds.maximum is not None and value > bounds.maximum:
        raise ValueError(f"{spec.id} must be <= {bounds.maximum}")
    if bounds.exclusive_minimum is not None and value <= bounds.exclusive_minimum:
        raise ValueError(f"{spec.id} must be > {bounds.exclusive_minimum}")


def _first_planet_id(resolver: LayerResolver) -> str | None:
    for spec in load_registry().parameters:
        path = _effective_path(resolver, spec)
        if path is None or not path.is_file():
            continue
        entry = _planet_entries(_load_yaml(path))
        if entry:
            return str(entry[0]["id"])
    return None


def _param_editable(
    spec: ParameterSpec,
    *,
    read_only: bool,
    value: Any,
    fork_layer: Layer | None,
) -> tuple[bool, str | None]:
    if read_only:
        return False, "read_only"
    if value is None:
        return False, "missing"
    if fork_layer is not None:
        earliest = min(get_layer_index(layer) for layer in spec.consumers)
        if earliest < get_layer_index(fork_layer):
            return False, "fork"
    return True, None


def read_lab(
    world_dir: Path,
    branch: str | None,
    planet_id: str | None,
    *,
    read_only: bool,
) -> dict[str, Any]:
    """Read the effective values for one planet and the current revision."""
    resolver = LayerResolver(world_dir, branch)
    fork_layer = resolver.get_fork_layer()
    specs = list(load_registry().parameters)
    selected = planet_id or _first_planet_id(resolver)
    if selected is None:
        raise ParameterLabUnavailableError("planet")

    documents: dict[Path, Any] = {}
    effective_paths: list[Path] = []
    parameters: list[dict[str, Any]] = []
    for spec in specs:
        path = _effective_path(resolver, spec)
        if path is not None:
            effective_paths.append(path)
        entry = None
        tail = _planet_path_tail(spec)
        if path is not None and tail is not None and path.is_file():
            document = documents.setdefault(path, _load_yaml(path))
            entry = _planet_entry(document, selected)
        value = _read_value(entry, tail) if entry is not None and tail is not None else None
        editable, reason = _param_editable(
            spec, read_only=read_only, value=value, fork_layer=fork_layer
        )
        parameters.append(
            {
                "id": spec.id,
                "group": spec.group.value,
                "value": float(value) if isinstance(value, int | float) else None,
                "unit": spec.unit,
                "range": spec.range.model_dump(by_alias=True, exclude_none=True)
                if spec.range is not None
                else None,
                "consumers": [layer.value for layer in spec.consumers],
                "source": path.relative_to(world_dir).as_posix() if path is not None else None,
                "editable": editable,
                "reason": reason,
            }
        )
    return {
        "planet": selected,
        "branch": branch,
        "fork_layer": fork_layer.value if fork_layer is not None else None,
        "read_only": read_only,
        "revision": _revision(effective_paths, world_dir),
        "parameters": parameters,
    }


def _affected_layers(values: dict[str, float]) -> list[Layer]:
    specs = {spec.id: spec for spec in load_registry().parameters}
    layers: set[Layer] = set()
    for parameter_id in values:
        spec = specs.get(parameter_id)
        if spec is None:
            raise ValueError(f"Unknown parameter id: {parameter_id}")
        layers.update(spec.consumers)
    return sorted(layers, key=get_layer_index)


def _save_yaml(path: Path, mutate: Callable[[Any], None]) -> None:
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    editor = YAML()
    editor.preserve_quotes = True
    data = editor.load(text)
    mutate(data)
    buffer = StringIO()
    editor.dump(data, buffer)
    with NamedTemporaryFile(
        dir=path.parent, mode="w", encoding="utf-8", newline=newline, delete=False
    ) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(buffer.getvalue())
            temp.close()
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)


def save_lab(
    world_dir: Path,
    branch: str | None,
    planet_id: str | None,
    values: dict[str, float],
    revision: str | None,
    *,
    read_only: bool,
) -> dict[str, Any]:
    """Save parameter values for one planet, preserving YAML formatting."""
    if not values:
        raise ValueError("No parameter values were provided")
    state = read_lab(world_dir, branch, planet_id, read_only=read_only)
    if read_only:
        raise ParameterLabReadOnlyError("read_only")
    if revision is not None and revision != state["revision"]:
        raise ParameterLabConflictError("revision")

    specs = {spec.id: spec for spec in load_registry().parameters}
    by_file: dict[str, dict[str, float]] = {}
    for parameter_id, value in values.items():
        spec = specs.get(parameter_id)
        if spec is None:
            raise ValueError(f"Unknown parameter id: {parameter_id}")
        _validate_value(spec, float(value))
        editable = next(
            (parameter for parameter in state["parameters"] if parameter["id"] == parameter_id),
            None,
        )
        if editable is None or not editable["editable"]:
            reason = editable["reason"] if editable is not None else "missing"
            raise ParameterLabReadOnlyError(reason)
        by_file.setdefault(spec.storage.file, {})[parameter_id] = float(value)

    resolver = LayerResolver(world_dir, branch)
    for file_values in by_file.values():
        spec = next(specs[parameter_id] for parameter_id in file_values)
        source = _effective_path(resolver, spec)
        if source is None or not source.is_file():
            raise ParameterLabUnavailableError(spec.storage.file)
        target = _target_path(world_dir, branch, spec)
        if target != source:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)

        def mutate(document: Any, *, file_values: dict[str, float] = file_values) -> None:
            entry = _planet_entry(document, str(state["planet"]))
            if entry is None:
                raise ParameterLabUnavailableError(str(state["planet"]))
            for parameter_id, value in file_values.items():
                tail = _planet_path_tail(specs[parameter_id])
                if tail is None:
                    raise ValueError(f"Unsupported storage path for {parameter_id}")
                _write_value(entry, tail, value)

        _save_yaml(target, mutate)

    updated = read_lab(world_dir, branch, state["planet"], read_only=read_only)
    affected = _affected_layers(values)
    updated["affected"] = [layer.value for layer in affected]
    updated["start_layer"] = affected[0].value if affected else None
    return updated


def save_as_branch(
    world_dir: Path,
    base_branch: str | None,
    name: str,
    planet_id: str | None,
    values: dict[str, float],
) -> dict[str, Any]:
    """Create a branch at the earliest consumer layer and save the values."""
    if not values:
        raise ValueError("No parameter values were provided")
    affected = _affected_layers(values)
    fork_layer = affected[0]
    manager = BranchManager(world_dir)
    manager.create_branch(name, fork_layer, parent=base_branch)
    try:
        state = save_lab(
            world_dir,
            name,
            planet_id,
            values,
            revision=None,
            read_only=False,
        )
    except Exception:
        manager.delete_branch(name)
        raise
    state["branch"] = name
    state["fork_layer"] = fork_layer.value
    state["affected"] = [layer.value for layer in affected]
    state["start_layer"] = fork_layer.value
    return state
