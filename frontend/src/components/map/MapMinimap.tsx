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
  mapCenter: { lon: number; lat: number }
  zoom: number
  containerWidth: number
  containerHeight: number
}

export default function MapMinimap({
  elevation,
  width: mapW,
  height: mapH,
  seaLevel,
  mapCenter,
  zoom,
  containerWidth: _cw,
  containerHeight: _ch,
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
    if (zoom <= 0) return []

    const halfW = 180 / zoom  // half the viewport width in degrees
    const halfH = 90 / zoom   // half the viewport height in degrees

    const lonL = mapCenter.lon - halfW
    const lonR = mapCenter.lon + halfW
    const latT = mapCenter.lat + halfH  // top = higher latitude
    const latB = mapCenter.lat - halfH  // bottom = lower latitude

    // Normalised [0,1] → minimap pixels
    const nxL = ((lonL + 180) / 360) * thumbW
    const nxR = ((lonR + 180) / 360) * thumbW
    const nyT = ((90 - latT) / 180) * thumbH
    const nyB = ((90 - latB) / 180) * thumbH

    const left = Math.min(nxL, nxR)
    const right = Math.max(nxL, nxR)
    const top = Math.min(nyT, nyB)
    const bottom = Math.max(nyT, nyB)
    const w = right - left
    const h = bottom - top

    // Split into rects for horizontal wrapping
    const rects: { x: number; y: number; w: number; h: number }[] = []
    if (left >= 0 && right <= thumbW) {
      rects.push({ x: left, y: top, w, h })
    } else if (left < 0) {
      rects.push({ x: left + thumbW, y: top, w: -left, h })
      rects.push({ x: 0, y: top, w: right, h })
    } else if (right > thumbW) {
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
