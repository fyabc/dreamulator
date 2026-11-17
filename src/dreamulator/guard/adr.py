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

import yaml
from jinja2.exceptions import TemplateError

from dreamulator.guard.facts import build_fact_context
from dreamulator.guard.stale import (
    RENDERED_BODY_KEY,
    check_decision_records,
    layer_input_fingerprint,
    read_baseline,
    render_checked_body,
    render_claims,
    write_baseline,
)
from dreamulator.guard.storage import (
    atomic_write_text,
    design_notes_dir,
    read_document,
    writable_design_notes_dir,
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


def _find_adr(world_dir: Path, adr_id: str, branch: str | None = None) -> Path:
    """Resolve an ADR id (``0001`` or ``0001-stellar-parameters``) to its file."""
    design_dir = writable_design_notes_dir(world_dir, branch)
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
    return yaml.safe_dump({"checked_against": fingerprints}, sort_keys=False).splitlines(
        keepends=True
    )


def _frontmatter_of(doc: Path) -> dict[str, object]:
    fm, _ = read_document(doc)
    return fm


def _status_of(doc: Path) -> str | None:
    status = _frontmatter_of(doc).get("status")
    return str(status) if status is not None else None


def _is_archived(doc: Path) -> bool:
    return bool(_frontmatter_of(doc).get("archived", False))


def count_accepted(world_dir: Path, branch: str | None = None) -> int:
    """Count ADR records currently ``accepted`` **and visible** (active ledger).

    Archived records stay ``accepted`` (their conclusions remain valid — see
    ``archive``); they just no longer occupy active-ledger capacity.
    """
    design_dir = design_notes_dir(world_dir, branch)
    if not design_dir.exists():
        return 0
    return sum(
        1
        for d in sorted(design_dir.glob("*.md"))
        if _status_of(d) == "accepted" and not _is_archived(d)
    )


def archive(
    world_dir: Path, limit: int = DEFAULT_MAX_ACCEPTED, branch: str | None = None
) -> list[Path]:
    """Hide the oldest ``accepted`` records from the active ledger until count ≤ limit.

    GUARD-01 (astra proposals-review §3.3): sets an ``archived: true``
    **visibility** field — it does NOT rewrite ``status``.  Storage/reading
    capacity is not evidence that a conclusion became invalid; the former
    behaviour silently deprecated still-accepted records, corrupting the
    ledger's truth.  Archived records keep ``status: accepted``, remain
    subject to stale detection (②/③ still scan every design-notes file), and
    can be restored by removing the field.  Returns the archived paths.
    """
    if limit < 0:
        raise ValueError("Archive limit must be non-negative")
    design_dir = writable_design_notes_dir(world_dir, branch)
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
        atomic_write_text(doc, content)
        archived.append(doc)
    return archived


def accept(
    world_dir: Path, branch: str | None, adr_id: str, limit: int = DEFAULT_MAX_ACCEPTED
) -> Path:
    """``proposed → accepted``: stamp status + fingerprints + rendered baseline.

    Validate evidence and capacity before saving all layer fingerprints,
    complete rendered text, and accepted status. An unchanged accepted record
    is a no-op; changed or retired records require a new decision.
    """
    if limit < 1:
        raise ValueError("Accept limit must be positive")
    doc = _find_adr(world_dir, adr_id, branch)
    content = doc.read_text(encoding="utf-8")
    fm, body = read_document(doc)
    status = fm.get("status")
    if status not in {"proposed", "accepted"}:
        raise ValueError(
            "Only a proposed record can be accepted; write a new decision for a retired record"
        )
    baseline = read_baseline(world_dir, branch)
    if status == "accepted":
        rel = doc.relative_to(world_dir).as_posix()
        findings = [f for f in check_decision_records(world_dir, branch) if f.path == rel]
        if findings or doc.name not in baseline:
            raise ValueError(
                "Accepted record needs review; restore its baseline "
                "or supersede it with a new decision"
            )
        # Repeating an unchanged acceptance is a no-op, not a new baseline.
        return doc
    if not _is_archived(doc) and count_accepted(world_dir, branch) >= limit:
        raise ValueError(
            f"ADR ledger is full ({limit} accepted records); run `guard archive` first"
        )

    context = build_fact_context(world_dir, branch)
    if context is None:
        raise ValueError(
            "Fact context unavailable; build this world or branch before accepting a decision"
        )
    try:
        claims = render_claims(body, context)
        claims[RENDERED_BODY_KEY] = render_checked_body(body, context)
    except (TemplateError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"Decision claims cannot be verified: {exc}") from exc
    fingerprints = {
        layer: layer_input_fingerprint(world_dir, branch, layer) for layer in _CHECKED_LAYERS
    }
    content = _set_frontmatter_field(content, "status", ["status: accepted\n"])
    content = _set_frontmatter_field(
        content, "checked_against", _checked_against_block(fingerprints)
    )
    baseline[doc.name] = claims
    # Publish the evidence first. Interrupted writes must never leave an
    # accepted decision whose baseline was not saved.
    write_baseline(world_dir, baseline, branch)
    atomic_write_text(doc, content)
    return doc


def supersede(world_dir: Path, adr_id: str, by: str, branch: str | None = None) -> Path:
    """``→ superseded by <by>``: mark an ADR superseded by a newer record.

    Only the ``status`` field changes; the conclusion body is never edited.
    """
    doc = _find_adr(world_dir, adr_id, branch)
    replacement = _find_adr(world_dir, by, branch)
    if replacement == doc:
        raise ValueError("A decision cannot supersede itself")
    if _status_of(replacement) != "accepted":
        raise ValueError("The replacement decision must be accepted first")
    target_status = f"superseded by {replacement.stem}"
    if _status_of(doc) == target_status:
        return doc
    if _status_of(doc) not in {"proposed", "accepted"}:
        raise ValueError("A retired decision cannot be superseded again")
    content = doc.read_text(encoding="utf-8")
    content = _set_frontmatter_field(content, "status", [f"status: {target_status}\n"])
    atomic_write_text(doc, content)
    return doc


def deprecate(world_dir: Path, adr_id: str, branch: str | None = None) -> Path:
    """``→ deprecated``: retire an ADR whose premise no longer holds."""
    doc = _find_adr(world_dir, adr_id, branch)
    if _status_of(doc) == "deprecated":
        return doc
    if _status_of(doc) not in {"proposed", "accepted"}:
        raise ValueError("A superseded decision cannot be deprecated")
    content = doc.read_text(encoding="utf-8")
    content = _set_frontmatter_field(content, "status", ["status: deprecated\n"])
    atomic_write_text(doc, content)
    return doc
