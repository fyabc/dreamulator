"""Command tree: object groups at the top level, old `export …` paths hidden but working."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from dreamulator.cli import app


def _help(*path: str) -> str:
    res = CliRunner().invoke(app, [*path, "--help"], terminal_width=120)
    assert res.exit_code == 0, res.output
    return res.output


def _commands(*path: str) -> list[str]:
    """Command names in the order the help lists them."""
    return re.findall(r"^│ ([a-z][a-z-]*) ", _help(*path), flags=re.MULTILINE)


def test_object_groups_are_top_level() -> None:
    top = _commands()
    for group in ("map", "region", "canvas", "render"):
        assert group in top
    assert "export" not in top  # hidden


def test_group_contents() -> None:
    assert _commands("map") == ["layers", "globe"]
    assert _commands("region") == ["pack", "build"]
    assert _commands("canvas") == [
        "plan",
        "refine",
        "generate",
        "status",
        "erode",
        "hydrology",
        "run",
        "window",
        "mosaic",
    ]
    assert "--backfill" in _help("canvas", "plan")
    assert "--river-threshold" in _help("canvas", "hydrology")


def test_old_paths_still_resolve() -> None:
    for path in (
        ("export", "layers"),
        ("export", "globe"),
        ("export", "clouds"),
        ("export", "region"),
        ("export", "build"),
        ("export", "render"),
        ("export", "canvas", "hydrology"),
        ("export", "canvas", "mesh-sea-lake"),
    ):
        _help(*path)
