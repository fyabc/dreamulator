"""Region pack API — serves terrain video-chain packs for the /packs QA page.

A region pack (``dreamulator export region``) is a directory under the packs
root holding ``input/`` (2048² engine channels + meta.json), ``refined-out/``
(4096² refined terrain + hydrology products), and optional render legs
(``color/``, ``carto/``, ``renders/``).  The /packs frontend page displays the
full-bleed channel PNGs and probes cell values for the worldbuilding QA loop
(screenshot → coordinates → attribution).

Window geometry is the exact inverse of
:func:`dreamulator.map.region_export.region_window`: ``deg_per_km =
180/(π·radius_km)`` with the planet radius from ``meta.json``, and the
east–west span divided by ``cos(center_lat)``.  The export grid is cropped to
whole source pixels (``pixel_box``), so the grid is treated as centred on
``(center_lat, center_lon)``; the sub-pixel offset this ignores is < 0.3 km —
irrelevant at QA zoom levels.

API-mode only by design: packs are gitignored multi-hundred-MB local
artifacts, never shipped to the static export (precedent: the narrate SSE
endpoints).  Raster reads are memoised with mmaps/PIL handles; on Windows
those handles lock the files, so regenerate a pack and restart ``serve`` to
pick up new outputs.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .maps import _file_response

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

router = APIRouter(prefix="/api/packs", tags=["packs"])

#: Top-level pack subdirectories the image endpoint may serve.  ``carto/`` is
#: excluded on purpose: those sheets carry figure furniture (margins, legends,
#: graticule labels), so their pixels are not map-registered.
_IMAGE_TOP_DIRS = frozenset({"input", "refined-out", "color", "prog-out", "gaea-out", "renders"})

_PACK_NAME_RE = re.compile(r"[^/\\]+")

_CACHE_CAP = 8
_NPY_CACHE: OrderedDict[str, np.ndarray] = OrderedDict()
_MASK_CACHE: OrderedDict[str, np.ndarray] = OrderedDict()

#: Rendered topo composites: build-dir → (png bytes, sources ETag).
_TOPO_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_TOPO_CACHE_CAP = 4

#: Maximum distance from the probed point to a river-segment endpoint for the
#: segment's flow/regime to be reported (refined cells are ~136 m across; 2 km
#: keeps the readout honest without snapping to distant channels).
_RIVER_SNAP_KM = 2.0


def _pack_roots() -> list[Path]:
    """Directories holding region packs.

    ``DREAMULATOR_PACKS_DIR`` overrides with a single flat root (tests,
    custom setups); the default scans every world's ``packs/`` directory —
    the ``export region`` default output, kept next to the world's other
    bulk build outputs (maps/, layers/*/derived/).
    """
    env_dir = os.environ.get("DREAMULATOR_PACKS_DIR")
    if env_dir:
        root = Path(env_dir).resolve()
        return [root] if root.is_dir() else []
    from dreamulator.world_manager import _data_dir

    data = _data_dir()
    if not data.is_dir():
        return []
    return sorted(p for p in (w / "packs" for w in data.iterdir() if w.is_dir()) if p.is_dir())


def _pack_dir(pack: str) -> Path:
    """Resolve a pack name to its directory, 404-ing anything malformed."""
    if not _PACK_NAME_RE.fullmatch(pack) or pack in {".", ".."}:
        raise HTTPException(status_code=404, detail=f"Unknown pack '{pack}'")
    for root in _pack_roots():
        candidate = (root / pack).resolve()
        if not candidate.is_relative_to(root.resolve()):
            continue
        if (candidate / "input" / "meta.json").is_file():
            return candidate
    raise HTTPException(status_code=404, detail=f"Unknown pack '{pack}'")


def _input_meta(pack_dir: Path) -> dict[str, Any]:
    """The pack's input/meta.json (small — re-read per request, never stale)."""
    meta: dict[str, Any] = json.loads(
        (pack_dir / "input" / "meta.json").read_text(encoding="utf-8")
    )
    return meta


# ---------------------------------------------------------------------------
# Window geometry (pure functions — exact inverse of region_export)
# ---------------------------------------------------------------------------


def _window(meta: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    """(center_lat, center_lon, deg_per_km, cos_lat, extent_km_x, extent_km_y)."""
    c_lat = float(meta["center_lat"])
    c_lon = float(meta["center_lon"])
    radius_km = float(meta.get("radius_km", 6371.0))
    ext_x = float(meta["extent_km"]["x"])
    ext_y = float(meta["extent_km"]["y"])
    deg_per_km = 180.0 / (math.pi * radius_km)
    return (c_lat, c_lon, deg_per_km, math.cos(math.radians(c_lat)), ext_x, ext_y)


def _ll_to_frac(
    win: tuple[float, float, float, float, float, float], lat: float, lon: float
) -> tuple[float, float]:
    """(u, v) window fractions: u east 0..1, v from north 0..1."""
    c_lat, c_lon, deg_per_km, cos_lat, ext_x, ext_y = win
    lon_u = (lon - c_lon + 180.0) % 360.0 - 180.0 + c_lon  # wrap ±180°
    u = 0.5 + (lon_u - c_lon) * cos_lat / deg_per_km / ext_x
    v = 0.5 - (lat - c_lat) / deg_per_km / ext_y
    return (u, v)


def _frac_to_ll(
    win: tuple[float, float, float, float, float, float], u: float, v: float
) -> tuple[float, float]:
    """Exact inverse of :func:`_ll_to_frac` (frontend graticule cross-check)."""
    c_lat, c_lon, deg_per_km, cos_lat, ext_x, ext_y = win
    lon = c_lon + (u - 0.5) * ext_x * deg_per_km / cos_lat
    lat = c_lat + (0.5 - v) * ext_y * deg_per_km
    return (lat, lon)


def _cell(u: float, v: float, shape: tuple[int, ...]) -> tuple[int, int]:
    """(row, col) clamped into a (h, w) raster; row 0 = north."""
    h, w = int(shape[0]), int(shape[1])
    row = min(h - 1, max(0, int(v * h)))
    col = min(w - 1, max(0, int(u * w)))
    return (row, col)


# ---------------------------------------------------------------------------
# Raster access (mmap / PIL memoisation, absolute-path keyed)
# ---------------------------------------------------------------------------


def _cached(
    cache: OrderedDict[str, np.ndarray], path: Path, load: Callable[[Path], np.ndarray]
) -> np.ndarray | None:
    if not path.is_file():
        return None
    key = str(path)
    hit = cache.get(key)
    if hit is not None:
        cache.move_to_end(key)
        return hit
    value = load(path)
    cache[key] = value
    while len(cache) > _CACHE_CAP:
        cache.popitem(last=False)
    return value


def _npy(pack_dir: Path, rel: str) -> np.ndarray | None:
    """Memory-mapped .npy read (random access is cheap; handle stays open)."""
    import numpy as np

    return _cached(_NPY_CACHE, pack_dir / rel, lambda p: np.load(p, mmap_mode="r"))


def _mask(pack_dir: Path, rel: str) -> np.ndarray | None:
    """An 8-bit mask PNG as a (h, w) uint8 array; ``.load()`` releases the file."""
    import numpy as np
    from PIL import Image

    def load(p: Path) -> np.ndarray:
        with Image.open(p) as img:
            return np.asarray(img.convert("L"))

    return _cached(_MASK_CACHE, pack_dir / rel, load)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_packs() -> dict[str, Any]:
    """Packs present under the root, newest first."""
    packs: list[dict[str, Any]] = []
    for root in _pack_roots():
        for entry in sorted(p for p in root.iterdir() if p.is_dir()):
            meta_file = entry / "input" / "meta.json"
            if not meta_file.is_file():
                continue
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            source = meta.get("source", {})
            packs.append(
                {
                    "name": entry.name,
                    "world": source.get("world"),
                    "planet": source.get("planet"),
                    "branch": source.get("branch"),
                    "center_lat": meta.get("center_lat"),
                    "center_lon": meta.get("center_lon"),
                    "span_km": meta.get("span_km"),
                    "mtime": datetime.fromtimestamp(meta_file.stat().st_mtime, tz=UTC).isoformat(
                        timespec="seconds"
                    ),
                    "legs": {
                        "color": (entry / "color").is_dir(),
                        "refined": (entry / "refined-out" / "meta.json").is_file(),
                        "carto": (entry / "carto").is_dir(),
                        "renders": (entry / "renders").is_dir(),
                        "prog": (entry / "prog-out").is_dir(),
                        "gaea": (entry / "gaea-out").is_dir(),
                    },
                }
            )
    packs.sort(key=lambda p: (p["mtime"], p["name"]), reverse=True)
    return {"ok": True, "data": packs}


@router.get("/{pack}/meta")
def pack_meta(pack: str) -> dict[str, Any]:
    """Both meta.json documents: input (window + legends), refined (hydrology)."""
    pack_dir = _pack_dir(pack)
    refined_file = pack_dir / "refined-out" / "meta.json"
    refined = (
        json.loads(refined_file.read_text(encoding="utf-8")) if refined_file.is_file() else None
    )
    return {"ok": True, "data": {"input": _input_meta(pack_dir), "refined": refined}}


@router.get("/{pack}/image/{path:path}")
def pack_image(pack: str, path: str, request: Request) -> Response:
    """Serve a whitelisted PNG from a pack with ETag revalidation."""
    pack_dir = _pack_dir(pack)
    parts = path.replace("\\", "/").split("/")
    if (
        not parts
        or parts[0] not in _IMAGE_TOP_DIRS
        or any(part in {"", ".", ".."} for part in parts)
        or not path.lower().endswith(".png")
    ):
        raise HTTPException(status_code=404, detail=f"Image not found: {path}")
    resolved = (pack_dir / Path(*parts)).resolve()
    if not resolved.is_relative_to(pack_dir) or not resolved.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {path}")
    return _file_response(request, resolved, "image/png")


@router.get("/{pack}/probe")
def probe(pack: str, lat: float, lon: float) -> dict[str, Any]:
    """Cell values at a lon/lat: height, biome/koppen codes, water masks, river.

    Row/col land on the refined grid when ``refined-out/height.meters.npy``
    exists (4096²), else the input grid; categorical codes are looked up at
    their own resolution (each raster's shape drives its own inverse — no
    factor arithmetic).  Coordinates outside the window are a 422: silent
    clamping would poison the QA loop this endpoint serves.
    """
    pack_dir = _pack_dir(pack)
    meta = _input_meta(pack_dir)
    win = _window(meta)
    u, v = _ll_to_frac(win, lat, lon)

    height = _npy(pack_dir, "refined-out/height.meters.npy")
    height_source: str | None
    if height is not None:
        height_source = "refined"
    else:
        height = _npy(pack_dir, "input/height.meters.npy")
        height_source = "input" if height is not None else None
    shape = height.shape if height is not None else (meta["grid"]["h"], meta["grid"]["w"])
    h, w = int(shape[0]), int(shape[1])
    if u < -0.5 / w or u > 1.0 + 0.5 / w or v < -0.5 / h or v > 1.0 + 0.5 / h:
        raise HTTPException(status_code=422, detail="coordinates outside pack window")

    row, col = _cell(u, v, shape)
    result: dict[str, Any] = {
        "row": row,
        "col": col,
        "res": {"w": w, "h": h},
        "height_source": height_source,
        "height_m": float(height[row, col]) if height is not None else None,
        "offset_km": {
            "x": round((u - 0.5) * win[4], 3),
            "y": round((0.5 - v) * win[5], 3),
        },
    }

    for key, rel in (
        ("biome_code", "input/biome.codes.npy"),
        ("koppen_code", "input/koppen.codes.npy"),
    ):
        codes = _npy(pack_dir, rel)
        if codes is not None:
            r, c = _cell(u, v, codes.shape)
            result[key] = int(codes[r, c])
        else:
            result[key] = None

    for key, rel in (
        ("river", "refined-out/rivers.png"),
        ("lake", "refined-out/lake.png"),
        ("sea_water", "refined-out/sea-water.png"),
    ):
        mask = _mask(pack_dir, rel)
        if mask is not None:
            r, c = _cell(u, v, mask.shape)
            result[key] = bool(mask[r, c] > 127)
        else:
            result[key] = None

    result["river_flow_accum"], result["river_regime"] = _river_lookup(pack_dir, u, v, win)
    return {"ok": True, "data": result}


def _river_lookup(
    pack_dir: Path, u: float, v: float, win: tuple[float, float, float, float, float, float]
) -> tuple[float | None, int | None]:
    """Nearest river-segment flow/regime.

    ``rivers.line.npy`` holds (M, 2, 2) km polylines in the SW-origin frame of
    ``prog_erosion.cell_xyz_km`` (x east, y north from the south-west corner);
    the window fractions are converted into that frame before the search.
    """
    lines = _npy(pack_dir, "refined-out/rivers.line.npy")
    if lines is None or len(lines) == 0:
        return (None, None)
    _, _, _, _, ext_x, ext_y = win
    x_q, y_q = u * ext_x, (1.0 - v) * ext_y
    d2 = (lines[..., 0] - x_q) ** 2 + (lines[..., 1] - y_q) ** 2
    idx = int(d2.argmin())
    if math.sqrt(float(d2.flat[idx])) > _RIVER_SNAP_KM:
        return (None, None)
    seg = idx // d2.shape[1]
    flows = _npy(pack_dir, "refined-out/rivers.flow.npy")
    regimes = _npy(pack_dir, "refined-out/rivers.regime.npy")
    return (
        float(flows[seg]) if flows is not None else None,
        int(regimes[seg]) if regimes is not None else None,
    )


# ---------------------------------------------------------------------------
# Display composites — the topo body (terrain + water) and the vector rivers
# ---------------------------------------------------------------------------


def _best_gaea_dir(pack_dir: Path) -> Path | None:
    """The best build available for display (refined → prog → gaea → input)."""
    for rel in ("refined-out", "prog-out", "gaea-out", "input"):
        d = pack_dir / rel
        if (d / "height.meters.npy").is_file() or (d / "rivers-h.exr").is_file():
            return d
    return None


def _palette_range_m(meta: dict[str, Any]) -> tuple[float, float]:
    """The shared-palette elevation range — same rule as ``carto_region``."""
    if "elevation_m_global" in meta:
        g = meta["elevation_m_global"]
        return (float(g[0]), float(g[1]))
    lo, hi = (float(v) for v in meta["height_png_range_m"])
    if lo > float(meta["sea_level_m"]):
        lo = float(meta["sea_level_m"]) - 1000.0
    return (lo, hi)


def _sources_etag(paths: list[Path]) -> str:
    """Weak Etag over (size, mtime) of every existing source file."""
    parts = []
    for p in paths:
        if p.is_file():
            st = p.stat()
            parts.append(f"{p.name}:{st.st_size:x}-{st.st_mtime_ns:x}")
    return 'W/"' + ",".join(parts) + '"'


@router.get("/{pack}/topo.png")
def pack_topo(pack: str, request: Request) -> Response:
    """Full-resolution topo body (terrain LUT + hillshade + lake/sea fills).

    The same :func:`carto_render.compose_rgb` raster that underlies the
    printed sheet, minus all figure furniture — full-bleed and exactly
    map-registered, so the /packs page shows the hi-res refined terrain the
    sheet was drawn from.  Rendered once and cached in memory; the ETag
    covers every source file, so a regenerated pack revalidates and
    re-renders.
    """
    pack_dir = _pack_dir(pack)
    gaea = _best_gaea_dir(pack_dir)
    if gaea is None:
        raise HTTPException(status_code=404, detail=f"No heightfield in pack '{pack}'")
    source_files = [
        pack_dir / "input" / "meta.json",
        gaea / "height.meters.npy",
        gaea / "sea-water.png",
        gaea / "sea-depth.png",
        gaea / "lake.png",
        pack_dir / "input" / "biome.codes.npy",
    ]
    etag = _sources_etag(source_files)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    cached = _TOPO_CACHE.get(str(gaea))
    if cached is not None and cached[1] == etag:
        _TOPO_CACHE.move_to_end(str(gaea))
        return Response(content=cached[0], media_type="image/png", headers=headers)

    import io

    import numpy as np
    from PIL import Image

    from dreamulator.media.carto_render import compose_rgb
    from dreamulator.media.satellite_color import load_inputs

    inputs = load_inputs(pack_dir / "input", gaea)
    rgb = compose_rgb(inputs, _palette_range_m(_input_meta(pack_dir)), res=inputs.height_m.shape[0])
    buf = io.BytesIO()
    Image.fromarray((np.clip(rgb, 0.0, 1.0) * 255.0).round().astype(np.uint8)).save(buf, "PNG")
    content = buf.getvalue()
    _TOPO_CACHE[str(gaea)] = (content, etag)
    while len(_TOPO_CACHE) > _TOPO_CACHE_CAP:
        _TOPO_CACHE.popitem(last=False)
    return Response(content=content, media_type="image/png", headers=headers)


@router.get("/{pack}/rivers.json")
def pack_rivers(pack: str) -> dict[str, Any]:
    """Vector river segments for display, in Leaflet-ready centre-origin km.

    Each segment is ``[[y, x], [y, x]]`` (y north, x east, kilometres from
    the window centre — the CRS.Simple frame the /packs map uses), converted
    from the SW-origin frame of ``rivers.line.npy``.  ``flows`` are relative
    upstream accumulation (the √-law width driver), ``regimes`` 0 perennial /
    1 non-perennial; empty lists when the pack has no vector channel.
    """
    pack_dir = _pack_dir(pack)
    gaea = _best_gaea_dir(pack_dir)
    empty: dict[str, Any] = {"segs": [], "flows": [], "regimes": [], "flow_max": 0.0}
    if gaea is None:
        return {"ok": True, "data": empty}
    rel = gaea.relative_to(pack_dir).as_posix()
    lines = _npy(pack_dir, rel + "/rivers.line.npy")
    if lines is None or len(lines) == 0:
        return {"ok": True, "data": empty}

    meta = _input_meta(pack_dir)
    ext_x, ext_y = float(meta["extent_km"]["x"]), float(meta["extent_km"]["y"])
    import numpy as np

    # (M, 2, 2) x-east/y-north km, SW origin → [y, x] centre origin, rounded
    # to metres to keep the JSON small.
    pts = np.stack([lines[..., 1] - ext_y / 2.0, lines[..., 0] - ext_x / 2.0], axis=-1)
    segs: list[Any] = np.round(pts.astype(np.float64), 3).tolist()
    flows_arr = _npy(pack_dir, rel + "/rivers.flow.npy")
    regimes_arr = _npy(pack_dir, rel + "/rivers.regime.npy")
    flows: list[Any] = (
        np.round(np.asarray(flows_arr, dtype=np.float64), 1).tolist()
        if flows_arr is not None
        else []
    )
    regimes: list[Any] = (
        np.asarray(regimes_arr).astype(int).tolist() if regimes_arr is not None else []
    )
    flow_max = max(flows) if flows else 0.0
    return {
        "ok": True,
        "data": {"segs": segs, "flows": flows, "regimes": regimes, "flow_max": flow_max},
    }
