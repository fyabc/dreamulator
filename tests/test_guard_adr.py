"""Tests for dreamulator.guard.adr — the decision-record state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from dreamulator.doc_render import parse_frontmatter
from dreamulator.guard.adr import accept, archive, count_accepted, deprecate, supersede
from dreamulator.guard.stale import read_baseline

if TYPE_CHECKING:
    from pathlib import Path

_CATALOG: dict[str, object] = {
    "stars": [{"id": "star_sol", "name": "Sol", "luminosity_sol": 1.0}],
    "bodies": [],
}


def _write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)


def _make_world(root: Path) -> Path:
    world = root / "test-world"
    _write_yaml(world / "layers" / "astronomy" / "input" / "stellar.yaml", {"stars": []})
    _write_yaml(world / "layers" / "astronomy" / "derived" / "system_catalog.yaml", _CATALOG)
    return world


def _write_adr(world: Path, name: str, status: str, body: str = "body\n") -> Path:
    path = world / "design-notes" / name
    _write_text(path, f"---\ntitle: Test\nstatus: {status}\n---\n{body}")
    return path


def _status(world: Path, name: str) -> str:
    content = (world / "design-notes" / name).read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(content)
    return str(fm["status"])


def test_accept_stamps_status_and_fingerprints(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-test.md", "proposed")

    path = accept(world, None, "0001")

    assert path.name == "0001-test.md"
    fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fm["status"] == "accepted"
    assert set(fm["checked_against"]) == {"astronomy", "geological"}


def test_accept_records_baseline_claims(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-test.md", "proposed", "x {{ entities.star_sol.luminosity_sol }} y\n")

    accept(world, None, "0001")

    baseline = read_baseline(world)
    assert baseline["0001-test.md"] == {"{{ entities.star_sol.luminosity_sol }}": "1.0"}


def test_supersede_marks_status(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-test.md", "accepted")

    supersede(world, "0001", "0002-new")

    assert _status(world, "0001-test.md") == "superseded by 0002-new"


def test_deprecate_marks_status(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-test.md", "accepted")

    deprecate(world, "0001")

    assert _status(world, "0001-test.md") == "deprecated"


def test_frontmatter_surgery_preserves_other_fields(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    path = world / "design-notes" / "0001-test.md"
    _write_text(
        path,
        '---\ntitle: "My ADR"\ntype: design\ntags: [a, b]\nstatus: proposed\n---\nbody\n',
    )

    accept(world, None, "0001")

    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fm["title"] == "My ADR"
    assert fm["type"] == "design"
    assert fm["tags"] == ["a", "b"]
    assert body == "body\n"


# ---------------------------------------------------------------------------
# 台账容量上限 + archive（harness.md §8.2）
# ---------------------------------------------------------------------------


def test_count_accepted(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-a.md", "accepted")
    _write_adr(world, "0002-b.md", "deprecated")
    _write_adr(world, "0003-c.md", "accepted")
    assert count_accepted(world) == 2


def test_archive_prunes_oldest_accepted(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    for i in range(5):
        _write_adr(world, f"000{i + 1}-r.md", "accepted")

    archived = archive(world, limit=3)

    assert [p.name for p in archived] == ["0001-r.md", "0002-r.md"]
    assert count_accepted(world) == 3
    assert _status(world, "0001-r.md") == "deprecated"
    assert _status(world, "0003-r.md") == "accepted"


def test_archive_noop_within_limit(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    _write_adr(world, "0001-r.md", "accepted")
    assert archive(world, limit=3) == []


def test_accept_rejects_when_ledger_full(tmp_path: Path) -> None:
    world = _make_world(tmp_path)
    for i in range(3):
        _write_adr(world, f"000{i + 1}-r.md", "accepted")
    _write_adr(world, "0009-new.md", "proposed")

    with pytest.raises(ValueError, match="ledger is full"):
        accept(world, None, "0009-new", limit=3)


def test_accept_idempotent_reaccept_at_limit(tmp_path: Path) -> None:
    """Re-accepting an already-accepted record does not hit the capacity limit."""
    world = _make_world(tmp_path)
    for i in range(3):
        _write_adr(world, f"000{i + 1}-r.md", "accepted")

    accept(world, None, "0001", limit=3)  # no raise
