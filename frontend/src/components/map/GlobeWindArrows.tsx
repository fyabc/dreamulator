/**
 * GlobeWindArrows — rAF-driven canvas overlay for surface wind arrows
 * on the 3D globe.  Screen-space direction comes from the globe projector
 * (analytical tangent projection, no numerical finite differences).
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
  windOpacity: number
  /** Monthly wind (tech debt 24): N×12 east/north components in mesh-cell
   *  order.  When both are provided the arrows show month `month` instead of
   *  the annual-mean wind. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  month?: number
}

const GRID_STEP = 4.5
const ARROW_SCALE = 0.6

function tempColor(tC: number): string {
  const clamped = Math.min(Math.max(tC, -10), 25)
  return `hsl(${240 - (clamped + 10) / 35 * 240}, 70%, 50%)`
}

export default function GlobeWindArrows({
  projectRef, voronoiCells, windOpacity,
  monthlyWindEast = null, monthlyWindNorth = null, month = 0,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const arrowsRef = useRef<{ lon: number; lat: number; u: number; v: number; color: string }[]>([])
  const maxSpdRef = useRef(0)

  useEffect(() => {
    if (windOpacity <= 0 || voronoiCells.length === 0) { arrowsRef.current = []; return }
    type E = { lon: number; lat: number; u: number; v: number; tC: number }
    const all: E[] = []
    let mx = 0
    const useMonthly = !!(monthlyWindEast && monthlyWindNorth)
    for (let i = 0; i < voronoiCells.length; i++) {
      const c = voronoiCells[i]
      let u: number, v: number
      if (useMonthly) {
        u = (monthlyWindEast as Float32Array)[i * 12 + month]
        v = (monthlyWindNorth as Float32Array)[i * 12 + month]
      } else {
        u = c.wind_east_m_s as number
        v = c.wind_north_m_s as number
      }
      if (u == null || v == null || !Number.isFinite(u) || !Number.isFinite(v)) continue
      const s = Math.sqrt(u * u + v * v); if (s > mx) mx = s
      all.push({ lon: c.lon ?? 0, lat: c.lat ?? 0, u, v, tC: c.temperature_C ?? 0 })
    }
    if (all.length === 0 || mx < 1e-9) { arrowsRef.current = []; maxSpdRef.current = 0; return }
    maxSpdRef.current = mx
    const bins = new Map<string, E>()
    for (const e of all) {
      const k = `${Math.round(e.lon / 2) * 2},${Math.round(e.lat / 2) * 2}`
      const p = bins.get(k); if (!p) bins.set(k, e)
      else if (e.u * e.u + e.v * e.v > p.u * p.u + p.v * p.v) bins.set(k, e)
    }
    const out: typeof arrowsRef.current = []
    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP)
      for (let lon = -180 + GRID_STEP; lon < 180; lon += GRID_STEP) {
        const e = bins.get(`${Math.round(lon / 2) * 2},${Math.round(lat / 2) * 2}`)
        if (!e) continue
        if (Math.sqrt(e.u * e.u + e.v * e.v) < 1e-9) continue
        out.push({ lon: e.lon, lat: e.lat, u: e.u, v: e.v, color: tempColor(e.tC) })
      }
    arrowsRef.current = out
  }, [voronoiCells, windOpacity, monthlyWindEast, monthlyWindNorth, month])

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
      const ud = a.u / spd; const vd = a.v / spd
      const dx = ud * p.ex + vd * p.nx
      const dy = ud * p.ey + vd * p.ny
      const dm = Math.sqrt(dx * dx + dy * dy)
      if (dm < 0.5) continue
      const sx = dx / dm; const sy = dy / dm

      ctx.globalAlpha = windOpacity * p.edgeFade
      const len = (1.5 + 13.5 * Math.sqrt(Math.min(spd / (maxSpdRef.current || 1), 1))) * ARROW_SCALE * (p.zoomScale ?? 1)
      const tx = p.x + sx * len; const ty = p.y + sy * len
      const hl = len * 0.38

      ctx.strokeStyle = a.color; ctx.lineWidth = Math.max(1, len * 0.13); ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(p.x - sx * len * 0.3, p.y - sy * len * 0.3)
      ctx.lineTo(tx - sx * hl * 0.5, ty - sy * hl * 0.5)
      ctx.stroke()

      ctx.fillStyle = a.color
      const ha = Math.atan2(sy, sx)
      ctx.beginPath(); ctx.moveTo(tx, ty)
      ctx.lineTo(tx - Math.cos(ha - 0.45) * hl, ty - Math.sin(ha - 0.45) * hl)
      ctx.lineTo(tx - Math.cos(ha + 0.45) * hl, ty - Math.sin(ha + 0.45) * hl)
      ctx.closePath(); ctx.fill()
    }
    rafRef.current = requestAnimationFrame(draw)
  }, [windOpacity, projectRef])

  useEffect(() => { rafRef.current = requestAnimationFrame(draw); return () => cancelAnimationFrame(rafRef.current) }, [draw])
  if (windOpacity <= 0) return null
  return <canvas ref={canvasRef} className="pointer-events-none" style={{ position: 'fixed', zIndex: 10, left: 0, top: 0 }} />
}
