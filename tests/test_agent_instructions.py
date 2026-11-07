"""Cross-agent instruction files stay paired, small and symlink-free.

``AGENTS.md`` is the single source shared by Claude Code, Codex and other
tools; each sibling ``CLAUDE.md`` only imports it. Skills live in
``.agents/skills`` and are mirrored as real files into ``.claude/skills``.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
STUB_IMPORT = "@AGENTS.md"
#: Codex stops adding project instructions at this many bytes by default.
CODEX_DEFAULT_LIMIT = 32 * 1024


def _tracked(pattern: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", pattern],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [ROOT / name for name in out.decode("utf-8").split("\0") if name]


def test_every_agents_md_has_an_importing_claude_md() -> None:
    agents = _tracked("*AGENTS.md")
    assert ROOT / "AGENTS.md" in agents
    for path in agents:
        stub = path.with_name("CLAUDE.md")
        assert stub.is_file(), f"{stub.relative_to(ROOT)} is missing"
        lines = [
            line.strip()
            for line in stub.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("<!--")
        ]
        assert lines == [STUB_IMPORT], f"{stub.relative_to(ROOT)} must only import AGENTS.md"


def test_every_claude_md_is_a_stub_next_to_agents_md() -> None:
    for stub in _tracked("*CLAUDE.md"):
        assert stub.with_name("AGENTS.md").is_file(), f"{stub.relative_to(ROOT)} has no AGENTS.md"


def test_root_instructions_fit_codex_default_limit() -> None:
    size = len((ROOT / "AGENTS.md").read_bytes())
    assert size < CODEX_DEFAULT_LIMIT, f"root AGENTS.md is {size} bytes"


def test_no_tracked_symlinks() -> None:
    out = subprocess.run(
        ["git", "ls-files", "-s"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout
    links = [line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("120000")]
    assert not links, f"symlinks break Windows clones: {links}"


def test_skills_use_portable_frontmatter() -> None:
    skills = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    assert skills
    for path in skills:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        meta = yaml.safe_load(text.split("---\n", 2)[1])
        assert set(meta) == {"name", "description"}, path
        assert meta["name"] == path.parent.name
        assert meta["description"].strip()


def test_claude_skill_mirror_is_in_sync() -> None:
    spec = importlib.util.spec_from_file_location(
        "sync_agent_skills", ROOT / "scripts" / "dev" / "sync_agent_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.drift() == [], "run scripts/dev/sync_agent_skills.py"
