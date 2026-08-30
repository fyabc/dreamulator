"""Thin CLI wrapper for the GSHHG Earth water-mask importer.

The implementation lives in ``dreamulator.import_earth_watermask``.  Usage::

    uv run python scripts/import_earth_watermask.py \
        --output-dir private/worlds/earth/maps/planet_earth
"""

from dreamulator.import_earth_watermask import main

if __name__ == "__main__":
    main()
