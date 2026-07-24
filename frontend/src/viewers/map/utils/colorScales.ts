/**
 * Color scales for map layer rendering.
 *
 * Each scale maps a normalised value [0, 1] to an RGB triplet.
 * Designed for use in GLSL shaders as lookup textures (1-D data textures).
 */

export interface ColorStop {
  value: number // 0..1
  color: [number, number, number] // RGB 0..255
}

// ---------------------------------------------------------------------------
// Terrain color scale (hypsometric tint)
// ---------------------------------------------------------------------------

/**
 * Mixed hypsometric tint (static fallback).
 * Ocean: NOAA ETOPO1 palette.  Land: ESRI Natural Earth style.
 */
export const TERRAIN_SCALE: ColorStop[] = [
  { value: 0.00, color: hexToRgb('#023858') },  // deepest ocean
  { value: 0.15, color: hexToRgb('#045A8D') },  // deep ocean
  { value: 0.30, color: hexToRgb('#2B8CBE') },  // mid ocean
  { value: 0.42, color: hexToRgb('#74A9CF') },  // shallow water
  { value: 0.49, color: hexToRgb('#5EA8D0') },  // mid-shallow (cool blue)
  { value: 0.498, color: hexToRgb('#A0D0E8') }, // water's edge (clean light blue)
  { value: 0.50, color: hexToRgb('#D0C8A0') },  // sand / beach
  { value: 0.51, color: hexToRgb('#7DAF5A') },  // coastal green
  { value: 0.53, color: hexToRgb('#2F7A3C') },  // forest green
  { value: 0.60, color: hexToRgb('#A0B040') },  // yellow-green hills
  { value: 0.70, color: hexToRgb('#C8A858') },  // yellow-brown plateau
  { value: 0.82, color: hexToRgb('#8B5E3C') },  // mountain brown
  { value: 0.88, color: hexToRgb('#A08078') },  // grey-brown high mt
  { value: 0.93, color: hexToRgb('#D8D0C8') },  // snow grey
  { value: 1.00, color: hexToRgb('#FFFFFF') },  // peak white
]

/** Binary land/sea. */
export const LANDSEA_SCALE: ColorStop[] = [
  { value: 0.0, color: [30, 60, 120] }, // water
  { value: 0.39, color: [30, 60, 120] }, // water up to sea level
  { value: 0.40, color: [80, 140, 60] }, // land at sea level
  { value: 1.0, color: [80, 140, 60] }, // land
]

// ---------------------------------------------------------------------------
// Plate colors (distinct categorical palette)
// ---------------------------------------------------------------------------

export const PLATE_COLORS: string[] = [
  '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231',
  '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4',
  '#469990', '#dcbeff', '#9A6324', '#fffac8', '#800000',
  '#aaffc3', '#808000', '#ffd8b1', '#000075', '#a9a9a9',
]

/** Get a hex colour for a plate index. */
export function plateColor(index: number): string {
  return PLATE_COLORS[index % PLATE_COLORS.length]
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/** Parse a hex color string to an [r, g, b] tuple (0–255). */
function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ]
}

// ---------------------------------------------------------------------------
// Adaptive hypsometric tint
// ---------------------------------------------------------------------------

/**
 * Generate an adaptive 256-entry RGBA lookup table based on the actual
 * elevation range of the dataset.
 *
 * The LUT is normalized so that index 0 = minElev and index 255 = maxElev.
 * Color scheme:
 *   Deep ocean  → shallow ocean → coast → lowland → midland →
 *   highland → mountain → peak
 *
 * @param minElev  Minimum elevation in metres (may be negative).
 * @param maxElev  Maximum elevation in metres.
 * @param seaLevel Sea-level elevation in metres (typically 0).
 */
export function generateAdaptiveTerrainScale(
  minElev: number,
  maxElev: number,
  seaLevel: number,
): Uint8Array {
  const range = maxElev - minElev || 1

  // Mixed hypsometric palette:
  //   Ocean: NOAA ETOPO1 v2.64 scientific palette (deep→shallow blues)
  //   Land:  ESRI / ArcGIS Natural Earth style (green→brown→grey→white)
  //
  // Colour scheme research and references documented in
  //   docs/usage/map-workflow.md § 配色方案
  const colorBreaks: { elev: number; color: [number, number, number] }[] = [
    // ---- Ocean: NOAA ETOPO1 ----
    { elev: minElev, color: hexToRgb('#023858') },
    { elev: minElev + range * 0.15, color: hexToRgb('#045A8D') },
    { elev: minElev + range * 0.30, color: hexToRgb('#2B8CBE') },
    { elev: seaLevel - Math.max(range * 0.02, 200), color: hexToRgb('#74A9CF') },
    { elev: seaLevel - Math.max(range * 0.005, 50), color: hexToRgb('#5EA8D0') },
    { elev: seaLevel - Math.max(range * 0.0015, 15), color: hexToRgb('#A0D0E8') },
    // ---- Shoreline ----
    { elev: seaLevel, color: hexToRgb('#D0C8A0') },
    // ---- Land: ESRI Natural Earth style ----
    { elev: seaLevel + Math.max(range * 0.005, 50), color: hexToRgb('#7DAF5A') },
    { elev: seaLevel + range * 0.02, color: hexToRgb('#2F7A3C') },
    { elev: seaLevel + range * 0.08, color: hexToRgb('#A0B040') },
    { elev: seaLevel + range * 0.18, color: hexToRgb('#C8A858') },
    { elev: seaLevel + range * 0.30, color: hexToRgb('#8B5E3C') },
    { elev: seaLevel + range * 0.35, color: hexToRgb('#A08078') },
    { elev: seaLevel + range * 0.40, color: hexToRgb('#D8D0C8') },
    { elev: maxElev, color: hexToRgb('#FFFFFF') },
  ]

  // Sort by elevation (should already be sorted, but be safe)
  colorBreaks.sort((a, b) => a.elev - b.elev)

  const lut = new Uint8Array(256 * 4)

  for (let i = 0; i < 256; i++) {
    // Map LUT index to elevation in metres
    const elev = minElev + (i / 255) * range

    // Find surrounding color stops
    let lower = colorBreaks[0]
    let upper = colorBreaks[colorBreaks.length - 1]
    for (let s = 0; s < colorBreaks.length - 1; s++) {
      if (elev >= colorBreaks[s].elev && elev <= colorBreaks[s + 1].elev) {
        lower = colorBreaks[s]
        upper = colorBreaks[s + 1]
        break
      }
    }

    const segRange = upper.elev - lower.elev
    const t = segRange > 0 ? (elev - lower.elev) / segRange : 0

    lut[i * 4 + 0] = Math.round(lower.color[0] + t * (upper.color[0] - lower.color[0]))
    lut[i * 4 + 1] = Math.round(lower.color[1] + t * (upper.color[1] - lower.color[1]))
    lut[i * 4 + 2] = Math.round(lower.color[2] + t * (upper.color[2] - lower.color[2]))
    lut[i * 4 + 3] = 255
  }

  return lut
}

// ---------------------------------------------------------------------------
// Utility: generate a 1-D lookup texture from a color scale
// ---------------------------------------------------------------------------

/**
 * Generate a Uint8Array RGB lookup table from a color scale.
 * Suitable for uploading as a 1-D DataTexture to the GPU.
 *
 * @param scale Color stops defining the gradient.
 * @param resolution Number of entries in the lookup table.
 * @returns Uint8Array of length resolution * 3 (RGB).
 */
export function generateLut(
  scale: ColorStop[],
  resolution: number = 256,
): Uint8Array {
  const lut = new Uint8Array(resolution * 3)
  const stops = [...scale].sort((a, b) => a.value - b.value)

  for (let i = 0; i < resolution; i++) {
    const t = i / (resolution - 1)

    // Find surrounding stops
    let lower = stops[0]
    let upper = stops[stops.length - 1]
    for (let s = 0; s < stops.length - 1; s++) {
      if (t >= stops[s].value && t <= stops[s + 1].value) {
        lower = stops[s]
        upper = stops[s + 1]
        break
      }
    }

    // Interpolate
    const range = upper.value - lower.value
    const alpha = range > 0 ? (t - lower.value) / range : 0
    lut[i * 3 + 0] = Math.round(lower.color[0] + alpha * (upper.color[0] - lower.color[0]))
    lut[i * 3 + 1] = Math.round(lower.color[1] + alpha * (upper.color[1] - lower.color[1]))
    lut[i * 3 + 2] = Math.round(lower.color[2] + alpha * (upper.color[2] - lower.color[2]))
  }

  return lut
}
