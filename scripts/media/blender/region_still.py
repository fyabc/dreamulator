"""region_still — build (and optionally render) a Blender scene from a region pack.

Script-rebuild workflow: the ``.blend`` is a disposable artifact, always
rebuildable from the data pack produced by ``dreamulator export region``
(see docs/design/proposals/blender-render-pipeline.md).  Scene units are
kilometres (1 unit = 1 km) with a physically correct vertical scale by
default (``--zscale`` exaggerates if a shot needs it).

Terrain defaults to the Gaea-eroded heightfield (``gaea-out/rivers-h.exr``,
falling back to ``erosion2-h.exr``; both are 8K builds storing the 0..1
normalised height — metres = value × (max − min) + min over the pack's
``height_gaea_png_range_m``).  ``--terrain input`` renders the raw engine
pack instead.  EXR row order was verified against the 16-bit PNG twin
(corr 0.997 same-order, 0.19 flipped).

Usage (Blender's bundled Python — args after ``--`` are ours):
    blender -b -P scripts/media/blender/region_still.py -- \
        --datadir private/video/nacrea-15_-100_2350km \
        [--render renders/still_001.png] [--res 1920x1080] \
        [--samples 256] [--zscale 1.0] [--mesh-res 2048] \
        [--terrain gaea|input] [--subsurf 0] [--blend out.blend]

Render: Cycles, device auto-fallback OptiX > CUDA > CPU, fixed seed 42,
OpenImageDenoise — deterministic given the same pack and flags.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np

#: Sun defaults — warm light (nacrea's red dwarf astra), 35° above horizon
#: from the south-east, ~0.5° angular diameter (astra is large in the sky).
SUN_COLOR = (1.0, 0.82, 0.62)
SUN_ANGLE_DEG = 0.53
SUN_AZIMUTH_DEG = 135.0
SUN_ALTITUDE_DEG = 35.0

#: Sky background — deep blue-grey, no texture (MVP).
SKY_COLOR = (0.028, 0.075, 0.118)
SKY_STRENGTH = 0.6

#: EXR build resolution → mesh vertex budget.  8K heights are box-averaged
#: down to ``--mesh-res`` (default 2048 = 4.2 M verts; subsurf would multiply
#: faces 16× per level, so it stays off by default on the 6 GB card).
GAEA_HEIGHT_EXRS = ("rivers-h.exr", "erosion2-h.exr")


def parse_args() -> argparse.Namespace:
    """Parse our flags from Blender's trailing ``--`` arguments."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datadir", required=True, type=Path, help="Region pack directory")
    p.add_argument(
        "--render",
        type=Path,
        default=None,
        help="Output PNG (skip = build only; bare name → <datadir>/renders/)",
    )
    p.add_argument("--res", default="1920x1080", help="Render resolution WxH")
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--zscale", type=float, default=1.0, help="Vertical exaggeration")
    p.add_argument("--mesh-res", type=int, default=2048, help="Terrain mesh resolution")
    p.add_argument(
        "--terrain", choices=("gaea", "input"), default="gaea", help="Height source"
    )
    p.add_argument(
        "--subsurf", type=int, default=0, help="Subsurf levels (0 = off; each level ×16 faces)"
    )
    p.add_argument("--blend", type=Path, default=None, help=".blend output path")
    p.add_argument("--sun-az", type=float, default=SUN_AZIMUTH_DEG)
    p.add_argument("--sun-alt", type=float, default=SUN_ALTITUDE_DEG)
    args = p.parse_args(argv)
    # Blender resolves relative paths against its own startup context, not the
    # shell's CWD — make every path absolute up front.  A relative --render
    # path always goes under <datadir>/renders/ (renders live with the pack).
    args.datadir = args.datadir.resolve()
    args.blend = (args.blend or args.datadir / "scene.blend").resolve()
    if args.render is not None:
        rp = args.render
        if not rp.is_absolute():
            rp = args.datadir / "renders" / rp
        args.render = rp.resolve()
    return args


def _box_downsample(a: np.ndarray, target: int) -> np.ndarray:
    """Box-average ``a`` down to ``target × target`` (integer factor only)."""
    h, w = a.shape
    if h <= target or w <= target:
        return a
    f = min(h // target, w // target)
    usable = target * f
    return a[:usable, :usable].reshape(target, f, target, f).mean(axis=(1, 3))


def load_height(args: argparse.Namespace, meta: dict) -> tuple[np.ndarray, str]:
    """Height in metres, row 0 = north, downsampled to ``--mesh-res``."""
    if args.terrain == "gaea":
        lo, hi = meta["height_gaea_png_range_m"]
        for name in GAEA_HEIGHT_EXRS:
            p = args.datadir / "gaea-out" / name
            if not p.exists():
                continue
            # Blender reads EXR natively (its bundled Python has no OpenEXR
            # module).  img.pixels is row-major bottom-up RGBA; flip to the
            # pack's row-0=north convention and take the R channel (Gaea's
            # single-channel Y export replicates into RGB).
            img = bpy.data.images.load(str(p))
            w, h = img.size
            px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
            bpy.data.images.remove(img)
            raw = px[::-1, :, 0].astype(np.float64)
            return _box_downsample(raw * (hi - lo) + lo, args.mesh_res), name
        print("[region_still] no Gaea EXR found — falling back to input heights")
    arr = np.load(args.datadir / "input" / "height.meters.npy").astype(np.float64)
    return _box_downsample(arr, args.mesh_res), "input/height.meters.npy"


def albedo_png(datadir: Path) -> Path:
    """Colour-authority albedo: colorize output first, engine tint fallback."""
    for p in (datadir / "color" / "albedo.png", datadir / "input" / "color.png"):
        if p.exists():
            return p
    raise FileNotFoundError(f"no albedo under {datadir}")


def build_terrain(
    height: np.ndarray, km_per_px: dict, zscale: float, subsurf: int = 0
) -> bpy.types.Object:
    """Grid mesh from the height field: row 0 = north (+Y), x/y in km, z km."""
    h, w = height.shape
    x_km = (np.arange(w) - (w - 1) / 2) * km_per_px["x"]
    y_km = ((h - 1) / 2 - np.arange(h)) * km_per_px["y"]
    z_km = height.astype(np.float64) * zscale / 1000.0

    verts, uvs = [], []
    for j in range(h):
        for i in range(w):
            verts.append((x_km[i], y_km[j], z_km[j, i]))
            uvs.append((i / (w - 1) if w > 1 else 0.0, 1.0 - (j / (h - 1) if h > 1 else 0.0)))
    faces = [
        (j * w + i, j * w + i + 1, (j + 1) * w + i + 1, (j + 1) * w + i)
        for j in range(h - 1)
        for i in range(w - 1)
    ]

    mesh = bpy.data.meshes.new("Terrain")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    uv = mesh.uv_layers.new(name="UVMap")
    if uv is not None:
        for loop, co in zip(uv.data, _loop_uvs(mesh, uvs), strict=False):
            loop.uv = co
    for poly in mesh.polygons:
        poly.use_smooth = True

    obj = bpy.data.objects.new("Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    if subsurf > 0:
        mod = obj.modifiers.new("Subsurf", "SUBSURF")
        mod.levels = subsurf
        mod.render_levels = subsurf
    return obj


def _loop_uvs(mesh: bpy.types.Mesh, vert_uvs: list) -> list:
    """Vertex-order UVs mapped to loop order (loops follow face vertex order)."""
    per_loop = []
    for poly in mesh.polygons:
        for vi in poly.vertices:
            per_loop.append(vert_uvs[vi])
    return per_loop


def terrain_material(color_png: Path) -> bpy.types.Material:
    mat = bpy.data.materials.new("Terrain")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.load(str(color_png))
    img.colorspace_settings.name = "sRGB"
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    mat.blend_method = "OPAQUE"
    return mat


def ocean_plane(extent_km: dict) -> bpy.types.Object:
    size = 4.0 * max(extent_km["x"], extent_km["y"])
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = "Ocean"
    mat = bpy.data.materials.new("Ocean")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    # Satellite-ocean blue (not photographic near-black): with only a sun and
    # a dim sky world, a physically dark water colour reads as void.
    bsdf.inputs["Base Color"].default_value = (0.09, 0.21, 0.33, 1.0)
    # Rougher than a mirror: kills the specular banding a flat plane shows at
    # glancing sun angles, and matches satellite-view water.
    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["IOR"].default_value = 1.33
    obj.data.materials.append(mat)
    return obj


def sun_light(az_deg: float, alt_deg: float) -> None:
    import math

    az, alt = math.radians(az_deg), math.radians(alt_deg)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    # LDR colour-authority pipeline: the albedo PNG is the reference look and
    # Standard view has no highlight rolloff, so the sun is calibrated (not
    # physical) — mid-tones land at L ≈ albedo·E·cosθ/π ≈ 0.5.  Blender's
    # default 1000 W/m² only works with an HDR view (AgX/Filmic), where this
    # scene renders near-white; verify changes with PIL statistics, not by
    # viewing the render (image viewers auto-tone-map).
    sun.data.energy = 6.0
    sun.data.color = SUN_COLOR
    sun.data.angle = math.radians(SUN_ANGLE_DEG)
    # Direction points from the sun toward the origin; place on the unit sphere.
    sun.location = (
        math.sin(az) * math.cos(alt),
        -math.cos(az) * math.cos(alt),
        math.sin(alt),
    )
    bpy.context.collection.objects.link(sun)


def camera(extent_km: dict) -> None:
    """High-oblique view: slant distance ~1.5× the region extent, 25° up."""
    import math

    e = max(extent_km["x"], extent_km["y"])
    slant = 1.5 * e
    alt = math.radians(25.0)
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 35.0
    cam_data.clip_end = 1.0e6  # km
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (0.0, -slant * math.cos(alt), slant * math.sin(alt))
    bpy.context.collection.objects.link(cam)

    target = bpy.data.objects.new("CamTarget", None)
    target.location = (0.0, 0.0, 0.0)
    bpy.context.collection.objects.link(target)
    con = cam.constraints.new("TRACK_TO")
    con.target = target

    bpy.context.scene.camera = cam


def world_sky() -> None:
    world = bpy.data.worlds.new("RegionSky")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (*SKY_COLOR, 1.0)
    bg.inputs["Strength"].default_value = SKY_STRENGTH
    bpy.context.scene.world = world
    # The albedo PNG is the colour authority (climate-coloured satellite look).
    # AgX — 5.x's default view transform — darkens midtones to protect HDR
    # highlights, which we don't have; Standard keeps the sRGB look faithful.
    bpy.context.scene.view_settings.view_transform = "Standard"


def pick_cycles_device() -> str:
    import contextlib

    prefs = bpy.context.preferences.addons["cycles"].preferences
    # Device enumeration varies across builds — failure just means the
    # already-registered device list is used as-is.
    with contextlib.suppress(Exception):
        prefs.get_devices()
    types = {d.type for d in prefs.devices}
    for t in ("OPTIX", "CUDA"):
        if t in types:
            prefs.compute_device_type = t
            bpy.context.scene.cycles.device = "GPU"
            return t
    bpy.context.scene.cycles.device = "CPU"
    return "CPU"


def main() -> int:
    args = parse_args()
    input_dir = args.datadir / "input"  # pack layout: input/ + gaea-out/ + color/
    meta = json.loads((input_dir / "meta.json").read_text(encoding="utf-8"))
    height, height_src = load_height(args, meta)

    t0 = time.perf_counter()
    kmpp = meta["km_per_px"]
    km_per_px = kmpp if isinstance(kmpp, dict) else {"x": float(kmpp), "y": float(kmpp)}
    terrain = build_terrain(height, km_per_px, args.zscale, args.subsurf)
    terrain.data.materials.append(terrain_material(albedo_png(args.datadir)))
    ocean_plane(meta["extent_km"])
    sun_light(args.sun_az, args.sun_alt)
    camera(meta["extent_km"])
    world_sky()
    print(
        f"[region_still] scene built: {len(terrain.data.vertices):,} verts, "
        f"{len(terrain.data.polygons):,} faces (pre-subsurf), "
        f"terrain={height_src} {height.shape[0]}×{height.shape[1]} "
        f"range [{height.min():.0f}, {height.max():.0f}] m "
        f"in {time.perf_counter() - t0:.1f}s"
    )

    bpy.ops.wm.save_as_mainfile(filepath=str(args.blend))
    print(f"[region_still] blend saved: {args.blend}")
    if args.render is None:
        return 0

    scene = bpy.context.scene
    w_str, h_str = args.res.lower().split("x")
    scene.render.resolution_x = int(w_str)
    scene.render.resolution_y = int(h_str)
    scene.render.image_settings.file_format = "PNG"
    args.render.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.render)

    scene.render.engine = "CYCLES"
    device = pick_cycles_device()
    scene.cycles.samples = args.samples
    scene.cycles.seed = 42
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"

    t1 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    print(
        f"[region_still] render done: {args.render} "
        f"({time.perf_counter() - t1:.1f}s, device={device}, samples={args.samples})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
