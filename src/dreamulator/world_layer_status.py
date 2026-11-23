"""Per-layer build status for the world-detail UI (LayerDag freshness).

The world.yaml ``layers.<name>.configured`` flag is a hand-maintained intent
declaration that goes stale immediately after creation, so it carries no
information about the actual state of a world's data.  This module computes
the real per-layer status on demand from the filesystem:

- ``input_source``   — where the layer's input comes from (resolver's
  ``root`` / ``branch:<name>`` / ``not configured``).
- ``input_doc_count`` — number of authored ``*.md`` documents.
- ``derived_fresh``  — ``fresh`` / ``stale`` / ``absent``: compared with the
  layer's recorded input projection when one exists, otherwise whether the
  derived products are older than the input YAML files.
- ``last_build_time`` — newest mtime across the layer's derived products.

Philosophy notes:

- A successful build records a per-layer input projection
  (``parameter_projection.py``): parsed YAML hashes plus the registered shared
  parameters that layer consumes.  Registered fields it does not consume are
  stripped first, so editing albedo does not mark the geological layer stale;
  unregistered fields stay in the hash and remain conservative.  Comment and
  formatting edits do not count.
- Without a record (older builds) the mtime comparison below is the fallback,
  so a layer becomes projection-aware after its next successful build.
- Narrative ``.md`` edits never participate: only the engine's declared input
  files do.
- The derived side for the geological layer includes ``maps/<planet>/``
  because the terrain pipeline's products (cvt mesh, elevation, plates)
  live there, not in ``layers/geological/derived/``.
- This is a display heuristic; the pipeline's own dirty check and the guard
  fingerprints remain authoritative for rebuild and audit decisions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _tree_newest_mtime(root: Path | None) -> float | None:
    """Newest file mtime under ``root`` (recursive); None if no files."""
    if root is None or not root.is_dir():
        return None
    newest: float | None = None
    for p in root.rglob("*"):
        if p.is_file():
            m = p.stat().st_mtime
            if newest is None or m > newest:
                newest = m
    return newest


def compute_layer_status(
    world_dir: Path,
    layer: Layer | str,
    *,
    branch: str | None = None,
    seed: int | None = None,
) -> dict[str, object]:
    """Compute the on-disk build status of one layer.

    Args:
        world_dir: Path to the world directory (root, not the branch dir).
        layer: Layer identifier (Layer enum or its value).
        branch: Optional branch name to resolve through.
        seed: Optional world seed. When given and a recorded input projection
            exists, freshness compares projections instead of mtimes.

    Returns:
        Dict with ``input_source``, ``input_doc_count``, ``derived_fresh``
        and ``last_build_time`` — the LayerSummary extension fields.
    """
    resolver = LayerResolver(world_dir, branch)
    source = resolver.resolve_layer(layer)

    # Input side: authored markdown count + newest YAML mtime (recursive).
    doc_count = len(resolver.list_input_files(layer, "*.md"))
    input_mtime: float | None = None
    if source.input_dir is not None:
        for p in sorted(source.input_dir.rglob("*.yaml")):
            m = p.stat().st_mtime
            if input_mtime is None or m > input_mtime:
                input_mtime = m

    # Derived side: the effective derived dir. It is resolved independently
    # of the input dir because engines build with defaults for layers that
    # declare no input, and branches write derived data below inherited inputs.
    layer_value = layer.value if isinstance(layer, Layer) else str(layer)
    derived_roots: list[Path] = []
    derived_dir = resolver.find_derived_dir(layer)
    if derived_dir is not None:
        derived_roots.append(derived_dir)
    if layer_value == Layer.GEOLOGICAL.value:
        # The terrain pipeline writes its products under maps/<planet>/;
        # use the most specific scope that has any.
        for scope_dir in resolver.iter_scope_dirs():
            maps_dir = scope_dir / "maps"
            if not maps_dir.is_dir():
                continue
            planet_dirs = [
                child
                for child in sorted(maps_dir.iterdir())
                if child.is_dir() and any(child.iterdir())
            ]
            if planet_dirs:
                derived_roots.extend(planet_dirs)
                break
    newest: float | None = None
    for root in derived_roots:
        root_mtime = _tree_newest_mtime(root)
        if root_mtime is not None and (newest is None or root_mtime > newest):
            newest = root_mtime
    derived_mtime = newest

    derived_fresh: str
    if derived_mtime is None:
        derived_fresh = "absent"
    else:
        projected: str | None = None
        if seed is not None:
            from dreamulator.parameter_projection import (
                current_input_projection,
                load_input_projection,
            )

            record = load_input_projection(resolver.find_derived_dir(layer))
            if record is not None:
                try:
                    current = current_input_projection(world_dir, layer, branch, seed)
                except Exception:  # noqa: BLE001 - status must not fail the plan
                    logger.warning(
                        "Could not compute input projection for %s", layer, exc_info=True
                    )
                    current = None
                if current is not None:
                    projected = "fresh" if current == record else "stale"
        if projected is None:
            projected = (
                "stale" if input_mtime is not None and input_mtime > derived_mtime else "fresh"
            )
        derived_fresh = projected

    return {
        "input_source": source.source if source.input_dir is not None else None,
        "input_doc_count": doc_count,
        "derived_fresh": derived_fresh,
        "last_build_time": (
            datetime.fromtimestamp(derived_mtime, tz=UTC).isoformat()
            if derived_mtime is not None
            else None
        ),
    }


def enrich_layer_summaries(
    world_dir: Path,
    layers: dict[str, dict[str, object]],
    *,
    branch: str | None = None,
    seed: int | None = None,
) -> dict[str, dict[str, object]]:
    """Augment a serialized ``WorldConfig.layers`` dict with build status.

    Used by the world-info API and the static exporter so both surfaces show
    the same freshness fields.  Layers missing from the dict are not added;
    unknown layer keys are passed through untouched (status fields attach
    wherever the resolver recognises the layer).
    """
    out = dict(layers)
    for name, info in out.items():
        if not isinstance(info, dict):
            continue
        try:
            status = compute_layer_status(world_dir, name, branch=branch, seed=seed)
        except ValueError:
            # Unknown layer identifier — leave the entry as-is.
            continue
        info = dict(info)
        info.update(status)
        out[name] = info
    return out
