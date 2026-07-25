/**
 * useGPUTerrain — GPU-accelerated terrain rendering.
 *
 * All color modes (terrain, landsea, plates, boundaries) pre-compute the
 * FULL RGBA colour buffer on the CPU, then upload as a single DataTexture.
 * The fragment shader simply displays the texture — guaranteed no black screen.
 *
 * Performance:
 * - terrain/landsea: ~200ms (LUT + hillshading per pixel)
 * - plates/boundaries: ~100ms (cellIdMap palette lookup per pixel)
 * - Pan/zoom: <1ms (just re-display the texture)
 */

import { useMemo } from 'react'
import * as THREE from 'three'
import type { ColorMode } from './TerrainPlane'
import type { CVTMesh, BoundaryType } from './types'
import type { CellIdMap } from './useCellIdMap'
import {
  generateAdaptiveTerrainScale,
  PLATE_COLORS,
} from './utils/colorScales'

// ---------------------------------------------------------------------------
// Helpers
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

// ---------------------------------------------------------------------------
// Minimal shaders — just display the pre-computed texture
// ---------------------------------------------------------------------------

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const fragmentShader = /* glsl */ `
precision highp float;
uniform sampler2D u_colorMap;
varying vec2 vUv;
void main() {
  gl_FragColor = texture2D(u_colorMap, vUv);
}
`

// ---------------------------------------------------------------------------
// Module-level cache — survives component unmount/remount (React Router nav)
// ---------------------------------------------------------------------------

interface CacheEntry {
  // Cache key fields
  elevation: Float32Array
  width: number
  height: number
  layers: Record<ColorMode, number>
  cellIdMap: CellIdMap | null | undefined
  cvtMesh: CVTMesh | null | undefined
  hoveredCell: number | null | undefined
  selectedCells: Set<number> | undefined
  // Cached result
  material: THREE.ShaderMaterial
}

let lastCache: CacheEntry | null = null

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseGPUTerrainOptions {
  elevation: Float32Array | null
  width: number
  height: number
  seaLevel: number
  elevMinM?: number
  elevMaxM?: number
  /** Per-layer opacity: { terrain: 0-1, landsea: 0-1, plates: 0-1, boundaries: 0-1 } */
  layers?: Record<ColorMode, number>
  hillshadeStrength?: number
  waterDepthFactor?: number
  cvtMesh?: CVTMesh | null
  cellIdMap?: CellIdMap | null
  /** Flip texture horizontally (needed for SphereGeometry; set false for PlaneGeometry). */
  flipHorizontal?: boolean
  /** Cell IDs to highlight in blue (hover) or yellow (selected). */
  hoveredCell?: number | null
  selectedCells?: Set<number>
}

export default function useGPUTerrain({
  elevation,
  width,
  height,
  seaLevel,
  elevMinM = -11000,
  elevMaxM = 9000,
  layers = { terrain: 1, landsea: 0, plates: 0, boundaries: 0 },
  hillshadeStrength = 0,
  waterDepthFactor = 0.5,
  cvtMesh,
  cellIdMap,
  flipHorizontal = true,
  hoveredCell = null,
  selectedCells,
}: UseGPUTerrainOptions): THREE.ShaderMaterial | null {
  return useMemo(() => {
    if (!elevation || width <= 0 || height <= 0) return null

    // Check module-level cache: if inputs match, reuse material instantly
    if (
      lastCache &&
      lastCache.elevation === elevation &&
      lastCache.width === width &&
      lastCache.height === height &&
      lastCache.layers.terrain === layers.terrain &&
      lastCache.layers.landsea === layers.landsea &&
      lastCache.layers.plates === layers.plates &&
      lastCache.layers.boundaries === layers.boundaries &&
      lastCache.cellIdMap === cellIdMap &&
      lastCache.cvtMesh === cvtMesh &&
      lastCache.hoveredCell === hoveredCell &&
      lastCache.selectedCells === selectedCells
    ) {
      return lastCache.material
    }

    const totalPixels = width * height
    const buf = new Uint8Array(totalPixels * 4)

    // Compute normalised sea level from absolute metres
    const range = elevMaxM - elevMinM || 1
    const normSeaLevel = (seaLevel - elevMinM) / range

    // --- Step 0: Cell-level land/sea map ---
    const activeModes = (Object.keys(layers) as ColorMode[]).filter((k) => layers[k] > 0)
    const maxCellId = cvtMesh?.cells.length ?? 0
    const cellLand = new Uint8Array(maxCellId)
    if (cvtMesh && (activeModes.some(m => m === 'landsea' || m === 'boundaries' || m === 'terrain'))) {
      for (const cell of cvtMesh.cells) {
        cellLand[cell.id] = cell.elevation >= seaLevel ? 1 : 0
      }
    }

    // --- Step 0b: Coastline FIRST (fast ~12ms) so it appears before terrain fills ---
    const coastlineSet = new Uint8Array(totalPixels)  // 1 = coastline pixel
    const debugCells = new Set([45391, 45768, 45912])
    if (activeModes.some(m => m === 'terrain') && cellIdMap && cellLand.length > 0) {
      console.time('coastline')
      const COAST_COLOR: [number, number, number] = [20, 20, 20]
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const i = y * width + x
          const isLandPx = elevation[i] >= normSeaLevel
          const rx = x + 1
          if (rx < width) {
            const ni = y * width + rx
            if (isLandPx !== (elevation[ni] >= normSeaLevel)) {
              const cid = cellIdMap[i]; const nCid = cellIdMap[ni]
              const draw = (cid != null && nCid != null && cid !== nCid)
                ? (cellLand[cid] !== cellLand[nCid])
                : true
              if (debugCells.has(cid!) || debugCells.has(nCid!)) {
                console.log(`coast: cells ${cid}(${cellLand[cid!]?'L':'O'})↔${nCid}(${cellLand[nCid!]?'L':'O'}) elev=${elevation[i].toFixed(3)}↔${elevation[ni].toFixed(3)} sl=${normSeaLevel.toFixed(3)} draw=${draw}`)
              }
              if (draw) {
                coastlineSet[i] = 1; coastlineSet[ni] = 1
                const pi = i * 4; const npi = ni * 4
                buf[pi]=COAST_COLOR[0]; buf[pi+1]=COAST_COLOR[1]; buf[pi+2]=COAST_COLOR[2]; buf[pi+3]=255
                buf[npi]=COAST_COLOR[0]; buf[npi+1]=COAST_COLOR[1]; buf[npi+2]=COAST_COLOR[2]; buf[npi+3]=255
              }
            }
          }
          const by = y + 1
          if (by < height) {
            const ni = by * width + x
            if (isLandPx !== (elevation[ni] >= normSeaLevel)) {
              const cid = cellIdMap[i]; const nCid = cellIdMap[ni]
              const draw = (cid != null && nCid != null && cid !== nCid)
                ? (cellLand[cid] !== cellLand[nCid])
                : true
              if (debugCells.has(cid!) || debugCells.has(nCid!)) {
                console.log(`coast: cells ${cid}(${cellLand[cid!]?'L':'O'})↔${nCid}(${cellLand[nCid!]?'L':'O'}) elev=${elevation[i].toFixed(3)}↔${elevation[ni].toFixed(3)} sl=${normSeaLevel.toFixed(3)} draw=${draw}`)
              }
              if (draw) {
                coastlineSet[i] = 1; coastlineSet[ni] = 1
                const pi = i * 4; const npi = ni * 4
                buf[pi]=COAST_COLOR[0]; buf[pi+1]=COAST_COLOR[1]; buf[pi+2]=COAST_COLOR[2]; buf[pi+3]=255
                buf[npi]=COAST_COLOR[0]; buf[npi+1]=COAST_COLOR[1]; buf[npi+2]=COAST_COLOR[2]; buf[npi+3]=255
              }
            }
          }
        }
      }
    }

    // --- Step 1: Precompute LUTs for all active layers ---
    const terrainLut = activeModes.includes('terrain')
      ? generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel) : null
    const landseaLut = activeModes.includes('landsea')
      ? (() => {
          const l = new Uint8Array(1024 * 3)
          const cutoff = Math.round(normSeaLevel * 1023)
          for (let i = 0; i < 1024; i++) {
            const c = i <= cutoff ? [30, 60, 120] : [80, 140, 60]
            l[i*3]=c[0]; l[i*3+1]=c[1]; l[i*3+2]=c[2]
          }
          return l
        })() : null

    // --- Step 2: Build cell colour palettes ---
    const platesColor = new Map<number, [number, number, number]>()
    const boundariesColor = new Map<number, [number, number, number]>()
    if (cvtMesh && (activeModes.includes('plates') || activeModes.includes('boundaries'))) {
      if (activeModes.includes('plates')) {
        const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
        const palette = new Map<string, [number, number, number]>()
        plateIds.forEach((pid, idx) => {
          palette.set(pid!, hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length]))
        })
        for (const cell of cvtMesh.cells) {
          if (cell.plate_id) {
            const c = palette.get(cell.plate_id)
            if (c) platesColor.set(cell.id, c)
          }
        }
      }
      if (activeModes.includes('boundaries')) {
        for (const cell of cvtMesh.cells) {
          const bType = cell.boundary_type as BoundaryType | null
          if (bType) {
            boundariesColor.set(cell.id, BOUNDARY_COLORS[bType])
          } else if ((cell as any).hotspot_id) {
            // Hotspot chain — magenta (overrides crust colour)
            boundariesColor.set(cell.id, HOTSPOT_COLOR)
          } else if ((cell as any).landform) {
            // Interior landform — orogeny (brown) or rift (teal)
            const lc = LANDFORM_COLORS[(cell as any).landform]
            if (lc) boundariesColor.set(cell.id, lc)
          } else {
            // Interior cell — colour by crust type
            const crust = (cell as any).crust_type || 'oceanic'
            const cc = CRUST_INTERIOR_COLORS[crust] ?? CRUST_INTERIOR_COLORS.oceanic
            boundariesColor.set(cell.id, cc)
          }
        }
      }
    }

    // --- Step 3: Composite all active layers per pixel ---
    const hasLayers = layers.terrain > 0 || layers.landsea > 0 || layers.plates > 0 || layers.boundaries > 0
    const justTerrain = layers.terrain > 0 && !(layers.landsea > 0 || layers.plates > 0 || layers.boundaries > 0)

    if (hasLayers) {
      for (let i = 0; i < totalPixels; i++) {
        const elev = elevation[i]
        const pi = i * 4

        if (justTerrain && terrainLut) {
          // Skip coastline pixels (already rendered in fast first pass)
          if (coastlineSet[i]) { buf[pi+3] = 255; continue }
          // Fast path: terrain-only (most common case) — direct copy
          const idx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
          buf[pi]   = terrainLut[idx * 4]
          buf[pi+1] = terrainLut[idx * 4 + 1]
          buf[pi+2] = terrainLut[idx * 4 + 2]
          if (elev < normSeaLevel) {
            const depth = (normSeaLevel - elev) / Math.max(normSeaLevel, 0.001)
            const f = 1 - waterDepthFactor * depth
            buf[pi]   = Math.round(buf[pi]   * f)
            buf[pi+1] = Math.round(buf[pi+1] * f)
            buf[pi+2] = Math.round(buf[pi+2] * f)
          }
          buf[pi+3] = 255
        } else {
          // General path: alpha-blend multiple layers (rare)
          if (coastlineSet[i]) { buf[pi+3] = 255; continue }
          let r = 0, g = 0, b = 0
          const cellId = cellIdMap?.[i]

          if (terrainLut) {
            const idx = Math.min(1023, Math.max(0, Math.round(elev * 1023)))
            let tr = terrainLut[idx*4], tg = terrainLut[idx*4+1], tb = terrainLut[idx*4+2]
            if (elev < normSeaLevel) {
              const depth = (normSeaLevel - elev) / Math.max(normSeaLevel, 0.001)
              const f = 1 - waterDepthFactor * depth
              tr = Math.round(tr*f); tg = Math.round(tg*f); tb = Math.round(tb*f)
            }
            const a = layers.terrain
            r = Math.round(tr * a); g = Math.round(tg * a); b = Math.round(tb * a)
          }

          if (landseaLut) {
            const cid = cellIdMap?.[i]
            const isLand = cid != null ? (cellLand[cid] === 1) : (elev >= normSeaLevel)
            const [lr, lg, lb] = isLand ? [80, 140, 60] : [30, 60, 120]
            const a = layers.landsea, ia = 1 - a
            r = Math.round(r * ia + lr * a); g = Math.round(g * ia + lg * a); b = Math.round(b * ia + lb * a)
          }

          if (layers.plates > 0 && cellId != null) {
            const pc = platesColor.get(cellId)
            if (pc) {
              const a = layers.plates, ia = 1 - a
              r = Math.round(r * ia + pc[0] * a); g = Math.round(g * ia + pc[1] * a); b = Math.round(b * ia + pc[2] * a)
            }
          }

          if (layers.boundaries > 0 && cellId != null) {
            const bc = boundariesColor.get(cellId)
            if (bc) {
              const a = layers.boundaries, ia = 1 - a
              r = Math.round(r * ia + bc[0] * a); g = Math.round(g * ia + bc[1] * a); b = Math.round(b * ia + bc[2] * a)
            }
          }

          buf[pi] = r; buf[pi+1] = g; buf[pi+2] = b; buf[pi+3] = 255
        }
      }
    }

    // --- Highlight overlay: blend highlight colour for hovered/selected cells ---
    if (cellIdMap && (hoveredCell != null || (selectedCells && selectedCells.size > 0))) {
      const HOVER_COLOR: [number, number, number] = [40, 120, 255]   // blue
      const SELECT_COLOR: [number, number, number] = [255, 220, 50]  // yellow
      for (let i = 0; i < totalPixels; i++) {
        const cid = cellIdMap[i]
        if (cid == null) continue
        const isSelected = selectedCells?.has(cid)
        const isHovered = cid === hoveredCell
        if (!isSelected && !isHovered) continue
        const [hr, hg, hb] = isSelected ? SELECT_COLOR : HOVER_COLOR
        const alpha = 0.55
        const pi = i * 4
        buf[pi]     = Math.round(buf[pi]     * (1 - alpha) + hr * alpha)
        buf[pi + 1] = Math.round(buf[pi + 1] * (1 - alpha) + hg * alpha)
        buf[pi + 2] = Math.round(buf[pi + 2] * (1 - alpha) + hb * alpha)
      }
    }

    // --- Reverse rows (always) + optionally reverse columns ---
    // Column flip: needed for SphereGeometry (globe, u=0→lon=180°).
    // NOT needed for PlaneGeometry (map, u=0→left edge→lon=-180°).
    let outBuf = new Uint8Array(totalPixels * 4)
    for (let y = 0; y < height; y++) {
      const srcRow = (height - 1 - y) * width * 4
      const dstRow = y * width * 4
      for (let x = 0; x < width; x++) {
        const srcX = flipHorizontal ? (width - 1 - x) * 4 : x * 4
        const dstX = x * 4
        outBuf[dstRow + dstX] = buf[srcRow + srcX]
        outBuf[dstRow + dstX + 1] = buf[srcRow + srcX + 1]
        outBuf[dstRow + dstX + 2] = buf[srcRow + srcX + 2]
        outBuf[dstRow + dstX + 3] = buf[srcRow + srcX + 3]
      }
    }

    // --- Step 3.5: Draw graticule on flipped buffer ---
    // Row → lat:  lat = y / height * 180 - 90   (row 0 = lat -90°)
    const GRID_STEP = 30
    const GRID_ALPHA = 0.08
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      const y = Math.round(((90 + lat) / 180) * height)
      if (y < 0 || y >= height) continue
      for (let x = 0; x < width; x++) {
        const pi = (y * width + x) * 4
        outBuf[pi] = Math.round(outBuf[pi] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 1] = Math.round(outBuf[pi + 1] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 2] = Math.round(outBuf[pi + 2] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
      }
    }
    for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
      const x = Math.round(((lon + 180) / 360) * width)
      if (x < 0 || x >= width) continue
      for (let y = 0; y < height; y++) {
        const pi = (y * width + x) * 4
        outBuf[pi] = Math.round(outBuf[pi] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 1] = Math.round(outBuf[pi + 1] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
        outBuf[pi + 2] = Math.round(outBuf[pi + 2] * (1 - GRID_ALPHA) + 255 * GRID_ALPHA)
      }
    }

    // --- Step 4: Upload as DataTexture ---
    const hasCellLayers = layers.plates > 0 || layers.boundaries > 0
    const filterType = hasCellLayers ? THREE.NearestFilter : THREE.LinearFilter
    const colorTex = new THREE.DataTexture(
      outBuf as unknown as BufferSource, width, height, THREE.RGBAFormat,
    )
    colorTex.wrapS = THREE.RepeatWrapping
    colorTex.wrapT = THREE.ClampToEdgeWrapping
    colorTex.minFilter = filterType
    colorTex.magFilter = filterType
    colorTex.needsUpdate = true

    const material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: { u_colorMap: { value: colorTex } },
      side: THREE.DoubleSide,
    })

    // Save to module-level cache (survives component unmount/remount)
    lastCache = { elevation, width, height, layers, cellIdMap, cvtMesh, hoveredCell, selectedCells, material }

    return material
  }, [
    elevation, width, height, seaLevel,
    elevMinM, elevMaxM, layers,
    hillshadeStrength, waterDepthFactor, cvtMesh, cellIdMap,
  ])
}
