/** SkyBackground — the universe-setting layer: seeded/authored star dots,
 *  deep-sky sprites and the galactic band (the planetarium posture: a static
 *  direction+magnitude catalogue rotated into the observer frame, never
 *  propagated).  Directions arrive as ecliptic-frame unit vectors; the same
 *  fitted rotation that powers the ecliptic grid turns them into ENU, then
 *  the active projector places them.  Everything is pointer-transparent —
 *  the background never intercepts a body click.
 */

import { useMemo } from 'react'

import { applyMat3, type Mat3 } from './frameFit'
import { starColorCss } from './bodyColor'
import type { ProjectDir } from './graticule'
import type { Vec3 } from './panProjector'
import type { SkyBackground } from './types'

/** Limiting magnitude rises as the field narrows (the zoom-linked limit
 *  planetariums use): a tighter field earns ~2 magnitudes of depth at 9×. */
export function backgroundLimit(baseLimit: number, fovDeg: number | null): number {
  const boost = fovDeg === null ? 1 : Math.max(0, 2 * Math.log10(90 / fovDeg))
  return baseLimit + Math.min(boost, 4)
}

/** Star dot radius in chart pixels: brighter = bigger, clamped to a point
 *  source.  Calibrated BELOW the system-body scale on purpose: the faintest
 *  system body (a −5 mag moon) outshines the brightest background star by
 *  ~100×, and the chart must read that hierarchy. */
export function starDotRadius(magnitude: number, limit: number): number {
  return Math.min(2.4, Math.max(0.5, 0.5 + (limit - magnitude) * 0.28))
}

/** Star dot opacity: the naked-eye fade, capped well below a lit planet disc. */
export function starDotAlpha(magnitude: number, limit: number): number {
  return Math.min(0.8, Math.max(0.1, 0.12 + (limit - magnitude) * 0.11))
}

export interface SkyBackgroundLayerProps {
  background: SkyBackground
  /** Ecliptic → ENU rotation fitted from the live result; null skips the layer. */
  rotation: Mat3 | null
  project: ProjectDir
  /** Vertical field of view in degrees; null = the all-sky disc. */
  fovDeg: number | null
  /** Pixel height of the view (deep-sky sprite scale). */
  height: number
}

function perpendicularBasis(pole: Vec3): [Vec3, Vec3] {
  const seed: Vec3 = Math.abs(pole.u) < 0.9 ? { e: 0, n: 0, u: 1 } : { e: 1, n: 0, u: 0 }
  const dot = seed.e * pole.e + seed.n * pole.n + seed.u * pole.u
  const e1raw: Vec3 = { e: seed.e - dot * pole.e, n: seed.n - dot * pole.n, u: seed.u - dot * pole.u }
  const len = Math.hypot(e1raw.e, e1raw.n, e1raw.u)
  const e1: Vec3 = { e: e1raw.e / len, n: e1raw.n / len, u: e1raw.u / len }
  const e2: Vec3 = {
    e: pole.n * e1.u - pole.u * e1.n,
    n: pole.u * e1.e - pole.e * e1.u,
    u: pole.e * e1.n - pole.n * e1.e,
  }
  return [e1, e2]
}

export default function SkyBackgroundLayer({
  background,
  rotation,
  project,
  fovDeg,
  height,
}: SkyBackgroundLayerProps) {
  const limit = useMemo(
    () => backgroundLimit(background.starfield.magnitude_limit, fovDeg),
    [background, fovDeg],
  )

  const stars = useMemo(() => {
    if (!rotation) return []
    return background.stars
      .filter((star) => star.magnitude <= limit)
      .map((star) => ({
        star,
        point: project(applyMat3(rotation, { e: star.unit[0], n: star.unit[1], u: star.unit[2] })),
      }))
      .filter((entry) => entry.point !== null)
  }, [background, rotation, project, limit])

  const dsos = useMemo(() => {
    if (!rotation) return []
    const degPerPx = (fovDeg ?? 120) / height
    return background.deep_sky
      .map((dso) => ({
        dso,
        point: project(applyMat3(rotation, { e: dso.unit[0], n: dso.unit[1], u: dso.unit[2] })),
        sizePx: Math.max(4, dso.angular_size_deg / degPerPx),
      }))
      .filter((entry) => entry.point !== null)
  }, [background, rotation, project, fovDeg, height])

  const bandPath = useMemo(() => {
    if (!rotation || !background.galactic_band) return ''
    const pole: Vec3 = {
      e: background.galactic_band.pole_unit[0],
      n: background.galactic_band.pole_unit[1],
      u: background.galactic_band.pole_unit[2],
    }
    const [e1, e2] = perpendicularBasis(pole)
    const segments: string[] = []
    let current: string[] = []
    for (let deg = 0; deg <= 360; deg += 3) {
      const theta = (deg * Math.PI) / 180
      const dir: Vec3 = {
        e: Math.cos(theta) * e1.e + Math.sin(theta) * e2.e,
        n: Math.cos(theta) * e1.n + Math.sin(theta) * e2.n,
        u: Math.cos(theta) * e1.u + Math.sin(theta) * e2.u,
      }
      const point = project(applyMat3(rotation, dir))
      if (point) current.push(`${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
      else if (current.length > 1) {
        segments.push(`M ${current.join(' L ')}`)
        current = []
      } else current = []
    }
    if (current.length > 1) segments.push(`M ${current.join(' L ')}`)
    return segments.join(' ')
  }, [background, rotation, project])

  const bandWidthPx =
    background.galactic_band && fovDeg
      ? (background.galactic_band.width_deg / fovDeg) * height
      : background.galactic_band
        ? (background.galactic_band.width_deg / 150) * height
        : 0

  return (
    <g pointerEvents="none">
      <defs>
        <radialGradient id="dso-glow">
          <stop offset="0%" stopColor="rgba(255,255,255,0.55)" />
          <stop offset="60%" stopColor="rgba(210,220,255,0.18)" />
          <stop offset="100%" stopColor="rgba(210,220,255,0)" />
        </radialGradient>
        <filter id="band-blur" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation={Math.max(3, bandWidthPx / 5)} />
        </filter>
      </defs>

      {/* Galactic band: a soft blurred great-circle stroke (procedural, not a texture) */}
      {bandPath && (
        <path
          d={bandPath}
          fill="none"
          stroke={`rgba(226,232,255,${0.3 * (background.galactic_band?.brightness ?? 0.35)})`}
          strokeWidth={bandWidthPx}
          filter="url(#band-blur)"
        />
      )}

      {/* Deep-sky sprites */}
      {dsos.map(({ dso, point, sizePx }) => (
        <g key={dso.id} opacity={Math.min(0.9, Math.max(0.25, (9 - dso.magnitude) / 6))}>
          <ellipse cx={point!.x} cy={point!.y} rx={sizePx} ry={sizePx * (dso.type === 'galaxy' ? 0.55 : 0.8)} fill="url(#dso-glow)" />
          {(dso.type === 'remnant' || dso.type === 'galaxy') && (
            <ellipse
              cx={point!.x}
              cy={point!.y}
              rx={sizePx * 0.85}
              ry={sizePx * (dso.type === 'galaxy' ? 0.4 : 0.68)}
              fill="none"
              stroke="rgba(255,255,255,0.3)"
              strokeWidth={0.8}
            />
          )}
        </g>
      ))}

      {/* Star dots (point sources, colour = temperature, alpha = naked-eye fade) */}
      {stars.map(({ star, point }) => (
        <circle
          key={star.id}
          cx={point!.x}
          cy={point!.y}
          r={starDotRadius(star.magnitude, limit)}
          fill={starColorCss(star.temperature_k)}
          opacity={starDotAlpha(star.magnitude, limit)}
        />
      ))}
    </g>
  )
}
