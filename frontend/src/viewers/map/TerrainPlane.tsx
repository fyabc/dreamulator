/**
 * useTerrainTexture — pre-renders a heightmap to a THREE.CanvasTexture
 * using Canvas 2D (color ramp + hillshading + water darkening).
 *
 * Supports elevation-based modes (terrain, landsea) via LUT color scales,
 * and cell-based modes (plates, boundaries) via CVT mesh polygon rendering.
 *
 * The texture is applied to a MeshBasicMaterial displayed via
 * WebGPURenderer (bypasses the ANGLE/D3D11 vertex attribute bug).
 */

import { useMemo } from 'react'
import * as THREE from 'three'
import {
  generateLut,
  generateAdaptiveTerrainScale,
  TERRAIN_SCALE,
  PLATE_COLORS,
} from './utils/colorScales'
import { projectForward, projectInverse, type ProjectionType } from './utils/projection'
import type { CVTMesh, BoundaryType } from './types'
import type { CellIdMap } from './useCellIdMap'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ColorMode = 'terrain' | 'landsea' | 'plates' | 'boundaries'

export interface TerrainTextureOptions {
  elevation: Float32Array | null
  width: number
  height: number
  seaLevel: number
  /** Minimum elevation in metres (for adaptive scale). */
  elevMinM?: number
  /** Maximum elevation in metres (for adaptive scale). */
  elevMaxM?: number
  colorMode?: ColorMode
  hillshadeStrength?: number
  waterDepthFactor?: number
  /** CVT mesh for cell-based color modes (plates, boundaries). */
  cvtMesh?: CVTMesh | null
  /** Pre-computed cell-ID map (from useCellIdMap). Enables O(1) palette lookup. */
  cellIdMap?: CellIdMap | null
  /** Map projection (default: equirectangular). Non-equirectangular projections
   *  re-sample the source data into the target projection's canvas. */
  projection?: ProjectionType
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sampleElev(elev: Float32Array, w: number, h: number, x: number, y: number): number {
  const wx = ((x % w) + w) % w
  const wy = Math.max(0, Math.min(h - 1, y))
  return elev[wy * w + wx]
}

/** Parse "#rrggbb" to [r, g, b]. */
function hexRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ]
}

// ---------------------------------------------------------------------------
// Boundary type colors
// ---------------------------------------------------------------------------

const BOUNDARY_COLORS: Record<BoundaryType, [number, number, number]> = {
  convergent: hexRgb('#e53935'),
  divergent: hexRgb('#43a047'),
  transform: hexRgb('#fdd835'),
}

// ---------------------------------------------------------------------------
// Graticule (grid lines)
// ---------------------------------------------------------------------------

const GRID_STEP = 30 // degrees
const GRID_ALPHA = 0.10 // faint white
const GRID_SAMPLE_STEP = 0.5 // degrees (sampling resolution for curved lines)

/**
 * Draw latitude/longitude grid lines on the final canvas.
 *
 * For equirectangular the lines are straight, drawn directly with Canvas 2D.
 * For Mollweide/Robinson each line is sampled via projectForward and drawn as
 * a polyline — the path breaks at projection boundaries (round-trip mismatch).
 */
function drawGraticule(
  ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D,
  w: number,
  h: number,
  projection: ProjectionType,
): void {
  ctx.save()
  ctx.strokeStyle = `rgba(255, 255, 255, ${GRID_ALPHA})`
  ctx.lineWidth = 1

  if (projection === 'equirectangular') {
    // --- Equirectangular: straight horizontal & vertical lines ----------
    // Latitude lines (exclude ±90° edges)
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      const y = ((90 - lat) / 180) * h
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(w, y)
      ctx.stroke()
    }
    // Longitude lines (exclude ±180° edges)
    for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
      const x = ((lon + 180) / 360) * w
      ctx.beginPath()
      ctx.moveTo(x, 0)
      ctx.lineTo(x, h)
      ctx.stroke()
    }
  } else {
    // --- Mollweide / Robinson: curved projected lines ------------------
    // Latitude lines (vary lon at fixed lat)
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      ctx.beginPath()
      let started = false
      for (let lon = -180; lon <= 180; lon += GRID_SAMPLE_STEP) {
        const fwd = projectForward(projection, lon, lat)
        const x = fwd.nx * w
        const y = fwd.ny * h
        // Round-trip check: is this point inside the projection boundary?
        const inv = projectInverse(projection, fwd.nx, fwd.ny)
        const back = projectForward(projection, inv.lon, inv.lat)
        const valid = Math.abs(back.nx - fwd.nx) < 0.02 && Math.abs(back.ny - fwd.ny) < 0.02
        if (valid) {
          if (!started) { ctx.moveTo(x, y); started = true }
          else { ctx.lineTo(x, y) }
        } else {
          started = false // break the path at projection edge
        }
      }
      ctx.stroke()
    }
    // Longitude lines (vary lat at fixed lon)
    for (let lon = -180; lon < 180; lon += GRID_STEP) {
      ctx.beginPath()
      let started = false
      for (let lat = -90; lat <= 90; lat += GRID_SAMPLE_STEP) {
        const fwd = projectForward(projection, lon, lat)
        const x = fwd.nx * w
        const y = fwd.ny * h
        const inv = projectInverse(projection, fwd.nx, fwd.ny)
        const back = projectForward(projection, inv.lon, inv.lat)
        const valid = Math.abs(back.nx - fwd.nx) < 0.02 && Math.abs(back.ny - fwd.ny) < 0.02
        if (valid) {
          if (!started) { ctx.moveTo(x, y); started = true }
          else { ctx.lineTo(x, y) }
        } else {
          started = false
        }
      }
      ctx.stroke()
    }
  }

  ctx.restore()
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export default function useTerrainTexture({
  elevation,
  width,
  height,
  seaLevel,
  elevMinM = -11000,
  elevMaxM = 9000,
  colorMode = 'terrain',
  hillshadeStrength = 0.7,
  waterDepthFactor = 0.5,
  cvtMesh,
  cellIdMap,
  projection = 'equirectangular',
}: TerrainTextureOptions): THREE.CanvasTexture | null {
  return useMemo(() => {
    if (!elevation) return null

    // Compute output canvas dimensions based on projection
    const isReprojected = projection !== 'equirectangular'
    let outW = width
    let outH = height
    if (isReprojected) {
      // Use projection aspect ratio; keep similar pixel count for quality
      const projAspect = projection === 'robinson' ? 2.662 : 2.0
      outH = Math.round(Math.sqrt(width * height / projAspect))
      outW = Math.round(outH * projAspect)
    }

    // Render equirectangular base into a buffer (always)
    const eqCanvas = new OffscreenCanvas(width, height)
    const eqCtx = eqCanvas.getContext('2d')!

    // Cell-based modes use polygon rendering
    const isCellMode = colorMode === 'plates' || colorMode === 'boundaries'

    // Compute normalised sea level from absolute metres
    const range = elevMaxM - elevMinM || 1
    const normSeaLevel = (seaLevel - elevMinM) / range

    if (!isCellMode) {
      // ------------------------------------------------------------------
      // Elevation-based modes: LUT + hillshading + water darkening
      // ------------------------------------------------------------------

      let lut: Uint8Array
      let isRgba = false

      if (colorMode === 'terrain') {
        // Adaptive hypsometric tint based on actual elevation range
        lut = generateAdaptiveTerrainScale(elevMinM, elevMaxM, seaLevel)
        isRgba = true
      } else if (colorMode === 'landsea') {
        // Dynamic binary LUT: sharp water/land boundary at the true sea level
        lut = new Uint8Array(256 * 3)
        const WATER: [number, number, number] = [30, 60, 120]
        const LAND: [number, number, number] = [80, 140, 60]
        const cutoff = Math.round(normSeaLevel * 255)
        for (let i = 0; i < 256; i++) {
          const c = i <= cutoff ? WATER : LAND
          lut[i * 3 + 0] = c[0]
          lut[i * 3 + 1] = c[1]
          lut[i * 3 + 2] = c[2]
        }
      } else {
        // Fallback to static terrain scale
        lut = generateLut(TERRAIN_SCALE, 256)
      }

      const imageData = eqCtx.createImageData(width, height)
      const px = imageData.data

      const lx = -1 / Math.sqrt(3)
      const ly = 1 / Math.sqrt(3)
      const lz = 1 / Math.sqrt(3)

      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const elev = elevation[y * width + x]
          const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))
          let r: number, g: number, b: number

          if (isRgba) {
            r = lut[lutIdx * 4 + 0]
            g = lut[lutIdx * 4 + 1]
            b = lut[lutIdx * 4 + 2]
          } else {
            r = lut[lutIdx * 3 + 0]
            g = lut[lutIdx * 3 + 1]
            b = lut[lutIdx * 3 + 2]
          }

          // Hillshading — skip for landsea (flat binary colours)
          if (hillshadeStrength > 0 && colorMode !== 'landsea') {
            const dx =
              sampleElev(elevation, width, height, x + 1, y) -
              sampleElev(elevation, width, height, x - 1, y)
            const dy =
              sampleElev(elevation, width, height, x, y + 1) -
              sampleElev(elevation, width, height, x, y - 1)
            const nx = -dx * hillshadeStrength * 8
            const ny = -dy * hillshadeStrength * 8
            const nz = 1
            const nLen = Math.sqrt(nx * nx + ny * ny + nz * nz)
            const shade = 0.4 + 0.6 * Math.max(0, (nx * lx + ny * ly + nz * lz) / nLen)
            r = Math.min(255, Math.round(r * shade))
            g = Math.min(255, Math.round(g * shade))
            b = Math.min(255, Math.round(b * shade))
          }

          // Water depth darkening — skip for landsea (single ocean colour)
          if (elev < normSeaLevel && colorMode !== 'landsea') {
            const depth = (normSeaLevel - elev) / Math.max(normSeaLevel, 0.001)
            const factor = 1.0 - waterDepthFactor * depth
            r = Math.round(r * factor)
            g = Math.round(g * factor)
            b = Math.round(b * factor)
          }

          const idx = (y * width + x) * 4
          px[idx] = r
          px[idx + 1] = g
          px[idx + 2] = b
          px[idx + 3] = 255
        }
      }

      eqCtx.putImageData(imageData, 0, 0)
    } else if (cvtMesh && cellIdMap && cellIdMap.length === width * height) {
      // ------------------------------------------------------------------
      // Cell-based modes: FAST palette lookup via pre-computed cell-ID map
      //
      // The cellIdMap was pre-computed by useCellIdMap (one-time KD-tree pass).
      // Now each pixel just does: cellIdMap[pixel] → cell_id → palette[color]
      // This is O(1) per pixel vs O(log N) for KD-tree → ~20× faster mode switch.
      //
      // Design reference: id Software lightmaps, Unreal virtual texturing,
      // Mapbox feature-ID picking, QGIS categorized renderers.
      // ------------------------------------------------------------------

      // Build plate color palette: plate_id → packed RGB
      const plateIds = [...new Set(cvtMesh.cells.map((c) => c.plate_id).filter(Boolean))]
      const platePalette = new Map<string, number>()
      plateIds.forEach((pid, idx) => {
        const [r, g, b] = hexRgb(PLATE_COLORS[idx % PLATE_COLORS.length])
        platePalette.set(pid!, (r << 16) | (g << 8) | b)
      })

      // Build cell → palette index lookup
      const cellToPlateColor = new Map<number, number>()
      const cellToBoundaryColor = new Map<number, number>()
      for (const cell of cvtMesh.cells) {
        if (cell.plate_id) {
          const color = platePalette.get(cell.plate_id)
          if (color !== undefined) cellToPlateColor.set(cell.id, color)
        }
        if (cell.boundary_type) {
          const [r, g, b] = BOUNDARY_COLORS[cell.boundary_type as BoundaryType]
          cellToBoundaryColor.set(cell.id, (r << 16) | (g << 8) | b)
        }
      }

      // Select which palette to use based on colorMode
      const palette = colorMode === 'plates' ? cellToPlateColor : cellToBoundaryColor

      // Render: for each pixel, O(1) cell-ID lookup → O(1) palette lookup
      const imageData = eqCtx.createImageData(width, height)
      const px = imageData.data
      const blendAlpha = 0.5
      const blendInv = 1 - blendAlpha
      const baseLut = generateLut(TERRAIN_SCALE, 256)

      for (let py = 0; py < height; py++) {
        const rowOff = py * width
        for (let px2 = 0; px2 < width; px2++) {
          const cellId = cellIdMap[rowOff + px2]
          const packed = palette.get(cellId)

          // Base terrain color
          const elev = elevation[rowOff + px2]
          const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))
          let r = baseLut[lutIdx * 3 + 0]
          let g = baseLut[lutIdx * 3 + 1]
          let b = baseLut[lutIdx * 3 + 2]

          // Blend overlay if cell has a color in the palette
          if (packed !== undefined) {
            r = (r * blendInv + ((packed >> 16) & 0xff) * blendAlpha) | 0
            g = (g * blendInv + ((packed >> 8) & 0xff) * blendAlpha) | 0
            b = (b * blendInv + (packed & 0xff) * blendAlpha) | 0
          }

          const idx = (rowOff + px2) * 4
          px[idx] = r
          px[idx + 1] = g
          px[idx + 2] = b
          px[idx + 3] = 255
        }
      }

      eqCtx.putImageData(imageData, 0, 0)
    } else {
      // ------------------------------------------------------------------
      // Cell mode requested but no CVT mesh — fall back to terrain rendering
      // ------------------------------------------------------------------
      const lut = generateLut(TERRAIN_SCALE, 256)
      const imageData = eqCtx.createImageData(width, height)
      const px = imageData.data

      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const elev = elevation[y * width + x]
          const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))
          const r = lut[lutIdx * 3 + 0]
          const g = lut[lutIdx * 3 + 1]
          const b = lut[lutIdx * 3 + 2]
          const idx = (y * width + x) * 4
          px[idx] = r
          px[idx + 1] = g
          px[idx + 2] = b
          px[idx + 3] = 255
        }
      }

      eqCtx.putImageData(imageData, 0, 0)
    }

    // ------------------------------------------------------------------
    // Projection re-sampling: warp equirectangular → target projection
    // ------------------------------------------------------------------
    let finalCanvas: OffscreenCanvas

    if (!isReprojected) {
      // No reprojection needed — use equirectangular directly
      finalCanvas = eqCanvas
    } else {
      // Re-sample from equirectangular to target projection
      finalCanvas = new OffscreenCanvas(outW, outH)
      const outCtx = finalCanvas.getContext('2d')!
      const outData = outCtx.createImageData(outW, outH)
      const outPx = outData.data

      // Get equirectangular pixel data for sampling
      const eqData = eqCtx.getImageData(0, 0, width, height)
      const eqPx = eqData.data

      for (let oy = 0; oy < outH; oy++) {
        for (let ox = 0; ox < outW; ox++) {
          // Normalised coordinates in output canvas [0, 1]
          const nx = ox / (outW - 1)
          const ny = oy / (outH - 1)

          // Inverse projection: output pixel → (lon, lat)
          const { lon, lat } = projectInverse(projection, nx, ny)

          // Check if the inverse projection returned valid coordinates
          const outside = isNaN(lon) || isNaN(lat) || lon < -180 || lon > 180 || lat < -90 || lat > 90
          // Round-trip check: projectInverse clamps edge values for non-cylindrical
          // projections (Mollweide ellipse corners, Robinson curved edges).  Forward-
          // project the result and compare — a mismatch means the pixel is outside
          // the projection's valid area.
          if (!outside) {
            const fwd = projectForward(projection, lon, lat)
            if (Math.abs(fwd.nx - nx) > 0.02 || Math.abs(fwd.ny - ny) > 0.02) {
              const idx = (oy * outW + ox) * 4
              outPx[idx] = 0; outPx[idx + 1] = 0; outPx[idx + 2] = 0; outPx[idx + 3] = 0
              continue
            }
          }
          if (outside) {
            const idx = (oy * outW + ox) * 4
            outPx[idx] = 0; outPx[idx + 1] = 0; outPx[idx + 2] = 0; outPx[idx + 3] = 0
            continue
          }

          // Map (lon, lat) to equirectangular pixel coordinates
          const ex = ((lon + 180) / 360) * (width - 1)
          const ey = ((90 - lat) / 180) * (height - 1)

          // Bilinear interpolation from equirectangular source
          const ex0 = Math.floor(ex)
          const ey0 = Math.floor(ey)
          const ex1 = Math.min(ex0 + 1, width - 1)
          const ey1 = Math.min(ey0 + 1, height - 1)
          const fx = ex - ex0
          const fy = ey - ey0

          const i00 = (ey0 * width + ex0) * 4
          const i10 = (ey0 * width + ex1) * 4
          const i01 = (ey1 * width + ex0) * 4
          const i11 = (ey1 * width + ex1) * 4

          const outIdx = (oy * outW + ox) * 4
          for (let c = 0; c < 4; c++) {
            const v =
              eqPx[i00 + c] * (1 - fx) * (1 - fy) +
              eqPx[i10 + c] * fx * (1 - fy) +
              eqPx[i01 + c] * (1 - fx) * fy +
              eqPx[i11 + c] * fx * fy
            outPx[outIdx + c] = Math.round(v)
          }
        }
      }

      outCtx.putImageData(outData, 0, 0)
    }

    // ---- Draw latitude/longitude grid lines -------------------------------
    const finalW = isReprojected ? outW : width
    const finalH = isReprojected ? outH : height
    const gridCtx = finalCanvas.getContext('2d')!
    drawGraticule(gridCtx, finalW, finalH, projection)

    const tex = new THREE.CanvasTexture(finalCanvas as any)
    tex.colorSpace = THREE.NoColorSpace // match DataTexture (GPU path) — raw sRGB bytes
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.needsUpdate = true
    return tex
  }, [elevation, width, height, seaLevel, elevMinM, elevMaxM, colorMode, hillshadeStrength, waterDepthFactor, cvtMesh, cellIdMap, projection])
}
