/** SkyCultureLayer — constellation figures from the civilization layer's sky
 *  cultures (the Stellarium sky-culture posture).  The culture file carries
 *  ids only; this layer joins them against the background catalogue, samples
 *  each edge along the great circle, and rotates+projects the samples through
 *  the same fitted frame as the background stars.  Figures sit above the star
 *  dots and below the coordinate grids.
 *
 *  With `interactive`, each figure carries a wide transparent hit path: hover
 *  brightens it and shows the culture's asterism name, and a tap selects it
 *  through the same data-bg-id namespace as authored stars/DSOs (the ids are
 *  disjoint by construction).
 */

import { useMemo, useState } from 'react'

import { applyMat3, type Mat3 } from './frameFit'
import type { ProjectDir } from './graticule'
import { buildAsterismGeometry, buildCultureLookup, type AsterismGeometry } from './skyCulture'
import type { SkyBackground, SkyCulture } from './types'

export interface SkyCultureLayerProps {
  culture: SkyCulture
  /** Position source for the referenced ids (the universe-setting catalogue). */
  background: SkyBackground
  /** Ecliptic → ENU rotation fitted from the live result; null skips the layer. */
  rotation: Mat3 | null
  project: ProjectDir
  /** Hover/click targets on the figures (the pan view). */
  interactive?: boolean
  /** Selected background-object id — keeps its figure bright + labelled. */
  selectedBgId?: string | null
}

const LINE_COLOR = 'rgba(255,214,170,0.35)'
const LINE_COLOR_MARKED = 'rgba(255,214,170,0.85)'
const LABEL_COLOR = 'rgba(255,224,190,0.95)'
const HALO = {
  stroke: 'rgba(4,8,18,0.85)',
  strokeWidth: 2.6,
  paintOrder: 'stroke',
} as const

export default function SkyCultureLayer({
  culture,
  background,
  rotation,
  project,
  interactive = false,
  selectedBgId = null,
}: SkyCultureLayerProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  const geometries = useMemo(() => {
    const lookup = buildCultureLookup(background)
    const out: AsterismGeometry[] = []
    for (const entry of culture.cultures) {
      for (const asterism of entry.asterisms) {
        const geometry = buildAsterismGeometry(entry, asterism, lookup)
        if (geometry) out.push(geometry)
      }
    }
    return out
  }, [culture, background])

  const figures = useMemo(() => {
    if (!rotation) return []
    return geometries
      .map((geometry) => {
        const segments: string[] = []
        for (const edge of geometry.edges) {
          let current: string[] = []
          for (const sample of edge) {
            const point = project(applyMat3(rotation, sample))
            if (point) {
              current.push(`${point.x.toFixed(1)} ${point.y.toFixed(1)}`)
            } else if (current.length > 1) {
              segments.push(`M ${current.join(' L ')}`)
              current = []
            } else {
              current = []
            }
          }
          if (current.length > 1) segments.push(`M ${current.join(' L ')}`)
        }
        const labelPoint = geometry.centroid ? project(applyMat3(rotation, geometry.centroid)) : null
        return { geometry, d: segments.join(' '), labelPoint }
      })
      .filter((figure) => figure.d !== '')
  }, [geometries, rotation, project])

  return (
    <g pointerEvents="none">
      {figures.map(({ geometry, d, labelPoint }) => {
        const marked =
          interactive && (hoveredId === geometry.asterism.id || selectedBgId === geometry.asterism.id)
        return (
          <g key={geometry.asterism.id}>
            <path
              d={d}
              fill="none"
              stroke={marked ? LINE_COLOR_MARKED : LINE_COLOR}
              strokeWidth={marked ? 1.6 : 1.1}
              strokeLinecap="round"
            />
            {interactive && (
              <path
                d={d}
                fill="none"
                stroke="transparent"
                strokeWidth={14}
                pointerEvents="all"
                data-bg-id={geometry.asterism.id}
                onMouseEnter={() => setHoveredId(geometry.asterism.id)}
                onMouseLeave={() => setHoveredId(null)}
              />
            )}
            {marked && labelPoint && (
              <text
                x={labelPoint.x}
                y={labelPoint.y - 10}
                fontSize={12}
                textAnchor="middle"
                fill={LABEL_COLOR}
                {...HALO}
              >
                {geometry.asterism.name}
              </text>
            )}
          </g>
        )
      })}
    </g>
  )
}
