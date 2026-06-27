/**
 * Label — screen-space annotation with leader line for celestial bodies.
 *
 * Inspired by Space Engine / Celestia / Universe Sandbox:
 * - A colored dot marks the body's projected screen position.
 * - A thin leader line extends upward to a text label.
 * - The label stays visible even when the body is sub-pixel at system scale.
 * - When zoomed in close enough that the body geometry is visible, the
 *   leader line shrinks and the label sits near the body surface.
 *
 * Rendered via @react-three/drei <Html> which projects a 3D world-space
 * anchor to a screen-space HTML element.
 */

import { Html } from '@react-three/drei'

interface LabelProps {
  /** Display name */
  name: string
  /** Dot/line color (CSS) */
  color: string
  /** Glow shadow color for the dot (CSS, defaults to color) */
  glowColor?: string
  /** Additional info line shown below the name (e.g. "G2V · 5772 K") */
  subtitle?: string
  /** Whether this body is currently selected */
  selected?: boolean
  /** Whether the label should be visible (false = hidden for decluttering) */
  visible?: boolean
  /** Click handler */
  onClick?: () => void
  /** Double-click handler — triggers camera focus */
  onDoubleClick?: () => void
  /** Pointer hover handler */
  onHover?: (hovering: boolean) => void
}

export default function Label({
  name,
  color,
  glowColor,
  subtitle,
  selected,
  visible = true,
  onClick,
  onDoubleClick,
  onHover,
}: LabelProps) {
  const glow = glowColor ?? color
  const lineH = selected ? 32 : 48

  if (!visible) return null

  return (
    <Html
      center
      zIndexRange={[100, 0]}
      style={{ pointerEvents: 'none', overflow: 'visible' }}
    >
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          transform: 'translateY(-8px)',
          userSelect: 'none',
        }}
      >
        {/* Text label */}
        <div
          onClick={(e) => {
            e.stopPropagation()
            onClick?.()
          }}
          onDoubleClick={(e) => {
            e.stopPropagation()
            onDoubleClick?.()
          }}
          onPointerEnter={() => onHover?.(true)}
          onPointerLeave={() => onHover?.(false)}
          style={{
            pointerEvents: 'auto',
            cursor: onClick ? 'pointer' : 'default',
            textAlign: 'center',
            marginBottom: 2,
          }}
        >
          <div
            style={{
              color: '#fff',
              fontSize: 11,
              fontWeight: 600,
              fontFamily: 'Inter, system-ui, sans-serif',
              textShadow: `0 0 4px ${glow}, 0 0 8px rgba(0,0,0,0.9)`,
              whiteSpace: 'nowrap',
              letterSpacing: '0.03em',
            }}
          >
            {name}
          </div>
          {subtitle && (
            <div
              style={{
                color: 'rgba(255,255,255,0.45)',
                fontSize: 9,
                fontFamily: 'Inter, system-ui, sans-serif',
                textShadow: '0 0 4px rgba(0,0,0,0.9)',
                whiteSpace: 'nowrap',
                marginTop: 1,
              }}
            >
              {subtitle}
            </div>
          )}
        </div>

        {/* Leader line */}
        <div
          style={{
            width: 1,
            height: lineH,
            background: `linear-gradient(to bottom, ${color}55, ${color}08)`,
          }}
        />

        {/* Dot at body position */}
        <div
          onClick={(e) => {
            e.stopPropagation()
            onClick?.()
          }}
          onDoubleClick={(e) => {
            e.stopPropagation()
            onDoubleClick?.()
          }}
          onPointerEnter={(e) => {
            e.stopPropagation()
            onHover?.(true)
          }}
          onPointerLeave={() => onHover?.(false)}
          style={{
            pointerEvents: 'auto',
            cursor: onClick ? 'pointer' : 'default',
            width: selected ? 8 : 6,
            height: selected ? 8 : 6,
            borderRadius: '50%',
            background: color,
            boxShadow: `0 0 6px ${glow}, 0 0 14px ${glow}66`,
            border: selected ? '1px solid rgba(255,255,255,0.5)' : 'none',
          }}
        />
      </div>
    </Html>
  )
}
