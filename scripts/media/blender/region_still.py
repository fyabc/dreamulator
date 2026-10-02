"""region_still — build (and optionally render) a Blender scene from a region pack.

Script-rebuild workflow: the ``.blend`` is a disposable artifact, always
rebuildable from the data pack produced by ``dreamulator export region``
(see docs/design/proposals/blender-render-pipeline.md).  Scene units are
kilometres (1 unit = 1 km) with a physically correct vertical scale by
default (``--zscale`` exaggerates if a shot needs it).

Usage (Blender's bundled Python — args after ``--`` are ours):
    blender -b -P scripts/media/blender/region_still.py -- \
        --datadir private/video/nacrea-0_0_2500km \
        [--render renders/still_001.png] [--res 1920x1080] \
        [--samples 256] [--zscale 1.0] [--blend out.blend]

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


def build_terrain(height: np.ndarray, km_per_px: dict, zscale: float) -> bpy.types.Object:
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
        for loop, co in zip(uv.data, _loop_uvs(mesh, uvs)):
            loop.uv = co
    for poly in mesh.polygons:
        poly.use_smooth = True

    obj = bpy.data.objects.new("Terrain", mesh)
    bpy.context.collection.objects.link(obj)
    mod = obj.modifiers.new("Subsurf", "SUBSURF")
    mod.levels = 3
    mod.render_levels = 3
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
    bsdf.inputs["Base Color"].default_value = (0.03, 0.10, 0.18, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.12
    bsdf.inputs["IOR"].default_value = 1.33
    obj.data.materials.append(mat)
    return obj


def sun_light(az_deg: float, alt_deg: float) -> None:
    import math

    az, alt = math.radians(az_deg), math.radians(alt_deg)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
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
    """High-oblique view: slant distance ~2.2× the region extent, 30° up."""
    import math

    e = max(extent_km["x"], extent_km["y"])
    slant = 2.2 * e
    alt = math.radians(30.0)
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


def pick_cycles_device() -> str:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.get_devices()
    except Exception:  # noqa: BLE001 — device enumeration varies across builds
        pass
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
    meta = json.loads((args.datadir / "meta.json").read_text(encoding="utf-8"))
    height = np.load(args.datadir / "height.meters.npy")

    t0 = time.perf_counter()
    terrain = build_terrain(height, meta["km_per_px"], args.zscale)
    terrain.data.materials.append(terrain_material(args.datadir / "color.png"))
    ocean_plane(meta["extent_km"])
    sun_light(args.sun_az, args.sun_alt)
    camera(meta["extent_km"])
    world_sky()
    print(
        f"[region_still] scene built: {len(terrain.data.vertices):,} verts, "
        f"{len(terrain.data.polygons):,} faces (pre-subsurf) in {time.perf_counter() - t0:.1f}s"
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
