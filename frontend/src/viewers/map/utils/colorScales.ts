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

/** Classic hypsometric tint: deep ocean → shallow → beach → grass → forest → rock → snow. */
export const TERRAIN_SCALE: ColorStop[] = [
  { value: 0.0, color: [10, 30, 80] }, // deep ocean
  { value: 0.25, color: [20, 60, 130] }, // mid ocean
  { value: 0.38, color: [40, 100, 170] }, // shallow water
  { value: 0.40, color: [194, 178, 129] }, // beach / coast
  { value: 0.42, color: [100, 160, 60] }, // lowland grass
  { value: 0.55, color: [60, 130, 40] }, // forest
  { value: 0.70, color: [120, 100, 60] }, // highland / rock
  { value: 0.85, color: [160, 140, 120] }, // mountain
  { value: 0.95, color: [230, 230, 240] }, // snow
  { value: 1.0, color: [255, 255, 255] }, // peak snow
]

/** Simple elevation gradient: dark → light. */
export const ELEVATION_SCALE: ColorStop[] = [
  { value: 0.0, color: [0, 0, 0] },
  { value: 1.0, color: [255, 255, 255] },
]

/** Binary land/sea. */
export const LANDSEA_SCALE: ColorStop[] = [
  { value: 0.0, color: [30, 60, 120] }, // water
  { value: 0.39, color: [30, 60, 120] }, // water up to sea level
  { value: 0.40, color: [80, 140, 60] }, // land at sea level
  { value: 1.0, color: [80, 140, 60] }, // land
]

/** Slope gradient: flat (green) → steep (red). */
export const SLOPE_SCALE: ColorStop[] = [
  { value: 0.0, color: [60, 130, 40] }, // flat
  { value: 0.3, color: [180, 160, 60] }, // moderate
  { value: 0.7, color: [180, 80, 40] }, // steep
  { value: 1.0, color: [200, 40, 20] }, // very steep / cliff
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
