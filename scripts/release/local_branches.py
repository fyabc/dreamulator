"""Local-only branch detection for release/export scripts.

Gitignored branches (e.g. the ``bridge-*`` counterfactuals, regeneratable via
``scripts/climate/build_bridge_branches.py``) are local diagnostic experiments
and must not reach the public site — neither via the static export
(``export_static.py``) nor via the release tarball (``publish_world_data.py``).
``.gitignore`` is the single source of truth; one batched ``git check-ignore``
call keeps this cheap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def local_only_branches(root: Path, world_dir: Path) -> set[str]:
    """Names of the world's branches that gitignore marks as local-only.

    Falls back to no filtering when git is unavailable or the world dir sits
    outside the repo (release CI extracts the data tarball into the repo
    checkout, so .gitignore semantics still apply there).
    """
    branches_dir = world_dir / "branches"
    if not branches_dir.exists():
        return set()
    candidates = [d for d in sorted(branches_dir.iterdir()) if d.is_dir()]
    if not candidates:
        return set()
    try:
        rel = [str(d.relative_to(root)).replace("\\", "/") for d in candidates]
    except ValueError:
        return set()  # world_dir outside the repo — nothing to match against
    try:
        # Bytes, not text=True: text mode translates \n → \r\n on Windows and
        # git then sees a trailing \r as part of the path (no match).
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(rel).encode("utf-8"),
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()  # git not installed
    if proc.returncode not in (0, 1):  # 0 = some ignored, 1 = none ignored
        return set()
    return {
        Path(line).name for line in proc.stdout.decode("utf-8").splitlines() if line.strip()
    }


def under_local_only_branch(path: Path, world_dir: Path, local_only: set[str]) -> bool:
    """True when ``path`` lives inside a local-only branch subtree of the world."""
    if not local_only:
        return False
    try:
        rel = path.relative_to(world_dir).parts
    except ValueError:
        return False
    return len(rel) >= 2 and rel[0] == "branches" and rel[1] in local_only
