"""Resolve the existing world/branch storage scopes for the guard ledger."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from dreamulator.branch_manager import BranchManager


def scope_dirs(world_dir: Path, branch: str | None = None) -> list[Path]:
    """Return current branch, its parents, and root, validating branch metadata."""
    result: list[Path] = []
    seen: set[str] = set()
    current = branch
    while current is not None:
        if current in seen:
            raise ValueError(f"Branch inheritance cycle at '{current}'")
        seen.add(current)
        # Read one metadata file, rather than traversing the resolver's chain.
        metadata = BranchManager(world_dir).get_branch(current)
        result.append(world_dir / "branches" / current)
        current = metadata.parent
    result.append(world_dir)
    return result


def design_notes_dir(world_dir: Path, branch: str | None = None) -> Path:
    """Use the nearest design-notes directory, as world document readers do."""
    scopes = scope_dirs(world_dir, branch)
    return next(
        (scope / "design-notes" for scope in scopes if (scope / "design-notes").exists()),
        scopes[0] / "design-notes",
    )


def writable_design_notes_dir(world_dir: Path, branch: str | None = None) -> Path:
    """Require branch-local records for writes; inherited records remain read-only."""
    scope = scope_dirs(world_dir, branch)[0]
    result = scope / "design-notes"
    if branch is not None and not result.exists():
        raise ValueError(
            f"Branch '{branch}' inherits its decision records; copy the records into "
            f"branches/{branch}/design-notes before changing that branch's ledger"
        )
    return result


def input_files(world_dir: Path, branch: str | None, layer: str) -> dict[str, list[Path]]:
    """Collect authored files by relative name, from the current scope to root."""
    # Validate layer names even when the directory does not exist.
    from dreamulator.models.layers import Layer

    Layer(layer)
    files: dict[str, list[Path]] = {}
    for scope in scope_dirs(world_dir, branch):
        directory = scope / "layers" / layer / "input"
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                files.setdefault(path.relative_to(directory).as_posix(), []).append(path)
    return files


def atomic_write_text(path: Path, text: str) -> None:
    """Replace a small ledger file only after its complete contents are written."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_document(doc: Path) -> tuple[dict[str, Any], str]:
    """Read guard metadata strictly; ordinary documents may omit frontmatter."""
    text = doc.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        raise ValueError("Document frontmatter is not closed")
    try:
        metadata = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise ValueError(f"Document frontmatter is invalid: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Document frontmatter must be a mapping")
    if "status" in metadata and not isinstance(metadata["status"], str):
        raise ValueError("The status field must be a string")
    if "archived" in metadata and not isinstance(metadata["archived"], bool):
        raise ValueError("The archived field must be a YAML boolean")
    return metadata, "".join(lines[closing + 1 :])
