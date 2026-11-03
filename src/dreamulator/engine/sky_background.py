"""Sky-background derivation — pure functions, no IO (the stellar_physics /
sky_geometry / ephemeris precedent).

Background directions are fixed on the celestial sphere, so the only work here
is: unit vectors from ecliptic lon/lat, apparent magnitudes from
luminosity+distance when authored that way, and the seeded procedural faint
star field.  The star field mirrors what planetarium software gets from a
magnitude-limited catalogue (Hipparcos/Tycho tiers in Stellarium): a static
direction+magnitude+colour table the renderer rotates into the observer frame.
Our table is procedural instead of observed — the world's sky is invented —
but deterministic (seeded), so builds reproduce exactly.
"""

from __future__ import annotations

import math

import numpy as np

from dreamulator.models.sky_background import (
    BackgroundStar,
    BackgroundStarDerived,
    DeepSkyObject,
    DeepSkyObjectDerived,
    GalacticBand,
    GalacticBandDerived,
    SkyBackgroundDerived,
    SkyBackgroundInput,
    StarfieldSpec,
    TransientEvent,
    TransientEventDerived,
    WanderingObject,
    WanderingObjectDerived,
)

# Bolometric magnitude of the Sun; the magnitude derived from luminosity is a
# bolometric approximation (no bolometric correction) — documented, not hidden.
M_BOL_SUN = 4.74


def unit_vector_ecliptic(lon_deg: float, lat_deg: float) -> tuple[float, float, float]:
    """Unit direction from ecliptic longitude/latitude (catalog frame)."""
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    return (
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    )


def magnitude_from_luminosity(luminosity_sol: float, distance_pc: float) -> float:
    """Apparent magnitude from bolometric luminosity and distance.

    m = M + 5 log10(d/10 pc) with M = M_bol,sun - 2.5 log10(L/L_sun): the same
    inverse-square bookkeeping sky_phenomena.md uses for stellar magnitudes,
    without a bolometric correction (stated approximation).
    """
    absolute = M_BOL_SUN - 2.5 * math.log10(luminosity_sol)
    return absolute + 5.0 * math.log10(distance_pc) - 5.0


def generate_starfield(spec: StarfieldSpec) -> list[BackgroundStarDerived]:
    """Seeded isotropic faint-star field with a power-law magnitude law.

    Directions: standard-normal draws normalized (isotropic on the sphere).
    Magnitudes: cumulative counts follow N(<m) ∝ 10^(0.6 m) (the classical
    naked-eye/telescope star-count slope), sampled by inverse CDF between
    0 and the spec's limit.  Temperatures: a three-bin draw biased to cool
    stars, matching the real field's colour mix at naked-eye depths.
    """
    if spec.count == 0:
        return []
    rng = np.random.default_rng(spec.seed)
    vectors = rng.standard_normal((spec.count, 3))
    vectors /= np.linalg.norm(vectors, axis=1)[:, None]

    m_min = 0.0
    span = 10.0 ** (0.6 * (spec.magnitude_limit - m_min)) - 1.0
    u = rng.random(spec.count)
    magnitudes = m_min + np.log10(1.0 + u * span) / 0.6

    bins = rng.random(spec.count)
    temperatures = np.where(
        bins < 0.60,
        rng.uniform(3000.0, 4500.0, spec.count),
        np.where(
            bins < 0.85,
            rng.uniform(4500.0, 6000.0, spec.count),
            rng.uniform(6000.0, 10000.0, spec.count),
        ),
    )

    return [
        BackgroundStarDerived(
            id=f"bg_star_{i:05d}",
            name=None,
            magnitude=round(float(magnitudes[i]), 2),
            temperature_k=round(float(temperatures[i]), 0),
            unit=(
                round(float(vectors[i, 0]), 6),
                round(float(vectors[i, 1]), 6),
                round(float(vectors[i, 2]), 6),
            ),
            source="starfield",
        )
        for i in range(spec.count)
    ]


def derive_star(star: BackgroundStar) -> BackgroundStarDerived:
    magnitude = star.magnitude
    source = "authored"
    if magnitude is None:
        # validator guarantees the luminosity+distance pair in this branch
        assert star.luminosity_sol is not None and star.distance_pc is not None
        magnitude = magnitude_from_luminosity(star.luminosity_sol, star.distance_pc)
    return BackgroundStarDerived(
        id=star.id,
        name=star.name,
        magnitude=round(magnitude, 2),
        temperature_k=star.temperature_k,
        unit=unit_vector_ecliptic(star.ecliptic_lon_deg, star.ecliptic_lat_deg),
        source=source,
        variability=star.variability,
    )


def derive_deep_sky(dso: DeepSkyObject) -> DeepSkyObjectDerived:
    return DeepSkyObjectDerived(
        id=dso.id,
        name=dso.name,
        type=dso.type,
        magnitude=dso.magnitude,
        angular_size_deg=dso.angular_size_deg,
        unit=unit_vector_ecliptic(dso.ecliptic_lon_deg, dso.ecliptic_lat_deg),
    )


def derive_band(band: GalacticBand) -> GalacticBandDerived:
    return GalacticBandDerived(
        pole_unit=unit_vector_ecliptic(band.pole_lon_deg, band.pole_lat_deg),
        width_deg=band.width_deg,
        brightness=band.brightness,
    )


def derive_event(event: TransientEvent) -> TransientEventDerived:
    return TransientEventDerived(
        id=event.id,
        type=event.type,
        unit=unit_vector_ecliptic(event.ecliptic_lon_deg, event.ecliptic_lat_deg),
        epoch_window_days=event.epoch_window_days,
        peak_magnitude=event.peak_magnitude,
        rate_per_myr=event.rate_per_myr,
    )


def derive_wandering(obj: WanderingObject) -> WanderingObjectDerived:
    return WanderingObjectDerived(
        id=obj.id,
        name=obj.name,
        object_type=obj.object_type,
        unit=unit_vector_ecliptic(obj.ecliptic_lon_deg, obj.ecliptic_lat_deg),
        distance_pc=obj.distance_pc,
        magnitude=obj.magnitude,
        close_approach_au=obj.close_approach_au,
        encounter_age_myr=obj.encounter_age_myr,
    )


def derive_sky_background(source: SkyBackgroundInput) -> SkyBackgroundDerived:
    """Input → derived: resolve magnitudes, freeze directions as unit vectors,
    and append the seeded star field to the authored stars."""
    stars = [derive_star(s) for s in source.stars]
    stars.extend(generate_starfield(source.starfield))
    return SkyBackgroundDerived(
        frame=source.frame,
        starfield=source.starfield,
        stars=stars,
        deep_sky=[derive_deep_sky(d) for d in source.deep_sky],
        galactic_band=derive_band(source.galactic_band) if source.galactic_band else None,
        transient_events=[derive_event(e) for e in source.transient_events],
        wandering_objects=[derive_wandering(o) for o in source.wandering_objects],
    )
