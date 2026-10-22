"""Fast full-disk rotation frames for the orbital weather-globe chain.

A planet spinning under a fixed camera with a fixed star has a **constant
atmospheric geometry**: the shell is spherically symmetric, so the view-ray
atmosphere in-scatter, transmittances and cloud-shell lighting do not change
from frame to frame.  Only the surface and cloud textures rotate.  This
module prepares all of that geometry once (:class:`SpinRenderer`) and then
produces frames by re-sampling the textures with a longitude offset.  A
720p, 8-second, 30 fps clip therefore costs one full atmosphere render plus a
few minutes of texture sampling instead of 240 full renders.

The renderer follows :func:`dreamulator.media.atmosphere_render.render_globe_atmosphere`
exactly; ``frame(0)`` is the same image as the static renderer (verified by
the unit test).  The rotation offset is subtracted from the texture longitude,
so the surface moves eastward (prograde) as the offset decreases.

This is deliberately a still-cloud rotation: L4 (time evolution) will advect
the cloud field along the wind; until then the clouds rotate rigidly with the
planet.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import gaussian_filter

from dreamulator.media.atmosphere_render import (
    CLOUD_ALTITUDE_KM,
    AtmosphereModel,
    _linear_to_srgb,
    _march_segment,
    _sample_equirect,
    _sample_equirect_rgb,
    _srgb_to_linear,
    build_multiscattering_lut,
    build_transmittance_lut,
)


class SpinRenderer:
    """Prepared full-disk renderer for a rotating planet.

    Parameters mirror :func:`render_globe_atmosphere`.  ``surface_rgb`` and
    ``cloud_alpha`` are the equirectangular surface and cloud textures; the
    camera and star are fixed in the inertial frame, so the terminator stays
    put while the textures rotate.
    """

    def __init__(
        self,
        surface_rgb: np.ndarray,
        cloud_alpha: np.ndarray,
        *,
        res: int = 720,
        center_lon_deg: float = 90.0,
        center_lat_deg: float = 15.0,
        sun_lon_deg: float | None = None,
        sun_lat_deg: float = 20.0,
        model: AtmosphereModel | None = None,
        cloud_rgb: tuple[int, int, int] = (252, 250, 245),
        cloud_altitude_km: float = CLOUD_ALTITUDE_KM,
        cloud_shadows: bool = True,
        ocean_mask: np.ndarray | None = None,
        sun_glint: bool = True,
        water_roughness: float = 0.08,
        multiple_scattering: bool = True,
        exposure: str = "white_balance",
        auto_exposure: bool = True,
        view_samples: int = 14,
    ) -> None:
        if model is None:
            model = AtmosphereModel()
        if exposure not in ("white_balance", "physical"):
            raise ValueError("exposure must be 'white_balance' or 'physical'")
        surface = _srgb_to_linear(np.asarray(surface_rgb, dtype=np.float64))
        cloud = np.asarray(cloud_alpha, dtype=np.float64)
        if surface.ndim != 3 or surface.shape[2] != 3:
            raise ValueError("surface_rgb must have shape (h, w, 3)")
        if cloud.shape != surface.shape[:2]:
            raise ValueError("cloud_alpha must match the surface grid")
        if ocean_mask is not None:
            ocean_mask = np.asarray(ocean_mask, dtype=np.float64)
            if ocean_mask.shape != surface.shape[:2]:
                raise ValueError("ocean_mask must match the surface grid")

        self.surface = surface
        self.cloud = cloud
        self.ocean = ocean_mask
        self.model = model
        self.res = res
        self.cloud_rgb = cloud_rgb
        self.cloud_altitude_km = cloud_altitude_km
        self.cloud_shadows = cloud_shadows
        self.sun_glint = sun_glint
        self.water_roughness = water_roughness
        self.exposure = exposure

        planet = model.planet_radius_km
        top = planet + model.top_altitude_km
        cloud_radius = planet + cloud_altitude_km

        lam_c = math.radians(center_lon_deg)
        phi_c = math.radians(center_lat_deg)
        if sun_lon_deg is None:
            sun_lon_deg = center_lon_deg - 25.0
        lam_s = math.radians(sun_lon_deg)
        phi_s = math.radians(sun_lat_deg)
        f = np.array(
            [
                math.cos(phi_c) * math.cos(lam_c),
                math.sin(phi_c),
                math.cos(phi_c) * math.sin(lam_c),
            ]
        )
        right = np.array([-math.sin(lam_c), 0.0, math.cos(lam_c)])
        up = np.cross(right, f)
        sun = np.array(
            [
                math.cos(phi_s) * math.cos(lam_s),
                math.sin(phi_s),
                math.cos(phi_s) * math.sin(lam_s),
            ]
        )
        self.f = f
        self.right = right
        self.up = up
        self.sun = sun

        half = res / 2.0
        py, px = np.mgrid[0:res, 0:res].astype(np.float64)
        vx = (px + 0.5 - half) / (half * 0.92)
        vy = (half - py - 0.5) / (half * 0.92)
        b2 = (vx * vx + vy * vy) * planet * planet
        b = np.sqrt(b2)
        origin = (vx * right[0] + vy * up[0]) * planet
        origin_y = (vx * right[1] + vy * up[1]) * planet
        origin_z = (vx * right[2] + vy * up[2]) * planet

        self.has_atmosphere = b < top
        self.hits_surface = b < planet
        self.hits_cloud = b < cloud_radius

        sigma_entry = np.sqrt(np.maximum(top * top - b2, 0.0))
        sigma_surface = np.sqrt(np.maximum(planet * planet - b2, 0.0))
        sigma_cloud = np.sqrt(np.maximum(cloud_radius * cloud_radius - b2, 0.0))
        sigma_end = np.where(self.hits_surface, sigma_surface, -sigma_entry)
        sigma_split = np.where(self.hits_cloud, sigma_cloud, sigma_end)

        lut = build_transmittance_lut(model)
        ms_lut = build_multiscattering_lut(model, lut) if multiple_scattering else None
        self.radiance_upper, self.trans_upper = _march_segment(
            origin_xy=(origin, origin_y),
            origin_z=origin_z,
            b2=b2,
            f=f,
            sun=sun,
            sigma_start=sigma_entry,
            sigma_end=sigma_split,
            model=model,
            lut=lut,
            n_steps=view_samples,
            ms_lut=ms_lut,
        )
        self.radiance_lower, self.trans_lower = _march_segment(
            origin_xy=(origin, origin_y),
            origin_z=origin_z,
            b2=b2,
            f=f,
            sun=sun,
            sigma_start=sigma_split,
            sigma_end=sigma_end,
            model=model,
            lut=lut,
            n_steps=view_samples,
            ms_lut=ms_lut,
        )

        # ---- Cloud shell static geometry and lighting ----
        cx = origin + sigma_cloud * f[0]
        cy = origin_y + sigma_cloud * f[1]
        cz = origin_z + sigma_cloud * f[2]
        c_radius = np.sqrt(np.maximum(cx * cx + cy * cy + cz * cz, 1e-9))
        self.c_lat = np.degrees(np.arcsin(np.clip(cy / c_radius, -1.0, 1.0)))
        self.c_lon = np.degrees(np.arctan2(cz, cx))
        cos_cloud = np.clip((cx * sun[0] + cy * sun[1] + cz * sun[2]) / c_radius, -1.0, 1.0)
        self.cos_cloud = np.clip(cos_cloud, 0.0, None)
        self.sun_cloud = lut.sample(np.full_like(self.c_lat, cloud_altitude_km), cos_cloud)
        self.h_tex = gaussian_filter(cloud, 3.0)
        self.tint = _srgb_to_linear(np.asarray(cloud_rgb, dtype=np.float64) / 255.0)
        self.sun_screen = np.array([np.dot(sun, right), np.dot(sun, up), np.dot(sun, f)])
        self.sun_screen = self.sun_screen / max(np.linalg.norm(self.sun_screen), 1e-9)
        self.tex_dlon = 360.0 / self.h_tex.shape[1]
        self.tex_dlat = 180.0 / self.h_tex.shape[0]

        # ---- Surface static geometry and lighting ----
        self.s_lat = np.degrees(
            np.arcsin(
                np.clip((origin_y + sigma_surface * f[1]) / np.maximum(planet, 1e-9), -1.0, 1.0)
            )
        )
        self.s_lon = np.degrees(
            np.arctan2(origin_z + sigma_surface * f[2], origin + sigma_surface * f[0])
        )
        n_x = (origin + sigma_surface * f[0]) / planet
        n_y = (origin_y + sigma_surface * f[1]) / planet
        n_z = (origin_z + sigma_surface * f[2]) / planet
        cos_surface = np.clip(n_x * sun[0] + n_y * sun[1] + n_z * sun[2], -1.0, 1.0)
        self.cos_surface = np.clip(cos_surface, 0.0, None)
        self.sun_surface = lut.sample(np.zeros_like(cos_surface), cos_surface)

        # Shadow ray from the surface point to the cloud shell.
        self.sh_lat = np.zeros((res, res), dtype=np.float64)
        self.sh_lon = np.zeros((res, res), dtype=np.float64)
        self.shadow_valid = np.zeros((res, res), dtype=bool)
        if cloud_shadows:
            along = cos_surface
            t_shadow = -along * planet + np.sqrt(
                np.maximum(
                    (along * planet) ** 2 + cloud_radius * cloud_radius - planet * planet,
                    0.0,
                )
            )
            sh_x = n_x * planet + t_shadow * sun[0]
            sh_y = n_y * planet + t_shadow * sun[1]
            sh_z = n_z * planet + t_shadow * sun[2]
            sh_radius = np.sqrt(np.maximum(sh_x * sh_x + sh_y * sh_y + sh_z * sh_z, 1e-9))
            self.sh_lat = np.degrees(np.arcsin(np.clip(sh_y / sh_radius, -1.0, 1.0)))
            self.sh_lon = np.degrees(np.arctan2(sh_z, sh_x))
            self.shadow_valid = self.hits_surface & (cos_surface > 0.0)

        # ---- Ocean sun glint static geometry ----
        self.glint_geom = np.zeros((res, res), dtype=np.float64)
        if sun_glint and ocean_mask is not None:
            half_vec = sun + f
            half_vec = half_vec / max(float(np.linalg.norm(half_vec)), 1e-9)
            cos_half = np.clip(n_x * half_vec[0] + n_y * half_vec[1] + n_z * half_vec[2], 0.0, 1.0)
            cos_view = np.clip(n_x * f[0] + n_y * f[1] + n_z * f[2], 0.0, 1.0)
            alpha = max(float(water_roughness), 1e-3)
            denom = cos_half * cos_half * (alpha * alpha - 1.0) + 1.0
            distribution = alpha * alpha / (math.pi * np.maximum(denom * denom, 1e-8))
            fresnel = 0.02 + 0.98 * (1.0 - cos_half) ** 5
            specular = np.minimum(
                distribution * fresnel / (4.0 * np.maximum(cos_view * cos_surface, 1e-4)),
                20.0,
            )
            self.glint_geom = specular * self.cos_surface * self.hits_surface

        # ---- Fixed exposure gain ----
        overhead = lut.sample(np.zeros(1), np.ones(1))[0]
        if exposure == "white_balance":
            self.gain = 1.0 / np.maximum(overhead, 1e-3)
        else:
            gain = np.asarray(model.light_color("physical"), dtype=np.float64)
            if auto_exposure:
                overhead_luminance = float(
                    0.2126 * overhead[0] + 0.7152 * overhead[1] + 0.0722 * overhead[2]
                )
                gain = gain * max(min(1.0 / max(overhead_luminance, 1e-6), 2.0), 0.5)
            self.gain = gain

    def frame(self, lon_offset_deg: float = 0.0) -> np.ndarray:
        """Render one frame with the textures shifted by ``lon_offset_deg``."""
        s_lon = self.s_lon + lon_offset_deg
        surface = _sample_equirect_rgb(self.surface, self.s_lat, s_lon)

        c_lon = self.c_lon + lon_offset_deg
        coverage = np.clip(_sample_equirect(self.cloud, self.c_lat, c_lon), 0.0, 1.0)
        h0 = _sample_equirect(self.h_tex, self.c_lat, c_lon)
        hx = _sample_equirect(self.h_tex, self.c_lat, c_lon + self.tex_dlon)
        hy = _sample_equirect(self.h_tex, self.c_lat - self.tex_dlat, c_lon)
        nx = -(hx - h0) * 8.0
        ny = -(hy - h0) * 8.0
        nlen = np.sqrt(nx * nx + ny * ny + 1.0)
        shade = np.clip(
            (nx * self.sun_screen[0] + ny * self.sun_screen[1] + self.sun_screen[2]) / nlen,
            0.0,
            1.0,
        )
        term = 0.45 + 0.95 * np.power(shade, 0.9)
        gate = np.clip(coverage / 0.15, 0.0, 1.0)
        thickness = 0.80 + 0.40 * coverage
        light_mod = 1.0 + gate * (term * thickness - 1.0)
        cloud_light = self.tint * self.sun_cloud * self.cos_cloud[..., None] * light_mod[..., None]

        shadow = np.ones((self.res, self.res), dtype=np.float64)
        if self.cloud_shadows:
            shadow_sample = 1.0 - np.clip(
                _sample_equirect(self.cloud, self.sh_lat, self.sh_lon + lon_offset_deg),
                0.0,
                1.0,
            )
            shadow = np.where(self.shadow_valid, shadow_sample, 1.0)

        surface_radiance = (
            surface
            * self.sun_surface
            * self.cos_surface[..., None]
            * shadow[..., None]
            * self.hits_surface[..., None]
        )
        if self.ocean is not None and np.any(self.glint_geom > 0.0):
            ocean = _sample_equirect(self.ocean, self.s_lat, s_lon).clip(0.0, 1.0)
            glint = self.glint_geom * ocean * shadow
            surface_radiance = surface_radiance + glint[..., None] * self.sun_surface

        behind_cloud = self.trans_lower * surface_radiance + self.radiance_lower
        with_cloud = coverage[..., None] * cloud_light + (1.0 - coverage[..., None]) * behind_cloud
        at_cloud = self.radiance_upper + self.trans_upper * with_cloud
        at_surface = self.radiance_upper + self.trans_upper * (
            self.trans_lower * surface_radiance + self.radiance_lower
        )
        rgb = np.where(self.hits_cloud[..., None], at_cloud, at_surface)
        rgb = np.where(self.has_atmosphere[..., None], rgb, 0.0)
        rgb = rgb * self.gain
        return np.asarray(np.clip(_linear_to_srgb(rgb), 0.0, 1.0) * 255.0, dtype=np.uint8)
