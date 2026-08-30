"""CRUST1.0 crustal-type parsing — real continental/oceanic/transitional crust.

CRUST1.0 (Laske et al. 2013, doi:10.1002/2013GL058322) is a 1°×1° global crustal
model.  Its add-on package classifies each cell into one of 36 crustal types
(``CNtype1_key.txt``); this module maps those types onto the model's three-way
``crust_type`` and samples the 360×180 grid at cell centres.

Provenance: Laske, G., Masters, G., Ma, Z., & Pasyanos, M. (2013). "Update on
CRUST1.0 — A 1-degree Global Model of Earth's Crust."  Downloaded from
https://igppweb.ucsd.edu/~gabi/crust1.html (add-on ``crust1.0-addon.tar.gz``).
"""

from __future__ import annotations

import numpy as np

# CRUST1.0 crustal type code → model crust_type.  The 36 types group naturally:
# continental (platforms / cratons / orogens / extended crust / shelf),
# transitional (island arc / forearc / slope / rift / thinned & intermed. crust),
# oceanic (normal / young / melt-affected oceanic, oceanic plateaus).
_CRUST1_TYPE_TO_CLASS: dict[str, str] = {
    # Continental
    "D-": "continental",
    "E-": "continental",
    "F-": "continental",
    "G1": "continental",
    "G2": "continental",
    "H1": "continental",
    "H2": "continental",
    "I1": "continental",
    "I2": "continental",
    "L1": "continental",
    "L2": "continental",
    "M-": "continental",
    "N-": "continental",
    "O-": "continental",
    "P-": "continental",
    "Q-": "continental",
    "R1": "continental",
    "R2": "continental",
    "T-": "continental",
    "U-": "continental",
    "Z1": "continental",
    "Z2": "continental",
    "C-": "continental",
    # Transitional
    "J-": "transitional",
    "K-": "transitional",
    "S-": "transitional",
    "V1": "transitional",
    "V2": "transitional",
    "W-": "transitional",
    "X-": "transitional",
    "Y1": "transitional",
    "Y2": "transitional",
    # Oceanic
    "A1": "oceanic",
    "A0": "oceanic",
    "B-": "oceanic",
    "Y3": "oceanic",
}


def parse_crust1_type(text: str) -> np.ndarray:
    """Parse ``CNtype1-1.txt`` → a (180, 360) array of 2-char type codes.

    The file is 180 rows (lat 89.5°N → 89.5°S) × 360 cols (lon 179.5°W → 179.5°E),
    each cell a 2-character crustal-type code.
    """
    rows = [line.split() for line in text.splitlines() if line.strip()]
    grid = np.array(rows, dtype=object)  # (180, 360)
    assert grid.shape == (180, 360), f"unexpected grid shape {grid.shape}"
    return grid


def sample_crust1(grid: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Sample the CRUST1.0 type grid at cell centres → per-cell class strings.

    Nearest-neighbour on the 1° grid: row 0 = 89.5°N, col 0 = −179.5°.
    """
    h, w = grid.shape
    row = np.clip(np.round(89.5 - lats).astype(np.int64), 0, h - 1)
    col = np.clip(np.round(lons + 179.5).astype(np.int64), 0, w - 1)
    codes = grid[row, col]
    return np.array([_CRUST1_TYPE_TO_CLASS.get(str(c), "oceanic") for c in codes], dtype=object)
