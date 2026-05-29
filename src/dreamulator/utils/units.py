"""Unit conversion helpers."""

from .constants import AU_M, M_EARTH, M_SUN, R_EARTH, R_SUN


def solar_mass_to_kg(m: float) -> float:
    """Convert solar masses to kilograms."""
    return m * M_SUN


def earth_mass_to_kg(m: float) -> float:
    """Convert Earth masses to kilograms."""
    return m * M_EARTH


def solar_radius_to_m(r: float) -> float:
    """Convert solar radii to meters."""
    return r * R_SUN


def earth_radius_to_m(r: float) -> float:
    """Convert Earth radii to meters."""
    return r * R_EARTH


def au_to_m(d: float) -> float:
    """Convert astronomical units to meters."""
    return d * AU_M


def m_to_au(d: float) -> float:
    """Convert meters to astronomical units."""
    return d / AU_M
