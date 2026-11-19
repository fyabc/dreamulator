/**
 * ElevationPreviewCanvas — draws the backend's preview grid (metres + land
 * mask) with a hypsometric tint, outlines the coast, and reads values under
 * the pointer.  The colours are for display; the numbers come straight from
 * the grid the server computed with the import functions.
 */

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { previewScale, pixelLatLon, type ElevationPreviewGrid } from '../../api/elevationImport'

type Rgb = [number, number, number]

const SEA_STOPS: Rgb[] = [
  [12, 30, 74], // deepest
  [30, 78, 140],
  [92, 154, 205], // shallow
]
const LAND_STOPS: Rgb[] = [
  [62, 128, 72], // coast
  [170, 168, 92],
  [146, 104, 64],
  [236, 236, 236], // highest
]
const COAST: Rgb = [255, 238, 88]

function ramp(stops: Rgb[], t: number): Rgb {
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1)
  const i = Math.min(stops.length - 2, Math.floor(x))
  const f = x - i
  const a = stops[i]
  const b = stops[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

interface Props {
  grid: ElevationPreviewGrid
  showCoast: boolean
}

interface Hover {
  lat: number
  lon: number
  metres: number
  land: boolean
}

export default function ElevationPreviewCanvas({ grid, showCoast }: Props) {
  const { t } = useTranslation('importer')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<Hover | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const { width, height, metres, land } = grid
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const img = ctx.createImageData(width, height)
    const { seaMin, seaMax, landMin, landMax } = previewScale(grid)
    const seaSpan = seaMax - seaMin || 1
    const landSpan = landMax - landMin || 1
    for (let i = 0; i < metres.length; i++) {
      const isLand = land[i] === 1
      let rgb: Rgb
      if (showCoast && isCoast(land, i, width, height)) rgb = COAST
      else if (isLand) rgb = ramp(LAND_STOPS, (metres[i] - landMin) / landSpan)
      else rgb = ramp(SEA_STOPS, (metres[i] - seaMin) / seaSpan)
      img.data[i * 4] = rgb[0]
      img.data[i * 4 + 1] = rgb[1]
      img.data[i * 4 + 2] = rgb[2]
      img.data[i * 4 + 3] = 255
    }
    ctx.putImageData(img, 0, 0)
  }, [grid, showCoast])

  const onMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = Math.floor(((e.clientX - rect.left) / rect.width) * grid.width)
    const y = Math.floor(((e.clientY - rect.top) / rect.height) * grid.height)
    if (x < 0 || y < 0 || x >= grid.width || y >= grid.height) return setHover(null)
    const i = y * grid.width + x
    const [lat, lon] = pixelLatLon(x, y, grid.width, grid.height)
    setHover({ lat, lon, metres: grid.metres[i], land: grid.land[i] === 1 })
  }

  return (
    <div>
      <canvas
        ref={canvasRef}
        data-testid="elevation-preview-canvas"
        className="w-full rounded border border-space-border cursor-crosshair"
        style={{ imageRendering: 'pixelated', aspectRatio: `${grid.width} / ${grid.height}` }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      />
      <p className="text-xs text-gray-400 mt-1 min-h-[1.25rem]" data-testid="elevation-preview-readout">
        {hover
          ? t('preview.readout', {
              lat: formatLat(hover.lat),
              lon: formatLon(hover.lon),
              metres: Math.round(hover.metres).toLocaleString(),
              kind: hover.land ? t('preview.land') : t('preview.sea'),
            })
          : t('preview.hoverHint')}
      </p>
    </div>
  )
}

function isCoast(land: Uint8Array, i: number, width: number, height: number): boolean {
  if (!land[i]) return false
  const x = i % width
  const y = (i - x) / width
  // Longitude wraps; latitude does not.
  const left = y * width + ((x - 1 + width) % width)
  const right = y * width + ((x + 1) % width)
  if (!land[left] || !land[right]) return true
  if (y > 0 && !land[i - width]) return true
  if (y < height - 1 && !land[i + width]) return true
  return false
}

function formatLat(lat: number): string {
  return `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? 'N' : 'S'}`
}

function formatLon(lon: number): string {
  return `${Math.abs(lon).toFixed(1)}°${lon >= 0 ? 'E' : 'W'}`
}
