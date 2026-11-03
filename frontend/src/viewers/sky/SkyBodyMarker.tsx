/** SkyBodyMarker — one body's marker (dark base disc + phase path + stroke
 *  ring + generous hit target).  Shared by the pan view and the all-sky disc;
 *  labels stay with each chart (their placement policy differs).
 */

import { HOVER_STROKE, LIT_FILL, SELECTED_STROKE } from './bodyColor'
import { phasePathD } from './phaseGeometry'

export interface SkyBodyMarkerProps {
  x: number
  y: number
  radius: number
  fill: string
  brightAngle: number
  isStar: boolean
  illuminatedFraction: number | null
  /** Irradiation halo width in px (0 = none); the chart supplies the gradient. */
  glare: number
  selected: boolean
  hovered: boolean
  dimmed: boolean
  onHover: (bodyId: string | null) => void
  onSelect: (bodyId: string) => void
  bodyId: string
  /** Suppress click right after a drag (set by the chart's pointer logic). */
  clickSuppressed?: () => boolean
}

export default function SkyBodyMarker({
  x,
  y,
  radius,
  fill,
  brightAngle,
  isStar,
  illuminatedFraction,
  glare,
  selected,
  hovered,
  dimmed,
  onHover,
  onSelect,
  bodyId,
  clickSuppressed,
}: SkyBodyMarkerProps) {
  const k = illuminatedFraction
  return (
    <g
      opacity={dimmed ? 0.35 : 1}
      data-body-id={bodyId}
      onMouseEnter={() => onHover(bodyId)}
      onMouseLeave={() => onHover(null)}
      onClick={() => {
        if (clickSuppressed?.()) return
        onSelect(bodyId)
      }}
      className="cursor-pointer"
    >
      {glare > 0 && (
        <circle cx={x} cy={y} r={radius + glare} fill="url(#body-glare)" opacity={0.5} />
      )}
      <circle cx={x} cy={y} r={radius} fill="#1a1a3a" stroke="none" />
      {k !== null && (
        <path
          d={phasePathD(x, y, radius, k, brightAngle)}
          fill={isStar ? fill : LIT_FILL}
        />
      )}
      <circle
        cx={x}
        cy={y}
        r={radius}
        fill="none"
        stroke={selected ? SELECTED_STROKE : hovered ? HOVER_STROKE : 'rgba(255,255,255,0.25)'}
        strokeWidth={selected || hovered ? 1.8 : 1}
      />
      <circle cx={x} cy={y} r={Math.max(12, radius)} fill="transparent" />
    </g>
  )
}
