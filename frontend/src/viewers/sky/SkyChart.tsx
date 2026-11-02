/** SkyChart — the all-sky overview disc: azimuthal-equidistant projection
 *  (radius linear in zenith distance), looking-up convention (N top, E left).
 *  The default sky view is the pan view (SkyPanChart); this disc answers
 *  "where is everything right now" at a glance and hosts the rise/set
 *  structure.  The pan view's current look direction is drawn as a crosshair.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import {
  ALTITUDE_RING_DEGREES,
  skyProjector,
  type SkyProjector,
} from './projector'
import { estimateTextWidth, layoutLabels, type Box, type LabelItem } from './labelLayout'
import { markerRadius } from './phaseGeometry'
import { buildMarkers, isOccultedMarker, labeledIds, type Marker } from './markers'
import { buildGridLayers, type GridToggles } from './skyGrids'
import SkyBodyMarker from './SkyBodyMarker'
import { NORTH_ACCENT, SELECTED_STROKE, TEXT_HALO } from './bodyColor'
import { altAzFromDir, type LookDirection } from './panProjector'
import type { SkyCatalog, SkyEphemerisResult } from './types'

const VIEW = 640
const RADIUS = 268
const GROUND_BAND = 1.08

export interface SkyChartProps {
  result: SkyEphemerisResult
  catalog: SkyCatalog | undefined
  selectedId: string | null
  hoveredId: string | null
  onHover: (bodyId: string | null) => void
  onSelect: (bodyId: string) => void
  /** The pan view's look direction, drawn as a crosshair (overview aid). */
  look?: LookDirection | null
  /** Overlay grids (horizon / equatorial / ecliptic). */
  grids: GridToggles
}

export default function SkyChart({
  result,
  catalog,
  selectedId,
  hoveredId,
  onHover,
  onSelect,
  look,
  grids,
}: SkyChartProps) {
  const { t } = useTranslation('sky')
  const projector = useMemo(() => skyProjector(VIEW / 2, VIEW / 2, RADIUS), [])

  const { markers } = useMemo(() => {
    const maxDeg = Math.max(...result.targets.map((r) => r.angular_diameter_deg), 1e-6)
    // Unclipped projection + the horizon-circle clipPath below: a setting
    // giant keeps its above-horizon sliver instead of popping out whole.
    return buildMarkers(result, catalog, (alt, az) => {
      const point = projector.projectUnclipped(alt, az)
      return point
    }, (d) => markerRadius(d, maxDeg))
  }, [result, catalog, projector])

  const gridLayers = useMemo(
    () =>
      buildGridLayers(
        result,
        (v) => {
          const { altDeg, azDeg } = altAzFromDir(v)
          return projector.project(altDeg, azDeg)
        },
        grids,
      ),
    [result, projector, grids],
  )

  const labelled = useMemo(
    () => labeledIds(markers, selectedId, hoveredId),
    [markers, selectedId, hoveredId],
  )

  const cardinalPoints = useMemo(() => {
    const map = new Map<'N' | 'E' | 'S' | 'W', { x: number; y: number; text: string }>()
    for (const dir of ['N', 'E', 'S', 'W'] as const) {
      const point = cardinalPoint(projector, dir)
      map.set(dir, { ...point, text: t(`chart.cardinal.${dir}`) })
    }
    return map
  }, [projector, t])

  const lookPoint = useMemo(
    () => (look ? projector.project(look.altDeg, look.azDeg) : null),
    [look, projector],
  )

  const labelPlacements = useMemo(() => {
    // Priority order: selected, hovered, then brightest (stable sort keeps
    // the magnitude order markers already carries).
    const items: LabelItem[] = markers
      .filter((m) => labelled.has(m.row.body_id))
      .sort((a, b) => {
        const rank = (id: string) => (id === selectedId ? 0 : id === hoveredId ? 1 : 2)
        return rank(a.row.body_id) - rank(b.row.body_id)
      })
      .map((m) => ({
        id: m.row.body_id,
        x: m.x,
        y: m.y,
        radius: m.radius,
        text: m.row.name ?? m.row.body_id,
        fontSize: 11,
      }))
    // Static obstacles: the four cardinal captions and the zenith caption.
    const obstacles: Box[] = []
    for (const card of cardinalPoints.values()) {
      const half = estimateTextWidth(card.text, 16) / 2 + 2
      obstacles.push({ left: card.x - half, right: card.x + half, top: card.y - 11, bottom: card.y + 11 })
    }
    const zenithWidth = estimateTextWidth(t('chart.zenith'), 10)
    obstacles.push({
      left: VIEW / 2 + 10,
      right: VIEW / 2 + 14 + zenithWidth,
      top: VIEW / 2 - 19,
      bottom: VIEW / 2 - 7,
    })
    return layoutLabels(items, obstacles)
  }, [markers, labelled, selectedId, hoveredId, cardinalPoints, t])

  return (
    <svg viewBox={`0 0 ${VIEW} ${VIEW}`} className="w-full h-full select-none">
        <defs>
          <clipPath id="disc-region">
            <circle cx={VIEW / 2} cy={VIEW / 2} r={RADIUS} />
          </clipPath>
        </defs>
        {/* Ground band + horizon */}
        <circle
          cx={VIEW / 2}
          cy={VIEW / 2}
          r={RADIUS * GROUND_BAND}
          fill="#0d0d22"
          stroke="none"
        />
        <circle
          cx={VIEW / 2}
          cy={VIEW / 2}
          r={RADIUS}
          fill="#030308"
          stroke="rgba(255,255,255,0.28)"
          strokeWidth={1}
        />

        {/* Overlay grids (segments break at the horizon via null projection) */}
        {gridLayers.map((layer, i) => (
          <path
            key={i}
            d={layer.d}
            fill="none"
            stroke={layer.stroke}
            strokeWidth={layer.width ?? 1}
            strokeDasharray={layer.dash}
            pointerEvents="none"
          />
        ))}
        {/* Altitude rings (r linear in zenith distance) + zenith mark */}
        {ALTITUDE_RING_DEGREES.map((alt) => (
          <circle
            key={alt}
            cx={VIEW / 2}
            cy={VIEW / 2}
            r={projector.radiusOf(90 - alt)}
            fill="none"
            stroke="rgba(255,255,255,0.14)"
            strokeWidth={1}
            strokeDasharray="4 6"
          />
        ))}
        <line x1={VIEW / 2 - 6} y1={VIEW / 2} x2={VIEW / 2 + 6} y2={VIEW / 2} stroke="rgba(255,255,255,0.2)" />
        <line x1={VIEW / 2} y1={VIEW / 2 - 6} x2={VIEW / 2} y2={VIEW / 2 + 6} stroke="rgba(255,255,255,0.2)" />
        <text x={VIEW / 2 + 12} y={VIEW / 2 - 10} fontSize={10} fill="rgba(255,255,255,0.35)" {...TEXT_HALO}>
          {t('chart.zenith')}
        </text>

        {/* Cardinals — N carries the accent (compass convention), E LEFT. */}
        {(['N', 'E', 'S', 'W'] as const).map((dir) => {
          const point = cardinalPoints.get(dir)!
          return (
            <text
              key={dir}
              x={point.x}
              y={point.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize={16}
              fontWeight={600}
              fill={dir === 'N' ? NORTH_ACCENT : 'rgba(255,255,255,0.5)'}
              {...TEXT_HALO}
              strokeWidth={3}
            >
              {point.text}
            </text>
          )
        })}

        {/* Body markers, clipped to the horizon circle */}
        <g clipPath="url(#disc-region)">
        {markers.map((m: Marker) => {
          const selected = m.row.body_id === selectedId
          const hovered = m.row.body_id === hoveredId
          return (
            <g key={m.row.body_id}>
              <SkyBodyMarker
                x={m.x}
                y={m.y}
                radius={m.radius}
                fill={m.fill}
                brightAngle={m.brightAngle}
                isStar={m.isStar}
                illuminatedFraction={m.row.illuminated_fraction}
                selected={selected}
                hovered={hovered}
                dimmed={m.row.apparent_magnitude >= 6 && !hovered && !selected}
                onHover={onHover}
                onSelect={onSelect}
                bodyId={m.row.body_id}
              />
              {m.row.altitude_deg > 0 && !isOccultedMarker(markers, m) && labelPlacements.has(m.row.body_id) &&
                (() => {
                  const placement = labelPlacements.get(m.row.body_id)!
                  return (
                    <text
                      x={m.x + placement.dx}
                      y={m.y + placement.dy}
                      textAnchor={placement.anchor}
                      fontSize={11}
                      fill={selected ? SELECTED_STROKE : 'rgba(255,255,255,0.78)'}
                      {...TEXT_HALO}
                    >
                      {m.row.name ?? m.row.body_id}
                    </text>
                  )
                })()}
            </g>
          )
        })}
        </g>

        {/* Pan-view look direction crosshair */}
        {lookPoint && (
          <g pointerEvents="none">
            <circle cx={lookPoint.x} cy={lookPoint.y} r={7} fill="none" stroke="#f0c040" strokeWidth={1.4} />
            <circle cx={lookPoint.x} cy={lookPoint.y} r={1.6} fill="#f0c040" />
          </g>
        )}
    </svg>
  )
}

function cardinalPoint(projector: SkyProjector, dir: 'N' | 'E' | 'S' | 'W'): { x: number; y: number } {
  const az = { N: 0, E: 90, S: 180, W: 270 }[dir]
  const point = projector.project(0, az)!
  const inward = (point.x - projector.cx) * 0.86 + projector.cx
  const inwardY = (point.y - projector.cy) * 0.86 + projector.cy
  return { x: inward, y: inwardY }
}
