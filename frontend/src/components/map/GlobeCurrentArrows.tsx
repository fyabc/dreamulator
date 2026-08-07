/**
 * GlobeCurrentArrows — rAF-driven canvas overlay for ocean current arrows
 * on the 3D globe.  Uses the projector ref populated by GlobeViewer every frame.
 */
import { useEffect, useRef, useCallback } from 'react'
import type { VoronoiCell } from '../../viewers/map/types'

type ProjectFn = (lon: number, lat: number) => { x: number; y: number; edgeFade: number; zoomScale: number } | null

interface Props {
  projectRef: React.MutableRefObject<ProjectFn | null>
  voronoiCells: VoronoiCell[]
  currentOpacity: number
}

const WARM = '#e040fb'
const COLD = '#00bcd4'
const GRID_STEP = 4.5
const ARROW_SCALE = 1.0

export default function GlobeCurrentArrows({ projectRef, voronoiCells, currentOpacity }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)

  // Pre-sampled arrow data (computed only when cells/opacity change)
  const arrowsRef = useRef<{ lon: number; lat: number; u: number; v: number; warm: boolean }[]>([])
  const maxSpdRef = useRef(0)

  // Rebuild arrow sample set when cells or opacity change
  useEffect(() => {
    if (currentOpacity <= 0 || voronoiCells.length === 0) {
      arrowsRef.current = []
      return
    }

    type OC = { lon: number; lat: number; u: number; v: number; sstAnom: number }
    const ocean: OC[] = []
    let maxSpd = 0
    for (const c of voronoiCells) {
      const u = c.ocean_current_east_m_s
      const v = c.ocean_current_north_m_s
      if (u == null || v == null) continue
      const s = Math.sqrt(u * u + v * v)
      if (s > maxSpd) maxSpd = s
      ocean.push({ lon: c.lon ?? 0, lat: c.lat ?? 0, u, v, sstAnom: c.sst_anomaly_c ?? 0 })
    }
    if (ocean.length === 0 || maxSpd < 1e-9) {
      arrowsRef.current = []
      maxSpdRef.current = 0
      return
    }
    maxSpdRef.current = maxSpd

    // 2° bin → fastest cell
    const bins = new Map<string, OC>()
    for (const oc of ocean) {
      const blon = Math.round(oc.lon / 2) * 2
      const blat = Math.round(oc.lat / 2) * 2
      const key = `${blon},${blat}`
      const prev = bins.get(key)
      if (!prev) { bins.set(key, oc) }
      else if (oc.u * oc.u + oc.v * oc.v > prev.u * prev.u + prev.v * prev.v) {
        bins.set(key, oc)
      }
    }

    const sampled: typeof arrowsRef.current = []
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
        const key = `${Math.round(lon / 2) * 2},${Math.round(lat / 2) * 2}`
        const oc = bins.get(key)
        if (!oc) continue
        const speed = Math.sqrt(oc.u * oc.u + oc.v * oc.v)
        if (speed < 1e-9) continue
        sampled.push({ lon: oc.lon, lat: oc.lat, u: oc.u, v: oc.v, warm: oc.sstAnom > 0 })
      }
    }
    arrowsRef.current = sampled
  }, [voronoiCells, currentOpacity])

  // rAF render loop
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const project = projectRef.current
    if (!canvas || !project) { rafRef.current = requestAnimationFrame(draw); return }

    // Match the R3F canvas size and position exactly
    const r3fCanvas = document.querySelector('canvas[data-engine]') as HTMLCanvasElement | null
    if (r3fCanvas) {
      const rect = r3fCanvas.getBoundingClientRect()
      if (canvas.width !== rect.width || canvas.height !== rect.height) {
        canvas.width = rect.width; canvas.height = rect.height
      }
      canvas.style.left = rect.left + 'px'
      canvas.style.top = rect.top + 'px'
      canvas.style.width = rect.width + 'px'
      canvas.style.height = rect.height + 'px'
    }
    const w = canvas.width
    const h = canvas.height

    const ctx = canvas.getContext('2d')
    if (!ctx) { rafRef.current = requestAnimationFrame(draw); return }

    ctx.clearRect(0, 0, w, h)

    const arrows = arrowsRef.current
    for (const a of arrows) {
      const p = project(a.lon, a.lat)
      if (!p) continue
      if (p.x < -50 || p.x > w + 50 || p.y < -50 || p.y > h + 50) continue

      ctx.globalAlpha = currentOpacity * p.edgeFade
      const angle = Math.atan2(a.v, a.u)
      const speed = Math.sqrt(a.u * a.u + a.v * a.v)
      const speedFrac = speed / (maxSpdRef.current || 1)
      const len = (1.5 + 13.5 * Math.sqrt(Math.min(speedFrac, 1))) * ARROW_SCALE * (p.zoomScale ?? 1)
      const tipX = p.x + Math.cos(angle) * len
      const tipY = p.y - Math.sin(angle) * len

      const color = a.warm ? WARM : COLD
      const strokeW = Math.max(1, len * 0.13)

      // Shaft
      const headLen = len * 0.38
      const shaftEndX = tipX - Math.cos(angle) * headLen * 0.5
      const shaftEndY = tipY + Math.sin(angle) * headLen * 0.5
      const shaftStartX = p.x - Math.cos(angle) * len * 0.3
      const shaftStartY = p.y + Math.sin(angle) * len * 0.3

      ctx.strokeStyle = color
      ctx.lineWidth = strokeW
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(shaftStartX, shaftStartY)
      ctx.lineTo(shaftEndX, shaftEndY)
      ctx.stroke()

      // Arrowhead
      const ha = 0.45
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.moveTo(tipX, tipY)
      ctx.lineTo(tipX - Math.cos(angle - ha) * headLen, tipY + Math.sin(angle - ha) * headLen)
      ctx.lineTo(tipX - Math.cos(angle + ha) * headLen, tipY + Math.sin(angle + ha) * headLen)
      ctx.closePath()
      ctx.fill()
    }

    rafRef.current = requestAnimationFrame(draw)
  }, [currentOpacity, projectRef])

  useEffect(() => {
    rafRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(rafRef.current)
  }, [draw])

  if (currentOpacity <= 0) return null

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none"
      style={{ position: 'fixed', zIndex: 10, left: 0, top: 0 }}
    />
  )
}
