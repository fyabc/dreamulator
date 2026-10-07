"""Per-layer build status for the world-detail UI (LayerDag freshness).

The world.yaml ``layers.<name>.configured`` flag is a hand-maintained intent
declaration that goes stale immediately after creation, so it carries no
information about the actual state of a world's data.  This module computes
the real per-layer status on demand from the filesystem:

- ``input_source``   — where the layer's input comes from (resolver's
  ``root`` / ``branch:<name>`` / ``not configured``).
- ``input_doc_count`` — number of authored ``*.md`` documents.
- ``derived_fresh``  — ``fresh`` / ``stale`` / ``absent``: whether the
  derived products are older than the layer's input YAML files.
- ``last_build_time`` — newest mtime across the layer's derived products.

Philosophy notes:

- The input side hashes **YAML only** (recursive), mirroring
  ``guard.stale.layer_input_fingerprint``: a narrative ``.md`` edit must not
  mark physics as stale.
- The derived side for the geological layer includes ``maps/<planet>/``
  because the terrain pipeline's products (cvt mesh, elevation, plates)
  live there, not in ``layers/geological/derived/``.
- This is a display heuristic (mtime comparison), not a content check; the
  pipeline's own dirty check and the guard fingerprints remain authoritative
  for rebuild and audit decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver

if TYPE_CHECKING:
    from pathlib import Path


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
) -> dict[str, object]:
    """Compute the on-disk build status of one layer.

    Args:
        world_dir: Path to the world directory (root, not the branch dir).
        layer: Layer identifier (Layer enum or its value).
        branch: Optional branch name to resolve through.

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

    # Derived side: the resolved derived dir; for geological the products
    # also live under maps/<planet>/ (terrain pipeline writes there).
    layer_value = layer.value if isinstance(layer, Layer) else str(layer)
    derived_roots: list[Path] = []
    if source.derived_dir is not None:
        derived_roots.append(source.derived_dir)
    if layer_value == Layer.GEOLOGICAL.value:
        scope_dir = world_dir / "branches" / branch if branch else world_dir
        maps_dir = scope_dir / "maps"
        if maps_dir.is_dir():
            derived_roots.extend(child for child in maps_dir.iterdir() if child.is_dir())
    newest: float | None = None
    for root in derived_roots:
        root_mtime = _tree_newest_mtime(root)
        if root_mtime is not None and (newest is None or root_mtime > newest):
            newest = root_mtime
    derived_mtime = newest

    if derived_mtime is None:
        derived_fresh = "absent"
    elif input_mtime is not None and input_mtime > derived_mtime:
        derived_fresh = "stale"
    else:
        derived_fresh = "fresh"

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
            status = compute_layer_status(world_dir, name, branch=branch)
        except ValueError:
            # Unknown layer identifier — leave the entry as-is.
            continue
        info = dict(info)
        info.update(status)
        out[name] = info
    return out
