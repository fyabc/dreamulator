"""Physical constants used across simulation engines.

Values are sourced from astropy.constants and exposed as plain floats
in SI units for convenience in computation code.
"""

from astropy import constants as const

# Speed of light (m/s)
C: float = const.c.value

# Gravitational constant (m^3 kg^-1 s^-2)
G: float = const.G.value

# Boltzmann constant (J/K)
K_B: float = const.k_B.value

# Stefan–Boltzmann constant (W m^-2 K^-4)
SIGMA: float = const.sigma_sb.value

# Solar mass (kg)
M_SUN: float = const.M_sun.value

# Solar radius (m)
R_SUN: float = const.R_sun.value

# Solar luminosity (W)
L_SUN: float = const.L_sun.value

# Earth mass (kg)
M_EARTH: float = const.M_earth.value

# Earth radius (m)
R_EARTH: float = const.R_earth.value

# Astronomical unit (m)
AU_M: float = const.au.value
