"""Mirror the canonical project skills into the Claude Code skill directory.

The single source is ``.agents/skills/<name>/`` (Agent Skills format, read by
Codex). Claude Code reads ``.claude/skills/<name>/`` instead, so this script
writes real-file copies there. Symlinks are deliberately avoided: on Windows
they need Administrator rights or Developer Mode, and a clone without
``core.symlinks`` checks them out as one-line text files.

Usage::

    uv run python scripts/dev/sync_agent_skills.py          # write the mirror
    uv run python scripts/dev/sync_agent_skills.py --check  # exit 1 on drift
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".agents" / "skills"
MIRROR = ROOT / ".claude" / "skills"


def _files(base: Path) -> dict[Path, bytes]:
    """Relative path → content with line endings normalised to LF."""
    if not base.is_dir():
        return {}
    return {
        path.relative_to(base): path.read_bytes().replace(b"\r\n", b"\n")
        for path in sorted(base.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def drift(source: Path = SOURCE, mirror: Path = MIRROR) -> list[str]:
    """Describe every difference between the canonical skills and the mirror."""
    wanted, present = _files(source), _files(mirror)
    problems = [f"missing in mirror: {p.as_posix()}" for p in wanted if p not in present]
    problems += [f"not in source: {p.as_posix()}" for p in present if p not in wanted]
    problems += [
        f"content differs: {p.as_posix()}"
        for p in wanted
        if p in present and wanted[p] != present[p]
    ]
    return problems


def sync(source: Path = SOURCE, mirror: Path = MIRROR) -> None:
    """Replace the mirror with a byte copy (LF endings) of the source tree."""
    if not source.is_dir():
        raise FileNotFoundError(f"canonical skill directory not found: {source}")
    if mirror.exists():
        shutil.rmtree(mirror)
    for relative, content in _files(source).items():
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()
    if args.check:
        problems = drift()
        for line in problems:
            print(line)
        if problems:
            print("run: uv run python scripts/dev/sync_agent_skills.py")
            return 1
        print("agent skills are in sync")
        return 0
    sync()
    print(f"mirrored {len(_files(SOURCE))} file(s) into {MIRROR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
