/** SkyPanChart — the immersive look-around view (the Stellarium posture):
 *  a perspective patch of sky filling the whole viewport, dragged to turn,
 *  wheeled/pinched to zoom the field.  Looking around is pure client-side
 *  projection of the engine result — no fetch; only the instant (time
 *  slider) queries the server.  The chart renders ONLY the sky: ground,
 *  grids, cardinals and markers — every surrounding control lives in the
 *  page's auto-hiding chrome.  A clean tap selects the tapped body (pointer
 *  capture retargets clicks, so selection is resolved from the press target);
 *  a tap on empty sky reports to onBackgroundSelect.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  clampLook,
  enuFromAltAz,
  fovFromPinch,
  groundPath,
  horizonPath,
  lookFromDrag,
  panProjector,
  type LookDirection,
  type ScreenPoint,
} from './panProjector'
import { estimateTextWidth, layoutLabels, type Box, type LabelItem } from './labelLayout'
import { buildMarkers, isOccultedMarker, labeledIds, type Marker } from './markers'
import { buildGridLayers, type GridToggles } from './skyGrids'
import SkyBodyMarker from './SkyBodyMarker'
import { GROUND_FILL, NORTH_ACCENT, SELECTED_STROKE, TEXT_HALO } from './bodyColor'
import type { SkyCatalog, SkyEphemerisResult } from './types'

const CARDINALS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const
const CARDINAL_AZ = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 } as const
const DRAG_THRESHOLD_PX = 4

export interface SkyPanChartProps {
  result: SkyEphemerisResult
  catalog: SkyCatalog | undefined
  /** Pixel size of the filled area (drives the viewBox and the projection). */
  width: number
  height: number
  look: LookDirection
  /** Live update while dragging/zooming (no URL write). */
  onLookChange: (look: LookDirection) => void
  /** Gesture ended with changes — commit to the URL. */
  onLookCommit: () => void
  grids: GridToggles
  selectedId: string | null
  hoveredId: string | null
  onHover: (bodyId: string | null) => void
  onSelect: (bodyId: string) => void
  /** Clean tap on empty sky (deselect). */
  onBackgroundSelect?: () => void
}

export default function SkyPanChart({
  result,
  catalog,
  width,
  height,
  look,
  onLookChange,
  onLookCommit,
  grids,
  selectedId,
  hoveredId,
  onHover,
  onSelect,
  onBackgroundSelect,
}: SkyPanChartProps) {
  const { t } = useTranslation('sky')
  const svgRef = useRef<SVGSVGElement>(null)
  const pointers = useRef(new Map<number, ScreenPoint>())
  const dragStart = useRef<{ look: LookDirection; px: ScreenPoint; degPerPx: number } | null>(null)
  const pinchStart = useRef<{ dist: number; fov: number } | null>(null)
  const movedRef = useRef(false)
  const dirtyRef = useRef(false)
  const downTargetRef = useRef<EventTarget | null>(null)
  const [dragging, setDragging] = useState(false)

  const projector = useMemo(() => panProjector(width, height, clampLook(look)), [width, height, look])

  const { markers } = useMemo(
    () =>
      buildMarkers(
        result,
        catalog,
        // Below-horizon parts are clipped by the sky-region clipPath below —
        // a horizon-straddling disc (giant planet at setting) must show its
        // above-horizon part, which a centre-altitude filter would botch.
        (alt, az) => projector.projectAltAz(alt, az),
        (d) => Math.min(140, Math.max(2.5, (d / projector.look.fovDeg) * (height / 2))),
      ),
    [result, catalog, projector, height],
  )

  const gridLayers = useMemo(
    () => buildGridLayers(result, (v) => projector.projectDir(v), grids),
    [result, projector, grids],
  )

  const labelled = useMemo(
    () => labeledIds(markers, selectedId, hoveredId),
    [markers, selectedId, hoveredId],
  )

  const cardinals = useMemo(
    () =>
      CARDINALS.map((dir) => ({
        dir,
        major: dir.length === 1,
        point: projector.projectAltAz(0, CARDINAL_AZ[dir]),
        text: t(`chart.cardinal.${dir}`),
      })),
    [projector, t],
  )

  const zenithPoint = useMemo(() => projector.projectDir(enuFromAltAz(90, 0)), [projector])

  const ticks = useMemo(
    () =>
      Array.from({ length: 24 }, (_, i) => i * 15)
        .map((az) => ({
          az,
          from: projector.projectAltAz(0, az),
          to: projector.projectAltAz(2.5, az),
        }))
        .filter((tick) => tick.from !== null && tick.to !== null),
    [projector],
  )

  const labelPlacements = useMemo(() => {
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
    const obstacles: Box[] = []
    for (const card of cardinals) {
      if (!card.major || !card.point) continue
      const half = estimateTextWidth(card.text, 15) / 2 + 2
      obstacles.push({
        left: card.point.x - half,
        right: card.point.x + half,
        top: card.point.y - 10,
        bottom: card.point.y + 10,
      })
    }
    if (zenithPoint) {
      const w = estimateTextWidth(t('chart.zenith'), 10)
      obstacles.push({
        left: zenithPoint.x + 8,
        right: zenithPoint.x + 12 + w,
        top: zenithPoint.y - 10,
        bottom: zenithPoint.y + 2,
      })
    }
    return layoutLabels(items, obstacles)
  }, [markers, labelled, selectedId, hoveredId, cardinals, zenithPoint, t])

  // Wheel zoom needs a non-passive native listener (React's wheel is passive).
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const factor = Math.exp(event.deltaY * 0.0012)
      onLookChange(clampLook({ ...look, fovDeg: look.fovDeg * factor }))
      dirtyRef.current = true
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [look, onLookChange])

  const pointerPos = (event: React.PointerEvent<SVGSVGElement>): ScreenPoint => ({
    x: event.clientX,
    y: event.clientY,
  })

  const handlePointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    // Capture the real hit target before the capture retargets later events.
    downTargetRef.current = event.target
    pointers.current.set(event.pointerId, pointerPos(event))
    if (pointers.current.size === 1) {
      const rect = event.currentTarget.getBoundingClientRect()
      dragStart.current = {
        look,
        px: pointerPos(event),
        degPerPx: look.fovDeg / Math.max(rect.height, 1),
      }
      movedRef.current = false
      setDragging(true)
    } else if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      pinchStart.current = { dist: Math.hypot(a.x - b.x, a.y - b.y), fov: look.fovDeg }
      dragStart.current = null
    }
  }

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!pointers.current.has(event.pointerId)) return
    pointers.current.set(event.pointerId, pointerPos(event))
    if (pointers.current.size === 2 && pinchStart.current) {
      const [a, b] = [...pointers.current.values()]
      const dist = Math.hypot(a.x - b.x, a.y - b.y)
      onLookChange(
        clampLook({ ...look, fovDeg: fovFromPinch(pinchStart.current.fov, pinchStart.current.dist, dist) }),
      )
      movedRef.current = true
      dirtyRef.current = true
    } else if (pointers.current.size === 1 && dragStart.current) {
      const px = pointerPos(event)
      const start = dragStart.current
      if (!movedRef.current && Math.hypot(px.x - start.px.x, px.y - start.px.y) < DRAG_THRESHOLD_PX) return
      movedRef.current = true
      dirtyRef.current = true
      onLookChange(lookFromDrag(start.look, start.px, px, start.degPerPx))
    }
  }

  const handlePointerEnd = (event: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId)
    if (pointers.current.size < 2) pinchStart.current = null
    if (pointers.current.size === 0) {
      setDragging(false)
      if (!movedRef.current) {
        // Pointer capture retargets the click to the SVG, so resolve the
        // press target ourselves: a body marker selects it, empty sky clears.
        const hit = (downTargetRef.current as Element | null)?.closest?.('[data-body-id]')
        const bodyId = hit?.getAttribute('data-body-id')
        if (bodyId) onSelect(bodyId)
        else onBackgroundSelect?.()
      } else if (dirtyRef.current) {
        dirtyRef.current = false
        onLookCommit()
      }
      dragStart.current = null
    }
  }

  const ground = useMemo(() => groundPath(projector), [projector])
  const horizon = useMemo(() => horizonPath(projector), [projector])

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      className={`w-full h-full select-none ${dragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      style={{ touchAction: 'none' }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
    >
      <defs>
        {/* Sky region = viewport minus the ground.  clipPath children UNION,
            so the subtraction must live in ONE compound path: rect outline +
            ground outline with evenodd (inside both ⇒ winding 2 ⇒ clipped). */}
        <clipPath id="sky-region">
          <path
            d={`M 0 0 L ${width} 0 L ${width} ${height} L 0 ${height} Z ${ground}`}
            clipRule="evenodd"
          />
        </clipPath>
      </defs>
      {/* Sky + grids (ground covers the below-horizon parts) */}
      <rect x={0} y={0} width={width} height={height} fill="#030308" />
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

      {/* Ground + horizon */}
      {ground && <path d={ground} fill={GROUND_FILL} stroke="none" pointerEvents="none" />}
      {ground && (
        <path d={ground} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={8} pointerEvents="none" />
      )}
      {horizon && (
        <path d={horizon} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth={1.5} pointerEvents="none" />
      )}

      {/* Azimuth ticks + cardinal labels on the horizon */}
      {ticks.map((tick) => (
        <line
          key={tick.az}
          x1={tick.from!.x}
          y1={tick.from!.y}
          x2={tick.to!.x}
          y2={tick.to!.y}
          stroke="rgba(255,255,255,0.22)"
          strokeWidth={1}
          pointerEvents="none"
        />
      ))}
      {cardinals.map(
        ({ dir, major, point, text }) =>
          point && (
            <text
              key={dir}
              x={point.x}
              y={point.y + (major ? 16 : 10)}
              textAnchor="middle"
              fontSize={major ? 15 : 10}
              fontWeight={major ? 600 : 400}
              fill={dir === 'N' ? NORTH_ACCENT : major ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.4)'}
              {...TEXT_HALO}
              pointerEvents="none"
            >
              {text}
            </text>
          ),
      )}

      {/* Zenith mark when in view */}
      {zenithPoint && (
        <g pointerEvents="none">
          <line x1={zenithPoint.x - 5} y1={zenithPoint.y} x2={zenithPoint.x + 5} y2={zenithPoint.y} stroke="rgba(255,255,255,0.25)" />
          <line x1={zenithPoint.x} y1={zenithPoint.y - 5} x2={zenithPoint.x} y2={zenithPoint.y + 5} stroke="rgba(255,255,255,0.25)" />
          <text x={zenithPoint.x + 9} y={zenithPoint.y + 4} fontSize={10} fill="rgba(255,255,255,0.35)" {...TEXT_HALO}>
            {t('chart.zenith')}
          </text>
        </g>
      )}

      {/* Body markers + labels, clipped to the sky region */}
      <g clipPath="url(#sky-region)">
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
                    pointerEvents="none"
                  >
                    {m.row.name ?? m.row.body_id}
                  </text>
                )
              })()}
          </g>
        )
      })}
      </g>
    </svg>
  )
}
