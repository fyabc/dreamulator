/**
 * TerrainPlane — pre-renders a heightmap to an OffscreenCanvas using
 * Canvas 2D (color ramp + hillshading + water darkening).
 *
 * The caller (MapViewer) draws the canvas into the viewport using
 * CSS positioning, completely bypassing Three.js UV-mapping issues
 * on certain GPU/driver combinations.
 */

import { useMemo } from 'react'
import { generateLut, TERRAIN_SCALE, ELEVATION_SCALE, LANDSEA_SCALE, SLOPE_SCALE } from './utils/colorScales'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ColorMode = 'terrain' | 'elevation' | 'landsea' | 'slope'

export interface TerrainPlaneProps {
  /** Elevation data as Float32Array [0, 1]. */
  elevation: Float32Array | null
  /** Raster width. */
  width: number
  /** Raster height. */
  height: number
  /** Normalised sea level [0, 1]. */
  seaLevel: number
  /** Color mode for the ramp. */
  colorMode?: ColorMode
  /** Hillshade strength [0, 1]. */
  hillshadeStrength?: number
  /** Water depth darkening factor [0, 1]. */
  waterDepthFactor?: number
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sampleElev(elev: Float32Array, w: number, h: number, x: number, y: number): number {
  const wx = ((x % w) + w) % w
  const wy = Math.max(0, Math.min(h - 1, y))
  return elev[wy * w + wx]
}

// ---------------------------------------------------------------------------
// Hook: pre-render terrain to an OffscreenCanvas
// ---------------------------------------------------------------------------

export default function useTerrainCanvas({
  elevation,
  width,
  height,
  seaLevel,
  colorMode = 'terrain',
  hillshadeStrength = 0.7,
  waterDepthFactor = 0.5,
}: TerrainPlaneProps): OffscreenCanvas | null {
  return useMemo(() => {
    if (!elevation) return null

    const scaleMap: Record<ColorMode, typeof TERRAIN_SCALE> = {
      terrain: TERRAIN_SCALE,
      elevation: ELEVATION_SCALE,
      landsea: LANDSEA_SCALE,
      slope: SLOPE_SCALE,
    }
    const scale = scaleMap[colorMode] || TERRAIN_SCALE
    const lut = generateLut(scale, 256)

    const canvas = new OffscreenCanvas(width, height)
    const ctx = canvas.getContext('2d')!
    const imageData = ctx.createImageData(width, height)
    const px = imageData.data

    const lx = -1 / Math.sqrt(3)
    const ly = 1 / Math.sqrt(3)
    const lz = 1 / Math.sqrt(3)

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const elev = elevation[y * width + x]
        const lutIdx = Math.min(255, Math.max(0, Math.round(elev * 255)))
        let r = lut[lutIdx * 3 + 0]
        let g = lut[lutIdx * 3 + 1]
        let b = lut[lutIdx * 3 + 2]

        // Hillshading
        if (hillshadeStrength > 0) {
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

        // Water depth darkening
        if (elev < seaLevel) {
          const depth = (seaLevel - elev) / Math.max(seaLevel, 0.001)
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

    ctx.putImageData(imageData, 0, 0)
    return canvas
  }, [elevation, width, height, seaLevel, colorMode, hillshadeStrength, waterDepthFactor])
}
