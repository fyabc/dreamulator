"""YAML configuration for the ``export clouds`` command.

The command has accumulated enough knobs (grid, seed, view, cover scaling and
the L3 cyclone block) that a file is easier to keep with a shot than a long
flag list.  CLI flags still win over the file, so quick one-off overrides do
not require editing it.

Example::

    grid: 8192x4096
    seed: 7
    globe_res: 1600
    center_lon: 90
    center_lat: 15
    sun_lat: 20
    cover_scale: 1.0
    cyclones:
      enabled: true
      seed: 31
      tropical_per_hemisphere: 1
      extratropical_per_hemisphere: 2
      tropical_scale: 1.0
      extratropical_scale: 1.0
    atmosphere:
      enabled: true
      exposure: white_balance
      cloud_altitude_km: 4.0
      cirrus_altitude_km: 9.0
      sun_glint: true
      multiple_scattering: true
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pathlib import Path


class CycloneTrack(BaseModel):
    """One explicit cyclone track entry (same fields as ``Cyclone``)."""

    model_config = ConfigDict(extra="forbid")

    lat_deg: float
    lon_deg: float
    kind: Literal["tropical", "extratropical"] = "tropical"
    central_pressure_hpa: float = 970.0
    environment_pressure_hpa: float = 1010.0
    rmax_km: float = 120.0
    outer_radius_km: float = 1800.0
    motion_east_m_s: float = 0.0
    motion_north_m_s: float = 0.0
    shape_seed: int = 0


class CycloneSettings(BaseModel):
    """L3 cyclone template block.

    ``tracks``, when non-empty, overrides the synthetic climatological set;
    it is the hand-off point for the future L1 track table.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    seed: int = 31
    tropical_per_hemisphere: int = 1
    extratropical_per_hemisphere: int = 2
    tropical_scale: float = 1.0
    extratropical_scale: float = 1.0
    tracks: list[CycloneTrack] = Field(default_factory=list)


class AtmosphereSettings(BaseModel):
    """L5 atmosphere block.

    Coefficients are derived from the world's ``stellar.yaml`` and
    ``planets.yaml`` at run time; the two override fields exist for QA and
    for worlds without atmospheric inputs.  ``exposure`` selects whether the
    camera white-balances the scene's direct daylight (``white_balance``,
    matching the authored surface palette) or keeps the K star's warm cast
    (``physical``).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cloud_altitude_km: float = Field(4.0, ge=0.0)
    cirrus_altitude_km: float = Field(9.0, gt=0.0)
    atmosphere_temperature_k: float = Field(273.15, gt=0.0)
    mie_scale: float = Field(1.0, ge=0.0)
    ozone_scale: float = Field(1.0, ge=0.0)
    cloud_shadows: bool = True
    sun_glint: bool = True
    water_roughness: float = Field(0.08, gt=0.0)
    multiple_scattering: bool = True
    exposure: Literal["white_balance", "physical"] = "white_balance"
    star_temperature_k: float | None = Field(None, gt=0.0)
    surface_pressure_atm: float | None = Field(None, gt=0.0)


class CloudRenderConfig(BaseModel):
    """Settings for one ``export clouds`` run."""

    model_config = ConfigDict(extra="forbid")

    grid: str = "8192x4096"
    seed: int = 7
    globe_res: int = 1600
    center_lon: float = 90.0
    center_lat: float = 15.0
    sun_lon: float | None = None
    sun_lat: float = 20.0
    cover_scale: float = 1.0
    cyclones: CycloneSettings = Field(default_factory=CycloneSettings)
    atmosphere: AtmosphereSettings = Field(default_factory=AtmosphereSettings)

    @classmethod
    def from_yaml(cls, path: Path) -> CloudRenderConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: top level must be a mapping")
        return cls.model_validate(raw)
