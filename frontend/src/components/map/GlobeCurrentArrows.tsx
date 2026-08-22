/**
 * GlobeCurrentArrows — rAF-driven canvas overlay for ocean current arrows
 * on the 3D globe.  Screen-space direction from globe projector's analytical
 * tangent frame (no numerical finite differences).
 */
import { useEffect, useRef, useCallback } from 'react'
import type { VoronoiCell } from '../../viewers/map/types'

type ProjectFn = (lon: number, lat: number) => ({
  x: number; y: number; edgeFade: number; zoomScale: number
  ex: number; ey: number; nx: number; ny: number
}) | null

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
  const arrowsRef = useRef<{ lon: number; lat: number; u: number; v: number; warm: boolean }[]>([])
  const maxSpdRef = useRef(0)

  useEffect(() => {
    if (currentOpacity <= 0 || voronoiCells.length === 0) { arrowsRef.current = []; return }
    type OC = { lon: number; lat: number; u: number; v: number; sstAnom: number }
    const ocean: OC[] = []
    let mx = 0
    for (const c of voronoiCells) {
      const u = c.ocean_current_east_m_s; const v = c.ocean_current_north_m_s
      if (u == null || v == null) continue
      const s = Math.sqrt(u * u + v * v); if (s > mx) mx = s
      ocean.push({ lon: c.lon ?? 0, lat: c.lat ?? 0, u, v, sstAnom: c.sst_anomaly_c ?? 0 })
    }
    if (ocean.length === 0 || mx < 1e-9) { arrowsRef.current = []; maxSpdRef.current = 0; return }
    maxSpdRef.current = mx
    const bins = new Map<string, OC>()
    for (const oc of ocean) {
      const k = `${Math.round(oc.lon / 2) * 2},${Math.round(oc.lat / 2) * 2}`
      const p = bins.get(k); if (!p) bins.set(k, oc)
      else if (oc.u * oc.u + oc.v * oc.v > p.u * p.u + p.v * p.v) bins.set(k, oc)
    }
    const out: typeof arrowsRef.current = []
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP)
      for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
        const oc = bins.get(`${Math.round(lon / 2) * 2},${Math.round(lat / 2) * 2}`)
        if (!oc) continue
        if (Math.sqrt(oc.u * oc.u + oc.v * oc.v) < 1e-9) continue
        out.push({ lon: oc.lon, lat: oc.lat, u: oc.u, v: oc.v, warm: oc.sstAnom > 0 })
      }
    arrowsRef.current = out
  }, [voronoiCells, currentOpacity])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const project = projectRef.current
    if (!canvas || !project) { rafRef.current = requestAnimationFrame(draw); return }
    const r3f = document.querySelector('canvas[data-engine]') as HTMLCanvasElement | null
    if (r3f) {
      const r = r3f.getBoundingClientRect()
      if (canvas.width !== r.width || canvas.height !== r.height) {
        canvas.width = r.width; canvas.height = r.height
      }
      canvas.style.left = r.left + 'px'; canvas.style.top = r.top + 'px'
      canvas.style.width = r.width + 'px'; canvas.style.height = r.height + 'px'
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) { rafRef.current = requestAnimationFrame(draw); return }
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (const a of arrowsRef.current) {
      const p = project(a.lon, a.lat)
      if (!p || p.edgeFade < 0.01) continue
      if (p.x < -50 || p.x > canvas.width + 50 || p.y < -50 || p.y > canvas.height + 50) continue

      const spd = Math.sqrt(a.u * a.u + a.v * a.v)
      if (spd < 1e-9) continue
      // Unit direction in local frame
      const ud = a.u / spd; const vd = a.v / spd
      const dx = ud * p.ex + vd * p.nx
      const dy = ud * p.ey + vd * p.ny
      const dm = Math.sqrt(dx * dx + dy * dy)
      if (dm < 0.5) continue
      const sx = dx / dm; const sy = dy / dm

      ctx.globalAlpha = currentOpacity * p.edgeFade
      const len = (1.5 + 13.5 * Math.sqrt(Math.min(spd / (maxSpdRef.current || 1), 1))) * ARROW_SCALE * (p.zoomScale ?? 1)
      const tx = p.x + sx * len; const ty = p.y + sy * len
      const hl = len * 0.38
      const color = a.warm ? WARM : COLD

      ctx.strokeStyle = color; ctx.lineWidth = Math.max(1, len * 0.13); ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(p.x - sx * len * 0.3, p.y - sy * len * 0.3)
      ctx.lineTo(tx - sx * hl * 0.5, ty - sy * hl * 0.5)
      ctx.stroke()

      ctx.fillStyle = color
      const ha = Math.atan2(sy, sx)
      ctx.beginPath(); ctx.moveTo(tx, ty)
      ctx.lineTo(tx - Math.cos(ha - 0.45) * hl, ty - Math.sin(ha - 0.45) * hl)
      ctx.lineTo(tx - Math.cos(ha + 0.45) * hl, ty - Math.sin(ha + 0.45) * hl)
      ctx.closePath(); ctx.fill()
    }
    rafRef.current = requestAnimationFrame(draw)
  }, [currentOpacity, projectRef])

  useEffect(() => { rafRef.current = requestAnimationFrame(draw); return () => cancelAnimationFrame(rafRef.current) }, [draw])
  if (currentOpacity <= 0) return null
  return <canvas ref={canvasRef} className="pointer-events-none" style={{ position: 'fixed', zIndex: 10, left: 0, top: 0 }} />
}
