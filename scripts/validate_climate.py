"""Thin CLI wrapper for the climate validation tool.

The implementation lives in ``dreamulator.validate_climate`` (moved from
scripts/ on 2026-08 so the CLI (``dreamulator climate validate``) can reuse
it without sys.path hacks). Usage is unchanged:

    uv run python scripts/validate_climate.py earth --branch terrain-dev
"""

from dreamulator.validate_climate import main

if __name__ == "__main__":
    main()
