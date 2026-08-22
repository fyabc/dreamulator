"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_worlds_dir(tmp_path: Path) -> Path:
    """Create a temporary worlds directory."""
    worlds_dir = tmp_path / "worlds"
    worlds_dir.mkdir()
    return worlds_dir


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project structure with templates."""
    # Copy templates from actual project
    import shutil

    project_root = Path(__file__).resolve().parent.parent
    templates_src = project_root / "data" / "templates"

    if templates_src.exists():
        templates_dst = tmp_path / "data" / "templates"
        shutil.copytree(templates_src, templates_dst)

    return tmp_path
