/**
 * MapPreviewCanvas — simple read-only terrain preview for WorldDetail.
 *
 * Uses a plain Canvas 2D element to render a small terrain thumbnail.
 * No Three.js needed for this simple preview.
 */

import { useEffect, useRef } from 'react'
import { TERRAIN_SCALE, generateLut } from '../../viewers/map/utils/colorScales'

interface MapPreviewCanvasProps {
  elevation: Float32Array | null
  width: number
  height: number
  seaLevel: number
  className?: string
}

export default function MapPreviewCanvas({
  elevation,
  width,
  height,
  seaLevel,
  className = '',
}: MapPreviewCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !elevation) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const thumbW = canvas.width
    const thumbH = canvas.height
    const imageData = ctx.createImageData(thumbW, thumbH)
    const lut = generateLut(TERRAIN_SCALE, 256)

    for (let ty = 0; ty < thumbH; ty++) {
      for (let tx = 0; tx < thumbW; tx++) {
        const sx = Math.min(width - 1, Math.round((tx / thumbW) * width))
        const sy = Math.min(height - 1, Math.round((ty / thumbH) * height))
        const val = elevation[sy * width + sx]

        // Sample LUT
        const lutIdx = Math.min(255, Math.round(val * 255))
        let r = lut[lutIdx * 3 + 0]
        let g = lut[lutIdx * 3 + 1]
        let b = lut[lutIdx * 3 + 2]

        // Water depth darkening
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
  }, [elevation, width, height, seaLevel])

  if (!elevation) {
    return (
      <div
        className={`flex items-center justify-center bg-space-surface/40 rounded-lg text-gray-500 text-sm ${className}`}
      >
        无地图数据
      </div>
    )
  }

  return (
    <canvas
      ref={canvasRef}
      width={512}
      height={256}
      className={`rounded-lg w-full ${className}`}
      style={{ imageRendering: 'pixelated', maxHeight: '200px', objectFit: 'cover' }}
    />
  )
}
