/** SkyBackground — the universe-setting layer: seeded/authored star dots,
 *  deep-sky sprites and the galactic band (the planetarium posture: a static
 *  direction+magnitude catalogue rotated into the observer frame, never
 *  propagated).  Directions arrive as ecliptic-frame unit vectors; the same
 *  fitted rotation that powers the ecliptic grid turns them into ENU, then
 *  the active projector places them.
 *
 *  With `interactive`, authored stars and deep-sky sprites carry invisible
 *  hit targets: hover shows a name tag and click selects the object (the
 *  chart resolves the press target via data-bg-id — pointer capture never
 *  delivers a plain click to the circle).  Procedural field stars stay
 *  pointer-transparent, as does everything when interactive is off.
 */

import { useMemo, useState } from 'react'

import { applyMat3, type Mat3 } from './frameFit'
import { starColorCss } from './bodyColor'
import { backgroundLimit, starDotRadius, starDotAlpha } from './backgroundStars'
import type { ProjectDir } from './graticule'
import type { Vec3 } from './panProjector'
import type { SkyBackground } from './types'

export interface SkyBackgroundLayerProps {
  background: SkyBackground
  /** Ecliptic → ENU rotation fitted from the live result; null skips the layer. */
  rotation: Mat3 | null
  project: ProjectDir
  /** Vertical field of view in degrees; null = the all-sky disc. */
  fovDeg: number | null
  /** Pixel height of the view (deep-sky sprite scale). */
  height: number
  /** Hover/click targets on authored stars and DSOs (the pan view). */
  interactive?: boolean
  /** Selected background-object id — draws the selection ring. */
  selectedBgId?: string | null
}

const HALO = {
  stroke: 'rgba(4,8,18,0.85)',
  strokeWidth: 2.6,
  paintOrder: 'stroke',
} as const

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
  interactive = false,
  selectedBgId = null,
}: SkyBackgroundLayerProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
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
      {dsos.map(({ dso, point, sizePx }) => {
        const marked = interactive && (hoveredId === dso.id || selectedBgId === dso.id)
        return (
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
            {marked && (
              <ellipse
                cx={point!.x}
                cy={point!.y}
                rx={Math.max(sizePx * 1.15, 9)}
                ry={Math.max(sizePx * (dso.type === 'galaxy' ? 0.7 : 1.0), 8)}
                fill="none"
                stroke="rgba(126,200,227,0.9)"
                strokeWidth={1.2}
              />
            )}
            {interactive && (
              <circle
                cx={point!.x}
                cy={point!.y}
                r={Math.max(9, sizePx * 0.7)}
                fill="transparent"
                pointerEvents="all"
                data-bg-id={dso.id}
                onMouseEnter={() => setHoveredId(dso.id)}
                onMouseLeave={() => setHoveredId(null)}
              />
            )}
            {marked && (
              <text
                x={point!.x + Math.max(sizePx * 1.15, 9) + 4}
                y={point!.y - 6}
                fontSize={11}
                fill="rgba(255,255,255,0.85)"
                {...HALO}
              >
                {dso.name ?? dso.id} · {dso.angular_size_deg.toFixed(1)}°
              </text>
            )}
          </g>
        )
      })}

      {/* Star dots (point sources, colour = temperature, alpha = naked-eye fade) */}
      {stars.map(({ star, point }) => {
        const authored = star.source === 'authored'
        const marked = interactive && authored && (hoveredId === star.id || selectedBgId === star.id)
        return (
          <g key={star.id}>
            <circle
              cx={point!.x}
              cy={point!.y}
              r={starDotRadius(star.magnitude, limit)}
              fill={starColorCss(star.temperature_k)}
              opacity={starDotAlpha(star.magnitude, limit)}
            />
            {marked && (
              <circle
                cx={point!.x}
                cy={point!.y}
                r={Math.max(starDotRadius(star.magnitude, limit) + 3.5, 6)}
                fill="none"
                stroke="rgba(126,200,227,0.9)"
                strokeWidth={1.2}
              />
            )}
            {interactive && authored && (
              <circle
                cx={point!.x}
                cy={point!.y}
                r={9}
                fill="transparent"
                pointerEvents="all"
                data-bg-id={star.id}
                onMouseEnter={() => setHoveredId(star.id)}
                onMouseLeave={() => setHoveredId(null)}
              />
            )}
            {marked && (
              <text
                x={point!.x + 11}
                y={point!.y - 8}
                fontSize={11}
                fill="rgba(255,255,255,0.85)"
                {...HALO}
              >
                {star.name ?? star.id} · {star.magnitude.toFixed(1)}ᵐ
              </text>
            )}
          </g>
        )
      })}
    </g>
  )
}
