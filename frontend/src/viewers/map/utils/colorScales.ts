/**
 * Color scales for map layer rendering.
 *
 * Each scale maps a normalised value [0, 1] to an RGB triplet.
 * Designed for use in GLSL shaders as lookup textures (1-D data textures).
 *
 * The colour DATA is a single source in `palettes.json` (also read by the
 * Python backend for headless PNG export — see `src/dreamulator/map/`).
 * This module re-exports that data with the typed views the map renderer
 * expects, and keeps the LUT-generation helpers that consume it.
 */
import palettesJson from '@dreamulator/palettes'

export interface ColorStop {
  value: number // 0..1
  color: [number, number, number] // RGB 0..255
}

// ---------------------------------------------------------------------------
// Categorical palettes (hex strings)
// ---------------------------------------------------------------------------

/** Standard Köppen-Geiger color palette (Beck et al. 2018), incl. `Ocean`. */
export const KOPPEN_COLORS: Record<string, string> = palettesJson.categorical.koppen

/** Whittaker biome colors (categorical, 12 land + ocean). */
export const WHITTAKER_COLORS: Record<string, string> = palettesJson.categorical.whittaker

/** USDA soil order colors (categorical, 12 orders). */
export const SOIL_COLORS: Record<string, string> = palettesJson.categorical.soil

/** Distinct categorical palette for tectonic plates. */
export const PLATE_COLORS: string[] = palettesJson.categorical.plate

/** Get a hex colour for a plate index. */
export function plateColor(index: number): string {
  return PLATE_COLORS[index % PLATE_COLORS.length]
}

// ---------------------------------------------------------------------------
// Continuous scales (ColorStop[] — RGB triplets)
// ---------------------------------------------------------------------------

/** Mixed hypsometric tint (static fallback). Ocean NOAA ETOPO1 + land ESRI. */
export const TERRAIN_SCALE: ColorStop[] = palettesJson.continuous.terrain as ColorStop[]

/** Binary land/sea. */
export const LANDSEA_SCALE: ColorStop[] = palettesJson.continuous.landsea as ColorStop[]

/** NPP sequential heatmap: warm-beige (low) → deep green (high). */
export const NPP_SCALE: ColorStop[] = palettesJson.continuous.npp as ColorStop[]

/** Annual mean temperature diverging scale (ColorBrewer RdBu, −40…+40 °C). */
export const TEMPERATURE_SCALE: ColorStop[] = palettesJson.continuous.temperature as ColorStop[]

/** Annual precipitation sequential scale (ColorBrewer YlGnBu, log-normalised). */
export const PRECIP_SCALE: ColorStop[] = palettesJson.continuous.precip as ColorStop[]

/** Habitability grade (宜居等级): dark slate → amber → green → teal. */
export const HABITABILITY_SCALE: ColorStop[] = palettesJson.continuous.habitability as ColorStop[]

/** Agriculture grade (农业等级): dark grey → beige → yellow → gold. */
export const AGRICULTURE_SCALE: ColorStop[] = palettesJson.continuous.agriculture as ColorStop[]

/** Drainage / flow accumulation (流域/排水): navy (low) → white (trunk), log-normalised. */
export const FLOW_SCALE: ColorStop[] = palettesJson.continuous.flow as ColorStop[]

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
 * Generate an adaptive RGBA lookup table based on the actual elevation range.
 *
 * The LUT is normalized so that index 0 = minElev and index N-1 = maxElev.
 * Colour breaks come from `palettes.json` (single source with the backend),
 * which encodes the NOAA ETOPO1 ocean + ESRI Natural Earth land scheme —
 * researched in docs/usage/map-workflow.md § 配色方案.
 */
export function generateAdaptiveTerrainScale(
  minElev: number,
  maxElev: number,
  seaLevel: number,
): Uint8Array {
  const range = maxElev - minElev || 1
  const lutSize: number = palettesJson.adaptive_terrain.lut_size
  const lut = new Uint8Array(lutSize * 4)

  // Resolve declarative breaks (anchor/fraction/clamp_m/sign) → elevation stops.
  const colorBreaks = palettesJson.adaptive_terrain.breaks.map((b) => {
    const anchorElev = b.anchor === 'min' ? minElev : b.anchor === 'sea' ? seaLevel : maxElev
    const offset = b.clamp_m != null ? Math.max(range * b.fraction, b.clamp_m) : range * b.fraction
    const elev = anchorElev + b.sign * offset
    return { elev, color: hexToRgb(b.color) }
  })
  colorBreaks.sort((a, b) => a.elev - b.elev)

  for (let i = 0; i < lutSize; i++) {
    // Map LUT index to elevation in metres
    const elev = minElev + (i / (lutSize - 1)) * range

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
  resolution: number = 1024,
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
