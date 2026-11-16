"""Two-ring transport across chunk edges, independently of direction selection."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dreamulator.map.river_routing import accumulate
from dreamulator.media import canvas_flow_tiled as flow
from dreamulator.media.canvas_pipeline import CanvasStore


def store_at(root: Path, tile: int, keys: list[tuple[int, int]]) -> CanvasStore:
    return SimpleNamespace(root=root, work=root / "work", tile=tile, chunks=keys, increments=None)


def put(store: CanvasStore, kind: str, grid: np.ndarray) -> None:
    t = store.tile
    for r, c in store.chunks:
        flow.save_chunk(store, kind, (r, c), grid[r * t : (r + 1) * t, c * t : (c + 1) * t])


def get(store: CanvasStore, kind: str) -> np.ndarray:
    layout = flow.ChunkLayout.of(store)
    out = np.zeros(layout.shape, dtype=flow.load_chunk(store, kind, store.chunks[0]).dtype)
    t = store.tile
    for r, c in store.chunks:
        out[r * t : (r + 1) * t, c * t : (c + 1) * t] = flow.load_chunk(store, kind, (r, c))
    return out


@pytest.mark.parametrize("radius", [1, 2])
@pytest.mark.parametrize("legacy", [False, True])
def test_halo_reads_layers_and_corners_with_old_or_new_saved_rings(
    tmp_path: Path, radius: int, legacy: bool
) -> None:
    t, n = 4, 12
    keys = [(r, c) for r in range(3) for c in range(3) if (r, c) != (0, 1)]
    store = store_at(tmp_path, t, keys)
    grid = np.arange(n * n).reshape(n, n)
    grid[:t, t : 2 * t] = -99
    put(store, "field", grid)
    if legacy:
        for key in keys:
            a = flow.load_chunk(store, "field", key)
            np.save(
                flow.flow_path(store, "field", key, "ring.npy"),
                np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]),
            )
    expected = np.pad(grid, radius, constant_values=-99)
    for r, c in keys:
        actual = flow.halo(
            store,
            flow.ChunkLayout.of(store),
            "field",
            (r, c),
            -99,
            dtype=np.int64,
            radius=radius,
        )
        np.testing.assert_array_equal(
            actual, expected[r * t : (r + 1) * t + 2 * radius, c * t : (c + 1) * t + 2 * radius]
        )


def uniform_graph(store: CanvasStore, direction: int) -> tuple[np.ndarray, np.ndarray]:
    layout = flow.ChunkLayout.of(store)
    rows, columns = layout.shape
    r, c = np.indices(layout.shape)
    dy, dx = flow.FLOW_OFFSETS[direction]
    target_r, target_c = r + dy, c + dx
    inside = (target_r >= 0) & (target_r < rows) & (target_c >= 0) & (target_c < columns)
    code = np.where(inside, direction, 255).astype(np.uint8)
    receiver = np.where(inside, target_r * columns + target_c, -1).ravel()
    put(store, "graded", (-dy * r - dx * c).astype(np.float32))
    put(store, "dir", code)
    put(store, "dir_route", code)
    return code, receiver


@pytest.mark.parametrize("direction", range(8, 16))
@pytest.mark.parametrize("workers", [1, 2])
@pytest.mark.parametrize("missing", [False, True])
def test_all_extended_directions_accumulate_across_second_layer_targets(
    tmp_path: Path, direction: int, workers: int, missing: bool
) -> None:
    keys = [(r, c) for r in range(3) for c in range(3) if not missing or (r, c) != (1, 1)]
    store = store_at(tmp_path, 8, keys)
    _, receiver = uniform_graph(store, direction)
    weight = np.arange(receiver.size).reshape(24, 24) / 1024
    if missing:
        absent = np.zeros(weight.shape, bool)
        absent[8:16, 8:16] = True
        weight[absent] = 0
        receiver[absent.ravel() | absent.ravel()[np.maximum(receiver, 0)]] = -1
    put(store, "source", weight)
    flow.tiled_accumulation(store, "source", float64=True, workers=workers)
    expected = accumulate(receiver, weight)
    actual = get(store, "acc_source")
    np.testing.assert_array_equal(actual, expected)
    assert actual.ravel()[receiver < 0].sum() == weight.sum()


def test_invalid_direction_is_rejected_before_indexing_offsets() -> None:
    with pytest.raises(ValueError, match="direction"):
        flow._local_receivers(np.full((4, 4), 16, np.uint8))


def test_monthly_counts_and_raw_channel_graph_match_whole_grid_consumption(tmp_path: Path) -> None:
    from dreamulator.map.prog_erosion import river_segments, river_segments_from_graph
    from dreamulator.media.canvas_lakes_tiled import Components
    from dreamulator.media.canvas_month_tiled import tiled_month_active
    from dreamulator.media.canvas_rivers_tiled import tiled_channel_graph
    from dreamulator.media.canvas_terminal_tiled import TerminalResult

    store = store_at(tmp_path, 8, [(r, c) for r in range(3) for c in range(3)])
    _, receiver = uniform_graph(store, 15)
    z = np.zeros(1, np.int64)
    comps = Components(0, z.copy(), z.copy(), z.copy(), z.copy(), z.copy())
    term = TerminalResult(
        n=0,
        external=z.copy(),
        total=z.copy(),
        demand=z.copy(),
        downstream_of=z.copy(),
        topo=[],
        is_term=np.zeros(1, bool),
        n_exits=z.copy(),
        kept_counts=z.copy(),
        stats={},
    )
    monthly = np.full((24, 24, 12), 300, np.float32)
    monthly[:, 12:, 6:] = 0
    count = np.zeros((24, 24), np.uint8)
    for m in range(12):
        count += (accumulate(receiver, monthly[..., m] / 300) >= 2).astype(np.uint8)
    put(store, "lbl_lakes0", np.zeros((24, 24), np.int32))
    put(store, "land2", np.ones((24, 24), np.uint8))
    tiled_month_active(
        store,
        comps,
        term,
        runoff_monthly_pack=monthly,
        evaporation_monthly_mm=None,
        precip_monthly_mm=None,
        active_cells=2,
        factor=1,
        workers=1,
    )
    np.testing.assert_array_equal(get(store, "month_active"), count)
    assert set(np.unique(count)) >= {6, 12}
    annual = accumulate(receiver, monthly.sum(axis=-1) / 300)
    put(store, "acc_w_depleted", annual)
    graph = tiled_channel_graph(
        store,
        comps,
        threshold_cells=2,
        mmu_cells=1,
        km_per_px=1,
        pixel_rows=24,
        has_descent=False,
        workers=1,
    )
    actual = river_segments_from_graph(graph, smooth=False)
    expected = river_segments(annual > 2, receiver, annual, 1, month_active=count, smooth=False)
    for a, b in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(a, b)


def test_lake_graph_resolves_an_exit_landing_in_the_second_border_layer(tmp_path: Path) -> None:
    from dreamulator.media import canvas_terminal_tiled as terminal

    store = store_at(tmp_path, 8, [(r, c) for r in range(3) for c in range(3)])
    shape = flow.ChunkLayout.of(store).shape
    code = np.full(shape, 255, np.uint8)
    path = [(5 + 2 * i, 1 + i) for i in range(7)]
    k = int(np.flatnonzero((flow.FLOW_OFFSETS == (2, 1)).all(axis=1))[0])
    rec = np.full(code.size, -1, np.int64)
    for a, b in zip(path[:-1], path[1:], strict=True):
        code[a] = k
        rec[a[0] * shape[1] + a[1]] = b[0] * shape[1] + b[1]
    labels = np.zeros(shape, np.int32)
    labels[path[1]], labels[path[5]] = 1, 2
    source = np.zeros(shape)
    source[path[0]] = 100
    cut = rec.copy()
    cut[labels.ravel() > 0] = -1
    r, c = np.indices(shape)
    dem = (100 - 2 * r - c).astype(np.float32)
    for kind, grid in (
        ("dir", code),
        ("graded", dem),
        ("dem", dem),
        ("lbl_lakes0", labels),
        ("acc_cut", accumulate(cut, source)),
    ):
        put(store, kind, grid)
    ctx = flow._ctx_of(store)
    ctx.extra = {
        "climate": terminal._Climate(
            precip=np.zeros(shape),
            temp=np.zeros(shape),
            open_water=np.full(shape, 5.0),
            block=1,
            width=shape[1],
            rbar=300,
        ),
        "key_index": {key: i for i, key in enumerate(ctx.keys)},
    }
    flow._init(ctx)
    info = [terminal._lake_info(key) for key in ctx.keys]
    external, evap, precip, exits = terminal._resolve_exits(info, len(ctx.keys), store.tile, 2)
    np.testing.assert_array_equal(external, [0, 100, 0])
    np.testing.assert_array_equal(evap, [0, 5, 5])
    np.testing.assert_array_equal(precip, [0, 0, 0])
    np.testing.assert_array_equal(exits["lab"], [1, 2])
    np.testing.assert_array_equal(exits["reach"], [2, 0])
    np.testing.assert_array_equal(
        exits["tg"], [path[2][0] * shape[1] + path[2][1], path[6][0] * shape[1] + path[6][1]]
    )
    # Monthly overflow must enter that same second-layer receiver and pass
    # through both lakes with the shared storage and evaporation budget.
    from dreamulator.map.prog_erosion import PassThroughLakes, month_active_counts
    from dreamulator.media.canvas_lakes_tiled import Components
    from dreamulator.media.canvas_month_tiled import tiled_month_active

    monthly = np.zeros((*shape, 12), np.float32)
    monthly[path[0]][:6] = 300
    ev = np.full((12, *shape), 60, np.float32)
    pr = np.zeros_like(ev)
    cells = exits["g"]
    pt = PassThroughLakes(
        labels=np.array([1, 2]),
        cells=cells,
        cell_lake=np.array([0, 1]),
        exits=cells,
        exit_lake=np.array([0, 1]),
        exit_target=exits["tg"],
        downstream=np.array([1, -1]),
        topo=np.array([0, 1]),
    )
    term = terminal.TerminalResult(
        n=2,
        external=np.array([0, 1800, 0]),
        total=np.array([0, 1800, 1080]),
        demand=np.array([0, 720, 720]),
        downstream_of=np.array([0, 2, 0]),
        topo=[1, 2],
        is_term=np.zeros(3, bool),
        n_exits=np.array([0, 1, 1]),
        kept_counts=np.array([0, 1, 1]),
        stats={},
        exit_cell=cells,
        exit_lake=exits["lab"],
        exit_target=exits["tg"],
        exit_reach=exits["reach"],
    )
    z = np.zeros(3, np.int64)
    comps = Components(2, np.array([0, 1, 1]), z.copy(), z.copy(), z.copy(), z.copy())
    put(store, "dir_route", code)
    tiled_month_active(
        store,
        comps,
        term,
        runoff_monthly_pack=monthly,
        evaporation_monthly_mm=ev,
        precip_monthly_mm=pr,
        active_cells=0.25,
        factor=1,
        workers=1,
    )
    expected = month_active_counts(
        np.argsort(dem.ravel(), kind="stable"),
        rec.copy(),
        monthly,
        np.ones(shape, bool),
        0.25,
        lakes=(pt, np.full((2, 12), 60 / 300)),
    )
    np.testing.assert_array_equal(get(store, "month_active"), expected)
