"""Terrain generator — procedural heightmap generation using multi-octave noise.

Produces realistic-looking terrain by layering Gaussian noise at multiple
scales, then shaping with continent masks and mountain ridges.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter


@dataclass
class TerrainParams:
    """Parameters controlling terrain generation."""

    num_continents: int = field(default=3, metadata={"description": "Approximate number of continents"})
    continent_scale: float = field(
        default=0.15,
        metadata={"description": "Base scale of continents as fraction of map width"},
    )
    mountaininess: float = field(
        default=0.5,
        metadata={"description": "0 = very flat, 1 = very mountainous"},
    )
    ocean_depth: float = field(
        default=0.35,
        metadata={"description": "Target mean ocean depth as normalised value [0, 1]"},
    )
    continental_shelf_width: float = field(
        default=0.05,
        metadata={"description": "Width of continental shelf as fraction of map width"},
    )
    roughness: float = field(
        default=0.5,
        metadata={"description": "Small-scale roughness [0, 1]"},
    )
    latitude_effect: bool = field(
        default=True,
        metadata={"description": "Apply latitude-based polar flattening"},
    )
    sea_level_target: float = field(
        default=0.4,
        metadata={"description": "Target fraction of map below sea level"},
    )


def generate_terrain(
    width: int,
    height: int,
    seed: int,
    params: TerrainParams | None = None,
) -> np.ndarray:
    """Generate a procedural heightmap.

    Args:
        width: Map width in pixels.
        height: Map height in pixels.
        seed: RNG seed for reproducibility.
        params: Terrain generation parameters (uses defaults if None).

    Returns:
        2-D numpy float64 array with values in [0, 1].
    """
    if params is None:
        params = TerrainParams()

    rng = np.random.default_rng(seed)
    terrain = np.zeros((height, width), dtype=np.float64)

    # --- Layer 1: Continental base ---
    # Large-scale noise for continent shapes
    base_sigma = width * params.continent_scale
    continent_noise = _make_noise(height, width, rng, sigma=base_sigma)

    # Add a second continent octave for variation
    continent_noise += 0.5 * _make_noise(height, width, rng, sigma=base_sigma * 0.6)
    continent_noise /= continent_noise.max() + 1e-10

    # Shape continents: push values above/below a threshold
    threshold = 1.0 - params.sea_level_target
    continent_mask = continent_noise > threshold
    terrain = np.where(
        continent_mask,
        0.5 + (continent_noise - threshold) * 2.0,  # land
        params.ocean_depth * (continent_noise / threshold),  # ocean
    )

    # --- Layer 2: Mountain ridges on land ---
    if params.mountaininess > 0:
        ridge_sigma = width * 0.03
        ridge_noise = _make_noise(height, width, rng, sigma=ridge_sigma)
        ridge_noise = np.abs(ridge_noise - 0.5) * 2.0  # fold to create ridges
        ridge_noise = ridge_noise ** (2.0 - params.mountaininess)  # sharpen
        terrain += continent_mask * ridge_noise * params.mountaininess * 0.3

    # --- Layer 3: Medium detail ---
    detail_sigma = width * 0.01
    detail = _make_noise(height, width, rng, sigma=detail_sigma)
    terrain += (detail - 0.5) * 0.1

    # --- Layer 4: Fine roughness ---
    if params.roughness > 0:
        fine_sigma = max(1.0, width * 0.003)
        fine = _make_noise(height, width, rng, sigma=fine_sigma)
        terrain += (fine - 0.5) * params.roughness * 0.05

    # --- Layer 5: Latitude effect (polar flattening) ---
    if params.latitude_effect:
        lats = np.linspace(1, -1, height)  # 1 at top (north), -1 at bottom
        polar_weight = 1.0 - 0.3 * np.abs(lats) ** 3  # slight flattening at poles
        terrain *= polar_weight[:, np.newaxis]

    # --- Layer 6: Continental shelf smoothing ---
    if params.continental_shelf_width > 0:
        shelf_sigma = width * params.continental_shelf_width
        terrain = gaussian_filter(terrain, sigma=(shelf_sigma * 0.5, shelf_sigma))

    # Normalise to [0, 1]
    tmin, tmax = terrain.min(), terrain.max()
    if tmax > tmin:
        terrain = (terrain - tmin) / (tmax - tmin)

    # --- Handle longitude wrap-around ---
    # Blend left/right edges AFTER normalisation for seamless wrapping
    blend_width = max(1, width // 8)
    _blend_horizontal_wrap(terrain, blend_width)

    return terrain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_noise(
    height: int,
    width: int,
    rng: np.random.Generator,
    sigma: float,
) -> np.ndarray:
    """Generate smooth Gaussian noise at a given scale.

    Args:
        height: Output height.
        width: Output width.
        rng: Random number generator.
        sigma: Gaussian smoothing sigma (controls feature size).

    Returns:
        2-D array with values roughly in [0, 1].
    """
    raw = rng.standard_normal((height, width))
    smoothed = gaussian_filter(raw, sigma=(sigma * height / width, sigma))
    # Normalise
    smin, smax = smoothed.min(), smoothed.max()
    if smax > smin:
        smoothed = (smoothed - smin) / (smax - smin)
    return smoothed


def _blend_horizontal_wrap(arr: np.ndarray, blend_width: int) -> None:
    """Blend left and right edges of a 2-D array for seamless wrapping.

    Cross-fades the left and right edge strips so that column 0 and
    column (w-1) converge to the same value (the seam).  Uses cosine
    interpolation for smoothness.  Modifies in place.
    """
    h, w = arr.shape
    if blend_width < 1 or w < blend_width * 2:
        return

    # Save original edge strips
    left_strip = arr[:, :blend_width].copy()
    right_strip = arr[:, w - blend_width :].copy()

    for i in range(blend_width):
        # i=0 is the seam (col 0 on left, col w-1 on right)
        # alpha: 0 at the seam → 1 at blend_width
        alpha = 0.5 * (1 - np.cos(np.pi * i / blend_width))
        # Left side: seam value is average of left[0] and right[-1]
        seam_val = 0.5 * (left_strip[:, 0] + right_strip[:, -1])
        arr[:, i] = alpha * left_strip[:, i] + (1 - alpha) * seam_val
        # Right side (mirrored): seam value is same average
        arr[:, w - 1 - i] = alpha * right_strip[:, blend_width - 1 - i] + (1 - alpha) * seam_val
