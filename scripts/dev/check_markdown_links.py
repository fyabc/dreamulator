#!/usr/bin/env python3
"""Check that relative links and images in tracked Markdown files resolve.

Companion to ``check_doc_refs.py`` (which audits ``file:line`` code references
in ``docs/design/pipelines/``).  This script audits the navigation layer the
READMEs and docs actually link through:

- inline links ``[text](target)`` and images ``![alt](target)``
- reference-style definitions ``[label]: target`` and their ``[text][label]``
  uses
- raw HTML ``src="..."`` / ``href="..."`` attributes (e.g. the logo ``<img>``)

Checks, per link:

1. the target file exists (resolved relative to the linking file; external
   URLs, ``mailto:`` and bare ``#anchors`` are skipped),
2. when an ``#anchor`` is present and the target is Markdown, the anchor
   matches a heading in that file (GitHub-style slug).

Scope: ``README.md``, ``README.zh-CN.md``, ``docs/**/*.md``,
``packages/**/*.md`` — mirrors what the ``docs`` CI workflow gates.  Private
notes are untracked and never scanned.

Usage::

    uv run python scripts/dev/check_markdown_links.py            # default scope
    uv run python scripts/dev/check_markdown_links.py --root /path/to/repo

Exit code 1 when any link is broken, so it can gate CI.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
from pathlib import Path

_SCAN_GLOBS = ["README.md", "README.zh-CN.md", "docs/**/*.md", "packages/**/*.md"]

# [text](target "title") / ![alt](target) — capture the target only.
_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[\"'][^)]*[\"'])?\s*\)")
# [label]: target (optionally "title") — at line start (≤3 spaces indent).
_REF_DEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s+(\S+)", re.MULTILINE)
# <img src="..."> / <a href="..."> — relative targets only.
_HTML_ATTR = re.compile(
    r"""<(?:img|a)\b[^>]*?\b(?:src|href)\s*=\s*["']([^"']+)["'][^>]*?>""",
    re.IGNORECASE,
)
# Fenced code blocks (``` / ~~~) are stripped before scanning so example code
# with link-like text does not false-positive.  Handles ~ vs ` fences and
# info strings; nesting is not supported (Markdown forbids it anyway).
_CODE_FENCE = re.compile(r"^(?:```|~~~).*$\n?|^```$", re.MULTILINE)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Blank out fenced blocks (open fence line through matching close line)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    fence = ""
    for line in lines:
        stripped = line.lstrip()
        if fence:
            out.append("\n" if line.endswith("\n") else "")
            if stripped.startswith(fence):
                fence = ""
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            out.append("\n" if line.endswith("\n") else "")
            continue
        out.append(line)
    return "".join(out)


def _find_project_root() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    return Path.cwd()


def _slugify(heading: str) -> str:
    """GitHub-style heading anchor: lowercase, drop punctuation, spaces → '-'."""
    text = heading.strip().lower()
    # Strip inline markup that should not contribute to the anchor.
    text = re.sub(r"[`*_]", "", text)
    out: list[str] = []
    for ch in text:
        if ch == " ":
            out.append("-")
        elif ch.isalnum() or ch == "-":
            out.append(ch)
        # other punctuation is dropped
    return "".join(out)


def _headings(md_text: str) -> set[str]:
    return {_slugify(h) for h in _HEADING.findall(md_text)}


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("//")


def _check_file(md_path: Path, root: Path) -> list[str]:
    """Return a list of human-readable failure lines for one Markdown file."""
    failures: list[str] = []
    text = _strip_code_fences(md_path.read_text(encoding="utf-8"))

    targets: list[str] = list(_INLINE_LINK.findall(text))
    targets += list(_HTML_ATTR.findall(text))
    # Reference definitions contribute their targets; reference *uses* resolve
    # through them, so checking the definitions covers both.
    targets += [t for _, t in _REF_DEF.findall(text)]

    anchor_cache: dict[Path, set[str]] = {}

    for raw in targets:
        if _is_external(raw) or raw.startswith("#"):
            continue
        target = urllib.parse.unquote(raw)
        path_part, _, anchor = target.partition("#")
        if not path_part:
            continue  # pure anchor already skipped above; defensive
        resolved = (md_path.parent / path_part).resolve()
        if not resolved.exists():
            failures.append(f"{md_path.relative_to(root)}: missing target '{raw}'")
            continue
        if anchor and resolved.suffix.lower() == ".md":
            if resolved not in anchor_cache:
                anchor_cache[resolved] = _headings(resolved.read_text(encoding="utf-8"))
            if anchor not in anchor_cache[resolved]:
                failures.append(
                    f"{md_path.relative_to(root)}: anchor '#{anchor}' not found in {raw}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=_find_project_root(),
        help="Repository root (default: auto-detected from this script's location)",
    )
    args = parser.parse_args()
    root: Path = args.root

    files: list[Path] = []
    for pattern in _SCAN_GLOBS:
        files.extend(sorted(root.glob(pattern)))

    all_failures: list[str] = []
    for md_path in files:
        all_failures.extend(_check_file(md_path, root))

    if all_failures:
        print(f"Broken links: {len(all_failures)}")
        for line in all_failures:
            print(f"  {line}")
        return 1
    print(f"Markdown link check passed ({len(files)} files scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
