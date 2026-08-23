#!/usr/bin/env python3
"""Check that code references in docs still point to real code.

Two checks, to keep docs faithful to the codebase as it evolves:

1. **``file:line`` references** (``filename.ext:linenumber``) — the file must
   exist (resolved by basename) and the line must be within the file's current
   line count.
2. **Backtick snake_case symbols** (`` `identifier` ``) — the identifier must
   appear somewhere in the codebase (``.py`` / ``.ts`` / ``.tsx``).  A snake_case
   identifier that no longer appears anywhere is a stale reference (renamed or
   removed symbol).  CamelCase and UPPERCASE identifiers (Köppen codes, class
   names, concept terms) are skipped as too noisy to classify automatically.

Usage::

    uv run python scripts/check_doc_refs.py                 # scan docs/design/pipelines
    uv run python scripts/check_doc_refs.py --docs docs/design/pipelines docs/usage

Exit code 1 when any reference is stale (file missing / line out of range /
identifier not found in code), so it can gate a pre-commit or CI step.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REF_LINE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*\.(?:py|ts|tsx|yaml|json)):(\d+)\b")
_REF_BACKTICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_CODE_ROOTS = ["src", "scripts", "tests", "frontend/src"]
_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".yaml", ".json"}


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _build_basename_map(root: Path) -> dict[str, list[Path]]:
    m: dict[str, list[Path]] = {}
    for code_root in _CODE_ROOTS:
        base = root / code_root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".yaml", ".json"}:
                m.setdefault(p.name, []).append(p)
    return m


def _code_identifiers(root: Path) -> set[str]:
    """All identifiers that appear anywhere in the codebase."""
    idents: set[str] = set()
    for code_root in _CODE_ROOTS:
        base = root / code_root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in _CODE_SUFFIXES:
                text = p.read_text(encoding="utf-8", errors="replace")
                idents.update(_WORD.findall(text))
    return idents


def _is_snake_case(name: str) -> bool:
    return "_" in name and name == name.lower()


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs",
        nargs="*",
        default=["docs/design/pipelines"],
        help="Docs directories to scan (default: docs/design/pipelines — implemented pipelines)",
    )
    args = parser.parse_args()

    root = _find_project_root()
    basename_map = _build_basename_map(root)
    idents = _code_identifiers(root)

    issues: list[tuple[str, str]] = []  # (location, reason)
    line_total = sym_total = 0
    for docs_dir in args.docs:
        base = root / docs_dir
        if not base.exists():
            print(f"WARNING: {docs_dir} not found, skipped", file=sys.stderr)
            continue
        for p in sorted(base.rglob("*.md")):
            rel = str(p.relative_to(root))
            text = p.read_text(encoding="utf-8")

            for m in _REF_LINE.finditer(text):
                line_total += 1
                fname, lineno = m.group(1), int(m.group(2))
                matches = basename_map.get(fname, [])
                if not matches:
                    issues.append((f"{rel}: {fname}:{lineno}", "FILE_NOT_FOUND"))
                elif len(matches) > 1:
                    issues.append((f"{rel}: {fname}:{lineno}", f"AMBIGUOUS ({len(matches)} files)"))
                else:
                    n_lines = _line_count(matches[0])
                    if lineno > n_lines:
                        issues.append(
                            (f"{rel}: {fname}:{lineno}", f"LINE_OUT_OF_RANGE ({n_lines} lines)")
                        )

            for m in _REF_BACKTICK.finditer(text):
                name = m.group(1)
                if not _is_snake_case(name) or name in idents:
                    continue
                sym_total += 1
                issues.append((f"{rel}: `{name}`", "NOT_IN_CODE"))

    print(f"Scanned {args.docs}: {line_total} file:line refs, {sym_total} unknown symbols.")
    if not issues:
        print("All references are valid.")
        return

    print(f"\n{len(issues)} stale references:\n")
    for loc, reason in issues:
        print(f"  {loc}  [{reason}]")
    sys.exit(1)


if __name__ == "__main__":
    main()
