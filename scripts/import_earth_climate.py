"""Thin CLI wrapper for the real-Earth climate importer.

The implementation lives in ``dreamulator.import_earth_climate``.  Usage::

    uv run python scripts/import_earth_climate.py \
        --output-dir private/worlds/earth/maps/planet_earth
"""

from dreamulator.import_earth_climate import main

if __name__ == "__main__":
    main()
