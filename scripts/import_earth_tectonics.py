"""Thin CLI wrapper for the PB2002 Earth tectonic-plate importer.

The implementation lives in ``dreamulator.import_earth_tectonics`` (mirroring
the ETOPO1 elevation importer).  Usage::

    uv run python scripts/import_earth_tectonics.py \
        --output-dir private/worlds/earth/maps/planet_earth
"""

from dreamulator.import_earth_tectonics import main

if __name__ == "__main__":
    main()
