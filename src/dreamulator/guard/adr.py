"""ADR（决策记录）状态机 —— 台账的写操作（harness.md §8）。

``stale.py`` 做**检测**（只读），本模块做**处置**（写 status + checked_against +
baseline）——「检测 ≠ 裁决」，裁决在这里显式发生：

- ``accept``    proposed → accepted（写 checked_against 指纹 + 渲染基线）
- ``supersede`` → superseded by <编号>（旧记录永不编辑结论，只改状态）
- ``deprecate`` → deprecated（设定弃用但历史保留）

纯函数式文件操作、无 RNG；每条操作只改 frontmatter 的 ``status`` /
``checked_against``，不动正文（harness.md §8「永不编辑 accepted 记录」）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.doc_render import parse_frontmatter
from dreamulator.guard.facts import build_fact_context
from dreamulator.guard.stale import (
    layer_input_fingerprint,
    read_baseline,
    render_claims,
    write_baseline,
)
from dreamulator.models.layers import LAYER_ORDER

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DEFAULT_MAX_ACCEPTED",
    "accept",
    "archive",
    "count_accepted",
    "deprecate",
    "supersede",
]

# GUARD-01 (astra proposals-review §3.3): fingerprint *every* layer, not just
# the system_catalog feeders.  A climate/ecology/civilization argument depends
# on its own layer's authored inputs too; unconfigured layers record "" (or
# the no-yaml sentinel) — harmless, and if an input dir appears later the
# fingerprint change fires ② exactly as it should.
_CHECKED_LAYERS: tuple[str, ...] = tuple(layer.value for layer in LAYER_ORDER)

# Ledger capacity: max concurrently-``accepted`` records per world (harness.md §8.2,
# Hermes "capacity limit + fail-on-overflow" — an unbounded ledger becomes a graveyard).
DEFAULT_MAX_ACCEPTED = 20


def _find_adr(world_dir: Path, adr_id: str) -> Path:
    """Resolve an ADR id (``0001`` or ``0001-stellar-parameters``) to its file."""
    design_dir = world_dir / "design-notes"
    adr_id = adr_id.removesuffix(".md")
    candidates = [
        d
        for d in sorted(design_dir.glob("*.md"))
        if d.stem == adr_id or d.stem.startswith(adr_id + "-")
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(f"no ADR matching '{adr_id}' in {design_dir}")
    raise ValueError(f"ambiguous ADR id '{adr_id}': {[c.name for c in candidates]}")


def _set_frontmatter_field(content: str, key: str, value_lines: list[str]) -> str:
    """Surgically set a top-level frontmatter key, preserving the rest.

    Replaces an existing key's block (its line + following indented lines) with
    ``value_lines``, or inserts before the closing ``---`` when absent.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("document has no frontmatter")

    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        raise ValueError("frontmatter is not closed")

    fm = lines[1:closing]
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(fm):
        line = fm[i]
        if line.rstrip("\n").startswith(key + ":"):
            i += 1
            while i < len(fm) and fm[i].startswith(" "):
                i += 1
            if value_lines:
                out.extend(value_lines)
            replaced = True
            continue
        out.append(line)
        i += 1
    if not replaced and value_lines:
        out.extend(value_lines)

    return "".join(lines[:1] + out + lines[closing:])


def _checked_against_block(fingerprints: dict[str, str]) -> list[str]:
    lines = ["checked_against:\n"]
    lines.extend(f"  {layer}: {fp}\n" for layer, fp in fingerprints.items())
    return lines


def _frontmatter_of(doc: Path) -> dict[str, object]:
    fm, _ = parse_frontmatter(doc.read_text(encoding="utf-8"))
    return fm


def _status_of(doc: Path) -> str | None:
    status = _frontmatter_of(doc).get("status")
    return str(status) if status is not None else None


def _is_archived(doc: Path) -> bool:
    return bool(_frontmatter_of(doc).get("archived", False))


def count_accepted(world_dir: Path) -> int:
    """Count ADR records currently ``accepted`` **and visible** (active ledger).

    Archived records stay ``accepted`` (their conclusions remain valid — see
    ``archive``); they just no longer occupy active-ledger capacity.
    """
    design_dir = world_dir / "design-notes"
    if not design_dir.exists():
        return 0
    return sum(
        1
        for d in sorted(design_dir.glob("*.md"))
        if _status_of(d) == "accepted" and not _is_archived(d)
    )


def archive(world_dir: Path, limit: int = DEFAULT_MAX_ACCEPTED) -> list[Path]:
    """Hide the oldest ``accepted`` records from the active ledger until count ≤ limit.

    GUARD-01 (astra proposals-review §3.3): sets an ``archived: true``
    **visibility** field — it does NOT rewrite ``status``.  Storage/reading
    capacity is not evidence that a conclusion became invalid; the former
    behaviour silently deprecated still-accepted records, corrupting the
    ledger's truth.  Archived records keep ``status: accepted``, remain
    subject to stale detection (②/③ still scan every design-notes file), and
    can be restored by removing the field.  Returns the archived paths.
    """
    design_dir = world_dir / "design-notes"
    accepted = [
        d
        for d in sorted(design_dir.glob("*.md"))
        if _status_of(d) == "accepted" and not _is_archived(d)
    ]
    overflow = max(0, len(accepted) - limit)

    archived: list[Path] = []
    for doc in accepted[:overflow]:
        content = doc.read_text(encoding="utf-8")
        content = _set_frontmatter_field(content, "archived", ["archived: true\n"])
        doc.write_text(content, encoding="utf-8")
        archived.append(doc)
    return archived


def accept(
    world_dir: Path, branch: str | None, adr_id: str, limit: int = DEFAULT_MAX_ACCEPTED
) -> Path:
    """``proposed → accepted``: stamp status + fingerprints + rendered baseline.

    Writes ``status: accepted`` and ``checked_against`` for the system_catalog
    source layers, then (re)records the ADR's rendered claims in the baseline
    (③).  Fails with ``ValueError`` when accepting a non-accepted record would
    exceed the ledger capacity (``limit``) — archive first, don't silently overflow.
    """
    doc = _find_adr(world_dir, adr_id)
    content = doc.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    if fm.get("status") != "accepted" and count_accepted(world_dir) >= limit:
        raise ValueError(
            f"ADR ledger is full ({limit} accepted records); run `guard archive` first"
        )

    fingerprints = {
        layer: layer_input_fingerprint(world_dir, branch, layer) for layer in _CHECKED_LAYERS
    }
    content = _set_frontmatter_field(content, "status", ["status: accepted\n"])
    content = _set_frontmatter_field(
        content, "checked_against", _checked_against_block(fingerprints)
    )
    doc.write_text(content, encoding="utf-8")

    context = build_fact_context(world_dir, branch)
    if context is not None:
        baseline = read_baseline(world_dir)
        baseline[doc.name] = render_claims(body, context)
        write_baseline(world_dir, baseline)

    return doc


def supersede(world_dir: Path, adr_id: str, by: str) -> Path:
    """``→ superseded by <by>``: mark an ADR superseded by a newer record.

    Only the ``status`` field changes; the conclusion body is never edited.
    """
    doc = _find_adr(world_dir, adr_id)
    content = doc.read_text(encoding="utf-8")
    content = _set_frontmatter_field(content, "status", [f"status: superseded by {by}\n"])
    doc.write_text(content, encoding="utf-8")
    return doc


def deprecate(world_dir: Path, adr_id: str) -> Path:
    """``→ deprecated``: retire an ADR whose premise no longer holds."""
    doc = _find_adr(world_dir, adr_id)
    content = doc.read_text(encoding="utf-8")
    content = _set_frontmatter_field(content, "status", ["status: deprecated\n"])
    doc.write_text(content, encoding="utf-8")
    return doc
