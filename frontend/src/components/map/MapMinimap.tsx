/**
 * MapMinimap — bird's-eye view showing current viewport on the full map.
 *
 * Similar to EU4's minimap: renders a thumbnail of the heightmap with a
 * rectangle indicating the area currently visible in the main viewer.
 * The rectangle wraps horizontally (cylindrical projection).
 */

import { useEffect, useRef } from 'react'
import { TERRAIN_SCALE, generateLut } from '../../viewers/map/utils/colorScales'

interface MapMinimapProps {
  elevation: Float32Array | null
  width: number
  height: number
  seaLevel: number
  pan: { x: number; y: number }
  zoom: number
  containerWidth: number
  containerHeight: number
  planeWidth: number
  planeHeight: number
}

export default function MapMinimap({
  elevation,
  width: mapW,
  height: mapH,
  seaLevel,
  pan,
  zoom,
  containerWidth,
  containerHeight,
  planeWidth,
  planeHeight,
}: MapMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const thumbW = 180
  const thumbH = Math.round((mapH / mapW) * thumbW)

  // Render elevation thumbnail
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !elevation) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const lut = generateLut(TERRAIN_SCALE, 256)
    const imageData = ctx.createImageData(thumbW, thumbH)

    for (let ty = 0; ty < thumbH; ty++) {
      for (let tx = 0; tx < thumbW; tx++) {
        const sx = Math.min(mapW - 1, Math.round((tx / thumbW) * mapW))
        const sy = Math.min(mapH - 1, Math.round((ty / thumbH) * mapH))
        const val = elevation[sy * mapW + sx]

        const lutIdx = Math.min(255, Math.round(val * 255))
        let r = lut[lutIdx * 3 + 0]
        let g = lut[lutIdx * 3 + 1]
        let b = lut[lutIdx * 3 + 2]

        if (val < seaLevel) {
          const depth = (seaLevel - val) / Math.max(seaLevel, 0.001)
          const factor = 1 - depth * 0.5
          r = Math.round(r * factor)
          g = Math.round(g * factor)
          b = Math.round(b * factor)
        }

        const idx = (ty * thumbW + tx) * 4
        imageData.data[idx] = r
        imageData.data[idx + 1] = g
        imageData.data[idx + 2] = b
        imageData.data[idx + 3] = 255
      }
    }

    ctx.putImageData(imageData, 0, 0)
  }, [elevation, mapW, mapH, seaLevel, thumbW, thumbH])

  // Compute viewport rectangle in minimap pixel coordinates
  const getViewportRects = () => {
    if (!planeWidth || !planeHeight || zoom <= 0) return []

    // Screen edges → normalised map coords
    const nxL = (-containerWidth / 2 - pan.x) / (planeWidth * zoom) + 0.5
    const nxR = (containerWidth / 2 - pan.x) / (planeWidth * zoom) + 0.5
    const nyT = (-containerHeight / 2 - pan.y) / (planeHeight * zoom) + 0.5
    const nyB = (containerHeight / 2 - pan.y) / (planeHeight * zoom) + 0.5

    // Convert to minimap pixels
    const left = nxL * thumbW
    const right = nxR * thumbW
    const top = nyT * thumbH
    const bottom = nyB * thumbH

    const w = right - left
    const h = bottom - top

    // Split into rects for horizontal wrapping
    const rects: { x: number; y: number; w: number; h: number }[] = []

    if (left >= 0 && right <= thumbW) {
      // Fully inside
      rects.push({ x: left, y: top, w, h })
    } else if (left < 0) {
      // Wraps on the left side
      rects.push({ x: left + thumbW, y: top, w: -left, h })
      rects.push({ x: 0, y: top, w: right, h })
    } else if (right > thumbW) {
      // Wraps on the right side
      rects.push({ x: left, y: top, w: thumbW - left, h })
      rects.push({ x: 0, y: top, w: right - thumbW, h })
    }

    return rects
  }

  const rects = getViewportRects()

  return (
    <div className="relative inline-block">
      <canvas
        ref={canvasRef}
        width={thumbW}
        height={thumbH}
        className="rounded border border-space-border"
        style={{ imageRendering: 'pixelated', width: thumbW, height: thumbH }}
      />
      {/* Viewport rectangle(s) */}
      <svg
        className="absolute inset-0 pointer-events-none"
        width={thumbW}
        height={thumbH}
      >
        {rects.map((r, i) => (
          <rect
            key={i}
            x={r.x}
            y={r.y}
            width={r.w}
            height={r.h}
            fill="rgba(255,255,255,0.1)"
            stroke="#fff"
            strokeWidth={1}
            strokeOpacity={0.7}
          />
        ))}
      </svg>
    </div>
  )
}
