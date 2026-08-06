"""Thin CLI wrapper for the ETOPO1 Earth elevation importer.

The implementation lives in ``dreamulator.import_earth_elevation`` (moved
from scripts/ on 2026-08 so the CLI (``dreamulator climate import-elevation``)
can reuse it without sys.path hacks). Usage is unchanged:

    uv run python scripts/import_earth_elevation.py [--resolution 2048x1024]
"""

from dreamulator.import_earth_elevation import main

if __name__ == "__main__":
    main()
