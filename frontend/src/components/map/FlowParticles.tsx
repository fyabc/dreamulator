/**
 * FlowParticles — nullschool-style advected particle overlay for the wind and
 * ocean-current layers.
 *
 * Particles live in lon/lat and are advanced by the sampled vector field each
 * animation frame (RK2 on the sphere).  The head of each particle is projected
 * through the viewer's allocation-free point projector; a segment is drawn from
 * its previous screen position, and the canvas is faded with `destination-out`
 * so the accumulated segments form a comet trail.
 *
 * Trails are screen-space: when the camera or map viewport moves, the overlay
 * clears instead of smearing old pixels across the new view.  A static globe /
 * map (the normal viewing and recording posture) accumulates long trails.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { PointProjector, ScreenPoint, VoronoiCell } from '../../viewers/map/types'
import {
  EARTH_RADIUS_M,
  advectParticle,
  buildFlowField,
  randomLonLat,
  sampleCellId,
  sampleFlow,
  type AdvectResult,
  type FlowField,
  type FlowKind,
  type FlowSample,
} from '../../viewers/map/flowField'

interface Props {
  projectRef: React.MutableRefObject<PointProjector | null>
  kind: FlowKind
  cells: VoronoiCell[]
  opacity: number
  /** Monthly wind arrays (wind only); absent → annual-mean wind. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  month?: number
  /** Planet radius (metres) for the m/s → degrees/s conversion. */
  planetRadiusM?: number
  /** Equirectangular cell-ID raster (`useCellIdMap`) for the ocean land check. */
  cellIdMap?: Uint32Array | null
  /** Dimensions of `cellIdMap` (the elevation raster's width/height). */
  meshWidth?: number
  meshHeight?: number
  /**
   * `fixed` aligns the canvas to the R3F globe canvas (page-level overlay);
   * `absolute` fills the parent container (2D map).
   */
  positioning?: 'fixed' | 'absolute'
}

const WIND_PARTICLES = 3400
const CURRENT_PARTICLES = 3000
/** Minimum streak length (CSS px) on frames where the view itself moved. */
const MOVED_MIN_STREAK_PX = 5
const WIND_BINS = 20
const CURRENT_BINS = 2

// Display accelerations (not model parameters): one real second advances one
// model day of wind, or 200 model days of ocean flow.  Ocean currents are two
// to three orders of magnitude slower than winds; without the larger factor
// their particles would appear frozen.
const WIND_SIM_SECONDS_PER_REAL_SECOND = 24 * 3600
const CURRENT_SIM_SECONDS_PER_REAL_SECOND = 200 * 86400

interface ParticleState {
  count: number
  lon: Float32Array
  lat: Float32Array
  /** Previous-frame position, used to draw one-frame streaks while the camera moves. */
  prevLon: Float32Array
  prevLat: Float32Array
  age: Float32Array
  life: Float32Array
  lastX: Float32Array
  lastY: Float32Array
  prevX: Float32Array
  prevY: Float32Array
  hasLast: Uint8Array
  hasSegment: Uint8Array
  bin: Uint8Array
}

const _screen: ScreenPoint = { x: 0, y: 0, edgeFade: 0 }
const _screenPrev: ScreenPoint = { x: 0, y: 0, edgeFade: 0 }
const _advect: AdvectResult = { lon: 0, lat: 0, speed: 0, aux: 0 }
const _sample: FlowSample = { u: 0, v: 0, aux: 0, valid: false }

function makeParticles(
  count: number,
  kind: FlowKind,
  field: FlowField | null,
  isLand: ((lon: number, lat: number) => boolean) | null,
): ParticleState {
  const state: ParticleState = {
    count,
    lon: new Float32Array(count),
    lat: new Float32Array(count),
    prevLon: new Float32Array(count),
    prevLat: new Float32Array(count),
    age: new Float32Array(count),
    life: new Float32Array(count),
    lastX: new Float32Array(count),
    lastY: new Float32Array(count),
    prevX: new Float32Array(count),
    prevY: new Float32Array(count),
    hasLast: new Uint8Array(count),
    hasSegment: new Uint8Array(count),
    bin: new Uint8Array(count),
  }
  for (let i = 0; i < count; i++) {
    respawnParticle(state, i, kind, field, isLand)
    state.age[i] = Math.random() * state.life[i]
  }
  return state
}

function respawnParticle(
  state: ParticleState,
  i: number,
  kind: FlowKind,
  field: FlowField | null,
  isLand: ((lon: number, lat: number) => boolean) | null,
): void {
  let p = randomLonLat()
  // Ocean particles may only start where the current field exists and the
  // underlying cell is water; wind is defined over land and sea alike.
  if (kind === 'current' && field) {
    for (let attempt = 0; attempt < 8; attempt++) {
      const inField = sampleFlow(field, p.lon, p.lat, _sample)
      const onLand = isLand ? isLand(p.lon, p.lat) : false
      if (inField && !onLand) break
      p = randomLonLat()
    }
  }
  state.lon[i] = p.lon
  state.lat[i] = p.lat
  state.prevLon[i] = p.lon
  state.prevLat[i] = p.lat
  state.age[i] = 0
  state.life[i] = kind === 'wind' ? 6 + Math.random() * 9 : 8 + Math.random() * 10
  state.hasLast[i] = 0
}

function windColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t))
  // Blue (slow) → green → yellow → red (fast), matching the nullschool idiom.
  return `hsl(${230 - 230 * clamped}, 88%, 56%)`
}

function currentColor(aux: number): string {
  return aux > 0 ? '#e040fb' : '#00bcd4'
}

export default function FlowParticles({
  projectRef,
  kind,
  cells,
  opacity,
  monthlyWindEast = null,
  monthlyWindNorth = null,
  month = 0,
  planetRadiusM = EARTH_RADIUS_M,
  cellIdMap = null,
  meshWidth = 0,
  meshHeight = 0,
  positioning = 'fixed',
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const particlesRef = useRef<ParticleState | null>(null)
  const lastTimeRef = useRef(0)
  const epochRef = useRef(-1)
  const sizeRef = useRef({ width: 0, height: 0 })

  // The engine writes cell IDs as 0..N-1; only build an ID→cell map when that
  // fast path does not hold, so the common case costs no extra memory.
  const cellById = useMemo(() => {
    if (cells.length === 0) return null
    if (cells[0].id === 0 && cells[cells.length - 1].id === cells.length - 1) return null
    const byId = new Map<number, VoronoiCell>()
    for (const c of cells) byId.set(c.id, c)
    return byId
  }, [cells])

  /** True when the cell under a geographic point is land (ocean particles only). */
  const isLand = useCallback((lon: number, lat: number): boolean => {
    const id = sampleCellId(cellIdMap, meshWidth, meshHeight, lon, lat)
    if (id < 0) return false
    const cell = cellById ? cellById.get(id) : cells[id]
    return cell?.water_class === 'land'
  }, [cellIdMap, meshWidth, meshHeight, cellById, cells])

  const field = useMemo(() => {
    if (cells.length === 0) return null
    const built = buildFlowField({
      kind,
      cells,
      monthlyWindEast,
      monthlyWindNorth,
      month,
    })
    return built.maxSpeed > 0 ? built : null
  }, [cells, kind, monthlyWindEast, monthlyWindNorth, month])

  const active = opacity > 0 && field !== null

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const project = projectRef.current
    if (!project) return

    // --- Size / position the overlay against the viewer canvas ------------
    let width = 0
    let height = 0
    if (positioning === 'fixed') {
      // Both the mobile and desktop layouts are mounted; only one R3F canvas
      // has a non-zero rect.  Align to that one (querySelector would pick the
      // hidden mobile canvas first).
      let source: HTMLCanvasElement | null = null
      for (const candidate of document.querySelectorAll('canvas[data-engine]')) {
        const rect = candidate.getBoundingClientRect()
        if (rect.width > 1 && rect.height > 1) {
          source = candidate as HTMLCanvasElement
          break
        }
      }
      if (!source) return
      const rect = source.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.style.left = `${rect.left}px`
      canvas.style.top = `${rect.top}px`
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
    } else {
      const parent = canvas.parentElement
      if (!parent) return
      width = parent.clientWidth
      height = parent.clientHeight
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
    }
    if (width <= 0 || height <= 0) return
    // Skip the duplicate instance living in the hidden (mobile/desktop) layout.
    const ownRect = canvas.getBoundingClientRect()
    if (ownRect.width <= 1 || ownRect.height <= 1) return

    const dpr = Math.min(2, window.devicePixelRatio || 1)
    const pixelW = Math.max(1, Math.round(width * dpr))
    const pixelH = Math.max(1, Math.round(height * dpr))
    const resized = canvas.width !== pixelW || canvas.height !== pixelH
    if (resized) {
      canvas.width = pixelW
      canvas.height = pixelH
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    // --- Particle state ----------------------------------------------------
    const count = kind === 'wind' ? WIND_PARTICLES : CURRENT_PARTICLES
    let particles = particlesRef.current
    if (!particles || particles.count !== count) {
      particles = makeParticles(count, kind, field, kind === 'current' ? isLand : null)
      particlesRef.current = particles
    }

    const now = performance.now()
    const last = lastTimeRef.current
    lastTimeRef.current = now
    // Cap the step so a background tab / long frame does not teleport every
    // particle across the planet (and keeps the RK2 midpoint meaningful).
    const dt = last > 0 ? Math.min(0.05, Math.max(0, (now - last) / 1000)) : 0

    const epoch = project.epoch ?? 0
    const moved = epoch !== epochRef.current || resized ||
      sizeRef.current.width !== width || sizeRef.current.height !== height
    epochRef.current = epoch
    sizeRef.current = { width, height }

    if (moved) {
      // The old trails were painted under the previous view; clear them.  The
      // particles themselves stay visible: this frame's segment is drawn from
      // the previous lon/lat projected under the *new* view.
      ctx.clearRect(0, 0, width, height)
    } else {
      // Fade old segments; a static view accumulates a persistent tail.
      ctx.globalCompositeOperation = 'destination-out'
      ctx.fillStyle = 'rgba(0, 0, 0, 0.03)'
      ctx.fillRect(0, 0, width, height)
      ctx.globalCompositeOperation = 'source-over'
    }

    if (dt <= 0 || !field) return

    const simSeconds = dt * (
      kind === 'wind'
        ? WIND_SIM_SECONDS_PER_REAL_SECOND
        : CURRENT_SIM_SECONDS_PER_REAL_SECOND
    )
    const bins = kind === 'wind' ? WIND_BINS : CURRENT_BINS
    const maxSpeed = field.maxSpeed > 0 ? field.maxSpeed : 1
    const wrapWidth = positioning === 'fixed' ? Infinity : width * 0.5
    const checkLand = kind === 'current'

    // --- Advect + project one step ----------------------------------------
    for (let i = 0; i < count; i++) {
      particles.age[i] += dt
      let ok = particles.age[i] <= particles.life[i]
      // The vector grid is a coarse 2° average and can bridge small islands;
      // the cell-ID raster is the authoritative per-point land check.
      if (ok && checkLand && isLand(particles.lon[i], particles.lat[i])) ok = false
      if (ok) {
        ok = advectParticle(
          field,
          particles.lon[i],
          particles.lat[i],
          planetRadiusM,
          simSeconds,
          _advect,
        )
        if (ok && checkLand && isLand(_advect.lon, _advect.lat)) ok = false
      }
      if (!ok) {
        respawnParticle(particles, i, kind, field, checkLand ? isLand : null)
        particles.hasSegment[i] = 0
        continue
      }

      const prevLon = particles.lon[i]
      const prevLat = particles.lat[i]
      particles.prevLon[i] = prevLon
      particles.prevLat[i] = prevLat
      const hadLast = particles.hasLast[i] === 1
      particles.lon[i] = _advect.lon
      particles.lat[i] = _advect.lat

      const visible = project(_advect.lon, _advect.lat, _screen)
      if (!visible || _screen.edgeFade < 0.02) {
        particles.hasLast[i] = 0
        particles.hasSegment[i] = 0
        continue
      }

      // While the camera/view moves, project the previous geographic position
      // under the new view so the particle still draws a one-frame streak
      // instead of vanishing until the view settles.
      let startOk = false
      if (moved) {
        if (project(prevLon, prevLat, _screenPrev) && _screenPrev.edgeFade >= 0.02) {
          const rawDx = _screen.x - _screenPrev.x
          const rawDy = _screen.y - _screenPrev.y
          const rawLen = Math.hypot(rawDx, rawDy)
          if (rawLen > 0.05) {
            // Extend the one-frame motion to a visible streak; the direction is
            // still the particle's own screen-space velocity.
            const scale = Math.max(1, MOVED_MIN_STREAK_PX / rawLen)
            particles.prevX[i] = _screen.x - rawDx * scale
            particles.prevY[i] = _screen.y - rawDy * scale
          } else {
            // Calm cell: a sub-pixel dot still keeps the particle visible.
            particles.prevX[i] = _screen.x - 0.6
            particles.prevY[i] = _screen.y
          }
          startOk = true
        }
      } else if (hadLast) {
        particles.prevX[i] = particles.lastX[i]
        particles.prevY[i] = particles.lastY[i]
        startOk = true
      }

      particles.lastX[i] = _screen.x
      particles.lastY[i] = _screen.y
      particles.hasLast[i] = 1
      if (!startOk) {
        particles.hasSegment[i] = 0
        continue
      }

      const dx = _screen.x - particles.prevX[i]
      const dy = _screen.y - particles.prevY[i]
      // A respawned particle has prev == current; drawing a zero-length
      // segment would only add a stray dot.
      if (dx * dx + dy * dy < 0.0004) {
        particles.hasSegment[i] = 0
        continue
      }
      // 2D maps wrap at the date line; a segment spanning the whole viewport
      // is a wrap artefact, not motion.
      if (Math.abs(dx) > wrapWidth) {
        particles.hasSegment[i] = 0
        continue
      }

      particles.hasSegment[i] = 1
      if (kind === 'wind') {
        // sqrt spreads typical (mid-speed) winds across the green/yellow part
        // of the ramp instead of leaving almost everything dark blue.
        const t = Math.sqrt(Math.min(1, _advect.speed / maxSpeed))
        particles.bin[i] = Math.min(WIND_BINS - 1, Math.floor(t * WIND_BINS))
      } else {
        particles.bin[i] = _advect.aux > 0 ? 0 : 1
      }
    }

    // --- Batched stroke (one path per colour bin) --------------------------
    ctx.globalAlpha = Math.min(1, opacity)
    ctx.lineWidth = kind === 'wind' ? 1.25 : 1.45
    ctx.lineCap = 'round'
    for (let b = 0; b < bins; b++) {
      let any = false
      for (let i = 0; i < count; i++) {
        if (particles.hasSegment[i] === 1 && particles.bin[i] === b) { any = true; break }
      }
      if (!any) continue
      ctx.strokeStyle = kind === 'wind'
        ? windColor((b + 0.5) / WIND_BINS)
        : (b === 0 ? currentColor(1) : currentColor(-1))
      ctx.beginPath()
      for (let i = 0; i < count; i++) {
        if (particles.hasSegment[i] !== 1 || particles.bin[i] !== b) continue
        ctx.moveTo(particles.prevX[i], particles.prevY[i])
        ctx.lineTo(particles.lastX[i], particles.lastY[i])
      }
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }, [field, isLand, kind, opacity, planetRadiusM, positioning, projectRef])

  useEffect(() => {
    if (!active) return
    let raf = 0
    const loop = () => {
      draw()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [active, draw])

  if (!active) return null

  return (
    <canvas
      ref={canvasRef}
      className={positioning === 'fixed'
        ? 'pointer-events-none'
        : 'pointer-events-none absolute inset-0'}
      style={positioning === 'fixed'
        ? { position: 'fixed', zIndex: 10, left: 0, top: 0 }
        : { zIndex: 1 }}
    />
  )
}
