/**
 * layerBakes — CPU bake of per-layer textures (Step 3 of the layer refactor,
 * see private/plans/map-layer-refactor.md).
 *
 * Each layer KIND is baked into its own DataTexture, keyed only by DATA
 * dependencies (elevation, mesh, cell-id map, sizing) — never by opacity.
 * Opacity is applied later on the GPU (useGPUTerrain's composite pass), so
 * slider drags cost a uniform update instead of a re-bake.
 *
 * Textures baked:
 *  - terrain   (full res, opaque base canvas: hypsometric LUT + water-depth
 *               darkening + coastline)
 *  - landsea   (full res, opaque base canvas: binary land/sea + coastline)
 *  - koppen    (half res, per-cell thematic colour, alpha=0 where no data)
 *  - plates    (half res, per-cell fill colour)
 *  - boundaries(half res, per-cell feature colour)
 *
 * Cell layers bake at HALF resolution: cells are ~76 km across (~8 px at
 * 4096-wide full res), so half res (~4 px/cell, NearestFilter) is visually
 * lossless and cuts bake time + GPU memory ~4x.
 */

import * as THREE from 'three'
import type { CVTMesh, BoundaryType } from './types'
import type { CellIdMap } from './useCellIdMap'
import {
  generateAdaptiveTerrainScale,
  PLATE_COLORS,
  KOPPEN_COLORS,
  WHITTAKER_COLORS,
  NPP_SCALE,
} from './utils/colorScales'

// ---------------------------------------------------------------------------
// Colour constants (moved from useGPUTerrain)
// ---------------------------------------------------------------------------

function hexRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ]
}

const BOUNDARY_COLORS: Record<BoundaryType, [number, number, number]> = {
  convergent: hexRgb('#e53935'),
  divergent: hexRgb('#43a047'),
  transform: hexRgb('#fdd835'),
}

/** Crust colours for interior cells (no boundary type) in the boundaries layer. */
const CRUST_INTERIOR_COLORS: Record<string, [number, number, number]> = {
  continental:   hexRgb('#c8a96e'),  // warm beige
  oceanic:       hexRgb('#4a7a9e'),  // muted blue
  transitional:  hexRgb('#8ea87a'),  // olive green
}

/** Hotspot chain colour — magenta-pink, distinct from convergent red. */
const HOTSPOT_COLOR: [number, number, number] = hexRgb('#e040fb')

/** Interior landform colours — paleo-orogeny (brown) and rift (teal). */
const LANDFORM_COLORS: Record<string, [number, number, number]> = {
  orogeny: hexRgb('#b8860b'),  // dark goldenrod
  rift:    hexRgb('#008080'),  // teal
}

const COAST_COLOR = [20, 20, 20] as const

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface LayerTextures {
  /** Opaque base canvas — hypsometric tint. */
  terrain: THREE.DataTexture
  /** Opaque base canvas — binary land/sea. */
  landsea: THREE.DataTexture
  /** Per-cell thematic colour (Köppen), alpha=0 where no data. Half res. */
  koppen: THREE.DataTexture
  /** Per-cell fill colour (plates), alpha=0 where no data. Half res. */
  plates: THREE.DataTexture
  /** Per-cell feature colour (boundaries/crust), alpha=0 where no data. Half res. */
  boundaries: THREE.DataTexture
  /** Arrow-field overlay — warm=magenta, cold=cyan arrows. Half res. */
  currents: THREE.DataTexture
  /** Whittaker biome thematic (per-cell categorical). Half res. */
  biomes: THREE.DataTexture
  /** NPP heatmap thematic (per-cell continuous). Half res. */
  npp: THREE.DataTexture
  /** Civilization cradle thematic (per-cell highlight). Half res. */
  domesticable: THREE.DataTexture
}

export interface BakeInputs {
  elevation: Float32Array       // normalised [0,1] heights, north-first rows
  width: number
  height: number
  seaLevel: number              // metres
  elevMinM: number
  elevMaxM: number
  waterDepthFactor: number
  flipHorizontal: boolean       // column flip (SphereGeometry UV convention)
  cvtMesh: CVTMesh | null | undefined
  cellIdMap: CellIdMap | null | undefined
}

// ---------------------------------------------------------------------------
// Module-level bake cache — survives component unmount/remount (route nav)
// ---------------------------------------------------------------------------

interface BakeCacheEntry extends BakeInputs {
  textures: LayerTextures
}

let bakeCache: BakeCacheEntry | null = null

function sameBakeInputs(a: BakeInputs, b: BakeInputs): boolean {
  // cellIdMap is intentionally NOT part of the key: it is derived
  // deterministically from (cvtMesh, width, height), and each mounted map
  // viewer builds its own array — comparing identity would thrash the cache
  // (every consumer re-baking over the previous one's entry).
  return (
    a.elevation === b.elevation &&
    a.width === b.width &&
    a.height === b.height &&
    a.seaLevel === b.seaLevel &&
    a.elevMinM === b.elevMinM &&
    a.elevMaxM === b.elevMaxM &&
    a.waterDepthFactor === b.waterDepthFactor &&
    a.flipHorizontal === b.flipHorizontal &&
    a.cvtMesh === b.cvtMesh
  )
}

/** Bake (or reuse cached) per-layer textures for the given inputs. */
export function getLayerTextures(inputs: BakeInputs): LayerTextures {
  if (bakeCache && sameBakeInputs(bakeCache, inputs)) {
    return bakeCache.textures
  }
  // Dispose stale GPU textures before replacing.
  if (bakeCache) {
    const t = bakeCache.textures
    t.terrain.dispose(); t.landsea.dispose(); t.koppen.dispose()
    t.plates.dispose(); t.boundaries.dispose(); t.currents.dispose()
    t.biomes.dispose(); t.npp.dispose(); t.domesticable.dispose()
  }

  const textures = bakeAll(inputs)
  bakeCache = { ...inputs, textures }
  return textures
}

// ---------------------------------------------------------------------------
// Bake implementation
// ---------------------------------------------------------------------------

/** Row-flip (always; texture flipY=false convention) + optional column flip. */
function flipBuffer(buf: Uint8Array, width: number, height: number, flipHorizontal: boolean): Uint8Array {
  const out = new Uint8Array(buf.length)
  for (let y = 0; y < height; y++) {
    const srcRow = (height - 1 - y) * width * 4
    const dstRow = y * width * 4
    for (let x = 0; x < width; x++) {
      const srcX = flipHorizontal ? (width - 1 - x) * 4 : x * 4
      const dstX = x * 4
      out[dstRow + dstX] = buf[srcRow + srcX]
      out[dstRow + dstX + 1] = buf[srcRow + srcX + 1]
      out[dstRow + dstX + 2] = buf[srcRow + srcX + 2]
      out[dstRow + dstX + 3] = buf[srcRow + srcX + 3]
    }
  }
  return out
}

function makeTexture(buf: Uint8Array, width: number, height: number, nearest: boolean): THREE.DataTexture {
  const tex = new THREE.DataTexture(buf as unknown as BufferSource, width, height, THREE.RGBAFormat)
  tex.wrapS = THREE.ClampToEdgeWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping
  const filter = nearest ? THREE.NearestFilter : THREE.LinearFilter
  tex.minFilter = filter
  tex.magFilter = filter
  tex.needsUpdate = true
  return tex
}

/**
 * Cell-level coastline detection (single pass over all pixels).  Returns a
 * mask (1 = coastline pixel) shared by BOTH base bakes — previously the
 * detection ran twice (once per base), doubling an already expensive pass.
 */
function computeCoastMask(
  width: number,
  height: number,
  cvtMesh: CVTMesh,
  cellIdMap: CellIdMap,
  seaLevel: number,
): Uint8Array {
  const mask = new Uint8Array(width * height)
  const cellLand = new Map<number, boolean>()
  for (const cell of cvtMesh.cells) {
    cellLand.set(cell.id, cell.elevation >= seaLevel)
  }
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x
      const cid = cellIdMap[i]
      if (cid == null) continue
      const isLand = cellLand.get(cid)
      if (isLand == null) continue
      // Right neighbour
      if (x + 1 < width) {
        const nCid = cellIdMap[y * width + x + 1]
        if (nCid != null && nCid !== cid) {
          const nLand = cellLand.get(nCid)
          if (nLand != null && isLand !== nLand) {
            mask[i] = 1
            mask[y * width + x + 1] = 1
          }
        }
      }
      // Bottom neighbour
      if (y + 1 < height) {
        const nCid = cellIdMap[(y + 1) * width + x]
        if (nCid != null && nCid !== cid) {
          const nLand = cellLand.get(nCid)
          if (nLand != null && isLand !== nLand) {
            mask[i] = 1
            mask[(y + 1) * width + x] = 1
          }
        }
      }
    }
  }
  return mask
}

function bakeTerrainBase(inp: BakeInputs, coastMask: Uint8Array | null): Uint8Array {
  const { elevation, width, height, elevMinM, elevMaxM, waterDepthFactor, flipHorizontal, seaLevel } = inp
  const totalPixels = width * height
  const buf = new Uint8Array(totalPixels * 4)
  const lut = generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel)
  const range = elevMaxM - elevMinM || 1
  const normSeaLevel = (seaLevel - elevMinM) / range

  for (let i = 0; i < totalPixels; i++) {
    const elev = elevation[i]
    const idx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
    let r = lut[idx * 4], g = lut[idx * 4 + 1], b = lut[idx * 4 + 2]
    if (elev < normSeaLevel) {
      const depth = (normSeaLevel - elev) / Math.max(normSeaLevel, 0.001)
      const f = 1 - waterDepthFactor * depth
      r = Math.round(r * f); g = Math.round(g * f); b = Math.round(b * f)
    }
    const pi = i * 4
    if (coastMask && coastMask[i]) {
      buf[pi] = COAST_COLOR[0]; buf[pi + 1] = COAST_COLOR[1]; buf[pi + 2] = COAST_COLOR[2]
    } else {
      buf[pi] = r; buf[pi + 1] = g; buf[pi + 2] = b
    }
    buf[pi + 3] = 255
  }

  return flipBuffer(buf, width, height, flipHorizontal)
}

function bakeLandseaBase(inp: BakeInputs, coastMask: Uint8Array | null): Uint8Array {
  const { elevation, width, height, seaLevel, elevMinM, elevMaxM, flipHorizontal } = inp
  const totalPixels = width * height
  const buf = new Uint8Array(totalPixels * 4)
  const range = elevMaxM - elevMinM || 1
  const normSeaLevel = (seaLevel - elevMinM) / range
  const cutoff = Math.round(normSeaLevel * 1023)

  for (let i = 0; i < totalPixels; i++) {
    const idx = Math.min(1023, Math.max(0, Math.round(elevation[i] * 1023)))
    const water = idx <= cutoff
    const pi = i * 4
    if (coastMask && coastMask[i]) {
      buf[pi] = COAST_COLOR[0]; buf[pi + 1] = COAST_COLOR[1]; buf[pi + 2] = COAST_COLOR[2]
    } else if (water) {
      buf[pi] = 30; buf[pi + 1] = 60; buf[pi + 2] = 120
    } else {
      buf[pi] = 80; buf[pi + 1] = 140; buf[pi + 2] = 60
    }
    buf[pi + 3] = 255
  }

  return flipBuffer(buf, width, height, flipHorizontal)
}

/** Per-cell colour palettes keyed by cell id (ported from useGPUTerrain). */
/** Look up a colour from a sequential scale by normalised value [0,1]. */
function sequentialColor(value: number, scale: typeof NPP_SCALE): [number, number, number] {
  const t = Math.max(0, Math.min(1, value))
  for (let i = scale.length - 1; i >= 0; i--) {
    if (t >= scale[i].value) {
      if (i === scale.length - 1) return scale[i].color
      const s = scale[i], e = scale[i + 1]
      const frac = (t - s.value) / (e.value - s.value)
      return [
        Math.round(s.color[0] + (e.color[0] - s.color[0]) * frac),
        Math.round(s.color[1] + (e.color[1] - s.color[1]) * frac),
        Math.round(s.color[2] + (e.color[2] - s.color[2]) * frac),
      ]
    }
  }
  return scale[0].color
}

function buildCellPalettes(cvtMesh: CVTMesh): {
  koppen: Map<number, [number, number, number]>
  plates: Map<number, [number, number, number]>
  boundaries: Map<number, [number, number, number]>
  currents: Map<number, [number, number, number]>
  biomes: Map<number, [number, number, number]>
  npp: Map<number, [number, number, number]>
  domesticable: Map<number, [number, number, number]>
} {
  const koppen = new Map<number, [number, number, number]>()
  const plates = new Map<number, [number, number, number]>()
  const boundaries = new Map<number, [number, number, number]>()
  const currents = new Map<number, [number, number, number]>()
  const biomes = new Map<number, [number, number, number]>()
  const npp = new Map<number, [number, number, number]>()
  const domesticable = new Map<number, [number, number, number]>()

  // NPP range for normalisation (Miami model bounded by [0, 3000] gC/m^2/yr)
  const NPP_MAX = 3000

  // Compute max ocean current speed for normalisation
  let maxSpeed = 0
  for (const cell of cvtMesh.cells) {
    const u = cell.ocean_current_east_m_s
    const v = cell.ocean_current_north_m_s
    if (u != null && v != null) {
      const s = Math.sqrt(u * u + v * v)
      if (s > maxSpeed) maxSpeed = s
    }
  }

  const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
  const palette = new Map<string, [number, number, number]>()
  plateIds.forEach((pid, idx) => {
    palette.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
  })

  for (const cell of cvtMesh.cells) {
    // Köppen thematic
    const kc = cell.koppen_class
    if (kc && KOPPEN_COLORS[kc]) {
      koppen.set(cell.id, hexRgb(KOPPEN_COLORS[kc]))
    } else if (cell.elevation < 0) {
      koppen.set(cell.id, hexRgb(KOPPEN_COLORS['Ocean']))
    }
    // Plate fill
    if (cell.plate_id) {
      const c = palette.get(cell.plate_id)
      if (c) plates.set(cell.id, c)
    }
    // Boundary/crust feature
    const bType = cell.boundary_type as BoundaryType | null
    if (bType) {
      boundaries.set(cell.id, BOUNDARY_COLORS[bType])
    } else if ((cell as any).hotspot_id) {
      boundaries.set(cell.id, HOTSPOT_COLOR)
    } else if ((cell as any).landform) {
      const lc = LANDFORM_COLORS[(cell as any).landform]
      if (lc) boundaries.set(cell.id, lc)
    } else {
      const crust = (cell as any).crust_type || 'oceanic'
      boundaries.set(cell.id, CRUST_INTERIOR_COLORS[crust] ?? CRUST_INTERIOR_COLORS.oceanic)
    }
    // Ocean current — direction-coloured (色相环 = 流向, 亮度 = 流速)
    const u = cell.ocean_current_east_m_s
    const v = cell.ocean_current_north_m_s
    // Fallback tint for ocean cells without current data
    if (cell.elevation < 0 && u == null && v == null) {
      currents.set(cell.id, [30, 100, 180])
    }
    if (u != null && v != null && maxSpeed > 1e-9) {
      const speed = Math.sqrt(u * u + v * v)
      const t = Math.min(speed / maxSpeed, 1.0)
      // Hue = flow direction  (0°=east=red, 90°=north=green, 180°=west=cyan, 270°=south=yellow)
      const hue = (Math.atan2(v, u) * (180 / Math.PI) + 360) % 360
      // Lightness ramps from dark (slow) to bright (fast)
      const L = 30 + 45 * Math.sqrt(t)  // 30 (slow) → 75 (fast)
      const S = 70  // saturation
      // HSL → RGB
      const h = hue / 60
      const chr = (1 - Math.abs(2 * L / 100 - 1)) * S / 100
      const x = chr * (1 - Math.abs((h % 2) - 1))
      const m = L / 100 - chr / 2
      let r1: number, g1: number, b1: number
      if (h < 1) { r1 = chr; g1 = x; b1 = 0 }
      else if (h < 2) { r1 = x; g1 = chr; b1 = 0 }
      else if (h < 3) { r1 = 0; g1 = chr; b1 = x }
      else if (h < 4) { r1 = 0; g1 = x; b1 = chr }
      else if (h < 5) { r1 = x; g1 = 0; b1 = chr }
      else { r1 = chr; g1 = 0; b1 = x }
      const r = Math.round((r1 + m) * 255)
      const g = Math.round((g1 + m) * 255)
      const b = Math.round((b1 + m) * 255)
      currents.set(cell.id, [r, g, b])
    }

    // Whittaker biome — categorical
    const bm: string | null = (cell as any).biome ?? null
    if (bm && WHITTAKER_COLORS[bm]) {
      biomes.set(cell.id, hexRgb(WHITTAKER_COLORS[bm]))
    }

    // NPP heatmap — continuous
    const nppVal: number | null = (cell as any).npp_gc_m2_yr ?? null
    if (nppVal != null) {
      npp.set(cell.id, sequentialColor(nppVal / NPP_MAX, NPP_SCALE))
    }

    // Civilization cradle — selective highlight
    const tags: string[] | undefined = (cell as any).domesticable_tags
    if (tags && tags.length > 0) {
      const hasHerb = tags.includes('large_herbivores_high')
      const hasCrop = tags.includes('staple_crops_high')
      if (hasHerb && hasCrop) {
        domesticable.set(cell.id, [255, 215, 0])
      } else if (hasHerb) {
        domesticable.set(cell.id, [255, 138, 101])
      } else if (hasCrop) {
        domesticable.set(cell.id, [129, 199, 132])
      }
    }
  }

  return { koppen, plates, boundaries, currents, biomes, npp, domesticable }
}

/**
 * Bake a per-cell layer at HALF resolution (alpha=0 where no cell colour).
 * Samples the full-res cell-id map at (2x, 2y) block origins.
 */
function bakeCellLayer(
  colors: Map<number, [number, number, number]>,
  width: number,
  height: number,
  cellIdMap: CellIdMap,
  flipHorizontal: boolean,
): Uint8Array {
  const w2 = Math.max(1, width >> 1)
  const h2 = Math.max(1, height >> 1)
  const buf = new Uint8Array(w2 * h2 * 4)  // alpha stays 0 where no colour
  for (let y = 0; y < h2; y++) {
    const srcRow = (2 * y) * width
    for (let x = 0; x < w2; x++) {
      const cid = cellIdMap[srcRow + 2 * x]
      if (cid == null) continue
      const c = colors.get(cid)
      if (!c) continue
      const pi = (y * w2 + x) * 4
      buf[pi] = c[0]; buf[pi + 1] = c[1]; buf[pi + 2] = c[2]; buf[pi + 3] = 255
    }
  }
  return flipBuffer(buf, w2, h2, flipHorizontal)
}

function bakeAll(inp: BakeInputs): LayerTextures {
  const { width, height, cvtMesh, cellIdMap, flipHorizontal } = inp
  const w2 = Math.max(1, width >> 1)
  const h2 = Math.max(1, height >> 1)

  const coastMask = (cvtMesh && cvtMesh.cells.length > 0 && cellIdMap)
    ? computeCoastMask(width, height, cvtMesh, cellIdMap, inp.seaLevel)
    : null
  const terrainBuf = bakeTerrainBase(inp, coastMask)
  const landseaBuf = bakeLandseaBase(inp, coastMask)

  // 1x1 transparent fallback when no cell data is available.
  const empty: Uint8Array = new Uint8Array([0, 0, 0, 0])
  let koppenBuf: Uint8Array = empty
  let platesBuf: Uint8Array = empty
  let boundariesBuf: Uint8Array = empty
  let currentsBuf: Uint8Array = empty
  let biomesBuf: Uint8Array = empty
  let nppBuf: Uint8Array = empty
  let domesticableBuf: Uint8Array = empty
  let kw = 1, kh = 1
  if (cvtMesh && cvtMesh.cells.length > 0 && cellIdMap) {
    const palettes = buildCellPalettes(cvtMesh)
    koppenBuf = bakeCellLayer(palettes.koppen, width, height, cellIdMap, flipHorizontal)
    platesBuf = bakeCellLayer(palettes.plates, width, height, cellIdMap, flipHorizontal)
    boundariesBuf = bakeCellLayer(palettes.boundaries, width, height, cellIdMap, flipHorizontal)
    biomesBuf = bakeCellLayer(palettes.biomes, width, height, cellIdMap, flipHorizontal)
    nppBuf = bakeCellLayer(palettes.npp, width, height, cellIdMap, flipHorizontal)
    domesticableBuf = bakeCellLayer(palettes.domesticable, width, height, cellIdMap, flipHorizontal)
    // currentsBuf: left transparent — ocean arrows rendered as SVG vectors
    kw = w2; kh = h2
  }

  return {
    terrain: makeTexture(terrainBuf, width, height, false),
    landsea: makeTexture(landseaBuf, width, height, false),
    koppen: makeTexture(koppenBuf, kw, kh, true),
    plates: makeTexture(platesBuf, kw, kh, true),
    boundaries: makeTexture(boundariesBuf, kw, kh, true),
    currents: makeTexture(currentsBuf, kw, kh, true),
    biomes: makeTexture(biomesBuf, kw, kh, true),
    npp: makeTexture(nppBuf, kw, kh, true),
    domesticable: makeTexture(domesticableBuf, kw, kh, true),
  }
}
