/**
 * SunControl — directional lighting controls for the 3D globe.
 *
 * Controls:
 *   - Sun longitude (0-360°): simulates the sun's position in the orbital plane,
 *     effectively rotating the directional light around the planet.
 *   - The planet's axial tilt is read from the geological data and applied
 *     to the light direction automatically.
 */

import { useCallback } from 'react'

interface SunControlProps {
  sunLongitudeDeg: number
  onChange: (deg: number) => void
  /** Axial tilt in degrees (display-only in this component). */
  axialTiltDeg?: number
}

/** Simple sun icon as inline SVG. */
function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  )
}

export default function SunControl({ sunLongitudeDeg, onChange, axialTiltDeg }: SunControlProps) {
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(parseInt(e.target.value))
    },
    [onChange],
  )

  const tiltLabel =
    axialTiltDeg != null ? ` · 倾角 ${axialTiltDeg}°` : ''

  return (
    <div className="space-y-1.5">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <span className="text-amber-400/80">
          <SunIcon />
        </span>
        <span className="text-xs text-gray-400">光照</span>
        <span className="text-[10px] font-mono tabular-nums ml-auto text-amber-300/80">
          {sunLongitudeDeg}°{tiltLabel}
        </span>
      </div>

      {/* Slider */}
      <input
        type="range"
        min="0"
        max="360"
        value={sunLongitudeDeg}
        onChange={handleChange}
        className="w-full h-1 accent-amber-400 cursor-pointer"
        title={`太阳直射经度（0° = 本初子午线正午）`}
      />

      {/* Tick labels */}
      <div className="flex justify-between text-[9px] text-gray-600 font-mono">
        <span>0°</span>
        <span>90°</span>
        <span>180°</span>
        <span>270°</span>
        <span>360°</span>
      </div>
    </div>
  )
}
