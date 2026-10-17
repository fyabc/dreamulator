"""Unit tests for the refine orchestrator's platform-dependent helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dreamulator.media.terrain_refine import _td_python

if TYPE_CHECKING:
    from pathlib import Path


def test_td_python_accepts_linux_venv_layout(tmp_path: Path) -> None:
    """The server refines on Linux, where uv venv puts the interpreter at
    .venv/bin/python (handoff 2026-10-16 #1 — it used to symlink this into
    Scripts/python.exe just to be found)."""
    repo = tmp_path / "td"
    py = repo / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    assert _td_python(repo) == py


def test_td_python_prefers_windows_layout(tmp_path: Path) -> None:
    """On Windows the native Scripts/python.exe layout wins when both exist."""
    repo = tmp_path / "td"
    linux = repo / ".venv" / "bin" / "python"
    linux.parent.mkdir(parents=True)
    linux.write_text("", encoding="utf-8")
    win = repo / ".venv" / "Scripts" / "python.exe"
    win.parent.mkdir(parents=True)
    win.write_text("", encoding="utf-8")
    assert _td_python(repo) == win


def test_td_python_missing_venv_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="terrain-diffusion venv not found"):
        _td_python(tmp_path / "nowhere")
