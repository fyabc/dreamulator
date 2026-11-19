"""Preflight and job endpoints for local-only region refinement."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from dreamulator.api_routes.packs import _input_meta, _pack_dir
from dreamulator.branch_manager import BranchManager
from dreamulator.build_jobs import BuildBusyError
from dreamulator.map.export import find_mesh_file
from dreamulator.map.manager import MapManager
from dreamulator.map.region_export import read_radius_km, region_window
from dreamulator.media.terrain_refine import REFINE_FACTOR, _td_python, td_compute_device
from dreamulator.region_jobs import (
    MAX_SPAN_KM,
    PACK_SIZES,
    RSS_LIMIT,
    RegionJob,
    RegionPlan,
    RegionWork,
    region_jobs,
)
from dreamulator.utils.resources import available_memory_bytes
from dreamulator.world_manager import WorldManager, _data_dir

router = APIRouter(prefix="/api/region-refinement", tags=["region-refinement"])
WorldId = Annotated[str, Field(pattern=r"^[\w][\w.-]{0,127}$")]


class RegionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal["world"]
    world: WorldId
    planet: WorldId
    branch: WorldId | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    span_km: float = Field(gt=0)
    input_px: Literal[256, 512, 1024] = 512


class RegionPackSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["pack"]
    pack: str = Field(min_length=1, max_length=255)


RegionSource = Annotated[RegionSelection | RegionPackSource, Field(discriminator="kind")]


def _configured_td() -> Path:
    if not sys.platform.startswith("linux"):
        raise HTTPException(503, "The web refinement runner currently requires Linux")
    location = os.environ.get("DREAMULATOR_TD_DIR")
    if not location:
        raise HTTPException(
            503, "Set DREAMULATOR_TD_DIR to a configured Terrain Diffusion checkout"
        )
    td = Path(location).resolve()
    try:
        _td_python(td)
    except FileNotFoundError as exc:
        raise HTTPException(
            503, "The configured Terrain Diffusion Python environment is missing"
        ) from exc
    return td


class RegionDevice(BaseModel):
    kind: Literal["gpu", "cpu", "unavailable"]
    name: str | None = None


@router.get("/device")
def region_device() -> RegionDevice:
    try:
        name = td_compute_device(_configured_td())
    except (HTTPException, OSError, ValueError, subprocess.SubprocessError):
        return RegionDevice(kind="unavailable")
    return RegionDevice(kind="gpu", name=name) if name else RegionDevice(kind="cpu")


def _environment() -> Path:
    td = _configured_td()
    available = available_memory_bytes()
    if available is None or available // 2 < RSS_LIMIT:
        raise HTTPException(503, "Web refinement requires at least 16 GiB of available RAM")
    return td


def _plan(source: RegionSelection | RegionPackSource) -> tuple[RegionPlan, RegionWork]:
    td = _environment()
    override = os.environ.get("DREAMULATOR_PACKS_DIR")
    native: float | None = None
    if isinstance(source, RegionPackSource):
        pack = _pack_dir(source.pack)
        meta = _input_meta(pack)
        grid = meta["grid"]
        pixels = int(grid["w"])
        span = float(meta["span_km"])
        if (
            int(grid["h"]) != pixels
            or meta.get("projection") != "azimuthal_equidistant"
            or float(meta["extent_km"]["x"]) != span
            or float(meta["extent_km"]["y"]) != span
            or not (pack / "input" / "height.meters.npy").is_file()
            or not meta.get("refinement_inputs")
        ):
            raise HTTPException(
                422, "The regional map lacks a square elevation and stored refinement inputs"
            )
        input_dir = pack / "input"
        if input_dir.is_symlink() or any(path.is_symlink() for path in input_dir.rglob("*")):
            raise HTTPException(422, "The regional input must not contain symbolic links")
        size = sum(path.stat().st_size for path in input_dir.rglob("*") if path.is_file())
        if size > 512 * 2**20:
            raise HTTPException(422, "The regional input exceeds the web refinement disk budget")
        scale = meta.get("cell_pitch_km")
        if isinstance(scale, (int, float)) and math.isfinite(scale) and scale > 0:
            native = float(scale)
        work = RegionWork(pack.parent, td, pack=pack)
    else:
        manager = WorldManager()
        try:
            world = manager.world_dir(source.world).resolve()
            if not world.is_relative_to(_data_dir().resolve()):
                raise FileNotFoundError(source.world)
            if source.branch is not None:
                BranchManager(world).get_branch(source.branch)
            maps = MapManager(world, source.branch)
            map_dir = maps._maps_dir(source.planet)
            meta_world = maps.get_map_metadata(source.planet)
        except FileNotFoundError as exc:
            raise HTTPException(404, "World or branch not found") from exc
        if map_dir is None or meta_world is None or find_mesh_file(map_dir) is None:
            raise HTTPException(422, "Build the world terrain before refining this selection")
        if not (map_dir / "climate_monthly.msgpack").is_file():
            raise HTTPException(422, "This selection needs monthly climate from a world build")
        radius = read_radius_km(map_dir, world)
        span = source.span_km
        try:
            region_window(source.lat, source.lon, span, radius)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        pixels = source.input_px
        native = radius * math.sqrt(4 * math.pi / meta_world.voronoi_num_cells)
        args = [
            source.world,
            "--planet",
            source.planet,
            "--lat",
            str(source.lat),
            "--lon",
            str(source.lon),
            "--span-km",
            str(span),
            "--out-res",
            str(pixels),
            "--data-dir",
            str(_data_dir().resolve()),
        ]
        if source.branch is not None:
            args.extend(("--branch", source.branch))
        work = RegionWork(
            Path(override).resolve() if override else world / "packs", td, export_args=tuple(args)
        )
    if not 0 < span <= MAX_SPAN_KM:
        raise HTTPException(
            422, f"Choose a window no larger than {MAX_SPAN_KM} km for web refinement"
        )
    if not 2 <= pixels <= PACK_SIZES[-1]:
        raise HTTPException(
            422, "The input grid is too large for web refinement; use a smaller selection"
        )
    return RegionPlan(
        span_km=span, input_px=pixels, output_px=pixels * REFINE_FACTOR, native_scale_km=native
    ), work


@router.post("/plan")
def plan_refinement(source: RegionSource) -> RegionPlan:
    plan, _ = _plan(source)
    return plan


@router.post("/jobs", status_code=202)
def start_refinement(source: RegionSource, tasks: BackgroundTasks) -> RegionJob:
    plan, work = _plan(source)
    try:
        job = region_jobs.reserve(plan)
    except BuildBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    tasks.add_task(region_jobs.execute, job.id, work)
    return job


@router.get("/jobs/{job_id}")
def get_refinement(job_id: str) -> RegionJob:
    try:
        return region_jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(404, "Refinement job not found") from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_refinement(job_id: str) -> RegionJob:
    try:
        return region_jobs.get(job_id, cancel=True)
    except KeyError as exc:
        raise HTTPException(404, "Refinement job not found") from exc
