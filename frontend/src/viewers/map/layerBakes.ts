/**
 * layerBakes — CPU bake of per-layer textures (Step 3 of the layer refactor,
 * see docs/design/map-system.md).
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
 * Cell layers bake at FULL resolution: cells are ~76 km across (~8 px at
 * 4096-wide full res).  Previously half-res (~4 px/cell) was visually
 * lossless at normal zoom but produced visible pixel blocks at high zoom;
 * full-res doubles the pixel density per cell at ~4× GPU memory / bake time.
 */

import * as THREE from 'three'
import { mark } from '../../utils/perf'
import type { CVTMesh, BoundaryType } from './types'
import type { CellIdMap } from './useCellIdMap'
import type { MonthlyClimateData } from '../../api/monthlyClimate'
import {
  PLATE_COLORS,
  KOPPEN_COLORS,
  WHITTAKER_COLORS,
  SOIL_COLORS,
  NPP_SCALE,
  TEMPERATURE_SCALE,
  PRECIP_SCALE,
  HABITABILITY_SCALE,
  AGRICULTURE_SCALE,
  FLOW_SCALE,
  generateAdaptiveTerrainScale,
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

/** Closed inland-lake colour — light cyan, distinct from the deep ocean blue. */
const LAKE_COLOR: [number, number, number] = hexRgb('#67e6dc')

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface LayerTextures {
  /** Hypsometric tint per-cell (thematic, half-res). Default map mode. */
  terrainThematic: THREE.DataTexture
  /** terrainThematic with coastlines baked in — used by the 3D globe so it
   *  doesn't need the FBO composite pass just for coastline overlay. */
  terrainWithCoastlines: THREE.DataTexture
  /** Binary land/sea per-cell (thematic, half-res). */
  landseaThematic: THREE.DataTexture
  /** Per-cell thematic colour (Köppen), alpha=0 where no data. Half res. */
  koppen: THREE.DataTexture
  /** Per-cell fill colour (plates), alpha=0 where no data. Half res. */
  plates: THREE.DataTexture
  /** Per-cell feature colour (boundaries/crust), alpha=0 where no data. Half res. */
  boundaries: THREE.DataTexture
  /** Coastline outline (feature, half-res). Always-on by default. */
  coastlines: THREE.DataTexture
  /** Whittaker biome thematic (per-cell categorical). Half res. */
  biomes: THREE.DataTexture
  /** NPP heatmap thematic (per-cell continuous). Half res. */
  npp: THREE.DataTexture
  /** Civilization cradle thematic (per-cell highlight). Half res. */
  domesticable: THREE.DataTexture
  /** Habitable coast thematic (宜居海岸, per-cell boolean). Half res. */
  habitable: THREE.DataTexture
  /** Agricultural core thematic (农业核心区, per-cell boolean). Half res. */
  agriculture: THREE.DataTexture
  /** USDA soil order thematic (per-cell categorical). Half res. */
  soil: THREE.DataTexture
  /** Biogeographic province thematic (per-cell categorical). Half res. */
  provinces: THREE.DataTexture
  /** Annual mean temperature thematic (per-cell continuous, diverging). Half res. */
  temperature: THREE.DataTexture
  /** Annual precipitation thematic (per-cell continuous, log-scaled). Half res. */
  precipitation: THREE.DataTexture
  /** Drainage / flow accumulation thematic (per-cell continuous, log-scaled). Half res. */
  flow: THREE.DataTexture
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
    t.terrainThematic.dispose(); t.landseaThematic.dispose(); t.koppen.dispose()
    t.plates.dispose(); t.boundaries.dispose(); t.coastlines.dispose()
    t.biomes.dispose(); t.npp.dispose(); t.domesticable.dispose()
    t.habitable.dispose(); t.agriculture.dispose()
    t.soil.dispose(); t.provinces.dispose()
    t.temperature.dispose(); t.precipitation.dispose()
    t.flow.dispose()
    t.terrainWithCoastlines.dispose()
  }

  mark('layer-bake-start')
  const textures = bakeAll(inputs)
  mark('layer-bake-end')
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

interface MakeTextureOpts {
  /** Minification filter. Default NearestFilter — no mipmaps, crisp when zoomed out. */
  nearestMin?: boolean
  /** Magnification filter. Default LinearFilter — smooth interpolation when zoomed in,
   *  eliminating the "pixel block" look at high zoom.  Set true only for categorical
   *  data (cell boundaries, plates) where crisp edges are more important. */
  nearestMag?: boolean
}

function makeTexture(
  buf: Uint8Array, width: number, height: number, opts?: MakeTextureOpts,
): THREE.DataTexture {
  const tex = new THREE.DataTexture(buf as unknown as BufferSource, width, height, THREE.RGBAFormat)
  tex.wrapS = THREE.ClampToEdgeWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping
  tex.minFilter = opts?.nearestMin === false ? THREE.LinearFilter : THREE.NearestFilter
  tex.magFilter = opts?.nearestMag ? THREE.NearestFilter : THREE.LinearFilter
  tex.needsUpdate = true
  return tex
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

function buildCellPalettes(
  cvtMesh: CVTMesh,
  elevMinM: number,
  elevMaxM: number,
  seaLevel: number,
  waterDepthFactor: number,
): {
  terrainThematic: Map<number, [number, number, number]>
  landseaThematic: Map<number, [number, number, number]>
  koppen: Map<number, [number, number, number]>
  plates: Map<number, [number, number, number]>
  boundaries: Map<number, [number, number, number]>
  coastlines: Map<number, [number, number, number]>
  biomes: Map<number, [number, number, number]>
  npp: Map<number, [number, number, number]>
  domesticable: Map<number, [number, number, number]>
  habitable: Map<number, [number, number, number]>
  agriculture: Map<number, [number, number, number]>
  soil: Map<number, [number, number, number]>
  provinces: Map<number, [number, number, number]>
  temperature: Map<number, [number, number, number]>
  precipitation: Map<number, [number, number, number]>
  flow: Map<number, [number, number, number]>
} {
  const terrainThematic = new Map<number, [number, number, number]>()
  const landseaThematic = new Map<number, [number, number, number]>()
  const koppen = new Map<number, [number, number, number]>()
  const plates = new Map<number, [number, number, number]>()
  const boundaries = new Map<number, [number, number, number]>()
  const coastlines = new Map<number, [number, number, number]>()
  const biomes = new Map<number, [number, number, number]>()
  const npp = new Map<number, [number, number, number]>()
  const domesticable = new Map<number, [number, number, number]>()
  const habitable = new Map<number, [number, number, number]>()
  const agriculture = new Map<number, [number, number, number]>()
  const soil = new Map<number, [number, number, number]>()
  const provinces = new Map<number, [number, number, number]>()
  const temperature = new Map<number, [number, number, number]>()
  const precipitation = new Map<number, [number, number, number]>()
  const flow = new Map<number, [number, number, number]>()

  // NPP range for normalisation.  Dynamic rather than the fixed Miami 3000 gC
  // ceiling — a red dwarf's PAR suppresses NPP far below 3000 (nacrea land NPP
  // peaks ~1200 gC), and a fixed ceiling washes the whole heatmap out.
  let nppMax = 0
  for (const cell of cvtMesh.cells) {
    const v = cell.npp_gc_m2_yr
    if (v != null && v > nppMax) nppMax = v
  }
  const NPP_MAX = nppMax > 0 ? nppMax : 3000

  // Flow accumulation range — dynamic max (like NPP): the largest basin maps to
  // the brightest stop.  Flow is resolution- and world-size-dependent, so a
  // fixed ceiling would either clip or wash out the drainage structure.
  let flowMax = 0
  for (const cell of cvtMesh.cells) {
    const v = cell.flow_accumulation
    if (v != null && v > flowMax) flowMax = v
  }
  const FLOW_MAX = flowMax > 0 ? flowMax : 1e6

  // Build adaptive hypsometric LUT (NOAA ETOPO1 ocean + ESRI Natural Earth land).
  const terrainLut = generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel)
  const lutSize = terrainLut.length / 4
  const elevRange = elevMaxM - elevMinM || 1
  function terrainColor(elevM: number): [number, number, number] {
    const idx = Math.round(((elevM - elevMinM) / elevRange) * (lutSize - 1))
    const clampedIdx = Math.max(0, Math.min(lutSize - 1, idx))
    const i = clampedIdx * 4
    let r = terrainLut[i], g = terrainLut[i + 1], b = terrainLut[i + 2]
    // Water depth darkening — matches pre-refactor bakeTerrainBase behaviour.
    if (elevM < seaLevel) {
      const depthFrac = Math.min(1, (seaLevel - elevM) / Math.max(1, seaLevel - elevMinM))
      const f = 1 - waterDepthFactor * depthFrac
      r = Math.round(r * f); g = Math.round(g * f); b = Math.round(b * f)
    }
    return [r, g, b]
  }

  const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
  const palette = new Map<string, [number, number, number]>()
  plateIds.forEach((pid, idx) => {
    palette.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
  })

  const provinceIds = [...new Set(cvtMesh.cells.map((c) => c.biogeographic_province).filter(Boolean))]
  const provincePalette = new Map<string, [number, number, number]>()
  provinceIds.forEach((pid, idx) => {
    provincePalette.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
  })

  for (const cell of cvtMesh.cells) {
    // Terrain thematic — hypsometric tint per cell
    terrainThematic.set(cell.id, terrainColor(cell.elevation))
    // Landsea thematic — binary
    landseaThematic.set(cell.id, cell.elevation >= seaLevel ? [76, 175, 80] : [21, 101, 192])

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
    } else if (cell.hotspot_id) {
      boundaries.set(cell.id, HOTSPOT_COLOR)
    } else if (cell.landform) {
      const lc = LANDFORM_COLORS[cell.landform]
      if (lc) boundaries.set(cell.id, lc)
    } else {
      const crust = cell.crust_type || 'oceanic'
      boundaries.set(cell.id, CRUST_INTERIOR_COLORS[crust] ?? CRUST_INTERIOR_COLORS.oceanic)
    }
    // Whittaker biome — categorical
    const bm: string | null = cell.biome ?? null
    if (bm && WHITTAKER_COLORS[bm]) {
      biomes.set(cell.id, hexRgb(WHITTAKER_COLORS[bm]))
    }

    // NPP heatmap — continuous
    const nppVal: number | null | undefined = cell.npp_gc_m2_yr
    if (nppVal != null) {
      npp.set(cell.id, sequentialColor(nppVal / NPP_MAX, NPP_SCALE))
    }

    // Civilization cradle — all land gets a neutral dark fill so the
    // base terrain doesn't bleed through where highlight is absent.
    if (cell.elevation >= 0) {
      const tags: string[] | undefined = cell.domesticable_tags
      if (tags && tags.length > 0) {
        const hasHerb = tags.includes('large_herbivores_high')
        const hasCrop = tags.includes('staple_crops_high')
        if (hasHerb && hasCrop) {
          domesticable.set(cell.id, [255, 215, 0])       // gold: both
        } else if (hasHerb) {
          domesticable.set(cell.id, [255, 138, 101])      // orange: pastoral
        } else if (hasCrop) {
          domesticable.set(cell.id, [129, 199, 132])      // green: agricultural
        } else {
          domesticable.set(cell.id, [45, 48, 55])         // neutral dark: low potential
        }
      } else {
        domesticable.set(cell.id, [45, 48, 55])           // neutral dark: no tags
      }
    }

    // Habitability grade (宜居等级) — progressive 0–100 ramp, land only.
    const habScore: number | null | undefined = cell.habitability_score
    if (habScore != null && cell.elevation >= 0) {
      habitable.set(cell.id, sequentialColor(habScore / 100, HABITABILITY_SCALE))
    }

    // Agriculture grade (农业等级) — progressive 0–100 ramp, land only
    // (the hard zero below the tree-line renders as the ramp's dark stop).
    const agriScore: number | null | undefined = cell.agriculture_score
    if (agriScore != null && cell.elevation >= 0) {
      agriculture.set(cell.id, sequentialColor(agriScore / 100, AGRICULTURE_SCALE))
    }

    // USDA soil order — categorical
    const soilType: string | null = cell.soil_type ?? null
    if (soilType && SOIL_COLORS[soilType]) {
      soil.set(cell.id, hexRgb(SOIL_COLORS[soilType]))
    }

    // Biogeographic province — categorical (realm.province id)
    const provinceId: string | null = cell.biogeographic_province ?? null
    if (provinceId) {
      const c = provincePalette.get(provinceId)
      if (c) provinces.set(cell.id, c)
    }

    // Annual mean temperature — continuous diverging, land only (ocean stays
    // transparent so the base terrain shows through, matching npp/biomes).
    const tC: number | null | undefined = cell.temperature_C
    if (tC != null && cell.elevation >= 0) {
      // Fixed −40…+40 °C physical range → 0 °C (freezing) at the centre stop.
      temperature.set(cell.id, sequentialColor((tC + 40) / 80, TEMPERATURE_SCALE))
    }

    // Annual precipitation — continuous, log-normalised (0…30000 mm), land only.
    // Log scale because precipitation spans five orders of magnitude; a linear
    // ramp would collapse ~95% of cells into the low end.
    const pMm: number | null | undefined = cell.precipitation_mm
    if (pMm != null && cell.elevation >= 0) {
      precipitation.set(
        cell.id,
        sequentialColor(Math.log10(pMm + 1) / Math.log10(30001), PRECIP_SCALE),
      )
    }

    // Drainage / flow accumulation — continuous, log-normalised, land only.
    // Log scale because catchment area spans ~3 orders of magnitude (single-cell
    // ~2600 km² @200k up to multi-million-km² continental basins).
    const fAcc: number | null | undefined = cell.flow_accumulation
    if (fAcc != null && fAcc > 0 && cell.elevation >= 0) {
      flow.set(
        cell.id,
        sequentialColor(Math.log10(fAcc + 1) / Math.log10(FLOW_MAX + 1), FLOW_SCALE),
      )
    }
    // Closed inland lakes (endorheic basins below sea level) get a distinct
    // colour so they read as lakes, not ocean, in the drainage layer.
    if (cell.is_lake) {
      flow.set(cell.id, LAKE_COLOR)
    }
  }

  return { terrainThematic, landseaThematic, koppen, plates, boundaries,
           coastlines, biomes, npp, domesticable, habitable, agriculture,
           soil, provinces, temperature, precipitation, flow }
}

/**
 * Coastline mask at FULL resolution — pixel-level detection (same algorithm
 * as the original computeCoastMask).  Two adjacent pixels that belong to
 * DIFFERENT cells where one is land and the other ocean → both pixels are
 * coastline.
 */
function bakeCoastlineMask(
  width: number,
  height: number,
  cvtMesh: CVTMesh,
  cellIdMap: CellIdMap,
  seaLevel: number,
  flipHorizontal: boolean,
): Uint8Array {
  const buf = new Uint8Array(width * height * 4)

  const cellLand = new Map<number, boolean>()
  for (const cell of cvtMesh.cells) {
    cellLand.set(cell.id, cell.elevation >= seaLevel)
  }

  for (let y = 0; y < height; y++) {
    const srcRow = y * width
    for (let x = 0; x < width; x++) {
      const cid = cellIdMap[srcRow + x]
      if (cid == null) continue
      const isLand = cellLand.get(cid)
      if (isLand == null) continue

      // Right neighbour
      if (x + 1 < width) {
        const nCid = cellIdMap[srcRow + (x + 1)]
        if (nCid != null && nCid !== cid) {
          const nLand = cellLand.get(nCid)
          if (nLand != null && isLand !== nLand) {
            const pi = (y * width + x) * 4
            buf[pi] = 20; buf[pi + 1] = 20; buf[pi + 2] = 20; buf[pi + 3] = 255
            const ni = (y * width + x + 1) * 4
            buf[ni] = 20; buf[ni + 1] = 20; buf[ni + 2] = 20; buf[ni + 3] = 255
          }
        }
      }
      // Bottom neighbour
      if (y + 1 < height) {
        const nextRow = (y + 1) * width
        const nCid = cellIdMap[nextRow + x]
        if (nCid != null && nCid !== cid) {
          const nLand = cellLand.get(nCid)
          if (nLand != null && isLand !== nLand) {
            const pi = (y * width + x) * 4
            buf[pi] = 20; buf[pi + 1] = 20; buf[pi + 2] = 20; buf[pi + 3] = 255
            const ni = ((y + 1) * width + x) * 4
            buf[ni] = 20; buf[ni + 1] = 20; buf[ni + 2] = 20; buf[ni + 3] = 255
          }
        }
      }
    }
  }

  return flipBuffer(buf, width, height, flipHorizontal)
}

/**
 * Bake a per-cell layer at FULL resolution (alpha=0 where no cell colour).
 * Samples every pixel of the full-res cell-id map.
 */
function bakeCellLayer(
  colors: Map<number, [number, number, number]>,
  width: number,
  height: number,
  cellIdMap: CellIdMap,
  flipHorizontal: boolean,
): Uint8Array {
  const buf = new Uint8Array(width * height * 4)
  for (let y = 0; y < height; y++) {
    const srcRow = y * width
    for (let x = 0; x < width; x++) {
      const cid = cellIdMap[srcRow + x]
      if (cid == null) continue
      const c = colors.get(cid)
      if (!c) continue
      const pi = (y * width + x) * 4
      buf[pi] = c[0]; buf[pi + 1] = c[1]; buf[pi + 2] = c[2]; buf[pi + 3] = 255
    }
  }
  return flipBuffer(buf, width, height, flipHorizontal)
}

/**
 * Bake a monthly temperature/precipitation layer (Phase 4 monthly display).
 *
 * Reads the per-cell monthly value (cell index `i`, month `m` → `i·months + m`)
 * from the backend's compact MessagePack, maps it through the *same* colour
 * scale as the annual layer, and bakes it to a texture via the existing
 * cell-ID map.  Land only (ocean stays transparent).
 */
export function bakeMonthlyLayer(
  monthly: MonthlyClimateData,
  month: number,
  field: 'temperature' | 'precipitation',
  cvtMesh: CVTMesh,
  cellIdMap: CellIdMap,
  width: number,
  height: number,
  flipHorizontal: boolean,
): THREE.DataTexture {
  const { months, tMonthly, pMonthly } = monthly
  const arr = field === 'temperature' ? tMonthly : pMonthly
  const colors = new Map<number, [number, number, number]>()

  for (let i = 0; i < cvtMesh.cells.length; i++) {
    const cell = cvtMesh.cells[i]
    if (cell.elevation < 0) continue
    const v = arr[i * months + month]
    const color =
      field === 'temperature'
        ? sequentialColor((v + 40) / 80, TEMPERATURE_SCALE)
        : sequentialColor(Math.log10(Math.max(v, 0) + 1) / Math.log10(30001), PRECIP_SCALE)
    colors.set(cell.id, color)
  }

  const buf = bakeCellLayer(colors, width, height, cellIdMap, flipHorizontal)
  return makeTexture(buf, width, height)
}

function bakeAll(inp: BakeInputs): LayerTextures {
  const { width, height, cvtMesh, cellIdMap, flipHorizontal } = inp

  // 1x1 transparent fallback
  const empty: Uint8Array = new Uint8Array([0, 0, 0, 0])
  let terrainThemBuf: Uint8Array = empty
  let landseaThemBuf: Uint8Array = empty
  let koppenBuf: Uint8Array = empty
  let platesBuf: Uint8Array = empty
  let boundariesBuf: Uint8Array = empty
  let coastlinesBuf: Uint8Array = empty
  let biomesBuf: Uint8Array = empty
  let nppBuf: Uint8Array = empty
  let domesticableBuf: Uint8Array = empty
  let habitableBuf: Uint8Array = empty
  let agricultureBuf: Uint8Array = empty
  let soilBuf: Uint8Array = empty
  let provincesBuf: Uint8Array = empty
  let temperatureBuf: Uint8Array = empty
  let precipitationBuf: Uint8Array = empty
  let flowBuf: Uint8Array = empty
  let kw = 1, kh = 1
  if (cvtMesh && cvtMesh.cells.length > 0 && cellIdMap) {
    const palettes = buildCellPalettes(cvtMesh, inp.elevMinM, inp.elevMaxM, inp.seaLevel, inp.waterDepthFactor)
    terrainThemBuf = bakeCellLayer(palettes.terrainThematic, width, height, cellIdMap, flipHorizontal)
    landseaThemBuf = bakeCellLayer(palettes.landseaThematic, width, height, cellIdMap, flipHorizontal)
    koppenBuf = bakeCellLayer(palettes.koppen, width, height, cellIdMap, flipHorizontal)
    platesBuf = bakeCellLayer(palettes.plates, width, height, cellIdMap, flipHorizontal)
    boundariesBuf = bakeCellLayer(palettes.boundaries, width, height, cellIdMap, flipHorizontal)
    coastlinesBuf = bakeCoastlineMask(width, height, cvtMesh, cellIdMap, inp.seaLevel, flipHorizontal)
    biomesBuf = bakeCellLayer(palettes.biomes, width, height, cellIdMap, flipHorizontal)
    nppBuf = bakeCellLayer(palettes.npp, width, height, cellIdMap, flipHorizontal)
    domesticableBuf = bakeCellLayer(palettes.domesticable, width, height, cellIdMap, flipHorizontal)
    habitableBuf = bakeCellLayer(palettes.habitable, width, height, cellIdMap, flipHorizontal)
    agricultureBuf = bakeCellLayer(palettes.agriculture, width, height, cellIdMap, flipHorizontal)
    soilBuf = bakeCellLayer(palettes.soil, width, height, cellIdMap, flipHorizontal)
    provincesBuf = bakeCellLayer(palettes.provinces, width, height, cellIdMap, flipHorizontal)
    temperatureBuf = bakeCellLayer(palettes.temperature, width, height, cellIdMap, flipHorizontal)
    precipitationBuf = bakeCellLayer(palettes.precipitation, width, height, cellIdMap, flipHorizontal)
    flowBuf = bakeCellLayer(palettes.flow, width, height, cellIdMap, flipHorizontal)
    kw = width; kh = height
  }

  // Merge terrain + feature layers → self-contained textures for the 3D globe
  // so it doesn't need the FBO composite pass (which has a known color-space
  // round-trip issue with MeshStandardMaterial PBR pipeline on some GPUs).

  // Helper: blend a feature layer (alpha=255 where present, 0 elsewhere) over
  // the terrain at the given opacity [0,1].
  function mergeFeature(
    base: Uint8Array,
    feature: Uint8Array,
    opacity: number,
  ): Uint8Array {
    const out = new Uint8Array(base.length)
    for (let i = 0; i < base.length; i += 4) {
      const fa = (feature[i + 3] / 255) * opacity
      if (fa > 0.001) {
        out[i] = Math.round(base[i] * (1 - fa) + feature[i] * fa)
        out[i + 1] = Math.round(base[i + 1] * (1 - fa) + feature[i + 1] * fa)
        out[i + 2] = Math.round(base[i + 2] * (1 - fa) + feature[i + 2] * fa)
      } else {
        out[i] = base[i]
        out[i + 1] = base[i + 1]
        out[i + 2] = base[i + 2]
      }
      out[i + 3] = 255
    }
    return out
  }

  const terrainWithCoastBuf = mergeFeature(terrainThemBuf, coastlinesBuf, 1.0)

  // Texture filter policy:
  // - Continuous data (terrain, NPP): magFilter=LinearFilter → smooth when zoomed in
  // - Categorical data (plates, Köppen, biomes, boundaries, coastlines,
  //   domesticable): magFilter=NearestFilter → crisp cell edges
  // - All textures: minFilter=NearestFilter (no mipmaps needed; crisp when zoomed out)
  return {
    terrainThematic: makeTexture(terrainThemBuf, kw, kh),
    terrainWithCoastlines: makeTexture(terrainWithCoastBuf, kw, kh),
    landseaThematic: makeTexture(landseaThemBuf, kw, kh, { nearestMag: true }),
    koppen: makeTexture(koppenBuf, kw, kh, { nearestMag: true }),
    plates: makeTexture(platesBuf, kw, kh, { nearestMag: true }),
    boundaries: makeTexture(boundariesBuf, kw, kh, { nearestMag: true }),
    coastlines: makeTexture(coastlinesBuf, kw, kh, { nearestMag: true }),
    biomes: makeTexture(biomesBuf, kw, kh, { nearestMag: true }),
    npp: makeTexture(nppBuf, kw, kh),
    domesticable: makeTexture(domesticableBuf, kw, kh, { nearestMag: true }),
    habitable: makeTexture(habitableBuf, kw, kh, { nearestMag: true }),
    agriculture: makeTexture(agricultureBuf, kw, kh, { nearestMag: true }),
    soil: makeTexture(soilBuf, kw, kh, { nearestMag: true }),
    provinces: makeTexture(provincesBuf, kw, kh, { nearestMag: true }),
    temperature: makeTexture(temperatureBuf, kw, kh),
    precipitation: makeTexture(precipitationBuf, kw, kh),
    flow: makeTexture(flowBuf, kw, kh),
  }
}
