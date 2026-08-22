"""Unit tests for the headless colour layer renderers (map/export.py)."""

import numpy as np
from PIL import Image

from dreamulator.map.export import (
    export_cell_index_grid,
    render_categorical_layer,
    render_continuous_layer,
    render_terrain_layer,
    save_rgba_png,
)
from dreamulator.map.models import CVTMesh, VoronoiCell
from dreamulator.map.palettes import (
    build_adaptive_terrain_lut,
    continuous_scale,
    koppen_colors,
    whittaker_colors,
)


def _mesh() -> CVTMesh:
    """Four cells: even = land (elev 9000), odd = ocean (elev −11000)."""
    cells = []
    for i in range(4):
        lon = -135.0 + i * 90.0
        rad = float(np.radians(lon))
        is_land = i % 2 == 0
        cells.append(
            VoronoiCell(
                id=i,
                lon=lon,
                lat=0.0,
                x=float(np.cos(rad)),
                y=0.0,
                z=float(np.sin(rad)),
                elevation=9000.0 if is_land else -11000.0,
                koppen_class="Af" if is_land else None,
                biome="tropical_rainforest" if is_land else "ocean",
                agriculture_score=50.0 if is_land else None,
                habitability_score=50.0,
            )
        )
    return CVTMesh(seed=42, num_cells=len(cells), cells=cells)


# A synthetic pixel→cell index map so colour mapping is tested deterministically
# without depending on KD-tree geometry: pixel (r, c) → cell (r * 2 + c).
_INDICES = np.array([[0, 1], [2, 3]])


def test_render_categorical_koppen():
    mesh = _mesh()
    rgba = render_categorical_layer(
        mesh, _INDICES, "koppen_class", koppen_colors(), ocean_fallback="Ocean"
    )
    # Land cell 0 (Af) → blue; ocean cell 1 (None) → ocean fallback.
    assert tuple(int(v) for v in rgba[0, 0]) == (0, 0, 255, 255)
    assert tuple(int(v) for v in rgba[0, 1]) == (26, 82, 118, 255)


def test_render_categorical_biome():
    mesh = _mesh()
    rgba = render_categorical_layer(mesh, _INDICES, "biome", whittaker_colors())
    # Land rainforest → (27,94,32); ocean → (21,101,192).
    assert tuple(int(v) for v in rgba[0, 0]) == (27, 94, 32, 255)
    assert tuple(int(v) for v in rgba[0, 1]) == (21, 101, 192, 255)


def test_render_continuous_agriculture_land_only():
    mesh = _mesh()
    rgba = render_continuous_layer(
        mesh,
        _INDICES,
        "agriculture_score",
        continuous_scale("agriculture"),
        normalize=lambda s: s / 100.0,
        land_only=True,
        sea_level=0.0,
    )
    # Land score 50 → yellow; ocean score None → transparent.
    assert tuple(int(v) for v in rgba[0, 0]) == (238, 210, 90, 255)
    assert tuple(int(v) for v in rgba[0, 1]) == (0, 0, 0, 0)


def test_render_continuous_habitability_ocean_masked():
    mesh = _mesh()
    rgba = render_continuous_layer(
        mesh,
        _INDICES,
        "habitability_score",
        continuous_scale("habitability"),
        normalize=lambda s: s / 100.0,
        land_only=True,
        sea_level=0.0,
    )
    # Land score 50 → amber; ocean cell has score 50 but is masked → transparent.
    assert tuple(int(v) for v in rgba[0, 0]) == (220, 180, 80, 255)
    assert tuple(int(v) for v in rgba[0, 1]) == (0, 0, 0, 0)


def test_render_terrain_layer():
    mesh = _mesh()
    lut = build_adaptive_terrain_lut(-11000.0, 9000.0, 0.0)
    rgba = render_terrain_layer(mesh, _INDICES, lut, -11000.0, 9000.0, 0.0)
    assert rgba.shape == (2, 2, 4)
    # Land at max elevation → peak white, fully opaque.
    assert tuple(int(v) for v in rgba[0, 0]) == (255, 255, 255, 255)
    # Ocean cell is darkened (r channel below the raw LUT ocean value).
    assert rgba[0, 1, 3] == 255
    assert int(rgba[0, 1, 0]) < int(lut[0, 0])


def test_export_cell_index_grid_shape():
    mesh = _mesh()
    indices = export_cell_index_grid(mesh, width=8, height=4)
    assert indices.shape == (4, 8)
    assert np.issubdtype(indices.dtype, np.integer)
    assert int(indices.min()) >= 0 and int(indices.max()) < mesh.num_cells


def test_save_rgba_png(tmp_path):
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[0, 0] = [255, 0, 0, 255]
    path = tmp_path / "layer.png"
    save_rgba_png(rgba, path)

    img = Image.open(path)
    assert img.mode == "RGBA"
    assert img.size == (2, 2)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)
